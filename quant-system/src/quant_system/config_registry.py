"""策略参数配置中心。

设计要点（M1 调整）：
- 参数 schema 以各策略类上的 params_schema 为单一事实来源（strategy/ 包），
  本模块通过注册表收集 —— 新增策略无需改本文件。
- 调度器启动时导出 data/config/schema.json，quant-web backend 只读该文件
  提供配置页 API，保持 backend 对本包零侵入（不 import）。
- 用户覆盖值存 data/config/active.json。get_params() 每次现读（文件极小、
  调用频率为分钟级），backend 保存后下一调度 tick 即热生效，无需重启。
- 任何非法覆盖（类型错/越界）回退代码默认值并告警——配置错误绝不能让
  策略静默跑偏（对齐 PROJECT_RULES「宁可拒绝，不可错报」）。

写入侧（保存/启用/回滚）在 quant-web/backend/main.py，读写分离：
写方仅 backend（配置页 API），读方仅 quant-system。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import Settings

log = logging.getLogger(__name__)


def strategy_ids() -> list[str]:
    """已注册策略 id（来自 strategy 注册表）。"""
    from .strategy import strategy_ids as _ids

    return _ids()


def strategy_schema(strategy_id: str) -> dict:
    """{label, params}；未知策略抛 KeyError。"""
    from .strategy import get_strategy

    s = get_strategy(strategy_id)
    return {"label": s.label, "params": s.params_schema}


def schemas() -> dict[str, dict]:
    """全部策略 {id: {label, params}}。"""
    from .strategy import schemas as _schemas

    return _schemas()


def _schema_path(settings: Settings) -> Path:
    return settings.data_dir / "config" / "schema.json"


def _active_path(settings: Settings) -> Path:
    return settings.data_dir / "config" / "active.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def export_schemas(settings: Settings) -> None:
    """导出参数 schema 到 data/config/schema.json（调度器启动时调用）。"""
    _atomic_write(_schema_path(settings), {"version": 1, "strategies": schemas()})


def load_active(settings: Settings) -> dict:
    """读取当前生效配置；缺失/损坏时返回空覆盖（全部走代码默认值）。"""
    p = _active_path(settings)
    if not p.exists():
        return {"version": 0, "saved_at": "", "actor": "", "strategies": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("active.json 读取失败，使用代码默认参数: %s", exc)
        return {"version": 0, "saved_at": "", "actor": "", "strategies": {}}


def _coerce(value: Any, pdef: dict) -> Any:
    """按参数定义校验/转换值；非法抛 ValueError。"""
    t = pdef["type"]
    try:
        if t == "int":
            v = int(value)
        elif t in ("percent", "float"):
            v = float(value)
        elif t == "bool":
            v = bool(value)
        else:
            v = value
    except (TypeError, ValueError):
        raise ValueError(f"参数 {pdef['key']} 类型错误（期望 {t}）")
    if t in ("percent", "float", "int"):
        if "min" in pdef and v < pdef["min"]:
            raise ValueError(f"参数 {pdef['key']} 低于下限 {pdef['min']}")
        if "max" in pdef and v > pdef["max"]:
            raise ValueError(f"参数 {pdef['key']} 超过上限 {pdef['max']}")
    return v


# 进程内临时覆盖（仅沙箱测试用）：sandbox 在独立子进程运行，模块级字典即隔离，
# 不触碰 active.json —— 测试参数绝不污染生产配置。
_OVERRIDES: dict[str, dict] = {}


def temporary_overrides(overrides: dict[str, dict]):
    """上下文管理器：with 块内 get_params() 优先返回覆盖值（同样过 schema 校验）。"""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        _OVERRIDES.update(overrides)
        try:
            yield
        finally:
            for sid in overrides:
                _OVERRIDES.pop(sid, None)

    return _ctx()


def get_params(settings: Settings, strategy_id: str) -> dict:
    """合并 沙箱覆盖 > 用户覆盖 > 代码默认；非法值回退默认并告警。"""
    schema = strategy_schema(strategy_id)  # 未知策略 KeyError 上浮
    overrides = _OVERRIDES.get(strategy_id) or load_active(settings).get("strategies", {}).get(strategy_id, {})
    out: dict[str, Any] = {}
    for pdef in schema["params"]:
        k, default = pdef["key"], pdef["default"]
        if k not in overrides:
            out[k] = default
            continue
        try:
            out[k] = _coerce(overrides[k], pdef)
        except ValueError as exc:
            log.warning("策略 %s 参数非法已回退默认: %s", strategy_id, exc)
            out[k] = default
    return out
