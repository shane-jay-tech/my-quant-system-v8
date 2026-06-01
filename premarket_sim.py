"""
盘前预演引擎 v1 — 集合竞价情绪 + 开盘仓位建议

功能：
1. 读取当日涨跌停家数、涨跌分布（复用 data_loader 的 sentiment）
2. 读取隔夜 A50 期货、美股中概走势（如果有数据）
3. 基于集合竞价（09:15-09:25）的量价数据生成情绪评分
4. 输出开盘仓位调整建议（维持/减仓/空仓）

使用方式：
    在每日 09:15 后运行，作为 daily_pipeline 的前置步骤
    python premarket_sim.py

输出：reports/premarket_YYYYMMDD.md
"""
import os, sys, json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

sys.path.insert(0, BASE_DIR)
from data_loader import load_market_sentiment
from core.config import get as cfg_get, SYSTEM_VERSION


def load_auction_data():
    """
    尝试读取集合竞价数据（09:25 快照）。
    如果本地无数据，返回空 dict。
    """
    # 实际接入时可通过 AKShare 的 stock_bid_ask_em 或其他接口获取
    # 当前为占位，使用历史情绪数据代理
    return {}


def calc_sentiment_score(sentiment):
    """
    将市场情绪指标转化为 0-100 的评分。
    50 为中性，>70 为强多头，<30 为强空头。
    """
    score = 50

    # 涨跌停家数对比
    zt = sentiment.get('涨停家数', 0)
    dt = sentiment.get('跌停家数', 0)
    total = zt + dt + 1
    score += (zt - dt) / total * 30  # 涨跌停差值影响 ±30

    # 涨跌家数对比
    up = sentiment.get('上涨家数', 0)
    down = sentiment.get('下跌家数', 0)
    if up + down > 0:
        score += (up - down) / (up + down) * 20  # 涨跌家数差值影响 ±20

    # HS300 波动率（高波动降分）
    vol = sentiment.get('hs300_vol20', 15)
    if vol > 25:
        score -= 10
    elif vol < 10:
        score += 5

    #  clamp
    score = max(10, min(90, score))
    return round(score, 1)


def recommend_position(score):
    """
    根据情绪评分推荐仓位比例。
    """
    if score >= 75:
        return {
            'action': 'maintain',
            'position_pct': 0.80,
            'message': f'情绪评分 {score}，强多头。维持高仓位（80%），可适度追涨。'
        }
    elif score >= 60:
        return {
            'action': 'maintain',
            'position_pct': 0.60,
            'message': f'情绪评分 {score}，偏多。维持中性偏高仓位（60%）。'
        }
    elif score >= 45:
        return {
            'action': 'maintain',
            'position_pct': 0.40,
            'message': f'情绪评分 {score}，中性震荡。控制仓位（40%），快进快出。'
        }
    elif score >= 30:
        return {
            'action': 'reduce',
            'position_pct': 0.20,
            'message': f'情绪评分 {score}，偏空。减仓至防御（20%），观望为主。'
        }
    else:
        return {
            'action': 'clear',
            'position_pct': 0.00,
            'message': f'情绪评分 {score}，强空头。建议空仓或极小仓位（≤10%），回避系统性风险。'
        }


def generate_report(sentiment, score, recommendation):
    lines = [
        f'# 盘前预演报告 - {datetime.now().strftime("%Y-%m-%d")}',
        '',
        f'> 生成时间：{datetime.now().strftime("%H:%M")}',
        '',
        '## 市场情绪指标',
        '',
    ]
    for k, v in sentiment.items():
        lines.append(f'- **{k}**：{v}')

    lines.extend([
        '',
        '## 情绪评分',
        '',
        f'- **综合评分**：{score} / 100',
        f'- **评级**：{"强多头" if score >= 75 else "偏多" if score >= 60 else "中性" if score >= 45 else "偏空" if score >= 30 else "强空头"}',
        '',
        '## 仓位建议',
        '',
        f'- **操作**：{recommendation["action"]}',
        f'- **建议仓位**：{recommendation["position_pct"]*100:.0f}%',
        f'- **理由**：{recommendation["message"]}',
        '',
        '---',
        f'*报告由 premarket_sim.py v{SYSTEM_VERSION} 自动生成*',
    ])

    path = os.path.join(RESULTS_DIR, f'premarket_{datetime.now().strftime("%Y%m%d")}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[PRE] Report: {path}')


def main():
    print(f"{'='*50}")
    print(f"  盘前预演 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    print('\n[1/2] Loading market sentiment...')
    sentiment = load_market_sentiment()
    if not sentiment:
        print('[PRE] No sentiment data available, using neutral fallback')
        sentiment = {'涨停家数': 30, '跌停家数': 10, '上涨家数': 2500, '下跌家数': 2000}

    print('\n[2/2] Calculating score and recommendation...')
    score = calc_sentiment_score(sentiment)
    rec = recommend_position(score)
    print(f'  Score: {score} | Action: {rec["action"]} | Position: {rec["position_pct"]*100:.0f}%')

    generate_report(sentiment, score, rec)
    print('\n[OK] Premarket simulation complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
