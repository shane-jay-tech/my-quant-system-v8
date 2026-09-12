"""h912-10 批B1：bark_sender.parsers 畸形输入容错 characterization。

对应基线 §四 第 2 行补测点：截断/编码异常/字段缺失/类型错分支。
与 tests/test_bark_parsers_h912_04.py 案例面不重叠（那份只测正常形态）。
"""

from __future__ import annotations

from datetime import datetime

import pytest

import bark_sender.parsers as parsers


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data) if isinstance(data, bytes) else path.write_text(data, encoding="utf-8")


def test_parse_report_full_truncated_empty_file_returns_unknown_and_no_stocks(tmp_path):
    """截断/空文件 → 日期「未知」、股票列表空，不抛异常。"""
    f = tmp_path / "pick_x.md"
    _write(f, "")
    pick_date, stocks = parsers.parse_report_full(str(f))
    assert pick_date == "未知"
    assert stocks == []


def test_parse_report_full_invalid_utf8_raises_unicodeerror(tmp_path):
    """编码异常（GBK 字节当 utf-8 读）→ UnicodeDecodeError 向上传播（冻结现行为）。"""
    f = tmp_path / "pick_bad.md"
    _write(f, b"# \xc4\xe3\xba\xc3 2026-09-12\n")
    with pytest.raises(UnicodeDecodeError):
        parsers.parse_report_full(str(f))


def test_parse_report_full_short_row_raises_indexerror(tmp_path):
    """【真缺陷冻结】列数不足的短行 → float(parts[3]) 抛 IndexError（try 只捕 ValueError），
    整个解析崩溃——容错缺口已记报告遗留，待日间修（本单不改生产码）。"""
    good = "| 1 | 600000 | 浦发银行 | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 80 |"
    broken = "| 2 | 000001 | 平安银行 |"  # 列数不足
    f = tmp_path / "pick_x.md"
    _write(f, f"2026-09-12 报告\n{good}\n{broken}\n")
    with pytest.raises(IndexError):
        parsers.parse_report_full(str(f))


def test_parse_daily_orders_buys_missing_orders_dir_raises(tmp_path, monkeypatch):
    """ORDERS_DIR 不存在 → os.listdir 抛 FileNotFoundError（冻结现行为，未做容错）。"""
    monkeypatch.setattr(parsers, "ORDERS_DIR", str(tmp_path / "nope"), raising=False)
    with pytest.raises(FileNotFoundError):
        parsers._parse_daily_orders_buys()


def test_parse_daily_orders_buys_empty_dir_returns_empty(tmp_path, monkeypatch):
    (tmp_path / "o").mkdir()
    monkeypatch.setattr(parsers, "ORDERS_DIR", str(tmp_path / "o"), raising=False)
    assert parsers._parse_daily_orders_buys() == []


def test_parse_daily_orders_buys_parses_buy_rows_with_thousands_separator(tmp_path, monkeypatch):
    """买入行解析（千分位价格容错），非买入行跳过、节外行不收。"""
    d = tmp_path / "o"
    d.mkdir()
    (d / "daily_orders_20260912.md").write_text(
        "## 今日买入订单（建议持有10天）\n"
        "| 600000 | 浦发银行 | 买入 | 1,234.5 | 100 | 123,450.0 | 已提交 |\n"
        "| 000001 | 平安银行 | 卖出 | 10.00 | 100 | 1000.0 | 已提交 |\n"
        "## 其他节\n"
        "| 600036 | 招商银行 | 买入 | 30.00 | 100 | 3000.0 | 已提交 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(parsers, "ORDERS_DIR", str(d), raising=False)
    buys = parsers._parse_daily_orders_buys()
    assert [b["code"] for b in buys] == ["600000"]
    assert buys[0]["price"] == 1234.5 and buys[0]["shares"] == 100


def test_parse_exit_advisor_sells_reads_today_file_and_stops_at_next_section(tmp_path, monkeypatch):
    """今日 exit_advisor 文件：节内行解析、下一个 ## 节截断。"""
    today = datetime.now().strftime("%Y%m%d")
    d = tmp_path
    (d / f"exit_advisor_{today}.md").write_text(
        "## 🚨 需要操作\n"
        "| 600000 | 浦发银行 | 10.00 | 9.00 | -10.0% | 止损 | 止损卖出 | 跌破止损线 |\n"
        "## 📊 继续持有\n"
        "| 000001 | 平安银行 | 10.00 | 11.00 | +10.0% | 持有 | 持有 | - |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(d), raising=False)
    sells = parsers._parse_exit_advisor_sells()
    assert [s["code"] for s in sells] == ["600000"]
    assert sells[0]["action"] == "止损卖出" and sells[0]["entry_price"] == 10.0


def test_get_pick_scores_skips_short_rows(tmp_path, monkeypatch):
    """列数 <10 的行跳过（字段缺失容错）。"""
    (tmp_path / "pick_x.md").write_text(
        "| 1 | 600000 | 浦发银行 | 银行 | 短行 |\n"
        "| 2 | 000001 | 平安银行 | 银行 | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 77 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path), raising=False)
    scores = parsers._get_pick_scores()
    assert scores == {"000001": 77}
