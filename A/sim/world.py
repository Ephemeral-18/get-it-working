"""2D 网格世界定义：尺寸、障碍与机器人初始位置。

坐标采用 (x, y)，原点在左上角，x 向右增长、y 向下增长，
与前端 Canvas 坐标系一致。
"""

WIDTH = 20
HEIGHT = 15

# 机器人初始位置（网格坐标），RESET 时回到这里
ROBOT_INITIAL_POSITION = (1, 1)

# 初始朝向（角度制：0 = +x 向右，90 = +y 向下，180 = -x 向左，270 = -y 向上）
ROBOT_INITIAL_HEADING = 0

# 障碍物格坐标
_OBSTACLE_WALLS = [
    # 竖墙：x=6, y=2..6
    *[(6, y) for y in range(2, 7)],
    # 横墙：y=9, x=10..16
    *[(x, 9) for x in range(10, 17)],
    # 方块障碍
    (13, 4),
    (14, 4),
    (13, 5),
    (14, 5),
]

OBSTACLES = frozenset(_OBSTACLE_WALLS)

# 巡检点（网格坐标）：地图上固定 9 个巡检目标格，自动巡检依次访问
PATROL_POINTS = [
    (3, 1),
    (8, 2),
    (12, 2),
    (17, 3),
    (15, 7),
    (18, 8),
    (12, 12),
    (5, 12),
    (2, 7),
]


class WorldMap:
    """网格地图：边界与障碍判定。"""

    def __init__(self, width=WIDTH, height=HEIGHT, obstacles=OBSTACLES,
                 robot_start=ROBOT_INITIAL_POSITION,
                 patrol_points=PATROL_POINTS):
        self.width = width
        self.height = height
        self.obstacles = frozenset(obstacles)
        self.robot_start = robot_start
        # 巡检点保持定义顺序（用于页面编号展示）
        self.patrol_points = tuple(patrol_points)

    def in_bounds(self, cell):
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def is_obstacle(self, cell):
        return cell in self.obstacles

    def is_traversable(self, cell):
        """可通行：在边界内且不是障碍。"""
        return self.in_bounds(cell) and not self.is_obstacle(cell)

    def to_dict(self):
        return {
            "width": self.width,
            "height": self.height,
            "start": [self.robot_start[0], self.robot_start[1]],
            "patrol_points": [[x, y] for x, y in self.patrol_points],
            "obstacles": [[x, y] for x, y in sorted(self.obstacles)],
        }
