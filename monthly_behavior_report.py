"""
月度行为偏差报告 v1 — 把 behavior_log.csv 30天数据汇总成 People Analytics 视角的月报

供作品集核心叙事：
- 系统推荐执行率
- 拒绝执行的票事后表现（hindsight：拒绝对了 vs 拒绝错了）
- 自主决策的票事后表现（凭直觉买的赢面 vs 系统推荐的赢面对比）
- deviation 类型分布（损失厌恶 / 过度交易 / 确认偏误的代理）

输出: reports/monthly_behavior_YYYYMM.md
"""
import os
import sys
import json
import pandas as pd
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

LOG_FILE = os.path.join(DATA_DIR, 'behavior_log.csv')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.csv')

sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION


def _load_log(lookback_days=30):
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    df = pd.read_csv(LOG_FILE, encoding='utf-8-sig', dtype={'日期': str})
    df['_dt'] = pd.to_datetime(df['日期'])
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)
    return df[df['_dt'] >= cutoff].copy()


def _load_history():
    if not os.path.exists(HISTORY_FILE):
        return None
    df = pd.read_csv(HISTORY_FILE, dtype={'代码': str})
    df['日期'] = pd.to_datetime(df['日期'])
    return df


def _hindsight_return(code, pick_date, history_df, n_days=5):
    """计算 pick_date 后 n_days 的实际收益（hindsight）"""
    if history_df is None:
        return None
    code = str(code).zfill(6)
    sub = history_df[history_df['代码'] == code].sort_values('日期')
    if len(sub) == 0:
        return None
    pick_dt = pd.to_datetime(pick_date)
    on_or_before = sub[sub['日期'] <= pick_dt]
    after = sub[sub['日期'] > pick_dt].head(n_days)
    if len(on_or_before) == 0 or len(after) == 0:
        return None
    entry = float(on_or_before.iloc[-1]['收盘'])
    exit_px = float(after.iloc[-1]['收盘'])
    if entry <= 0:
        return None
    return round((exit_px / entry - 1) * 100, 2)


def aggregate(df, history_df):
    """聚合统计 + 计算 hindsight 表现

    Returns: dict 包含执行率、各 deviation_type 频次、推荐 vs 自主 vs 拒绝的事后收益
    """
    summary = {
        'days': len(df),
        'date_range': f"{df['日期'].min()} ~ {df['日期'].max()}" if len(df) > 0 else 'N/A',
        'deviation_dist': df['deviation_type'].value_counts().to_dict() if len(df) > 0 else {},
    }

    rec_returns = []
    rejected_returns = []
    autonomous_returns = []
    executed_returns = []

    for _, row in df.iterrows():
        try:
            recs = json.loads(row['系统推荐'])
            actuals = json.loads(row['用户实际'])
        except Exception:
            continue
        d = row['日期']
        rec_codes = {r['code'] for r in recs}
        act_codes = {a['code'] for a in actuals if a.get('direction') == '买入'}

        for r in recs:
            ret = _hindsight_return(r['code'], d, history_df, 5)
            if ret is None:
                continue
            rec_returns.append(ret)
            if r['code'] in act_codes:
                executed_returns.append(ret)
            else:
                rejected_returns.append(ret)

        for a in actuals:
            if a.get('direction') != '买入':
                continue
            if a['code'] in rec_codes:
                continue
            ret = _hindsight_return(a['code'], d, history_df, 5)
            if ret is not None:
                autonomous_returns.append(ret)

    def _stat(rs):
        if not rs:
            return {'n': 0, 'mean': None, 'win_rate': None}
        wins = sum(1 for r in rs if r > 0)
        return {'n': len(rs), 'mean': round(sum(rs) / len(rs), 2), 'win_rate': round(wins / len(rs) * 100, 1)}

    summary['rec_all_5d'] = _stat(rec_returns)
    summary['executed_5d'] = _stat(executed_returns)
    summary['rejected_5d'] = _stat(rejected_returns)
    summary['autonomous_5d'] = _stat(autonomous_returns)

    return summary


