"""
出场顾问 v1 — 每日检查所有持仓，生成卖出/持有建议

出场条件（5级）：
  🚨 止损: 现价 ≤ 止损价 → 立即卖出
  ✅ 止盈: 现价 ≥ 止盈价 → 获利离场
  ⏰ 到期: 持有天数 ≥ 最大持有 → 到期离场
  ⚠️ 死叉: MA5下穿MA20 → 趋势转弱
  📉 预警: 现价 < MA20 或 RSI < 35 → 关注风险

输入: sim账户持仓 + 真实交易持仓 + 最新行情 + 历史K线
输出: results/exit_advisor_YYYYMMDD.md
"""
import os, sys, json, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION, get as cfg_get

# 保留模块级常量以兼容旧测试/旧 import，但默认值跟随 core.config sim.*。
STOP_LOSS_PCT = cfg_get('sim.stop_loss_pct', -0.08)
TAKE_PROFIT_PCT = cfg_get('sim.take_profit_pct', 0.20)
MAX_HOLD_DAYS = cfg_get('sim.max_hold_days', 10)


def _risk_defaults():
    """sim.* 单一真相源的风控默认值（每次调用重读，配置热更新生效）。"""
    return {
        'stop_loss_pct': float(cfg_get('sim.stop_loss_pct', STOP_LOSS_PCT)),
        'take_profit_pct': float(cfg_get('sim.take_profit_pct', TAKE_PROFIT_PCT)),
        'max_hold_days': int(cfg_get('sim.max_hold_days', MAX_HOLD_DAYS)),
    }


def effective_risk_config(risk_config=None):
    """与 sim_trade.load_risk_config 的 alert_only 语义对齐。

    - alert_only=True：stop/take 强制用 sim.*（反馈循环不覆盖），仅 max_hold_days 可由 risk_config 接管。
    - alert_only=False / 缺失：risk_config 覆盖 stop/take/hold，缺失项回退 sim.*。
    """
    cfg = dict(risk_config or {})
    defaults = _risk_defaults()
    alert_only = cfg.get('alert_only', False) is True
    if alert_only:
        cfg['stop_loss_pct'] = defaults['stop_loss_pct']
        cfg['take_profit_pct'] = defaults['take_profit_pct']
    else:
        for key in ('stop_loss_pct', 'take_profit_pct', 'max_hold_days'):
            if key not in cfg or cfg[key] is None:
                cfg[key] = defaults[key]
    if 'max_hold_days' not in cfg or cfg['max_hold_days'] is None:
        cfg['max_hold_days'] = defaults['max_hold_days']
    return cfg


