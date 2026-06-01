"""Alpha Gate 交易日口径回归测试（2026-08-24）。

锁定的行为：
1. check_trading_day 周一拿到上周五行情不再误判为长假。
2. Alpha Gate 非交易日不计数、不写状态；交易日确认后才计数。
3. core.pipeline.run_all 非交易日干净跳过（rc=0），不会把周末记成 FATAL。
4. 流水线先确认交易日再跑 Alpha Gate，且不再重复执行 check_trading_day 子进程。
"""
import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import check_trading_day
import alpha_gate
from core import pipeline


def _fake_sina_response(data_date, volume):
    class Resp:
        status_code = 200
        encoding = 'gbk'
        text = ''

    # 与真实新浪格式一致：名称在 index 0，成交量 index 8，日期 index 30
    fields = ['上证指数'] + ['0'] * 31
    fields[8] = str(volume)
    fields[30] = data_date
    resp = Resp()
    resp.text = 'var hq_str_sh000001="' + ','.join(fields) + '";'
    return resp


class _FakeETFResult:
    severity = 'severe'
    excess_pct = -2.0


# ---------- check_trading_day ----------

def test_weekend_returns_false_without_network_request():
    def boom(*a, **k):
        raise AssertionError('weekend must short-circuit before network')

    ok, reason = check_trading_day.is_trading_day(
        today=date(2026, 8, 22), request_get=boom)
    assert ok is False
    assert '周末' in reason


def test_monday_with_friday_quote_is_trading_day():
    ok, reason = check_trading_day.is_trading_day(
        today=date(2026, 8, 24),  # Monday
        request_get=lambda *a, **k: _fake_sina_response('2026-08-21', 123456),
    )
    assert ok is True
    assert '上一工作日' in reason


def test_tuesday_stale_friday_quote_is_not_trading_day():
    ok, reason = check_trading_day.is_trading_day(
        today=date(2026, 8, 25),  # Tuesday
        request_get=lambda *a, **k: _fake_sina_response('2026-08-21', 123456),
    )
    assert ok is False
    assert '长假' in reason


def test_network_failure_fails_open(monkeypatch):
    monkeypatch.setattr(check_trading_day.time, 'sleep', lambda s: None)

    def boom(*a, **k):
        raise ConnectionError('offline')

    ok, reason = check_trading_day.is_trading_day(
        today=date(2026, 8, 24), request_get=boom)
    assert ok is True
    assert '无法确认' in reason


# ---------- alpha_gate 非交易日不计数 ----------

def test_alpha_gate_non_trading_day_does_not_count(tmp_path, monkeypatch):
    state_dir = str(tmp_path)
    state_file = alpha_gate._state_file_path(state_dir)
    initial = alpha_gate._blank_state()
    alpha_gate._atomic_write_json(state_file, initial)

    monkeypatch.setattr(alpha_gate, 'evaluate_etf_gate', lambda: _FakeETFResult())

    r1 = alpha_gate.check_alpha_gate(
        state_dir=state_dir, is_trading_day_fn=lambda: (False, 'weekend'))
    r2 = alpha_gate.check_alpha_gate(
        state_dir=state_dir, is_trading_day_fn=lambda: (False, 'weekend'))

    assert r1.counted is False
    assert r1.severity == 'non_trading'
    assert r1.consecutive_severe_days == 0
    assert r2.consecutive_severe_days == 0
    saved = alpha_gate._load_state(state_dir)
    assert saved.get('last_counted_date') is None
    assert saved.get('history') == []


def test_alpha_gate_confirmed_trading_day_still_dedupes(tmp_path, monkeypatch):
    state_dir = str(tmp_path)
    state_file = alpha_gate._state_file_path(state_dir)
    alpha_gate._atomic_write_json(state_file, alpha_gate._blank_state())
    monkeypatch.setattr(alpha_gate, 'evaluate_etf_gate', lambda: _FakeETFResult())

    r1 = alpha_gate.check_alpha_gate(state_dir=state_dir, trading_day_ok=True)
    r2 = alpha_gate.check_alpha_gate(state_dir=state_dir, trading_day_ok=True)

    assert r1.counted is True
    assert r1.consecutive_severe_days == 1
    assert r2.consecutive_severe_days == 1  # 同一交易日只 +1
    saved = alpha_gate._load_state(state_dir)
    assert saved.get('last_counted_date') is not None


# ---------- core.pipeline 交易日闸门 ----------

def test_run_all_skips_cleanly_on_non_trading_day(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(pipeline, '_check_trading_day_inline', lambda: (False, 'weekend'))
    monkeypatch.setattr(pipeline, '_run_script',
                        lambda name, step, base_dir: calls.append(name) or 0)

    rc = pipeline.run_all(dry_run=False)

    assert rc == 0
    assert calls == []  # 非交易日一个业务步骤都不该跑
    assert '非交易日' in capsys.readouterr().out


def test_run_all_confirms_trading_day_before_alpha_gate_and_dedupes_step(monkeypatch):
    run_order = []
    precheck_kwargs = {}
    monkeypatch.setattr(pipeline, '_check_trading_day_inline',
                        lambda: (True, 'trading day'))
    monkeypatch.setattr(pipeline, '_run_script',
                        lambda name, step, base_dir: run_order.append(name) or 0)

    def fake_precheck(trading_day_ok=True):
        precheck_kwargs['trading_day_ok'] = trading_day_ok
        run_order.append('__alpha_gate__')
        return False, ''

    monkeypatch.setattr(pipeline, '_alpha_gate_precheck', fake_precheck)

    rc = pipeline.run_all(dry_run=False)

    assert rc == 0
    assert precheck_kwargs.get('trading_day_ok') is True
    assert run_order[0] == '__alpha_gate__'  # 交易日确认后才计数
    assert 'check_trading_day' not in run_order  # 内联检测后不再重复跑子进程
