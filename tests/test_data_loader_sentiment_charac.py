# -*- coding: utf-8 -*-
"""load_market_sentiment characterization（d914-72 T5）：四处静默 except 改显式日志。

假 akshare 经 sys.modules 注入（函数内 import），零联网、零真实抓取。
"""
import sys
import types

import pandas as pd
import pytest

import data_loader as dl

ALLOWED = {"涨停家数", "跌停家数", "上涨家数", "下跌家数", "hs300_vol20"}


class FakeAk:
    """按 mode 控制各接口抛异常或返回固定 DataFrame。"""

    def __init__(self, fail: set):
        self.fail = fail

    def stock_zt_pool_em(self, date):
        if "zt" in self.fail:
            raise RuntimeError("zt down")
        return pd.DataFrame({"代码": ["600000", "600001"]})

    def stock_zt_pool_dtgc_em(self, date):
        if "dt" in self.fail:
            raise RuntimeError("dt down")
        return pd.DataFrame({"代码": ["600002"]})

    def stock_zdfx_em(self):
        if "zdfx" in self.fail:
            raise RuntimeError("zdfx down")
        return pd.DataFrame({"上涨家数": [3000], "下跌家数": [2000]})


def _install_fake_ak(monkeypatch, fail):
    fake = FakeAk(fail)
    monkeypatch.setitem(sys.modules, "akshare", fake)
    return fake


def _hs300_bad_file(tmp_path):
    """损坏的 hs300 文件：有文件但读入后必抛（缺收盘/日期列）。"""
    pd.DataFrame({"foo": [1]}).to_csv(tmp_path / "hs300_index.csv", index=False)


@pytest.fixture()
def clean_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
    return tmp_path


def test_all_fail_returns_empty_and_logs_four_times(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
    _hs300_bad_file(tmp_path)
    _install_fake_ak(monkeypatch, fail={"zt", "dt", "zdfx"})
    result = dl.load_market_sentiment()
    assert result == {}
    out = capsys.readouterr().out
    assert out.count("unavailable") >= 4
    assert set(result) <= ALLOWED


def test_all_success_no_unavailable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dl, "DATA_DIR", tmp_path)  # 无 hs300 文件 → 该抓取点整体跳过
    _install_fake_ak(monkeypatch, fail=set())
    result = dl.load_market_sentiment()
    assert result["涨停家数"] == 2
    assert result["跌停家数"] == 1
    assert result["上涨家数"] == 3000
    assert result["下跌家数"] == 2000
    out = capsys.readouterr().out
    assert out.count("unavailable") == 0
    assert set(result) <= ALLOWED


def test_partial_failure_keys_and_log_count(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
    _install_fake_ak(monkeypatch, fail={"zt"})
    result = dl.load_market_sentiment()
    assert "涨停家数" not in result
    assert result["跌停家数"] == 1
    assert capsys.readouterr().out.count("unavailable") == 1
    assert set(result) <= ALLOWED


def test_hs300_vol_failure_logged(tmp_path, monkeypatch, capsys):
    _hs300_bad_file(tmp_path)
    monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
    _install_fake_ak(monkeypatch, fail={"zt", "dt", "zdfx"})
    result = dl.load_market_sentiment()
    out = capsys.readouterr().out
    assert "hs300_vol20 unavailable" in out
    assert set(result) <= ALLOWED


def test_result_key_set_never_grows(tmp_path, monkeypatch, capsys):
    for fail in ({"zt"}, {"dt", "zdfx"}, set(), {"zt", "dt", "zdfx"}):
        capsys.readouterr()
        _hs300_bad_file(tmp_path)
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _install_fake_ak(monkeypatch, fail=fail)
        result = dl.load_market_sentiment()
        assert set(result) <= ALLOWED
