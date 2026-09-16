# -*- coding: utf-8 -*-
"""stall_watchdog 纯函数单测（d914-70）。

覆盖 _is_holiday、_is_trading、weekdays_between 三个纯函数——
含内置节假日表命中、交易日历注入、跨年窗口、反向窗口边界。
零 DB、零网络、零生产文件触碰。
"""
from datetime import date
import stall_watchdog as sw


def test_is_holiday_builtin_hit():
    """内置节假日表命中：国庆 10-01。"""
    assert sw._is_holiday(date(2026, 10, 1)) is True


def test_is_holiday_builtin_miss():
    """非节假日：3 月 15 日不在表内 → False。"""
    assert sw._is_holiday(date(2026, 3, 15)) is False


def test_is_holiday_year_not_in_table():
    """年份不在内置表 → False（保守回退）。"""
    assert sw._is_holiday(date(2030, 10, 1)) is False


def test_is_trading_weekday_no_cal():
    """周三（工作日且非节假日）→ True。"""
    assert sw._is_trading(date(2026, 9, 16), None) is True


def test_is_trading_weekend_no_cal():
    """周六 → False。"""
    assert sw._is_trading(date(2026, 9, 19), None) is False


def test_is_trading_holiday_weekday_no_cal():
    """国庆期间的工作日 → False（节假日表覆盖）。"""
    assert sw._is_trading(date(2026, 10, 1), None) is False


def test_is_trading_with_cal_override():
    """提供交易日历时以真实日历为准。"""
    cal = {'2026-09-19', '2026-09-20'}  # 周末被标为交易日（调休）
    assert sw._is_trading(date(2026, 9, 19), cal) is True
    assert sw._is_trading(date(2026, 9, 16), cal) is False  # 不在日历 → 非交易日


def test_weekdays_between_normal():
    """周一到周五 → 5 个交易日。"""
    assert sw.weekdays_between(date(2026, 9, 14), date(2026, 9, 18)) == 4


def test_weekdays_between_cross_weekend():
    """周五到下周一 → 2 个交易日（跳过周末）。"""
    assert sw.weekdays_between(date(2026, 9, 18), date(2026, 9, 22)) == 2


def test_weekdays_between_reverse_returns_zero():
    """end < start → 0（反向窗口）。"""
    assert sw.weekdays_between(date(2026, 9, 18), date(2026, 9, 14)) == 0


def test_weekdays_between_same_day_returns_zero():
    """start == end → 0（开区间左端不含）。"""
    assert sw.weekdays_between(date(2026, 9, 14), date(2026, 9, 14)) == 0
