"""配置加载：只从项目 .env 读取，不把密钥写进代码/日志/仓库。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根 = 本文件上两级（src/quant_system/config.py -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


class ConfigError(RuntimeError):
    pass


def load_env(env_path: Path | None = None) -> None:
    """加载 .env；不存在时不报错（允许只读本地数据场景）。"""
    path = env_path or DEFAULT_ENV_PATH
    if path.exists():
        load_dotenv(path, override=False)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"环境变量 {name} 未配置，请在 {DEFAULT_ENV_PATH} 中填写")
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


class Settings:
    """项目配置。迁移时只需保证 .env 就位。"""

    def __init__(self, env_path: Path | None = None) -> None:
        load_env(env_path)

        # 数据源密钥（仅校验调用对应源时必需，这里不强制全部存在）
        self.hithink_api_key: str = _optional("HITHINK_FINANCE_API_KEY")
        self.xuangutong_ivanka_token: str = _optional("XUANGUTONG_IVANKA_TOKEN")

        # 输出
        self.telegram_chat_id: str = _optional("TELEGRAM_CHAT_ID", "7646550994")

        # 数据目录（默认项目根/data）。⚠️ QUANT_DATA_DIR 若配置了相对路径，
        # 必须锚定到项目根 —— 原样 Path("data") 会跟随进程 cwd 漂移，
        # 导致 cd 到不同目录启动时写出两套数据目录（2026-09-09 实测踩坑）。
        raw = _optional("QUANT_DATA_DIR", "").strip()
        if raw:
            p = Path(raw).expanduser()
            self.data_dir = p if p.is_absolute() else (PROJECT_ROOT / p).resolve()
        else:
            self.data_dir = PROJECT_ROOT / "data"
        self.raw_dir = self.data_dir / "raw"

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def require_hithink(self) -> str:
        return _required("HITHINK_FINANCE_API_KEY")

    def require_xuangutong_token(self) -> str:
        return _required("XUANGUTONG_IVANKA_TOKEN")
