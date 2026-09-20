"""标准化数据快照层（M3）：live 取数自动落盘，回放只读快照。

目录：data/std/<运行日>/<capability>-<args哈希>.json
  - live 模式（默认）：resolve 每次取数成功后把标准化结果写入当日快照；
  - replay 模式（replay_scope）：resolve 只读快照，缺失即抛 SnapshotMissing，
    绝不现场拉数——防止回放混入未来数据。

快照 key = capability + 参数规范化哈希，同参重跑覆盖写（幂等）。
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger(__name__)

SNAPSHOT_SUBDIR = "std"


class SnapshotMissing(RuntimeError):
    """回放模式下快照缺失（含缺失的 capability/args 与所在目录）。"""

    def __init__(self, capability: str, args: dict, dir_path: Path):
        self.capability = capability
        self.args = args
        self.dir_path = dir_path
        super().__init__(
            f"快照缺失: {capability} args={args}（目录 {dir_path}）。"
            f"该数据当日未落过快照，无法回放；可先用 live 模式补采。"
        )


# 回放模式目录（None = live）
_REPLAY_DIR: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar(
    "replay_snapshot_dir", default=None
)

# live 模式强制落盘目录日期（None = 落运行当日）。回填（backfill）用：
# 历史日期取数时把快照写到 data/std/<历史日期>/，而不是今天的目录。
_SAVE_DATE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "snapshot_save_date", default=None
)


def current_dir() -> Optional[Path]:
    return _REPLAY_DIR.get()


@contextmanager
def save_date_scope(date: str):
    """live 取数时把快照强制落盘到 data/std/<date>/（回填历史快照用）。"""
    tok = _SAVE_DATE.set(date)
    try:
        yield
    finally:
        _SAVE_DATE.reset(tok)


@contextmanager
def replay_scope(settings: "Settings", date: str):
    """进入回放模式：期间 resolve 只读 data/std/<date>/。"""
    tok = _REPLAY_DIR.set(snapshot_dir(settings, date))
    try:
        yield
    finally:
        _REPLAY_DIR.reset(tok)


def snapshot_dir(settings: "Settings", date: str) -> Path:
    return settings.data_dir / SNAPSHOT_SUBDIR / date


def _key(capability: str, args: dict) -> str:
    canon = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    h = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]
    return f"{capability}-{h}"


def _jsonable(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def save(settings: "Settings", date: str, capability: str, args: dict, value: Any) -> Path:
    """live 模式落盘快照；失败只告警不阻断主流程。"""
    try:
        d = snapshot_dir(settings, date)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{_key(capability, args)}.json"
        from .timeutil import now_sh

        doc = {
            "capability": capability,
            "args": _jsonable(args),
            "saved_at": now_sh().isoformat(),
            "payload": _jsonable(value),
        }
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(p)
        return p
    except Exception as exc:  # noqa: BLE001 - 快照失败不阻断取数
        log.warning("快照落盘失败 %s%s: %s", capability, args, exc)
        return Path("")


def load(dir_path: Path, capability: str, args: dict, decode: Callable[[Any], Any]) -> Any:
    """回放模式读取快照；缺失抛 SnapshotMissing。"""
    p = dir_path / f"{_key(capability, args)}.json"
    if not p.exists():
        raise SnapshotMissing(capability, args, dir_path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    return decode(doc.get("payload"))


def io(settings: "Settings", capability: str, args: dict,
       live: Callable[[], Any], decode: Callable[[Any], Any],
       *, date: str | None = None) -> Any:
    """快照 IO 统一入口：replay 读快照；live 取数并落盘。

    date 为落盘目录用的运行日（缺省=今天）；args 参与快照 key。
    """
    snap = current_dir()
    if snap is not None:
        return load(snap, capability, args, decode)

    from .timeutil import sh_today

    value = live()
    save(settings, _SAVE_DATE.get() or date or sh_today(), capability, args, value)
    return value
