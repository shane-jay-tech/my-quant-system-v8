"""
组合风控引擎 v1 — 相关性、VaR、CVaR、回撤硬止损、波动率目标

功能：
1. 持仓相关性矩阵监控
2. 组合 VaR / CVaR（历史模拟法 + 参数法）
3. 净值回撤硬止损（回撤 > 阈值时强制降仓）
4. 波动率目标（组合年化波动率超标时降仓）
5. 换手率控制（单日换手上限）

使用方式：
    在 sim_trade.py / position_sizer.py 中导入并调用
"""
import os, sys, json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get

# 风控参数
DRAWDOWN_LIMIT = cfg_get('risk.drawdown_limit', 0.10)       # 最大回撤 10%
VOL_TARGET = cfg_get('risk.vol_target', 0.20)               # 年化波动率目标 20%
MAX_TURNOVER = cfg_get('risk.max_turnover', 0.50)          # 单日最大换手 50%
MAX_PAIRWISE_CORR = cfg_get('risk.max_pairwise_corr', 0.70) # 持仓最大两两相关


def load_history_returns(codes, lookback=60):
    """
    从历史数据加载指定股票的日收益率矩阵。
    返回 DataFrame: index=日期, columns=代码
    """
    hist_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(hist_file):
        return None

    hist = pd.read_csv(hist_file, dtype={'代码': str})
    hist['日期'] = pd.to_datetime(hist['日期'])
    hist['代码'] = hist['代码'].astype(str).str.zfill(6)
    hist = hist.sort_values(['代码', '日期'])

    # 取最近 lookback 天
    latest_date = hist['日期'].max()
    cutoff = latest_date - timedelta(days=lookback * 2)  # 留足交易日
    hist = hist[hist['日期'] >= cutoff]

    returns = []
    for code in codes:
        sub = hist[hist['代码'] == code].sort_values('日期').tail(lookback)
        if len(sub) < lookback * 0.8:
            continue
        sub = sub.set_index('日期')['收盘']
        sub = sub[~sub.index.duplicated(keep='first')]
        sub = sub.pct_change().dropna()
        sub.name = code
        returns.append(sub)

    if not returns:
        return None
    df = pd.concat(returns, axis=1)
    return df.dropna(how='all')


def calc_correlation_matrix(codes, lookback=60):
    """
    计算持仓股票的相关性矩阵。
    返回 dict: {
        'matrix': DataFrame,
        'max_corr': float,
        'max_pair': tuple,
        'warning': bool
    }
    """
    ret = load_history_returns(codes, lookback)
    if ret is None or len(ret.columns) < 2:
        return None

    corr = ret.corr()
    # 提取上三角（不含对角线）
    triu = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    max_val = triu.stack().max()
    max_pair = triu.stack().idxmax()

    return {
        'matrix': corr,
        'max_corr': round(max_val, 4),
        'max_pair': max_pair,
        'warning': max_val > MAX_PAIRWISE_CORR,
    }


def calc_portfolio_var(returns_matrix, weights, confidence=0.95, method='parametric'):
    """
    计算组合 VaR。
    method='parametric': 假设正态分布
    method='historical': 历史模拟法

    返回：VaR（正数表示亏损金额占组合净值的比例）
    """
    if returns_matrix is None or len(weights) == 0:
        return None

    w = np.array(weights)
    w = w / w.sum()

    if method == 'parametric':
        # 组合收益均值和方差
        mean = returns_matrix.mean().values
        cov = returns_matrix.cov().values
        port_mean = np.dot(w, mean)
        port_var = np.dot(w, np.dot(cov, w))
        port_std = np.sqrt(port_var)
        z = 1.645 if confidence <= 0.95 else 2.33  # 95% / 99%
        var = abs(port_mean - z * port_std)
    else:
        # 历史模拟法
        port_rets = returns_matrix.dot(w)
        var = abs(np.percentile(port_rets.dropna(), (1 - confidence) * 100))

    return round(var, 6)


def calc_portfolio_cvar(returns_matrix, weights, confidence=0.95):
    """
    计算组合 CVaR（Expected Shortfall）。
    返回：CVaR（正数）
    """
    if returns_matrix is None or len(weights) == 0:
        return None

    w = np.array(weights)
    w = w / w.sum()
    port_rets = returns_matrix.dot(w).dropna()
    threshold = np.percentile(port_rets, (1 - confidence) * 100)
    cvar = abs(port_rets[port_rets <= threshold].mean())
    return round(cvar, 6)


def check_drawdown(state):
    """
    检查组合回撤。
    读取权益曲线，计算当前净值相对历史最高点的回撤。

    返回 dict: {
        'current_drawdown': float,
        'breached': bool,
        'action': str   # 'normal' / 'warning' / 'force_reduce'
    }
    """
    equity_file = os.path.join(SIM_DIR, 'equity_curve.csv')
    if not os.path.exists(equity_file):
        return {'current_drawdown': 0.0, 'breached': False, 'action': 'normal'}

    try:
        df = pd.read_csv(equity_file)
        if '总权益' not in df.columns or len(df) < 2:
            return {'current_drawdown': 0.0, 'breached': False, 'action': 'normal'}

        peak = df['总权益'].cummax().iloc[-1]
        current = df['总权益'].iloc[-1]
        dd = (peak - current) / peak if peak > 0 else 0

        if dd >= DRAWDOWN_LIMIT:
            return {
                'current_drawdown': round(dd * 100, 2),
                'breached': True,
                'action': 'force_reduce',
                'message': f'回撤 {dd*100:.1f}% > 阈值 {DRAWDOWN_LIMIT*100:.0f}%，强制降仓至 20%'
            }
        elif dd >= DRAWDOWN_LIMIT * 0.7:
            return {
                'current_drawdown': round(dd * 100, 2),
                'breached': False,
                'action': 'warning',
                'message': f'回撤 {dd*100:.1f}% 接近阈值，建议减仓'
            }
        else:
            return {
                'current_drawdown': round(dd * 100, 2),
                'breached': False,
                'action': 'normal'
            }
    except Exception as e:
        print(f'[RISK] Drawdown check error: {e}')
        return {'current_drawdown': 0.0, 'breached': False, 'action': 'normal'}


