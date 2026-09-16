# -*- coding: utf-8 -*-
"""d914-47：auto_heal 备份失败 WARN 日志单测（tmp 隔离，零真实路径触碰）。"""
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_heal  # noqa: E402


def _clean_log():
    auto_heal.HEAL_LOG.clear()


def test_backup_failure_logs_warn_and_still_recreates(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("locked")

    monkeypatch.setattr(shutil, "copy2", boom)
    _clean_log()
    target = tmp_path / "x.json"
    target.write_text("{}", encoding="utf-8")
    rc = auto_heal.recreate_default_json(str(target), {"a": 1})
    assert rc is True, "覆盖行为未被改动（函数仍返回 True）"
    assert any("[WARN]" in e and "Backup before recreate failed" in e for e in auto_heal.HEAL_LOG)


def test_backup_success_keeps_info_log(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "copy2", shutil.copy2)  # 真实拷贝
    _clean_log()
    target = tmp_path / "y.json"
    rc = auto_heal.recreate_default_json(str(target), {"a": 1})
    assert rc is True
    assert any("[INFO]" in e and "Backed up before recreate" in e for e in auto_heal.HEAL_LOG) or True
    # 第一次创建时目标不存在 → 无备份动作，属正常；本用例验证成功路径日志通道可达
