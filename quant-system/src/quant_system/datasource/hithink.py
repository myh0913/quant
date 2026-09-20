"""Financial API（同花顺 fuyao）适配器。

认证：REST 请求头 X-api-key（从 .env 的 HITHINK_FINANCE_API_KEY 读取）。
Base URL：https://fuyao.aicubes.cn
错误码：code=2001 key 缺失/无效；code=2003 无权访问；业务成功 code=0。
已实测（2026-09-05/06）：竞价快照、历史日K、涨停/跌停/炸板池、连板天梯、
龙虎榜、热榜、财务三大表、估值、指数/成分、复权因子、交易日历均可用。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Settings
from ..models import LimitUpStock
from .base import BaseDataSource, AuthError, DataSourceError, request_with_retry

BASE = "https://fuyao.aicubes.cn"


class HithinkSource(BaseDataSource):
    source_name = "hithink"

    def __init__(self, settings: Settings):
        super().__init__(settings.raw_dir)
        self._settings = settings
        self._api_key: Optional[str] = None

    def _headers(self) -> dict:
        if self._api_key is None:
            self._api_key = self._settings.require_hithink()
        return {"X-api-key": self._api_key, "User-Agent": "quant-system/0.1"}

    # ---------- 通用 GET ----------
    def _get(self, path: str, params: dict | None = None, name: str = "data", timeout: int = 30):
        resp, meta = request_with_retry(
            "GET",
            BASE + path,
            raw_dir=self.raw_dir,
            source=self.source_name,
            name=name,
            params=params,
            headers=self._headers(),
            timeout=timeout,
        )
        body = resp.json()
        code = body.get("code")
        if code != 0:
            msg = str(body.get("message", ""))[:120]
            if code == 2001:
                raise AuthError(f"{path} -> {msg}")
            raise DataSourceError("api", f"{path} -> code={code} {msg}", retriable=code in (2003,))
        return body.get("data") or {}, meta

    # ---------- 竞价快照（策略一校验源） ----------
    def auction_snapshot(self, thscodes: list[str], stage: str = "final") -> list[dict]:
        """批量竞价快照。stage=final 终态 / live 实时；单批 1-100 只；当日无历史参数。"""
        if not thscodes:
            return []
        data, meta = self._get(
            "/api/a-share/auction/snapshot",
            {"thscodes": ",".join(thscodes), "stage": stage},
            name=f"auction_{stage}_{len(thscodes)}",
        )
        return list(data.get("item", []) or [])

    # ---------- 历史日 K ----------
    def daily_bars(self, thscode: str, start_ms: int, end_ms: int, adjust: str = "none") -> list[dict]:
        """单股历史日 K。仅支持 1d；窗口 ≤10 年；每次一个 thscode。"""
        data, meta = self._get(
            "/api/a-share/prices/historical",
            {"thscode": thscode, "interval": "1d", "start": start_ms, "end": end_ms, "adjust": adjust},
            name=f"daily_{thscode}",
        )
        return list(data.get("item", []) or [])

    # ---------- 涨停/跌停/炸板池 ----------
    def limit_up_pool(self, date_ms: int | None = None, page: int = 1, size: int = 50,
                      sort_field: str = "continue_day_cnt", sort_dir: str = "desc") -> tuple[list[dict], dict]:
        """涨停池。date_ms=交易日 Asia/Shanghai 零点毫秒；支持历史日期。"""
        params = {"page": page, "size": size, "sort_field": sort_field, "sort_dir": sort_dir}
        if date_ms is not None:
            params["date_ms"] = date_ms
        data, meta = self._get("/api/a-share/special-data/limit-up-pool", params, name="limit_up_pool")
        return list(data.get("item", []) or []), data.get("pagination") or {}

    def limit_down_pool(self, date_ms: int | None = None, page: int = 1, size: int = 50) -> list[dict]:
        params = {"page": page, "size": size}
        if date_ms is not None:
            params["date_ms"] = date_ms
        data, _ = self._get("/api/a-share/special-data/limit-down-pool", params, name="limit_down_pool")
        return list(data.get("item", []) or [])

    def limit_break_pool(self, date_ms: int | None = None, page: int = 1, size: int = 50,
                         sort_field: str = "open_times", sort_dir: str = "desc") -> list[dict]:
        params = {"page": page, "size": size, "sort_field": sort_field, "sort_dir": sort_dir}
        if date_ms is not None:
            params["date_ms"] = date_ms
        data, _ = self._get("/api/a-share/special-data/limit-break-pool", params, name="limit_break_pool")
        return list(data.get("item", []) or [])

    def limit_up_ladder(self) -> dict:
        """近 30 个交易日连板梯队矩阵。"""
        data, _ = self._get("/api/a-share/special-data/limit-up-ladder", {}, name="ladder")
        return data

    # ---------- 市场总龙头（暂定：连板数最多） ----------
    def market_leader(self, date_ms: int | None = None) -> Optional[LimitUpStock]:
        """当前/指定日期连板数最高的股票。返回 None 表示无涨停。"""
        items, _ = self.limit_up_pool(date_ms=date_ms, size=10, sort_field="continue_day_cnt", sort_dir="desc")
        for it in items:
            cnt = it.get("continue_day_cnt") or 0
            if cnt <= 0:
                continue
            return LimitUpStock(
                thscode=it.get("thscode", ""),
                name=it.get("name", ""),
                limit_up_time=it.get("limit_up_time"),
                continue_day_cnt=cnt,
                seal_money=it.get("seal_money"),
                limit_up_reason=it.get("limit_up_reason"),
                is_st=bool(it.get("is_st")),
                is_new=bool(it.get("is_new")),
            )
        return None

    # ---------- 财务 ----------
    def income_statements(self, thscode: str, period: str = "annual", limit: int = 4) -> list[dict]:
        data, _ = self._get(
            "/api/a-share/financials/income-statements",
            {"thscode": thscode, "period": period, "limit": limit},
            name=f"income_{thscode}",
        )
        return list(data.get("item", []) or [])

    def valuation_snapshot(self, thscodes: list[str]) -> list[dict]:
        if not thscodes:
            return []
        data, _ = self._get(
            "/api/a-share/valuations/snapshot",
            {"thscodes": ",".join(thscodes)},
            name=f"valuation_{len(thscodes)}",
        )
        return list(data.get("item", []) or [])
