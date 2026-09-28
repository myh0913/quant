"""调度器纯逻辑单元测试——无网络，注入时钟。

2026-09-08 实测回归：hithink 交易日历返回 YYYYMMDD 紧凑格式，
必须归一化为 YYYY-MM-DD 再比对（否则全天任务被静默跳过）。
2026-09-29 回归：权威日历判休市（09-25 中秋休市日全管线照跑）+ 盘后补跑。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quant_system.scheduler import (
    in_window,
    load_state,
    should_catchup_postmarket,
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
        dates, _auth = _fetch_calendar(s)
        assert "2026-09-08" in dates
        assert "20260908" not in dates
        cached = json.loads((tmp_path / "state" / "calendar.json").read_text())
        assert "2026-09-08" in cached["dates"]


class TestIsTradingDay:
    """权威日历判休市（2026-09-29 回归）。

    09-25 中秋踩坑：旧逻辑对"日历未覆盖当天"一律周一至五兜底，休市日照跑
    全管线。新口径：本次取数成功/缓存为当日写入（authoritative）且 date≤今天
    且未列出 → 休市；未来日期/取数失败/陈旧缓存仍周几兜底（09-09 防空转保留）。
    """

    def _settings(self, tmp_path):
        from quant_system.config import Settings

        s = Settings.__new__(Settings)
        s.data_dir = tmp_path
        return s

    def test_authoritative_calendar_not_listing_today_is_holiday(self, tmp_path, monkeypatch):
        """当天成功取数仍未列出今天 → 休市（09-25 中秋回归）。"""
        from quant_system import scheduler as sched

        s = self._settings(tmp_path)
        monkeypatch.setattr(sched, "_fetch_calendar", lambda settings, need=None: ({"2026-09-24"}, True))
        today = sched.now_sh().strftime("%Y-%m-%d")
        assert sched.is_trading_day(s, today) is False

    def test_trading_day_listed_is_trading(self, tmp_path, monkeypatch):
        from quant_system import scheduler as sched

        s = self._settings(tmp_path)
        today = sched.now_sh().strftime("%Y-%m-%d")
        monkeypatch.setattr(sched, "_fetch_calendar", lambda settings, need=None: ({today}, True))
        assert sched.is_trading_day(s, today) is True

    def test_stale_cache_uncovered_falls_back_to_weekday(self, tmp_path, monkeypatch):
        """缓存非当日写入（陈旧）且未覆盖今天 → 周几兜底（09-09 防空转保留）。"""
        from quant_system import scheduler as sched

        s = self._settings(tmp_path)
        monkeypatch.setattr(sched, "_fetch_calendar", lambda settings, need=None: ({"2026-09-24"}, False))
        today = sched.now_sh().strftime("%Y-%m-%d")
        wd = datetime.strptime(today, "%Y-%m-%d").weekday() < 5
        assert sched.is_trading_day(s, today) is wd

    def test_fetch_failure_falls_back_to_weekday(self, tmp_path, monkeypatch):
        from quant_system import scheduler as sched

        s = self._settings(tmp_path)

        def _boom(settings, need=None):
            raise RuntimeError("上游故障")

        monkeypatch.setattr(sched, "_fetch_calendar", _boom)
        today = sched.now_sh().strftime("%Y-%m-%d")
        wd = datetime.strptime(today, "%Y-%m-%d").weekday() < 5
        assert sched.is_trading_day(s, today) is wd

    def test_future_date_uncovered_falls_back_to_weekday(self, tmp_path, monkeypatch):
        """未来日期未覆盖 → 周几兜底（不误杀未来交易日）。"""
        from quant_system import scheduler as sched

        s = self._settings(tmp_path)
        monkeypatch.setattr(sched, "_fetch_calendar", lambda settings, need=None: ({"2026-09-24"}, True))
        wd = datetime.strptime("2026-10-09", "%Y-%m-%d").weekday() < 5
        assert sched.is_trading_day(s, "2026-10-09") is wd

    def test_holiday_inside_coverage_is_false(self, tmp_path, monkeypatch):
        """日历覆盖内的历史休市日 → False（原行为保留）。"""
        from quant_system import scheduler as sched

        s = self._settings(tmp_path)
        monkeypatch.setattr(
            sched, "_fetch_calendar",
            lambda settings, need=None: ({"2026-09-21", "2026-09-22", "2026-09-24"}, True),
        )
        assert sched.is_trading_day(s, "2026-09-25") is False
        assert sched.is_trading_day(s, "2026-09-24") is True


class TestCatchupPostmarket:
    """盘后窗口错过（服务中断/重启）→ 当天内补跑一次（2026-09-29 回归）。"""

    def test_catchup_when_window_passed_and_never_ran(self):
        st = {"postmarket_done": False, "postmarket_catchup_done": False}
        assert should_catchup_postmarket(at("18:20"), st)

    def test_no_catchup_when_done(self):
        st = {"postmarket_done": True, "postmarket_catchup_done": False}
        assert not should_catchup_postmarket(at("18:20"), st)

    def test_no_catchup_when_already_caught_up(self):
        st = {"postmarket_done": False, "postmarket_catchup_done": True}
        assert not should_catchup_postmarket(at("18:20"), st)

    def test_no_catchup_inside_window(self):
        st = {"postmarket_done": False, "postmarket_catchup_done": False}
        assert not should_catchup_postmarket(at("17:30"), st)

    def test_no_catchup_before_window(self):
        st = {"postmarket_done": False, "postmarket_catchup_done": False}
        assert not should_catchup_postmarket(at("15:00"), st)
