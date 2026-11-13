"""巡检轮次功能测试：固定起点、离开-返回完成判定、巡检记录。

本文件只测 sim 仿真核心（嵌入式方向），不依赖 api 层；
走 HTTP 接口的巡检联调用例在 tests/test_api.py（运维方向维护）。
"""

from sim.simulator import IDLE, Simulator
from sim.world import WorldMap


def make_sim(**kwargs):
    return Simulator(WorldMap(**kwargs))


def do_round(sim):
    """从起点出发完成一轮巡检：前进离开 → 转向 180° → 前进返回。"""
    sim.handle_command("MOVE", {"dir": "forward"})
    sim.handle_command("MOVE", {"dir": "right"})
    sim.handle_command("MOVE", {"dir": "right"})
    return sim.handle_command("MOVE", {"dir": "forward"})


# ---------------------------------------------------------------------------
# 初始化与无副作用场景
# ---------------------------------------------------------------------------

def test_initial_no_records():
    sim = Simulator()
    patrol = sim.state_dict()["patrol"]
    assert patrol["rounds_completed"] == 0
    assert patrol["records"] == []
    assert patrol["left_start"] is False


def test_state_reads_do_not_create_records():
    sim = Simulator()
    first = sim.state_dict()
    for _ in range(3):
        sim.state_dict()
    assert sim.state_dict() == first


def test_turn_in_place_at_start_does_not_leave():
    sim = Simulator()
    sim.handle_command("MOVE", {"dir": "left"})
    sim.handle_command("MOVE", {"dir": "right"})
    patrol = sim.state_dict()["patrol"]
    assert patrol["left_start"] is False
    assert patrol["records"] == []


# ---------------------------------------------------------------------------
# 完成判定
# ---------------------------------------------------------------------------

def test_leave_then_return_completes_round_one():
    sim = Simulator()
    sim.handle_command("MOVE", {"dir": "forward"})  # (2,1) 离开起点
    patrol = sim.state_dict()["patrol"]
    assert patrol["left_start"] is True
    assert patrol["records"] == []

    sim.handle_command("MOVE", {"dir": "right"})    # heading 90
    sim.handle_command("MOVE", {"dir": "right"})    # heading 180
    result = sim.handle_command("MOVE", {"dir": "forward"})  # 一次有效移动返回 (1,1)
    assert result.ok
    assert "round 1 completed" in result.msg
    state = sim.state_dict()
    assert (state["robot"]["x"], state["robot"]["y"]) == (1, 1)
    patrol = state["patrol"]
    assert patrol["rounds_completed"] == 1
    assert patrol["left_start"] is False
    assert len(patrol["records"]) == 1
    record = patrol["records"][0]
    assert record["round"] == 1
    assert isinstance(record["completed_at"], str) and record["completed_at"]


def test_round_completes_after_wandering():
    """多步远离后返回，同样只记一轮。"""
    sim = Simulator()
    sim.handle_command("MOVE", {"dir": "forward"})  # (2,1) 离开
    sim.handle_command("MOVE", {"dir": "right"})    # heading 90
    sim.handle_command("MOVE", {"dir": "forward"})  # (2,2)
    sim.handle_command("MOVE", {"dir": "left"})     # heading 0
    sim.handle_command("MOVE", {"dir": "back"})     # (1,2) 仍离开
    assert sim.state_dict()["patrol"]["records"] == []

    sim.handle_command("MOVE", {"dir": "left"})     # heading 270
    result = sim.handle_command("MOVE", {"dir": "forward"})  # 回 (1,1)
    assert result.ok
    patrol = sim.state_dict()["patrol"]
    assert patrol["rounds_completed"] == 1
    assert [r["round"] for r in patrol["records"]] == [1]


def test_second_round_requires_leaving_again():
    sim = Simulator()
    do_round(sim)
    # 机器人已在起点：原地转向不产生记录
    sim.handle_command("MOVE", {"dir": "left"})
    sim.handle_command("MOVE", {"dir": "right"})
    assert sim.state_dict()["patrol"]["rounds_completed"] == 1
    # 再次离开并返回 → 第 2 轮
    do_round(sim)
    patrol = sim.state_dict()["patrol"]
    assert patrol["rounds_completed"] == 2
    assert [r["round"] for r in patrol["records"]] == [1, 2]


# ---------------------------------------------------------------------------
# 无效移动不影响巡检
# ---------------------------------------------------------------------------

def test_invalid_move_does_not_complete_round():
    sim = make_sim(width=3, height=3, obstacles={(2, 0)}, robot_start=(1, 1))
    sim.handle_command("MOVE", {"dir": "forward"})  # (2,1) 离开起点
    sim.handle_command("MOVE", {"dir": "left"})     # heading 270（向上）
    result = sim.handle_command("MOVE", {"dir": "forward"})  # (2,0) 是障碍
    assert not result.ok
    state = sim.state_dict()
    assert state["state"] == "COLLISION"
    assert (state["robot"]["x"], state["robot"]["y"]) == (2, 1)
    patrol = state["patrol"]
    assert patrol["records"] == []
    assert patrol["left_start"] is True  # 尝试仍在进行，未丢失也未误判完成

    # 调整朝向后仍可完成本轮
    sim.handle_command("MOVE", {"dir": "left"})      # heading 180
    assert sim.handle_command("MOVE", {"dir": "forward"}).ok  # 回 (1,1)
    assert sim.state_dict()["patrol"]["rounds_completed"] == 1


def test_invalid_move_at_start_does_not_record():
    sim = make_sim(width=2, height=2, obstacles=frozenset(), robot_start=(0, 0))
    sim.handle_command("MOVE", {"dir": "left"})     # heading 270
    sim.handle_command("MOVE", {"dir": "left"})     # heading 180
    result = sim.handle_command("MOVE", {"dir": "forward"})  # (-1,0) 越界
    assert not result.ok
    patrol = sim.state_dict()["patrol"]
    assert patrol["records"] == []
    assert patrol["left_start"] is False


# ---------------------------------------------------------------------------
# RESET 语义
# ---------------------------------------------------------------------------

def test_reset_aborts_attempt_but_keeps_records():
    sim = Simulator()
    do_round(sim)
    assert sim.state_dict()["patrol"]["rounds_completed"] == 1

    # 再次离开后 RESET：中止当前尝试
    sim.handle_command("MOVE", {"dir": "forward"})
    result = sim.handle_command("RESET")
    assert result.ok
    state = sim.state_dict()
    assert state["state"] == IDLE
    assert (state["robot"]["x"], state["robot"]["y"]) == (1, 1)
    patrol = state["patrol"]
    assert patrol["left_start"] is False
    assert patrol["rounds_completed"] == 1
    assert len(patrol["records"]) == 1

    # 下一轮轮次继续递增
    do_round(sim)
    patrol = sim.state_dict()["patrol"]
    assert patrol["rounds_completed"] == 2
    assert [r["round"] for r in patrol["records"]] == [1, 2]


# ---------------------------------------------------------------------------
# 无推理模块注入时的缺省行为（深度学习方向的 detector 由 api 组装时注入）
# ---------------------------------------------------------------------------

def test_without_detector_anomaly_stays_default():
    sim = Simulator()
    sim.handle_command("MOVE", {"dir": "forward"})
    sensors = sim.state_dict()["sensors"]
    assert sensors["anomaly_prob"] == 0.0
    assert sensors["anomaly_label"] == "normal"
