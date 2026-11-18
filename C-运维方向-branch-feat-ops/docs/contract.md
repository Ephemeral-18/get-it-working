# 接口契约（阶段一）

> 契约冻结后修改需全员同意。本文件记录当前已实现的字段；`ANOMALY`/`DONE` 状态
> 与独立推理服务在后续阶段启用。
> 2026-11-09 增补：巡检点（`/map` 的 `patrol_points`）、自动巡检（`PLAN`）、
> 回到起点（`HOME`）、单步驱动（`STEP`）与状态字段 `auto`，见第 7 节。
> 2026-11-10 增补：异常检测推理模块（`inference/`，深度学习方向）接入，
> `anomaly_prob` / `anomaly_label` 由推理结果填充，见第 3 节。

## 1. 状态（GET /state）

```json
{
  "tick": 128,
  "robot": { "x": 5, "y": 3, "heading": 0, "speed": 0.4 },
  "battery": 100.0,
  "sensors": {
    "front": 1.2, "left": 0.8, "right": 1.5, "back": 2.0,
    "touch": false,
    "anomaly_prob": 0.0,
    "anomaly_label": "normal"
  },
  "path": [],
  "path_index": 0,
  "state": "RUNNING",
  "log": "step to (6,3)",
  "auto": false,
  "patrol": {
    "rounds_completed": 2,
    "left_start": false,
    "points_total": 9,
    "points_visited": 5,
    "visited": [[3, 1], [8, 2], [12, 2], [17, 3], [15, 7]],
    "records": [
      { "round": 1, "completed_at": "2026-11-04T15:30:45.123+08:00" },
      { "round": 2, "completed_at": "2026-11-04T15:33:12.456+08:00" }
    ]
  }
}
```

- `state` 取值：`IDLE / RUNNING / PAUSED / COLLISION`（`ANOMALY / DONE` 后续启用）。
- 阶段一形态：无独立 tick 循环，`tick` 记录已处理指令条数；传感器为确定性
  射线测距（单位：格，上限 10），噪声注入属后续阶段。
- `anomaly_prob` / `anomaly_label`：由深度学习方向的推理模块计算（见第 3 节），
  sim 每处理一条指令采样一次；未注入推理模块时恒为 `0.0` / `normal`。
- `patrol`：巡检轮次与巡检点进度，由 sim 维护（详见第 6、7 节判定规则）。
- `auto`：自动巡检是否进行中（`PLAN`/`HOME` 生效期间为 `true`）；`path` 为
  完整规划路径，`path_index` 为已走步数（两者仅在自动巡检期间有意义）。

## 2. 指令（POST /cmd）

请求：

```json
{ "cmd": "MOVE", "param": { "dir": "forward" }, "from": "user", "seq": 7 }
```

响应：

```json
{ "ok": true, "msg": "step to (6,3)", "state": { "...": "同上状态结构" } }
```

- `cmd` 取值：`START / STOP / MOVE / RESET / PLAN / HOME / STEP`。
- `MOVE` 的 `dir`：`forward / back` 沿朝向平移一格；`left / right` 原地转向 90°。
- 目标格越界或为障碍 → 拒绝移动：`ok=false`、位置不变、`state=COLLISION`。
- `PAUSED` 状态拒绝一切 `MOVE`；`RESET` 回到初始位置并置 `IDLE`
  （同时清空推理窗口，`anomaly` 恢复 `normal`）。
- `PLAN` 触发自动巡检（已实现，见第 7 节）；`HOME` 回到起点；`STEP` 推进一步。
- `from` / `seq` 字段保留，暂不参与处理。

## 3. 推理请求与响应（inference 模块，深度学习方向）

进程内调用形态（当前实现）：sim 每处理一条指令，把最近一帧
`[front, left, right, back, touch]` 交给 `inference.detector.AnomalyDetector`，
窗口取最近 10 帧（`WINDOW_SIZE = 10`），返回
`(anomaly_prob, anomaly_label)` 填入 `/state` 的 `sensors`。
窗口第 5 位为碰撞事件标志（`1.0` = 本次指令被碰撞拒绝），
因此连续 2 次撞墙/越界即判定异常，贴墙行驶不误报。

