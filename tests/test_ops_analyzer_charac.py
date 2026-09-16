"""ops_analyzer characterization 用例（d913a-38，2026-09-13）。

只锁定现行为，不改生产码；全部离线（tmp_path/monkeypatch 隔离，无网络/文件外呼）。
覆盖分支：pct 空值/取整、fmt_table 结构、parse_logs 步骤解析+事件捕获+since 过滤+文件名过滤、
analyze 失败计数与 20260815 前后分桶。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ops_analyzer  # noqa: E402


def test_pct_empty_and_selection():
    """空序列返回 0.0；单元素恒返回该值；90 分位按 round 索引取最近值（现行为）。"""
    assert ops_analyzer.pct([], 90) == 0.0
    assert ops_analyzer.pct([7.5], 90) == 7.5
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    # round(0.9*9)=8 → vals[8]=9.0
    assert ops_analyzer.pct(vals, 90) == 9.0
    assert ops_analyzer.pct(vals, 100) == 10.0


def test_fmt_table_structure():
    """表头行 + 全 --- 分隔行 + 逐行拼接，单元格一律 str()。"""
    out = ops_analyzer.fmt_table(["step", "n"], [("fetch", 3), (1, None)])
    lines = out.split("\n")
    assert lines[0] == "| step | n |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| fetch | 3 |"
    assert lines[3] == "| 1 | None |"


def _make_log(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_logs_steps_events_and_filters(tmp_path, monkeypatch):
    """步骤行解析、WARN/FAIL 事件捕获、since 过滤、非 pipeline_*.log 忽略。"""
    _make_log(tmp_path, "pipeline_20260910.log",
              "[10:00:00] [1/5] fetch_history(...)\n"
              "-> fetch_history finished in 12.5s, rc=0\n"
              "[WARN] 磁盘余量低\n"
              "-> build_features finished in 3.0s, rc=1\n"
              "Traceback (most recent call last):\n")
    _make_log(tmp_path, "pipeline_20260901.log",
              "-> fetch_history finished in 99.9s, rc=0\n")  # since 之前，应被滤掉
    _make_log(tmp_path, "unrelated_20260910.log", "-> x finished in 1s, rc=0\n")  # 命名不符
    monkeypatch.setattr(ops_analyzer, "LOGS", tmp_path)
    runs = ops_analyzer.parse_logs("20260910")
    assert len(runs) == 1
    run = runs[0]
    assert run["date"] == "20260910"
    assert run["steps"] == [("fetch_history", 12.5, 0), ("build_features", 3.0, 1)]
    kinds = [k for k, _ in run["events"]]
    # 现行为：rc!=0 不产生文本事件；事件只来自 [WARN]/[FAIL]/Traceback/[ERROR] 行
    assert kinds == ["WARN", "FAIL"]


def test_parse_logs_since_empty_and_oserror_skip(tmp_path, monkeypatch):
    """since 全滤 → 空列表；不可读文件跳过不抛（OSError 分支）。"""
    monkeypatch.setattr(ops_analyzer, "LOGS", tmp_path)
    assert ops_analyzer.parse_logs("20260910") == []
    _make_log(tmp_path, "pipeline_20260910.log", "-> a finished in 1s, rc=0\n")
    real_read = Path.read_text

    def boom(self, *a, **k):
        raise OSError("locked")

    monkeypatch.setattr(Path, "read_text", boom)
    assert ops_analyzer.parse_logs("20260910") == []
    monkeypatch.setattr(Path, "read_text", real_read)


def test_analyze_failure_counts_and_split(tmp_path):
    """analyze：rc!=0 计失败；run_totals 与 fetch_history 按 20260815 前后分桶。"""
    runs = [
        {"date": "20260801", "steps": [("fetch_history", 100.0, 0), ("train", 10.0, 0)], "events": []},
        {"date": "20260910", "steps": [("fetch_history", 5.0, 0), ("train", 12.0, 1)], "events": [("FAIL", "boom")]},
    ]
    rows, trend_rows, run_totals, before, after, fh_b, fh_a, fail_samples, failures = ops_analyzer.analyze(runs)
    assert failures == {"train": 1}
    assert run_totals == [("20260801", 110.0, 0), ("20260910", 17.0, 1)]
    assert before == [110.0] and after == [17.0]
    assert fh_b == [100.0] and fh_a == [5.0]
    # 主表按均耗时降序：fetch_history(52.5) > train(11.0)
    assert [r[0] for r in rows] == ["fetch_history", "train"]
    assert fail_samples["文本告警/报错"] == ["20260910 FAIL: boom"]
