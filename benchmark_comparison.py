"""
v8 vs HS300 长持基准对比 v1

回答的问题：「我跑这套系统比无脑买沪深300长持，到底赚不赚？」

数据源：
- 系统侧：sim_results/equity_curve.csv 或 results/honest_evaluation.md（回测）
- 基准侧：data/hs300_index.csv（HS300 收盘价）

输出：reports/benchmark_YYYYMMDD.md（文字 + 表格，不画图避免 matplotlib 依赖）
"""
import os
import sys
import json
import pandas as pd
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION

# 对比口径跟随系统本金配置（2026-08-24 起为 2400）
DEFAULT_CAPITAL = float(cfg_get('sim.initial_capital', 2400))


def load_hs300():
    f = os.path.join(DATA_DIR, 'hs300_index.csv')
    if not os.path.exists(f):
        return None
    df = pd.read_csv(f)
    df['日期'] = pd.to_datetime(df['日期'])
    return df.sort_values('日期')


def hs300_long_only_metrics(start_date, end_date, capital=None):
    """假设在 start_date 用 capital 全押 HS300 ETF（用指数代替），end_date 卖出"""
    if capital is None:
        capital = DEFAULT_CAPITAL
    capital = float(capital)
    idx = load_hs300()
    if idx is None or len(idx) == 0:
        return None
    sub = idx[(idx['日期'] >= pd.Timestamp(start_date)) & (idx['日期'] <= pd.Timestamp(end_date))].copy()
    if len(sub) < 2:
        return None
    entry = float(sub.iloc[0]['收盘'])
    exit_px = float(sub.iloc[-1]['收盘'])

    # 等额定投基准（每周一买入相同金额）
    weekly = sub[sub['日期'].dt.dayofweek == 0].copy()
    if len(weekly) >= 2:
        # 假设每周一投入 capital / weeks 份额
        weeks = len(weekly)
        per_buy = capital / weeks
        total_shares = sum(per_buy / float(w['收盘']) for _, w in weekly.iterrows())
        dca_value = total_shares * exit_px
        dca_return_pct = (dca_value / capital - 1) * 100
    else:
        dca_return_pct = None

    pnl_pct = (exit_px / entry - 1) * 100
    # 计算最大回撤
    rolling_max = sub['收盘'].cummax()
    drawdown = (sub['收盘'] / rolling_max - 1) * 100
    max_dd = drawdown.min()

    return {
        'start': str(sub.iloc[0]['日期'].date()),
        'end': str(sub.iloc[-1]['日期'].date()),
        'days': len(sub),
        'long_only_return_pct': round(pnl_pct, 2),
        'long_only_value': round(capital * (1 + pnl_pct / 100), 2),
        'dca_return_pct': round(dca_return_pct, 2) if dca_return_pct is not None else None,
        'max_drawdown_pct': round(max_dd, 2),
        'entry': round(entry, 2),
        'exit': round(exit_px, 2),
    }


def v8_metrics_from_backtest():
    """从最新 honest_evaluation.md 提取 v8 回测指标"""
    f = os.path.join(RESULTS_DIR, 'honest_evaluation.md')
    if not os.path.exists(f):
        return None
    import re
    text = open(f, encoding='utf-8').read()

    metrics = {'source': 'backtest', 'file': 'honest_evaluation.md'}
    m10 = re.search(r'\|\s*10日\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([+\-][\d.]+)%\s*\|\s*([+\-][\d.]+)%', text)
    if m10:
        metrics['10d_trades'] = int(m10.group(1))
        metrics['10d_win_rate'] = float(m10.group(2))
        metrics['10d_gross'] = float(m10.group(3))
        metrics['10d_net'] = float(m10.group(4))

    m_alpha = re.search(r'超额收益\*?\*?:\s*([+\-][\d.]+)%', text)
    if m_alpha:
        metrics['excess_vs_hs300'] = float(m_alpha.group(1))

    return metrics


def v8_metrics_from_sim():
    """从 sim_results/equity_curve.csv 提取实盘模拟权益曲线"""
    f = os.path.join(SIM_DIR, 'equity_curve.csv')
    if not os.path.exists(f):
        return None
    try:
        df = pd.read_csv(f)
    except Exception:
        return None
    if len(df) < 2 or '总权益' not in df.columns:
        return None

    start = float(df.iloc[0]['总权益'])
    end = float(df.iloc[-1]['总权益'])
    pnl_pct = (end / start - 1) * 100
    rolling_max = df['总权益'].cummax()
    dd = (df['总权益'] / rolling_max - 1) * 100
    max_dd = dd.min()

    return {
        'source': 'sim_equity',
        'days': len(df),
        'sim_return_pct': round(pnl_pct, 2),
        'sim_start_equity': round(start, 2),
        'sim_end_equity': round(end, 2),
        'sim_max_drawdown_pct': round(max_dd, 2),
    }


