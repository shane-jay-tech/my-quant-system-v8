"""Tests for walk_forward reproducibility snapshot wiring (2026-06-17).
Adopted from psy-analysis snapshot pattern via scripts/common/snapshot."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import walk_forward as wf


def _fake_results():
    return [
        {"window": 1, "train_start": "2026-01-01", "train_end": "2026-04-01",
         "test_start": "2026-04-01", "test_end": "2026-05-01",
         "best_params": {"MA_LONG": 30, "RSI_LOW": 30, "RSI_HIGH": 70},
         "train_score": 0.05, "test_score": 0.01, "test_trades": 8, "overfit_ratio": 0.8},
    ]


def test_build_snapshot_deterministic_for_same_inputs():
    hist = pd.DataFrame({"代码": ["000001", "000002"], "收盘": [10.0, 20.0]})
    s1 = wf.build_wf_snapshot(hist, _fake_results())
    s2 = wf.build_wf_snapshot(hist, _fake_results())
    if s1 is None:  # snapshot module unavailable -> skip
        return
    assert s1["data_hash"] == s2["data_hash"]
    assert s1["param_hash"] == s2["param_hash"]


def test_snapshot_changes_with_data():
    a = wf.build_wf_snapshot(pd.DataFrame({"x": [1, 2]}), _fake_results())
    b = wf.build_wf_snapshot(pd.DataFrame({"x": [1, 3]}), _fake_results())
    if a is None:
        return
    assert a["data_hash"] != b["data_hash"]


def test_report_embeds_snapshot_and_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(wf, "RESULTS_DIR", str(tmp_path))
    hist = pd.DataFrame({"代码": ["000001"], "收盘": [10.0]})
    snap = wf.build_wf_snapshot(hist, _fake_results())
    wf.generate_report(_fake_results(), wf_snapshot=snap)

    md = list(tmp_path.glob("walk_forward_*.md"))
    assert md, "report md not written"
    text = md[0].read_text(encoding="utf-8")
    if snap is not None:
        assert "复现快照" in text and snap["snapshot_id"] in text
        sidecar = list(tmp_path.glob("walk_forward_*.snapshot.json"))
        assert sidecar, "snapshot sidecar not written"
        loaded = json.loads(sidecar[0].read_text(encoding="utf-8"))
        assert loaded["snapshot_id"] == snap["snapshot_id"]
        assert "result" in loaded and "windows" in loaded["result"]


def test_report_without_snapshot_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(wf, "RESULTS_DIR", str(tmp_path))
    wf.generate_report(_fake_results(), wf_snapshot=None)
    md = list(tmp_path.glob("walk_forward_*.md"))
    assert md and "Walk-Forward 验证报告" in md[0].read_text(encoding="utf-8")
