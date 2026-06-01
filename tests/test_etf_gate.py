"""Tests for etf_gate.py — the 'don't bother stock-picking, buy ETF' banner.

Coverage:
    - parsing all known excess-return text formats
    - severity classification at the boundaries (0 / 1)
    - data-freshness downgrade to 'stale'
    - silent 'unknown' when no source file exists
    - banner formatting (severe/warning/stale wrap with separators; normal is bare; unknown empty)
    - banner contains no emoji and no People-Analytics framing
"""
import os
import sys
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from etf_gate import (
    EtfGateResult,
    SEVERE_THRESHOLD_PCT,
    WARNING_THRESHOLD_PCT,
    _parse_excess_from_text,
    evaluate_etf_gate,
    format_gate_banner,
)


# ---------- parsing ----------

class TestParseExcess:
    def test_bold_format(self):
        assert _parse_excess_from_text("**超额收益**: -0.71%") == -0.71

    def test_plain_format(self):
        assert _parse_excess_from_text("超额收益: +1.23%") == 1.23

    def test_full_width_colon(self):
        assert _parse_excess_from_text("超额收益：-0.5%") == -0.5

    def test_table_vs_hs300_format(self):
        # the form benchmark_comparison.py writes
        assert _parse_excess_from_text("| 超额（vs HS300）| -0.71% |") == -0.71

    def test_no_match_returns_none(self):
        assert _parse_excess_from_text("plain text without metric") is None

    def test_picks_first_match_when_multiple(self):
        text = "前文 **超额收益**: -0.71%\n后文 超额收益: +9.99%"
        assert _parse_excess_from_text(text) == -0.71


# ---------- evaluate_etf_gate ----------

def _write_honest_eval(base: Path, excess_str: str, mtime_age_days: float = 0.0):
    """Write a minimal honest_evaluation.md with the given excess line."""
    results = base / "results"
    results.mkdir(parents=True, exist_ok=True)
    p = results / "honest_evaluation.md"
    p.write_text(
        f"# 策略诚实评估\n\n## 基准对比\n- **超额收益**: {excess_str}\n",
        encoding="utf-8",
    )
    if mtime_age_days > 0:
        new_mtime = time.time() - mtime_age_days * 86400
        os.utime(p, (new_mtime, new_mtime))
    return p


def _write_market_data(base: Path, hs300_last_date, stock_dates):
    """写出 data/stock_YYYYMMDD.csv（文件名供交易日历用）+ data/hs300_index.csv。

    v8.7：etf_gate 的陈旧判定基于真实行情数据日期，所以测试要造出
    "本地最新交易日"（stock_*.csv 文件名）与 hs300_index.csv 最新日期。
    日期参数格式 'YYYY-MM-DD'。
    """
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    for d in stock_dates:
        (data / f"stock_{d.replace('-', '')}.csv").write_text(
            "代码,收盘\n000001,10\n", encoding="utf-8"
        )
    (data / "hs300_index.csv").write_text(
        "日期,收盘\n2025-07-23,4000.0\n" + f"{hs300_last_date},4800.0\n",
        encoding="utf-8",
    )


