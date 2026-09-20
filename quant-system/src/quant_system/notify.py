"""可选推送通道（全部不依赖 OpenClaw）。

主通道：quant-web 监听 data/advice/ 自动 WS 推送（零侵入，无需本模块）。
备用：ntfy.sh 手机推送 —— .env 设置 NTFY_TOPIC=<自定义主题> 后自动启用，
      手机装 ntfy App 订阅同名主题即可收到通知。
"""
from __future__ import annotations

import os

import requests


def notify(text: str, title: str = "quant-system") -> bool:
    """推送一条通知。未配置 NTFY_TOPIC 时静默跳过（返回 False）。"""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=text.encode("utf-8"),
            headers={"Title": title, "Tags": "chart_with_upwards_trend"},
            timeout=5,
        )
        return True
    except Exception:  # noqa: BLE001 — 推送失败不阻断主流程
        return False
