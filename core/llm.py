"""
统一 LLM 通道（v8.7 预备：LLM 融合层）

设计原则：
- 密钥只从环境变量或 data/secrets.json 读取，源码零硬编码
- OpenAI 兼容 chat/completions（DeepSeek 官方即此协议）
- 无 key 时 is_available() 返回 False，调用方必须优雅降级（规则兜底 / 跳过）
- 每次调用写入 cost_tracker 成本日志（真实 usage 优先，无 usage 时估算）
- 重试策略借鉴 TradingAgents-CN-studio digest：空内容加倍 max_tokens 重试一次；HTTP 错误退避重试

用法：
    from core.llm import llm_available, chat
    if llm_available():
        text, usage = chat([{"role": "user", "content": "..."}], max_tokens=800)
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SECRETS_PATH = os.path.join(BASE_DIR, 'data', 'secrets.json')

DEFAULT_BASE_URL = 'https://api.deepseek.com/v1'
DEFAULT_MODEL = 'deepseek-v4-flash'   # 成本优先：简报/分析师默认走 Flash

# DeepSeek 官方定价（元/百万 token，2026 口径，用于无 usage 时估算；有 usage 时按 usage 算）
PRICE_CNY_PER_MTOK = {
    'deepseek-v4-flash': (1.0, 3.0),
    'deepseek-v4-pro': (3.0, 9.0),
}


class LLMError(RuntimeError):
    pass


def _read_secrets() -> dict:
    if not os.path.exists(_SECRETS_PATH):
        return {}
    try:
        with open(_SECRETS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_llm_config() -> dict:
    """优先级：环境变量 > data/secrets.json > 默认值。返回 {'api_key','base_url','model'}。"""
    sec = _read_secrets()
    api_key = (os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('OPENAI_API_KEY')
               or sec.get('deepseek_api_key') or sec.get('llm_api_key') or '')
    base_url = (os.environ.get('DEEPSEEK_BASE_URL') or sec.get('deepseek_base_url')
                or sec.get('llm_base_url') or DEFAULT_BASE_URL)
    model = (os.environ.get('DEEPSEEK_MODEL') or sec.get('deepseek_model')
             or sec.get('llm_model') or DEFAULT_MODEL)
    return {'api_key': str(api_key).strip(), 'base_url': str(base_url).rstrip('/'), 'model': str(model)}


def llm_available() -> bool:
    return bool(load_llm_config()['api_key'])


def _estimate_cost_cny(model: str, input_tok: int, output_tok: int) -> float:
    in_p, out_p = PRICE_CNY_PER_MTOK.get(model, PRICE_CNY_PER_MTOK[DEFAULT_MODEL])
    return round(input_tok / 1_000_000 * in_p + output_tok / 1_000_000 * out_p, 4)


def _log_cost(operation: str, model: str, usage: dict, detail: str = '') -> None:
    """写入 cost_tracker 日志；任何异常不影响主流程。"""
    try:
        from cost_tracker import log_llm_call
        input_tok = int(usage.get('prompt_tokens') or 0)
        output_tok = int(usage.get('completion_tokens') or 0)
        cny = _estimate_cost_cny(model, input_tok, output_tok)
        log_llm_call(operation, detail, cost_override={
            'description': f'LLM {model}',
            'detail': detail,
            'model': model,
            'input_tokens': input_tok,
            'output_tokens': output_tok,
            'total_tokens': input_tok + output_tok,
            'estimated_cost_usd': round(cny / 7.2, 6),
            'estimated_cost_cny': cny,
        })
    except Exception as exc:  # pragma: no cover - 日志失败不阻断
        print(f"[LLM] cost log skipped: {exc}", flush=True)


def chat(messages: list[dict], *, max_tokens: int = 1200, temperature: float = 0.3,
         operation: str = 'llm_chat', detail: str = '', timeout: int = 120,
         retries: int = 2, model: Optional[str] = None) -> tuple[str, dict]:
    """OpenAI 兼容对话。返回 (文本, usage)。无 key 抛 LLMError，调用方应先 llm_available()。"""
    cfg = load_llm_config()
    if not cfg['api_key']:
        raise LLMError('LLM api_key 未配置（DEEPSEEK_API_KEY 或 data/secrets.json:deepseek_api_key）')
    import requests

    model = model or cfg['model']
    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': int(max_tokens),
        'temperature': float(temperature),
        'stream': False,
    }
    headers = {'Authorization': f"Bearer {cfg['api_key']}", 'Content-Type': 'application/json'}
    url = f"{cfg['base_url']}/chat/completions"

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            r.raise_for_status()
            body = r.json()
            choice = (body.get('choices') or [{}])[0]
            text = ((choice.get('message') or {}).get('content') or '').strip()
            usage = body.get('usage') or {}
            _log_cost(operation, model, usage, detail)
            if not text and attempt < retries:
                # 推理模型思考吃满 token 的常见坑：加倍重试
                payload['max_tokens'] = max(payload['max_tokens'] * 2, 2048)
                continue
            if not text:
                raise LLMError(f"模型返回空内容（finish_reason={choice.get('finish_reason')}）")
            return text, usage
        except LLMError:
            raise
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                wait = 2 * (2 ** attempt)
                print(f"[LLM] {operation} attempt {attempt + 1} failed: {exc}; retry in {wait}s", flush=True)
                time.sleep(wait)
    raise LLMError(f"{operation} 调用失败: {last_err}")


def parse_json_object(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象（容忍 ```json 围栏与前后废话）。失败返回 {}。"""
    import re
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or '').strip(), flags=re.S)
    start, end = t.find('{'), t.rfind('}')
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(t[start:end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}
