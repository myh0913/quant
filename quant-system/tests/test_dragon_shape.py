"""龙回头建池·首阴日形态/量能过滤单元测试（_pullback_shape_reject，mock 分时）。

用户规则（2026-09-19，三分支）：
- 高开 ≥ +3%：9:30-9:33 最高=开盘价（未冲高）+ 9:33 前最低 ≤ -2% + 9:33→收盘振幅 ≤ 3%
- 低开 ≤ -2%：首阴量 < 连板峰值×0.6 + 全天振幅 ≤ 3%
- 平开（-2%~+3%）：首阴量 < 0.7x + 未冲高 + 9:33 时点价格 ≤ -2% + 9:33后振幅 ≤ 3%
"""
from __future__ import annotations

import pytest

from quant_system.analyzer import DayInfo
from quant_system.strategy import dragon
from quant_system.strategy.dragon import _pullback_shape_reject

PARAMS = {
    "shape_high_open_pct": 0.03,
    "shape_morning_low_pct": -0.02,
    "shape_low_open_pct": -0.02,
    "shape_range_pct": 0.03,
    "shape_low_volume_ratio": 0.8,
    "shape_flat_volume_ratio": 1.0,
}
WAVE_VOL = 100_000.0  # 连板日最大量（股）


def day(open_: float, pre_close: float = 100.0, volume: float = 50_000.0) -> DayInfo:
    return DayInfo(idx=0, date="2026-09-17", open=open_, high=open_ * 1.01,
                   low=open_ * 0.98, close=open_ * 0.99, pre_close=pre_close,
                   volume=volume, pct=0.0, is_limit_up=False, is_one_word=False)


def pts(*pairs: tuple[str, float]) -> list[dict]:
    return [{"time_label": t, "price": p, "volume": 0} for t, p in pairs]


@pytest.fixture()
def fake_minutes(monkeypatch):
    """按日期返回预置分时；记录调用。"""
    holder: dict = {"calls": []}

    def _fake(settings, thscode, date):
        holder["calls"].append((thscode, date))
        return holder.get("points", [])

    monkeypatch.setattr(dragon, "standard_minute_points", _fake)
    return holder


def test_high_open_pass(fake_minutes):
    # 高开 +8%：未冲高（9:31 即下跌），9:33 前最低 97（-3%），9:33 后振幅 2% → 通过
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:33", 97.0),
                                 ("10:00", 98.0), ("15:00", 99.0))
    assert _pullback_shape_reject(None, "600001.SH", day(108.0), PARAMS, WAVE_VOL) == ""


def test_high_open_rushed_reject(fake_minutes):
    # 高开但 9:31 冲到 109 > 开盘 108 → 拒
    fake_minutes["points"] = pts(("09:31", 109.0), ("09:33", 97.0), ("15:00", 99.0))
    r = _pullback_shape_reject(None, "600001.SH", day(108.0), PARAMS, WAVE_VOL)
    assert "9:33前冲高" in r


def test_high_open_no_deep_reject(fake_minutes):
    # 高开 +8% 但 9:33 前最低只到 99（-1%）→ 拒
    fake_minutes["points"] = pts(("09:31", 101.0), ("09:33", 99.0),
                                 ("09:35", 95.0), ("15:00", 99.0))
    r = _pullback_shape_reject(None, "600001.SH", day(108.0), PARAMS, WAVE_VOL)
    assert "9:33前未深水" in r


def test_high_open_range_reject(fake_minutes):
    # 高开 +8%、深水过，但 9:33 后 97→104 振幅 7% → 拒
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:33", 97.0),
                                 ("10:30", 104.0), ("15:00", 100.0))
    r = _pullback_shape_reject(None, "600001.SH", day(108.0), PARAMS, WAVE_VOL)
    assert "9:33后振幅过大" in r


def test_low_open_pass(fake_minutes):
    # 低开 -3%：首阴量 0.5x < 0.8x（缩量 ✓），全天 96.5~98 振幅 1.5% → 通过
    fake_minutes["points"] = pts(("09:31", 97.0), ("10:00", 96.5),
                                 ("13:00", 98.0), ("15:00", 97.0))
    assert _pullback_shape_reject(None, "600001.SH", day(97.0), PARAMS, WAVE_VOL) == ""


def test_low_open_volume_reject(fake_minutes):
    # 低开但首阴量 0.9x ≥ 0.8x → 拒
    fake_minutes["points"] = pts(("09:31", 97.0), ("15:00", 97.0))
    r = _pullback_shape_reject(
        None, "600001.SH", day(97.0, volume=90_000.0), PARAMS, WAVE_VOL)
    assert "低开量能偏大" in r


