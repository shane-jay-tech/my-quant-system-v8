"""
推送渠道注册表 v1（v8.7 预备：交付层 P0-3）

借鉴 TradingAgents-CN-studio 的 notify 设计：
- Channel 抽象 + registry.register 注册式扩展
- 配置键支持 "type#别名"，同类型可配多个实例（如两个飞书群）
- 逐渠道失败隔离：一个渠道挂了不影响其他渠道，结果逐条返回
- Bark 始终保留为默认渠道（有 token 就发），新渠道零配置不影响老行为

配置来源（优先级：环境变量 > data/secrets.json:notify_channels）：
    secrets.json:
      "notify_channels": {
        "webhook":        {"url": "https://..."},
        "feishu":         {"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx", "secret": ""},
        "feishu#决策群":  {"webhook": "..."}
      }
    环境变量：QUANT_NOTIFY_WEBHOOK_URL / QUANT_FEISHU_WEBHOOK / QUANT_FEISHU_SECRET

用法：
    from bark_sender.channels import push_all
    for line in push_all("标题", "正文"): print(line)
"""
from __future__ import annotations

import abc
import base64
import hashlib
import hmac
import json
import os
import time

import requests

from .config import BARK_TOKENS, _SECRETS_PATH


class Channel(abc.ABC):
    name: str = 'base'
    alias: str = ''

    @abc.abstractmethod
    def send(self, title: str, body: str) -> None:
        """发送；失败抛异常，由 push_all 逐条记录。"""


class ChannelRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, type[Channel]] = {}

    def register(self, cls: type[Channel]) -> type[Channel]:
        self._factories[cls.name] = cls
        return cls

    def names(self) -> list[str]:
        return sorted(self._factories)

    def build(self, ctype: str, options: dict, alias: str = '') -> Channel:
        if ctype not in self._factories:
            raise KeyError(f"未知推送渠道: {ctype}（可用: {self.names()}）")
        ch = self._factories[ctype](options or {})
        ch.alias = alias or ctype
        return ch


registry = ChannelRegistry()


@registry.register
class BarkChannel(Channel):
    name = 'bark'

    def __init__(self, options: dict):
        self.tokens = list(options.get('tokens') or BARK_TOKENS)
        if not self.tokens:
            raise ValueError('bark 渠道没有 token（data/secrets.json:bark_tokens）')

    def send(self, title: str, body: str) -> None:
        from .push import send_bark
        if not send_bark(title, body, tokens=self.tokens):
            raise RuntimeError('Bark 服务端未确认发送成功')


@registry.register
class WebhookChannel(Channel):
    """通用 JSON webhook：POST {title, body, source}。"""
    name = 'webhook'

    def __init__(self, options: dict):
        self.url = str(options.get('url') or '')
        self.timeout = int(options.get('timeout', 15))
        if not self.url:
            raise ValueError('webhook 渠道缺少 url')

    def send(self, title: str, body: str) -> None:
        r = requests.post(self.url, json={'title': title, 'body': body, 'source': 'my-quant-system-v8'},
                          timeout=self.timeout)
        r.raise_for_status()


def _feishu_sign(secret: str, ts: int) -> str:
    digest = hmac.new(f"{ts}\n{secret}".encode('utf-8'), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode('utf-8')


@registry.register
class FeishuChannel(Channel):
    """飞书群自定义机器人 webhook（可选签名）。"""
    name = 'feishu'

    def __init__(self, options: dict):
        self.webhook = str(options.get('webhook') or '')
        self.secret = str(options.get('secret') or '')
        if not self.webhook:
            raise ValueError('feishu 渠道缺少 webhook')

    def send(self, title: str, body: str) -> None:
        payload: dict = {
            'msg_type': 'interactive',
            'card': {
                'header': {'title': {'tag': 'plain_text', 'content': title[:60]}, 'template': 'blue'},
                'elements': [{'tag': 'markdown', 'content': body[:4000]}],
            },
        }
        if self.secret:
            ts = int(time.time())
            payload['timestamp'] = str(ts)
            payload['sign'] = _feishu_sign(self.secret, ts)
        r = requests.post(self.webhook, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json() if r.content else {}
        # 飞书永远 200，错误藏在 code 里
        if result.get('code') not in (0, None) or result.get('StatusCode') not in (0, None):
            raise RuntimeError(f"飞书返回错误: {result}")


# ============================================================
# 配置 → 渠道实例
# ============================================================
def load_channel_config() -> dict[str, dict]:
    cfg: dict[str, dict] = {}
    if os.path.exists(_SECRETS_PATH):
        try:
            with open(_SECRETS_PATH, 'r', encoding='utf-8') as f:
                sec = json.load(f)
            nc = sec.get('notify_channels') or {}
            if isinstance(nc, dict):
                cfg.update({k: (v or {}) for k, v in nc.items() if isinstance(v, dict)})
        except Exception as exc:
            print(f"[NOTIFY] secrets.json 解析失败，忽略 notify_channels: {exc}", flush=True)
    if url := os.environ.get('QUANT_NOTIFY_WEBHOOK_URL'):
        cfg['webhook#env'] = {'url': url}
    if wh := os.environ.get('QUANT_FEISHU_WEBHOOK'):
        cfg['feishu#env'] = {'webhook': wh, 'secret': os.environ.get('QUANT_FEISHU_SECRET', '')}
    return cfg


def build_channels(cfg: dict | None = None, include_bark: bool = True) -> list[Channel]:
    """构建全部可用渠道。配置不全的渠道跳过并打印原因，不抛异常。"""
    cfg = load_channel_config() if cfg is None else cfg
    channels: list[Channel] = []
    if include_bark and BARK_TOKENS:
        channels.append(registry.build('bark', {}))
    for key, options in cfg.items():
        ctype, _, alias = key.partition('#')
        if ctype == 'bark':
            continue  # Bark 由 include_bark 统一处理
        try:
            channels.append(registry.build(ctype, options, alias=alias or ctype))
        except Exception as exc:
            print(f"[NOTIFY] 跳过渠道 {key}: {exc}", flush=True)
    return channels


def push_all(title: str, body: str, channels: list[Channel] | None = None) -> list[str]:
    """向所有渠道推送，返回逐渠道结果行（'OK xxx' / 'FAIL xxx: 异常类型'）。

    v8.7 安全修复：失败原因只保留异常类名——requests 异常原文常含完整 webhook URL，
    会随 daily_pipeline 日志落盘，等于把推送凭据写进日志。
    """
    channels = build_channels() if channels is None else channels
    if not channels:
        return ['FAIL 没有任何可用推送渠道（配置 data/secrets.json:bark_tokens 或 notify_channels）']
    results = []
    for ch in channels:
        label = ch.alias or ch.name
        try:
            ch.send(title, body)
            results.append(f"OK {label}")
        except Exception as exc:
            results.append(f"FAIL {label}: {type(exc).__name__}")
    return results
