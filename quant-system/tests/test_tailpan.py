"""尾盘选股（龙回头·尾盘）规则单元测试——无网络。

用户规则（2026-09-19 修订）：
- 通用前提：现价 < 今开；高开场景量能上限 1.5x
- 场景A 高开回踩（≥+3%）：9:30-9:33 最高=开盘价 + 截至9:33最低≤-2% + 9:33后振幅≤3%
- 场景B 低开收敛（≤-2%）：今日量 < 连板峰值×0.6 + 全天振幅≤3%
- 场景C 平开低走（-2%~+3%）：今日量<0.7x + 未冲高 + 9:33价格≤-2% + 9:33后振幅≤3%
"""
from __future__ import annotations

from quant_system.strategy.tailpan import evaluate_tailpan

PRE = 10.0  # 昨收
PARAMS = {
    "min_open_pct": 0.03,
    "morning_low_pct": -0.02,
    "low_open_pct": -0.02,
    "range_pct": 0.03,
    "volume_ratio_max": 1.5,
    "low_open_volume_ratio": 0.8,
    "flat_volume_ratio": 1.0,
}
WAVE_VOL = 1_000_000.0  # 连板日最大量（股）


def pts(*pairs: tuple[str, float]) -> list[dict]:
    return [{"time_label": t, "price": p, "volume": 0} for t, p in pairs]


def vpts(*triples: tuple[str, float, float]) -> list[dict]:
    return [{"time_label": t, "price": p, "volume": v} for t, p, v in triples]


