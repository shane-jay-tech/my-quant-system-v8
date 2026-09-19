"""q918-01：bark_sender.rebalancer.build_adjustment_plan characterization 冻结测试。

基线 #1（docs/insights/quant-test-baseline-20260915.md：A 口径 9%）。风控相邻域，
只允许 characterization——先跑后断言，冻结现值，不写期望数值。零生产码改动。

时钟：经 conftest.frozen_clock 冻结 bark_sender.parsers（FROZEN_CLOCK_TARGETS 已登记），
exit_advisor 今日文件名日期确定，跨午夜不挂。路径：monkeypatch 模块常量
（parsers.RESULTS_DIR / parsers.ORDERS_DIR / rebalancer.SIM_DIR / rebalancer.BASE_DIR）。
"""

from __future__ import annotations

import json

import pytest

import bark_sender.parsers as parsers
import bark_sender.rebalancer as rebalancer

FROZEN_PLAN = (
    "\n═══ 🔄 今日完整调仓计划 ═══\n"
    "\n"
    "【卖出】\n"
    "  测试A(600001) 500股 × 9.00元 → 预计回收约4,491元\n"
    "    原因: 达到止损位\n"
    "  预计回收总资金: 约4,491元 (已预留0.2%滑点+手续费)\n"
    "\n"
    "【买入】（按选股评分从高到低分配）\n"
    "  1. 测试C(600003) 200股 × 20.00元 ≈ 4,000元 (评分60) — 来源: 卖出款\n"
    "\n"
    "【资金不足，可选择性执行】\n"
    "  · 测试B(600002) 1000股 ≈ 8,500元 (评分80) — 需额外资金\n"
    "\n"
    "【剩余资金】约491元 (留作现金)\n"
    "\n"
    "💡 操作顺序: 先卖后买，确保资金到位\n"
)


def _seed(tmp_path, *, with_sells=True, with_buys=True, with_position=True, with_scores=True):
    """在 tmp_path 造全套输入，返回各目录路径。卖单 500 股 × 9.00 元。"""
    results = tmp_path / "results"
    orders = tmp_path / "orders"
    sim = tmp_path / "sim_results"
    for d in (results, orders, sim):
        d.mkdir(parents=True)

    if with_sells:
        today = parsers.datetime.now().strftime("%Y%m%d")
        (results / f"exit_advisor_{today}.md").write_text(
            "# exit advisor\n"
            "## 🚨 需要操作\n"
            "| 600001 | 测试A | 10.00 | 9.00 | -10% | - | 止损 | 达到止损位 |\n"
            "## 📊 观察池\n"
            "| 999999 | 不解析 | 1 | 1 | 0% | - | 持有 | 忽略 |\n",
            encoding="utf-8",
        )
    if with_buys:
        (orders / "daily_orders_20260918.md").write_text(
            "## 今日买入订单（建议持有10天）\n"
            "| 600002 | 测试B | 买入 | 8.50 | 1000 | 8500.00 | 来源A |\n"
            "| 600003 | 测试C | 买入 | 20.00 | 200 | 4000.00 | 来源B |\n",
            encoding="utf-8",
        )
    if with_position:
        (sim / "account_state.json").write_text(
            json.dumps({"positions": [{"code": "600001", "shares": 500}]}),
            encoding="utf-8",
        )
    if with_scores:
        (results / "pick_20260918.md").write_text(
            "2026-09-18 报告\n"
            "| 1 | 600002 | 测试B | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 80 |\n"
            "| 2 | 600003 | 测试C | 10.00 | +1.0% | 9.8 | 9.5 | 55.0 | 1.2 | 500亿 | 60 |\n",
            encoding="utf-8",
        )
    return results, orders, sim


def _patch_paths(monkeypatch, tmp_path, results, orders, sim):
    monkeypatch.setattr(parsers, "RESULTS_DIR", str(results), raising=False)
    monkeypatch.setattr(parsers, "ORDERS_DIR", str(orders), raising=False)
    monkeypatch.setattr(rebalancer, "SIM_DIR", str(sim), raising=False)
    monkeypatch.setattr(rebalancer, "BASE_DIR", str(tmp_path), raising=False)


def test_sells_missing_returns_none(tmp_path, monkeypatch, frozen_clock):
    """缺卖单（sells=[]）→ None，短路与持仓/评分无关。"""
    frozen_clock("2026-09-19 12:00:00")
    results, orders, sim = _seed(tmp_path, with_sells=False)
    _patch_paths(monkeypatch, tmp_path, results, orders, sim)
    assert rebalancer.build_adjustment_plan() is None


def test_buys_missing_returns_none(tmp_path, monkeypatch, frozen_clock):
    """缺买单（buys=[]）→ None。"""
    frozen_clock("2026-09-19 12:00:00")
    results, orders, sim = _seed(tmp_path, with_buys=False)
    _patch_paths(monkeypatch, tmp_path, results, orders, sim)
    assert rebalancer.build_adjustment_plan() is None


def test_empty_position_returns_none(tmp_path, monkeypatch, frozen_clock):
    """空仓侧：卖出的票无任何持仓（sim/real 均无）→ shares≤0 全部跳过 → None。"""
    frozen_clock("2026-09-19 12:00:00")
    results, orders, sim = _seed(tmp_path, with_position=False)
    _patch_paths(monkeypatch, tmp_path, results, orders, sim)
    assert rebalancer.build_adjustment_plan() is None


def test_full_position_plan_frozen_output(tmp_path, monkeypatch, frozen_clock):
    """满仓侧：500 股可卖，回收 4,491 元（=9.00×500×0.998，先跑实测冻结）。

    评分排序 600002(80)>600003(60)：600002 需 8,500 超回收额 → 落「资金不足」；
    600003 需 4,000 ≤ 4,491 → 分配；剩余 491 元 > 10 → 出「剩余资金」行。
    全文等值冻结现值。"""
    frozen_clock("2026-09-19 12:00:00")
    results, orders, sim = _seed(tmp_path)
    _patch_paths(monkeypatch, tmp_path, results, orders, sim)
    plan = rebalancer.build_adjustment_plan()
    assert plan == FROZEN_PLAN
