"""safe_request 重试/退避分支 characterization（916p-a1-005）。

零真实网络：requests.get 全部 monkeypatch 假响应；time.sleep 打桩防真等
（AGENTS.md 反反爬：UA 伪装/随机延时/最多 3 次指数退避——本单只钉分支行为）。
可复跑：python -m pytest tests/test_fetch_stock_safe_request.py -q
"""
import fetch_stock_data as m


class FakeResp:
    def __init__(self, status):
        self.status_code = status


def _patch(monkeypatch, responses, calls):
    """按序出队的假 requests.get；记录调用次数。responses 尾元素循环复用。"""
    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        idx = min(len(calls) - 1, len(responses) - 1)
        r = responses[idx]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(m.requests, "get", fake_get)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)


URL = "http://example.invalid/quote"


def test_first_200_returns_immediately(monkeypatch):
    """①首次 200 → 返回该响应且只调 1 次（:49 短路）。"""
    calls = []
    _patch(monkeypatch, [FakeResp(200)], calls)
    resp = m.safe_request(URL, {}, {}, label="t200")
    assert resp is not None and resp.status_code == 200
    assert len(calls) == 1


def test_persistent_500_exhausts_to_none(monkeypatch):
    """②连续 500×3 → None 且调用次数恰为 max_retries（:47-53 分支）。"""
    calls = []
    _patch(monkeypatch, [FakeResp(500)] * 3 + [FakeResp(500)], calls)
    resp = m.safe_request(URL, {}, {}, max_retries=3, label="t500")
    assert resp is None
    assert len(calls) == 3


def test_403_warn_contains_code(monkeypatch, capsys):
    """③403 → 打印含 403 的 WARN（:50-51 专用分支）。"""
    _patch(monkeypatch, [FakeResp(403)] * 3 + [FakeResp(403)], [])
    m.safe_request(URL, {}, {}, max_retries=2, label="t403")
    out = capsys.readouterr().out
    assert "[WARN] 403 Forbidden on t403" in out


def test_other_status_warn_contains_status(monkeypatch, capsys):
    """④其它非 200（502）→ 打印含状态码的 WARN（:52-53 通用分支）。"""
    _patch(monkeypatch, [FakeResp(502)] * 3 + [FakeResp(502)], [])
    m.safe_request(URL, {}, {}, max_retries=1, label="t502")
    out = capsys.readouterr().out
    assert "[WARN] HTTP 502 on t502" in out


def test_exception_prints_retry_and_returns_none(monkeypatch, capsys):
    """⑤requests.get 抛异常 → 打印 [RETRY]、不上抛、耗尽后 None（:54-58）。"""
    calls = []
    _patch(monkeypatch, [ConnectionError("boom")], calls)
    resp = m.safe_request(URL, {}, {}, max_retries=3, label="terr")
    assert resp is None
    out = capsys.readouterr().out
    assert "[RETRY] terr attempt 1/3" in out
    assert len(calls) == 3  # 异常同样计入重试轮次


def test_max_retries_one_fails_fast(monkeypatch):
    """⑥max_retries=1 且失败 → 只调 1 次即 None（:44 for 范围）。"""
    calls = []
    _patch(monkeypatch, [FakeResp(500), FakeResp(200)], calls)
    resp = m.safe_request(URL, {}, {}, max_retries=1, label="t1")
    assert resp is None
    assert len(calls) == 1  # 即使第二次会 200 也不再调


def test_headers_dicts_have_ua_and_referer():
    """⑦两个 header 工厂返回 dict 且含非空 UA/Referer（:18-37）。"""
    for headers in (m.get_sina_headers(), m.get_em_headers()):
        assert isinstance(headers, dict)
        assert headers.get("User-Agent")
        assert headers.get("Referer")