def test_scene_a_pass():
    # 高开 +8%，开盘3分钟未冲高（9:31 即下跌），9:33 前杀到 -3%，9:33 后振幅 2% → 通过
    c = evaluate_tailpan("600001.SH", "示例", 3, 10.8, PRE,
                         pts(("09:31", 10.5), ("09:33", 9.7), ("10:00", 9.8),
                             ("14:44", 9.9)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert not c.rejected
    assert c.scene == "A"
    assert c.boards == 3
    assert abs(c.open_pct - 0.08) < 1e-9
    assert abs(c.morning_low_pct - (-0.03)) < 1e-9
    assert abs(c.range_pct - 0.02) < 1e-9
    assert c.last_price == 9.9
    assert any("开盘3分钟未冲高" in n for n in c.notes)


def test_scene_a_rushed_reject():
    # 高开 +8% 但 9:31 冲到 10.9 > 开盘 10.8 → 拒"9:33前冲高"
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                         pts(("09:31", 10.9), ("09:33", 9.7), ("14:44", 9.9)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "9:33前冲高" in c.reject_reason


def test_scene_a_range_reject():
    # 9:33 后从 9.7 拉到 10.3：区间振幅 6% > 3% → 拒
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                         pts(("09:31", 10.5), ("09:33", 9.7), ("09:40", 10.3),
                             ("14:44", 10.1)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "9:33后振幅过大" in c.reject_reason


def test_scene_a_deep_reject():
    # 9:33 前最低只到 -1%（9.9）；9:35 才杀到 -5% 不计入早盘窗 → 拒
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                         pts(("09:31", 10.2), ("09:32", 9.9), ("09:35", 9.5),
                             ("14:44", 10.1)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "未达深水" in c.reject_reason
    assert abs(c.morning_low_pct - (-0.01)) < 1e-9


def test_scene_b_pass():
    # 低开 -3%，量 0（缩量 ✓），全天 9.6~9.8 振幅 2% ≤3% → 通过
    c = evaluate_tailpan("600001.SH", "示例", 2, 9.7, PRE,
                         pts(("09:31", 9.65), ("10:00", 9.6), ("11:30", 9.8),
                             ("14:44", 9.65)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert not c.rejected
    assert c.scene == "B"
    assert abs(c.open_pct - (-0.03)) < 1e-9
    assert abs(c.range_pct - 0.02) < 1e-9


def test_scene_b_volume_reject():
    # 低开但今日量 0.9x ≥ 0.8x → 拒"低开量能偏大"
    c = evaluate_tailpan("600001.SH", "示例", 2, 9.7, PRE,
                         vpts(("09:31", 9.65, 4500), ("10:00", 9.6, 2250),
                              ("14:44", 9.65, 2250)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "低开量能偏大" in c.reject_reason
    assert abs(c.volume_ratio - 0.9) < 1e-9


def test_scene_b_range_reject():
    # 低开 -3%，全天 9.6~9.95 振幅 3.5% > 3% → 拒
    c = evaluate_tailpan("600001.SH", "示例", 2, 9.7, PRE,
                         pts(("09:31", 9.6), ("10:30", 9.95), ("14:44", 9.6)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "全天振幅过大" in c.reject_reason


def test_scene_c_pass():
    # 平开 +2%：开盘3分钟未冲高（单调下跌），9:33 价格 -3% ≤ -2%，
    # 9:33 后 9.7~9.9 振幅 2% ≤3%，量 0 < 0.7x → 通过
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.2, PRE,
                         pts(("09:31", 10.2), ("09:32", 10.0), ("09:33", 9.7),
                             ("10:30", 9.8), ("14:44", 9.9)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert not c.rejected
    assert c.scene == "C"
    assert abs(c.pct_933 - (-0.03)) < 1e-9
    assert abs(c.range_pct - 0.02) < 1e-9


def test_scene_c_volume_reject():
    # 平开但今日量 1.2x ≥ 1.0x → 拒"平开量能偏大"
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.2, PRE,
                         vpts(("09:31", 10.2, 6000), ("09:33", 9.7, 3000),
                              ("14:44", 9.8, 3000)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "平开量能偏大" in c.reject_reason


def test_scene_c_rushed_reject():
    # 平开但 9:32 冲到 10.4 > 开盘 10.2 → 拒
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.2, PRE,
                         pts(("09:31", 10.2), ("09:32", 10.4), ("09:33", 9.7),
                             ("14:44", 9.8)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "9:33前冲高" in c.reject_reason


def test_scene_c_933_not_deep_reject():
    # 平开未冲高但 9:33 价格 -1% > -2% → 拒"9:33未至深水"
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.2, PRE,
                         pts(("09:31", 10.2), ("09:32", 10.0), ("09:33", 9.9),
                             ("14:44", 9.8)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "9:33未至深水" in c.reject_reason


def test_scene_c_range_reject():
    # 平开 9:33 深水后拉到 10.6：9:33 后振幅 9% > 3% → 拒
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.2, PRE,
                         pts(("09:31", 10.2), ("09:33", 9.7), ("10:30", 10.6),
                             ("14:44", 9.8)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "9:33后振幅过大" in c.reject_reason


def test_volume_ratio_max_reject_scene_a():
    # 场景A 形态全过，但今日量 3.0x > 1.5x（共用上限）→ 拒
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                         vpts(("09:31", 10.5, 1000), ("09:33", 9.7, 1000),
                              ("10:00", 9.8, 1000), ("14:44", 9.9, 0)),
                         PARAMS, wave_max_volume=100_000.0)
    assert c.rejected and "今日量超连板峰值" in c.reject_reason
    assert abs(c.volume_ratio - 3.0) < 1e-9


def test_volume_missing_baseline_skipped():
    # 连板峰值量缺失（0）→ 跳过量能检查，场景A 仍通过
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                         pts(("09:31", 10.5), ("09:33", 9.7), ("14:44", 9.9)),
                         PARAMS, wave_max_volume=0.0)
    assert not c.rejected
    assert c.volume_ratio is None
    assert any("量能基准缺失" in n for n in c.notes)


def test_reject_price_above_open():
    # 现价 ≥ 今开（未走阴）→ 拒绝（优先于场景判定）
    c = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                         pts(("09:31", 10.4), ("09:33", 9.7), ("14:44", 10.9)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert c.rejected and "未走阴" in c.reject_reason


def test_reject_missing_data():
    c = evaluate_tailpan("600001.SH", "示例", 2, 0.0, PRE, [], PARAMS)
    assert c.rejected and "数据缺失" in c.reject_reason
    c2 = evaluate_tailpan("600001.SH", "示例", 2, 10.8, PRE,
                          pts(("10:30", 10.5)), PARAMS)
    assert c2.rejected and "09:33前无分时" in c2.reject_reason


def test_boundary_equal_values():
    # 边界值不拒（>= / <= 语义）。昨收取 100 整数价避免浮点误差。
    # 场景A 边界：高开恰 +3%、未冲高（9:31 即低于开盘）、9:33 低点恰 -2%、振幅在限内
    c = evaluate_tailpan("600001.SH", "示例", 2, 103.0, 100.0,
                         pts(("09:31", 100.5), ("09:33", 98.0), ("09:34", 98.5),
                             ("14:44", 100.0)),
                         PARAMS, wave_max_volume=WAVE_VOL)
    assert not c.rejected
    assert c.scene == "A"
    assert abs(c.morning_low_pct - (-0.02)) < 1e-9

    # 场景B 边界：低开恰 -2%、全天振幅恰 3%、量比恰低于 0.6
    c2 = evaluate_tailpan("600001.SH", "示例", 2, 98.0, 100.0,
                          pts(("09:31", 97.0), ("11:30", 100.0), ("14:44", 97.5)),
                          PARAMS, wave_max_volume=WAVE_VOL)
    assert not c2.rejected and c2.scene == "B"
    assert abs(c2.range_pct - 0.03) < 1e-9

    # 场景C 边界：9:33 价格恰 -2%（99.0 未冲高：≤开盘 102 ✓）
    c3 = evaluate_tailpan("600001.SH", "示例", 2, 102.0, 100.0,
                          pts(("09:31", 102.0), ("09:32", 100.0), ("09:33", 98.0),
                              ("14:44", 99.0)),
                          PARAMS, wave_max_volume=WAVE_VOL)
    assert not c3.rejected and c3.scene == "C"
    assert abs(c3.pct_933 - (-0.02)) < 1e-9
