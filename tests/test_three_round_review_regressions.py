# -*- coding: utf-8 -*-
"""三轮全面审查（2026-05-30）回归测试：锁定 8 处 critical fix 不再退化。"""
import os
import sys
import json
import tempfile
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Round 1 #1: cost_model.with_slippage 开关（防 SLIPPAGE 双扣）
# ============================================================
def test_cost_model_with_slippage_off_skips_slippage_share():
    """with_slippage=False 时 round_trip_cost 不应包含 slippage 份额，
    避免回测 entry/exit 价格已调整滑点后再扣一次。"""
    from cost_model import round_trip_cost

    on = round_trip_cost(mcap=50e8, notional=10000, with_slippage=True)
    off = round_trip_cost(mcap=50e8, notional=10000, with_slippage=False)
    # 开关关闭时 slippage 字段应为 0；rate 至少应该减去那块滑点
    assert off.slippage == 0
    assert off.rate < on.rate


def test_get_cost_by_mcap_with_slippage_param_propagates():
    from cost_model import get_cost_by_mcap

    on = get_cost_by_mcap(50e8, notional=10000, with_slippage=True)
    off = get_cost_by_mcap(50e8, notional=10000, with_slippage=False)
    assert off < on


# ============================================================
# Round 1 #2: cost_model REGIME_ALLOC 五档 key
# ============================================================
def test_regime_allocation_has_five_explicit_keys():
    """compute_dynamic_notional 不应再在 '牛市/熊市' 上 fallback 到默认 0.40。"""
    from cost_model import REGIME_ALLOC

    for k in ('强牛', '弱牛', '震荡', '弱熊', '强熊'):
        assert k in REGIME_ALLOC, f'缺 {k} 档位'


# ============================================================
# Round 1 #5: position_sizer.calc_gap_deviation prev_close
# ============================================================
def test_gap_deviation_uses_yesterday_close():
    """iloc[-1] 是历史最后一条（今日），prev_close 应取 iloc[-2]（昨日）。"""
    from position_sizer import calc_gap_deviation

    # 构造：昨日收盘 10.0，今日开盘 10.5（跳空 +5%）
    hist = pd.DataFrame({
        '代码': ['000001'] * 5,
        '日期': pd.to_datetime(['2026-05-26', '2026-05-27', '2026-05-28', '2026-05-29', '2026-05-30']),
        '开盘': [9.5, 9.7, 9.8, 9.9, 10.5],
        '收盘': [9.6, 9.8, 9.9, 10.0, 10.5],
        '最高': [9.7, 9.9, 10.0, 10.1, 10.6],
        '最低': [9.4, 9.6, 9.7, 9.8, 10.4],
    })
    # current_price = 今日开盘 10.5，prev_close = iloc[-2]['收盘'] = 10.0 → gap≈+5%
    result = calc_gap_deviation('000001', current_price=10.5, hist_df=hist)
    assert result is not None
    gap_pct = result['gap_pct']
    # 旧 bug 用 iloc[-1] 即今日收盘 10.5 → gap=0；修复后用 iloc[-2]=10.0 → gap=+5%
    assert abs(gap_pct - 5.0) < 0.5, f'gap_pct={gap_pct}, 期望 ~5%'


# ============================================================
# Round 2 #2: alpha_gate 同日重复运行不二次累加
# ============================================================
def test_alpha_gate_same_day_no_double_count(tmp_path):
    """severity='severe' 同一交易日重复跑 check_alpha_gate 应只累加 1 次。"""
    import alpha_gate

    # 写一个 paused=False / counter=0 的初始 state
    state_dir = str(tmp_path)
    state_file = alpha_gate._state_file_path(state_dir)
    initial = alpha_gate._blank_state()
    alpha_gate._atomic_write_json(state_file, initial)

    # mock evaluate_etf_gate 返回 severe
    class _FakeETFResult:
        severity = 'severe'
        excess_pct = -2.0

    orig = alpha_gate.evaluate_etf_gate
    alpha_gate.evaluate_etf_gate = lambda: _FakeETFResult()
    try:
        r1 = alpha_gate.check_alpha_gate(state_dir=state_dir, trading_day_ok=True)
        r2 = alpha_gate.check_alpha_gate(state_dir=state_dir, trading_day_ok=True)
        assert r1.consecutive_severe_days == 1
        # 第二次调用（同一天）不再 +1
        assert r2.consecutive_severe_days == 1, f'同日二次 +1 → {r2.consecutive_severe_days}'
    finally:
        alpha_gate.evaluate_etf_gate = orig


