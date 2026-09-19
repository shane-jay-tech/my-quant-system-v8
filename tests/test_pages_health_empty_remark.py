"""q918-14：app/pages.py 与 ops/health.py 备注列守卫验证（同族 A 类 #7/#15）。

两处 .str 前置 fillna('').astype(str) 守卫（q918-13 同族，样板 formatters.py:262）：
- pages 渲染路径：整列空备注 CSV → 不再走「读取交易记录失败」warning，
  caption 计数正确（真实交易 1 笔、示例数据行被过滤）。
- health 健康检查路径：沙箱 REPO_ROOT 整跑 run_all → 'Metric: real trades'
  计数项为 True 且 detail 计数正确（守卫前 AttributeError 会被 except 吞成误报健康）。
崩溃防御，零数值逻辑改动。
"""

from __future__ import annotations

from types import ModuleType
from unittest.mock import MagicMock

import pytest

import app.pages as pages
import ops.health as oh

CSV_ROWS = (
    "日期,代码,名称,方向,备注\n"
    "2026-01-01,510300,沪深300ETF,买入,示例数据\n"   # 应被过滤
    "2026-01-02,510300,沪深300ETF,卖出,\n"          # 保留（整列空备注→float64 崩溃面）
)


def test_pages_render_empty_remark_counts_kept_rows(tmp_path, monkeypatch):
    """pages 渲染：守卫前 AttributeError→warning 静默吞；守卫后 caption 计数=保留行数。"""
    (tmp_path / "real_trades.csv").write_text(CSV_ROWS, encoding="utf-8")
    monkeypatch.setattr(pages, "BASE_DIR", str(tmp_path))
    fake_st = MagicMock()
    # st.columns(3)/st.tabs(2) 解包需要真列表（MagicMock 默认 __iter__ 为空）
    fake_st.columns.side_effect = lambda spec=3, *a, **k: [
        MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(spec if isinstance(spec, int) else 3))
    ]
    fake_st.tabs.side_effect = lambda n=3, *a, **k: [MagicMock() for _ in range(n if isinstance(n, int) else 3)]
    fake_st.number_input.return_value = 0.0   # :1143 与 int 比较
    fake_st.text_input.return_value = ""
    fake_st.date_input.return_value = "2026-01-02"
    fake_st.selectbox.return_value = ""
    monkeypatch.setattr(pages, "st", fake_st)

    pages.render_my_trades_page()

    captions = [str(c.args) for c in fake_st.caption.call_args_list if c.args]
    assert any("共 1 笔真实交易记录" in c for c in captions), captions
    warns = [str(c.args) for c in fake_st.warning.call_args_list if c.args]
    assert not any("读取交易记录失败" in c for c in warns), warns


@pytest.fixture()
def health_sandbox(tmp_path, monkeypatch):
    """run_all 沙箱：REPO_ROOT 指向 tmp，报告/数据目录隔离，重型校验器 stub。"""
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "real_trades.csv").write_text(CSV_ROWS, encoding="utf-8")

    monkeypatch.setattr(oh, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(oh, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(oh, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(oh, "RESULTS_DIR", tmp_path / "results")

    fake_dv = ModuleType("data_validator")
    fake_dv.check_stock_csv = lambda: {"status": "FAIL", "reason": "sandbox"}
    fake_dv.check_history_csv = lambda: {"status": "FAIL", "reason": "sandbox"}
    monkeypatch.setitem(__import__("sys").modules, "data_validator", fake_dv)
    return tmp_path


def test_health_run_all_empty_remark_metric_counts_kept_rows(health_sandbox):
    """health 整跑：守卫前 .str 崩被 except 吞掉→误报健康；守卫后计数项 True 且计数=1。"""
    results = oh.run_all()
    real = [c for c in results["checks"] if c.get("name") == "Metric: real trades"]
    assert real, results["checks"]
    entry = real[0]
    assert entry["status"] == "PASS"
    assert "1 real trades" in entry.get("detail", "")
