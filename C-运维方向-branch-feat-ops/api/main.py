"""FastAPI 应用：REST 接口与静态页面托管（运维方向）。

阶段一以进程内方式转发 sim：一个 Simulator 实例持有全部状态，
页面刷新与轮询只读取状态，不产生副作用（与接口契约一致）。

本层同时是组装点（组合根）：把深度学习方向的异常检测推理模块
（inference.detector.AnomalyDetector）注入 sim 的 Simulator，
除此之外不掺任何业务规则。

自动巡检由服务端定时循环驱动：每隔 SIM_AUTO_INTERVAL 秒调用一次
simulator.auto_step()，仅在自动巡检激活时推进一步；测试中可通过
环境变量 SIM_AUTO_LOOP=0 关闭定时器，改用 STEP 指令逐步驱动。
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.staticfiles import StaticFiles

from inference.detector import AnomalyDetector
from sim.simulator import Simulator

# 服务端自动步进配置：SIM_AUTO_LOOP=0 关闭（测试用），SIM_AUTO_INTERVAL 调整步进间隔
AUTO_LOOP_ENABLED = os.environ.get("SIM_AUTO_LOOP", "1") != "0"
AUTO_STEP_INTERVAL = float(os.environ.get("SIM_AUTO_INTERVAL", "0.6"))


async def _auto_loop():
    """自动巡检定时循环：激活时每间隔推进一步。"""
    while True:
        await asyncio.sleep(AUTO_STEP_INTERVAL)
        simulator.auto_step()


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_auto_loop()) if AUTO_LOOP_ENABLED else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()


app = FastAPI(title="Web 智能巡检机器人仿真系统", version="0.3.0", lifespan=lifespan)

# 进程内单例仿真器：记录保存在内存中，服务重启即清空。
# 组装点：把深度学习方向的推理模块注入 sim（sim 不 import inference）。
simulator = Simulator(detector=AnomalyDetector())

# 静态页面目录（web/ 原生 HTML/CSS/JS）
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/health")
def health():
    """存活探针。"""
    return {"ok": True}


@app.get("/state")
def get_state():
    """当前完整状态（含巡检轮次与巡检点进度）。"""
    return simulator.state_dict()


@app.get("/map")
def get_map():
    """地图定义：尺寸、固定起点、巡检点与障碍。"""
    return simulator.map_dict()


@app.post("/cmd")
def post_cmd(payload: dict = Body(default={})):
    """处理一条指令，返回处理结果与最新状态。"""
    result = simulator.handle_command(payload.get("cmd"), payload.get("param") or {})
    return {"ok": result.ok, "msg": result.msg, "state": simulator.state_dict()}


# 静态页面挂载在 /（须在 API 路由之后，避免覆盖 /health /state /map /cmd 与 /docs）
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
