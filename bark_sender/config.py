"""
Bark 推送模块配置（v8.7 清理版）

- Bark token 只从 data/secrets.json 读取（bark_tokens 列表优先，其次 bark_token 单值）
- v8.7: 删除源码里的硬编码 token 回退——凭据零硬编码；没配 token 时 BARK_TOKENS 为空列表，
  send_bark() 会明确返回 False 并打印迁移提示，不再静默"假成功"
- v8.7: 删除 RESULTS_DIR/REPORTS_DIR 等指向 bark_sender/ 子目录的错误常量（从未被引用，
  且与 parsers.py 里指向项目根的同名常量冲突）
"""
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(BASE_DIR)
_SECRETS_PATH = os.path.join(_PROJECT_ROOT, 'data', 'secrets.json')


def _read_secrets() -> dict:
    if not os.path.exists(_SECRETS_PATH):
        return {}
    try:
        with open(_SECRETS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_bark_tokens() -> list:
    sec = _read_secrets()
    tokens = sec.get('bark_tokens') or []
    if isinstance(tokens, list) and tokens:
        return [str(t) for t in tokens if t]
    token = sec.get('bark_token', '')
    if token:
        return [str(token)]
    print("[BARK] 未配置 Bark token：请在 data/secrets.json 写入 bark_tokens 列表", flush=True)
    return []


BARK_TOKENS = _load_bark_tokens()
BARK_TOKEN = BARK_TOKENS[0] if BARK_TOKENS else ''
