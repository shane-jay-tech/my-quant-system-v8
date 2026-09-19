"""q918-08：core/config.py 非法配置分支 characterization（基线 #8）。

冻结现值：损坏 json/空文件 → DEFAULTS 兜底＋[CONFIG] WARNING 打印（capsys 捕获）；
合法覆盖 → _deep_merge 后 get() 用户值优先；配置缺失 → tmp+os.replace 原子生成默认文件；
set_value → 原子写用户覆盖文件并立即生效。只读配置结构，零资金数值断言。
"""

from __future__ import annotations

import json

import pytest

import core.config as cc


@pytest.fixture()
def cfg_env(tmp_path, monkeypatch):
    cfg_file = tmp_path / "system_config.json"
    monkeypatch.setattr(cc, "_CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(cc, "_CACHE", None)
    monkeypatch.setattr(cc, "_CACHE_MTIME", None)
    return cfg_file


def test_corrupt_json_falls_back_to_defaults_with_warning(cfg_env, capsys):
    """损坏 json → 本次使用 DEFAULTS 兜底，且打印 [CONFIG] WARNING（:200 锚点）。"""
    cfg_env.write_text('{"tier": {"level": ', encoding="utf-8")
    cfg = cc.reload()
    assert cfg["tier"]["level"] == cc.DEFAULTS["tier"]["level"]
    out = capsys.readouterr().out
    assert "[CONFIG] WARNING" in out
    assert str(cfg_env) in out
    assert "解析失败" in out


def test_empty_file_falls_back_to_defaults(cfg_env, capsys):
    """空文件 → json 解析失败 → DEFAULTS 兜底＋告警（同分支）。"""
    cfg_env.write_text("", encoding="utf-8")
    cfg = cc.reload()
    assert cfg["tier"]["level"] == cc.DEFAULTS["tier"]["level"]
    assert "解析失败" in capsys.readouterr().out


def test_legal_override_takes_precedence_via_get(cfg_env):
    """合法覆盖文件 → _deep_merge：用户键优先、其余回落 DEFAULTS（get 点分路径）。"""
    cfg_env.write_text(json.dumps({"tier": {"level": "pro"}}), encoding="utf-8")
    assert cc.get("tier.level") == "pro"
    assert cc.get("system.version") == cc.DEFAULTS["system"]["version"]


def test_missing_file_creates_defaults_atomically(cfg_env):
    """配置缺失 → tmp+os.replace 原子生成默认配置文件，无 .tmp 残留。"""
    cfg = cc.reload()
    assert cfg_env.exists()
    assert not cfg_env.with_name(cfg_env.name + ".tmp").exists()
    on_disk = json.loads(cfg_env.read_text(encoding="utf-8"))
    assert on_disk["tier"]["level"] == cc.DEFAULTS["tier"]["level"]
    assert cfg["tier"]["level"] == cc.DEFAULTS["tier"]["level"]


def test_set_value_atomic_write_and_immediate_effect(cfg_env):
    """set_value：只写用户覆盖文件（点分路径建节点），.tmp→os.replace 原子落盘，
    json 可读回，同进程 get() 立即生效。"""
    value = cc.set_value("tier.level", "advanced")
    assert value == "advanced"
    assert not cfg_env.with_name(cfg_env.name + ".tmp").exists()
    on_disk = json.loads(cfg_env.read_text(encoding="utf-8"))
    assert on_disk["tier"]["level"] == "advanced"
    assert cc.get("tier.level") == "advanced"
