"""
数据接入层 v1 — 基本面 + 资金流 + 宏观代理

功能：
1. 通过 AKShare 获取财务指标（ROE、净利润增速、经营现金流）
2. 北向资金持股数据
3. 个股主力资金流向
4. 宏观情绪代理（涨跌停家数、HS300 波动率）

设计原则：
- 本地缓存（data/cache/），当日数据不复采
- 失败降级：任何接口异常返回空 DataFrame，不阻塞选股流水线
- 统一列名输出，与 strategy.py 无缝集成
"""
import os, sys, json, time
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# v7.6: 统一配置中心
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get

# ---------- 缓存工具 ----------

def _cache_path(name):
    today = datetime.now().strftime('%Y%m%d')
    return os.path.join(CACHE_DIR, f'{name}_{today}.csv')


def _load_cache(name):
    p = _cache_path(name)
    if os.path.exists(p):
        return pd.read_csv(p, dtype={'代码': str})
    return None


def _save_cache(name, df):
    if df is None or len(df) == 0:
        return
    p = _cache_path(name)
    df.to_csv(p, index=False, encoding='utf-8-sig')


# ---------- 基本面数据 ----------

def load_fundamental_data(codes=None):
    """
    获取最新财务指标。
    返回 DataFrame: 代码, 名称, ROE, 净利润增速(%), 营收增速(%), 经营现金流(亿), 负债率(%)
    """
    cached = _load_cache('fundamental')
    if cached is not None:
        print('[DATA] Fundamental cache hit')
        if codes is not None:
            cached = cached[cached['代码'].isin(codes)]
        return cached

    try:
        import akshare as ak
    except ImportError:
        print('[DATA] akshare not installed, skip fundamental')
        return pd.DataFrame()

    print('[DATA] Fetching fundamental data via akshare...')
    rows = []
    # 使用 stock_financial_report_sina 或 stock_yjbb_em（业绩快报）
    # Round-2 修复（2026-05-30）：date 必须传"报告期"YYYYMMDD（季度末），不是自然日。
    # 旧版用 datetime.now() 得到例如 20260530，akshare 内部找不到对应季报数据 → 静默返回空 df
    # → 整个 ROE / 净利润增速 / 负债率因子永远为空（fundamental cache 为空文件）
    # 修复：取"上一已公布季报期"——A 股报告期为 0331/0630/0930/1231，提前 ~30 日已披露
    def _latest_report_period():
        now = datetime.now()
        # 4 月底起 Q1 数据齐；7 月末 Q2；10 月末 Q3；4 月末上年报。
        # 安全策略：取 (今天 - 45 天) 之前最近的季度末
        ref = now - timedelta(days=45)
        for mmdd in ('1231', '0930', '0630', '0331'):
            yyyy = ref.year
            cand = f'{yyyy}{mmdd}'
            if cand <= ref.strftime('%Y%m%d'):
                return cand
        return f'{ref.year - 1}1231'
    try:
        # 业绩报表（最新已披露季度）
        report_period = _latest_report_period()
        df_yjbb = ak.stock_yjbb_em(date=report_period)
        print(f'[DATA] Fundamental report period = {report_period}')
        if df_yjbb is not None and len(df_yjbb) > 0:
            # 统一列名（不同 akshare 版本列名可能有差异）
            col_map = {
                '股票代码': '代码',
                '股票简称': '名称',
                '净资产收益率': 'ROE',
                '净资产收益率(%)': 'ROE',
                '净利润同比增长率': '净利润增速',
                '净利润同比增长率(%)': '净利润增速',
                '营业收入同比增长率': '营收增速',
                '营业收入同比增长率(%)': '营收增速',
                '每股经营现金流量': '每股现金流',
                '负债合计': '负债合计',
                '资产总计': '资产总计',
            }
            df_yjbb = df_yjbb.rename(columns={k: v for k, v in col_map.items() if k in df_yjbb.columns})
            if '代码' in df_yjbb.columns:
                df_yjbb['代码'] = df_yjbb['代码'].astype(str).str.zfill(6)
                # 计算负债率
                if '负债合计' in df_yjbb.columns and '资产总计' in df_yjbb.columns:
                    df_yjbb['负债率'] = df_yjbb['负债合计'] / df_yjbb['资产总计'] * 100
                # 筛选需要的列
                keep = ['代码', '名称', 'ROE', '净利润增速', '营收增速', '每股现金流', '负债率']
                available = [c for c in keep if c in df_yjbb.columns]
                df_out = df_yjbb[available].copy()
                # 数值清洗
                for c in ['ROE', '净利润增速', '营收增速', '负债率']:
                    if c in df_out.columns:
                        df_out[c] = pd.to_numeric(df_out[c], errors='coerce')
                _save_cache('fundamental', df_out)
                if codes is not None:
                    df_out = df_out[df_out['代码'].isin(codes)]
                print(f'[DATA] Fundamental loaded: {len(df_out)} stocks')
                return df_out
    except Exception as e:
        print(f'[DATA] Fundamental fetch failed: {e}')

    return pd.DataFrame()


