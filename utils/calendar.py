"""交易日历工具 — 单一真相源（v8.7 抽取）。

之前 sim_trade.py / position_sizer.py / broker_adapter.py 各自有 `get_last_trading_day` 副本。
统一到这里。

注意：和 `check_trading_day.py`（网络判断今天是不是交易日）职责不同——这里只看本地 stock_*.csv 文件名。
"""
from __future__ import annotations

import glob
import os
from datetime import datetime
from typing import Iterable

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, 'data')


def _list_local_trading_days(data_dir: str | None = None) -> list[str]:
    """从 stock_YYYYMMDD.csv 文件名列出本地已知交易日（升序 'YYYY-MM-DD'）。"""
    d = data_dir or DEFAULT_DATA_DIR
    days = []
    for path in glob.glob(os.path.join(d, 'stock_*.csv')):
        basename = os.path.basename(path)
        date_str = basename.replace('stock_', '').replace('.csv', '')
        try:
            days.append(datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d'))
        except ValueError:
            continue
    return sorted(set(days))


def get_last_trading_day(fmt: str = '%Y-%m-%d', data_dir: str | None = None) -> str:
    """从最新 stock_*.csv 文件名提取最近交易日。

    Args:
        fmt: 输出日期格式。位置敏感的调用方传 '%Y%m%d'。
        data_dir: 默认 BASE_DIR/data；测试可注入 tmp 目录。

    Returns:
        格式化日期字符串。如果没找到 stock_*.csv，返回今天。
    """
    d = data_dir or DEFAULT_DATA_DIR
    stock_files = sorted(glob.glob(os.path.join(d, 'stock_*.csv')), reverse=True)
    if stock_files:
        basename = os.path.basename(stock_files[0])
        date_str = basename.replace('stock_', '').replace('.csv', '')
        return datetime.strptime(date_str, '%Y%m%d').strftime(fmt)
    return datetime.now().strftime(fmt)


def count_trading_days(start_date, end_date, data_dir: str | None = None) -> int:
    """统计 [start_date, end_date] 区间的交易日数（包含两端，闭区间）。

    Why: exit_advisor 等模块需要"持有 N 个交易日"语义，而 (now - entry).days 是日历日，
    会把周末/节假日误算进去导致到期/止盈被提前触发。

    数据源优先级：
    1. data/stock_YYYYMMDD.csv 文件名（本系统每个交易日都会落地，已 8+ 天回溯）
    2. 兜底：用 weekday < 5（周一~五）当作交易日（不剔节假日，仅作 fallback）

    Args:
        start_date: 起始日期，str 'YYYY-MM-DD'/'YYYY/MM/DD' 或 datetime/date 对象。
        end_date: 结束日期，同上。
        data_dir: 测试可注入 tmp 目录。

    Returns:
        交易日数；start > end 时返回 0；解析失败时返回 0。
    """
    def _to_date(v):
        if hasattr(v, 'date'):
            return v.date() if hasattr(v, 'hour') else v
        if isinstance(v, str):
            for f in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
                try:
                    return datetime.strptime(v[:10] if len(v) >= 10 else v, f).date()
                except ValueError:
                    continue
            try:
                import pandas as pd
                return pd.to_datetime(v).date()
            except Exception:
                return None
        return None

    s = _to_date(start_date)
    e = _to_date(end_date)
    if s is None or e is None or s > e:
        return 0

    from datetime import timedelta

    def _weekday_count(a, b):
        n = 0
        cur = a
        while cur <= b:
            if cur.weekday() < 5:
                n += 1
            cur += timedelta(days=1)
        return n

    local_days = _list_local_trading_days(data_dir)
    if local_days:
        # v8.7+ round 2: 区间必须被 local_days "完全覆盖" 才直接用 local 计数。
        # 否则旧持仓（entry_date 早于 local 最旧文件）会被低估，触发"满 N 天到期"延迟。
        # archive_old_data.py 周一会清旧文件，local_days 窗口会缩，所以这里要特别小心。
        # round 3 修：前段终点必须夹到 e；后段起点必须夹到 s（否则查询区间完全在 local
        # 左侧或右侧时会把不属于 [s,e] 的天数算进来）。
        s_str = s.strftime('%Y-%m-%d')
        e_str = e.strftime('%Y-%m-%d')
        local_min, local_max = local_days[0], local_days[-1]
        if s_str >= local_min and e_str <= local_max:
            return len([d for d in local_days if s_str <= d <= e_str])
        total = 0
        if s_str < local_min:
            # [s, min(e, local_min-1)]
            head_end = min(e, _to_date(local_min) - timedelta(days=1))
            if head_end >= s:
                total += _weekday_count(s, head_end)
        cov_s = max(s_str, local_min)
        cov_e = min(e_str, local_max)
        if cov_s <= cov_e:
            total += len([d for d in local_days if cov_s <= d <= cov_e])
        if e_str > local_max:
            # [max(s, local_max+1), e]
            tail_start = max(s, _to_date(local_max) + timedelta(days=1))
            if tail_start <= e:
                total += _weekday_count(tail_start, e)
        return total

    return _weekday_count(s, e)
