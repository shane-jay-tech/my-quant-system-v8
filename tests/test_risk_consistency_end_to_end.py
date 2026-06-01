"""风控口径端到端一致性测试（2026-08-24 round 10）。

验证 GOAL 风控层要求：止损/止盈/持有天数与真实账户基线在
position_sizer → sim_trade → exit_advisor 链路上口径一致；强熊空仓。
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import position_sizer as ps
import sim_trade
import exit_advisor


def _picks_df():
    return pd.DataFrame([
        {'代码': '600000', '名称': '股0', '收盘': 8.0, 'momentum': 1.0,
         '流通市值': 6e10},
        {'代码': '600001', '名称': '股1', '收盘': 8.0, 'momentum': 1.0,
         '流通市值': 6e10},
        {'代码': '600002', '名称': '股2', '收盘': 8.0, 'momentum': 1.0,
         '流通市值': 6e10},
    ])


def _config_stub(stop=-0.08, take=0.20, hold=10):
    def fake(key, default=None):
        mapping = {
            'sim.stop_loss_pct': stop,
            'sim.take_profit_pct': take,
            'sim.max_hold_days': hold,
            'sim.initial_capital': 2400,
            'portfolio.exclude_held_from_picks': False,
            'cost.order_gate_max_pct': 0.025,
        }
        return mapping.get(key, default)
    return fake


def _sim_state(cash=2400.0):
    return {
        'cash': cash, 'total_invested': 0, 'equity': cash,
        'initial_capital': 2400.0, 'positions': [],
        'total_trades': 0, 'winning_trades': 0, 'total_pnl': 0.0,
        'total_commission': 0.0, 'total_stamp_tax': 0.0,
        'total_trade_volume': 0.0,
    }


def test_alert_only_end_to_end_stop_take_hold_consistent(monkeypatch):
    # 1) position_sizer 生成订单，并回退固定止损；2400 本金要预留每笔佣金，
    #    计划只能保留 2 笔（3×800+3×5=2415 > 2400）
    monkeypatch.setattr(ps, 'cfg_get', _config_stub())
    orders, summary = ps.calculate_position_sizes(
        _picks_df(), regime='震荡', total_capital=2400)
    assert len(orders) == 2
    assert summary['预计佣金合计'] == 10.0
    assert summary['预计占用现金'] == 1610.0
    ps.calculate_stop_loss(None, orders)
    order = orders[0]
    assert order['止损方式'] == '固定-8%'

    # 2) sim_trade 按 alert_only=true 的 risk_config 执行（stop/take 用 sim.*）
    risk_file = {'stop_loss_pct': -0.20, 'take_profit_pct': 0.50,
                 'max_hold_days': 10, 'alert_only': True}
    monkeypatch.setattr(sim_trade, 'cfg_get', _config_stub())
    state = _sim_state()
    prices = {o['代码']: {'price': 8.0, 'name': o['名称'], 'change_pct': 0}
              for o in orders}
    executed = sim_trade.execute_buy_orders(
        state, orders, prices,
        stop_loss_pct=-0.08, take_profit_pct=0.20)
    assert len(executed) == 2
    pos = executed[0]
    assert pos['stop_loss'] == order['止损价'] == 7.36
    assert pos['take_profit'] == round(8.01 * 1.20, 2)  # sim 按滑点后 8.01 入场

    # 3) exit_advisor 用同一 risk_config + alert_only 语义分析
    result = exit_advisor.analyze_position(
        pos, {'600000': {'price': 8.0, 'name': '股0', 'change_pct': 0}},
        history_df=None, risk_config=dict(risk_file))
    assert result['stop_loss'] == pos['stop_loss']
    assert result['take_profit'] == pos['take_profit']


def test_non_alert_only_overrides_flow_consistently(tmp_path, monkeypatch):
    """alert_only=false 时，反馈循环对 stop/take/hold 的覆盖在两个模块一致。"""
    risk_file = {'stop_loss_pct': -0.10, 'take_profit_pct': 0.25,
                 'max_hold_days': 7, 'alert_only': False}
    risk_path = tmp_path / 'risk_config.json'
    risk_path.write_text(json.dumps(risk_file), encoding='utf-8')
    monkeypatch.setattr(sim_trade, 'RISK_CONFIG_FILE', str(risk_path))
    sim_effective = sim_trade.load_risk_config()
    assert sim_effective == {
        'STOP_LOSS_PCT': -0.10, 'TAKE_PROFIT_PCT': 0.25, 'MAX_HOLD_DAYS': 7,
    }

    exit_rules = exit_advisor.effective_risk_config(dict(risk_file))
    assert exit_rules['stop_loss_pct'] == sim_effective['STOP_LOSS_PCT']
    assert exit_rules['take_profit_pct'] == sim_effective['TAKE_PROFIT_PCT']
    assert exit_rules['max_hold_days'] == sim_effective['MAX_HOLD_DAYS']


def test_strong_bear_generates_no_orders_and_sim_stays_flat(monkeypatch):
    monkeypatch.setattr(ps, 'cfg_get', _config_stub())
    orders, summary = ps.calculate_position_sizes(
        _picks_df(), regime='强熊', total_capital=2400)
    assert orders == []
    assert summary['alloc_pct'] == 0.0

    state = _sim_state()
    executed = sim_trade.execute_buy_orders(
        state, [], {}, stop_loss_pct=-0.08, take_profit_pct=0.20)
    assert executed == []
    assert state['positions'] == []


def test_position_sizer_budget_follows_sim_account_baseline(tmp_path, monkeypatch):
    """仓位计算预算必须读取 sim 账户 initial_capital（真实账户联动的结果）。"""
    state_dir = tmp_path / 'sim_results'
    state_dir.mkdir()
    (state_dir / 'account_state.json').write_text(
        json.dumps({'initial_capital': 1005.0}), encoding='utf-8')
    monkeypatch.setattr(ps, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(ps, '_CONFIG_CAPITAL', 2400.0)
    assert ps._resolve_default_capital() == 1005.0


def test_real_trades_net_invested_drives_sim_baseline(tmp_path, monkeypatch):
    """sim 起步资金在未手填 manual_capital 时跟随 real_trades.csv 净投入。"""
    trades = tmp_path / 'real_trades.csv'
    trades.write_text(
        '日期,代码,名称,方向,价格,数量,成交额,手续费,下单依据,备注\n'
        '2026-08-20,600000,股0,买入,10.0,100,1000.0,5.0,sys,\n',
        encoding='utf-8')
    monkeypatch.setattr(sim_trade, 'REAL_TRADES_FILE', str(trades))
    monkeypatch.setattr(sim_trade, 'get_manual_capital', lambda: None)
    monkeypatch.setattr(sim_trade, '_USE_REAL_CAPITAL', True)
    assert sim_trade.get_real_invested_capital() == 1005.0
    assert sim_trade.resolve_initial_capital() == 1005.0
