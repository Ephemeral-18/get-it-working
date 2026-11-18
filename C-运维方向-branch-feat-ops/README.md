# Web 智能巡检机器人仿真系统

纯软件 2D 网格智能巡检机器人仿真系统：Web 可视化控制、FastAPI 后端、异常检测推理、容器化部署（容器化为后续阶段）。

## 功能清单

- 基础版 B1：Canvas 渲染 20×15 网格 + 障碍 + 机器人，四方向手动控制加启停重置
- 基础版 B2：`GET /health`、`GET /state`、`GET /map`、`POST /cmd` 四个 RESTful 接口
- 碰撞判定：目标格为障碍或越界时拒绝移动，位置不变并置 `COLLISION`
- 巡检点与自动巡检：地图 9 个固定巡检点（到达即打卡），`PLAN` 自动巡检
  （贪心最近邻 + BFS 规划依次访问并返回起点，服务端定时步进）、
  `HOME` 回到起点、`STOP`/`START` 暂停恢复，页面展示巡检点进度与规划路径
- 巡检轮次：固定起点（机器人初始位置）在地图上标记；离开起点后再次有效移动返回即完成一轮，
  生成含轮次与完成时间的记录（内存保存），页面展示记录列表
- 虚拟感知异常检测：`inference/` 推理模块吃最近 10 帧传感器窗口，
  输出 `anomaly_prob` / `anomaly_label`；连续 2 次碰撞判定异常，
  页面徽标变红、机器人变色（当前为规则基线，升级训练模型的路径见 `docs/model.md`）

## 快速开始

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>（接口文档在 `/docs`）。
Windows 下双击 `启动.bat` 自动装依赖并打开页面；`局域网共享.bat` 供同网段同学访问。

## 架构

```
web（Canvas 渲染 + 按钮）  →  api（FastAPI REST，组装点）  →  sim（网格世界 + 状态机 + 传感器）
                                                              │
                                              inference（异常检测推理，深度学习方向）
```

## 各模块说明

### sim 仿真与控制（负责人 A，嵌入式方向）

- `sim/world.py`：20×15 网格世界、障碍、固定起点与 9 个巡检点定义
- `sim/simulator.py`：机器人状态机（IDLE/RUNNING/PAUSED/COLLISION）、碰撞判定、
  巡检轮次判定、巡检点打卡、贪心最近邻 + BFS 自动巡检规划、四方向射线测距虚拟传感器
- 异常检测不在 sim 内实现：Simulator 接受注入的 detector（接口见模块 docstring），
  sim 与 inference 互不 import，只通过「一帧 5 个数」的窗口对接
- 自测：`python -m pytest tests/test_patrol.py tests/test_auto_patrol.py`

### inference 异常检测（负责人 B，深度学习方向）

- `inference/detector.py`：滑动窗口（10 帧）异常检测，输出 `(prob, label)`，
  当前为规则基线 rule-v0.1，升级训练模型的采数/训练/评测路径见 `docs/model.md`
- 自测：`python -m pytest tests/test_inference.py`

### api 与 web 与部署（负责人 C，运维方向）

- `api/main.py`：四个 REST 接口、静态页面托管、自动巡检定时循环；
  同时是组装点——把 `AnomalyDetector` 注入 `Simulator`
- `web/`：原生 HTML/CSS/JS，500ms 轮询 `/state`，展示地图、巡检进度与异常徽标
- `tests/test_api.py`：接口契约与三人方向端到端联调用例
- 工程配套：`requirements.txt`、`conftest.py`、`docs/contract.md`、
  `.github/workflows/ci.yml`、启动脚本

接口契约见 `docs/contract.md`，冻结后修改需全员同意；
目录归属见 `docs/model.md` 与下表，谁都不改别人目录，Git 冲突自然为零。

## 分工与仓库结构

| 目录 | 方向 | 分支 |
| --- | --- | --- |
| `sim/` | A 嵌入式 | `feat-sim` |
| `inference/`、`docs/model.md` | B 深度学习 | `feat-inference` |
| `api/`、`web/`、`tests/test_api.py`、工程配套 | C 运维 | `feat-ops` |

三人分支合并顺序：`feat-sim` → `feat-inference` → `feat-ops`（C 最后合并并做整仓验收）。

## 运行测试

```bash
python -m pytest
```

## 开发进度

- 2026-11-04：搭建阶段一最小闭环（B1/B2）：网格地图、手动移动与碰撞拒绝、REST API、Canvas 前端与 pytest 测试。
- 2026-11-04：新增巡检轮次功能：固定起点地图标记、离开-返回完成判定、巡检记录列表（内存存储），判定规则见 `docs/contract.md` 第 6 节。
- 2026-11-09：新增 9 个巡检点、自动巡检（`PLAN`，规划依次访问并返回起点）、回到起点（`HOME`）与页面巡检点进度展示，判定规则见 `docs/contract.md` 第 7 节。
- 2026-11-10：按嵌入式 / 深度学习 / 运维三方向拆分代码并接入异常检测推理模块（`inference/`），页面新增异常徽标（撞墙两次变红），判定规则见 `docs/contract.md` 第 3、8 节。

## 已知不足

- 异常检测当前为规则基线，尚未训练模型（升级路径见 `docs/model.md`）
- 传感器噪声注入、`ANOMALY`/`DONE` 状态、容器化部署、独立推理服务为后续阶段
- 巡检记录保存在内存中，服务重启即清空
