import numpy as np
import pandas as pd
import pytest

import enhanced_backtest as eb


def _prepared_history(periods=16):
    dates = pd.date_range("2026-01-01", periods=periods, freq="D")
    close = 100 + np.arange(periods, dtype=float)
    return pd.DataFrame(
        {
            "日期": dates,
            "代码": "000001",
            "开盘": close + 0.25,
            "收盘": close,
            "MA5": close - 1,
            "MA20": close - 2,
            "RSI": 50.0,
            "ret_1d": 0.01,
            "ret_3d": 0.03,
            "ret_5d": 0.05,
        }
    )


def _today(name="样本股", mcap=8e9):
    return pd.DataFrame([{"代码": "000001", "名称": name, "流通市值": mcap}])


def _patch_backtest_dependencies(monkeypatch, mode="next_open"):
    monkeypatch.setattr(eb, "calc_indicators", lambda frame: frame.copy())
    monkeypatch.setattr(eb, "BACKTEST_DAYS", 16)
    monkeypatch.setattr(eb, "EXECUTION_MODE", mode)
    monkeypatch.setattr(eb, "compute_dynamic_notional", lambda regime, count: 1000.0)
    calls = []

    def fake_cost(mcap, **kwargs):
        calls.append((mcap, kwargs))
        return 0.01

    monkeypatch.setattr(eb, "get_cost_by_mcap", fake_cost)
    return calls


def test_calc_indicators_keeps_stock_groups_isolated():
    dates = pd.date_range("2026-01-01", periods=35, freq="D")
    frame = pd.concat(
        [
            pd.DataFrame({"日期": dates, "代码": "000001", "收盘": np.arange(35) + 10}),
            pd.DataFrame({"日期": dates, "代码": "000002", "收盘": np.arange(35) + 100}),
        ],
        ignore_index=True,
    )
    result = eb.calc_indicators(frame)

    for code in ["000001", "000002"]:
        group = result[result["代码"] == code]
        assert group["MA5"].iloc[:4].isna().all()
        assert group["MA20"].iloc[:29].isna().all()
        assert group["ret_1d"].iloc[0] != group["ret_1d"].iloc[0]


def test_next_open_uses_t_plus_one_open_and_does_not_double_charge_slippage(monkeypatch):
    calls = _patch_backtest_dependencies(monkeypatch, mode="next_open")
    history = _prepared_history()

    trades, daily, benchmark = eb.backtest(history, _today(), None)

    first = trades.iloc[0]
    assert first["日期"] == "2026-01-01"
    assert first["持有"] == 1
    assert first["入场"] == round(history.iloc[1]["开盘"] * (1 + eb.SLIPPAGE), 2)
    assert first["出场"] == round(history.iloc[2]["开盘"] * (1 - eb.SLIPPAGE), 2)
    assert first["成本率"] == 1.0
    assert daily.iloc[0]["候选"] == 1
    assert benchmark is None
    assert calls
    assert all(kwargs["with_slippage"] is False for _, kwargs in calls)


def test_same_close_legacy_mode_uses_signal_close(monkeypatch):
    _patch_backtest_dependencies(monkeypatch, mode="same_close")
    history = _prepared_history()

    trades, _, _ = eb.backtest(history, _today(), None)

    first = trades.iloc[0]
    assert first["入场"] == round(history.iloc[0]["收盘"] * (1 + eb.SLIPPAGE), 2)
    assert first["出场"] == round(history.iloc[1]["收盘"] * (1 - eb.SLIPPAGE), 2)


def test_next_open_skips_signal_when_t_plus_one_open_is_invalid(monkeypatch):
    _patch_backtest_dependencies(monkeypatch, mode="next_open")
    history = _prepared_history()
    history.loc[1, "开盘"] = np.nan

    trades, _, _ = eb.backtest(history, _today(), None)

    assert "2026-01-01" not in set(trades["日期"])
    assert len(trades) > 0


@pytest.mark.parametrize(
    "name, mcap",
    [("ST样本", 8e9), ("普通股", 1e9)],
)
def test_backtest_hard_filters_st_and_low_market_cap(monkeypatch, name, mcap):
    _patch_backtest_dependencies(monkeypatch)
    trades, daily, _ = eb.backtest(_prepared_history(), _today(name=name, mcap=mcap), None)
    assert trades.empty
    assert (daily["候选"] == 0).all()


