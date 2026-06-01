# -*- coding: utf-8 -*-
"""v8.x: 合并页「设置模拟本金」相关纯逻辑测试（不拉起 Streamlit 运行时）。

只测可隔离的纯函数 _reset_sim_account —— UI 回调（number_input/button）依赖
Streamlit runtime，不在单测范围。
"""
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.pages as pages


def test_reset_sim_account_writes_consistent_state(tmp_path):
    state_path = str(tmp_path / "account_state.json")
    pages._reset_sim_account(state_path, 3000.0)

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    # 基线/现金/权益三者一致 = 本金；计数清零；空仓
    assert state["initial_capital"] == 3000.0
    assert state["cash"] == 3000.0
    assert state["equity"] == 3000.0
    assert state["positions"] == []
    assert state["total_trades"] == 0
    assert state["total_pnl"] == 0.0
    assert state["_reset_reason"] == "manual_capital_set"


def test_reset_sim_account_clears_sidecar_files(tmp_path):
    state_path = str(tmp_path / "account_state.json")
    eq = tmp_path / "equity_curve.csv"
    th = tmp_path / "trade_history.csv"
    eq.write_text("日期,总权益\n2026-06-01,1200\n", encoding="utf-8")
    th.write_text("日期,代码,方向\n2026-06-01,000001,买入\n", encoding="utf-8")

    pages._reset_sim_account(state_path, 2500.0)

    # 旧权益曲线 + 旧成交历史都被清掉，避免和清零计数矛盾
    assert not eq.exists()
    assert not th.exists()


def test_reset_sim_account_no_sidecar_is_ok(tmp_path):
    # 旁路文件不存在时不应报错
    state_path = str(tmp_path / "account_state.json")
    pages._reset_sim_account(state_path, 1800.0)
    assert os.path.exists(state_path)
