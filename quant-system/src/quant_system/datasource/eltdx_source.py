"""eltdx 数据源适配器（主源）。

独立 Python SDK 脚本化，不依赖 OpenClaw 工具；连接通达信行情服务器。
能力（已实测 2026-09-05）：
- 竞价成交额服务端排序前 N（策略一主路径）
- 当日/历史竞价过程（9:15-9:25 逐点，历史约从 2025-10 起）
- 当日 09:25 正式撮合
- 分钟 K / 历史分时
- 每日涨跌停价
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from ..config import Settings
from ..models import AuctionPoint, AuctionRankRow, MinuteBar, OpeningMatch
from ..pool import is_target_stock
from .base import BaseDataSource, DataSourceError

# 服务端排序请求量：取 50 保证过滤后仍有 10 只目标股
_RANK_REQUEST_N = 50


def to_eltdx_code(thscode: str) -> str:
    """内部标准代码（600519.SH）→ eltdx 代码（sh600519）。"""
    from ..pool import normalize_thscode

    n = normalize_thscode(thscode)
    if n.endswith(".SH"):
        return "sh" + n[:6]
    return "sz" + n[:6]


class EltdxSource(BaseDataSource):
    source_name = "eltdx"

    def __init__(self, settings: Settings):
        super().__init__(settings.raw_dir)
        self._client = None  # 惰性创建，保持连接复用

    # ---------- 内部 ----------
    def _get_client(self):
        if self._client is None:
            try:
                from eltdx import TdxClient  # 可选依赖，延迟导入

                self._client = TdxClient(timeout=3)
            except Exception as exc:  # noqa: BLE001
                raise DataSourceError("import", f"eltdx 未安装或初始化失败: {exc}") from exc
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- 竞价成交额排名（策略一主路径） ----------
    def auction_top_amount(self, limit: int = 10) -> list[AuctionRankRow]:
        """竞价成交额降序前 limit 只（已按 60/00、非ST 过滤）。

        实现：服务端按“开盘金额”排序取前 50，本地过滤后取前 limit。
        日期：以服务端行情日期为准（非交易日可能返回最近交易日快照）。
        """
        client = self._get_client()
        try:
            table = client.helpers.realtime_rank(sort_by="开盘金额", count=_RANK_REQUEST_N)
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError("rank", f"realtime_rank 失败: {exc}", retriable=True) from exc
        rows = list(getattr(table, "rows", []) or [])

        now = datetime.now(timezone.utc)
        result: list[AuctionRankRow] = []
        for r in rows:
            code = (getattr(r, "full_code", "") or "").lower()
            name = getattr(r, "name", "") or ""
            ticker = code[-6:] if len(code) >= 6 else code
            if not is_target_stock(ticker, name):
                continue
            # 竞价成交额必须用 raw.open_amount（单位元）；r.amount 是当日总成交额，不是竞价额
            raw = getattr(r, "raw", None)
            open_amount = float(getattr(raw, "open_amount", 0.0) or 0.0)
            open_price = float(getattr(raw, "open_price", 0.0) or 0.0)
            pre_close = float(getattr(raw, "pre_close_price", 0.0) or 0.0)
            auction_pct = None
            if pre_close:
                auction_pct = (open_price - pre_close) / pre_close
            result.append(
                AuctionRankRow(
                    thscode=ticker + (".SH" if ticker.startswith("60") else ".SZ"),
                    ticker=ticker,
                    name=name,
                    auction_amount_yuan=open_amount,
                    auction_pct=auction_pct,
                    auction_price=open_price,
                    open_price=open_price,
                    pre_close=pre_close,
                    source=self.source_name,
                    data_date="",  # 服务端日期待从表字段补充
                    ts=now,
                )
            )
            if len(result) >= limit:
                break
        return result

    # ---------- 竞价过程（策略一核心） ----------
    def auction_series(self, code: str, date: str | None = None) -> list[AuctionPoint]:
        """集合竞价过程点。date 为 YYYY-MM-DD，缺省=当日；历史约从 2025-10 起。"""
        client = self._get_client()
        try:
            series = client.auctions.series(code, date) if date else client.auctions.series(code)
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError("auction", f"auctions.series({code},{date}) 失败: {exc}") from exc
        points = list(getattr(series, "points", []) or [])
        out = []
        for p in points:
            tl = getattr(p, "time_label", None)
            if not tl:
                continue
            out.append(
                AuctionPoint(
                    time_label=str(tl),
                    price=float(getattr(p, "price", 0.0) or 0.0),
                    matched_volume=float(getattr(p, "matched_volume", 0.0) or 0.0),
                    unmatched_volume=float(getattr(p, "unmatched_volume", 0.0) or 0.0),
                )
            )
        return out

    def opening_match(self, code: str, date: str | None = None) -> Optional[OpeningMatch]:
        """09:25 正式撮合。date 为空或等于当日 → today 接口；否则走历史接口。"""
        client = self._get_client()
        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        try:
            if date and date != today:
                om = client.trades.opening_match_history(code, date)
            else:
                om = client.trades.opening_match_today(code)
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError("opening_match", f"opening_match({code},{date}) 失败: {exc}") from exc
        if om is None:
            return None
        return OpeningMatch(
            price=float(getattr(om, "price", 0.0) or 0.0),
            volume=float(getattr(om, "volume", 0.0) or 0.0),
            time_label=str(getattr(om, "time_label", "09:25")),
        )

    # ---------- 分钟 K（策略二/三） ----------
    def minute_bars(self, code: str, period: str = "1m", count: int = 240) -> list[MinuteBar]:
        """分钟 K 线。period 支持 1m/5m/15m/30m/60m；count 为根数。"""
        client = self._get_client()
        try:
            bars = client.bars.get(code, period=period, count=count)
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError("bars", f"bars.get({code},{period}) 失败: {exc}") from exc
        items = list(getattr(bars, "bars", []) or [])
        out = []
        for b in items:
            out.append(
                MinuteBar(
                    ts=datetime.fromisoformat(str(getattr(b, "time", ""))) if getattr(b, "time", None) else datetime.now(timezone.utc),
                    open=float(getattr(b, "open", 0.0) or 0.0),
                    high=float(getattr(b, "high", 0.0) or 0.0),
                    low=float(getattr(b, "low", 0.0) or 0.0),
                    close=float(getattr(b, "close", 0.0) or 0.0),
                    volume_lots=float(getattr(b, "volume_lots", 0.0) or 0.0),
                    amount=float(getattr(b, "amount", 0.0) or 0.0),
                )
            )
        return out
