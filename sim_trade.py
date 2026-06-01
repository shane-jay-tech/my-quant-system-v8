"""
模拟交易引擎 v1 — 虚拟账户 + 每日持仓追踪 + 自动卖出 + 权益曲线

功能：
1. 虚拟资金账户（初始10万），支持买入/卖出
2. 每日读取订单并执行模拟成交
3. 自动检查出场条件（止损/止盈/持有天数到期）
4. 记录每笔交易和每日权益
5. 生成权益曲线和交易统计
"""
import os, sys, json, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')

# v7.5: 统一配置中心（保留本地默认值作为 fallback）
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION

# v8 Phase 1.2: 成本常量从 cost_model 单一真相源读取
# Why: 历史上 sim_trade 用 0.00025 而 enhanced_backtest 用 0.0003，
# 同一笔交易两边算出不同成本，用户决策被误导。统一后两边同源。
from cost_model import (
    COMMISSION_RATE as _COMM_RATE,
    COMMISSION_MIN as _COMM_MIN,
    STAMP_TAX_RATE as _STAMP_RATE,
    order_passes_cost_gate,
)

_FALLBACK_CAPITAL = cfg_get('sim.initial_capital', 2400)
_USE_REAL_CAPITAL = cfg_get('sim.use_real_capital', True)
REAL_TRADES_FILE = os.path.join(BASE_DIR, 'real_trades.csv')


def _cost_gate_max_pct():
    """防线二读取配置：与 position_sizer 同一阈值，逐单实时判断。"""
    try:
        return float(cfg_get('cost.order_gate_max_pct', 0.025))
    except Exception:
        return 0.025


def _order_cost_gate_check(code, amount, mcap=0):
    """返回 (ok, breakdown)。旧/手工订单缺 mcap 时按小盘滑点最保守。"""
    return order_passes_cost_gate(amount, mcap, _cost_gate_max_pct())


def get_real_invested_capital():
    """读 real_trades.csv 算真实账户净投入 — 买入(成交额+手续费) - 卖出(成交额-手续费)。

    v8.7（2026-05-28）：sim 账户预算联动真实交易。
    real_trades.csv 不存在/空表/列缺失时返回 None，调用方走 _FALLBACK_CAPITAL。
    """
    if not os.path.exists(REAL_TRADES_FILE):
        return None
    try:
        df = pd.read_csv(REAL_TRADES_FILE, dtype={'代码': str})
    except Exception:
        return None
    if len(df) == 0 or '方向' not in df.columns or '成交额' not in df.columns:
        return None
    fee = pd.to_numeric(df.get('手续费', 0), errors='coerce').fillna(0)
    amount = pd.to_numeric(df['成交额'], errors='coerce').fillna(0)
    direction = df['方向'].astype(str)
    # 买入：从口袋掏出 amount + fee；卖出：放回 amount - fee
    cash_out = ((direction == '买入') * (amount + fee)).sum()
    cash_in = ((direction == '卖出') * (amount - fee)).sum()
    net_invested = float(cash_out - cash_in)
    if net_invested <= 0:
        return None
    return round(net_invested, 2)


def get_manual_capital():
    """读取用户手填的真实总资金（config: sim.manual_capital）。

    v8.x（2026-06-04）：用户在仪表盘手填真实股市总资金，作为模拟账户基线的
    最高优先级来源。未设置 / 非法 / <=0 时返回 None，调用方继续走自动推算。
    cfg_get 会在配置文件 mtime 变化时自动 reload，所以 UI 改完即时生效。
    """
    val = cfg_get('sim.manual_capital', None)
    try:
        if val is not None and float(val) > 0:
            return round(float(val), 2)
    except (TypeError, ValueError):
        pass
    return None


def resolve_initial_capital():
    """决定 sim 账户起步资金。

    优先级：① 用户手填 manual_capital > ② real_trades.csv 净投入 > ③ config fallback。
    """
    manual = get_manual_capital()
    if manual is not None:
        return manual
    if _USE_REAL_CAPITAL:
        real = get_real_invested_capital()
        if real is not None:
            return real
    return _FALLBACK_CAPITAL


# 模块级常量保留向后兼容（旧测试/旧报告引用），但 init_account/report 用 state['initial_capital']
INITIAL_CAPITAL = resolve_initial_capital()
STOP_LOSS_PCT = cfg_get('sim.stop_loss_pct', -0.08)
TAKE_PROFIT_PCT = cfg_get('sim.take_profit_pct', 0.20)
MAX_HOLD_DAYS = cfg_get('sim.max_hold_days', 10)
SLIPPAGE = cfg_get('sim.slippage', 0.001)  # 0.1% 买入滑点
DAILY_LIMIT_PCT = cfg_get('sim.daily_limit_pct', 9.8)  # A股涨停阈值

STATE_FILE = os.path.join(SIM_DIR, 'account_state.json')
TRADES_FILE = os.path.join(SIM_DIR, 'trade_history.csv')
EQUITY_FILE = os.path.join(SIM_DIR, 'equity_curve.csv')
RISK_CONFIG_FILE = os.path.join(DATA_DIR, 'risk_config.json')


def get_limit_pct(code):
    """按股票代码前缀返回涨停阈值（用于买入过滤）"""
    if code.startswith('688') or code.startswith('300') or code.startswith('301'):
        return 19.8
    if code.startswith('8') or code.startswith('9'):
        return 29.8
    return DAILY_LIMIT_PCT


