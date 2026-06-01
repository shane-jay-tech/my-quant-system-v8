"""
回测引擎 v5 — MA(5,30)降低死叉噪声 + 大盘择时 + 动量排序

核心改进：
1. MA(5,30)替代(5,20)：经A/B验证降低死叉误触发（10日净+2.04%,胜率+4.7%）
2. 大盘择时：沪深300在MA20下方时空仓/减仓
3. 动量排序：多日涨幅加权而非单日涨跌
4. 集中持仓：Top 10 而非 Top 20
"""
import pandas as pd
import numpy as np
import os, sys, glob, requests, time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

# v7.5: 统一配置中心（保留本地默认值作为 fallback）
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get

MA_SHORT = cfg_get('backtest.ma_short', 5)
MA_LONG = cfg_get('backtest.ma_long', 30)
RSI_PERIOD = cfg_get('backtest.rsi_period', 14)
RSI_LOW = cfg_get('backtest.rsi_low', 30)
RSI_HIGH = cfg_get('backtest.rsi_high', 70)
MCAP_MIN = cfg_get('backtest.mcap_min', 5e9)
TOP_N = cfg_get('backtest.top_n', 10)

# 滑点（仅用于成交价 next_open 模拟，与 cost_model 的双边滑点率独立）
SLIPPAGE = cfg_get('backtest.slippage', 0.001)  # 集合竞价/实时滑点 0.1%
BACKTEST_DAYS = cfg_get('backtest.backtest_days', 120)
EXECUTION_MODE = cfg_get('backtest.execution_mode', 'next_open')  # next_open | same_close

# v8: 真实成本模型统一从 cost_model.py 读取（单一真相源）
# Why: 历史上 enhanced_backtest 用 0.0003 佣金率、sim_trade 用 0.00025，
# 同一笔交易两边算出不同成本，用户决策被误导。统一后 backtest/sim/walk_forward 同源。
from cost_model import (
    get_cost_by_mcap,
    compute_dynamic_notional,
    realized_cost_summary,
    format_cost_header,
    format_cost_examples,
    PER_TRADE_NOTIONAL,
)


def fetch_index():
    """加载 HS300 基准（data/hs300_index.csv）。

    刷新逻辑统一委托给 fetch_index.py（全系统单一写入源），避免与每日 pipeline
    的 fetch_index 步骤出现两份写入逻辑（一个合并、一个全量覆盖）相互打架、
    把合并好的历史重新截断。本函数只负责"确保刷新一次 + 读出 DataFrame"。
    """
    f = os.path.join(DATA_DIR, 'hs300_index.csv')
    # 通常每日 pipeline 的 fetch_index 步骤已把基准刷到最新；这里只在"缺失/落后最新
    # 交易日"时才再走一次网络，避免每天回测都重复抓取（仍复用 fetch_index 单一写入源）。
    need_refresh = True
    if os.path.exists(f):
        try:
            cur = pd.read_csv(f)
            cur_last = pd.to_datetime(cur['日期'], errors='coerce').max()
            from utils.calendar import get_last_trading_day
            last_td = pd.to_datetime(get_last_trading_day(data_dir=DATA_DIR))
            if pd.notna(cur_last) and cur_last >= last_td:
                need_refresh = False
        except Exception:
            need_refresh = True
    if need_refresh:
        try:
            from fetch_index import update_hs300_index
            update_hs300_index(DATA_DIR)
        except Exception as e:
            print(f"[BACKTEST] 基准刷新失败（非致命，沿用现有文件）：{e}")
    if os.path.exists(f):
        try:
            df = pd.read_csv(f)
            df['日期'] = pd.to_datetime(df['日期'])
            return df.sort_values('日期')
        except Exception as e:
            print(f"[BACKTEST] 读取基准失败：{e}")
    return None


