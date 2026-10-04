"""内置调度器 —— 纯 Python 常驻进程，与 OpenClaw/agent 完全无关。

用法：
    cd project/quant-system
    ./.venv/bin/python -m quant_system.scheduler            # 常驻运行
    ./.venv/bin/python -m quant_system.scheduler --once auction     # 手动单跑
    ./.venv/bin/python -m quant_system.scheduler --once postmarket

交易日时间轴（Asia/Shanghai）：
    09:25-09:40  策略一 竞价抢筹（一次；错过窗口跳过，可 --once 手动补）
    09:26-10:00  盘中触发轮询（每 60s；10:00 自动结束）
    14:45-15:00  尾盘选股（策略四当日候选，一次；失败自动重试）
    17:00-18:00  盘后建池（策略二/三明日候选）+ 情绪周期判定（失败自动重试）

产出全部落盘 data/advice/<date>/ → quant-web 监听目录实时推送前端。
状态 data/state/scheduler-<date>.json —— 重启幂等，当日已完成任务不重复执行。
"""
from __future__ import annotations

import argparse
import json
import logging
import time as _time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from . import config_registry

SH_TZ = ZoneInfo("Asia/Shanghai")
log = logging.getLogger("quant-scheduler")

AUCTION_WINDOW = ("09:25", "09:40")
INTRADAY_WINDOW = ("09:26", "10:00")
INTRADAY_INTERVAL = 60  # 秒
TAILPAN_WINDOW = ("14:45", "15:00")
POSTMARKET_WINDOW = ("17:00", "18:00")


def now_sh() -> datetime:
    return datetime.now(SH_TZ)


# ============================== 交易日历 ==============================


def _calendar_cache(settings: Settings) -> Path:
    return settings.data_dir / "state" / "calendar.json"


def _fetch_calendar(settings: Settings, need: str | None = None) -> tuple[set[str], bool]:
    """交易日列表（hithink 交易日历，缓存 5 天）。失败抛异常由调用方兜底。

    返回 (dates, authoritative)：authoritative=True 表示「本次取数成功」或
    「缓存为查询日当天写入」——源在交易日当天开盘前必然已包含当天
    （2026-09-28 实测：交易日 00:00 取数已含当日；09-25 中秋当天取数止于 09-24），
    因此权威日历"未列出今天"= 今天休市，可作为节假日判定依据。

    ⚠️ 上游日历只发布到"最近交易日"，跨交易日后旧缓存必然不覆盖当天。若 need
      （通常=今天）超出缓存覆盖范围，则改为最多每 1 小时强制刷新一次；
      否则 prev_trading_day 会取到错误的上一交易日
      （2026-09-10 实测踩坑：缓存最远 09-08，09-10 的上一交易日被当成 09-08，
       盘中计划用错 09-08 涨停池，策略二监控了两天前的票、策略三监控清单为空）。
    """
    cache = _calendar_cache(settings)
    now = datetime.now(SH_TZ)
    if cache.exists():
        try:
            j = json.loads(cache.read_text())
            fetched = datetime.fromisoformat(j["fetched_at"])
            dates = set(j["dates"])
            covered = not need or (dates and need <= max(dates))
            ttl = timedelta(days=5) if covered else timedelta(hours=1)
            if now - fetched < ttl:
                return dates, fetched.date() == now.date()
        except Exception:  # noqa: BLE001
            pass
    from .datasource.resolve import standard_trading_days

    try:
        dates = standard_trading_days(settings)
    except Exception:
        # 刷新失败也要推进时间戳：缓存未覆盖当天时每 15s tick 都会走到这里，
        # 不推进时间戳会把上游接口打爆（限流后全天拿不到日历）
        try:
            if cache.exists():
                old = json.loads(cache.read_text())
                if old.get("dates"):
                    cache.write_text(json.dumps(
                        {"fetched_at": now.isoformat(), "dates": old["dates"]}, ensure_ascii=False
                    ))
        except Exception:  # noqa: BLE001
            pass
        raise
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"fetched_at": datetime.now(SH_TZ).isoformat(), "dates": dates}, ensure_ascii=False)
    )
    return set(dates), True


