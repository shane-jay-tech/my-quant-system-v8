"""q918-02：utils/trading_calendar.is_trading_day_by_calendar 边界 characterization（基线 #7）。

冻结现值契约：
- 纯集合成员判断（无周末硬编码）——周六/周日不在集合 → False；
- 集合外工作日 → False；集合内工作日 → True（正向路径一并冻结）；
- 日历不可用（get_trading_days → None）→ None（调用方走启发式兜底契约）；
- 字符串入参走 str(day)[:10] 分支。
零网络：get_trading_days 整体 monkeypatch，_refresh/akshare 永不触网。
"""

from __future__ import annotations

from datetime import date

import utils.trading_calendar as tc

# 2026-09-19=周六、09-20=周日、09-21=周一、09-22=周二
FIXED_DAYS = {"2026-09-21", "2026-09-23"}


def _patch_days(monkeypatch):
    monkeypatch.setattr(tc, "get_trading_days", lambda data_dir: set(FIXED_DAYS))


def test_saturday_not_in_set_returns_false(monkeypatch):
    _patch_days(monkeypatch)
    assert tc.is_trading_day_by_calendar(date(2026, 9, 19), "d") is False


def test_sunday_not_in_set_returns_false(monkeypatch):
    _patch_days(monkeypatch)
    assert tc.is_trading_day_by_calendar(date(2026, 9, 20), "d") is False


def test_weekday_outside_set_returns_false(monkeypatch):
    """集合外工作日（周二不在日历）→ False——节假日经日历排除正是本模块动机。"""
    _patch_days(monkeypatch)
    assert tc.is_trading_day_by_calendar(date(2026, 9, 22), "d") is False


def test_weekday_inside_set_returns_true(monkeypatch):
    _patch_days(monkeypatch)
    assert tc.is_trading_day_by_calendar(date(2026, 9, 21), "d") is True


def test_calendar_unavailable_returns_none(monkeypatch):
    """启发式兜底契约：日历不可用 → None（不是 False，调用方按未知处理）。"""
    monkeypatch.setattr(tc, "get_trading_days", lambda data_dir: None)
    assert tc.is_trading_day_by_calendar(date(2026, 9, 21), "d") is None


def test_string_input_uses_first_ten_chars(monkeypatch):
    """非 date 入参走 str(day)[:10] 分支（ISO 字符串直接判成员）。"""
    _patch_days(monkeypatch)
    assert tc.is_trading_day_by_calendar("2026-09-21T15:00:00", "d") is True
    assert tc.is_trading_day_by_calendar("2026-09-20", "d") is False
