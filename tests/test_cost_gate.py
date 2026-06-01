"""每笔订单成本门槛回归测试（2026-08-24 round 4）。

锁定：cost_model 纯函数、position_sizer 第一道门槛 + 集中 fallback、
sim_trade 执行前第二道门槛（加仓按增量金额、减仓不受限）。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from cost_model import order_passes_cost_gate, round_trip_cost
import position_sizer
import sim_trade


def _picks_df(prices=(8.0, 8.0, 8.0), mcaps=(0, 0, 0)):
    rows = []
    for i, (price, mcap) in enumerate(zip(prices, mcaps)):
        rows.append({
            '代码': f'60000{i}', '名称': f'股{i}', '收盘': price,
            '最新价': price, 'momentum': 1.0,
            '流通市值': mcap,
        })
    return pd.DataFrame(rows)


def _sizer_cfg_stub(max_pct):
    def fake(key, default=None):
        if key == 'cost.order_gate_max_pct':
            return max_pct
        return default
    return fake


def _sim_state(cash=5000.0):
    return {
        'cash': cash, 'total_invested': 0, 'equity': cash,
        'initial_capital': 2400.0, 'positions': [],
        'total_trades': 0, 'winning_trades': 0, 'total_pnl': 0.0,
        'total_commission': 0.0, 'total_stamp_tax': 0.0,
        'total_trade_volume': 0.0,
    }


# ---------- cost_model 纯函数 ----------

def test_cost_model_gate_rejects_expensive_small_order():
    ok, cb = order_passes_cost_gate(400, mcap=0, max_pct=0.025)
    assert ok is False
    assert cb.pct > 2.5


def test_cost_model_gate_accepts_large_order_and_explicit_limit():
    ok, cb = order_passes_cost_gate(2400, mcap=0, max_pct=0.025)
    assert ok is True
    assert cb.pct < 2.5

    ok2, _ = order_passes_cost_gate(400, mcap=0, max_pct=0.04)
    assert ok2 is True


def test_cost_model_gate_rejects_nonpositive_amount():
    ok, cb = order_passes_cost_gate(0, mcap=0, max_pct=0.025)
    assert ok is False
    assert cb.notional == 0


# ---------- position_sizer 第一道门槛 ----------

def test_position_sizer_top3_rejected_fallback_single_passes(monkeypatch):
    monkeypatch.setattr(position_sizer, 'cfg_get', _sizer_cfg_stub(0.015))
    orders, summary = position_sizer.calculate_position_sizes(
        _picks_df(prices=(8.0, 8.0, 8.0), mcaps=(0, 0, 0)),
        regime='震荡', total_capital=2400,
    )
    # top3 各约 800 元、小盘往返成本 1.9% > 1.5% → 全被拦；fallback 单票原本 2400，
    # 但 2400+5 佣金超过本金，现金收口缩到 200 股（1600+5），仍过 1.5% 成本门槛
    assert len(orders) == 1
    assert orders[0]['金额'] == 1600.0
    assert orders[0]['预计佣金'] == 5.0
    assert summary['cost_gate_skipped'] == 3
    assert summary['cost_gate_fallback_used'] is True
    assert '往返成本' in orders[0]
    assert orders[0]['往返成本率'] < 0.015


def test_position_sizer_all_candidates_rejected_returns_empty(monkeypatch):
    monkeypatch.setattr(position_sizer, 'cfg_get', _sizer_cfg_stub(0.005))
    orders, summary = position_sizer.calculate_position_sizes(
        _picks_df(prices=(8.0, 8.0, 8.0), mcaps=(0, 0, 0)),
        regime='震荡', total_capital=2400,
    )
    assert orders == []
    assert summary['cost_gate_skipped'] >= 4  # 3 主候选 + 1 fallback
    assert summary['cost_gate_fallback_used'] is False


def test_position_sizer_normal_orders_pass_default_gate(monkeypatch):
    # 默认 2.5%：800 元小盘 1.9% 应通过；但 2400 现金容不下 3 笔佣金
    # （3×805=2415），现金收口必须保留 2 笔计划，保证 sim/实盘可完整执行
    orders, summary = position_sizer.calculate_position_sizes(
        _picks_df(prices=(8.0, 8.0, 8.0), mcaps=(0, 0, 0)),
        regime='震荡', total_capital=2400,
    )
    assert len(orders) == 2
    assert summary['cost_gate_skipped'] == 0
    assert summary['预计佣金合计'] == 10.0
    assert summary['预计占用现金'] == 1610.0
    assert summary['cash_remaining'] == 790.0
    assert all('往返成本' in o and '往返成本率' in o for o in orders)


def test_position_sizer_strong_bear_keeps_empty_with_gate_fields():
    orders, summary = position_sizer.calculate_position_sizes(
        _picks_df(), regime='强熊', total_capital=2400,
    )
    assert orders == []
    assert summary['cost_gate_max_pct'] == 0.025
    assert summary['cost_gate_skipped'] == 0


# ---------- sim_trade 第二道门槛 ----------

def test_sim_trade_rejects_expensive_manual_order(monkeypatch):
    state = _sim_state()
    prices = {'600000': {'price': 4.0, 'name': '股0', 'change_pct': 0}}
    order = {'代码': '600000', '股数': 100, '流通市值': 0}  # 400 元 → 成本 3.15%
    executed = sim_trade.execute_buy_orders(state, [order], prices)
    assert executed == []
    assert state['positions'] == []
    assert state['cash'] == 5000.0


def test_sim_trade_accepts_normal_order(monkeypatch):
    state = _sim_state()
    prices = {'600000': {'price': 4.0, 'name': '股0', 'change_pct': 0}}
    order = {'代码': '600000', '股数': 500, '流通市值': 6e10}  # 2000 元
    executed = sim_trade.execute_buy_orders(state, [order], prices)
    assert len(executed) == 1
    assert len(state['positions']) == 1
    assert state['cash'] < 5000.0


def test_sim_trade_reduction_is_not_blocked_by_gate(monkeypatch):
    state = _sim_state(cash=1000.0)
    state['positions'] = [{
        'code': '600000', 'name': '股0', 'shares': 500,
        'entry_price': 4.0, 'entry_date': '2026-08-20',
        'current_price': 4.0, 'stop_loss': 3.7, 'take_profit': 4.8,
        'hold_days': 1, 'unrealized_pnl': 0, 'unrealized_pnl_pct': 0,
    }]
    state['total_invested'] = 2000.0
    prices = {'600000': {'price': 4.0, 'name': '股0', 'change_pct': 0}}
    order = {'代码': '600000', '股数': 100, '流通市值': 0}  # 400 元高成本，但这是减仓
    executed = sim_trade.execute_buy_orders(state, [order], prices)
    assert len(executed) == 1
    assert executed[0]['shares'] == 100
    assert state['cash'] > 1000.0  # 减仓回款