_fallback_logged: set[str] = set()  # 已记过日志的日期（tick 15s 一次，避免刷屏）
_holiday_logged: set[str] = set()  # 权威日历判休市的日期（避免刷屏）


def is_trading_day(settings: Settings, date: str) -> bool:
    """交易日判定。
    - 日历覆盖内：以日历为准（节假日正确排除）
    - 权威日历（本次取数成功或缓存为当日写入）未列出且 date≤今天：判休市
      ——源开盘前即知当天开闭市，交易日当天必含当日（2026-09-25 中秋实测：
       当天取数止于 09-24，旧逻辑走周几兜底导致休市日全管线照跑产出脏数据）
    - 未来日期 / 日历获取失败 / 缓存非当日写入：周一至五兜底，否则每个交易日
      早晨调度器都会静默空转
      （2026-09-09 实测踩坑：竞价/盘中全天未跑且无任何告警）
    """
    wd = datetime.strptime(date, "%Y-%m-%d").weekday() < 5
    today = now_sh().strftime("%Y-%m-%d")
    try:
        cal, authoritative = _fetch_calendar(settings, need=date)
    except Exception as exc:  # noqa: BLE001
        log.warning("交易日历获取失败（%s），按周一至五兜底", exc)
        return wd
    if not cal:  # 空日历按获取失败处理，绝不能据此判为非交易日（否则全天空转）
        return wd
    if date in cal:
        return True
    if cal and date > max(cal):
        if date <= today and authoritative:
            if date not in _holiday_logged:
                _holiday_logged.add(date)
                log.info("交易日历（权威）未列出 %s → 判休市", date)
            return False
        if date not in _fallback_logged:
            _fallback_logged.add(date)
            log.info("交易日历未覆盖 %s（日历最远 %s），按周一至五兜底", date, max(cal))
        return wd
    return False


def prev_trading_day(settings: Settings, date: str) -> str:
    """上一个交易日。"""
    try:
        cal, _auth = _fetch_calendar(settings, need=date)
        before = [d for d in sorted(cal) if d < date]
        if before:
            return before[-1]
    except Exception:  # noqa: BLE001
        pass
    d = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ============================== 状态 ==============================


def _state_path(settings: Settings, date: str) -> Path:
    return settings.data_dir / "state" / f"scheduler-{date}.json"


def load_state(settings: Settings, date: str) -> dict:
    p = _state_path(settings, date)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"auction_done": False, "intraday_ended": False, "intraday_last": None,
            "tailpan_done": False, "postmarket_done": False, "postmarket_catchup_done": False,
            "intraday_triggered": [], "intraday_expired": []}


def save_state(settings: Settings, date: str, st: dict) -> None:
    p = _state_path(settings, date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1))


# ============================== 窗口判定（纯逻辑，可单测） ==============================


def in_window(now: datetime, start_hm: str, end_hm: str) -> bool:
    hm = now.strftime("%H:%M")
    return start_hm <= hm <= end_hm


def should_run_once(now: datetime, st: dict, key: str, window: tuple[str, str]) -> bool:
    return in_window(now, *window) and not st.get(key)


