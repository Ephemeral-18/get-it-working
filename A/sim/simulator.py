"""机器人仿真核心：状态机、指令执行、碰撞判定、巡检轮次判定、自动巡检。

阶段一形态：不跑独立 tick 循环，状态在收到指令时按需推进，
tick 记录已处理的指令条数。传感器为确定性射线测距（噪声注入属后续阶段）。

异常检测（深度学习方向 inference 模块）：Simulator 不自己实现推理，
由组装方（api 层）通过构造参数注入 detector；每处理一条指令后采样一次
传感器窗口并调用 detector.update()。未注入 detector 时
anomaly_prob 恒为 0.0、anomaly_label 恒为 normal，行为与本模块单独
开发联调时一致。

移动规则（B1/B2 基线）：
- MOVE 的 forward / back 沿当前朝向平移一格，left / right 原地转向 90 度；
- 目标格越界或为障碍时拒绝移动：位置不变，状态置 COLLISION；
- PAUSED 状态下拒绝一切 MOVE；碰撞后允许再次移动以恢复；
- 自动巡检进行中拒绝手动 MOVE，避免抢占自动路径。

巡检轮次：
- 固定起点 = 机器人初始位置（WorldMap.robot_start），由后端管理；
- 成功离开起点后，再经一次有效移动回到起点即完成一轮，
  生成一条含轮次与完成时间的记录（内存保存）；
- 停留在起点、原地转向、读取状态均不产生记录；
- 无效移动（碰撞/越界）不改变位置，不影响巡检进度；
- RESET 回到起点会中止未完成的尝试，但轮次计数与历史记录保留。

巡检点与自动巡检：
- 地图固定 9 个巡检点（WorldMap.patrol_points），手动/自动移动落到
  巡检点即打卡（patrol.points_visited 递增）；
- PLAN：贪心最近邻 + BFS 规划依次访问全部可达巡检点并返回起点，
  由服务端定时循环或 STEP 指令逐步驱动；
- HOME：规划从当前位置返回起点的路径并自动行走；
- STOP 暂停自动步进、START 恢复；RESET 清空自动路径与巡检点打卡进度。
"""

import datetime as _dt
from collections import deque

from .world import ROBOT_INITIAL_HEADING, WorldMap

# 状态机取值（与接口契约一致；ANOMALY / DONE 在后续阶段启用）
IDLE = "IDLE"
RUNNING = "RUNNING"
PAUSED = "PAUSED"
COLLISION = "COLLISION"

# 朝向 -> 单位位移 (dx, dy)
_HEADING_VECTORS = {
    0: (1, 0),
    90: (0, 1),
    180: (-1, 0),
    270: (0, -1),
}

# 射线测距上限（格）
_SENSOR_MAX = 10.0

# 展示用恒定速度（契约字段，阶段一不参与运算）
_ROBOT_SPEED = 0.4


class CommandResult:
    """单条指令的处理结果。"""

    def __init__(self, ok, msg):
        self.ok = ok
        self.msg = msg


