"""组合风控层（M3，2026-09-18）：建议出口的账户级约束。

规则（先到先得，超出降级为"观察不下单"）：
1. 单票去重：同一票当日只保留首条建议；
2. 总仓位上限：建议仓位合计 ≤ max_total_position（默认 80%，留现金）；
3. 同板块集中度：预留接口，板块数据源未接入前不生效（诚实降级，不假装）。

仓位梯度（cycle.strategy_gate 的 factor 0.3/0.5/1.0 + 过热减半）由
调用方（scheduler 各建议出口 / auction_grab）计算 position_pct 后传入。

参数经注册表进配置中心（strategy_id=portfolio，量化配置页"组合风控"卡，
热生效）；同时接受 dict / pydantic 模型两种条目形态（就地修改）。
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from . import config_registry

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger(__name__)

# 参数 schema 常量：注册类在 strategy/__init__.py（避免 portfolio ↔ strategy 循环导入）
PORTFOLIO_LABEL = "组合风控"
PORTFOLIO_PARAMS_SCHEMA = [
    {
        "key": "max_total_position",
        "label": "总仓位上限",
        "type": "float",
        "default": 0.8,
        "min": 0.3,
        "max": 1.0,
        "step": 0.05,
        "unit": "比例",
        "desc": "当日全部建议仓位合计上限（默认 80% 留现金；超出按触发先后降级）",
    },
    {
        "key": "enable_sector_concentration",
        "label": "同板块集中度（未生效）",
        "type": "bool",
        "default": False,
        "desc": "板块数据源未接入，当前开关不产生任何限制（接入后单板块≤40%）",
    },
]


def _get(item: Any, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _set(item: Any, key: str, value) -> None:
    if isinstance(item, dict):
        item[key] = value
    else:
        setattr(item, key, value)


def apply_portfolio_limits(items: list, settings: "Settings") -> dict:
    """对建议列表应用组合约束（按传入顺序=触发时间先到先得，就地修改）。

    每个条目读写：thscode / position_pct（0-1，可为 None 按 0 处理）；
    降级条目写：position_pct=0、demoted=True、portfolio_note=原因。
    返回统计 {kept, demoted_dup, demoted_total}。
    """
    p = config_registry.get_params(settings, "portfolio")
    max_total = float(p["max_total_position"])
    seen: set[str] = set()
    used = 0.0
    kept = demoted_dup = demoted_total = 0
    for it in items:
        code = _get(it, "thscode", "") or ""
        # 规则1：单票去重
        if code and code in seen:
            _set(it, "position_pct", 0.0)
            _set(it, "demoted", True)
            _set(it, "portfolio_note", "当日已有该票建议（单票去重）")
            demoted_dup += 1
            continue
        pct = float(_get(it, "position_pct") or 0.0)
        # 规则2：总仓位上限
        if used + pct > max_total + 1e-9:
            _set(it, "position_pct", 0.0)
            _set(it, "demoted", True)
            _set(it, "portfolio_note", f"总仓位超限（已用{used*100:.0f}%+{pct*100:.0f}%>上限{max_total*100:.0f}%，先到先得）")
            demoted_total += 1
            if code:
                seen.add(code)
            continue
        # 规则3：同板块集中度 —— 板块数据源未接入，预留（2026-09-18）
        used += pct
        if code:
            seen.add(code)
        if _get(it, "demoted") is None:
            _set(it, "demoted", False)
        kept += 1
    stats = {"kept": kept, "demoted_dup": demoted_dup, "demoted_total": demoted_total}
    if demoted_dup or demoted_total:
        log.info("组合风控：%d 保留，降级（重复 %d / 超总仓 %d）", kept, demoted_dup, demoted_total)
    return stats


def position_display(base_pct: float, factor: float) -> tuple[float, str]:
    """基准仓位 × 周期系数 → (position_pct, 展示文案)。"""
    pct = round(base_pct * factor, 4)
    return pct, f"{base_pct*100:.0f}%×{factor}={pct*100:.0f}%"
