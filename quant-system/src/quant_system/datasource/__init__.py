"""数据源适配器包。"""
from .base import (
    AuthError,
    BaseDataSource,
    DataSourceError,
    RateLimitError,
    request_with_retry,
    save_raw,
)
from .eltdx_source import EltdxSource
from .eastmoney import EastmoneySource
from .hithink import HithinkSource
from .xuangutong import XuangutongSource

__all__ = [
    "AuthError",
    "BaseDataSource",
    "DataSourceError",
    "RateLimitError",
    "request_with_retry",
    "save_raw",
    "EltdxSource",
    "HithinkSource",
    "XuangutongSource",
    "EastmoneySource",
]
