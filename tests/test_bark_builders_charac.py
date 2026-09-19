"""h912-15 批B2：bark_sender.builders 模板分支补测（38-103 正文组装、243-332 tier/research）。

与 tests/test_bark_builders_h912_04.py 不重叠：本文件覆盖「有股票」时的完整模板组装、
集中度双提示、研究模式全分支、tier auto 分支与 ETF 闸门横幅/脚注接线。
"""

from __future__ import annotations

import bark_sender.builders as builders


def _stock(name="浦发银行", code="600000", price="10.00", change="+1.0%", score="80"):
    return {"name": name, "code": code, "price": price, "change": change, "score": score}


def _stub_env(monkeypatch, *, sector="银行", gate_severity="unknown", banner=""):
    """隔离外部读数：个性化/回顾/回测/板块分类/ETF 闸门全部 stub。"""
    monkeypatch.setattr(builders, "build_personalized_section", lambda: [])
    monkeypatch.setattr(builders, "parse_performance_tracking", lambda: None)
    monkeypatch.setattr(builders, "parse_honest_eval", lambda: None)
    monkeypatch.setattr(builders, "classify_sector", lambda code, name: sector)

    class _Gate:
        should_show_banner = bool(banner)
        severity = gate_severity

    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: banner)
    monkeypatch.setattr(builders, "_build_friction_cost_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_portfolio_risk_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_broker_orders_addendum", lambda: "")


def test_build_bark_message_full_template(monkeypatch):
    """38-103 主体：标题统计＋榜单/板块分布/为何选中/明日操作参考四段齐全。"""
    _stub_env(monkeypatch, sector="银行")
    stocks = [_stock(name=f"股{i}", code=f"60000{i}", change="+2.0%", score="85") for i in range(3)]
    title, body = builders.build_bark_message("2026-09-12", stocks)
    assert title == "选股报告 2026-09-12 | Top3均涨+2.0% | 3/3上涨"
    assert "═══ Top10 榜单 ═══" in body
    assert "═══ 板块分布 ═══" in body and "银行3只(100%)" in body
    assert "═══ 为何选中这些股票 ═══" in body
    assert "--- 明日操作参考 ---" in body


def test_build_bark_message_top10_cap_on_large_list(monkeypatch):
    """>10 只 → 榜单只取前 10（n_show 截断规则）。"""
    _stub_env(monkeypatch)
    stocks = [_stock(name=f"股{i:02d}", code=f"6000{i:02d}") for i in range(12)]
    _, body = builders.build_bark_message("2026-09-12", stocks)
    assert body.count("\n#") == 10  # #1..#10 共 10 行
    assert "#10 " in body and "#11" not in body


def test_build_bark_message_concentration_dual_warnings(monkeypatch):
    """单一板块 100%（≥40%）→ 集中度风险提示；≥3 只 → 同板块提醒，双提示齐发。"""
    _stub_env(monkeypatch, sector="银行")
    stocks = [_stock(name=f"股{i}", code=f"60000{i}") for i in range(4)]
    _, body = builders.build_bark_message("2026-09-12", stocks)
    assert "集中度过高(100%)" in body
    assert "同一板块建议不超过3只" in body


def test_build_bark_message_previous_review_wiring(monkeypatch):
    """绩效数据存在 → 回顾区块接进正文（:92-95 接线）。"""
    _stub_env(monkeypatch)
    monkeypatch.setattr(
        builders, "parse_performance_tracking",
        lambda: {"previous": {"date": "2026-09-10", "count": 5, "win_rate": 60.0, "avg_ret": 1.2}},
    )
    _, body = builders.build_bark_message("2026-09-12", [_stock()])
    assert "--- 上次推荐回顾 ---" in body


def test_build_bark_message_uses_injected_bt_data(monkeypatch):
    """bt_data 显式传入时不再读 honest_eval（:98-99 分支）。"""
    _stub_env(monkeypatch)
    bt = {"bull_trades": 30, "bear_trades": 10, "net10": 1.5, "excess": 0.5}
    _, body = builders.build_bark_message("2026-09-12", [_stock()], bt_data=bt)
    assert "近60日牛市占比75%" in body


# ---- 243-332：tier 路由（auto/横幅/脚注）与研究模式 ----

def test_tier_auto_appends_broker_addendum(monkeypatch, tmp_path):
    """auto 档 → 券商订单附录接线（pro 档没有）。"""
    from core import config as core_config

    class _Gate:
        should_show_banner = False
        severity = "unknown"

    monkeypatch.setattr(core_config, "BARK_TEMPLATE_LEVEL", "auto")
    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: "")
    monkeypatch.setattr(builders, "_build_portfolio_risk_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_friction_cost_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_broker_orders_addendum", lambda: "\n═══ 券商订单（Auto 级）═══")
    _, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert "═══ 券商订单（Auto 级）═══" in body


def test_tier_gate_banner_goes_to_top(monkeypatch):
    """闸门 severe/warning → 横幅置于正文顶部。"""
    from core import config as core_config

    class _Gate:
        should_show_banner = True
        severity = "severe"

    monkeypatch.setattr(core_config, "BARK_TEMPLATE_LEVEL", "pro")
    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: "⚠️ ETF 横幅")
    monkeypatch.setattr(builders, "_build_portfolio_risk_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_friction_cost_addendum", lambda: "")
    _, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert body.startswith("⚠️ ETF 横幅")


