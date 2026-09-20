"""策略二：连板捉妖（原 strategy_lianban.py 迁移 + 注册表适配）。

用户规则（docs/USER_KNOWLEDGE.md §4）：
- 盘后(T-1)：昨日 2/3 连板 → 结构过滤（第一波/非三板组/各板量≥波前一日量/
  首板放量≥1.5倍/位置过滤 首板前日开盘÷30日最低<1.15）
- 竞价(T 9:25)：环境过滤（连板成功率、竞价跌停数≤2）→ 场景判断
  场景A 大幅低开(≤-5%) → 直接买入建议
  场景B 低开(-5%~0%) → 待盘中放量上攻确认（2026-09-17 由 -3% 改 -5%）
  场景C 高开 → 待盘中先跌后放量涨确认
- 盘中：分钟级触发，仅开盘后前 10 分钟内有效，超时不触发（2026-09-17 用户定义）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from .. import config_registry
from ..advice import Advice
from ..analyzer import DailyBarAnalyzer
from ..cycle import CycleThresholds, DEFAULT_THRESHOLDS, classify, compute_indicators, strategy_gate
from ..datasource.resolve import (
    data_session,
    standard_daily_bars,
    standard_limit_up_pool,
    standard_monitor_stocks,
    standard_opening_match,
    standard_pre_close,
)
from ..models import MonitorStock
from ..risk import run_risk_checks
from .base import SCENE_IMMEDIATE, SCENE_PENDING, SCENE_SKIP, ConfirmOutcome, Strategy, register

if TYPE_CHECKING:
    from ..config import Settings


# ---------- 盘中触发（场景 B/C，分钟级） ----------


class IntradayTrigger(BaseModel):
    """盘中触发结果。"""

    scene: str
    triggered: bool = False
    trigger_time: Optional[str] = None
    trigger_price: Optional[float] = None
    minute_pct: Optional[float] = None  # 触发分钟涨幅
    volume_ratio: Optional[float] = None  # 触发分钟量 / 前均量
    detail: str = ""


def _pct(cur: float, prev: float) -> float:
    return (cur - prev) / prev if prev else 0.0


def evaluate_intraday_scene(
    points: list[dict],
    scene: str,
    *,
    window: int = 10,
    min_pct: float = 0.01,
    vol_multiple: float = 1.5,
) -> IntradayTrigger:
    """回放盘中触发（场景 B/C）。

    points: [{time_label, price, volume}, ...] 分钟分时（升序，含 9:31 起）。
    用户已定义：快速 = 1 分钟内幅度 > 1%。
    放量倍数 1.5（用户 2026-09-09 确认，与建池规则4的 ≥1.5 倍对齐）。
    窗口：仅开盘后前 window 分钟（默认 10，用户 2026-09-17 定义），超时不触发。

    场景 B（低开待上攻）：窗口内出现“放量上涨分钟”（涨幅≥min_pct 且 量≥前均量×vol_multiple）→ 触发。
    场景 C（高开先跌后涨）：窗口内先出现“快速下跌分钟”（跌幅≤-min_pct），随后出现“放量上涨分钟”→ 触发。
    """
    result = IntradayTrigger(scene=scene)
    if len(points) < 3:
        result.detail = "分时数据不足"
        return result
    obs = points[: window]
    # 首根无前价，从第 2 根开始
    saw_drop = False
    for i in range(1, len(obs)):
        p, prev = obs[i], obs[i - 1]
        pct = _pct(p["price"], prev["price"])
        if pct <= -min_pct:
            saw_drop = True
        if pct >= min_pct:
            avg_vol = sum(q["volume"] for q in obs[max(0, i - 5) : i]) / max(1, i - max(0, i - 5))
            vr = p["volume"] / avg_vol if avg_vol else None
            if vr is not None and vr >= vol_multiple:
                if scene == "C" and not saw_drop:
                    continue  # 场景 C 必须先跌后涨
                result.triggered = True
                result.trigger_time = p["time_label"]
                result.trigger_price = p["price"]
                result.minute_pct = pct
                result.volume_ratio = round(vr, 2)
                kind = "先跌后放量上攻" if scene == "C" else "放量上攻"
                result.detail = (
                    f"{p['time_label']} {kind}: 分钟涨幅 {pct*100:.2f}% ≥ {min_pct*100:.0f}%, "
                    f"量比 {vr:.1f}x ≥ {vol_multiple}x"
                )
                return result
    if scene == "C":
        result.detail = f"窗口 {window} 分钟内未出现先跌后放量涨（saw_drop={saw_drop}）"
    else:
        result.detail = f"窗口 {window} 分钟内未出现放量上攻（涨幅≥{min_pct*100:.0f}% 且 量≥{vol_multiple}x 均量）"
    return result


class LianbanCandidate(BaseModel):
    """连板候选（结构过滤后）。"""

    thscode: str
    name: str
    boards: int = Field(..., description="连板天数（2 或 3）")
    volume_ratio: Optional[float] = Field(None, description="首板量/波前一日量")
    structure_notes: list[str] = Field(default_factory=list)
    rejected: bool = False
    reject_reason: str = ""


class AuctionEnv(BaseModel):
    """竞价环境（T 日 9:25）。"""

    total_yesterday_boards: int = 0
    success_count: int = 0
    success_rate: Optional[float] = None
    limit_down_count: int = 0
    ok: bool = True
    note: str = ""


class LianbanScene(BaseModel):
    thscode: str
    name: str
    scene: str = Field(..., description="A=大幅低开直接买 / B=低开待盘中 / C=高开待盘中 / X=不参与")
    auction_pct: Optional[float] = None
    detail: str = ""


class LianbanReport(BaseModel):
    strategy: str = "连板捉妖"
    data_date: str
    ran_at: datetime
    pool_size: int = 0
    candidates: list[LianbanCandidate] = Field(default_factory=list)
    rejected: list[LianbanCandidate] = Field(default_factory=list)
    env: Optional[AuctionEnv] = None
    scenes: list[LianbanScene] = Field(default_factory=list)
    advices: list[Advice] = Field(default_factory=list)
    blocked: list[dict] = Field(default_factory=list)
    # 情绪周期门控：否决时报告为空，必须把原因带出来，否则使用者无法区分
    # 「门控否决」和「数据/策略异常」（2026-09-15 沙箱实测踩坑：全 0 无解释）
    gate_state: str = ""
    gate_note: str = ""


# ---------- 盘后候选池 ----------

def build_lianban_candidates(settings: "Settings", date: str) -> tuple[list[LianbanCandidate], list[LianbanCandidate]]:
    """T-1 盘后：涨停池 → 2/3 连板 → 结构过滤。

    返回 (通过, 被拒)。
    """
    items = standard_limit_up_pool(settings, date)

    # 股票池过滤：只做 60/00 主板、非 ST（创业板/科创板/北交所/可转债不参与，2026-09-17）
    from ..pool import filter_target_stocks

    items = filter_target_stocks(items)

    # 阈值来自配置中心（量化配置页可改，热生效）
    p = config_registry.get_params(settings, "lianban")
    min_vr = p["min_first_board_volume_ratio"]
    max_pos = p["max_position_ratio"]
    wave_lookback = int(p["first_wave_lookback_days"])

    passed: list[LianbanCandidate] = []
    rejected: list[LianbanCandidate] = []

    with data_session(settings):
        for it in items:
            boards = int(it.get("continue_day_cnt") or 0)
            if boards not in (2, 3):
                continue
            thscode = it.get("thscode", "")
            name = it.get("name", "")
            cand = LianbanCandidate(thscode=thscode, name=name, boards=boards)

            # 拉日线做结构分析（60 日足够覆盖 20 日回看 + 当前波）
            bars = standard_daily_bars(settings, thscode, date, lookback_days=60)
            if len(bars) < 10:
                cand.rejected = True
                cand.reject_reason = "日线数据不足"
                rejected.append(cand)
                continue
            az = DailyBarAnalyzer(bars)
            if az.has_suspect_day():
                cand.rejected = True
                cand.reject_reason = "日线疑似除权/数据异常（单日涨跌幅越界）"
                rejected.append(cand)
                continue

            # 规则1：只做第一波（最近 N 个交易日内无其他连板波）
            if not az.is_first_wave(lookback=wave_lookback):
                cand.rejected = True
                cand.reject_reason = f"非第一波（{wave_lookback}日内有过连板）"
                rejected.append(cand)
                continue
            # 规则2：排除三板组
            # 定义：首板量≤前日1.2倍 + 两根一字 + 一字量≤首板1/10
            if az.is_sanbanzu():
                cand.rejected = True
                cand.reject_reason = "三板组（首板量≤前日1.2倍+两根一字+一字量≤首板1/10）"
                rejected.append(cand)
                continue
            # 规则3：连板期间所有涨停板成交量 ≥ 波启动前一日量（量能不萎缩）
            if not az.wave_volume_sustained():
                cand.rejected = True
                cand.reject_reason = "连板期间涨停板量低于波启动前一日量"
                rejected.append(cand)
                continue
            # 规则4：首板量 / 波启动前一日量 ≥ min_vr
            vr = az.volume_ratio()
            cand.volume_ratio = vr
            if vr is None or vr < min_vr:
                cand.rejected = True
                cand.reject_reason = f"量能不足（首板量/波前量={vr and round(vr, 2)}，要求≥{min_vr}倍）"
                rejected.append(cand)
                continue
            # 规则5：首板前一交易日开盘价 / 最近30交易日最低价 < max_pos（低位启动过滤）
            pos = az.pre_wave_open_vs_low(lookback=30)
            if pos is None or pos >= max_pos:
                cand.rejected = True
                cand.reject_reason = (
                    f"位置过滤未过（首板前日开盘/30日最低={pos and round(pos, 2)}，要求<{max_pos}）"
                )
                rejected.append(cand)
                continue

            cand.structure_notes = [
                f"{boards}连板·第一波",
                f"首板放量 {round(vr, 2)}x",
                "各板量≥波前一日量",
                f"位置比 {round(pos, 2)}（<{max_pos}）",
            ]
            passed.append(cand)

    return passed, rejected


# ---------- 竞价环境 + 场景 ----------

def evaluate_auction_env(settings: "Settings", prev_date: str, cur_date: str) -> AuctionEnv:
    """T 日 9:25：昨日全部连板票的今日竞价表现。

    成功率 = 竞价涨幅 > 0 的比例；竞价跌停数 = 竞价价 ≤ 跌停价的数量。
    用户规则：不能出现 2 只以上跌停板。
    """
    board_stocks = standard_limit_up_pool(settings, prev_date)
    board_stocks = [it for it in board_stocks if int(it.get("continue_day_cnt") or 0) >= 2]

    env = AuctionEnv(total_yesterday_boards=len(board_stocks))
    if not board_stocks:
        env.note = "昨日无连板票"
        return env

    # 阈值来自配置中心
    p = config_registry.get_params(settings, "lianban")
    limit_down_pct = p["auction_limit_down_pct"]
    max_limit_down = int(p["max_auction_limit_down"])

    with data_session(settings):
        up = 0
        for it in board_stocks:
            thscode = it.get("thscode", "")
            try:
                om = standard_opening_match(settings, thscode, cur_date)
            except Exception:  # noqa: BLE001
                continue
            if om is None:
                continue
            pre = float(it.get("last_price") or 0)  # 昨收≈池内最后价
            if not pre:
                continue
            pct = (om.price - pre) / pre
            if pct > 0:
                up += 1
            if pct <= limit_down_pct:
                env.limit_down_count += 1

    n = env.total_yesterday_boards
    env.success_rate = up / n if n else None
    env.ok = env.limit_down_count <= max_limit_down
    if not env.ok:
        env.note = f"昨日连板竞价跌停 {env.limit_down_count} 只（>{max_limit_down}，环境否决）"
    return env


def classify_scenes(candidates: list[LianbanCandidate], settings: "Settings", cur_date: str) -> list[LianbanScene]:
    """T 日 9:25 场景分类（低开阈值来自配置中心）。"""
    p = config_registry.get_params(settings, "lianban")
    low_a = p["scene_a_low_open"]
    low_b = p["scene_b_low_open"]
    scenes: list[LianbanScene] = []
    with data_session(settings):
        for c in candidates:
            # 竞价涨幅：opening_match 价 vs 昨收（昨收用实时快照）
            try:
                om = standard_opening_match(settings, c.thscode, cur_date)
                pre = standard_pre_close(settings, c.thscode, cur_date)
            except Exception:  # noqa: BLE001
                scenes.append(LianbanScene(thscode=c.thscode, name=c.name, scene="X", detail="竞价数据获取失败"))
                continue
            if om is None or not pre:
                scenes.append(LianbanScene(thscode=c.thscode, name=c.name, scene="X", detail="无竞价/昨收数据"))
                continue
            pct = (om.price - pre) / pre
            if pct <= low_a:
                scene, detail = "A", f"大幅低开 {pct*100:.2f}%（<={low_a*100:.0f}%，直接买入）"
            elif low_b <= pct < 0:
                scene, detail = "B", f"稍微低开 {pct*100:.2f}%（待盘中放量上攻确认）"
            elif pct >= 0:
                scene, detail = "C", f"高开 {pct*100:.2f}%（待盘中先跌后放量涨确认）"
            else:
                scene, detail = "X", f"低开过度 {pct*100:.2f}%（{low_a*100:.0f}%~{low_b*100:.0f}% 之间，未定义场景）"
            scenes.append(LianbanScene(thscode=c.thscode, name=c.name, scene=scene, auction_pct=pct, detail=detail))
    return scenes


# ---------- 编排 ----------

def run_lianban(settings: "Settings", prev_date: str, cur_date: str,
                thresholds: CycleThresholds = DEFAULT_THRESHOLDS) -> LianbanReport:
    """连板捉妖：盘后候选 + 竞价环境 + 场景 → 建议。退潮/冰点/分歧 → 全局否决。"""
    # 情绪周期门控
    try:
        indicators = compute_indicators(settings, cur_date)
        cycle_j = classify(indicators, thresholds)
        gate_ok, gate_factor, gate_note = strategy_gate(cycle_j.state, "连板捉妖", cycle_j.overheated)
    except Exception as exc:  # noqa: BLE001
        cycle_j, gate_ok, gate_factor, gate_note = None, True, 1.0, f"周期计算失败（{exc}）放行待复核"
    if not gate_ok:
        r = LianbanReport(
            data_date=cur_date, ran_at=datetime.now(timezone.utc), pool_size=0,
            gate_state=cycle_j.state.value if cycle_j else "unknown",
            gate_note=gate_note,
        )
        r.scenes = []
        return r
    gate_state = cycle_j.state.value if cycle_j else ""

    passed, rejected = build_lianban_candidates(settings, prev_date)
    env = evaluate_auction_env(settings, prev_date, cur_date)
    report = LianbanReport(
        data_date=cur_date,
        ran_at=datetime.now(timezone.utc),
        pool_size=len(passed) + len(rejected),
        candidates=passed,
        rejected=rejected,
        env=env,
        gate_state=gate_state,
        gate_note=gate_note,
    )
    if not env.ok:
        return report  # 环境否决，不生成场景
    scenes = classify_scenes(passed, settings, cur_date)
    report.scenes = scenes

    # 场景A（大幅低开）生成建议；B/C 标注待盘中确认
    monitors: list[MonitorStock] = []
    try:
        monitors = standard_monitor_stocks(settings)
    except Exception:  # noqa: BLE001
        pass

    for sc in scenes:
        if sc.scene != "A":
            continue
        checks = run_risk_checks(sc.thscode, monitors)
        hard_fail = [c for c in checks if not c.passed and c.hard_block]
        if hard_fail:
            report.blocked.append({"thscode": sc.thscode, "name": sc.name, "reasons": [c.detail for c in hard_fail]})
            continue
        cand = next((c for c in passed if c.thscode == sc.thscode), None)
        # 仓位梯度（M3）：基准仓位 × 周期系数（0.3/0.5/1.0，过热减半）
        from ..portfolio import position_display

        base_pct = float(config_registry.get_params(settings, "lianban")["base_position_pct"])
        pos_pct, pos_text = position_display(base_pct, gate_factor)
        report.advices.append(
            Advice(
                thscode=sc.thscode,
                name=sc.name,
                strategy="连板捉妖",
                action="买入建议（场景A：大幅低开）",
                generated_at=datetime.now(timezone.utc),
                data_date=cur_date,
                reference_price=None,
                trigger_condition=sc.detail,
                position=pos_text,
                position_pct=pos_pct,
                valid_until="当日有效",
                factor_summary={"scene": sc.scene, "auction_pct": sc.auction_pct,
                                "boards": cand.boards if cand else None,
                                "volume_ratio": cand.volume_ratio if cand else None},
                reasons=[sc.detail] + (cand.structure_notes if cand else []),
                risk_notes=[f"{c.name}: {c.detail}" for c in checks],
                pending_confirmations=["止损规则待确认",
                                        "场景B/C 盘中确认规则待实现"],
            )
        )
    # 组合风控（M3）：单票去重 + 总仓位上限，超出降级为观察
    from ..portfolio import apply_portfolio_limits

    apply_portfolio_limits(report.advices, settings)
    return report


# ============================== 注册表适配 ==============================


@register
class LianbanStrategy(Strategy):
    """连板捉妖：盘后建池 + 竞价场景 + 盘中放量确认。"""

    strategy_id = "lianban"
    label = "连板捉妖"
    has_pool_phase = True
    has_intraday_phase = True
    candidate_model = LianbanCandidate

    params_schema = [
        {
            "key": "min_first_board_volume_ratio",
            "label": "首板最小量比",
            "type": "float",
            "default": 1.5,
            "min": 1.0,
            "max": 5.0,
            "step": 0.1,
            "unit": "倍",
            "desc": "首板量/波启动前一日量 ≥ 此值（建池规则4，用户 2026-09-09 确认 1.5）",
        },
        {
            "key": "max_position_ratio",
            "label": "位置过滤上限",
            "type": "float",
            "default": 1.15,
            "min": 1.0,
            "max": 2.0,
            "step": 0.01,
            "unit": "倍",
            "desc": "首板前日开盘/最近30日最低 < 此值（低位启动过滤，规则5）",
        },
        {
            "key": "first_wave_lookback_days",
            "label": "第一波回看天数",
            "type": "int",
            "default": 20,
            "min": 5,
            "max": 60,
            "step": 1,
            "unit": "天",
            "desc": "回看 N 个交易日内无其他连板波才算第一波（规则1）",
        },
        {
            "key": "auction_limit_down_pct",
            "label": "竞价跌停判定",
            "type": "percent",
            "default": -0.098,
            "min": -0.11,
            "max": -0.05,
            "step": 0.001,
            "desc": "昨日连板票竞价涨幅 ≤ 此值记为竞价跌停（默认 -9.8%）",
        },
        {
            "key": "max_auction_limit_down",
            "label": "竞价跌停数上限",
            "type": "int",
            "default": 2,
            "min": 0,
            "max": 10,
            "step": 1,
            "unit": "只",
            "desc": "昨日连板票今日竞价跌停数超过此值 → 环境否决（用户规则：≤2）",
        },
        {
            "key": "scene_a_low_open",
            "label": "场景A 大幅低开",
            "type": "percent",
            "default": -0.05,
            "min": -0.10,
            "max": -0.01,
            "step": 0.005,
            "desc": "竞价涨幅 ≤ 此值 → 场景A 直接买入（默认 -5%）",
        },
        {
            "key": "scene_b_low_open",
            "label": "场景B 低开下限",
            "type": "percent",
            "default": -0.05,
            "min": -0.08,
            "max": -0.001,
            "step": 0.005,
            "desc": "竞价涨幅在 [此值, 0) → 场景B 待盘中放量上攻（默认 -5%，用户 2026-09-17 调整）",
        },
        {
            "key": "intraday_window_min",
            "label": "盘中观察窗口",
            "type": "int",
            "default": 10,
            "min": 5,
            "max": 120,
            "step": 1,
            "unit": "分钟",
            "desc": "仅开盘后前 N 分钟内寻找 B/C 触发，超时不触发（默认 10 分钟，用户 2026-09-17 调整）",
        },
        {
            "key": "intraday_min_rise",
            "label": "盘中快速分钟涨跌",
            "type": "percent",
            "default": 0.01,
            "min": 0.002,
            "max": 0.05,
            "step": 0.001,
            "desc": "单分钟涨/跌幅 ≥ 此值视为快速（用户定义 1%）",
        },
        {
            "key": "intraday_vol_multiple",
            "label": "盘中放量倍数",
            "type": "float",
            "default": 1.5,
            "min": 1.0,
            "max": 5.0,
            "step": 0.1,
            "unit": "倍",
            "desc": "触发分钟量 ≥ 前5分钟均量 × 此值（默认 1.5x）",
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

    def build_pool(self, settings: "Settings", date: str):
        return build_lianban_candidates(settings, date)

    def classify_scenes(self, candidates: list, settings: "Settings", cur_date: str) -> list:
        return classify_scenes(candidates, settings, cur_date)

    def scene_kind(self, scene: str) -> str:
        return {"A": SCENE_IMMEDIATE, "B": SCENE_PENDING, "C": SCENE_PENDING}.get(scene, SCENE_SKIP)

    def confirm_intraday(self, points: list[dict], item: dict, params: dict) -> ConfirmOutcome:
        r = evaluate_intraday_scene(
            points, item["scene"],
            window=int(params["intraday_window_min"]),
            min_pct=params["intraday_min_rise"],
            vol_multiple=params["intraday_vol_multiple"],
        )
        return ConfirmOutcome(triggered=r.triggered, detail=r.detail, data=r.model_dump())

    def intraday_expired(self, points: list[dict], params: dict) -> bool:
        # 分时根数越过观察窗口仍未触发 → 前 N 根已固定，结果恒定（2026-09-17）
        return len(points) > int(params["intraday_window_min"])