def load_risk_config():
    path = os.path.join(DATA_DIR, 'risk_config.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def load_sim_positions():
    """加载模拟账户持仓"""
    path = os.path.join(SIM_DIR, 'account_state.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        state = json.load(f)
    return state.get('positions', [])


def load_real_positions():
    """加载真实交易中未卖出的持仓（FIFO 配对，剩余仓为加权均价）。

    v8.7+ Round 2: 改用 FIFO 加权均价 + 最早未平仓买入日期，和
    strategy_feedback.pair_real_trades_fifo 的语义对齐。
    Why: 之前用 last_buy 当 entry_price，多次买同一只票时止损线/到期判定都基于
    最近一次买入价，与 FIFO 实际持仓成本不一致。"满 N 个交易日"也会从最近一次
    买入算，导致旧仓永远不到期。
    """
    path = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, dtype={'代码': str})
    if '备注' in df.columns:
        df = df[~df['备注'].str.contains('示例', na=False)]
    df['日期'] = pd.to_datetime(df.get('日期', pd.NaT), errors='coerce')
    # 同日买卖：买入先入队
    df['_dir_rank'] = df['方向'].map({'买入': 0, '卖出': 1}).fillna(2).astype(int)
    df = df.sort_values(['代码', '日期', '_dir_rank']).drop(columns=['_dir_rank'])

    positions = []
    for code, group in df.groupby('代码'):
        buy_queue = []  # {price, shares_left, date, name}
        for _, row in group.iterrows():
            direction = str(row.get('方向', ''))
            try:
                price = float(row['价格'])
                shares = int(row['数量'])
            except (TypeError, ValueError, KeyError):
                continue
            if price <= 0 or shares <= 0:
                continue
            if direction == '买入':
                buy_queue.append({
                    'price': price, 'shares_left': shares,
                    'date': row.get('日期'), 'name': str(row.get('名称', '')),
                })
            elif direction == '卖出':
                remaining = shares
                while remaining > 0 and buy_queue:
                    head = buy_queue[0]
                    take = min(remaining, head['shares_left'])
                    head['shares_left'] -= take
                    remaining -= take
                    if head['shares_left'] <= 0:
                        buy_queue.pop(0)
        if not buy_queue:
            continue
        # FIFO 剩余 → 加权均价 + 最早未平仓买入日期
        total_shares = sum(b['shares_left'] for b in buy_queue)
        if total_shares <= 0:
            continue
        weighted_price = sum(b['price'] * b['shares_left'] for b in buy_queue) / total_shares
        earliest = min((b['date'] for b in buy_queue if pd.notna(b['date'])),
                       default=buy_queue[0]['date'])
        name = buy_queue[0]['name']
        positions.append({
            'code': code.zfill(6),
            'name': name,
            'entry_price': round(weighted_price, 4),
            'entry_date': earliest.strftime('%Y-%m-%d') if hasattr(earliest, 'strftime') else earliest,
            'shares': int(total_shares),
            'stop_loss': round(weighted_price * (1 + STOP_LOSS_PCT), 2),
            'take_profit': round(weighted_price * (1 + TAKE_PROFIT_PCT), 2),
            'source': 'real',
        })
    return positions


def load_history_df():
    path = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, dtype={'代码': str})
    df['日期'] = pd.to_datetime(df['日期'])
    return df


def load_latest_prices():
    """加载最新股价，返回{code: {price, name}}"""
    stocks = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not stocks:
        return {}
    df = pd.read_csv(stocks[0], dtype={'代码': str})
    prices = {}
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        prices[code] = {
            'price': float(row['最新价']),
            'name': str(row['名称']),
            'change_pct': float(row['涨跌幅']) if '涨跌幅' in row else 0,
        }
    return prices


def calc_ma(code, history_df, period, ref_date=None):
    """计算股票的MA值"""
    stock = history_df[history_df['代码'] == code].copy()
    if len(stock) < period:
        return None
    stock = stock.sort_values('日期')
    if ref_date:
        stock = stock[stock['日期'] <= ref_date]
    return float(stock['收盘'].tail(period).mean())


