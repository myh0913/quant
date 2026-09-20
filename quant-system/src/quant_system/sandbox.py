"""沙箱 CLI：在线测试策略 / 探测数据源（由 quant-web backend 以子进程调用）。

用法：
    python -m quant_system.sandbox test --strategy auction_grab --date 2026-09-15 \
        [--params '{"min_rise": 0.03}']
    python -m quant_system.sandbox test --strategy lianban --date 2026-09-15
    python -m quant_system.sandbox test --strategy dragon   --date 2026-09-15
    python -m quant_system.sandbox ping [datasource_id]

输出契约：stdout 只输出一个 JSON（backend 解析最后一行）；所有日志走 stderr。
沙箱隔离三重保障：
1. 独立子进程（与调度器进程隔离）；
2. 参数经 config_registry.temporary_overrides 进程内注入，不触碰 active.json；
3. 不调用 persist_report / persist=False，绝不写 advice 落盘目录、不推 WS。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config_registry
from .config import Settings

log = logging.getLogger("sandbox")
SH_TZ = ZoneInfo("Asia/Shanghai")


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


def _valid_date(s: str) -> str:
    datetime.strptime(s, "%Y-%m-%d")
    return s


def _test_lianban(settings: Settings, prev: str, cur: str, warnings: list[str]) -> dict:
    """连板捉妖沙箱：完整走 盘后池 → 竞价环境/场景 → 盘中触发评估（不落盘）。"""
    from .strategy import open_minute_fetcher
    from .strategy.lianban import evaluate_intraday_scene, run_lianban

    rep = run_lianban(settings, prev, cur)
    p = config_registry.get_params(settings, "lianban")
    triggered, not_triggered = [], []
    with open_minute_fetcher(settings) as fetch:
        for sc in rep.scenes:
            if sc.scene not in ("B", "C"):
                continue
            try:
                pts = fetch(sc.thscode, cur)
                r = evaluate_intraday_scene(
                    pts, sc.scene,
                    window=int(p["intraday_window_min"]),
                    min_pct=p["intraday_min_rise"],
                    vol_multiple=p["intraday_vol_multiple"],
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{sc.name}({sc.thscode}) 分时评估失败: {exc}")
                continue
            row = {**sc.model_dump(), "intraday": r.model_dump()}
            (triggered if r.triggered else not_triggered).append(row)
    return {
        "gate_state": rep.gate_state,
        "gate_note": rep.gate_note,
        "pool": {
            "passed": [c.model_dump() for c in rep.candidates],
            "rejected": [c.model_dump() for c in rep.rejected],
            "pool_size": rep.pool_size,
        },
        "env": rep.env.model_dump() if rep.env else None,
        "scenes": [s.model_dump() for s in rep.scenes],
        "advices": [a.model_dump(mode="json") for a in rep.advices],
        "blocked": rep.blocked,
        "intraday": {
            "triggered": triggered,
            "not_triggered": [
                {"thscode": t["thscode"], "name": t["name"], "scene": t["scene"],
                 "detail": t["intraday"].get("detail", "")}
                for t in not_triggered
            ],
        },
    }


def _test_dragon(settings: Settings, prev: str, cur: str, warnings: list[str]) -> dict:
    """龙回头沙箱：盘后池 → 竞价场景 → 承接/横盘确认（不落盘）。"""
    from .strategy import open_minute_fetcher
    from .strategy.dragon import confirm_chengjie_hengpan, run_dragon

    rep = run_dragon(settings, prev, cur)
    p = config_registry.get_params(settings, "dragon")
    confirmed, not_confirmed = [], []
    with open_minute_fetcher(settings) as fetch:
        for sc in rep.scenes:
            if sc.scene not in ("E", "F"):
                continue
            try:
                pts = fetch(sc.thscode, cur)
                cf = confirm_chengjie_hengpan(
                    pts,
                    range_pct=p["hengpan_range_pct"],
                    chengjie_min=int(p["chengjie_minutes"]),
                    hengpan_min=int(p["hengpan_minutes"]),
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{sc.name}({sc.thscode}) 分时确认失败: {exc}")
                continue
            row = {**sc.model_dump(), "confirm": cf.model_dump()}
            (confirmed if cf.confirmed else not_confirmed).append(row)
    return {
        "gate_state": rep.gate_state,
        "gate_note": rep.gate_note,
        "pool": {
            "passed": [c.model_dump() for c in rep.candidates],
            "rejected": [c.model_dump() for c in rep.rejected],
            "pool_size": rep.pool_size,
        },
        "scenes": [s.model_dump() for s in rep.scenes],
        "advices": [a.model_dump(mode="json") for a in rep.advices],
        "blocked": rep.blocked,
        "intraday": {
            "confirmed": confirmed,
            "not_confirmed": [
                {"thscode": t["thscode"], "name": t["name"], "scene": t["scene"],
                 "detail": t["confirm"].get("detail", "")}
                for t in not_confirmed
            ],
        },
    }


def cmd_test(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    settings = Settings()
    settings.ensure_dirs()
    strategy = args.strategy
    try:
        config_registry.strategy_schema(strategy)
    except KeyError as exc:
        _emit({"error": str(exc)})
        return 2
    date = _valid_date(args.date)
    overrides: dict[str, dict] | None = None
    if args.params:
        params = json.loads(args.params)
        schema_keys = {p["key"] for p in config_registry.strategy_schema(strategy)["params"]}
        bad = set(params) - schema_keys
        if bad:
            _emit({"error": f"未知参数: {sorted(bad)}"})
            return 2
        overrides = {strategy: params}

    warnings: list[str] = []
    today_sh = datetime.now(SH_TZ).strftime("%Y-%m-%d")

    with config_registry.temporary_overrides(overrides or {}):
        if strategy == "auction_grab":
            # eltdx.auction_top_amount 仅取当日实时竞价排行，无历史回放能力
            if date != today_sh:
                _emit({"error": f"竞价主力抢筹依赖当日实时竞价排行，沙箱日期必须为今天（{today_sh}）。"
                                 f"历史回放需给 auction_rank 接口补 date 参数（列入 P3 字段映射改造）。"})
                return 2
            from .strategy.auction_grab import run_auction_grab

            rep = run_auction_grab(settings, date=date, persist=False)
            result = rep.model_dump(mode="json")
        else:
            from .scheduler import prev_trading_day

            prev = prev_trading_day(settings, date)
            result = (
                _test_lianban(settings, prev, date, warnings)
                if strategy == "lianban"
                else _test_dragon(settings, prev, date, warnings)
            )

    _emit({
        "sandbox": True,
        "strategy": strategy,
        "date": date,
        "params_overrides": overrides[strategy] if overrides else None,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.perf_counter() - t0) * 1000),
        "warnings": warnings,
        "result": result,
    })
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    from .datasource import registry as ds_registry

    settings = Settings()
    settings.ensure_dirs()
    ds_registry.export_datasources(settings)  # 顺带保证注册表文件在位（调度器未启动过也能列出）
    known = {d["id"] for d in ds_registry.DATASOURCES}
    if args.ds_id and args.ds_id not in known:
        _emit({"error": f"未知数据源: {args.ds_id}（可选: {sorted(known)}）"})
        return 2
    results = ds_registry.run_ping(settings, args.ds_id)
    _emit({"ok": all(r["ok"] for r in results.values()), "results": results})
    return 0


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="quant_system.sandbox", description="策略沙箱 / 数据源探测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_test = sub.add_parser("test", help="沙箱运行策略（不落盘）")
    ap_test.add_argument("--strategy", required=True,
                         choices=sorted(config_registry.strategy_ids()))
    ap_test.add_argument("--date", required=True, help="交易日 YYYY-MM-DD")
    ap_test.add_argument("--params", default=None, help="参数覆盖 JSON（对象，键为参数 key）")
    ap_test.set_defaults(fn=cmd_test)

    ap_ping = sub.add_parser("ping", help="数据源连通性探测")
    ap_ping.add_argument("ds_id", nargs="?", default=None, help="缺省探测全部")
    ap_ping.set_defaults(fn=cmd_ping)

    args = ap.parse_args()
    try:
        return int(args.fn(args))
    except Exception as exc:  # noqa: BLE001
        log.exception("沙箱执行失败")
        _emit({"error": f"{type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc(limit=8)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
