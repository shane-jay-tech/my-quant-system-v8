"""pytest 全局安全护栏（v8.7 审查补丁，2026-09-02）。

事故背景：一次测试/AppTest 会话误触发「取消手动本金」UI 回调，把生产
sim_results/account_state.json 重置并删除 equity_curve.csv / trade_history.csv。
根因是 app.pages._reset_sim_account 以真实 BASE_DIR 执行。

防线：autouse fixture 给 _reset_sim_account 加一层路径守卫——
只允许写 pytest tmp 目录，写生产 sim_results 直接 AssertionError。
AppTest 与单测共用同一进程内模块，同样受保护。
"""
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
PROD_SIM_RESULTS = os.path.realpath(os.path.join(BASE_DIR, 'sim_results'))


@pytest.fixture(autouse=True)
def _block_production_sim_reset(monkeypatch):
    from app import pages

    orig = pages._reset_sim_account

    def guarded(state_path, capital):
        real = os.path.realpath(str(state_path))
        if real == PROD_SIM_RESULTS or real.startswith(PROD_SIM_RESULTS + os.sep):
            raise AssertionError(
                f"测试禁止重置生产模拟账户（{real}）。"
                f"测试请使用 tmp_path；生产重置只能由用户在仪表盘显式点击触发。"
            )
        return orig(state_path, capital)

    monkeypatch.setattr(pages, "_reset_sim_account", guarded)
    yield


# ---------------------------------------------------------------------------
# 确定性时钟 fixture（d913b-36，时敏 fixture 规范化）
# ---------------------------------------------------------------------------
# 背景：newbie_protection / multi_strategy / position_sizer 三模块在模块内
# `from datetime import datetime(, date)` 直引时间入口，存在「午夜翻转」时敏
# 行为（cutoff 边界、按日期命名落盘、trading-day 日历窗口）。
# 本 fixture 只 patch 靶点模块的名字绑定（不污染全局 datetime），
# 支持 23:59:59 与次日 00:00:01 两个探针时刻。
import datetime as _datetime_mod
import importlib as _importlib

FROZEN_CLOCK_TARGETS = {
    'newbie_protection': ('datetime',),
    'multi_strategy': ('datetime',),
    'position_sizer': ('datetime', 'date'),
    # 2026-09-15 日间修复（根因）：d914-30 给 bark 两个时敏测试加了 frozen_clock，
    # 但漏登记本表 → fixture 静默不 patch 任何东西，测试用冻结日期拼文件名、
    # 被测代码仍取真实日期（parsers.py:128 / push.py:53）→ 跨日必挂。
    'bark_sender.parsers': ('datetime',),
    'bark_sender.push': ('datetime',),
}


def _frozen_datetime_class(fixed):
    class FrozenDateTime(_datetime_mod.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

        @classmethod
        def today(cls):
            return fixed

    FrozenDateTime.__name__ = 'FrozenDateTime'
    return FrozenDateTime


def _frozen_date_class(fixed):
    fixed_date = fixed.date()

    class FrozenDate(_datetime_mod.date):
        @classmethod
        def today(cls):
            return fixed_date

    FrozenDate.__name__ = 'FrozenDate'
    return FrozenDate


@pytest.fixture
def frozen_clock(monkeypatch):
    """确定性时钟工厂：frozen_clock('2026-09-13 23:59:59') → 返回 fixed datetime。

    对 FROZEN_CLOCK_TARGETS 内模块做模块级名字绑定替换；测试结束由
    monkeypatch 自动还原。探针时刻惯例：'YYYY-MM-DD 23:59:59'（翻转前）
    与 'YYYY-MM-DD 00:00:01'（翻转后，日期为次日）。
    """

    def _freeze(fixed_str: str):
        fixed = _datetime_mod.datetime.strptime(fixed_str, '%Y-%m-%d %H:%M:%S')
        for mod_name, names in FROZEN_CLOCK_TARGETS.items():
            mod = _importlib.import_module(mod_name)
            if 'datetime' in names:
                monkeypatch.setattr(mod, 'datetime', _frozen_datetime_class(fixed))
            if 'date' in names:
                monkeypatch.setattr(mod, 'date', _frozen_date_class(fixed))
        return fixed

    return _freeze
