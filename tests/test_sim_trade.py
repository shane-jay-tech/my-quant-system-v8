# -*- coding: utf-8 -*-
import os
import json
import pytest
import sys
from datetime import datetime, date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sim_trade


@pytest.fixture
def isolated_sim_trade(tmp_path, monkeypatch):
    monkeypatch.setattr(sim_trade, "RISK_CONFIG_FILE", str(tmp_path / "rc.json"))
    monkeypatch.setattr(sim_trade, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(sim_trade, "SIM_DIR", str(tmp_path))
    # 默认指向不存在的路径，避免测试无意中读到生产 real_trades.csv
    monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(tmp_path / "no_real.csv"))
    # 隔离生产配置里的 manual_capital（用户可在 UI 手填），让本类测试专注 real-trades 联动；
    # 需要测手填优先级的用例会自己再 setattr 覆盖。
    monkeypatch.setattr(sim_trade, "get_manual_capital", lambda: None)
    return tmp_path


class TestSimTrade:
    def test_load_risk_config_missing_file(self, isolated_sim_trade):
        assert sim_trade.load_risk_config() == {}

    def test_load_risk_config_no_alert_only_field(self, isolated_sim_trade):
        payload = {
            "stop_loss_pct": -0.06,
            "take_profit_pct": 0.18,
            "max_hold_days": 12,
        }
        with open(sim_trade.RISK_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        assert sim_trade.load_risk_config() == {
            "STOP_LOSS_PCT": -0.06,
            "TAKE_PROFIT_PCT": 0.18,
            "MAX_HOLD_DAYS": 12,
        }

    def test_load_risk_config_alert_only_true(self, isolated_sim_trade):
        payload = {
            "stop_loss_pct": -0.05,
            "take_profit_pct": 0.16,
            "max_hold_days": 9,
            "alert_only": True,
        }
        with open(sim_trade.RISK_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        assert sim_trade.load_risk_config() == {
            "MAX_HOLD_DAYS": 9,
        }

    def test_load_risk_config_alert_only_false(self, isolated_sim_trade):
        payload = {
            "stop_loss_pct": -0.07,
            "take_profit_pct": 0.22,
            "max_hold_days": 15,
            "alert_only": False,
        }
        with open(sim_trade.RISK_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        assert sim_trade.load_risk_config() == {
            "STOP_LOSS_PCT": -0.07,
            "TAKE_PROFIT_PCT": 0.22,
            "MAX_HOLD_DAYS": 15,
        }

    def test_load_risk_config_corrupt_json(self, isolated_sim_trade):
        with open(sim_trade.RISK_CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("{not-valid-json")

        with pytest.raises(json.JSONDecodeError):
            sim_trade.load_risk_config()

    def test_save_state_no_tmp_residue(self, isolated_sim_trade):
        sim_trade.save_state({"cash": 12345, "positions": []})

        assert os.path.exists(sim_trade.STATE_FILE)
        assert not os.path.exists(sim_trade.STATE_FILE + ".tmp")
        assert not list(isolated_sim_trade.glob("*.tmp"))

    def test_save_state_round_trip(self, isolated_sim_trade):
        state = {
            "cash": 88888,
            "positions": [
                {"代码": "000001", "名称": "平安银行", "shares": 100, "price": 10.5}
            ],
        }

        sim_trade.save_state(state)

        with open(sim_trade.STATE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded == state
        assert loaded["cash"] == 88888
        assert loaded["positions"][0]["代码"] == "000001"

    def test_save_state_adds_updated_key(self, isolated_sim_trade):
        state = {"cash": 50000, "positions": []}

        sim_trade.save_state(state)

        assert "_updated" in state
        assert isinstance(state["_updated"], str)
        assert state["_updated"]

        with open(sim_trade.STATE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["_updated"] == state["_updated"]

    def test_init_account_fresh_start(self, isolated_sim_trade):
        assert not os.path.exists(sim_trade.STATE_FILE)

        account = sim_trade.init_account()

        assert os.path.exists(sim_trade.STATE_FILE)
        # v8.7：fresh state 用 resolve_initial_capital()（real_trades 不存在时 = fallback）
        assert account["cash"] == sim_trade.resolve_initial_capital()
        assert account["positions"] == []
        assert "_updated" in account

        with open(sim_trade.STATE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)

        assert saved == account

    def test_init_account_existing_state(self, isolated_sim_trade):
        existing = {"cash": 77777}
        with open(sim_trade.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)

        account = sim_trade.init_account()

        # v8.6+ 字段回填：cash 必须保留原值；其他字段补默认
        assert account["cash"] == 77777
        for key in ("equity", "positions", "total_trades", "total_pnl",
                    "total_commission", "total_stamp_tax", "total_trade_volume"):
            assert key in account, f"backfill should add {key!r}"


class TestRealCapitalLinkage:
    """v8.7: 模拟账户预算联动 real_trades.csv（用户选项 B）"""

    def _write_real_trades(self, path, rows):
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False, encoding='utf-8-sig')

    def test_get_real_invested_no_file(self, isolated_sim_trade, monkeypatch):
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE",
                            str(isolated_sim_trade / "missing.csv"))
        assert sim_trade.get_real_invested_capital() is None

    def test_get_real_invested_empty_file(self, isolated_sim_trade, monkeypatch):
        path = isolated_sim_trade / "rt.csv"
        path.write_text("日期,代码,方向,成交额,手续费\n", encoding='utf-8-sig')
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        assert sim_trade.get_real_invested_capital() is None

    def test_get_real_invested_buy_only(self, isolated_sim_trade, monkeypatch):
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1000.0, "手续费": 5.0},
            {"日期": "2026-05-16", "代码": "000002", "方向": "买入",
             "成交额": 700.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        # 1000+5 + 700+5 = 1710
        assert sim_trade.get_real_invested_capital() == 1710.0

    def test_get_real_invested_buy_and_sell(self, isolated_sim_trade, monkeypatch):
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1000.0, "手续费": 5.0},
            {"日期": "2026-05-20", "代码": "000001", "方向": "卖出",
             "成交额": 600.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        # cash_out=1005, cash_in=595 → net 410
        assert sim_trade.get_real_invested_capital() == 410.0

    def test_get_real_invested_negative_returns_none(self, isolated_sim_trade, monkeypatch):
        # 全卖光的极端情况：净投入 <= 0 → fallback
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1000.0, "手续费": 5.0},
            {"日期": "2026-05-20", "代码": "000001", "方向": "卖出",
             "成交额": 2000.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        assert sim_trade.get_real_invested_capital() is None

    def test_resolve_initial_capital_uses_real(self, isolated_sim_trade, monkeypatch):
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1500.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)
        assert sim_trade.resolve_initial_capital() == 1505.0

    def test_resolve_initial_capital_fallback_when_disabled(self, isolated_sim_trade, monkeypatch):
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1500.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", False)
        monkeypatch.setattr(sim_trade, "_FALLBACK_CAPITAL", 100_000)
        assert sim_trade.resolve_initial_capital() == 100_000

    def test_init_account_delta_sync_increase(self, isolated_sim_trade, monkeypatch):
        # 老 state baseline=1200，real_trades 现在算出 1709 → cash 加 509
        existing = {"cash": 200, "initial_capital": 1200}
        with open(sim_trade.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)

        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1700.0, "手续费": 9.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)

        account = sim_trade.init_account()
        assert account["initial_capital"] == 1709.0
        assert account["cash"] == 709.0  # 200 + (1709 - 1200)

    def test_init_account_backfill_then_sync(self, isolated_sim_trade, monkeypatch):
        # 老 state（v8.6 之前）没有 initial_capital 字段；不能直接当前真实当基线，
        # 否则 delta=0 永远不同步。应当：backfill = _FALLBACK_CAPITAL → 然后 delta sync。
        existing = {"cash": 200}  # 没 initial_capital
        with open(sim_trade.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)

        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 2000.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)
        monkeypatch.setattr(sim_trade, "_FALLBACK_CAPITAL", 1200)

        account = sim_trade.init_account()
        # baseline 从 backfill=1200 → sync 到 2005，delta=+805
        assert account["initial_capital"] == 2005.0
        assert account["cash"] == 1005.0  # 200 + (2005 - 1200)

    def test_init_account_delta_sync_clamps_negative(self, isolated_sim_trade, monkeypatch):
        # 用户取走真实账户钱 → real 净投入降低；如果直接减会让 cash<0，必须钳到 0
        existing = {"cash": 100, "initial_capital": 5000}
        with open(sim_trade.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)

        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 500.0, "手续费": 0.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)

        account = sim_trade.init_account()
        assert account["initial_capital"] == 500.0
        assert account["cash"] == 0  # 不会变负数


