"""自动巡检与回到起点功能测试：巡检点打卡、PLAN/HOME/STEP。

本文件只测 sim 仿真核心（嵌入式方向），不依赖 api 层；
走 HTTP 接口的 PLAN 联调用例在 tests/test_api.py（运维方向维护）。
"""

from sim.simulator import Simulator
from sim.world import WorldMap

POINT_COUNT = 9


def walk_auto(sim, max_steps=500):
    """逐步走完当前自动路径。"""
    for _ in range(max_steps):
        if not sim.state_dict()["auto"]:
            break
        result = sim.handle_command("STEP")
        assert result.ok
    assert not sim.state_dict()["auto"], "auto route did not finish"


def test_map_has_nine_patrol_points():
    data = WorldMap().to_dict()
    assert len(data["patrol_points"]) == POINT_COUNT
    obstacles = set(map(tuple, data["obstacles"]))
    assert all(tuple(p) not in obstacles for p in data["patrol_points"])


def test_plan_visits_all_points_and_returns_to_start():
    sim = Simulator()
    result = sim.handle_command("PLAN")
    assert result.ok
    state = sim.state_dict()
    assert state["auto"] is True
    assert len(state["path"]) > 0
    assert state["path_index"] == 0

    walk_auto(sim)
    state = sim.state_dict()
    assert state["patrol"]["points_visited"] == POINT_COUNT
    assert (state["robot"]["x"], state["robot"]["y"]) == (1, 1)
    assert state["patrol"]["rounds_completed"] == 1
    assert "complete" in state["log"]


def test_manual_move_rejected_during_auto():
    sim = Simulator()
    assert sim.handle_command("PLAN").ok
    result = sim.handle_command("MOVE", {"dir": "forward"})
    assert not result.ok
    state = sim.state_dict()
    assert state["state"] == "RUNNING"
    assert state["path_index"] == 0


def test_stop_pauses_auto_and_start_resumes():
    sim = Simulator()
    assert sim.handle_command("PLAN").ok
    assert sim.handle_command("STOP").ok
    result = sim.handle_command("STEP")
    assert not result.ok
    assert sim.state_dict()["path_index"] == 0
    assert sim.handle_command("START").ok
    assert sim.handle_command("STEP").ok
    assert sim.state_dict()["path_index"] == 1


def test_home_returns_to_start():
    sim = Simulator()
    sim.handle_command("MOVE", {"dir": "forward"})  # 离开起点到 (2,1)
    assert sim.handle_command("MOVE", {"dir": "right"}).ok
    sim.handle_command("MOVE", {"dir": "forward"})  # (2,2)
    result = sim.handle_command("HOME")
    assert result.ok
    walk_auto(sim)
    state = sim.state_dict()
    assert (state["robot"]["x"], state["robot"]["y"]) == (1, 1)
    assert state["patrol"]["rounds_completed"] == 1


def test_reset_clears_auto_state():
    sim = Simulator()
    assert sim.handle_command("PLAN").ok
    assert sim.handle_command("RESET").ok
    state = sim.state_dict()
    assert state["auto"] is False
    assert state["path"] == []
    assert state["path_index"] == 0
    assert state["state"] == "IDLE"
    assert state["patrol"]["points_visited"] == 0


def test_auto_patrol_keeps_anomaly_normal():
    """自动巡检全程不碰撞：异常概率不应越过判定阈值。"""
    sim = Simulator()
    assert sim.handle_command("PLAN").ok
    walk_auto(sim)
    sensors = sim.state_dict()["sensors"]
    assert sensors["anomaly_label"] == "normal"
    assert sensors["anomaly_prob"] < 0.5
