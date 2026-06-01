"""core.pipeline._alpha_gate_precheck 测试 — Alpha Gate 每日计数接线。

背景：v8.6 设计「每天调用 evaluate_etf_gate() 计数」，旧实现只读 is_paused()，
状态文件从不更新，门永远不会触发。本测试锁定新行为：每次 precheck 必须调用
check_alpha_gate()；异常必须 fail-open；paused 时返回停跑原因。
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core import pipeline


def _fake_result(paused=False, severity="normal", reason="", counted=True):
    class R:
        pass

    r = R()
    r.paused = paused
    r.severity = severity
    r.consecutive_severe_days = 0
    r.pause_reason = reason
    r.counted = counted
    return r


def test_precheck_runs_daily_check(monkeypatch):
    import alpha_gate
    calls = []

    def fake_check(*args, **kwargs):
        calls.append(kwargs.get('trading_day_ok'))
        return _fake_result()

    monkeypatch.setattr(alpha_gate, "check_alpha_gate", fake_check)
    paused, reason = pipeline._alpha_gate_precheck()
    assert calls == [True]  # run_all 已确认交易日，不应让 alpha_gate 再次联网
    assert paused is False
    assert reason == ""


def test_precheck_reports_paused(monkeypatch):
    import alpha_gate
    monkeypatch.setattr(alpha_gate, "check_alpha_gate",
                        lambda **kwargs: _fake_result(
                            paused=True, severity="severe", reason="underperform"))
    paused, reason = pipeline._alpha_gate_precheck()
    assert paused is True
    assert reason == "underperform"


def test_precheck_fails_open_on_exception(monkeypatch):
    import alpha_gate

    def boom(**kwargs):
        raise RuntimeError("state file broken")

    monkeypatch.setattr(alpha_gate, "check_alpha_gate", boom)
    paused, reason = pipeline._alpha_gate_precheck()
    assert paused is False
    assert reason == ""
