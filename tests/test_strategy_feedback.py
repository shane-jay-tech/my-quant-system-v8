# -*- coding: utf-8 -*-
import os
import json
import pytest
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import strategy_feedback


@pytest.fixture
def isolated_strategy_feedback(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    sim_dir = tmp_path / "sim_results"

    data_dir.mkdir()
    sim_dir.mkdir()

    monkeypatch.setattr(strategy_feedback, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(strategy_feedback, "SIM_DIR", str(sim_dir))
    monkeypatch.setattr(strategy_feedback, "BASE_DIR", str(tmp_path))

    return {
        "tmp_path": tmp_path,
        "data_dir": data_dir,
        "sim_dir": sim_dir,
    }


@pytest.fixture
def default_adjustments():
    return {
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.20,
        "max_hold_days": 10,
        "position_size_mult": 1.0,
        "alert_only": True,
        "actions": [],
    }


def make_cold_start_data(n_good, n_bad):
    good = [{"盈亏%": 5.0, "出场原因": "止盈"}] * n_good
    bad = [{"盈亏%": -3.0, "出场原因": "死叉"}] * n_bad
    return {
        "trades": good + bad,
        "good": good,
        "bad": bad,
        "manifest": {"date_range": "test"},
        "is_cold_start": True,
    }


def read_risk_config(data_dir):
    with open(data_dir / "risk_config.json", "r", encoding="utf-8") as f:
        return json.load(f)


class TestAnalyzeRiskAdjustments:
    def test_analyze_defaults(self, isolated_strategy_feedback):
        adjustments = strategy_feedback.analyze_risk_adjustments()

        # warnings may contain informational messages when no data exists; check key values only
        assert adjustments["stop_loss_pct"] == -0.08
        assert adjustments["take_profit_pct"] == 0.20
        assert adjustments["max_hold_days"] == 10
        assert adjustments["position_size_mult"] == 1.0
        assert adjustments["alert_only"] is True
        assert adjustments["actions"] == []
        assert adjustments["trade_source"] == "none"

    def test_analyze_required_keys(self, isolated_strategy_feedback):
        adjustments = strategy_feedback.analyze_risk_adjustments()

        required = {
            "stop_loss_pct",
            "take_profit_pct",
            "max_hold_days",
            "position_size_mult",
            "alert_only",
            "warnings",
            "actions",
            "data_source",
            "trade_source",
        }

        assert required.issubset(adjustments.keys())

    def test_analyze_stop_loss_unchanged(self, isolated_strategy_feedback):
        cold_start_data = make_cold_start_data(n_good=9, n_bad=21)

        adjustments = strategy_feedback.analyze_risk_adjustments(
            cold_start_data=cold_start_data
        )

        assert adjustments["stop_loss_pct"] == -0.08
        assert any("[Alert-only]" in action for action in adjustments["actions"])

    def test_analyze_position_mult_unchanged(self, isolated_strategy_feedback):
        cold_start_data = make_cold_start_data(n_good=9, n_bad=21)

        adjustments = strategy_feedback.analyze_risk_adjustments(
            cold_start_data=cold_start_data
        )

        assert adjustments["position_size_mult"] == 1.0
        assert any("[Alert-only]" in action for action in adjustments["actions"])

    def test_analyze_below_threshold(self, isolated_strategy_feedback):
        cold_start_data = make_cold_start_data(n_good=3, n_bad=7)

        adjustments = strategy_feedback.analyze_risk_adjustments(
            cold_start_data=cold_start_data
        )

        assert len(adjustments["actions"]) == 0


class TestApplyRiskAdjustments:
    def test_apply_write_read(
        self,
        isolated_strategy_feedback,
        default_adjustments,
    ):
        data_dir = isolated_strategy_feedback["data_dir"]

        strategy_feedback.apply_risk_adjustments(default_adjustments)

        config = read_risk_config(data_dir)

        assert config["stop_loss_pct"] == -0.08
        assert config["take_profit_pct"] == 0.20
        assert config["max_hold_days"] == 10
        assert config["position_size_mult"] == 1.0
        assert config["alert_only"] is True
        assert "updated" in config

    def test_apply_no_tmp_residue(
        self,
        isolated_strategy_feedback,
        default_adjustments,
    ):
        data_dir = isolated_strategy_feedback["data_dir"]

        strategy_feedback.apply_risk_adjustments(default_adjustments)

        assert (data_dir / "risk_config.json").exists()
        assert not (data_dir / "risk_config.json.tmp").exists()
        assert not list(data_dir.glob("*.tmp"))

    def test_apply_no_archive_first_write(
        self,
        isolated_strategy_feedback,
        default_adjustments,
    ):
        data_dir = isolated_strategy_feedback["data_dir"]

        strategy_feedback.apply_risk_adjustments(default_adjustments)

        history_dir = data_dir / "risk_config_history"
        archives = list(history_dir.glob("*.json")) if history_dir.exists() else []

        assert archives == []

    def test_apply_creates_archive_second_write(
        self,
        isolated_strategy_feedback,
        default_adjustments,
    ):
        data_dir = isolated_strategy_feedback["data_dir"]

        strategy_feedback.apply_risk_adjustments(default_adjustments)

        updated_adjustments = dict(default_adjustments)
        updated_adjustments["max_hold_days"] = 12
        strategy_feedback.apply_risk_adjustments(updated_adjustments)

        history_dir = data_dir / "risk_config_history"
        archives = list(history_dir.glob("*.json"))

        assert len(archives) >= 1
        assert read_risk_config(data_dir)["max_hold_days"] == 12

    def test_apply_config_has_alert_only(
        self,
        isolated_strategy_feedback,
        default_adjustments,
    ):
        data_dir = isolated_strategy_feedback["data_dir"]

        strategy_feedback.apply_risk_adjustments(default_adjustments)

        config = read_risk_config(data_dir)

        assert "alert_only" in config
        assert config["alert_only"] is True

    def test_apply_cleans_old_archive(
        self,
        isolated_strategy_feedback,
        default_adjustments,
    ):
        data_dir = isolated_strategy_feedback["data_dir"]

        strategy_feedback.apply_risk_adjustments(default_adjustments)

        history_dir = data_dir / "risk_config_history"
        history_dir.mkdir(exist_ok=True)

        old_archive = history_dir / "risk_config_19990101_000000.json"
        old_archive.write_text(
            json.dumps({"old": True}, ensure_ascii=False),
            encoding="utf-8",
        )

        old_mtime = (datetime.now() - timedelta(days=31)).timestamp()
        os.utime(old_archive, (old_mtime, old_mtime))

        updated_adjustments = dict(default_adjustments)
        updated_adjustments["take_profit_pct"] = 0.25
        strategy_feedback.apply_risk_adjustments(updated_adjustments)

        assert not old_archive.exists()
        assert (data_dir / "risk_config.json").exists()
        assert read_risk_config(data_dir)["take_profit_pct"] == 0.25
