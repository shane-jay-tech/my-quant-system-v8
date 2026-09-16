"""「备注列整列空 → float64 → .str 崩」缺陷钉桩（916p-a1-006）。

本用例钉住 trade_analyzer._load_real_trades 的**当前缺陷形态**（实测复现
2026-09-17，AttributeError: Can only use .str accessor with string values,
not floating —— trade_analyzer.py:17）：备注整列空被 read_csv 读成 float64，
.str 访问器直接抛 AttributeError 且本函数不捕获。
修复（fillna('').astype(str) 形态，参照 bark_sender/formatters.py:262）落地后，
本用例应改为断言「持仓保留、不抛错」。
数据仅表头+空备注一行，零资金/收益/统计数值。
可复跑：python -m pytest tests/test_trade_analyzer_empty_remark_pin.py -q
"""
import os

import pytest

import trade_analyzer as ta


def test_empty_remark_column_current_defect_form(tmp_path):
    """钉住：整列空备注 → AttributeError 自 _load_real_trades 冒泡（当前缺陷）。"""
    csv = tmp_path / "real_trades.csv"
    csv.write_text("日期,代码,名称,方向,备注\n2026-01-01,510300,沪深300ETF,买入,\n",
                   encoding="utf-8")
    with pytest.raises(AttributeError):
        ta._load_real_trades(str(tmp_path))
    assert os.path.exists(str(csv))  # 佐证读的就是这份临时数据
