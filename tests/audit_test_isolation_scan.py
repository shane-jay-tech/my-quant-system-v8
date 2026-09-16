# -*- coding: utf-8 -*-
"""audit_test_isolation v2 扫描器单测（d914-07）。

golden 哨兵：已知误报形态不再命中（tmp_path 变量链、同行豁免），
已知违规形态必报（裸写/裸赋值/网络）。直接喂内联片段给 audit_text。
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_test_isolation import audit_text  # noqa: E402


def cats(result):
    return {f['category'] for f in result}


def test_cross_line_tmp_variable_not_flagged():
    """① 跨行上下文：open 的变量源自 tmp_path 派生 → 不报 abs-write。"""
    text = (
        "def test_x(tmp_path):\n"
        "    data_dir = tmp_path / 'data'\n"
        "    with open(data_dir / 'regime_state.json', 'w') as f:\n"
        "        f.write('{}')\n"
    )
    result = audit_text(text, 'fake.py')
    assert 'abs-write' not in cats(result)


def test_cross_line_history_variable_not_flagged():
    """①b 多行前向：window 内 `x = …tmp` 赋值链可跨 2-3 行命中。"""
    text = (
        "def test_y(tmp_path):\n"
        "    state_path = str(tmp_path / 'account_state.json')\n"
        "    with open(state_path, 'w') as f:\n"
        "        f.write('{}')\n"
    )
    result = audit_text(text, 'fake.py')
    assert 'abs-write' not in cats(result)


def test_bare_module_assign_flagged():
    """② 裸赋值规则：mod.ATTR = … 绕过 monkeypatch → 记 bare-assign。"""
    text = "newbie_protection.ACTIVITY_FILE = str(tmp_path / 'a.json')\n"
    result = audit_text(text, 'fake.py')
    assert 'bare-assign' in cats(result)


def test_monkeypatch_setattr_not_flagged_as_bare_assign():
    """②b 正确写法（monkeypatch.setattr）不得记 bare-assign。"""
    text = "monkeypatch.setattr(newbie_protection, 'ACTIVITY_FILE', str(p))\n"
    result = audit_text(text, 'fake.py')
    assert 'bare-assign' not in cats(result)


def test_real_write_without_tmp_flagged():
    """对照：真实裸写（无 tmp 痕迹）仍必须命中 abs-write。"""
    text = "with open('data/kaoyan-copy.db', 'w') as f:\n    f.write('x')\n"
    result = audit_text(text, 'fake.py')
    assert 'abs-write' in cats(result)


def test_network_import_flagged():
    """哨兵：import requests 仍必须命中 net（high）。"""
    text = "import requests\n"
    result = audit_text(text, 'fake.py')
    assert 'net' in cats(result)
