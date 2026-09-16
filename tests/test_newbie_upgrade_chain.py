# -*- coding: utf-8 -*-
"""p911r/0912-05-08：newbie_protection 升级链 characterization 补测。

覆盖 apply_upgrade 的 4 条路径（8e78/19-05 遗留第 3 条）：
未达顶阶顺次升级 / 顶阶返回 None / 重复调用幂等 / phase 记录与推荐语随阶更新。
隔离：STATUS_FILE/DATA_DIR 全部 monkeypatch 到 tmp_path，绝不触碰真实文件。
"""
import json
from pathlib import Path

import pytest

import newbie_protection as np_mod

PHASES = np_mod.PHASE_ORDER


@pytest.fixture
def env(tmp_path, monkeypatch):
    status_file = tmp_path / "newbie_status.json"
    monkeypatch.setattr(np_mod, "STATUS_FILE", str(status_file))
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(np_mod, "DATA_DIR", str(tmp_path))
    return status_file


def _write(status_file: Path, phase: str):
    status_file.write_text(json.dumps({
        "first_start_date": "2026-09-01",
        "current_phase": phase,
        "day_number": 30,
        "phase_start_date": "2026-09-01",
        "recommendation": "",
    }, ensure_ascii=False), encoding="utf-8")


def test_apply_upgrade_advances_one_phase(env):
    """未达顶阶：升级恰好前进一阶，并落盘。"""
    _write(env, PHASES[0])
    new_phase = np_mod.apply_upgrade()
    assert new_phase == PHASES[1]
    on_disk = json.loads(env.read_text(encoding="utf-8"))
    assert on_disk["current_phase"] == PHASES[1]


def test_apply_upgrade_at_top_returns_none(env):
    """已达最高阶：返回 None，阶段不再前进。"""
    top = PHASES[-1]
    _write(env, top)
    assert np_mod.apply_upgrade() is None
    on_disk = json.loads(env.read_text(encoding="utf-8"))
    assert on_disk["current_phase"] == top


def test_apply_upgrade_idempotent_consecutive(env):
    """连续调用逐阶推进且不跳阶（相邻相位差恰为 1）。"""
    _write(env, PHASES[0])
    seen = []
    for _ in range(len(PHASES) - 1):
        seen.append(np_mod.apply_upgrade())
    assert seen == list(PHASES[1:])


def test_apply_upgrade_updates_recommendation(env):
    """升级到 simulation 时刷新推荐语（非空）。"""
    _write(env, PHASES[0])
    np_mod.apply_upgrade()
    on_disk = json.loads(env.read_text(encoding="utf-8"))
    assert on_disk.get("recommendation")
