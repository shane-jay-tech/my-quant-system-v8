"""h912-15 批B2：bark_sender.push mock 网络分支补测（零真实请求）。

与 tests/test_bark_push_h912_04.py 不重叠：本文件聚焦 multi-token 混合结果、
json 解析失败回退「成功」文本分支、超时/连接异常分类。
注：现实现为每 token 单次尝试（v8.7 契约），不存在重试循环——任务书假设的
「重试耗尽/重试后成功」分支在产码中不存在，用例按实有分支覆盖（报告已披露）。
"""

from __future__ import annotations

import requests

import bark_sender.push as push


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_timeout_per_token_marks_failure(monkeypatch):
    """超时（requests.Timeout）→ 该 token 失败、all_ok=False、不抛出。"""

    def raise_timeout(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(push.requests, "post", raise_timeout)
    assert push.send_bark("t", "b", tokens=["tok1"]) is False


def test_connection_error_per_token_marks_failure(monkeypatch):
    def raise_conn(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(push.requests, "post", raise_conn)
    assert push.send_bark("t", "b", tokens=["tok1"]) is False


def test_json_parse_failure_falls_back_to_text_marker(monkeypatch):
    """200 但 body 非 JSON、文本含「成功」→ 视为成功（:42-44 回退分支）。"""
    monkeypatch.setattr(
        push.requests, "post",
        lambda *a, **k: _FakeResp(200, payload=None, text="发送成功 id=123"),
    )
    assert push.send_bark("t", "b", tokens=["tok1"]) is True


def test_json_parse_failure_without_marker_is_failure(monkeypatch):
    """200 非 JSON 且无「成功」→ 失败。"""
    monkeypatch.setattr(
        push.requests, "post",
        lambda *a, **k: _FakeResp(200, payload=None, text="gateway html"),
    )
    assert push.send_bark("t", "b", tokens=["tok1"]) is False


def test_mixed_tokens_any_failure_returns_false(monkeypatch):
    """多 token：首个失败、其余成功 → all_ok=False（全量成功才 True）。"""
    responses = [
        _FakeResp(500, {}, "server error"),
        _FakeResp(200, {"code": "80000000", "msg": "ok"}),
        _FakeResp(200, {"code": "80000000", "msg": "ok"}),
    ]
    seen = []

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.append(json["token"])
        return responses[len(seen) - 1]

    monkeypatch.setattr(push.requests, "post", fake_post)
    assert push.send_bark("t", "b", tokens=["a", "b", "c"]) is False
    assert seen == ["a", "b", "c"]  # 失败不中断后续 token


def test_all_tokens_success_returns_true(monkeypatch):
    monkeypatch.setattr(
        push.requests, "post",
        lambda *a, **k: _FakeResp(200, {"code": "80000000", "msg": "ok"}),
    )
    assert push.send_bark("t", "b", tokens=["a", "b"]) is True


def test_post_called_with_api_endpoint_and_payload_shape(monkeypatch):
    """冻结请求形态：端点 URL、payload 字段（token/title/msg/sender）。"""
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResp(200, {"code": "80000000", "msg": "ok"})

    monkeypatch.setattr(push.requests, "post", fake_post)
    assert push.send_bark("标题", "正文", tokens=["tokX"]) is True
    assert captured["url"].startswith("http://")
    assert captured["json"]["token"] == "tokX"
    assert captured["json"]["title"] == "标题"
    assert captured["json"]["msg"] == "正文"
    assert captured["json"]["sender"] == "量化选股系统"
