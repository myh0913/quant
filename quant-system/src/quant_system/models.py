"""统一数据模型（Pydantic）。字段名与单位在此固定，策略层不直接面对供应商字段。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AuctionRankRow(BaseModel):
    """竞价成交额排名行（策略一核心）。"""

    thscode: str = Field(..., description="带交易所后缀代码，内部标准 .SH/.SZ（如 600540.SH / 000001.SZ）；选股通 .SS 必须归一为 .SH")
    ticker: str = Field(..., description="6 位纯代码")
    name: str = Field(..., description="股票名称")
    auction_amount_yuan: float = Field(..., description="竞价成交额，单位元")
    auction_pct: Optional[float] = Field(None, description="竞价涨跌幅，小数（0.035=+3.5%）")
    auction_price: Optional[float] = Field(None, description="竞价价格，单位元")
    open_price: Optional[float] = Field(None, description="开盘价，单位元")
    pre_close: Optional[float] = Field(None, description="昨收价，单位元")
    source: str = Field(..., description="数据源标识：eltdx / tdx_tqlex / hithink")
    data_date: str = Field(..., description="数据所属交易日 YYYY-MM-DD")
    ts: datetime = Field(..., description="采集时间")


class AuctionPoint(BaseModel):
    """集合竞价过程点（9:15-9:25 逐点）。"""

    time_label: str = Field(..., description="时间标签，如 09:20:00")
    price: float = Field(..., description="竞价价，单位元")
    matched_volume: float = Field(..., description="虚拟成交量，单位手")
    unmatched_volume: float = Field(..., description="未匹配量，单位手")


class OpeningMatch(BaseModel):
    """9:25 正式撮合。"""

    price: float = Field(..., description="成交价，单位元")
    volume: float = Field(..., description="成交量，单位手")
    time_label: str = Field(..., description="09:25")


class MinuteBar(BaseModel):
    """分钟 K 线。"""

    ts: datetime = Field(..., description="K 线时间")
    open: float
    high: float
    low: float
    close: float
    volume_lots: float = Field(..., description="成交量，单位手")
    amount: float = Field(..., description="成交额，单位元")


class LimitUpStock(BaseModel):
    """涨停池条目。"""

    thscode: str
    name: str
    limit_up_time: Optional[str] = Field(None, description="首次涨停时间 HH:MM 或 HH:MM:SS")
    continue_day_cnt: Optional[int] = Field(None, description="连板天数")
    seal_money: Optional[float] = Field(None, description="封单额，单位元")
    limit_up_reason: Optional[str] = Field(None, description="涨停原因")
    is_st: bool = False
    is_new: bool = False


class ThemeRank(BaseModel):
    """题材排名条目（选股通）。"""

    plate_id: int
    name: str
    description: Optional[str] = None
    rank: int = Field(..., description="当日排名（1 起）")
    core_avg_pcp: Optional[float] = Field(None, description="核心股平均涨跌幅，小数")
    ts: datetime


class MonitorStock(BaseModel):
    """东财重点监控/异动条目。"""

    thscode: Optional[str] = None
    name: str
    monitor_type: Literal["restricted", "severe", "unusual"] = Field(
        ..., description="restricted=重点监控 / severe=严重异常波动 / unusual=异常波动"
    )
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notice_date: Optional[str] = None
    reason: Optional[str] = None
    info_code: Optional[str] = None
    source: str = "eastmoney"
