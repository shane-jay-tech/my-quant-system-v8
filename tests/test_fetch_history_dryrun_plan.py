# -*- coding: utf-8 -*-
"""fetch_history.py --dry-run-plan 回归（q918-19，q916-04 切片3）。

零网络、零写盘：只喂 tmp_path 里的盘上状态，验证增量计划算得对且**一个字节都没落**。
运行：python -m pytest tests/test_fetch_history_dryrun_plan.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_history as fh  # noqa: E402


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """DATA_DIR / HISTORY_FILE 全指到 tmp；池文件当日名不存在 ⇒ 走"回退最新一份"分支。

    顺手把网络口子打成必炸：计划档一旦漏进真正的抓取路径就该当场失败。
    注意必须**同时**炸 `request_with_backoff`：它内部是 `except Exception: time.sleep(2**n)`，
    只炸 `requests.get` 会被它整个吞掉 ⇒ 用例不会红，只会慢（实测 14 秒退避后仍继续跑）。
    """
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(fh, "DATA_DIR", data)
    monkeypatch.setattr(fh, "HISTORY_FILE", data / "history.csv")

    def _no_network(*a, **k):
        raise AssertionError("dry-run-plan 不应发起任何网络请求")

    monkeypatch.setattr(fh, "request_with_backoff", _no_network)
    monkeypatch.setattr(fh.requests, "get", _no_network)
    monkeypatch.setattr(fh.requests, "post", _no_network)
    return data


def _pool(data: Path, codes, name="stock_20260913.csv"):
    pd.DataFrame({"代码": codes, "最新价": [10.0] * len(codes)}).to_csv(data / name, index=False)
    return data / name


def _history(data: Path, rows):
    pd.DataFrame(rows, columns=["代码", "日期"]).to_csv(data / "history.csv", index=False)


def test_plan_counts_new_and_stale_and_parses_target_date(sandbox, capsys):
    _pool(sandbox, ["000001", "600519", "300750"])
    _history(sandbox, [("000001", "2026-09-13"),        # 已到目标日 ⇒ 跳过
                       ("600519", "2026-09-10")])       # 落后 ⇒ stale

    assert fh.main(["--dry-run-plan"]) == 0
    plan = fh._resolve_increment_plan()

    assert plan["target_date"] == "2026-09-13"          # 目标日取自池文件名，不是"今天"
    assert plan["new_codes"] == ["300750"]
    assert plan["stale_codes"] == ["600519"]
    assert plan["codes_to_fetch"] == ["300750", "600519"]
    assert plan["pool_size"] == 3 and plan["used_fallback"] is True
    out = capsys.readouterr().out
    assert "[DRY-RUN-PLAN]" in out and "待补代码  : 2 只" in out
    assert "stream-append" in out and "整体重写" in out      # 写入方式两档都要讲清（追加 vs 重写）


def test_plan_touches_nothing_on_disk(sandbox):
    """硬口径：跑计划**不建 history.csv、不改池文件、不留任何新文件**（零写盘）。"""
    _pool(sandbox, ["000001", "600519"])
    before = {p.name: p.stat().st_mtime_ns for p in sandbox.iterdir()}

    fh.main(["--dry-run-plan"])

    assert not (sandbox / "history.csv").exists()
    assert {p.name: p.stat().st_mtime_ns for p in sandbox.iterdir()} == before


def test_plan_reports_missing_pool_and_exits_1(sandbox, capsys):
    """连股票池都没有 ⇒ 与 main 的 FATAL 同口径，返回 1 而不是抛异常。"""
    assert fh.main(["--dry-run-plan"]) == 1
    assert "No stock data file found" in capsys.readouterr().out
    assert not (sandbox / "history.csv").exists()


def test_broken_history_is_treated_as_all_new(sandbox, capsys):
    """history.csv 读不动时不得静默"零待补"——按原语义 WARN 后把全部代码算作全新。"""
    _pool(sandbox, ["000001", "600519"])
    (sandbox / "history.csv").write_text("这不是csv，列头都没有\nXXXX\n", encoding="utf-8")

    plan = fh._resolve_increment_plan()

    assert sorted(plan["new_codes"]) == ["000001", "600519"] and plan["stale_codes"] == []
    assert "[WARN] Failed to read existing history" in capsys.readouterr().out