def test_low_open_range_reject(fake_minutes):
    # 低开 -3% 但全天 95~100 振幅 5% → 拒
    fake_minutes["points"] = pts(("09:31", 96.0), ("11:00", 100.0),
                                 ("15:00", 96.5))
    r = _pullback_shape_reject(None, "600001.SH", day(97.0), PARAMS, WAVE_VOL)
    assert "全天振幅过大" in r


def test_flat_open_pass(fake_minutes):
    # 平开 +2%：量 0.5x < 1.0x ✓，未冲高 ✓，9:33 价格 97（-3%）≤ -2% ✓，
    # 9:33 后 97~99 振幅 2% ≤3% ✓ → 通过
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:32", 100.0),
                                 ("09:33", 97.0), ("10:30", 98.0), ("15:00", 99.0))
    assert _pullback_shape_reject(None, "600001.SH", day(102.0), PARAMS, WAVE_VOL) == ""


def test_flat_open_volume_reject(fake_minutes):
    # 平开但首阴量 1.2x ≥ 1.0x → 拒
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:33", 97.0), ("15:00", 99.0))
    r = _pullback_shape_reject(
        None, "600001.SH", day(102.0, volume=120_000.0), PARAMS, WAVE_VOL)
    assert "平开量能偏大" in r


def test_flat_open_rushed_reject(fake_minutes):
    # 平开但 9:32 冲到 104 > 开盘 102 → 拒
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:32", 104.0),
                                 ("09:33", 97.0), ("15:00", 99.0))
    r = _pullback_shape_reject(None, "600001.SH", day(102.0), PARAMS, WAVE_VOL)
    assert "9:33前冲高" in r


def test_flat_open_933_not_deep_reject(fake_minutes):
    # 平开未冲高但 9:33 价格 -1% > -2% → 拒
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:32", 100.0),
                                 ("09:33", 99.0), ("15:00", 98.0))
    r = _pullback_shape_reject(None, "600001.SH", day(102.0), PARAMS, WAVE_VOL)
    assert "9:33未至深水" in r


def test_flat_open_range_reject(fake_minutes):
    # 平开 9:33 深水后拉到 106：振幅 9% > 3% → 拒
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:33", 97.0),
                                 ("10:30", 106.0), ("15:00", 98.0))
    r = _pullback_shape_reject(None, "600001.SH", day(102.0), PARAMS, WAVE_VOL)
    assert "9:33后振幅过大" in r


def test_missing_minutes_reject(fake_minutes):
    # 高开但分时缺失 → 拒（宁可拒绝不可错报）
    fake_minutes["points"] = []
    r = _pullback_shape_reject(None, "600001.SH", day(108.0), PARAMS, WAVE_VOL)
    assert "分时缺失" in r


def test_missing_pre_close_reject(fake_minutes):
    # 昨收缺失 → 拒
    d = day(108.0)
    d.pre_close = 0.0
    r = _pullback_shape_reject(None, "600001.SH", d, PARAMS, WAVE_VOL)
    assert "昨收缺失" in r
    assert fake_minutes["calls"] == []


def test_boundary_equal_values(fake_minutes):
    # 边界：高开恰 +3%、未冲高、9:33 低点恰 -2%、9:33 后振幅恰在限内 → 不拒
    fake_minutes["points"] = pts(("09:31", 101.0), ("09:33", 98.0),
                                 ("09:34", 98.5), ("15:00", 101.0))
    assert _pullback_shape_reject(None, "600001.SH", day(103.0), PARAMS, WAVE_VOL) == ""

    # 边界：低开恰 -2%、全天振幅恰 3%、量恰低于 0.6 → 不拒
    fake_minutes["points"] = pts(("09:31", 97.0), ("11:30", 100.0),
                                 ("15:00", 97.5))
    d = day(98.0, volume=59_000.0)
    assert _pullback_shape_reject(None, "600001.SH", d, PARAMS, WAVE_VOL) == ""

    # 边界：平开、9:33 价格恰 -2% → 不拒
    fake_minutes["points"] = pts(("09:31", 102.0), ("09:32", 100.0),
                                 ("09:33", 98.0), ("15:00", 99.0))
    assert _pullback_shape_reject(None, "600001.SH", day(102.0), PARAMS, WAVE_VOL) == ""
