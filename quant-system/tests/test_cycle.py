"""情绪周期状态机单元测试——合成指标，无网络。

2026-09-14 更新：退潮改为复合条件（炸板率≥35% 且 晋级率<25%/跌停多）；
高晋级+高炸板 → 分歧（高位分歧加剧），不再一刀切退潮。
"""
from __future__ import annotations

import pytest

from quant_system.cycle import (
    CycleIndicators,
    CycleState,
    CycleThresholds,
    classify,
    strategy_gate,
)


def ind(**kw) -> CycleIndicators:
    """默认构造一个"修复态"指标，便于逐项改坏测试。"""
    base = dict(
        date="2026-09-08", temperature=45.0, limit_up_count=60, limit_down_count=5,
        break_ratio=0.15, promotion_rate=0.30, board_height=4,
        leader_thscode="600001.SH", leader_name="示例", leader_limit_down=False,
        index_daily_pct=0.005,
    )
    base.update(kw)
    return CycleIndicators(**base)


class TestRetreat:
    def test_break_ratio_with_weak_promotion(self):
        # 复合条件：炸板率≥35% 且 晋级率<25% → 退潮
        j = classify(ind(break_ratio=0.55, promotion_rate=0.10))
        assert j.state == CycleState.RETREAT
        assert any("炸板率" in r for r in j.reasons)

    def test_2026_09_08_real_values(self):
        # 真实 09-08：炸板55% 晋级15.9% 温度46 → 退潮
        j = classify(ind(break_ratio=0.551, promotion_rate=0.159, temperature=46.3, limit_up_count=40))
        assert j.state == CycleState.RETREAT

    def test_high_break_strong_promotion_is_diverge(self):
        # 用户确认 2026-09-14：高晋级(27.5%)+高炸板(38.5%) → 分歧，不退潮
        j = classify(ind(break_ratio=0.385, promotion_rate=0.275, temperature=55.9,
                         limit_up_count=56, limit_down_count=18, board_height=4))
        assert j.state == CycleState.DIVERGE
        assert any("高位分歧加剧" in r for r in j.reasons)

    def test_leader_limit_down(self):
        j = classify(ind(leader_limit_down=True))
        assert j.state == CycleState.RETREAT

    def test_limit_down_count(self):
        j = classify(ind(limit_down_count=60))
        assert j.state == CycleState.RETREAT

    def test_blackswan_index_drop(self):
        j = classify(ind(index_daily_pct=-0.035))
        assert j.state == CycleState.RETREAT
        assert any("黑天鹅" in r for r in j.reasons)


class TestDiverge:
    def test_break_ratio_mid(self):
        j = classify(ind(break_ratio=0.28))
        assert j.state == CycleState.DIVERGE

    def test_low_promotion(self):
        j = classify(ind(break_ratio=0.10, promotion_rate=0.10))
        assert j.state == CycleState.DIVERGE
        assert any("晋级率" in r for r in j.reasons)


class TestAccel:
    def test_all_three_conditions(self):
        j = classify(ind(temperature=65, promotion_rate=0.30, board_height=6))
        assert j.state == CycleState.ACCEL

    def test_missing_one_fails(self):
        # 高度4<5 → 不加速
        j = classify(ind(temperature=65, promotion_rate=0.30, board_height=4, limit_up_count=80))
        assert j.state != CycleState.ACCEL


class TestRepairAndIce:
    def test_repair(self):
        j = classify(ind())  # 默认值即修复
        assert j.state == CycleState.REPAIR

    def test_repair_needs_confirm_on_first_day(self):
        j = classify(ind(), prev_state=CycleState.RETREAT)
        assert j.state == CycleState.REPAIR
        assert j.relaxed_needs_confirm

    def test_repair_no_confirm_if_same_as_prev(self):
        j = classify(ind(), prev_state=CycleState.REPAIR)
        assert not j.relaxed_needs_confirm

    def test_ice(self):
        j = classify(ind(temperature=25, limit_down_count=40, limit_up_count=20))
        assert j.state == CycleState.ICE


class TestOverheat:
    def test_overheated_halves_position(self):
        j = classify(ind(temperature=78, promotion_rate=0.30, board_height=7))
        assert j.overheated
        _, factor, note = strategy_gate(j.state, "连板捉妖", j.overheated)
        assert factor == 0.5
        assert "过热" in note


class TestGate:
    def test_gate_matrix(self):
        # 退潮全禁
        for s in ("竞价主力抢筹", "连板捉妖", "龙回头"):
            ok, f, _ = strategy_gate(CycleState.RETREAT, s)
            assert not ok and f == 0
        # 加速全开 1.0
        for s in ("竞价主力抢筹", "连板捉妖", "龙回头"):
            ok, f, _ = strategy_gate(CycleState.ACCEL, s)
            assert ok and f == 1.0
        # 冰点转折只开策略一 0.3
        ok1, f1, _ = strategy_gate(CycleState.TURN, "竞价主力抢筹")
        ok2, _, _ = strategy_gate(CycleState.TURN, "连板捉妖")
        assert ok1 and f1 == 0.3 and not ok2
        # 分歧：策略二禁、策略一/三 0.5
        ok_a, fa, _ = strategy_gate(CycleState.DIVERGE, "竞价主力抢筹")
        ok_l, fl, _ = strategy_gate(CycleState.DIVERGE, "龙回头")
        ok_z, fz, _ = strategy_gate(CycleState.DIVERGE, "连板捉妖")
        assert ok_a and fa == 0.5 and ok_l and fl == 0.5 and not ok_z

    def test_thresholds_easy_to_change(self):
        """用户改阈值后判定立即变化（快速修改验证）。"""
        th = CycleThresholds(retreat_break_ratio=0.99)  # 抬高退潮线
        j = classify(ind(break_ratio=0.55, promotion_rate=0.10), th=th)
        assert j.state != CycleState.RETREAT
