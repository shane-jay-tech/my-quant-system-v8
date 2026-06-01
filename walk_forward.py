"""
Walk-Forward 验证引擎 v1 — 滚动训练/测试窗口 + 参数稳定性分析

功能：
1. 将历史数据切分为多个滚动窗口（训练集 + 测试集）
2. 在训练集上网格搜索最优参数（MA_LONG, RSI_LOW/HIGH）
3. 在测试集上验证样本外表现
4. 统计参数稳定性和过拟合风险

输出：reports/walk_forward_YYYYMMDD.md
"""
import os, sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import product

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

sys.path.insert(0, BASE_DIR)
from enhanced_backtest import backtest, calc_indicators, fetch_index
from cost_model import get_cost_by_mcap, compute_dynamic_notional
from core.config import get as cfg_get, SYSTEM_VERSION

# Reproducibility snapshot via the shared hub (best-effort; WF still runs without it).
try:
    sys.path.insert(0, os.path.dirname(BASE_DIR))  # D:\code on path
    from scripts.common import snapshot as _snapshot  # type: ignore
except Exception:  # pragma: no cover
    _snapshot = None

TRAIN_DAYS = cfg_get('walkforward.train_days', 120)
TEST_DAYS = cfg_get('walkforward.test_days', 30)
STEP_DAYS = cfg_get('walkforward.step_days', 30)
USE_REAL_COST = cfg_get('walkforward.use_real_cost', True)
SIMPLIFIED_COST = cfg_get('walkforward.simplified_cost', 0.002)  # legacy fallback

# 参数网格
PARAM_GRID = {
    'MA_LONG': [20, 25, 30],
    'RSI_LOW': [25, 30, 35],
    'RSI_HIGH': [65, 70, 75],
}


def _calc_indicators_with_ma(hist_df, ma_long):
    """Round-2 修复（2026-05-30）：本地化 MA 计算，让 ma_long 真正生效。
    Why: 旧版调 enhanced_backtest.calc_indicators 用全局 MA_LONG=30 写到 'MA20' 列，
    walk_forward 网格搜索 MA_LONG=[20,25,30] 永远查同一列 → grid search 退化为 RSI×RSI 二维。
    """
    hist = hist_df.copy()
    hist['日期'] = pd.to_datetime(hist['日期'])
    hist = hist.sort_values(['代码', '日期'])
    results = []
    for code, group in hist.groupby('代码'):
        g = group.sort_values('日期').copy()
        c = g['收盘']
        g['MA5'] = c.rolling(5).mean()
        g['MA_long'] = c.rolling(ma_long).mean()
        d = c.diff()
        gain, loss = d.clip(lower=0), (-d).clip(lower=0)
        g['RSI'] = 100 - 100 / (1 + gain.ewm(alpha=1/14, adjust=False).mean()
                                / loss.ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan))
        g['ret_5d'] = c.pct_change(5)
        results.append(g)
    return pd.concat(results, ignore_index=True)


def run_backtest_window(hist_df, today_df, index_df, params, test_dates):
    """
    在给定日期窗口内运行简化回测，返回平均净收益。
    """
    ma_long = params['MA_LONG']
    rsi_low = params['RSI_LOW']
    rsi_high = params['RSI_HIGH']

    hist = _calc_indicators_with_ma(hist_df, ma_long)
    # 简化：只取 test_dates 内的信号
    trades = []
    for td in test_dates:
        data = hist[hist['日期'] <= td]
        lidx = data.groupby('代码')['日期'].idxmax()
        latest = data.loc[lidx]
        latest = latest[latest['日期'] == td].copy()
        if len(latest) == 0:
            continue

        # 基础筛选 — 用 ma_long 决定的 MA_long 列
        cond = (
            (latest['收盘'] > latest['MA5']) & (latest['MA5'] > latest['MA_long']) &
            (latest['RSI'] > rsi_low) & (latest['RSI'] < rsi_high)
        )
        picks = latest[cond].copy()
        if len(picks) == 0:
            continue

        # 简单动量排序
        picks['momentum'] = picks['ret_5d'].fillna(0)
        top = picks.nlargest(5, 'momentum')

        for _, p in top.iterrows():
            code = p['代码']
            entry = p['收盘']
            # 持有5日
            td_idx = test_dates.index(td)
            exit_idx = td_idx + 5
            if exit_idx >= len(test_dates):
                continue
            exit_td = test_dates[exit_idx]
            exit_row = hist[(hist['代码'] == code) & (hist['日期'] == exit_td)]
            if len(exit_row) == 0:
                continue
            exit_px = exit_row.iloc[0]['收盘']
            gross = exit_px / entry - 1
            # v8 Phase 1.2: 真实成本（cost_model 单一真相源）
            # Why: 0.002 简化成本会让 grid search 偏向高频参数，1200 元真实成本下这些
            # 参数会把本金当手续费送掉。USE_REAL_COST=True 默认开启。
            if USE_REAL_COST:
                # 用 5 只持仓 + 震荡市做保守估计（picks_count 在 walk_forward 里固定 5）
                dyn_notional = compute_dynamic_notional('震荡', 5)
                trade_cost = get_cost_by_mcap(p.get('mcap', 0), notional=dyn_notional)
            else:
                trade_cost = SIMPLIFIED_COST
            net = gross - trade_cost
            trades.append(net)

    if not trades:
        return -999, 0
    return np.mean(trades), len(trades)


