"""
知识内化引擎 v1 — 将研究报告自动整合进 CLAUDE.md 知识库

功能：
1. 扫描 reports/ 中未标记 [Integrated] 的报告
2. 提取"可落地建议"章节（### 建议N：...）
3. 追加到 CLAUDE.md 的 # 量化策略知识库 章节
4. 在报告头部插入 [Integrated YYYYMMDD] 标记
5. 在 memory.md 追加学习记录
"""
import os, sys, glob, re, hashlib
from datetime import datetime

# Reuse the shared content hash (team-collab scripts/common). Best-effort: if
# the hub isn't reachable, fall back to a local sha256 so this stays standalone.
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.common.snapshot import hash_data as _hash_data  # type: ignore
except Exception:  # pragma: no cover
    def _hash_data(data, length=12):
        return hashlib.sha256(str(data).encode("utf-8")).hexdigest()[:length]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
BOOKS_DIR = os.path.join(BASE_DIR, 'books')
CLAUDE_MD = os.path.join(BASE_DIR, 'CLAUDE.md')
MEMORY_MD = os.path.join(BASE_DIR, 'memory.md')


def find_unintegrated_reports():
    """找出头部未标记 [Integrated] 的报告"""
    if not os.path.exists(REPORTS_DIR):
        print("[KNOWLEDGE] No reports/ directory yet")
        return []

    unintegrated = []
    for f in sorted(glob.glob(os.path.join(REPORTS_DIR, '*.md'))):
        with open(f, 'r', encoding='utf-8') as fh:
            first_lines = ''.join([fh.readline() for _ in range(15)])
        if '[Integrated' not in first_lines:
            unintegrated.append(f)
        else:
            print(f"[KNOWLEDGE] Skipping (already integrated): {os.path.basename(f)}")
    return unintegrated


def extract_suggestions(report_path):
    """从报告中提取「可落地的因子/参数建议」内容"""
    with open(report_path, 'r', encoding='utf-8') as fh:
        content = fh.read()

    suggestions = []

    # 提取 ## 二、可落地... 到 ## 三、 之间的内容
    pattern = r'## 二、可落地的因子/参数建议\s*\n(.*?)(?=## 三、)'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        section = match.group(1).strip()
        # 提取每个 ### 建议N：... 的标题
        titles = re.findall(r'### (建议\d+：.+?)\n', section)
        suggestions.append(('section', section, titles))

    # 也尝试提取 ## 一、核心发现
    findings = []
    pattern_f = r'## 一、核心发现\s*\n(.*?)(?=## 二、)'
    match_f = re.search(pattern_f, content, re.DOTALL)
    if match_f:
        f_section = match_f.group(1).strip()
        bullets = re.findall(r'\d+\.\s*\*\*(.+?)\*\*', f_section)
        findings = bullets

    return suggestions, findings


def extract_external_suggestions(report_path):
    """从外部研究报告（external_research_*）中提取因子建议"""
    with open(report_path, 'r', encoding='utf-8') as fh:
        content = fh.read()

    suggestions = []
    # 匹配 "可落地因子建议" 行
    for m in re.finditer(r'\*\*可落地因子建议\*\*[：:]\s*(.+?)(?:\n|$)', content):
        suggestions.append(m.group(1).strip())
    # 匹配 "一句话总结"
    summaries = []
    for m in re.finditer(r'\*\*一句话总结\*\*[：:]\s*(.+?)(?:\n|$)', content):
        summaries.append(m.group(1).strip())

    return suggestions, summaries


def extract_topic_from_report(report_path):
    """从研究报告的文件名/标题提取研究主题"""
    with open(report_path, 'r', encoding='utf-8') as fh:
        first_line = fh.readline().strip()
    # 提取 # 后的标题
    m = re.search(r'^#\s*(.+?)(?:\n|$)', first_line)
    if m:
        return m.group(1).strip()
    return os.path.basename(report_path).replace('.md', '')


def build_external_knowledge_entry(report_path, ext_suggestions, ext_summaries):
    """构建外部研究知识条目 [来源: arXiv]"""
    report_name = os.path.basename(report_path)
    date_str = datetime.now().strftime('%Y%m%d')

    lines = []
    lines.append(f"### 外部研究：arXiv 量化金融论文 [来源: arXiv]")
    lines.append(f"> 来源：`reports/{report_name}` | 整合日期：{date_str}")

    if ext_summaries:
        lines.append("")
        lines.append("**论文发现**：")
        for s in ext_summaries[:3]:
            lines.append(f"- {s}")

    if ext_suggestions:
        lines.append("")
        lines.append("**可落地因子建议**：")
        for s in ext_suggestions[:5]:
            lines.append(f"- [待验证] {s}")

    lines.append("")
    return '\n'.join(lines), f"arXiv论文：{', '.join(ext_summaries[:1])}"


