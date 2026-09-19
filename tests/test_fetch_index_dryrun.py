# -*- coding: utf-8 -*-
"""fetch_index.py --dry-run 回归（q918-20，模板复用 q916-04 切片1）。

**零网络**：monkeypatch `_fetch_sina_hs300` 喂固定记录，只测合并与写点。覆盖：
dry-run 不落盘、不留 .tmp、打印 would-write；无旗标时合并语义与原子替换逐字不变。
运行：python -m pytest tests/ -k fetch_index -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_index as fi  # noqa: E402


def _recs():
    return [{"日期": "2026-09-18", "收盘": 4000.0}, {"日期": "2026-09-19", "收盘": 4010.5}]


@pytest.fixture()
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "_fetch_sina_hs300", lambda *a, **k: _recs())
    monkeypatch.setattr(fi, "DRY", False)
    monkeypatch.setattr(fi, "DRY_HITS", [])
    return tmp_path / "data"


def test_dryrun_writes_nothing_and_leaves_no_tmp(offline, monkeypatch, capsys):
    """dry-run：返回 True（合并确实成功），但 csv 与 .tmp 都不落盘。"""
    monkeypatch.setattr(fi, "DRY", True)
    offline.mkdir(parents=True)

    assert fi.update_hs300_index(data_dir=str(offline)) is True
    path = offline / fi.INDEX_FILE
    assert not path.exists(), "dry-run 不得落盘"
    assert not Path(str(path) + ".tmp").exists(), "dry-run 不得留下 .tmp 半成品"
    out = capsys.readouterr().out
    assert "[DRY-RUN] W1 would-write" in out
    assert "would-write: 1 个写点" in out
    assert ("W1", str(path)) in fi.DRY_HITS


def test_dryrun_does_not_create_data_dir(offline, monkeypatch, capsys):
    """dry-run 连数据目录都不建（矩阵的写点含 makedirs）。"""
    monkeypatch.setattr(fi, "DRY", True)

    fi.update_hs300_index(data_dir=str(offline))

    assert not offline.exists()
    assert "[DRY-RUN] W1 would-write" in capsys.readouterr().out


def test_default_writes_merged_csv_atomically(offline, capsys):
    """无旗标：落盘、无 .tmp 残留、末行是最新日 ⇒ 原子替换与排序不变。"""
    assert fi.update_hs300_index(data_dir=str(offline)) is True
    path = offline / fi.INDEX_FILE
    assert path.exists() and not Path(str(path) + ".tmp").exists()
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "日期,收盘"
    assert lines[-1].startswith("2026-09-19")
    assert "DRY-RUN" not in capsys.readouterr().out


def test_default_keeps_history_rows_and_replaces_same_day(offline):
    """合并语义不受本次改动影响：窗口外的历史行保留，同日以新数据为准（keep='last'）。"""
    offline.mkdir(parents=True)
    path = offline / fi.INDEX_FILE
    path.write_text("日期,收盘\n2026-01-05,3900.0\n2026-09-18,3999.0\n", encoding="utf-8")

    assert fi.update_hs300_index(data_dir=str(offline)) is True

    body = path.read_text(encoding="utf-8-sig").replace("\r", "").strip().splitlines()
    assert body[0] == "日期,收盘"
    assert "2026-01-05,3900.0" in body                      # 历史行保住（不被本次窗口覆盖）
    assert [l for l in body if l.startswith("2026-09-18")] == ["2026-09-18,4000.0"]  # 同日取新值
    assert body[-1].startswith("2026-09-19")
