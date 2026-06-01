import json

import numpy as np
import pandas as pd
import pytest

import portfolio_risk as pr


def _write_equity(tmp_path, values):
    sim_dir = tmp_path / "sim_results"
    sim_dir.mkdir()
    pd.DataFrame({"总权益": values}).to_csv(sim_dir / "equity_curve.csv", index=False)
    return sim_dir


def test_load_history_returns_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "DATA_DIR", str(tmp_path))
    assert pr.load_history_returns(["000001"]) is None


def test_load_history_returns_normalizes_codes_and_skips_short_series(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "DATA_DIR", str(tmp_path))
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    rows = [
        {"日期": date, "代码": 1, "收盘": 10 + i * 0.1}
        for i, date in enumerate(dates)
    ]
    rows += [
        {"日期": date, "代码": 2, "收盘": 20 + i * 0.1}
        for i, date in enumerate(dates[:5])
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "history.csv", index=False)

    result = pr.load_history_returns(["000001", "000002"], lookback=20)

    assert list(result.columns) == ["000001"]
    assert len(result) == 19
    assert result.index.is_monotonic_increasing


def test_correlation_matrix_flags_pair_above_limit(monkeypatch):
    returns = pd.DataFrame(
        {
            "000001": [0.01, -0.02, 0.03, -0.01],
            "000002": [0.02, -0.04, 0.06, -0.02],
        }
    )
    monkeypatch.setattr(pr, "load_history_returns", lambda codes, lookback=60: returns)

    result = pr.calc_correlation_matrix(["000001", "000002"])

    assert result["max_pair"] == ("000001", "000002")
    assert result["max_corr"] == 1.0
    assert bool(result["warning"]) is True


@pytest.mark.parametrize("returns, weights", [(None, [1]), (pd.DataFrame({"a": [0.1]}), [])])
def test_var_rejects_missing_inputs(returns, weights):
    assert pr.calc_portfolio_var(returns, weights) is None


def test_parametric_var_normalizes_weights_and_uses_confidence():
    returns = pd.DataFrame(
        {"a": [-0.03, 0.01, -0.01, 0.02], "b": [-0.02, 0.00, 0.01, 0.01]}
    )

    var_95 = pr.calc_portfolio_var(returns, [2, 2], confidence=0.95)
    var_99 = pr.calc_portfolio_var(returns, [1, 1], confidence=0.99)

    assert var_95 > 0
    assert var_99 > var_95


def test_historical_var_matches_portfolio_percentile():
    returns = pd.DataFrame(
        {"a": [-0.04, -0.01, 0.02, 0.03], "b": [-0.02, 0.00, 0.01, 0.02]}
    )
    portfolio = returns.dot(np.array([0.75, 0.25]))
    expected = round(abs(np.percentile(portfolio, 5)), 6)

    assert pr.calc_portfolio_var(returns, [3, 1], method="historical") == expected


def test_cvar_is_tail_mean_loss():
    returns = pd.DataFrame({"a": [-0.10, -0.04, 0.01, 0.02, 0.03]})
    assert pr.calc_portfolio_cvar(returns, [1], confidence=0.80) == 0.10


def test_drawdown_missing_or_invalid_file_is_normal(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "SIM_DIR", str(tmp_path))
    assert pr.check_drawdown({})["action"] == "normal"

    pd.DataFrame({"wrong": [100, 90]}).to_csv(tmp_path / "equity_curve.csv", index=False)
    assert pr.check_drawdown({})["action"] == "normal"


@pytest.mark.parametrize(
    "values, action, breached",
    [
        ([100, 110, 105], "normal", False),
        ([100, 110, 102], "warning", False),
        ([100, 110, 99], "force_reduce", True),
    ],
)
def test_drawdown_action_thresholds(tmp_path, monkeypatch, values, action, breached):
    monkeypatch.setattr(pr, "SIM_DIR", str(_write_equity(tmp_path, values)))
    result = pr.check_drawdown({})
    assert result["action"] == action
    assert result["breached"] is breached