# ---------- 资金流数据 ----------

def load_north_flow(codes=None):
    """
    北向资金（陆股通）持股数据。
    返回 DataFrame: 代码, 北向持股(万股), 北向占比(%), 北向5日净买入(万股)
    """
    cached = _load_cache('north_flow')
    if cached is not None:
        print('[DATA] North flow cache hit')
        if codes is not None:
            cached = cached[cached['代码'].isin(codes)]
        return cached

    try:
        import akshare as ak
    except ImportError:
        print('[DATA] akshare not installed, skip north flow')
        return pd.DataFrame()

    print('[DATA] Fetching north flow via akshare...')
    # Round-2 修复（2026-05-30）：stock_gdfx_free_holding_detail_em 是"股东分析"——返回的是
    # 上市公司前十大流通股东明细（社保/基金/险资等），不是陆股通北向持股，列名也对不上
    # → 永远走 except，north_flow cache 永远空，"北向因子"在策略里始终拿不到信号
    # 修复：改用 stock_hsgt_hold_stock_em（沪深港通持股个股榜，实测 akshare 1.16+ 支持）
    # 旧 API 留作 fallback，方便老版本 akshare 用户
    try:
        try:
            # 首选：陆股通持股个股榜（北向资金真口径）
            df_north = ak.stock_hsgt_hold_stock_em(market='北向', indicator='今日排行')
        except (AttributeError, TypeError):
            # 兼容旧版 akshare：退回更早的接口名
            try:
                df_north = ak.stock_hsgt_north_acc_flow_in_em()
            except Exception:
                df_north = ak.stock_gdfx_free_holding_detail_em()  # 最后兜底：旧版逻辑
        if df_north is not None and len(df_north) > 0:
            # 列名适配（hsgt_hold_stock_em / stock_hsgt_north_acc_flow_in_em / 旧版三套兼容）
            col_map = {
                '股票代码': '代码',
                '代码': '代码',
                '名称': '名称',
                '股票简称': '名称',
                '今日持股-股数': '北向持股',
                '今日持股-市值': '北向市值',
                '今日持股-占流通股比': '北向占比',
                '持股数量': '北向持股',
                '持股数量(股)': '北向持股',
                '占总股本比例': '北向占比',
                '占总股本比例(%)': '北向占比',
            }
            df_north = df_north.rename(columns={k: v for k, v in col_map.items() if k in df_north.columns})
            if '代码' in df_north.columns:
                df_north['代码'] = df_north['代码'].astype(str).str.zfill(6)
                keep = ['代码', '北向持股', '北向占比']
                available = [c for c in keep if c in df_north.columns]
                df_out = df_north[available].copy()
                for c in ['北向持股', '北向占比']:
                    if c in df_out.columns:
                        df_out[c] = pd.to_numeric(df_out[c], errors='coerce')
                _save_cache('north_flow', df_out)
                if codes is not None:
                    df_out = df_out[df_out['代码'].isin(codes)]
                print(f'[DATA] North flow loaded: {len(df_out)} stocks')
                return df_out
    except Exception as e:
        print(f'[DATA] North flow fetch failed: {e}')

    return pd.DataFrame()


