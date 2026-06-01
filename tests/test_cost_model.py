"""Tests for cost_model.py — single source of truth for trading costs.

Coverage:
    - slippage by mcap tier (large / mid / small)
    - one-side cost (buy vs sell — sell pays stamp tax)
    - round-trip cost rate matches hand-calculated values
    - small notional (1200 RMB scenario) hits 5 RMB commission floor → 8%+ cost
    - dynamic notional follows regime × picks_count
    - realized_cost_summary parses '成本率' / 毛收益-净收益 columns
    - format_cost_header produces useful banner (no NaN, no emoji)
    - sim_trade and enhanced_backtest now use the same constants (consistency check)
"""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from cost_model import (
    COMMISSION_RATE,
    COMMISSION_MIN,
    STAMP_TAX_RATE,
    SLIP_LARGE,
    SLIP_MID,
    SLIP_SMALL,
    PER_TRADE_NOTIONAL,
    DEFAULT_CAPITAL,
    REGIME_ALLOC,
    CostBreakdown,
    slippage_rate_by_mcap,
    order_cost_amount,
    round_trip_cost,
    get_cost_by_mcap,
    compute_dynamic_notional,
    realized_cost_summary,
    format_cost_header,
    format_cost_examples,
)


# ---------- slippage by mcap ----------

class TestSlippage:
    def test_large_cap(self):
        assert slippage_rate_by_mcap(6e10) == SLIP_LARGE

    def test_large_cap_boundary(self):
        # exactly 500e8 = 50 billion → still large
        assert slippage_rate_by_mcap(5e10) == SLIP_LARGE

    def test_mid_cap(self):
        assert slippage_rate_by_mcap(1e10) == SLIP_MID

    def test_mid_cap_boundary(self):
        # exactly 50e8 = 5 billion → still mid
        assert slippage_rate_by_mcap(5e9) == SLIP_MID

    def test_small_cap(self):
        assert slippage_rate_by_mcap(3e9) == SLIP_SMALL

    def test_zero_mcap_falls_to_small(self):
        # missing mcap = most conservative (small cap)
        assert slippage_rate_by_mcap(0) == SLIP_SMALL

    def test_none_mcap_falls_to_small(self):
        assert slippage_rate_by_mcap(None) == SLIP_SMALL

    def test_garbage_mcap_falls_to_small(self):
        assert slippage_rate_by_mcap("not a number") == SLIP_SMALL


# ---------- single-side cost ----------

class TestOrderCost:
    def test_buy_no_stamp_tax(self):
        # buy 10000 yuan large cap: commission max(3, 5) = 5; no stamp
        # slippage 10000 * 0.001 = 10
        c = order_cost_amount('buy', 10000, 6e10)
        assert c == pytest.approx(5 + 0 + 10, abs=0.01)

    def test_sell_pays_stamp(self):
        c_buy = order_cost_amount('buy', 10000, 6e10)
        c_sell = order_cost_amount('sell', 10000, 6e10)
        # sell extra = stamp tax = 10000 * 0.0005 = 5
        assert c_sell - c_buy == pytest.approx(5, abs=0.01)

    def test_zero_amount(self):
        assert order_cost_amount('buy', 0, 1e10) == 0

    def test_negative_amount(self):
        assert order_cost_amount('buy', -100, 1e10) == 0

    def test_min_commission_floor(self):
        # 200 yuan * 0.0003 = 0.06 < 5 floor; should pay 5
        c = order_cost_amount('buy', 200, 1e10)
        # commission = 5, stamp = 0, slip = 200 * 0.002 = 0.4
        assert c == pytest.approx(5 + 0 + 0.4, abs=0.01)


# ---------- round-trip cost (the user-facing one) ----------

