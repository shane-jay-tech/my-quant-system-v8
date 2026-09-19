# -*- coding: utf-8 -*-
"""渠道注册表与配置校验路径钉桩（q918-34）。

⚠ **红线声明（部分范围）**：任务书还要求"已知 secret+ts 钉签名前缀与长度"，
`_feishu_sign`（`bark_sender/channels.py:102`）是 HMAC-SHA256 签名＝**鉴权/加密凭据域**，
夜班协议对该域只允许只读报告 ⇒ 本文件**不测签名、不调 `FeishuChannel.send()`**（那会真的执行签名分支）。
签名与 feishu 发送分支（:118-146、:102-103）留白，差额与交接说明见 outbox 结果。

钉的是注册表与校验：`registry.names/build` 的未知渠道 KeyError 文案（:61）、
三处配置守卫 ValueError（:77 bark 无 token、:94 webhook 缺 url、:116 feishu 缺 webhook）、
`BarkChannel.send` 两个分支（:80-82，`push.send_bark` 打桩不联网）、
`build_channels` 对坏配置的静默跳过（:160-166），以及 `push_all` 失败行**只留异常类名**
（:169-181 的安全设计：requests 异常原文含完整 webhook URL，会把推送凭据写进日志）。
可复跑：python -m pytest tests/test_bark_channels_sign_charac.py -q
"""
from __future__ import annotations

import pytest

import bark_sender.channels as ch


# --- 注册表 -------------------------------------------------------------------


def test_registry_names_is_sorted_list_of_registered():
    assert ch.registry.names() == ['bark', 'feishu', 'webhook']


def test_register_decorator_returns_class_unchanged():
    """`register` 既入表又原样返回类（作为装饰器用时不能吞掉类对象）。"""

    class _Probe(ch.Channel):
        name = 'probe_tmp'

        def send(self, title, body):
            return None

    assert ch.registry.register(_Probe) is _Probe
    assert 'probe_tmp' in ch.registry.names()
    ch.registry._factories.pop('probe_tmp')  # 复原，别污染其它用例


def test_build_unknown_channel_keyerror_lists_available_names():
    with pytest.raises(KeyError) as ei:
        ch.registry.build('sms', {})
    msg = str(ei.value)
    assert '未知推送渠道' in msg and 'sms' in msg
    for n in ch.registry.names():
        assert n in msg  # 可用清单全列出，便于运维照着改配置


def test_build_alias_falls_back_to_ctype_and_none_options_still_hits_guard():
    """`alias or ctype`（:65）空别名回落类型名；`options or {}`（:63）让 None 不再抛 TypeError，
    但缺 url 仍按 :94 守卫报错——两条语义分开钉。"""
    a = ch.registry.build('webhook', {'url': 'https://example.invalid/hook'}, alias='')
    b = ch.registry.build('webhook', {'url': 'https://example.invalid/hook2'}, alias='决策群')
    assert (a.alias, b.alias) == ('webhook', '决策群')
    assert (a.name, b.name) == ('webhook', 'webhook')  # name 是类属性，不受 alias 影响
    with pytest.raises(ValueError):
        ch.registry.build('webhook', None)


# --- 三处配置守卫 --------------------------------------------------------------


def test_bark_without_any_token_raises_with_remedy_hint(monkeypatch):
    monkeypatch.setattr(ch, 'BARK_TOKENS', [])
    with pytest.raises(ValueError) as ei:
        ch.registry.build('bark', {})
    assert str(ei.value) == 'bark 渠道没有 token（data/secrets.json:bark_tokens）'


def test_bark_copies_tokens_from_options_not_by_reference(monkeypatch):
    """`list(options.get('tokens') or BARK_TOKENS)`（:75）：改渠道实例不该动模块级常量。"""
    monkeypatch.setattr(ch, 'BARK_TOKENS', ['fake-shared-1'])
    inst = ch.registry.build('bark', {})
    assert inst.tokens == ['fake-shared-1']
    inst.tokens.append('fake-extra')
    assert ch.BARK_TOKENS == ['fake-shared-1']


def test_webhook_missing_url_and_feishu_missing_webhook_messages():
    """两条 ValueError 文案逐字钉住（运维在日志里看到的是这句，改字要过测试）。"""
    with pytest.raises(ValueError) as e1:
        ch.registry.build('webhook', {})
    assert str(e1.value) == 'webhook 渠道缺少 url'
    with pytest.raises(ValueError) as e2:
        ch.registry.build('feishu', {'webhook': ''})
    assert str(e2.value) == 'feishu 渠道缺少 webhook'


