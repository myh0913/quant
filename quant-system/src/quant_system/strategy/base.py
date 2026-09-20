"""策略统一协议与注册表（M1）。

目标：换/加策略 = 新增一个实现本协议的类并 @register，调度器、配置导出、
沙箱全部自动纳入，零处硬编码策略名。

阶段模型（对齐调度器现有时间轴）：
- auction   9:25 竞价阶段。has_auction_advice=True 的策略在此直接产出完整建议
            （如竞价主力抢筹）；连板/龙回头在此只做场景分类（结果进盘中计划）。
- pool      17:00 盘后建池，产出下一交易日候选（如连板/龙回头）。
- intraday  9:26-10:00 盘中确认，对 pending 场景用分钟分时判定触发。

参数 schema 以各策略类上的 params_schema 为单一事实来源（dict 结构与
data/config/schema.json 完全一致，由 config_registry 导出）。
"""
from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..config import Settings


class StrategyResult(BaseModel):
    """单因子级策略判定结果（竞价主力抢筹等即时策略用）。"""

    signal: bool = False
    passed: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)


class ConfirmOutcome(BaseModel):
    """盘中确认的统一返回（调度器据此落盘与去重）。"""

    triggered: bool = False
    detail: str = ""
    data: dict = Field(default_factory=dict, description="策略专属结果（原样落盘 result 字段）")


# 场景类别：调度器只认识这三类，不认识具体字母
SCENE_IMMEDIATE = "immediate"   # 竞价即可定论 → 直接出建议
SCENE_PENDING = "pending"       # 待盘中确认
SCENE_SKIP = "skip"             # 不参与


class Strategy(ABC):
    """策略协议。子类至少实现自己声明参与的阶段对应的方法。"""

    strategy_id: ClassVar[str]          # 配置中心键 & 落盘池前缀（lianban/dragon/auction_grab）
    label: ClassVar[str]                # 展示名（建议/推送里的策略名，须与历史落盘一致）
    params_schema: ClassVar[list[dict]] = []

    has_auction_advice: ClassVar[bool] = False   # 竞价阶段直接产出完整建议
    has_pool_phase: ClassVar[bool] = False       # 参与 17:00 盘后建池
    has_intraday_phase: ClassVar[bool] = False   # 参与盘中确认

    # ---------- 竞价阶段（has_auction_advice=True 时实现） ----------
    def run_auction_pipeline(self, settings: "Settings", date: str | None = None,
                             *, persist: bool = True, thresholds=None):
        raise NotImplementedError(f"{self.label} 不参与竞价建议阶段")

    # ---------- 盘后建池（has_pool_phase=True 时实现） ----------
    candidate_model: ClassVar[type[BaseModel] | None] = None

    def build_pool(self, settings: "Settings", date: str):
        """T 日盘后 → (通过, 被拒) 候选列表，元素为 candidate_model 实例。"""
        raise NotImplementedError(f"{self.label} 不参与盘后建池")

    def candidates_from_rows(self, rows: list[dict] | None) -> list[BaseModel] | None:
        """从盘后落盘池恢复候选；rows=None（无落盘）返回 None 由调用方重建。"""
        if rows is None or self.candidate_model is None:
            return None
        try:
            return [self.candidate_model.model_validate(r) for r in rows]
        except Exception:  # noqa: BLE001
            return None

    # ---------- 竞价场景分类（has_intraday_phase=True 时实现） ----------
    def classify_scenes(self, candidates: list, settings: "Settings", cur_date: str) -> list:
        """T 日 9:25 场景分类；返回元素须含 thscode/name/scene/detail/auction_pct。"""
        raise NotImplementedError(f"{self.label} 无场景分类")

    def scene_kind(self, scene: str) -> str:
        """场景字母 → immediate/pending/skip（调度器唯一依赖的分派依据）。"""
        raise NotImplementedError

    # ---------- 盘中确认（has_intraday_phase=True 时实现） ----------
    def confirm_intraday(self, points: list[dict], item: dict, params: dict) -> ConfirmOutcome:
        """points: [{time_label, price, volume}]；item: 盘中计划条目。"""
        raise NotImplementedError(f"{self.label} 不参与盘中确认")

    def intraday_expired(self, points: list[dict], params: dict) -> bool:
        """分时已越过策略观察窗口且未触发 → 结果恒定，调度器停止轮询并落归因。

        默认 False（如龙回头 E/F 全程有效至 10:00）；窗口有界的策略
        （连板 B/C 仅开盘前 N 分钟）应覆写。
        """
        return False


# ============================== 注册表 ==============================

_REGISTRY: dict[str, Strategy] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """类装饰器：注册策略实例。strategy_id 冲突直接报错（防静默覆盖）。"""
    instance = cls()
    if instance.strategy_id in _REGISTRY:
        raise RuntimeError(f"策略重复注册: {instance.strategy_id}")
    _REGISTRY[instance.strategy_id] = instance
    return cls


def get_strategy(strategy_id: str) -> Strategy:
    try:
        return _REGISTRY[strategy_id]
    except KeyError:
        raise KeyError(f"未知策略: {strategy_id}（已注册: {sorted(_REGISTRY)}）") from None


def all_strategies() -> list[Strategy]:
    return list(_REGISTRY.values())


def strategy_ids() -> list[str]:
    return sorted(_REGISTRY)


def with_phase(*, pool: bool = False, intraday: bool = False, auction_advice: bool = False) -> list[Strategy]:
    """按阶段筛选已注册策略（保持注册顺序）。"""
    out = []
    for s in _REGISTRY.values():
        if pool and not s.has_pool_phase:
            continue
        if intraday and not s.has_intraday_phase:
            continue
        if auction_advice and not s.has_auction_advice:
            continue
        out.append(s)
    return out


def schemas() -> dict[str, dict]:
    """{strategy_id: {label, params}} —— config_registry 导出 schema.json 的数据源。"""
    return {s.strategy_id: {"label": s.label, "params": s.params_schema} for s in _REGISTRY.values()}
