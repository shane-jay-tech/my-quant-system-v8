"""S4-a 地基批单测（2026-09-10）：core/paths.py 与 core/secrets.py 骨架。

锁定行为：
1. paths：REPO_ROOT 锚点、目录常量、data_file 往返、dated_file 命名、
   latest_dated 取最新、ensure_dir 幂等。
2. secrets：环境变量层解析、缺失 fail-closed（None / MissingSecretError）、
   错误文案只出 `***` 占位不泄漏、llm_available 只回布尔。
本测试不读取、不打印任何真实凭据值（占位值一律用假值 dummy）。
"""
from __future__ import annotations

import datetime as dt

import pytest

from core.paths import (
    BACKUP_DIR,
    DATA_DIR,
    LOGS_DIR,
    ORDERS_DIR,
    REPO_ROOT,
    RESULTS_DIR,
    REPORTS_DIR,
    data_file,
    dated_file,
    ensure_dir,
    latest_dated,
)
from core.secrets import MissingSecretError, get_secret, llm_available


# ---------- paths ----------

def test_repo_root_anchor():
    assert (REPO_ROOT / 'core' / 'paths.py').is_file()
    assert REPO_ROOT.name not in ('', '.')


def test_dir_constants_under_root():
    for d in (DATA_DIR, RESULTS_DIR, REPORTS_DIR, LOGS_DIR, ORDERS_DIR, BACKUP_DIR):
        assert d.parent == REPO_ROOT


def test_data_file_roundtrip():
    assert data_file('stock_20260910.csv') == REPO_ROOT / 'data' / 'stock_20260910.csv'


def test_dated_file_naming():
    p = dated_file(DATA_DIR, 'stock', 'csv', dt.date(2026, 9, 10))
    assert p.name == 'stock_20260910.csv'
    assert dated_file(DATA_DIR, 'h', '.csv', dt.date(2026, 1, 2)).name == 'h_20260102.csv'


def test_latest_dated_picks_max(tmp_path):
    (tmp_path / 'stock_20260901.csv').write_text('a', encoding='utf-8')
    (tmp_path / 'stock_20260910.csv').write_text('b', encoding='utf-8')
    (tmp_path / 'stock_note.csv').write_text('noise', encoding='utf-8')
    assert latest_dated(tmp_path, 'stock', 'csv') == tmp_path / 'stock_20260910.csv'


def test_latest_dated_empty_and_missing_dir(tmp_path):
    assert latest_dated(tmp_path / 'nope', 'stock', 'csv') is None
    assert latest_dated(tmp_path, 'nomatch', 'csv') is None


def test_ensure_dir_idempotent(tmp_path):
    p = ensure_dir(tmp_path / 'a' / 'b')
    assert p.is_dir()
    assert ensure_dir(p) == p


def test_paths_module_has_no_chdir():
    import inspect

    import core.paths as paths_mod
    src = inspect.getsource(paths_mod)
    assert 'os.chdir(' not in src


# ---------- secrets ----------

def test_env_layer_resolution(monkeypatch):
    monkeypatch.setenv('S4A_DUMMY_KEY', 'dummy-value-not-a-real-secret')
    assert get_secret('S4A_DUMMY_KEY') == 'dummy-value-not-a-real-secret'


def test_missing_secret_returns_none_fail_closed(monkeypatch):
    monkeypatch.delenv('S4A_DEFINITELY_MISSING', raising=False)
    assert get_secret('S4A_DEFINITELY_MISSING') is None


def test_missing_required_raises(monkeypatch):
    monkeypatch.delenv('S4A_DEFINITELY_MISSING', raising=False)
    with pytest.raises(MissingSecretError) as ei:
        get_secret('S4A_DEFINITELY_MISSING', required=True)
    assert ei.value.name == 'S4A_DEFINITELY_MISSING'


def test_error_message_uses_placeholder_only():
    msg = str(MissingSecretError('S4A_ANY'))
    assert '***' in msg
    assert 'S4A_ANY' in msg


def test_registry_names_resolvable_shape():
    # 已知名单解析结果要么 None 要么非空字符串；本断言不落任何值。
    for name in ('DEEPSEEK_API_KEY', 'GPT_API_KEY', 'BARK_URL', 'BARK_KEY'):
        v = get_secret(name)
        assert v is None or (isinstance(v, str) and len(v) > 0)


def test_llm_available_returns_bool():
    assert llm_available() in (True, False)

# ---------- S4-d 回归：列表/对象型占位配置不得被 str() 破坏（2026-09-11 实推暴露） ----------

def test_secret_list_and_object_keep_types(tmp_path, monkeypatch):
    """实推事故回归：bark_tokens 列表曾被 _load_kv 的 str() 变成 "['a','b']" 当成单个 token。

    现象：Bark 服务端回「token错误或者失效」；根因是 JSON 占位层读成了字符串。
    本测试用假值（dummy），不读真实凭据。
    """
    import json as _json

    from core import secrets as sec

    fake = tmp_path / "secrets.json"
    fake.write_text(_json.dumps({
        "bark_tokens": ["dummy-aaa", "dummy-bbb"],
        "bark_token": "dummy-single",
        "notify_channels": {"webhook#x": {"url": "https://example.invalid/hook"}},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sec, "_SECRETS_JSON_PATH", fake)
    monkeypatch.setattr(sec, "_ENV_LOCAL_PATH", tmp_path / "no-env.local")
    monkeypatch.delenv("BARK_TOKENS", raising=False)
    monkeypatch.delenv("BARK_KEY", raising=False)
    monkeypatch.delenv("NOTIFY_CHANNELS", raising=False)

    tokens = sec.get_secret_list("BARK_TOKENS")
    assert tokens == ["dummy-aaa", "dummy-bbb"]
    assert all("[" not in t and "'" not in t for t in tokens), "不允许返回列表的字符串表示"
    assert sec.get_secret("BARK_KEY") == "dummy-single"
    channels = sec.get_secret_object("NOTIFY_CHANNELS")
    assert channels == {"webhook#x": {"url": "https://example.invalid/hook"}}
    assert sec.get_secret_object("NOTIFY_CHANNELS_MISSING") == {}


def test_secret_list_env_single_value(tmp_path, monkeypatch):
    """环境变量层命中时，列表型凭据返回单元素列表。"""
    from core import secrets as sec

    monkeypatch.setattr(sec, "_SECRETS_JSON_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(sec, "_ENV_LOCAL_PATH", tmp_path / "no-env.local")
    monkeypatch.setenv("BARK_TOKENS", "dummy-env")
    assert sec.get_secret_list("BARK_TOKENS") == ["dummy-env"]