def test_whitespace_only_webhook_url_passes_the_guard(monkeypatch):
    """现状（不是期望）：守卫是 `str(options.get('url') or '')` 后判真值——
    纯空白串 `'   '` 是 truthy，于是**建得出一个坏渠道**，错误推迟到 send 时才炸。
    钉住它，免得哪天"顺手收紧校验"没人发现行为变了。
    （`requests.post` 全程打桩，本文件零真实网络。）"""
    def boom(url, **kw):
        raise RuntimeError('403 Client Error for url: https://hooks.invalid/hook/TOKEN-LEAK')

    monkeypatch.setattr(ch.requests, 'post', boom)
    inst = ch.WebhookChannel({'url': '   '})
    assert inst.url == '   '
    assert len(ch.build_channels({'webhook': {'url': '   '}}, include_bark=False)) == 1  # 渠道被建出来
    res = ch.push_all('t', 'b', channels=[inst])
    assert res == ['FAIL webhook: RuntimeError']  # 只剩异常类名，原文里的 hook token 不外泄


def test_webhook_timeout_coerced_to_int_with_default_15():
    assert ch.WebhookChannel({'url': 'https://example.invalid/h'}).timeout == 15
    assert ch.WebhookChannel({'url': 'u', 'timeout': '7'}).timeout == 7


# --- BarkChannel.send 两分支（打桩，不联网、不真推）------------------------------


def test_bark_send_raises_runtime_when_server_unconfirmed(monkeypatch):
    monkeypatch.setattr('bark_sender.push.send_bark', lambda *a, **k: False)
    inst = ch.registry.build('bark', {'tokens': ['fake-a']})
    with pytest.raises(RuntimeError) as ei:
        inst.send('t', 'b')
    assert str(ei.value) == 'Bark 服务端未确认发送成功'


def test_bark_send_passes_tokens_and_silent_on_true(monkeypatch):
    seen = {}

    def fake_send_bark(title, body, tokens=None):
        seen.update({'title': title, 'body': body, 'tokens': tokens})
        return True

    monkeypatch.setattr('bark_sender.push.send_bark', fake_send_bark)
    inst = ch.registry.build('bark', {'tokens': ['fake-a', 'fake-b']})
    inst.send('标题', '正文')
    assert seen == {'title': '标题', 'body': '正文', 'tokens': ['fake-a', 'fake-b']}


# --- build_channels：坏配置静默跳过 --------------------------------------------


def test_build_channels_skips_unknown_and_bark_keys_without_raising(capsys):
    """`registry.build` 单独调用会 KeyError，但 `build_channels` 把它 catch 掉只打印
    （:160-166）；`bark` 键在 cfg 里被 `continue` 让位给 include_bark。"""
    chans = ch.build_channels({'sms': {'x': 1}, 'bark': {'tokens': ['fake-c']},
                               'webhook': {'url': 'https://example.invalid/h'}}, include_bark=False)
    assert [c.name for c in chans] == ['webhook']
    printed = capsys.readouterr().out
    # KeyError 的 str() 只带消息不带类名（`str(KeyError('x')) == "'x'"`），所以钉消息
    assert '跳过渠道 sms' in printed and '未知推送渠道' in printed


def test_build_channels_includes_bark_only_when_tokens_present(monkeypatch):
    monkeypatch.setattr(ch, 'BARK_TOKENS', ['fake-shared-1'])
    assert [c.name for c in ch.build_channels({}, include_bark=True)] == ['bark']
    monkeypatch.setattr(ch, 'BARK_TOKENS', [])
    assert ch.build_channels({}, include_bark=True) == []


# --- push_all：失败行不得带异常原文（凭据不落日志）------------------------------


def test_push_all_result_lines_contain_only_exception_class_name(monkeypatch):
    """安全钉桩：失败行必须是 `FAIL <label>: <ExcName>`，**不得**出现异常消息——
    requests 的异常原文常含完整 webhook URL（含 hook token），进日志等于泄凭据。"""
    class _Boom(RuntimeError):
        pass

    class _Bad(ch.Channel):
        name = 'bad'
        alias = 'bad#alias'

        def send(self, title, body):
            raise _Boom("403 Client Error for url: https://hooks.invalid/bot/send/fake-secret-token")

    lines = ch.push_all('t', 'b', channels=[_Bad()])
    assert lines == ['FAIL bad#alias: _Boom']
    joined = ' '.join(lines)
    for leak in ('https', 'hooks.invalid', 'fake-secret-token', '403'):
        assert leak not in joined


def test_push_all_without_any_channel_returns_single_fail_line(monkeypatch):
    monkeypatch.setattr(ch, 'BARK_TOKENS', [])
    monkeypatch.setattr(ch, 'load_channel_config', lambda: {})
    out = ch.push_all('t', 'b')
    assert len(out) == 1 and out[0].startswith('FAIL 没有任何可用推送渠道')
