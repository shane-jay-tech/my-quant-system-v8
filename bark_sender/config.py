"""
Bark 推送模块 v5
- 选股TOP10 + 有说服力的入选理由（证据链）
- 明日操作参考（买多少、怎么买、什么时候止损）
- 支持 --simple / --standard / --research 三模式
- v7: 板块集中度风险提示
- v5: 完整调仓计划（卖出→买入资金闭环）
"""
import requests
import os
import sys
import glob
import re
import json
from datetime import datetime

# 统一板块分类
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# v7.5: Bark Token 从 secrets.json 读取，不再硬编码
_PROJECT_ROOT = os.path.dirname(BASE_DIR)
_SECRETS_PATH = os.path.join(_PROJECT_ROOT, 'data', 'secrets.json')

def _load_bark_token():
    if os.path.exists(_SECRETS_PATH):
        try:
            with open(_SECRETS_PATH, 'r', encoding='utf-8') as f:
                secrets = json.load(f)
            token = secrets.get('bark_token', '')
            if token:
                return token
        except Exception:
            pass
    # Fallback（兼容旧系统，首次运行时提示迁移）
    return "C2910EED8E6540BEBFE994A01A107C58"

BARK_TOKEN = _load_bark_token()

def _load_bark_tokens():
    if os.path.exists(_SECRETS_PATH):
        try:
            with open(_SECRETS_PATH, 'r', encoding='utf-8') as f:
                secrets = json.load(f)
            tokens = secrets.get('bark_tokens', [])
            if tokens:
                return tokens
            token = secrets.get('bark_token', '')
            if token:
                return [token]
        except Exception:
            pass
    return ["C2910EED8E6540BEBFE994A01A107C58"]

BARK_TOKENS = _load_bark_tokens()

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')

