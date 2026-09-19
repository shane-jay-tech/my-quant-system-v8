# -*- coding: utf-8 -*-
"""`备注` 列 dtype 守卫的回归（q918-16 终切片；同族 A 类 #8/#10-13）。

钉的不是"会不会抛异常"——五处都在 `try/except Exception` 里，**病灶是被吞掉的静默错值**：
`备注` 整列为空时 pandas 给 float64，`.str` 抛 AttributeError ⇒
`_count_real_trades()` 回 0、`calc_execution_quality()` 回 None、`_lookup_position_shares()` 少算真实持仓。
零真实路径：三个模块的 BASE_DIR/SIM_DIR 一律 monkeypatch 到 tmp_path。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bark_sender.rebalancer as rb  # noqa: E402
import newbie_protection as npz  # noqa: E402


def _trades(tmp_path, body):
    (tmp_path / "real_trades.csv").write_text(
        "代码,方向,数量,备注\n" + body, encoding="utf-8")
    return tmp_path


def test_count_real_trades_not_silently_zero_when_remark_empty(tmp_path, monkeypatch):
    """整列备注为空 ⇒ 改前 `except` 吞掉 AttributeError 返回 0；改后必须返回真实行数。"""
    _trades(tmp_path, "600519,买入,100,\n000001,买入,200,\n600519,卖出,50,\n")
    monkeypatch.setattr(npz, "BASE_DIR", str(tmp_path))

    assert npz._count_real_trades() == 3


def test_lookup_position_shares_still_counts_real_when_remark_empty(tmp_path, monkeypatch):
    """真实持仓不得因备注全空而被静默丢掉（这条最贵：它喂调仓建议的股数）。"""
    _trades(tmp_path, "600519,买入,100,\n600519,买入,50,\n")
    monkeypatch.setattr(rb, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(rb, "SIM_DIR", str(tmp_path / "_no_sim_dir_"))   # 只留真实持仓一路

    assert rb._lookup_position_shares("600519") == 150


def test_guard_does_not_loosen_the_example_filter(tmp_path, monkeypatch):
    """守卫只是 dtype 兜底：`示例` 行照旧被剔除，混合列也不该多算。"""
    _trades(tmp_path, "600519,买入,100,示例数据请删除\n000001,买入,200,\n300750,买入,10,示例\n")
    monkeypatch.setattr(npz, "BASE_DIR", str(tmp_path))

    assert npz._count_real_trades() == 1
