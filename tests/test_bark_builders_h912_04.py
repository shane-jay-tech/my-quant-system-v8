"""h912-04 批A：bark_sender.builders characterization（结构/分支冻结，零资金数值断言）。

覆盖缺口（基线 34%）：空列表短路、simple 模板风险分档、三个 addendum 的
缺文件→空串分支、tier 路由（beginner→simple / pro→standard）。
"""
from __future__ import annotations

import json

import bark_sender.builders as builders


def _stock(score="80", name="浦发银行", code="600000", price="10.00", change="+1.0%"):
    return {"name": name, "code": code, "price": price, "change": change, "score": score}


def test_build_bark_message_empty_stocks_short_circuit():
    title, body = builders.build_bark_message("2026-09-12", [])
    assert title == "量化选股"
    assert "今日无股票通过筛选条件" in body


def test_build_bark_message_simple_empty_stocks_short_circuit():
    title, body = builders.build_bark_message_simple("2026-09-12", [])
    assert title == "量化选股"
    assert "今日无符合条件的股票" in body


def test_simple_template_risk_tiers():
    high_title, high_body = builders.build_bark_message_simple("2026-09-12", [_stock(score="40")])
    assert "风险高" in high_body
    _, mid_body = builders.build_bark_message_simple("2026-09-12", [_stock(score="60")])
    assert "风险中" in mid_body
    _, low_body = builders.build_bark_message_simple("2026-09-12", [_stock(score="85")])
    assert "风险低" in low_body


def test_friction_addendum_no_orders_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, "ORDERS_DIR", str(tmp_path), raising=False)
    assert builders._build_friction_cost_addendum() == ""


def test_friction_addendum_structure_only(tmp_path, monkeypatch):
    (tmp_path / "daily_orders_20260912.json").write_text(
        json.dumps({"订单": [{"代码": "600000", "金额": 8000}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(builders, "ORDERS_DIR", str(tmp_path), raising=False)
    out = builders._build_friction_cost_addendum()
    assert "═══ 摩擦成本预估 ═══" in out
    assert "买入总额" in out and "成本占比" in out
    empty = json.dumps({"订单": [{"代码": "600000", "金额": 0}]}, ensure_ascii=False)
    (tmp_path / "daily_orders_20260912.json").write_text(empty, encoding="utf-8")
    assert builders._build_friction_cost_addendum() == ""


def test_portfolio_risk_addendum_missing_and_present(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, "DATA_DIR", str(tmp_path), raising=False)
    assert builders._build_portfolio_risk_addendum() == ""
    (tmp_path / "risk_report.json").write_text(
        json.dumps({"drawdown": {"current_dd": "-5%", "action": "normal", "message": "ok"},
                    "volatility": {"annualized": "18%", "target": "20%"}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    out = builders._build_portfolio_risk_addendum()
    assert "═══ 组合风控（Pro 级）═══" in out
    assert "回撤" in out and "波动率" in out


def test_broker_orders_addendum_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, "BROKER_ORDERS_DIR", str(tmp_path / "nope"), raising=False)
    assert builders._build_broker_orders_addendum() == ""


def test_tier_router_routes_beginner_to_simple(monkeypatch, tmp_path):
    from core import config as core_config

    class _Gate:
        should_show_banner = False
        severity = "unknown"

    monkeypatch.setattr(core_config, "BARK_TEMPLATE_LEVEL", "beginner")
    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: "")
    monkeypatch.setattr(builders, "_build_friction_cost_addendum", lambda: "")
    title, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert title.startswith("选股 ")
    assert "首选:" in body


def test_tier_router_routes_pro_to_standard(monkeypatch, tmp_path):
    from core import config as core_config

    class _Gate:
        should_show_banner = False
        severity = "unknown"

    monkeypatch.setattr(core_config, "BARK_TEMPLATE_LEVEL", "pro")
    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: "")
    monkeypatch.setattr(builders, "_build_portfolio_risk_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_friction_cost_addendum", lambda: "")
    monkeypatch.setattr(builders, "build_personalized_section", lambda: [])
    monkeypatch.setattr(builders, "parse_performance_tracking", lambda: None)
    monkeypatch.setattr(builders, "parse_honest_eval", lambda: None)
    title, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert title.startswith("选股报告")
    assert "Top10 榜单" in body
