"""q918-09：core/pipeline.py 失败路径 characterization（基线 #9）。

冻结现值：脚本缺失 → [MISS] 打印＋返回码 127；stub 返回 rc=1 → 透传（重试次数按 step.retry）；
--list → 返回 0 且逐行打印步骤清单。subprocess.run 全程 monkeypatch 免真执行。
"""

from __future__ import annotations

import core.pipeline as pl


def test_missing_script_returns_127_with_miss_line(tmp_path, capsys, monkeypatch):
    """脚本不存在 → 打印「[MISS] <name>: <path> not found」→ 返回 127（:179 锚点）。"""
    monkeypatch.setattr(pl.subprocess, "run", lambda *a, **k: pytest_fail_no_exec())
    rc = pl._run_script("ghost", {"script": "no_such_script.py"}, str(tmp_path))
    assert rc == 127
    out = capsys.readouterr().out
    assert "[MISS] ghost" in out and "not found" in out


def pytest_fail_no_exec():
    raise AssertionError("脚本缺失分支不应执行 subprocess")


def test_rc1_passthrough_with_retry_count(tmp_path, capsys, monkeypatch):
    """stub rc=1 → 透传 1；retry=2 → subprocess.run 恰 2 次、[RETRY] 打印一次、零真等待。"""
    calls = []

    class _R:
        returncode = 1

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        return _R()

    monkeypatch.setattr(pl.subprocess, "run", fake_run)
    monkeypatch.setattr(pl.time, "sleep", lambda s: calls.append(("sleep", s)))
    step = {"script": "stub.py", "retry": 2, "retry_wait": 0}
    (tmp_path / "stub.py").write_text("pass", encoding="utf-8")
    rc = pl._run_script("stubbed", step, str(tmp_path))
    assert rc == 1
    assert len(calls) == 2
    assert "sleep" not in [c[0] for c in calls if isinstance(c, tuple)]
    out = capsys.readouterr().out
    assert "[RETRY] stubbed attempt 1 failed (rc=1)" in out


def test_rc0_after_retry_returns_zero(tmp_path, capsys, monkeypatch):
    """第一次 rc=1、第二次 rc=0 → 返回 0（重试成功路径）。"""
    results = [type("R", (), {"returncode": 1})(), type("R", (), {"returncode": 0})()]
    monkeypatch.setattr(pl.subprocess, "run", lambda cmd, cwd=None: results.pop(0))
    monkeypatch.setattr(pl.time, "sleep", lambda s: None)
    step = {"script": "stub.py", "retry": 2, "retry_wait": 0}
    (tmp_path / "stub.py").write_text("pass", encoding="utf-8")
    assert pl._run_script("flaky", step, str(tmp_path)) == 0


def test_list_flag_prints_steps_and_returns_zero(capsys):
    """--list 契约：返回 0，逐行输出 [ON]/[..]/[--] 标记的步骤清单。"""
    rc = pl.main(["--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[ON]" in out or "[..]" in out or "[--]" in out
    assert "tiers=" in out and "sched=" in out
