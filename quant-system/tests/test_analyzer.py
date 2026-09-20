"""analyzer 除权检测与量比口径单元测试——无网络（2026-09-17）。"""
from __future__ import annotations

from quant_system.analyzer import DailyBarAnalyzer


def bar(date_ms: int, o: float, h: float, l: float, c: float, v: float) -> dict:
    return {"date_ms": date_ms, "open_price": o, "high_price": h,
            "low_price": l, "close_price": c, "volume": v}


# 2026-09-01 ~ 09-15 交易日毫秒时间戳（顺序即可，具体日期无关）
_D = [1756684800000 + i * 86400000 for i in range(11)]


def test_no_suspect_on_normal_series():
    bars = [bar(_D[i], 10, 10.2, 9.9, 10 + i * 0.05, 1000) for i in range(11)]
    az = DailyBarAnalyzer(bars)
    assert not az.has_suspect_day()


def test_suspect_on_ex_dividend_jump():
    # 第 6 根从 10.5 跳到 7.0（-33%，主板不可能）→ 除权/数据异常
    bars = [bar(_D[i], 10, 10.2, 9.9, 10 + i * 0.1, 1000) for i in range(6)]
    bars.append(bar(_D[6], 7.2, 7.4, 6.9, 7.0, 2000))
    bars += [bar(_D[7 + i], 7.0, 7.2, 6.9, 7.1, 800) for i in range(4)]
    az = DailyBarAnalyzer(bars)
    assert az.has_suspect_day()


def test_pullback_volume_ratio_none_when_yin_not_last():
    # 3 连板后：阴线在中间、末根是阳线 → 非首阴当日，量比必须 None
    bars = [
        bar(_D[0], 10.0, 10.5, 10.0, 10.2, 500),   # 普通日
        bar(_D[1], 10.3, 11.22, 10.3, 11.22, 1000),  # 涨停 10%
        bar(_D[2], 11.3, 12.34, 11.3, 12.34, 1200),  # 涨停
        bar(_D[3], 12.0, 12.2, 11.5, 11.6, 1500),   # 阴线（但不是最后一根）
        bar(_D[4], 11.6, 12.0, 11.5, 11.8, 900),    # 阳线
    ]
    az = DailyBarAnalyzer(bars)
    assert az.pullback_day() is None
    assert az.pullback_volume_ratio() is None


def test_pullback_volume_ratio_when_yin_is_last():
    bars = [
        bar(_D[0], 10.0, 10.5, 10.0, 10.2, 500),
        bar(_D[1], 10.3, 11.22, 10.3, 11.22, 1000),
        bar(_D[2], 11.3, 12.34, 11.3, 12.34, 1200),
        bar(_D[3], 12.0, 12.2, 11.5, 11.6, 3000),   # 首阴=最后一根，量 3000/1200=2.5x
    ]
    az = DailyBarAnalyzer(bars)
    assert az.pullback_day() is not None
    assert abs(az.pullback_volume_ratio() - 2.5) < 1e-9