class TestRoundTrip:
    def test_breakdown_returns_dataclass(self):
        cb = round_trip_cost(1e10, 1000)
        assert isinstance(cb, CostBreakdown)
        assert cb.notional == 1000
        assert cb.total > 0
        assert cb.rate > 0

    def test_small_notional_hits_floor(self):
        # 1200 RMB user, 200 yuan per trade, mid-cap
        cb = round_trip_cost(1e10, 200)
        # commission 5*2=10, stamp 200*0.0005=0.1, slip 200*0.002*2=0.8
        # total 10.9 / 200 = 5.45%
        assert cb.pct == pytest.approx(5.45, abs=0.01)

    def test_large_notional_below_floor(self):
        # 100k notional: commission 100k*0.0003 > 5, no floor
        cb = round_trip_cost(6e10, 100000)
        # commission (100k*0.0003)*2=60, stamp 50, slip 100k*0.001*2=200
        # total 310 / 100k = 0.31%
        assert cb.pct == pytest.approx(0.31, abs=0.01)

    def test_default_notional_when_none(self):
        cb = round_trip_cost(1e10, None)
        assert cb.notional == PER_TRADE_NOTIONAL

    def test_get_cost_by_mcap_compat(self):
        # backwards-compat: returns rate as 0~1, not %
        rate = get_cost_by_mcap(1e10, 200)
        cb = round_trip_cost(1e10, 200)
        assert rate == pytest.approx(cb.rate, abs=1e-10)


# ---------- dynamic notional ----------

class TestDynamicNotional:
    def test_strong_bull_5_picks(self):
        # 2400 * 0.80 / 5 = 384
        n = compute_dynamic_notional('强牛', 5)
        assert n == pytest.approx(384, abs=0.5)

    def test_choppy_3_picks(self):
        # 2400 * 0.40 / 3 = 320
        n = compute_dynamic_notional('震荡', 3)
        assert n == pytest.approx(320, abs=0.5)

    def test_strong_bear_returns_default(self):
        # alloc=0 → return PER_TRADE_NOTIONAL
        n = compute_dynamic_notional('强熊', 5)
        assert n == PER_TRADE_NOTIONAL

    def test_unknown_regime_falls_to_choppy(self):
        n = compute_dynamic_notional('unknown', 3)
        assert n == pytest.approx(2400 * 0.40 / 3, abs=0.5)

    def test_min_floor_100(self):
        # 2400 * 0.20 / 100 picks would be tiny, but we floor at 100
        n = compute_dynamic_notional('弱熊', 100)
        assert n >= 100

    def test_zero_picks_returns_default(self):
        n = compute_dynamic_notional('强牛', 0)
        assert n == PER_TRADE_NOTIONAL


# ---------- realized cost summary (the report-header data source) ----------

class TestRealizedCostSummary:
    def test_empty_trades_returns_unavailable(self):
        s = realized_cost_summary(None)
        assert s['available'] is False
        s = realized_cost_summary(pd.DataFrame())
        assert s['available'] is False

    def test_from_cost_rate_column(self):
        df = pd.DataFrame({'成本率': [3.0, 5.0, 7.0]})
        s = realized_cost_summary(df)
        assert s['available'] is True
        assert s['mean_pct'] == pytest.approx(5.0)
        assert s['min_pct'] == 3.0
        assert s['max_pct'] == 7.0
        assert s['n_trades'] == 3

    def test_from_gross_minus_net(self):
        df = pd.DataFrame({'毛收益': [10.0, 8.0], '净收益': [5.0, 2.0]})
        s = realized_cost_summary(df)
        assert s['available'] is True
        assert s['mean_pct'] == pytest.approx(5.5)

    def test_missing_columns_returns_unavailable(self):
        df = pd.DataFrame({'foo': [1, 2]})
        s = realized_cost_summary(df)
        assert s['available'] is False


# ---------- format helpers ----------

