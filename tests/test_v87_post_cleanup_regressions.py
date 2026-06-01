# -*- coding: utf-8 -*-
"""v8.7+ 第二轮清理回归测试：覆盖 A1/A2/A3/A4 四类已修 bug。"""
import os
import sys
import json
from datetime import datetime, date

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A2: utils.calendar.count_trading_days — 交易日计数
# ============================================================
def test_count_trading_days_inclusive_same_day(tmp_path):
    from utils.calendar import count_trading_days
    # 同一天闭区间应为 1（无本地数据时 fallback 到 weekday）
    assert count_trading_days('2026-05-25', '2026-05-25', data_dir=str(tmp_path)) == 1  # 周一


def test_count_trading_days_skips_weekend(tmp_path):
    from utils.calendar import count_trading_days
    # 2026-05-22(周五) → 2026-05-25(周一) = 2 交易日（周末跳过）
    n = count_trading_days('2026-05-22', '2026-05-25', data_dir=str(tmp_path))
    assert n == 2


def test_count_trading_days_uses_local_files_when_present(tmp_path):
    from utils.calendar import count_trading_days
    # 区间 [5/25, 5/27] 完全被本地覆盖 → 严格按本地交易日计数（只 5/25 + 5/27）
    (tmp_path / 'stock_20260525.csv').write_text('x', encoding='utf-8')  # 周一
    (tmp_path / 'stock_20260527.csv').write_text('x', encoding='utf-8')  # 周三
    n = count_trading_days('2026-05-25', '2026-05-27', data_dir=str(tmp_path))
    assert n == 2


def test_count_trading_days_invalid_returns_zero(tmp_path):
    from utils.calendar import count_trading_days
    assert count_trading_days('2026-05-25', '2026-05-20', data_dir=str(tmp_path)) == 0
    assert count_trading_days(None, '2026-05-25', data_dir=str(tmp_path)) == 0


# ============================================================
# A1: sim_trade full-mode 非交易日 dict-as-price 不再 TypeError
# ============================================================
def test_sim_trade_full_non_trading_day_uses_price_field(tmp_path, monkeypatch):
    """full 模式非交易日分支应 prices[code]['price']，不再把整 dict 当 price。"""
    import sim_trade

    sim_dir = tmp_path / 'sim_results'
    data_dir = tmp_path / 'data'
    sim_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(sim_trade, 'SIM_DIR', str(sim_dir))
    monkeypatch.setattr(sim_trade, 'DATA_DIR', str(data_dir))
    monkeypatch.setattr(sim_trade, 'STATE_FILE', str(sim_dir / 'account_state.json'))
    monkeypatch.setattr(sim_trade, 'EQUITY_FILE', str(sim_dir / 'equity_curve.csv'))
    monkeypatch.setattr(sim_trade, 'INITIAL_CAPITAL', 1200)

    # 桩：非交易日
    monkeypatch.setattr(sim_trade, 'is_today_trading_day', lambda: False)
    # 桩：账户有 1 笔持仓
    fake_state = {
        'starting_capital': 1200, 'initial_capital': 1200, 'cash': 200,
        'positions': [{
            'code': '600028', 'name': '中国石化',
            'entry_price': 5.0, 'shares': 100, 'entry_date': '2026-05-20',
            'stop_loss': 4.6, 'take_profit': 6.0,
            'current_price': 5.0,
        }],
        'equity': 700, 'realized_pnl': 0, 'total_pnl': 0, 'total_trades': 0,
        'total_commission': 0, 'total_stamp_tax': 0, 'total_trade_volume': 0,
    }
    monkeypatch.setattr(sim_trade, 'init_account', lambda: dict(fake_state))
    # load_price_data 返回 dict-of-dict 真实结构
    monkeypatch.setattr(sim_trade, 'load_price_data', lambda: {
        '600028': {'price': 5.5, 'name': '中国石化', 'change_pct': 1.0}
    })
    saved = {}
    monkeypatch.setattr(sim_trade, 'save_state', lambda s: saved.update(s))
    # SIM_MODE 是 main 里 from core.config import 的，通过 core.config 注入
    import core.config as _cfg
    monkeypatch.setattr(_cfg, 'SIM_MODE', 'full', raising=False)

    rc = sim_trade.main()
    assert rc == 0
    pos = saved['positions'][0]
    # 5.5 是数字，不是 dict
    assert pos['current_price'] == 5.5
    assert pos['unrealized_pnl'] == round((5.5 - 5.0) * 100, 2)
    assert pos['unrealized_pnl_pct'] == round((5.5 / 5.0 - 1) * 100, 2)


