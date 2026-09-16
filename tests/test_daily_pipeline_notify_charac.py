# -*- coding: utf-8 -*-
"""daily_pipeline._notify_failure characterization（d914-71 T4）。

只测失败通知链路（写标记文件 + 推送调用），subprocess.run 必须被 patch
（否则可能真推 Bark）。绝不执行 daily_pipeline 的 main/真实流水线。
"""
import re
import subprocess

import daily_pipeline as dp


def _patch_env(tmp_path, monkeypatch, calls):
    monkeypatch.setattr(dp, "BASE_DIR", str(tmp_path))
    fail_marker = tmp_path / "data" / "pipeline_failed.txt"
    monkeypatch.setattr(dp, "FAIL_MARKER", str(fail_marker))

    def fake_run(argv, *a, **k):
        calls.append(argv)
        return 0

    monkeypatch.setattr(subprocess, "run", fake_run)
    return fail_marker


def test_notify_failure_normal_path(tmp_path, monkeypatch):
    calls = []
    fail_marker = _patch_env(tmp_path, monkeypatch, calls)
    dp._notify_failure("boom")
    assert fail_marker.exists()
    content = fail_marker.read_text(encoding="utf-8")
    assert "boom" in content
    first_line = content.splitlines()[0]
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", first_line), first_line
    assert len(calls) == 1
    assert any("send_to_bark.py" in str(arg) for arg in calls[0])


def test_notify_failure_swallows_push_oserror(tmp_path, monkeypatch):
    calls = []
    fail_marker = _patch_env(tmp_path, monkeypatch, calls)

    def boom_run(argv, *a, **k):
        raise OSError("push channel down")

    monkeypatch.setattr(subprocess, "run", boom_run)
    dp._notify_failure("boom")
    assert fail_marker.exists(), "推送失败也必须先落标记文件"
    assert "boom" in fail_marker.read_text(encoding="utf-8")


def test_notify_failure_creates_data_dir(tmp_path, monkeypatch):
    calls = []
    fail_marker = _patch_env(tmp_path, monkeypatch, calls)
    assert not fail_marker.parent.exists(), "前置：data/ 子目录尚不存在"
    dp._notify_failure("boom")
    assert fail_marker.exists(), "os.makedirs(exist_ok=True) 应自建目录"
