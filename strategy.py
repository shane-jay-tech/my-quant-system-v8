"""
增强版选股策略：MA 均线 + RSI + MACD + 成交量确认 + 流通市值筛选

筛选条件：
  1. 最新价 > MA5 > MA20（多头排列）
  2. 30 < RSI(14) < 70（非超买超卖）
  3. MACD 柱 > 0 或 DIF > DEA（趋势向上）
  4. 成交量 > 20日均量 × 1.2（放量确认）
  5. 流通市值 > 50亿
  6. 非 ST、非 *ST

评分机制（总分100）：
  - 趋势强度 30分（MA5/MA20偏离度）
  - RSI合理性 20分（45-55最合理）
  - MACD动量 20分（柱状线强度）
  - 量能确认 15分（量比）
  - 当日涨跌 15分（非涨停优先）

按综合评分降序，取前20输出 Markdown 表格（含止损参考位）
"""
import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime
from sector_classifier import classify_sector, detect_sector_concentration
from position_sizer import detect_market_regime, fetch_hs300_data

# ========== 配置 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# v7.6: 统一配置中心（保留本地默认值作为 fallback）
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

# 策略参数（优先从统一配置读取）
MA_SHORT = cfg_get('strategy.ma_short', 5)
MA_LONG = cfg_get('strategy.ma_long', 30)
RSI_PERIOD = cfg_get('strategy.rsi_period', 14)
RSI_LOW = cfg_get('strategy.rsi_low', 30)
RSI_HIGH = cfg_get('strategy.rsi_high', 70)
MCAP_MIN = cfg_get('strategy.mcap_min', 5e9)
TOP_N = cfg_get('strategy.top_n', 20)

# MACD 参数
MACD_FAST = cfg_get('strategy.macd_fast', 12)
MACD_SLOW = cfg_get('strategy.macd_slow', 26)
MACD_SIGNAL = cfg_get('strategy.macd_signal', 9)

# 成交量参数
VOL_RATIO_MIN = cfg_get('strategy.vol_ratio_min', 1.2)

# 动态参数开关
USE_DYNAMIC_PARAMS = cfg_get('strategy.use_dynamic_params', True)


def _fallback_stop_loss(price):
    """ATR 不可用时的止损回退价，跟随 sim.stop_loss_pct（当前 -8%），不再写死 -5%。"""
    try:
        pct = float(cfg_get('sim.stop_loss_pct', -0.08))
    except Exception:
        pct = -0.08
    return round(price * (1 + pct), 2)


def load_evolved_params():
    """加载轻量进化引擎微调后的参数，覆盖默认值"""
    import json
    state_file = os.path.join(DATA_DIR, 'evolve_daily_state.json')
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
        current = state.get('current_params', {})
        # 只返回和默认值不同的参数
        evolved = {}
        key_map = {
            'RSI_LOW': 'RSI_LOW', 'RSI_HIGH': 'RSI_HIGH',
            'MA_LONG': 'MA_LONG', 'TOP_N': 'TOP_N', 'MAX_SINGLE_POSITION': 'MAX_SINGLE_POSITION',
        }
        for ek, sk in key_map.items():
            if ek in current:
                evolved[sk] = current[ek]
        return evolved
    except Exception:
        return {}


def get_adaptive_params(regime=None):
    """
    根据市场状态返回动态调整的参数

    动态参数规则 [动态参数规则] v7:
    - 强牛：RSI(25,75), MA(5,30) — 包容强势股，慢线更长防死叉
    - 弱牛：RSI(28,72), MA(5,30) — 略放宽上限
    - 震荡：RSI(30,70), MA(5,25) — 适中，快出慢进
    - 弱熊：RSI(35,65), MA(5,15) — 保守选股，快速出场
    - 强熊：RSI(38,60), MA(5,10) — 极度保守，极快出场
    """
    if not USE_DYNAMIC_PARAMS or regime is None:
        return {
            'rsi_low': RSI_LOW, 'rsi_high': RSI_HIGH,
            'ma_short': MA_SHORT, 'ma_long': MA_LONG,
            'regime': 'default'
        }

    param_map = {
        '强牛': {'rsi_low': 25, 'rsi_high': 75, 'ma_short': 5, 'ma_long': 30},
        '弱牛': {'rsi_low': 28, 'rsi_high': 72, 'ma_short': 5, 'ma_long': 30},
        '震荡': {'rsi_low': 30, 'rsi_high': 70, 'ma_short': 5, 'ma_long': 25},
        '弱熊': {'rsi_low': 35, 'rsi_high': 65, 'ma_short': 5, 'ma_long': 15},
        '强熊': {'rsi_low': 38, 'rsi_high': 60, 'ma_short': 5, 'ma_long': 10},
    }

    params = param_map.get(regime, param_map['震荡'])
    params['regime'] = regime
    return params


