# -*- coding: utf-8 -*-
"""q920-04：`pipeline --dry-run` 把旗标透传给子步骤 argv。

改前 `core/pipeline.py` 的 dry-run 只打印"将运行哪些步骤"就 return 0（q918-20 遗留 3 / q918-21 §四 的批评点）。
现在：认识 `--dry-run` 的步骤真的拉起来预演，**不认识的一律跳过并点名**（绝不裸跑＝真写盘）。
零真实子进程（`subprocess.run` 全桩）、零网络、tmp_path 隔离。
运行：python -m pytest tests/test_pipeline_dryrun_passthrough.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import pipeline as pl  # noqa: E402


CAPABLE = """import argparse
p = argparse.ArgumentParser()
p.add_argument('--dry-run', action='store_true')
a = p.parse_args()
print('child dry-run' if a.dry_run else 'child real run')
"""

NOT_CAPABLE = """import argparse
p = argparse.ArgumentParser()
p.add_argument('--only-real', action='store_true')
p.parse_args()
print('no dry-run support')
"""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """两个假步骤 + 桩掉的 subprocess，记录每次真实 argv。"""
    (tmp_path / "cap.py").write_text(CAPABLE, encoding="utf-8")
    (tmp_path / "raw.py").write_text(NOT_CAPABLE, encoding="utf-8")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(pl.subprocess, "run", fake_run)
    monkeypatch.setattr(pl, "_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(pl, "_python", lambda: "PY")
    monkeypatch.setattr(pl, "_FLAG_CACHE", {})
    steps = {
        "cap_step": {"script": "cap.py", "tiers": ["beginner"], "schedule": "daily", "label": "认旗标"},
        "raw_step": {"script": "raw.py", "tiers": ["beginner"], "schedule": "daily", "label": "不认旗标"},
    }
    active = [{"id": k, "script": v["script"], "active": True, "reason": ""} for k, v in steps.items()]
    monkeypatch.setattr(pl, "PIPELINE_STEPS", steps)
    monkeypatch.setattr(pl, "list_steps", lambda: list(active))
    monkeypatch.setattr(pl, "SYSTEM_TIER", type("T", (), {"value": "beginner"})())
    return tmp_path, calls


def test_capable_step_is_launched_with_the_flag(sandbox):
    sandbox_path, calls = sandbox

    assert pl.run_all(dry_run=True) == 0

    assert len(calls) == 1, "只该拉起认旗标的那一步"
    assert calls[0][-1] == "--dry-run"                     # 完成标准点名的这条
    assert calls[0][:2] == ["PY", str(sandbox_path / "cap.py")]


def test_incapable_step_is_skipped_not_run_bare(sandbox, capsys):
    _tmp, calls = sandbox

    pl.run_all(dry_run=True)

    out = capsys.readouterr().out
    assert not any(c[1].endswith("raw.py") for c in calls)   # 裸跑＝真写盘，绝对不行
    assert "skip raw_step" in out and "拒绝裸跑" in out
    assert "透传 1 步真预演 | 跳过 1 步" in out


def test_dry_run_does_not_bare_run_anything_even_when_fatal(sandbox, monkeypatch, capsys):
    monkeypatch.setattr(pl, "PIPELINE_STEPS", {
        "cap_step": {"script": "cap.py", "tiers": ["beginner"], "schedule": "daily", "fatal_on_fail": True},
        "raw_step": {"script": "raw.py", "tiers": ["beginner"], "schedule": "daily", "fatal_on_fail": True},
    })

    def boom(cmd, **kw):
        class R:
            returncode = 3

        return R()

    monkeypatch.setattr(pl.subprocess, "run", boom)

    assert pl.run_all(dry_run=True) == 3                     # 预演失败要如实带出 rc，不许粉饰成 0
    out = capsys.readouterr().out
    assert "FATAL" in out
    assert "skip raw_step" not in out                        # fatal 步失败后必须中止，不再往下排后面的步


def test_dry_run_suppresses_retries(sandbox, monkeypatch):
    """预演不该按正式跑那样重试＋睡 retry_wait（fetch_quote 是 retry=3/wait=60）。"""
    monkeypatch.setattr(pl, "PIPELINE_STEPS", {
        "cap_step": {"script": "cap.py", "tiers": ["beginner"], "schedule": "daily", "retry": 3, "retry_wait": 60},
        "raw_step": {"script": "raw.py", "tiers": ["beginner"], "schedule": "daily"},
    })
    calls = []

    def failing(cmd, **kw):
        calls.append(list(cmd))

        class R:
            returncode = 1

        return R()

    monkeypatch.setattr(pl.subprocess, "run", failing)

    assert pl.run_all(dry_run=True) == 1
    assert len(calls) == 1                                   # 只试一次


def test_real_registry_only_passes_to_scripts_that_declare_the_flag():
    """真实注册表口径：6 个透传、其余不碰——钉住"不会把 --dry-run 塞给 strategy.py 这类脚本"。"""
    root = Path(__file__).resolve().parents[1]

    for script in ("fetch_stock_data.py", "fetch_history.py", "fetch_minute_kline.py",
                   "fetch_index.py", "digest.py", "send_to_bark.py"):
        assert pl._step_accepts_flag(str(root / script)), script
    for script in ("strategy.py", "position_sizer.py", "sim_trade.py", "enhanced_backtest.py"):
        assert not pl._step_accepts_flag(str(root / script)), script
    assert not pl._step_accepts_flag(str(root / "does_not_exist.py"))


def test_normal_run_still_passes_no_dry_flag(sandbox, monkeypatch):
    _tmp, calls = sandbox
    # 非预演路径先过交易日与 Alpha Gate 两道门（今天可能是周末），本例只关心 argv 里有没有多塞旗标
    monkeypatch.setattr(pl, "_check_trading_day_inline", lambda: (True, "测试用"))
    monkeypatch.setattr(pl, "_alpha_gate_precheck", lambda **kw: (False, ""))

    pl.run_all()

    assert len(calls) == 2                                                 # 正式跑：两步都启动（含不认旗标的）
    assert all("--dry-run" not in c for c in calls)                        # 默认行为零变化
