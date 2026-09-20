"""日线分析器：从日线序列计算涨停、连板波、一字板、量能。

纯逻辑，无网络；输入为 hithink daily_bars 原始格式（date_ms/OHLC/volume）。
主板涨停近似判定：涨幅 ≥ 9.8%（容差覆盖四舍五入）；ST 股已在股票池层排除。

除权/数据异常（2026-09-17）：上游日 K 无 pre_close 字段，涨跌幅只能用前根
收盘递推；主板涨跌停 ±10%，|递推涨幅| > 10.5% 只可能是除权除息/送转/数据
错误 → 标记 suspect，候选层整票拒收（宁可拒绝，不可错报）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

LIMIT_UP_PCT = 0.098  # 主板近似涨停阈值
ONE_WORD_TOL = 0.999  # 一字板：四价均 ≥ 涨停价×0.999
SUSPECT_PCT = 0.105   # 主板单日涨跌幅超此值 → 疑似除权/数据异常

# 早盘窗截止（用户 2026-09-19 定义"截至 9:33 的当日最低点"）。
# 分时 time_label 为补零 "HH:MM"（实测 eltdx），字符串比较安全；
# "截至 9:33" 含 9:33 根，"9:33 之后" 区间取 >= 9:33（含当根，语义：此后不再创异常波动）。
MORNING_CUTOFF = "09:33"


@dataclass
class DayInfo:
    idx: int
    date: str
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    volume: float
    pct: float  # close/pre_close - 1，小数
    is_limit_up: bool
    is_one_word: bool  # 一字板：全天未开板（四价≈涨停价）
    suspect: bool = False  # 疑似除权/数据异常（递推涨幅越界）

    @property
    def limit_price(self) -> float:
        return round(self.pre_close * 1.1, 2) if self.pre_close else 0.0


@dataclass
class Wave:
    """连续涨停波。"""

    start_idx: int
    end_idx: int  # 含
    days: int  # 连板天数

    @property
    def first_day(self) -> int:
        return self.start_idx


class DailyBarAnalyzer:
    def __init__(self, bars: list[dict]):
        """bars: hithink daily_bars 原始列表（时间升序），字段 date_ms/open_price/.../volume。"""
        self.days: list[DayInfo] = []
        pre = 0.0
        for i, b in enumerate(bars):
            close = float(b.get("close_price") or 0)
            o = float(b.get("open_price") or 0)
            h = float(b.get("high_price") or 0)
            l = float(b.get("low_price") or 0)
            v = float(b.get("volume") or 0)
            pct = (close - pre) / pre if pre else 0.0
            is_lu = pct >= LIMIT_UP_PCT and pre > 0
            limit_px = round(pre * 1.1, 2)
            one_word = is_lu and o >= limit_px * ONE_WORD_TOL and l >= limit_px * ONE_WORD_TOL
            suspect = pre > 0 and abs(pct) > SUSPECT_PCT
            # date_ms 毫秒 → YYYY-MM-DD
            import datetime as _dt

            d = _dt.datetime.fromtimestamp(
                int(b.get("date_ms", 0)) / 1000, tz=_dt.timezone(_dt.timedelta(hours=8))
            ).strftime("%Y-%m-%d")
            self.days.append(
                DayInfo(i, d, o, h, l, close, pre, v, pct, is_lu, one_word, suspect)
            )
            pre = close

    def has_suspect_day(self) -> bool:
        """序列中存在疑似除权/数据异常日 → 候选层整票拒收。"""
        return any(d.suspect for d in self.days)

    # ---------- 连板波 ----------
    def limit_up_waves(self) -> list[Wave]:
        """所有连续涨停波（≥2 天才算连板波）。"""
        waves: list[Wave] = []
        i = 0
        while i < len(self.days):
            if self.days[i].is_limit_up:
                j = i
                while j + 1 < len(self.days) and self.days[j + 1].is_limit_up:
                    j += 1
                if j - i + 1 >= 2:
                    waves.append(Wave(i, j, j - i + 1))
                i = j + 1
            else:
                i += 1
        return waves

    def current_wave(self) -> Wave | None:
        """最后一根 K 线所在的连板波（若最后一天涨停且属于≥2连板波）。"""
        if not self.days or not self.days[-1].is_limit_up:
            return None
        for w in self.limit_up_waves():
            if w.end_idx == len(self.days) - 1:
                return w
        return None

    # ---------- 用户规则 ----------
    def is_first_wave(self, lookback: int = 20) -> bool:
        """当前波之前 lookback 个交易日内无其他连板波（只做第一波）。"""
        cur = self.current_wave()
        if cur is None:
            return False
        for w in self.limit_up_waves():
            if w.end_idx == cur.end_idx:
                continue
            if cur.start_idx - w.end_idx <= lookback:
                return False
        return True

    def is_sanbanzu(self) -> bool:
        """三板组：当前波 3 板，首板量≤前日量×1.2，后两板一字且量≤首板量×0.1。"""
        cur = self.current_wave()
        if cur is None or cur.days != 3:
            return False
        d1, d2, d3 = self.days[cur.start_idx], self.days[cur.start_idx + 1], self.days[cur.start_idx + 2]
        pre_vol = self.days[cur.start_idx - 1].volume if cur.start_idx > 0 else float("inf")
        cond1 = d1.volume <= pre_vol * 1.2
        cond2 = d2.is_one_word and d3.is_one_word
        cond3 = d2.volume <= d1.volume * 0.1 and d3.volume <= d1.volume * 0.1
        return cond1 and cond2 and cond3

    def volume_ratio(self) -> float | None:
        """当前波首日量 / 波启动前一日量（用户：跟启动前比至少 1.5 倍量）。"""
        cur = self.current_wave()
        if cur is None or cur.start_idx == 0:
            return None
        pre_vol = self.days[cur.start_idx - 1].volume
        if not pre_vol:
            return None
        return self.days[cur.start_idx].volume / pre_vol

    def wave_volume_sustained(self) -> bool:
        """连板期间所有涨停板成交量 ≥ 波启动前一日成交量（用户：量能不萎缩）。

        波启动前一日即首板前一交易日；波始于序列首日或前一日无量时无法判定，返回 False。
        """
        cur = self.current_wave()
        if cur is None or cur.start_idx == 0:
            return False
        base = self.days[cur.start_idx - 1].volume
        if not base:
            return False
        return all(self.days[k].volume >= base for k in range(cur.start_idx, cur.end_idx + 1))

    def pre_wave_open_vs_low(self, lookback: int = 30) -> float | None:
        """首板前一交易日开盘价 / 最近 lookback 个交易日最低价（用户：<1.15 才参与，低位启动）。

        最低点取最低价（low），窗口为序列末尾 lookback 根 K 线（含最新一根）。
        """
        cur = self.current_wave()
        if cur is None or cur.start_idx == 0:
            return None
        pre_open = self.days[cur.start_idx - 1].open
        min_low = min((d.low for d in self.days[-lookback:] if d.low), default=0.0)
        if not pre_open or not min_low:
            return None
        return pre_open / min_low

    # ---------- 龙回头扩展 ----------

    def last_wave(self) -> Wave | None:
        """最后一波 ≥2 连板，且紧邻最后一根 K 线。

        用户规则：最后一根 K 线之前是连续涨停状态（≥2 连板的任意板数），
        即波末必须直接衔接最新 K 线（首阴），中间不允许有间隔交易日。
        """
        waves = self.limit_up_waves()
        if not waves:
            return None
        w = waves[-1]
        if w.end_idx != len(self.days) - 2:
            return None
        return w

    def pullback_day(self) -> DayInfo | None:
        """龙回头：连板波结束后的第一根阴线（收盘<开盘），且必须是最后一根 K 线。

        返回该阴线 DayInfo；若最后 K 线非首阴（仍涨停/阳线/已隔多日）则返回 None。
        用户定义：首次调整 = 连续涨停板后第一次出现阴线（收盘价<开盘价）。
        """
        w = self.last_wave()
        if w is None:
            return None
        for k in range(w.end_idx + 1, len(self.days)):
            d = self.days[k]
            if d.close < d.open:  # 阴线
                return d if k == len(self.days) - 1 else None
        return None

    def pullback_volume_ratio(self) -> float | None:
        """首阴量 / 首阴前一日量（用户：超过 2.5 倍可能连跌，不做）。

        口径与 pullback_day 一致：第一根阴线必须是最后一根 K 线（首阴当日），
        否则返回 None（2026-09-17 统一，防中间阴线误算）。
        """
        w = self.last_wave()
        if w is None:
            return None
        for k in range(w.end_idx + 1, len(self.days)):
            d = self.days[k]
            if d.close < d.open:
                if k != len(self.days) - 1:
                    return None  # 首阴不在最后一根 → 非本策略对象
                pre = self.days[k - 1] if k > 0 else None
                if pre is None or not pre.volume:
                    return None
                return d.volume / pre.volume
        return None

    def pullback_shape(self) -> str:
        """首阴形态：大阴线 / 长上引线 / 普通阴线。"""
        w = self.last_wave()
        if w is None:
            return ""
        for k in range(w.end_idx + 1, len(self.days)):
            d = self.days[k]
            if d.close < d.open:
                body = (d.open - d.close) / d.open if d.open else 0
                upper = (d.high - max(d.open, d.close)) / d.open if d.open else 0
                if body >= 0.05:
                    return "大阴线"
                if upper >= 0.03:
                    return "长上引线"
                return "普通阴线"
        return ""
