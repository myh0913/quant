"""组合风控与回测聚合单元测试——无网络（2026-09-18 M2/M3）。"""
from __future__ import annotations

from quant_system.backtest import aggregate
from quant_system.config import Settings
from quant_system.portfolio import apply_portfolio_limits, position_display


def make_settings(tmp_path) -> Settings:
    s = Settings.__new__(Settings)
    s.data_dir = tmp_path
    s.raw_dir = tmp_path / "raw"
    return s


class TestPortfolio:
    def test_dedup_same_stock(self, tmp_path):
        s = make_settings(tmp_path)
        items = [
            {"thscode": "600001.SH", "name": "A", "position_pct": 0.2},
            {"thscode": "600001.SH", "name": "A", "position_pct": 0.2},
        ]
        stats = apply_portfolio_limits(items, s)
        assert items[0]["position_pct"] == 0.2 and not items[0]["demoted"]
        assert items[1]["demoted"] and items[1]["position_pct"] == 0.0
        assert "单票去重" in items[1]["portfolio_note"]
        assert stats["demoted_dup"] == 1

    def test_total_position_cap(self, tmp_path):
        s = make_settings(tmp_path)
        items = [
            {"thscode": "600001.SH", "name": "A", "position_pct": 0.4},
            {"thscode": "600002.SH", "name": "B", "position_pct": 0.4},
            {"thscode": "600003.SH", "name": "C", "position_pct": 0.4},  # 0.4+0.4=0.8 已到上限
        ]
        apply_portfolio_limits(items, s)
        assert not items[0]["demoted"] and not items[1]["demoted"]
        assert items[2]["demoted"] and "总仓位超限" in items[2]["portfolio_note"]

    def test_position_display(self):
        pct, text = position_display(0.2, 0.5)
        assert pct == 0.1
        assert "20%×0.5=10%" in text


class TestBacktestAggregate:
    def test_aggregate_excludes_unfillable_and_demoted_zero(self):
        # demoted 条目 position_pct=0 但仍可能成交口径有值 → 胜负统计应剔除 unfillable
        entries = [
            {"strategy": "lianban", "win": True, "win_close": True, "unfillable": False, "next_high_pct": 0.03},
            {"strategy": "lianban", "win": False, "win_close": False, "unfillable": True, "next_high_pct": 0.05},
            {"strategy": "dragon", "win": True, "win_close": False, "unfillable": False, "next_high_pct": 0.01,
             "gate_state": "修复"},
        ]
        agg = aggregate(entries)
        assert agg["overall"]["count"] == 3
        assert agg["overall"]["fillable"] == 2
        assert agg["overall"]["win_rate"] == 1.0
        assert agg["overall"]["win_rate_close"] == 0.5
        assert agg["cycle:修复"]["count"] == 1
