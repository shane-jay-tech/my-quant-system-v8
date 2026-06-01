import os, json, glob, re
from datetime import datetime
from .parsers import _parse_exit_advisor_sells, _parse_daily_orders_buys, _get_pick_scores

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')

def _lookup_position_shares(code):
    """查找某只股票的总持仓股数（模拟+真实）"""
    total_shares = 0

    # 1. 模拟持仓
    sim_path = os.path.join(SIM_DIR, 'account_state.json')
    if os.path.exists(sim_path):
        try:
            with open(sim_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            for pos in state.get('positions', []):
                if pos.get('code', '') == code:
                    total_shares += int(pos.get('shares', 0))
        except Exception:
            pass

    # 2. 真实持仓
    real_path = os.path.join(BASE_DIR, 'real_trades.csv')
    if os.path.exists(real_path):
        try:
            import pandas as pd
            df = pd.read_csv(real_path, dtype={'代码': str})
            if '备注' in df.columns:
                df = df[~df['备注'].str.contains('示例', na=False)]
            for c, group in df.groupby('代码'):
                if c.zfill(6) == code.zfill(6):
                    buys = group[group['方向'] == '买入']['数量'].sum()
                    sells = group[group['方向'] == '卖出']['数量'].sum() if '卖出' in group['方向'].values else 0
                    total_shares += int(buys - sells)
        except Exception:
            pass

    return total_shares



def build_adjustment_plan():
    """生成完整调仓计划：卖出→资金计算→买入分配"""
    sells = _parse_exit_advisor_sells()
    buys = _parse_daily_orders_buys()

    if not sells or not buys:
        return None

    # 补充卖出股数
    sells_with_shares = []
    total_proceeds = 0.0
    for s in sells:
        shares = _lookup_position_shares(s['code'])
        if shares <= 0:
            continue
        proceeds = s['current_price'] * shares * 0.998
        s['shares'] = shares
        s['proceeds'] = proceeds
        sells_with_shares.append(s)
        total_proceeds += proceeds

    if not sells_with_shares:
        return None

    # 按选股评分排序买入清单
    scores = _get_pick_scores()
    for b in buys:
        b['score'] = scores.get(b['code'], 50)
    buys_sorted = sorted(buys, key=lambda b: b['score'], reverse=True)

    # 资金分配
    remaining = total_proceeds
    allocated_buys = []
    unallocated_buys = []
    for b in buys_sorted:
        if remaining >= b['amount']:
            allocated_buys.append(b)
            remaining -= b['amount']
        else:
            unallocated_buys.append(b)

    # 构建输出
    lines = []
    lines.append("")
    lines.append("═══ 🔄 今日完整调仓计划 ═══")
    lines.append("")

    # 卖出区块
    lines.append("【卖出】")
    for s in sells_with_shares:
        lines.append(f"  {s['name']}({s['code']}) {s['shares']}股 × {s['current_price']:.2f}元 → 预计回收约{s['proceeds']:,.0f}元")
        lines.append(f"    原因: {s['reason'][:60]}")
    lines.append(f"  预计回收总资金: 约{total_proceeds:,.0f}元 (已预留0.2%滑点+手续费)")
    lines.append("")

    # 买入区块
    lines.append("【买入】（按选股评分从高到低分配）")
    for i, b in enumerate(allocated_buys, 1):
        lines.append(f"  {i}. {b['name']}({b['code']}) {b['shares']}股 × {b['price']:.2f}元 ≈ {b['amount']:,.0f}元 (评分{b['score']}) — 来源: 卖出款")
    lines.append("")

    if unallocated_buys:
        lines.append("【资金不足，可选择性执行】")
        for b in unallocated_buys:
            lines.append(f"  · {b['name']}({b['code']}) {b['shares']}股 ≈ {b['amount']:,.0f}元 (评分{b['score']}) — 需额外资金")
        lines.append("")

    if remaining > 10:
        lines.append(f"【剩余资金】约{remaining:,.0f}元 (留作现金)")
    lines.append("")
    lines.append("💡 操作顺序: 先卖后买，确保资金到位")
    lines.append("")

    return '\n'.join(lines)


