"""股票池过滤：只保留 60/00 开头、非 ST/*ST 的普通主板股票。"""
from __future__ import annotations

import re

_PREFIX_OK = ("60", "00")
_ST_PAT = re.compile(r"^(\*ST|ST)", re.IGNORECASE)


def normalize_thscode(code: str) -> str:
    """归一化证券代码为内部标准格式：6位.SH/.SZ。

    兼容输入：600519 / 600519.SH / 600519.SS / sh600519 / sz000001 等。
    非法输入返回空串。内部统一用 .SH/.SZ（与同花顺/东财一致）；
    选股通的 .SS 必须归一为 .SH，否则跨源比对会失配（2026-09-06 实测踩坑）。
    """
    c = (code or "").strip().upper()
    for suf in (".SS", ".SH", ".SZ", ".BJ"):
        if c.endswith(suf):
            c = c[: -len(suf)]
            break
    if c.startswith("SH") or c.startswith("SZ"):
        c = c[2:]
    if len(c) != 6 or not c.isdigit():
        return ""
    if c.startswith("6"):
        return c + ".SH"
    if c.startswith(("0", "3")):
        return c + ".SZ"
    return c + ".BJ" if c.startswith(("4", "8", "9")) else ""


def is_target_stock(code: str, name: str = "") -> bool:
    """判断股票是否属于首期股票池（60/00 开头、非 ST/*ST）。"""
    code = (code or "").strip().lower()
    # 兼容带交易所后缀（600540.SS / 000001.SZ / sz000001 / sh600519）
    for suf in (".ss", ".sh", ".sz", ".bj"):
        if code.endswith(suf):
            code = code[: -len(suf)]
            break
    if code.startswith("sz") or code.startswith("sh"):
        code = code[2:]
    if len(code) != 6 or not code.isdigit():
        return False
    return code.startswith(_PREFIX_OK) and not _ST_PAT.match(name or "")


def filter_target_stocks(rows, code_attr="thscode", name_attr="name") -> list:
    """对 dict-like 列表应用股票池过滤，保留字段原样。"""
    out = []
    for r in rows:
        code = r.get(code_attr, "") if isinstance(r, dict) else getattr(r, code_attr, "")
        name = r.get(name_attr, "") if isinstance(r, dict) else getattr(r, name_attr, "")
        if is_target_stock(code, name):
            out.append(r)
    return out
