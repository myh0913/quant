"""数据源自描述注册表：能力声明 + 连通性探测 + 导出。

设计对齐 config_registry：本包是唯一事实来源，调度器启动时导出
data/config/datasources.json（backend 配置页只读）；health_check 仅在
sandbox ping 子进程中按需执行并记录 data/config/datasource_health.json。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from .base import BaseDataSource, DataSourceError
from .eastmoney import EastmoneySource
from .eltdx_source import EltdxSource
from .hithink import HithinkSource
from .xuangutong import XuangutongSource

log = logging.getLogger(__name__)

# 能力（用途）清单是 P3「字段映射/主备切换」的基础：声明每个源能提供什么
DATASOURCES: list[dict] = [
    {
        "id": "eltdx",
        "label": "eltdx 本地行情",
        "kind": "tcp",
        "capabilities": ["auction_top_amount", "opening_match", "minute_points", "quote_snapshot"],
        "desc": "竞价成交额排名 / 开盘匹配 / 分钟分时（策略一二三主行情源）",
    },
    {
        "id": "hithink",
        "label": "同花顺 iFind",
        "kind": "http",
        "capabilities": ["limit_up_pool", "limit_down_pool", "limit_break_pool", "daily_bars",
                          "auction_snapshot", "ladder", "valuation"],
        "desc": "涨停/跌停/炸板池 / 日线 / 竞价快照 / 连板梯队",
    },
    {
        "id": "xuangutong",
        "label": "选股通",
        "kind": "http",
        "capabilities": ["market_sentiment", "theme_rank", "theme_stocks", "newsflash"],
        "desc": "市场情绪指标 / 题材排行 / 快讯",
    },
    {
        "id": "eastmoney",
        "label": "东方财富",
        "kind": "http",
        "capabilities": ["restricted_stocks", "unusual_stocks"],
        "desc": "监管名单 / 严重异动（风控输入）",
    },
]

_SOURCE_CLS: dict[str, type[BaseDataSource]] = {
    "eltdx": EltdxSource,
    "hithink": HithinkSource,
    "xuangutong": XuangutongSource,
    "eastmoney": EastmoneySource,
}

# 能力 → 可提供的数据源（有序 = 默认优先级）。多源能力可在量化配置页指定
# 主/备（datasource_prefs.json），resolve 层按契约取数并自动切换（M2）。
CAPABILITY_PROVIDERS: dict[str, list[str]] = {
    "limit_up_pool": ["hithink", "xuangutong"],
    "limit_down_pool": ["hithink"],
    "minute_points": ["eltdx"],
    "opening_match": ["eltdx"],
    "auction_top_amount": ["eltdx"],
    "auction_series": ["eltdx"],
    "pre_close": ["eltdx"],
    "daily_bars": ["hithink"],
    "market_sentiment": ["xuangutong"],
    "index_snapshot": ["hithink"],
    "monitor_stocks": ["eastmoney"],
    "trading_calendar": ["hithink"],
}


def _prefs_path(settings: Settings) -> Path:
    return settings.data_dir / "config" / "datasource_prefs.json"


def load_prefs(settings: Settings) -> dict:
    """能力 → {primary, fallback}；backend 唯一写方，本包每次现读（热生效）。"""
    try:
        doc = json.loads(_prefs_path(settings).read_text(encoding="utf-8"))
        return doc.get("prefs", {}) if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _probe(ds_id: str, settings: Settings) -> dict:
    """单源轻量探测：走真实取数路径的最小请求。"""
    t0 = time.perf_counter()
    try:
        if ds_id == "eltdx":
            with EltdxSource(settings) as src:
                snaps = src._get_client().quotes.get_snapshots(["sh000001"])
                ok = bool(snaps)
            detail = "上证指数快照获取成功" if ok else "快照为空"
        elif ds_id == "hithink":
            src = HithinkSource(settings)
            items, _total = src.limit_up_pool(size=1)  # 返回 (items, total) 元组
            ok = isinstance(items, list)
            detail = f"涨停池接口返回 {len(items)} 行（size=1 探测）"
        elif ds_id == "xuangutong":
            src = XuangutongSource(settings)
            d = src.market_sentiment()
            ok = bool(d)
            detail = "市场情绪指标获取成功"
        elif ds_id == "eastmoney":
            src = EastmoneySource(settings)
            rows = src.severe_unusual(page_size=1)
            ok = isinstance(rows, list)
            detail = f"异动接口返回 {len(rows)} 行（page_size=1 探测）"
        else:
            return {"ok": False, "latency_ms": 0, "detail": f"未知数据源: {ds_id}"}
        return {
            "ok": bool(ok),
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "detail": detail,
        }
    except DataSourceError as exc:
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000),
                "detail": f"DataSourceError: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000),
                "detail": f"{type(exc).__name__}: {exc}"}


def _health_path(settings: Settings) -> Path:
    return settings.data_dir / "config" / "datasource_health.json"


def run_ping(settings: Settings, ds_id: str | None = None) -> dict:
    """探测并记录。ds_id=None 探测全部。返回 {ds_id: result}。"""
    ids = [ds_id] if ds_id else [d["id"] for d in DATASOURCES]
    results: dict = {}
    hp = _health_path(settings)
    try:
        results = json.loads(hp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        results = {}
    for i in ids:
        r = _probe(i, settings)
        r["checked_at"] = datetime.now(timezone.utc).isoformat()
        results[i] = r
        log.info("数据源探测 %s: ok=%s %sms %s", i, r["ok"], r["latency_ms"], r["detail"])
    hp.parent.mkdir(parents=True, exist_ok=True)
    tmp = hp.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(hp)
    return {i: results[i] for i in ids}


def export_datasources(settings: Settings) -> None:
    """导出注册表（调度器启动时调用）：数据源 + 能力提供方映射。"""
    out_dir = settings.data_dir / "config"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {"version": 2, "datasources": DATASOURCES, "capability_providers": CAPABILITY_PROVIDERS}
    tmp = out_dir / "datasources.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_dir / "datasources.json")
