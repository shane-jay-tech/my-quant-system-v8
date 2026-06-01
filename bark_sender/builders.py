import os, sys, glob, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sector_classifier import classify_sector
from etf_gate import evaluate_etf_gate, format_gate_banner
from cost_model import COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE
from core.config import get as cfg_get
from .parsers import parse_honest_eval, parse_performance_tracking, _get_pick_scores
from .formatters import explain_stock_detailed, build_previous_review, build_tomorrow_guide, build_personalized_section
from .rebalancer import build_adjustment_plan

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
BROKER_ORDERS_DIR = os.path.join(BASE_DIR, 'broker_orders')


def _cfg_number(key, default):
    """从 core.config 读数字，缺失/异常时回退 default。"""
    try:
        value = cfg_get(key, default)
        return float(value) if value is not None else float(default)
    except Exception:
        return float(default)


def _sim_rule_tail() -> str:
    """simple 推送尾部风控文案，跟随系统真实配置（不再是写死的 +15%/5-10天）。"""
    stop_pct = _cfg_number('sim.stop_loss_pct', -0.08)
    take_pct = _cfg_number('sim.take_profit_pct', 0.20)
    hold_days = int(_cfg_number('sim.max_hold_days', 10))
    return f"止损{stop_pct:.0%} | 止盈{take_pct:+.0%} | 持{hold_days}天"

def build_bark_message(pick_date, stocks, bt_data=None):
    """构建 Bark 推送内容 v3"""
    if not stocks:
        return "量化选股", f"{pick_date}\n今日无股票通过筛选条件"

    n_show = min(10, len(stocks))
    avg_change = sum(float(s['change'].replace('%', '').replace('+', '')) for s in stocks[:n_show]) / n_show
    up_count = sum(1 for s in stocks[:n_show] if '+' in s['change'])

    title = f"选股报告 {pick_date} | Top{n_show}均涨{avg_change:+.1f}% | {up_count}/{n_show}上涨"

    lines = []
    lines.append(f"{pick_date} 量化选股 · v5策略")

    # 个性化持仓区块
    personal = build_personalized_section()
    if personal:
        lines.extend(personal)

    lines.append(f"全市场筛选 → 精选Top{n_show}，均涨幅{avg_change:+.1f}%，{up_count}只上涨")
    lines.append("")

    # TOP 10 简洁列表
    lines.append("═══ Top10 榜单 ═══")
    for i, s in enumerate(stocks[:n_show], 1):
        lines.append(f"#{i} {s['name']}({s['code']}) {s['price']} {s['change']} {s['score']}分")
    lines.append("")

    # 板块分布（使用统一分类器 + 占比）
    sectors = {}
    for s in stocks[:n_show]:
        sec = classify_sector(s['code'], s['name'])
        sectors[sec] = sectors.get(sec, 0) + 1
    lines.append("═══ 板块分布 ═══")
    sector_items = []
    for sec, cnt in sorted(sectors.items(), key=lambda x: -x[1]):
        pct = cnt / n_show * 100
        sector_items.append(f"{sec}{cnt}只({pct:.0f}%)")
    sector_summary = ' | '.join(sector_items)
    lines.append(sector_summary)
    max_sec = max(sectors, key=sectors.get)
    max_sec_pct = sectors[max_sec] / n_show * 100
    if max_sec_pct >= 40:
        lines.append(f"风险提示：{max_sec}集中度过高({max_sec_pct:.0f}%)，建议分散至不超过30%")
    if sectors[max_sec] >= 3:
        lines.append(f"提醒：{max_sec}板块{ sectors[max_sec]}只，同一板块建议不超过3只")
    lines.append("")

    # 入选理由 —— 有证据链的详细版
    lines.append("═══ 为何选中这些股票 ═══")
    lines.append("")
    for i, s in enumerate(stocks[:n_show], 1):
        lines.append(f"{i}. {explain_stock_detailed(s)}")
        lines.append("")

    # 上次推荐回顾（验证策略有效性）
    perf_data = parse_performance_tracking()
    review_lines = build_previous_review(perf_data)
    if review_lines:
        lines.extend(review_lines)

    # 明日操作参考
    if bt_data is None:
        bt_data = parse_honest_eval()
    lines.append(build_tomorrow_guide(stocks, bt_data))

    body = '\n'.join(lines)
    return title, body



