#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试隔离规范审计 v2（d914-07：跨行上下文 / 裸赋值规则 / 防回归哨兵）。

在 d913b-42 v1 基础上三处增强：
① 跨行上下文：open/写路径引用的变量若源自 tmp_path（同函数内 `x = tmp_path / …`
   或参数名含 tmp），不再误报——v1 只看单行，position_sizer/v87 两例即此类误报；
② 裸赋值规则：`mod.ATTR = …`（模块属性直接赋值且 ATTR 为全大写路径常量形态）
   记 bare-assign（中）——绕过 monkeypatch 的跨测试泄漏形态（d913b-36 初版实证）；
③ 防回归哨兵：tests/audit_test_isolation_scan.py 以内联 golden 片段锁定
   「已知误报不报 + 已知违规必报」的判定面。

只读扫描，退出码恒 0（差异是发现不是错误）。
"""
import argparse
import re
import sys
from pathlib import Path

NET_RE = re.compile(r'^\s*(import|from)\s+(requests|urllib|socket|httpx)\b', re.M)
SIM_RESULTS_RE = re.compile(r'[\'"]sim_results[/\\]')
DATA_PATH_RE = re.compile(r'[\'"](data[/\\][^\'"]*)[\'"]')
OPEN_WRITE_RE = re.compile(r'open\(([^)]*)([\'"])[wa]\+?[\'"]')
ENV_RE = re.compile(r'os\.environ\[[^\]]+\]\s*=')
BARE_ASSIGN_RE = re.compile(r'^\s*(\w+)\.([A-Z][A-Z0-9_]{2,})\s*=[^=]', re.M)
TMP_DEF_RE = re.compile(r'^\s*(\w+)\s*=\s*tmp_path\b|^\s*(\w+)\s*=\s*str\(tmp_path|'
                        r'def \w+\([^)]*\btmp\w*', re.M)

SEVERITY = {'net': 'high', 'sim-results': 'high', 'bare-assign': 'medium',
            'data-path': 'medium', 'abs-write': 'medium', 'env-write': 'low'}
ORDER = {'high': 0, 'medium': 1, 'low': 2}


def _tmp_context(text: str, pos: int, radius: int = 600) -> bool:
    """跨行上下文：命中点前后 radius 范围内是否出现 tmp_path 隔离迹象。"""
    window = text[max(0, pos - radius):pos + radius]
    return 'tmp_path' in window or 'monkeypatch' in window


def audit_text(text: str, filename: str = '<text>') -> list:
    findings = []
    lines = text.splitlines()

    def add(cat, line_no, snippet):
        findings.append({'file': filename, 'line': line_no,
                         'severity': SEVERITY[cat], 'category': cat,
                         'snippet': snippet.strip()[:120]})

    for category, pattern in (('net', NET_RE), ('sim-results', SIM_RESULTS_RE),
                              ('data-path', DATA_PATH_RE), ('env-write', ENV_RE)):
        for m in pattern.finditer(text):
            line_no = text.count('\n', 0, m.start()) + 1
            add(category, line_no, lines[line_no - 1])

    # ① 跨行上下文增强的写文件检查
    tmp_vars = {m.group(1) or m.group(2) for m in TMP_DEF_RE.finditer(text)}
    for m in OPEN_WRITE_RE.finditer(text):
        line_no = text.count('\n', 0, m.start()) + 1
        line = lines[line_no - 1]
        window_start = max(0, text.rfind('\n', 0, m.start() - 400))
        window = text[window_start:m.start()]
        arg = m.group(1)
        first_ref = re.split(r'[,()]', arg)[0].strip()
        var_name = re.split(r"[\s/.\[]", first_ref)[0].strip()
        # 变量源自 tmp_path（赋值/参数链）→ 不报；同行已含 tmp_path 也不报
        if 'tmp_path' in line or re.search(rf'\b{re.escape(var_name)}\s*=\s*.*tmp', window) \
                or var_name in tmp_vars:
            continue
        add('abs-write', line_no, line.strip()[:120])

    # ② 裸赋值规则：模块属性直接赋值（绕过 monkeypatch 的泄漏形态）
    for m in BARE_ASSIGN_RE.finditer(text):
        line_no = text.count('\n', 0, m.start()) + 1
        line = lines[line_no - 1]
        if 'monkeypatch' in line or 'setattr' in line:
            continue
        if 'self.' in line or line.strip().startswith('#'):
            continue
        add('bare-assign', line_no, line.strip()[:120])

    return findings


def audit_file(path: Path) -> list:
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []
    return audit_text(text, str(path))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='quant 测试隔离审计 v2（只读扫描）')
    parser.add_argument('--root', default='tests')
    parser.add_argument('--severity', default='low', choices=['high', 'medium', 'low'])
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f'[audit] 目录不存在：{root}')
        return 0

    findings = []
    files = sorted(p for p in root.rglob('*.py')
                   if not any(part in {'__pycache__'} for part in p.parts))
    for path in files:
        findings.extend(audit_file(path))
    findings = [f for f in findings if ORDER[f['severity']] <= ORDER[args.severity]]
    findings.sort(key=lambda f: (ORDER[f['severity']], f['file'], f['line']))

    print(f'scanned_files={len(files)} findings={len(findings)}')
    current = None
    for f in findings:
        if f['file'] != current:
            current = f['file']
            print(f'\n{current}')
        print(f"  L{f['line']} [{f['severity']}/{f['category']}] {f['snippet']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
