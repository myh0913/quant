"""策略注册表单元测试——无网络。

M1 不变量：
- 三个策略已注册，id 与历史配置中心键一致（schema.json / 落盘文件名兼容）；
- 参数 schema 从策略类导出，结构与旧 schema.json 完全一致（前端零改动）；
- 场景分派 scene_kind 正确；盘后落盘池可经 candidates_from_rows 恢复；
- 调度器与业务代码不再出现策略名/场景字母硬编码（静态扫描）。
"""
from __future__ import annotations

from pathlib import Path

from quant_system import config_registry
from quant_system.strategy import (
    SCENE_IMMEDIATE,
    SCENE_PENDING,
    SCENE_SKIP,
    all_strategies,
    get_strategy,
    schemas,
    strategy_ids,
    with_phase,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "quant_system"


class TestRegistry:
    def test_three_strategies_registered(self):
        assert strategy_ids() == ["auction_grab", "dragon", "lianban", "portfolio", "tailpan"]

    def test_labels_match_history(self):
        # 落盘建议/push 里的策略名必须与历史一致
        assert get_strategy("auction_grab").label == "竞价主力抢筹"
        assert get_strategy("lianban").label == "连板捉妖"
        assert get_strategy("dragon").label == "龙回头"
        assert get_strategy("tailpan").label == "龙回头·尾盘"

    def test_unknown_strategy_raises(self):
        try:
            get_strategy("nope")
        except KeyError:
            pass
        else:
            raise AssertionError("应抛 KeyError")

    def test_phase_flags(self):
        assert [s.strategy_id for s in with_phase(auction_advice=True)] == ["auction_grab"]
        assert {s.strategy_id for s in with_phase(pool=True)} == {"lianban", "dragon"}
        assert {s.strategy_id for s in with_phase(intraday=True)} == {"lianban", "dragon"}


class TestSchemaCompat:
    """schema.json 结构不变（backend 配置页 / 前端零改动的契约）。"""

    def test_schema_shape(self):
        sc = schemas()
        assert set(sc) == {"auction_grab", "lianban", "dragon", "tailpan", "portfolio"}
        for sid, doc in sc.items():
            assert set(doc) == {"label", "params"}
            for p in doc["params"]:
                assert {"key", "label", "type", "default"} <= set(p)

    def test_param_keys_unchanged(self):
        sc = schemas()
        assert [p["key"] for p in sc["auction_grab"]["params"]] == [
            "min_rise", "max_chg_925", "limit", "base_position_pct",
        ]
        assert {p["key"] for p in sc["lianban"]["params"]} >= {
            "min_first_board_volume_ratio", "scene_a_low_open", "intraday_window_min",
        }
        assert {p["key"] for p in sc["dragon"]["params"]} >= {
            "wave_volume_ratio_max", "hengpan_minutes", "chengjie_minutes",
        }

    def test_config_registry_delegates(self):
        assert config_registry.strategy_ids() == strategy_ids()
        assert config_registry.strategy_schema("lianban")["label"] == "连板捉妖"


class TestSceneDispatch:
    def test_lianban_scene_kind(self):
        s = get_strategy("lianban")
        assert s.scene_kind("A") == SCENE_IMMEDIATE
        assert s.scene_kind("B") == SCENE_PENDING
        assert s.scene_kind("C") == SCENE_PENDING
        assert s.scene_kind("X") == SCENE_SKIP

    def test_dragon_scene_kind(self):
        s = get_strategy("dragon")
        assert s.scene_kind("D") == SCENE_IMMEDIATE
        assert s.scene_kind("E") == SCENE_PENDING
        assert s.scene_kind("F") == SCENE_PENDING
        assert s.scene_kind("X") == SCENE_SKIP


class TestPoolRoundtrip:
    def test_candidates_from_rows(self):
        from quant_system.strategy.lianban import LianbanCandidate

        s = get_strategy("lianban")
        rows = [{"thscode": "600001.SH", "name": "示例", "boards": 2}]
        out = s.candidates_from_rows(rows)
        assert out == [LianbanCandidate(thscode="600001.SH", name="示例", boards=2)]

    def test_none_rows_returns_none(self):
        assert get_strategy("lianban").candidates_from_rows(None) is None

    def test_bad_rows_returns_none(self):
        assert get_strategy("lianban").candidates_from_rows([{"bad": 1}]) is None


class TestNoHardcodedStrategyNames:
    """调度器不得再出现具体策略名/场景字母分派（换策略零改动的保障）。"""

    def test_scheduler_free_of_strategy_names(self):
        code = (SRC / "scheduler.py").read_text(encoding="utf-8")
        for banned in ("连板捉妖", "龙回头", "竞价主力抢筹", "lianban_pool", "dragon_pool"):
            assert banned not in code, f"scheduler.py 出现硬编码: {banned}"
        # 场景字母分派（A/B/C/D/E/F）也不允许
        assert '"A", "B", "C"' not in code and '"D", "E", "F"' not in code

    def test_old_modules_gone(self):
        for name in ("strategies.py", "strategy_lianban.py", "strategy_dragon.py", "pipeline.py"):
            assert not (SRC / name).exists(), f"旧模块未删除: {name}"

    def test_all_strategies_have_schema(self):
        for s in all_strategies():
            assert s.params_schema, f"{s.strategy_id} 缺 params_schema"
