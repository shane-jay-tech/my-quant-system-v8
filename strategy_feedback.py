"""
策略反馈闭环 v2 — 衡量策略表现 → 更新权重 → 调整风控参数 + 冷启动

功能：
1. 读取历史多策略投票结果，计算3/5/10日前瞻收益
2. 按策略汇总胜率和平均收益
3. 生成 data/strategy_forward_returns.csv（供 multi_strategy 权重更新）
4. 基于整体表现自动调整风控参数
5. 生成反馈报告 → reports/strategy_feedback_YYYYMMDD.md
6. v2: 冷启动 — 真实交易不足时加载回测数据预填充
"""
import os, sys, json, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION
from core.config import get as cfg_get

COLD_START_ENABLED = True
MIN_REAL_TRADES = 5  # 真实交易少于此数则启用冷启动
# v8.6: 仓位/止损调整门槛 — 30 笔以下统计噪音过大，禁用自动调整
MIN_TRADES_FOR_ADJUST = cfg_get('feedback.min_trades_for_adjust', 30)


def load_history_data():
    """加载历史K线数据"""
    f = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(f):
        return None
    df = pd.read_csv(f, dtype={'代码': str})
    df['日期'] = pd.to_datetime(df['日期'])
    return df


def calc_forward_returns(pick_date, code, history_df, horizon_days=[3, 5, 10]):
    """
    计算选股后N个交易日的实际收益

    Args:
        pick_date: 选股日期 (str 'YYYY-MM-DD' or datetime)
        code: 股票代码
        history_df: 历史K线
        horizon_days: 前瞻天数列表

    Returns:
        dict: {f'ret_{d}d': float or None, ...}
    """
    if isinstance(pick_date, str):
        pick_date = pd.to_datetime(pick_date)

    stock_hist = history_df[history_df['代码'] == code].copy()
    if len(stock_hist) == 0:
        return {f'ret_{d}d': None for d in horizon_days}

    stock_hist = stock_hist.sort_values('日期')

    # 找到选股日当天的数据
    pick_day_data = stock_hist[stock_hist['日期'] == pick_date]
    if len(pick_day_data) == 0:
        # 取选股日之前最近的一个交易日
        stock_hist_before = stock_hist[stock_hist['日期'] <= pick_date]
        if len(stock_hist_before) == 0:
            return {f'ret_{d}d': None for d in horizon_days}
        pick_idx = stock_hist_before.index[-1]
        entry_price = stock_hist_before.iloc[-1]['收盘']
        # 在前向窗口中找N日后的价格
        stock_hist_after = stock_hist[stock_hist['日期'] > pick_date]
    else:
        pick_idx = pick_day_data.index[-1]
        entry_price = pick_day_data.iloc[-1]['收盘']
        stock_hist_after = stock_hist[stock_hist['日期'] > pick_date]

    results = {}
    for d in horizon_days:
        future_data = stock_hist_after.head(d)
        if len(future_data) >= min(d, 1):
            exit_price = future_data.iloc[-1]['收盘']
            ret = (exit_price / entry_price - 1) * 100
            results[f'ret_{d}d'] = round(ret, 2)
        else:
            results[f'ret_{d}d'] = None

    return results