# ============================================================
# A3: strategy_feedback FIFO 配对 + 真实交易 metrics
# ============================================================
def test_pair_real_trades_fifo_one_round_trip():
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': '中国石化',
         '方向': '买入', '价格': 5.00, '数量': 100, '成交额': 500.0, '手续费': 5.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': '中国石化',
         '方向': '卖出', '价格': 5.50, '数量': 100, '成交额': 550.0, '手续费': 5.5},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 1
    t = closed[0]
    assert t['code'] == '600028'
    assert t['entry_price'] == 5.00
    assert t['exit_price'] == 5.50
    assert t['shares'] == 100
    # Round 2: pnl_pct 改为净 PnL（含费）；毛 PnL 看 pnl_pct_gross
    assert abs(t['pnl_pct_gross'] - 10.0) < 0.01


def test_pair_real_trades_fifo_partial_sell():
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': '中国石化',
         '方向': '买入', '价格': 5.0, '数量': 200, '成交额': 1000.0, '手续费': 5.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': '中国石化',
         '方向': '卖出', '价格': 5.5, '数量': 100, '成交额': 550.0, '手续费': 5.5},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 1
    assert closed[0]['shares'] == 100  # 只配对了一半


def test_pair_real_trades_fifo_two_buys_one_sell():
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
        {'日期': '2026-05-21', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 6.0, '数量': 100, '成交额': 600.0, '手续费': 5.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 5.5, '数量': 150, '成交额': 825.0, '手续费': 5.5},
    ])
    closed = sf.pair_real_trades_fifo(df)
    # FIFO：先卖 100@5（毛 +10%），再卖 50 来自 6.0 那批（毛 -8.33%）
    assert len(closed) == 2
    assert abs(closed[0]['pnl_pct_gross'] - 10.0) < 0.01
    assert closed[1]['pnl_pct_gross'] < 0


def test_strategy_feedback_real_closed_metrics(tmp_path, monkeypatch):
    """real_count > 0 且有平仓时，metrics 应含真实胜率/盈亏比，不是占位字符串。"""
    import strategy_feedback as sf

    monkeypatch.setattr(sf, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(sf, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(sf, 'SIM_DIR', str(tmp_path / 'sim_results'))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sim_results').mkdir()

    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 5.5, '数量': 100, '成交额': 550.0, '手续费': 5.5},
    ])
    df.to_csv(tmp_path / 'real_trades.csv', index=False)

    adj = sf.analyze_risk_adjustments(cold_start_data=None)
    assert adj['trade_source'] == 'real'
    assert adj['metrics']['已平仓'] == 1
    # 不再是 placeholder
    assert adj['metrics']['胜率'] != '待积累卖出记录'
    assert adj['metrics']['胜率'] != '待完善盈亏计算'
    assert '100.0%' in adj['metrics']['胜率']


def test_strategy_feedback_real_no_closed_yet(tmp_path, monkeypatch):
    """只买没卖：metrics 显示 0 平仓 + '待积累卖出记录'。"""
    import strategy_feedback as sf

    monkeypatch.setattr(sf, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(sf, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(sf, 'SIM_DIR', str(tmp_path / 'sim_results'))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sim_results').mkdir()

    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
    ])
    df.to_csv(tmp_path / 'real_trades.csv', index=False)

    adj = sf.analyze_risk_adjustments(cold_start_data=None)
    assert adj['metrics']['已平仓'] == 0
    assert adj['metrics']['胜率'] == '待积累卖出记录'


