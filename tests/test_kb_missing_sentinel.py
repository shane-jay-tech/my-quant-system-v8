# -*- coding: utf-8 -*-
"""KB_FILE 缺失告警哨兵——测试先行（q918-31，xfail 钉期望，零生产码改动）。

期望来源：`docs/insights/quant-kb-convergence-prereq-20260917.md:18`
「删分支＝行为变更（KB_FILE 意外缺失时由『静默回退旧源』变为『读空』）——建议拍板时同步加『KB_FILE 缺失即启动告警』哨兵。」

被钉的两个实现（**同一逻辑存在两份拷贝**，正是该哨兵要防的漂移面）：
- `integrate_knowledge.py:195 _read_kb_content()`（告警前缀 `[KNOWLEDGE]`）
- `evolve_strategy.py:35 _read_kb_content()`（告警前缀 `[EVOLVE]`）

现状（`test_kb_missing_*` 之非 xfail 组所钉）：KB_FILE 缺失但 CLAUDE.md 仍有「# 量化策略知识库」旧节时**会**打迁移提示；
**两个来源都不在盘时静默返回 ''，stderr 一个字节都没有** ⇒ 无人值守的日终流水线不会知道知识库断了。

拍板落地后本文件要一起改：xfail 组（期望）转 pass 并摘装饰器；`test_kb_silent_when_both_absent_today`（现状）改写成断言告警。
可复跑：python -m pytest tests/ -q -k kb
"""
from __future__ import annotations

import os

import pytest

import evolve_strategy as ev
import integrate_knowledge as ik

LEGACY_SECTION = '# 量化策略知识库'
MODULES = [pytest.param(ik, '[KNOWLEDGE]', id='integrate_knowledge'),
           pytest.param(ev, '[EVOLVE]', id='evolve_strategy')]


def _absent(monkeypatch, mod, tmp_path):
    """把两个来源都指到不存在的路径（不碰真实 docs/knowledge/quant-kb.md）。"""
    monkeypatch.setattr(mod, 'KB_FILE', str(tmp_path / 'nope' / 'quant-kb.md'))
    monkeypatch.setattr(mod, 'CLAUDE_MD', str(tmp_path / 'nope' / 'CLAUDE.md'))


# --- 期望（未实现）→ xfail 钉桩 ------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason='KB_FILE 与 CLAUDE.md 双缺失时静默返回空串，无 stderr 告警（哨兵待 n916d-19 拍板后加）',
)
@pytest.mark.parametrize('mod,label', MODULES)
def test_kb_missing_both_absent_should_warn(mod, label, monkeypatch, tmp_path, capsys):
    _absent(monkeypatch, mod, tmp_path)
    assert mod._read_kb_content() == ''
    captured = capsys.readouterr()
    assert captured.err != '', f'期望 {label} 前缀的启动告警，实际 stderr 为空'
    assert 'KB_FILE' in captured.err


# --- 现状钉桩（三条，全绿）------------------------------------------------------


def test_kb_silent_when_both_absent_today(monkeypatch, tmp_path, capsys):
    """钉住"今天就是静默"——与上面的 xfail 是一对，哨兵落地时两条要一起改。"""
    _absent(monkeypatch, ik, tmp_path)
    _absent(monkeypatch, ev, tmp_path)
    capsys.readouterr()

    assert ik._read_kb_content() == ''
    assert ev._read_kb_content() == ''
    err = capsys.readouterr().err
    assert err == ''  # 两个模块都没吭声


@pytest.mark.parametrize('mod,label', MODULES)
def test_kb_fallback_to_legacy_section_does_warn(mod, label, monkeypatch, tmp_path, capsys):
    """回退分支自身已有告警（现成行为，钉住它，免得"删回退分支"时静默混过去）。"""
    legacy = tmp_path / 'CLAUDE.md'
    legacy.write_text(f'{LEGACY_SECTION}\n\n- [待验证] 样例条目\n', encoding='utf-8')
    monkeypatch.setattr(mod, 'KB_FILE', str(tmp_path / 'nope.md'))
    monkeypatch.setattr(mod, 'CLAUDE_MD', str(legacy))

    content = mod._read_kb_content()
    err = capsys.readouterr().err

    assert LEGACY_SECTION in content and '[待验证] 样例条目' in content
    assert 'KB_FILE 缺失' in err and label in err


@pytest.mark.parametrize('mod', [p.values[0] for p in MODULES], ids=['integrate_knowledge', 'evolve_strategy'])
def test_kb_reads_kb_file_when_present_without_warning(mod, monkeypatch, tmp_path, capsys):
    kb = tmp_path / 'quant-kb.md'
    kb.write_text(f'{LEGACY_SECTION}\n正文\n', encoding='utf-8')
    monkeypatch.setattr(mod, 'KB_FILE', str(kb))
    monkeypatch.setattr(mod, 'CLAUDE_MD', str(tmp_path / 'nope.md'))

    assert LEGACY_SECTION in mod._read_kb_content()
    assert capsys.readouterr().err == ''  # 正常路径不该有告警


def test_kb_has_two_separate_implementations(monkeypatch, tmp_path):
    """同一份"双读"逻辑在两个模块各有一份拷贝（前缀不同），漂移成本由这条记录在案：
    哨兵/文案将来若只改一处，本用例的对照仍为真但语义已分叉。"""
    assert ik._read_kb_content is not ev._read_kb_content
    assert str(ik.KB_FILE) == str(ev.KB_FILE)   # 数据源单一来自 core.paths:25，这点是统一的
    # CLAUDE_MD 则由两模块各自硬编码（integrate_knowledge.py:26 / evolve_strategy.py:24），值相同但非共享常量
    assert ik.CLAUDE_MD == ev.CLAUDE_MD == os.path.join(ik.BASE_DIR, 'CLAUDE.md')
