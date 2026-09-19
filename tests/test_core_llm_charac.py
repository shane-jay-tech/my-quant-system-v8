"""q918-07：core/llm.py chat() 错误分支与重试链 characterization（基线 #6）。

冻结现值（先跑后断言）：500/超时 → 重试 retries 次（sleep 2,4）后包成 LLMError「调用失败」；
空 choices → 不 sleep、max_tokens 逐次翻倍、终抛 LLMError「模型返回空内容」（LLMError 直通不重包）；
正常 → _log_cost 成本记录恰一次、返回 (text, usage)。
零真实 API：requests.post / load_llm_config / time 全部替换。
"""

from __future__ import annotations

import pytest
import requests as _real_requests

import core.llm as llm


class _FakeTime:
    def __init__(self):
        self.sleeps = []

    def sleep(self, s):
        self.sleeps.append(s)


class _Resp:
    def __init__(self, *, status=200, body=None, exc=None):
        self._status, self._body, self._exc = status, body, exc

    def raise_for_status(self):
        if self._status >= 400:
            e = _real_requests.exceptions.HTTPError(f"{self._status}")
            e.response = self
            raise e

    def json(self):
        return self._body


def _patch_cfg(monkeypatch):
    monkeypatch.setattr(llm, "load_llm_config", lambda: {
        "api_key": "test-key", "base_url": "http://test.local", "model": "test-model",
    })


def _ok_body(text="hello"):
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_http_500_retries_then_wraps_llmerror(monkeypatch):
    """500 → raise_for_status 抛 HTTPError → 重试 retries 次（sleep 2,4）→ LLMError「调用失败」。"""
    _patch_cfg(monkeypatch)
    ft = _FakeTime()
    monkeypatch.setattr(llm, "time", ft)
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return _Resp(status=500)

    monkeypatch.setattr(_real_requests, "post", fake_post)
    monkeypatch.setattr(llm, "_log_cost", lambda *a, **k: pytest.fail("失败路径不应记成本"))

    with pytest.raises(llm.LLMError) as ei:
        llm.chat([{"role": "user", "content": "hi"}], operation="op500", retries=2)
    assert len(calls) == 3
    assert ft.sleeps == [2, 4]
    assert "op500 调用失败" in str(ei.value)


def test_timeout_retries_then_wraps_llmerror(monkeypatch):
    """requests.post 超时异常 → 同一重试链 → 最终 LLMError。"""
    _patch_cfg(monkeypatch)
    ft = _FakeTime()
    monkeypatch.setattr(llm, "time", ft)

    def fake_post(url, **kw):
        raise _real_requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(_real_requests, "post", fake_post)
    monkeypatch.setattr(llm, "_log_cost", lambda *a, **k: pytest.fail("失败路径不应记成本"))

    with pytest.raises(llm.LLMError) as ei:
        llm.chat([{"role": "user", "content": "hi"}], operation="opTO", retries=2)
    assert ft.sleeps == [2, 4]
    assert "opTO 调用失败" in str(ei.value)


def test_empty_choices_doubles_max_tokens_without_sleep_then_empty_error(monkeypatch):
    """空 choices：attempt<retries 时 max_tokens 翻倍且不 sleep；耗尽后抛
    LLMError「模型返回空内容」（LLMError 直通，不被包成「调用失败」）。"""
    _patch_cfg(monkeypatch)
    ft = _FakeTime()
    monkeypatch.setattr(llm, "time", ft)
    payloads = []

    def fake_post(url, json=None, **kw):
        payloads.append(json["max_tokens"])
        return _Resp(status=200, body={"choices": [], "usage": {}})

    monkeypatch.setattr(_real_requests, "post", fake_post)
    monkeypatch.setattr(llm, "_log_cost", lambda *a, **k: None)

    with pytest.raises(llm.LLMError) as ei:
        llm.chat([{"role": "user", "content": "hi"}], max_tokens=1200, operation="opE", retries=2)
    assert payloads == [1200, 2400, 4800]
    assert ft.sleeps == []            # 空内容重试不走 sleep
    assert "模型返回空内容" in str(ei.value)
    assert "调用失败" not in str(ei.value)


def test_success_returns_text_usage_and_logs_cost_once(monkeypatch):
    """正常态：返回 (text, usage)；_log_cost 恰一次；零 sleep。"""
    _patch_cfg(monkeypatch)
    ft = _FakeTime()
    monkeypatch.setattr(llm, "time", ft)
    cost_calls = []
    monkeypatch.setattr(llm, "_log_cost", lambda op, model, usage, detail="": cost_calls.append((op, model, usage)))

    monkeypatch.setattr(_real_requests, "post", lambda url, **kw: _Resp(status=200, body=_ok_body()))
    text, usage = llm.chat([{"role": "user", "content": "hi"}], operation="opOK")
    assert text == "hello"
    assert usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert len(cost_calls) == 1 and cost_calls[0][0] == "opOK" and cost_calls[0][1] == "test-model"
    assert ft.sleeps == []
