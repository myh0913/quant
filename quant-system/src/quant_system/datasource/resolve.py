"""能力级取数契约层（M2/M3）：业务代码只依赖本层，不直接绑定具体数据源。

- 每个能力定义统一返回契约（字段/类型/单位），适配差异收敛在本层；
- 主源按 datasource_prefs.json（量化配置页可改，热生效），主源失败自动
  切换备源并告警——对齐「宁可拒绝，不可错报」：备源也失败则抛错上浮，
  绝不静默返回不完整数据；
- 连接复用：循环取数场景用 `with data_session(settings):` 包住，期间每个
  数据源至多一个实例（eltdx TCP 连接不重建）；无会话时自动临时建连；
- 快照（M3）：live 取数自动落盘 data/std/<运行日>/；replay_scope 内只读
  快照、缺失抛 SnapshotMissing，绝不现场拉数（防未来数据）。

新增可切换能力：CAPABILITY_PROVIDERS 声明 + 本层加契约函数 + 校验各源
返回对齐契约（字段映射写在归一化函数里）。
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Optional

from .. import snapshot
from .base import BaseDataSource, DataSourceError
from .eastmoney import EastmoneySource
from .eltdx_source import EltdxSource, to_eltdx_code
from .hithink import HithinkSource
from .registry import CAPABILITY_PROVIDERS, _SOURCE_CLS, load_prefs
from .xuangutong import XuangutongSource

if TYPE_CHECKING:
    from ..config import Settings
    from ..models import AuctionPoint, AuctionRankRow, MonitorStock, OpeningMatch

log = logging.getLogger(__name__)

# 涨停池契约（limit_up_pool）字段说明（消费方：strategy/lianban / strategy/dragon / cycle）：
#   thscode: str          同花顺代码（600207.SS）
#   name: str             股票名称
#   continue_day_cnt: int 连板天数（≥1）
#   last_price: float     最新价（T 日涨停价；evaluate_auction_env 用作昨收近似）
LIMIT_UP_POOL_CONTRACT = {
    "thscode": "str 代码",
    "name": "str 名称",
    "continue_day_cnt": "int 连板天数",
    "last_price": "float 最新价（元）",
}


# ============================== 会话（连接复用） ==============================


class DataSession:
    """取数会话：期间复用各数据源连接（每源至多一个实例）。"""

    def __init__(self, settings: "Settings"):
        self._settings = settings
        self._sources: dict[str, BaseDataSource] = {}

    def get(self, source_id: str) -> BaseDataSource:
        if source_id not in self._sources:
            self._sources[source_id] = _SOURCE_CLS[source_id](self._settings)
        return self._sources[source_id]

    def close(self) -> None:
        for src in self._sources.values():
            try:
                src.close()
            except Exception:  # noqa: BLE001
                pass
        self._sources.clear()


_SESSION: contextvars.ContextVar[Optional[DataSession]] = contextvars.ContextVar(
    "resolve_session", default=None
)


@contextmanager
def data_session(settings: "Settings"):
    """打开取数会话：with 块内所有 standard_* 复用同一批数据源连接。"""
    ds = DataSession(settings)
    tok = _SESSION.set(ds)
    try:
        yield ds
    finally:
        _SESSION.reset(tok)
        ds.close()


def _run(settings: "Settings", source_id: str, fn: Callable[[BaseDataSource], object]) -> object:
    """在会话内（或临时会话）对指定源执行 fn(source)。"""
    ds = _SESSION.get()
    if ds is not None:
        return fn(ds.get(source_id))
    with data_session(settings) as d:
        return fn(d.get(source_id))


def _fetch(settings: "Settings", capability: str, fetchers: dict[str, Callable[[], object]]) -> object:
    """按能力取主备源：prefs 覆盖 > CAPABILITY_PROVIDERS 顺序。全失败抛错。"""
    providers = CAPABILITY_PROVIDERS.get(capability, [])
    prefs = load_prefs(settings).get(capability, {})
    primary = prefs.get("primary") if prefs.get("primary") in providers else (providers[0] if providers else None)
    fallback = prefs.get("fallback") if prefs.get("fallback") in providers else None
    order = [s for s in (primary, fallback) if s and s in fetchers]
    if not order:
        order = [s for s in providers if s in fetchers]
    if not order:
        raise DataSourceError("resolve", f"{capability} 无可用数据源")

    last_exc: Exception | None = None
    for i, sid in enumerate(order):
        try:
            return fetchers[sid]()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("%s 取数失败（source=%s）: %s", capability, sid, exc)
            if i == 0 and len(order) > 1:
                log.warning("%s 主源失败已切换备源: 用 %s", capability, order[1])
    raise DataSourceError("resolve", f"{capability} 全部来源失败: {last_exc}") from last_exc


# ============================== 快照接入 ==============================


def _dec_list(model: type) -> Callable[[Any], list]:
    def dec(payload: Any) -> list:
        return [model.model_validate(x) for x in (payload or [])]

    return dec


def _dec_optional(model: type) -> Callable[[Any], Any]:
    def dec(payload: Any):
        return model.model_validate(payload) if payload else None

    return dec


def _dec_identity(payload: Any) -> Any:
    return payload


def _dec_float(payload: Any) -> Optional[float]:
    return None if payload is None else float(payload)


def _io(settings: "Settings", capability: str, args: dict,
        live: Callable[[], Any], decode: Callable[[Any], Any] = _dec_identity) -> Any:
    """能力取数 + 快照：replay 读快照，live 取数并落盘。"""
    date = args.get("date")
    return snapshot.io(
        settings, capability, args, live, decode,
        date=date if isinstance(date, str) else None,
    )


# ============================== 池类能力 ==============================


def _norm_xgt_limit_up_rows(rows: list[dict]) -> list[dict]:
    """选股通 flash-api 涨停池行 → 契约字段（与 hithink 行同构）。

    字段映射（2026-09-15 实测 flash-api /api/pool/detail）：
      symbol → thscode（同为 .SS/.SZ 后缀，无需转换）
      stock_chi_name → name
      limit_up_days → continue_day_cnt
      price → last_price
    其余字段透传（下游仅消费契约字段）。
    """
    out: list[dict] = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        row = dict(it)
        row["thscode"] = it.get("symbol", "")
        row["name"] = it.get("stock_chi_name", "")
        row["continue_day_cnt"] = int(it.get("limit_up_days") or 0)
        row["last_price"] = float(it.get("price") or 0)
        out.append(row)
    out.sort(key=lambda r: r["continue_day_cnt"], reverse=True)  # 对齐 hithink 连板数降序
    return out


def standard_limit_up_pool(settings: "Settings", date: str) -> list[dict]:
    """涨停池契约：指定交易日（YYYY-MM-DD）的涨停池，按连板天数降序。"""
    from ..timeutil import date_ms

    def _fetch_hithink() -> list[dict]:
        def fn(src: HithinkSource) -> list[dict]:
            items, _total = src.limit_up_pool(
                date_ms=date_ms(date), size=200, sort_field="continue_day_cnt", sort_dir="desc"
            )
            return [it for it in items if isinstance(it, dict)]

        return _run(settings, "hithink", fn)

    def _fetch_xuangutong() -> list[dict]:
        def fn(src: XuangutongSource) -> list[dict]:
            return _norm_xgt_limit_up_rows(src.limit_up_pool(date=date))

        return _run(settings, "xuangutong", fn)

    return _io(settings, "limit_up_pool", {"date": date},
               lambda: _fetch(settings, "limit_up_pool",
                              {"hithink": _fetch_hithink, "xuangutong": _fetch_xuangutong}))


def limit_up_pool_counts_by_source(settings: "Settings", date: str) -> dict[str, int]:
    """涨停池对账（2026-09-17）：各源分别取数（不走主备切换），返回 {source_id: 条数}。

    供盘后对账用：主备源条数差异过大 → 数据异常告警。单源失败该源记 -1。
    """
    from ..timeutil import date_ms

    out: dict[str, int] = {}

    def _hithink(src: HithinkSource) -> int:
        items, _total = src.limit_up_pool(
            date_ms=date_ms(date), size=200, sort_field="continue_day_cnt", sort_dir="desc"
        )
        return len(items)

    def _xuangutong(src: XuangutongSource) -> int:
        return len(src.limit_up_pool(date=date))

    for sid, fn in (("hithink", _hithink), ("xuangutong", _xuangutong)):
        try:
            out[sid] = int(_run(settings, sid, fn))
        except Exception as exc:  # noqa: BLE001
            log.warning("对账取数失败（source=%s）: %s", sid, exc)
            out[sid] = -1
    return out


def standard_limit_down_pool(settings: "Settings", date: str | None = None) -> list[dict]:
    """跌停池契约：指定交易日（缺省=当日），list[dict] 原始条目。"""
    from ..timeutil import date_ms, sh_today

    d = date or sh_today()

    def fn(src: HithinkSource) -> list[dict]:
        return src.limit_down_pool(date_ms=date_ms(d), size=200)

    return _io(settings, "limit_down_pool", {"date": d},
               lambda: _fetch(settings, "limit_down_pool",
                              {"hithink": lambda: _run(settings, "hithink", fn)}))


# ============================== eltdx 行情类能力 ==============================


def standard_auction_top_amount(settings: "Settings", limit: int = 10) -> "list[AuctionRankRow]":
    """竞价成交额前 N（已按 60/00、非 ST 过滤）。仅当日实时（历史回放走快照）。"""
    from ..models import AuctionRankRow

    def fn(src: EltdxSource):
        return src.auction_top_amount(limit=limit)

    return _io(settings, "auction_top_amount", {"limit": limit},
               lambda: _fetch(settings, "auction_top_amount",
                              {"eltdx": lambda: _run(settings, "eltdx", fn)}),
               _dec_list(AuctionRankRow))


def standard_auction_series(settings: "Settings", thscode: str, date: str) -> "list[AuctionPoint]":
    """竞价过程点（9:15-9:25）。thscode 接受内部标准格式（600519.SH）。"""
    from ..models import AuctionPoint

    def fn(src: EltdxSource):
        return src.auction_series(to_eltdx_code(thscode), date)

    return _io(settings, "auction_series", {"thscode": thscode, "date": date},
               lambda: _fetch(settings, "auction_series",
                              {"eltdx": lambda: _run(settings, "eltdx", fn)}),
               _dec_list(AuctionPoint))


def standard_opening_match(settings: "Settings", thscode: str, date: str) -> "Optional[OpeningMatch]":
    """9:25 正式撮合；无撮合数据返回 None。date 支持历史（eltdx 历史接口，约 2025-10 起）。"""
    from ..models import OpeningMatch

    def fn(src: EltdxSource):
        return src.opening_match(to_eltdx_code(thscode), date)

    return _io(settings, "opening_match", {"thscode": thscode, "date": date},
               lambda: _fetch(settings, "opening_match",
                              {"eltdx": lambda: _run(settings, "eltdx", fn)}),
               _dec_optional(OpeningMatch))


def standard_minute_points(settings: "Settings", thscode: str, date: str) -> list[dict]:
    """分钟分时契约：[{time_label, price, volume}]（升序）。当日实盘 today，历史 history。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    today = _dt.now(_ZI("Asia/Shanghai")).strftime("%Y-%m-%d")

    def fn(src: EltdxSource) -> list[dict]:
        full = to_eltdx_code(thscode)
        client = src._get_client()
        series = client.minutes.today(full) if date == today else client.minutes.history(full, date)
        pts = getattr(series, "points", None) or []
        return [
            {"time_label": p.time_label, "price": float(p.price or 0), "volume": float(p.volume or 0)}
            for p in pts
        ]

    return _io(settings, "minute_points", {"thscode": thscode, "date": date},
               lambda: _fetch(settings, "minute_points",
                              {"eltdx": lambda: _run(settings, "eltdx", fn)}))


