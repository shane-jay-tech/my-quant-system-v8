# -*- coding: utf-8 -*-
"""时敏 characterization 用例（d913b-36）：三组高危未覆盖项 × frozen_clock。

三组（源自 0913-0510-06-quant-midnight-timebomb 遗留清单）：
  A. newbie_protection   —— today±days cutoff 与访问/点击记录的午夜翻转；
  B. multi_strategy      —— 权重历史/对比报告按 datetime.now() 打日期（午夜换日）；
  C. position_sizer      —— regime hysteresis 的 date.today() + trading-day 文件名日历
   （含「23:59:59 与 00:00:01 结果不同」的真午夜翻转例）。

全部用 frozen_clock 冻结时钟 + tmp_path 隔离落盘，不改生产码、不做资金数值断言。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import newbie_protection  # noqa: E402
import multi_strategy  # noqa: E402
import position_sizer  # noqa: E402

CLOCK_BEFORE = '2026-09-13 23:59:59'
CLOCK_AFTER = '2026-09-14 00:00:01'


# ---------------------------------------------------------------- A 组：newbie_protection
def _seed_activity(tmp_path, visits):
    activity_file = tmp_path / 'user_activity.json'
    activity_file.write_text(json.dumps({'learning_center_visits': visits}), encoding='utf-8')
    return str(activity_file)


@pytest.mark.parametrize('clock,expected', [
    (CLOCK_BEFORE, 1),   # cutoff=09-06，边界日访问 2026-09-06 >= cutoff 计入
    (CLOCK_AFTER, 0),    # cutoff=09-07，同一访问被挤出 7 天窗口（午夜翻转）
])
def test_a1_learning_visits_cutoff_midnight_flip(tmp_path, frozen_clock, monkeypatch, clock, expected):
    frozen_clock(clock)
    monkeypatch.setattr(newbie_protection, 'ACTIVITY_FILE', _seed_activity(tmp_path, ['2026-09-06']))
    assert newbie_protection._count_recent_learning_visits(days=7) == expected


@pytest.mark.parametrize('clock,expected', [
    (CLOCK_BEFORE, 1),   # 日记 2026-09-07 00:00 >= cutoff 09-06 23:59:59 → 计入
    (CLOCK_AFTER, 0),    # cutoff 09-07 00:00:01 → 同一日记被挤出（秒级边界翻转）
])
def test_a2_recent_diaries_cutoff_midnight_flip(tmp_path, frozen_clock, monkeypatch, clock, expected):
    frozen_clock(clock)
    psych_dir = tmp_path / 'psychology'
    psych_dir.mkdir()
    (psych_dir / 'daily_20260907.md').write_text('日记', encoding='utf-8')
    monkeypatch.setattr(newbie_protection, 'PSYCH_DIR', str(psych_dir))
    assert newbie_protection._count_recent_diaries(days=7) == expected


@pytest.mark.parametrize('clock,expected_date', [
    (CLOCK_BEFORE, '2026-09-13'),
    (CLOCK_AFTER, '2026-09-14'),
])
def test_a3_record_learning_visit_stamps_frozen_date(tmp_path, frozen_clock, monkeypatch, clock, expected_date):
    frozen_clock(clock)
    monkeypatch.setattr(newbie_protection, 'ACTIVITY_FILE', _seed_activity(tmp_path, []))
    newbie_protection.record_learning_visit()
    activity = json.loads(Path(newbie_protection.ACTIVITY_FILE).read_text(encoding='utf-8'))
    assert activity['learning_center_visits'][-1] == expected_date


# ---------------------------------------------------------------- B 组：multi_strategy
def _strategies():
    return [SimpleNamespace(name='trend', weight=0.5),
            SimpleNamespace(name='meanrev', weight=0.5)]


@pytest.mark.parametrize('clock,expected_date', [
    (CLOCK_BEFORE, '2026-09-13'),
    (CLOCK_AFTER, '2026-09-14'),
])
def test_b1_weight_history_record_stamps_frozen_date(tmp_path, frozen_clock, monkeypatch, clock, expected_date):
    frozen_clock(clock)
    monkeypatch.setattr(multi_strategy, 'DATA_DIR', str(tmp_path))
    returns_csv = tmp_path / 'forward_returns.csv'
    returns_csv.write_text('策略,5日收益\ntrend,0.03\nmeanrev,-0.01\n', encoding='utf-8')
    multi_strategy.update_strategy_weights(_strategies(), str(returns_csv))
    history = json.loads((tmp_path / 'strategy_weights.json').read_text(encoding='utf-8'))
    assert history['records'][-1]['date'] == expected_date


def test_b2_weight_history_cross_midnight_two_dates(tmp_path, frozen_clock, monkeypatch):
    """同一进程内跨午夜两次更新：两条记录各自带当时钟日期（换日不串档）。"""
    monkeypatch.setattr(multi_strategy, "DATA_DIR", str(tmp_path))
    returns_csv = tmp_path / 'forward_returns.csv'
    returns_csv.write_text('策略,5日收益\ntrend,0.03\nmeanrev,-0.01\n', encoding='utf-8')
    frozen_clock(CLOCK_BEFORE)
    multi_strategy.update_strategy_weights(_strategies(), str(returns_csv))
    frozen_clock(CLOCK_AFTER)
    multi_strategy.update_strategy_weights(_strategies(), str(returns_csv))
    history = json.loads((tmp_path / 'strategy_weights.json').read_text(encoding='utf-8'))
    assert [record['date'] for record in history['records'][-2:]] == ['2026-09-13', '2026-09-14']


@pytest.mark.parametrize('clock,expected_date', [
    (CLOCK_BEFORE, '2026-09-13'),
    (CLOCK_AFTER, '2026-09-14'),
])
def test_b3_comparison_report_header_stamps_frozen_date(frozen_clock, clock, expected_date):
    frozen_clock(clock)
    report = multi_strategy.generate_comparison_report({}, pd.DataFrame(), [], '2026-09-12')
    assert f'生成时间：{expected_date}' in report


# ---------------------------------------------------------------- C 组：position_sizer
def _seed_regime_world(tmp_path, monkeypatch, *, first_seen, stock_dates):
    """构造 regime_state + stock_*.csv 交易日历（文件名即交易日历）。"""
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    state = {'last_regime': 'neutral', 'candidate_regime': 'weak_bull'}
    if first_seen:
        state['candidate_first_seen_date'] = first_seen
    (data_dir / 'regime_state.json').write_text(json.dumps(state), encoding='utf-8')
    for date_str in stock_dates:
        (data_dir / f'stock_{date_str}.csv').write_text('x\n', encoding='utf-8')
    monkeypatch.setattr(position_sizer, 'DATA_DIR', str(data_dir))
    return data_dir


@pytest.mark.parametrize('clock', [CLOCK_BEFORE, CLOCK_AFTER])
def test_c1_hysteresis_stays_without_trading_days(tmp_path, frozen_clock, monkeypatch, clock):
    """候选首见 09-11、窗口内零交易日 → 两时钟下都维持 last_regime（一致性）。"""
    frozen_clock(clock)
    _seed_regime_world(tmp_path, monkeypatch, first_seen='2026-09-11', stock_dates=[])
    assert position_sizer._apply_regime_hysteresis('weak_bull') == 'neutral'


@pytest.mark.parametrize('clock', [CLOCK_BEFORE, CLOCK_AFTER])
def test_c2_hysteresis_flips_with_enough_trading_days(tmp_path, frozen_clock, monkeypatch, clock):
    """窗口内 2 个交易日（09-12、09-13）≥ hysteresis-1=1 → 两时钟下都真切档。"""
    frozen_clock(clock)
    _seed_regime_world(tmp_path, monkeypatch, first_seen='2026-09-11',
                       stock_dates=['20260912', '20260913'])
    assert position_sizer._apply_regime_hysteresis('weak_bull') == 'weak_bull'


@pytest.mark.parametrize('clock,expected_first_seen', [
    (CLOCK_BEFORE, '2026-09-13'),
    (CLOCK_AFTER, '2026-09-14'),
])
def test_c3_first_launch_seeds_frozen_today(tmp_path, frozen_clock, monkeypatch, clock, expected_first_seen):
    """首次启动：candidate_first_seen_date 写入当时钟 today（午夜后换日）。"""
    frozen_clock(clock)
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    monkeypatch.setattr(position_sizer, 'DATA_DIR', str(data_dir))
    position_sizer._apply_regime_hysteresis('neutral')
    state = json.loads((data_dir / 'regime_state.json').read_text(encoding='utf-8'))
    assert state['candidate_first_seen_date'] == expected_first_seen


@pytest.mark.parametrize('clock,expected', [
    (CLOCK_BEFORE, 'neutral'),   # 09-13 23:59:59：窗口 (09-12, 09-13] 无交易日 → 不切
    (CLOCK_AFTER, 'weak_bull'),  # 09-14 00:00:01：文件 stock_20260914 落入窗口 → 第 1 天即达标切换
])
def test_c4_midnight_timebomb_future_dated_stock_file(tmp_path, frozen_clock, monkeypatch, clock, expected):
    """真·午夜翻转：after-midnight 新交易日文件使 hysteresis 立即达标。"""
    frozen_clock(clock)
    _seed_regime_world(tmp_path, monkeypatch, first_seen='2026-09-12',
                       stock_dates=['20260914'])
    assert position_sizer._apply_regime_hysteresis('weak_bull') == expected