def calc_rsi(code, history_df, period=14):
    """计算RSI(14)"""
    stock = history_df[history_df['代码'] == code].copy()
    if len(stock) < period + 2:
        return None
    stock = stock.sort_values('日期')
    closes = stock['收盘']
    deltas = closes.diff()
    gains = deltas.clip(lower=0)
    losses = -deltas.clip(upper=0)
    avg_gain = gains.rolling(period).mean().iloc[-1]
    avg_loss = losses.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def analyze_position(pos, prices, history_df, risk_config):
    """分析单个持仓，返回出场建议"""
    rules = effective_risk_config(risk_config)
    code = pos['code']
    entry_price = pos['entry_price']
    entry_date = str(pos.get('entry_date', ''))
    shares = pos.get('shares', 0)
    stop_loss = pos.get('stop_loss', round(entry_price * (1 + float(rules['stop_loss_pct'])), 2))
    take_profit = pos.get('take_profit', round(entry_price * (1 + float(rules['take_profit_pct'])), 2))

    max_hold = int(rules['max_hold_days'])
    stop_pct = rules['stop_loss_pct']

    result = {
        'code': code,
        'name': pos.get('name', ''),
        'entry_price': entry_price,
        'entry_date': entry_date,
        'shares': shares,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'source': pos.get('source', 'sim'),
        'signals': [],
        'action': 'hold',
        'action_label': '持有',
    }

    # 当前价格
    if code not in prices:
        result['action'] = 'unknown'
        result['action_label'] = '无行情数据'
        return result

    current_price = prices[code]['price']
    pnl_pct = (current_price / entry_price - 1) * 100
    result['current_price'] = current_price
    result['pnl_pct'] = round(pnl_pct, 2)

    # 持有天数（v8.7+: 交易日，不算周末/节假日）
    # Why: 之前用 (now - entry).days = 日历日，碰到周末/国庆会让"满 N 天到期"提前触发平仓
    if entry_date:
        try:
            entry_dt = pd.to_datetime(entry_date)
            from utils.calendar import count_trading_days
            hold_days = max(0, count_trading_days(entry_dt, datetime.now()) - 1)
        except Exception:
            hold_days = 0
    else:
        hold_days = 0
    result['hold_days'] = hold_days

    # --- 出场条件检查（优先级从高到低）---
    signals = []

    # 1. 🚨 止损
    if current_price <= stop_loss:
        signals.append({'level': 'urgent', 'icon': '🚨', 'reason': f'止损触发：现价{current_price}≤止损{stop_loss}（{pnl_pct:+.1f}%）'})
        result['action'] = 'sell_stop'
        result['action_label'] = '🚨 立即止损'

    # 2. ✅ 止盈
    elif current_price >= take_profit:
        signals.append({'level': 'good', 'icon': '✅', 'reason': f'止盈触发：现价{current_price}≥止盈{take_profit}（{pnl_pct:+.1f}%）'})
        result['action'] = 'sell_profit'
        result['action_label'] = '✅ 止盈离场'

    # 3. ⏰ 到期
    elif hold_days >= max_hold:
        signals.append({'level': 'warning', 'icon': '⏰', 'reason': f'持有到期：{hold_days}日≥{max_hold}日上限'})
        result['action'] = 'sell_expiry'
        result['action_label'] = '⏰ 到期离场'

    # 4. ⚠️ 死叉 (MA5 < MA20)
    ma5 = calc_ma(code, history_df, 5) if history_df is not None else None
    ma20 = calc_ma(code, history_df, 20) if history_df is not None else None
    result['ma5'] = round(ma5, 2) if ma5 else None
    result['ma20'] = round(ma20, 2) if ma20 else None

    if ma5 and ma20 and ma5 < ma20:
        signals.append({'level': 'warning', 'icon': '⚠️', 'reason': f'MA死叉：MA5({ma5:.2f})<MA20({ma20:.2f})，趋势转弱'})
        if result['action'] == 'hold':
            result['action'] = 'warn_deadcross'
            result['action_label'] = '⚠️ 死叉预警'

    # 5. 📉 RSI弱势
    rsi = calc_rsi(code, history_df) if history_df is not None else None
    result['rsi'] = round(rsi, 1) if rsi else None

    if current_price < (ma20 or current_price) and rsi and rsi < 35:
        signals.append({'level': 'info', 'icon': '📉', 'reason': f'弱势：价格<MA20且RSI({rsi:.1f})<35'})
        if result['action'] == 'hold':
            result['action'] = 'warn_weak'
            result['action_label'] = '📉 关注风险'

    # 6. 📊 正常持有
    if not signals:
        signals.append({'level': 'ok', 'icon': '📊', 'reason': f'正常：浮盈{pnl_pct:+.1f}%，持有{hold_days}日'})

    result['signals'] = signals
    return result


