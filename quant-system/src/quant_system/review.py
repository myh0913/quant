"""复盘打分（M4）：T 日盘后，对上一交易日的建议做表现核算。

数据源：
- data/advice/<X>/ 下的建议（X = 上一交易日）：
  1) auction_grab_*.json 的 advices（策略一，参考价=9:25 撮合价）
  2) intraday_*.json：场景 A/D 即时建议 + 盘中触发条目（有 result.trigger_price/
     confirm_price 用作入场价，否则以 X 日开盘价近似并标注）
- 行情：standard_daily_bars（X 与 T 两根日 K，经 resolve，自动落快照）

产出 data/advice/<T>/review_*.json（type=review，随 WS 推送前端）：
- items：逐条 {thscode, name, strategy, scene, entry, entry_note,
  day0_close_pct, next_close_pct, next_high_pct, next_low_pct, win, config_version}
- by_strategy：{策略: {count, fillable, wins, win_rate, avg_next_high_pct}}
  （count=全部条数，fillable=可成交数；胜率分母=fillable，买不进不稀释）
- config_version 取建议落盘时的版本（历史文件无版本记 0）

口径说明（保守近似）：
- 主指标 next_high_pct = (T日最高 - 入场价)/入场价 —— 次日冲高可卖出的盈亏
  （短线视角：开盘冲高即可离场，比收盘价更贴近实际可得的卖点）
- win = next_high_pct > 0；策略一参考价为 X 日 9:25 撮合价；
  若竞价已涨停（chg_925≥9.8%）标记 unfillable（实际可能买不进），
  该条计入 items 但不计入胜负统计
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .datasource.resolve import data_session, standard_daily_bars
from .store import persist_report
from .timeutil import date_ms

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger(__name__)

# 场景 A/D = 即时建议；盘中触发条目含 result
_IMMEDIATE_SCENES = {"A", "D"}

# 场景→策略兜底（与前端 entryStrategy 同一规则：A/B/C=连板捉妖，D/E/F=龙回头）。
# 旧版调度器落的盘中文件无 strategy 字段，聚合时按场景推断，避免出现"未知"桶
_SCENE_STRATEGY = {"A": "连板捉妖", "B": "连板捉妖", "C": "连板捉妖",
                   "D": "龙回头", "E": "龙回头", "F": "龙回头"}


def collect_advices(settings: "Settings", advice_date: str) -> list[dict]:
    """收集某日全部可操作建议（策略一 advices + 即时场景 + 盘中触发）。"""
    d: Path = settings.data_dir / "advice" / advice_date
    if not d.exists():
        return []
    items: list[dict] = []
    for p in sorted(d.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        cfg_ver = doc.get("config_version", 0)

        # ① 策略一报告的 advices
        if isinstance(doc.get("advices"), list):
            for a in doc["advices"]:
                if isinstance(a, dict) and a.get("thscode"):
                    items.append({
                        "thscode": a["thscode"], "name": a.get("name", ""),
                        "strategy": a.get("strategy", ""),
                        "scene": (a.get("factor_summary") or {}).get("scene"),
                        "reference_price": a.get("reference_price"),
                        "chg_925_pct": (a.get("factor_summary") or {}).get("chg_925_pct"),
                        "config_version": cfg_ver,
                    })

        # ② 盘中即时建议（intraday_<策略名>）与触发条目（intraday_<code>）
        name = p.stem
        if name.startswith("intraday_") and not name.startswith("intraday_plan"):
            scene = doc.get("scene")
            has_result = isinstance(doc.get("result"), dict)
            if scene in _IMMEDIATE_SCENES or has_result:
                if doc.get("thscode"):
                    r = doc.get("result") or {}
                    items.append({
                        "thscode": doc["thscode"], "name": doc.get("name", ""),
                        "strategy": doc.get("strategy") or _SCENE_STRATEGY.get(scene, ""),
                        "scene": scene,
                        "reference_price": r.get("trigger_price") or r.get("confirm_price"),
                        "chg_925_pct": None,
                        "config_version": doc.get("config_version", cfg_ver),
                    })
    return items


def _bar_map(bars: list[dict]) -> dict[str, dict]:
    """hithink 日 K 列表 → {YYYY-MM-DD: bar}。"""
    import datetime as _dt

    out: dict[str, dict] = {}
    for b in bars:
        ms = b.get("date_ms")
        if not ms:
            continue
        d = _dt.datetime.fromtimestamp(
            int(ms) / 1000, tz=_dt.timezone(_dt.timedelta(hours=8))
        ).strftime("%Y-%m-%d")
        out[d] = b
    return out


def _pct(cur: float, base: float) -> float | None:
    return (cur - base) / base if base else None


def run_review(settings: "Settings", today: str, prev: str | None = None) -> dict:
    """对 prev（缺省=上一交易日）的建议做次日表现核算，落盘并返回报告。"""
    if prev is None:
        from .scheduler import prev_trading_day

        prev = prev_trading_day(settings, today)

    advices = collect_advices(settings, prev)
    items: list[dict] = []
    with data_session(settings):
        for adv in advices:
            code = adv["thscode"]
            it = {**adv, "entry": None, "entry_note": "", "win": None,
                  "day0_close_pct": None, "next_close_pct": None,
                  "next_high_pct": None, "next_low_pct": None, "unfillable": False}
            try:
                # 回看窗按 T-X 实际自然日差扩：lookback=2 的自然日窗仅 ~3 天，
                # 跨周末（3 天）刚好擦边，跨国庆/春节（8+ 天）会取不到 X 日K，
                # 导致整日复盘条目"日K缺失"
                span = (datetime.strptime(today, "%Y-%m-%d")
                        - datetime.strptime(prev, "%Y-%m-%d")).days
                bars = standard_daily_bars(
                    settings, code, today, lookback_days=max(2, span + 1))
                bm = _bar_map(bars)
                bx, bt = bm.get(prev), bm.get(today)
                if not bx or not bt:
                    it["entry_note"] = f"日K缺失（{'X' if not bx else ''}{'T' if not bt else ''}）"
                    items.append(it)
                    continue
                entry = adv.get("reference_price") or float(bx.get("open_price") or 0)
                it["entry"] = entry
                if not adv.get("reference_price"):
                    it["entry_note"] = "无参考价，以当日开盘价近似"
                chg925 = adv.get("chg_925_pct")
                if chg925 is not None and chg925 >= 9.8:
                    it["unfillable"] = True
                    it["entry_note"] = "竞价已涨停，实际可能无法成交"
                it["day0_close_pct"] = _pct(float(bx.get("close_price") or 0), entry)
                it["next_close_pct"] = _pct(float(bt.get("close_price") or 0), entry)
                it["next_high_pct"] = _pct(float(bt.get("high_price") or 0), entry)
                it["next_low_pct"] = _pct(float(bt.get("low_price") or 0), entry)
                if not it["unfillable"]:
                    # 双口径胜负（2026-09-17）：冲高（乐观，次日最高）+ 收盘（保守，次日收盘）
                    if it["next_high_pct"] is not None:
                        it["win"] = it["next_high_pct"] > 0
                    if it["next_close_pct"] is not None:
                        it["win_close"] = it["next_close_pct"] > 0
            except Exception as exc:  # noqa: BLE001
                it["entry_note"] = f"行情获取失败: {exc}"[:120]
            items.append(it)

    # 聚合（可成交条目才计入胜负；胜率分母=可成交数，买不进不稀释胜率）
    # 双口径：win_rate=次日冲高口径（乐观），win_rate_close=次日收盘口径（保守）
    by_strategy: dict[str, dict] = {}
    for it in items:
        key = it.get("strategy") or "未知"
        agg = by_strategy.setdefault(key, {"count": 0, "fillable": 0, "wins": 0,
                                           "wins_close": 0, "pcts": [], "pcts_close": []})
        agg["count"] += 1
        if it.get("win") is True:
            agg["wins"] += 1
        if it.get("win_close") is True:
            agg["wins_close"] += 1
        if it["next_high_pct"] is not None and not it["unfillable"]:
            agg["fillable"] += 1
            agg["pcts"].append(it["next_high_pct"])
            agg["pcts_close"].append(it["next_close_pct"])
    for key, agg in by_strategy.items():
        scored = agg.pop("pcts")
        scored_close = agg.pop("pcts_close")
        agg["win_rate"] = round(agg["wins"] / agg["fillable"], 4) if agg["fillable"] else None
        agg["win_rate_close"] = round(agg["wins_close"] / agg["fillable"], 4) if agg["fillable"] else None
        agg["avg_next_high_pct"] = round(sum(scored) / len(scored), 6) if scored else None
        agg["avg_next_close_pct"] = (
            round(sum(scored_close) / len(scored_close), 6)
            if scored_close and any(p is not None for p in scored_close) else None
        )

    report = {
        "type": "review", "date": today, "advice_date": prev,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "items": items, "by_strategy": by_strategy,
        "total": len(items),
    }
    persist_report(settings, today, "review", report)
    log.info("复盘完成：%s 建议 %d 条（来源 %s）", prev, len(items), list(by_strategy))
    return report


def summary_line(report: dict) -> str:
    """盘后推送摘要一行（双口径胜率：冲高/收盘）。"""
    parts = []
    for strat, agg in report.get("by_strategy", {}).items():
        wr = f"{agg['win_rate']*100:.0f}%" if agg.get("win_rate") is not None else "-"
        wrc = f"{agg['win_rate_close']*100:.0f}%" if agg.get("win_rate_close") is not None else "-"
        parts.append(f"{strat} {agg['count']}条 胜率{wr}/{wrc}(收)")
    return f"复盘({report.get('advice_date')}建议)：{report.get('total', 0)}条 " + "；".join(parts)
