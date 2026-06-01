"""_self_check K-line freshness 交易日口径回归（2026-08-24 round 5）。

周一拿到上周五数据：日历差 3 天，交易日落差 1 天，不能再误报 FAIL。
"""
import sys
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import utils.calendar as calendar_mod
import _self_check


def test_friday_to_monday_is_one_trading_day_behind(monkeypatch):
    monkeypatch.setattr(calendar_mod, 'count_trading_days',
                        lambda latest, today, data_dir=None: 2)
    assert _self_check._trading_days_behind(
        date(2026, 8, 21), today=date(2026, 8, 24)) == 1


def test_same_day_is_zero_trading_days_behind(monkeypatch):
    monkeypatch.setattr(calendar_mod, 'count_trading_days',
                        lambda latest, today, data_dir=None: 1)
    assert _self_check._trading_days_behind(
        date(2026, 8, 24), today=date(2026, 8, 24)) == 0


def test_negative_count_clamps_to_zero(monkeypatch):
    monkeypatch.setattr(calendar_mod, 'count_trading_days',
                        lambda latest, today, data_dir=None: 0)
    assert _self_check._trading_days_behind(
        date(2026, 8, 24), today=date(2026, 8, 24)) == 0


def test_fallback_to_calendar_days_when_calendar_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('calendar unavailable')

    monkeypatch.setattr(calendar_mod, 'count_trading_days', boom)
    assert _self_check._trading_days_behind(
        date(2026, 8, 21), today=datetime(2026, 8, 24, 15, 0)) == 3


def test_data_dir_is_forwarded(monkeypatch, tmp_path):
    captured = {}

    def fake_count(latest, today, data_dir=None):
        captured['data_dir'] = data_dir
        return 2

    monkeypatch.setattr(calendar_mod, 'count_trading_days', fake_count)
    assert _self_check._trading_days_behind(
        date(2026, 8, 21), today=date(2026, 8, 24),
        data_dir=str(tmp_path)) == 1
    assert captured['data_dir'] == str(tmp_path)
