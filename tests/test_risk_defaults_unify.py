"""风控默认值单一真相源回归测试（2026-08-24 round 3）。

锁定：auto_heal 重建 risk_config、exit_advisor 回退、position_sizer ATR 止损回退、
strategy 报告文案都跟随 core.config sim.*（-8% / +20% / 10天），不再出现 -5% / 30 天 / +30%。
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import auto_heal
import exit_advisor
import position_sizer
import strategy


def _sim_config_stub(stop=-0.08, take=0.20, hold=10, capital=2400.0):
    def fake(key, default=None):
        mapping = {
            'sim.stop_loss_pct': stop,
            'sim.take_profit_pct': take,
            'sim.max_hold_days': hold,
            'sim.initial_capital': capital,
        }
        return mapping.get(key, default)
    return fake


# ---------- auto_heal ----------

def test_auto_heal_rebuilds_risk_config_from_single_source(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_heal, 'BASE', str(tmp_path))
    monkeypatch.setattr(auto_heal, 'cfg_get', _sim_config_stub())

    ok = auto_heal.fix_missing_risk_config()
    assert ok is True

    saved = json.loads((tmp_path / 'data' / 'risk_config.json').read_text(encoding='utf-8'))
    assert saved['stop_loss_pct'] == -0.08
    assert saved['take_profit_pct'] == 0.20
    assert saved['max_hold_days'] == 10
    assert saved['alert_only'] is True  # 防止重建后反馈循环意外接管 stop/take


# ---------- exit_advisor ----------

def test_exit_advisor_effective_config_alert_only_uses_sim_defaults(monkeypatch):
    monkeypatch.setattr(exit_advisor, 'cfg_get', _sim_config_stub())
    rules = exit_advisor.effective_risk_config({
        'stop_loss_pct': -0.5, 'take_profit_pct': 0.5,
        'max_hold_days': 99, 'alert_only': True,
    })
    assert rules['stop_loss_pct'] == -0.08
    assert rules['take_profit_pct'] == 0.20
    assert rules['max_hold_days'] == 99  # alert_only 只接管 hold


def test_exit_advisor_effective_config_non_alert_allows_feedback_overrides(monkeypatch):
    monkeypatch.setattr(exit_advisor, 'cfg_get', _sim_config_stub())
    rules = exit_advisor.effective_risk_config({
        'stop_loss_pct': -0.10, 'take_profit_pct': 0.25, 'max_hold_days': 7,
    })
    assert rules['stop_loss_pct'] == -0.10
    assert rules['take_profit_pct'] == 0.25
    assert rules['max_hold_days'] == 7


def test_exit_advisor_analyze_position_uses_effective_rules(monkeypatch):
    monkeypatch.setattr(exit_advisor, 'cfg_get', _sim_config_stub())
    pos = {'code': '600000', 'name': '测试', 'entry_price': 10.0,
           'entry_date': '2026-08-14', 'shares': 100, 'source': 'sim'}
    prices = {'600000': {'price': 10.0, 'name': '测试', 'change_pct': 0}}
    result = exit_advisor.analyze_position(
        pos, prices, history_df=None,
        risk_config={'max_hold_days': 7, 'alert_only': True},
    )
    assert result['stop_loss'] == 9.20
    assert result['take_profit'] == 12.00
    assert result['hold_days'] <= 7


def test_exit_advisor_report_rules_are_dynamic(tmp_path, monkeypatch):
    monkeypatch.setattr(exit_advisor, 'RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(exit_advisor, 'cfg_get', _sim_config_stub())
    analyses = [{
        'code': '600000', 'name': '测试', 'entry_price': 10.0,
        'current_price': 10.0, 'shares': 100, 'pnl_pct': 0.0,
        'hold_days': 1, 'source': 'sim', 'action': 'hold',
        'action_label': '持有', 'signals': [],
    }]
    path = exit_advisor.generate_report(analyses)
    text = Path(path).read_text(encoding='utf-8')
    assert '止损价（-8%）' in text
    assert '止盈价（+20%）' in text
    assert '持有≥10个交易日' in text
    assert '-5%' not in text


# ---------- position_sizer ----------

def test_position_sizer_fallback_stop_uses_config(tmp_path, monkeypatch):
    monkeypatch.setattr(position_sizer, 'cfg_get', _sim_config_stub())
    orders = [{'代码': '600000', '价格': 10.0}]
    out = position_sizer.calculate_stop_loss(None, orders)
    assert out[0]['止损价'] == 9.20
    assert out[0]['止损方式'] == '固定-8%'
    assert out[0]['止损幅度'] == '-8.0%'


def test_position_sizer_short_history_uses_config_fallback(monkeypatch):
    monkeypatch.setattr(position_sizer, 'cfg_get', _sim_config_stub())
    hist = pd.DataFrame([
        {'代码': '600000', '日期': pd.Timestamp('2026-08-20'),
         '最高': 10.5, '最低': 9.5, '收盘': 10.0},
        {'代码': '600000', '日期': pd.Timestamp('2026-08-21'),
         '最高': 10.4, '最低': 9.6, '收盘': 10.2},
    ])
    orders = [{'代码': '600000', '价格': 10.2}]
    out = position_sizer.calculate_stop_loss(hist, orders, atr_period=14)
    assert out[0]['止损方式'] == '固定-8%'
    assert out[0]['止损价'] == round(10.2 * 0.92, 2)


# ---------- strategy ----------

def test_strategy_fallback_stop_uses_config(monkeypatch):
    monkeypatch.setattr(strategy, 'cfg_get', _sim_config_stub())
    assert strategy._fallback_stop_loss(10.0) == 9.20


def test_strategy_report_text_uses_config(monkeypatch):
    monkeypatch.setattr(strategy, 'cfg_get', _sim_config_stub())
    df = pd.DataFrame([{
        '代码': '600000', '名称': '测试', '板块': '金融', '最新价': 10.0,
        '涨跌幅': 1.0, 'MA5': 9.8, 'MA20': 9.5, 'RSI': 55.0, '量比': 1.5,
        '流通市值_亿': 100.0, '综合评分': 90, '风险': '中', '选入理由': '测试',
    }])
    out = strategy.render_markdown(
        df, target_date='2026-08-21',
        adaptive={'rsi_low': 30, 'rsi_high': 70}, regime='震荡')
    assert '止损参考：-8%' in out
    assert '小资金模式' in out
    assert '最多 3 只，单票上限约 1/3' in out
    assert '止损参考：-5%' not in out

    summary = strategy.generate_summary(df)
    assert '止损设MA20或-8%' in summary
    assert '止损设MA20或-5%' not in summary
