"""数据源统一接口与通用工具：重试、原始响应落盘、错误语义。"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests


class DataSourceError(RuntimeError):
    """数据源错误基类。message 必须能解释失败阶段和下一步。"""

    def __init__(self, stage: str, message: str, *, retriable: bool = False):
        self.stage = stage
        self.retriable = retriable
        super().__init__(f"[{stage}] {message}")


class AuthError(DataSourceError):
    def __init__(self, message: str):
        super().__init__("auth", message, retriable=False)


class RateLimitError(DataSourceError):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        self.retry_after = retry_after
        super().__init__("rate_limit", message, retriable=True)


def save_raw(payload: Any, raw_dir: Path, source: str, name: str, date: str | None = None) -> Path:
    """把原始响应保存到 data/raw/<source>/<date>/<ts>-<name>.json。

    返回保存路径；失败时打印告警但不中断主流程。
    """
    try:
        d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder = raw_dir / source / d
        folder.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3]
        path = folder / f"{ts}-{name}.json"
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload, ensure_ascii=False, default=str)
        path.write_text(body, encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001 - 落盘失败不应中断取数
        print(f"[warn] save_raw failed for {source}/{name}: {exc}")
        return Path("")


def payload_hash(payload: Any) -> str:
    body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def request_with_retry(
    method: str,
    url: str,
    *,
    raw_dir: Path,
    source: str,
    name: str,
    params: dict | None = None,
    headers: dict | None = None,
    json_body: Any = None,
    timeout: int = 30,
    retries: int = 2,
    backoff: float = 1.0,
    ok_codes: tuple[int, ...] = (200,),
) -> tuple[requests.Response, dict[str, Any]]:
    """GET/POST 请求，带重试与原始响应保存。

    返回 (response, meta)；meta 含 elapsed_ms、attempts、raw_path、sha256。
    业务级错误码由调用方根据各源契约判断（如 code != 20000）。
    """
    attempts = 0
    last_exc: Optional[Exception] = None
    t0 = time.perf_counter()
    while attempts <= retries:
        attempts += 1
        try:
            resp = requests.request(
                method, url, params=params, headers=headers, json=json_body, timeout=timeout
            )
            if resp.status_code in ok_codes:
                try:
                    body: Any = resp.json()
                except ValueError:
                    body = resp.text
                path = save_raw(body, raw_dir, source, name)
                meta = {
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "attempts": attempts,
                    "raw_path": str(path),
                    "sha256": payload_hash(body),
                    "http": resp.status_code,
                }
                return resp, meta
            last_exc = DataSourceError(
                "http",
                f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:120]}",
                retriable=resp.status_code >= 500 or resp.status_code == 429,
            )
        except requests.Timeout as exc:
            last_exc = DataSourceError("http", f"{method} {url} timeout after {timeout}s", retriable=True)
        except requests.RequestException as exc:
            last_exc = DataSourceError("http", f"{method} {url} -> {exc}", retriable=True)
        if attempts <= retries:
            time.sleep(backoff * attempts)
    raise last_exc or DataSourceError("http", f"{method} {url} failed")


class BaseDataSource:
    """数据源基类。子类实现业务方法，复用 save_raw/request_with_retry。"""

    source_name = "base"

    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir
