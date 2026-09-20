"""股票池过滤与代码归一化单元测试（无网络）。"""
from __future__ import annotations

from quant_system.pool import filter_target_stocks, is_target_stock, normalize_thscode


def test_sh_main():
    assert is_target_stock("600540.SS", "新赛股份")
    assert is_target_stock("sh600519", "贵州茅台")
    assert is_target_stock("600519", "")


def test_sz_main():
    assert is_target_stock("000001.SZ", "平安银行")
    assert is_target_stock("sz000892", "欢瑞世纪")
    # 002/003 属于深主板（00 开头）
    assert is_target_stock("002472", "双环传动")
    assert is_target_stock("003040", "楚天龙")


def test_excluded():
    assert not is_target_stock("300308", "中际旭创")
    assert not is_target_stock("301297", "富乐德")
    assert not is_target_stock("688981", "中芯国际")
    assert not is_target_stock("920075", "柏星龙")
    assert not is_target_stock("600121", "ST郑煤")
    assert not is_target_stock("600121", "*ST郑煤")
    assert not is_target_stock("")
    assert not is_target_stock("12345")


def test_filter_rows():
    rows = [
        {"thscode": "600540.SS", "name": "新赛股份"},
        {"thscode": "300308.SZ", "name": "中际旭创"},
        {"thscode": "000001.SZ", "name": "平安银行"},
    ]
    out = filter_target_stocks(rows)
    assert [r["thscode"] for r in out] == ["600540.SS", "000001.SZ"]


def test_normalize_thscode():
    assert normalize_thscode("600519") == "600519.SH"
    assert normalize_thscode("600519.SH") == "600519.SH"
    assert normalize_thscode("600519.SS") == "600519.SH"  # 选股通后缀归一
    assert normalize_thscode("sh600519") == "600519.SH"
    assert normalize_thscode("sz000001") == "000001.SZ"
    assert normalize_thscode("000001.SZ") == "000001.SZ"
    assert normalize_thscode("") == ""
    assert normalize_thscode("abc") == ""
    assert normalize_thscode("920075.BJ") == "920075.BJ"