class TestFormatHeader:
    def test_with_data(self):
        s = {'available': True, 'mean_pct': 7.84, 'min_pct': 2.81, 'max_pct': 12.40, 'n_trades': 123}
        h = format_cost_header(s)
        assert '7.84%' in h
        assert '2.81%' in h
        assert '12.40%' in h
        assert '123' in h
        assert '真实成本' in h

    def test_without_data(self):
        s = {'available': False}
        h = format_cost_header(s)
        assert 'N/A' in h
        assert '无交易' in h

    def test_no_emoji_in_header(self):
        s = {'available': True, 'mean_pct': 5.0, 'min_pct': 3.0, 'max_pct': 7.0, 'n_trades': 10}
        h = format_cost_header(s)
        for ch in h:
            cp = ord(ch)
            assert not (0x1F300 <= cp <= 0x1FAFF), 'emoji in cost header'


class TestFormatExamples:
    def test_returns_three_tiers(self):
        ex = format_cost_examples(200)
        assert '大盘' in ex
        assert '中盘' in ex
        assert '小盘' in ex


# ---------- consistency check across modules ----------

class TestModuleConsistency:
    """Lock-in test: enhanced_backtest, sim_trade, walk_forward all use cost_model
    constants. If anyone re-introduces hardcoded 0.00025 / 0.0003, this trips.
    """

    def test_constants_match_config(self):
        # cost_model loads from system_config.json on import; canary values
        assert COMMISSION_RATE == 0.0003
        assert COMMISSION_MIN == 5.0
        assert STAMP_TAX_RATE == 0.0005

    def test_sim_trade_uses_cost_model(self):
        import sim_trade
        assert sim_trade._COMM_RATE == COMMISSION_RATE
        assert sim_trade._COMM_MIN == COMMISSION_MIN
        assert sim_trade._STAMP_RATE == STAMP_TAX_RATE

    def test_enhanced_backtest_uses_cost_model(self):
        import enhanced_backtest
        # the function reference is the same one (re-exported from cost_model)
        from cost_model import get_cost_by_mcap as cm_func
        assert enhanced_backtest.get_cost_by_mcap is cm_func

    def test_walk_forward_uses_cost_model(self):
        import walk_forward
        # walk_forward imports compute_dynamic_notional and get_cost_by_mcap
        from cost_model import get_cost_by_mcap as cm_func
        assert walk_forward.get_cost_by_mcap is cm_func


# ---------- 2400 RMB scenario sanity ----------

class TestSmallCapitalScenario:
    """User's actual setup: 2400 RMB, 5 RMB commission floor.

    These numbers should make it crystal clear why the previous 0.2% report
    header was misleading.
    """

    def test_choppy_3picks_real_cost_above_3pct(self):
        # 2400 * 40% / 3 = 320 yuan per trade, mid-cap ≈ 3.58%
        n = compute_dynamic_notional('震荡', 3)
        rate = get_cost_by_mcap(1e10, n)
        assert rate > 0.03

    def test_strong_bull_5picks_real_cost_above_3pct(self):
        n = compute_dynamic_notional('强牛', 5)
        rate = get_cost_by_mcap(1e10, n)
        # 384 yuan: about 3.05%
        assert rate > 0.03

    def test_legacy_1200_yuan_still_worse(self, monkeypatch):
        """历史口径回归：1200 元时同样 5 元 floor，单笔成本仍 >5%。"""
        import cost_model as cm
        monkeypatch.setattr(cm, "DEFAULT_CAPITAL", 1200.0)
        n = cm.compute_dynamic_notional('震荡', 3)
        rate = cm.get_cost_by_mcap(1e10, n)
        assert rate > 0.05

    def test_legacy_02pct_was_a_lie(self):
        """The OLD `COST=0.002` value (0.2%) was wrong by an order of magnitude
        for any realistic 2400-yuan scenario. This test documents the bug.
        """
        legacy_cost = 0.002
        actual = get_cost_by_mcap(1e10, 200)  # typical small-cap trade
        assert actual > legacy_cost * 10  # at least 10x higher