# ============================================================
# A4: pipeline 顺序 — exit_advisor 必须排在 position_sizing 之前
# ============================================================
def test_pipeline_exit_advisor_before_position_sizing():
    from core.pipeline import PIPELINE_STEPS
    keys = list(PIPELINE_STEPS.keys())
    assert 'exit_advisor' in keys
    assert 'position_sizing' in keys
    assert keys.index('exit_advisor') < keys.index('position_sizing'), \
        f"exit_advisor 必须在 position_sizing 之前；当前顺序: {keys}"


def test_pipeline_exit_advisor_only_once():
    """避免重复注册（旧位置漏删）。"""
    from core.pipeline import PIPELINE_STEPS
    keys = list(PIPELINE_STEPS.keys())
    assert keys.count('exit_advisor') == 1


# ============================================================
# Round 2 修复回归测试 — M1/M2/M3/M4/M5/M6/M7/M8/M9
# ============================================================
def test_count_trading_days_partial_coverage(tmp_path):
    """M1: entry_date 早于本地 stock_*.csv 最旧文件时不丢日期。"""
    from utils.calendar import count_trading_days
    # 本地只有 2026-05-25(周一) ~ 2026-05-29(周五) 5 个工作日
    for d in ['20260525', '20260526', '20260527', '20260528', '20260529']:
        (tmp_path / f'stock_{d}.csv').write_text('x', encoding='utf-8')
    # 区间从 5/18 开始（周一），早于 local_min 5/25：覆盖前段必须 fallback weekday
    n = count_trading_days('2026-05-18', '2026-05-29', data_dir=str(tmp_path))
    # 5/18~5/22 (Mon-Fri) = 5 个 weekday；5/25~5/29 = 5 个本地交易日；合计 10
    assert n == 10


def test_pair_real_trades_fifo_buy_fee_not_double_counted():
    """M2: 一批 200 股的买入手续费 10 元，分两次卖 100+100，总买入费应只摊 10 元。"""
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 200, '成交额': 1000.0, '手续费': 10.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
        {'日期': '2026-05-23', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 2
    # 平价进出：毛 PnL = 0；扣 100 股摊销的买入费(10*100/200=5) + 卖出费 5 = -10
    assert abs(closed[0]['pnl_amount'] - (-10.0)) < 1e-6
    assert abs(closed[1]['pnl_amount'] - (-10.0)) < 1e-6
    # 总扣费正好 = 1 笔买入费 + 2 笔卖出费 = 10 + 5 + 5 = 20
    assert abs(sum(t['pnl_amount'] for t in closed) - (-20.0)) < 1e-6


def test_pair_real_trades_fifo_pnl_pct_net_of_fees():
    """M3: 1200元小资金 + 5元手续费下限：毛 +0.5% 实际亏损，pnl_pct 应反映净。"""
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 6.0, '数量': 100, '成交额': 600.0, '手续费': 5.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 6.03, '数量': 100, '成交额': 603.0, '手续费': 5.0},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 1
    t = closed[0]
    # 毛 +0.5%
    assert abs(t['pnl_pct_gross'] - 0.5) < 0.05
    # 净 = (3 - 5 - 5) / (600 + 5) = -7/605 ≈ -1.16%
    assert t['pnl_pct'] < 0
    assert abs(t['pnl_pct'] - (-7.0 / 605.0 * 100)) < 0.05


def test_pair_real_trades_fifo_nan_fee_safe():
    """M4: 手续费列为 NaN 不应污染 pnl_amount。"""
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': float('nan')},
        {'日期': '2026-05-22', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 5.5, '数量': 100, '成交额': 550.0, '手续费': float('nan')},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 1
    t = closed[0]
    # NaN fee 退化为 0；50 元毛 PnL 不应变 NaN
    assert t['pnl_amount'] == t['pnl_amount']  # not NaN
    assert abs(t['pnl_amount'] - 50.0) < 1e-6


def test_pair_real_trades_fifo_same_day_buy_before_sell():
    """M5: 同日买卖，CSV 顺序错乱时也要 买入 → 卖出 排序。"""
    import strategy_feedback as sf
    # CSV 中卖出行写在买入行前面（极端模拟）
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 5.5, '数量': 100, '成交额': 550.0, '手续费': 5.0},
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 1  # 没排序的话买入会被忽略，闭合数=0


