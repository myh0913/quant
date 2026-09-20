"""参数版本绩效聚合（M1 闭环，2026-09-18）。

聚合 data/advice/<date>/review_*.json 的逐条 config_version，
输出 {strategy: {version: {count, win_rate, win_rate_close, ...}}} 到
data/config/perf.json —— 量化配置页"本版本累计绩效"数据源。

注意：不写 advice 目录（避免污染建议流/前端报告页），配置页经
quant-web backend /api/config/perf 直读本文件。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger(__name__)

MIN_SAMPLE = 10  # 样本不足阈值（少于该条数标注"样本不足"）


def _iter_review_items(settings: "Settings", days: int = 30) -> list[dict]:
    """收集最近 N 个自然日内全部 review 条目。"""
    from datetime import datetime, timedelta

    base = settings.data_dir / "advice"
    if not base.is_dir():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    items: list[dict] = []
    for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name >= cutoff):
        for f in sorted(d.glob("review_*.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(doc.get("items"), list):
                items.extend(it for it in doc["items"] if isinstance(it, dict))
    return items


def aggregate_by_version(settings: "Settings", days: int = 30) -> dict:
    """按 策略 × config_version 聚合建议绩效（双口径）。"""
    items = _iter_review_items(settings, days=days)
    agg: dict[str, dict[int, dict]] = {}
    for it in items:
        strat = it.get("strategy") or "未知"
        ver = int(it.get("config_version") or 0)
        bucket = agg.setdefault(strat, {}).setdefault(ver, {
            "count": 0, "fillable": 0, "wins": 0, "wins_close": 0,
        })
        bucket["count"] += 1
        if it.get("win") is True:
            bucket["wins"] += 1
        if it.get("win_close") is True:
            bucket["wins_close"] += 1
        if it.get("next_high_pct") is not None and not it.get("unfillable"):
            bucket["fillable"] += 1

    out: dict[str, dict] = {}
    for strat, versions in agg.items():
        out[strat] = {}
        for ver, b in sorted(versions.items()):
            fillable = b["fillable"]
            out[strat][str(ver)] = {
                "count": b["count"],
                "fillable": fillable,
                "win_rate": round(b["wins"] / fillable, 4) if fillable else None,
                "win_rate_close": round(b["wins_close"] / fillable, 4) if fillable else None,
                "sample_enough": fillable >= MIN_SAMPLE,
            }
    return out


def export_perf(settings: "Settings", days: int = 30) -> dict:
    """聚合并写 data/config/perf.json（原子写）。返回写出的文档。"""
    from datetime import datetime, timezone

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "min_sample": MIN_SAMPLE,
        "strategies": aggregate_by_version(settings, days=days),
    }
    p: Path = settings.data_dir / "config" / "perf.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    log.info("版本绩效聚合完成 → %s（%d 策略）", p, len(doc["strategies"]))
    return doc