def generate_report(analyses):
    """生成出场建议报告"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')

    # 统计
    sell_count = sum(1 for a in analyses if a['action'].startswith('sell'))
    warn_count = sum(1 for a in analyses if a['action'].startswith('warn'))
    hold_count = sum(1 for a in analyses if a['action'] == 'hold')
    total_value = sum(a.get('current_price', a['entry_price']) * a['shares'] for a in analyses)
    total_pnl = sum(
        (a.get('current_price', a['entry_price']) - a['entry_price']) * a['shares']
        for a in analyses
    )

    lines = [
        f"# 出场顾问报告 — {datetime.now().strftime('%Y-%m-%d')}",
        f"",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 检查持仓：{len(analyses)}只 | 持仓市值：CNY{total_value:,.0f} | 浮动盈亏：CNY{total_pnl:+,.0f}",
        f"> 卖出信号：{sell_count}只 | 预警：{warn_count}只 | 正常持有：{hold_count}只",
        f"",
    ]

    # 需要卖出的排最前面
    priority_order = {'sell_stop': 0, 'sell_profit': 1, 'sell_expiry': 2, 'warn_deadcross': 3, 'warn_weak': 4, 'hold': 5, 'unknown': 6}
    analyses_sorted = sorted(analyses, key=lambda x: priority_order.get(x['action'], 99))

    if sell_count > 0:
        lines.extend([
            f"## 🚨 需要操作 ({sell_count}只)",
            f"",
            f"| 代码 | 名称 | 入场价 | 现价 | 盈亏 | 持有 | 建议 | 原因 |",
            f"|------|------|--------|------|------|------|------|------|",
        ])
        for a in analyses_sorted:
            if a['action'].startswith('sell'):
                sig = a['signals'][0]
                lines.append(
                    f"| {a['code']} | {a['name']} | {a['entry_price']} | {a.get('current_price','?')} | "
                    f"{a.get('pnl_pct',0):+.1f}% | {a.get('hold_days',0)}日 | {a['action_label']} | {sig['reason']} |"
                )
        lines.append("")

    if warn_count > 0:
        lines.extend([
            f"## ⚠️ 需要关注 ({warn_count}只)",
            f"",
            f"| 代码 | 名称 | 入场价 | 现价 | 盈亏 | 持有 | 指标 | 建议 |",
            f"|------|------|--------|------|------|------|------|------|",
        ])
        for a in analyses_sorted:
            if a['action'].startswith('warn'):
                ma_info = f"MA5:{a.get('ma5','?')}/MA20:{a.get('ma20','?')}" if a.get('ma5') else ''
                rsi_info = f"RSI:{a.get('rsi','?')}" if a.get('rsi') else ''
                indicators = ' '.join([ma_info, rsi_info]).strip()
                lines.append(
                    f"| {a['code']} | {a['name']} | {a['entry_price']} | {a.get('current_price','?')} | "
                    f"{a.get('pnl_pct',0):+.1f}% | {a.get('hold_days',0)}日 | {indicators} | {a['action_label']} |"
                )
        lines.append("")

    if hold_count > 0:
        lines.extend([
            f"## 📊 正常持有 ({hold_count}只)",
            f"",
            f"| 代码 | 名称 | 入场价 | 现价 | 盈亏 | 持有 | 来源 |",
            f"|------|------|--------|------|------|------|------|",
        ])
        for a in analyses_sorted:
            if a['action'] == 'hold':
                src = '真实' if a['source'] == 'real' else '模拟'
                lines.append(
                    f"| {a['code']} | {a['name']} | {a['entry_price']} | {a.get('current_price','?')} | "
                    f"{a.get('pnl_pct',0):+.1f}% | {a.get('hold_days',0)}日 | {src} |"
                )
        lines.append("")

    rules = _risk_defaults()
    stop_pct = float(rules['stop_loss_pct'])
    take_pct = float(rules['take_profit_pct'])
    hold_days = int(rules['max_hold_days'])

    lines.extend([
        f"## 出场规则",
        f"",
        f"| 级别 | 条件 | 操作 |",
        f"|------|------|------|",
        f"| 🚨 止损 | 现价≤止损价（{stop_pct:.0%}） | 立即卖出 |",
        f"| ✅ 止盈 | 现价≥止盈价（{take_pct:+.0%}） | 获利离场 |",
        f"| ⏰ 到期 | 持有≥{hold_days}个交易日 | 到期离场 |",
        f"| ⚠️ 死叉 | MA5<MA20 | 趋势转弱，建议减仓 |",
        f"| 📉 预警 | 价格<MA20 且 RSI<35 | 关注风险 |",
        f"",
        f"---",
        f"*报告由 exit_advisor.py v{SYSTEM_VERSION} 自动生成*",
    ])

    report_path = os.path.join(RESULTS_DIR, f'exit_advisor_{today_str}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return report_path


def build_bark_exit_summary(analyses):
    """生成Bark推送用的卖出摘要"""
    sell_items = [a for a in analyses if a['action'].startswith('sell')]
    warn_items = [a for a in analyses if a['action'].startswith('warn')]

    if not sell_items and not warn_items:
        return None, None

    title_parts = []
    if sell_items:
        title_parts.append(f"{len(sell_items)}只卖出")
    if warn_items:
        title_parts.append(f"{len(warn_items)}只预警")
    title = ' | '.join(title_parts)

    lines = [f"# 持仓检查 — {datetime.now().strftime('%m-%d')}", ""]
    if sell_items:
        lines.append("## 🚨 建议卖出")
        for a in sell_items:
            lines.append(f"- {a['code']} {a['name']}: {a['action_label']} | {a.get('pnl_pct',0):+.1f}% | 持{a.get('hold_days',0)}日")
        lines.append("")
    if warn_items:
        lines.append("## ⚠️ 关注预警")
        for a in warn_items:
            lines.append(f"- {a['code']} {a['name']}: {a['action_label']} | {a.get('pnl_pct',0):+.1f}%")

    return title, '\n'.join(lines)


def main():
    rules = _risk_defaults()
    print(f"{'='*50}")
    print(f"  Exit Advisor v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Exit rules: stop{float(rules['stop_loss_pct']):.0%} | "
          f"profit{float(rules['take_profit_pct']):+.0%} | "
          f"expiry {int(rules['max_hold_days'])}d | deadcross | RSI<35")
    print(f"{'='*50}")

    # 1. 加载数据
    risk = load_risk_config()
    sim_positions = load_sim_positions()
    real_positions = load_real_positions()
    prices = load_latest_prices()
    history_df = load_history_df()

    print(f"[EXIT] Sim positions: {len(sim_positions)}, Real positions: {len(real_positions)}")
    print(f"[EXIT] Prices loaded: {len(prices)}, History: {len(history_df) if history_df is not None else 0} rows")

    # 2. 合并所有持仓（去重，真实优先）
    all_positions = {}
    for p in sim_positions:
        p['source'] = 'sim'
        all_positions[p['code']] = p
    for p in real_positions:
        p['source'] = 'real'
        all_positions[p['code']] = p  # 真实覆盖模拟

    if not all_positions:
        print("[EXIT] No positions to analyze")
        return 0

    # 3. 逐只分析
    analyses = []
    for code, pos in all_positions.items():
        analysis = analyze_position(pos, prices, history_df, risk)
        analyses.append(analysis)

    # 4. 统计并输出
    sell_count = sum(1 for a in analyses if a['action'].startswith('sell'))
    warn_count = sum(1 for a in analyses if a['action'].startswith('warn'))

    print(f"\n[EXIT] Results: {sell_count} sell, {warn_count} warn, {len(analyses)-sell_count-warn_count} hold")
    for a in analyses:
        if a['action'] != 'hold':
            label = a['action_label'].encode('ascii', errors='replace').decode('ascii')
            print(f"  {label}: {a['code']} {a['name']} ({a.get('pnl_pct',0):+.1f}%)")

    # 5. 生成报告
    report_path = generate_report(analyses)
    print(f"\n[EXIT] Report: {report_path}")

    # 6. 保存JSON供Bark使用
    json_path = os.path.join(RESULTS_DIR, f'exit_advisor_{datetime.now().strftime("%Y%m%d")}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(analyses, f, ensure_ascii=False, indent=2, default=str)

    return 0


if __name__ == '__main__':
    sys.exit(main())