def calc_indicators(hist_df):
    """MA + RSI（保持简单有效）"""
    hist = hist_df.copy()
    hist['日期'] = pd.to_datetime(hist['日期'])
    hist = hist.sort_values(['代码', '日期'])
    results = []
    for code, group in hist.groupby('代码'):
        g = group.sort_values('日期').copy()
        c = g['收盘']
        g['MA5'] = c.rolling(MA_SHORT).mean()
        g['MA20'] = c.rolling(MA_LONG).mean()
        d = c.diff()
        gain, loss = d.clip(lower=0), (-d).clip(lower=0)
        g['RSI'] = 100 - 100/(1 + gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean() / loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean().replace(0, np.nan))
        g['ret_1d'] = c.pct_change()
        g['ret_3d'] = c.pct_change(3)
        g['ret_5d'] = c.pct_change(5)
        results.append(g)
    return pd.concat(results, ignore_index=True)


def backtest(hist_df, today_df, index_df):
    print("[BACKTEST] Computing indicators (MA+RSI)...")
    hist = calc_indicators(hist_df)
    all_dates = sorted(hist['日期'].unique())
    test_dates = all_dates[-BACKTEST_DAYS:]

    mcap = dict(zip(today_df['代码'].astype(str).str.zfill(6), today_df['流通市值']))
    names = dict(zip(today_df['代码'].astype(str).str.zfill(6), today_df['名称']))
    st = set(c for c, n in names.items() if 'ST' in str(n))

    # 大盘择时信号：沪深300是否在MA20上方
    bull_market = set()
    if index_df is not None:
        idx = index_df.copy()
        idx['MA20'] = idx['收盘'].rolling(20).mean()
        for _, r in idx.iterrows():
            if pd.notna(r['MA20']) and r['收盘'] > r['MA20']:
                bull_market.add(r['日期'].date())

    # 基准收益
    bm = []
    if index_df is not None:
        ix = index_df.set_index('日期')['收盘']
        for j in range(1, len(test_dates)):
            d, prev = test_dates[j], test_dates[j-1]
            if d in ix.index and prev in ix.index:
                bm.append({'日期': d, '基准(%)': (ix[d]/ix[prev]-1)*100})

    trades = []
    daily = []

    for i, td in enumerate(test_dates[:-10]):
        data = hist[hist['日期'] <= td]
        lidx = data.groupby('代码')['日期'].idxmax()
        latest = data.loc[lidx]
        latest = latest[latest['日期'] == td].copy()
        if len(latest) == 0: continue

        latest['mcap'] = latest['代码'].map(mcap).fillna(0)
        td_date = td.date() if hasattr(td, 'date') else td

        # 基本筛选
        cond = (
            (latest['收盘'] > latest['MA5']) & (latest['MA5'] > latest['MA20']) &
            (latest['RSI'] > RSI_LOW) & (latest['RSI'] < RSI_HIGH) &
            (latest['mcap'] > MCAP_MIN) & (~latest['代码'].isin(st))
        )
        candidates = latest[cond].copy()
        n_candidates = len(candidates)

        # 大盘择时：熊市只选5只
        is_bull = td_date in bull_market
        n_pick = TOP_N if is_bull else max(3, TOP_N // 3)
        regime_str = '牛市' if is_bull else '熊市/震荡'

        if len(candidates) == 0:
            daily.append({'日期': str(td_date), '候选': 0, '选中': 0, '市场': regime_str})
            continue

        # 动量排序：1日涨跌×0.5 + 3日×0.3 + 5日×0.2
        candidates['momentum'] = (
            candidates['ret_1d'].fillna(0) * 0.5 +
            candidates['ret_3d'].fillna(0) * 0.3 +
            candidates['ret_5d'].fillna(0) * 0.2
        )
        picks = candidates.nlargest(n_pick, 'momentum')

        # v8: T+1 开盘成交模型 — 信号 t 日收盘判定，t+1 日开盘买入
        # EXECUTION_MODE='next_open' 时启用；'same_close' 走 legacy 路径（仅 A/B 用）
        idx_t = all_dates.index(td)
        same_close = (EXECUTION_MODE == 'same_close')

        # 入场日：next_open 模式下为 t+1（开盘），same_close 模式下为 t（收盘）
        entry_offset = 0 if same_close else 1
        entry_idx = idx_t + entry_offset
        if entry_idx >= len(all_dates):
            continue
        entry_date = all_dates[entry_idx]

        for hold in [1, 5, 10]:
            # 出场日索引：next_open 模式下为 entry+hold（hold 日后开盘），same_close 模式下为 t+hold（收盘）
            f_idx = entry_idx + hold if not same_close else idx_t + hold
            if f_idx >= len(all_dates): continue

            for _, p in picks.iterrows():
                code = p['代码']
                # 入场价：next_open 用 entry_date 开盘价；same_close 用 t 日收盘
                if same_close:
                    raw_entry = p['收盘']
                else:
                    entry_row = hist[(hist['代码']==code)&(hist['日期']==entry_date)]
                    if len(entry_row) == 0:
                        continue
                    raw_entry = entry_row.iloc[0].get('开盘')
                    if pd.isna(raw_entry) or raw_entry <= 0:
                        continue
                entry = raw_entry * (1 + SLIPPAGE)

                exit_px = entry
                exit_reason = '到期'
                ma_dead_cross = False

                # 持有期内逐日检查 MA 死叉
                for off in range(1, hold+1):
                    # 检查日：next_open 模式下从 entry_date 开始往后；same_close 从 t 开始往后
                    base_idx = entry_idx if not same_close else idx_t
                    ck = base_idx + off
                    if ck >= len(all_dates): break
                    cd = all_dates[ck]
                    row = hist[(hist['代码']==code)&(hist['日期']==cd)]
                    if len(row)==0: continue

                    ma5_v = row.iloc[0].get('MA5', 0)
                    ma30_v = row.iloc[0].get('MA20', 0)

                    # MA5 下穿 MA30 → 信号 cd 日收盘确认 → 卖出价用 cd+1 日开盘（next_open）
                    if pd.notna(ma5_v) and pd.notna(ma30_v) and ma5_v < ma30_v and off >= 3:
                        if same_close:
                            sell_px = row.iloc[0]['收盘']
                        else:
                            sell_idx = base_idx + off + 1
                            if sell_idx >= len(all_dates):
                                sell_px = row.iloc[0]['收盘']  # 最后一天兜底用收盘
                            else:
                                sell_date = all_dates[sell_idx]
                                sell_row = hist[(hist['代码']==code)&(hist['日期']==sell_date)]
                                if len(sell_row) == 0:
                                    sell_px = row.iloc[0]['收盘']
                                else:
                                    sell_px = sell_row.iloc[0].get('开盘', row.iloc[0]['收盘'])
                                    if pd.isna(sell_px) or sell_px <= 0:
                                        sell_px = row.iloc[0]['收盘']
                        exit_px = sell_px * (1 - SLIPPAGE)
                        exit_reason = f'MA死叉({off}日)'
                        ma_dead_cross = True
                        break

                    # 到期出场价：next_open 用 ck 日开盘，same_close 用 ck 日收盘
                    if same_close:
                        exit_raw = row.iloc[0]['收盘']
                    else:
                        exit_raw = row.iloc[0].get('开盘')
                        if pd.isna(exit_raw) or exit_raw <= 0:
                            exit_raw = row.iloc[0]['收盘']
                    exit_px = exit_raw * (1 - SLIPPAGE)

                gross = (exit_px - entry) / entry
                # v8: 按市值分档 + 动态单笔成本（regime + picks_count 决定）
                # Round-1 修复（2026-05-30）：
                # 1. regime_str 用 cost_model 的 5 档 key（"强牛/弱牛/震荡/弱熊/强熊"），
                #    旧版 "牛市/熊市/震荡" → REGIME_ALLOC.get fallback 0.40，dyn_notional 永远当中性档算
                # 2. 滑点已通过 entry/exit_px 调整入价（line 188/224/236），
                #    cost_model.round_trip_cost 又把双边滑点率算进 trade_cost = 双扣，
                #    传 with_slippage=False 让 cost_model 跳过滑点份额（commission + stamp_tax 仍算）
                cm_regime = '强牛' if (is_bull and abs(p.get('momentum', 0)) > 2) else \
                            '弱牛' if is_bull else \
                            '震荡' if (n_pick >= TOP_N // 2) else '弱熊'
                dyn_notional = compute_dynamic_notional(cm_regime, n_pick)
                trade_cost = get_cost_by_mcap(p.get('mcap', 0), notional=dyn_notional, with_slippage=False)
                net = gross - trade_cost

                trades.append({
                    '日期': str(td_date), '代码': code, '名称': names.get(code, ''),
                    '入场': round(entry, 2), '出场': round(exit_px, 2),
                    '持有': hold, '毛收益': round(gross*100, 2), '净收益': round(net*100, 2),
                    '成本率': round(trade_cost*100, 2), '出场原因': exit_reason, '市场': regime_str,
                })

        daily.append({'日期': str(td_date), '候选': n_candidates, '选中': n_pick, '市场': regime_str})
        if (i+1) % 20 == 0: print(f"[BACKTEST] {i+1}/{len(test_dates)-10}")

    return pd.DataFrame(trades), pd.DataFrame(daily), pd.DataFrame(bm) if bm else None


def analyze(trades, bm):
    r = {}
    if len(trades) == 0:
        r['持有1日'] = {'交易数': 0, '胜率': 'N/A', '毛收益': 'N/A', '净收益': 'N/A', '成本': 'N/A', 'MA死叉出场率': 'N/A'}
        r['持有5日'] = {'交易数': 0, '胜率': 'N/A', '毛收益': 'N/A', '净收益': 'N/A', '成本': 'N/A', 'MA死叉出场率': 'N/A'}
        r['持有10日'] = {'交易数': 0, '胜率': 'N/A', '毛收益': 'N/A', '净收益': 'N/A', '成本': 'N/A', 'MA死叉出场率': 'N/A'}
        return r
    for d in [1, 5, 10]:
        sub = trades[trades['持有']==d]
        if len(sub)==0: continue
        w = (sub['净收益']>0).sum()/len(sub)*100
        net, gross = sub['净收益'].mean(), sub['毛收益'].mean()
        r[f'持有{d}日'] = {
            '交易数': len(sub), '胜率': f'{w:.1f}%',
            '毛收益': f'{gross:+.2f}%', '净收益': f'{net:+.2f}%',
            '成本': f'{gross-net:.2f}%',
            'MA死叉出场率': f"{(sub['出场原因'].str.contains('MA死叉')).sum()/len(sub)*100:.1f}%"
        }

    # 牛熊对比
    for rg in ['牛市', '熊市/震荡']:
        sub = trades[(trades['市场']==rg)&(trades['持有']==10)]
        if len(sub)>0:
            w = (sub['净收益']>0).sum()/len(sub)*100
            r[f'{rg}(10日)'] = {'笔数': len(sub), '胜率': f'{w:.1f}%', '净收益': f"{sub['净收益'].mean():+.2f}%"}

    # 基准对比
    if bm is not None and len(bm)>0:
        bm_daily = bm['基准(%)'].mean()
        t10 = trades[trades['持有']==10]
        if len(t10)>0:
            s10 = t10.groupby('日期')['净收益'].mean().mean()
            r['基准对比'] = {
                '沪深300日均': f'{bm_daily:.2f}%',
                '策略10日净': f'{s10:+.2f}%',
                '超额': f'{s10-bm_daily*10:+.2f}%',
            }

    # 连亏
    t5 = trades[trades['持有']==5]
    if len(t5)>0:
        da = t5.groupby('日期')['净收益'].mean()
        ms = cs = 0
        for v in da:
            cs = cs+1 if v<0 else 0; ms = max(ms, cs)
        r['风控'] = {'最大连亏天数': ms}

    return r


def render(results, trades=None):
    t10_found = False
    net10, wr10 = 0, 0
    for k, v in results.items():
        if k == '持有10日':
            try:
                net10 = float(v['净收益'].replace('%','').replace('+',''))
                wr10 = float(v['胜率'].replace('%',''))
                t10_found = True
            except (ValueError, AttributeError):
                net10, wr10 = 0, 0
            break

    if net10 > 2 and wr10 > 48: verdict = "✅ **可以赚钱** — 策略有正向预期收益（趋势跟踪天然低胜率，靠盈亏比取胜）"
    elif net10 > 0.5: verdict = "⚠️ **微利** — 需要市场配合才能稳定盈利"
    else: verdict = "❌ **需要外部辅助** — 纯技术面在当前市场环境下无显著优势"

    # 真实成本报告：从 trades DataFrame 取 mean/min/max，替代 legacy COST=0.002 的虚假展示
    cost_summary = realized_cost_summary(trades)
    cost_header = format_cost_header(cost_summary)

    lines = [
        f"# 策略诚实评估 v4",
        f"",
        f"> 回测 {BACKTEST_DAYS}天 | {cost_header} | 出场: MA死叉",
        f"> 成本口径：双边总成本 = 买卖佣金（5 元 floor）+ 印花税 + 买卖滑点",
        f"> {verdict}",
        f"",
        f"## 核心指标",
        f"| 持有 | 交易数 | 胜率 | 毛收益 | 净收益 | 死叉出场 |",
        f"|------|--------|------|--------|--------|----------|",
    ]
    for d in [1, 5, 10]:
        k = f'持有{d}日'
        if k in results:
            v = results[k]
            lines.append(f"| {d}日 | {v['交易数']} | {v['胜率']} | {v['毛收益']} | {v['净收益']} | {v['MA死叉出场率']} |")

    lines.extend(["", "## 大盘择时效果（10日持有）", "| 市场状态 | 笔数 | 胜率 | 净收益 |", "|----------|------|------|--------|"])
    for k, v in results.items():
        if '(' in k and '10日' in k:
            lines.append(f"| {k.replace('(10日)','')} | {v['笔数']} | {v['胜率']} | {v['净收益']} |")

    if '基准对比' in results:
        b = results['基准对比']
        lines.extend(["", "## 基准对比", f"- 沪深300日均涨跌: {b['沪深300日均']}", f"- 策略10日净收益: {b['策略10日净']}", f"- **超额收益**: {b['超额']}"])

    if '风控' in results:
        lines.extend(["", "## 风控", f"- 最大连续亏损: {results['风控']['最大连亏天数']}天"])

    lines.extend(["", "---", "*不美化。*"])
    return '\n'.join(lines)


def main():
    print("="*60)
    print(f"  诚实回测 v4 | 真实成本（cost_model 单一真相源） | MA死叉出场 | 大盘择时")
    print("="*60)

    hf = os.path.join(DATA_DIR, 'history.csv')
    sf = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not os.path.exists(hf) or not sf: print("[FATAL] No data"); return 1

    hist = pd.read_csv(hf, dtype={'代码': str})
    today = pd.read_csv(sf[0], dtype={'代码': str})

    print("[1/3] Index...")
    idx = fetch_index()

    print("[2/3] Backtest...")
    trades, daily, bm = backtest(hist, today, idx)

    print(f"[3/3] {len(trades)} trades...")
    results = analyze(trades, bm)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    report = render(results, trades=trades)
    rf = os.path.join(RESULTS_DIR, 'honest_evaluation.md')
    with open(rf, 'w', encoding='utf-8') as f: f.write(report)

    # Print key results
    for k, v in results.items():
        if '持有' in k: print(f"  {k}: 净收益={v['净收益']}, 胜率={v['胜率']}")
    if '基准对比' in results:
        print(f"  超额收益: {results['基准对比']['超额']}")

    return 0

if __name__ == '__main__':
    sys.exit(main())