# v8.7: 抽取到 utils/calendar.py，保留这里作为别名以兼容老 import
from utils.calendar import get_last_trading_day  # noqa: E402,F401


def is_today_trading_day():
    """判断今天是否为交易日（基于是否存在当日 stock 数据文件）"""
    today_file = os.path.join(DATA_DIR, f"stock_{datetime.now().strftime('%Y%m%d')}.csv")
    return os.path.exists(today_file)


def load_risk_config():
    """加载策略反馈系统生成的风控参数

    v8.6: 支持 alert-only 模式 — 当 risk_config.json 里 alert_only=True 时，
    跳过 stop_loss_pct/take_profit_pct 的覆盖（保持代码默认 -0.08 / 0.20），
    仅读 max_hold_days。这是反向反馈循环修复的最后一环。
    """
    if not os.path.exists(RISK_CONFIG_FILE):
        return {}

    with open(RISK_CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)

    alert_only = config.get('alert_only', False) is True
    if alert_only:
        print('[SIM] Risk config alert-only mode, skipping stop/take adjustments')
        config_items = [('max_hold_days', 'MAX_HOLD_DAYS')]
    else:
        config_items = [
            ('stop_loss_pct', 'STOP_LOSS_PCT'),
            ('take_profit_pct', 'TAKE_PROFIT_PCT'),
            ('max_hold_days', 'MAX_HOLD_DAYS'),
        ]

    applied = {}
    for key, var in config_items:
        if key in config:
            applied[var] = config[key]

    if applied:
        print(f"[SIM] Risk config loaded: {applied}")
    return applied


def init_account():
    """初始化或加载账户状态。

    v8.7（2026-05-28）：sim 账户预算联动真实交易。
    - 第一次创建：起步资金 = resolve_initial_capital()（真实净投入或 fallback）
    - 每次启动：检测 real_trades.csv 净投入 vs state['initial_capital'] 的 delta，
      把 delta 加到 cash（追加投入跟同步，撤资也跟同步），并更新 initial_capital。
    """
    os.makedirs(SIM_DIR, exist_ok=True)
    starting_capital = resolve_initial_capital()

    defaults = {
        'cash': starting_capital,
        'total_invested': 0,
        'equity': starting_capital,
        'initial_capital': starting_capital,  # v8.7 基线：用作累计收益率分母
        'positions': [],       # [{code, name, shares, entry_price, entry_date, stop_loss, take_profit}]
        'created': datetime.now().strftime('%Y-%m-%d'),
        'total_trades': 0,
        'winning_trades': 0,
        'total_pnl': 0.0,
        'total_commission': 0.0,
        'total_stamp_tax': 0.0,
        'total_trade_volume': 0.0,
    }

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        # 老 state 字段回填（5/15 创建时还没有 commission/stamp_tax/trade_volume 三字段）
        # 注意：initial_capital 单独处理 — 老 state 缺这个字段时，
        # 不能直接拿当前 starting_capital 兜底，否则 delta sync 永远 0。
        # 应当先按 _FALLBACK_CAPITAL 假设（旧版基线 = config 默认 1200），
        # 再让 delta sync 把基线追到真实净投入，cash 同步增减。
        backfilled = []
        for k, v in defaults.items():
            if k == 'initial_capital':
                continue
            if k not in state:
                state[k] = v
                backfilled.append(k)
        if 'initial_capital' not in state:
            state['initial_capital'] = _FALLBACK_CAPITAL
            backfilled.append('initial_capital')
        if backfilled:
            print(f"[SIM] Backfilled missing state fields: {backfilled}")

        # v8.x: 用户手填本金时，manual_capital 是唯一真相源 —
        # 锁定基线为 manual，禁用 real_trades delta-sync（避免双源互相覆盖）。
        # 基线的「现金一致性」由 UI「保存并重置」显式重建，这里只对齐基线、不动 cash。
        manual = get_manual_capital()
        if manual is not None:
            if abs(state.get('initial_capital', 0) - manual) >= 0.01:
                print(f"[SIM] Manual capital baseline aligned: "
                      f"{state.get('initial_capital', 0):.2f} -> {manual:.2f}")
                state['initial_capital'] = manual
        # v8.7: 真实交易资金联动 — delta sync（仅当用户未手填本金时生效）
        elif _USE_REAL_CAPITAL:
            real_now = get_real_invested_capital()
            if real_now is not None:
                old_baseline = state['initial_capital']
                delta = round(real_now - old_baseline, 2)
                if abs(delta) >= 0.01:
                    new_cash = state['cash'] + delta
                    if new_cash < 0:
                        print(f"[SIM] Real capital delta {delta:+.2f} would drive cash negative "
                              f"(cash={state['cash']:.2f}); clamping to 0")
                        new_cash = 0
                    state['cash'] = round(new_cash, 2)
                    state['initial_capital'] = real_now
                    print(f"[SIM] Real capital sync: baseline {old_baseline:.2f} -> {real_now:.2f} "
                          f"(delta {delta:+.2f}); cash adjusted")

        print(f"[SIM] Loaded account: cash={state['cash']:.0f}, equity={state.get('equity', 0):.0f}, "
              f"baseline={state.get('initial_capital', _FALLBACK_CAPITAL):.0f}")
        return state

    state = defaults
    save_state(state)
    print(f"[SIM] New account created: capital={starting_capital:,.0f}")
    return state