def test_dead_cross_confirmed_at_close_exits_next_day_open(monkeypatch):
    _patch_backtest_dependencies(monkeypatch, mode="next_open")
    history = _prepared_history()
    history.loc[4, "MA5"] = 90
    history.loc[4, "MA20"] = 95

    trades, _, _ = eb.backtest(history, _today(), None)
    trade = trades[(trades["日期"] == "2026-01-01") & (trades["持有"] == 5)].iloc[0]

    assert trade["出场原因"] == "MA死叉(3日)"
    assert trade["出场"] == round(history.iloc[5]["开盘"] * (1 - eb.SLIPPAGE), 2)


def test_bull_market_uses_full_top_n_and_builds_benchmark(monkeypatch):
    _patch_backtest_dependencies(monkeypatch)
    monkeypatch.setattr(eb, "TOP_N", 7)
    history = _prepared_history(periods=40)
    monkeypatch.setattr(eb, "BACKTEST_DAYS", 40)
    index = pd.DataFrame(
        {
            "日期": history["日期"],
            "收盘": np.arange(40, dtype=float) + 100,
        }
    )

    trades, daily, benchmark = eb.backtest(history, _today(), index)

    assert len(trades) > 0
    assert daily.iloc[-1]["市场"] == "牛市"
    assert daily.iloc[-1]["选中"] == 7
    assert benchmark is not None
    assert "基准(%)" in benchmark.columns


def test_analyze_empty_returns_explicit_na_for_all_horizons():
    result = eb.analyze(pd.DataFrame(), None)
    assert list(result) == ["持有1日", "持有5日", "持有10日"]
    assert all(item["胜率"] == "N/A" for item in result.values())


def test_analyze_calculates_win_rate_cost_cross_benchmark_and_loss_streak():
    trades = pd.DataFrame(
        [
            {"日期": "2026-01-01", "持有": 1, "净收益": 1.0, "毛收益": 1.5, "出场原因": "到期", "市场": "牛市"},
            {"日期": "2026-01-01", "持有": 5, "净收益": -1.0, "毛收益": -0.5, "出场原因": "到期", "市场": "牛市"},
            {"日期": "2026-01-02", "持有": 5, "净收益": -2.0, "毛收益": -1.5, "出场原因": "MA死叉(3日)", "市场": "熊市/震荡"},
            {"日期": "2026-01-01", "持有": 10, "净收益": 2.0, "毛收益": 2.5, "出场原因": "MA死叉(3日)", "市场": "牛市"},
        ]
    )
    benchmark = pd.DataFrame({"基准(%)": [0.1, 0.1]})

    result = eb.analyze(trades, benchmark)

    assert result["持有10日"]["胜率"] == "100.0%"
    assert result["持有10日"]["成本"] == "0.50%"
    assert result["持有10日"]["MA死叉出场率"] == "100.0%"
    assert result["牛市(10日)"]["笔数"] == 1
    assert result["基准对比"]["超额"] == "+1.00%"
    assert result["风控"]["最大连亏天数"] == 2


@pytest.mark.parametrize(
    "net, win_rate, phrase",
    [(3.0, 60.0, "可以赚钱"), (1.0, 40.0, "微利"), (0.0, 40.0, "需要外部辅助")],
)
def test_render_verdict_thresholds(monkeypatch, net, win_rate, phrase):
    monkeypatch.setattr(eb, "realized_cost_summary", lambda trades: {"available": False})
    monkeypatch.setattr(eb, "format_cost_header", lambda summary: "无成交成本样本")
    results = {
        "持有10日": {
            "交易数": 1,
            "胜率": f"{win_rate}%",
            "毛收益": f"{net + 0.5:+.2f}%",
            "净收益": f"{net:+.2f}%",
            "MA死叉出场率": "0.0%",
        }
    }
    report = eb.render(results)
    assert phrase in report


def test_fetch_index_skips_refresh_when_local_data_is_current(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "DATA_DIR", str(tmp_path))
    pd.DataFrame({"日期": ["2026-07-14"], "收盘": [4000]}).to_csv(
        tmp_path / "hs300_index.csv", index=False
    )
    import fetch_index
    import utils.calendar

    calls = []
    monkeypatch.setattr(utils.calendar, "get_last_trading_day", lambda data_dir=None: "2026-07-14")
    monkeypatch.setattr(fetch_index, "update_hs300_index", lambda data_dir=None: calls.append(data_dir))

    result = eb.fetch_index()
    assert calls == []
    assert result.iloc[0]["收盘"] == 4000
    assert pd.api.types.is_datetime64_any_dtype(result["日期"])
