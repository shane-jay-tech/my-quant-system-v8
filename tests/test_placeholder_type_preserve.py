# -*- coding: utf-8 -*-
"""p911r-37：JSON 占位层原始类型保持回归用例（09437c0 修复场景矩阵化）。

场景：data/secrets.json 占位层含 list/dict/int/bool 值时，_load_json_raw 读回
必须保持原始类型（此前 _load_kv 的 str() 曾把 bark_tokens 列表打成字符串，致实推失败）。
只读真实凭据：全程使用 tmp_path 临时 JSON，不读 data/secrets.json 明文。
"""
import json
from pathlib import Path

from core.secrets import _load_json_raw


def _write(tmp_path: Path, payload: dict) -> tuple[Path, tuple[int, int]]:
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    from core.secrets import _fingerprint
    return p, _fingerprint(p)


def test_list_value_stays_list_of_str(tmp_path):
    """bark_tokens 列表场景（09437c0 回归本体）：读回仍是 list 且元素为 str。"""
    p, fp = _write(tmp_path, {"bark_tokens": ["C291abc", "A499def"]})
    data = _load_json_raw(p, fp)
    assert isinstance(data["bark_tokens"], list)
    assert data["bark_tokens"] == ["C291abc", "A499def"]
    assert all(isinstance(x, str) for x in data["bark_tokens"])


def test_dict_value_stays_dict(tmp_path):
    p, fp = _write(tmp_path, {"nested": {"a": 1, "b": "two"}})
    data = _load_json_raw(p, fp)
    assert isinstance(data["nested"], dict)
    assert data["nested"] == {"a": 1, "b": "two"}


def test_int_value_stays_int(tmp_path):
    p, fp = _write(tmp_path, {"retry_limit": 3})
    data = _load_json_raw(p, fp)
    assert isinstance(data["retry_limit"], int)
    assert data["retry_limit"] == 3
    assert not isinstance(data["retry_limit"], bool)


def test_bool_value_stays_bool(tmp_path):
    p, fp = _write(tmp_path, {"enabled": True, "disabled": False})
    data = _load_json_raw(p, fp)
    assert data["enabled"] is True
    assert data["disabled"] is False


def test_missing_file_returns_empty_dict(tmp_path):
    """文件不存在（fp=(-1,-1) 哨兵）→ 空 dict，不抛错。"""
    assert _load_json_raw(tmp_path / "nope.json", (-1, -1)) == {}