def test_drawdown_corrupt_csv_fails_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "SIM_DIR", str(tmp_path))
    (tmp_path / "equity_curve.csv").write_text('"unterminated', encoding="utf-8")
    assert pr.check_drawdown({}) == {
        "current_drawdown": 0.0,
        "breached": False,
        "action": "normal",
    }


def test_volatility_requires_enough_history(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "SIM_DIR", str(_write_equity(tmp_path, [100] * 19)))
    assert pr.check_volatility_target({}) == {"current_vol": 0.0, "breached": False}


def test_volatility_target_normal_and_breached(tmp_path, monkeypatch):
    stable = 100 * np.cumprod([1.001] * 30)
    sim_dir = _write_equity(tmp_path, stable)
    monkeypatch.setattr(pr, "SIM_DIR", str(sim_dir))
    assert pr.check_volatility_target({}, target_vol=0.20)["action"] == "normal"

    volatile = 100 * np.cumprod([1.08 if i % 2 else 0.92 for i in range(30)])
    pd.DataFrame({"总权益": volatile}).to_csv(sim_dir / "equity_curve.csv", index=False)
    result = pr.check_volatility_target({}, target_vol=0.20)
    assert bool(result["breached"]) is True
    assert result["action"] == "force_reduce"


def test_turnover_handles_zero_equity():
    state = {"cash": 0, "positions": []}
    assert pr.check_turnover(state, [{"金额": 100}]) == {"turnover": 0.0, "breached": False}


def test_turnover_normal_and_blocked():
    state = {
        "cash": 1000,
        "positions": [{"current_price": 10, "shares": 10}],
    }
    assert pr.check_turnover(state, [{"金额": 100}])["action"] == "normal"

    blocked = pr.check_turnover(state, [{"金额": 1000}])
    assert blocked["turnover"] == 100.0
    assert blocked["breached"] is True
    assert blocked["action"] == "block_new"


def test_generate_report_aggregates_all_force_actions(monkeypatch):
    state = {
        "cash": 1000,
        "positions": [
            {"code": "000001", "current_price": 10, "shares": 10},
            {"code": "000002", "current_price": 20, "shares": 10},
        ],
    }
    returns = pd.DataFrame({"000001": [-0.1, 0.02], "000002": [-0.08, 0.01]})
    monkeypatch.setattr(
        pr,
        "check_drawdown",
        lambda state: {"action": "force_reduce", "message": "drawdown"},
    )
    monkeypatch.setattr(
        pr,
        "check_volatility_target",
        lambda state: {"action": "force_reduce", "message": "volatility"},
    )
    monkeypatch.setattr(
        pr,
        "calc_correlation_matrix",
        lambda codes: {"max_corr": 0.99, "max_pair": ("000001", "000002"), "warning": True},
    )
    monkeypatch.setattr(pr, "load_history_returns", lambda codes: returns)
    monkeypatch.setattr(
        pr,
        "check_turnover",
        lambda state, orders: {"breached": True, "message": "turnover"},
    )

    report = pr.generate_risk_report(state, new_orders=[{"金额": 1}])

    assert report["var_95"] > 0
    assert report["cvar_95"] > 0
    assert report["recommended_actions"] == [
        "drawdown",
        "volatility",
        "持仓相关性过高: ('000001', '000002')=0.99",
        "turnover",
    ]


@pytest.mark.xfail(
    strict=True,
    reason="generate_risk_report 对 correlation=None 直接调用 .get，单持仓会崩溃",
)
def test_generate_report_supports_single_position(monkeypatch):
    monkeypatch.setattr(pr, "check_drawdown", lambda state: {"action": "normal"})
    monkeypatch.setattr(pr, "check_volatility_target", lambda state: {"action": "normal"})
    state = {
        "cash": 1000,
        "positions": [{"code": "000001", "current_price": 10, "shares": 10}],
    }
    report = pr.generate_risk_report(state)
    assert report["correlation"] is None
    assert report["recommended_actions"] == []


def test_save_risk_report_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "DATA_DIR", str(tmp_path))
    report = {"drawdown": {"action": "normal"}, "recommended_actions": []}
    pr.save_risk_report(report)
    assert json.loads((tmp_path / "risk_report.json").read_text(encoding="utf-8")) == report
