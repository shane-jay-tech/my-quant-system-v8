"""A 股交易日历（v8.7 审查补丁）

背景：check_trading_day 只用新浪行情日期 + 周末启发式，无法区分
"普通周一（上周五行情 day_diff=3）"与"节假日周一（上周五行情 day_diff=3）"，
法定节假日周一会被误判成交易日，流水线带着旧数据生成虚假订单。

实现：
- 优先读本地缓存 data/trading_calendar.csv（列：trade_date）
- 缓存缺失时尝试 akshare.tool_trade_date_hist_sina() 拉取全量交易日历并原子落盘
- 任何失败返回 None（未知），由调用方按原 fail-open 启发式兜底
- 只做判断，不写行情/订单，不改变任何决策逻辑
"""
from __future__ import annotations

import os
from datetime import date, datetime

CACHE_NAME = 'trading_calendar.csv'
_COL = 'trade_date'


def _load_cache(data_dir: str) -> set[str] | None:
    path = os.path.join(data_dir, CACHE_NAME)
    if not os.path.exists(path):
        return None
    try:
        import pandas as pd
        df = pd.read_csv(path, dtype={_COL: str})
        if _COL not in df.columns or df.empty:
            return None
        return {str(v).strip()[:10] for v in df[_COL].dropna()}
    except Exception:
        return None


def _refresh(data_dir: str) -> set[str] | None:
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty or _COL not in df.columns:
            return None
        days = {str(v).strip()[:10] for v in df[_COL].dropna()}
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, CACHE_NAME)
        tmp = path + '.tmp'
        df.to_csv(tmp, index=False, encoding='utf-8-sig')
        os.replace(tmp, path)
        return days
    except Exception as exc:
        print(f"[CALENDAR] refresh failed, fallback to heuristic: {exc}", flush=True)
        return None


def get_trading_days(data_dir: str) -> set[str] | None:
    """返回交易日集合（'YYYY-MM-DD'），拿不到返回 None。"""
    cached = _load_cache(data_dir)
    if cached is not None:
        return cached
    return _refresh(data_dir)


def is_trading_day_by_calendar(day, data_dir: str) -> bool | None:
    """日历判断：True/False；日历不可用时返回 None（调用方走启发式兜底）。"""
    days = get_trading_days(data_dir)
    if days is None:
        return None
    key = day.strftime('%Y-%m-%d') if hasattr(day, 'strftime') else str(day)[:10]
    return key in days