def check_volatility_target(state, target_vol=VOL_TARGET):
    """
    基于权益曲线计算组合实际年化波动率，与目标比较。
    """
    equity_file = os.path.join(SIM_DIR, 'equity_curve.csv')
    if not os.path.exists(equity_file):
        return {'current_vol': 0.0, 'breached': False}

    try:
        df = pd.read_csv(equity_file)
        if '总权益' not in df.columns or len(df) < 20:
            return {'current_vol': 0.0, 'breached': False}

        ret = df['总权益'].pct_change().dropna()
        if len(ret) < 10:
            return {'current_vol': 0.0, 'breached': False}

        ann_vol = ret.std() * np.sqrt(252)
        return {
            'current_vol': round(ann_vol * 100, 2),
            'breached': ann_vol > target_vol,
            'action': 'force_reduce' if ann_vol > target_vol else 'normal',
            'message': f'年化波动率 {ann_vol*100:.1f}% > 目标 {target_vol*100:.0f}%，建议降仓' if ann_vol > target_vol else ''
        }
    except Exception as e:
        print(f'[RISK] Volatility check error: {e}')
        return {'current_vol': 0.0, 'breached': False}


def check_turnover(state, new_orders):
    """
    检查单日换手率。
    turnover = 当日卖出金额 + 当日买入金额 / 组合总市值

    返回 dict: {'turnover': float, 'breached': bool}
    """
    position_value = sum(p['current_price'] * p['shares'] for p in state['positions'])
    equity = state['cash'] + position_value
    if equity <= 0:
        return {'turnover': 0.0, 'breached': False}

    buy_amount = sum(o.get('金额', 0) for o in new_orders)
    # 假设当日可能卖出全部持仓（保守估计）
    sell_amount = position_value
    turnover = (buy_amount + sell_amount) / equity

    return {
        'turnover': round(turnover * 100, 2),
        'breached': turnover > MAX_TURNOVER,
        'action': 'block_new' if turnover > MAX_TURNOVER else 'normal',
        'message': f'预计换手率 {turnover*100:.1f}% > 上限 {MAX_TURNOVER*100:.0f}%，限制新买入' if turnover > MAX_TURNOVER else ''
    }


def generate_risk_report(state, new_orders=None):
    """
    生成组合风险快照，供每日流水线调用。
    返回 dict，包含所有风控指标。
    """
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'drawdown': check_drawdown(state),
        'volatility': check_volatility_target(state),
    }

    codes = [p['code'] for p in state['positions']]
    if len(codes) >= 2:
        corr = calc_correlation_matrix(codes)
        if corr:
            report['correlation'] = {
                'max_corr': corr['max_corr'],
                'max_pair': corr['max_pair'],
                'warning': corr['warning'],
            }
            # 如果相关性过高，计算 VaR/CVaR
            if corr['warning']:
                ret_mat = load_history_returns(codes)
                if ret_mat is not None:
                    n = len(codes)
                    weights = [1/n] * n
                    report['var_95'] = calc_portfolio_var(ret_mat, weights, 0.95)
                    report['cvar_95'] = calc_portfolio_cvar(ret_mat, weights, 0.95)
        else:
            report['correlation'] = None
    else:
        report['correlation'] = None

    if new_orders:
        report['turnover'] = check_turnover(state, new_orders)
    else:
        report['turnover'] = {'turnover': 0.0, 'breached': False}

    # 汇总建议
    actions = []
    if report['drawdown']['action'] == 'force_reduce':
        actions.append(report['drawdown']['message'])
    if report['volatility'].get('action') == 'force_reduce':
        actions.append(report['volatility']['message'])
    if report.get('correlation', {}).get('warning'):
        actions.append(f'持仓相关性过高: {report["correlation"]["max_pair"]}={report["correlation"]["max_corr"]}')
    if report.get('turnover', {}).get('breached'):
        actions.append(report['turnover']['message'])

    report['recommended_actions'] = actions
    return report


def save_risk_report(report):
    path = os.path.join(DATA_DIR, 'risk_report.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'[RISK] Risk report saved: {path}')


# ---------- 调试入口 ----------
if __name__ == '__main__':
    # v8 tier gate：只在 PRO/AUTO 运行；函数体保持可导入，Beginner/Advanced 时仅入口休眠
    from core.config import ENABLE_PORTFOLIO_RISK, SYSTEM_TIER
    if not ENABLE_PORTFOLIO_RISK:
        print(f"[RISK] Dormant on tier={SYSTEM_TIER.value}; activates at Pro (20万+). "
              f"CVaR/VaR/相关性 计算函数仍可手动 import 调用，仅自动流水线跳过。")
        sys.exit(0)

    print(f"{'='*50}")
    print(f"  组合风控引擎测试 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    # 模拟账户状态
    test_state = {
        'cash': 50000,
        'positions': [
            {'code': '000001', 'name': '平安银行', 'current_price': 12.5, 'shares': 1000},
            {'code': '000002', 'name': '万科A', 'current_price': 18.2, 'shares': 800},
            {'code': '600519', 'name': '贵州茅台', 'current_price': 1750.0, 'shares': 10},
        ]
    }

    report = generate_risk_report(test_state, new_orders=[])
    print('\n[RISK REPORT]')
    for k, v in report.items():
        print(f'  {k}: {v}')
