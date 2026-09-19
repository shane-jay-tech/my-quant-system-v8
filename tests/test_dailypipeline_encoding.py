# -*- coding: utf-8 -*-
"""daily_pipeline 失败推送的 subprocess 编码参数锁定（q918-39）。

镜像 `tests/test_daily_pipeline_notify_charac.py:22`（d914-71 T4）的 `monkeypatch.setattr(subprocess, "run", ...)` 手法
——`_notify_failure` 内是 `import subprocess`（daily_pipeline.py:33）后直接 `subprocess.run(...)`，
所以必须 patch **模块对象上的属性**，不是 patch `daily_pipeline.subprocess`（后者不存在于模块命名空间）。
绝不真推 Bark、绝不执行 main/流水线。
可复跑：python -m pytest tests/test_dailypipeline_encoding.py -q
"""
from __future__ import annotations

import inspect
import subprocess
import sys

import daily_pipeline as dp

_REAL_RUN = subprocess.run  # _spy_run 会替换模块属性，这里先留一份真身


def _spy_run(monkeypatch, tmp_path):
    """把 BASE_DIR/FAIL_MARKER 隔离到 tmp_path，并拦截 subprocess.run。"""
    calls = []
    monkeypatch.setattr(dp, "BASE_DIR", str(tmp_path))
    marker = tmp_path / "data" / "pipeline_failed.txt"
    monkeypatch.setattr(dp, "FAIL_MARKER", str(marker))

    def fake_run(argv, *a, **kw):
        calls.append((list(argv), kw))
        return 0

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls, marker


def test_notify_failure_passes_utf8_replace(monkeypatch, tmp_path):
    """钉住 :36 的两个新参数：encoding='utf-8' + errors='replace'。"""
    calls, _ = _spy_run(monkeypatch, tmp_path)
    dp._notify_failure("boom")

    assert len(calls) == 1
    argv, kw = calls[0]
    assert kw.get("encoding") == "utf-8"
    assert kw.get("errors") == "replace"


def test_encoding_fix_keeps_existing_kwargs(monkeypatch, tmp_path):
    """补参数不许动既有语义：cwd 仍在仓库根、timeout 仍 60、argv 仍是 --file/--no-digest 三件套。"""
    calls, marker = _spy_run(monkeypatch, tmp_path)
    dp._notify_failure("pipeline exploded")

    argv, kw = calls[0]
    assert kw.get("timeout") == 60 and kw.get("cwd") == str(tmp_path)
    assert argv[1].endswith("send_to_bark.py")
    assert argv[argv.index("--file") + 1] == str(marker)
    assert "--no-digest" in argv
    assert "pipeline exploded" in marker.read_text(encoding="utf-8")


def test_kwargs_accepted_by_popen_strict_signature(monkeypatch, tmp_path):
    """防拼写漂移：`subprocess.run` 收 **kwargs（实测），写错成 `encode=` 也不报错、
    只是静默不生效；`Popen.__init__` 无 **kwargs，故拿它的参数名表逐个核。
    （不能整体 bind——`timeout` 是 run 自有参数，Popen 里没有。）"""
    calls, _ = _spy_run(monkeypatch, tmp_path)
    dp._notify_failure("boom")
    _, kw = calls[0]

    run_only = {"input", "capture_output", "timeout", "check"}
    popen_params = set(inspect.signature(subprocess.Popen.__init__).parameters)
    unknown = sorted(k for k in kw if k not in run_only and k not in popen_params)
    assert unknown == [], f"这些参数名 Popen 不认，会被 run 的 **kwargs 静默吞掉: {unknown}"
    assert kw["encoding"] == "utf-8" and kw["errors"] == "replace"


def test_encoding_without_capture_is_inert(monkeypatch, tmp_path):
    """如实记录：该调用点**没有** capture_output/stdout=PIPE，所以 encoding 今天不改变任何行为
    （实测 stdout 仍是 None）。此用例真起一个无害子进程验证——不跑 send_to_bark.py、不联网。"""
    calls, _ = _spy_run(monkeypatch, tmp_path)
    dp._notify_failure("boom")
    _, kw = calls[0]

    real_run = _REAL_RUN  # 不能用 subprocess.run——已被 _spy_run 换成假的
    proc = real_run([sys.executable, "-c", "pass"], timeout=kw["timeout"],
                    encoding=kw["encoding"], errors=kw["errors"])
    assert proc.returncode == 0
    assert proc.stdout is None  # 无管道 ⇒ 没有可解码的流，encoding 形同占位
