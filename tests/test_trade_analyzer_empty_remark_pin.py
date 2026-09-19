"""「备注列整列空 → float64 → .str 崩」缺陷修复翻转钉桩（916p-a1-006 → q918-13）。

历史（2026-09-17 实测）：备注整列空被 read_csv 读成 float64，
.str 访问器抛 AttributeError（trade_analyzer.py:17），本文件曾以
pytest.raises(AttributeError) 钉住缺陷形态。
q918-13 修复落地（_load_real_trades 读入后 fillna('').astype(str) 守卫，
样板=bark_sender/formatters.py:262）：本文件翻转为断言「不抛错且持仓保留」，
并补一行钉住示例数据过滤语义未被守卫带偏。
数据仅表头＋空备注一行，零资金/收益/统计数值。
可复跑：python -m pytest tests/test_trade_analyzer_empty_remark_pin.py -q
"""
import os

import trade_analyzer as ta


def test_empty_remark_column_no_raise_and_rows_kept(tmp_path):
    """翻转钉桩：整列空备注 → 不抛错，持仓行保留（守卫只修 dtype 不删行）。"""
    csv = tmp_path / "real_trades.csv"
    csv.write_text("日期,代码,名称,方向,备注\n2026-01-01,510300,沪深300ETF,买入,\n",
                   encoding="utf-8")
    df, count = ta._load_real_trades(str(tmp_path))
    assert df is not None and count == 1
    assert len(df) == 1
    assert os.path.exists(str(csv))  # 佐证读的就是这份临时数据


def test_sample_rows_still_filtered_after_guard(tmp_path):
    """守卫不带偏过滤语义：备注含「示例数据」的行仍被剔除。"""
    csv = tmp_path / "real_trades.csv"
    csv.write_text(
        "日期,代码,名称,方向,备注\n"
        "2026-01-01,510300,沪深300ETF,买入,示例数据\n"
        "2026-01-02,510300,沪深300ETF,卖出,\n",
        encoding="utf-8",
    )
    df, count = ta._load_real_trades(str(tmp_path))
    assert count == 1 and len(df) == 1
    assert (df['备注'] == '').all()  # 空备注经守卫后为空串 dtype=object
