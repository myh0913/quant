"""竞价因子计算（策略一：竞价主力抢筹）。

因子层只做数值提取和计算，不做买卖判断；所有涨跌幅统一为小数。
数据经 resolve 能力层获取（auction_series / opening_match），不绑定具体源。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from .datasource.resolve import data_session, standard_auction_series, standard_opening_match
from .models import AuctionRankRow

if TYPE_CHECKING:
    from .config import Settings


class AuctionFactor(BaseModel):
    """单只股票的竞价因子快照（策略一所需全部字段）。"""

    thscode: str
    name: str
    rank: int = Field(..., description="竞价成交额排名（1 起）")
    auction_amount_yuan: float = Field(..., description="竞价成交额，元")
    pre_close: float = Field(..., description="昨收价，元")
    p920: Optional[float] = Field(None, description="09:20:00 竞价价格，元")
    p925: Optional[float] = Field(None, description="09:25 正式撮合价，元")
    rise_920_925: Optional[float] = Field(None, description="(p925-p920)/p920，小数")
    chg_925: Optional[float] = Field(None, description="(p925-pre_close)/pre_close，小数")
    below_zero_920: Optional[bool] = Field(None, description="09:20 价格是否低于昨收（0 轴）")
    data_date: str = Field(..., description="数据所属交易日 YYYY-MM-DD")
    errors: list[str] = Field(default_factory=list, description="取数失败记录，不阻断整体")


def build_auction_factors(
    settings: "Settings", rank_rows: list[AuctionRankRow], date: str
) -> list[AuctionFactor]:
    """为竞价成交额前 N 名逐只补齐 9:20/9:25 因子。

    每只股票发起 2 次请求（auction_series + opening_match）；
    单只失败记入 errors，不阻断整体。
    """
    factors: list[AuctionFactor] = []
    with data_session(settings):
        for idx, row in enumerate(rank_rows):
            f = AuctionFactor(
                thscode=row.thscode,
                name=row.name,
                rank=idx + 1,
                auction_amount_yuan=row.auction_amount_yuan,
                pre_close=row.pre_close or 0.0,
                data_date=date,
            )
            try:
                pts = standard_auction_series(settings, row.thscode, date)
                f.p920 = next(
                    (p.price for p in pts if p.time_label.startswith("09:20")), None
                )
            except Exception as exc:  # noqa: BLE001
                f.errors.append(f"auction_series: {exc}")
            try:
                om = standard_opening_match(settings, row.thscode, date)
                f.p925 = om.price if om else None
            except Exception as exc:  # noqa: BLE001
                f.errors.append(f"opening_match: {exc}")

            if f.p920 is not None and f.p925 is not None and f.pre_close:
                if f.p920:
                    f.rise_920_925 = (f.p925 - f.p920) / f.p920
                f.chg_925 = (f.p925 - f.pre_close) / f.pre_close
                f.below_zero_920 = f.p920 < f.pre_close
            factors.append(f)
    return factors
