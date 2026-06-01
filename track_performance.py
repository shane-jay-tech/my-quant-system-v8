"""
持仓表现追踪器
- 读取历史所有 pick_*.md 对应的选股记录
- 计算每批选股的实际后续表现
- 绘制累计收益曲线（ASCII 格式）
- 输出绩效追踪报告
"""
import pandas as pd
import numpy as np
import os
import sys
import glob
import re
import json
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

# 追踪参数
TRACK_DAYS = [1, 3, 5, 10]  # 追踪持有天数
TRACK_FILE = os.path.join(DATA_DIR, 'pick_performance.json')


def load_tracker():
    if os.path.exists(TRACK_FILE):
        with open(TRACK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'records': [], 'summary': {}, 'updated': None}


def save_tracker(tracker):
    os.makedirs(DATA_DIR, exist_ok=True)
    tracker['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(TRACK_FILE, 'w', encoding='utf-8') as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)


def parse_pick_report(filepath):
    """从 Markdown 报告中提取选股列表"""
    picks = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取日期
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', content)
    if not date_match:
        return None, []

    pick_date = date_match.group(1)

    # 提取股票行：| 1 | 300265 | 通光线缆 | ...
    for line in content.split('\n'):
        line = line.strip()
        if re.match(r'\|\s*\d+\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 3 and re.match(r'\d{6}', parts[1]):
                picks.append({
                    '代码': parts[1],
                    '名称': parts[2],
                    '选股日期': pick_date,
                })

    return pick_date, picks


def track_forward_returns(history_df, picks_list):
    """
    追踪每批选股在持有 N 日后的表现
    """
    hist = history_df.copy()
    hist['日期'] = pd.to_datetime(hist['日期'])
    all_dates = sorted(hist['日期'].unique())

    records = []

    for pick_date_str, picks in picks_list:
        pick_date = pd.to_datetime(pick_date_str)

        # 在交易日列表中定位
        if pick_date not in all_dates:
            # 找最近的交易日
            nearby = [d for d in all_dates if d <= pick_date]
            if not nearby:
                continue
            pick_date = nearby[-1]

        pick_idx = all_dates.index(pick_date)

        for pick in picks:
            code = pick['代码']
            # 获取选股日价格
            entry_row = hist[(hist['代码'] == code) & (hist['日期'] == pick_date)]
            if len(entry_row) == 0:
                continue
            entry_price = entry_row.iloc[0]['收盘']
            if entry_price <= 0:
                continue

            for days in TRACK_DAYS:
                future_idx = pick_idx + days
                if future_idx >= len(all_dates):
                    continue
                future_date = all_dates[future_idx]
                exit_row = hist[(hist['代码'] == code) & (hist['日期'] == future_date)]
                if len(exit_row) == 0:
                    continue
                exit_price = exit_row.iloc[0]['收盘']
                if exit_price <= 0:
                    continue

                ret = (exit_price - entry_price) / entry_price * 100
                records.append({
                    '选股日期': pick_date_str,
                    '代码': code,
                    '名称': pick['名称'],
                    '入场价': entry_price,
                    '出场价': exit_price,
                    '持有天数': days,
                    '收益率(%)': round(ret, 2),
                    '盈利': ret > 0,
                })

    return pd.DataFrame(records)


def generate_performance_report(track_df):
    """生成绩效追踪报告"""
    if len(track_df) == 0:
        return "无追踪数据"

    lines = [
        "# 选股绩效追踪报告",
        "",
        f"> 追踪股票池：最近所有选股报告中的推荐股票",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 按持有期统计",
        "",
    ]

    for days in sorted(track_df['持有天数'].unique()):
        subset = track_df[track_df['持有天数'] == days]
        wins = subset['盈利'].sum()
        win_rate = wins / len(subset) * 100
        avg_ret = subset['收益率(%)'].mean()
        max_ret = subset['收益率(%)'].max()
        min_ret = subset['收益率(%)'].min()

        lines.append(f"### 持有 {days} 日")
        lines.append(f"- 交易次数: {len(subset)}")
        lines.append(f"- 胜率: {win_rate:.1f}%")
        lines.append(f"- 平均收益: {avg_ret:+.2f}%")
        lines.append(f"- 最大收益: {max_ret:+.2f}%")
        lines.append(f"- 最大亏损: {min_ret:+.2f}%")
        lines.append("")

    # 累计收益曲线
    lines.append("## 累计收益曲线")
    lines.append("")

    # 按选股日期聚合，计算等权组合净值
    daily_returns = track_df.groupby('选股日期')['收益率(%)'].mean()
    cumulative = (1 + daily_returns / 100).cumprod()
    total_return = (cumulative.iloc[-1] - 1) * 100

    lines.append(f"组合累计收益: **{total_return:+.2f}%**")
    lines.append("")

    # ASCII 曲线
    if len(cumulative) > 2:
        values = cumulative.values
        norm_values = (values - values.min()) / (values.max() - values.min()) if values.max() > values.min() else np.ones_like(values) * 0.5
        width = 50

        lines.append("```")
        lines.append(f"净值范围: {values.min():.3f} ~ {values.max():.3f}")
        lines.append("")
        for i, (date, val) in enumerate(zip(cumulative.index, values)):
            bar_len = int(norm_values[i] * width)
            bar = '█' * bar_len
            date_str = str(date)[:10]
            lines.append(f"  {date_str} │{bar} {val:.3f}")
        lines.append("```")

    lines.append("")
    lines.append("## 选股日期明细")
    lines.append("")
    lines.append("| 选股日期 | 股票数 | 平均收益(%) | 胜率(%) |")
    lines.append("|----------|--------|------------|---------|")

    for date in sorted(track_df['选股日期'].unique()):
        subset = track_df[track_df['选股日期'] == date]
        avg_ret = subset['收益率(%)'].mean()
        win_rate = subset['盈利'].sum() / len(subset) * 100
        lines.append(f"| {date} | {len(subset)} | {avg_ret:+.2f} | {win_rate:.1f} |")

    lines.append("")
    lines.append("---")
    lines.append("*追踪数据基于历史K线，不构成投资建议。*")

    return '\n'.join(lines)


def main():
    print(f"{'='*50}")
    print(f"  持仓表现追踪器 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # 查找所有选股报告
    pattern = os.path.join(RESULTS_DIR, 'pick_*.md')
    report_files = sorted(glob.glob(pattern))
    if not report_files:
        print("[ERROR] No pick reports found.")
        return 1

    print(f"[TRACK] Found {len(report_files)} report(s): {[os.path.basename(f) for f in report_files]}")

    # 解析所有报告
    all_picks = {}
    for f in report_files:
        date, picks = parse_pick_report(f)
        if date and picks:
            all_picks[date] = picks
            print(f"[TRACK] {date}: {len(picks)} stocks from {os.path.basename(f)}")

    if not all_picks:
        print("[ERROR] No valid picks found in reports.")
        return 1

    # 加载历史数据
    history_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(history_file):
        print("[ERROR] No history data found.")
        return 1

    hist_df = pd.read_csv(history_file, dtype={'代码': str})

    # 追踪表现
    picks_list = [(date, picks) for date, picks in sorted(all_picks.items())]
    track_df = track_forward_returns(hist_df, picks_list)

    if len(track_df) == 0:
        print("[WARN] No tracking data available (picks may be too recent).")
        return 0

    # 生成报告
    report = generate_performance_report(track_df)
    report_file = os.path.join(RESULTS_DIR, 'performance_tracking.md')
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"[TRACK] Report saved to: {report_file}")
    print(f"[TRACK] Tracked {len(track_df)} forward-return observations")

    win_rate = track_df['盈利'].sum() / len(track_df) * 100
    avg_ret = track_df['收益率(%)'].mean()
    print(f"[TRACK] Overall: {win_rate:.1f}% win rate, {avg_ret:+.2f}% avg return")

    # v7.6: 同时更新 JSON tracker（兼容原 pick_tracker 格式）
    tracker = load_tracker()
    # 按选股日期汇总次日收益（持有1天）
    next_day = track_df[track_df['持有天数'] == 1]
    if len(next_day) > 0:
        for date in sorted(next_day['选股日期'].unique()):
            if any(r.get('pick_date') == date for r in tracker['records']):
                continue
            sub = next_day[next_day['选股日期'] == date]
            up = sub['盈利'].sum()
            record = {
                'pick_date': date,
                'tracked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'stock_count': len(sub),
                'tracked_count': len(sub),
                'up': int(up),
                'down': int(len(sub) - up),
                'win_rate': round(up / len(sub) * 100, 1) if len(sub) > 0 else 0,
                'avg_return': round(sub['收益率(%)'].mean(), 2) if len(sub) > 0 else 0,
                'max_return': round(sub['收益率(%)'].max(), 2) if len(sub) > 0 else 0,
                'min_return': round(sub['收益率(%)'].min(), 2) if len(sub) > 0 else 0,
            }
            tracker['records'].append(record)
        # 更新 summary
        all_avg = [r['avg_return'] for r in tracker['records']]
        all_wr = [r['win_rate'] for r in tracker['records']]
        tracker['summary'] = {
            'total_pick_days': len(tracker['records']),
            'avg_next_day_return': round(np.mean(all_avg), 2) if all_avg else 0,
            'avg_win_rate': round(np.mean(all_wr), 1) if all_wr else 0,
            'positive_days': sum(1 for r in all_avg if r > 0),
            'total_stocks_tracked': sum(r['tracked_count'] for r in tracker['records']),
            'rolling_5d_avg': round(np.mean(all_avg[-5:]), 2) if len(all_avg) >= 5 else (round(np.mean(all_avg), 2) if all_avg else 0),
        }
        save_tracker(tracker)
        print(f"[TRACK] JSON tracker updated: {len(tracker['records'])} records")

    return 0


if __name__ == '__main__':
    sys.exit(main())
