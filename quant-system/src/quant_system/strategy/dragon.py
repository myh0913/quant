"""策略三：龙回头（原 strategy_dragon.py 迁移 + 注册表适配）。

用户规则（docs/USER_KNOWLEDGE.md §5，2026-09-19 修订）：
- 盘后(T-1)：最后一根K线之前是连续涨停状态（≥2连板的任意板数，紧邻无间隔）
  + 末根K线为首阴（收盘<开盘）→ 候选
  排除：三板组；首阴量>连板交易日最高成交量×1.5（2026-09-19，
  原首阴量/前日量2.5x口径已按用户要求移除）
- 首阴日形态过滤（2026-09-19 修订，分时判定，三分支）：
  高开 ≥3%：9:30-9:33 最高=开盘价（未冲高）+ 9:33 前最低 ≤ -2% + 9:33→收盘振幅 ≤ 3%
  低开 ≤-2%：首阴量 < 连板峰值×0.8（缩量）+ 全天振幅 ≤ 3%
  平开（-2%~+3%）：首阴量 < 连板峰值×1.0 + 未冲高 + 9:33 时点价格 ≤ -2% + 9:33后振幅 ≤ 3%
- 竞价(T)：大幅低开<-5% 直接买；稍微低开/高开低走 待盘中；高开高走不追
- 盘中：承接=3分钟±2%；横盘=10分钟±2%（用户已定义）
  出货检测（反复拉升）：用户标注待程序化，当前占位不拦截
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from .. import config_registry
from ..advice import Advice
from ..analyzer import MORNING_CUTOFF, DailyBarAnalyzer, DayInfo
from ..cycle import CycleThresholds, DEFAULT_THRESHOLDS, classify, compute_indicators, strategy_gate
from ..datasource.resolve import (
    data_session,
    standard_daily_bars,
    standard_limit_up_pool,
    standard_minute_points,
    standard_monitor_stocks,
    standard_opening_match,
    standard_pre_close,
)
from ..models import MonitorStock
from ..risk import run_risk_checks
from ..timeutil import shift_calendar_days
from .base import SCENE_IMMEDIATE, SCENE_PENDING, SCENE_SKIP, ConfirmOutcome, Strategy, register

if TYPE_CHECKING:
    from ..config import Settings


class DragonCandidate(BaseModel):
    """龙回头候选（盘后结构过滤后）。"""

    thscode: str
    name: str
    boards: int = Field(..., description="此前连板波天数（≥2）")
    shape: str = Field("", description="首阴形态：大阴线/长上引线/普通阴线")
    pb_volume_ratio: Optional[float] = Field(None, description="首阴量/前日量")
    shape_open_pct: Optional[float] = Field(None, description="首阴日开盘涨幅（今开/昨收-1）")
    wave_volume_ratio: Optional[float] = Field(None, description="首阴量/连板日最大量")
    notes: list[str] = Field(default_factory=list)
    rejected: bool = False
    reject_reason: str = ""


class DragonScene(BaseModel):
    thscode: str
    name: str
    scene: str = Field(..., description="D=大幅低开直接买 / E=低开待承接横盘 / F=高开低走待横盘 / X=不参与")
    auction_pct: Optional[float] = None
    detail: str = ""


class IntradayConfirm(BaseModel):
    """盘中承接/横盘确认结果。"""

    confirmed: bool = False
    confirm_time: Optional[str] = None
    confirm_price: Optional[float] = None
    detail: str = ""


class DragonReport(BaseModel):
    strategy: str = "龙回头"
    data_date: str
    ran_at: datetime
    pool_size: int = 0
    candidates: list[DragonCandidate] = Field(default_factory=list)
    rejected: list[DragonCandidate] = Field(default_factory=list)
    scenes: list[DragonScene] = Field(default_factory=list)
    confirms: list[IntradayConfirm] = Field(default_factory=list)
    advices: list[Advice] = Field(default_factory=list)
    blocked: list[dict] = Field(default_factory=list)
    # 情绪周期门控原因（否决时报告为空，必须可解释）
    gate_state: str = ""
    gate_note: str = ""


# ---------- 盘后候选 ----------

def build_dragon_candidates(settings: "Settings", date: str) -> tuple[list[DragonCandidate], list[DragonCandidate]]:
    """T-1 盘后：找"≥2连板 + 波后首阴(最后一根K线)"的票。

    ⚠️ 数据源：候选在 T-1 是阴线不在涨停池，必须查 T-2~T-6 的涨停池
    找回连板波股票，再用日线精确判定首阴。
    """
    # 1. 从近 6 个自然日（覆盖~4交易日）的涨停池收集所有出现过的股票
    from ..pool import is_target_stock
    from ..snapshot import SnapshotMissing

    stock_set: dict[str, str] = {}  # thscode -> name
    for delta in range(2, 8):  # T-2 ~ T-7
        d = shift_calendar_days(date, -delta)
        try:
            items = standard_limit_up_pool(settings, d)
        except SnapshotMissing:
            raise  # 回放模式快照缺失必须上浮（否则静默得出 0 候选的假成功）
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            if int(it.get("continue_day_cnt") or 0) >= 1:
                code, nm = it.get("thscode", ""), it.get("name", "")
                # 只做 60/00 主板、非 ST（创业板/科创板/北交所/可转债不参与，2026-09-17）
                if is_target_stock(code, nm):
                    stock_set.setdefault(code, nm)

    passed: list[DragonCandidate] = []
    rejected: list[DragonCandidate] = []

    # 阈值来自配置中心（量化配置页可改，热生效）
    p = config_registry.get_params(settings, "dragon")

    with data_session(settings):
        for thscode, name in stock_set.items():
            if not thscode:
                continue
            cand = DragonCandidate(thscode=thscode, name=name, boards=0)

            bars = standard_daily_bars(settings, thscode, date, lookback_days=60)
            if len(bars) < 10:
                cand.rejected, cand.reject_reason = True, "日线不足"
                rejected.append(cand)
                continue
            az = DailyBarAnalyzer(bars)
            if az.has_suspect_day():
                cand.rejected, cand.reject_reason = True, "日线疑似除权/数据异常（单日涨跌幅越界）"
                rejected.append(cand)
                continue
            w = az.last_wave()
            if w is None or w.days < 2:
                continue  # 无≥2连板波，非本策略对象（静默跳过，不占拒绝清单）
            cand.boards = w.days
            pb = az.pullback_day()
            if pb is None:
                continue  # 波后未出现首阴或首阴非最新K线（静默跳过）
            cand.shape = az.pullback_shape()
            vr = az.pullback_volume_ratio()
            cand.pb_volume_ratio = vr
            # 排除：首阴量 > 连板交易日最高成交量 × wave_volume_ratio_max（2026-09-19）
            wave_max_vol = max((d.volume for d in az.days[w.start_idx:w.end_idx + 1]), default=0.0)
            if wave_max_vol > 0:
                wvr = pb.volume / wave_max_vol
                cand.wave_volume_ratio = wvr
                if wvr > float(p["wave_volume_ratio_max"]):
                    cand.rejected, cand.reject_reason = True, (
                        f"首阴量超连板峰值（{wvr:.2f}x > {float(p['wave_volume_ratio_max'])}x）"
                    )
                    rejected.append(cand)
                    continue
            # 排除：首阴日形态/量能不符（2026-09-19，高开/低开/平开三分支）
            shape_rej = _pullback_shape_reject(settings, thscode, pb, p, wave_max_vol)
            if shape_rej:
                cand.rejected, cand.reject_reason = True, shape_rej
                rejected.append(cand)
                continue
            # 排除三板组（基于该波）
            if w.days == 3 and _wave_is_sanbanzu(az, w):
                cand.rejected, cand.reject_reason = True, "三板组"
                rejected.append(cand)
                continue
            sop = (pb.open - pb.pre_close) / pb.pre_close if pb.pre_close else None
            cand.shape_open_pct = sop
            shape_tag = (
                "首阴高开回踩" if sop is not None and sop >= float(p["shape_high_open_pct"])
                else "首阴低开收敛" if sop is not None and sop <= float(p["shape_low_open_pct"])
                else "首阴平开低走"
            )
            cand.notes = [f"前波{w.days}连板", f"首阴形态={cand.shape}",
                          f"首阴量比={vr and round(vr, 2)}x",
                          f"{shape_tag}" + (f"（开盘{sop*100:+.2f}%）" if sop is not None else ""),
                          *( [f"首阴/连板峰值={cand.wave_volume_ratio and round(cand.wave_volume_ratio, 2)}x"]
                             if cand.wave_volume_ratio is not None else [] )]
            passed.append(cand)
    return passed, rejected


def _pullback_shape_reject(
    settings: "Settings", thscode: str, pb: DayInfo, p: dict, wave_max_vol: float = 0.0
) -> str:
    """首阴日形态/量能过滤（用户 2026-09-19，三分支）：返回拒绝原因，空串=通过。

    - 高开 ≥ shape_high_open_pct：9:30-9:33 最高=开盘价（未冲高）+ 9:33 前最低
      ≤ shape_morning_low_pct + 9:33→收盘振幅 ≤ shape_range_pct；
    - 低开 ≤ shape_low_open_pct：首阴量 < 连板峰值 × shape_low_volume_ratio
      + 全天振幅 ≤ shape_range_pct；
    - 平开（两者之间，原空档新场景）：首阴量 < 连板峰值 × shape_flat_volume_ratio
      + 未冲高 + 9:33 时点价格 ≤ shape_morning_low_pct + 9:33后振幅 ≤ shape_range_pct。

    "最高价是开盘价"语义 = 开盘后 3 分钟未冲高（区间最高 ≤ 开盘价 + 微小容差；
    分时无 bar 最高价，用分钟价近似）。振幅 =（区间最高-区间最低）/昨收。
    """
    pre = pb.pre_close
    if not pre:
        return "首阴日昨收缺失"
    from ..snapshot import SnapshotMissing

    open_pct = (pb.open - pre) / pre
    hi_thr = float(p["shape_high_open_pct"])
    lo_thr = float(p["shape_low_open_pct"])
    range_max = float(p["shape_range_pct"])
    wvr: Optional[float] = (
        pb.volume / wave_max_vol if wave_max_vol > 0 else None
    )

    try:
        points = standard_minute_points(settings, thscode, pb.date)
    except SnapshotMissing:
        raise  # 回放模式快照缺失必须上浮
    except Exception:  # noqa: BLE001
        return "首阴日分时获取失败"
    pts = [q for q in points if q.get("price") and q["price"] > 0]
    if not pts:
        return "首阴日分时缺失"
    early = [q for q in pts if q["time_label"] <= MORNING_CUTOFF]
    if not early:
        return f"首阴日{MORNING_CUTOFF}前无分时"
    early_hi = max(q["price"] for q in early)
    pct_933 = (early[-1]["price"] - pre) / pre
    rushed = early_hi > pb.open * (1 + 1e-6)

    def _amp(seg: list[dict]) -> Optional[float]:
        if not seg:
            return None
        return (max(q["price"] for q in seg) - min(q["price"] for q in seg)) / pre

    if open_pct >= hi_thr:
        # 高开回踩：未冲高 + 9:33 前深水 + 其后收敛
        if rushed:
            return f"首阴9:33前冲高（9:30-9:33最高{early_hi:.2f} > 开盘{pb.open:.2f}）"
        ml = (min(q["price"] for q in early) - pre) / pre
        if ml > float(p["shape_morning_low_pct"]):
            return (f"首阴高开{open_pct*100:+.2f}%但9:33前未深水"
                    f"（{ml*100:.2f}% > {float(p['shape_morning_low_pct'])*100:.0f}%）")
        amp = _amp([q for q in pts if q["time_label"] >= MORNING_CUTOFF])
        if amp is None or amp > range_max:
            amp_text = f"{amp*100:.2f}%" if amp is not None else "数据缺失"
            return f"首阴9:33后振幅过大（{amp_text} > {range_max*100:.0f}%）"
        return ""
    if open_pct <= lo_thr:
        # 低开收敛：缩量（<0.6x）+ 全天振幅
        if wvr is not None and wvr >= float(p["shape_low_volume_ratio"]):
            return (f"首阴低开量能偏大（{wvr:.2f}x ≥ "
                    f"{float(p['shape_low_volume_ratio'])}x）")
        amp = _amp(pts)
        if amp is None or amp > range_max:
            amp_text = f"{amp*100:.2f}%" if amp is not None else "数据缺失"
            return f"首阴低开{open_pct*100:+.2f}%但全天振幅过大（{amp_text} > {range_max*100:.0f}%）"
        return ""
    # 平开低走（-2% ~ +3%）：缩量（<0.7x）+ 未冲高 + 9:33 深水 + 其后收敛
    if wvr is not None and wvr >= float(p["shape_flat_volume_ratio"]):
        return (f"首阴平开量能偏大（{wvr:.2f}x ≥ "
                f"{float(p['shape_flat_volume_ratio'])}x）")
    if rushed:
        return f"首阴9:33前冲高（9:30-9:33最高{early_hi:.2f} > 开盘{pb.open:.2f}）"
    if pct_933 > float(p["shape_morning_low_pct"]):
        return (f"首阴平开9:33未至深水（{pct_933*100:.2f}% > "
                f"{float(p['shape_morning_low_pct'])*100:.0f}%）")
    amp = _amp([q for q in pts if q["time_label"] >= MORNING_CUTOFF])
    if amp is None or amp > range_max:
        amp_text = f"{amp*100:.2f}%" if amp is not None else "数据缺失"
        return f"首阴9:33后振幅过大（{amp_text} > {range_max*100:.0f}%）"
    return ""


def _wave_is_sanbanzu(az: DailyBarAnalyzer, w) -> bool:
    """判断指定波是否三板组（首板量≤前日1.2倍+两一字+量≤首板1/10）。"""
    if w.days != 3:
        return False
    d1, d2, d3 = az.days[w.start_idx], az.days[w.start_idx + 1], az.days[w.start_idx + 2]
    pre_vol = az.days[w.start_idx - 1].volume if w.start_idx > 0 else float("inf")
    return (
        d1.volume <= pre_vol * 1.2
        and d2.is_one_word and d3.is_one_word
        and d2.volume <= d1.volume * 0.1 and d3.volume <= d1.volume * 0.1
    )


# ---------- 竞价场景 ----------

def classify_dragon_scenes(candidates: list[DragonCandidate], settings: "Settings", cur_date: str) -> list[DragonScene]:
    """竞价场景分类（低开/高开阈值来自配置中心）。"""
    p = config_registry.get_params(settings, "dragon")
    low_d = p["scene_d_low_open"]
    low_e = p["scene_e_low_open"]
    max_chase = p["max_chase_open"]
    scenes: list[DragonScene] = []
    with data_session(settings):
        for c in candidates:
            try:
                om = standard_opening_match(settings, c.thscode, cur_date)
                pre = standard_pre_close(settings, c.thscode, cur_date)
            except Exception:  # noqa: BLE001
                scenes.append(DragonScene(thscode=c.thscode, name=c.name, scene="X", detail="竞价数据失败"))
                continue
            if om is None or not pre:
                scenes.append(DragonScene(thscode=c.thscode, name=c.name, scene="X", detail="无竞价/昨收"))
                continue
            pct = (om.price - pre) / pre
            if pct <= low_d:
                scene, detail = "D", f"大幅低开 {pct*100:.2f}%（<={low_d*100:.0f}%，直接买入）"
            elif low_e <= pct < 0:
                scene, detail = "E", f"稍微低开 {pct*100:.2f}%（待盘中承接+横盘确认）"
            elif pct >= max_chase:
                scene, detail = "X", f"高开高走 {pct*100:.2f}%（≥{max_chase*100:.0f}%，不追）"
            else:  # 0 ~ max_chase 高开
                scene, detail = "F", f"高开 {pct*100:.2f}%（若盘中低走待横盘确认；直接高走不追）"
            scenes.append(DragonScene(thscode=c.thscode, name=c.name, scene=scene, auction_pct=pct, detail=detail))
    return scenes


# ---------- 盘中承接/横盘确认 ----------

def confirm_chengjie_hengpan(
    points: list[dict], *, range_pct: float = 0.02, chengjie_min: int = 3, hengpan_min: int = 10
) -> IntradayConfirm:
    """场景E确认：分时稳住 → 承接（3分钟±2%）→ 横盘（连续10分钟±2%）。

    用户定义：承接=3分钟内波动±2%；横盘=连续10分钟波动±2%。
    实现：从某分钟起，此后连续 N 分钟的价格都在该分钟价 ±range_pct 内。
    """
    if len(points) < chengjie_min + hengpan_min:
        return IntradayConfirm(detail=f"分时不足（需≥{chengjie_min + hengpan_min}点）")
    for i in range(1, len(points) - hengpan_min + 1):
        base = points[i]["price"]
        window = points[i : i + hengpan_min]
        if all(abs(p["price"] - base) / base <= range_pct for p in window):
            return IntradayConfirm(
                confirmed=True,
                confirm_time=window[hengpan_min - 1]["time_label"],
                confirm_price=window[-1]["price"],
                detail=f"{window[0]['time_label']}起连续{hengpan_min}分钟波动±{range_pct*100:.0f}%内（承接{chengjie_min}分钟+横盘）",
            )
    return IntradayConfirm(detail=f"未出现连续{hengpan_min}分钟±{range_pct*100:.0f}%横盘")


# ---------- 编排 ----------

def run_dragon(settings: "Settings", prev_date: str, cur_date: str,
               thresholds: CycleThresholds = DEFAULT_THRESHOLDS) -> DragonReport:
    """龙回头：退潮/冰点 → 全局否决（分歧态允许，符合策略三定位）。"""
    try:
        indicators = compute_indicators(settings, cur_date)
        cycle_j = classify(indicators, thresholds)
        gate_ok, gate_factor, gate_note = strategy_gate(cycle_j.state, "龙回头", cycle_j.overheated)
    except Exception as exc:  # noqa: BLE001
        cycle_j, gate_ok, gate_factor, gate_note = None, True, 1.0, f"周期计算失败（{exc}）放行待复核"
    if not gate_ok:
        return DragonReport(
            data_date=cur_date, ran_at=datetime.now(timezone.utc), pool_size=0,
            gate_state=cycle_j.state.value if cycle_j else "unknown",
            gate_note=gate_note,
        )

    passed, rejected = build_dragon_candidates(settings, prev_date)
    report = DragonReport(
        data_date=cur_date,
        ran_at=datetime.now(timezone.utc),
        pool_size=len(passed) + len(rejected),
        candidates=passed,
        rejected=rejected,
        gate_state=cycle_j.state.value if cycle_j else "",
        gate_note=gate_note,
    )
    scenes = classify_dragon_scenes(passed, settings, cur_date)
    report.scenes = scenes

    monitors: list[MonitorStock] = []
    try:
        monitors = standard_monitor_stocks(settings)
    except Exception:  # noqa: BLE001
        pass

    # 盘中确认参数（承接/横盘时长与波动带）来自配置中心
    dp = config_registry.get_params(settings, "dragon")

    with data_session(settings):
        for sc in scenes:
            if sc.scene == "X":
                continue
            # 场景E/F：盘中确认
            if sc.scene in ("E", "F"):
                points = standard_minute_points(settings, sc.thscode, cur_date)
                cf = confirm_chengjie_hengpan(
                    points,
                    range_pct=dp["hengpan_range_pct"],
                    chengjie_min=int(dp["chengjie_minutes"]),
                    hengpan_min=int(dp["hengpan_minutes"]),
                )
                report.confirms.append(cf)
                if not cf.confirmed:
                    continue
            # 场景D：直接建议
            checks = run_risk_checks(sc.thscode, monitors)
            hard_fail = [c for c in checks if not c.passed and c.hard_block]
            if hard_fail:
                report.blocked.append({"thscode": sc.thscode, "name": sc.name, "reasons": [c.detail for c in hard_fail]})
                continue
            cand = next((c for c in passed if c.thscode == sc.thscode), None)
            # 仓位梯度（M3）：基准仓位 × 周期系数
            from ..portfolio import position_display

            base_pct = float(config_registry.get_params(settings, "dragon")["base_position_pct"])
            pos_pct, pos_text = position_display(base_pct, gate_factor)
            action_map = {"D": "买入建议（场景D：大幅低开）", "E": "买入建议（场景E：低开+承接横盘确认）", "F": "买入建议（场景F：高开低走至横盘）"}
            report.advices.append(
                Advice(
                    thscode=sc.thscode,
                    name=sc.name,
                    strategy="龙回头",
                    action=action_map[sc.scene],
                    generated_at=datetime.now(timezone.utc),
                    data_date=cur_date,
                    reference_price=None,
                    trigger_condition=sc.detail,
                    position=pos_text,
                    position_pct=pos_pct,
                    valid_until="当日有效",
                    factor_summary={"scene": sc.scene, "auction_pct": sc.auction_pct,
                                    "boards": cand.boards if cand else None,
                                    "shape": cand.shape if cand else None},
                    reasons=[sc.detail] + (cand.notes if cand else []),
                    risk_notes=[f"{c.name}: {c.detail}" for c in checks],
                    pending_confirmations=["止损规则待确认",
                                            "出货检测（反复拉升）待程序化"],
                )
            )
    # 组合风控（M3）：单票去重 + 总仓位上限，超出降级为观察
    from ..portfolio import apply_portfolio_limits

    apply_portfolio_limits(report.advices, settings)
    return report


# ============================== 注册表适配 ==============================


@register
class DragonStrategy(Strategy):
    """龙回头：盘后建池 + 竞价场景 + 盘中承接/横盘确认。"""

    strategy_id = "dragon"
    label = "龙回头"
    has_pool_phase = True
    has_intraday_phase = True
    candidate_model = DragonCandidate

    params_schema = [
        {
            "key": "wave_volume_ratio_max",
            "label": "首阴量/连板峰值上限",
            "type": "float",
            "default": 1.5,
            "min": 1.0,
            "max": 5.0,
            "step": 0.1,
            "unit": "倍",
            "desc": "首阴量 > 连板交易日最高成交量 × 此值 → 排除（2026-09-19 用户规则 1.5x）",
        },
        {
            "key": "shape_high_open_pct",
            "label": "首阴形态高开阈值",
            "type": "percent",
            "default": 0.03,
            "min": 0.005,
            "max": 0.15,
            "step": 0.005,
            "desc": "首阴日开盘涨幅 ≥ 此值 → 要求 9:33 前深水 + 其后收敛（用户规则 默认 +3%）",
        },
        {
            "key": "shape_morning_low_pct",
            "label": "首阴形态早盘深水",
            "type": "percent",
            "default": -0.02,
            "min": -0.10,
            "max": -0.001,
            "step": 0.005,
            "desc": "首阴高开分支：截至 9:33 的当日最低涨幅 ≤ 此值（默认 -2%）",
        },
        {
            "key": "shape_low_open_pct",
            "label": "首阴形态低开阈值",
            "type": "percent",
            "default": -0.02,
            "min": -0.10,
            "max": -0.001,
            "step": 0.005,
            "desc": "首阴日开盘涨幅 ≤ 此值 → 要求全天振幅收敛（默认 -2%）",
        },
        {
            "key": "shape_range_pct",
            "label": "首阴形态振幅上限",
            "type": "percent",
            "default": 0.03,
            "min": 0.005,
            "max": 0.10,
            "step": 0.005,
            "desc": "高开/平开分支=9:33→收盘 / 低开分支=全天的（最高-最低）/昨收 ≤ 此值（默认 3%）",
        },
        {
            "key": "shape_low_volume_ratio",
            "label": "首阴低开量能上限",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 2.0,
            "step": 0.05,
            "unit": "倍",
            "desc": "首阴低开分支：首阴量须 < 连板峰值 × 此值（用户规则 默认 0.8x，缩量低开）",
        },
        {
            "key": "shape_flat_volume_ratio",
            "label": "首阴平开量能上限",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 2.0,
            "step": 0.05,
            "unit": "倍",
            "desc": "首阴平开分支：首阴量须 < 连板峰值 × 此值（用户规则 默认 1.0x）",
        },
        {
            "key": "scene_d_low_open",
            "label": "场景D 大幅低开",
            "type": "percent",
            "default": -0.05,
            "min": -0.10,
            "max": -0.01,
            "step": 0.005,
            "desc": "竞价涨幅 ≤ 此值 → 场景D 直接买入（默认 -5%）",
        },
        {
            "key": "scene_e_low_open",
            "label": "场景E 低开下限",
            "type": "percent",
            "default": -0.03,
            "min": -0.08,
            "max": -0.001,
            "step": 0.005,
            "desc": "竞价涨幅在 [此值, 0) → 场景E 待承接横盘确认（默认 -3%）",
        },
        {
            "key": "max_chase_open",
            "label": "高开不追上限",
            "type": "percent",
            "default": 0.05,
            "min": 0.01,
            "max": 0.15,
            "step": 0.005,
            "desc": "竞价涨幅 ≥ 此值 → 高开高走不追（默认 5%）",
        },
        {
            "key": "hengpan_range_pct",
            "label": "横盘波动带",
            "type": "percent",
            "default": 0.02,
            "min": 0.005,
            "max": 0.05,
            "step": 0.001,
            "desc": "承接/横盘确认分钟内价格波动 ±此值内（用户定义 ±2%）",
        },
        {
            "key": "chengjie_minutes",
            "label": "承接时长",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 15,
            "step": 1,
            "unit": "分钟",
            "desc": "承接确认分钟数（用户定义 3 分钟）",
        },
        {
            "key": "hengpan_minutes",
            "label": "横盘时长",
            "type": "int",
            "default": 10,
            "min": 3,
            "max": 30,
            "step": 1,
            "unit": "分钟",
            "desc": "连续横盘分钟数（用户定义 10 分钟）",
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
        return build_dragon_candidates(settings, date)

    def classify_scenes(self, candidates: list, settings: "Settings", cur_date: str) -> list:
        return classify_dragon_scenes(candidates, settings, cur_date)

    def scene_kind(self, scene: str) -> str:
        return {"D": SCENE_IMMEDIATE, "E": SCENE_PENDING, "F": SCENE_PENDING}.get(scene, SCENE_SKIP)

    def confirm_intraday(self, points: list[dict], item: dict, params: dict) -> ConfirmOutcome:
        r = confirm_chengjie_hengpan(
            points,
            range_pct=params["hengpan_range_pct"],
            chengjie_min=int(params["chengjie_minutes"]),
            hengpan_min=int(params["hengpan_minutes"]),
        )
        return ConfirmOutcome(triggered=r.confirmed, detail=r.detail, data=r.model_dump())
