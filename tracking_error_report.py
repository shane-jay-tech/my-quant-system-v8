"""
Tracking Error 诊断 v1 — 回测预期 vs 实盘模拟的真实偏离

回答的问题：「我的系统部署后，行为偏离了我设计的回测多远？」

输入：
- 回测预测分布：results/honest_evaluation.md（10日净收益）
- 模拟实际表现：sim_results/equity_curve.csv 或 trade_history.csv

输出：reports/tracking_error_YYYYMMDD.md
"""
import os
import sys
import re
import pandas as pd
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION


def load_backtest_metrics():
    f = os.path.join(RESULTS_DIR, 'honest_evaluation.md')
    if not os.path.exists(f):
        return None
    text = open(f, encoding='utf-8').read()

    metrics = {}
    for d in [1, 5, 10]:
        m = re.search(rf'\|\s*{d}日\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([+\-][\d.]+)%\s*\|\s*([+\-][\d.]+)%', text)
        if m:
            metrics[f'{d}d_trades'] = int(m.group(1))
            metrics[f'{d}d_win_rate'] = float(m.group(2))
            metrics[f'{d}d_gross'] = float(m.group(3))
            metrics[f'{d}d_net'] = float(m.group(4))

    m_excess = re.search(r'超额收益\*?\*?:\s*([+\-][\d.]+)%', text)
    if m_excess:
        metrics['excess_pct'] = float(m_excess.group(1))

    return metrics if metrics else None


def load_sim_trades_metrics():
    f = os.path.join(SIM_DIR, 'trade_history.csv')
    if not os.path.exists(f):
        return None
    try:
        df = pd.read_csv(f)
    except Exception:
        return None
    if len(df) == 0:
        return None

    metrics = {'sim_trades': len(df)}
    if '盈亏' in df.columns:
        df_with_pnl = df[df['盈亏'].notna() & (df['盈亏'] != 0)]
        if len(df_with_pnl) > 0:
            metrics['sim_win_rate'] = round((df_with_pnl['盈亏'] > 0).mean() * 100, 1)
            metrics['sim_avg_pnl'] = round(df_with_pnl['盈亏'].mean(), 2)
            # 假设回测/实盘等量比较：如果列里有"盈亏%"或"收益率"用它
        for pct_col in ['盈亏%', '收益率', 'pnl_pct']:
            if pct_col in df.columns:
                metrics['sim_avg_pnl_pct'] = round(df[pct_col].dropna().mean(), 2)
                break
    return metrics


def compute_tracking_error(bt, sim):
    """计算 tracking error 维度"""
    te = {}
    if bt is None or sim is None:
        return te

    if 'sim_win_rate' in sim and '10d_win_rate' in bt:
        te['win_rate_drift_pct'] = round(sim['sim_win_rate'] - bt['10d_win_rate'], 2)

    if 'sim_avg_pnl_pct' in sim and '10d_net' in bt:
        te['avg_return_drift_pct'] = round(sim['sim_avg_pnl_pct'] - bt['10d_net'], 2)

    if 'sim_trades' in sim and '10d_trades' in bt:
        te['trade_count_ratio'] = round(sim['sim_trades'] / max(1, bt['10d_trades']), 3)

    return te


def render_report(bt, sim, te):
    today = datetime.now()
    lines = [
        f"# Tracking Error 诊断 — {today.strftime('%Y-%m-%d %H:%M')}",
        "",
        "> 回答：模型部署后，实盘行为偏离设计意图多远？",
        "",
        "## 回测设计期望",
        "",
    ]
    if bt:
        lines.extend([
            "| 指标 | 数值 |",
            "|------|------|",
        ])
        for k, v in bt.items():
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("⚠️ 回测数据不可用")

    lines.extend(["", "## 实盘模拟实际", ""])
    if sim:
        lines.extend([
            "| 指标 | 数值 |",
            "|------|------|",
        ])
        for k, v in sim.items():
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("⚠️ sim_results 数据不足（需要至少 1 笔已平仓交易）")

    lines.extend(["", "## Tracking Error", ""])
    if te:
        lines.extend([
            "| 维度 | 漂移 | 解读 |",
            "|------|------|------|",
        ])
        # 解读规则
        if 'win_rate_drift_pct' in te:
            d = te['win_rate_drift_pct']
            if d > 5:
                interp = "实盘胜率显著高于回测（运气好 / 数据漂移好）"
            elif d < -5:
                interp = "⚠️ 实盘胜率明显低于回测（look-ahead bias 仍残留 / 市场状态变化）"
            else:
                interp = "胜率匹配良好"
            lines.append(f"| 胜率漂移 | {d:+.2f} pct | {interp} |")
        if 'avg_return_drift_pct' in te:
            d = te['avg_return_drift_pct']
            if d > 0.5:
                interp = "实盘收益高于回测（少见，注意是否选样本偏好）"
            elif d < -0.5:
                interp = "⚠️ 实盘收益低于回测 — 滑点/手续费可能仍被低估"
            else:
                interp = "收益匹配良好"
            lines.append(f"| 平均收益漂移 | {d:+.2f}% | {interp} |")
        if 'trade_count_ratio' in te:
            r = te['trade_count_ratio']
            if r < 0.1:
                interp = "实盘交易次数远低于回测（信号太严格或数据缺失）"
            elif r > 5:
                interp = "实盘交易次数远高于回测（过度交易风险）"
            else:
                interp = "交易频率合理"
            lines.append(f"| 交易频率比 | {r:.3f} | {interp} |")
    else:
        lines.append("数据不足，下次再看。")

    lines.extend([
        "",
        "## 关键结论",
        "",
    ])
    if not bt:
        lines.append("- 缺少回测数据，先跑 enhanced_backtest.py")
    elif not sim:
        lines.append("- 缺少实盘模拟数据，需要先跑几笔 sim_trade")
    else:
        if 'win_rate_drift_pct' in te and abs(te['win_rate_drift_pct']) < 5 and 'avg_return_drift_pct' in te and abs(te['avg_return_drift_pct']) < 0.5:
            lines.append("- ✅ 模型部署后行为与设计意图基本一致")
        else:
            lines.append("- ⚠️ 存在显著漂移，需要诊断成本模型 / 数据质量 / 信号定义")

    lines.extend([
        "",
        "---",
        f"*由 tracking_error_report.py v{SYSTEM_VERSION} 自动生成*",
    ])

    return '\n'.join(lines)


def main():
    print(f"{'='*50}")
    print(f"  Tracking Error 诊断 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    bt = load_backtest_metrics()
    sim = load_sim_trades_metrics()
    te = compute_tracking_error(bt, sim)

    if bt:
        print(f"  backtest 10d: net={bt.get('10d_net', '?')}%, win={bt.get('10d_win_rate', '?')}%")
    if sim:
        print(f"  sim trades: {sim.get('sim_trades', '?')}, win={sim.get('sim_win_rate', '?')}%")
    if te:
        print(f"  tracking error: {te}")

    report = render_report(bt, sim, te)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')
    path = os.path.join(REPORTS_DIR, f'tracking_error_{today_str}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"[TRACKING] saved: {path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