def should_tick(now: datetime, st: dict, window: tuple[str, str], interval_s: int) -> bool:
    """轮询窗口内 且（从未跑过 或 距上次 ≥ interval）。"""
    if not in_window(now, *window):
        return False
    last = st.get("intraday_last")
    if not last:
        return True
    last_dt = datetime.strptime(f"{now.date()} {last}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=SH_TZ)
    return (now - last_dt).total_seconds() >= interval_s


def window_passed(now: datetime, end_hm: str) -> bool:
    return now.strftime("%H:%M") > end_hm


def should_catchup_postmarket(now: datetime, st: dict) -> bool:
    """盘后窗口（17:00-18:00）已错过且当天从未成功跑过 → 当天内补跑一次。

    覆盖场景：窗口内服务中断/重启导致 postmarket 整体缺失
    （2026-09-28 实测：14:45 后服务消失、18:18 维护重启，17:00 建池/复盘/周期
    定版全部没跑，且复盘断档——09-24 建议永久漏结算）。补跑只试一次，
    失败不再自动重试（避免每 15s tick 打上游），留给 --once postmarket 手动补。
    """
    return (window_passed(now, POSTMARKET_WINDOW[1])
            and not st.get("postmarket_done")
            and not st.get("postmarket_catchup_done"))


# ============================== 任务 ==============================

# task_error 落盘节流：同任务 5 分钟内不重复告警
_task_error_last: dict[str, float] = {}


def _persist_task_error(settings: Settings, today: str, task: str, exc: Exception) -> None:
    """任务失败 → 落盘 task_error 报告，quant-web 后端监听后向前端广播告警。"""
    import time as _time

    now = _time.time()
    if now - _task_error_last.get(task, 0) < 300:
        return
    _task_error_last[task] = now
    try:
        from .store import persist_report

        persist_report(settings, today, "task_error", {
            "type": "task_error", "date": today, "task": task,
            "error": str(exc)[:300],
            "ran_at": datetime.now(SH_TZ).isoformat(),
        })
        log.warning("task_error 已落盘: %s %s", task, exc)
    except Exception:  # noqa: BLE001
        log.exception("task_error 落盘失败")


def task_auction(settings: Settings) -> str:
    """09:25 竞价阶段：注册表中所有 has_auction_advice 策略（当前=策略一）。返回摘要文本。"""
    from .strategy import with_phase

    parts = []
    for s in with_phase(auction_advice=True):
        r = s.run_auction_pipeline(settings)
        parts.append(
            f"[{s.label} {r.data_date}] 周期={r.cycle_state} 候选={r.candidates} "
            f"建议={len(r.advices)} 拦截={len(r.blocked)}"
        )
    summary = " ".join(parts)
    log.info(summary)
    return summary


def _load_saved_pool(settings: Settings, prev: str, kind: str) -> list[dict] | None:
    """读取盘后落盘的候选池（data/advice/<prev>/<kind>_pool_*.json 取最新一份）。

    返回 None = 没有可用落盘（盘后任务未跑/失败），调用方需现场重建；
    返回 [] = 盘后任务正常跑过但当日无候选，属有效结果，不应重建。
    """
    d = settings.data_dir / "advice" / prev
    files = sorted(d.glob(f"{kind}_pool_*.json"))
    if not files:
        return None
    try:
        j = json.loads(files[-1].read_text())
        return j.get("candidates") or []
    except Exception:  # noqa: BLE001
        return None


def _build_intraday_plan(settings: Settings, today: str) -> dict:
    """首次轮询时构建：昨日候选 + 今日竞价场景 → 待盘中确认清单（含即时建议）。

    注册表驱动：遍历 has_intraday_phase 策略。候选来源优先用盘后落盘池
    （17:00 盘后任务的权威产出，零 API 依赖、无日期歧义），缺失时才现场重建。
    候选池里的日期错了整场监控就全错，因此这里必须留下日志
    （2026-09-10 实测踩坑：日历缓存过期 → prev 取错 → 重建用了 T-2 涨停池，
     策略二监控了错误清单、策略三清单为空，且全程无一行日志可查）。
    """
    from . import config_registry
    from .strategy import SCENE_IMMEDIATE, with_phase

    prev = prev_trading_day(settings, today)

    # 门控状态合成（2026-09-29 重构，修"盘中计划用降级数据否决"问题）：
    # 当日 classify 在 9:26 恒 data_degraded（炸板率/晋级率要等涨停池 ~14:56 入库），
    # 降级判定不再直接用于否决；改为 当日classify(仅非降级采信) ⊕ T-1定版 ⊕ 实时恶化腿，
    # 取更差者（恶化立即生效）。全部缺失 → UNKNOWN 不否决（绝不静默禁用）。
    # T-0070 修复：classify/compute_indicators 此前漏导入 → NameError 被吞、当日复核腿
    # 恒失败回退（09-29 起每日日志「name 'classify' is not defined」）。
    from .cycle import classify, combined_gate_state, compute_indicators, prev_finalized

    pf = prev_finalized(settings, prev)
    try:
        j_today = classify(compute_indicators(settings, today))
    except Exception as exc:  # noqa: BLE001
        log.warning("盘中计划：当日周期复核失败（%s），回退 T-1 定版+恶化腿", exc)
        j_today = None
    state, over_eff, gate_reasons, gate_degraded = combined_gate_state(
        settings, today,
        pf["state"] if pf else None, bool(pf["overheated"]) if pf else False, j_today,
    )
    cycle_check = {
        "state": state.value if state else "UNKNOWN",
        "degraded": gate_degraded or (j_today is not None and j_today.data_degraded),
        "reasons": gate_reasons,
        "source": ("today_classify" if (j_today is not None and not j_today.data_degraded)
                   else ("prev_finalized+deterioration" if state else "none")),
    }

    # 桶结构：{strategy_id: [pending...], "immediate": [...]} —— 与历史缓存兼容
    # （旧缓存键即 lianban/dragon = strategy_id）；cycle_factors 为当日周期仓位系数（M3）
    plan: dict = {s.strategy_id: [] for s in with_phase(intraday=True)}
    plan["immediate"] = []
    plan["cycle_factors"] = {}
    _skip_keys = ("immediate", "cycle_factors")

    from .portfolio import apply_portfolio_limits, position_display

    for s in with_phase(intraday=True):
        if state is not None:
            from .cycle import strategy_gate as _gate

            ok, factor, note = _gate(state, s.label, over_eff)
            if not ok:
                log.warning("盘中计划：%s 被周期门控否决（%s），本日不监控", s.label, note)
                cycle_check.setdefault("vetoed", []).append(s.label)
                continue
            plan["cycle_factors"][s.strategy_id] = factor
        rows = _load_saved_pool(settings, prev, s.strategy_id)
        candidates = s.candidates_from_rows(rows)
        if candidates is None:
            log.warning("盘中计划：%s 无可用盘后池落盘（%s），现场重建（依赖行情接口）", s.label, prev)
            candidates, _ = s.build_pool(settings, prev)

        scenes = s.classify_scenes(candidates, settings, today)
        for sc in scenes:
            kind = s.scene_kind(sc.scene)
            if kind == SCENE_IMMEDIATE:
                plan["immediate"].append({
                    "strategy": s.label, "strategy_id": s.strategy_id,
                    "thscode": sc.thscode, "name": sc.name, "scene": sc.scene, "detail": sc.detail,
                })
            else:
                plan[s.strategy_id].append({
                    "strategy": s.label, "strategy_id": s.strategy_id,
                    "thscode": sc.thscode, "name": sc.name, "scene": sc.scene, "detail": sc.detail,
                })

    # 即时场景落盘（9:25 竞价即可定论），并补时间戳（前端时间列展示用）；
    # 仓位 = 基准 × 当日周期系数（M3），再过组合约束（单票去重/总仓位上限）
    from .store import persist_report

    cfg_ver = int(config_registry.load_active(settings).get("version") or 0)
    now_iso = datetime.now(SH_TZ).isoformat()
    for item in plan["immediate"]:
        sid = item.get("strategy_id") or item["strategy"]
        try:
            base_pct = float(config_registry.get_params(settings, sid)["base_position_pct"])
        except KeyError:
            base_pct = 0.2  # 旧缓存策略无该参数 → 沿用默认
        pos_pct, pos_text = position_display(base_pct, float(plan["cycle_factors"].get(sid, 1.0)))
        item["position_pct"] = pos_pct
        item["position"] = pos_text
        item["triggered_at"] = now_iso
        item["config_version"] = cfg_ver
    apply_portfolio_limits(plan["immediate"], settings)
    for item in plan["immediate"]:
        persist_report(settings, today, f"intraday_{item['strategy']}", item)
    # 盘中计划整体落盘到 advice 目录：前端“待确认”分区数据源 + quant-web 同步推送
    persist_report(settings, today, "intraday_plan", {
        "type": "intraday_plan", "date": today,
        "cycle_check": cycle_check,
        "pending": [i for sid in plan if sid not in _skip_keys for i in plan[sid]],
        "immediate": plan["immediate"],
    })
    log.info(
        "盘中计划 %s（prev=%s）：%s 即时建议=%d 条%s",
        today, prev,
        {sid: [(i["name"], i["scene"]) for i in plan[sid]] for sid in plan if sid not in _skip_keys},
        len(plan["immediate"]),
        f" 周期复核={cycle_check}" if cycle_check else "",
    )
    return plan


def task_intraday(settings: Settings, today: str, st: dict) -> None:
    """盘中轮询：注册表驱动，各策略 confirm_intraday 判定触发。触发即落盘。"""
    from . import config_registry
    from .cycle import compute_deterioration
    from .store import persist_report
    from .strategy import get_strategy, open_minute_fetcher

    cache_f = settings.data_dir / "state" / f"intraday-plan-{today}.json"
    if cache_f.exists():
        plan = json.loads(cache_f.read_text())
    else:
        plan = _build_intraday_plan(settings, today)
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(plan, ensure_ascii=False))

    triggered = set(st.get("intraday_triggered", []))
    expired = set(st.get("intraday_expired", []))
    _skip_keys = ("immediate", "cycle_factors")
    todo: list[tuple[dict, str]] = [
        (i, sid) for sid, items in plan.items() if sid not in _skip_keys for i in items
        if i["thscode"] not in triggered and i["thscode"] not in expired
    ]
    # 盘中恶化复检（每 5 分钟，2026-09-29）：恶化立即生效 → 当日剩余待监控票全部停止。
    # 触发落盘 intraday_halt 报告（quant-web 推送前端）+ 通知；已触发建议不可撤回，仅停后续。
    # T-0070：复检须先于 todo 早退执行 —— 09-30 实证 todo 清空（E 类触发）后，复检在
    # `if not todo: return` 处永久停摆至 10:00（末次复检 09:41:16，09:56/57 窗口命中点
    # 未被采到）；todo 已空时 halted=[] 仍照常落盘+通知，告知"监控已无对象、恶化仍在"。
    if not st.get("deterioration_fired"):
        now_dt = datetime.now(SH_TZ)
        last = st.get("deterioration_last")
        if last is None or (now_dt - datetime.fromisoformat(last)).total_seconds() >= 300:
            st["deterioration_last"] = now_dt.isoformat()
            chk = compute_deterioration(settings, today)
            if chk.triggered:
                st["deterioration_fired"] = True
                halted = [i["thscode"] for i, _sid in todo]
                expired.update(halted)
                st["intraday_expired"] = sorted(expired)
                persist_report(settings, today, "intraday_halt", {
                    "type": "intraday_halt", "date": today, "reasons": chk.reasons,
                    "halted": halted, "ran_at": now_dt.isoformat(),
                })
                log.warning("盘中恶化复检触发（%s）→ 停止当日剩余监控 %s", chk.reasons, halted)
                from .notify import notify

                notify(f"盘中恶化（{'; '.join(chk.reasons)}），停止当日剩余监控 {len(halted)} 只", "盘中恶化停机")
                save_state(settings, today, st)
                return

    if not todo:
        return

    # 旧版缓存 item 可能缺 strategy 字段，按 strategy_id 桶补齐；
    # 更旧的无 strategy_id 桶（键固定 lianban/dragon），也按桶名回填
    for item, sid in todo:
        s = get_strategy(sid)
        item.setdefault("strategy", s.label)
        item.setdefault("strategy_id", sid)

    fired = []
    window_closed = []
    attempted = 0
    fetch_fails = 0
    with open_minute_fetcher(settings) as fetch:
        for item, sid in todo:
            s = get_strategy(sid)
            code = item["thscode"]
            if code in triggered or code in expired:
                continue
            attempted += 1
            try:
                pts = fetch(code, today)
            except Exception as exc:  # noqa: BLE001
                fetch_fails += 1
                log.warning("分时获取失败 %s: %s", code, exc)
                continue
            params = config_registry.get_params(settings, s.strategy_id)
            r = s.confirm_intraday(pts, item, params)
            if r.triggered:
                fired.append((item, r))
            elif s.intraday_expired(pts, params):
                # 观察窗口已过且未触发 → 结果恒定，落归因并停止轮询（2026-09-17）
                window_closed.append((item, r))

    # 待监控票的分时全部获取失败 → 视为行情接口异常，交给调度层落盘告警
    if attempted and fetch_fails == attempted:
        raise RuntimeError(f"盘中分时全部获取失败（{fetch_fails}/{attempted}），疑似行情接口异常")

    # 触发建议补仓位（基准×当日周期系数）并过组合约束（M3；触发顺序=先到先得）
    from .portfolio import apply_portfolio_limits, position_display

    factors = plan.get("cycle_factors") or {}
    for item, _r in fired:
        sid = item.get("strategy_id") or item.get("strategy")
        try:
            base_pct = float(config_registry.get_params(settings, sid)["base_position_pct"])
        except KeyError:
            base_pct = 0.2  # 旧缓存/无该参数的策略 → 沿用默认
        pos_pct, pos_text = position_display(base_pct, float(factors.get(sid, 1.0)))
        item["position_pct"] = pos_pct
        item["position"] = pos_text
    apply_portfolio_limits([item for item, _r in fired], settings)

    for item, r in fired:
        entry = {**item, "result": r.data, "triggered_at": datetime.now(SH_TZ).isoformat(),
                 "config_version": int(config_registry.load_active(settings).get("version") or 0)}
        persist_report(settings, today, f"intraday_{item['thscode'].split('.')[0]}", entry)
        triggered.add(item["thscode"])
        log.info("盘中触发: %s %s %s", item["name"], item["scene"], r.detail)

    for item, r in window_closed:
        entry = {**item, "result": {"triggered": False, "window_expired": True, "detail": r.detail},
                 "triggered_at": datetime.now(SH_TZ).isoformat(),
                 "config_version": int(config_registry.load_active(settings).get("version") or 0)}
        persist_report(settings, today, f"intraday_{item['thscode'].split('.')[0]}", entry)
        expired.add(item["thscode"])
        log.info("盘中窗口过期未触发: %s %s %s", item["name"], item["scene"], r.detail)

    st["intraday_triggered"] = sorted(triggered)
    st["intraday_expired"] = sorted(expired)
    if fired:
        from .notify import notify

        notify("\n".join(f"{i['name']} {i['scene']} {r.detail}" for i, r in fired), "盘中触发")


