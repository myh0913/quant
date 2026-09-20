"""建议模型与生成器：策略信号 + 风控通过 → 结构化建议草案。

仓位/止损/止盈规则待用户确认（规格书 §11.1），在建议中显式标注，不编造数值。
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .factors import AuctionFactor
from .strategy import StrategyResult


class Advice(BaseModel):
    """一条操作建议。字段对齐规格书 §4 的最低要求。"""

    thscode: str
    name: str
    strategy: str
    action: str = Field(..., description="买入建议 / 不参与")
    generated_at: datetime
    data_date: str
    reference_price: float | None = Field(None, description="参考价（9:25 撮合价），元")
    trigger_condition: str = ""
    position: str | None = Field(None, description="建议仓位（展示文案）")
    position_pct: float | None = Field(None, description="建议仓位比例（基准×周期系数，0-1；0=降级观察）")
    demoted: bool | None = Field(None, description="组合风控降级为观察（不下单）")
    portfolio_note: str = Field("", description="组合风控降级原因")
    stop_loss: str | None = Field(None, description="止损条件（待确认）")
    valid_until: str = ""
    factor_summary: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    pending_confirmations: list[str] = Field(default_factory=list)


def build_advice(f: AuctionFactor, sr: StrategyResult, risk_notes: list[str]) -> Advice:
    """生成建议草案。仓位由调用方按 基准×周期系数 填（M3）；止损仍标注待确认。"""
    pending: list[str] = []
    if sr.signal:
        pending.append("止损/止盈规则待确认")
    return Advice(
        thscode=f.thscode,
        name=f.name,
        strategy="竞价主力抢筹",
        action="买入建议" if sr.signal else "不参与",
        generated_at=datetime.now(timezone.utc),
        data_date=f.data_date,
        reference_price=f.p925,
        trigger_condition="竞价 9:25 满足：9:20 低于昨收 + 9:20→9:25 上涨≥2% + 9:25 涨幅<5%",
        position=None,
        stop_loss=None,
        valid_until="当日有效（建议模式默认）",
        factor_summary={
            "rank": f.rank,
            "auction_amount_yi": round(f.auction_amount_yuan / 1e8, 2),
            "p920": f.p920,
            "p925": f.p925,
            "pre_close": f.pre_close,
            "rise_920_925_pct": round(f.rise_920_925 * 100, 2) if f.rise_920_925 is not None else None,
            "chg_925_pct": round(f.chg_925 * 100, 2) if f.chg_925 is not None else None,
        },
        reasons=list(sr.passed) if sr.signal else [],
        risk_notes=risk_notes,
        pending_confirmations=pending,
    )
