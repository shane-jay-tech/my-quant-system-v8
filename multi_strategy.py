"""
多策略并行对比框架 v1 — 趋势跟随 + 均值回归 + 低波动率

功能：
1. 3个独立策略并行选股，各自打分排序
2. 对比报告：Top5、重叠度、历史胜率
3. 加权投票：策略权重基于近20日表现动态调整
4. 输出最终投票结果 → results/multi_strategy_YYYYMMDD.md
"""
import os, sys, json, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION

TOP_N_PER_STRATEGY = 15  # 每个策略的候选数
FINAL_TOP_N = 20         # 最终输出数
WEIGHT_WINDOW = 20        # 权重评估窗口（交易日）
WEIGHT_SMOOTH = 0.3       # 权重更新平滑系数

# ============================================================
# 基础策略类
# ============================================================
class BaseStrategy:
    def __init__(self):
        self.name = 'base'
        self.weight = 1.0
        self.perf_history = []  # [(date, win_rate_3d, win_rate_5d, avg_ret_5d)]

    def screen(self, today_df, history_df):
        """返回 DataFrame，包含 代码/名称/最新价/综合评分 等"""
        raise NotImplementedError

    def score_stock(self, stock_hist, today_row):
        """对单只股票评分，返回 (score, reasons)"""
        raise NotImplementedError


# ============================================================
# 策略1：趋势跟随
# ============================================================
class TrendFollowingStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.name = '趋势跟随'

    def screen(self, today_df, history_df):
        """复用现有 strategy.py 的选股逻辑"""
        from strategy import screen_stocks
        return screen_stocks(today_df, history_df)


