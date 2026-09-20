"""策略一：竞价主力抢筹（原 strategies.py + pipeline.py 合并迁移）。

用户规则（docs/USER_KNOWLEDGE.md §3，2026-09-05 确认）：
1. 候选 = 竞价成交额前 10（已按 60/00、非 ST 过滤）
2. 9:20 价格低于昨收（低于 0 轴）
3. 9:25 价格高于 9:20
4. 9:25 相对 9:20 上涨 ≥ 2%
5. 9:25 相对昨收涨幅 < 5%

策略阈值与候选数来自配置中心（量化配置页可改、热生效）；
规则不得由实现者自行改写。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .. import config_registry
from ..advice import Advice, build_advice
from ..cycle import CycleJudgement, CycleThresholds, DEFAULT_THRESHOLDS, classify, compute_indicators, strategy_gate
from ..datasource.resolve import (
    data_session,
    standard_auction_top_amount,
    standard_monitor_stocks,
)
from ..factors import AuctionFactor, build_auction_factors
from ..models import MonitorStock
from ..risk import run_risk_checks
from ..store import persist_report
from .base import Strategy, StrategyResult, register

if TYPE_CHECKING:
    from ..config import Settings


class PipelineReport(BaseModel):
    strategy: str
    data_date: str
    ran_at: datetime
    candidates: int
    factors: list[AuctionFactor] = Field(default_factory=list)
    results: dict[str, StrategyResult] = Field(default_factory=dict)
    advices: list[Advice] = Field(default_factory=list)
    blocked: list[dict] = Field(default_factory=list)
    risk_source_note: str = ""
    cycle_state: str = ""
    cycle_reasons: list[str] = Field(default_factory=list)
    cycle_position_factor: float = 1.0
    config_version: int = 0  # 运行时 active.json 版本（复盘按参数版本分组用）


@register
class AuctionGrabStrategy(Strategy):
    """竞价主力抢筹：竞价阶段直接产出完整建议（数据→因子→策略→风控→建议）。"""

    strategy_id = "auction_grab"
    label = "竞价主力抢筹"
    has_auction_advice = True

    params_schema = [
        {
            "key": "min_rise",
            "label": "9:20→9:25 最小拉升",
            "type": "percent",
            "default": 0.02,
            "min": 0.0,
            "max": 0.20,
            "step": 0.001,
            "desc": "9:25 价格相对 9:20 的最小涨幅，默认 2%（用户定义 2026-09-05）",
        },
        {
            "key": "max_chg_925",
            "label": "9:25 最高涨幅",
            "type": "percent",
            "default": 0.05,
            "min": 0.0,
            "max": 0.30,
            "step": 0.001,
            "desc": "9:25 相对昨收的最大涨幅，达到即放弃（追高风险），默认 5%",
        },
        {
            "key": "limit",
            "label": "竞价候选数",
            "type": "int",
            "default": 10,
            "min": 1,
            "max": 30,
            "step": 1,
            "unit": "只",
            "desc": "按竞价成交额取前 N 名作为候选池",
        },
        {
            "key": "base_position_pct",
            "label": "基准单票仓位",
            "type": "percent",
            "default": 0.2,
            "min": 0.05,
            "max": 0.5,
            "step": 0.05,
            "desc": "单票建议仓位基数，实际 = 此值 × 周期系数（M3 仓位梯度，默认 20%）",
        },
    ]

    def __init__(self, min_rise: float = 0.02, max_chg_925: float = 0.05):
        """阈值可显式注入（测试用）；生产路径走配置中心（见 run_auction_pipeline）。"""
        self.min_rise = min_rise
        self.max_chg_925 = max_chg_925

    def evaluate(self, f: AuctionFactor, *, min_rise: float | None = None,
                 max_chg_925: float | None = None) -> StrategyResult:
        r = StrategyResult()
        min_rise = self.min_rise if min_rise is None else min_rise
        max_chg_925 = self.max_chg_925 if max_chg_925 is None else max_chg_925
        # 数据完整性
        if f.errors:
            r.rejected.append(f"数据不完整: {'; '.join(f.errors[:2])}")
            return r
        if f.p920 is None or f.p925 is None or not f.pre_close:
            r.rejected.append("缺少 9:20/9:25/昨收数据")
            return r
        # 条件 2：9:20 低于 0 轴（昨收）
        if not (f.p920 < f.pre_close):
            r.rejected.append(f"9:20 未低于昨收（{f.p920:.2f} >= {f.pre_close:.2f}）")
            return r
        r.passed.append(f"9:20={f.p920:.2f} 低于昨收 {f.pre_close:.2f}")
        # 条件 3+4：9:25 相对 9:20 上涨 ≥ 2%
        if f.rise_920_925 is None or f.rise_920_925 < min_rise:
            pct = f"{f.rise_920_925 * 100:.2f}%" if f.rise_920_925 is not None else "无"
            r.rejected.append(f"9:20→9:25 涨幅不足（{pct} < {min_rise * 100:.0f}%）")
            return r
        r.passed.append(f"9:20→9:25 上涨 {f.rise_920_925 * 100:.2f}%")
        # 条件 5：9:25 相对昨收 < 5%
        if f.chg_925 is None or f.chg_925 >= max_chg_925:
            pct = f"{f.chg_925 * 100:.2f}%" if f.chg_925 is not None else "无"
            r.rejected.append(f"9:25 涨幅过高（{pct} >= {max_chg_925 * 100:.0f}%）")
            return r
        r.passed.append(f"9:25 涨幅 {f.chg_925 * 100:.2f}% < 5%")
        r.signal = True
        return r

    def run_auction_pipeline(self, settings: "Settings", date: str | None = None, limit: int | None = None,
                             thresholds: CycleThresholds = DEFAULT_THRESHOLDS,
                             *, persist: bool = True) -> PipelineReport:
        """竞价主力抢筹端到端。

        情绪周期门控：禁用态（退潮/冰点）→ 直接返回否决报告（不出建议）。
        thresholds 可注入（测试/调参用）；默认为用户确认值。
        persist=False 为沙箱模式：只算不落盘（量化配置页在线测试用）。
        """
        date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        params = config_registry.get_params(settings, self.strategy_id)
        cfg_ver = int(config_registry.load_active(settings).get("version") or 0)
        if limit is None:
            limit = int(params["limit"])
        min_rise = params["min_rise"]
        max_chg_925 = params["max_chg_925"]

        # ---- 情绪周期全局门控 ----
        cycle_j: CycleJudgement | None = None
        gate_ok, gate_factor, gate_note = True, 1.0, ""
        try:
            indicators = compute_indicators(settings, date)
            cycle_j = classify(indicators, thresholds)
            gate_ok, gate_factor, gate_note = strategy_gate(cycle_j.state, self.label, cycle_j.overheated)
        except Exception as exc:  # noqa: BLE001
            gate_note = f"情绪周期计算失败（{exc}），门控放行但需人工复核"

        if not gate_ok:
            report = PipelineReport(
                strategy=self.label, data_date=date, ran_at=datetime.now(timezone.utc),
                candidates=0, risk_source_note=f"情绪周期否决：{gate_note}",
                cycle_state=cycle_j.state.value if cycle_j else "",
                cycle_reasons=cycle_j.reasons if cycle_j else [gate_note],
                cycle_position_factor=0.0, config_version=cfg_ver,
            )
            if persist:
                _persist(settings, date, report)
            return report

        # ---- ① 数据 → ② 因子 ----
        with data_session(settings):
            rank = standard_auction_top_amount(settings, limit=limit)
            factors = build_auction_factors(settings, rank, date)

        # 监管名单（风控输入）
        monitors: list[MonitorStock] = []
        risk_note = ""
        try:
            monitors = standard_monitor_stocks(settings)
        except Exception as exc:  # noqa: BLE001
            risk_note = f"监管名单获取失败（{exc}），黑名单检查降级为空名单"

        report = PipelineReport(
            strategy=self.label, data_date=date, ran_at=datetime.now(timezone.utc),
            candidates=len(factors), factors=factors, risk_source_note=risk_note,
            cycle_state=cycle_j.state.value if cycle_j else "",
            cycle_reasons=cycle_j.reasons if cycle_j else [gate_note],
            cycle_position_factor=gate_factor, config_version=cfg_ver,
        )

        # ---- ③ 策略 → ④ 风控 → ⑤ 建议 ----
        for f in factors:
            sr = self.evaluate(f, min_rise=min_rise, max_chg_925=max_chg_925)
            report.results[f.thscode] = sr
            if sr.signal:
                checks = run_risk_checks(f.thscode, monitors)
                hard_fail = [c for c in checks if not c.passed and c.hard_block]
                notes = [f"{c.name}: {c.detail}" for c in checks if c.hard_block or not c.passed]
                if hard_fail:
                    report.blocked.append(
                        {"thscode": f.thscode, "name": f.name, "reasons": [c.detail for c in hard_fail]}
                    )
                else:
                    adv = build_advice(f, sr, notes)
                    # 仓位梯度（M3）：基准仓位 × 周期系数（替代旧"待确认×情绪系数"文案）
                    from ..portfolio import position_display

                    base_pct = float(params["base_position_pct"])
                    pos_pct, pos_text = position_display(base_pct, gate_factor)
                    adv.position_pct = pos_pct
                    adv.position = pos_text
                    report.advices.append(adv)

        # ---- ⑥ 组合风控（M3）：单票去重 + 总仓位上限 ----
        from ..portfolio import apply_portfolio_limits

        apply_portfolio_limits(report.advices, settings)

        # ---- ⑦ 记录 ----
        if persist:
            _persist(settings, date, report)
        return report


def _persist(settings: "Settings", date: str, report: PipelineReport) -> None:
    persist_report(settings, date, "auction_grab", report)


def run_auction_grab(settings: "Settings", date: str | None = None, limit: int | None = None,
                     thresholds: CycleThresholds = DEFAULT_THRESHOLDS, *, persist: bool = True) -> PipelineReport:
    """兼容入口：调度器/沙箱使用。等价于注册表实例的 run_auction_pipeline。"""
    from . import get_strategy

    return get_strategy("auction_grab").run_auction_pipeline(
        settings, date=date, limit=limit, thresholds=thresholds, persist=persist
    )
