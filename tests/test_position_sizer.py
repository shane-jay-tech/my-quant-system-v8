# -*- coding: utf-8 -*-
import os
import json
import pytest
import sys
from datetime import datetime, date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import position_sizer


STRONG_BULL = "强牛"
WEAK_BULL = "弱牛"
CHOPPY = "震荡"
WEAK_BEAR = "弱熊"
STRONG_BEAR = "强熊"


@pytest.fixture
def isolated_position_sizer(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    orders_dir = tmp_path / "orders"
    results_dir = tmp_path / "results"

    data_dir.mkdir()
    orders_dir.mkdir()
    results_dir.mkdir()

    monkeypatch.setattr(position_sizer, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(position_sizer, "ORDERS_DIR", str(orders_dir))
    monkeypatch.setattr(position_sizer, "RESULTS_DIR", str(results_dir))

    return {
        "tmp_path": tmp_path,
        "data_dir": data_dir,
        "orders_dir": orders_dir,
        "results_dir": results_dir,
    }


@pytest.fixture
def picks_df():
    return pd.DataFrame(
        [
            {"代码": "000001", "名称": "平安银行", "收盘": 5.0, "momentum": 0.90},
            {"代码": "000002", "名称": "万科A", "收盘": 5.0, "momentum": 0.80},
            {"代码": "000003", "名称": "国农科技", "收盘": 5.0, "momentum": 0.70},
        ],
        columns=["代码", "名称", "收盘", "momentum"],
    )


def _write_regime_state(data_dir, payload):
    with open(data_dir / "regime_state.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _write_stock_file(data_dir, day):
    path = data_dir / f"stock_{day.strftime('%Y%m%d')}.csv"
    path.write_text("代码,收盘\n000001,5.0\n", encoding="utf-8")
    return path


class TestHysteresis:
    def test_hysteresis_first_call(self, isolated_position_sizer):
        result = position_sizer._apply_regime_hysteresis(WEAK_BULL)

        assert result == WEAK_BULL

    def test_hysteresis_same_regime(self, isolated_position_sizer):
        data_dir = isolated_position_sizer["data_dir"]
        _write_regime_state(data_dir, {"last_regime": CHOPPY})

        result = position_sizer._apply_regime_hysteresis(CHOPPY)

        assert result == CHOPPY

    def test_hysteresis_different_no_stock_files(self, isolated_position_sizer):
        data_dir = isolated_position_sizer["data_dir"]
        _write_regime_state(
            data_dir,
            {
                "last_regime": CHOPPY,
                "candidate_regime": WEAK_BULL,
                "candidate_first_seen_date": (date.today() - timedelta(days=1)).isoformat(),
            },
        )

        result = position_sizer._apply_regime_hysteresis(WEAK_BULL)

        assert result == CHOPPY

    def test_hysteresis_one_file_triggers_switch(self, isolated_position_sizer):
        data_dir = isolated_position_sizer["data_dir"]
        today = date.today()
        yesterday = today - timedelta(days=1)

        _write_regime_state(
            data_dir,
            {
                "last_regime": CHOPPY,
                "candidate_regime": WEAK_BULL,
                "candidate_first_seen_date": yesterday.isoformat(),
            },
        )
        _write_stock_file(data_dir, today)

        result = position_sizer._apply_regime_hysteresis(WEAK_BULL)

        assert result == WEAK_BULL

    def test_hysteresis_malformed_filename_no_error(self, isolated_position_sizer):
        data_dir = isolated_position_sizer["data_dir"]
        yesterday = date.today() - timedelta(days=1)

        _write_regime_state(
            data_dir,
            {
                "last_regime": CHOPPY,
                "candidate_regime": WEAK_BULL,
                "candidate_first_seen_date": yesterday.isoformat(),
            },
        )
        (data_dir / "stock_badname.csv").write_text("bad,data\n", encoding="utf-8")

        result = position_sizer._apply_regime_hysteresis(WEAK_BULL)

        assert result == CHOPPY

    def test_hysteresis_old_file_not_counted(self, isolated_position_sizer):
        data_dir = isolated_position_sizer["data_dir"]
        today = date.today()

        _write_regime_state(
            data_dir,
            {
                "last_regime": CHOPPY,
                "candidate_regime": WEAK_BULL,
                "candidate_first_seen_date": today.isoformat(),
            },
        )
        (data_dir / "stock_20200101.csv").write_text("代码,收盘\n000001,5.0\n", encoding="utf-8")

        result = position_sizer._apply_regime_hysteresis(WEAK_BULL)

        assert result == CHOPPY


class TestPositionSizes:
    def test_positions_strong_bull_alloc(self, isolated_position_sizer, picks_df):
        orders, summary = position_sizer.calculate_position_sizes(
            picks_df,
            STRONG_BULL,
            total_capital=100000,
        )

        assert summary["alloc_pct"] == 0.80

    def test_positions_choppy_alloc(self, isolated_position_sizer, picks_df):
        orders, summary = position_sizer.calculate_position_sizes(
            picks_df,
            CHOPPY,
            total_capital=100000,
        )

        assert summary["alloc_pct"] == 0.40

    def test_positions_empty_picks(self, isolated_position_sizer):
        empty = pd.DataFrame(columns=["代码", "名称", "收盘", "momentum"])

        orders, summary = position_sizer.calculate_position_sizes(
            empty,
            STRONG_BULL,
            total_capital=100000,
        )

        assert orders == []

    def test_positions_strong_bear(self, isolated_position_sizer, picks_df):
        orders, summary = position_sizer.calculate_position_sizes(
            picks_df,
            STRONG_BEAR,
            total_capital=100000,
        )

        assert summary["alloc_pct"] == 0.00
        assert orders == []

    def test_positions_small_capital_alloc(self, isolated_position_sizer, picks_df):
        # 混合方案（2026-05-28）：小资金 (<=3000) 锁定全仓避免成本死亡螺旋
        # 即使在震荡 regime（大资金应分档 40%）也保持 100%
        orders, summary = position_sizer.calculate_position_sizes(
            picks_df,
            CHOPPY,
            total_capital=1200,
        )

        assert summary["alloc_pct"] == 1.0

    def test_positions_small_capital_strong_bear(self, isolated_position_sizer, picks_df):
        # 但强熊例外：小资金也空仓 — 危险信号资金少更应躲
        orders, summary = position_sizer.calculate_position_sizes(
            picks_df,
            STRONG_BEAR,
            total_capital=1200,
        )

        assert summary["alloc_pct"] == 0.00
        assert orders == []