# v8.7: 抽到 utils/file_io.py，保留别名以兼容旧调用
from utils.file_io import atomic_write_json as _atomic_write_json  # noqa: E402,F401


def save_state(state):
    """保存账户状态到文件（v8.6: atomic write）"""
    os.makedirs(SIM_DIR, exist_ok=True)
    state['_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _atomic_write_json(STATE_FILE, state)


def load_daily_orders():
    """加载最新的订单文件"""
    if not os.path.exists(ORDERS_DIR):
        return []

    files = sorted(glob.glob(os.path.join(ORDERS_DIR, 'daily_orders_*.json')), reverse=True)
    if not files:
        return []

    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data.get('订单', [])


def load_price_data():
    """加载最新股价数据"""
    stocks = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not stocks:
        return {}

    df = pd.read_csv(stocks[0], dtype={'代码': str})
    # 标准化列名
    col_map = {'最新价': 'price', '名称': 'name', '涨跌幅': 'change'}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    prices = {}
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        prices[code] = {
            'price': float(row.get('price', row.get('最新价', 0))),
            'name': str(row.get('name', row.get('名称', ''))),
            'change_pct': float(row.get('change', row.get('涨跌幅', 0))),
        }
    return prices


def execute_buy_orders(state, orders, prices, stop_loss_pct=None, take_profit_pct=None):
    """执行买入订单 — 创建新仓位或按最新订单更新已有仓位"""
    if stop_loss_pct is None:
        stop_loss_pct = STOP_LOSS_PCT
    if take_profit_pct is None:
        take_profit_pct = TAKE_PROFIT_PCT

    if not orders:
        return []

    executed = []
    for order in orders:
        code = order['代码']
        if code not in prices:
            continue

        raw_price = prices[code]['price']
        name = prices[code]['name']
        change_pct = prices[code].get('change_pct', 0)

        # 涨停过滤：按板块区分阈值（科创/创业 20%，北交所 30%，主板 10%）
        limit_pct = get_limit_pct(code)
        if change_pct >= limit_pct:
            print(f"[SIM] SKIP {code} {name}: 涨停({change_pct:+.2f}% >= {limit_pct}%)，无法买入")
            continue

        # 滑点：实际成交价略高于信号价
        price = round(raw_price * (1 + SLIPPAGE), 2)
        shares = order.get('股数', 0)
        amount = shares * price

        if amount <= 0:
            continue

        # 防线二：每笔订单执行前再过成本门槛（position_sizer 是第一道，这里防手工/旧订单绕过）
        mcap = order.get('流通市值', 0) or 0

        # 检查是否已持有：更新到最新订单的数量/止损/止盈
        existing = [p for p in state['positions'] if p['code'] == code]
        if existing:
            pos = existing[0]
            old_shares = pos['shares']
            if old_shares != shares:
                share_diff = shares - old_shares
                cash_diff = share_diff * price
                if cash_diff > 0:
                    # 加仓：只对新增投入金额过成本门槛
                    gate_ok, cb = _order_cost_gate_check(code, abs(cash_diff), mcap)
                    if not gate_ok:
                        print(f"[SIM] Cost gate SKIP add {code} {name}: "
                              f"round-trip cost={cb.pct:.2f}% > max={_cost_gate_max_pct()*100:.2f}%")
                        continue
                    # 重新计算加权平均成本
                    commission = max(abs(cash_diff) * _COMM_RATE, _COMM_MIN)
                    if state['cash'] < cash_diff + commission:
                        print(f"[SIM] Insufficient cash to adjust {code}: need {cash_diff + commission:.0f} (含佣金{commission:.2f})")
                        continue
                    state['cash'] -= cash_diff + commission
                    state['total_invested'] += cash_diff
                    state['total_commission'] += commission
                    state['total_trade_volume'] += abs(cash_diff)
                    total_cost = pos['entry_price'] * old_shares + price * share_diff
                    pos['entry_price'] = round(total_cost / shares, 2)
                else:
                    # 减仓：entry_price 不变，释放资金（按成本价减少 total_invested）；减仓不受买入成本门槛限制
                    release_amount = abs(share_diff) * price
                    commission = max(release_amount * _COMM_RATE, _COMM_MIN)
                    state['cash'] += release_amount - commission
                    cost_released = abs(share_diff) * pos['entry_price']
                    state['total_invested'] -= cost_released
                    state['total_commission'] += commission
                    state['total_trade_volume'] += release_amount
                print(f"[SIM] UPDATE {code} {name}: {old_shares}->{shares}股 (cash adj {cash_diff:+,.0f}, avg cost {pos['entry_price']})")

            pos['shares'] = shares
            pos['current_price'] = price
            pos['stop_loss'] = order.get('止损价', round(price * (1 + stop_loss_pct), 2))
            pos['take_profit'] = round(price * (1 + take_profit_pct), 2)
            pos['unrealized_pnl'] = (price - pos['entry_price']) * shares
            pos['unrealized_pnl_pct'] = round((price / pos['entry_price'] - 1) * 100, 2)
            executed.append(pos)
            continue

        # 新买入：成本门槛 + 扣除成交额与佣金（最低5元）
        gate_ok, cb = _order_cost_gate_check(code, amount, mcap)
        if not gate_ok:
            print(f"[SIM] Cost gate SKIP buy {code} {name}: amount={amount:.0f}, "
                  f"round-trip cost={cb.pct:.2f}% > max={_cost_gate_max_pct()*100:.2f}%")
            continue

        commission = max(amount * _COMM_RATE, _COMM_MIN)
        total_cost = amount + commission
        if state['cash'] < total_cost:
            print(f"[SIM] Insufficient cash for {code}: need {total_cost:.0f} (含佣金{commission:.2f}), have {state['cash']:.0f}")
            continue

        state['cash'] -= total_cost
        state['total_invested'] += amount
        state['total_commission'] += commission
        state['total_trade_volume'] += amount

        # 订单中的止损价优先（来自ATR计算），否则用百分比兜底
        order_stop = order.get('止损价', 0)
        stop = order_stop if order_stop and order_stop > 0 else round(price * (1 + stop_loss_pct), 2)

        position = {
            'code': code,
            'name': name,
            'shares': shares,
            'entry_price': price,
            'entry_date': get_last_trading_day(fmt='%Y-%m-%d'),
            'current_price': price,
            'stop_loss': stop,
            'take_profit': round(price * (1 + take_profit_pct), 2),
            'hold_days': 0,
            'unrealized_pnl': 0.0,
            'unrealized_pnl_pct': 0.0,
        }
        state['positions'].append(position)
        executed.append(position)

        print(f"[SIM] BUY {code} {name}: {shares}股 @ {price} = {amount:,.0f}")

    return executed


def load_history_for_sim():
    """加载历史K线用于MA/RSI计算"""
    hist_path = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(hist_path):
        return None
    try:
        df = pd.read_csv(hist_path, dtype={'代码': str})
        df['日期'] = pd.to_datetime(df['日期'])
        return df
    except Exception:
        return None


def calc_ma_sim(code, history_df, period):
    """计算MA"""
    if history_df is None:
        return None
    stock = history_df[history_df['代码'] == code]
    if len(stock) < period:
        return None
    return float(stock.sort_values('日期')['收盘'].tail(period).mean())


def calc_rsi_sim(code, history_df, period=14):
    """计算RSI"""
    if history_df is None:
        return None
    stock = history_df[history_df['代码'] == code]
    if len(stock) < period + 2:
        return None
    closes = stock.sort_values('日期')['收盘']
    deltas = closes.diff()
    gains = deltas.clip(lower=0)
    losses = -deltas.clip(upper=0)
    avg_gain = gains.rolling(period).mean().iloc[-1]
    avg_loss = losses.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return float(100 - 100 / (1 + avg_gain / avg_loss))


def check_exits(state, prices, max_hold_days=None):
    """检查出场条件：止损/止盈/到期/死叉/RSI弱势"""
    if max_hold_days is None:
        max_hold_days = MAX_HOLD_DAYS

    closed = []
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')

    # 加载K线用于技术指标
    history_df = load_history_for_sim()

    should_increment = state.get('_last_check_date') != today_str
    if not should_increment:
        print(f"[SIM] Already checked exits today ({today_str}), skipping hold_days increment")

    for pos in state['positions'][:]:
        code = pos['code']
        if should_increment:
            pos['hold_days'] += 1

        if code in prices:
            pos['current_price'] = prices[code]['price']

        current = pos['current_price']
        entry = pos['entry_price']
        pnl = (current - entry) / entry if entry > 0 else 0
        pos['unrealized_pnl'] = round(current * pos['shares'] - entry * pos['shares'], 2)
        pos['unrealized_pnl_pct'] = round(pnl * 100, 2)

        exit_reason = None
        exit_price = current

        # 1. 止损
        # Round-1 修复（2026-05-30）：跳空跌破止损时用 current 实际价，不再用预设 stop_loss 价
        # Why: 旧版 exit_price = pos['stop_loss'] 把跌停穿透情况优化记成 -8% 整，
        # 实际成交价 (current) 可能是 -10%/-15% (跌停 + 滑点)。模拟成本被低估。
        if current <= pos['stop_loss']:
            exit_reason = f'止损 ({pnl*100:+.1f}%)'
            exit_price = current

        # 2. 止盈
        elif current >= pos['take_profit']:
            exit_reason = f'止盈 ({pnl*100:+.1f}%)'
            exit_price = current

        # 3. 到期
        elif pos['hold_days'] >= max_hold_days:
            exit_reason = f'到期 ({pos["hold_days"]}日/{max_hold_days}d)'

        # 4. MA死叉 — Round-1 修复：MA5/MA20 与 exit_advisor.py 一致（旧版用 MA30 不一致）
        # Why: 旧 sim_trade 用 MA5<MA30 判死叉，exit_advisor 用 MA5<MA20，
        # 同一个出场议题两套标准，sim 出场提前/滞后于建议。
        ma5 = calc_ma_sim(code, history_df, 5)
        ma20 = calc_ma_sim(code, history_df, 20)
        if not exit_reason and ma5 and ma20 and ma5 < ma20:
            exit_reason = f'死叉 (MA5:{ma5:.2f}<MA20:{ma20:.2f})'

        # 5. RSI弱势 — 复用上面 ma20，避免重复 calc_ma_sim 调用
        rsi = calc_rsi_sim(code, history_df)
        if not exit_reason and ma20 and current < ma20 and rsi and rsi < 35:
            exit_reason = f'弱势 (价格<MA20, RSI:{rsi:.1f})'

        if exit_reason:
            # 卖出滑点：实际卖出价略低于信号价
            exit_price = round(exit_price * (1 - SLIPPAGE), 2)
            gross_amount = exit_price * pos['shares']
            sell_commission = max(gross_amount * _COMM_RATE, _COMM_MIN)
            stamp_tax = gross_amount * _STAMP_RATE
            net_amount = gross_amount - sell_commission - stamp_tax
            pnl_amount = net_amount - entry * pos['shares']

            # 基于实际成交价重新计算盈亏百分比（与 pnl_amount 一致）
            realized_pnl_pct = (net_amount / (entry * pos['shares']) - 1) if entry > 0 else 0

            state['cash'] += net_amount
            state['total_invested'] -= entry * pos['shares']
            state['total_trades'] += 1
            state['total_pnl'] += pnl_amount
            state['total_commission'] += sell_commission
            state['total_stamp_tax'] += stamp_tax
            state['total_trade_volume'] += gross_amount
            if pnl_amount > 0:
                state['winning_trades'] += 1

            closed.append({
                **pos,
                'exit_price': round(exit_price, 2),
                'exit_date': today.strftime('%Y-%m-%d'),
                'exit_reason': exit_reason,
                'realized_pnl': round(pnl_amount, 2),
                'realized_pnl_pct': f'{realized_pnl_pct*100:+.2f}%',
                'sell_commission': round(sell_commission, 2),
                'stamp_tax': round(stamp_tax, 2),
            })

            state['positions'].remove(pos)
            print(f"[SIM] SELL {code} {pos['name']}: {exit_reason} | PnL: {pnl_amount:+.0f} ({realized_pnl_pct*100:+.2f}%) | 佣金{sell_commission:.2f} 印花税{stamp_tax:.2f}")

    state['_last_check_date'] = today_str
    return closed


def record_trades(closed_positions):
    """记录已平仓交易到CSV"""
    if not closed_positions:
        return

    rows = []
    for p in closed_positions:
        rows.append({
            '代码': p['code'],
            '名称': p.get('name', ''),
            '入场日期': p['entry_date'],
            '出场日期': p.get('exit_date', ''),
            '入场价': p['entry_price'],
            '出场价': p.get('exit_price', 0),
            '股数': p['shares'],
            '盈亏': p.get('realized_pnl', 0),
            '盈亏%': p.get('realized_pnl_pct', ''),
            '出场原因': p.get('exit_reason', ''),
            '持有天数': p.get('hold_days', 0),
        })

    df_new = pd.DataFrame(rows)

    if os.path.exists(TRADES_FILE):
        df_old = pd.read_csv(TRADES_FILE)
        df_new = pd.concat([df_old, df_new], ignore_index=True)

    df_new.to_csv(TRADES_FILE, index=False, encoding='utf-8-sig')


def update_equity_curve(state):
    """更新权益曲线"""
    today_str = datetime.now().strftime('%Y-%m-%d')

    # 计算当前总权益
    position_value = sum(p['current_price'] * p['shares'] for p in state['positions'])
    equity = state['cash'] + position_value
    state['equity'] = round(equity, 2)

    row = {
        '日期': today_str,
        '现金': round(state['cash'], 2),
        '持仓市值': round(position_value, 2),
        '总权益': round(equity, 2),
        '持仓数': len(state['positions']),
        '累计交易': state['total_trades'],
        '累计盈亏': round(state['total_pnl'], 2),
    }

    if os.path.exists(EQUITY_FILE):
        df = pd.read_csv(EQUITY_FILE)
        # 去重：同一天只保留最新
        df = df[df['日期'] != today_str]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])

    df.sort_values('日期').to_csv(EQUITY_FILE, index=False, encoding='utf-8-sig')
    return equity


