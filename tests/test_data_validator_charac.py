# -*- coding: utf-8 -*-
"""data_validator 只读 characterization 单测（d914-69 T2）。

不改生产码；全部 tmp_path/monkeypatch 隔离，绝不调用 main()（它会写 reports/）。
阈值经 dv.cfg_get 强制走默认值，避免本机 system_config 覆盖导致 4000 假设漂移。
不断言任何具体资金/价格数值（只断言 status / reason 关键字 / metrics 键存在性）。
"""
import json
from pathlib import Path

import pandas as pd
import pytest

import data_validator as dv


@pytest.fixture()
def iso_env(tmp_path, monkeypatch):
    """隔离 DATA_DIR/REPO_ROOT/REPORTS_DIR 并强制配置默认值。"""
    monkeypatch.setattr(dv, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dv, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dv, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(dv, "cfg_get", lambda k, d=None: d)
    return tmp_path


def _stock_csv(data_dir, rows=4000, zero_ratio=0.0, include_price=True, include_volume=True):
    n_zero = int(rows * zero_ratio)
    data = {"代码": [f"{600000 + i}" for i in range(rows)]}
    if include_price:
        prices = [10.0] * rows
        for i in range(n_zero):
            prices[i] = 0.0
        data["最新价"] = prices
    if include_volume:
        data["成交量"] = [1000 + i for i in range(rows)]
    pd.DataFrame(data).to_csv(data_dir / "stock_20260914.csv", index=False, encoding="utf-8")


# ---- check_stock_csv（5 条） ----

def test_stock_csv_missing_dir_fail(iso_env):
    r = dv.check_stock_csv()
    assert r["status"] == "FAIL"
    assert r["reason"] == "no stock_*.csv files"


def test_stock_csv_row_count_below_min_fail(iso_env):
    _stock_csv(iso_env, rows=100)
    r = dv.check_stock_csv()
    assert r["status"] == "FAIL"
    assert "row count" in r["reason"]


def test_stock_csv_low_nonzero_ratio_warn(iso_env):
    _stock_csv(iso_env, rows=4000, zero_ratio=0.05)
    r = dv.check_stock_csv()
    assert r["status"] == "WARN"
    assert "nonzero_price_ratio" in r["metrics"]


def test_stock_csv_no_price_column_fail(iso_env):
    _stock_csv(iso_env, rows=4000, include_price=False)
    r = dv.check_stock_csv()
    assert r["status"] == "FAIL"
    assert "no price column" in r["reason"]


def test_stock_csv_all_green_ok(iso_env):
    _stock_csv(iso_env, rows=4000)
    r = dv.check_stock_csv()
    assert r["status"] == "OK"


# ---- check_history_csv（3 条） ----

def test_history_csv_missing_fail(iso_env):
    r = dv.check_history_csv()
    assert r["status"] == "FAIL"
    assert "missing" in r["reason"]


def test_history_csv_bad_date_fail(iso_env):
    pd.DataFrame({"代码": ["600000"], "日期": ["垃圾日期"]}).to_csv(
        iso_env / "history.csv", index=False, encoding="utf-8")
    r = dv.check_history_csv()
    assert r["status"] == "FAIL"
    assert "read failed" in r["reason"]


def test_history_csv_today_ok(iso_env):
    today = pd.Timestamp.now().normalize().strftime("%Y-%m-%d")
    pd.DataFrame({"代码": ["600000", "600001"], "日期": [today, today]}).to_csv(
        iso_env / "history.csv", index=False, encoding="utf-8")
    r = dv.check_history_csv()
    # 周末/日历边界下退化为工作日或日历口径均合法（风险 B，以实测为准）
    assert r["status"] in ("OK", "WARN")
    assert "lag_unit" in r["metrics"]


# ---- check_multi_vote（4 条） ----

def test_multi_vote_no_files_warn(iso_env):
    r = dv.check_multi_vote()
    assert r["status"] == "WARN"
    assert "no multi_vote files yet" in r["reason"]


def test_multi_vote_empty_list_warn(iso_env):
    orders = iso_env / "orders"
    orders.mkdir(exist_ok=True)
    (orders / "multi_vote_20260914.json").write_text("[]", encoding="utf-8")
    r = dv.check_multi_vote()
    assert r["status"] == "WARN"
    assert "multi_vote empty" in r["reason"]


def test_multi_vote_missing_fields_fail(iso_env):
    orders = iso_env / "orders"
    orders.mkdir(exist_ok=True)
    (orders / "multi_vote_20260914.json").write_text(
        json.dumps([{"代码": "600000"}]), encoding="utf-8")
    r = dv.check_multi_vote()
    assert r["status"] == "FAIL"
    assert "missing fields" in r["reason"]


def test_multi_vote_complete_ok(iso_env):
    orders = iso_env / "orders"
    orders.mkdir(exist_ok=True)
    (orders / "multi_vote_20260914.json").write_text(
        json.dumps([{"代码": "600000", "名称": "样本股", "最新价": 1, "最终得分": 2}]),
        encoding="utf-8")
    r = dv.check_multi_vote()
    assert r["status"] == "OK"


# ---- write_report（1 条） ----

def test_write_report_overall_ok_and_content(iso_env):
    path, overall = dv.write_report({"x": {"status": "OK", "reason": "", "metrics": {}}})
    assert overall == "OK"
    text = Path(path).read_text(encoding="utf-8")
    assert "## 总体：OK" in text
    assert "由 data_validator.py v" in text
