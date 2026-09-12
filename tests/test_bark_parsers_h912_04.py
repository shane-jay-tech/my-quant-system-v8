"""h912-04 批A：bark_sender.parsers characterization（冻结现行为，零生产码改动）。

覆盖缺口（基线 12%）：报告表格双格式自动侦测、缺文件→None/[]、畸形评分→50 兜底。
只做行为/结构断言，不写资金数值断言。
"""
from __future__ import annotations

import bark_sender.parsers as parsers


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_parse_report_full_sector_column_autodetect(tmp_path, monkeypatch):
    row = "| 1 | 600000 | 浦发银行 | 银行 | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 80 | 低 | 流动性好"
    f = tmp_path / "pick_20260912.md"
    _write(f, "# 选股报告 2026-09-12\n| 序 | 代码 | 名称 | 板块 | 现价 | 涨幅 |\n" + row)
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    pick_date, stocks = parsers.parse_report_full(str(f))
    assert pick_date == "2026-09-12"
    assert len(stocks) == 1
    s = stocks[0]
    assert s["code"] == "600000" and s["name"] == "浦发银行"
    assert s["price"] == "10.00" and s["score"] == "80" and s["risk"] == "低"
    assert s["reason"] == "流动性好"


def test_parse_report_full_no_sector_and_unknown_date(tmp_path):
    row = "| 1 | 000001 | 平安银行 | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 80 | 低"
    f = tmp_path / "pick_x.md"
    _write(f, "无日期开头\n" + row)
    pick_date, stocks = parsers.parse_report_full(str(f))
    assert pick_date == "未知"
    assert len(stocks) == 1
    assert stocks[0]["code"] == "000001" and stocks[0]["score"] == "80"


def test_parse_honest_eval_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    assert parsers.parse_honest_eval() is None


def test_parse_honest_eval_extracts_sections(tmp_path, monkeypatch):
    content = (
        "| 牛市 | 202 | 54.5% | +4.99% |\n"
        "| 熊市/震荡 | 188 | 51.2% | -1.20% |\n"
        "超额收益: +3.10%\n"
        "最大连续亏损: 4\n"
        "| 10日 | 202 | 54.5% | +4.99% | +4.79% | 10.9% |\n"
    )
    _write(tmp_path / "honest_evaluation.md", content)
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    data = parsers.parse_honest_eval()
    assert data["bull_trades"] == 202 and data["bull_wr"] == 54.5 and data["bull_net"] == 4.99
    assert data["bear_trades"] == 188 and data["bear_net"] == -1.20
    assert data["excess"] == 3.10
    assert data["max_consecutive_loss"] == 4
    assert data["wr10"] == 54.5 and data["net10"] == 4.79


def test_parse_performance_tracking_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    assert parsers.parse_performance_tracking() is None


def test_parse_exit_advisor_sells_missing_today_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    assert parsers._parse_exit_advisor_sells() == []


def test_get_pick_scores_empty_dir_and_malformed_score(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    assert parsers._get_pick_scores() == {}
    _write(
        tmp_path / "pick_20260912.md",
        "| 1 | 600000 | 浦发银行 | 银行 | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | N/A |\n"
        "| 2 | 000001 | 平安银行 | 银行 | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 66 |\n",
    )
    scores = parsers._get_pick_scores()
    assert scores["600000"] == 50
    assert scores["000001"] == 66
