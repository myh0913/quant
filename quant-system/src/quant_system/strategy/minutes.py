"""分钟分时取数会话（盘中确认阶段共用，M2 起内部走 resolve 能力层）。

调度器/沙箱通过 open_minute_fetcher 获得一个 (thscode, date) -> points 的
可调用对象，全程复用同一数据源连接；调用方不感知底层源。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..config import Settings

MinuteFetcher = Callable[[str, str], list[dict]]


def fetch_minute_points(settings: "Settings", thscode: str, date: str) -> list[dict]:
    """拉取分钟分时：[{time_label, price, volume}]。当日实盘 today，历史 history。"""
    from ..datasource.resolve import standard_minute_points

    return standard_minute_points(settings, thscode, date)


@contextmanager
def open_minute_fetcher(settings: "Settings"):
    """打开一个复用连接的分时取数会话：with open_minute_fetcher(s) as fetch: fetch(code, date)。"""
    from ..datasource.resolve import data_session, standard_minute_points

    with data_session(settings):
        yield lambda thscode, date: standard_minute_points(settings, thscode, date)
