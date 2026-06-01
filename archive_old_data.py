"""
老数据归档 v1 — 把老旧产物从工作目录移到 archive/{YYYYMM}/

策略：
- data/stock_YYYYMMDD.csv：保留最近 N 天，更老的归档
- orders/*.{json,md,txt}：保留 N 天
- results/*.{md,json,csv}：保留 N 天
- reports/*.md：保留 N 天

不归档的（需保留的核心 state 文件）：
- data/history.csv, data/system_config.json, data/portfolio_state.json,
  data/regime_state.json, data/evolve_daily_state.json, data/strategy_forward_returns.csv,
  data/risk_config.json, data/pick_performance.json, data/strategy_weights.json,
  data/good_trades.json, data/bad_trades.json, data/cold_start_manifest.json
"""
import os
import sys
import re
import shutil
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_ROOT = os.path.join(BASE_DIR, 'archive')

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION

# 不能归档的核心 state 文件（白名单）
# v8.5: 加入 risk_report.json / equity_curve.csv / account_state.json /
#       trade_history.csv / newbie_status.json / factor_weights.json /
#       arena_config.json / secrets.json
PROTECTED = {
    # 配置/版本中心
    'system_config.json', 'risk_config.json', 'secrets.json',
    # K 线 / 指数主数据
    'history.csv', 'hs300_index.csv',
    # 系统 state
    'portfolio_state.json', 'regime_state.json', 'evolve_daily_state.json',
    'newbie_status.json', 'minute_kline_status.json',
    # 学习 / 反馈数据
    'strategy_forward_returns.csv', 'pick_performance.json',
    'strategy_weights.json', 'factor_weights.json', 'arena_config.json',
    'behavior_log.csv', 'cold_start_manifest.json',
    'good_trades.json', 'bad_trades.json',
    # sim 账户产物
    'equity_curve.csv', 'account_state.json', 'trade_history.csv',
    'risk_report.json',
}

DATE_PATTERNS = [
    re.compile(r'(\d{8})'),                              # 20260518
    re.compile(r'(\d{4}-\d{2}-\d{2})'),                  # 2026-05-18
    re.compile(r'(\d{4}_\d{2}_\d{2})'),                  # 2026_05_18
]


def extract_date(filename):
    """从文件名提取日期"""
    for pat in DATE_PATTERNS:
        m = pat.search(filename)
        if m:
            s = m.group(1).replace('-', '').replace('_', '')
            try:
                return datetime.strptime(s, '%Y%m%d').date()
            except ValueError:
                continue
    return None


def archive_dir(src_dir, days_keep, file_filter=None):
    """归档 src_dir 下日期早于 (today - days_keep) 的文件

    Args:
        src_dir: 源目录绝对路径
        days_keep: 保留的天数
        file_filter: callable(filename)->bool 决定是否处理；None 表示处理所有
    Returns:
        (archived_count, skipped_count)
    """
    if not os.path.isdir(src_dir):
        return 0, 0
    cutoff = date.today() - timedelta(days=days_keep)
    archived = 0
    skipped = 0
    for fname in os.listdir(src_dir):
        src_path = os.path.join(src_dir, fname)
        if not os.path.isfile(src_path):
            continue
        if fname in PROTECTED:
            skipped += 1
            continue
        if file_filter and not file_filter(fname):
            skipped += 1
            continue
        # .bak 文件特殊：保留 90 天
        if fname.endswith('.bak'):
            bak_cutoff = date.today() - timedelta(days=90)
            d = extract_date(fname)
            if d is None or d > bak_cutoff:
                skipped += 1
                continue

        d = extract_date(fname)
        if d is None or d > cutoff:
            skipped += 1
            continue

        # 归档目标
        ym = d.strftime('%Y%m')
        archive_subdir = os.path.join(ARCHIVE_ROOT, ym, os.path.basename(src_dir))
        os.makedirs(archive_subdir, exist_ok=True)
        dst_path = os.path.join(archive_subdir, fname)
        try:
            shutil.move(src_path, dst_path)
            archived += 1
        except Exception as e:
            print(f"[ARCHIVE] move failed {fname}: {e}")
            skipped += 1
    return archived, skipped


def main():
    print(f"{'='*50}")
    print(f"  数据归档 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    targets = [
        ('data', cfg_get('archive.stock_csv_keep_days', 7),
         lambda n: n.startswith('stock_') and n.endswith('.csv')),
        ('orders', cfg_get('archive.orders_keep_days', 30), None),
        ('results', cfg_get('archive.results_keep_days', 30), None),
        ('reports', cfg_get('archive.reports_keep_days', 60), None),
    ]

    total_archived = 0
    for sub, days, ff in targets:
        src = os.path.join(BASE_DIR, sub)
        archived, skipped = archive_dir(src, days, ff)
        total_archived += archived
        print(f"  {sub}/: archived={archived}, skipped={skipped} (keep_days={days})")

    print(f"\n[ARCHIVE] total archived: {total_archived}")
    print(f"[ARCHIVE] archive root: {ARCHIVE_ROOT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
