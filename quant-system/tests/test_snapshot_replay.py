"""快照层与回放测试——无网络，快照用夹具手工落盘。

M3 不变量：
- live 取数自动落快照；replay_scope 内只读快照、缺失抛 SnapshotMissing；
- 回放确定性：同快照同参数，两次回放的策略性输出（factors/建议标的/summary）一致；
- 快照缺失的 phases 记为 ok=False + warnings，不炸整场回放。
"""
from __future__ import annotations

import json

import pytest

from quant_system.config import Settings
from quant_system.models import AuctionPoint, AuctionRankRow, OpeningMatch
from quant_system.snapshot import SnapshotMissing, replay_scope, save, snapshot_dir
from quant_system.replay import run_replay

D = "2026-09-11"        # 回放日（周五）
PREV = "2026-09-10"     # 上一交易日（周四）
CODE = "600001.SH"


def make_settings(tmp_path) -> Settings:
    s = Settings.__new__(Settings)
    s.data_dir = tmp_path
    s.raw_dir = tmp_path / "raw"
    return s


def seed_auction_snapshots(s: Settings) -> None:
    """为 auction_grab 在 D 日铺一套完整快照（指标→门控通过，标的触发买入）。"""
    save(s, D, "market_sentiment", {"date": D}, {
        "market_temperature": 45.0, "limit_up_count": 60, "limit_down_count": 5,
        "limit_up_broken_count": 10,
    })
    pool_row = {"thscode": CODE, "name": "示例股份", "continue_day_cnt": 3, "last_price": 10.0}
    save(s, D, "limit_up_pool", {"date": D}, [pool_row])
    save(s, D, "limit_up_pool", {"date": PREV}, [pool_row])  # 晋级率 100%
    save(s, D, "index_snapshot", {}, 0.005)
    save(s, D, "monitor_stocks", {}, [])
    save(s, D, "auction_top_amount", {"limit": 10}, [
        AuctionRankRow(
            thscode=CODE, ticker="600001", name="示例股份",
            auction_amount_yuan=1.2e8, auction_price=9.9, open_price=9.9,
            pre_close=10.0, source="eltdx", data_date=D,
            ts="2026-09-11T01:25:00+00:00",
        )
    ])
    save(s, D, "auction_series", {"thscode": CODE, "date": D}, [
        AuctionPoint(time_label="09:20:00", price=9.9, matched_volume=100, unmatched_volume=50),
    ])
    save(s, D, "opening_match", {"thscode": CODE, "date": D},
         OpeningMatch(price=10.15, volume=1200, time_label="09:25"))


class TestSnapshotIO:
    def test_replay_reads_snapshot(self, tmp_path):
        """replay_scope 内读快照（不再触发任何数据源）。"""
        from quant_system.datasource import registry as ds_registry
        from quant_system.datasource.resolve import standard_limit_up_pool

        s = make_settings(tmp_path)
        save(s, D, "limit_up_pool", {"date": D}, [{"thscode": CODE, "name": "x", "continue_day_cnt": 2, "last_price": 9.0}])

        class _Boom:
            def __init__(self, _s):
                raise AssertionError("回放模式不得触达数据源")

        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(ds_registry._SOURCE_CLS, "hithink", _Boom)
            with replay_scope(s, D):
                rows = standard_limit_up_pool(s, D)
        assert rows[0]["thscode"] == CODE

    def test_replay_missing_raises(self, tmp_path):
        from quant_system.datasource.resolve import standard_limit_up_pool

        s = make_settings(tmp_path)
        with replay_scope(s, D):
            with pytest.raises(SnapshotMissing):
                standard_limit_up_pool(s, D)

    def test_live_saves_snapshot(self, tmp_path, monkeypatch):
        from quant_system.datasource import registry as ds_registry
        from quant_system.datasource.resolve import standard_limit_up_pool
        from quant_system.timeutil import sh_today

        s = make_settings(tmp_path)

        class _FakeHS:
            source_name = "hithink"

            def __init__(self, st):
                self.raw_dir = st.raw_dir

            def limit_up_pool(self, date_ms=None, page=1, size=50, sort_field="x", sort_dir="desc"):
                return ([{"thscode": CODE, "name": "x", "continue_day_cnt": 2, "last_price": 9.0}], {})

        monkeypatch.setitem(ds_registry._SOURCE_CLS, "hithink", _FakeHS)
        rows = standard_limit_up_pool(s, D)  # live 模式
        assert rows[0]["thscode"] == CODE
        files = list(snapshot_dir(s, D).glob("limit_up_pool-*.json"))
        assert files, "live 取数应自动落快照"
        doc = json.loads(files[0].read_text())
        assert doc["capability"] == "limit_up_pool"
        assert doc["payload"][0]["thscode"] == CODE
        # sh_today 快照目录也应有（当日的落盘）；此处 D 非 today，验证 args 落盘正确即可
        assert doc["args"] == {"date": D}


class TestReplay:
    def test_auction_replay_deterministic(self, tmp_path):
        s = make_settings(tmp_path)
        seed_auction_snapshots(s)

        r1 = run_replay(s, D, ["auction_grab"])
        r2 = run_replay(s, D, ["auction_grab"])

        assert r1["summary"]["auction_grab"]["advices"] == 1
        assert r1["summary"]["auction_grab"]["candidates"] == 1
        au1 = r1["results"]["auction_grab"]["phases"]["auction"]
        assert au1["ok"] is True
        assert au1["cycle_state"] == "修复"
        assert [a["thscode"] for a in au1["advices"]] == [CODE]

        # 确定性：策略性输出一致（时间戳类字段除外）
        au2 = r2["results"]["auction_grab"]["phases"]["auction"]
        assert au1["factors"] == au2["factors"]
        assert [a["thscode"] for a in au1["advices"]] == [a["thscode"] for a in au2["advices"]]
        assert r1["summary"] == r2["summary"]
        assert r1["warnings"] == r2["warnings"] == []

    def test_replay_with_param_override_changes_result(self, tmp_path):
        """参数 9:20→9:25 最小拉升 0.02→0.10：夹具涨幅 2.53% 应不再触发。"""
        s = make_settings(tmp_path)
        seed_auction_snapshots(s)

        r = run_replay(s, D, ["auction_grab"], params={"auction_grab": {"min_rise": 0.10}})
        assert r["summary"]["auction_grab"]["advices"] == 0
        assert r["params_overrides"] == {"auction_grab": {"min_rise": 0.10}}

    def test_missing_snapshots_degrade_not_crash(self, tmp_path):
        """连板/龙回头无快照 → phase ok=False + warning，不影响其他策略。"""
        s = make_settings(tmp_path)
        seed_auction_snapshots(s)  # 只铺 auction 所需

        r = run_replay(s, D, ["auction_grab", "lianban", "dragon"])
        assert r["results"]["auction_grab"]["phases"]["auction"]["ok"] is True
        for sid in ("lianban", "dragon"):
            pool = r["results"][sid]["phases"]["pool"]
            assert pool["ok"] is False
            assert "快照缺失" in pool["error"]
        assert any("快照缺失" in w for w in r["warnings"])
