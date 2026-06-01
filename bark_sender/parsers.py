import os, glob, re, json
from datetime import datetime
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')

def find_latest_report():
    pattern = os.path.join(RESULTS_DIR, 'pick_*.md')
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


def parse_report_full(filepath):
    """从报告中提取完整信息"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', content)
    pick_date = date_match.group(1) if date_match else '未知'

    # 提取股票行（含MA5/MA20/RSI/量比/市值）
    stocks = []
    for line in content.split('\n'):
        if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            # Auto-detect format: with/without 板块 column
            try:
                float(parts[3])
                has_sector = False
            except ValueError:
                has_sector = True
            if has_sector and len(parts) >= 12:
                stocks.append({
                    'code': parts[1], 'name': parts[2], 'price': parts[4],
                    'change': parts[5], 'ma5': parts[6], 'ma20': parts[7],
                    'rsi': parts[8], 'vol_ratio': parts[9], 'mcap': parts[10],
                    'score': parts[11], 'risk': parts[12] if len(parts) > 12 else '',
                    'reason': parts[13] if len(parts) > 13 else '',
                })
            elif not has_sector and len(parts) >= 11:
                stocks.append({
                    'code': parts[1], 'name': parts[2], 'price': parts[3],
                    'change': parts[4], 'ma5': parts[5], 'ma20': parts[6],
                    'rsi': parts[7], 'vol_ratio': parts[8], 'mcap': parts[9],
                    'score': parts[10], 'risk': parts[11] if len(parts) > 11 else '',
                    'reason': parts[12] if len(parts) > 12 else '',
                })

    return pick_date, stocks


def parse_honest_eval():
    """读取诚实评估数据"""
    path = os.path.join(RESULTS_DIR, 'honest_evaluation.md')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    data = {}
    # 提取市场状态数据
    bull_match = re.search(r'牛市\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([+-][\d.]+)%', content)
    bear_match = re.search(r'熊市/震荡\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([+-][\d.]+)%', content)
    excess_match = re.search(r'超额收益\*?\*?\s*:\s*([+-][\d.]+)%', content)
    max_loss_match = re.search(r'最大连续亏损\s*:\s*(\d+)', content)

    if bull_match:
        data['bull_trades'] = int(bull_match.group(1))
        data['bull_wr'] = float(bull_match.group(2))
        data['bull_net'] = float(bull_match.group(3))
    if bear_match:
        data['bear_trades'] = int(bear_match.group(1))
        data['bear_wr'] = float(bear_match.group(2))
        data['bear_net'] = float(bear_match.group(3))
    if excess_match:
        data['excess'] = float(excess_match.group(1))
    if max_loss_match:
        data['max_consecutive_loss'] = int(max_loss_match.group(1))

    # 10日核心指标: | 10日 | 202 | 54.5% | +4.99% | +4.79% | 10.9% |
    net10 = re.search(r'10日\s*\|\s*\d+\s*\|\s*([\d.]+)%\s*\|\s*[+\d.%]+\s*\|\s*([+-][\d.]+)%', content)
    if net10:
        data['wr10'] = float(net10.group(1))
        data['net10'] = float(net10.group(2))

    return data



def parse_performance_tracking():
    """读取最新绩效追踪，用于回顾上次推荐表现"""
    path = os.path.join(RESULTS_DIR, 'performance_tracking.md')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取最近一个选股日期的表现
    prev = {}
    date_match = re.search(r'\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d+)\s*\|\s*([+-][\d.]+)\s*\|\s*([\d.]+)', content)
    if date_match:
        prev['date'] = date_match.group(1)
        prev['count'] = int(date_match.group(2))
        prev['avg_ret'] = float(date_match.group(3))
        prev['win_rate'] = float(date_match.group(4))

    # 提取总体统计
    overall = {}
    wr_match = re.search(r'Overall:\s*([\d.]+)%\s*win rate,\s*([+-][\d.]+)%', content)
    if wr_match:
        overall['win_rate'] = float(wr_match.group(1))
        overall['avg_ret'] = float(wr_match.group(2))

    return {'previous': prev, 'overall': overall}



def _parse_exit_advisor_sells():
    """从今日 exit_advisor 报告中提取需要卖出的股票列表（仅止损/止盈/到期）。

    v8.7+ Round 2: 仅读今天的文件，缺失时返回空。
    Why: rebalancer 用 sells 决定"卖几只 → 回收资金 → 再买几只"。如果用昨天的 sells
    会把已卖过的票再当未卖出处理，造成重复推送 / 资金错算。
    """
    today = datetime.now().strftime('%Y%m%d')
    today_path = os.path.join(RESULTS_DIR, f'exit_advisor_{today}.md')
    if not os.path.exists(today_path):
        return []
    with open(today_path, 'r', encoding='utf-8') as f:
        content = f.read()

    sells = []
    in_sell_section = False
    for line in content.split('\n'):
        if line.startswith('## 🚨 需要操作'):
            in_sell_section = True
            continue
        elif in_sell_section and (line.startswith('## ') or line.startswith('## 📊')):
            in_sell_section = False
            continue

        if in_sell_section and re.match(r'\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 8:
                code = parts[0]
                name = parts[1]
                entry_price = float(parts[2])
                current_price = float(parts[3])
                pnl_str = parts[4]
                action = parts[6]
                reason = parts[7] if len(parts) > 7 else ''
                sells.append({
                    'code': code, 'name': name,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'pnl_str': pnl_str, 'action': action, 'reason': reason,
                })
    return sells


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


def _parse_daily_orders_buys():
    """从最新daily_orders文件中提取买入清单"""
    order_files = sorted(
        [f for f in os.listdir(ORDERS_DIR) if f.startswith('daily_orders_') and f.endswith('.md')],
        reverse=True
    )
    if not order_files:
        return []

    with open(os.path.join(ORDERS_DIR, order_files[0]), 'r', encoding='utf-8') as f:
        content = f.read()

    buys = []
    in_order_section = False
    for line in content.split('\n'):
        if line.startswith('## 今日订单'):
            in_order_section = True
            continue
        elif in_order_section and line.startswith('## '):
            in_order_section = False
            continue

        if in_order_section and re.match(r'\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 7 and parts[2] == '买入':
                code = parts[0]
                name = parts[1]
                price = float(parts[3].replace(',', ''))
                shares = int(parts[4].replace(',', ''))
                amount = float(parts[5].replace(',', ''))
                buys.append({
                    'code': code, 'name': name,
                    'price': price, 'shares': shares, 'amount': amount,
                })
    return buys



def _get_pick_scores():
    """从最新pick报告中获取选股评分，用于调仓优先级排序"""
    pick_files = sorted(
        [f for f in os.listdir(RESULTS_DIR) if f.startswith('pick_') and f.endswith('.md')],
        reverse=True
    )
    if not pick_files:
        return {}

    with open(os.path.join(RESULTS_DIR, pick_files[0]), 'r', encoding='utf-8') as f:
        content = f.read()

    scores = {}
    for line in content.split('\n'):
        if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) < 10:
                continue
            code = parts[1]
            # Auto-detect: if parts[3] is numeric, no 板块 column; otherwise 板块 present
            try:
                float(parts[3])
                score_idx = 10
            except ValueError:
                score_idx = 11
            try:
                score = int(float(parts[score_idx])) if score_idx < len(parts) else 50
            except (ValueError, IndexError):
                score = 50
            scores[code] = score
    return scores