```json
{
  "request_id": "r-0012",
  "window": [[1.2, 0.8, 1.5, 2.0, 0.42]],
  "result": { "label": "anomaly", "prob": 0.91, "model_ver": "v0.1" }
}
```

升级为独立 inference 服务（后续阶段）时沿用上图的 HTTP 契约：
`window` 为最近 10 帧读数，B 方向模型对窗口分类输出是否异常；
A（sim）只管塞数、B（inference）只管分类、C（api）只管转发，
三方解耦不变。模块设计与升级路径见 `docs/model.md`。

## 4. 地图（GET /map）

```json
{ "width": 20, "height": 15, "start": [1, 1], "patrol_points": [[3, 1], [8, 2], [12, 2], [17, 3], [15, 7], [18, 8], [12, 12], [5, 12], [2, 7]], "obstacles": [[6, 2], [6, 3]] }
```

- `start`：固定起点（机器人初始位置），前端据此在地图上标记起点。
- `patrol_points`：9 个固定巡检点，前端编号展示、到达打卡（见第 7 节）。

## 5. 其他接口

- `GET /health` → `{"ok": true}`
- 静态页面由 api 服务挂载在 `/`，`/docs` 为自动生成的接口文档。

## 6. 巡检轮次判定规则

- 固定起点 = 机器人初始位置（`/map` 的 `start`），由后端管理。
- 完成一轮：机器人经**有效移动**离开起点后，再经一次**有效移动**回到起点。
  每轮只生成一条记录（`round` 轮次 + `completed_at` 完成时间），轮次递增。
- 以下情形**不产生记录**：初始化、停留在起点、原地转向、读取状态（含页面
  500ms 轮询与刷新重拉）。
- 无效移动（目标格越界或为障碍）：位置不变、置 `COLLISION`，不影响巡检进度
  （未完成也不丢失已离开状态）。
- `RESET`：回到起点并置 `IDLE`，中止未完成的尝试（`left_start` 复位）；
  已完成轮次与历史记录保留，下一轮轮次继续递增。
- 记录保存在内存中，服务重启即清空（后续阶段再接入持久化）。

## 7. 巡检点与自动巡检规则

- 地图固定 9 个巡检点（`/map` 的 `patrol_points`），前端编号 1–9 展示。
- 打卡：手动或自动移动**落到**巡检点即计入 `patrol.points_visited`，重复经过
  不重复计数；原地转向、读取状态不打卡。
- `PLAN`：贪心最近邻 + BFS 依次规划访问全部可达巡检点，最后一段自动返回起点
  （因此自动巡检完成即完成一轮巡检）；无可达巡检点时返回 `ok=false`。
- 自动巡检期间拒绝手动 `MOVE`；`STOP` 暂停自动步进（`PAUSED`），`START` 恢复；
  `RESET` 清空自动路径与巡检点打卡进度（轮次与历史记录保留）。
- `HOME`：从当前位置规划返回起点的路径并自动行走；已在起点时直接成功。
- 步进驱动：服务端每 `SIM_AUTO_INTERVAL` 秒（默认 0.6s）自动推进一步，
  也可用 `STEP` 指令手动推进一步（测试用）；`SIM_AUTO_LOOP=0` 可关闭定时器。
- 前端以蓝色虚线展示剩余规划路径，巡检点打卡后由橙色变绿并打勾。

## 8. 异常检测展示（2026-11-10 增补）

- 前端「机器人状态」卡片展示异常检测徽标：正常为绿色，
  `anomaly_label = anomaly` 时变红并显示概率。
- 演示方法：手动控制机器人向边界/障碍连续移动被拒 2 次
  （两次碰撞事件入窗口），徽标变红；`RESET` 后恢复绿色。
- 推理模块的判定规则与升级路径由 `docs/model.md` 说明，属深度学习方向维护。
