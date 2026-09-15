# -*- coding: utf-8 -*-
"""weekdays_between 边界用例（q914-33）——文件名取 stallwatchdog 连写，
匹配验收命令 ``pytest tests -q -k stallwatchdog``。

语义锚定（左开右闭）：start_exclusive 不含当日、end_inclusive 含当日；
周末不计；反向窗口 0。2026-09 基准周：9/11 周五、9/12 周六、9/14 周一。
零 DB、零网络。
"""
from datetime import date

import stall_watchdog as sw


def test_start_saturday_window_counts_only_weekday():
    """start 为周六（9/12）且被排除，(9/12, 9/14] 内仅周一 9/14 计 1。"""
    assert sw.weekdays_between(date(2026, 9, 12), date(2026, 9, 14)) == 1


def test_end_monday_included():
    """end 为周一（9/14）且为右闭端，必须计入：(9/11 周五, 9/14] = 1。"""
    assert sw.weekdays_between(date(2026, 9, 11), date(2026, 9, 14)) == 1


def test_start_monday_excluded():
    """start 为周一（9/14）被左开排除：(9/14, 9/15] = 1（仅周二）。"""
    assert sw.weekdays_between(date(2026, 9, 14), date(2026, 9, 15)) == 1


def test_start_equals_end_returns_zero():
    """start == end（空集）返回 0，不抛错。"""
    assert sw.weekdays_between(date(2026, 9, 14), date(2026, 9, 14)) == 0


def test_cross_month_boundary():
    """跨月窗口：(2026-08-31 周一, 2026-09-02 周三] = 2（9/1、9/2；8/31 左开不计）。"""
    assert sw.weekdays_between(date(2026, 8, 31), date(2026, 9, 2)) == 2
