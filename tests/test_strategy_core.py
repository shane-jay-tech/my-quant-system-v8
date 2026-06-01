import json

import numpy as np
import pandas as pd
import pytest

import strategy


def _history(code="000001", periods=70, start="2026-01-01", slope=0.2):
    dates = pd.date_range(start, periods=periods, freq="D")
    close = 100 + np.arange(periods) * slope
    volume = np.full(periods, 1000.0)
    volume[-1] = 2000.0
    return pd.DataFrame(
        {
            "日期": dates,
            "代码": code,
            "开盘": close - 0.1,
            "最高": close + 1,
            "最低": close - 1,
            "收盘": close,
            "成交量": volume,
        }
    )


def _today(code="000001", name="样本股", change=5.0, mcap=8e9, volume=1000, price=114):
    return pd.DataFrame(
        [
            {
                "代码": code,
                "名称": name,
                "涨跌幅": change,
                "流通市值": mcap,
                "成交量": volume,
                "最新价": price,
            }
        ]
    )


def _patch_indicators_and_market(monkeypatch, rsi=50.0):
    monkeypatch.setattr(
        strategy,
        "calc_rsi",
        lambda close, period=14: pd.Series(rsi, index=close.index, dtype=float),
    )
    monkeypatch.setattr(
        strategy,
        "calc_macd",
        lambda close: (
            pd.Series(2.0, index=close.index),
            pd.Series(1.0, index=close.index),
            pd.Series(0.5, index=close.index),
        ),
    )
    monkeypatch.setattr(
        strategy,
        "calc_atr",
        lambda high, low, close, period=14: pd.Series(1.0, index=close.index),
    )
    monkeypatch.setattr(strategy, "fetch_hs300_data", lambda: pd.DataFrame())
    monkeypatch.setattr(strategy, "detect_market_regime", lambda data: ("震荡", {}))
    monkeypatch.setattr(strategy, "classify_sector", lambda code, name: "测试板块")
    monkeypatch.setattr(
        strategy,
        "detect_sector_concentration",
        lambda rows, max_per_sector=3: (
            [{**row, "集中风险": False} for row in rows],
            {},
            [],
        ),
    )


def test_load_evolved_params_missing_and_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy, "DATA_DIR", str(tmp_path))
    assert strategy.load_evolved_params() == {}
    (tmp_path / "evolve_daily_state.json").write_text("{bad", encoding="utf-8")
    assert strategy.load_evolved_params() == {}


def test_load_evolved_params_only_returns_supported_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy, "DATA_DIR", str(tmp_path))
    state = {
        "current_params": {
            "RSI_LOW": 35,
            "MA_LONG": 20,
            "MAX_SINGLE_POSITION": 0.2,
            "UNKNOWN": 1,
        }
    }
    (tmp_path / "evolve_daily_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    assert strategy.load_evolved_params() == {
        "RSI_LOW": 35,
        "MA_LONG": 20,
        "MAX_SINGLE_POSITION": 0.2,
    }


@pytest.mark.parametrize(
    "regime, expected",
    [
        ("强牛", (25, 75, 30)),
        ("弱牛", (28, 72, 30)),
        ("震荡", (30, 70, 25)),
        ("弱熊", (35, 65, 15)),
        ("强熊", (38, 60, 10)),
        ("未知状态", (30, 70, 25)),
    ],
)
def test_adaptive_params_cover_all_regimes(regime, expected):
    params = strategy.get_adaptive_params(regime)
    assert (params["rsi_low"], params["rsi_high"], params["ma_long"]) == expected
    assert params["regime"] == regime


def test_adaptive_params_can_be_disabled(monkeypatch):
    monkeypatch.setattr(strategy, "USE_DYNAMIC_PARAMS", False)
    params = strategy.get_adaptive_params("强牛")
    assert params["regime"] == "default"
    assert params["rsi_low"] == strategy.RSI_LOW


def test_indicator_shapes_and_known_atr():
    close = pd.Series([10.0, 9.0, 8.0, 7.0])
    rsi = strategy.calc_rsi(close, period=2)
    assert len(rsi) == len(close)
    assert rsi.iloc[-1] == 0.0

    high = pd.Series([11.0, 12.0, 10.0])
    low = pd.Series([9.0, 9.0, 8.0])
    close = pd.Series([10.0, 11.0, 9.0])
    atr = strategy.calc_atr(high, low, close, period=2)
    assert atr.iloc[0] == 2.0
    assert atr.iloc[-1] > 2.0


