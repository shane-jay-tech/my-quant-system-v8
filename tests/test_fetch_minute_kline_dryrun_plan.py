# -*- coding: utf-8 -*-
"""fetch_minute_kline.py --dry-run-plan 回归（q918-19，q916-04 切片3）。

零网络（把 requests.get 打成必炸来证明没发请求）、零写盘。
运行：python -m pytest tests/test_fetch_minute_kline_dryrun_plan.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_minute_kline as fk  # noqa: E402


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    minute = data / "minute_kline"
    minute.mkdir(parents=True)
    monkeypatch.setattr(fk, "DATA_DIR", str(data))
    monkeypatch.setattr(fk, "MINUTE_DIR", str(minute))
    monkeypatch.setattr(fk, "DRY", False)
    monkeypatch.setattr(fk, "DRY_HITS", [])

    def _no_network(*a, **k):                      # 计划档一旦碰网络就当场炸
        raise AssertionError("dry-run-plan 不应发起任何网络请求")

    monkeypatch.setattr(fk.requests, "get", _no_network)
    return data, minute


def test_plan_lists_missing_codes_from_constant_pool(sandbox, capsys):
    data, minute = sandbox
    for code in ("600519", "000858"):
        (minute / f"{code}.csv").write_text("ts,close\n2026-09-19,10.0\n", encoding="utf-8")

    assert fk.main(["--dry-run-plan"]) == 0
    out = capsys.readouterr().out

    assert "[DRY-RUN-PLAN]" in out
    assert "整文件覆写" in out and "不是追加" in out        # 覆写 vs 追加是本单要点名的口径
    pool = [c.zfill(6) for c in fk.HS300_TOP50[:50]]
    assert f"已存在    : 2 只" in out
    assert f"待补      : {len(pool) - 2} 只" in out


def test_plan_writes_nothing_and_no_marker(sandbox):
    data, minute = sandbox
    before = sorted(p.name for p in minute.iterdir())

    fk.main(["--dry-run-plan"])

    assert sorted(p.name for p in minute.iterdir()) == before
    assert not (data / ".minute_degraded").exists()      # W2 副作用不碰
    assert not (minute / "_fetch_status.json").exists()   # W3 副作用不碰
    assert fk.DRY_HITS == []                              # 计划档不产生"被拦写点"记录


def test_plan_reports_existing_side_effect_files(sandbox, capsys):
    """降级标记在盘时要如实说"在盘"——这正是人最需要看到的一条本地状态。"""
    data, minute = sandbox
    (data / ".minute_degraded").write_text('{"date": "2026-09-18"}', encoding="utf-8")

    fk.main(["--dry-run-plan"])
    out = capsys.readouterr().out

    assert "降级标记 在盘" in out
    assert "状态文件 不在盘" in out
    assert not (minute / "_fetch_status.json").exists()   # 报状态不等于改状态
