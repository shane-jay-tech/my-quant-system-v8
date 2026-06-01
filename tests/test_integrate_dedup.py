"""Tests for integrate_knowledge content-based dedup + value-gating (2026-06-17).

Root problem fixed: the KB was bloated by dozens of near-identical daily reports
because dedup was by SOURCE PATH only (each daily_insight_YYYYMMDD.md is a new
path). Now we also dedup by CONTENT fingerprint and drop empty (no-bullet) entries.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import integrate_knowledge as ik


def test_fingerprint_ignores_date_source_and_markers():
    e1 = ("### 报告 A\n> 来源：`reports/daily_insight_20260601.md` | 整合日期：20260601\n"
          "**可落地建议**：\n- [待验证] 建议3：RSI 阈值动态调整\n- 建议4：连涨/连跌过滤\n")
    e2 = ("### 报告 B\n> 来源：`reports/daily_insight_20260602.md` | 整合日期：20260602\n"
          "**可落地建议**：\n- 建议4：连涨/连跌过滤\n- 建议3：RSI 阈值动态调整\n")  # same bullets, diff order/date/source
    assert ik._content_fingerprint(e1) == ik._content_fingerprint(e2)


def test_fingerprint_none_when_no_bullets():
    assert ik._content_fingerprint("### 空条目\n> 来源：`x.md`\n") is None


def test_different_content_different_fingerprint():
    a = "### A\n- 建议1：换 ETF 月轮动\n"
    b = "### B\n- 建议2：加入可转债\n"
    assert ik._content_fingerprint(a) != ik._content_fingerprint(b)


def test_update_claude_md_skips_content_duplicates(tmp_path, monkeypatch):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(
        "# 量化交易系统\n\n# 量化策略知识库\n\n"
        "### 已有报告\n> 来源：`reports/daily_insight_20260601.md` | 整合日期：20260601\n"
        "**可落地建议**：\n- 建议3：RSI 阈值动态调整\n- 建议4：连涨/连跌过滤\n",
        encoding="utf-8")
    monkeypatch.setattr(ik, "CLAUDE_MD", str(claude))

    # New entry: different source path, IDENTICAL substantive content -> must be skipped
    dup = ("### 新报告\n> 来源：`reports/daily_insight_20260602.md` | 整合日期：20260602\n"
           "**可落地建议**：\n- 建议4：连涨/连跌过滤\n- 建议3：RSI 阈值动态调整\n")
    ik.update_claude_md([dup])
    after = claude.read_text(encoding="utf-8")
    assert after.count("daily_insight_20260602") == 0  # content-dup not added


def test_update_claude_md_adds_genuinely_new(tmp_path, monkeypatch):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# 量化交易系统\n\n# 量化策略知识库\n\n"
                      "### 旧\n> 来源：`reports/a.md`\n- 建议3：RSI 动态\n", encoding="utf-8")
    monkeypatch.setattr(ik, "CLAUDE_MD", str(claude))
    new = "### 全新\n> 来源：`reports/new.md` | 整合日期：20260617\n- 建议9：引入波动率因子\n"
    ik.update_claude_md([new])
    assert "建议9：引入波动率因子" in claude.read_text(encoding="utf-8")


def test_update_claude_md_skips_empty_entries(tmp_path, monkeypatch):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# 量化交易系统\n\n# 量化策略知识库\n\n", encoding="utf-8")
    monkeypatch.setattr(ik, "CLAUDE_MD", str(claude))
    empty = "### 无内容\n> 来源：`reports/empty.md` | 整合日期：20260617\n"  # no bullets
    ik.update_claude_md([empty])
    assert "reports/empty.md" not in claude.read_text(encoding="utf-8")


def test_dedupe_existing_kb_collapses_duplicates(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    # KB with 3 entries: two identical-content daily reports + one unique; plus a tail section.
    claude.write_text(
        "# 项目规范\n\n正文若干。\n\n# 量化策略知识库\n\n"
        "### 报告A\n> 来源：`reports/daily_insight_20260601.md` | 整合日期：20260601\n"
        "**可落地建议**：\n- 建议3：RSI 动态\n- 建议4：连涨过滤\n\n---\n"
        "### 报告B\n> 来源：`reports/daily_insight_20260602.md` | 整合日期：20260602\n"
        "**可落地建议**：\n- 建议4：连涨过滤\n- 建议3：RSI 动态\n\n---\n"
        "### 独特\n> 来源：`reports/special.md`\n- 建议9：波动率因子\n\n"
        "# 成本优先原则\n\n这段必须原样保留。\n",
        encoding="utf-8")
    stats = ik.dedupe_existing_kb(claude_path=str(claude), dry_run=False, backup=True)
    assert stats["total"] == 3 and stats["kept"] == 2 and stats["removed_dup"] == 1
    after = claude.read_text(encoding="utf-8")
    # unique entry kept, tail preserved verbatim, one dup removed
    assert "建议9：波动率因子" in after
    assert "# 成本优先原则" in after and "这段必须原样保留" in after
    assert after.count("daily_insight_2026060") == 1  # only first daily kept
    assert (tmp_path / "CLAUDE.md.bak").exists()  # backup written


def test_dedupe_dry_run_does_not_write(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    original = ("# 项目规范\n\n# 量化策略知识库\n\n### A\n> 来源：`a.md`\n- 建议3：x\n\n---\n"
                "### B\n> 来源：`b.md`\n- 建议3：x\n\n# 尾部\n")
    claude.write_text(original, encoding="utf-8")
    stats = ik.dedupe_existing_kb(claude_path=str(claude), dry_run=True)
    assert stats["removed_dup"] == 1
    assert claude.read_text(encoding="utf-8") == original  # unchanged on dry-run
