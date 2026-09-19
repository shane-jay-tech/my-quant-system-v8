# -*- coding: utf-8 -*-
"""fetch_stock_data.py --dry-run 回归（q918-20，模板复用 q916-04 切片1）。

tmp 隔离、**零网络**（只测写点 helper，不跑 main() 的抓取链）。覆盖：
dry-run 不建目录/不落盘且打印 would-write；不带旗标时行为逐字不变（含 utf-8-sig 与列序）。
运行：python -m pytest tests/ -k stock_data -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_stock_data as fs  # noqa: E402


def _df():
    return pd.DataFrame({"代码": ["600519", "000001"], "涨跌幅": [1.5, -0.5]})


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    data = tmp_path / "data"          # 故意预建，与生产 DATA_DIR 恒在盘同口径
    data.mkdir()
    monkeypatch.setattr(fs, "DATA_DIR", data)
    monkeypatch.setattr(fs, "DRY", False)
    monkeypatch.setattr(fs, "DRY_HITS", [])
    return data


def test_dryrun_writes_nothing_and_says_would_write(tmp_data, monkeypatch, capsys):
    """dry-run：返回目标路径（调用方汇总要用），但**文件不存在**，且 DRY_HITS 记到 W1。"""
    monkeypatch.setattr(fs, "DRY", True)

    got = fs.save_stock_snapshot(_df(), "20260919")

    assert str(got).endswith("stock_20260919.csv")
    assert not Path(got).exists(), "dry-run 不得落盘"
    out = capsys.readouterr().out
    assert "[DRY-RUN] W1 would-write" in out
    assert ("W1", str(got)) in fs.DRY_HITS


def test_dryrun_does_not_create_missing_directory(tmp_path, monkeypatch, capsys):
    """dry-run 连目录都不建（矩阵里 W1 的"写点"含 makedirs，短路要一起短）。"""
    target = tmp_path / "not_created"
    monkeypatch.setattr(fs, "DATA_DIR", target)
    monkeypatch.setattr(fs, "DRY", True)

    fs.save_stock_snapshot(_df(), "20260919")

    assert not target.exists()
    assert "[DRY-RUN] W1 would-write" in capsys.readouterr().out


def test_default_still_writes_the_same_csv(tmp_data, capsys):
    """无旗标：行为逐字不变——建文件、utf-8-sig BOM、列序与 index=False。"""
    got = fs.save_stock_snapshot(_df(), "20260919")

    raw = Path(got).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "生产历史编码是 utf-8-sig，不得被顺手改掉"
    text = raw.decode("utf-8-sig")
    assert text.splitlines()[0] == "代码,涨跌幅"
    assert "600519" in text and "000001" in text
    assert "DRY-RUN" not in capsys.readouterr().out
    assert fs.DRY_HITS == []


def test_default_creates_missing_directory(tmp_path, monkeypatch):
    """无旗标时目录不存在要能自建（makedirs 仍在写分支里，没被 dry-run 改动带走）。"""
    target = tmp_path / "fresh_dir"
    monkeypatch.setattr(fs, "DATA_DIR", target)
    monkeypatch.setattr(fs, "DRY", False)

    got = fs.save_stock_snapshot(_df(), "20260920")

    assert target.is_dir() and Path(got).exists()
