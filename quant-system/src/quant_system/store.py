"""统一落盘：data/advice/<date>/<name>_<HHMMSS>.json。

quant-web 后端监听该目录（QUANT_ADVICE_DIR），新文件/变化 → WS 实时推送前端。
文件名时间戳用上海时间（人可读）；排序以 JSON 内 ran_at 为准。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel

SH_TZ = ZoneInfo("Asia/Shanghai")


def persist_report(settings, date: str, name: str, report: BaseModel | dict) -> Path:
    """落盘建议/报告 JSON；返回路径。report 为 Pydantic 模型或 dict。"""
    d = settings.data_dir / "advice" / date
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(SH_TZ).strftime("%H%M%S")
    p = d / f"{name}_{ts}.json"
    if isinstance(report, BaseModel):
        body = report.model_dump_json(indent=2)
    else:
        body = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    p.write_text(body, encoding="utf-8")
    return p
