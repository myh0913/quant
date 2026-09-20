"""静态架构测试：业务代码禁止直接依赖具体数据源（换源只改 resolve 的保障）。

M2 规则：
- datasource/ 包之外不得 import 具体数据源类（EltdxSource/HithinkSource/
  XuangutongSource/EastmoneySource）；
- 业务取数必须走 datasource.resolve 的 standard_* 契约函数。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "quant_system"

# 允许 import 具体源的模块（datasource 包内部 + 各自模块自身）
_ALLOWED = {
    SRC / "datasource",
}

_BAN_PATTERNS = [
    r"from\s+\.datasource\.(eltdx_source|eastmoney|hithink|xuangutong)\s+import",
    r"from\s+quant_system\.datasource\.(eltdx_source|eastmoney|hithink|xuangutong)\s+import",
    r"\b(EltdxSource|HithinkSource|XuangutongSource|EastmoneySource)\s*\(",
]


def _iter_business_py():
    for p in SRC.rglob("*.py"):
        if any(str(p).startswith(str(a)) for a in _ALLOWED):
            continue
        yield p


class TestNoDirectDataSourceUsage:
    def test_business_code_does_not_import_sources(self):
        offenders = []
        for p in _iter_business_py():
            code = p.read_text(encoding="utf-8")
            for pat in _BAN_PATTERNS:
                if re.search(pat, code):
                    offenders.append(f"{p.relative_to(SRC)}: {pat}")
        assert not offenders, "业务代码出现直接数据源依赖:\n" + "\n".join(offenders)

    def test_resolve_covers_all_declared_capabilities(self):
        """CAPABILITY_PROVIDERS 里声明的每个能力都必须有契约函数实现。"""
        from quant_system.datasource import registry, resolve

        code = (Path(resolve.__file__)).read_text(encoding="utf-8")
        for cap in registry.CAPABILITY_PROVIDERS:
            # 每个能力至少被一个 standard_* 函数引用（capability 字符串出现在 resolve 中）
            assert f'"{cap}"' in code, f"能力 {cap} 已声明但 resolve 层无实现"

    def test_all_capabilities_have_provider(self):
        from quant_system.datasource import registry

        for cap, providers in registry.CAPABILITY_PROVIDERS.items():
            assert providers, f"能力 {cap} 无提供方"
            for sid in providers:
                assert sid in registry._SOURCE_CLS, f"能力 {cap} 引用未知数据源 {sid}"
