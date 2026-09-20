# -*- coding: utf-8 -*-
"""q920-09：bark_sender.builders 残留 miss 分支 characterization 补测。

基线更新（2026-09-20 实测，非 q918 时的 21 miss）：
  python -m pytest tests/ -q --cov=bark_sender.builders --cov-report=term-missing
  bark_sender/builders.py  232 stmts  13 miss  94%   25-26, 125-130, 209, 211, 213-214, 223
本文件逐段钉这 13 行（全部可测，无「不可测」项）。**零生产码改动**，只补测试。

与既有测试不重叠：test_bark_builders_h912_04 / test_bark_builders_charac 覆盖正文组装与 tier 路由，
本文件只吃它们没走到的 6 个分支。
"""
from __future__ import annotations

import json

import bark_sender.builders as builders


def _stock(name="浦发银行", code="600000", price="10.00", change="+1.0%", score="80"):
    return {"name": name, "code": code, "price": price, "change": change, "score": score}


# ---------------------------------------------------------------- 25-26
def test_cfg_number_异常回退默认值(monkeypatch):
    """builders.py:22-26 —— cfg_get 抛异常 / 返回 None / 返回非数字，三条都必须回退 default，绝不向上抛。"""
    def boom(*a, **k):
        raise RuntimeError("cfg exploded")

    monkeypatch.setattr(builders, "cfg_get", boom)
    assert builders._cfg_number("sim.stop_loss_pct", -0.08) == -0.08      # except 分支（25-26）

    monkeypatch.setattr(builders, "cfg_get", lambda k, d: None)
    assert builders._cfg_number("sim.stop_loss_pct", -0.08) == -0.08      # value is None 分支

    monkeypatch.setattr(builders, "cfg_get", lambda k, d: "not-a-number")
    assert builders._cfg_number("sim.stop_loss_pct", -0.08) == -0.08      # float() 抛错 → 同 except

    monkeypatch.setattr(builders, "cfg_get", lambda k, d: 0.2)
    assert builders._cfg_number("sim.take_profit_pct", -0.08) == 0.2      # 正常路径不被误伤


# ---------------------------------------------------------------- 125-130
def test_simple_模板备选段_两只以上才出现(monkeypatch):
    """builders.py:124-130 —— n_show>1 才拼「备选:」段；单只时该段整段不得出现。"""
    monkeypatch.setattr(builders, "_sim_rule_tail", lambda: "止损-8% | 止盈+20% | 持10天")

    _, body2 = builders.build_bark_message_simple(
        "2026-09-20", [_stock("浦发银行", "600000", score="80"), _stock("万科A", "000002", score="60")])
    assert "备选:" in body2
    assert "  万科A 10.00元 +1.0% 风险中" in body2        # 60 分落「中」档（<70 且 >=55）

    _, body1 = builders.build_bark_message_simple("2026-09-20", [_stock("浦发银行", "600000")])
    assert "备选:" not in body1

    # 4 只时 n_show = min(3, 4) = 3 ⇒ 备选段恰好 2 行（缩进两空格），第 4 只不出现
    _, body3 = builders.build_bark_message_simple("2026-09-20", [_stock(name=f"股{i}", code=f"60000{i}", score="40")
                                                                for i in range(4)])
    backup_lines = [l for l in body3.split("\n") if l.startswith("  股")]
    assert "备选:" in body3 and len(backup_lines) == 2, body3
    assert "股3" not in body3


# ------------------------------------------------- 209 / 211 / 213-214
def _write_risk(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(builders, "DATA_DIR", str(tmp_path))
    (tmp_path / "risk_report.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_portfolio_risk附录_相关性预警与建议动作(monkeypatch, tmp_path):
    """builders.py:209 与 :211 —— correlation.warning 与 recommended_actions 两段拼接。"""
    _write_risk(monkeypatch, tmp_path, {
        "drawdown": {"current_dd": "3.2%", "action": "normal", "message": "回撤可控"},
        "volatility": {"annualized": "18%", "target": "15%"},
        "correlation": {"warning": "银行与地产相关性 0.87"},
        "recommended_actions": ["降低银行仓位", "增配公用事业", "保留现金", "第四条应被截断"],
    })
    out = builders._build_portfolio_risk_addendum()
    assert "═══ 组合风控（Pro 级）═══" in out
    assert "相关性预警：银行与地产相关性 0.87" in out                 # :209
    assert "建议：降低银行仓位" in out and "建议：保留现金" in out      # :211
    assert "第四条应被截断" not in out                               # [:3] 截断口径


def test_portfolio_risk附录_无预警时不出这两行(monkeypatch, tmp_path):
    """反向：correlation 无 warning、recommended_actions 为空 ⇒ 两行都不出现（证明 209/211 是条件分支）。"""
    _write_risk(monkeypatch, tmp_path, {"correlation": {}, "recommended_actions": []})
    out = builders._build_portfolio_risk_addendum()
    assert "相关性预警" not in out and "建议：" not in out


def test_portfolio_risk附录_坏JSON返回空串(monkeypatch, tmp_path):
    """builders.py:213-214 —— json 解析失败走 except，返回空串而非抛异常（推送不能因风控附录崩）。"""
    _write_risk(monkeypatch, tmp_path, "{ this is not json ")
    assert builders._build_portfolio_risk_addendum() == ""

    # 文件不存在也返回空串（:193-194）
    monkeypatch.setattr(builders, "DATA_DIR", str(tmp_path / "nowhere"))
    assert builders._build_portfolio_risk_addendum() == ""


# ---------------------------------------------------------------- 223
def test_broker_orders附录_目录存在但为空返回空串(monkeypatch, tmp_path):
    """builders.py:219-223 —— 目录在但零文件 ⇒ 返回空串（不是拼一个只有标题的空壳）。"""
    empty = tmp_path / "broker_orders"
    empty.mkdir()
    monkeypatch.setattr(builders, "BROKER_ORDERS_DIR", str(empty))
    assert builders._build_broker_orders_addendum() == ""       # :223

    # 目录不存在同样空串（:219-220）
    monkeypatch.setattr(builders, "BROKER_ORDERS_DIR", str(tmp_path / "missing"))
    assert builders._build_broker_orders_addendum() == ""

    # 有文件则正常拼段（反向对照，证明不是恒返回空）
    (empty / "order_a.csv").write_text("x", encoding="utf-8")
    (empty / "order_b.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr(builders, "BROKER_ORDERS_DIR", str(empty))   # 指回有文件的目录
    out = builders._build_broker_orders_addendum()
    assert "═══ 券商订单（Auto 级）═══" in out and "order_b.csv" in out and "order_a.csv" in out