def analyze_past_picks(history_df, lookback_days=30):
    """
    分析近N天的所有投票结果，计算各策略的前瞻收益

    Returns:
        pd.DataFrame with columns: 日期, 代码, 名称, 策略, 策略内排名, 3日收益, 5日收益, 10日收益
    """
    vote_files = sorted(glob.glob(os.path.join(ORDERS_DIR, 'multi_vote_*.json')))
    if not vote_files:
        print("[FEEDBACK] No multi_vote files found")
        return pd.DataFrame()

    cutoff_date = datetime.now() - timedelta(days=lookback_days + 10)  # 留足前瞻窗口

    all_rows = []
    n_total = len(vote_files)
    n_filtered_cutoff = 0
    n_filtered_no_history = 0
    n_analyzed = 0
    for vf in vote_files:
        # 从文件名提取日期
        basename = os.path.basename(vf)
        date_str = basename.replace('multi_vote_', '').replace('.json', '')
        try:
            pick_date = pd.to_datetime(datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d'))
        except ValueError:
            continue

        if pick_date < cutoff_date:
            n_filtered_cutoff += 1
            continue

        # v8: 把 +3 改 +1，让冷启动期至少能产出 partial 数据
        # Why: history 数据通常 T 日盘后更新，vote 文件也是 T 日生成；
        # 严格要求 +3 天前瞻会让最近 3 天的 vote 全被过滤，导致 strategy_forward_returns.csv 永远空
        if history_df['日期'].max() < pick_date + timedelta(days=1):
            n_filtered_no_history += 1
            continue
        n_analyzed += 1

        with open(vf, 'r', encoding='utf-8') as f:
            votes = json.load(f)

        for v in votes:
            code = v.get('代码', '')
            name = v.get('名称', '')
            strat_ranks = v.get('各策略排名', {})
            # 跳过无策略归属的
            if not strat_ranks:
                continue

            # 计算前瞻收益
            fwd = calc_forward_returns(pick_date, code, history_df, [3, 5, 10])

            for strat_name, rank in strat_ranks.items():
                all_rows.append({
                    '选股日期': pick_date.strftime('%Y-%m-%d'),
                    '代码': code,
                    '名称': name,
                    '策略': strat_name,
                    '策略内排名': rank,
                    '3日收益': fwd.get('ret_3d'),
                    '5日收益': fwd.get('ret_5d'),
                    '10日收益': fwd.get('ret_10d'),
                })

    print(f"[FEEDBACK] Vote files: total={n_total} | cutoff_filtered={n_filtered_cutoff} | "
          f"history_too_short={n_filtered_no_history} | analyzed={n_analyzed} | rows={len(all_rows)}")

    if not all_rows:
        print("[FEEDBACK] No analyzable past picks")
        return pd.DataFrame()

    return pd.DataFrame(all_rows)


def generate_forward_returns_file(analysis_df):
    """生成策略前瞻收益汇总文件

    v8: 即使 analysis_df 为空也写一个仅含表头的 csv 占位
    Why: multi_strategy.update_strategy_weights 用 os.path.exists 检查；
         文件不存在 → 走 fallback 等权 → 多策略加权变成 mean voting；
         空文件存在 → 走 try 块的 fallback (perf 0.5 → softmax 等权)，行为一致但更显式
    """
    path = os.path.join(DATA_DIR, 'strategy_forward_returns.csv')

    if len(analysis_df) == 0:
        # 写空占位 csv，让 multi_strategy 走显式 fallback 而非文件不存在分支
        empty_df = pd.DataFrame(columns=['日期', '策略', '5日收益', '5日胜率', '选股数'])
        empty_df.to_csv(path, index=False, encoding='utf-8-sig')
        print(f"[FEEDBACK] Empty forward_returns placeholder written: {path}")
        return path

    # 按策略+选股日期汇总
    summary = analysis_df.groupby(['选股日期', '策略']).agg(
        平均3日收益=('3日收益', 'mean'),
        平均5日收益=('5日收益', 'mean'),
        平均10日收益=('10日收益', 'mean'),
        胜率3日=('3日收益', lambda x: (x > 0).mean()),
        胜率5日=('5日收益', lambda x: (x > 0).mean()),
        胜率10日=('10日收益', lambda x: (x > 0).mean()),
        选股数量=('代码', 'count'),
    ).reset_index()

    summary = summary.rename(columns={
        '平均3日收益': '3日收益',
        '平均5日收益': '5日收益',
        '平均10日收益': '10日收益',
    })

    # 保存为multi_strategy.py期望的格式
    # 策略, 5日收益 (主要优化目标), 选股日期
    output = summary[['选股日期', '策略', '5日收益', '胜率5日', '选股数量']].copy()
    output.columns = ['日期', '策略', '5日收益', '5日胜率', '选股数']

    path = os.path.join(DATA_DIR, 'strategy_forward_returns.csv')
    output.to_csv(path, index=False, encoding='utf-8-sig')
    print(f"[FEEDBACK] Forward returns saved: {path} ({len(output)} rows)")
    return path


def load_cold_start_trades():
    """加载冷启动交易数据（从回测生成的JSON文件）"""
    good_file = os.path.join(DATA_DIR, 'good_trades.json')
    bad_file = os.path.join(DATA_DIR, 'bad_trades.json')
    manifest_file = os.path.join(DATA_DIR, 'cold_start_manifest.json')

    if not os.path.exists(good_file) or not os.path.exists(bad_file):
        return None

    try:
        with open(good_file, 'r', encoding='utf-8') as f:
            good = json.load(f)
        with open(bad_file, 'r', encoding='utf-8') as f:
            bad = json.load(f)

        all_trades = good + bad
        if not all_trades:
            return None

        # Load manifest for metadata
        manifest = {}
        if os.path.exists(manifest_file):
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

        print(f"[FEEDBACK] Cold start: loaded {len(good)} good + {len(bad)} bad trades from backtest")
        print(f"[FEEDBACK] Cold start manifest: {manifest.get('date_range', 'unknown')}, "
              f"{manifest.get('total_trades', '?')} total backtest trades")

        return {
            'trades': all_trades,
            'good': good,
            'bad': bad,
            'manifest': manifest,
            'is_cold_start': True,
        }
    except Exception as e:
        print(f"[FEEDBACK] Failed to load cold start data: {e}")
        return None


def load_real_trades():
    """加载真实交易记录（优先数据源）"""
    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(real_file):
        return None, 0
    try:
        df = pd.read_csv(real_file, dtype={'代码': str})
        # 过滤掉示例数据行
        if '备注' in df.columns:
            df = df[~df['备注'].str.contains('示例数据', na=False)]
        return df, len(df)
    except Exception:
        return None, 0


def _safe_float(v, default=0.0):
    """v8.7+ Round 2: NaN/None/空串安全转 float。

    Why: pd.read_csv 把缺失的'手续费'读成 NaN，`float(NaN or 0) = NaN`（NaN 是 truthy），
    NaN 一旦混进 pnl_amount 就会污染整条 metrics 链（NaN > 0 = False，胜率失真；
    int(NaN) 会 raise）。
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN check
        return default
    return f


def _safe_int(v, default=0):
    f = _safe_float(v, default)
    try:
        return int(f)
    except (TypeError, ValueError, OverflowError):
        return default


def pair_real_trades_fifo(real_df):
    """v8.7+: 真实交易 FIFO 配对，得到已平仓交易的 PnL%（含手续费的净 PnL）。

    Why: v8.6 之前 strategy_feedback 在 real_count > 0 时走 placeholder 分支
    （硬编码 win_rate=0.5、盈亏=0、提前 return），真实交易越多反馈越失效。
    Round 2 修复：
    - 买入手续费用 original_shares 摊销（不是变化中的 shares_left），避免分批卖时多扣
    - pnl_pct 用净 PnL 除以买入成本（小资金 5 元手续费下限会让毛 +0.5% 实际是亏）
    - 同日买卖按 买入 → 卖出 排序，避免日内 T+0 数据顺序错乱（A 股理论 T+1，但
      数据中如有同日双向行须保证 buy 先入队）

    Args:
        real_df: load_real_trades() 返回的 DataFrame。

    Returns:
        list[dict]: 含 code, name, entry_date, exit_date, entry_price, exit_price,
                   shares, pnl_pct (净), pnl_pct_gross (毛), pnl_amount (净), exit_reason
    """
    if real_df is None or len(real_df) == 0:
        return []

    df = real_df.copy()
    if '代码' not in df.columns or '方向' not in df.columns:
        return []
    df['代码'] = df['代码'].astype(str).str.zfill(6)
    df['日期'] = pd.to_datetime(df.get('日期', pd.NaT), errors='coerce')
    # M5: 同日双向：买入 → 卖出 排序（_dir_rank=0 买，1 卖）
    # Round 3: 用 mergesort 保证稳定排序，同日同向记录维持原始顺序，FIFO 可复现
    df['_dir_rank'] = df['方向'].map({'买入': 0, '卖出': 1}).fillna(2).astype(int)
    df = df.sort_values(['代码', '日期', '_dir_rank'], kind='mergesort').drop(columns=['_dir_rank'])

    closed = []
    for code, group in df.groupby('代码'):
        buy_queue = []  # {price, shares_left, original_shares, date, name, total_fee}
        for _, row in group.iterrows():
            direction = str(row.get('方向', ''))
            price = _safe_float(row.get('价格', 0))
            shares = _safe_int(row.get('数量', 0))
            fee = _safe_float(row.get('手续费', 0))
            if price <= 0 or shares <= 0:
                continue
            name = str(row.get('名称', ''))
            d = row.get('日期')
            if direction == '买入':
                buy_queue.append({
                    'price': price,
                    'shares_left': shares,
                    'original_shares': shares,  # M2: 静态分母
                    'date': d, 'name': name,
                    'total_fee': fee,  # M2: 整批买入手续费
                })
            elif direction == '卖出':
                remaining = shares
                sell_fee_per_share = (fee / shares) if shares else 0
                while remaining > 0 and buy_queue:
                    head = buy_queue[0]
                    take = min(remaining, head['shares_left'])
                    entry_p = head['price']
                    exit_p = price
                    # M2: 买入手续费用 original_shares（静态）摊销，分批卖不会重复扣
                    buy_fee_per_share = (head['total_fee'] / head['original_shares']) \
                                        if head['original_shares'] else 0
                    gross_pnl_amount = (exit_p - entry_p) * take
                    pnl_amount = gross_pnl_amount - sell_fee_per_share * take \
                                 - buy_fee_per_share * take
                    pnl_pct_gross = (exit_p / entry_p - 1) * 100 if entry_p else 0
                    # M3: 净 pnl_pct = 净盈亏 / 买入成本（含买入费）
                    cost_basis = entry_p * take + buy_fee_per_share * take
                    pnl_pct = (pnl_amount / cost_basis * 100) if cost_basis > 0 else 0
                    closed.append({
                        'code': code,
                        'name': head['name'] or name,
                        'entry_date': head['date'],
                        'exit_date': d,
                        'entry_price': entry_p,
                        'exit_price': exit_p,
                        'shares': take,
                        'pnl_pct': round(pnl_pct, 4),
                        'pnl_pct_gross': round(pnl_pct_gross, 4),
                        'pnl_amount': round(pnl_amount, 2),
                        'exit_reason': '真实卖出',
                    })
                    head['shares_left'] -= take
                    remaining -= take
                    if head['shares_left'] <= 0:
                        buy_queue.pop(0)
                # remaining > 0 时表示卖空 / 数据缺失，silently 忽略
    return closed


def analyze_risk_adjustments(cold_start_data=None):
    """
    基于真实交易 > 模拟交易整体表现，判断是否需要调整风控参数
    数据源优先级：real_trades.csv > sim trade_history.csv > 冷启动回测

    Returns:
        dict: 调整建议
    """
    trades_file = os.path.join(SIM_DIR, 'trade_history.csv')
    equity_file = os.path.join(SIM_DIR, 'equity_curve.csv')

    # v8.7+ Round 2: alert_only 改读 config（默认仍 True），不再硬编码
    # Why: 之前 alert_only=True 写死，所有 else 分支结构性 dead code；
    # 升级到 Pro/Auto 想关 alert_only 时除了改源码无路可走
    # Round 3: 用 _parse_bool 显式解析；之前 bool(cfg) 对字符串 'False'/'0' 仍返回 True，
    # 用户在 system_config.json 里写 "alert_only": "false" 永远关不掉
    _alert_raw = cfg_get('feedback.alert_only', True)
    if isinstance(_alert_raw, bool):
        alert_only_default = _alert_raw
    elif isinstance(_alert_raw, (int, float)):
        alert_only_default = bool(_alert_raw)
    else:
        alert_only_default = str(_alert_raw).strip().lower() in ('true', '1', 'yes', 'y', 'on')
    adjustments = {
        'stop_loss_pct': -0.08,
        'take_profit_pct': 0.20,
        'max_hold_days': 10,
        'position_size_mult': 1.0,
        'warnings': [],
        'actions': [],
        'data_source': '无',
        'trade_source': 'none',
        'alert_only': alert_only_default,
    }

    # 第一优先级：真实交易记录
    real_df, real_count = load_real_trades()
    if real_count > 0:
        adjustments['trade_source'] = 'real'
        adjustments['data_source'] = f'[实盘数据] 真实交易 ({real_count}笔)'
        adjustments['warnings'].append('[实盘数据] 基于用户真实成交记录分析')

        # v8.7+: FIFO 配对真实买卖，算真实 PnL/win_rate（之前是 placeholder=0.5 硬编码）
        closed = pair_real_trades_fifo(real_df)
        closed_count = len(closed)

        buy_trades = real_df[real_df['方向'] == '买入'] if '方向' in real_df.columns else real_df
        total_amount = (buy_trades['成交额'].sum() if '成交额' in buy_trades.columns
                       else (buy_trades['价格'] * buy_trades['数量']).sum())

        if closed_count == 0:
            # 真实交易存在但全是开仓：metrics 显示当前敞口，不调任何参数
            adjustments['metrics'] = {
                '总交易': real_count,
                '总成交额': f'{total_amount:,.0f}',
                '已平仓': 0,
                '胜率': '待积累卖出记录',
                '数据来源': adjustments['data_source'],
            }
            return adjustments

        # 有平仓 → 算真实统计
        wins = [t for t in closed if t['pnl_pct'] > 0]
        losses = [t for t in closed if t['pnl_pct'] <= 0]
        win_rate = len(wins) / closed_count
        avg_win = float(np.mean([t['pnl_pct'] for t in wins])) if wins else 0
        avg_loss = float(np.mean([t['pnl_pct'] for t in losses])) if losses else 0
        total_pnl_pct = sum(t['pnl_pct'] for t in closed)
        total_pnl_amount = sum(t['pnl_amount'] for t in closed)
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # alert-only 模式 + MIN_TRADES_FOR_ADJUST 门槛：和 sim 路径一致
        alert_only = adjustments.get('alert_only') is True
        if win_rate < 0.35 and closed_count >= MIN_TRADES_FOR_ADJUST:
            action = f'[实盘] 胜率{win_rate:.0%}<35%，仓位系数降至0.5'
            if alert_only:
                adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
            else:
                adjustments['position_size_mult'] = 0.5
                adjustments['actions'].append(action)
        elif win_rate < 0.45 and closed_count >= MIN_TRADES_FOR_ADJUST:
            action = f'[实盘] 胜率{win_rate:.0%}<45%，仓位系数降至0.7'
            if alert_only:
                adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
            else:
                adjustments['position_size_mult'] = 0.7
                adjustments['actions'].append(action)
        elif win_rate > 0.60 and closed_count >= MIN_TRADES_FOR_ADJUST:
            action = f'[实盘] 胜率{win_rate:.0%}>60%，仓位系数提升至1.2'
            if alert_only:
                adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
            else:
                adjustments['position_size_mult'] = 1.2
                adjustments['actions'].append(action)

        if profit_factor < 1.0 and closed_count >= MIN_TRADES_FOR_ADJUST:
            action = f'[实盘] 盈亏比{profit_factor:.2f}<1，止盈从20%降至12%'
            if alert_only:
                adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
            else:
                adjustments['take_profit_pct'] = 0.12
                adjustments['actions'].append(action)
        elif profit_factor > 2.5 and closed_count >= MIN_TRADES_FOR_ADJUST:
            action = f'[实盘] 盈亏比{profit_factor:.2f}>2.5，止盈从20%升至25%'
            if alert_only:
                adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
            else:
                adjustments['take_profit_pct'] = 0.25
                adjustments['actions'].append(action)

        if closed_count < MIN_TRADES_FOR_ADJUST:
            adjustments['warnings'].append(
                f'[实盘] 平仓样本{closed_count}<{MIN_TRADES_FOR_ADJUST}笔，'
                f'统计噪音过大，仅展示指标不调参'
            )

        adjustments['metrics'] = {
            '总交易': real_count,
            '已平仓': closed_count,
            '胜率': f'{win_rate:.1%}',
            '平均盈利': f'{avg_win:+.2f}%',
            '平均亏损': f'{avg_loss:+.2f}%',
            '盈亏比': f'{profit_factor:.2f}',
            '总盈亏(%)': f'{total_pnl_pct:+.2f}%',
            '总盈亏(元)': f'{total_pnl_amount:+,.2f}',
            '数据来源': adjustments['data_source'],
        }
        return adjustments

    # 第二优先级：模拟交易记录
    real_trades_exist = os.path.exists(trades_file)
    real_trades_count = 0
    if real_trades_exist:
        try:
            real_df = pd.read_csv(trades_file)
            real_trades_count = len(real_df)
        except Exception:
            real_trades_count = 0

    # Cold start: real trades < minimum, use backtest data
    if real_trades_count < MIN_REAL_TRADES and COLD_START_ENABLED and cold_start_data:
        cold_trades = cold_start_data['trades']
        cold_good = cold_start_data['good']
        cold_bad = cold_start_data['bad']
        total_cold = len(cold_trades)

        if total_cold >= 5:
            win_count = len(cold_good)
            lose_count = len(cold_bad)
            win_rate = win_count / total_cold
            avg_win = np.mean([t['盈亏%'] for t in cold_good]) if cold_good else 0
            avg_loss = np.mean([t['盈亏%'] for t in cold_bad]) if cold_bad else 0
            total_pnl = sum(t['盈亏%'] for t in cold_trades)
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
            stop_count = sum(1 for t in cold_bad if '死叉' in str(t.get('出场原因', '')))
            stop_loss_rate = stop_count / lose_count if lose_count > 0 else 0

            adjustments['data_source'] = f'回测冷启动 ({total_cold}笔模拟交易, {cold_start_data["manifest"].get("date_range", "")})'
            adjustments['warnings'].append('[冷启动数据] 基于回测模拟交易分析，后续将被实盘数据替换')

            # v8.6: alert-only 模式 — 不再自动改止损/止盈，仓位门槛提到 MIN_TRADES_FOR_ADJUST
            alert_only = adjustments.get('alert_only') is True
            if stop_loss_rate > 0.5 and total_cold >= MIN_TRADES_FOR_ADJUST:
                action = f'[冷启动] 死叉出场率{stop_loss_rate:.0%}偏高，止损从-8%放宽到-10%'
                if alert_only:
                    adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
                else:
                    adjustments['stop_loss_pct'] = -0.10
                    adjustments['actions'].append(action)
            elif stop_loss_rate < 0.2 and total_cold >= MIN_TRADES_FOR_ADJUST:
                action = f'[冷启动] 止损率{stop_loss_rate:.0%}偏低，止损从-8%收紧到-6%'
                if alert_only:
                    adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
                else:
                    adjustments['stop_loss_pct'] = -0.06
                    adjustments['actions'].append(action)

            if win_rate < 0.40 and total_cold >= MIN_TRADES_FOR_ADJUST:
                action = f'[冷启动] 胜率{win_rate:.0%}<40%，仓位系数降至0.7'
                if alert_only:
                    adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
                else:
                    adjustments['position_size_mult'] = 0.7
                    adjustments['actions'].append(action)
            elif win_rate > 0.55 and total_cold >= MIN_TRADES_FOR_ADJUST:
                action = f'[冷启动] 胜率{win_rate:.0%}>55%，仓位系数提升至1.1'
                if alert_only:
                    adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
                else:
                    adjustments['position_size_mult'] = 1.1
                    adjustments['actions'].append(action)

            if profit_factor > 1.5 and total_cold >= MIN_TRADES_FOR_ADJUST:
                action = f'[冷启动] 盈亏比{profit_factor:.2f}>1.5，止盈从20%升至25%'
                if alert_only:
                    adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
                else:
                    adjustments['take_profit_pct'] = 0.25
                    adjustments['actions'].append(action)

            adjustments['metrics'] = {
                '总交易': total_cold,
                '胜率': f'{win_rate:.1%}',
                '平均盈利': f'{avg_win:+.2f}%',
                '平均亏损': f'{avg_loss:+.2f}%',
                '盈亏比': f'{profit_factor:.2f}',
                '总盈亏': f'{total_pnl:+.2f}%',
                '止损率': f'{stop_loss_rate:.1%}',
                '数据来源': '回测冷启动',
            }

            return adjustments

    # No real trades, no cold start
    if not os.path.exists(trades_file) or real_trades_count == 0:
        adjustments['warnings'].append('无交易历史，使用默认风控参数')
        if not cold_start_data:
            adjustments['warnings'].append('冷启动数据也未生成，请运行 enhanced_backtest.py 生成')
        adjustments['data_source'] = '无'
        return adjustments

    # Real trades available — use them
    trades = pd.read_csv(trades_file)
    total_trades = len(trades)
    win_rate = (trades['盈亏'] > 0).mean()
    avg_win = trades[trades['盈亏'] > 0]['盈亏'].mean() if len(trades[trades['盈亏'] > 0]) > 0 else 0
    avg_loss = trades[trades['盈亏'] <= 0]['盈亏'].mean() if len(trades[trades['盈亏'] <= 0]) > 0 else 0
    total_pnl = trades['盈亏'].sum()
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    exit_reasons = trades['出场原因'].value_counts().to_dict()
    stop_loss_count = sum(v for k, v in exit_reasons.items() if '止损' in str(k))
    stop_loss_rate = stop_loss_count / total_trades if total_trades > 0 else 0

    adjustments['data_source'] = f'模拟交易 ({total_trades}笔)'

    # v8.6: alert-only 模式 — 不再自动改止损/止盈，仓位门槛提到 MIN_TRADES_FOR_ADJUST
    alert_only = adjustments.get('alert_only') is True
    if stop_loss_rate > 0.5 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'止损率{stop_loss_rate:.0%}偏高，止损从-8%放宽到-10%'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['stop_loss_pct'] = -0.10
            adjustments['actions'].append(action)
    elif stop_loss_rate < 0.2 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'止损率{stop_loss_rate:.0%}偏低，止损从-8%收紧到-6%'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['stop_loss_pct'] = -0.06
            adjustments['actions'].append(action)

    if win_rate < 0.35 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'胜率{win_rate:.0%}<35%，仓位系数降至0.5'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['position_size_mult'] = 0.5
            adjustments['actions'].append(action)
    elif win_rate < 0.45 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'胜率{win_rate:.0%}<45%，仓位系数降至0.7'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['position_size_mult'] = 0.7
            adjustments['actions'].append(action)
    elif win_rate > 0.60 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'胜率{win_rate:.0%}>60%，仓位系数提升至1.2'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['position_size_mult'] = 1.2
            adjustments['actions'].append(action)

    if profit_factor < 1.0 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'盈亏比{profit_factor:.2f}<1，止盈从20%降至12%'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['take_profit_pct'] = 0.12
            adjustments['actions'].append(action)
    elif profit_factor > 2.5 and total_trades >= MIN_TRADES_FOR_ADJUST:
        action = f'盈亏比{profit_factor:.2f}>2.5，止盈从20%升至25%'
        if alert_only:
            adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
        else:
            adjustments['take_profit_pct'] = 0.25
            adjustments['actions'].append(action)

    if os.path.exists(equity_file):
        equity = pd.read_csv(equity_file)
        if len(equity) > 5:
            peak = equity['总权益'].cummax()
            drawdown = (equity['总权益'] / peak - 1)
            max_dd = drawdown.min()
            if max_dd < -0.15:
                adjustments['max_hold_days'] = 7
                adjustments['actions'].append(f'最大回撤{max_dd:.1%}，持有天数从10缩至7日')

    adjustments['metrics'] = {
        '总交易': total_trades,
        '胜率': f'{win_rate:.1%}',
        '平均盈利': f'{avg_win:+,.0f}',
        '平均亏损': f'{avg_loss:+,.0f}',
        '盈亏比': f'{profit_factor:.2f}',
        '总盈亏': f'{total_pnl:+,.0f}',
        '止损率': f'{stop_loss_rate:.1%}',
        '数据来源': '实盘模拟',
    }

    return adjustments


def _archive_old_risk_config(config_path):
    """v8.6: 写新风控参数前先归档旧版本到 data/risk_config_history/。

    Why: 反馈循环每天可能改一次风控参数；3 个月后想问"为什么止损是 -10% 而不是 -8%"
    没法查。归档后保留历史，可审计。
    保留最近 30 天，超过自动清理。
    """
    if not os.path.exists(config_path):
        return
    history_dir = os.path.join(DATA_DIR, 'risk_config_history')
    os.makedirs(history_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_path = os.path.join(history_dir, f'risk_config_{ts}.json')
    try:
        import shutil
        shutil.copy2(config_path, archive_path)
    except Exception as e:
        print(f"[FEEDBACK] archive failed: {e}")
        return
    # 清理 30 天前的归档
    cutoff = datetime.now() - timedelta(days=30)
    for fname in os.listdir(history_dir):
        if not fname.startswith('risk_config_') or not fname.endswith('.json'):
            continue
        try:
            ts_str = fname.replace('risk_config_', '').replace('.json', '').split('_')[0]
            ftime = datetime.strptime(ts_str, '%Y%m%d')
            if ftime < cutoff:
                os.remove(os.path.join(history_dir, fname))
        except Exception:
            continue


# v8.7: 抽到 utils/file_io.py，保留别名以兼容旧调用
from utils.file_io import atomic_write_json as _atomic_write_json  # noqa: E402,F401


def apply_risk_adjustments(adjustments):
    """将风控调整写入配置文件（v8.6: 历史归档 + atomic write）"""
    config_path = os.path.join(DATA_DIR, 'risk_config.json')

    config = {}
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

    # v8.6: 归档旧版本
    _archive_old_risk_config(config_path)

    config['stop_loss_pct'] = adjustments['stop_loss_pct']
    config['take_profit_pct'] = adjustments['take_profit_pct']
    config['max_hold_days'] = adjustments['max_hold_days']
    config['position_size_mult'] = adjustments['position_size_mult']
    config['alert_only'] = adjustments.get('alert_only', False)  # v8.6: 反馈循环修复 flag
    config['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    _atomic_write_json(config_path, config)

    print(f"[FEEDBACK] Risk config updated: {config_path}")
    for action in adjustments.get('actions', []):
        print(f"[FEEDBACK]   {action}")
    return config_path


def generate_feedback_report(analysis_df, adjustments):
    """生成反馈报告"""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    is_cold = ('冷启动' in str(adjustments.get('warnings', '')) or
               '冷启动' in adjustments.get('data_source', ''))

    lines = [
        f"# 策略反馈报告 — {datetime.now().strftime('%Y-%m-%d')}",
        f"",
    ]
    if is_cold:
        lines.append(f"> ⚠️ **冷启动模式** — 使用回测模拟数据，后续将被实盘数据替换")
    lines.extend([
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 作用：衡量策略表现 → 更新权重 → 调整风控",
        f"> 数据来源：{adjustments.get('data_source', '未知')}",
        f"",
    ])

    # 策略表现
    if len(analysis_df) > 0:
        lines.extend([
            f"## 策略前瞻表现",
            f"",
            f"| 策略 | 选股数 | 5日胜率 | 平均5日收益 | 平均10日收益 |",
            f"|------|--------|---------|-------------|-------------|",
        ])
        for strat in analysis_df['策略'].unique():
            sub = analysis_df[analysis_df['策略'] == strat]
            n = len(sub)
            win5 = (sub['5日收益'] > 0).mean() if '5日收益' in sub.columns else 0
            avg5 = sub['5日收益'].mean() if '5日收益' in sub.columns else 0
            avg10 = sub['10日收益'].mean() if '10日收益' in sub.columns else 0
            lines.append(f"| {strat} | {n} | {win5:.0%} | {avg5:+.2f}% | {avg10:+.2f}% |")
        lines.append("")

    # 风控调整
    metrics = adjustments.get('metrics', {})
    lines.extend([
        f"## 交易统计",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
    ])
    for k, v in metrics.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    actions = adjustments.get('actions', [])
    if actions:
        lines.extend([
            f"## 风控自动调整",
            f"",
        ])
        for a in actions:
            lines.append(f"- {a}")
        lines.append("")

    lines.extend([
        f"## 当前风控参数",
        f"",
        f"| 参数 | 数值 |",
        f"|------|------|",
        f"| 止损 | {adjustments['stop_loss_pct']*100:+.0f}% |",
        f"| 止盈 | {adjustments['take_profit_pct']*100:+.0f}% |",
        f"| 最大持有天数 | {adjustments['max_hold_days']}日 |",
        f"| 仓位系数 | {adjustments['position_size_mult']:.1f}x |",
        f"",
        "---",
        f"*报告由 strategy_feedback.py v{SYSTEM_VERSION} 自动生成*",
    ])

    report_path = os.path.join(REPORTS_DIR, f'strategy_feedback_{datetime.now().strftime("%Y%m%d")}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"[FEEDBACK] Report: {report_path}")
    return report_path


def main():
    print(f"{'='*50}")
    print(f"  策略反馈闭环 v2 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  冷启动兼容 | 真实交易不足时自动回退")
    print(f"{'='*50}")

    # 0. 加载冷启动数据（如果存在）
    print("\n[0/5] Checking cold start data...")
    cold_start_data = load_cold_start_trades()
    if cold_start_data:
        print(f"  Cold start available: {len(cold_start_data['trades'])} virtual trades ready")
    else:
        print(f"  No cold start data found, will rely on real trade data only")

    # 1. 加载历史数据
    print("\n[1/5] Loading history data...")
    history_df = load_history_data()
    if history_df is None:
        print("[FATAL] No history data")
        return 1
    print(f"  History: {len(history_df)} rows, {history_df['日期'].min()} ~ {history_df['日期'].max()}")

    # 2. 分析历史选股的前瞻表现
    print("\n[2/5] Analyzing past picks forward returns...")
    analysis_df = analyze_past_picks(history_df, lookback_days=30)

    if len(analysis_df) > 0:
        print(f"  Analyzed {len(analysis_df)} pick-strategy pairs")
        print(f"  Date range: {analysis_df['选股日期'].min()} ~ {analysis_df['选股日期'].max()}")
        print(f"  Strategies: {analysis_df['策略'].unique().tolist()}")

        for strat in analysis_df['策略'].unique():
            sub = analysis_df[analysis_df['策略'] == strat]
            win5 = (sub['5日收益'].dropna() > 0).mean()
            avg5 = sub['5日收益'].dropna().mean()
            print(f"  {strat}: n={len(sub)}, 5d_win={win5:.0%}, 5d_avg={avg5:+.2f}%")

        generate_forward_returns_file(analysis_df)
    else:
        print("  No analyzable data (need 3+ days of history after first vote)")

    # 3. 分析风控调整（使用冷启动数据）
    print("\n[3/5] Analyzing risk adjustments...")
    adjustments = analyze_risk_adjustments(cold_start_data=cold_start_data)
    for action in adjustments.get('actions', []):
        print(f"  {action}")
    if not adjustments.get('actions'):
        print("  No adjustments needed")
    print(f"  Data source: {adjustments.get('data_source', '未知')}")

    # 4. 应用调整并生成报告
    print("\n[4/5] Applying adjustments & generating report...")
    apply_risk_adjustments(adjustments)
    generate_feedback_report(analysis_df, adjustments)

    print(f"\n[OK] Feedback loop complete")
    return 0


if __name__ == '__main__':
    sys.exit(main())
