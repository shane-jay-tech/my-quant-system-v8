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


def _inject(monkeypatch, p, as_path):
    monkeypatch.setattr(fh, "HISTORY_FILE", p if as_path else str(p))
    monkeypatch.setattr(fh, "DRY", False)
    monkeypatch.setattr(fh, "DRY_HITS", [])


@pytest.fixture()
def tmp_hist(tmp_path, monkeypatch):
    """按**生产口径**注入：生产里 HISTORY_FILE = DATA_DIR / 'history.csv'，是 Path。

    q920（2026-09-20）：这个 fixture 过去注入 str(p)，注释还写着「与 W3
    HISTORY_FILE + .tmp 历史语义一致」——正是这个口径差让  HISTORY_FILE + '.tmp'
    的 TypeError 在测试里永远看不到（str + str 恰好能过），于是最终去重
    **长期没有真正执行过**，history.csv 里积了 48.6 万行重复。
    测试必须用生产的类型口径；字符串口径另开一个 fixture 单独覆盖。
    """
    p = tmp_path / "history.csv"
    _inject(monkeypatch, p, as_path=True)
    yield p


@pytest.fixture()
def tmp_hist_str(tmp_path, monkeypatch):
    """字符串注入口径（历史调用方按 str 注入的场景），与生产口径分开覆盖。"""
    p = tmp_path / "history.csv"
    _inject(monkeypatch, p, as_path=False)
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
    """默认路径不变：无旗标时 W3 去重照常执行（生产口径 = Path）。"""
    df = pd.DataFrame({"代码": ["001", "001"], "日期": ["2026-09-15", "2026-09-15"],
                       "收盘": [1.0, 1.0]})
    df.to_csv(tmp_hist, index=False, encoding="utf-8-sig")
    fh.final_dedupe()
    after = pd.read_csv(tmp_hist, dtype={"代码": str})
    assert len(after) == 1                             # 去重生效
    assert "DRY-RUN" not in capsys.readouterr().out


@pytest.mark.parametrize("fixture_name", ["tmp_hist", "tmp_hist_str"])
def test_final_dedupe_works_for_both_path_and_str(monkeypatch, capsys, request, fixture_name):
    """q920 回归：Path 与 str 两种口径都必须能真正去重，且不留 .tmp。

    这条直接针对那个长期静默失败：老代码在 Path 口径下抛 TypeError，
    被 except 吞成一行 WARN，文件里的重复行原样留着。
    """
    hist = request.getfixturevalue(fixture_name)
    pd.DataFrame({"代码": ["001", "001"], "日期": ["2026-09-15", "2026-09-15"],
                  "收盘": [1.0, 1.0]}).to_csv(hist, index=False, encoding="utf-8-sig")
    fh.final_dedupe()
    out = capsys.readouterr().out
    assert "DEGRADED" not in out, "去重失败了（%s 口径）：%s" % (fixture_name, out)
    assert "Final dedupe failed" not in out, out
    assert len(pd.read_csv(hist, dtype={"代码": str})) == 1
    assert not Path(str(hist) + ".tmp").exists(), "临时文件残留"


def test_final_dedupe_normalizes_code_padding(tmp_path, monkeypatch, capsys):
    """q920：文件里同时存在 '1' 与 '000001' 两种写法（历史遗留，不补零那批停在 2026-05-12）。

    下游主要消费者读进来都会 astype+zfill —— 早就把两者当同一只股票，于是同一交易日
    被算两遍。只按 raw 代码去重合并不了它们，必须先规范化到 6 位。
    """
    p = tmp_path / "history.csv"
    pd.DataFrame({
        "代码": ["1", "000001", "1", "000001"],
        "日期": ["2026-01-21", "2026-01-22", "2026-05-12", "2026-05-12"],
        "收盘": [10.0, 10.5, 11.0, 11.0],
    }).to_csv(p, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(fh, "HISTORY_FILE", p)
    monkeypatch.setattr(fh, "DRY", False)
    monkeypatch.setattr(fh, "DRY_HITS", [])
    fh.final_dedupe()
    after = pd.read_csv(p, dtype={"代码": str})
    assert set(after["代码"]) == {"000001"}, after["代码"].tolist()
    assert len(after) == 3, after                 # 2026-05-12 的两种写法合并成一行
    assert not after.duplicated(subset=["代码", "日期"]).any()
    assert "代码规范化" in capsys.readouterr().out


def test_final_dedupe_failure_is_loud_not_silent(tmp_path, monkeypatch, capsys):
    """清理失败必须打成醒目横幅（非致命但**不可静默**）——静默正是它躺几个月的原因。"""
    p = tmp_path / "history.csv"
    _seed(p)
    monkeypatch.setattr(fh, "HISTORY_FILE", p)
    monkeypatch.setattr(fh, "DRY", False)
    monkeypatch.setattr(fh, "DRY_HITS", [])

    def boom(*a, **kw):
        raise OSError("模拟：读盘失败")
    monkeypatch.setattr(fh.pd, "read_csv", boom)
    fh.final_dedupe()                                  # 非致命：不抛
    out = capsys.readouterr().out
    assert "[DEGRADED]" in out and "最终去重失败" in out, out
    assert "重复计数" in out, out                      # 必须说清后果
    assert "final_dedupe()" in out, out                # 必须给修复命令
