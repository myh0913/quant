"""东财重点监控/异动适配器。

页面：https://vipmoney.eastmoney.com/collect/min_data/point_stock_monitor/index.html
三层接口（2026-09-06 实测）：
- 重点监控证券：mobappconfig.securities.eastmoney.com/emcfg/stock_monitor.json（最新，无历史）
- 严重异常波动：RPT_APP_UNUSUALBASIC filter=(UNUSUAL_TYPE="002")
- 普通异常波动：RPT_APP_UNUSUALBASIC filter=(UNUSUAL_TYPE="001")（约 9 万+ 条历史可分页）
约束：未声明商业授权，仅低频研究用途；需移动端 UA/Referer。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..models import MonitorStock
from ..pool import normalize_thscode
from .base import BaseDataSource, DataSourceError, request_with_retry

MOBCONFIG = "https://mobappconfig.securities.eastmoney.com"
DATACENTER = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
REFERER = "https://vipmoney.eastmoney.com/collect/min_data/point_stock_monitor/index.html"

_COMMON_COLUMNS = (
    "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,UNUSUAL_TYPE,START_DATE,END_DATE,"
    "INFO_CODE,NOTICE_DATE,UNUSUAL_REASON,UNUSUAL_REASON_TYPE,MRAKET_TYPE"
)


class EastmoneySource(BaseDataSource):
    source_name = "eastmoney"

    def __init__(self, settings):
        super().__init__(settings.raw_dir)

    # ---------- 重点监控证券（最新） ----------
    def restricted_stocks(self) -> list[MonitorStock]:
        """交易所重点监控证券（最新名单，无历史分页）。"""
        resp, meta = request_with_retry(
            "GET", MOBCONFIG + "/emcfg/stock_monitor.json",
            raw_dir=self.raw_dir, source=self.source_name, name="restricted",
            headers={"User-Agent": UA, "Referer": REFERER}, timeout=20,
        )
        rows = resp.json()
        if not isinstance(rows, list):
            raise DataSourceError("api", "重点监控返回非数组")
        out: list[MonitorStock] = []
        for r in rows:
            code = str(r.get("STKCODE", ""))
            market = str(r.get("MARKET", ""))
            thscode = ""
            if len(code) == 6:
                if market == "1":
                    thscode = code + ".SH"
                elif market == "0":
                    thscode = code + ".SZ"
                elif market == "B":
                    thscode = code + ".BJ"
            out.append(
                MonitorStock(
                    thscode=thscode or None,
                    name=str(r.get("STKNAME", "")),
                    monitor_type="restricted",
                    start_date=r.get("VALIDATESTARTDATE"),
                    end_date=r.get("VALIDATEENDDATE"),
                    source=self.source_name,
                )
            )
        return out

    # ---------- 异常波动体系（001 普通 / 002 严重） ----------
    def _unusual(
        self,
        unusual_type: str,
        page: int = 1,
        page_size: int = 50,
        is_his: Optional[str] = None,
    ) -> list[MonitorStock]:
        filt = f'(UNUSUAL_TYPE="{unusual_type}")'
        if is_his is not None:
            filt += f'(IS_HIS="{is_his}")'
        params = {
            "reportName": "RPT_APP_UNUSUALBASIC",
            "columns": _COMMON_COLUMNS + ',PREDICT_START_DATE,PREDICT_END_DATE,IS_HIS',
            "filter": filt,
            "sortColumns": "NOTICE_DATE,END_DATE",
            "sortTypes": "-1,-1",
            "pageNumber": page,
            "pageSize": page_size,
            "source": "SECURITIES",
            "client": "APP",
        }
        resp, meta = request_with_retry(
            "GET", DATACENTER,
            raw_dir=self.raw_dir, source=self.source_name,
            name=f"unusual_{unusual_type}_p{page}",
            params=params, headers={"User-Agent": UA, "Referer": REFERER}, timeout=20,
        )
        body = resp.json()
        result = body.get("result") or {}
        rows = result.get("data") or []
        out: list[MonitorStock] = []
        for r in rows:
            out.append(
                MonitorStock(
                    thscode=r.get("SECUCODE"),
                    name=str(r.get("SECURITY_NAME_ABBR", "")),
                    monitor_type=("severe" if unusual_type == "002" else "unusual"),
                    start_date=r.get("START_DATE"),
                    end_date=r.get("END_DATE"),
                    notice_date=r.get("NOTICE_DATE"),
                    reason=r.get("UNUSUAL_REASON"),
                    info_code=r.get("INFO_CODE"),
                    source=self.source_name,
                )
            )
        return out

    def severe_unusual(self, page: int = 1, page_size: int = 50) -> list[MonitorStock]:
        """严重异常波动（002）。"""
        return self._unusual("002", page=page, page_size=page_size)

    def unusual(self, page: int = 1, page_size: int = 50) -> list[MonitorStock]:
        """普通异常波动（001）。"""
        return self._unusual("001", page=page, page_size=page_size)