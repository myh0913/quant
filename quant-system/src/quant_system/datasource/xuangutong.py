"""选股通适配器（xuangutong.com.cn）。

免登录接口（已实测）：
- flash-api：市场情绪（market_indicator/line）、涨停池（支持历史日期）、
  题材排名/核心表现/题材个股
- baoer-api：新闻快讯（需要 x-ivanka-token，从 .env 的 XUANGUTONG_IVANKA_TOKEN 读取）

历史说明：早期曾用首页 SSR HTML 正则解析情绪指标，2026-09-08 选股通
调整首页结构后 limit_down / limit_up_broken_count 等字段在 HTML 中已
不存在，全部解析为 0；market_sentiment() 已改调 flash-api 同源接口。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Settings
from ..models import ThemeRank
from .base import AuthError, BaseDataSource, DataSourceError, request_with_retry

FLASH = "https://flash-api.xuangubao.com.cn"
BAOER = "https://baoer-api.xuangubao.com.cn"
HOME = "https://xuangutong.com.cn"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class XuangutongSource(BaseDataSource):
    source_name = "xuangutong"

    def __init__(self, settings: Settings):
        super().__init__(settings.raw_dir)
        self._settings = settings
        self._ivanka_token_value: Optional[str] = None

    # ---------- 首页情绪指标 ----------
    # 2026-09-09 修复：选股通首页 HTML 已不返回 limit_down_count /
    # limit_up_broken_count 等字段，正则解析全部得 null。改调 flash-api
    # market_indicator/line 拿当日最新点，与 quant-web /api/sentiment 同源。
    # 字段名保持原样（market_temperature / limit_* 等），cycle.py 等调用方零改动。
    SENTIMENT_FIELDS = (
        "market_temperature,limit_up_count,limit_down_count,"
        "limit_up_broken_count,limit_up_broken_ratio,ziranzhangting_count,"
        "rise_count,fall_count,stay_count,yesterday_limit_up_avg_pcp,lianbangaodu"
    )

    def market_sentiment(self) -> dict:
        """市场情绪指标（今天最新点）。字段与 market_sentiment_by_date 一致。"""
        today = datetime.now().strftime("%Y-%m-%d")
        out = self.market_sentiment_by_date(today)
        if out:
            return out
        # 盘前/非交易日无分钟点 → 返回带采集标记的空字典，调用方按缺字段处理
        return {
            "_collected_at": datetime.now(timezone.utc).isoformat(),
        }

    def market_sentiment_by_date(self, date: str) -> dict:
        """市场情绪指标：flash-api /api/market_indicator/line 指定日期最后一个点。

        无点（盘前/非交易日/历史未覆盖）返回 {}。支持历史日期回算。
        """
        resp, meta = request_with_retry(
            "GET", FLASH + "/api/market_indicator/line",
            raw_dir=self.raw_dir, source=self.source_name, name=f"sentiment_{date}",
            params={"fields": self.SENTIMENT_FIELDS, "date": date},
            headers={"User-Agent": UA, "Referer": HOME + "/"}, timeout=20,
        )
        body = resp.json()
        if body.get("code") not in (20000, 0):
            raise DataSourceError(
                "api",
                f"market_sentiment_by_date({date}) code={body.get('code')} {body.get('message')}",
            )
        points = body.get("data") or []
        if not points:
            return {}
        p = points[-1]
        out: dict[str, Any] = {
            k: p.get(k)
            for k in (
                "market_temperature", "limit_up_count", "limit_down_count",
                "limit_up_broken_count", "limit_up_broken_ratio",
                "yesterday_limit_up_avg_pcp", "ziranzhangting_count",
                "rise_count", "fall_count", "stay_count", "lianbangaodu",
            )
        }
        out["_collected_at"] = datetime.now(timezone.utc).isoformat()
        out["_raw_path"] = meta["raw_path"]
        return out

    # ---------- 涨停池（支持历史日期） ----------
    def limit_up_pool(self, date: str | None = None) -> list[dict]:
        """涨停池。date=YYYY-MM-DD 支持历史交易日；返回原始条目 dict 列表。"""
        params: dict[str, Any] = {"pool_name": "limit_up"}
        if date:
            params["date"] = date
        resp, meta = request_with_retry(
            "GET", FLASH + "/api/pool/detail", raw_dir=self.raw_dir,
            source=self.source_name, name=f"limit_up_{date or 'today'}",
            params=params, headers={"User-Agent": UA, "Referer": HOME + "/"},
            timeout=20,
        )
        body = resp.json()
        if body.get("code") not in (20000, 0):
            raise DataSourceError("api", f"limit_up_pool code={body.get('code')} {body.get('message')}")
        items = body.get("data") or []
        if not isinstance(items, list):
            return []
        return items

    # ---------- 题材排名 ----------
    def theme_rank(self) -> list[ThemeRank]:
        """当日题材排名（surge_stock/plates）。数组顺序=排名；无历史日期参数。"""
        resp, meta = request_with_retry(
            "GET", FLASH + "/api/surge_stock/plates", raw_dir=self.raw_dir,
            source=self.source_name, name="themes", headers={"User-Agent": UA}, timeout=20,
        )
        body = resp.json()
        if body.get("code") != 20000:
            raise DataSourceError("api", f"theme_rank code={body.get('code')} {body.get('message')}")
        data = body.get("data") or {}
        items = data.get("items") or []
        now = datetime.now(timezone.utc)
        out: list[ThemeRank] = []
        for i, it in enumerate(items):
            out.append(
                ThemeRank(
                    plate_id=int(it.get("id", 0)),
                    name=it.get("name", ""),
                    description=it.get("description"),
                    rank=i + 1,
                    core_avg_pcp=None,
                    ts=now,
                )
            )
        return out

    # ---------- 题材核心表现 ----------
    def theme_core_avg(self, plate_ids: list[int]) -> dict[int, float]:
        """题材核心股平均涨跌幅（plate/data）。返回 {plate_id: core_avg_pcp(小数)}。"""
        if not plate_ids:
            return {}
        resp, meta = request_with_retry(
            "GET", FLASH + "/api/plate/data", raw_dir=self.raw_dir,
            source=self.source_name, name="plate_data",
            params={"fields": "core_avg_pcp,plate_name", "plates": ",".join(str(i) for i in plate_ids)},
            headers={"User-Agent": UA}, timeout=20,
        )
        body = resp.json()
        if body.get("code") != 20000:
            raise DataSourceError("api", f"theme_core_avg code={body.get('code')} {body.get('message')}")
        data = body.get("data") or {}
        out: dict[int, float] = {}
        for pid, rec in data.items():
            try:
                out[int(pid)] = float(rec.get("core_avg_pcp") or 0.0)
            except (TypeError, ValueError):
                continue
        return out

    # ---------- 题材内个股 ----------
    def theme_stocks(self, normal: bool = True, uplimit: bool = True) -> list[dict]:
        """题材内个股（surge_stock/stocks）。返回按 fields 解码后的 dict 列表。"""
        resp, meta = request_with_retry(
            "GET", FLASH + "/api/surge_stock/stocks", raw_dir=self.raw_dir,
            source=self.source_name, name="theme_stocks",
            params={"normal": str(normal).lower(), "uplimit": str(uplimit).lower()},
            headers={"User-Agent": UA, "Referer": HOME + "/top-gainer"}, timeout=20,
        )
        body = resp.json()
        if body.get("code") != 20000:
            raise DataSourceError("api", f"theme_stocks code={body.get('code')} {body.get('message')}")
        data = body.get("data") or {}
        fields = data.get("fields") or []
        rows = data.get("items")
        if not isinstance(rows, list) or rows is None:
            return []
        out: list[dict] = []
        for row in rows:
            if isinstance(row, list) and len(row) == len(fields):
                out.append(dict(zip(fields, row)))
            else:
                out.append({"__raw__": row})
        return out

    # ---------- 新闻快讯（需 token） ----------
    def _ivanka_token(self) -> str:
        if self._ivanka_token_value is None:
            self._ivanka_token_value = self._settings.require_xuangutong_token()
        return self._ivanka_token_value

    def newsflash(self, limit: int = 20, subj_ids: int = 10, has_explain: bool = False) -> list[dict]:
        """新闻快讯。需 x-ivanka-token；返回 messages 列表（字段见 skill §12）。"""
        resp, meta = request_with_retry(
            "GET", BAOER + "/api/v6/message/newsflash", raw_dir=self.raw_dir,
            source=self.source_name, name="newsflash",
            params={"limit": limit, "subj_ids": subj_ids, "has_explain": str(has_explain).lower(), "platform": "pcweb"},
            headers={"x-ivanka-token": self._ivanka_token(), "User-Agent": UA, "Referer": HOME + "/"},
            timeout=20,
        )
        body = resp.json()
        code = body.get("code")
        if code == 50008:
            raise AuthError("newsflash token 无效（code=50008）")
        if code != 20000:
            raise DataSourceError("api", f"newsflash code={code} {body.get('message')}")
        data = body.get("data") or {}
        return list(data.get("messages", []) or [])
