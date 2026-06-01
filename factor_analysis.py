"""
因子分析引擎 v1 — IC / IR 计算 + 多因子权重优化

功能：
1. 从历史数据计算技术因子（动量、波动率、RSI、MACD、均线偏离等）
2. 计算未来 N 日收益（forward returns）
3. 计算各因子的 Spearman IC 和 IR
4. 基于 IR 推荐多因子加权权重
5. 输出因子健康报告 → reports/factor_analysis_YYYYMMDD.md

使用方式：
    python factor_analysis.py
    # 或在 strategy.py 中调用 recommend_weights_from_ic()
"""
import os, sys, json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy.stats import spearmanr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION

# 分析参数
HORIZONS = cfg_get('factor.horizons', [1, 5, 10])
MIN_DAYS = cfg_get('factor.min_days', 60)  # 最少需要多少天数据
TOP_N = cfg_get('factor.top_n', 100)       # 每日取前多少只股票计算（减少计算量）


def calc_technical_factors(history_df):
    """
    对历史数据逐日计算技术因子。
    返回 DataFrame，每行是 (日期, 代码) 的因子值。
    """
    hist = history_df.copy()
    hist['日期'] = pd.to_datetime(hist['日期'])
    hist['代码'] = hist['代码'].astype(str).str.zfill(6)
    hist = hist.sort_values(['代码', '日期'])

    factors = []
    for code, group in hist.groupby('代码'):
        g = group.sort_values('日期').copy()
        if len(g) < 30:
            continue

        c = g['收盘']
        v = g['成交量']
        h = g['最高']
        l = g['最低']

        # 1. 动量因子
        g['mom_5d'] = c.pct_change(5)
        g['mom_10d'] = c.pct_change(10)
        g['mom_20d'] = c.pct_change(20)

        # 2. 波动率因子
        g['volatility_20d'] = c.pct_change().rolling(20).std()

        # 3. 均线偏离
        ma5 = c.rolling(5).mean()
        ma20 = c.rolling(20).mean()
        g['ma5_bias'] = (c / ma5 - 1) * 100
        g['ma20_bias'] = (c / ma20 - 1) * 100
        g['ma5_gt_ma20'] = (ma5 > ma20).astype(int)

        # 4. RSI
        delta = c.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        g['rsi_14'] = 100 - (100 / (1 + rs))

        # 5. MACD
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        g['macd_bar'] = 2 * (dif - dea)
        g['macd_gt_0'] = (g['macd_bar'] > 0).astype(int)

        # 6. 成交量因子
        vol_ma20 = v.rolling(20).mean()
        g['vol_ratio'] = v / vol_ma20.replace(0, np.nan)

        # 7. ATR
        tr1 = h - l
        tr2 = abs(h - c.shift(1))
        tr3 = abs(l - c.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        g['atr_14'] = tr.rolling(14).mean()
        g['atr_pct'] = g['atr_14'] / c * 100

        # 8. 振幅
        g['amplitude'] = ((h - l) / c.shift(1)) * 100

        factor_cols = [
            '日期', '代码', '名称',
            'mom_5d', 'mom_10d', 'mom_20d',
            'volatility_20d', 'ma5_bias', 'ma20_bias', 'ma5_gt_ma20',
            'rsi_14', 'macd_bar', 'macd_gt_0', 'vol_ratio', 'atr_pct', 'amplitude'
        ]
        available = [c for c in factor_cols if c in g.columns]
        factors.append(g[available])

    if not factors:
        return pd.DataFrame()
    return pd.concat(factors, ignore_index=True)


def calc_forward_returns(history_df, horizons=HORIZONS):
    """
    计算未来 N 日收益。
    返回 DataFrame，列：日期, 代码, ret_1d, ret_5d, ret_10d
    """
    hist = history_df.copy()
    hist['日期'] = pd.to_datetime(hist['日期'])
    hist['代码'] = hist['代码'].astype(str).str.zfill(6)
    hist = hist.sort_values(['代码', '日期'])

    results = []
    for code, group in hist.groupby('代码'):
        g = group.sort_values('日期').copy()
        c = g['收盘']
        for d in horizons:
            g[f'ret_{d}d'] = c.shift(-d) / c - 1
        results.append(g[['日期', '代码'] + [f'ret_{d}d' for d in horizons]])

    return pd.concat(results, ignore_index=True)


def calc_ic(factor_df, returns_df, horizon=5, factor_cols=None):
    """
    计算指定 horizon 下各因子的 Spearman IC。
    返回 dict: {factor_name: (ic_mean, ic_std, ir, p_value)}
    """
    if factor_cols is None:
        factor_cols = [c for c in factor_df.columns if c not in ['日期', '代码', '名称']]

    merged = pd.merge(factor_df, returns_df[['日期', '代码', f'ret_{horizon}d']], on=['日期', '代码'], how='inner')
    merged = merged.dropna(subset=[f'ret_{horizon}d'])

    # 按日期分组，计算每日截面 IC
    daily_ics = {f: [] for f in factor_cols}
    for date, sub in merged.groupby('日期'):
        if len(sub) < 30:  # 截面样本太少则跳过
            continue
        for f in factor_cols:
            sub_f = sub[[f, f'ret_{horizon}d']].dropna()
            if len(sub_f) < 10:
                continue
            ic, p = spearmanr(sub_f[f], sub_f[f'ret_{horizon}d'])
            if not np.isnan(ic):
                daily_ics[f].append(ic)

    result = {}
    for f in factor_cols:
        ics = np.array(daily_ics[f])
        if len(ics) < 20:
            result[f] = {'ic_mean': np.nan, 'ic_std': np.nan, 'ir': np.nan, 'p_value': np.nan, 'days': len(ics)}
            continue
        ic_mean = np.mean(ics)
        ic_std = np.std(ics)
        ir = ic_mean / ic_std if ic_std > 0 else 0
        # p-value: t-test for mean != 0
        from scipy.stats import t as t_dist
        t_stat = ic_mean / (ic_std / np.sqrt(len(ics)))
        p_val = 2 * (1 - t_dist.cdf(abs(t_stat), len(ics) - 1))
        result[f] = {
            'ic_mean': round(ic_mean, 4),
            'ic_std': round(ic_std, 4),
            'ir': round(ir, 4),
            'p_value': round(p_val, 4),
            'days': len(ics)
        }
    return result


def recommend_weights(ic_results, min_ir=0.3, max_weight=0.40):
    """
    基于 IR 推荐因子权重。
    规则：
    - IR < 0.3 的因子权重为 0（无效因子）
    - 按 IR 的平方加权（IR^2 反映信息比率的稳定性）
    - 最大单因子权重不超过 40%

    返回 dict: {factor: weight}
    """
    valid = {f: r for f, r in ic_results.items()
             if r.get('ir', 0) >= min_ir and r.get('p_value', 1) < 0.10}

    if not valid:
        print('[FACTOR] No valid factors found, fallback to equal weights')
        # 回退：等权
        all_factors = [f for f in ic_results.keys()]
        n = len(all_factors)
        return {f: round(1/n, 4) for f in all_factors}

    # IR^2 加权
    ir2 = {f: max(r['ir'], 0) ** 2 for f, r in valid.items()}
    total = sum(ir2.values())
    weights = {f: w / total for f, w in ir2.items()}

    # 最大权重限制
    for f in list(weights.keys()):
        if weights[f] > max_weight:
            excess = weights[f] - max_weight
            weights[f] = max_weight
            others = [k for k in weights.keys() if k != f]
            if others:
                for o in others:
                    weights[o] += excess / len(others)

    return {f: round(w, 4) for f, w in weights.items()}


def save_weights(weights, horizon=5):
    """将推荐权重保存到 data/factor_weights.json，供 strategy.py 读取。"""
    path = os.path.join(DATA_DIR, 'factor_weights.json')
    data = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'horizon': horizon,
        'weights': weights
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[FACTOR] Weights saved: {path}')


def load_weights():
    """加载最新权重，供 strategy.py 调用。"""
    path = os.path.join(DATA_DIR, 'factor_weights.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def generate_report(ic_results, weights, horizon=5):
    """生成 Markdown 报告。"""
    lines = [
        f'# 因子分析报告 - {datetime.now().strftime("%Y-%m-%d")}',
        '',
        f'> 前瞻窗口：{horizon} 个交易日',
        f'> 计算日期：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        '## 因子 IC / IR 统计',
        '',
        '| 因子 | IC均值 | IC标准差 | IR | p-value | 样本天数 | 状态 |',
        '|------|--------|----------|-----|---------|----------|------|',
    ]

    for f, r in sorted(ic_results.items(), key=lambda x: x[1].get('ir', 0), reverse=True):
        status = '有效' if r.get('ir', 0) >= 0.3 and r.get('p_value', 1) < 0.10 else '无效'
        lines.append(
            f"| {f} | {r.get('ic_mean', 'N/A')} | {r.get('ic_std', 'N/A')} | "
            f"{r.get('ir', 'N/A')} | {r.get('p_value', 'N/A')} | {r.get('days', 'N/A')} | {status} |"
        )

    lines.extend([
        '',
        '## 推荐权重（基于 IR² 加权）',
        '',
        '| 因子 | 权重 |',
        '|------|------|',
    ])
    for f, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        lines.append(f'| {f} | {w*100:.1f}% |')

    lines.extend([
        '',
        '---',
        f'*报告由 factor_analysis.py v{SYSTEM_VERSION} 自动生成*',
    ])

    report_path = os.path.join(RESULTS_DIR, f'factor_analysis_{datetime.now().strftime("%Y%m%d")}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[FACTOR] Report: {report_path}')
    return report_path


def main():
    print(f"{'='*50}")
    print(f"  因子分析引擎 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    hist_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(hist_file):
        print('[FATAL] history.csv not found.')
        return 1

    hist = pd.read_csv(hist_file, dtype={'代码': str})
    if len(hist) == 0:
        print('[FATAL] Empty history data.')
        return 1

    print(f'[FACTOR] History loaded: {len(hist)} rows')

    # 1. 计算因子
    print('\n[1/4] Calculating technical factors...')
    factor_df = calc_technical_factors(hist)
    print(f'  Factors: {len(factor_df)} rows, {len(factor_df.columns)} cols')

    # 2. 计算 forward returns
    print('\n[2/4] Calculating forward returns...')
    returns_df = calc_forward_returns(hist)
    print(f'  Returns: {len(returns_df)} rows')

    # 3. 计算 IC（以 5 日为主要参考）
    print('\n[3/4] Calculating IC / IR...')
    ic_results = calc_ic(factor_df, returns_df, horizon=5)
    for f, r in sorted(ic_results.items(), key=lambda x: x[1].get('ir', 0), reverse=True):
        print(f"  {f}: IC={r.get('ic_mean'):.4f}, IR={r.get('ir'):.4f}, p={r.get('p_value'):.4f}")

    # 4. 推荐权重
    print('\n[4/4] Recommending weights...')
    weights = recommend_weights(ic_results)
    for f, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        print(f'  {f}: {w*100:.1f}%')

    save_weights(weights, horizon=5)
    generate_report(ic_results, weights, horizon=5)

    print('\n[OK] Factor analysis complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