def generate_sim_report():
    """生成模拟交易绩效报告"""
    os.makedirs(SIM_DIR, exist_ok=True)

    # 账户状态（先 init 才能拿到 baseline）
    state = init_account()
    baseline = state.get('initial_capital', _FALLBACK_CAPITAL) or _FALLBACK_CAPITAL
    pos_value = sum(p['current_price'] * p['shares'] for p in state['positions'])
    equity = state['cash'] + pos_value
    total_return = (equity / baseline - 1) * 100 if baseline > 0 else 0

    lines = [
        f"# 模拟交易绩效报告",
        f"",
        f"> 生成日期：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 当前基线（真实净投入）：CNY{baseline:,.2f}",
        f"",
    ]

    lines.extend([
        f"## 账户概览",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总权益 | CNY{equity:,.2f} |",
        f"| 现金 | CNY{state['cash']:,.2f} |",
        f"| 持仓市值 | CNY{pos_value:,.2f} |",
        f"| 累计收益率 | {total_return:+.2f}% |",
        f"| 累计交易 | {state['total_trades']}笔 |",
        f"| 胜率 | {state['winning_trades']/max(1,state['total_trades'])*100:.1f}% |",
        f"| 累计盈亏 | CNY{state['total_pnl']:+,.2f} |",
        f"",
    ])

    # 成本汇总：hypothetical = 假设没有 5 元 floor 时的纯比例佣金
    hypothetical_commission = state['total_trade_volume'] * _COMM_RATE
    extra_commission = state['total_commission'] - hypothetical_commission
    extra_pct = (extra_commission / baseline * 100) if baseline > 0 else 0
    lines.extend([
        f"## 成本汇总",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 累计佣金 | CNY{state['total_commission']:,.2f} |",
        f"| 累计印花税 | CNY{state['total_stamp_tax']:,.2f} |",
        f"| 总成交额 | CNY{state['total_trade_volume']:,.2f} |",
        f"| 券商最低佣金影响 | 本周期因低佣金门槛多支付{max(0, extra_commission):.2f}元，占本金{extra_pct:.1f}% |",
        f"",
    ])

    # 当前持仓
    if state['positions']:
        lines.extend([
            f"## 当前持仓",
            f"",
            f"| 代码 | 名称 | 入场价 | 现价 | 股数 | 持仓天数 | 浮动盈亏 |",
            f"|------|------|--------|------|------|----------|----------|",
        ])
        for p in state['positions']:
            lines.append(
                f"| {p['code']} | {p['name']} | {p['entry_price']} | {p['current_price']} | "
                f"{p['shares']} | {p['hold_days']}日 | {p['unrealized_pnl_pct']:+.2f}% |"
            )
        lines.append("")

    # 权益曲线摘要
    if os.path.exists(EQUITY_FILE):
        df = pd.read_csv(EQUITY_FILE)
        if len(df) > 0:
            lines.extend([
                f"## 权益曲线",
                f"",
                f"- 起始日期：{df['日期'].iloc[0]}",
                f"- 最新日期：{df['日期'].iloc[-1]}",
                f"- 数据点数：{len(df)}",
                f"- 最高权益：CNY{df['总权益'].max():,.2f}",
                f"- 最低权益：CNY{df['总权益'].min():,.2f}",
                f"- 最大回撤：{((df['总权益'].max() - df['总权益'].min()) / df['总权益'].max() * 100):.2f}%",
                f"",
            ])

    # 交易历史摘要
    if os.path.exists(TRADES_FILE):
        trades = pd.read_csv(TRADES_FILE)
        if len(trades) > 0:
            win_trades = trades[trades['盈亏'] > 0]
            loss_trades = trades[trades['盈亏'] <= 0]
            lines.extend([
                f"## 交易统计",
                f"",
                f"| 指标 | 数值 |",
                f"|------|------|",
                f"| 总交易 | {len(trades)}笔 |",
                f"| 盈利交易 | {len(win_trades)}笔 ({len(win_trades)/max(1,len(trades))*100:.1f}%) |",
                f"| 亏损交易 | {len(loss_trades)}笔 |",
                f"| 平均盈利 | CNY{win_trades['盈亏'].mean():+,.2f}" if len(win_trades) > 0 else "| 平均盈利 | N/A |",
                f"| 平均亏损 | CNY{loss_trades['盈亏'].mean():+,.2f}" if len(loss_trades) > 0 else "| 平均亏损 | N/A |",
                f"| 盈亏比 | {abs(win_trades['盈亏'].mean()/loss_trades['盈亏'].mean()):.2f}" if len(win_trades) > 0 and len(loss_trades) > 0 and loss_trades['盈亏'].mean() != 0 else "| 盈亏比 | N/A |",
                f"| 总盈亏 | CNY{trades['盈亏'].sum():+,.2f} |",
                f"",
                f"## 出场原因分布",
                f"",
            ])
            for reason, cnt in trades['出场原因'].value_counts().items():
                sub = trades[trades['出场原因'] == reason]
                lines.append(f"- {reason}: {cnt}笔, 平均盈亏 {sub['盈亏'].mean():+,.2f}")

    # 执行质量评估：对比真实交易 vs 系统建议
    exec_quality = calc_execution_quality()
    if exec_quality:
        lines.extend(exec_quality)

    lines.extend(["", "---", f"*报告由 sim_trade.py v{SYSTEM_VERSION} 自动生成*"])

    report_path = os.path.join(SIM_DIR, 'sim_report.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"[SIM] Report: {report_path}")
    return report_path


def calc_execution_quality():
    """对比真实交易与系统建议，计算滑点和纪律偏差"""
    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(real_file):
        return None

    try:
        import pandas as pd
        real = pd.read_csv(real_file, dtype={'代码': str})
        if '备注' in real.columns:
            real = real[~real['备注'].str.contains('示例数据', na=False)]
        if len(real) == 0:
            return None
    except Exception:
        return None

    # 加载系统订单
    orders_dir = os.path.join(BASE_DIR, 'orders')
    order_files = sorted(
        [f for f in os.listdir(orders_dir) if f.startswith('daily_orders_') and f.endswith('.json')],
        reverse=True
    )

    system_orders = {}
    if order_files:
        import json
        with open(os.path.join(orders_dir, order_files[0]), 'r', encoding='utf-8') as f:
            order_data = json.load(f)
        for o in order_data.get('订单', []):
            system_orders[o['代码']] = o

    # 计算滑点：真实成交价 vs 系统建议价
    slippages = []
    discipline_issues = 0
    matched = 0

    for _, trade in real.iterrows():
        code = str(trade['代码']).zfill(6)
        direction = str(trade.get('方向', ''))
        price = float(trade['价格'])

        if code in system_orders:
            matched += 1
            sys_price = system_orders[code].get('价格', price)
            if sys_price and sys_price > 0:
                slip = (price / sys_price - 1) * 100
                if direction == '卖出':
                    slip = -slip  # 卖出滑点反向
                slippages.append(slip)
        else:
            discipline_issues += 1

    if not slippages and discipline_issues == 0 and matched == 0:
        return None

    avg_slip = sum(slippages) / len(slippages) if slippages else 0

    # 判断评价
    if abs(avg_slip) < 0.3 and discipline_issues <= 1:
        grade = '优秀'
    elif abs(avg_slip) < 0.8 and discipline_issues <= 3:
        grade = '良好'
    else:
        grade = '需改进'

    return [
        f"## 执行质量评估",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 匹配到系统订单 | {matched}笔 |",
        f"| 滑点均值 | {avg_slip:+.2f}% |",
        f"| 纪律偏差(无匹配订单) | {discipline_issues}次 |",
        f"| 评价 | {grade} |",
        f"",
        f"> 滑点=真实成交价相对系统建议价的偏离。正值=买贵了/卖便宜了。",
        f"> 纪律偏差=不在系统推荐列表中的自主交易。",
        f"",
        f"📊 本周执行评分：滑点均值 {avg_slip:+.2f}% | 纪律偏差 {discipline_issues} 次 | 评价：{grade}",
        f"",
    ]


def _main_lite():
    """v8 lite 模式（Beginner 1200 元小资金）：跑订单撮合 + 出场检查，但不做组合风控/换手控制。

    v8.6 修订（2026-05-28）：原 lite 模式只读 CSV 算市值不下单，导致小资金账户从未演练过持仓变化。
    现在：加载订单 → 检查出场（止损/止盈/到期/死叉/弱势）→ 买入新订单 → 落地 state。
    与 full 的区别：跳过 portfolio_risk 组合风控、跳过执行质量评估、跳过换手控制。
    """
    print(f"{'='*50}")
    print(f"  模拟交易 [lite] @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  小资金账本：撮合订单 + 出场检查，跳过组合风控")
    print(f"{'='*50}")

    # 非交易日保护
    if not is_today_trading_day():
        print(f"[SIM lite] Non-trading day ({datetime.now().strftime('%Y-%m-%d')}). Updating equity only.")
        state = init_account()
        prices = load_price_data()
        if state['positions'] and prices:
            for pos in state['positions']:
                code = pos['code']
                if code in prices:
                    pos['current_price'] = prices[code]['price']
                    pos['unrealized_pnl'] = round((prices[code]['price'] - pos['entry_price']) * pos['shares'], 2)
                    pos['unrealized_pnl_pct'] = round((prices[code]['price'] / pos['entry_price'] - 1) * 100, 2)
        equity = update_equity_curve(state)
        save_state(state)
        print(f"[SIM lite] Equity: {equity:,.2f}")
        return 0

    # 加载风控参数（可能被 strategy_feedback alert-only 模式调整过）
    risk = load_risk_config()
    stop_loss = risk.get('STOP_LOSS_PCT', STOP_LOSS_PCT)
    take_profit = risk.get('TAKE_PROFIT_PCT', TAKE_PROFIT_PCT)
    max_hold = int(risk.get('MAX_HOLD_DAYS', MAX_HOLD_DAYS))

    state = init_account()
    prices = load_price_data()
    print(f"[SIM lite] Loaded {len(prices)} stock prices, {len(state['positions'])} positions")

    # 1. 检查现有持仓出场
    print("\n[SIM lite] Checking exits for existing positions...")
    closed = check_exits(state, prices, max_hold_days=max_hold)
    if closed:
        record_trades(closed)
        print(f"[SIM lite] Closed {len(closed)} position(s)")
    else:
        print("[SIM lite] No positions to close")

    # 2. 加载当日订单 — 排除刚因止损/死叉卖出的票避免回头买
    orders = load_daily_orders()
    if closed:
        blocked = {c['code'] for c in closed if '止损' in c['exit_reason'] or '死叉' in c['exit_reason']}
        if blocked:
            orders = [o for o in orders if o['代码'] not in blocked]
            print(f"[SIM lite] Blocked re-buy of {len(blocked)} just-sold: {sorted(blocked)}")

    # 3. 执行买入订单
    if orders:
        print(f"\n[SIM lite] Executing {len(orders)} buy order(s)...")
        executed = execute_buy_orders(state, orders, prices, stop_loss_pct=stop_loss, take_profit_pct=take_profit)
        print(f"[SIM lite] Executed {len(executed)} buy(s)")
    else:
        print("[SIM lite] No new orders to execute")

    # 4. 更新权益 + 落地
    equity = update_equity_curve(state)
    save_state(state)
    baseline = state.get('initial_capital', _FALLBACK_CAPITAL)
    print(f"\n[SIM lite] Equity: {equity:,.2f} ({((equity/baseline)-1)*100:+.2f}%) | positions={len(state['positions'])} | baseline={baseline:,.0f}")

    try:
        generate_sim_report()
    except Exception as e:
        print(f"[SIM lite] Report skipped: {e}")

    print(f"[OK] Lite simulation done (with fills, no portfolio risk eval)")
    return 0


def main():
    # v8 双模式分发：lite=Beginner 极简账本 / full=Advanced+ 完整撮合+滑点+执行质量
    from core.config import SIM_MODE
    if SIM_MODE == 'lite':
        return _main_lite()

    print(f"{'='*50}")
    print(f"  模拟交易引擎 [full] v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 非交易日保护：无当日行情数据时跳过交易（但仍可更新持仓市值/检查出场）
    if not is_today_trading_day():
        print(f"[SIM] Non-trading day detected ({datetime.now().strftime('%Y-%m-%d')}). Skipping new orders.")
        state = init_account()
        prices = load_price_data()
        if state['positions'] and prices:
            for pos in state['positions']:
                code = pos['code']
                if code in prices:
                    # v8.7+: load_price_data() 返回 {code: {'price', 'name', 'change_pct'}}
                    # lite 模式之前已修，full 模式漏修：直接当 price 用会 TypeError
                    px = prices[code]['price']
                    pos['current_price'] = px
                    pos['unrealized_pnl'] = round((px - pos['entry_price']) * pos['shares'], 2)
                    pos['unrealized_pnl_pct'] = round((px / pos['entry_price'] - 1) * 100, 2)
        # v8.7+ Round 2: full 模式非交易日也刷新权益曲线，和 lite 保持对称
        # Why: lite 路径调 update_equity_curve，full 不调 → 节假日 equity 列空缺，
        # benchmark_compare/tracking_error_report 周末跑出来缺数。
        # Round 3: 收紧 except — 仅吞 IOError/OSError（写盘失败可重试），其余抛回
        # 让 daily_pipeline 看到 fatal_on_fail=False 走 [WARN] 分支，避免静默吞数据 bug
        try:
            update_equity_curve(state)
        except (OSError, IOError) as exc:
            print(f"[SIM] equity update skipped (IO): {exc}")
        save_state(state)
        return 0

    # 加载风控参数（可能被 strategy_feedback 调整过）
    risk = load_risk_config()
    stop_loss = risk.get('STOP_LOSS_PCT', STOP_LOSS_PCT)
    take_profit = risk.get('TAKE_PROFIT_PCT', TAKE_PROFIT_PCT)
    max_hold = int(risk.get('MAX_HOLD_DAYS', MAX_HOLD_DAYS))

    # 1. 加载/初始化账户
    state = init_account()
    baseline = state.get('initial_capital', _FALLBACK_CAPITAL)

    print(f"  初始资金: CNY{baseline:,.0f} | 止损{stop_loss*100:.0f}% | 止盈{take_profit*100:.0f}% | 最多{max_hold}日")
    print(f"{'='*50}")

    # 2. 加载价格数据
    prices = load_price_data()
    print(f"[SIM] Loaded {len(prices)} stock prices")

    # 3. 检查现有持仓的出场条件
    print("\n[SIM] Checking exits for existing positions...")
    closed = check_exits(state, prices, max_hold_days=max_hold)
    if closed:
        record_trades(closed)
        print(f"[SIM] Closed {len(closed)} position(s)")
    else:
        print("[SIM] No positions to close")

    # 4. 加载当日订单并排除已卖出股票
    orders = load_daily_orders()
    if closed:
        blocked_codes = {c['code'] for c in closed if '止损' in c['exit_reason'] or '死叉' in c['exit_reason']}
        if blocked_codes:
            orders = [o for o in orders if o['代码'] not in blocked_codes]
            print(f"\n[SIM] Blocked re-buy of {len(blocked_codes)} just-sold stock(s): {', '.join(sorted(blocked_codes))}")

    # 5. 组合风控检查（v7.6: 回撤硬止损 + 波动率目标）
    # v8: tier gate —— 仅 Pro/Auto 启用；其他 tier 整段跳过（CVaR 计算函数仍可手动 import）
    from core.config import ENABLE_PORTFOLIO_RISK
    if ENABLE_PORTFOLIO_RISK:
        try:
            from portfolio_risk import generate_risk_report, save_risk_report
            risk_report = generate_risk_report(state, new_orders=orders)
            save_risk_report(risk_report)
            if risk_report['drawdown']['action'] == 'force_reduce':
                print(f"\n[RISK] {risk_report['drawdown']['message']}")
                print("[RISK] All new buy orders CANCELLED due to drawdown limit")
                orders = []
            elif risk_report['volatility'].get('action') == 'force_reduce':
                print(f"\n[RISK] {risk_report['volatility']['message']}")
                print("[RISK] All new buy orders CANCELLED due to volatility target breach")
                orders = []
            else:
                if risk_report['drawdown']['action'] == 'warning':
                    print(f"\n[RISK] WARNING: {risk_report['drawdown']['message']}")
                if risk_report.get('correlation', {}).get('warning'):
                    print(f"\n[RISK] WARNING: {risk_report['recommended_actions']}")
        except Exception as e:
            print(f"\n[RISK] Risk check skipped: {e}")
    else:
        print(f"\n[RISK] Portfolio risk dormant（Pro 级 20万+ 解锁）")

    # 6. 执行新订单
    if orders:
        print(f"\n[SIM] Executing {len(orders)} buy orders...")
        executed = execute_buy_orders(state, orders, prices, stop_loss_pct=stop_loss, take_profit_pct=take_profit)
        print(f"[SIM] Executed {len(executed)} buy(s)")
    else:
        print("\n[SIM] No new orders today")

    # 5. 更新权益曲线
    equity = update_equity_curve(state)
    save_state(state)

    # 6. 生成报告
    print(f"\n[SIM] Current equity: {equity:,.2f} ({((equity/baseline)-1)*100:+.2f}%)")
    print(f"[SIM] Positions: {len(state['positions'])}, Cash: {state['cash']:,.0f}")

    report_path = generate_sim_report()
    print(f"\n[OK] Simulation cycle complete")

    return 0


if __name__ == '__main__':
    sys.exit(main())