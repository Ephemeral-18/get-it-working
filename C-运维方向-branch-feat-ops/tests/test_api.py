"""API 接口测试（运维方向）：契约字段、指令转发与三人方向联调用例。

其中「巡检轮次走接口」「PLAN 走接口」「异常检测走接口」三个用例
分别验证 sim（嵌入式方向）与 inference（深度学习方向）经 api 组装后的
端到端行为，需要三人分支合并后才能运行。
"""

from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app

client = TestClient(app)


def _reset():
    assert client.post("/cmd", json={"cmd": "RESET", "param": {}}).json()["ok"] is True


def test_health():
    assert client.get("/health").json() == {"ok": True}


def test_map_shape():
    data = client.get("/map").json()
    assert data["width"] == 20
    assert data["height"] == 15
    assert isinstance(data["obstacles"], list)
    assert data["obstacles"]


def test_state_contract_fields():
    _reset()
    data = client.get("/state").json()
    for key in ("tick", "robot", "battery", "sensors", "path", "path_index", "state", "log", "patrol"):
        assert key in data
    assert data["state"] in {"IDLE", "RUNNING", "PAUSED", "COLLISION"}
    assert set(data["robot"]) == {"x", "y", "heading", "speed"}
    assert set(data["sensors"]) == {
        "front", "left", "right", "back", "touch", "anomaly_prob", "anomaly_label",
    }


def test_cmd_move_updates_state():
    _reset()
    res = client.post(
        "/cmd",
        json={"cmd": "MOVE", "param": {"dir": "forward"}, "from": "user", "seq": 1},
    ).json()
    assert res["ok"] is True
    assert res["state"]["robot"]["x"] == 2


def test_cmd_collision_rejected():
    _reset()
    client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "left"}})
    client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "left"}})
    # 两次左转后 heading=180（向左）：先走到 (0,1)，再前进步越界 (-1,1) 被拒绝
    first = client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "forward"}}).json()
    assert first["ok"] is True
    second = client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "forward"}}).json()
    assert second["ok"] is False
    assert second["state"]["state"] == "COLLISION"
    assert second["state"]["robot"]["x"] == 0


def test_cmd_unknown_rejected():
    res = client.post("/cmd", json={"cmd": "FLY", "param": {}}).json()
    assert res["ok"] is False


def test_static_index_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


# ---------------------------------------------------------------------------
# 跨方向联调：巡检轮次（嵌入式）经 HTTP 接口
# ---------------------------------------------------------------------------

def test_api_patrol_flow_and_map_start():
    _reset()

    map_data = client.get("/map").json()
    assert map_data["start"] == [1, 1]

    def move(direction):
        return client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": direction}}).json()

    move("forward")
    move("right")
    move("right")
    result = move("forward")
    assert result["state"]["patrol"]["rounds_completed"] == 1

    # 重复读取状态（等价于刷新页面轮询）不新增记录
    for _ in range(3):
        assert len(client.get("/state").json()["patrol"]["records"]) == 1


# ---------------------------------------------------------------------------
# 跨方向联调：自动巡检（嵌入式）经 HTTP 接口
# ---------------------------------------------------------------------------

def test_api_plan_step_flow():
    # api.main.simulator 是跨测试共享的单例：换入全新实例，避免污染其他用例
    original = api_main.simulator
    api_main.simulator = api_main.Simulator()
    try:
        _reset()
        assert client.post("/cmd", json={"cmd": "PLAN", "param": {}}).json()["ok"] is True
        for _ in range(500):
            state = client.get("/state").json()
            if not state["auto"]:
                break
            res = client.post("/cmd", json={"cmd": "STEP", "param": {}}).json()
            assert res["ok"] is True
        state = client.get("/state").json()
        assert state["patrol"]["points_visited"] == 9
        assert state["patrol"]["rounds_completed"] == 1
    finally:
        api_main.simulator = original


# ---------------------------------------------------------------------------
# 跨方向联调：异常检测（深度学习）经 HTTP 接口
# ---------------------------------------------------------------------------

def test_anomaly_detector_via_api():
    _reset()
    # 走到左边界格 (0,1)，朝西
    client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "left"}})
    client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "left"}})
    client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "forward"}})
    # 第一次撞界：touch 入窗口，概率上升但未过阈值
    first = client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "forward"}}).json()
    assert first["ok"] is False
    sensors = first["state"]["sensors"]
    assert sensors["anomaly_label"] == "normal"
    assert 0.0 < sensors["anomaly_prob"] < 0.5
    # 第二次撞界：窗口内两次碰撞，判定异常
    second = client.post("/cmd", json={"cmd": "MOVE", "param": {"dir": "forward"}}).json()
    assert second["ok"] is False
    sensors = second["state"]["sensors"]
    assert sensors["anomaly_label"] == "anomaly"
    assert sensors["anomaly_prob"] >= 0.5
    # RESET 清空推理窗口，恢复正常
    _reset()
    sensors = client.get("/state").json()["sensors"]
    assert sensors["anomaly_label"] == "normal"
    assert sensors["anomaly_prob"] == 0.0
