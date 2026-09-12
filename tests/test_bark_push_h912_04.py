"""h912-04 批A：bark_sender.push characterization（mock 网络，零真实外发）。

覆盖缺口（基线 23%）：无 token 明确 False（v8.7 契约）、服务端 code 分支、
异常吞并 → False、newbie bark 文件解析。全部 mock requests，不联网。
"""
from __future__ import annotations

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


def test_send_bark_no_tokens_returns_false():
    assert push.send_bark("t", "b", tokens=[]) is False


def test_send_bark_success_code_80000000(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResp(200, {"code": "80000000", "msg": "ok"})

    monkeypatch.setattr(push.requests, "post", fake_post)
    assert push.send_bark("t", "b", tokens=["tok1", "tok2"]) is True
    assert len(calls) == 2
    assert calls[0]["token"] == "tok1" and calls[0]["title"] == "t"


def test_send_bark_server_error_code_returns_false(monkeypatch):
    monkeypatch.setattr(
        push.requests, "post",
        lambda *a, **k: _FakeResp(200, {"code": "400", "msg": "bad token"}),
    )
    assert push.send_bark("t", "b", tokens=["tok1"]) is False


def test_send_bark_http_error_returns_false(monkeypatch):
    monkeypatch.setattr(push.requests, "post", lambda *a, **k: _FakeResp(500, {}, "err"))
    assert push.send_bark("t", "b", tokens=["tok1"]) is False


def test_send_bark_exception_swallows_and_returns_false(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(push.requests, "post", boom)
    assert push.send_bark("t", "b", tokens=["tok1"]) is False


def test_send_from_newbie_file_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "BASE_DIR", str(tmp_path), raising=False)
    assert push.send_from_newbie_file() is None


def test_send_from_newbie_file_parses_title_and_body(tmp_path, monkeypatch):
    orders = tmp_path / "orders"
    orders.mkdir()
    (orders / "bark_simple_20260912.txt").write_text(
        "TITLE: 今日选股 3 只\n首选: 浦发银行(600000)\n止损-8% | 止盈+20% | 持10天\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(push, "BASE_DIR", str(tmp_path), raising=False)
    result = push.send_from_newbie_file()
    assert result is not None
    title, body = result
    assert title == "今日选股 3 只"
    assert body.startswith("首选: 浦发银行(600000)")