class TestManualCapital:
    """v8.x: 用户手填真实总资金（manual_capital）— 最高优先级 + 自动推算兜底"""

    def _write_real_trades(self, path, rows):
        pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')

    # ---- get_manual_capital 解析 ----
    def test_get_manual_capital_unset(self, monkeypatch):
        monkeypatch.setattr(sim_trade, "cfg_get", lambda k, d=None: None)
        assert sim_trade.get_manual_capital() is None

    def test_get_manual_capital_valid(self, monkeypatch):
        monkeypatch.setattr(sim_trade, "cfg_get", lambda k, d=None: 3000)
        assert sim_trade.get_manual_capital() == 3000.0

    def test_get_manual_capital_zero_or_negative_is_none(self, monkeypatch):
        monkeypatch.setattr(sim_trade, "cfg_get", lambda k, d=None: 0)
        assert sim_trade.get_manual_capital() is None
        monkeypatch.setattr(sim_trade, "cfg_get", lambda k, d=None: -50)
        assert sim_trade.get_manual_capital() is None

    def test_get_manual_capital_garbage_is_none(self, monkeypatch):
        monkeypatch.setattr(sim_trade, "cfg_get", lambda k, d=None: "abc")
        assert sim_trade.get_manual_capital() is None

    # ---- resolve_initial_capital 三级优先级 ----
    def test_manual_beats_real_and_fallback(self, isolated_sim_trade, monkeypatch):
        # 手填存在 → 即使真实订单和 fallback 都有值，也用手填的
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1500.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)
        monkeypatch.setattr(sim_trade, "_FALLBACK_CAPITAL", 1200)
        monkeypatch.setattr(sim_trade, "get_manual_capital", lambda: 8888.0)
        assert sim_trade.resolve_initial_capital() == 8888.0

    def test_real_used_when_no_manual(self, isolated_sim_trade, monkeypatch):
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 1500.0, "手续费": 5.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)
        monkeypatch.setattr(sim_trade, "get_manual_capital", lambda: None)
        assert sim_trade.resolve_initial_capital() == 1505.0

    def test_fallback_when_no_manual_no_real(self, isolated_sim_trade, monkeypatch):
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", False)
        monkeypatch.setattr(sim_trade, "_FALLBACK_CAPITAL", 1200)
        monkeypatch.setattr(sim_trade, "get_manual_capital", lambda: None)
        assert sim_trade.resolve_initial_capital() == 1200

    # ---- init_account：手填本金时禁用 real_trades delta-sync ----
    def test_manual_disables_real_delta_sync(self, isolated_sim_trade, monkeypatch):
        # 老 state baseline=1200，真实订单算出 5000，但用户手填 3000 →
        # 基线锁定 3000，cash 不被 real delta-sync 改动。
        existing = {"cash": 800, "initial_capital": 1200}
        with open(sim_trade.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)
        path = isolated_sim_trade / "rt.csv"
        self._write_real_trades(path, [
            {"日期": "2026-05-15", "代码": "000001", "方向": "买入",
             "成交额": 5000.0, "手续费": 0.0},
        ])
        monkeypatch.setattr(sim_trade, "REAL_TRADES_FILE", str(path))
        monkeypatch.setattr(sim_trade, "_USE_REAL_CAPITAL", True)
        monkeypatch.setattr(sim_trade, "get_manual_capital", lambda: 3000.0)

        account = sim_trade.init_account()
        assert account["initial_capital"] == 3000.0   # 对齐到手填值
        assert account["cash"] == 800                 # cash 没被 real delta 改动