class TestEvaluateGate:
    def test_severe_when_negative(self, tmp_path):
        _write_honest_eval(tmp_path, "-0.71%")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "severe"
        assert r.excess_pct == -0.71
        assert "建议直接买 ETF" in r.message
        assert "510300" in r.message

    def test_severe_at_zero_boundary(self, tmp_path):
        _write_honest_eval(tmp_path, "0.0%")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "severe"  # excess <= 0 -> severe

    def test_warning_when_below_friction(self, tmp_path):
        _write_honest_eval(tmp_path, "+0.5%")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "warning"
        assert "扣完佣金" in r.message or "持平" in r.message

    def test_warning_at_one_percent_boundary(self, tmp_path):
        _write_honest_eval(tmp_path, "+1.0%")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "warning"  # 0 < excess <= 1 -> warning

    def test_normal_when_above_friction(self, tmp_path):
        _write_honest_eval(tmp_path, "+2.5%")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "normal"
        assert r.excess_pct == 2.5

    def test_unknown_when_no_data(self, tmp_path):
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "unknown"
        assert r.excess_pct is None
        assert r.message == ""

    def test_falls_back_to_benchmark_report(self, tmp_path):
        # primary missing, secondary present
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        (reports / "benchmark_20260101.md").write_text(
            "# v8 vs HS300\n超额收益: -2.0%\n", encoding="utf-8",
        )
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "severe"
        assert r.excess_pct == -2.0
        assert "benchmark_20260101.md" in r.source

    def test_picks_newest_benchmark_report(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir(parents=True)
        (reports / "benchmark_20260101.md").write_text("超额收益: -5.0%\n", encoding="utf-8")
        (reports / "benchmark_20260201.md").write_text("超额收益: +3.0%\n", encoding="utf-8")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.excess_pct == 3.0  # newest wins (sorted desc by name)

    def test_stale_when_market_data_lags(self, tmp_path):
        # v8.7: 行情基线数据(hs300_index.csv)落后本地最新交易日很多 → stale
        # （基于真实数据日期判定，不再看报告文件 mtime）
        _write_honest_eval(tmp_path, "+5.0%")
        _write_market_data(
            tmp_path,
            hs300_last_date="2026-05-22",
            stock_dates=["2026-06-12", "2026-06-15", "2026-06-16"],
        )
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "stale"
        assert "未更新" in r.message
        assert "交易日" in r.message
        assert r.excess_pct == 5.0  # 数字仍解析，只是标记陈旧

    def test_fresh_market_data_not_stale(self, tmp_path):
        # hs300 最新日期 == 本地最新交易日 → 不陈旧 → 按超额分级
        _write_honest_eval(tmp_path, "+5.0%")
        _write_market_data(
            tmp_path,
            hs300_last_date="2026-06-16",
            stock_dates=["2026-06-12", "2026-06-15", "2026-06-16"],
        )
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "normal"

    def test_no_market_data_does_not_false_alarm(self, tmp_path):
        # 缺 hs300_index.csv → 无法判定 → 不报 stale（宁可不报不误报），退回按超额分级
        _write_honest_eval(tmp_path, "-0.71%")
        r = evaluate_etf_gate(str(tmp_path))
        assert r.severity == "severe"


# ---------- banner formatting ----------

class TestFormatBanner:
    def test_severe_wrapped_in_separators(self):
        r = EtfGateResult("severe", "[ETF闸门] 测试消息", -1.0, "test")
        b = format_gate_banner(r)
        assert b.startswith("=" * 32)
        assert b.endswith("=" * 32)
        assert "[ETF闸门] 测试消息" in b

    def test_warning_wrapped_in_separators(self):
        r = EtfGateResult("warning", "[ETF闸门] 警告", 0.5, "test")
        b = format_gate_banner(r)
        assert "=" * 32 in b

    def test_stale_wrapped_in_separators(self):
        r = EtfGateResult("stale", "[ETF闸门] 数据过期", None, "test")
        b = format_gate_banner(r)
        assert "=" * 32 in b

    def test_normal_no_separator(self):
        r = EtfGateResult("normal", "[ETF闸门] 超额 +2%", 2.0, "test")
        b = format_gate_banner(r)
        assert "=" * 32 not in b
        assert b == "[ETF闸门] 超额 +2%"

    def test_unknown_returns_empty(self):
        r = EtfGateResult("unknown", "", None, "none")
        assert format_gate_banner(r) == ""

    def test_banner_contains_no_emoji(self):
        # User explicitly does not want emoji in console / Bark output.
        # Spot-check common emoji ranges.
        for sev in ("severe", "warning", "normal", "stale"):
            msg = "[ETF闸门] sample"
            r = EtfGateResult(sev, msg, 0.0, "test")
            b = format_gate_banner(r)
            for ch in b:
                cp = ord(ch)
                assert not (0x1F300 <= cp <= 0x1FAFF), f"emoji found in {sev}"

    def test_should_show_banner_property(self):
        for sev in ("severe", "warning", "stale"):
            assert EtfGateResult(sev, "x", 0.0, "t").should_show_banner is True
        for sev in ("normal", "unknown"):
            assert EtfGateResult(sev, "x", 0.0, "t").should_show_banner is False


# ---------- thresholds ----------

class TestThresholdConstants:
    """Lock the threshold contract so future edits to etf_gate trip a test."""

    def test_severe_threshold_is_zero(self):
        assert SEVERE_THRESHOLD_PCT == 0.0

    def test_warning_threshold_is_one_percent(self):
        # 1200 RMB friction is ~0.83% commission round-trip + 0.05% stamp ≈ 0.9%.
        # 1.0% is the smallest "round" number that covers friction.
        assert WARNING_THRESHOLD_PCT == 1.0
