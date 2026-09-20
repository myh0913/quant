"""风控层：对策略信号执行否决检查。

v0 最小实现：
- 监管黑名单（东财重点监控 + 严重异常波动）→ 硬否决
- 情绪周期状态机 → 占位检查（待设计，不假装已实现，不否决）
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import MonitorStock
from .pool import normalize_thscode


@dataclass
class RiskCheckResult:
    name: str
    passed: bool
    detail: str
    hard_block: bool = True


def check_monitor_blacklist(thscode: str, monitors: list[MonitorStock]) -> RiskCheckResult:
    """命中重点监控/严重异常波动 → 硬否决。

    代码先归一化为 .SH/.SZ 再比对（路 2026-09-06 实测：.SS vs .SH 失配导致漏拦）。
    """
    target = normalize_thscode(thscode)
    hit = next(
        (m for m in monitors if m.thscode and normalize_thscode(m.thscode) == target),
        None,
    )
    if hit:
        label = {"restricted": "重点监控", "severe": "严重异常波动", "unusual": "异常波动"}.get(
            hit.monitor_type, hit.monitor_type
        )
        return RiskCheckResult(
            name="监管黑名单",
            passed=False,
            detail=f"命中{label}: {hit.name} {(hit.reason or '')[:60]}",
        )
    return RiskCheckResult(name="监管黑名单", passed=True, detail="未命中")


def check_sentiment_cycle_placeholder() -> RiskCheckResult:
    """情绪周期状态机尚未设计；占位检查，当前不否决。"""
    return RiskCheckResult(
        name="情绪周期（占位）",
        passed=True,
        detail="状态机待设计（见 PROJECT_STATUS 下一步）；当前不否决",
        hard_block=False,
    )


def run_risk_checks(thscode: str, monitors: list[MonitorStock]) -> list[RiskCheckResult]:
    return [
        check_monitor_blacklist(thscode, monitors),
        check_sentiment_cycle_placeholder(),
    ]