def build_knowledge_entry(report_path, suggestions, findings):
    """构建要追加到 CLAUDE.md 的知识条目"""
    report_name = os.path.basename(report_path)
    topic = extract_topic_from_report(report_path)
    date_str = datetime.now().strftime('%Y%m%d')

    lines = []
    lines.append(f"### {topic}")
    lines.append(f"> 来源：`reports/{report_name}` | 整合日期：{date_str}")

    if findings:
        lines.append("")
        lines.append("**核心发现**：")
        for f in findings[:3]:
            lines.append(f"- {f}")

    if suggestions:
        for sec, content, titles in suggestions:
            lines.append("")
            lines.append("**可落地建议**：")
            for t in titles:
                lines.append(f"- {t}")

    lines.append("")
    return '\n'.join(lines), topic


def _extract_existing_sources(content):
    """从 CLAUDE.md 中提取已存在的"> 来源：path"行（仅 path 部分），用于幂等检查。"""
    sources = set()
    for m in re.finditer(r'>\s*来源：`?([^`|\n]+?)`?\s*(?:\||\n)', content):
        sources.add(m.group(1).strip())
    return sources


def _content_fingerprint(entry):
    """对一条知识条目的"实质内容"取指纹：只看 `- ` 开头的要点（核心发现/可落地建议），
    剥掉日期/来源/[待验证] 等噪声，排序后哈希。无任何要点则返回 None（视为无信息）。

    这是治理"知识库被几十条雷同每日报告刷屏"的关键：旧逻辑只按来源路径去重，
    而每天的 daily_insight_YYYYMMDD.md 路径不同、内容却一样，于是天天追加。
    改按内容指纹去重 + 空内容价值门控（借 team-collab finding-schema 的去重思路）。
    """
    bullets = []
    for line in entry.splitlines():
        s = line.strip()
        if s.startswith("- "):
            b = s[2:].replace("[待验证]", "").replace("[[待验证]", "").strip()
            if b:
                bullets.append(b)
    if not bullets:
        return None
    return _hash_data("\n".join(sorted(bullets)))


def _existing_content_fingerprints(content):
    """把 CLAUDE.md 拆成 ### 块，给每块算内容指纹，得到已存在内容的指纹集合。"""
    fps = set()
    for block in re.split(r'\n(?=### )', content):
        fp = _content_fingerprint(block)
        if fp:
            fps.add(fp)
    return fps


def update_claude_md(knowledge_entries):
    """在 CLAUDE.md 中新建或追加 # 量化策略知识库 章节（幂等：按"来源"去重）。"""
    if not os.path.exists(CLAUDE_MD):
        print("[KNOWLEDGE] CLAUDE.md not found, creating...")
        with open(CLAUDE_MD, 'w', encoding='utf-8') as fh:
            fh.write("# 量化交易系统 - 项目规范\n\n")

    with open(CLAUDE_MD, 'r', encoding='utf-8') as fh:
        content = fh.read()

    existing_sources = _extract_existing_sources(content)
    seen_fps = _existing_content_fingerprints(content)
    fresh_entries = []
    skipped_src = skipped_content = skipped_empty = 0
    for entry in knowledge_entries:
        m = re.search(r'>\s*来源：`?([^`|\n]+?)`?\s*(?:\||\n)', entry)
        src = m.group(1).strip() if m else None
        if src and src in existing_sources:
            skipped_src += 1
            continue
        fp = _content_fingerprint(entry)
        if fp is None:                       # 价值门控：无任何实质要点，不收录
            skipped_empty += 1
            continue
        if fp in seen_fps:                   # 内容去重：实质内容与已有条目重复
            skipped_content += 1
            continue
        fresh_entries.append(entry)
        seen_fps.add(fp)
        if src:
            existing_sources.add(src)

    if not fresh_entries:
        print(f"[KNOWLEDGE] No new entries (skipped {skipped_src} by-source, "
              f"{skipped_content} by-content, {skipped_empty} empty)")
        return

    kb_header = "# 量化策略知识库"
    if kb_header in content:
        idx = content.find(kb_header)
        next_section = re.search(r'\n# [^#]', content[idx + len(kb_header):])
        if next_section:
            insert_pos = idx + len(kb_header) + next_section.start()
            new_content = content[:insert_pos] + '\n' + '\n---\n'.join(fresh_entries) + '\n' + content[insert_pos:]
        else:
            new_content = content.rstrip() + '\n\n' + '\n---\n'.join(fresh_entries) + '\n'
    else:
        new_content = content.rstrip() + '\n\n' + kb_header + '\n\n' + '\n---\n'.join(fresh_entries) + '\n'

    with open(CLAUDE_MD, 'w', encoding='utf-8') as fh:
        fh.write(new_content)
    print(f"[KNOWLEDGE] Updated CLAUDE.md: +{len(fresh_entries)} entries "
          f"(skipped {skipped_src} by-source, {skipped_content} by-content, {skipped_empty} empty)")


