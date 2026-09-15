# -*- coding: utf-8 -*-
"""q916-05：stall_watchdog 其余公开函数（parse_yyyymmdd / main）契约边界用例。

范式循 q914-33：只钉既有行为的边界，不改任何逻辑；main 用例以
sys.modules 桩隔离真实日历（utils.trading_calendar → 返回 None 走内置表退化），
保证零网络、零盘上依赖。
"""
import sys
import types
from datetime import date

import pytest

import stall_watchdog as sw


# ---------------------------------------------------------------------------
# parse_yyyymmdd（≥2 边界）
# ---------------------------------------------------------------------------

def test_parse_yyyymmdd_roundtrip_valid():
    assert sw.parse_yyyymmdd("20260915") == date(2026, 9, 15)


def test_parse_yyyymmdd_invalid_calendar_day_raises():
    """月/日越界（2 月 30 日）→ date() 构造抛 ValueError，不返回 None。"""
    with pytest.raises(ValueError):
        sw.parse_yyyymmdd("20260230")


def test_parse_yyyymmdd_short_string_raises():
    """短串在 int('') 处抛 ValueError（无位数预校验）。"""
    with pytest.raises(ValueError):
        sw.parse_yyyymmdd("2026")


# ---------------------------------------------------------------------------
# main（≥2 边界；sys.modules 桩隔离日历，零网络）
# ---------------------------------------------------------------------------

@pytest.fixture
def no_calendar(monkeypatch):
    """utils.trading_calendar 桩：get_trading_days 恒返 None → 内置节假日表退化路径。"""
    fake_utils = types.ModuleType("utils")
    fake_tc = types.ModuleType("utils.trading_calendar")
    fake_tc.get_trading_days = lambda data_dir: None
    monkeypatch.setitem(sys.modules, "utils", fake_utils)
    monkeypatch.setitem(sys.modules, "utils.trading_calendar", fake_tc)


def test_main_no_activity_returns_1(monkeypatch, capsys, no_calendar):
    """logs 与 orders 全缺（known 空）→ 活动日无法确定，返回 1。"""
    dates = {"logs/pipeline_*.log": None,
             "orders/daily_orders_*.json": None,
             "data/stock_*.csv": "20260914"}
    monkeypatch.setattr(sw, "_latest_date", lambda pattern: dates[pattern])
    monkeypatch.setattr(sys, "argv", ["stall_watchdog.py"])
    rc = sw.main()
    assert rc == 1
    assert "no pipeline logs and no orders files found" in capsys.readouterr().out


def test_main_stalled_dryrun_returns_0_without_push(monkeypatch, capsys, no_calendar):
    """活动日远落后参照日 → STALL；--dry-run 只打印不推送，返回 0。"""
    dates = {"logs/pipeline_*.log": "20260901",
             "orders/daily_orders_*.json": None,
             "data/stock_*.csv": "20260914"}
    monkeypatch.setattr(sw, "_latest_date", lambda pattern: dates[pattern])
    monkeypatch.setattr(sys, "argv", ["stall_watchdog.py", "--dry-run"])

    def _boom(title, body):  # 防御：若走到推送即炸
        raise AssertionError("dry-run must not push")
    fake_bark = types.ModuleType("bark_sender")
    fake_bark.send_bark = _boom
    monkeypatch.setitem(sys.modules, "bark_sender", fake_bark)

    rc = sw.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "STALL" in out
    assert "alert NOT sent" in out


def test_main_ok_returns_0(monkeypatch, capsys, no_calendar):
    """活动日=参照日 → lag=0 < 阈值 → OK，返回 0。"""
    today = date.today().strftime("%Y%m%d")
    dates = {"logs/pipeline_*.log": today,
             "orders/daily_orders_*.json": today,
             "data/stock_*.csv": today}
    monkeypatch.setattr(sw, "_latest_date", lambda pattern: dates[pattern])
    monkeypatch.setattr(sys, "argv", ["stall_watchdog.py"])
    rc = sw.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "verdict             : OK" in out
