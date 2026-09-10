"""统一凭据入口（S4-a 地基批，2026-09-10）。

红线（不可越）：
- 本模块只定义「从哪读、怎么读、缺了怎么办」；日志/异常/文档中出现凭据值
  一律以 `***` 占位，本模块任何代码路径不得 print/log 真实值；
- .env.local 与 data/secrets.json 的内容与位置零改动；
- 禁止新增任何硬编码回退值（fail-closed：缺失即 None / MissingSecretError）。

解析顺序：环境变量 > REPO_ROOT/.env.local > data/secrets.json（占位配置层）。
缓存：进程内 lru_cache；.env.local / secrets.json 的 (mtime_ns, size) 指纹
变化时自动失效重读。日志只允许写 "secret resolved=yes/no" 形态的布尔结论。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache

from core.paths import DATA_DIR, REPO_ROOT

_ENV_LOCAL_PATH: "os.PathLike[str]" = REPO_ROOT / '.env.local'
_SECRETS_JSON_PATH: "os.PathLike[str]" = DATA_DIR / 'secrets.json'


class MissingSecretError(RuntimeError):
    """required=True 且凭据缺失。文案只给修复指引，不回显任何值。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"missing secret '{name}' (current value: ***). "
            f"Fix: set env var '{name}', or add '{name}=...' to .env.local, "
            f"or provide the placeholder entry in data/secrets.json."
        )


@dataclass(frozen=True)
class SecretSpec:
    """凭据注册表行：逻辑名 / 环境变量键 / 值线索说明（不含值本身）。"""

    name: str
    env_key: str
    file_hint: str


_REGISTRY: dict[str, SecretSpec] = {
    spec.name: spec
    for spec in (
        SecretSpec('DEEPSEEK_API_KEY', 'DEEPSEEK_API_KEY', 'env or .env.local'),
        SecretSpec('GPT_API_KEY', 'GPT_API_KEY', 'env or .env.local'),
        SecretSpec('BARK_URL', 'BARK_URL', 'env / .env.local / data/secrets.json:bark_url'),
        SecretSpec('BARK_KEY', 'BARK_KEY', 'env / .env.local / data/secrets.json:bark_token'),
    )
}

# 占位配置层（data/secrets.json）里的历史键名 → 注册表逻辑名
_JSON_KEY_ALIASES: dict[str, str] = {
    'DEEPSEEK_API_KEY': 'deepseek_api_key',
    'GPT_API_KEY': 'gpt_api_key',
    'BARK_URL': 'bark_url',
    'BARK_KEY': 'bark_token',
}


def _fingerprint(path: "os.PathLike[str]") -> tuple[int, int]:
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (-1, -1)


@lru_cache(maxsize=8)
def _load_kv(path: "os.PathLike[str]", fp: tuple[int, int], fmt: str) -> dict[str, str]:
    """按 (mtime_ns, size) 指纹缓存的键值读取；文件缺失/损坏 → 空表。

    fmt: 'env'=.env.local 的 KEY=VALUE 行；'json'=JSON 对象。
    值不落日志、不进异常，仅随 dict 在进程内流转。
    """
    if fp == (-1, -1):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return {}
    kv: dict[str, str] = {}
    if fmt == 'json':
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            kv = {str(k): str(v) for k, v in data.items()}
        return kv
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        kv[key.strip()] = value.strip().strip('"').strip("'")
    return kv


def get_secret(name: str, *, required: bool = False) -> str | None:
    """统一凭据入口。解析顺序：环境变量 > .env.local > data/secrets.json。

    required=True 且最终缺失 → raise MissingSecretError(name)。
    未知 name 一律按原样查环境变量与 .env.local（不进 _REGISTRY 校验），
    保持对新增凭据的开放；注册表仅作为已知名单与 JSON 键别名映射。
    """
    spec = _REGISTRY.get(name)
    env_key = spec.env_key if spec else name

    value = os.environ.get(env_key)
    if value:
        return value

    kv = _load_kv(_ENV_LOCAL_PATH, _fingerprint(_ENV_LOCAL_PATH), 'env')
    value = kv.get(env_key)
    if value:
        return value

    if spec:
        jkv = _load_kv(_SECRETS_JSON_PATH, _fingerprint(_SECRETS_JSON_PATH), 'json')
        value = jkv.get(_JSON_KEY_ALIASES.get(name, name.lower()))
        if value:
            return value

    if required:
        raise MissingSecretError(name)
    return None


def llm_available() -> bool:
    """fail-closed 布尔自检：任一 LLM key 解析成功即 True。只回布尔，不回值。"""
    return any(get_secret(n) for n in ('DEEPSEEK_API_KEY', 'GPT_API_KEY'))
