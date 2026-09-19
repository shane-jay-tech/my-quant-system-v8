"""q918-10：bark_sender/config.py token 载入三态 characterization。

冻结现值：bark_tokens 列表优先（滤空元素）→ bark_token 单值兜底 → 空列表＋「未配置」迁移提示。
脱敏红线：测试零真实 token 值（占位假串，断言只用 len/类型）；secrets 源头全 monkeypatch。
"""

from __future__ import annotations

import bark_sender.config as bcfg


def test_token_list_priority_and_empty_filtered(monkeypatch):
    """bark_tokens 列表存在 → 原样返回但滤掉空元素，长度与类型冻结。"""
    monkeypatch.setattr(bcfg, "get_secret_list", lambda key: ["占位假串A", "", "占位假串B"])
    monkeypatch.setattr(bcfg, "get_secret", lambda key: None)
    tokens = bcfg._load_bark_tokens()
    assert isinstance(tokens, list) and len(tokens) == 2
    assert all(isinstance(t, str) and t for t in tokens)


def test_single_token_fallback_when_list_empty(monkeypatch):
    """列表为空 → bark_token 单值兜底，包装成单元素列表。"""
    monkeypatch.setattr(bcfg, "get_secret_list", lambda key: [])
    monkeypatch.setattr(bcfg, "get_secret", lambda key: "占位假串S")
    tokens = bcfg._load_bark_tokens()
    assert isinstance(tokens, list) and len(tokens) == 1
    assert isinstance(tokens[0], str)


def test_no_token_returns_empty_with_migration_hint(monkeypatch, capsys):
    """两者皆缺 → 空列表＋「未配置」提示打印（v8.7 不再假成功）。"""
    monkeypatch.setattr(bcfg, "get_secret_list", lambda key: None)
    monkeypatch.setattr(bcfg, "get_secret", lambda key: None)
    tokens = bcfg._load_bark_tokens()
    assert tokens == []
    out = capsys.readouterr().out
    assert "[BARK] 未配置 Bark token" in out
