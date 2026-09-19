"""q918-15：exit_advisor / strategy_feedback 备注列 dtype 守卫验证（报告链切片）。

两处同款守卫（fillna('').astype(str)，样板=bark_sender/formatters.py:262）：
- exit_advisor.load_real_positions：整列空备注 CSV → 不抛、FIFO 持仓正确保留、示例行仍过滤。
- strategy_feedback.load_real_trades：同上（该函数自带 except 会把崩溃吞成 (None, 0)，
  守卫后正常返回 df——「静默吞成零数据」与「崩溃」都是缺陷面）。
fixture 的价格/数量仅为成交记录字段（FIFO 配对需要），断言不涉及任何资金数值结论。
"""

from __future__ import annotations

import exit_advisor
import strategy_feedback

ROWS = (
    "日期,代码,名称,方向,价格,数量,备注\n"
    "2026-01-01,510300,沪深300ETF,买入,10.0,100,示例数据\n"  # 两处过滤词「示例/示例数据」均命中
    "2026-01-02,510300,沪深300ETF,卖出,10.5,100,示例数据\n"
    "2026-01-03,510300,沪深300ETF,买入,10.2,100,\n"          # 保留（整列空备注→float64 崩溃面）
)


def test_exit_advisor_load_real_positions_empty_remark_no_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(exit_advisor, "BASE_DIR", str(tmp_path))
    (tmp_path / "real_trades.csv").write_text(ROWS, encoding="utf-8")
    positions = exit_advisor.load_real_positions()
    assert isinstance(positions, list) and len(positions) == 1  # 未平仓买入 1 笔保留


def test_strategy_feedback_load_real_trades_empty_remark_no_silent_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy_feedback, "BASE_DIR", str(tmp_path))
    (tmp_path / "real_trades.csv").write_text(ROWS, encoding="utf-8")
    df, count = strategy_feedback.load_real_trades()
    assert df is not None and count == 1
