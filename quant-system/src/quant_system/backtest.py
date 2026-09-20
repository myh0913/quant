"""回测引擎（M2，2026-09-18）：日期驱动批量验证策略规则与参数。

用法：
    python -m quant_system.backtest --start 2026-09-01 --end 2026-09-16 \
        [--strategies lianban,dragon,tailpan] [--params JSON] [--force-fetch]

设计（对齐 docs/EVOLUTION_DESIGN.md M2）：
- 每个交易日 T 用"日模拟引擎"完整复刻调度器当日流程：
  周期门控(当日指标) → T-1 建池 → 竞价场景 → 盘中确认（分钟分时）
- 双模式：
  * fetch 模式：live 取数并经 save_date_scope 强制把快照落 data/std/T/
    （顺带完成回填，之后同参数回测走 replay 零 API）；
  * replay 模式：只读 T 快照；缺失自动降级 fetch 补齐后重跑该日。
- 全部经 resolve 能力层 → 快照 key 天然一致，无未来数据
  （replay 模式绝不现场拉数；fetch 模式拉的也是 T 当日历史数据）。
- 产出 data/backtest/<run_id>/{status.json, report.json}，stdout 单 JSON（backend 契约）。

已知局限（诚实呈现，不假装）：
- 竞价主力抢筹不参与（eltdx 竞价排行无历史接口）；
- 监管名单(monitor_stocks)无历史快照 → 尾盘风控用当前名单近似/盘中路径本就无此检查；
- 事件回测不含滑点/排队成交；竞价已涨停按 unfillable 剔除（同复盘口径）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config_registry
from .config import Settings
from .snapshot import SnapshotMissing, replay_scope, save_date_scope

log = logging.getLogger("backtest")

BACKTEST_STRATEGIES = ("lianban", "dragon", "tailpan")  # auction_grab 无历史数据源


# ============================== 日模拟引擎 ==============================


def _cycle_gate(settings: Settings, today: str, label: str) -> tuple[bool, float, str, str]:
    """当日周期门控；失败放行待复核（对齐调度器口径）。"""
    from .cycle import classify, compute_indicators, strategy_gate

    try:
        j = classify(compute_indicators(settings, today))
        ok, factor, note = strategy_gate(j.state, label, j.overheated)
        return ok, factor, note, j.state.value
    except Exception as exc:  # noqa: BLE001
        return True, 1.0, f"周期计算失败（{exc}）放行待复核", "unknown"


def _simulate_lianban_dragon(settings: Settings, sid: str, prev: str, cur: str) -> dict:
    """连板/龙回头日模拟：门控 → T-1 池 → 场景 → 盘中确认（不落盘/不通知）。

    对齐 scheduler._build_intraday_plan + task_intraday 的生产路径。
    """
    from .datasource.resolve import standard_minute_points
    from .strategy import SCENE_IMMEDIATE, get_strategy

    s = get_strategy(sid)
    ok, factor, note, gate_state = _cycle_gate(settings, cur, s.label)
    day: dict = {
        "strategy": sid, "label": s.label, "gate_ok": ok, "gate_state": gate_state,
        "gate_note": note, "gate_factor": factor, "entries": [], "pool_passed": 0,
    }
    if not ok:
        return day

    passed, _rejected = s.build_pool(settings, prev)
    day["pool_passed"] = len(passed)
    scenes = s.classify_scenes(passed, settings, cur)
    params = config_registry.get_params(settings, sid)
    from .portfolio import apply_portfolio_limits, position_display  # noqa: F401（apply 在场景循环后统一执行）

    base_pct = float(params["base_position_pct"])
    pos_pct, _text = position_display(base_pct, factor)

    for sc in scenes:
        kind = s.scene_kind(sc.scene)
        if kind != SCENE_IMMEDIATE:
            pts = standard_minute_points(settings, sc.thscode, cur)
            r = s.confirm_intraday(pts, {"scene": sc.scene, "thscode": sc.thscode}, params)
            if not r.triggered:
                continue
            price = (r.data or {}).get("trigger_price") or (r.data or {}).get("confirm_price")
            day["entries"].append({
                "thscode": sc.thscode, "name": sc.name, "scene": sc.scene,
                "kind": "triggered", "entry_price": price,
                "detail": r.detail, "position_pct": pos_pct, "gate_state": gate_state,
            })
        else:
            day["entries"].append({
                "thscode": sc.thscode, "name": sc.name, "scene": sc.scene,
                "kind": "immediate", "entry_price": None,  # 无触发价，核算时以 T 日开盘价近似
                "detail": sc.detail, "position_pct": pos_pct, "gate_state": gate_state,
            })
    # 组合风控（对齐生产路径：单票去重 + 总仓位上限，先到先得）
    from .portfolio import apply_portfolio_limits

    apply_portfolio_limits(day["entries"], settings)
    return day


def _simulate_tailpan(settings: Settings, prev: str, cur: str) -> dict:
    from .strategy.tailpan import select_tailpan

    rep = select_tailpan(settings, cur, prev)
    day: dict = {
        "strategy": "tailpan", "label": "龙回头·尾盘", "gate_ok": rep["gate_ok"],
        "gate_state": rep["gate_state"], "gate_note": rep["gate_note"],
        "gate_factor": rep["gate_factor"], "entries": [], "pool_passed": len(rep["candidates"]),
    }
    for c in rep["candidates"]:
        day["entries"].append({
            "thscode": c["thscode"], "name": c["name"], "scene": "尾盘",
            "kind": "tailpan", "entry_price": c.get("last_price"),
            "detail": "；".join(c.get("notes") or []),
            "position_pct": c.get("position_pct"), "demoted": c.get("demoted"),
            "portfolio_note": c.get("portfolio_note", ""), "gate_state": rep["gate_state"],
        })
    return day


def simulate_day(settings: Settings, sid: str, prev: str, cur: str, *, fetch: bool) -> dict:
    """单日单策略模拟。fetch=True：live 取数+快照落 T；否则 replay 只读 T 快照。"""
    if fetch:
        with save_date_scope(cur):
            return _simulate_lianban_dragon(settings, sid, prev, cur) \
                if sid in ("lianban", "dragon") else _simulate_tailpan(settings, prev, cur)
    with replay_scope(settings, cur):
        return _simulate_lianban_dragon(settings, sid, prev, cur) \
            if sid in ("lianban", "dragon") else _simulate_tailpan(settings, prev, cur)


# ============================== 表现核算 ==============================


def _bar_map(settings: Settings, codes: list[str], end: str) -> dict[str, dict[str, dict]]:
    """批量取日线 → {thscode: {date: bar}}（live 历史接口，核算用）。"""
    from .datasource.resolve import data_session, standard_daily_bars

    out: dict[str, dict[str, dict]] = {}
    with data_session(settings):
        for code in codes:
            try:
                bars = standard_daily_bars(settings, code, end, lookback_days=90)
            except Exception as exc:  # noqa: BLE001
                log.warning("核算日线获取失败 %s: %s", code, exc)
                continue
            import datetime as _dt

            m = {}
            for b in bars:
                d = _dt.datetime.fromtimestamp(
                    int(b.get("date_ms", 0)) / 1000,
                    tz=_dt.timezone(_dt.timedelta(hours=8)),
                ).strftime("%Y-%m-%d")
                m[d] = b
            out[code] = m
    return out


def evaluate_performance(settings: Settings, entries: list[dict], end_date: str) -> None:
    """为每条 entry 就地补 T/T+1 表现字段（口径对齐 review.py 双口径）。

    即时场景无触发价 → 以 T 日开盘价近似（同复盘）；T 日开盘已涨停（主板口径
    open ≥ pre_close×1.098）→ unfillable 不计胜负（买不进）。
    """
    codes = sorted({e["thscode"] for e in entries})
    bars = _bar_map(settings, codes, end=end_date)

    for e in entries:
        e.setdefault("day0_close_pct", None)
        e.setdefault("next_close_pct", None)
        e.setdefault("next_high_pct", None)
        e.setdefault("next_low_pct", None)
        e.setdefault("win", None)
        e.setdefault("win_close", None)
        e.setdefault("unfillable", False)
        m = bars.get(e["thscode"])
        if not m:
            e["entry_note"] = "日K缺失"
            continue
        b0, b1 = m.get(e["date"]), m.get(e["next_date"])
        if not b1:
            e["entry_note"] = "T+1 日K缺失（区间末日或停牌）" if b0 else "日K缺失"
            if not b0:
                continue
        if not b0:
            e["entry_note"] = "T 日K缺失"
            continue
        entry = e.get("entry_price")
        if not entry:
            entry = float(b0.get("open_price") or 0)
            e["entry_price"] = entry
            e["entry_note"] = "即时场景无触发价，以 T 日开盘价近似"
        # T 日开盘即涨停（近似主板口径）→ 实际可能买不进
        dates = sorted(m)
        i0 = dates.index(e["date"])
        if i0 > 0:
            pre = float(m[dates[i0 - 1]].get("close_price") or 0)
            o0 = float(b0.get("open_price") or 0)
            if pre > 0 and (o0 - pre) / pre >= 0.098:
                e["unfillable"] = True
                e["entry_note"] = (e.get("entry_note", "") + "；T 日开盘已涨停，实际可能无法成交").strip("；")

        def _pct(a: float | None, b: float | None) -> float | None:
            return (a - b) / b if (a and b) else None

        e["day0_close_pct"] = _pct(float(b0.get("close_price") or 0), entry)
        if b1:
            e["next_close_pct"] = _pct(float(b1.get("close_price") or 0), entry)
            e["next_high_pct"] = _pct(float(b1.get("high_price") or 0), entry)
            e["next_low_pct"] = _pct(float(b1.get("low_price") or 0), entry)
        if e["next_high_pct"] is not None:
            e["win"] = e["next_high_pct"] > 0
        if e["next_close_pct"] is not None:
            e["win_close"] = e["next_close_pct"] > 0


def aggregate(entries: list[dict]) -> dict:
    """聚合（策略 × 口径），unfillable/demoted 不计胜负。"""
    def _agg(rows: list[dict]) -> dict:
        fillable = [r for r in rows if r.get("win") is not None and not r.get("unfillable")]
        return {
            "count": len(rows),
            "fillable": len(fillable),
            "win_rate": round(sum(1 for r in fillable if r["win"]) / len(fillable), 4) if fillable else None,
            "win_rate_close": round(sum(1 for r in fillable if r.get("win_close")) / len(fillable), 4) if fillable else None,
            "avg_next_high_pct": round(sum(r["next_high_pct"] for r in fillable) / len(fillable), 6) if fillable else None,
        }

    out: dict[str, dict] = {"overall": _agg(entries)}
    for sid in sorted({e["strategy"] for e in entries}):
        out[sid] = _agg([e for e in entries if e["strategy"] == sid])
    # 分周期状态（验证门控有效性）
    for state in sorted({str(e.get("gate_state")) for e in entries if e.get("gate_state")}):
        out[f"cycle:{state}"] = _agg([e for e in entries if e.get("gate_state") == state])
    return out


# ============================== 运行器 ==============================


def _trading_days(settings: Settings, start: str, end: str) -> list[str]:
    from .scheduler import _fetch_calendar

    cal = _fetch_calendar(settings, need=end)
    return sorted(d for d in cal if start <= d <= end)


def run_backtest(settings: Settings, start: str, end: str, sids: list[str],
                 params: dict | None = None, force_fetch: bool = False,
                 out_dir: Path | None = None, throttle: float = 0.0) -> dict:
    """主入口：逐日模拟 → 表现核算 → 聚合 → 落 status/report。"""
    from .scheduler import prev_trading_day

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = out_dir or (settings.data_dir / "backtest" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "status.json"

    def _status(**kw) -> None:
        status_path.write_text(json.dumps(
            {"run_id": run_id, "start": start, "end": end, "strategies": sids,
             **kw}, ensure_ascii=False), encoding="utf-8")

    days = _trading_days(settings, start, end)
    _status(status="running", progress={"done": 0, "total": len(days)}, started_at=datetime.now(timezone.utc).isoformat())

    all_entries: list[dict] = []
    day_notes: list[dict] = []
    with config_registry.temporary_overrides(params or {}):
        for i, d in enumerate(days):
            prev = prev_trading_day(settings, d)
            nxt = days[i + 1] if i + 1 < len(days) else ""
            for sid in sids:
                try:
                    if force_fetch:
                        day = simulate_day(settings, sid, prev, d, fetch=True)
                    else:
                        try:
                            day = simulate_day(settings, sid, prev, d, fetch=False)
                        except SnapshotMissing:
                            day = None  # 快照不足 → fetch 补齐
                    if day is None:
                        time.sleep(throttle)
                        day = simulate_day(settings, sid, prev, d, fetch=True)
                except Exception as exc:  # noqa: BLE001
                    log.exception("回测日 %s %s 失败", d, sid)
                    day_notes.append({"date": d, "strategy": sid, "error": f"{type(exc).__name__}: {exc}"[:200]})
                    _status(status="running", progress={"done": i + 1, "total": len(days), "current": d})
                    continue
                for e in day["entries"]:
                    e["strategy"] = day["strategy"]  # day 级字段下放到 entry（aggregate 用）
                    e["date"] = d
                    e["next_date"] = nxt
                    e["config_version"] = int(config_registry.load_active(settings).get("version") or 0)
                all_entries.extend(day["entries"])
                day_notes.append({"date": d, "strategy": sid,
                                  "gate": day["gate_state"], "entries": len(day["entries"])})
            _status(status="running", progress={"done": i + 1, "total": len(days), "current": d})
            if throttle:
                time.sleep(throttle)

    evaluate_performance(settings, all_entries, end_date=days[-1] if days else end)

    report = {
        "type": "backtest", "run_id": run_id,
        "start": start, "end": end, "strategies": sids,
        "params": params or {},
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "trading_days": len(days),
        "aggregate": aggregate(all_entries),
        "entries": all_entries,
        "days": day_notes,
        "limitations": [
            "竞价主力抢筹无历史竞价排行数据，未参与回测",
            "监管名单无历史快照，尾盘风控按当前名单近似",
            "事件回测不含滑点/排队成交；竞价涨停 unfillable 已剔除",
        ],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _status(status="done", progress={"done": len(days), "total": len(days)},
            finished_at=datetime.now(timezone.utc).isoformat(), entries=len(all_entries))
    return report


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="quant_system.backtest", description="日期驱动批量回测")
    ap.add_argument("--start", required=True, help="开始交易日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="结束交易日 YYYY-MM-DD")
    ap.add_argument("--strategies", default=",".join(BACKTEST_STRATEGIES),
                    help=f"逗号分隔（可选: {BACKTEST_STRATEGIES}）")
    ap.add_argument("--params", default=None, help="参数覆盖 JSON：{strategy_id: {key: value}}")
    ap.add_argument("--force-fetch", action="store_true", help="忽略已有快照，全部重新取数回填")
    ap.add_argument("--throttle", type=float, default=0.0, help="fetch 日间限速秒数")
    args = ap.parse_args()

    sids = [s.strip() for s in args.strategies.split(",") if s.strip()]
    bad = set(sids) - set(BACKTEST_STRATEGIES)
    if bad:
        print(json.dumps({"error": f"不可回测的策略: {sorted(bad)}（可选: {BACKTEST_STRATEGIES}）"}, ensure_ascii=False))
        return 2
    params = json.loads(args.params) if args.params else None

    settings = Settings()
    settings.ensure_dirs()
    try:
        report = run_backtest(settings, args.start, args.end, sids, params,
                              force_fetch=args.force_fetch, throttle=args.throttle)
    except Exception as exc:  # noqa: BLE001
        log.exception("回测执行失败")
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}",
                          "traceback": traceback.format_exc(limit=8)}, ensure_ascii=False))
        return 1
    # stdout 单 JSON 契约（backend 解析）——报告本体过大，stdout 只给摘要
    print(json.dumps({
        "run_id": report["run_id"], "trading_days": report["trading_days"],
        "aggregate": report["aggregate"], "entries": len(report["entries"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
