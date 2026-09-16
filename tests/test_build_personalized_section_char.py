"""build_personalized_section / build_tomorrow_guide 分支 characterization（d913a-41）。

红线遵守：不断言任何资金数值（pnl/价格/市值只用存在性与非零资金字段缺席判定），
全部 monkeypatch/tmp_path 隔离，无真实流水线调用。生产码零改动。
"""
import pandas as pd
import pytest

from bark_sender import formatters


# ---------- build_personalized_section：无持仓分支 ----------

def test_personalized_no_file_returns_empty(tmp_path, monkeypatch):
    """real_trades.csv 不存在 → 返回空列表（无持仓分支）。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path))
    assert formatters.build_personalized_section() == []


def test_personalized_all_closed_returns_empty(tmp_path, monkeypatch):
    """全部买卖对平（无未平仓持仓）→ 返回空列表。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path))
    pd.DataFrame({
        "代码": ["600000", "600000"], "名称": ["X", "X"], "方向": ["买入", "卖出"],
        "数量": [100, 100], "价格": [1.0, 1.0], "日期": ["2026-09-01", "2026-09-02"],
        "备注": ["", ""],
    }).to_csv(tmp_path / "real_trades.csv", index=False)
    assert formatters.build_personalized_section() == []


def test_personalized_example_rows_filtered(tmp_path, monkeypatch):
    """备注含「示例」的行被剔除 → 剔完为空则返回空列表（备注过滤分支）。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path))
    pd.DataFrame({
        "代码": ["600000"], "名称": ["X"], "方向": ["买入"], "数量": [100],
        "价格": [1.0], "日期": ["2026-09-01"], "备注": ["示例数据勿删"],
    }).to_csv(tmp_path / "real_trades.csv", index=False)
    assert formatters.build_personalized_section() == []


def test_personalized_open_position_without_price_files(tmp_path, monkeypatch):
    """有未平仓持仓、无 stock_*.csv 行情文件 → current_price 回退 entry_price，
    输出含持仓节标题与代码（分支与结构断言，不含资金数值断言）。
    注：备注列须非空——空值读成 NaN 后 .str.contains 崩、被函数 except 吞成 []（现行为）。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(formatters, "DATA_DIR", str(tmp_path / "empty_data"))
    pd.DataFrame({
        "代码": ["600000"], "名称": ["X"], "方向": ["买入"], "数量": [100],
        "价格": [1.0], "日期": ["2026-09-01"], "备注": ["持有"],
    }).to_csv(tmp_path / "real_trades.csv", index=False)
    lines = formatters.build_personalized_section()
    assert isinstance(lines, list) and lines
    assert any("你的持仓" in l for l in lines)
    assert any("600000" in l for l in lines)


# ---------- build_tomorrow_guide：max_consecutive_loss 行存在/缺失 ----------

@pytest.fixture()
def guide_inputs():
    stocks = [{"name": f"股票{i}", "score": 90 + i, "price": "1.0", "change": "+1.0%"}
              for i in range(3)]
    return stocks


def test_guide_with_max_consecutive_loss(guide_inputs, monkeypatch):
    """bt_data 含 max_consecutive_loss → 输出含「历史最大连续亏损」提示行。"""
    monkeypatch.setattr(formatters, "_risk_control_lines", lambda: [])
    out = formatters.build_tomorrow_guide(guide_inputs, {"max_consecutive_loss": 3})
    assert "历史最大连续亏损" in out


def test_guide_without_max_consecutive_loss(guide_inputs, monkeypatch):
    """bt_data 缺该键 / bt_data=None → 不出现该行（缺失分支）。"""
    monkeypatch.setattr(formatters, "_risk_control_lines", lambda: [])
    assert "历史最大连续亏损" not in formatters.build_tomorrow_guide(guide_inputs, {})
    assert "历史最大连续亏损" not in formatters.build_tomorrow_guide(guide_inputs, None)


def test_personalized_empty_remark_column_keeps_positions(tmp_path, monkeypatch):
    """备注列整列为空（pd 读成 float64）时，未平仓持仓不得被静默丢弃。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(formatters, "DATA_DIR", str(tmp_path / "empty_data"))
    (tmp_path / "real_trades.csv").write_text(
        "日期,代码,名称,方向,价格,数量,成交额,手续费,下单依据,备注\n"
        "2026-09-01,600000,X,买入,1.0,100,100.0,5.0,系统推荐,\n",
        encoding="utf-8")
    lines = formatters.build_personalized_section()
    assert isinstance(lines, list) and lines
    assert any("你的持仓" in l for l in lines)
    assert any("600000" in l for l in lines)


def test_personalized_all_example_remark_returns_empty(tmp_path, monkeypatch):
    """备注列整列都是「示例」→ 仍返回 []（防修复误伤原语义）。"""
    monkeypatch.setattr(formatters, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(formatters, "DATA_DIR", str(tmp_path / "empty_data"))
    (tmp_path / "real_trades.csv").write_text(
        "日期,代码,名称,方向,价格,数量,成交额,手续费,下单依据,备注\n"
        "2026-09-01,600000,X,买入,1.0,100,100.0,5.0,系统推荐,示例数据勿删\n",
        encoding="utf-8")
    assert formatters.build_personalized_section() == []
