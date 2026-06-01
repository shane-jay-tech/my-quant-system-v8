"""一次性脚本：清理 CLAUDE.md 中"# 量化策略知识库"章节的重复条目。

去重规则：按"> 来源：xxx"行分组，同一个来源只保留**最后一次**出现的版本（即最新的整合日期）。
范围：仅触动 "# 量化策略知识库" 到下一个 "# " 章节之间。其它章节原文保留。
"""
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(BASE_DIR, 'CLAUDE.md')


def split_kb_section(content):
    header = "# 量化策略知识库"
    idx = content.find(header)
    if idx == -1:
        return content, None, None, ''
    after = idx + len(header)
    next_match = re.search(r'\n# [^#]', content[after:])
    end = after + next_match.start() if next_match else len(content)
    return content[:idx], header + content[after:end], content[end:], header


def parse_entries(kb_block):
    # 拆 entries（按 ### 标题或 --- 分隔）
    parts = re.split(r'\n(?=### )', kb_block)
    head = parts[0]
    entries = parts[1:]
    return head, entries


def entry_source(entry):
    m = re.search(r'>\s*来源：`?([^`|\n]+?)`?\s*(?:\||\n)', entry)
    return m.group(1).strip() if m else None


def main():
    with open(CLAUDE_MD, 'r', encoding='utf-8') as f:
        content = f.read()

    before, kb, after, _ = split_kb_section(content)
    if kb is None:
        print('[INFO] no "# 量化策略知识库" section, nothing to do')
        return 0

    head, entries = parse_entries(kb)
    seen = {}
    order = []
    for e in entries:
        # 清掉前后的 --- 分隔行 / 多余空行
        clean = re.sub(r'^\s*-{3,}\s*\n', '', e)
        clean = re.sub(r'\n\s*-{3,}\s*$', '', clean)
        src = entry_source(clean)
        key = src or f'__no_source_{len(order)}'
        if key not in seen:
            order.append(key)
        seen[key] = clean.rstrip() + '\n'

    deduped_entries = [seen[k] for k in order]
    new_kb = head.rstrip() + '\n\n' + '\n---\n'.join(deduped_entries) + '\n'
    new_content = before + new_kb + after

    if new_content == content:
        print('[INFO] no duplicates found')
        return 0

    with open(CLAUDE_MD, 'w', encoding='utf-8') as f:
        f.write(new_content)
    removed = len(entries) - len(deduped_entries)
    print(f'[OK] removed {removed} duplicate entries; kept {len(deduped_entries)} unique entries')
    return 0


if __name__ == '__main__':
    sys.exit(main())