@pytest.mark.parametrize(
    "inputs, expected",
    [
        ((105, 100, 106, 50, 2, 1, 1, 2.0, 5), 100),
        ((100.1, 100, 101, 40, 2, 1, -1, 0.8, -2), 48),
        ((90, 100, 90, 30, 0, 1, -1, 0.1, -6), 4),
    ],
)
def test_score_stock_exercises_quality_bands(inputs, expected):
    assert strategy.score_stock(*inputs) == expected


def test_screen_stocks_selects_valid_candidate_and_sets_risk_fields(monkeypatch):
    _patch_indicators_and_market(monkeypatch)
    result = strategy.screen_stocks(
        _today(),
        _history(),
        target_date="2026-03-11",
        override_params={"TOP_N": 1},
    )

    assert result["代码"].tolist() == ["000001"]
    assert result.iloc[0]["止损价"] == pytest.approx(result.iloc[0]["最新价"] - 2)
    assert result.iloc[0]["风险"] == "低"
    assert "MACD正向" in result.iloc[0]["选入理由"]
    assert result.iloc[0]["板块"] == "测试板块"


def test_screen_stocks_filters_st_low_mcap_halt_delist_and_new_stock(monkeypatch):
    _patch_indicators_and_market(monkeypatch)
    today = pd.concat(
        [
            _today("000001", "正常股"),
            _today("000002", "ST问题股"),
            _today("000003", "低市值", mcap=1e9),
            _today("000004", "停牌股", volume=0),
            _today("000005", "退市样本"),
            _today("000006", "新股"),
        ],
        ignore_index=True,
    )
    history = pd.concat([_history("000001"), _history("000006", periods=10)])

    result = strategy.screen_stocks(today, history, override_params={"TOP_N": 10})

    assert result["代码"].tolist() == ["000001"]


def test_screen_stocks_override_rsi_boundary_is_enforced(monkeypatch):
    _patch_indicators_and_market(monkeypatch, rsi=50)
    result = strategy.screen_stocks(
        _today(),
        _history(),
        override_params={"RSI_LOW": 55, "RSI_HIGH": 70},
    )
    assert result.empty


def test_sector_concentration_prefers_safe_candidate_over_higher_score(monkeypatch):
    _patch_indicators_and_market(monkeypatch)
    today = pd.concat(
        [_today("000001", "高分股", change=5), _today("000002", "安全股", change=1)],
        ignore_index=True,
    )
    history = pd.concat([_history("000001"), _history("000002")])

    def tag_first_risky(rows, max_per_sector=3):
        tagged = []
        for index, row in enumerate(rows):
            tagged.append({**row, "集中风险": index == 0})
        return tagged, {}, ["集中度警告"]

    monkeypatch.setattr(strategy, "detect_sector_concentration", tag_first_risky)
    result = strategy.screen_stocks(today, history, override_params={"TOP_N": 1})
    assert result["代码"].tolist() == ["000002"]


@pytest.mark.xfail(
    strict=True,
    reason="screen_stocks 的 target_date 目前只用于日志，没有截断历史数据，存在未来函数",
)
def test_screen_stocks_does_not_read_after_target_date(monkeypatch):
    seen_lengths = []
    _patch_indicators_and_market(monkeypatch)

    def record_rsi(close, period=14):
        seen_lengths.append(len(close))
        return pd.Series(50.0, index=close.index)

    monkeypatch.setattr(strategy, "calc_rsi", record_rsi)
    history = _history(periods=70)
    target_date = history.iloc[60]["日期"]
    strategy.screen_stocks(_today(), history, target_date=target_date)
    assert seen_lengths == [61]


def test_render_markdown_and_summary_expose_decision_context():
    result = pd.DataFrame(
        [
            {
                "代码": "000001",
                "名称": "样本股",
                "板块": "金融",
                "最新价": 10.0,
                "涨跌幅": 2.0,
                "MA5": 9.8,
                "MA20": 9.5,
                "RSI": 52.0,
                "量比": 1.5,
                "流通市值_亿": 80.0,
                "综合评分": 88,
                "风险": "中",
                "选入理由": "强趋势",
            }
        ]
    )
    markdown = strategy.render_markdown(
        result,
        "2026-07-14",
        adaptive={"rsi_low": 30, "rsi_high": 70},
        regime="震荡",
    )
    summary = strategy.generate_summary(result)

    assert "000001" in markdown
    assert "震荡" in markdown
    assert "免责声明" in markdown
    assert "今日选出1只" in summary
    assert len(summary) <= 100


def test_generate_summary_empty():
    assert strategy.generate_summary(pd.DataFrame()) == "今日无股票通过筛选。"