def dedupe_existing_kb(claude_path=None, dry_run=True, backup=True):
    """一次性清理「# 量化策略知识库」里**内容重复**的历史条目（保留每种内容的首次出现，
    删除后续雷同条目；同时丢弃无实质要点的空条目）。

    只动知识库段落，段落以外的内容逐字保留。dry_run=True 时只报告不写盘。
    返回 dict：{total, kept, removed_dup, removed_empty, removed_sources}。
    """
    path = claude_path or CLAUDE_MD
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()

    kb_header = "# 量化策略知识库"
    if kb_header not in content:
        return {"total": 0, "kept": 0, "removed_dup": 0, "removed_empty": 0, "removed_sources": []}

    start = content.find(kb_header)
    # 知识库段落到下一个顶级标题（# 开头，非 ##/###）为止
    after = content[start + len(kb_header):]
    m_next = re.search(r'\n# [^#]', after)
    kb_body = after[:m_next.start()] if m_next else after
    tail = after[m_next.start():] if m_next else ""
    head = content[:start + len(kb_header)]

    # 拆成 ### 块（块前的 --- 分隔线/空行剥掉）
    blocks = re.split(r'\n(?=### )', kb_body)
    lead = blocks[0] if blocks and not blocks[0].lstrip().startswith("### ") else ""
    entry_blocks = blocks[1:] if lead else blocks

    seen = set()
    kept, removed_dup, removed_empty, removed_sources = [], 0, 0, []
    for blk in entry_blocks:
        body = re.sub(r'^\s*(-{3,}\s*)+', '', blk)        # strip leading --- separators
        body = re.sub(r'(\n\s*-{3,}\s*)+$', '', body.rstrip())  # and trailing ones
        if not body.strip():
            continue
        fp = _content_fingerprint(body)
        src_m = re.search(r'>\s*来源：`?([^`|\n]+?)`?\s*(?:\||\n)', body)
        src = src_m.group(1).strip() if src_m else "?"
        if fp is None:
            removed_empty += 1
            removed_sources.append(src)
            continue
        if fp in seen:
            removed_dup += 1
            removed_sources.append(src)
            continue
        seen.add(fp)
        kept.append(body.rstrip())

    stats = {
        "total": len(entry_blocks), "kept": len(kept),
        "removed_dup": removed_dup, "removed_empty": removed_empty,
        "removed_sources": removed_sources,
    }
    if dry_run:
        print(f"[DEDUPE dry-run] 知识库条目 {stats['total']} → 保留 {stats['kept']}，"
              f"删重复 {removed_dup}、删空 {removed_empty}")
        return stats

    if backup:
        bak = path + ".bak"
        with open(bak, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"[DEDUPE] 备份原文件 → {bak}")

    new_kb = (lead.rstrip() + "\n\n" if lead.strip() else "\n\n") + "\n\n---\n\n".join(kept) + "\n"
    new_content = head + new_kb + tail
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_content)
    print(f"[DEDUPE] 已清理：保留 {stats['kept']}，删除 {removed_dup + removed_empty} 条")
    return stats


