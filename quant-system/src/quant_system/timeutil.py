"""时间与交易日工具（全项目唯一实现，禁止再各处内联复制）。"""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

SH_TZ = ZoneInfo("Asia/Shanghai")


def now_sh() -> _dt.datetime:
    return _dt.datetime.now(SH_TZ)


def sh_today() -> str:
    """上海时区今天（YYYY-MM-DD）。"""
    return now_sh().strftime("%Y-%m-%d")


def date_ms(date: str) -> int:
    """YYYY-MM-DD → 当日 00:00 (Asia/Shanghai) 的 Unix 毫秒时间戳。

    hithink 系接口的 date_ms 参数统一用它（此前在 resolve/strategy_lianban
    各内联一份，2026-09-15 收敛）。
    """
    d = _dt.datetime.strptime(date, "%Y-%m-%d")
    return int(d.replace(tzinfo=SH_TZ).timestamp() * 1000)


def shift_calendar_days(date: str, days: int) -> str:
    """自然日偏移（不跳周末——交易日判断由调用方负责）。"""
    d = _dt.datetime.strptime(date, "%Y-%m-%d") + _dt.timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def prev_weekday(date: str) -> str:
    """上一个周一~周五（无日历时的兜底近似）。"""
    d = _dt.datetime.strptime(date, "%Y-%m-%d") - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d.strftime("%Y-%m-%d")