class Simulator:
    """机器人仿真器：持有地图与机器人状态，处理指令并输出状态。"""

    def __init__(self, world=None, detector=None):
        """detector：异常检测推理对象（深度学习方向提供，可为 None）。

        只要求实现 update(frame) -> (prob, label) 与 reset()，
        frame 为 [front, left, right, back, touch] 一帧传感器读数。
        """
        self.world = world or WorldMap()
        self._detector = detector
        self._tick = 0
        self._log = "initialized"
        # 巡检进度：轮次与记录跨 RESET 保留，仅进程生命周期内有效
        self._patrol_rounds = 0
        self._records = []
        # 巡检点打卡与自动巡检路径（RESET 时清空）
        self._visited_points = set()
        self._auto_route = []  # 完整路径 (x, y) 列表，含终点
        self._auto_cursor = 0  # 下一步要走的路径下标
        self._auto_active = False
        self._auto_purpose = ""
        self._reset_robot()

    # ------------------------------------------------------------------
    # 指令入口
    # ------------------------------------------------------------------
    def handle_command(self, cmd, param=None):
        """处理一条指令（cmd: START/STOP/MOVE/RESET/PLAN）。"""
        cmd = (cmd or "").upper()
        handlers = {
            "START": self._cmd_start,
            "STOP": self._cmd_stop,
            "MOVE": self._cmd_move,
            "RESET": self._cmd_reset,
            "PLAN": self._cmd_plan,
            "HOME": self._cmd_home,
            "STEP": self._cmd_step,
        }
        handler = handlers.get(cmd)
        if handler is None:
            self._log = f"unknown cmd: {cmd}"
            return CommandResult(False, self._log)
        result = handler(param or {})
        self._tick += 1
        # 每处理一条指令采样一次传感器，刷新异常检测推理结果
        # （窗口第 5 位为碰撞事件标志：仅本次指令被碰撞拒绝时为 1）
        self._update_anomaly(collision=(not result.ok and self._state == COLLISION))
        return result

    # ------------------------------------------------------------------
    # 状态输出
    # ------------------------------------------------------------------
    def state_dict(self):
        return {
            "tick": self._tick,
            "robot": {
                "x": self._position[0],
                "y": self._position[1],
                "heading": self._heading,
                "speed": _ROBOT_SPEED,
            },
            "battery": 100.0,
            "sensors": self._sensors(),
            "path": [[x, y] for x, y in self._auto_route],
            "path_index": self._auto_cursor,
            "state": self._state,
            "log": self._log,
            "auto": self._auto_active,
            "patrol": {
                "rounds_completed": self._patrol_rounds,
                "left_start": self._left_start,
                "records": [dict(record) for record in self._records],
                "points_total": len(self.world.patrol_points),
                "points_visited": len(self._visited_points),
                "visited": [[x, y] for x, y in sorted(self._visited_points)],
            },
        }

    def map_dict(self):
        return self.world.to_dict()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _reset_robot(self):
        self._position = self.world.robot_start
        self._heading = ROBOT_INITIAL_HEADING
        self._state = IDLE
        # 回到起点中止未完成的巡检尝试；轮次计数与历史记录保留
        self._left_start = False
        # 清空自动巡检路径与巡检点打卡进度
        self._auto_route = []
        self._auto_cursor = 0
        self._auto_active = False
        self._auto_purpose = ""
        self._visited_points = set()
        # 异常检测回到初始判定
        self._anomaly_prob = 0.0
        self._anomaly_label = "normal"
        if self._detector is not None:
            self._detector.reset()

    def _update_anomaly(self, collision=False):
        """采样当前一帧传感器读数，交给推理模块刷新异常判定。

        只在指令处理与定时步进时调用；读取状态（GET /state 轮询）
        不产生副作用，保证 state_dict 可重复读取且结果一致。
        collision：本次指令是否发生碰撞（目标格越界/障碍被拒绝）。
        """
        if self._detector is None:
            return
        front = self._ray(self._heading)
        frame = [
            front,
            self._ray((self._heading + 270) % 360),
            self._ray((self._heading + 90) % 360),
            self._ray((self._heading + 180) % 360),
            1.0 if collision else 0.0,
        ]
        self._anomaly_prob, self._anomaly_label = self._detector.update(frame)

    def _cmd_start(self, _param):
        self._state = RUNNING
        self._log = "started"
        return CommandResult(True, self._log)

    def _cmd_stop(self, _param):
        self._state = PAUSED
        self._log = "paused"
        return CommandResult(True, self._log)

    def _cmd_reset(self, _param):
        self._reset_robot()
        self._log = "reset"
        return CommandResult(True, self._log)

    def _cmd_plan(self, _param):
        """PLAN：规划并开始自动巡检（依次访问全部巡检点后返回起点）。"""
        if self._auto_active:
            self._log = "plan rejected: auto patrol already running"
            return CommandResult(False, self._log)
        route = self._build_patrol_route()
        if not route:
            self._log = "plan failed: no reachable patrol points"
            return CommandResult(False, self._log)
        self._auto_route = route
        self._auto_cursor = 0
        self._auto_active = True
        self._auto_purpose = "auto patrol"
        self._state = RUNNING
        self._log = (f"auto patrol started: {len(route)} steps, "
                     f"{len(self.world.patrol_points)} checkpoints")
        return CommandResult(True, self._log)

    def _cmd_home(self, _param):
        """HOME：规划从当前位置返回起点的路径并自动行走。"""
        if self._auto_active:
            self._log = "home rejected: auto route already running"
            return CommandResult(False, self._log)
        if self._position == self.world.robot_start:
            self._log = "already at start"
            return CommandResult(True, self._log)
        path = self._bfs_path(self._position, self.world.robot_start)
        if path is None:
            self._log = "home failed: no path to start"
            return CommandResult(False, self._log)
        self._auto_route = path
        self._auto_cursor = 0
        self._auto_active = True
        self._auto_purpose = "return to start"
        self._state = RUNNING
        self._log = f"returning to start: {len(path)} steps"
        return CommandResult(True, self._log)

    def _cmd_step(self, _param):
        """STEP：自动巡检推进一步（服务端定时器与测试用它驱动）。"""
        return self._auto_step()

    def auto_step(self):
        """供 api 层定时循环调用：自动巡检激活时推进一步。"""
        result = self._auto_step()
        self._update_anomaly(collision=(not result.ok and self._state == COLLISION))
        return result

    def _auto_step(self):
        if not self._auto_active:
            self._log = "auto step rejected: no active route"
            return CommandResult(False, self._log)
        if self._state == PAUSED:
            self._log = "auto step skipped: paused"
            return CommandResult(False, self._log)
        if self._auto_cursor >= len(self._auto_route):
            self._finish_auto()
            return CommandResult(True, self._log)
        target = self._auto_route[self._auto_cursor]
        if not self.world.is_traversable(target):
            # 规划后地图不应变化，此分支为防御：中止自动巡检
            self._auto_active = False
            self._state = COLLISION
            self._log = f"auto patrol aborted: ({target[0]},{target[1]}) blocked"
            return CommandResult(False, self._log)
        self._auto_cursor += 1
        self._position = target
        self._state = RUNNING
        self._log = self._apply_patrol(target)
        if self._auto_cursor >= len(self._auto_route):
            self._finish_auto()
        return CommandResult(True, self._log)

    def _finish_auto(self):
        self._auto_active = False
        self._state = IDLE
        self._log = f"{self._auto_purpose} complete; {self._log}"

    def _bfs_path(self, src, dst):
        """BFS 最短路：返回 src（不含）到 dst（含）的格序列，不可达返回 None。"""
        if src == dst:
            return []
        queue = deque([src])
        parent = {src: None}
        while queue:
            current = queue.popleft()
            for dx, dy in _HEADING_VECTORS.values():
                nxt = (current[0] + dx, current[1] + dy)
                if nxt in parent or not self.world.is_traversable(nxt):
                    continue
                parent[nxt] = current
                if nxt == dst:
                    path = [nxt]
                    while parent[path[-1]] is not None:
                        path.append(parent[path[-1]])
                    path.reverse()
                    return path
                queue.append(nxt)
        return None

    def _build_patrol_route(self):
        """贪心最近邻 + BFS：依次访问全部可达巡检点，最后回到起点。"""
        current = self._position
        remaining = [p for p in self.world.patrol_points
                     if self.world.is_traversable(p)]
        route = []
        while remaining:
            best_path = None
            best_target = None
            for candidate in remaining:
                path = self._bfs_path(current, candidate)
                if path is not None and (best_path is None or len(path) < len(best_path)):
                    best_path = path
                    best_target = candidate
            if best_path is None:
                break  # 剩余巡检点均不可达，放弃
            route.extend(best_path)
            current = best_target
            remaining.remove(best_target)
        if current != self.world.robot_start:
            tail = self._bfs_path(current, self.world.robot_start)
            if tail:
                route.extend(tail)
        return route

    def _cmd_move(self, param):
        if self._state == PAUSED:
            self._log = "move rejected: paused"
            return CommandResult(False, self._log)

        if self._auto_active:
            self._log = "move rejected: auto patrol in progress"
            return CommandResult(False, self._log)

        direction = str(param.get("dir", "")).lower()

        if direction in ("left", "right"):
            delta = -90 if direction == "left" else 90
            self._heading = (self._heading + delta) % 360
            self._state = RUNNING
            self._log = f"turn {direction}, heading {self._heading}"
            return CommandResult(True, self._log)

        if direction in ("forward", "back"):
            dx, dy = _HEADING_VECTORS[self._heading]
            if direction == "back":
                dx, dy = -dx, -dy
            target = (self._position[0] + dx, self._position[1] + dy)
            if not self.world.is_traversable(target):
                self._state = COLLISION
                reason = "out of bounds" if not self.world.in_bounds(target) else "obstacle ahead"
                self._log = f"move {direction} to {target} rejected: {reason}"
                return CommandResult(False, self._log)
            self._position = target
            self._state = RUNNING
            self._log = self._apply_patrol(target)
            return CommandResult(True, self._log)

        self._log = f"unknown dir: {direction}"
        return CommandResult(False, self._log)

    def _apply_patrol(self, position):
        """按一次有效平移的结果更新巡检进度，返回本步日志文案。

        仅位置发生变化的平移参与判定：落到巡检点 → 打卡；
        回到起点且此前已离开 → 完成一轮；离开起点 → 标记尝试进行中；
        原地转向不进入本逻辑。
        """
        msg = f"step to ({position[0]},{position[1]})"
        if position in self.world.patrol_points and position not in self._visited_points:
            self._visited_points.add(position)
            msg += (f"; checkpoint {len(self._visited_points)}/"
                    f"{len(self.world.patrol_points)}")
        if position == self.world.robot_start:
            if self._left_start:
                self._patrol_rounds += 1
                self._records.append({
                    "round": self._patrol_rounds,
                    "completed_at": _dt.datetime.now().astimezone().isoformat(
                        timespec="milliseconds"
                    ),
                })
                self._left_start = False
                msg += f"; round {self._patrol_rounds} completed"
            return msg
        # 成功离开起点，标记本轮尝试进行中
        self._left_start = True
        return msg

    def _sensors(self):
        front = self._ray(self._heading)
        return {
            "front": front,
            "left": self._ray((self._heading + 270) % 360),
            "right": self._ray((self._heading + 90) % 360),
            "back": self._ray((self._heading + 180) % 360),
            "touch": front <= 1.0,
            "anomaly_prob": self._anomaly_prob,
            "anomaly_label": self._anomaly_label,
        }

    def _ray(self, heading):
        """沿 heading 方向射线测距：到最近障碍/边界的格数，上限 _SENSOR_MAX。"""
        dx, dy = _HEADING_VECTORS[heading]
        x, y = self._position
        distance = 0
        while distance < _SENSOR_MAX:
            x += dx
            y += dy
            distance += 1
            if not self.world.is_traversable((x, y)):
                return float(distance)
        return float(_SENSOR_MAX)
