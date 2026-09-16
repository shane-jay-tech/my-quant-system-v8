"""atomic_write_json characterization（916p-a1-002）。

断言 file_io.atomic_write_json 的写入/排序/建目录/覆盖/原子性契约。
全部 tmp_path，禁止碰仓根任何路径（docs/tests-isolation-norm.md 范式五）。
可复跑：python -m pytest tests/test_file_io_atomic.py -q
"""
import json


import pytest

from utils.file_io import atomic_write_json


def test_plain_write_roundtrip(tmp_path):
    """①普通写入：文件存在且 json.load 回读相等（:22 json.dump 主路径）。"""
    p = tmp_path / "a.json"
    data = {"b": 1, "a": [1, 2]}
    atomic_write_json(str(p), data)
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == data


def test_sort_keys_false_preserves_insertion_order(tmp_path):
    """②sort_keys=False 保持插入序（:22 默认参数）：首 key 为后插入的 'z'。"""
    p = tmp_path / "order.json"
    atomic_write_json(str(p), {"z": 1, "a": 2}, sort_keys=False)
    text = p.read_text(encoding="utf-8")
    assert text.index('"z"') < text.index('"a"')


def test_sort_keys_true_sorted_and_trailing_newline(tmp_path):
    """③sort_keys=True：key 升序且文件以换行结尾（:26 f.write('\\n') alpha_gate 流派）。"""
    p = tmp_path / "sorted.json"
    atomic_write_json(str(p), {"z": 1, "a": 2}, sort_keys=True)
    text = p.read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"z"')
    assert text.endswith("\n")


def test_ensure_dir_creates_missing_parents(tmp_path):
    """④ensure_dir=True：父目录不存在也能建目录并写入（:19-20 makedirs）。"""
    p = tmp_path / "deep" / "nest" / "x.json"
    atomic_write_json(str(p), {"ok": True}, ensure_dir=True)
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": True}


def test_overwrite_existing_target(tmp_path):
    """⑤目标已存在：覆盖为新内容（os.replace :28 原子替换语义）。"""
    p = tmp_path / "b.json"
    p.write_text("old", encoding="utf-8")
    atomic_write_json(str(p), {"new": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"new": 1}


def test_unserializable_data_raises_and_original_intact(tmp_path):
    """⑥data 不可序列化 → 抛 TypeError 且原文件内容不变（os.replace :28 未达，
    目标文件绝无半成品——原子性对「目标文件」成立）。
    ⚠️ 任务书预期「目录内无 .tmp 残留」与实现不符：:24 open('.tmp','w') 先建临时
    文件，:25 json.dump 中途抛出时无清理，.tmp 会残留（characterization 如实钉死
    现状；清理改进属业务码变更，本单禁止改动，已留报告建议日间）。"""
    p = tmp_path / "c.json"
    p.write_text("original", encoding="utf-8")
    with pytest.raises(TypeError):
        atomic_write_json(str(p), object())
    assert p.read_text(encoding="utf-8") == "original"
    # 现状如实断言：失败窗口 .tmp 残留（非任务书预期的「无残留」）
    assert list(tmp_path.glob("*.tmp"))
