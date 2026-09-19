# -*- coding: utf-8 -*-
"""fetch_minute_kline.py --dry-run 切片2 回归（n916x-18，q916-04 设计稿）。

tmp 隔离、零网络。覆盖：dry-run 不写文件／不删文件（W2' 删除短路）／
默认行为等价（写/删/状态照常）。运行：python -m pytest tests/ -k minute_kline -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_minute_kline as fk  # noqa: E402


@pytest.fixture()
def tmp_dirs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir(parents=True)               # 生产 DATA_DIR 恒在盘，测试同口径预建
    minute = data / "minute_kline"
    monkeypatch.setattr(fk, "DATA_DIR", str(data))
    monkeypatch.setattr(fk, "MINUTE_DIR", str(minute))
    monkeypatch.setattr(fk, "DRY", False)
    monkeypatch.setattr(fk, "DRY_HITS", [])
    yield data, minute


def _stats(success=45, total=50):
    return {'success': success, 'failed': total - success, 'eastmoney': success, 'sina': 0, 'eastmoney_30m': 0}


def test_dryrun_save_minute_data_writes_nothing(tmp_dirs, monkeypatch, capsys):
    """dry-run：W1 零写盘＋打印 would-write，仍返回 filepath 供调用方计数。"""
    data, minute = tmp_dirs
    monkeypatch.setattr(fk, "DRY", True)
    df = pd.DataFrame({"close": [1.0, 2.0]})
    got = fk.save_minute_data("600519", df)
    assert got.endswith("600519.csv")
    assert not Path(got).exists()                      # 零写盘
    assert "[DRY-RUN] W1 would-write" in capsys.readouterr().out
    assert fh_w1_recorded()


def fh_w1_recorded():
    return any(w == "W1" for w, _ in fk.DRY_HITS)


def test_default_save_minute_data_writes(tmp_dirs, capsys):
    """默认行为不变：无旗标时照常写文件、无 DRY-RUN 输出。"""
    data, minute = tmp_dirs
    df = pd.DataFrame({"close": [1.0, 2.0]})
    got = fk.save_minute_data("600519", df)
    assert Path(got).exists()
    assert "DRY-RUN" not in capsys.readouterr().out
    assert fk.DRY_HITS == []


def test_dryrun_degrade_marker_not_written(tmp_dirs, monkeypatch, capsys):
    """dry-run：降级分支 W2 短路——.minute_degraded 不落盘、统计打印照常。"""
    data, minute = tmp_dirs
    monkeypatch.setattr(fk, "DRY", True)
    fk._write_fetch_outcomes(_stats(success=30, total=50), 50, ["600519"], 60.0)
    assert not (data / ".minute_degraded").exists()    # W2 短路
    assert not (minute / "_fetch_status.json").exists()  # W3 短路
    out = capsys.readouterr().out
    assert "[DRY-RUN] W2 would-write" in out
    assert "[DRY-RUN] W3 would-write" in out
    assert "Success rate 60%" in out                   # 降级统计照常计算


def test_dryrun_degrade_marker_not_deleted(tmp_dirs, monkeypatch, capsys):
    """dry-run：清除分支 W2' 删除短路——已存在的标记必须原样保留（显式 return 保证不执行 os.remove）。"""
    data, minute = tmp_dirs
    marker = data / ".minute_degraded"
    marker.write_text('{"date": "2026-09-17"}', encoding="utf-8")
    before = marker.read_bytes()
    monkeypatch.setattr(fk, "DRY", True)
    fk._write_fetch_outcomes(_stats(success=50, total=50), 50, [], 100.0)
    assert marker.exists() and marker.read_bytes() == before  # 不删任何文件
    out = capsys.readouterr().out
    assert "would-delete" in out
    assert ("W2'", str(marker)) in fk.DRY_HITS


def test_default_outcomes_write_and_clear(tmp_dirs, capsys):
    """默认行为等价：低成功率写降级标记＋状态 json；高成功率清除既有标记。"""
    data, minute = tmp_dirs
    minute.mkdir(parents=True, exist_ok=True)  # 生产中 MINUTE_DIR 已由 save_minute_data 建好
    fk._write_fetch_outcomes(_stats(success=30, total=50), 50, ["600519"], 60.0)
    assert (data / ".minute_degraded").exists()        # 降级标记照写
    assert (minute / "_fetch_status.json").exists()    # 状态照写
    marker = data / ".minute_degraded"
    fk._write_fetch_outcomes(_stats(success=50, total=50), 50, [], 100.0)
    assert not marker.exists()                         # 达标清除照删
    assert "DRY-RUN" not in capsys.readouterr().out