def build_bark_message_simple(pick_date, stocks, bt_data=None):
    """简易模式 — 极简，只留操作要素：代码+方向+价格+风险"""
    if not stocks:
        return "量化选股", f"{pick_date}\n今日无符合条件的股票"

    n_show = min(3, len(stocks))
    top = stocks[0]
    top_score = int(float(top['score']))
    risk = "低" if top_score >= 70 else ("中" if top_score >= 55 else "高")

    title = f"选股 {pick_date[-4:]} | {top['name']} {top['price']}元"

    lines = []
    lines.append(f"首选: {top['name']}({top['code']})")
    lines.append(f"现价 {top['price']}元  {top['change']}  评分{top['score']}  风险{risk}")
    lines.append("")

    if n_show > 1:
        lines.append("备选:")
        for s in stocks[1:n_show]:
            s_score = int(float(s['score']))
            s_risk = "低" if s_score >= 70 else ("中" if s_score >= 55 else "高")
            lines.append(f"  {s['name']} {s['price']}元 {s['change']} 风险{s_risk}")
        lines.append("")

    lines.append(_sim_rule_tail())
    lines.append("模型建议仅供参考")

    body = '\n'.join(lines)
    return title, body


# ============================================================
# v8 分级附录构造器（addendum）
# ============================================================
def _build_friction_cost_addendum():
    """所有 tier 都启用：从最新 daily_orders 估算佣金/印花税摩擦成本。

    v8.7 修正三件事：
    1. 订单金额字段是「金额」（旧代码读「实际投入/买入金额」，恒为 0 → 附录从不显示）。
    2. 佣金/印花税从 cost_model 单一真相源读，不再硬编码 0.00025。
    3. 按每笔订单分别套 5 元最低佣金，而不是把总买入额只套一次 floor
       （3 笔各 800 元：真实佣金 15+15=30，旧公式只算约 7.2×2）。
    """
    pattern = os.path.join(ORDERS_DIR, 'daily_orders_*.json')
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return ""
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
        orders = data.get('订单', []) or []
        if not orders:
            return ""
        total_buy = 0.0
        round_trip = 0.0
        n = 0
        for o in orders:
            # 兼容历史字段拼写，但以当前真实字段「金额」为准
            amount = float(o.get('金额') or o.get('实际投入') or o.get('买入金额') or 0)
            if amount <= 0:
                continue
            n += 1
            total_buy += amount
            commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
            round_trip += commission * 2 + amount * STAMP_TAX_RATE
        if total_buy <= 0 or n == 0:
            return ""
        pct = round_trip / total_buy * 100
        lines = ["", "═══ 摩擦成本预估 ═══"]
        lines.append(f"买入总额：¥{total_buy:,.0f}（{n} 笔订单）")
        lines.append(
            f"往返费用：¥{round_trip:.2f}（每笔佣金 max({COMMISSION_RATE:.2%}, ¥{COMMISSION_MIN:.0f})，"
            f"卖出印花税 {STAMP_TAX_RATE:.2%}）"
        )
        lines.append(f"成本占比：{pct:.2f}%")
        if pct > 1.0:
            lines.append(f"⚠️ 摩擦成本占比偏高（>1%），小资金不宜频繁交易")
        return '\n'.join(lines)
    except Exception:
        return ""


def _build_portfolio_risk_addendum():
    """Pro/Auto: 拼接 data/risk_report.json 摘要。"""
    risk_path = os.path.join(DATA_DIR, 'risk_report.json')
    if not os.path.exists(risk_path):
        return ""
    try:
        with open(risk_path, 'r', encoding='utf-8') as f:
            r = json.load(f)
        lines = ["", "═══ 组合风控（Pro 级）═══"]
        d = r.get('drawdown') or {}
        if d:
            lines.append(f"回撤：{d.get('current_dd', d.get('current', 'N/A'))} | 状态：{d.get('action', 'normal')}")
            if d.get('message'):
                lines.append(f"  · {d['message']}")
        v = r.get('volatility') or {}
        if v:
            lines.append(f"波动率：{v.get('annualized', v.get('current', 'N/A'))} | 目标：{v.get('target', 'N/A')}")
        c = r.get('correlation') or {}
        if c.get('warning'):
            lines.append(f"相关性预警：{c['warning']}")
        for a in (r.get('recommended_actions') or [])[:3]:
            lines.append(f"建议：{a}")
        return '\n'.join(lines)
    except Exception:
        return ""


def _build_broker_orders_addendum():
    """Auto: 列出今日生成的券商订单文件。"""
    if not os.path.isdir(BROKER_ORDERS_DIR):
        return ""
    files = sorted(glob.glob(os.path.join(BROKER_ORDERS_DIR, '*')), reverse=True)[:5]
    if not files:
        return ""
    lines = ["", "═══ 券商订单（Auto 级）═══"]
    for f in files:
        if os.path.isfile(f):
            lines.append(f"📎 {os.path.basename(f)}")
    lines.append(f"路径：broker_orders/")
    return '\n'.join(lines)


