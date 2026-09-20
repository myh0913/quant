"""策略包：统一协议（base）+ 三个策略实现。

导入本包即完成注册；业务代码一律通过注册表取策略：
    from .strategy import get_strategy, with_phase, all_strategies

新增策略：新建模块 → 实现 Strategy 子类 → @register → 在此 __init__ 导入。
"""
from .base import (
    SCENE_IMMEDIATE,
    SCENE_PENDING,
    SCENE_SKIP,
    ConfirmOutcome,
    Strategy,
    StrategyResult,
    all_strategies,
    get_strategy,
    register,
    schemas,
    strategy_ids,
    with_phase,
)

# 导入即注册（顺序 = 注册表顺序）
from .auction_grab import AuctionGrabStrategy, PipelineReport  # noqa: F401
from .dragon import DragonStrategy  # noqa: F401
from .lianban import LianbanStrategy  # noqa: F401
from .minutes import fetch_minute_points, open_minute_fetcher  # noqa: F401
from .tailpan import TailpanStrategy  # noqa: F401

# 组合风控：非策略（不参与阶段），注册仅为参数进配置中心。
# 注册类定义在此（而非 portfolio.py），避免 portfolio ↔ strategy 循环导入。
from ..portfolio import PORTFOLIO_LABEL, PORTFOLIO_PARAMS_SCHEMA


class PortfolioStrategy(Strategy):
    """组合风控参数卡：总仓位上限 / 板块集中度开关（未生效）。"""

    strategy_id = "portfolio"
    label = PORTFOLIO_LABEL
    params_schema = PORTFOLIO_PARAMS_SCHEMA


register(PortfolioStrategy)

__all__ = [
    "Strategy", "StrategyResult", "ConfirmOutcome",
    "SCENE_IMMEDIATE", "SCENE_PENDING", "SCENE_SKIP",
    "register", "get_strategy", "all_strategies", "strategy_ids", "with_phase", "schemas",
    "AuctionGrabStrategy", "LianbanStrategy", "DragonStrategy", "TailpanStrategy",
    "PortfolioStrategy",
    "PipelineReport",
    "fetch_minute_points", "open_minute_fetcher",
]
