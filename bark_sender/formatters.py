import os, sys, glob, json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sector_classifier import classify_sector
from core.config import get as cfg_get

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')


def _cfg_number(key, default):
    """从 core.config 读数字，缺失/异常时回退 default。"""
    try:
        value = cfg_get(key, default)
        return float(value) if value is not None else float(default)
    except Exception:
        return float(default)


def _latest_order_regime() -> str:
    """读最新 daily_orders 的市场状态档位（强牛/弱牛/震荡/弱熊/强熊）；读不到返回空串。"""
    try:
        files = sorted(glob.glob(os.path.join(ORDERS_DIR, 'daily_orders_*.json')), reverse=True)
        if not files:
            return ''
        with open(files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
        return str((data.get('市场状态') or {}).get('档位', '') or '')
    except Exception:
        return ''


def _risk_control_lines() -> list[str]:
    """【仓位与风控】文案：跟随系统真实配置，不再写死旧参数。

    2400 元属于 position_sizer 的小资金模式：除强熊外全仓、取前 3 只、单票上限 1/3。
    大资金按市场状态分档；止损/止盈/持有天数一律读 sim.*。
    """
    capital = _cfg_number('sim.initial_capital', 2400)
    stop_pct = _cfg_number('sim.stop_loss_pct', -0.08)
    take_pct = _cfg_number('sim.take_profit_pct', 0.20)
    hold_days = int(_cfg_number('sim.max_hold_days', 10))
    regime = _latest_order_regime()

    if capital <= 3000:
        if regime == '强熊':
            position_line = f"总仓位：强熊市空仓观望（本金 ¥{capital:,.0f}）"
        else:
            position_line = (
                f"总仓位：小资金模式（本金 ¥{capital:,.0f}）除强熊外全仓，"
                f"最多同时持有 3 只，单票上限约 1/3"
            )
    else:
        if regime == '强熊':
            position_line = "总仓位：强熊市空仓观望"
        else:
            position_line = "总仓位：按市场状态分档（强牛80% / 弱牛60% / 震荡40% / 弱熊20% / 强熊0%）"

    return [
        "【仓位与风控】",
        position_line,
        f"止损线：{stop_pct:.0%} 硬止损（系统配置，跌破即执行）",
        f"止盈参考：{take_pct:+.0%}（系统配置，触发即分批/全仓了结）",
        f"持有周期：最长 {hold_days} 个交易日（到期/止损/止盈任一触发先离场）",
    ]

def explain_stock_detailed(s):
    """有说服力的入选理由 —— 证据 + 逻辑 + 结论"""
    name = s['name']
    change = s['change']
    score = s.get('score', '')
    reason = s.get('reason', '')
    rsi = s.get('rsi', '')
    vol_ratio = s.get('vol_ratio', '')
    ma5 = s.get('ma5', '')
    ma20 = s.get('ma20', '')
    price = s.get('price', '')

    points = []

    # 1. 趋势结构：价格与均线的关系
    try:
        p = float(price)
        m5 = float(ma5)
        m20 = float(ma20)
        if m5 > m20 and p > m5:
            points.append(f"均线呈多头排列（MA5={ma5} > MA20={ma20}），且当前价{price}站在两条均线上方，上升趋势明确")
        elif m5 > m20:
            points.append(f"均线多头排列（MA5={ma5} > MA20={ma20}），趋势结构健康")
        elif p > m20:
            points.append(f"价格{price}站稳MA20（{ma20}）上方，中期趋势未破")
    except Exception:
        pass

    # 2. 量能：放量意味着资金关注
    try:
        vr = float(vol_ratio)
        if vr >= 2.0:
            points.append(f"量比高达{vol_ratio}，是日常成交量的{vr}倍，远超1.2的筛选门槛——这说明今日有大资金在主动买入，短期上涨动能较强")
        elif vr >= 1.5:
            points.append(f"量比{vol_ratio}，成交量温和放大超过50%，有资金在悄悄进场")
        else:
            points.append(f"量比{vol_ratio}，成交量正常，趋势稳定")
    except Exception:
        pass

    # 3. RSI：判断是否过热
    try:
        r = float(rsi)
        if 40 <= r <= 60:
            points.append(f"RSI={rsi}处于40-60的「黄金区间」——既没有超买（>70），也没有超卖（<30），说明上涨空间充足且风险可控")
        elif 60 < r <= 70:
            points.append(f"RSI={rsi}偏强但未超买，短期仍有上行空间，但需关注是否继续升温")
        elif r < 40:
            points.append(f"RSI={rsi}偏低，股价经过调整后有反弹需求")
    except Exception:
        pass

    # 4. 涨跌情况
    try:
        chg = float(change.replace('%', '').replace('+', ''))
        if chg >= 4:
            points.append(f"今日涨幅{change}，属于强势突破形态，但追高需设好止损")
        elif chg >= 2:
            points.append(f"今日涨幅{change}，温和放量上涨，属于稳健的「进二退一」节奏")
        elif chg >= 0:
            points.append(f"今日涨幅{change}，小幅推进，蓄力充分")
    except Exception:
        pass

    # 5. 特殊信号
    if '强趋势' in reason:
        points.append("该股处于明显的上升通道中，趋势强度得分高，惯性上涨的概率较大")
    if 'MACD正向' in reason:
        points.append("MACD指标为正值——这是个客观信号，说明短周期均线在上方，多头占优")

    # 组装：取最有说服力的3-4条
    selected = points[:4]
    if not selected:
        return f"{name} 评分{score}分，综合技术面表现靠前"

    return f"{name}（{change}，{score}分）：{'；'.join(selected)}"



def build_previous_review(perf_data):
    """构建上次推荐回顾"""
    if not perf_data or not perf_data.get('previous'):
        return []

    prev = perf_data['previous']
    if not prev.get('date'):
        return []

    lines = []
    lines.append("--- 上次推荐回顾 ---")
    lines.append("")

    wr = prev.get('win_rate', 0)
    ret = prev.get('avg_ret', 0)
    emoji = "✅" if ret > 0 else "❌"

    lines.append(f"{emoji} {prev['date']}选股1日后：{prev['count']}只可追踪，"
                 f"胜率{wr:.0f}%，平均收益{ret:+.2f}%")

    # 解读
    if ret > 0.5 and wr >= 50:
        lines.append("趋势延续良好 → 策略有效，今日选股信心较高")
    elif ret > 0:
        lines.append("正收益但胜率偏低 → 盈亏比在起作用，维持标准仓位")
    else:
        lines.append("上次选股短期承压 → 关注是否触发止损，做好风控")

    lines.append("")
    return lines



def build_tomorrow_guide(stocks, bt_data):
    """构建明日操作参考"""
    lines = []
    lines.append("--- 明日操作参考 ---")
    lines.append("")

    # 市场状态判断
    total_stocks = len(stocks)
    top_n = min(10, max(1, total_stocks))
    up_count = sum(1 for s in stocks[:10] if '+' in s['change'])
    avg_change = sum(float(s['change'].replace('%', '').replace('+', '')) for s in stocks[:top_n]) / top_n

    # 尝试从回测数据判断市场
    if bt_data and 'bull_trades' in bt_data:
        bull_pct = bt_data['bull_trades'] / (bt_data['bull_trades'] + bt_data['bear_trades']) * 100
        lines.append(f"【市场环境】近60日牛市占比{bull_pct:.0f}%，10日策略净收益{bt_data.get('net10', 0):+.2f}%，超额HS300 {bt_data.get('excess', 0):+.2f}%")
    else:
        lines.append(f"【市场环境】当前候选池规模（{total_stocks}只）和Top10均涨幅（{avg_change:+.1f}%），市场广度健康，偏多格局")

    lines.append("")

    # 买入建议
    lines.append("【买入参考】")

    # 按评分梯队分类
    tier1 = [s for s in stocks[:10] if int(float(s.get('score', 0))) >= 97]
    tier2 = [s for s in stocks[:10] if 94 <= int(float(s.get('score', 0))) < 97]
    tier3 = [s for s in stocks[:10] if int(float(s.get('score', 0))) < 94]

    if tier1:
        names = '、'.join(s['name'] for s in tier1[:3])
        lines.append(f"第一梯队（>97分）：{names}")
        lines.append(f"  → 优先关注，开盘后若涨幅<2%可考虑直接建仓")

    if tier2:
        names = '、'.join(s['name'] for s in tier2[:3])
        lines.append(f"第二梯队（94-96分）：{names}")
        lines.append(f"  → 作为替补，若第一梯队高开太多（>3%），转投第二梯队")

    lines.append("")

    # 仓位和风控（跟随系统真实配置与小资金模式，见 _risk_control_lines）
    lines.extend(_risk_control_lines())

    # 参考入场价
    lines.append("入场参考：优先在「股价回踩MA5附近」时买入，而非追高")
    lines.append("")

    # 风险提示
    lines.append("【主要风险】")
    # 检测板块集中度
    sector_hint = ""
    power_stocks = [s['name'] for s in stocks[:10] if '电力' in s['name'] or '电' in s['name']]
    if len(power_stocks) >= 3:
        sector_hint = f"电力板块入选{len(power_stocks)}只，集中度过高。若电力板块整体回调，组合将同步回撤。建议跨板块分散，同板块不超过3只。"

    if sector_hint:
        lines.append(sector_hint)
    else:
        lines.append("关注大盘系统性风险：若 ETF 闸门/Alpha Gate 提示连续跑输沪深300，"
                     "优先空仓或改持 510300/510310 ETF，而不是继续加仓选股")

    if bt_data and 'max_consecutive_loss' in bt_data:
        lines.append(f"历史最大连续亏损{bt_data['max_consecutive_loss']}天，做好心理准备，趋势策略靠的是让赢家跑得远")

    return '\n'.join(lines)



def build_personalized_section():
    """构建用户真实持仓的个性化摘要"""
    import pandas as pd
    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(real_file):
        return []

    try:
        df = pd.read_csv(real_file, dtype={'代码': str})
        if '备注' in df.columns:
            df = df[~df['备注'].str.contains('示例', na=False)]
        if len(df) == 0:
            return []
    except Exception:
        return []

    # 找未平仓的真实持仓
    open_positions = []
    for code, group in df.groupby('代码'):
        buys = group[group['方向'] == '买入']
        sells = group[group['方向'] == '卖出']
        total_bought = buys['数量'].sum()
        total_sold = sells['数量'].sum() if len(sells) > 0 else 0
        if total_bought > total_sold:
            last_buy = buys.iloc[-1]
            entry_price = float(last_buy['价格'])
            entry_date = last_buy['日期']
            shares = int(total_bought - total_sold)

            # 获取当前价格
            current_price = None
            stock_files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
            if stock_files:
                try:
                    prices_df = pd.read_csv(stock_files[0], dtype={'代码': str})
                    row = prices_df[prices_df['代码'].astype(str).str.zfill(6) == code.zfill(6)]
                    if len(row) > 0:
                        current_price = float(row.iloc[0]['最新价'])
                except Exception:
                    pass

            if current_price:
                pnl_pct = (current_price / entry_price - 1) * 100
                pnl_amount = (current_price - entry_price) * shares
            else:
                pnl_pct = 0
                pnl_amount = 0

            open_positions.append({
                'code': code.zfill(6),
                'name': last_buy['名称'],
                'entry_price': entry_price,
                'current_price': current_price or entry_price,
                'shares': shares,
                'pnl_pct': pnl_pct,
                'pnl_amount': pnl_amount,
                'entry_date': entry_date,
            })

    if not open_positions:
        return []

    total_pnl = sum(p['pnl_amount'] for p in open_positions)
    total_value = sum(p['current_price'] * p['shares'] for p in open_positions)

    lines = []
    lines.append("═══ 你的持仓 ═══")
    for p in open_positions:
        emoji = '📈' if p['pnl_pct'] > 0 else ('📉' if p['pnl_pct'] < -5 else '📊')
        lines.append(f"{emoji} {p['name']}({p['code']}) {p['current_price']:.2f} | 浮{p['pnl_pct']:+.1f}%")
    lines.append(f"总市值: {total_value:,.0f} | 总浮盈: {total_pnl:+,.0f}")
    lines.append("")
    return lines


# ═══════════════════════════════════════════════════════════
# v5: 完整调仓计划 — 卖出→买入资金闭环
# ═══════════════════════════════════════════════════════════

