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


# ============================== 竞价/盘中实时恶化腿（2026-09-29） ==============================


def _settings(tmp_path):
    from quant_system.config import Settings

    s = Settings.__new__(Settings)  # 不触发 .env 重载
    s.data_dir = tmp_path
    return s


def _sent(monkeypatch, payload: dict | None):
    """打在 resolve 源头：compute_deterioration 函数级导入 standard_market_sentiment。"""
    from quant_system.datasource import resolve as _resolve

    if payload is None:
        def _boom(_s, _d=None):
            raise RuntimeError("源故障")
    else:
        def _boom(_s, _d=None):
            return payload
    monkeypatch.setattr(_resolve, "standard_market_sentiment", _boom)


class TestDeterioration:
    """实时恶化腿：阈值标定 09-21/24/28 早盘快照（温度/跌停早盘区分度弱，溢价为主判据）。"""

    def test_premium_negative_triggers(self, tmp_path, monkeypatch):
        _sent(monkeypatch, {"market_temperature": 47.0, "yesterday_limit_up_avg_pcp": -0.017})
        from quant_system.cycle import compute_deterioration

        chk = compute_deterioration(_settings(tmp_path), "2026-09-28")
        assert chk.triggered and any("溢价" in r for r in chk.reasons)

    def test_premium_0928_real_value_not_triggered(self, tmp_path, monkeypatch):
        # 09-28 早盘真实值：溢价 +0.38%、温度 46.96 → 竞价时点未恶化，不触发
        _sent(monkeypatch, {"market_temperature": 46.96, "yesterday_limit_up_avg_pcp": 0.0038,
                            "limit_down_count": 1})
        from quant_system.cycle import compute_deterioration

        chk = compute_deterioration(_settings(tmp_path), "2026-09-28")
        assert not chk.triggered and not chk.data_degraded

    def test_low_temperature_triggers(self, tmp_path, monkeypatch):
        _sent(monkeypatch, {"market_temperature": 21.0, "yesterday_limit_up_avg_pcp": 0.005})
        from quant_system.cycle import compute_deterioration

        chk = compute_deterioration(_settings(tmp_path), "2026-09-28")
        assert chk.triggered and any("温度" in r for r in chk.reasons)

    def test_missing_snapshot_degraded_not_triggered(self, tmp_path, monkeypatch):
        _sent(monkeypatch, None)
        from quant_system.cycle import compute_deterioration

        chk = compute_deterioration(_settings(tmp_path), "2026-09-28")
        assert not chk.triggered and chk.data_degraded

    def test_missing_fields_degraded_not_triggered(self, tmp_path, monkeypatch):
        _sent(monkeypatch, {"rise_count": 100})
        from quant_system.cycle import compute_deterioration

        chk = compute_deterioration(_settings(tmp_path), "2026-09-28")
        assert not chk.triggered and chk.data_degraded


class TestPrevFinalized:
    def test_parse_latest(self, tmp_path):
        from quant_system.cycle import CycleState, prev_finalized

        s = _settings(tmp_path)
        d = s.data_dir / "advice" / "2026-09-28"
        d.mkdir(parents=True)
        (d / "cycle_170034.json").write_text('{"state": "分歧", "overheated": false}', encoding="utf-8")
        (d / "cycle_013057.json").write_text('{"state": "退潮", "overheated": false}', encoding="utf-8")
        pf = prev_finalized(s, "2026-09-28")
        assert pf["state"] == CycleState.RETREAT  # 取最新一份

    def test_missing_returns_none(self, tmp_path):
        from quant_system.cycle import prev_finalized

        assert prev_finalized(_settings(tmp_path), "2026-09-28") is None

    def test_bad_json_returns_none(self, tmp_path):
        from quant_system.cycle import prev_finalized

        s = _settings(tmp_path)
        d = s.data_dir / "advice" / "2026-09-28"
        d.mkdir(parents=True)
        (d / "cycle_170034.json").write_text("{broken", encoding="utf-8")
        assert prev_finalized(s, "2026-09-28") is None


class TestWorstState:
    def test_ordering(self):
        from quant_system.cycle import CycleState, worst_state

        assert worst_state(CycleState.DIVERGE, CycleState.RETREAT) == CycleState.RETREAT
        assert worst_state(CycleState.REPAIR, CycleState.ACCEL) == CycleState.ACCEL
        assert worst_state(None, CycleState.ICE) == CycleState.ICE
        assert worst_state(None, None) is None


class TestCombinedGateState:
    def test_today_trusted_used_as_base(self, tmp_path, monkeypatch):
        from quant_system import cycle as cy

        s = _settings(tmp_path)
        _sent(monkeypatch, {"market_temperature": 47.0, "yesterday_limit_up_avg_pcp": 0.0038})
        today_j = cy.CycleJudgement(state=cy.CycleState.REPAIR, data_degraded=False)
        state, _over, reasons, _deg = cy.combined_gate_state(s, "2026-09-28", cy.CycleState.DIVERGE, False, today_j)
        assert state == cy.CycleState.REPAIR

    def test_today_degraded_falls_back_to_prev(self, tmp_path, monkeypatch):
        from quant_system import cycle as cy

        s = _settings(tmp_path)
        _sent(monkeypatch, {"market_temperature": 47.0, "yesterday_limit_up_avg_pcp": 0.0038})
        today_j = cy.CycleJudgement(state=cy.CycleState.DIVERGE, data_degraded=True)
        state, _over, reasons, _deg = cy.combined_gate_state(
            s, "2026-09-28", cy.CycleState.DIVERGE, False, today_j)
        assert state == cy.CycleState.DIVERGE
        assert any("T-1 定版" in r for r in reasons)
        assert any("数据降级" in r for r in reasons)

    def test_deterioration_overrides_prev_diverge(self, tmp_path, monkeypatch):
        """恶化立即生效：T-1 分歧 + 竞价溢价转负 → 按退潮否决。"""
        from quant_system import cycle as cy

        s = _settings(tmp_path)
        _sent(monkeypatch, {"market_temperature": 47.0, "yesterday_limit_up_avg_pcp": -0.01})
        today_j = cy.CycleJudgement(state=cy.CycleState.DIVERGE, data_degraded=True)
        state, _over, reasons, _deg = cy.combined_gate_state(
            s, "2026-09-28", cy.CycleState.DIVERGE, False, today_j)
        assert state == cy.CycleState.RETREAT

    def test_all_missing_returns_none_pass(self, tmp_path, monkeypatch):
        """无 T-1 定版 + 当日降级 + 恶化腿未触发 → None（调用方放行）。"""
        from quant_system import cycle as cy

        s = _settings(tmp_path)
        _sent(monkeypatch, {"market_temperature": 47.0, "yesterday_limit_up_avg_pcp": 0.0038})
        today_j = cy.CycleJudgement(state=cy.CycleState.DIVERGE, data_degraded=True)
        state, _over, reasons, _deg = cy.combined_gate_state(s, "2026-09-28", None, False, today_j)
        assert state is None
        assert any("放行" in r for r in reasons)