def load_fund_flow_individual(codes=None):
    """
    个股主力资金流向（当日）。
    返回 DataFrame: 代码, 主力净流入(亿), 主力净流入占比(%)
    """
    cached = _load_cache('fund_flow')
    if cached is not None:
        print('[DATA] Fund flow cache hit')
        if codes is not None:
            cached = cached[cached['代码'].isin(codes)]
        return cached

    try:
        import akshare as ak
    except ImportError:
        print('[DATA] akshare not installed, skip fund flow')
        return pd.DataFrame()

    print('[DATA] Fetching fund flow via akshare...')
    try:
        # 个股资金流向
        df_flow = ak.stock_fund_flow_individual()
        if df_flow is not None and len(df_flow) > 0:
            col_map = {
                '代码': '代码',
                '名称': '名称',
                '主力净流入-净额': '主力净流入',
                '主力净流入-净占比': '主力净流入占比',
            }
            df_flow = df_flow.rename(columns={k: v for k, v in col_map.items() if k in df_flow.columns})
            if '代码' in df_flow.columns:
                df_flow['代码'] = df_flow['代码'].astype(str).str.zfill(6)
                keep = ['代码', '主力净流入', '主力净流入占比']
                available = [c for c in keep if c in df_flow.columns]
                df_out = df_flow[available].copy()
                for c in ['主力净流入', '主力净流入占比']:
                    if c in df_out.columns:
                        df_out[c] = pd.to_numeric(df_out[c], errors='coerce')
                _save_cache('fund_flow', df_out)
                if codes is not None:
                    df_out = df_out[df_out['代码'].isin(codes)]
                print(f'[DATA] Fund flow loaded: {len(df_out)} stocks')
                return df_out
    except Exception as e:
        print(f'[DATA] Fund flow fetch failed: {e}')

    return pd.DataFrame()


# ---------- 宏观情绪代理 ----------

def load_market_sentiment():
    """
    市场情绪代理指标：
    - 当日涨停家数 / 跌停家数
    - HS300 近 20 日波动率
    - 上涨家数 / 下跌家数

    返回 dict
    """
    try:
        import akshare as ak
    except ImportError:
        return {}

    print('[DATA] Fetching market sentiment...')
    result = {}
    try:
        # 涨跌停家数
        df_zdt = ak.stock_zt_pool_em(date=datetime.now().strftime('%Y%m%d'))
        if df_zdt is not None:
            result['涨停家数'] = len(df_zdt)
    except Exception:
        pass

    try:
        df_dt = ak.stock_zt_pool_dtgc_em(date=datetime.now().strftime('%Y%m%d'))
        if df_dt is not None:
            result['跌停家数'] = len(df_dt)
    except Exception:
        pass

    try:
        # 涨跌分布
        df_zdfbx = ak.stock_zdfx_em()
        if df_zdfbx is not None and '上涨家数' in df_zdfbx.columns:
            result['上涨家数'] = int(df_zdfbx['上涨家数'].iloc[0]) if len(df_zdfbx) > 0 else 0
            result['下跌家数'] = int(df_zdfbx['下跌家数'].iloc[0]) if len(df_zdfbx) > 0 else 0
    except Exception:
        pass

    # HS300 波动率（从本地数据计算）
    hs300_path = os.path.join(DATA_DIR, 'hs300_index.csv')
    if os.path.exists(hs300_path):
        try:
            df_hs = pd.read_csv(hs300_path)
            df_hs['日期'] = pd.to_datetime(df_hs['日期'])
            df_hs = df_hs.sort_values('日期')
            if len(df_hs) >= 20:
                ret = df_hs['收盘'].pct_change().dropna()
                result['hs300_vol20'] = round(ret.tail(20).std() * np.sqrt(252) * 100, 2)
        except Exception:
            pass

    print(f'[DATA] Sentiment: {result}')
    return result


# ---------- 统一合并接口 ----------

def load_all_factors(codes=None):
    """
    统一加载所有外部因子，合并为单张宽表。
    供 strategy.py / multi_strategy.py 调用。

    Returns:
        pd.DataFrame: 以 代码 为 key 的宽表，列包含所有可用因子
    """
    dfs = []

    f1 = load_fundamental_data(codes)
    if len(f1) > 0:
        dfs.append(f1.set_index('代码'))

    f2 = load_north_flow(codes)
    if len(f2) > 0:
        dfs.append(f2.set_index('代码'))

    f3 = load_fund_flow_individual(codes)
    if len(f3) > 0:
        dfs.append(f3.set_index('代码'))

    if not dfs:
        return pd.DataFrame()

    merged = dfs[0]
    for d in dfs[1:]:
        merged = merged.join(d, how='outer', rsuffix='_dup')
        # 去除重复名称列
        dup_cols = [c for c in merged.columns if '_dup' in c]
        merged = merged.drop(columns=dup_cols, errors='ignore')

    merged = merged.reset_index()
    # 去重：同名保留第一个
    if '名称' in merged.columns:
        merged = merged.drop_duplicates(subset=['代码'], keep='first')
    print(f'[DATA] All factors merged: {len(merged)} stocks, {len(merged.columns)} cols')
    return merged


# ---------- 调试入口 ----------
if __name__ == '__main__':
    print(f"{'='*50}")
    print(f"  数据接入层测试 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")
    df = load_all_factors()
    print(df.head())
    sentiment = load_market_sentiment()
    print(sentiment)
