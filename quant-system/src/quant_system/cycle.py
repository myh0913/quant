"""情绪周期状态机（用户确认版 2026-09-07）。

⚠️ 所有阈值集中在 CycleThresholds —— 要调参只改这一个类，别处不出现魔法数字。
用户已确认：退潮线=炸板率35% / 加速=温度60+晋级25%+高度5（三条同时）/ 仓位梯度 0.3-0.5-1.0。
放宽类状态（修复/加速/冰点转折）需连续 2 个交易日确认，v0 通过 relaxed_needs_confirm 标记暴露。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .config import Settings


# ============================== 阈值（用户快速修改区） ==============================


@dataclass
class CycleThresholds:
    """全部阈值集中在此。用户确认 2026-09-07；改动后无需改其他代码。"""

    # 退潮（用户确认：炸板率≥35%）
    retreat_break_ratio: float = 0.35      # 炸板率 ≥ 此值 → 退潮
    retreat_limit_down: int = 50           # 跌停数 ≥ 此值 → 退潮
    retreat_leader_limit_down: bool = True  # 龙头跌停 → 退潮
    retreat_temp_floor: float = 25.0       # 温度 < 此值 → 退潮
    retreat_promotion_max: float = 0.25    # 炸板率≥35% 时需晋级率< 此值才退潮（用户确认 2026-09-14）

    # 分歧
    divergence_break_ratio: float = 0.25   # 炸板率 25%~35% → 分歧
    divergence_promotion: float = 0.15     # 晋级率 < 15% → 分歧

    # 加速/高潮（用户确认：三条同时满足）
    accel_temp: float = 60.0               # 温度 ≥ 60
    accel_promotion: float = 0.25          # 晋级率 ≥ 25%
    accel_height: int = 5                  # 连板高度 ≥ 5

    # 修复
    repair_temp_low: float = 30.0
    repair_temp_high: float = 60.0
    repair_limit_up: int = 40              # 涨停 ≥ 40
    repair_break_ratio: float = 0.25       # 炸板率 < 25%

    # 冰点
    ice_temp: float = 30.0                 # 温度 < 30
    ice_limit_down: int = 30               # 且 跌停 ≥ 30 或 涨停 < 30
    ice_limit_up: int = 30

    # 冰点转折
    turn_limit_up: int = 50                # 冰点后：涨停 ≥ 50
    turn_temp_recover: float = 40.0        # 或 温度回升 ≥ 40

    # 过热（草案：减半，不直接禁买）
    overheated_temp: float = 75.0          # 温度 ≥ 75 且 高度 ≥ 6 → 仓位减半
    overheated_height: int = 6

    # 黑天鹅近似
    blackswan_index_drop: float = -0.03    # 大盘单日跌 > 3% → 按退潮处理
    blackswan_limit_down: int = 100        # 或 跌停 > 100


DEFAULT_THRESHOLDS = CycleThresholds()


# ============================== 指标与状态 ==============================


class CycleState(str, Enum):
    ICE = "冰点"
    TURN = "冰点转折"
    REPAIR = "修复"
    ACCEL = "加速/高潮"
    DIVERGE = "分歧"
    RETREAT = "退潮"


_RETREAT_FIRST = [CycleState.RETREAT, CycleState.DIVERGE, CycleState.ICE, CycleState.ACCEL, CycleState.REPAIR, CycleState.TURN]


@dataclass
class CycleIndicators:
    """单日情绪指标（compute_indicators 产出）。"""

    date: str
    temperature: Optional[float] = None
    limit_up_count: int = 0
    limit_down_count: int = 0
    break_ratio: Optional[float] = None      # 炸板/(炸板+涨停)
    promotion_rate: Optional[float] = None   # 昨日涨停今日仍涨停比例
    board_height: int = 0                     # 最高连板
    leader_thscode: str = ""
    leader_name: str = ""
    leader_limit_down: bool = False
    index_daily_pct: Optional[float] = None   # 上证指数日涨幅
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CycleJudgement:
    state: CycleState
    reasons: list[str] = field(default_factory=list)
    overheated: bool = False
    relaxed_needs_confirm: bool = False       # 放宽类首次出现 → 建议次日复认
    data_degraded: bool = False               # 关键指标缺失 → 判定可信度降级（2026-09-17）
    indicators: Optional[CycleIndicators] = None


# ============================== 指标采集 ==============================


def compute_indicators(settings: Settings, date: str | None = None) -> CycleIndicators:
    """从选股通+hithink 采集单日指标（M2 起全部经 resolve 能力层）。date 为空=最近交易日。"""
    from .datasource.resolve import (
        standard_index_snapshot_pct,
        standard_limit_down_pool,
        standard_limit_up_pool,
        standard_market_sentiment,
    )
    from .timeutil import prev_weekday, sh_today

    date = date or sh_today()
    ind = CycleIndicators(date=date)

    # 温度/涨跌停/炸板率：flash-api line 按日期取（支持历史回算；当日返回盘中逐点）
    sent: dict = standard_market_sentiment(settings, date)
    if not sent:
        sent = standard_market_sentiment(settings)  # 兜底（仅当天可靠）

    ind.temperature = sent.get("market_temperature")
    ind.limit_up_count = int(sent.get("limit_up_count") or 0)
    br = sent.get("limit_up_broken_count") or 0
    if ind.limit_up_count + br > 0:
        ind.break_ratio = br / (ind.limit_up_count + br)

    # 跌停数：line 缺失时 hithink 跌停池兜底（历史日期用跌停池 date）
    ldn = sent.get("limit_down_count")
    if ldn is None:
        try:
            ldn = len(standard_limit_down_pool(settings, date))
        except Exception:  # noqa: BLE001
            ldn = 0
    ind.limit_down_count = int(ldn or 0)

    # 涨停池：高度、龙头、晋级率（主/备源可配置）
    try:
        cur = standard_limit_up_pool(settings, date)
        if cur:
            ind.board_height = int(cur[0].get("continue_day_cnt") or 0)
            ind.leader_thscode = cur[0].get("thscode", "")
            ind.leader_name = cur[0].get("name", "")
        # 昨日池（晋级率）
        prev = standard_limit_up_pool(settings, prev_weekday(date))
        prev_codes = {it.get("thscode") for it in prev}
        cur_codes = {it.get("thscode") for it in cur}
        if prev_codes:
            ind.promotion_rate = len(prev_codes & cur_codes) / len(prev_codes)
    except Exception:  # noqa: BLE001
        pass

    # 龙头是否跌停（在跌停池中）
    if ind.leader_thscode:
        try:
            downs = standard_limit_down_pool(settings)
            ind.leader_limit_down = any(d.get("thscode") == ind.leader_thscode for d in downs)
        except Exception:  # noqa: BLE001
            pass

    # 大盘指数日涨幅（上证）；快照缺失/接口失败 → None（回测历史日无指数快照时容错）
    try:
        ind.index_daily_pct = standard_index_snapshot_pct(settings)
    except Exception:  # noqa: BLE001
        ind.index_daily_pct = None

    return ind


# ============================== 判定 ==============================


def classify(
    ind: CycleIndicators,
    th: CycleThresholds = DEFAULT_THRESHOLDS,
    prev_state: Optional[CycleState] = None,
) -> CycleJudgement:
    """六态判定。优先级：退潮>分歧>冰点>加速>修复>转折（安全优先）。"""
    j = CycleJudgement(state=CycleState.REPAIR, indicators=ind)
    br = ind.break_ratio
    t = ind.temperature

    # 数据降级标记：关键指标缺失时判定可信度下降（区分"真分歧"与"数据源挂了"）
    j.data_degraded = (
        ind.temperature is None
        or ind.break_ratio is None
        or ind.promotion_rate is None
    )
    if j.data_degraded:
        missing = [
            label for label, v in (
                ("温度", ind.temperature), ("炸板率", ind.break_ratio),
                ("晋级率", ind.promotion_rate),
            ) if v is None
        ]
        j.reasons.append(f"⚠️ 数据降级：{'+'.join(missing)}缺失，判定可信度低")

    # 黑天鹅近似 → 直接退潮
    if (ind.index_daily_pct is not None and ind.index_daily_pct <= th.blackswan_index_drop) or (
        ind.limit_down_count >= th.blackswan_limit_down
    ):
        j.state = CycleState.RETREAT
        j.reasons.append(f"黑天鹅近似：大盘{ind.index_daily_pct*100 if ind.index_daily_pct is not None else '-'}% / 跌停{ind.limit_down_count}")
        return j

    # 退潮（复合条件，用户确认 2026-09-14：炸板率≥35% 需叠加弱势信号；高晋级+高炸板 → 分歧不退潮）
    high_break = br is not None and br >= th.retreat_break_ratio
    weak_alongside = (
        ind.promotion_rate is not None and ind.promotion_rate < th.retreat_promotion_max
    ) or ind.limit_down_count >= th.retreat_limit_down
    if (high_break and weak_alongside) \
            or ind.limit_down_count >= th.retreat_limit_down \
            or (th.retreat_leader_limit_down and ind.leader_limit_down) \
            or (t is not None and t < th.retreat_temp_floor):
        j.state = CycleState.RETREAT
        if high_break and weak_alongside:
            j.reasons.append(f"炸板率{br*100:.1f}%≥{th.retreat_break_ratio*100:.0f}% 且 晋级率弱/跌停多")
        if ind.limit_down_count >= th.retreat_limit_down:
            j.reasons.append(f"跌停{ind.limit_down_count}≥{th.retreat_limit_down}")
        if ind.leader_limit_down:
            j.reasons.append("龙头跌停")
        if t is not None and t < th.retreat_temp_floor:
            j.reasons.append(f"温度{t:.0f}<{th.retreat_temp_floor:.0f}")
        return j

    # 分歧
    if (br is not None and br >= th.divergence_break_ratio) or (
        ind.promotion_rate is not None and ind.promotion_rate < th.divergence_promotion
    ):
        j.state = CycleState.DIVERGE
        if br is not None and br >= th.retreat_break_ratio:
            # 高炸板但晋级强 → 高位分歧加剧（用户确认 2026-09-14：不归退潮）
            j.reasons.append(f"炸板率{br*100:.1f}%≥{th.retreat_break_ratio*100:.0f}% 但晋级率{ind.promotion_rate*100:.1f}%≥{th.retreat_promotion_max*100:.0f}%（高位分歧加剧）")
        elif br is not None and br >= th.divergence_break_ratio:
            j.reasons.append(f"炸板率{br*100:.1f}%∈[{th.divergence_break_ratio*100:.0f}%,{th.retreat_break_ratio*100:.0f}%)")
        if ind.promotion_rate is not None and ind.promotion_rate < th.divergence_promotion:
            j.reasons.append(f"晋级率{ind.promotion_rate*100:.1f}%<{th.divergence_promotion*100:.0f}%")
        return j

    # 冰点
    if t is not None and t < th.ice_temp and (ind.limit_down_count >= th.ice_limit_down or ind.limit_up_count < th.ice_limit_up):
        j.state = CycleState.ICE
        j.reasons.append(f"温度{t:.0f}<{th.ice_temp:.0f} 且 跌停{ind.limit_down_count}/涨停{ind.limit_up_count}")
        return j

    # 加速（三条同时，用户确认）
    if (t is not None and t >= th.accel_temp and ind.promotion_rate is not None
            and ind.promotion_rate >= th.accel_promotion and ind.board_height >= th.accel_height):
        j.state = CycleState.ACCEL
        j.reasons.append(f"温度{t:.0f}≥{th.accel_temp:.0f} + 晋级{ind.promotion_rate*100:.0f}%≥{th.accel_promotion*100:.0f}% + 高度{ind.board_height}≥{th.accel_height}")
    elif (t is not None and th.repair_temp_low <= t <= th.repair_temp_high
          and ind.limit_up_count >= th.repair_limit_up
          and (br is not None and br < th.repair_break_ratio)):
        j.state = CycleState.REPAIR
        j.reasons.append(f"温度{t:.0f}∈[{th.repair_temp_low:.0f},{th.repair_temp_high:.0f}] 涨停{ind.limit_up_count}≥{th.repair_limit_up} 炸板率{br*100:.1f}%<{th.repair_break_ratio*100:.0f}%")
    else:
        # 未达修复标准 → 归入分歧（结构不达标的中性日视为弱）
        j.state = CycleState.DIVERGE
        j.reasons.append("未达修复/加速标准（结构偏弱归分歧）")

    # 过热标记
    if t is not None and t >= th.overheated_temp and ind.board_height >= th.overheated_height:
        j.overheated = True
        j.reasons.append(f"过热：温度{t:.0f}≥{th.overheated_temp:.0f} 且 高度{ind.board_height}≥{th.overheated_height} → 仓位减半")

    # 放宽确认标记
    if j.state in (CycleState.REPAIR, CycleState.ACCEL) and prev_state != j.state:
        j.relaxed_needs_confirm = True
    return j


# ============================== 策略联动（用户确认梯度） ==============================

_GATE = {
    # state: {策略名: (allowed, 仓位系数)}
    CycleState.ICE:     {"竞价主力抢筹": (False, 0.0), "连板捉妖": (False, 0.0), "龙回头": (False, 0.0)},
    CycleState.TURN:    {"竞价主力抢筹": (True, 0.3),  "连板捉妖": (False, 0.0), "龙回头": (False, 0.0)},
    CycleState.REPAIR:  {"竞价主力抢筹": (True, 0.5),  "连板捉妖": (True, 0.5),  "龙回头": (True, 0.5)},
    CycleState.ACCEL:   {"竞价主力抢筹": (True, 1.0),  "连板捉妖": (True, 1.0),  "龙回头": (True, 1.0)},
    CycleState.DIVERGE: {"竞价主力抢筹": (True, 0.5),  "连板捉妖": (False, 0.0), "龙回头": (True, 0.5)},
    CycleState.RETREAT: {"竞价主力抢筹": (False, 0.0), "连板捉妖": (False, 0.0), "龙回头": (False, 0.0)},
}


def strategy_gate(state: CycleState, strategy_name: str, overheated: bool = False) -> tuple[bool, float, str]:
    """返回 (允许, 仓位系数, 说明)。过热 → 系数减半。"""
    allowed, factor = _GATE[state].get(strategy_name, (False, 0.0))
    note = f"{state.value}"
    if allowed and overheated:
        factor *= 0.5
        note += "+过热减半"
    if not allowed:
        note += " → 禁用"
    return allowed, factor, note


# ============================== 竞价/盘中实时恶化腿（2026-09-29） ==============================


@dataclass
class DeteriorationCheck:
    """竞价/盘中时点实时恶化检验结果。

    背景（2026-09-28 实测）：9:25 竞价段当日 classify 恒 data_degraded
    （炸板率/晋级率要等涨停池 ~14:56 才入库），旧门控用降级误判状态做放行/
    否决均不可信；T-1 定版又看不见当日盘中恶化（09-28 早盘温度 47→14:45 跌至 27）。
    本腿只用 9:25 时点实际可得且经标定有区分度的信号，触发即视同退潮级恶化
    （恶化立即生效），不触发则维持 T-1 定版门控。
    """

    triggered: bool = False
    reasons: list[str] = field(default_factory=list)
    temperature: Optional[float] = None
    yesterday_premium: Optional[float] = None   # 昨池竞价溢价（小数，-0.017=-1.7%）
    limit_down_count: Optional[int] = None
    data_degraded: bool = False                  # 快照缺失/字段缺失 → 不触发不否决


def compute_deterioration(settings: Settings, date: str | None = None) -> DeteriorationCheck:
    """9:25/盘中时点实时恶化检验（阈值标定 2026-09-29，样本 09-21/24/28 早盘快照）。

    标定：昨池竞价溢价 加速日 +1.48% / 分歧日 +1.07% / 当日盘中恶化至退潮日 +0.38%；
    竞价温度与跌停数在 9:25 时点区分度弱（09-28 早盘跌停仅 1 家，14:45 才 57 家）。
    故判据保守取两条，宁少拦不误拦：
    ① 昨池竞价溢价 ≤0（昨日涨停票今晨竞价整体转负=情绪急冻）
    ② 竞价温度 < retreat_temp_floor（与退潮温度线同源 25）
    快照缺失/关键字段缺失 → data_degraded=True，不触发不否决（绝不静默禁用）。
    """
    from .datasource.resolve import standard_market_sentiment
    from .timeutil import sh_today

    date = date or sh_today()
    chk = DeteriorationCheck()
    try:
        sent: dict = standard_market_sentiment(settings, date)
    except Exception:  # noqa: BLE001
        sent = {}
    if not sent:
        chk.data_degraded = True
        chk.reasons.append("实时情绪快照缺失，恶化腿不评估")
        return chk
    th = DEFAULT_THRESHOLDS
    chk.temperature = sent.get("market_temperature")
    chk.yesterday_premium = sent.get("yesterday_limit_up_avg_pcp")
    ld = sent.get("limit_down_count")
    chk.limit_down_count = int(ld) if ld is not None else None
    p = chk.yesterday_premium
    if p is not None and p <= 0:
        chk.triggered = True
        chk.reasons.append(f"昨池竞价溢价 {p * 100:.2f}%≤0（情绪急冻）")
    if chk.temperature is not None and chk.temperature < th.retreat_temp_floor:
        chk.triggered = True
        chk.reasons.append(f"竞价温度 {chk.temperature:.1f}<{th.retreat_temp_floor:.0f}")
    if p is None and chk.temperature is None:
        chk.data_degraded = True
        chk.reasons.append("快照缺溢价/温度字段，恶化腿不评估")
    return chk


def prev_finalized(settings: Settings, prev: str) -> Optional[dict]:
    """读 qg 侧上一交易日盘后定版（advice/{prev}/cycle_*.json 最新一份）。

    返回 {"state": CycleState, "overheated": bool}；文件缺失/解析失败 → None
    （门控按"无定版"处理，绝不静默禁用）。
    """
    files = (settings.data_dir / "advice" / prev).glob("cycle_*.json")
    files = [f for f in files]
    if not files:
        return None
    # 按 mtime 取最新写入：文件名 HHMMSS 字典序会把回补文件（如 013057）
    # 排在常规盘后文件（170034）之前而漏选（2026-09-29 单测抓出）
    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        j = json.loads(latest.read_text())
        return {"state": CycleState(j["state"]), "overheated": bool(j.get("overheated"))}
    except Exception:  # noqa: BLE001
        return None


def worst_state(*states: Optional[CycleState]) -> Optional[CycleState]:
    """按安全优先级（退潮>分歧>冰点>加速>修复>转折）取最差状态；全 None → None。"""
    cand = [s for s in states if s is not None]
    return min(cand, key=_RETREAT_FIRST.index) if cand else None


def combined_gate_state(
    settings: Settings,
    date: str,
    prev_state: Optional[CycleState],
    prev_overheated: bool = False,
    today_j: Optional[CycleJudgement] = None,
) -> tuple[Optional[CycleState], bool, list[str], bool]:
    """竞价/盘中门控状态合成（2026-09-29，修 T-0036 审计"竞价门控时序"问题）。

    - 当日 classify 非降级 → 采信为基准；降级 → 回退 T-1 定版
    - 实时恶化腿（compute_deterioration）触发 → 视同退潮，与基准取更差者
      （恶化立即生效，用户确认规则）
    - 全部缺失 → (None, ...)：调用方按"绝不静默禁用"放行并留痕

    返回 (state|None, overheated, reasons, degraded)。
    """
    chk = compute_deterioration(settings, date)
    det = CycleState.RETREAT if chk.triggered else None
    reasons = list(chk.reasons)

    if today_j is not None and not today_j.data_degraded:
        base, over = today_j.state, today_j.overheated
        reasons = list(today_j.reasons) + reasons
    else:
        base, over = prev_state, prev_overheated
        if today_j is not None and today_j.data_degraded:
            reasons.append("当日判定数据降级，不采信")
        if prev_state is not None:
            reasons.append(f"T-1 定版={prev_state.value}")

    state = worst_state(base, det)
    if state is None:
        reasons.append("无T-1定版且恶化腿未触发 → 放行（绝不静默禁用）")
    return state, over, reasons, chk.data_degraded
