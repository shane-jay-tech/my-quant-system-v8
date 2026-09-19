"""q918-02：utils/trading_calendar.is_trading_day_by_calendar 边界 characterization（基线 #7）。

冻结现值契约：
- 纯集合成员判断（无周末硬编码）——周六/周日不在集合 → False；
- 集合外工作日 → False；集合内工作日 → True（正向路径一并冻结）；
- 日历不可用（get_trading_days → None）→ None（调用方走启发式兜底契约）；
- 字符串入参走 str(day)[:10] 分支。
零网络：get_trading_days 整体 monkeypatch，_refresh/akshare 永不触网；
刷新分支（q918-03，S5 F-4）经 sys.modules 注入假 akshare 冻结 None/空表/缺列/正常四形态与缓存落盘。
"""

from __future__ import annotations

import sys
import types
from datetime import date

import pandas as pd

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


# ---------- 刷新失败分支（q918-03，S5 F-4：utils/trading_calendar.py:37-40 三分支无测试） ----------


def _inject_akshare(monkeypatch, ret):
    """sys.modules 注入假 akshare，tool_trade_date_hist_sina 返回 ret（绝不触网）。"""
    fake = types.ModuleType("akshare")
    fake.tool_trade_date_hist_sina = lambda: ret
    monkeypatch.setitem(sys.modules, "akshare", fake)


def test_refresh_none_calendar_returns_none(tmp_path, monkeypatch):
    """akshare 返回 None → get_trading_days 返回 None，且不落缓存。"""
    _inject_akshare(monkeypatch, None)
    assert tc.get_trading_days(str(tmp_path)) is None
    assert not (tmp_path / tc.CACHE_NAME).exists()


def test_refresh_empty_df_returns_none(tmp_path, monkeypatch):
    """akshare 返回空表 → None，不落缓存。"""
    _inject_akshare(monkeypatch, pd.DataFrame())
    assert tc.get_trading_days(str(tmp_path)) is None
    assert not (tmp_path / tc.CACHE_NAME).exists()


def test_refresh_missing_column_returns_none(tmp_path, monkeypatch):
    """akshare 返回缺 trade_date 列的表 → None，不落缓存。"""
    _inject_akshare(monkeypatch, pd.DataFrame({"x": [1, 2]}))
    assert tc.get_trading_days(str(tmp_path)) is None
    assert not (tmp_path / tc.CACHE_NAME).exists()


def test_refresh_normal_df_returns_days_and_writes_cache(tmp_path, monkeypatch):
    """正常表 → 返回日期集合，且原子落盘 trading_calendar.csv（tmp→replace）。"""
    _inject_akshare(monkeypatch, pd.DataFrame({"trade_date": ["2026-09-21", "2026-09-23"]}))
    days = tc.get_trading_days(str(tmp_path))
    assert days == {"2026-09-21", "2026-09-23"}
    assert (tmp_path / tc.CACHE_NAME).exists()
    assert not (tmp_path / (tc.CACHE_NAME + ".tmp")).exists()  # 原子替换后无残留


def test_cache_hit_skips_refresh(tmp_path, monkeypatch):
    """缓存优先契约：缓存可读时根本不调 akshare（假模块一旦被调即炸）。"""
    pd.DataFrame({"trade_date": ["2026-09-21"]}).to_csv(tmp_path / tc.CACHE_NAME, index=False, encoding="utf-8-sig")
    fake = types.ModuleType("akshare")

    def _must_not_be_called():
        raise AssertionError("缓存命中时不应触网刷新")

    fake.tool_trade_date_hist_sina = _must_not_be_called
    monkeypatch.setitem(sys.modules, "akshare", fake)
    assert tc.get_trading_days(str(tmp_path)) == {"2026-09-21"}
