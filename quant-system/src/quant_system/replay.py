"""回放 CLI（M3）：对历史快照重跑策略，分钟级验证参数改动。

用法：
    python -m quant_system.replay --date 2026-09-12                      # 全策略
    python -m quant_system.replay --date 2026-09-12 --strategy lianban
    python -m quant_system.replay --date 2026-09-12 \
        --params '{"auction_grab": {"min_rise": 0.03}}'                  # 参数对比

行为：
- 只读 data/std/<date>/ 快照，绝不现场拉数（防未来数据）；快照缺失 →
  对应阶段记 warning，不中断其他策略；
- 参数经 temporary_overrides 进程内注入（不触碰 active.json）；
- 结果落盘 data/replay/<date>/<strategy>_<HHMMSS>.json，并 stdout 输出单个 JSON
  （供 backend 子进程调用，同 sandbox 契约）。

注意：快照只覆盖系统 live 运行过（或沙箱测试过）的能力调用。例如当日只
监控了 5 只票的分时，回放换参数后新增的监控票会报 SnapshotMissing。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import config_registry
from .config import Settings
from .snapshot import SnapshotMissing, replay_scope
from .strategy import get_strategy, strategy_ids
from .store import persist_report

log = logging.getLogger("replay")


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


def _replay_auction(settings: Settings, sid: str, date: str) -> dict:
    s = get_strategy(sid)
    rep = s.run_auction_pipeline(settings, date=date, persist=False)
    return {
        "phase": "auction",
        "ok": True,
        "cycle_state": rep.cycle_state,
        "cycle_reasons": rep.cycle_reasons,
        "candidates": rep.candidates,
        "advices": [a.model_dump(mode="json") for a in rep.advices],
        "blocked": rep.blocked,
        "factors": [f.model_dump(mode="json") for f in rep.factors],
    }


def _replay_pool_and_intraday(settings: Settings, sid: str, date: str) -> dict:
    """盘后建池 + 竞价场景 + 盘中确认（对齐调度器当日全流程）。"""
    from .datasource.resolve import standard_minute_points
    from .strategy import SCENE_PENDING

    s = get_strategy(sid)
    passed, rejected = s.build_pool(settings, date)
    out = {
        "phase": "pool+intraday",
        "ok": True,
        "pool": {
            "passed": [c.model_dump(mode="json") for c in passed],
            "rejected": [c.model_dump(mode="json") for c in rejected],
            "pool_size": len(passed) + len(rejected),
        },
        "scenes": [],
        "intraday": {"triggered": [], "not_triggered": [], "missing": []},
    }

    scenes = s.classify_scenes(passed, settings, date)
    out["scenes"] = [sc.model_dump(mode="json") for sc in scenes]

    params = config_registry.get_params(settings, s.strategy_id)
    for sc in scenes:
        if s.scene_kind(sc.scene) != SCENE_PENDING:
            continue
        try:
            pts = standard_minute_points(settings, sc.thscode, date)
            r = s.confirm_intraday(pts, {"scene": sc.scene, "thscode": sc.thscode}, params)
        except SnapshotMissing as exc:
            out["intraday"]["missing"].append({"thscode": sc.thscode, "name": sc.name, "reason": str(exc)[:200]})
            continue
        row = {"thscode": sc.thscode, "name": sc.name, "scene": sc.scene,
               "triggered": r.triggered, "detail": r.detail, "result": r.data}
        out["intraday"]["triggered" if r.triggered else "not_triggered"].append(row)
    return out


def run_replay(settings: Settings, date: str, sids: list[str],
               params: dict[str, dict] | None = None) -> dict:
    """执行回放并返回汇总报告（不写 advice 目录；结果落 data/replay/）。"""
    t0 = time.perf_counter()
    results: dict[str, dict] = {}
    warnings: list[str] = []

    with config_registry.temporary_overrides(params or {}):
        with replay_scope(settings, date):
            for sid in sids:
                s = get_strategy(sid)
                entry: dict = {"label": s.label, "phases": {}}
                if s.has_auction_advice:
                    try:
                        entry["phases"]["auction"] = _replay_auction(settings, sid, date)
                    except SnapshotMissing as exc:
                        entry["phases"]["auction"] = {"ok": False, "error": str(exc)[:300]}
                        warnings.append(f"{s.label} 竞价阶段: 快照缺失")
                    except Exception as exc:  # noqa: BLE001
                        entry["phases"]["auction"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
                        warnings.append(f"{s.label} 竞价阶段失败: {exc}")
                if s.has_pool_phase:
                    try:
                        entry["phases"]["pool"] = _replay_pool_and_intraday(settings, sid, date)
                    except SnapshotMissing as exc:
                        entry["phases"]["pool"] = {"ok": False, "error": str(exc)[:300]}
                        warnings.append(f"{s.label} 建池阶段: 快照缺失")
                    except Exception as exc:  # noqa: BLE001
                        entry["phases"]["pool"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
                        warnings.append(f"{s.label} 建池阶段失败: {exc}")
                results[sid] = entry

    report = {
        "type": "replay",
        "date": date,
        "strategies": sids,
        "params_overrides": params or {},
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.perf_counter() - t0) * 1000),
        "warnings": warnings,
        "results": results,
    }
    # 摘要：每策略建议数/触发数（前端对比表用）
    summary = {}
    for sid, entry in results.items():
        sm = {}
        au = entry["phases"].get("auction")
        if au and au.get("ok"):
            sm["advices"] = len(au.get("advices") or [])
            sm["blocked"] = len(au.get("blocked") or [])
            sm["candidates"] = au.get("candidates")
        po = entry["phases"].get("pool")
        if po and po.get("ok"):
            sm["pool_passed"] = len(po.get("pool", {}).get("passed") or [])
            sm["scenes"] = len(po.get("scenes") or [])
            sm["triggered"] = len(po.get("intraday", {}).get("triggered") or [])
            sm["snapshot_missing"] = len(po.get("intraday", {}).get("missing") or [])
        summary[sid] = sm
    report["summary"] = summary
    return report


def _persist(settings: Settings, report: dict) -> Path:
    d = settings.data_dir / "replay" / report["date"]
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    p = d / f"{'-'.join(report['strategies'])}_{ts}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="quant_system.replay", description="对历史快照回放策略")
    ap.add_argument("--date", required=True, help="回放交易日 YYYY-MM-DD")
    ap.add_argument("--strategy", default="all", help=f"策略 id 或 all（可选: {strategy_ids()}）")
    ap.add_argument("--params", default=None, help="参数覆盖 JSON：{strategy_id: {key: value}}")
    ap.add_argument("--no-persist", action="store_true", help="不落盘 data/replay/")
    args = ap.parse_args()

    sids = strategy_ids() if args.strategy == "all" else [args.strategy]
    params = json.loads(args.params) if args.params else None
    if params:
        bad = set(params) - set(strategy_ids())
        if bad:
            _emit({"error": f"未知策略: {sorted(bad)}"})
            return 2

    settings = Settings()
    settings.ensure_dirs()
    try:
        report = run_replay(settings, args.date, sids, params)
    except Exception as exc:  # noqa: BLE001
        log.exception("回放执行失败")
        _emit({"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=8)})
        return 1
    if not args.no_persist:
        report["saved_to"] = str(_persist(settings, report))
    _emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
