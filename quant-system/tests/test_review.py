"""复盘打分测试——无网络（日线走快照）。"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from quant_system.config import Settings
from quant_system.review import collect_advices, run_review, summary_line
from quant_system.snapshot import replay_scope, save
from quant_system.timeutil import date_ms

X = "2026-09-10"   # 建议日
T = "2026-09-11"   # 核算日
CODE = "600001.SH"


def make_settings(tmp_path) -> Settings:
    s = Settings.__new__(Settings)
    s.data_dir = tmp_path
    s.raw_dir = tmp_path / "raw"
    return s


def seed_advice_files(s: Settings):
    d = s.data_dir / "advice" / X
    d.mkdir(parents=True)
    # 策略一报告（1 条可成交 + 1 条竞价涨停不可成交）
    (d / "auction_grab_092500.json").write_text(json.dumps({
        "type": "auction_grab", "date": X, "config_version": 7,
        "advices": [
            {"thscode": CODE, "name": "示例股份", "strategy": "竞价主力抢筹",
             "reference_price": 10.15, "factor_summary": {"chg_925_pct": 1.5}},
            {"thscode": "600002.SH", "name": "涨停股份", "strategy": "竞价主力抢筹",
             "reference_price": 11.0, "factor_summary": {"chg_925_pct": 9.9}},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    # 盘中触发条目（无参考价 → 触发价）
    (d / "intraday_600001_093700.json").write_text(json.dumps({
        "strategy": "连板捉妖", "thscode": CODE, "name": "示例股份", "scene": "B",
        "config_version": 7, "result": {"trigger_price": 9.95},
    }, ensure_ascii=False), encoding="utf-8")
    # 应被忽略：intraday_plan 与无 scene 的池子文件
    (d / "intraday_plan_092600.json").write_text(json.dumps(
        {"type": "intraday_plan", "pending": [], "immediate": []}), encoding="utf-8")
    (d / "lianban_pool_170000.json").write_text(json.dumps(
        {"type": "lianban_pool", "candidates": [], "rejected": []}), encoding="utf-8")


def seed_bars_snapshot(s: Settings):
    """铺 T 日快照：daily_bars(end=T, lookback=2) 覆盖 X/T 两根。"""
    start = (_dt.datetime.strptime(T, "%Y-%m-%d") - _dt.timedelta(days=3)).strftime("%Y-%m-%d")
    bars = {
        CODE: [
            {"date_ms": date_ms(X), "open_price": 10.0, "high_price": 10.3, "low_price": 9.9,
             "close_price": 10.2, "volume": 1000},
            # T 日收盘 10.05 < 入场 10.15（收盘口径亏），最高 10.8 > 入场（冲高口径赢）
            {"date_ms": date_ms(T), "open_price": 10.25, "high_price": 10.8, "low_price": 10.0,
             "close_price": 10.05, "volume": 1200},
        ],
        "600002.SH": [
            {"date_ms": date_ms(X), "open_price": 11.0, "high_price": 11.0, "low_price": 11.0,
             "close_price": 11.0, "volume": 10},
            {"date_ms": date_ms(T), "open_price": 11.5, "high_price": 12.1, "low_price": 11.4,
             "close_price": 12.1, "volume": 20},
        ],
    }
    for code, rows in bars.items():
        save(s, T, "daily_bars", {"thscode": code, "start": start, "end": T, "lookback": 2}, rows)


class TestCollect:
    def test_collects_actionable_only(self, tmp_path):
        s = make_settings(tmp_path)
        seed_advice_files(s)
        items = collect_advices(s, X)
        # 策略一 2 条 + 盘中触发 1 条（同一代码出现两次属正常：不同策略/时点）
        assert len(items) == 3
        assert all(it["config_version"] == 7 for it in items)
        assert {it["strategy"] for it in items} == {"竞价主力抢筹", "连板捉妖"}

    def test_strategy_fallback_by_scene(self, tmp_path):
        """旧版盘中文件无 strategy 字段 → 按场景兜底推断（A/B/C=连板，D/E/F=龙回头）。"""
        s = make_settings(tmp_path)
        d = s.data_dir / "advice" / X
        d.mkdir(parents=True)
        for scene in ("B", "E"):
            (d / f"intraday_60000{scene}_093000.json").write_text(json.dumps({
                "thscode": f"60000{scene}.SH", "name": f"旧文件{scene}", "scene": scene,
                "result": {"trigger_price": 10.0},  # 无 strategy 字段（旧调度器产物）
            }, ensure_ascii=False), encoding="utf-8")
        items = collect_advices(s, X)
        by_scene = {it["scene"]: it for it in items}
        assert by_scene["B"]["strategy"] == "连板捉妖"
        assert by_scene["E"]["strategy"] == "龙回头"

    def test_empty_day(self, tmp_path):
        s = make_settings(tmp_path)
        assert collect_advices(s, X) == []


class TestRunReview:
    def test_scores_and_aggregates(self, tmp_path):
        s = make_settings(tmp_path)
        seed_advice_files(s)
        seed_bars_snapshot(s)

        with replay_scope(s, T):  # 行情走快照，无网络
            rep = run_review(s, T, prev=X)

        assert rep["advice_date"] == X and rep["total"] == 3
        by = {it["thscode"]: it for it in rep["items"]}

        a1 = next(i for i in rep["items"] if i["strategy"] == "竞价主力抢筹" and i["thscode"] == CODE)
        assert a1["entry"] == 10.15
        assert a1["day0_close_pct"] is not None and abs(a1["day0_close_pct"] - (10.2 - 10.15) / 10.15) < 1e-9
        # 主指标=次日最高：收盘亏（10.05）但冲高赢（10.8）→ win=True
        assert a1["next_close_pct"] < 0 and a1["win"] is True
        assert abs(a1["next_high_pct"] - (10.8 - 10.15) / 10.15) < 1e-9
        assert a1["unfillable"] is False

        a2 = by["600002.SH"]
        assert a2["unfillable"] is True and a2["win"] is None  # 竞价涨停不计胜负

        trig = next(i for i in rep["items"] if i["strategy"] == "连板捉妖")
        assert trig["entry"] == 9.95  # result.trigger_price 作为入场价

        agg = rep["by_strategy"]["竞价主力抢筹"]
        assert agg["count"] == 2 and agg["fillable"] == 1  # 600002 买不进不计可成交
        assert agg["wins"] == 1 and agg["win_rate"] == 1.0  # 胜率分母=可成交数
        # 均冲高只含可成交条目（600002 unfillable 不计入）
        assert abs(agg["avg_next_high_pct"] - (10.8 - 10.15) / 10.15) < 1e-6

        # 报告落盘（advice 目录 → WS 推送）
        files = list((s.data_dir / "advice" / T).glob("review_*.json"))
        assert files and json.loads(files[-1].read_text())["type"] == "review"

    def test_missing_bars_degrade(self, tmp_path):
        s = make_settings(tmp_path)
        seed_advice_files(s)
        with replay_scope(s, T):  # 无 daily_bars 快照 → 逐条降级，不炸
            rep = run_review(s, T, prev=X)
        assert rep["total"] == 3
        assert all(it["next_close_pct"] is None for it in rep["items"])
        assert "复盘" in summary_line(rep)

    def test_long_holiday_span(self, tmp_path):
        """跨国庆：T-X 自然日差 9 天，回看窗按 span 扩，X 日K 不缺失。

        回归：旧实现固定 lookback=2（自然日窗 ~3 天），跨长假时 X 日K
        取不到 → 全部条目"日K缺失"（节假日复盘整日报废）。
        """
        x, t = "2026-09-30", "2026-10-09"  # 节前最后交易日 → 节后首个交易日
        s = make_settings(tmp_path)
        d = s.data_dir / "advice" / x
        d.mkdir(parents=True)
        (d / "auction_grab_092500.json").write_text(json.dumps({
            "date": x,
            "advices": [
                {"thscode": CODE, "name": "节前股份", "strategy": "竞价主力抢筹",
                 "reference_price": 10.0, "factor_summary": {"chg_925_pct": 1.0}},
            ],
        }, ensure_ascii=False), encoding="utf-8")

        # 铺快照：run_review 会按 span+1=10 请求 → start = t - int(10*1.7)=17 天
        lookback = (_dt.datetime.strptime(t, "%Y-%m-%d")
                    - _dt.datetime.strptime(x, "%Y-%m-%d")).days + 1
        start = (_dt.datetime.strptime(t, "%Y-%m-%d")
                 - _dt.timedelta(days=int(lookback * 1.7))).strftime("%Y-%m-%d")
        save(s, t, "daily_bars",
             {"thscode": CODE, "start": start, "end": t, "lookback": lookback}, [
                 {"date_ms": date_ms(x), "open_price": 10.0, "high_price": 10.2,
                  "low_price": 9.9, "close_price": 10.1, "volume": 100},
                 {"date_ms": date_ms(t), "open_price": 10.2, "high_price": 10.6,
                  "low_price": 10.0, "close_price": 10.5, "volume": 120},
             ])

        with replay_scope(s, t):
            rep = run_review(s, t, prev=x)

        it = rep["items"][0]
        assert it["entry"] == 10.0
        assert it["day0_close_pct"] is not None  # 旧实现此处为 None（X 日K 取不到）
        assert it["next_close_pct"] is not None and it["win"] is True