def render_report(summary):
    today = datetime.now()
    ym = today.strftime('%Y%m')
    lines = [
        f"# 月度行为偏差报告 — {today.strftime('%Y年%m月')}",
        "",
        f"> 数据范围：{summary['date_range']} | {summary['days']} 个交易日",
        "> 视角：People Analytics — 量化决策偏差",
        "",
        "## 1. Deviation 类型分布",
        "",
        "| 类型 | 频次 | 含义 |",
        "|------|------|------|",
    ]
    type_meanings = {
        '全执行': '完全按系统推荐执行（基线）',
        '拒绝执行': '系统推荐但用户主动选择不买（损失厌恶代理）',
        '自主决策': '用户买了系统未推荐的票（过度自信代理）',
        '数量调整': '票一致但股数偏离 >10%（仓位偏好）',
        '未操作': '系统推荐但当日完全未下单',
        '混合偏离': '拒绝部分推荐 + 自主下单部分（最复杂）',
        '无推荐+无操作': '系统因 regime 等原因未推荐 + 用户合规未操作',
        '无推荐+自主': '系统未推荐但用户自己下单（信号外交易，最危险）',
    }
    for t, n in summary['deviation_dist'].items():
        meaning = type_meanings.get(t, '')
        lines.append(f"| {t} | {n} | {meaning} |")

    lines.extend([
        "",
        "## 2. 事后表现对比（5 日 hindsight 收益）",
        "",
        "| 类别 | 样本数 | 5日均收益 | 胜率 | 解读 |",
        "|------|--------|-----------|------|------|",
    ])

    cats = [
        ('系统全部推荐', summary['rec_all_5d'], '基线：系统选股的真实表现'),
        ('用户已执行', summary['executed_5d'], '你按推荐买入的票'),
        ('用户拒绝的推荐', summary['rejected_5d'], '⚠️ 若胜率/均收益 ≥ 已执行 → 你的"拒绝判断"是噪声，建议提升执行率'),
        ('用户自主买入', summary['autonomous_5d'], '⚠️ 若 < 系统推荐均值 → 凭直觉的票普遍跑输系统'),
    ]
    for label, st, note in cats:
        if st['n'] == 0:
            lines.append(f"| {label} | 0 | N/A | N/A | — |")
        else:
            lines.append(f"| {label} | {st['n']} | {st['mean']:+.2f}% | {st['win_rate']}% | {note} |")

    lines.extend([
        "",
        "## 3. People Analytics 视角解读",
        "",
    ])

    # 关键洞察生成
    rejected = summary['rejected_5d']
    executed = summary['executed_5d']
    autonomous = summary['autonomous_5d']

    if rejected['n'] >= 5 and executed['n'] >= 5:
        if rejected['mean'] is not None and executed['mean'] is not None:
            if rejected['mean'] > executed['mean']:
                lines.append('- **损失厌恶警告**：你拒绝执行的票均收益 ' + f'{rejected["mean"]:+.2f}% > 已执行的 {executed["mean"]:+.2f}%' + '。说明拒绝判断在数据上是错的，过度规避导致漏掉真实信号。')
            else:
                lines.append('- **拒绝判断有效**：你拒绝执行的票均收益 ' + f'{rejected["mean"]:+.2f}% < 已执行的 {executed["mean"]:+.2f}%' + '。你识别差信号的能力优于系统平均水平。')

    if autonomous['n'] >= 5:
        if autonomous['mean'] is not None and summary['rec_all_5d']['mean'] is not None:
            if autonomous['mean'] < summary['rec_all_5d']['mean']:
                lines.append('- **过度自信代价**：你自主买入的票均收益 ' + f'{autonomous["mean"]:+.2f}% < 系统推荐 {summary["rec_all_5d"]["mean"]:+.2f}%' + '。凭直觉跑输系统 — 减少信号外交易。')
            else:
                lines.append('- **直觉有效**：自主买入的票均收益 ' + f'{autonomous["mean"]:+.2f}% ≥ 系统推荐' + '。你有系统未捕捉到的私有信号源。')

    if not lines[-1].startswith('-'):
        lines.append("- 数据样本不足，下个月再看。")

    lines.extend([
        "",
        "## 4. 建议",
        "",
        "- 把这份报告作为 People Analytics 作品集的核心数据资产",
        "- 关注的不是『赚了多少钱』，而是『决策偏差是否被你看到并修正』",
        "",
        "---",
        f"*由 monthly_behavior_report.py v{SYSTEM_VERSION} 自动生成*",
    ])

    return '\n'.join(lines), ym


def main():
    print(f"{'='*50}")
    print(f"  月度行为偏差报告 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    df = _load_log(30)
    if len(df) == 0:
        print("[MONTHLY] no behavior_log entries in last 30 days, skip")
        return 0

    history_df = _load_history()
    summary = aggregate(df, history_df)
    report, ym = render_report(summary)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f'monthly_behavior_{ym}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"[MONTHLY] report saved: {path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
