# -*- coding: utf-8 -*-
"""fetch_history.py --dry-run 切片1 回归（n916x-17，q916-04 设计稿）。

tmp 隔离、零网络（EM 快路径三点 stub）。覆盖：
dry-run 下零写盘＋逐写点打印／默认路径不变／W3 短路与默认去重语义。
运行：python -m pytest tests/test_fetch_history_dryrun.py -q
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_history as fh  # noqa: E402


@pytest.fixture()
def tmp_hist(tmp_path, monkeypatch):
    p = tmp_path / "history.csv"
    # HISTORY_FILE 注入 str 口径（与 W3 'HISTORY_FILE + .tmp' 历史语义一致）；断言用 Path
    monkeypatch.setattr(fh, "HISTORY_FILE", str(p))
    monkeypatch.setattr(fh, "DRY", False)
    monkeypatch.setattr(fh, "DRY_HITS", [])
    yield p


def _seed(hist: Path, rows=3):
    df = pd.DataFrame({"代码": [str(100 + i) for i in range(rows)],
                       "日期": ["2026-09-15"] * rows, "收盘": [1.0] * rows})
    df.to_csv(hist, index=False, encoding="utf-8-sig")
    return df


def test_dryrun_save_increment_writes_nothing(tmp_hist, monkeypatch, capsys):
    """dry-run：save_increment 零写盘＋打印 W2 would-append。"""
    monkeypatch.setattr(fh, "DRY", True)
    df = pd.DataFrame({"代码": ["001"], "日期": ["2026-09-16"], "收盘": [2.0]})
    fh.save_increment(df)
    assert not tmp_hist.exists()                       # 零写盘
    out = capsys.readouterr().out
    assert "[DRY-RUN] W2 would-append" in out          # 写点打印
    assert ("W2", str(tmp_hist)) in fh.DRY_HITS


def test_default_save_increment_unchanged(tmp_hist, monkeypatch, capsys):
    """默认路径不变：无旗标时增量照常落盘、无 DRY-RUN 输出。"""
    assert fh.DRY is False
    df = pd.DataFrame({"代码": ["001"], "日期": ["2026-09-16"], "收盘": [2.0]})
    fh.save_increment(df)
    assert tmp_hist.exists()
    assert "DRY-RUN" not in capsys.readouterr().out
    assert fh.DRY_HITS == []


def test_dryrun_fastpath_intercepts_w0_w1(tmp_hist, monkeypatch, capsys):
    """dry-run：EM 快路径拦截 W0 备份与 W1 追加（零 .bak、原文件不变、仍返回内存代码集）。"""
    _seed(tmp_hist)
    before = tmp_hist.read_bytes()
    monkeypatch.setattr(fh, "DRY", True)
    codes = [f"9{i:03d}" for i in range(60)]
    day = "2026-09-16"
    em_df = pd.DataFrame({"代码": codes, "日期": [day] * 60, "收盘": [3.0] * 60})
    monkeypatch.setattr(fh, "fetch_em_snapshot", lambda: object())
    monkeypatch.setattr(fh, "em_snapshot_rows", lambda diff, day_: em_df)
    monkeypatch.setattr(fh, "em_vs_sina_crosscheck", lambda df, f: (True, "ok"))
    latest = {c: day for c in codes}
    got = fh.try_em_fastpath(set(codes), latest, day, "sina_snapshot_dummy")
    assert got is not None and len(got) == 60          # 内存返回不变
    assert not Path(str(tmp_hist) + ".bak").exists()   # W0 备份被拦
    assert tmp_hist.read_bytes() == before             # W1 零写盘
    out = capsys.readouterr().out
    assert "[DRY-RUN] W0 would-backup" in out
    assert "[DRY-RUN] W1 would-append" in out
    assert "DRY: would append 60 rows" in out


def test_dryrun_final_dedupe_short_circuit(tmp_hist, monkeypatch, capsys):
    """dry-run：W3 短路——重复行原样保留、无 .tmp 残留、打印 would-rewrite。"""
    df = pd.DataFrame({"代码": ["001", "001"], "日期": ["2026-09-15", "2026-09-15"],
                       "收盘": [1.0, 1.0]})
    df.to_csv(tmp_hist, index=False, encoding="utf-8-sig")
    before = tmp_hist.read_bytes()
    monkeypatch.setattr(fh, "DRY", True)
    fh.final_dedupe()
    assert tmp_hist.read_bytes() == before             # 零改写
    assert not Path(str(tmp_hist) + ".tmp").exists()
    out = capsys.readouterr().out
    assert "[DRY-RUN] W3 would-rewrite" in out
    assert "1 rows" in out                             # 报告将压平为的行数（2 重复行→1）


def test_default_final_dedupe_rewrites(tmp_hist, monkeypatch, capsys):
    """默认路径不变：无旗标时 W3 去重照常执行（str 路径语义）。"""
    df = pd.DataFrame({"代码": ["001", "001"], "日期": ["2026-09-15", "2026-09-15"],
                       "收盘": [1.0, 1.0]})
    df.to_csv(tmp_hist, index=False, encoding="utf-8-sig")
    fh.final_dedupe()
    after = pd.read_csv(tmp_hist, dtype={"代码": str})
    assert len(after) == 1                             # 去重生效
    assert "DRY-RUN" not in capsys.readouterr().out