def test_tier_normal_gate_banner_becomes_footnote(monkeypatch):
    """闸门 normal → 横幅作脚注追加正文末尾（不置顶）。"""
    from core import config as core_config

    class _Gate:
        should_show_banner = False
        severity = "normal"

    monkeypatch.setattr(core_config, "BARK_TEMPLATE_LEVEL", "pro")
    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: "✅ 跑赢基准小贴士")
    monkeypatch.setattr(builders, "_build_portfolio_risk_addendum", lambda: "")
    monkeypatch.setattr(builders, "_build_friction_cost_addendum", lambda: "")
    _, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert not body.startswith("✅")
    assert body.rstrip().endswith("✅ 跑赢基准小贴士")


def test_research_mode_empty_and_full(monkeypatch):
    """研究模式：空列表短路；有数据时方法论/回测/因子/板块/页脚齐全。"""
    _stub_env(monkeypatch, sector="银行")
    title, body = builders.build_bark_message_research("2026-09-12", [])
    assert title == "选股研究" and "无信号" in body

    bt = {"近60日持有": {"净收益": "+5%", "胜率": "55%"}, "基准对比": {"超额": "+2%"}}
    stocks = [_stock(name="股A", score="90"), _stock(name="股B", code="000001", score="88")]
    title, body = builders.build_bark_message_research("2026-09-12", stocks, bt_data=bt)
    assert title == "研究 | 2026-09-12 | Top2均涨+1.0%"
    assert "## 策略方法论" in body and "5因子评分" in body
    assert "## 策略回测绩效" in body and "净收益 +5%" in body and "超额收益: +2%" in body
    assert "## 今日选股及因子得分" in body and "股A(600000)" in body
    assert "## 板块分布" in body and "*研究模式报告 · 仅供量化研究参考*" in body


# ---- q918-06（S5 B-6）：auto 档真依赖接线——附录函数不 stub，只隔离读盘路径 ----


def _wire_env(monkeypatch, tmp_path):
    """与 _stub_env 同样的外部读数隔离，但保留三个附录真函数，读盘指向 tmp_path。"""
    monkeypatch.setattr(builders, "build_personalized_section", lambda: [])
    monkeypatch.setattr(builders, "parse_performance_tracking", lambda: None)
    monkeypatch.setattr(builders, "parse_honest_eval", lambda: None)
    monkeypatch.setattr(builders, "classify_sector", lambda code, name: "银行")

    class _Gate:
        should_show_banner = False
        severity = "unknown"

    monkeypatch.setattr(builders, "evaluate_etf_gate", lambda base: _Gate())
    monkeypatch.setattr(builders, "format_gate_banner", lambda gate: "")

    from core import config as core_config
    monkeypatch.setattr(core_config, "BARK_TEMPLATE_LEVEL", "auto")

    data_dir = tmp_path / "data"
    orders_dir = tmp_path / "orders"
    broker_dir = tmp_path / "broker_orders"
    data_dir.mkdir()
    orders_dir.mkdir()
    monkeypatch.setattr(builders, "DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(builders, "ORDERS_DIR", str(orders_dir), raising=False)
    monkeypatch.setattr(builders, "BROKER_ORDERS_DIR", str(broker_dir), raising=False)
    return data_dir, orders_dir, broker_dir


def test_tier_auto_real_addendum_wiring_headers_in_order(monkeypatch, tmp_path):
    """auto 档真依赖接线：最小种子文件喂真附录函数，正文含三段标题且顺序
    组合风控→券商订单→摩擦成本（结构断言，零数值断言；种子金额仅为让摩擦段非空）。"""
    import json

    data_dir, orders_dir, broker_dir = _wire_env(monkeypatch, tmp_path)
    (data_dir / "risk_report.json").write_text("{}", encoding="utf-8")   # 空风控报告也出标题
    broker_dir.mkdir()
    (broker_dir / "order_20260912.csv").write_text("placeholder", encoding="utf-8")
    (orders_dir / "daily_orders_20260912.json").write_text(
        json.dumps({"订单": [{"金额": 1000}]}, ensure_ascii=False), encoding="utf-8"
    )

    _, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert "═══ 组合风控（Pro 级）═══" in body
    assert "═══ 券商订单（Auto 级）═══" in body
    assert "═══ 摩擦成本预估 ═══" in body
    assert body.index("组合风控（Pro 级）") < body.index("券商订单（Auto 级）") < body.index("摩擦成本预估")


def test_tier_auto_empty_data_yields_no_addendum_headers(monkeypatch, tmp_path):
    """真依赖空数据侧：tmp 目录全空 → 三个附录真函数全走「无数据→空串」分支，
    正文不含任何附录标题（证明接线读的是被隔离的真实路径，非 stub 残留）。"""
    _wire_env(monkeypatch, tmp_path)
    _, body = builders.build_bark_message_for_tier("2026-09-12", [_stock()])
    assert "═══ 组合风控（Pro 级）═══" not in body
    assert "═══ 券商订单（Auto 级）═══" not in body
    assert "═══ 摩擦成本预估 ═══" not in body
