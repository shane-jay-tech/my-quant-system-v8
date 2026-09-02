"""v8.7 深挖审查修复回归（2026-09-03，全部离线）。

锁定本轮深入审查后修的决策核心 bug（均只改变错误行为/防数据破坏，不改策略公式）：
- strategy_feedback：短窗口不许冒充 3/5/10 日；无平仓时 apply=False 防重置风控
- walk_forward：测试集带训练期预热
- portfolio_manager：sim 持仓并入排除集合；同日不重复 +1 持有日数
- etf_gate：按 mtime 选最新可解析评估源
- strategy_arena：策略专属权益曲线优先，共用曲线标记 proxy
- check_trading_day：周一歧义分支走交易日历
- evolve_daily_light：启发式门槛 0.20，0.05 级噪音候选必须拒绝
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import strategy_feedback as sf  # noqa: E402
import portfolio_manager  # noqa: E402
import strategy_arena  # noqa: E402
import check_trading_day  # noqa: E402
import evolve_daily_light as edl  # noqa: E402
import etf_gate  # noqa: E402


def _hist(dates, code='600000', closes=None):
    closes = closes or [10] * len(dates)
    return pd.DataFrame({'代码': [code] * len(dates), '日期': pd.to_datetime(dates), '收盘': closes})


# ------------------------------------------------------------
# strategy_feedback
# ------------------------------------------------------------
def test_forward_returns_require_full_horizon():
    hist = _hist(['2026-08-10', '2026-08-11', '2026-08-12'], closes=[10, 11, 12])
    r = sf.calc_forward_returns('2026-08-10', '600000', hist)
    assert r['ret_3d'] is None  # 只有 2 天未来数据，旧版会拿 2 日收益冒充 3/5/10 日
    assert r['ret_5d'] is None and r['ret_10d'] is None

    hist5 = _hist(['2026-08-10', '2026-08-11', '2026-08-12', '2026-08-13', '2026-08-14', '2026-08-15'],
                  closes=[10, 10.5, 11, 11.5, 12, 12.5])
    r5 = sf.calc_forward_returns('2026-08-10', '600000', hist5)
    assert r5['ret_3d'] == 15.0  # 3 日后 11.5/10-1
    assert r5['ret_5d'] == 25.0
    assert r5['ret_10d'] is None


def test_no_closed_trades_marks_no_apply(monkeypatch, tmp_path):
    real = pd.DataFrame({'方向': ['买入', '买入'], '代码': ['600000', '600001'],
                         '成交额': [1000.0, 1000.0]})
    monkeypatch.setattr(sf, 'load_real_trades', lambda: (real, 2))
    adj = sf.analyze_risk_adjustments()
    assert adj['trade_source'] == 'real'
    assert adj.get('apply') is False  # 旧版返回后 main 仍会把默认风控写回 risk_config.json


def test_no_data_at_all_marks_no_apply(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, 'load_real_trades', lambda: (pd.DataFrame(), 0))
    monkeypatch.setattr(sf, 'SIM_DIR', str(tmp_path))  # trade_history.csv 不存在
    adj = sf.analyze_risk_adjustments(cold_start_data=None)
    assert adj['data_source'] == '无'
    assert adj.get('apply') is False


def test_forward_returns_file_drops_incomplete_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, 'DATA_DIR', str(tmp_path))
    analysis_df = pd.DataFrame({
        '选股日期': ['2026-08-17', '2026-08-17'],
        '策略': ['trend', 'meanrev'],
        '3日收益': [1.0, 2.0],
        '5日收益': [None, None],  # 尚未攒满 5 日
        '10日收益': [None, None],
        '代码': ['600000', '600001'],
    })
    sf.generate_forward_returns_file(analysis_df)
    out = pd.read_csv(tmp_path / 'strategy_forward_returns.csv', encoding='utf-8-sig')
    assert len(out) == 0  # NaN 组不得进入策略权重（否则被当成 0 胜率）


# ------------------------------------------------------------
# walk_forward
# ------------------------------------------------------------
def test_walk_forward_test_hist_includes_warmup(monkeypatch):
    import walk_forward as wf
    n = wf.TRAIN_DAYS + wf.TEST_DAYS + 5
    dates = pd.date_range('2026-01-01', periods=n)
    hist = pd.DataFrame({
        '代码': ['600000'] * n, '日期': list(dates), '收盘': list(range(45, 45 + n)),
    })
    captured = {}

    def fake_run(hist_df, today_df, index_df, params, test_dates):
        captured['n_rows'] = len(hist_df)
        captured['min_date'] = hist_df['日期'].min()
        captured['test_start'] = min(test_dates)
        return 0.01, 3

    monkeypatch.setattr(wf, 'run_backtest_window', fake_run)
    wf.walk_forward(hist, None, None)
    # 第二次调用是测试集验证：其历史必须包含测试期之前的数据（预热）
    assert captured['min_date'] < captured['test_start']


# ------------------------------------------------------------
# portfolio_manager
# ------------------------------------------------------------
def test_get_held_codes_includes_sim_account(tmp_path, monkeypatch):
    (tmp_path / 'sim_results').mkdir()
    (tmp_path / 'portfolio_state.json').write_text(
        json.dumps({'as_of': '2026-09-03', 'positions': [{'代码': '000001'}], 'history': []}),
        encoding='utf-8')
    (tmp_path / 'sim_results' / 'account_state.json').write_text(
        json.dumps({'positions': [{'code': '600000'}]}), encoding='utf-8')
    monkeypatch.setattr(portfolio_manager, 'STATE_FILE', str(tmp_path / 'portfolio_state.json'))
    monkeypatch.setattr(portfolio_manager, 'BASE_DIR', str(tmp_path))
    codes = portfolio_manager.get_held_codes()
    assert codes == {'000001', '600000'}  # 两套真相源合并，防止实际持仓被重复推荐


def test_increment_holding_days_idempotent_same_day(tmp_path, monkeypatch):
    state_file = tmp_path / 'portfolio_state.json'
    state_file.write_text(json.dumps({'as_of': '2000-01-01',  # 非今天：第一次调用应 +1 并更新 as_of
                                      'positions': [{'代码': '000001', '持有日数': 5}],
                                      'history': []}), encoding='utf-8')
    monkeypatch.setattr(portfolio_manager, 'STATE_FILE', str(state_file))
    assert portfolio_manager.increment_holding_days() == 1
    assert portfolio_manager.increment_holding_days() == 0  # 同日重跑不再 +1
    loaded = json.loads(state_file.read_text(encoding='utf-8'))
    assert loaded['positions'][0]['持有日数'] == 6


# ------------------------------------------------------------
# etf_gate / strategy_arena / check_trading_day / evolve
# ------------------------------------------------------------
def test_etf_gate_prefers_newest_source(tmp_path):
    (tmp_path / 'results').mkdir()
    (tmp_path / 'reports').mkdir()
    old = tmp_path / 'results' / 'honest_evaluation.md'
    new = tmp_path / 'reports' / 'benchmark_20260903.md'
    old.write_text('# eval\n\n**超额收益**: -1.00%\n', encoding='utf-8')
    new.write_text('# benchmark\n\n**超额收益**: +0.50%\n', encoding='utf-8')
    old_time = 1_700_000_000
    new_time = 1_800_000_000
    os.utime(old, (old_time, old_time))
    os.utime(new, (new_time, new_time))
    r = etf_gate.evaluate_etf_gate(base_dir=str(tmp_path))
    assert r.excess_pct == 0.50
    assert 'benchmark_20260903.md' in r.source


def test_arena_uses_own_equity_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy_arena, 'SIM_DIR', str(tmp_path))
    shared = pd.DataFrame({'总权益': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    own = pd.DataFrame({'总权益': [100, 110, 120, 130, 140, 150, 160, 170, 180, 190]})
    shared.to_csv(tmp_path / 'equity_curve.csv', index=False, encoding='utf-8-sig')
    own.to_csv(tmp_path / 'arena_base_equity.csv', index=False, encoding='utf-8-sig')
    own_metrics = strategy_arena.evaluate_strategy('base')
    shared_metrics = strategy_arena.evaluate_strategy('mut_1')
    assert own_metrics['proxy'] is False and own_metrics['return'] > 0.5
    assert shared_metrics['proxy'] is True


def test_arena_skips_elimination_when_all_proxy(monkeypatch, tmp_path):
    monkeypatch.setattr(strategy_arena, 'save_arena_state', lambda state: None)
    state = {'generation': 1, 'strategies': [{'id': 'base', 'name': '基准', 'params': {}, 'capital': 1000},
                                             {'id': 'mut_1', 'name': '变异1', 'params': {}, 'capital': 1000}]}
    monkeypatch.setattr(strategy_arena, 'evaluate_strategy',
                        lambda sid, lookback_days=30: {'score': 0.5, 'return': 0.1, 'sharpe': 1.0,
                                                       'max_dd': 0.1, 'proxy': True})
    out = strategy_arena.run_evaluation(state)
    assert out['generation'] == 1  # 全代理数据不得淘汰/变异
    assert len(out['strategies']) == 2
    assert out.get('proxy_only') is True


def test_trading_day_monday_holiday_uses_calendar(monkeypatch):
    fields = ['上证指数'] + ['3000'] * 7 + ['100000000'] + ['0'] * 21 + ['2026-01-02', '15:00:00', '00']
    payload = ','.join(fields)

    def fake_get(url, headers=None, timeout=None):
        class R:
            status_code = 200
            encoding = ''
            text = f'var hq_str_sh000001="{payload}";'
        return R()
    monkeypatch.setattr('utils.trading_calendar.is_trading_day_by_calendar', lambda day, data_dir: False)
    ok, reason = check_trading_day.is_trading_day(date(2026, 1, 5), request_get=fake_get)  # 周一
    assert ok is False and '节假日' in reason

    monkeypatch.setattr('utils.trading_calendar.is_trading_day_by_calendar', lambda day, data_dir: True)
    ok2, _ = check_trading_day.is_trading_day(date(2026, 1, 5), request_get=fake_get)
    assert ok2 is True


def test_evolve_threshold_rejects_noise_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(edl, 'STATE_FILE', str(tmp_path / 's.json'))
    monkeypatch.setattr(edl, 'DRY_RUN_ONLY', True)
    state = edl.load_state()
    noise = {'param': 'RSI_LOW', 'old': 30, 'new': 29, 'estimated_improvement': 0.05}
    ok, reason = edl.apply_adjustment(noise, state)
    assert ok is False and 'threshold' in reason
    strong = {'param': 'RSI_LOW', 'old': 30, 'new': 29, 'estimated_improvement': 0.25}
    ok2, reason2 = edl.apply_adjustment(strong, state)
    assert ok2 is True and 'dry-run' in reason2