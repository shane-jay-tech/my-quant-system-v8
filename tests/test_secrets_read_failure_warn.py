# -*- coding: utf-8 -*-
"""S4CD-2 可观测性（20260915-123647-66d5）：secrets 读取失败的一次性 stderr 告警。

断言三件事：失败时 stderr 出现告警（含路径与原因）、告警与回显里绝无键值、
正常路径零告警；同路径同原因同进程只告警一次。
"""
import pytest

from core import secrets


@pytest.fixture()
def clear_warned():
    secrets._WARNED_READ_FAILURES.clear()
    yield
    secrets._WARNED_READ_FAILURES.clear()


def test_parse_failure_warns_once_without_leaking_values(tmp_path, monkeypatch, capsys, clear_warned):
    bad = tmp_path / "broken.env"
    bad.write_text("BARK_TOKEN=super-secret-value-42", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk exploded")

    monkeypatch.setattr(secrets, "open", boom, raising=False)
    assert secrets._load_kv(str(bad), (11, 22), "env") == {}
    err = capsys.readouterr().err
    assert "read failure" in err
    assert str(bad) in err
    assert "OSError" in err
    assert "super-secret-value-42" not in err
    assert "BARK_TOKEN=super-secret-value-42" not in err

    # 同一路径换指纹再失败：仍只告警一次（去重台账命中）
    secrets._load_kv(str(bad), (33, 44), "env")
    assert capsys.readouterr().err == ""


def test_missing_file_warns_once(tmp_path, capsys, clear_warned):
    missing = tmp_path / "nope.env"
    assert secrets._load_kv(str(missing), (-1, -1), "env") == {}
    err = capsys.readouterr().err
    assert "missing" in err and str(missing) in err
    assert "super-secret" not in err


def test_invalid_json_warns_without_content(tmp_path, capsys, clear_warned):
    bad = tmp_path / "broken.json"
    bad.write_text('{"bark_tokens": ["C291-secret", "A499-secret"],', encoding="utf-8")
    assert secrets._load_json_raw(str(bad), (7, 7)) == {}
    err = capsys.readouterr().err
    assert "parse/read failed" in err and str(bad) in err
    assert "C291-secret" not in err and "A499-secret" not in err


def test_healthy_path_is_silent(tmp_path, capsys, clear_warned):
    good = tmp_path / "good.env"
    good.write_text("BARK_TOKEN=super-secret-value-42\n", encoding="utf-8")
    fp = secrets._fingerprint(good)
    assert secrets._load_kv(str(good), fp, "env") == {"BARK_TOKEN": "super-secret-value-42"}
    assert capsys.readouterr().err == ""
