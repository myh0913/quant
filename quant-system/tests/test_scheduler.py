"""调度器纯逻辑单元测试——无网络，注入时钟。

2026-09-08 实测回归：hithink 交易日历返回 YYYYMMDD 紧凑格式，
必须归一化为 YYYY-MM-DD 再比对（否则全天任务被静默跳过）。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quant_system.scheduler import (
    in_window,
    load_state,
    should_run_once,
    should_tick,
    window_passed,
)

SH = ZoneInfo("Asia/Shanghai")


def at(hm: str) -> datetime:
    return datetime.strptime(f"2026-09-07 {hm}", "%Y-%m-%d %H:%M").replace(tzinfo=SH)


class TestWindow:
    def test_in_window(self):
        assert in_window(at("09:25"), "09:25", "09:40")
        assert in_window(at("09:40"), "09:25", "09:40")
        assert not in_window(at("09:24"), "09:25", "09:40")
        assert not in_window(at("09:41"), "09:25", "09:40")

    def test_window_passed(self):
        assert window_passed(at("10:01"), "10:00")
        assert not window_passed(at("09:59"), "10:00")


class TestOnce:
    def test_runs_in_window_when_not_done(self):
        st = {"auction_done": False}
        assert should_run_once(at("09:25"), st, "auction_done", ("09:25", "09:40"))

    def test_skips_when_done(self):
        st = {"auction_done": True}
        assert not should_run_once(at("09:30"), st, "auction_done", ("09:25", "09:40"))

    def test_skips_outside_window(self):
        st = {"auction_done": False}
        assert not should_run_once(at("09:45"), st, "auction_done", ("09:25", "09:40"))
        assert not should_run_once(at("09:20"), st, "auction_done", ("09:25", "09:40"))


class TestTick:
    def test_first_tick_runs(self):
        st = {"intraday_last": None}
        assert should_tick(at("09:26"), st, ("09:26", "10:00"), 60)

    def test_interval_spacing(self):
        st = {"intraday_last": "09:30:00"}
        assert not should_tick(datetime(2026, 9, 7, 9, 30, 30, tzinfo=SH), st, ("09:26", "10:00"), 60)
        assert should_tick(datetime(2026, 9, 7, 9, 31, 0, tzinfo=SH), st, ("09:26", "10:00"), 60)

    def test_outside_window_no_tick(self):
        st = {"intraday_last": None}
        assert not should_tick(at("10:01"), st, ("09:26", "10:00"), 60)
        assert not should_tick(at("09:25"), st, ("09:26", "10:00"), 60)


class TestState:
    def test_load_default(self, tmp_path):
        from quant_system.config import Settings

        s = Settings.__new__(Settings)  # 不触发 .env 重载
        s.data_dir = tmp_path
        st = load_state(s, "2026-09-07")
        assert st["auction_done"] is False
        assert st["intraday_triggered"] == []

    def test_save_roundtrip(self, tmp_path):
        from quant_system.config import Settings
        from quant_system.scheduler import save_state

        s = Settings.__new__(Settings)
        s.data_dir = tmp_path
        st = {"auction_done": True, "intraday_triggered": ["600001.SH"]}
        save_state(s, "2026-09-07", st)
        assert load_state(s, "2026-09-07") == st


class TestCalendarFormat:
    """回归：hithink 返回 YYYYMMDD 紧凑格式，必须归一化（2026-09-08 实测踩坑）。

    M2 起日历走 resolve.standard_trading_days（内部经 _SOURCE_CLS 实例化源），
    因此 mock 打在 registry._SOURCE_CLS 上。
    """

    def test_compact_dates_normalized(self, tmp_path, monkeypatch):
        import json

        from quant_system.config import Settings
        from quant_system.datasource import registry as ds_registry
        from quant_system.scheduler import _fetch_calendar

        s = Settings.__new__(Settings)
        s.data_dir = tmp_path
        s.raw_dir = tmp_path / "raw"

        class _FakeHS:
            def __init__(self, _s):
                pass

            def _get(self, path, params=None, name="data", timeout=30):
                return {"item": [{"date": "20260905"}, {"date": "20260908"}]}, {}

        monkeypatch.setitem(ds_registry._SOURCE_CLS, "hithink", _FakeHS)
        dates = _fetch_calendar(s)
        assert "2026-09-08" in dates
        assert "20260908" not in dates
        cached = json.loads((tmp_path / "state" / "calendar.json").read_text())
        assert "2026-09-08" in cached["dates"]