# ========== 指标计算 ==========
def calc_rsi(close_series, period=14):
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(close_series):
    """返回 DIF, DEA, MACD柱"""
    ema_fast = close_series.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close_series.ewm(span=MACD_SLOW, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=MACD_SIGNAL, adjust=False).mean()
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def calc_atr(high, low, close, period=14):
    """计算 ATR（平均真实波幅），用于止损参考"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


# ========== 评分系统 ==========
def score_stock(ma5, ma20, price, rsi, dif, dea, macd_bar, vol_ratio, change_pct,
                rsi_low=None, rsi_high=None):
    """
    综合评分（满分100）
    各部分权重基于回测最优参数调校（v7.6: 权重待统计验证）
    """
    _rsi_low = rsi_low if rsi_low is not None else RSI_LOW
    _rsi_high = rsi_high if rsi_high is not None else RSI_HIGH

    score = 0

    # 1. 趋势强度（30分）：MA5/MA20 偏离度
    if ma20 > 0 and ma5 > ma20:
        trend_strength = (ma5 / ma20 - 1) * 100  # 百分比偏离
        # 偏离在 0.5% ~ 8% 之间最理想
        if 0.5 <= trend_strength <= 8:
            score += 30
        elif trend_strength < 0.5:
            score += 15
        else:
            score += 20  # 偏离过大减分

    # 2. RSI 合理性（20分）：45-55 最健康
    if 45 <= rsi <= 55:
        score += 20
    elif 40 <= rsi <= 60:
        score += 15
    elif _rsi_low < rsi < _rsi_high:
        score += 8

    # 3. MACD 动量（20分）
    if macd_bar > 0:
        score += 10  # 柱状线为正
        if dif > dea:
            score += 10  # 金叉状态
        else:
            score += 5
    elif dif > dea:
        score += 8  # 柱状线为负但趋势仍向上
    else:
        score += 2

    # 4. 量能确认（15分）
    if vol_ratio >= 2.0:
        score += 15  # 显著放量
    elif vol_ratio >= 1.5:
        score += 12
    elif vol_ratio >= VOL_RATIO_MIN:
        score += 8
    elif vol_ratio >= 0.8:
        score += 4

    # 5. 当日涨跌（15分）：非涨停/跌停，温和上涨最佳
    if 3 <= change_pct <= 8:
        score += 15  # 温和上涨最佳
    elif 0 < change_pct < 3:
        score += 12
    elif 8 < change_pct < 20:
        score += 8  # 涨太多有回调风险
    elif -3 <= change_pct < 0:
        score += 6
    elif change_pct <= -5:
        score += 2  # 大跌减分

    return score


# ========== 选股主逻辑 ==========
def screen_stocks(today_df, history_df, target_date=None, override_params=None):
    """选股主逻辑。override_params 用于传入进化参数，不污染模块全局变量。"""
    # v7.6: 局部参数覆盖，避免修改全局常量
    _ma_long = override_params.get('MA_LONG', MA_LONG) if override_params else MA_LONG
    _rsi_low = override_params.get('RSI_LOW', RSI_LOW) if override_params else RSI_LOW
    _rsi_high = override_params.get('RSI_HIGH', RSI_HIGH) if override_params else RSI_HIGH
    _top_n = override_params.get('TOP_N', TOP_N) if override_params else TOP_N
    _vol_ratio_min = override_params.get('VOL_RATIO_MIN', VOL_RATIO_MIN) if override_params else VOL_RATIO_MIN

    if target_date is None:
        target_date = history_df['日期'].max()

    print(f"[STRATEGY] Screening for date: {target_date}")

    today = today_df.copy()
    today['代码'] = today['代码'].astype(str).str.zfill(6)

    hist = history_df.copy()
    hist['代码'] = hist['代码'].astype(str).str.zfill(6)
    hist['日期'] = pd.to_datetime(hist['日期'])
    hist = hist.sort_values(['代码', '日期'])

    # 过滤 ST
    st_mask = today['名称'].str.contains(r'\*?ST', na=False, regex=True)
    st_codes = set(today.loc[st_mask, '代码'].tolist())
    print(f"[STRATEGY] Filtered {len(st_codes)} ST stocks")

    non_st = today[~today['代码'].isin(st_codes)]
    mcap_filtered = non_st[non_st['流通市值'] > MCAP_MIN].copy()
    print(f"[STRATEGY] After MCAP > 50亿: {len(mcap_filtered)} stocks")

    # v7.6: 过滤停牌、退市、新股（上市不足60天）
    halt_mask = (mcap_filtered['成交量'] == 0) | (mcap_filtered['最新价'] == 0) | (mcap_filtered['最新价'].isna())
    delist_mask = mcap_filtered['名称'].str.contains('退市', na=False)
    # 新股：历史数据不足60个交易日
    hist_counts = hist.groupby('代码').size()
    new_stock_codes = set(hist_counts[hist_counts < 60].index)
    new_mask = mcap_filtered['代码'].isin(new_stock_codes)
    excluded = halt_mask | delist_mask | new_mask
    if excluded.any():
        print(f"[STRATEGY] Filtered {excluded.sum()} stocks (halt/delist/new)")
        mcap_filtered = mcap_filtered[~excluded].copy()

    # 检测市场状态，获取自适应参数
    idx_data = fetch_hs300_data()
    regime, regime_info = detect_market_regime(idx_data)
    adaptive = get_adaptive_params(regime) if USE_DYNAMIC_PARAMS else get_adaptive_params(None)
    # 若 override_params 提供了 RSI/MA 边界，优先使用
    if override_params:
        adaptive['rsi_low'] = override_params.get('RSI_LOW', adaptive['rsi_low'])
        adaptive['rsi_high'] = override_params.get('RSI_HIGH', adaptive['rsi_high'])
        adaptive['ma_long'] = override_params.get('MA_LONG', adaptive['ma_long'])
    print(f"[STRATEGY] Market regime: {regime} | RSI({adaptive['rsi_low']},{adaptive['rsi_high']}) "
          f"MA({adaptive['ma_short']},{adaptive['ma_long']})")

    # 逐股评分
    results = []
    codes_to_process = mcap_filtered['代码'].unique()
    total = len(codes_to_process)

    for i, code in enumerate(codes_to_process):
        stock_hist = hist[hist['代码'] == code].copy()
        if len(stock_hist) < _ma_long + MACD_SLOW + 5:
            continue

        stock_hist = stock_hist.sort_values('日期')
        close = stock_hist['收盘']
        high = stock_hist['最高']
        low = stock_hist['最低']

        # 计算指标（使用局部 _ma_long）
        stock_hist['MA5'] = close.rolling(MA_SHORT).mean()
        stock_hist['MA20'] = close.rolling(_ma_long).mean()
        stock_hist['RSI'] = calc_rsi(close, RSI_PERIOD)
        dif, dea, macd_bar = calc_macd(close)
        stock_hist['DIF'] = dif
        stock_hist['DEA'] = dea
        stock_hist['MACD'] = macd_bar
        stock_hist['ATR'] = calc_atr(high, low, close, 14)

        # 成交量指标
        stock_hist['VOL_MA20'] = stock_hist['成交量'].rolling(20).mean()
        stock_hist['VOL_RATIO'] = stock_hist['成交量'] / stock_hist['VOL_MA20'].replace(0, np.nan)

        latest = stock_hist.iloc[-1]
        ma5 = latest.get('MA5', np.nan)
        ma20 = latest.get('MA20', np.nan)
        rsi = latest.get('RSI', np.nan)
        dif_v = latest.get('DIF', np.nan)
        dea_v = latest.get('DEA', np.nan)
        macd_v = latest.get('MACD', np.nan)
        atr_v = latest.get('ATR', np.nan)
        vol_ratio = latest.get('VOL_RATIO', np.nan)
        price = latest['收盘']

        if pd.isna(ma5) or pd.isna(ma20) or pd.isna(rsi):
            continue
        if pd.isna(dif_v) or pd.isna(dea_v):
            continue

        # 硬性条件筛选（v7.6: 使用自适应参数 + 局部 override）
        if not (price > ma5 > ma20):
            continue
        if not (adaptive['rsi_low'] < rsi < adaptive['rsi_high']):
            continue
        if pd.notna(vol_ratio) and vol_ratio < _vol_ratio_min:
            continue

        # 获取当日涨跌幅
        today_row = today[today['代码'] == code]
        if len(today_row) == 0:
            continue
        today_row = today_row.iloc[0]
        change_pct = today_row['涨跌幅']
        mcap = today_row['流通市值']

        # 综合评分（使用局部 _rsi_low / _rsi_high 作为评分边界参考）
        total_score = score_stock(
            ma5, ma20, price, rsi,
            dif_v, dea_v, macd_v if pd.notna(macd_v) else 0,
            vol_ratio if pd.notna(vol_ratio) else 1,
            change_pct, _rsi_low, _rsi_high
        )

        # 止损参考 = entry * (1 - 2*ATR/entry) ≈ entry - 2*ATR；ATR 缺失时回退系统配置止损
        stop_loss = price - 2 * atr_v if pd.notna(atr_v) and atr_v > 0 else _fallback_stop_loss(price)

        # 风险等级
        if rsi > 65:
            risk = "高"
        elif rsi > 50:
            risk = "中"
        else:
            risk = "低"

        # 选入理由
        reasons = []
        if ma5 / ma20 > 1.03:
            reasons.append("强趋势")
        if pd.notna(vol_ratio) and vol_ratio > 2:
            reasons.append("显著放量")
        if pd.notna(macd_v) and macd_v > 0:
            reasons.append("MACD正向")
        if 45 <= rsi <= 55:
            reasons.append("RSI健康")
        if 3 <= change_pct <= 8:
            reasons.append("温和上涨")
        if not reasons:
            reasons.append("均线多头")

        results.append({
            '代码': code,
            '名称': today_row['名称'],
            '最新价': price,
            '涨跌幅': change_pct,
            'MA5': round(ma5, 2),
            'MA20': round(ma20, 2),
            'RSI': round(rsi, 2),
            'MACD': round(macd_v, 4) if pd.notna(macd_v) else 0,
            '量比': round(vol_ratio, 2) if pd.notna(vol_ratio) else 0,
            '流通市值_亿': round(mcap / 1e8, 2),
            '流通市值': mcap,
            '止损价': round(stop_loss, 2),
            '风险': risk,
            '综合评分': total_score,
            '选入理由': ' + '.join(reasons),
            '板块': classify_sector(code, today_row['名称']),
        })

        if (i + 1) % 500 == 0:
            print(f"[STRATEGY] Processed {i+1}/{total}, {len(results)} candidates")

    print(f"[STRATEGY] Candidates passing all filters: {len(results)}")

    results_df = pd.DataFrame(results)
    if len(results_df) == 0:
        return results_df

    # 按综合评分降序取足够多，用于板块集中度检测
    results_df = results_df.sort_values('综合评分', ascending=False)
    top_candidates = results_df.head(_top_n + 5).to_dict('records')  # 多取5只备选

    # 板块集中度检测
    tagged, sector_stats, warnings = detect_sector_concentration(top_candidates, max_per_sector=3)

    # 优先保留未标记风险的，然后补充分数高的
    safe = [s for s in tagged if not s['集中风险']]
    risky = [s for s in tagged if s['集中风险']]

    # 最终选择：safe优先，不够从risky补
    final_selection = safe[:_top_n]
    if len(final_selection) < _top_n:
        final_selection += risky[:_top_n - len(final_selection)]

    results_df = pd.DataFrame(final_selection).head(_top_n)
    results_df = results_df.reset_index(drop=True)

    if warnings:
        for w in warnings:
            print(f"[STRATEGY] {w}")

    # 板块分布摘要
    final_sectors = results_df['板块'].value_counts().to_dict()
    sector_summary = ' | '.join(f'{s}({c}只)' for s, c in final_sectors.items())
    print(f"[STRATEGY] Sector distribution: {sector_summary}")
    print(f"[STRATEGY] Top {len(results_df)} by composite score (post sector rebalance)")
    print(f"[STRATEGY] Score range: {results_df['综合评分'].min()} ~ {results_df['综合评分'].max()}")
    return results_df


# ========== 输出 Markdown ==========
def render_markdown(results_df, target_date, adaptive=None, regime='未知'):
    # 板块分布
    sector_dist = results_df['板块'].value_counts().to_dict() if '板块' in results_df.columns else {}
    sector_line = ' | '.join(f'{s}({c}只)' for s, c in sector_dist.items())

    lines = [
        f"# 量化选股结果 - {target_date}",
        "",
        f"> **策略**：MA多头排列 + RSI({adaptive['rsi_low']}-{adaptive['rsi_high']}) + MACD正向 + 量比>1.2 + 流通市值>50亿 + 非ST + 板块集中度风控",
        f"> **市场状态**：{regime} | 自适应参数",
        f"> **评分维度**：趋势强度(30) + RSI合理性(20) + MACD动量(20) + 量能确认(15) + 当日涨跌(15)",
        f"> **选股数量**：{len(results_df)} 只 | **板块分布**：{sector_line}",
        f"> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| 排名 | 代码 | 名称 | 板块 | 最新价 | 涨跌(%) | MA5 | MA20 | RSI | 量比 | 市值(亿) | 评分 | 风险 | 选入理由 |",
        "|------|------|------|------|--------|---------|-----|------|-----|------|---------|------|------|----------|",
    ]

    for rank, (_, row) in enumerate(results_df.iterrows(), 1):
        change_str = f"{row['涨跌幅']:+.2f}" if row['涨跌幅'] != 0 else "0.00"
        sector = row.get('板块', '其他')
        lines.append(
            f"| {rank} | {row['代码']} | {row['名称']} | {sector} | {row['最新价']:.2f} | "
            f"{change_str} | {row['MA5']:.2f} | {row['MA20']:.2f} | "
            f"{row['RSI']:.2f} | {row['量比']:.2f} | {row['流通市值_亿']:.2f} | "
            f"{row['综合评分']} | {row['风险']} | {row['选入理由']} |"
        )

    lines.append("")
    lines.append("## 风险提示")
    lines.append(f"- 高评分股票已通过多因子验证，但仍需关注大盘系统性风险")
    try:
        stop_pct = float(cfg_get('sim.stop_loss_pct', -0.08))
    except Exception:
        stop_pct = -0.08
    lines.append(f"- 止损参考：{stop_pct:.0%}（系统配置，ATR 可用时按 2×ATR）或跌破 MA20 应考虑离场")
    try:
        capital = float(cfg_get('sim.initial_capital', 2400))
    except Exception:
        capital = 2400.0
    if capital <= 3000:
        lines.append(f"- 持仓建议：小资金模式（本金 ¥{capital:,.0f}）除强熊外全仓，最多 3 只，单票上限约 1/3")
    else:
        lines.append(f"- 持仓建议：单票仓位不超过 15%，总仓位随大盘走势调整")
    lines.append("")
    lines.append("---")
    lines.append("*免责声明：以上结果基于量化模型自动生成，不构成投资建议。股市有风险，投资需谨慎。*")

    return '\n'.join(lines)


def generate_summary(results_df):
    if len(results_df) == 0:
        return "今日无股票通过筛选。"

    count = len(results_df)
    avg_change = results_df['涨跌幅'].mean()
    avg_rsi = results_df['RSI'].mean()
    score_range = f"{results_df['综合评分'].min()}-{results_df['综合评分'].max()}"
    high_risk = (results_df['风险'] == '高').sum()

    try:
        stop_pct = float(cfg_get('sim.stop_loss_pct', -0.08))
    except Exception:
        stop_pct = -0.08
    summary = (
        f"今日选出{count}只(评分{score_range}分)，"
        f"均涨幅{avg_change:+.2f}%，均RSI {avg_rsi:.1f}。"
        f"其中高风险{high_risk}只。"
        f"选股基于多头排列+MACD正向+量能确认，止损设MA20或{stop_pct:.0%}。"
    )
    return summary[:100]


# ========== 主函数 ==========
def main(target_date=None):
    print(f"{'='*50}")
    print(f"  增强版量化选股策略 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    os.makedirs(RESULTS_DIR, exist_ok=True)

    today_str = datetime.now().strftime('%Y%m%d')
    today_file = os.path.join(DATA_DIR, f'stock_{today_str}.csv')

    if not os.path.exists(today_file):
        import glob
        files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
        if not files:
            print("[FATAL] No stock data file found.")
            sys.exit(1)
        today_file = files[0]

    print(f"[STRATEGY] Data: {today_file}")
    today_df = pd.read_csv(today_file, dtype={'代码': str})

    history_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(history_file):
        print("[FATAL] No history data.")
        sys.exit(1)

    print(f"[STRATEGY] History: {history_file}")
    history_df = pd.read_csv(history_file, dtype={'代码': str})

    # 加载进化参数（v7.6: 通过 override_params 传入，禁止修改全局变量）
    override_params = None
    if USE_DYNAMIC_PARAMS:
        evolved = load_evolved_params()
        if evolved:
            override_params = evolved
            print(f"[STRATEGY] Evolved params loaded: {evolved}")

    results = screen_stocks(today_df, history_df, target_date, override_params=override_params)

    # v7.6: 基本面因子二次过滤（ROE、净利润增速）
    if len(results) > 0:
        try:
            from data_loader import load_all_factors
            factor_df = load_all_factors(codes=results['代码'].tolist())
            if len(factor_df) > 0:
                results = results.merge(factor_df[['代码', 'ROE', '净利润增速', '负债率']], on='代码', how='left')
                before = len(results)
                # 硬性过滤：ROE <= 0 或 净利润增速 <= -20% 剔除
                mask_keep = (
                    (results['ROE'].isna()) | (results['ROE'] > 0)
                ) & (
                    (results['净利润增速'].isna()) | (results['净利润增速'] > -20)
                )
                results = results[mask_keep].copy()
                after = len(results)
                if after < before:
                    print(f"[STRATEGY] Fundamental filter removed {before - after} stocks (ROE<=0 or profit growth<=-20%)")
                # 如果有负债率，高负债（>80%）警告
                if '负债率' in results.columns:
                    high_debt = results[results['负债率'] > 80]
                    if len(high_debt) > 0:
                        print(f"[STRATEGY] WARNING: {len(high_debt)} stocks with debt ratio > 80%")
        except Exception as e:
            print(f"[STRATEGY] Fundamental filter skipped: {e}")

    if target_date is None:
        basename = os.path.basename(today_file)
        file_date_str = basename.replace('stock_', '').replace('.csv', '')
        target_date = f"{file_date_str[:4]}-{file_date_str[4:6]}-{file_date_str[6:8]}"

    # 获取市场状态用于报告渲染
    idx_data = fetch_hs300_data()
    regime, _ = detect_market_regime(idx_data)
    adaptive = get_adaptive_params(regime) if USE_DYNAMIC_PARAMS else get_adaptive_params(None)

    if len(results) == 0:
        md = f"# 量化选股结果 - {target_date}\n\n> 今日无股票通过筛选条件。\n"
    else:
        md = render_markdown(results, target_date, adaptive, regime)

    date_tag = str(target_date).replace('-', '')
    output_file = os.path.join(RESULTS_DIR, f'pick_{date_tag}.md')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"[STRATEGY] Report: {output_file}")

    summary = generate_summary(results) if len(results) > 0 else "无股票通过筛选。"
    print(f"\n[SUMMARY] {summary}")

    return 0


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(target))
