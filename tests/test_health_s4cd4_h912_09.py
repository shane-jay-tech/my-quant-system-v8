"""h912-09 S4CD-4：硬编码 token 扫描提为公共路径的 spy 断言。

改前失败锚点：_scan_hardcoded_bark_token 不存在（AttributeError）、
if 分支下 results 无 'External: Bark token' 检查项。
"""

from __future__ import annotations

from pathlib import Path

import ops.health as health

import pytest


def _run_branch(monkeypatch, tmp_path, *, bark_key, tokens, secrets_exists):
    """在指定分支配置下跑 run_all，返回（检查项列表, spy 调用次数）。"""
    monkeypatch.setattr(health, "get_secret", lambda k: bark_key)
    monkeypatch.setattr(health, "get_secret_list", lambda k: list(tokens))
    monkeypatch.setattr(
        health, "data_file", lambda name: tmp_path / ("secrets.json" if secrets_exists else "_absent.json")
    )
    monkeypatch.setattr(health, "REPORTS_DIR", tmp_path / "reports")  # 报告隔离，不污染仓库
    calls = []
    orig_scan = getattr(health, "_scan_hardcoded_bark_token", None)

    def spy():
        calls.append(1)
        return orig_scan() if orig_scan else False

    if orig_scan is not None:
        monkeypatch.setattr(health, "_scan_hardcoded_bark_token", spy)
    else:
        # 改前：扫描函数尚不存在，spy 无法挂载——保留空 calls（断言必然失败）
        monkeypatch.setattr(health, "_scan_hardcoded_bark_token", spy, raising=False)

    health.run_all()
    bark_checks = [c for c in health.results["checks"] if c["name"] == "External: Bark token"]
    return bark_checks, len(calls)


def test_scan_runs_on_if_branch(monkeypatch, tmp_path):
    """原 if 分支（token 已配置）此前不执行扫描——修复后必须命中 ≥1 次。"""
    checks, calls = _run_branch(
        monkeypatch, tmp_path, bark_key="fake", tokens=[], secrets_exists=True
    )
    assert calls >= 1, "if 分支未执行硬编码扫描（S4CD-4 病灶）"
    assert len(checks) == 1 and checks[0]["status"] in ("PASS", "FAIL")


def test_scan_runs_on_elif_branch(monkeypatch, tmp_path):
    """原 elif 分支（无 token 无 secrets.json）——修复后扫描仍命中（行为保持）。"""
    checks, calls = _run_branch(
        monkeypatch, tmp_path, bark_key=None, tokens=[], secrets_exists=False
    )
    assert calls >= 1
    assert len(checks) == 1 and checks[0]["status"] == "PASS"  # 仓内推送源码无硬编码 token


def test_scan_runs_on_else_branch(monkeypatch, tmp_path):
    """原 else 分支（secrets.json 存在但无 token）——修复后扫描命中 ≥1 次。"""
    (tmp_path / "secrets.json").write_text("{}", encoding="utf-8")
    checks, calls = _run_branch(
        monkeypatch, tmp_path, bark_key=None, tokens=[], secrets_exists=True
    )
    assert calls >= 1, "else 分支未执行硬编码扫描（S4CD-4 病灶）"
    assert len(checks) == 1


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_schtasks_decode_no_thread_warning(monkeypatch, tmp_path):
    """n916d-16 同族（n916d-17 顺延单）：schtasks GBK 输出不再炸 UTF-8 读线程。

    锁定：run_all 全程无 PytestUnhandledThreadExceptionWarning（subprocess 读线程
    加 encoding+errors=replace 后不再抛 UnicodeDecodeError）。
    """
    import pytest

    monkeypatch.setattr(health, "get_secret", lambda k: None)
    monkeypatch.setattr(health, "get_secret_list", lambda k: [])
    monkeypatch.setattr(health, "data_file", lambda name: tmp_path / "_absent.json")
    monkeypatch.setattr(health, "REPORTS_DIR", tmp_path / "reports")
    health.run_all()