STD_KEEP_DAYS = 7  # data/std 快照保留天数（2026-09-17 用户确认）


def _cleanup_std(settings: Settings, keep_days: int = STD_KEEP_DAYS) -> None:
    """清理 data/std/ 下超过保留天数的日期目录（每日盘后执行一次）。"""
    import shutil

    base = settings.data_dir / "std"
    if not base.is_dir():
        return
    cutoff = (now_sh() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    removed = 0
    for d in base.iterdir():
        if d.is_dir() and d.name <= cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    if removed:
        log.info("快照清理：删除 %s 前目录 %d 个（保留 %d 天）", cutoff, removed, keep_days)


def _cross_check_limit_up(settings: Settings, date: str) -> None:
    """涨停数主备源对账：hithink vs 选股通，差异过大落 task_error 告警（2026-09-17）。"""
    from .datasource.resolve import limit_up_pool_counts_by_source

    counts = limit_up_pool_counts_by_source(settings, date)
    valid = {k: v for k, v in counts.items() if v >= 0}
    if len(valid) < 2:
        log.warning("涨停池对账未完成（有效源不足）: %s", counts)
        return
    vals = list(valid.values())
    if max(vals) - min(vals) > max(5, int(0.1 * max(vals))):
        msg = f"涨停池对账异常：{counts}（{date}）"
        log.warning(msg)
        _persist_task_error(settings, date, "data_check", RuntimeError(msg))
    else:
        log.info("涨停池对账通过：%s", counts)


def task_tailpan(settings: Settings) -> str:
    """14:45 尾盘选股：尾盘策略当日候选（选股规则在 strategy/tailpan.py）。"""
    from .strategy.tailpan import run_tailpan_pool

    today = now_sh().strftime("%Y-%m-%d")
    prev = prev_trading_day(settings, today)
    return run_tailpan_pool(settings, today, prev)


def task_postmarket(settings: Settings, date: str | None = None) -> str:
    """17:00 盘后：注册表驱动建池（明日候选）+ 情绪周期判定，全部落盘。

    date 缺省=今天；回补历史交易日传 --date（建池/周期/复盘均按该日数据执行）。
    """
    from .cycle import classify, compute_indicators
    from .store import persist_report
    from .strategy import with_phase

    today = date or now_sh().strftime("%Y-%m-%d")
    summaries = []

    for s in with_phase(pool=True):
        passed, rejected = s.build_pool(settings, today)
        persist_report(settings, today, f"{s.strategy_id}_pool", {
            "type": f"{s.strategy_id}_pool", "date": today, "for_next_trading_day": True,
            "candidates": [c.model_dump() for c in passed],
            "rejected": [c.model_dump() for c in rejected],
        })
        summaries.append(f"{s.label}候选 {len(passed)}（拒 {len(rejected)}）")

    ind = compute_indicators(settings, today)
    j = classify(ind)
    persist_report(settings, today, "cycle", {
        "type": "cycle", "date": today, "state": j.state.value,
        "reasons": j.reasons, "overheated": j.overheated,
        "data_degraded": j.data_degraded,
        "indicators": {"temperature": ind.temperature, "limit_up": ind.limit_up_count,
                        "limit_down": ind.limit_down_count,
                        "break_ratio": ind.break_ratio, "promotion": ind.promotion_rate,
                        "height": ind.board_height, "leader": ind.leader_name},
    })
    summaries.append(f"周期={j.state.value}" + ("（数据降级）" if j.data_degraded else ""))

    # 快照目录按保留天数清理 + 涨停池主备源对账（失败均不阻断盘后产出）
    try:
        _cleanup_std(settings)
    except Exception:  # noqa: BLE001
        log.exception("快照清理失败（不影响盘后产出）")
    try:
        _cross_check_limit_up(settings, today)
    except Exception as exc:  # noqa: BLE001
        log.warning("涨停池对账未完成（不影响盘后产出）: %s", exc)

    # 复盘（M4）：对上一交易日建议做次日表现核算（失败不阻断盘后任务）
    try:
        from .review import run_review, summary_line

        rep = run_review(settings, today)
        summaries.append(summary_line(rep))
    except Exception as exc:  # noqa: BLE001
        log.exception("复盘任务失败（不影响建池产出）")
        _persist_task_error(settings, today, "review", exc)

    # 参数版本绩效聚合（M1 闭环）：复盘产出 → 配置页"本版本累计"数据源
    try:
        from .report import export_perf

        export_perf(settings)
    except Exception:  # noqa: BLE001
        log.exception("版本绩效聚合失败（不影响盘后产出）")

    text = f"[盘后 {today}] " + "；".join(summaries)
    log.info(text)
    from .notify import notify

    notify(text, "盘后建池")
    return text


# ============================== 主循环 ==============================


def tick_once(settings: Settings, now: datetime | None = None) -> dict:
    """单次调度检查（可单测/手动）。返回最新状态。"""
    now = now or now_sh()
    today = now.strftime("%Y-%m-%d")
    if not is_trading_day(settings, today):
        return {}
    st = load_state(settings, today)
    changed = False

    # 竞价任务
    if should_run_once(now, st, "auction_done", AUCTION_WINDOW):
        try:
            task_auction(settings)
        except Exception as exc:  # noqa: BLE001
            log.exception("auction 任务失败")
            _persist_task_error(settings, today, "auction", exc)
        st["auction_done"] = True
        changed = True

    # 盘中轮询
    if should_tick(now, st, INTRADAY_WINDOW, INTRADAY_INTERVAL):
        try:
            task_intraday(settings, today, st)
        except Exception as exc:  # noqa: BLE001
            log.exception("intraday 轮询失败")
            _persist_task_error(settings, today, "intraday", exc)
        st["intraday_last"] = now.strftime("%H:%M:%S")
        changed = True
    if window_passed(now, INTRADAY_WINDOW[1]) and not st.get("intraday_ended"):
        st["intraday_ended"] = True
        changed = True
        log.info("盘中轮询到点自动结束（10:00）")

    # 尾盘选股（失败不标记完成，窗口内下轮 tick 自动重试）
    if should_run_once(now, st, "tailpan_done", TAILPAN_WINDOW):
        try:
            task_tailpan(settings)
            st["tailpan_done"] = True
        except Exception as exc:  # noqa: BLE001
            log.exception("tailpan 任务失败（窗口内将重试）")
            _persist_task_error(settings, today, "tailpan", exc)
        changed = True

    # 盘后任务（失败不标记完成，窗口内下轮 tick 自动重试）
    if should_run_once(now, st, "postmarket_done", POSTMARKET_WINDOW):
        try:
            task_postmarket(settings)
            st["postmarket_done"] = True
        except Exception as exc:  # noqa: BLE001
            log.exception("postmarket 任务失败（窗口内将重试）")
            _persist_task_error(settings, today, "postmarket", exc)
        changed = True

    # 盘后补跑：窗口已错过（服务中断/重启）且当天从未成功 → 当天内补跑一次
    if should_catchup_postmarket(now, st):
        try:
            log.warning("postmarket 窗口已过仍未完成，执行补跑（%s）", today)
            task_postmarket(settings)
            st["postmarket_done"] = True
        except Exception as exc:  # noqa: BLE001
            log.exception("postmarket 补跑失败（不再自动重试，可 --once postmarket 手动补）")
            _persist_task_error(settings, today, "postmarket_catchup", exc)
        st["postmarket_catchup_done"] = True
        changed = True

    if changed:
        save_state(settings, today, st)
    return st


def _setup_logging() -> None:
    """stdout（systemd journal）+ 文件双通道；文件不可用不影响调度。

    2026-09-28 实测教训：journal -u quant-scheduler 只有 systemd 启停记录、
    logs/scheduler.log 停在 09-20，17:00 盘后管线缺失后完全无法归因。
    """
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "scheduler.log",
                                 maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:  # noqa: BLE001
        pass  # 日志文件不可用不阻断调度（仍有 stdout）


def run_loop(settings: Settings | None = None, tick_seconds: int = 15) -> None:
    settings = settings or Settings()
    settings.ensure_dirs()
    # 导出策略参数 schema + 数据源注册表（quant-web 配置页数据源；backend 零侵入只读）
    config_registry.export_schemas(settings)
    from .datasource.registry import export_datasources

    export_datasources(settings)
    _setup_logging()
    log.info("quant-system 调度器启动（tick=%ss，Ctrl+C 退出）", tick_seconds)
    while True:
        try:
            tick_once(settings)
        except KeyboardInterrupt:
            log.info("调度器退出")
            return
        except Exception:  # noqa: BLE001
            log.exception("调度 tick 异常（继续运行）")
        try:
            _time.sleep(tick_seconds)
        except KeyboardInterrupt:
            log.info("调度器退出")
            return


def main() -> None:
    ap = argparse.ArgumentParser(description="quant-system 内置调度器")
    ap.add_argument("--once", choices=["auction", "intraday", "tailpan", "postmarket"], help="手动单跑一个任务")
    ap.add_argument("--date", help="配合 --once postmarket：回补指定交易日（缺省=今天）")
    args = ap.parse_args()
    settings = Settings()
    settings.ensure_dirs()
    config_registry.export_schemas(settings)  # 手动单跑也要保证 schema 文件在位
    from .datasource.registry import export_datasources

    export_datasources(settings)
    _setup_logging()

    if not args.once:
        run_loop(settings)
        return
    if args.once == "auction":
        print(task_auction(settings))
    elif args.once == "intraday":
        today = now_sh().strftime("%Y-%m-%d")
        st = load_state(settings, today)
        task_intraday(settings, today, st)
        save_state(settings, today, st)
    elif args.once == "tailpan":
        print(task_tailpan(settings))
    else:
        print(task_postmarket(settings, args.date))


if __name__ == "__main__":
    main()
