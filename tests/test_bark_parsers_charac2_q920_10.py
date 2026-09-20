# -*- coding: utf-8 -*-
"""q920-10：bark_sender.parsers 残留 miss 收尾 characterization。

基线更新（2026-09-20 实测，非 q918 时的 6 miss）：
  python -m pytest tests/ -q --cov=bark_sender.parsers --cov-report=term-missing
  bark_sender/parsers.py  155 stmts  5 miss  97%   11-13, 114-115
本文件把这两段（find_latest_report 全函数 + parse_performance_tracking 的 overall 提取）钉住。
**零生产码改动**，只补测试。

与既有测试不重叠：test_bark_parsers_h912_04（正常形态）/ test_bark_parsers_charac（畸形输入容错）
都没碰这两个函数。
"""
from __future__ import annotations

import bark_sender.parsers as parsers


# ---------------------------------------------------------------- 11-13
def test_find_latest_report_取字典序最大的pick文件(monkeypatch, tmp_path):
    """parsers.py:10-13 —— 无文件返回 None；有文件取 sorted(reverse=True)[0]（文件名即日期 ⇒ 最新在前）。"""
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path))
    assert parsers.find_latest_report() is None          # :13 files 为空的分支

    (tmp_path / "pick_20260918.md").write_text("a", encoding="utf-8")
    (tmp_path / "pick_20260919.md").write_text("b", encoding="utf-8")
    (tmp_path / "not_a_pick.md").write_text("c", encoding="utf-8")   # 不匹配 pick_*.md，必须被忽略
    got = parsers.find_latest_report()
    assert got is not None and got.endswith("pick_20260919.md"), got
    assert got == str(tmp_path / "pick_20260919.md")     # 返回的是完整路径


def test_find_latest_report_目录不存在也不炸(monkeypatch, tmp_path):
    """反向：RESULTS_DIR 指向不存在目录 ⇒ glob 空、返回 None（不得抛异常）。"""
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path / "nowhere"))
    assert parsers.find_latest_report() is None


# ---------------------------------------------------------------- 114-115
def test_performance_tracking_提取overall胜率与收益(monkeypatch, tmp_path):
    """parsers.py:112-117 —— overall 正则命中时补 win_rate/avg_ret（此前从未被覆盖）。"""
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path))
    (tmp_path / "performance_tracking.md").write_text(
        "# 绩效追踪\n\n"
        "| 日期 | 数量 | 平均收益 | 胜率 |\n"
        "| 2026-09-18 | 3 | +1.50 | 66.7 |\n\n"
        "Overall: 55.5% win rate, +1.23% avg return\n",
        encoding="utf-8",
    )
    out = parsers.parse_performance_tracking()
    assert out is not None
    assert out["previous"] == {"date": "2026-09-18", "count": 3, "avg_ret": 1.5, "win_rate": 66.7}
    assert out["overall"] == {"win_rate": 55.5, "avg_ret": 1.23}      # :114-115


def test_performance_tracking_无overall行时字典为空(monkeypatch, tmp_path):
    """反向：没有 Overall 行 ⇒ overall 保持 {}（证明 114-115 是条件分支而非恒执行）。"""
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path))
    (tmp_path / "performance_tracking.md").write_text(
        "| 2026-09-18 | 3 | +1.50 | 66.7 |\n", encoding="utf-8")
    out = parsers.parse_performance_tracking()
    assert out["previous"]["count"] == 3
    assert out["overall"] == {}


def test_performance_tracking_文件缺失返回None(monkeypatch, tmp_path):
    """parsers.py:96-97 —— 文件不存在返回 None（调用方据此跳过回顾段）。"""
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(tmp_path / "nowhere"))
    assert parsers.parse_performance_tracking() is None