def standard_pre_close(settings: "Settings", thscode: str, date: str | None = None) -> float:
    """昨收价。失败/缺失返回 0.0（调用方按无数据处理）。

    - date 为空或=今天：eltdx 实时快照（含交易所除权调整，最准确）；
    - date 为历史（回填/回测）：昨收 = date 前一交易日收盘价，从 daily_bars 推导
      （eltdx 快照无历史能力，2026-09-18 回测支持）。
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    from ..pool import normalize_thscode
    from ..timeutil import shift_calendar_days

    today = _dt.now(_ZI("Asia/Shanghai")).strftime("%Y-%m-%d")

    def fn(src: EltdxSource) -> float:
        n = normalize_thscode(thscode)
        snaps = src._get_client().quotes.get_snapshots([to_eltdx_code(thscode)])
        pre = float(getattr(snaps[0], "pre_close_price", 0) or 0) if snaps else 0.0
        return pre if n else 0.0

    if date is None or date == today:
        try:
            return float(_io(settings, "pre_close", {"thscode": thscode},
                             lambda: _fetch(settings, "pre_close",
                                            {"eltdx": lambda: _run(settings, "eltdx", fn)}),
                             _dec_float))
        except DataSourceError:
            return 0.0

    # 历史昨收：从日线推导（date 前一交易日的收盘价）
    def _derive() -> float:
        end = shift_calendar_days(date, -1)  # 多回看几日覆盖周末/节假日
        bars = standard_daily_bars(settings, thscode, end, lookback_days=10)
        return float(bars[-1]["close_price"]) if bars else 0.0

    try:
        return float(_io(settings, "pre_close", {"thscode": thscode, "date": date},
                         _derive, _dec_float))
    except DataSourceError:
        return 0.0


# ============================== 日线 / 情绪 / 监管 / 日历 ==============================


def standard_daily_bars(settings: "Settings", thscode: str, end_date: str, lookback_days: int = 60) -> list[dict]:
    """日 K 契约：截至 end_date 回看 lookback_days 个交易日（自然日窗 ≈ ×1.7），不复权。"""
    import datetime as _dt

    from ..timeutil import date_ms

    end = _dt.datetime.strptime(end_date, "%Y-%m-%d")
    start = (end - _dt.timedelta(days=int(lookback_days * 1.7))).strftime("%Y-%m-%d")

    def fn(src: HithinkSource) -> list[dict]:
        return src.daily_bars(thscode, date_ms(start), date_ms(end_date), adjust="none")

    return _io(settings, "daily_bars",
               {"thscode": thscode, "start": start, "end": end_date, "lookback": lookback_days},
               lambda: _fetch(settings, "daily_bars",
                              {"hithink": lambda: _run(settings, "hithink", fn)}))


def standard_market_sentiment(settings: "Settings", date: str | None = None) -> dict:
    """市场情绪契约：指定日期最后一个分钟点（缺省=今天）。无点返回 {}。

    字段：market_temperature / limit_up_count / limit_down_count /
    limit_up_broken_count / limit_up_broken_ratio / _collected_at 等。
    """
    from ..timeutil import sh_today

    d = date or sh_today()

    def fn(src: XuangutongSource) -> dict:
        return src.market_sentiment_by_date(d)

    return _io(settings, "market_sentiment", {"date": d},
               lambda: _fetch(settings, "market_sentiment",
                              {"xuangutong": lambda: _run(settings, "xuangutong", fn)}))


def standard_index_snapshot_pct(settings: "Settings") -> Optional[float]:
    """上证指数当日涨幅（黑天鹅近似用）。失败返回 None。"""

    def fn(src: HithinkSource) -> Optional[float]:
        snap, _meta = src._get("/api/a-share-index/prices/snapshot", {"thscodes": "000001.SH"}, name="idx_sh")
        items = snap[0].get("item", []) if isinstance(snap, tuple) else (snap or {}).get("item", [])
        if items:
            it = items[0]
            if it.get("prev_price"):
                return (it.get("last_price", 0) - it["prev_price"]) / it["prev_price"]
        return None

    try:
        return _io(settings, "index_snapshot", {},
                   lambda: _fetch(settings, "index_snapshot",
                                  {"hithink": lambda: _run(settings, "hithink", fn)}),
                   _dec_float)
    except DataSourceError:
        return None


def standard_monitor_stocks(settings: "Settings") -> "list[MonitorStock]":
    """监管名单契约：东财重点监控 + 严重异常（风控输入）。"""
    from ..models import MonitorStock

    def fn(src: EastmoneySource) -> "list[MonitorStock]":
        monitors: list[MonitorStock] = src.restricted_stocks()
        monitors += src.severe_unusual(page_size=50)
        return monitors

    return _io(settings, "monitor_stocks", {},
               lambda: _fetch(settings, "monitor_stocks",
                              {"eastmoney": lambda: _run(settings, "eastmoney", fn)}),
               _dec_list(MonitorStock))


def standard_trading_days(settings: "Settings") -> list[str]:
    """交易日历契约：YYYY-MM-DD 字符串列表（hithink 返回 YYYYMMDD 已归一化）。"""

    def fn(src: HithinkSource) -> list[str]:
        data, _meta = src._get("/api/a-share/calendar/trading-days", {}, name="calendar")
        dates: list[str] = []
        for it in data.get("item") or []:
            d = str(it.get("date", ""))
            if len(d) == 8 and d.isdigit():  # 20260908 → 2026-09-08
                d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            if d:
                dates.append(d)
        if not dates:
            raise RuntimeError("交易日历返回为空")
        return dates

    return _io(settings, "trading_calendar", {},
               lambda: _fetch(settings, "trading_calendar",
                              {"hithink": lambda: _run(settings, "hithink", fn)}))
