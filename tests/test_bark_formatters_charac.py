"""h912-10 批B1：bark_sender.formatters 格式化边界 characterization。

对应基线 §四 第 5 行补测点：大数/负数/零/空值/None/超长输入。
只做行为/文案结构断言，不写资金数值计算断言。
"""

from __future__ import annotations

import bark_sender.formatters as formatters


def _stock(**over):
    base = {"name": "浦发银行", "code": "600000", "price": "10.00", "change": "+1.0%",
            "score": "80", "rsi": "55.0", "vol_ratio": "1.2", "ma5": "9.8", "ma20": "9.5", "reason": ""}
    base.update(over)
    return base


# ---- explain_stock_detailed：字段边界 ----

def test_explain_empty_fields_falls_back_to_score_line():
    """空值/None 字段全缺失 → 回退到「综合技术面表现靠前」句。"""
    out = formatters.explain_stock_detailed({"name": "X", "change": "", "score": ""})
    assert out.startswith("X 评分") and "综合技术面表现靠前" in out


def test_explain_ma_bullish_alignment_branch():
    """均线多头 + 价站双线上 → 多头排列文案。"""
    s = _stock(price="10.5", ma5="9.8", ma20="9.5")
    out = formatters.explain_stock_detailed(s)
    assert "均线呈多头排列" in out and "站在两条均线上方" in out


def test_explain_huge_volume_ratio_takes_big_money_branch():
    """大数量比（vr=999）→ 「大资金主动买入」分支文案。"""
    out = formatters.explain_stock_detailed(_stock(vol_ratio="999"))
    assert "量比高达999" in out and "大资金" in out


def test_explain_rsi_golden_zone():
    """RSI=50 黄金区间文案。"""
    out = formatters.explain_stock_detailed(_stock(rsi="50"))
    assert "黄金区间" in out


def test_explain_negative_change_adds_no_rally_point():
    """负涨幅（-3.0%）→ 无涨幅点，其余正常组装。"""
    out = formatters.explain_stock_detailed(_stock(change="-3.0%", rsi=""))
    assert "今日涨幅-3.0%" not in out
    assert out.startswith("浦发银行（-3.0%")


def test_explain_special_signal_keywords_append_points():
    """技术面字段留空（不产点）时，reason 含「强趋势」「MACD正向」→ 追加两条信号点。"""
    out = formatters.explain_stock_detailed(_stock(price="", ma5="", ma20="", rsi="", vol_ratio="", change="0.0%", reason="强趋势 MACD正向"))
    assert "上升通道" in out and "MACD" in out


def test_explain_max_four_points_selected():
    """超长信号堆叠 → 只取前 4 条（截断规则）。"""
    s = _stock(price="10.5", ma5="9.8", ma20="9.5", vol_ratio="2.5", rsi="50",
               change="+5.0%", reason="强趋势 MACD正向")
    out = formatters.explain_stock_detailed(s)
    body = out.split("）：", 1)[1]
    assert body.count("；") == 3  # 4 条点之间 3 个分隔


# ---- build_previous_review：空值与三分支 ----

def test_previous_review_none_and_missing_date_return_empty():
    """None / 无 previous / 无 date → 空列表。"""
    assert formatters.build_previous_review(None) == []
    assert formatters.build_previous_review({}) == []
    assert formatters.build_previous_review({"previous": {"count": 3}}) == []


def test_previous_review_three_interpretation_branches_with_big_number():
    """大数/负数收益的三种解读分支与 ±.2f 格式化。"""
    good = formatters.build_previous_review({"previous": {"date": "2026-09-10", "count": 5, "win_rate": 60, "avg_ret": 12.345}})
    assert "✅" in good[2] and "+12.35%" in good[2] and "趋势延续良好" in good[3]
    mid = formatters.build_previous_review({"previous": {"date": "d", "count": 5, "win_rate": 40, "avg_ret": 0.2}})
    assert "盈亏比在起作用" in mid[3]
    bad = formatters.build_previous_review({"previous": {"date": "d", "count": 5, "win_rate": 40, "avg_ret": -3}})
    assert "❌" in bad[2] and "-3.00%" in bad[2] and "承压" in bad[3]


# ---- build_tomorrow_guide：空值/梯队/集中度 ----

def test_tomorrow_guide_empty_stocks_no_crash():
    """零候选 → 不崩溃，输出候选池 0 只文案。"""
    out = formatters.build_tomorrow_guide([], None)
    assert "候选池规模（0只）" in out
    assert "【仓位与风控】" in out


def test_tomorrow_guide_tiers_and_power_concentration():
    """梯队阈值（97/94）与电力板块集中度提示（≥3 只）。"""
    stocks = [
        _stock(name="电A", score="98"), _stock(name="电B", score="95"),
        _stock(name="电C", score="93"), _stock(name="正常股", score="90"),
    ]
    out = formatters.build_tomorrow_guide(stocks, {"bull_trades": 30, "bear_trades": 10, "net10": 1.5, "excess": 0.5})
    assert "第一梯队（>97分）：电A" in out
    assert "第二梯队（94-96分）：电B" in out
    assert "牛市占比75%" in out
    assert "电力板块入选3只" in out


def test_risk_control_lines_small_vs_large_capital_and_bear(monkeypatch):
    """小/大资金 × 强熊/常态 四象限文案（配置走默认）。"""
    monkeypatch.setattr(formatters, "cfg_get", lambda k, d: d)
    monkeypatch.setattr(formatters, "_latest_order_regime", lambda: "")
    small = formatters._risk_control_lines()
    assert "小资金模式" in small[1] and "止损线：-8%" in small[2] and "止盈参考：+20%" in small[3]
    monkeypatch.setattr(formatters, "cfg_get", lambda k, d: 8000 if k == "sim.initial_capital" else d)
    big = formatters._risk_control_lines()
    assert "按市场状态分档" in big[1]
    monkeypatch.setattr(formatters, "_latest_order_regime", lambda: "强熊")
    assert "强熊市空仓观望" in formatters._risk_control_lines()[1]


def test_personalized_section_missing_and_broken_csv_return_empty(tmp_path, monkeypatch):
    """real_trades.csv 缺失/损坏 → 空列表（异常路径容错）。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path), raising=False)
    assert formatters.build_personalized_section() == []
    (tmp_path / "real_trades.csv").write_bytes(b"\xff\xfe broken,csv\n\x00\x01")
    assert formatters.build_personalized_section() == []