def walk_forward(hist_df, today_df, index_df):
    all_dates = sorted(hist_df['日期'].unique())
    if len(all_dates) < TRAIN_DAYS + TEST_DAYS:
        print('[WF] Insufficient history data')
        return []

    windows = []
    start = 0
    while start + TRAIN_DAYS + TEST_DAYS <= len(all_dates):
        train_dates = all_dates[start:start + TRAIN_DAYS]
        test_dates = all_dates[start + TRAIN_DAYS:start + TRAIN_DAYS + TEST_DAYS]
        windows.append((train_dates, test_dates))
        start += STEP_DAYS

    results = []
    for i, (train_dates, test_dates) in enumerate(windows):
        print(f'\n[WF] Window {i+1}/{len(windows)}: train {len(train_dates)}d, test {len(test_dates)}d')
        train_hist = hist_df[hist_df['日期'].isin(train_dates)]
        test_hist = hist_df[hist_df['日期'].isin(test_dates)]

        # 网格搜索
        best_params = None
        best_score = -999
        grid_results = []
        for ma_long, rsi_low, rsi_high in product(PARAM_GRID['MA_LONG'], PARAM_GRID['RSI_LOW'], PARAM_GRID['RSI_HIGH']):
            score, n = run_backtest_window(train_hist, today_df, index_df,
                                           {'MA_LONG': ma_long, 'RSI_LOW': rsi_low, 'RSI_HIGH': rsi_high},
                                           train_dates[-30:])  # 训练集内最后30天验证
            grid_results.append({
                'MA_LONG': ma_long, 'RSI_LOW': rsi_low, 'RSI_HIGH': rsi_high,
                'score': score, 'trades': n
            })
            if score > best_score:
                best_score = score
                best_params = {'MA_LONG': ma_long, 'RSI_LOW': rsi_low, 'RSI_HIGH': rsi_high}

        print(f'  Best train params: {best_params}, score={best_score:.4f}')

        # 测试集验证
        if best_params:
            test_score, test_n = run_backtest_window(test_hist, today_df, index_df, best_params, test_dates)
        else:
            test_score, test_n = -999, 0

        results.append({
            'window': i + 1,
            'train_start': str(train_dates[0]),
            'train_end': str(train_dates[-1]),
            'test_start': str(test_dates[0]),
            'test_end': str(test_dates[-1]),
            'best_params': best_params,
            'train_score': round(best_score, 4),
            'test_score': round(test_score, 4),
            'test_trades': test_n,
            'overfit_ratio': round(best_score / (test_score + 1e-9), 2) if test_score > 0 else None,
        })

    return results


def build_wf_snapshot(hist_df, results):
    """盖一个复现戳：把"输入数据指纹 + WF 参数 + 结果摘要"打包，便于事后审计
    "这份过拟合结论到底基于哪版数据/哪组参数"。无 snapshot 模块时返回 None。"""
    if _snapshot is None:
        return None
    params = {
        "train_days": TRAIN_DAYS, "test_days": TEST_DAYS, "step_days": STEP_DAYS,
        "param_grid": PARAM_GRID, "use_real_cost": USE_REAL_COST,
        "system_version": SYSTEM_VERSION,
    }
    summary = {
        "windows": len(results),
        "avg_overfit_ratio": round(
            np.mean([r["overfit_ratio"] for r in results if r.get("overfit_ratio") not in (None, "N/A")] or [0]), 4),
        "avg_test_score": round(np.mean([r["test_score"] for r in results] or [0]), 4),
    }
    try:
        return _snapshot.make_snapshot(data=hist_df, params=params, result=summary)
    except Exception:
        return None


