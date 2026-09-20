"""龙回头·尾盘选股（14:45 当日候选）。

用户规则（2026-09-19 修订）：
- 基础：T-1 为 ≥2 连板波的波末板（与盘后龙回头建池同源的连板波判定，
  只是"首阴"从 T-1 已收盘 K 线换成 T 日盘中正在形成的阴线）+ 排除三板组
- 通用前提：现价 < 今开（当日 K 线正在收阴）
- 量能排除（高开场景共用上限）：今日成交量 > 连板日最高成交量 × 1.5 → 拒
- 场景A 高开回踩（高开 ≥ +3%）：
  1. 9:30→9:33 最高价 = 开盘价（开盘后 3 分钟未冲高）
  2. 截至 9:33 的当日最低点 ≤ -2%（相对昨收；高开后快速杀至深水）
  3. 9:33 → 14:45 最高价到最低价的波动幅度 ≤ 3%（振幅=区间高低差/昨收）
- 场景B 低开收敛（低开 ≤ -2%）：
  1. 今日成交量 < 连板日最高成交量 × 0.8（低开缩量）
  2. 截至尾盘全天最高到最低的波动幅度 ≤ 3%
- 场景C 平开低走（-2% ~ +3%，2026-09-19 新增）：
  1. 今日成交量 < 连板日最高成交量 × 1.0
  2. 9:30→9:33 最高价 = 开盘价（未冲高）
  3. 9:33 时点价格 ≤ -2%（开盘后 3 分钟内跌至深水）
  4. 9:33 → 14:45 区间振幅 ≤ 3%

与盘后建池的差异：首阴判定对象是 T 日盘中（未走完）；
也不做竞价场景分类与盘中承接确认（14:45 一次性产出，服务当日尾盘）。

单位口径（2026-09-18 实测）：hithink 日线 volume=股，eltdx 分时 volume=手，
换算 MINUTE_VOL_TO_SHARES=100（三只样本 ratio=0.0100）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from .. import config_registry
from ..analyzer import MORNING_CUTOFF, DailyBarAnalyzer
from ..datasource.resolve import (
    data_session,
    standard_daily_bars,
    standard_limit_up_pool,
    standard_minute_points,
    standard_opening_match,
    standard_pre_close,
)
from .base import Strategy, register

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger(__name__)

# 分时累计量（手）→ 股（与 hithink 日线 volume 同单位）；2026-09-18 实测换算系数
MINUTE_VOL_TO_SHARES = 100.0


class TailpanCandidate(BaseModel):
    """尾盘选股候选（T-1 连板波 + T 日盘中规则过滤后）。"""

    thscode: str
    name: str
    boards: int = 0
    scene: Optional[str] = Field(None, description="A=高开回踩 / B=低开收敛 / C=平开低走")
    open_pct: Optional[float] = Field(None, description="今开/昨收-1")
    morning_low_pct: Optional[float] = Field(None, description="场景A：截至09:33最低点/昨收-1")
    pct_933: Optional[float] = Field(None, description="9:33 时点价格涨幅（场景C判定用）")
    range_pct: Optional[float] = Field(None, description="判定区间振幅（A/C=9:33后区间 / B=全天）")
    volume_ratio: Optional[float] = Field(None, description="今日量/连板日最大量")
    last_pct: Optional[float] = Field(None, description="现价/昨收-1")
    last_price: Optional[float] = None
    notes: list[str] = Field(default_factory=list)
    position_pct: Optional[float] = Field(None, description="建议仓位（基准×周期系数，M3）")
    demoted: Optional[bool] = Field(None, description="组合风控降级为观察")
    portfolio_note: str = ""
    rejected: bool = False
    reject_reason: str = ""


def evaluate_tailpan(
    thscode: str,
    name: str,
    boards: int,
    open_price: float,
    pre_close: float,
    points: list[dict],
    params: dict,
    wave_max_volume: float = 0.0,
) -> TailpanCandidate:
    """对单只票应用尾盘规则（纯逻辑，可单测）。

    params:
      min_open_pct（场景A高开下限，正小数）、morning_low_pct（9:33 深水阈值，负小数，
      场景A=截至9:33最低、场景C=9:33时点价格）、low_open_pct（场景B低开上限，负小数）、
      range_pct（区间振幅上限，正小数）、volume_ratio_max（高开场景今日量/连板峰值上限）、
      low_open_volume_ratio（场景B量能上限）、flat_volume_ratio（场景C量能上限）。
    wave_max_volume: 连板交易日最大成交量（股，日线口径）；<=0 时跳过量能检查。
    """
    cand = TailpanCandidate(thscode=thscode, name=name, boards=boards)
    if not open_price or not pre_close or not points:
        cand.rejected, cand.reject_reason = True, "竞价/昨收/分时数据缺失"
        return cand

    open_pct = (open_price - pre_close) / pre_close
    pts = [p for p in points if p["price"] > 0]
    early = [p for p in pts if p["time_label"] <= MORNING_CUTOFF]
    if not early:
        cand.rejected, cand.reject_reason = True, f"{MORNING_CUTOFF}前无分时数据"
        return cand
    morning_low_pct = (min(p["price"] for p in early) - pre_close) / pre_close
    # 9:33 时点价格（early 最后一根即 09:33 当根；数据缺根时取最后可得根）
    pct_933 = (early[-1]["price"] - pre_close) / pre_close
    # 9:30→9:33 区间最高价（分时无 bar 最高价，用分钟价近似；"最高价是开盘价"
    # 语义 = 开盘后 3 分钟未冲高：区间最高 ≤ 开盘价 + 微小容差）
    early_hi = max(p["price"] for p in early)
    rushed = early_hi > open_price * (1 + 1e-6)

    last = pts[-1]
    last_pct = (last["price"] - pre_close) / pre_close
    cand.open_pct = open_pct
    cand.morning_low_pct, cand.pct_933 = morning_low_pct, pct_933
    cand.last_pct, cand.last_price = last_pct, last["price"]

    def _amp(seg: list[dict]) -> float:
        """区间振幅 =（区间最高-区间最低）/昨收。"""
        hi, lo = max(p["price"] for p in seg), min(p["price"] for p in seg)
        return (hi - lo) / pre_close

    # 通用前提：现价 < 今开（当日正在收阴）
    if last["price"] >= open_price:
        cand.rejected, cand.reject_reason = True, (
            f"现价不低于今开（现价{last_pct*100:.2f}% ≥ 开盘{open_pct*100:.2f}%，未走阴）"
        )
        return cand

    # 今日量（股）与连板峰值比；高开场景共用上限，B/C 分支有更严上限
    vr: Optional[float] = None
    if wave_max_volume > 0:
        today_vol = sum(float(p.get("volume") or 0) for p in pts) * MINUTE_VOL_TO_SHARES
        vr = today_vol / wave_max_volume
        cand.volume_ratio = vr
        if vr > float(params["volume_ratio_max"]):
            cand.rejected, cand.reject_reason = True, (
                f"今日量超连板峰值（{vr:.2f}x > {float(params['volume_ratio_max'])}x，放量过猛）"
            )
            return cand

    min_open = float(params["min_open_pct"])
    range_max = float(params["range_pct"])
    after = [p for p in pts if p["time_label"] >= MORNING_CUTOFF]
    if open_pct >= min_open:
        # 场景A：高开回踩
        if rushed:
            cand.scene, cand.range_pct = "A", _amp(after)
            cand.rejected, cand.reject_reason = True, (
                f"9:33前冲高（9:30-9:33最高{early_hi:.2f} > 开盘{open_price:.2f}）"
            )
            return cand
        low_max = float(params["morning_low_pct"])
        if morning_low_pct > low_max:
            cand.rejected, cand.reject_reason = True, (
                f"9:33前低点未达深水（{morning_low_pct*100:.2f}% > {low_max*100:.0f}%）"
            )
            return cand
        amp = _amp(after)
        cand.scene, cand.range_pct = "A", amp
        if amp > range_max:
            cand.rejected, cand.reject_reason = True, (
                f"9:33后振幅过大（{amp*100:.2f}% > {range_max*100:.0f}%）"
            )
            return cand
        cand.notes = [
            f"前波{boards}连板",
            f"高开{open_pct*100:+.2f}%",
            "开盘3分钟未冲高",
            f"9:33前低点{morning_low_pct*100:.2f}%",
            f"9:33后振幅{amp*100:.2f}%",
            f"量比{vr:.2f}x" if vr is not None else "量能基准缺失",
            f"现价{last_pct*100:+.2f}%",
        ]
        return cand

    low_open = float(params["low_open_pct"])
    low_vr_max = float(params["low_open_volume_ratio"])
    flat_vr_max = float(params["flat_volume_ratio"])
    if open_pct <= low_open:
        # 场景B：低开收敛（低开缩量 + 全天振幅收敛）
        if vr is not None and vr >= low_vr_max:
            cand.scene = "B"
            cand.rejected, cand.reject_reason = True, (
                f"低开量能偏大（{vr:.2f}x ≥ {low_vr_max}x）"
            )
            return cand
        amp = _amp(pts)
        cand.scene, cand.range_pct = "B", amp
        if amp > range_max:
            cand.rejected, cand.reject_reason = True, (
                f"全天振幅过大（{amp*100:.2f}% > {range_max*100:.0f}%）"
            )
            return cand
        cand.notes = [
            f"前波{boards}连板",
            f"低开{open_pct*100:+.2f}%",
            f"量比{vr:.2f}x" if vr is not None else "量能基准缺失",
            f"全天振幅{amp*100:.2f}%",
            f"现价{last_pct*100:+.2f}%",
        ]
        return cand

    # 场景C：平开低走（-2% ~ +3%）：缩量 + 未冲高 + 9:33 深水 + 其后收敛
    if vr is not None and vr >= flat_vr_max:
        cand.scene = "C"
        cand.rejected, cand.reject_reason = True, (
            f"平开量能偏大（{vr:.2f}x ≥ {flat_vr_max}x）"
        )
        return cand
    if rushed:
        cand.scene = "C"
        cand.rejected, cand.reject_reason = True, (
            f"9:33前冲高（9:30-9:33最高{early_hi:.2f} > 开盘{open_price:.2f}）"
        )
        return cand
    c_deep = float(params["morning_low_pct"])
    if pct_933 > c_deep:
        cand.scene = "C"
        cand.rejected, cand.reject_reason = True, (
            f"9:33未至深水（{pct_933*100:.2f}% > {c_deep*100:.0f}%）"
        )
        return cand
    amp = _amp(after)
    cand.scene, cand.range_pct = "C", amp
    if amp > range_max:
        cand.rejected, cand.reject_reason = True, (
            f"9:33后振幅过大（{amp*100:.2f}% > {range_max*100:.0f}%）"
        )
        return cand
    cand.notes = [
        f"前波{boards}连板",
        f"平开{open_pct*100:+.2f}%",
        f"量比{vr:.2f}x" if vr is not None else "量能基准缺失",
        "开盘3分钟未冲高",
        f"9:33价格{pct_933*100:.2f}%",
        f"9:33后振幅{amp*100:.2f}%",
        f"现价{last_pct*100:+.2f}%",
    ]
    return cand


def build_tailpan_candidates(
    settings: "Settings", prev: str, cur: str
) -> tuple[list[TailpanCandidate], list[TailpanCandidate]]:
    """T 日 14:45 尾盘建池：T-1 涨停池（≥2连板）→ 日线确认波末紧邻 → 盘中 3 条规则。

    与盘后建池的圈池方向不同：波末在 T-1（昨天还在涨停池里），直接取
    T-1 涨停池 continue_day_cnt ≥ 2 的票即可，无需回溯多日。
    """
    from ..pool import is_target_stock
    from ..snapshot import SnapshotMissing

    p = config_registry.get_params(settings, "tailpan")

    pool = [
        it for it in standard_limit_up_pool(settings, prev)
        if int(it.get("continue_day_cnt") or 0) >= 2
        # 只做 60/00 主板、非 ST（创业板/科创板/北交所/可转债不参与，2026-09-17）
        and is_target_stock(it.get("thscode", ""), it.get("name", ""))
    ]

    passed: list[TailpanCandidate] = []
    rejected: list[TailpanCandidate] = []

    with data_session(settings):
        for it in pool:
            thscode, nm = it.get("thscode", ""), it.get("name", "")
            if not thscode:
                continue
            bars = standard_daily_bars(settings, thscode, prev, lookback_days=60)
            if len(bars) < 10:
                rejected.append(TailpanCandidate(
                    thscode=thscode, name=nm, rejected=True, reject_reason="日线不足"))
                continue
            az = DailyBarAnalyzer(bars)
            if az.has_suspect_day():
                rejected.append(TailpanCandidate(
                    thscode=thscode, name=nm, rejected=True,
                    reject_reason="日线疑似除权/数据异常（单日涨跌幅越界）"))
                continue
            w = az.current_wave()  # 波末必须紧邻 T-1（昨日是波末板）
            if w is None or w.days < 2:
                continue  # 与涨停池连板口径不符，非本策略对象（静默跳过）
            # 排除三板组（2026-09-19：与盘后建池同口径）
            if az.is_sanbanzu():
                rejected.append(TailpanCandidate(
                    thscode=thscode, name=nm, boards=w.days,
                    rejected=True, reject_reason="三板组"))
                continue
            try:
                om = standard_opening_match(settings, thscode, cur)
                pre = standard_pre_close(settings, thscode, cur)
                points = standard_minute_points(settings, thscode, cur)
            except SnapshotMissing:
                raise  # 回放模式快照缺失必须上浮（否则静默得出 0 候选的假成功）
            except Exception:  # noqa: BLE001
                rejected.append(TailpanCandidate(
                    thscode=thscode, name=nm, boards=w.days,
                    rejected=True, reject_reason="今日行情获取失败"))
                continue
            # 连板交易日最大成交量（股，日线口径）——今日量能排除的基准
            wave_max_vol = max((d.volume for d in az.days[w.start_idx:w.end_idx + 1]), default=0.0)
            cand = evaluate_tailpan(
                thscode, nm, w.days, om.price if om else 0.0, pre, points, p,
                wave_max_volume=wave_max_vol)
            (rejected if cand.rejected else passed).append(cand)
    return passed, rejected


def select_tailpan(settings: "Settings", today: str, prev: str) -> dict:
    """尾盘选股纯函数：周期门控 + 建池 + 风控，返回报告 dict（不落盘/不通知）。

    生产（run_tailpan_pool）与回测（backtest.py）共用同一套规则。
    """
    from ..cycle import classify, compute_indicators, strategy_gate
    from ..risk import run_risk_checks

    # 情绪周期门控（与龙回头同池：退潮/冰点否决，分歧减仓不否决）
    try:
        cycle_j = classify(compute_indicators(settings, today))
        gate_ok, gate_factor, gate_note = strategy_gate(cycle_j.state, "龙回头", cycle_j.overheated)
        gate_state = cycle_j.state.value
    except Exception as exc:  # noqa: BLE001
        gate_ok, gate_factor, gate_note = True, 1.0, f"周期计算失败（{exc}）放行待复核"
        gate_state = "unknown"
    report = {
        "type": "tailpan_pool", "date": today, "prev": prev,
        "candidates": [], "rejected": [],
        "gate_state": gate_state, "gate_note": gate_note,
        "gate_factor": gate_factor, "gate_ok": gate_ok,
    }
    if not gate_ok:
        return report

    passed, rejected = build_tailpan_candidates(settings, prev, today)

    # 风控：监管黑名单（东财重点监控+严重异常）硬否决
    monitors: list = []
    try:
        from ..datasource.resolve import standard_monitor_stocks

        monitors = standard_monitor_stocks(settings)
    except Exception:  # noqa: BLE001
        pass  # 回测历史日无监管名单快照 → 风控跳过（已知局限）
    still: list[TailpanCandidate] = []
    for c in passed:
        hard = [chk for chk in run_risk_checks(c.thscode, monitors) if not chk.passed and chk.hard_block]
        if hard:
            c.rejected, c.reject_reason = True, f"风控拦截：{hard[0].detail}"
            rejected.append(c)
        else:
            still.append(c)

    # 仓位梯度（M3）：基准仓位 × 周期系数 + 组合约束（单票去重/总仓位上限）
    from ..portfolio import apply_portfolio_limits, position_display

    base_pct = float(config_registry.get_params(settings, "tailpan")["base_position_pct"])
    pos_pct, _text = position_display(base_pct, gate_factor)
    for c in still:
        c.position_pct = pos_pct
    apply_portfolio_limits(still, settings)

    report["candidates"] = [c.model_dump() for c in still]
    report["rejected"] = [c.model_dump() for c in rejected]
    return report


def run_tailpan_pool(settings: "Settings", today: str, prev: str) -> str:
    """14:45 尾盘任务主体：选股（select_tailpan）+ 落盘 + 通知（调度器只管窗口与状态）。"""
    from ..notify import notify
    from ..store import persist_report

    report = select_tailpan(settings, today, prev)
    persist_report(settings, today, "tailpan_pool", report)
    n_pass, n_rej = len(report["candidates"]), len(report["rejected"])
    if not report["gate_ok"]:
        text = f"[尾盘 {today}] 周期否决（{report['gate_note']}），本轮不选股"
        log.warning(text)
    else:
        text = f"[尾盘 {today}] 龙回头尾盘候选 {n_pass}（拒 {n_rej}）周期={report['gate_state']}"
        log.info(text)
    notify(text, "尾盘选股")
    return text


# ============================== 注册表适配 ==============================


@register
class TailpanStrategy(Strategy):
    """龙回头·尾盘：14:45 当日盘中建池。

    不参与竞价/盘后建池/盘中确认三阶段（has_* 全 False），注册仅为
    参数 schema 进配置中心（量化配置页可改阈值，热生效）。
    """

    strategy_id = "tailpan"
    label = "龙回头·尾盘"

    params_schema = [
        {
            "key": "min_open_pct",
            "label": "场景A 高开下限",
            "type": "percent",
            "default": 0.03,
            "min": 0.005,
            "max": 0.15,
            "step": 0.005,
            "desc": "场景A：今开/昨收-1 ≥ 此值（用户规则 默认 +3%）",
        },
        {
            "key": "morning_low_pct",
            "label": "场景A 早盘低点上限",
            "type": "percent",
            "default": -0.02,
            "min": -0.10,
            "max": -0.001,
            "step": 0.005,
            "desc": "场景A：截至 9:33 的当日最低涨幅 ≤ 此值（负值，用户规则 默认 -2%）",
        },
        {
            "key": "low_open_pct",
            "label": "场景B 低开上限",
            "type": "percent",
            "default": -0.02,
            "min": -0.10,
            "max": -0.001,
            "step": 0.005,
            "desc": "场景B：今开/昨收-1 ≤ 此值（用户规则 默认 -2%）",
        },
        {
            "key": "range_pct",
            "label": "区间振幅上限",
            "type": "percent",
            "default": 0.03,
            "min": 0.005,
            "max": 0.10,
            "step": 0.005,
            "desc": "A/C=9:33 后至尾盘 / B=全天的（最高-最低）/昨收 ≤ 此值（用户规则 默认 3%）",
        },
        {
            "key": "volume_ratio_max",
            "label": "高开场景量能上限",
            "type": "float",
            "default": 1.5,
            "min": 1.0,
            "max": 5.0,
            "step": 0.1,
            "unit": "倍",
            "desc": "今日成交量 > 连板交易日最大成交量 × 此值 → 排除（用户规则 默认 1.5x）",
        },
        {
            "key": "low_open_volume_ratio",
            "label": "低开场景量能上限",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 2.0,
            "step": 0.05,
            "unit": "倍",
            "desc": "场景B：今日量须 < 连板峰值 × 此值（用户规则 默认 0.8x，缩量低开）",
        },
        {
            "key": "flat_volume_ratio",
            "label": "平开场景量能上限",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 2.0,
            "step": 0.05,
            "unit": "倍",
            "desc": "场景C：今日量须 < 连板峰值 × 此值（用户规则 默认 1.0x）",
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
