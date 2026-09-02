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
