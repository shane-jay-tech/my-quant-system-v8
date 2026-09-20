# -*- coding: utf-8 -*-
"""q920-01：`request_with_backoff` 末次异常告警 ＋ dry-run 双旗标互斥（两脚本）。

上游：`q918-19-quant-dryrun-slice3-plan` 遗留「`request_with_backoff(:83-105)` 吞掉一切异常并退避重试
⇒ 真 bug 伪装成网络不稳，日志零行」。
零网络（`requests.get` 全桩）、零写盘（不发起的请求不会碰盘）、`time.sleep` 打桩 ⇒ 不真退避。
运行：python -m pytest tests/test_fetch_backoff_warn_and_flags.py -q
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_history as fh  # noqa: E402
import fetch_minute_kline as fk  # noqa: E402


class Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.encoding = "utf-8"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """退避是真睡觉（2+4+8=14s 起）——测试里一律 no-op，只记次数。"""
    sleeps = []
    monkeypatch.setattr(fh.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


@pytest.fixture
def boom_requests(monkeypatch):
    """把 `requests.get` 换成可编程的桩：`seq` 里每项要么是异常类，要么是状态码。"""
    calls = []

    def install(seq):
        state = {"i": 0}

        def fake_get(url, params=None, headers=None, timeout=None):
            idx = min(state["i"], len(seq) - 1)
            state["i"] += 1
            calls.append((url, headers))
            item = seq[idx]
            if isinstance(item, Exception):
                raise item
            return Resp(item)

        monkeypatch.setattr(fh.requests, "get", fake_get)
        return calls

    return install


def _warn_records(caplog):
    return [r for r in caplog.records if r.levelno <= logging.WARNING and "[WARN]" in r.getMessage()]


def test_last_attempt_exception_is_logged_once(caplog, boom_requests):
    boom_requests([ValueError("解析器炸了")])

    with caplog.at_level(logging.WARNING, logger=fh.__name__):
        assert fh.request_with_backoff("http://x/y", {}, max_retries=3) is None

    warns = _warn_records(caplog)
    assert len(warns) == 1                          # 一次运行一条，不逐次刷屏
    assert "ValueError" in warns[0].getMessage() and "连续 3 次" in warns[0].getMessage()


def test_retry_semantics_unchanged_three_attempts_and_none_backed(caplog, boom_requests, no_sleep):
    calls = boom_requests([ValueError("超时")])

    with caplog.at_level(logging.WARNING, logger=fh.__name__):
        out = fh.request_with_backoff("http://x/y", {"a": 1}, max_retries=3)

    assert out is None and len(calls) == 3
    # 每次尝试前先睡 REQUEST_DELAY 的随机 jitter（0.5~1.0s），退避值是确定的 2/4/8
    assert [s for s in no_sleep if s in (2, 4, 8)] == [2, 4, 8]
    assert all(0.5 <= s <= 1.0 for s in no_sleep if s not in (2, 4, 8))


def test_no_warning_when_the_last_attempt_returns_a_response(caplog, boom_requests):
    """中途抖一下、最后一次正常返回 456 ⇒ 那是限流不是代码 bug，不该混进同一条 WARN。"""
    boom_requests([ValueError("抖动"), 456])

    with caplog.at_level(logging.WARNING, logger=fh.__name__):
        assert fh.request_with_backoff("http://x/y", {}, max_retries=3) is None

    assert _warn_records(caplog) == []


def test_no_warning_on_immediate_success(caplog, boom_requests):
    boom_requests([200])

    with caplog.at_level(logging.WARNING, logger=fh.__name__):
        resp = fh.request_with_backoff("http://x/y", {})

    assert resp.status_code == 200 and _warn_records(caplog) == []


def test_warning_names_the_url_that_failed(caplog, boom_requests):
    boom_requests([RuntimeError("boom")])

    with caplog.at_level(logging.WARNING, logger=fh.__name__):
        fh.request_with_backoff("https://finance.sina.com.cn/quotedetail", {}, max_retries=1)

    assert "finance.sina.com.cn" in _warn_records(caplog)[0].getMessage()


# ────────────────────────── 双旗标互斥 ──────────────────────────
def test_history_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit) as ei:
        fh._parse_args(["--dry-run", "--dry-run-plan"])
    assert ei.value.code == 2                       # argparse 用法错误口径，不是自定义异常


@pytest.mark.parametrize("argv", [["--dry-run"], ["--dry-run-plan"], []])
def test_history_single_flag_still_parses(argv):
    args = fh._parse_args(argv)
    assert args.dry_run == ("--dry-run" in argv)
    assert args.dry_run_plan == ("--dry-run-plan" in argv)


def test_minute_main_rejects_both_flags_before_doing_anything(monkeypatch):
    def trip(*a, **k):
        raise AssertionError("旗标冲突必须在解析阶段就退出，不许先干活")

    monkeypatch.setattr(fk, "describe_plan", trip)
    with pytest.raises(SystemExit) as ei:
        fk.main(["--dry-run", "--dry-run-plan"])
    assert ei.value.code == 2


def test_minute_history_same_conflict_via_main(monkeypatch):
    with pytest.raises(SystemExit) as ei:
        fh.main(["--dry-run", "--dry-run-plan"])
    assert ei.value.code == 2