# ============================================================
# 策略2：均值回归
# ============================================================
class MeanReversionStrategy(BaseStrategy):
    """
    寻找超跌反弹机会：
    - 价格在MA20之下但尚未跌破MA60太远
    - RSI从低位回升（<40但不在新低）
    - 近5日跌幅在3%-12%之间（有意义回撤但非崩盘）
    - 成交量在反弹日放大
    """
    def __init__(self):
        super().__init__()
        self.name = '均值回归'
        self.MCAP_MIN = 5e9

    def screen(self, today_df, history_df):
        today = today_df.copy()
        today['代码'] = today['代码'].astype(str).str.zfill(6)
        hist = history_df.copy()
        hist['代码'] = hist['代码'].astype(str).str.zfill(6)
        hist['日期'] = pd.to_datetime(hist['日期'])
        hist = hist.sort_values(['代码', '日期'])

        st_mask = today['名称'].str.contains(r'\*?ST', na=False, regex=True)
        st_codes = set(today.loc[st_mask, '代码'].tolist())
        non_st = today[~today['代码'].isin(st_codes)]
        valid = non_st[non_st['流通市值'] > self.MCAP_MIN].copy()

        results = []
        codes = valid['代码'].unique()
        for i, code in enumerate(codes):
            stock_hist = hist[hist['代码'] == code].copy()
            if len(stock_hist) < 60:
                continue
            stock_hist = stock_hist.sort_values('日期')
            close = stock_hist['收盘']
            high = stock_hist['最高']
            low = stock_hist['最低']
            vol = stock_hist['成交量']

            stock_hist['MA20'] = close.rolling(20).mean()
            stock_hist['MA60'] = close.rolling(60).mean()

            # RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            stock_hist['RSI'] = 100 - (100 / (1 + rs))

            stock_hist['VOL_MA20'] = vol.rolling(20).mean()
            stock_hist['VOL_RATIO'] = vol / stock_hist['VOL_MA20'].replace(0, np.nan)
            stock_hist['RET_5D'] = close.pct_change(5)

            latest = stock_hist.iloc[-1]
            price = latest['收盘']
            ma20 = latest.get('MA20', np.nan)
            ma60 = latest.get('MA60', np.nan)
            rsi = latest.get('RSI', np.nan)
            vol_ratio = latest.get('VOL_RATIO', np.nan)
            ret_5d = latest.get('RET_5D', np.nan)

            if pd.isna(ma20) or pd.isna(rsi):
                continue

            # 核心筛选：价格低于MA20，RSI从低点回升，非崩盘
            if not (price < ma20):
                continue
            if not (ma60 > 0 and price > ma60 * 0.85):
                continue
            if not (25 < rsi < 55):
                continue

            # RSI回升检测（5日前RSI更低）
            rsi_5d_ago = stock_hist['RSI'].iloc[-6] if len(stock_hist) >= 6 else rsi
            rsi_rising = rsi > rsi_5d_ago if pd.notna(rsi_5d_ago) else False

            # 评分
            score = 0
            reasons = []

            # 1. 偏离度 (25分)：适度偏离MA20
            dev_pct = (ma20 / price - 1) * 100
            if 3 <= dev_pct <= 10:
                score += 25
                reasons.append('适度超跌')
            elif 1 <= dev_pct < 3:
                score += 15
                reasons.append('轻度回撤')
            elif 10 < dev_pct <= 15:
                score += 10
                reasons.append('深度超跌')

            # 2. RSI低位回升 (25分)
            if 30 <= rsi < 40 and rsi_rising:
                score += 25
                reasons.append('RSI低位反弹')
            elif 40 <= rsi <= 50 and rsi_rising:
                score += 18
                reasons.append('RSI回升')
            elif 30 <= rsi < 40:
                score += 12
                reasons.append('RSI超卖')
            elif 25 < rsi < 55:
                score += 6

            # 3. 量能确认 (20分)
            if pd.notna(vol_ratio):
                if vol_ratio >= 1.5:
                    score += 20
                    reasons.append('放量反弹')
                elif vol_ratio >= 1.1:
                    score += 12
                elif vol_ratio >= 0.8:
                    score += 6

            # 4. 基本面 (15分)：MA60支撑
            if pd.notna(ma60) and price > ma60:
                score += 15
                reasons.append('MA60支撑')
            elif pd.notna(ma60) and price > ma60 * 0.95:
                score += 8

            # 5. 跌幅适中 (15分)：-12%到-3%最佳
            if pd.notna(ret_5d):
                if -10 <= ret_5d * 100 <= -3:
                    score += 15
                    reasons.append('跌幅适中')
                elif -15 <= ret_5d * 100 < -10:
                    score += 8
                elif -3 < ret_5d * 100 < 0:
                    score += 10

            today_row = today[today['代码'] == code]
            if len(today_row) == 0:
                continue
            today_row = today_row.iloc[0]

            if not reasons:
                reasons.append('超跌候选')

            results.append({
                '代码': code,
                '名称': today_row['名称'],
                '最新价': round(price, 2),
                '涨跌幅': today_row.get('涨跌幅', 0),
                'MA20': round(ma20, 2),
                'RSI': round(rsi, 2),
                '偏离MA20%': round(dev_pct, 1),
                '量比': round(vol_ratio, 2) if pd.notna(vol_ratio) else 0,
                '流通市值_亿': round(today_row.get('流通市值', 0) / 1e8, 2),
                '综合评分': score,
                '选入理由': ' + '.join(reasons),
            })

        results_df = pd.DataFrame(results)
        if len(results_df) > 0:
            results_df = results_df.sort_values('综合评分', ascending=False)
        return results_df