def test_position_sizer_only_uses_today_exit_signals(tmp_path, monkeypatch):
    """M6: position_sizer 不应静默使用昨天的 exit_advisor 文件。"""
    import position_sizer
    monkeypatch.setattr(position_sizer, 'BASE_DIR', str(tmp_path))
    results_dir = tmp_path / 'results'
    results_dir.mkdir()
    # 只有昨天的文件（从今天往回 1 天）
    yesterday = (datetime.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
    (results_dir / f'exit_advisor_{yesterday}.json').write_text(
        '[{"code":"600028","action":"sell","reason":"stale"}]', encoding='utf-8')
    sigs = position_sizer._load_today_exit_signals()
    assert sigs == [], '今日文件不存在时不应回退用昨天的文件'


def test_bark_sender_only_uses_today_exit_advisor(tmp_path, monkeypatch):
    """M6: bark_sender 同样不应静默用昨天的 .md。"""
    from bark_sender import parsers as p
    monkeypatch.setattr(p, 'RESULTS_DIR', str(tmp_path))
    yesterday = (datetime.now() - pd.Timedelta(days=1)).strftime('%Y%m%d')
    (tmp_path / f'exit_advisor_{yesterday}.md').write_text(
        '## 🚨 需要操作\n| 600028 | A | 5.0 | 4.5 | -10% | sell | 卖出 | stale |',
        encoding='utf-8')
    sells = p._parse_exit_advisor_sells()
    assert sells == []


def test_alert_only_reads_config(tmp_path, monkeypatch):
    """M7: alert_only 应可由 config 关闭，不再硬编码 True。"""
    import strategy_feedback as sf
    monkeypatch.setattr(sf, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(sf, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(sf, 'SIM_DIR', str(tmp_path / 'sim_results'))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sim_results').mkdir()
    # 桩 cfg_get：返回 False 关闭 alert_only
    monkeypatch.setattr(sf, 'cfg_get',
                        lambda key, default=None: False if key == 'feedback.alert_only' else default)
    adj = sf.analyze_risk_adjustments(cold_start_data=None)
    assert adj['alert_only'] is False


def test_exit_advisor_load_real_positions_fifo_avg(tmp_path, monkeypatch):
    """M8: 多次买入后 entry_price 应是加权均价，entry_date 应是最早未平仓日。"""
    import exit_advisor
    monkeypatch.setattr(exit_advisor, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(exit_advisor, 'STOP_LOSS_PCT', -0.08)
    monkeypatch.setattr(exit_advisor, 'TAKE_PROFIT_PCT', 0.20)
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
        {'日期': '2026-05-21', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 6.0, '数量': 100, '成交额': 600.0, '手续费': 5.0},
    ])
    df.to_csv(tmp_path / 'real_trades.csv', index=False)
    pos_list = exit_advisor.load_real_positions()
    assert len(pos_list) == 1
    pos = pos_list[0]
    assert abs(pos['entry_price'] - 5.5) < 1e-6  # (5*100 + 6*100)/200
    assert pos['entry_date'] == '2026-05-20'   # 最早未平仓买入日
    assert pos['shares'] == 200


def test_sim_trade_full_non_trading_day_updates_equity(tmp_path, monkeypatch):
    """M9: full 模式非交易日也应调 update_equity_curve（和 lite 对称）。"""
    import sim_trade
    sim_dir = tmp_path / 'sim_results'
    data_dir = tmp_path / 'data'
    sim_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(sim_trade, 'SIM_DIR', str(sim_dir))
    monkeypatch.setattr(sim_trade, 'DATA_DIR', str(data_dir))
    monkeypatch.setattr(sim_trade, 'STATE_FILE', str(sim_dir / 'account_state.json'))
    monkeypatch.setattr(sim_trade, 'INITIAL_CAPITAL', 1200)
    monkeypatch.setattr(sim_trade, 'is_today_trading_day', lambda: False)
    fake_state = {
        'starting_capital': 1200, 'initial_capital': 1200, 'cash': 200,
        'positions': [{'code': '600028', 'name': 'A', 'entry_price': 5.0,
                       'shares': 100, 'entry_date': '2026-05-20',
                       'stop_loss': 4.6, 'take_profit': 6.0}],
        'equity': 700, 'realized_pnl': 0,
        'total_commission': 0, 'total_stamp_tax': 0, 'total_trade_volume': 0,
    }
    monkeypatch.setattr(sim_trade, 'init_account', lambda: dict(fake_state))
    monkeypatch.setattr(sim_trade, 'load_price_data',
                        lambda: {'600028': {'price': 5.5, 'name': 'A', 'change_pct': 1.0}})
    monkeypatch.setattr(sim_trade, 'save_state', lambda s: None)
    called = {'n': 0}
    monkeypatch.setattr(sim_trade, 'update_equity_curve',
                        lambda s: called.update(n=called['n'] + 1) or 750.0)
    import core.config as _cfg
    monkeypatch.setattr(_cfg, 'SIM_MODE', 'full', raising=False)
    rc = sim_trade.main()
    assert rc == 0
    assert called['n'] == 1, 'full 模式非交易日应调 update_equity_curve 一次'


# ============================================================
# Round 3 修复回归测试 — R1 (M1 区间误扩) / R2 (M5 排序稳定) / R3 (M7 bool 字符串)
# ============================================================
def test_count_trading_days_query_entirely_left_of_local(tmp_path):
    """R1: 查询区间完全在 local 左侧时，前段不应越过查询终点。

    DeepSeek 找到的 bug：query [4/1, 4/5] + local [4/10..]，前段 _weekday_count(4/1, 4/9)
    会把 4/6~4/9 也算进来 → 偏大。修后应仅算 [4/1, 4/5]。
    """
    from utils.calendar import count_trading_days
    (tmp_path / 'stock_20260410.csv').write_text('x', encoding='utf-8')  # 周五
    # 4/1 周三 ~ 4/5 周日：4/1 4/2 4/3 是工作日 = 3
    n = count_trading_days('2026-04-01', '2026-04-05', data_dir=str(tmp_path))
    assert n == 3, f'前段不应越过 e=4/5 算到 4/9；得到 {n}'


def test_count_trading_days_query_entirely_right_of_local(tmp_path):
    """R1 对称：查询区间完全在 local 右侧时，后段不应早于查询起点。"""
    from utils.calendar import count_trading_days
    (tmp_path / 'stock_20260401.csv').write_text('x', encoding='utf-8')  # 周三
    # 4/13 周一 ~ 4/17 周五：5 个工作日
    n = count_trading_days('2026-04-13', '2026-04-17', data_dir=str(tmp_path))
    assert n == 5, f'后段不应从 4/2 算（应 ≥4/13）；得到 {n}'


def test_pair_real_trades_fifo_stable_sort_order():
    """R2: 同日同向多笔输入，mergesort 保证按输入顺序入队。"""
    import strategy_feedback as sf
    df = pd.DataFrame([
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 4.0, '数量': 100, '成交额': 400.0, '手续费': 5.0},
        {'日期': '2026-05-20', '代码': '600028', '名称': 'A', '方向': '买入',
         '价格': 5.0, '数量': 100, '成交额': 500.0, '手续费': 5.0},
        {'日期': '2026-05-22', '代码': '600028', '名称': 'A', '方向': '卖出',
         '价格': 6.0, '数量': 100, '成交额': 600.0, '手续费': 5.0},
    ])
    closed = sf.pair_real_trades_fifo(df)
    assert len(closed) == 1
    # 第一买入 4.0 应优先卖出（不是 5.0）
    assert closed[0]['entry_price'] == 4.0


def test_alert_only_string_false_parses_correctly(tmp_path, monkeypatch):
    """R3: cfg 返回字符串 'False' 应被识别为 False（之前 bool('False')=True 漏修）。"""
    import strategy_feedback as sf
    monkeypatch.setattr(sf, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(sf, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(sf, 'SIM_DIR', str(tmp_path / 'sim_results'))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sim_results').mkdir()
    monkeypatch.setattr(sf, 'cfg_get',
                        lambda key, default=None: 'False' if key == 'feedback.alert_only' else default)
    adj = sf.analyze_risk_adjustments(cold_start_data=None)
    assert adj['alert_only'] is False, '字符串 "False" 应该解析成 False'


def test_alert_only_string_true_variants(tmp_path, monkeypatch):
    """R3: 'true' / '1' / 'yes' 等都应识别为 True；其他字符串识别为 False。"""
    import strategy_feedback as sf
    monkeypatch.setattr(sf, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(sf, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(sf, 'SIM_DIR', str(tmp_path / 'sim_results'))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sim_results').mkdir()
    for raw, expected in [('true', True), ('1', True), ('YES', True),
                          ('on', True), ('0', False), ('no', False), ('', False)]:
        monkeypatch.setattr(sf, 'cfg_get',
                            lambda key, default=None, _r=raw: _r if key == 'feedback.alert_only' else default)
        adj = sf.analyze_risk_adjustments(cold_start_data=None)
        assert adj['alert_only'] is expected, f'cfg {raw!r} → expected {expected}, got {adj["alert_only"]}'


def test_sim_trade_full_non_trading_day_does_not_swallow_value_error(tmp_path, monkeypatch):
    """R4: full 非交易日 update_equity_curve 抛 ValueError 时不再静默吞。"""
    import sim_trade
    sim_dir = tmp_path / 'sim_results'
    data_dir = tmp_path / 'data'
    sim_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(sim_trade, 'SIM_DIR', str(sim_dir))
    monkeypatch.setattr(sim_trade, 'DATA_DIR', str(data_dir))
    monkeypatch.setattr(sim_trade, 'STATE_FILE', str(sim_dir / 'account_state.json'))
    monkeypatch.setattr(sim_trade, 'INITIAL_CAPITAL', 1200)
    monkeypatch.setattr(sim_trade, 'is_today_trading_day', lambda: False)
    fake_state = {
        'starting_capital': 1200, 'initial_capital': 1200, 'cash': 1200,
        'positions': [], 'equity': 1200, 'realized_pnl': 0,
        'total_commission': 0, 'total_stamp_tax': 0, 'total_trade_volume': 0,
    }
    monkeypatch.setattr(sim_trade, 'init_account', lambda: dict(fake_state))
    monkeypatch.setattr(sim_trade, 'load_price_data', lambda: {})
    monkeypatch.setattr(sim_trade, 'save_state', lambda s: None)

    def _bad_equity(s):
        raise ValueError('corrupt data')
    monkeypatch.setattr(sim_trade, 'update_equity_curve', _bad_equity)
    import core.config as _cfg
    monkeypatch.setattr(_cfg, 'SIM_MODE', 'full', raising=False)
    # ValueError 应抛出（不被静默吞），让上层 pipeline 看到
    with pytest.raises(ValueError):
        sim_trade.main()


# ============================================================
# A2 应用：exit_advisor.analyze_position 跨周末持仓天数应为交易日
# ============================================================
def test_exit_advisor_hold_days_skips_weekend(monkeypatch, tmp_path):
    """周五买、下周一查：日历日 3 天，但交易日应为 1。"""
    import exit_advisor

    monkeypatch.setattr(exit_advisor, 'DATA_DIR', str(tmp_path))

    # 桩 datetime.now() = 2026-05-25 周一
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 25, 10, 0, 0)
    monkeypatch.setattr(exit_advisor, 'datetime', FakeDT)

    pos = {
        'code': '600028', 'name': 'A',
        'entry_price': 5.0, 'entry_date': '2026-05-22',  # 周五
        'shares': 100,
    }
    prices = {'600028': {'price': 5.1, 'name': 'A', 'change_pct': 0}}
    result = exit_advisor.analyze_position(pos, prices, history_df=None,
                                           risk_config={'max_hold_days': 10})
    # 5/22 ~ 5/25 = 2 交易日 - 1 = 1（不应是日历的 3 天）
    assert result['hold_days'] == 1