def build_bark_message_for_tier(pick_date, stocks, bt_data=None):
    """v8 tier 路由：按 BARK_TEMPLATE_LEVEL 选择基础模板并拼接附录。

    - beginner: 简易指令卡 + ETF 闸门 + 摩擦成本
    - advanced: 标准模板（含多策略对比/明日操作）+ ETF 闸门 + 摩擦成本
    - pro:      标准 + ETF 闸门 + 组合风控 + 摩擦成本
    - auto:     标准 + ETF 闸门 + 组合风控 + 券商订单附件 + 摩擦成本

    ETF 闸门：当系统超额收益跑不赢沪深300（或勉强跑赢扣完手续费持平），
    在推送顶部加横幅，提醒用户直接买 ETF 长持。详见 etf_gate.py。
    """
    from core.config import BARK_TEMPLATE_LEVEL

    if BARK_TEMPLATE_LEVEL == 'beginner':
        title, body = build_bark_message_simple(pick_date, stocks, bt_data)
    else:
        title, body = build_bark_message(pick_date, stocks, bt_data)

    # Top banner: ETF 闸门. severe / warning / stale 都强制顶部展示;
    # normal => optional small footnote 在 body 末尾;
    # unknown => silent.
    gate = evaluate_etf_gate(BASE_DIR)
    banner = format_gate_banner(gate)
    if gate.should_show_banner and banner:
        body = banner + '\n\n' + body

    addenda = []
    if BARK_TEMPLATE_LEVEL in ('pro', 'auto'):
        addenda.append(_build_portfolio_risk_addendum())
    if BARK_TEMPLATE_LEVEL == 'auto':
        addenda.append(_build_broker_orders_addendum())
    addenda.append(_build_friction_cost_addendum())

    # Normal-but-positive footnote: small green note at bottom (not banner).
    if gate.severity == 'normal' and banner:
        addenda.append('\n' + banner)

    extras = '\n'.join(x for x in addenda if x)
    if extras:
        body = body + '\n' + extras
    return title, body


def build_bark_message_research(pick_date, stocks, bt_data=None):
    """研究模式 — 侧重方法论、回测数据、因子分析"""
    if not stocks:
        return "选股研究", f"{pick_date}\n无信号"

    n_show = min(10, len(stocks))
    avg_change = sum(float(s['change'].replace('%', '').replace('+', '')) for s in stocks[:n_show]) / n_show

    title = f"研究 | {pick_date} | Top{n_show}均涨{avg_change:+.1f}%"

    lines = []
    lines.append(f"# 选股研究简报 — {pick_date}")
    lines.append("")

    # 方法论
    lines.append("## 策略方法论")
    lines.append("- 模型：5因子评分（趋势30% + RSI20% + MACD20% + 量能15% + 涨跌15%）")
    lines.append("- 筛选：MA多头排列 + RSI(30-70) + 市值>50亿 + 非ST")
    lines.append("- 排序：动量加权（1日×0.5 + 3日×0.3 + 5日×0.2）")
    lines.append("- 出场：MA(5,30)死叉或到期")
    lines.append("")

    # 回测数据
    if bt_data:
        lines.append("## 策略回测绩效")
        for k, v in bt_data.items():
            if '持有' in str(k):
                lines.append(f"- {k}: 净收益 {v.get('净收益','N/A')}, 胜率 {v.get('胜率','N/A')}")
        if '基准对比' in bt_data:
            b = bt_data['基准对比']
            lines.append(f"- 超额收益: {b.get('超额','N/A')}")

    lines.append("")

    # 选股详情
    lines.append("## 今日选股及因子得分")
    for i, s in enumerate(stocks[:n_show], 1):
        lines.append(f"{i}. {s['name']}({s['code']}) — {s['price']} {s['change']} — 评分{s['score']}")
        # 详细的因子解释
        lines.append(f"   {explain_stock_detailed(s)}")

    lines.append("")

    # 板块分析
    sectors = {}
    for s in stocks[:n_show]:
        sec = classify_sector(s['code'], s['name'])
        sectors[sec] = sectors.get(sec, 0) + 1
    lines.append("## 板块分布")
    for sec, cnt in sorted(sectors.items(), key=lambda x: -x[1]):
        lines.append(f"- {sec}: {cnt}只")

    lines.append("")
    lines.append("---")
    lines.append("*研究模式报告 · 仅供量化研究参考*")

    body = '\n'.join(lines)
    return title, body


