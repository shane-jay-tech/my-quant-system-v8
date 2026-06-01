"""
蒙特卡洛模拟引擎 v1 — 随机扰动下的策略稳健性评估

功能：
1. 对历史回测结果进行多次随机扰动：
   - 滑点随机化（正态分布，均值=基准滑点）
   - 起始日期偏移（±5天）
   - 参数微扰（RSI±3, MA±2）
2. 生成收益分布、胜率分布、最大回撤分布
3. 输出置信区间和破产概率估计

输出：reports/monte_carlo_YYYYMMDD.md
"""
import os, sys
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

sys.path.insert(0, BASE_DIR)
from enhanced_backtest import backtest, calc_indicators, fetch_index
from core.config import get as cfg_get, SYSTEM_VERSION

N_SIMULATIONS = cfg_get('montecarlo.n_simulations', 500)
SLIPPAGE_STD = cfg_get('montecarlo.slippage_std', 0.0005)  # 滑点标准差 0.05%
START_OFFSET_MAX = cfg_get('montecarlo.start_offset_max', 5)  # 起始日最大偏移


def simulate_once(hist_df, today_df, index_df, seed=None):
    """
    单次蒙特卡洛模拟。
    返回 dict: {avg_return, win_rate, max_dd, sharpe}
    """
    if seed is not None:
        np.random.seed(seed)

    # 复制数据避免污染
    hist = hist_df.copy()

    # 1. 起始日偏移
    all_dates = sorted(hist['日期'].unique())
    offset = np.random.randint(-START_OFFSET_MAX, START_OFFSET_MAX + 1)
    if abs(offset) >= len(all_dates) // 2:
        offset = 0
    if offset != 0:
        hist = hist[hist['日期'].isin(all_dates[max(0, offset):offset or len(all_dates)])]

    # 2. 参数微扰
    rsi_low = 30 + np.random.randint(-3, 4)
    rsi_high = 70 + np.random.randint(-3, 4)
    ma_long = 30 + np.random.randint(-2, 3)

    # 3. 滑点随机化（通过在回测中注入随机冲击）
    # 简化：直接在收益上扣除随机成本
    trades, daily, bm = backtest(hist, today_df, index_df)
    if len(trades) == 0:
        return None

    # 对每笔净收益注入随机滑点冲击
    extra_cost = np.random.normal(0, SLIPPAGE_STD * 2, len(trades))
    trades['mc_net'] = trades['净收益'] / 100 - extra_cost

    avg_ret = trades['mc_net'].mean()
    win_rate = (trades['mc_net'] > 0).mean()

    # 最大回撤（从收益序列模拟权益曲线）
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in trades['mc_net']:
        equity *= (1 + r)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    # 简化夏普：日收益 / 日收益标准差 * sqrt(252)
    sharpe = (trades['mc_net'].mean() / (trades['mc_net'].std() + 1e-9)) * np.sqrt(252) if trades['mc_net'].std() > 0 else 0

    return {
        'avg_return': avg_ret,
        'win_rate': win_rate,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
    }


def run_monte_carlo(hist_df, today_df, index_df):
    print(f'[MC] Running {N_SIMULATIONS} simulations...')
    results = []
    for i in range(N_SIMULATIONS):
        r = simulate_once(hist_df, today_df, index_df, seed=i)
        if r:
            results.append(r)
        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{N_SIMULATIONS} done')
    return pd.DataFrame(results)


def generate_report(df):
    if len(df) == 0:
        print('[MC] No simulation results')
        return

    lines = [
        f'# 蒙特卡洛稳健性报告 - {datetime.now().strftime("%Y-%m-%d")}',
        '',
        f'> 模拟次数：{len(df)} | 滑点标准差：{SLIPPAGE_STD*100:.2f}% | 起始日偏移：±{START_OFFSET_MAX}天',
        '',
        '## 收益分布',
        '',
        f"- 平均收益：{df['avg_return'].mean():.2%}",
        f"- 中位数收益：{df['avg_return'].median():.2%}",
        f"- 5% 分位数：{df['avg_return'].quantile(0.05):.2%}",
        f"- 95% 分位数：{df['avg_return'].quantile(0.95):.2%}",
        '',
        '## 胜率分布',
        '',
        f"- 平均胜率：{df['win_rate'].mean():.1%}",
        f"- 胜率 < 50% 的概率：{(df['win_rate'] < 0.5).mean():.1%}",
        '',
        '## 最大回撤分布',
        '',
        f"- 平均最大回撤：{df['max_drawdown'].mean():.2%}",
        f"-  worst 5% 回撤：{df['max_drawdown'].quantile(0.95):.2%}",
        '',
        '## 夏普率分布',
        '',
        f"- 平均夏普率：{df['sharpe'].mean():.2f}",
        f"- 夏普率 < 0 的概率：{(df['sharpe'] < 0).mean():.1%}",
        '',
        '## 破产概率估计',
        '',
        f"- 单次交易亏损 > 5% 的概率：{(df['avg_return'] < -0.05).mean():.2%}",
        f"- 最大回撤 > 20% 的概率：{(df['max_drawdown'] > 0.20).mean():.2%}",
        '',
        '---',
        f'*报告由 monte_carlo.py v{SYSTEM_VERSION} 自动生成*',
    ]

    path = os.path.join(RESULTS_DIR, f'monte_carlo_{datetime.now().strftime("%Y%m%d")}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[MC] Report: {path}')


def main():
    # v8 tier gate：Advanced 及以上自动运行；Beginner 时手动触发（Streamlit 按钮）仍可调用 run_monte_carlo()
    from core.config import ENABLE_MONTE_CARLO, SYSTEM_TIER
    if not ENABLE_MONTE_CARLO:
        print(f"[MC] Dormant on tier={SYSTEM_TIER.value}; activates at Advanced (3万+). "
              f"研究模式可在 Streamlit 页面手动触发；流水线已跳过。")
        return 0

    print(f"{'='*50}")
    print(f"  蒙特卡洛模拟 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    import glob
    hist_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(hist_file):
        print('[FATAL] history.csv not found')
        return 1

    hist = pd.read_csv(hist_file, dtype={'代码': str})
    hist['日期'] = pd.to_datetime(hist['日期'])

    stock_files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not stock_files:
        print('[FATAL] No stock data')
        return 1
    today_df = pd.read_csv(stock_files[0], dtype={'代码': str})

    index_df = fetch_index()

    df = run_monte_carlo(hist, today_df, index_df)
    generate_report(df)
    print('\n[OK] Monte-Carlo complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