def render_report(v8_bt, v8_sim, hs300, capital=None):
    if capital is None:
        capital = DEFAULT_CAPITAL
    capital = float(capital)
    today = datetime.now()
    lines = [
        f"# v8 vs HS300 基准对比 — {today.strftime('%Y-%m-%d %H:%M')}",
        "",
        "> 回答：跑 v8 比无脑买沪深300 长持/定投到底强不强？",
        f"> 比较口径：相同时间窗口 + 相同初始资金 {capital:,.0f} 元",
        "",
    ]

    if hs300:
        lines.extend([
            "## HS300 基准（被动持有）",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 时间窗口 | {hs300['start']} ~ {hs300['end']} ({hs300['days']} 个交易日) |",
            f"| 期初点位 | {hs300['entry']} |",
            f"| 期末点位 | {hs300['exit']} |",
            f"| **一次性长持收益** | **{hs300['long_only_return_pct']:+.2f}%** ({hs300['long_only_value']} 元) |",
            f"| **每周等额定投收益** | **{hs300['dca_return_pct']:+.2f}%** |" if hs300['dca_return_pct'] is not None else "| 每周等额定投收益 | N/A |",
            f"| 最大回撤 | {hs300['max_drawdown_pct']:.2f}% |",
            "",
        ])
    else:
        lines.append("⚠️ HS300 数据不可用（data/hs300_index.csv 缺失或为空）")

    if v8_bt:
        lines.extend([
            "## v8 回测（理论收益）",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 数据源 | {v8_bt.get('file', 'N/A')} |",
            f"| 10 日持有交易数 | {v8_bt.get('10d_trades', 'N/A')} |",
            f"| 10 日胜率 | {v8_bt.get('10d_win_rate', 'N/A')}% |",
            f"| 10 日毛收益 | {v8_bt.get('10d_gross', 'N/A')}% |",
            f"| **10 日净收益** | **{v8_bt.get('10d_net', 'N/A')}%** |",
            f"| 超额（vs HS300）| {v8_bt.get('excess_vs_hs300', 'N/A')}% |",
            "",
        ])

    if v8_sim:
        lines.extend([
            "## v8 实盘模拟（sim_results）",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 模拟天数 | {v8_sim['days']} |",
            f"| 期初权益 | {v8_sim['sim_start_equity']} |",
            f"| 期末权益 | {v8_sim['sim_end_equity']} |",
            f"| **累计收益** | **{v8_sim['sim_return_pct']:+.2f}%** |",
            f"| 最大回撤 | {v8_sim['sim_max_drawdown_pct']:.2f}% |",
            "",
        ])

    # 一句话结论 — 阈值与 etf_gate.py 同步（0% / 1%，小资金摩擦感知）
    lines.extend(["## 一句话结论", ""])
    if hs300 and v8_bt and 'excess_vs_hs300' in v8_bt:
        excess = v8_bt['excess_vs_hs300']
        if excess > 1.0:
            lines.append(
                f"- ✅ v8 跑赢 HS300 基准 {excess:+.2f}%（10日窗口）。"
                f"超额覆盖了佣金与印花税，继续运行有意义。"
            )
        elif excess > 0.0:
            lines.append(
                f"- ⚠️ v8 仅跑赢 {excess:+.2f}%。{capital:,.0f} 元资金的双向佣金+印花税占比不低，"
                f"扣完基本持平，考虑改买 ETF 省心（510300 / 510310）。"
            )
        else:
            lines.append(
                f"- ❌ v8 跑输 HS300 基准 {excess:+.2f}%。"
                f"**对 {capital:,.0f} 元资金量，无脑买 HS300 ETF 长持（510300 / 510310）是更优选择**，"
                f"别折腾选股。"
            )
    else:
        lines.append("- 数据不足以下结论，下次运行再看。")

    lines.extend([
        "",
        "---",
        f"*由 benchmark_comparison.py v{SYSTEM_VERSION} 自动生成*",
    ])

    return '\n'.join(lines)


def main():
    print(f"{'='*50}")
    print(f"  v8 vs HS300 基准对比 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    v8_bt = v8_metrics_from_backtest()
    v8_sim = v8_metrics_from_sim()

    # HS300 取过去 120 天（与回测窗口对齐）
    end = date.today()
    start = end - timedelta(days=180)
    hs300 = hs300_long_only_metrics(start, end, DEFAULT_CAPITAL)

    if v8_bt:
        print(f"  v8 backtest 10d net: {v8_bt.get('10d_net', 'N/A')}%, excess: {v8_bt.get('excess_vs_hs300', 'N/A')}%")
    if v8_sim:
        print(f"  v8 sim cumulative: {v8_sim['sim_return_pct']}%, days: {v8_sim['days']}")
    if hs300:
        print(f"  HS300 long-only ({hs300['days']}d): {hs300['long_only_return_pct']:+.2f}%, DCA: {hs300.get('dca_return_pct', 'N/A')}%")

    report = render_report(v8_bt, v8_sim, hs300, DEFAULT_CAPITAL)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')
    path = os.path.join(REPORTS_DIR, f'benchmark_{today_str}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"[BENCHMARK] saved: {path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
