"""调度器纯逻辑单元测试——无网络，注入时钟。

2026-09-08 实测回归：hithink 交易日历返回 YYYYMMDD 紧凑格式，
必须归一化为 YYYY-MM-DD 再比对（否则全天任务被静默跳过）。
2026-09-29 回归：权威日历判休市（09-25 中秋休市日全管线照跑）+ 盘后补跑。
"""
from __future__ import annotations

import json
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


class TestIntradayPlanClassifyImport:
    """B2 回归（T-0070）：`_build_intraday_plan` 必须导入并使用 classify。

    2026-09-29 起生产逐字日志：`name 'classify' is not defined` → 当日周期复核
    腿恒失败、回退「T-1 定版+恶化腿」（09:26 竞价时点当日判定恒为降级，回退
    结果与设计预期等效、影响≈0，但 source/reasons 失真，缺陷本身须修复）。
    """

    def _settings(self, tmp_path):
        from quant_system.config import Settings

        s = Settings.__new__(Settings)
        s.data_dir = tmp_path
        return s

    def test_build_plan_calls_classify_for_today(self, tmp_path, monkeypatch):
        from quant_system import config_registry, portfolio, scheduler as sched, strategy
        from quant_system import cycle, store

        monkeypatch.setattr(sched, "prev_trading_day", lambda settings, today: "2026-09-29")
        monkeypatch.setattr(cycle, "prev_finalized", lambda settings, date: None)
        sentinel = object()
        seen: dict = {}
        monkeypatch.setattr(cycle, "compute_indicators", lambda settings, date=None: sentinel)

        class _J:
            data_degraded = True

        def _classify(ind):
            seen["ind"] = ind
            return _J()

        monkeypatch.setattr(cycle, "classify", _classify)
        monkeypatch.setattr(
            cycle, "combined_gate_state",
            lambda settings, today, pf_state, pf_hot, j_today: (None, False, [], False),
        )
        monkeypatch.setattr(strategy, "with_phase", lambda **kw: [])
        monkeypatch.setattr(config_registry, "load_active", lambda settings: {"version": 1})
        monkeypatch.setattr(portfolio, "apply_portfolio_limits", lambda items, settings: {})
        monkeypatch.setattr(store, "persist_report", lambda *a, **kw: None)

        plan = sched._build_intraday_plan(self._settings(tmp_path), "2026-09-30")

        # 修复前：classify 未导入 → NameError 被吞 → classify 从未被调用（断言红）
        assert seen.get("ind") is sentinel
        assert plan["immediate"] == []


class TestDeteriorationRecheckDecoupled:
    """B1 回归（T-0070）：恶化复检与 todo 解耦。

    2026-09-30 实证：09:42 E 类触发致 todo 清空后，复检在 `if not todo: return`
    早退处永久停摆至 10:00；若 10:00 前恶化，halt 通知不再推送。修复后复检块
    先于早退执行（todo 已空时 halted 为空列表，仍落盘+通知+落状态）。
    """

    def _settings(self, tmp_path):
        from quant_system.config import Settings

        s = Settings.__new__(Settings)
        s.data_dir = tmp_path
        return s

    def _write_plan(self, tmp_path, today, triggered_codes):
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        plan = {
            "lianban": [
                {"strategy": "连板捉妖", "strategy_id": "lianban", "thscode": c,
                 "name": c, "scene": "B", "detail": ""}
                for c in triggered_codes
            ],
            "dragon": [],
            "immediate": [],
            "cycle_factors": {},
        }
        (state_dir / f"intraday-plan-{today}.json").write_text(
            json.dumps(plan, ensure_ascii=False)
        )

    def test_recheck_runs_when_todo_empty(self, tmp_path, monkeypatch):
        """todo 已清空（全部已触发/过期）→ 复检仍按 5 分钟间隔执行并落时间戳。"""
        from quant_system import cycle, scheduler as sched

        today = "2026-09-30"
        self._write_plan(tmp_path, today, ["600001.SH"])
        st = {"deterioration_last": None, "intraday_triggered": ["600001.SH"], "intraday_expired": []}
        called: dict = {}

        def _chk(settings, date=None):
            called["hit"] = True
            return cycle.DeteriorationCheck()

        monkeypatch.setattr(cycle, "compute_deterioration", _chk)

        sched.task_intraday(self._settings(tmp_path), today, st)

        # 修复前：todo 为空 → 早退、复检从不执行（断言红）
        assert "hit" in called
        assert st["deterioration_last"] is not None

    def test_halt_still_notified_when_todo_empty(self, tmp_path, monkeypatch):
        """todo 已清空且恶化触发 → 仍落盘 intraday_halt + 通知 + 状态写回。"""
        from quant_system import cycle, notify as notify_mod, scheduler as sched, store

        today = "2026-09-30"
        self._write_plan(tmp_path, today, ["600001.SH"])
        st = {"deterioration_last": None, "intraday_triggered": ["600001.SH"], "intraday_expired": []}
        monkeypatch.setattr(
            cycle, "compute_deterioration",
            lambda settings, date=None: cycle.DeteriorationCheck(
                triggered=True, reasons=["测试触发"]
            ),
        )
        persisted: list = []
        notified: list = []
        monkeypatch.setattr(
            store, "persist_report",
            lambda settings, d, kind, payload: persisted.append((kind, payload)),
        )
        monkeypatch.setattr(
            notify_mod, "notify", lambda text, title="": notified.append((title, text))
        )

        sched.task_intraday(self._settings(tmp_path), today, st)

        assert st.get("deterioration_fired") is True
        assert [k for k, _ in persisted] == ["intraday_halt"]
        assert persisted[0][1]["halted"] == []
        assert notified and "盘中恶化" in notified[0][1]
        assert sched.load_state(self._settings(tmp_path), today)["deterioration_fired"] is True