def generate_report(results, wf_snapshot=None):
    if not results:
        return

    lines = [
        f'# Walk-Forward 验证报告 - {datetime.now().strftime("%Y-%m-%d")}',
        '',
        f'> 训练窗口：{TRAIN_DAYS} 天 | 测试窗口：{TEST_DAYS} 天 | 步长：{STEP_DAYS} 天',
        '',
        '## 各窗口表现',
        '',
        '| 窗口 | 训练期 | 测试期 | 最优参数 | 训练收益 | 测试收益 | 交易数 | 过拟合比 |',
        '|------|--------|--------|----------|----------|----------|--------|----------|',
    ]

    for r in results:
        params_str = f"MA{r['best_params']['MA_LONG']}/RSI{r['best_params']['RSI_LOW']}-{r['best_params']['RSI_HIGH']}" if r['best_params'] else 'N/A'
        lines.append(
            f"| {r['window']} | {r['train_start']}~{r['train_end'][-5:]} | "
            f"{r['test_start']}~{r['test_end'][-5:]} | {params_str} | "
            f"{r['train_score']:.2%} | {r['test_score']:.2%} | {r['test_trades']} | {r['overfit_ratio'] or 'N/A'} |"
        )

    # 统计参数稳定性
    param_counts = {}
    for r in results:
        if r['best_params']:
            key = f"MA{r['best_params']['MA_LONG']}/RSI{r['best_params']['RSI_LOW']}-{r['best_params']['RSI_HIGH']}"
            param_counts[key] = param_counts.get(key, 0) + 1

    lines.extend([
        '',
        '## 参数稳定性',
        '',
        '| 参数组合 | 出现次数 | 占比 |',
        '|----------|----------|------|',
    ])
    total = len(results)
    for k, v in sorted(param_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f'| {k} | {v} | {v/total*100:.0f}% |')

    if wf_snapshot:
        lines.extend([
            '', '## 复现快照',
            '',
            f'- 快照 ID：`{wf_snapshot["snapshot_id"]}`',
            f'- 输入数据指纹：`{wf_snapshot["data_hash"]}`（history.csv 内容哈希）',
            f'- 参数指纹：`{wf_snapshot["param_hash"]}`',
            '- 用途：核对"本次过拟合结论基于哪版数据/参数"；数据或参数一变，指纹即变。',
        ])

    lines.extend(['', '---', f'*报告由 walk_forward.py v{SYSTEM_VERSION} 自动生成*'])

    path = os.path.join(RESULTS_DIR, f'walk_forward_{datetime.now().strftime("%Y%m%d")}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[WF] Report: {path}')

    # 旁车 JSON：完整快照（含结果摘要），供程序化审计/比对
    if wf_snapshot and _snapshot is not None:
        snap_path = os.path.join(RESULTS_DIR, f'walk_forward_{datetime.now().strftime("%Y%m%d")}.snapshot.json')
        try:
            _snapshot.export(wf_snapshot, snap_path)
            print(f'[WF] Snapshot: {snap_path}')
        except Exception:
            pass


def main():
    # v8 tier gate：Advanced 及以上自动运行；Beginner 时手动触发仍可调用 walk_forward()
    from core.config import ENABLE_WALK_FORWARD, SYSTEM_TIER
    if not ENABLE_WALK_FORWARD:
        print(f"[WF] Dormant on tier={SYSTEM_TIER.value}; activates at Advanced (3万+). "
              f"研究模式可在 Streamlit 页面手动触发；流水线已跳过。")
        return 0

    print(f"{'='*50}")
    print(f"  Walk-Forward 验证 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    hist_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(hist_file):
        print('[FATAL] history.csv not found')
        return 1

    hist = pd.read_csv(hist_file, dtype={'代码': str})
    hist['日期'] = pd.to_datetime(hist['日期'])

    # 加载最新 stock 数据用于流通市值过滤
    import glob
    stock_files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not stock_files:
        print('[FATAL] No stock data')
        return 1
    today_df = pd.read_csv(stock_files[0], dtype={'代码': str})

    index_df = fetch_index()

    results = walk_forward(hist, today_df, index_df)
    generate_report(results, wf_snapshot=build_wf_snapshot(hist, results))
    print('\n[OK] Walk-Forward complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