# ============================================================
# 策略3：低波动率
# ============================================================
class LowVolatilityStrategy(BaseStrategy):
    """
    寻找低波动、稳定上行品种：
    - 20日年化波动率低（<30%优先）
    - 正收益趋势（近20日收益>0）
    - 高Sharpe-like比率
    - 避免急涨急跌（最大回撤小）
    """
    def __init__(self):
        super().__init__()
        self.name = '低波动率'
        self.MCAP_MIN = 5e9

    def screen(self, today_df, history_df):
        today = today_df.copy()
        today['代码'] = today['代码'].astype(str).str.zfill(6)
        hist = history_df.copy()
        hist['代码'] = hist['代码'].astype(str).str.zfill(6)
        hist['日期'] = pd.to_datetime(hist['日期'])
        hist = hist.sort_values(['代码', '日期'])

        st_mask = today['名称'].str.contains(r'\*?ST', na=False, regex=True)
        st_codes = set(today.loc[st_mask, '代码'].tolist())
        non_st = today[~today['代码'].isin(st_codes)]
        valid = non_st[non_st['流通市值'] > self.MCAP_MIN].copy()

        results = []
        codes = valid['代码'].unique()
        for i, code in enumerate(codes):
            stock_hist = hist[hist['代码'] == code].copy()
            if len(stock_hist) < 30:
                continue
            stock_hist = stock_hist.sort_values('日期')
            close = stock_hist['收盘']

            # 日收益率
            returns = close.pct_change().dropna()
            if len(returns) < 20:
                continue

            # 20日年化波动率
            vol20 = returns.tail(20).std()
            ann_vol = vol20 * np.sqrt(252)  # 年化

            # 近20日累计收益
            ret_20d = (close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 else 0

            # Sharpe-like (无风险利率假设0)
            sharpe = ret_20d / (vol20 * np.sqrt(20) + 1e-9) if vol20 > 0 else 0

            # 最大回撤（近20日）
            roll_max = close.tail(20).cummax()
            drawdown = (close.tail(20) / roll_max - 1).min()

            # MA20
            ma20 = close.rolling(20).mean().iloc[-1]
            price = close.iloc[-1]

            # 筛选条件
            if ann_vol > 0.45:  # 年化波动率>45%排除
                continue
            if ret_20d < -0.12:  # 近20日跌超12%排除
                continue

            # 评分
            score = 0
            reasons = []

            # 1. 低波动 (35分)
            if ann_vol < 0.20:
                score += 35
                reasons.append('极低波动')
            elif ann_vol < 0.28:
                score += 28
                reasons.append('低波动')
            elif ann_vol < 0.35:
                score += 18
                reasons.append('中等波动')
            elif ann_vol <= 0.45:
                score += 8

            # 2. 正收益趋势 (20分)
            if ret_20d > 0.05:
                score += 20
                reasons.append('稳健上涨')
            elif ret_20d > 0.02:
                score += 15
                reasons.append('温和上涨')
            elif ret_20d > 0:
                score += 10
            elif ret_20d > -0.05:
                score += 5

            # 3. Sharpe-like (25分)
            if sharpe > 1.5:
                score += 25
                reasons.append('高Sharpe')
            elif sharpe > 0.8:
                score += 18
            elif sharpe > 0.3:
                score += 10

            # 4. 小回撤 (20分)
            if drawdown > -0.03:
                score += 20
                reasons.append('极小回撤')
            elif drawdown > -0.06:
                score += 14
                reasons.append('低回撤')
            elif drawdown > -0.10:
                score += 8

            today_row = today[today['代码'] == code]
            if len(today_row) == 0:
                continue
            today_row = today_row.iloc[0]

            if not reasons:
                reasons.append('低波候选')

            results.append({
                '代码': code,
                '名称': today_row['名称'],
                '最新价': round(price, 2),
                '涨跌幅': today_row.get('涨跌幅', 0),
                '年化波动率%': round(ann_vol * 100, 1),
                '20日收益%': round(ret_20d * 100, 2),
                'Sharpe': round(sharpe, 2),
                '最大回撤%': round(drawdown * 100, 2),
                '流通市值_亿': round(today_row.get('流通市值', 0) / 1e8, 2),
                '综合评分': score,
                '选入理由': ' + '.join(reasons),
            })

        results_df = pd.DataFrame(results)
        if len(results_df) > 0:
            results_df = results_df.sort_values('综合评分', ascending=False)
        return results_df


# ============================================================
# 投票器
# ============================================================
class StrategyVoter:
    """多策略加权投票"""
    def __init__(self, strategies, initial_weights=None):
        self.strategies = strategies
        if initial_weights:
            for s, w in zip(self.strategies, initial_weights):
                s.weight = w
        self.n_strategies = len(strategies)

    def vote(self, all_results):
        """
        加权投票 v2：策略内百分位排名 + 轻量共识加成

        - 每个策略内用百分位排名（0~100），避免某策略满分霸榜
        - 共识加成：[0.7-1.0]，1/3共识=0.8, 2/3=0.9, 3/3=1.0
        - 最终得分 = 百分位排名 × 共识加成

        Args:
            all_results: dict[strategy_name -> DataFrame]

        Returns:
            DataFrame sorted by combined score
        """
        vote_map = {}  # code -> {pct_score_sum, weight_sum, name, price, ...}

        for strat in self.strategies:
            df = all_results.get(strat.name)
            if df is None or len(df) == 0:
                continue

            # 策略内百分位排名：将综合评分映射到0-100百分位
            scores = df['综合评分'].values
            n = len(scores)
            if n > 1:
                # 排名 (越高越好) → 百分位 [0, 100]
                # 用numpy argsort稳定排名（ties按出现顺序，近似处理）
                order = scores.argsort()
                ranks = np.zeros(n)
                ranks[order] = np.arange(1, n + 1)  # 1..n
                pct_scores = (ranks - 1) / (n - 1) * 100  # 0 to 100
            else:
                pct_scores = np.array([100.0])

            for i, (_, row) in enumerate(df.iterrows()):
                code = row['代码']
                pct = pct_scores[i]
                weighted = pct * strat.weight
                rank_in_strat = i + 1
                if code not in vote_map:
                    vote_map[code] = {
                        '代码': code,
                        '名称': row.get('名称', ''),
                        '最新价': row.get('最新价', 0),
                        '涨跌幅': row.get('涨跌幅', 0),
                        '加权得分': 0,
                        '权重和': 0,
                        '各策略排名': {},
                        '各策略得分': {},
                    }
                vote_map[code]['加权得分'] += weighted
                vote_map[code]['权重和'] += strat.weight
                vote_map[code]['各策略排名'][strat.name] = rank_in_strat
                vote_map[code]['各策略得分'][strat.name] = row['综合评分']

        if not vote_map:
            return pd.DataFrame()

        # v8: 删除 consensus bonus
        # 旧逻辑：3/3 共识 ×1.0、1/3 共识 ×0.8 → 三个反向策略下倾向选"勉强 2/3 的边缘股"
        # 新逻辑：最终得分 = 加权得分 / 权重和；共识度仅作信息列、不影响排名
        # 让多样性回归：单策略 strong-pick 只要在该策略内排名靠前就能进决赛圈
        for code, v in vote_map.items():
            if v['权重和'] > 0:
                v['最终得分'] = round(v['加权得分'] / v['权重和'], 1)
            else:
                v['最终得分'] = 0
            v['共识度'] = f"{len(v['各策略排名'])}/{self.n_strategies}"

        results = sorted(vote_map.values(), key=lambda x: x['最终得分'], reverse=True)
        return pd.DataFrame(results)


# ============================================================
# 权重更新
# ============================================================
def update_strategy_weights(strategies, forward_returns_path=None):
    """
    基于近20日表现动态调整策略权重

    评估指标：5日胜率（>0即胜）+ 5日平均收益
    权重 = softmax(综合得分)，平滑更新
    """
    weights_file = os.path.join(DATA_DIR, 'strategy_weights.json')

    # 加载历史权重
    if os.path.exists(weights_file):
        with open(weights_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    else:
        history = {'records': [], 'current_weights': {}}

    # 如果有新的表现数据，评估并更新
    if forward_returns_path and os.path.exists(forward_returns_path):
        try:
            perf = pd.read_csv(forward_returns_path)
            new_scores = {}
            for strat in strategies:
                strat_perf = perf[perf['策略'] == strat.name]
                if len(strat_perf) > 0:
                    win_rate = (strat_perf['5日收益'] > 0).mean()
                    avg_ret = strat_perf['5日收益'].mean()
                    score = win_rate * 0.6 + max(0, avg_ret / 0.05) * 0.4  # 归一化
                    new_scores[strat.name] = round(score, 3)
                else:
                    new_scores[strat.name] = 0.5  # 无数据默认

            # softmax归一化
            scores = np.array(list(new_scores.values()))
            if scores.sum() > 0:
                exp_scores = np.exp(scores - scores.max())
                new_weights = exp_scores / exp_scores.sum()
            else:
                new_weights = np.ones(len(strategies)) / len(strategies)

            # 平滑更新
            old_weights = history.get('current_weights', {})
            for i, strat in enumerate(strategies):
                old_w = old_weights.get(strat.name, 1.0 / len(strategies))
                strat.weight = old_w * (1 - WEIGHT_SMOOTH) + new_weights[i] * WEIGHT_SMOOTH
                old_weights[strat.name] = round(strat.weight, 4)

            history['current_weights'] = old_weights
            history['records'].append({
                'date': datetime.now().strftime('%Y-%m-%d'),
                'scores': new_scores,
                'weights': old_weights,
            })
            # 保留最近60条
            history['records'] = history['records'][-60:]

            with open(weights_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[VOTER] Weight update skipped: {e}")
    else:
        # 使用已有权重
        current = history.get('current_weights', {})
        if current:
            for strat in strategies:
                strat.weight = current.get(strat.name, 1.0 / len(strategies))
        print(f"[VOTER] Using stored weights: { {s.name: round(s.weight, 3) for s in strategies} }")


# ============================================================
# 对比报告生成
# ============================================================
def generate_comparison_report(all_results, vote_results, strategies, target_date):
    """生成多策略对比Markdown报告"""
    lines = [
        f"# 多策略对比报告 — {target_date}",
        f"",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 策略数量：{len(strategies)} | 投票方式：加权投票",
        f"",
        f"## 策略权重",
        f"",
        f"| 策略 | 权重 | 说明 |",
        f"|------|------|------|",
    ]
    desc_map = {
        '趋势跟随': '捕捉强势上涨趋势中的龙头股',
        '均值回归': '寻找超跌反弹机会，逆向布局',
        '低波动率': '优选低波动稳健标的，控风险',
    }
    for s in strategies:
        desc = desc_map.get(s.name, '')
        lines.append(f"| {s.name} | {s.weight:.3f} | {desc} |")

    lines.extend(['', '## 各策略 Top 5', ''])

    strat_dfs = {}
    for s in strategies:
        df = all_results.get(s.name)
        if df is not None and len(df) > 0:
            strat_dfs[s.name] = df.head(TOP_N_PER_STRATEGY)
        else:
            strat_dfs[s.name] = pd.DataFrame()

    for name, df in strat_dfs.items():
        lines.append(f"### {name}")
        if len(df) == 0:
            lines.append('\n*无符合条件的股票*\n')
            continue

        top5 = df.head(5)
        # 确定该策略特有的列
        cols = ['代码', '名称', '最新价', '综合评分']
        extra_cols = [c for c in ['RSI', '偏离MA20%', '年化波动率%', 'Sharpe', '量比'] if c in df.columns]
        cols = cols[:2] + extra_cols[:2] + cols[2:]

        header = '| ' + ' | '.join(cols) + ' |'
        sep = '|' + '|'.join(['------'] * len(cols)) + '|'
        lines.append(header)
        lines.append(sep)
        for _, row in top5.iterrows():
            vals = []
            for c in cols:
                v = row.get(c, '')
                if isinstance(v, float):
                    v = f'{v:.2f}'
                vals.append(str(v))
            lines.append('| ' + ' | '.join(vals) + ' |')
        lines.append('')

    # 重叠度矩阵
    lines.extend(['## 策略重叠度', ''])
    strat_names = [s.name for s in strategies]
    lines.append('| 策略对 | 重叠数量 | 重叠率 |')
    lines.append('|--------|----------|--------|')
    for i in range(len(strat_names)):
        for j in range(i + 1, len(strat_names)):
            si = strat_dfs.get(strat_names[i], pd.DataFrame())
            sj = strat_dfs.get(strat_names[j], pd.DataFrame())
            if len(si) > 0 and len(sj) > 0:
                codes_i = set(si['代码'].tolist())
                codes_j = set(sj['代码'].tolist())
                overlap = codes_i & codes_j
                ov_count = len(overlap)
                ov_rate = ov_count / min(len(codes_i), len(codes_j)) * 100 if min(len(codes_i), len(codes_j)) > 0 else 0
                lines.append(f'| {strat_names[i]} vs {strat_names[j]} | {ov_count} | {ov_rate:.0f}% |')
            else:
                lines.append(f'| {strat_names[i]} vs {strat_names[j]} | N/A | N/A |')

    # 共识股票（被多个策略同时选中的）
    lines.extend(['', '## 高共识股票（被2+策略选中）', ''])
    if len(vote_results) > 0:
        high_consensus = vote_results[vote_results['各策略排名'].apply(lambda x: len(x) >= 2)]
        if len(high_consensus) > 0:
            lines.append('| 代码 | 名称 | 最新价 | 最终得分 | 共识度 | 策略排名 |')
            lines.append('|------|------|--------|----------|--------|----------|')
            for _, row in high_consensus.iterrows():
                rank_str = ' '.join(f'{k}#{v}' for k, v in row['各策略排名'].items())
                lines.append(f"| {row['代码']} | {row['名称']} | {row['最新价']:.2f} | {row['最终得分']:.1f} | {row['共识度']} | {rank_str} |")
        else:
            lines.append('*无高共识股票*')
    else:
        lines.append('*无投票结果*')

    lines.extend(['', '---', f'*报告由 multi_strategy.py v{SYSTEM_VERSION} 自动生成*'])
    return '\n'.join(lines)


# ============================================================
# 主流程
# ============================================================
def main():
    print(f"{'='*50}")
    print(f"  多策略并行对比框架 v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    # 加载数据
    today_str = datetime.now().strftime('%Y%m%d')
    today_file = os.path.join(DATA_DIR, f'stock_{today_str}.csv')
    if not os.path.exists(today_file):
        files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
        if not files:
            print("[FATAL] No stock data found")
            return 1
        today_file = files[0]

    history_file = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(history_file):
        print("[FATAL] No history data found")
        return 1

    print(f"[MULTI] Data: {today_file}")
    today_df = pd.read_csv(today_file, dtype={'代码': str})
    print(f"[MULTI] Today stocks: {len(today_df)}")

    print(f"[MULTI] History: {history_file}")
    history_df = pd.read_csv(history_file, dtype={'代码': str})

    # 初始化3个策略
    strategies = [
        TrendFollowingStrategy(),
        MeanReversionStrategy(),
        LowVolatilityStrategy(),
    ]

    # 更新权重
    perf_file = os.path.join(DATA_DIR, 'strategy_forward_returns.csv')
    update_strategy_weights(strategies, perf_file)

    print(f"\n[MULTI] Strategy weights:")
    for s in strategies:
        print(f"  {s.name}: {s.weight:.3f}")

    # 运行各策略
    all_results = {}
    for s in strategies:
        print(f"\n[MULTI] Running {s.name}...")
        try:
            df = s.screen(today_df, history_df)
            if df is not None and len(df) > 0:
                df = df.head(TOP_N_PER_STRATEGY)
                all_results[s.name] = df
                print(f"  {s.name}: {len(df)} picks, top score: {df['综合评分'].max()}")
            else:
                all_results[s.name] = pd.DataFrame()
                print(f"  {s.name}: 0 picks")
        except Exception as e:
            print(f"  {s.name}: ERROR - {e}")
            all_results[s.name] = pd.DataFrame()

    # 加权投票
    print(f"\n[MULTI] Voting...")
    voter = StrategyVoter(strategies)
    vote_results = voter.vote(all_results)

    if len(vote_results) > 0:
        vote_results = vote_results.head(FINAL_TOP_N)
        print(f"  Final picks: {len(vote_results)}")
        # 保存投票结果JSON，供 position_sizer 使用
        os.makedirs(ORDERS_DIR, exist_ok=True)
        vote_json = os.path.join(ORDERS_DIR, f'multi_vote_{today_str}.json')
        vote_results.to_json(vote_json, orient='records', force_ascii=False)
        print(f"  Vote saved: {vote_json}")
    else:
        print("  No consensus picks — all strategies returned empty")

    # 生成对比报告
    target_date = datetime.now().strftime('%Y-%m-%d')
    report = generate_comparison_report(all_results, vote_results, strategies, target_date)

    report_file = os.path.join(RESULTS_DIR, f'multi_strategy_{today_str}.md')
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n[MULTI] Report: {report_file}")

    # 简要摘要
    print(f"\n[MULTI] Summary:")
    for s in strategies:
        df = all_results.get(s.name, pd.DataFrame())
        print(f"  {s.name}: {len(df)} candidates (w={s.weight:.3f})")
    if len(vote_results) > 0:
        top3 = vote_results.head(3)
        for _, r in top3.iterrows():
            print(f"  ★ {r['代码']} {r['名称']}: score={r['最终得分']:.1f}, consensus={r['共识度']}")

    return 0


if __name__ == '__main__':
    sys.exit(main())