# ============================================================
# Round 2 #3: fetch_history.code_to_sina_symbol 沪市可转债
# ============================================================
@pytest.mark.parametrize('code,expected', [
    ('110001', 'sh110001'),  # 沪市可转债
    ('113043', 'sh113043'),
    ('118000', 'sh118000'),
    ('123001', 'sz123001'),  # 深市可转债（保持 sz）
    ('159001', 'sz159001'),  # 深市 ETF
    ('600001', 'sh600001'),
    ('000001', 'sz000001'),
    ('300001', 'sz300001'),
    ('888001', 'bj888001'),
])
def test_sina_symbol_handles_sh_convertible_bonds(code, expected):
    from fetch_history import code_to_sina_symbol
    assert code_to_sina_symbol(code) == expected


# ============================================================
# Round 3 #1: log_real_trade.calc_fee 套用 5 元最低佣金
# ============================================================
def test_log_real_trade_fee_applies_min_commission():
    """1200 元小额买入：实际佣金应 = 5 元（不是 amount × 0.025% = 0.3 元）。"""
    from log_real_trade import calc_fee

    fee_buy_small = calc_fee('买入', price=12.0, qty=100, amount=1200.0)
    # 买入：佣金 max(1200 × 0.0003, 5) = 5；印花 0
    assert fee_buy_small == 5.0, f'1200 元买入 fee 应是 5 元（最低佣金），实际 {fee_buy_small}'

    fee_sell_small = calc_fee('卖出', price=12.0, qty=100, amount=1200.0)
    # 卖出：佣金 5 + 印花 1200 × 0.0005 = 5.6
    assert abs(fee_sell_small - 5.6) < 0.01, f'1200 元卖出 fee 应是 5.60 元，实际 {fee_sell_small}'


def test_log_real_trade_fee_above_threshold_uses_rate():
    """大额成交：佣金按 amount × 0.0003 计算，不再触发最低。"""
    from log_real_trade import calc_fee

    fee_buy_big = calc_fee('买入', price=100.0, qty=1000, amount=100000.0)
    # 100000 × 0.0003 = 30 > 5 → 走 rate
    assert abs(fee_buy_big - 30.0) < 0.01


# ============================================================
# Round 2 #1: walk_forward.MA_LONG 参数真生效
# ============================================================
def test_walk_forward_ma_long_param_actually_used():
    """`_calc_indicators_with_ma(hist, ma_long)` 不同 ma_long 应产出不同 MA_long 列。"""
    from walk_forward import _calc_indicators_with_ma

    # 30 个交易日 close = 10..39（线性递增）
    n = 30
    hist = pd.DataFrame({
        '代码': ['000001'] * n,
        '日期': pd.date_range('2026-04-01', periods=n, freq='D'),
        '收盘': list(range(10, 10 + n)),
        '开盘': list(range(10, 10 + n)),
    })

    out_20 = _calc_indicators_with_ma(hist, ma_long=20)
    out_30 = _calc_indicators_with_ma(hist, ma_long=30)
    # 最后一行 MA_long 应不同（20 日 ≠ 30 日均值）
    last20 = out_20.iloc[-1]['MA_long']
    last30 = out_30.iloc[-1]['MA_long']
    assert not np.isnan(last20)
    assert not np.isnan(last30)
    assert abs(last20 - last30) > 1e-6, '不同 ma_long 产出相同列 → 修复退化'


# ============================================================
# 收尾健康检查
# ============================================================
def test_pipeline_registry_all_scripts_exist():
    from core.pipeline import PIPELINE_STEPS

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    missing = []
    for k, v in PIPELINE_STEPS.items():
        if not os.path.exists(os.path.join(base, v['script'])):
            missing.append((k, v['script']))
    assert not missing, f'pipeline 注册表里有不存在的脚本: {missing}'