def mark_report_integrated(report_path):
    """在报告头部插入 [Integrated YYYYMMDD]"""
    with open(report_path, 'r', encoding='utf-8') as fh:
        content = fh.read()

    today = datetime.now().strftime('%Y%m%d')
    marker = f"[Integrated {today}]"

    if marker in content:
        return

    # 在 # 标题后插入标记
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('# ') and i == 0:
            lines.insert(i + 1, f'\n> {marker}')
            break
    else:
        lines.insert(0, f'> {marker}\n')

    with open(report_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    print(f"[KNOWLEDGE] Marked report: {os.path.basename(report_path)} {marker}")


def update_memory(entries_info):
    """在 memory.md 追加学习记录"""
    today = datetime.now().strftime('%Y%m%d')

    if not os.path.exists(MEMORY_MD):
        with open(MEMORY_MD, 'w', encoding='utf-8') as fh:
            fh.write("# 项目记忆\n\n")

    with open(MEMORY_MD, 'r', encoding='utf-8') as fh:
        content = fh.read()

    lines = []
    for report_name, topic in entries_info:
        summary = topic[:60] + ('...' if len(topic) > 60 else '')
        lines.append(f"[学习] {today} | {report_name} | {summary} | 待验证")

    entry = '\n'.join(lines)
    if entry not in content:
        with open(MEMORY_MD, 'a', encoding='utf-8') as fh:
            fh.write('\n' + entry + '\n')

    print(f"[KNOWLEDGE] Appended {len(entries_info)} learning records to memory.md")


def integrate_books():
    """将 books/ 中的反爬知识也整合进知识库"""
    books_kb = []
    if not os.path.exists(BOOKS_DIR):
        return books_kb

    # 幂等：CLAUDE.md 已经收录的 books/ 来源直接跳过
    existing_sources = set()
    if os.path.exists(CLAUDE_MD):
        with open(CLAUDE_MD, 'r', encoding='utf-8') as fh:
            existing_sources = _extract_existing_sources(fh.read())

    for f in glob.glob(os.path.join(BOOKS_DIR, '*.md')):
        src_path = f"books/{os.path.basename(f)}"
        if src_path in existing_sources:
            continue
        with open(f, 'r', encoding='utf-8') as fh:
            content = fh.read()

        chapters = re.findall(r'## ([一二三四五六七八九十]+、.+?)\n', content)
        if chapters:
            name = os.path.basename(f).replace('.md', '')
            books_kb.append(f"### 反反爬知识库：{name}")
            books_kb.append(f"> 来源：`{src_path}` | 章数：{len(chapters)}")
            books_kb.append("")
            books_kb.append("**核心章节**：")
            for ch in chapters[:5]:
                books_kb.append(f"- {ch}")
            books_kb.append("")
            books_kb.append("**使用方法**：写爬虫时启用「反反爬虫 Skill」，所有反爬模式自动应用。")
            books_kb.append("")

    return books_kb


def main():
    print("=" * 60)
    print("  知识内化引擎 v1")
    print("=" * 60)

    # Step 1: 扫描未整合报告
    print("\n[1/4] Scanning unintegrated reports...")
    reports = find_unintegrated_reports()
    print(f"  Found {len(reports)} unintegrated report(s)")

    # Step 2: 提取知识
    print("\n[2/4] Extracting knowledge...")
    knowledge_blocks = []
    entries_info = []

    for rp in reports:
        fname = os.path.basename(rp)
        if fname.startswith('external_research_'):
            # 外部研究报告使用专用提取器
            ext_suggestions, ext_summaries = extract_external_suggestions(rp)
            if ext_suggestions or ext_summaries:
                entry, topic = build_external_knowledge_entry(rp, ext_suggestions, ext_summaries)
                knowledge_blocks.append(entry)
                entries_info.append((fname, topic))
                print(f"  Extracted (arXiv): {fname}")
        else:
            suggestions, findings = extract_suggestions(rp)
            if suggestions or findings:
                entry, topic = build_knowledge_entry(rp, suggestions, findings)
                knowledge_blocks.append(entry)
                entries_info.append((fname, topic))
                print(f"  Extracted from: {fname}")

    # Step 3: 整合 books/ 知识
    print("\n[3/4] Integrating books/ knowledge...")
    book_kb = integrate_books()
    if book_kb:
        knowledge_blocks.insert(0, '\n'.join(book_kb))
        entries_info.insert(0, ('反反爬实战笔记.md', '反反爬虫知识体系'))
        print(f"  Integrated books/ knowledge base")

    # Step 4: 更新 CLAUDE.md
    if knowledge_blocks:
        update_claude_md(knowledge_blocks)

    # Step 5: 标记已整合报告
    print("\n[4/4] Marking reports & updating memory...")
    for rp in reports:
        mark_report_integrated(rp)

    # Step 6: 更新 memory
    if entries_info:
        update_memory(entries_info)

    print(f"\n[OK] Knowledge integration complete.")
    print(f"  Reports processed: {len(reports)}")
    print(f"  Knowledge entries: {len(knowledge_blocks)}")
    print(f"  CLAUDE.md updated: {CLAUDE_MD}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
