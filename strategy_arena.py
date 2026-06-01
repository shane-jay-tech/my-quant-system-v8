"""
策略竞技引擎 v1 — 多策略并行竞技 + 自动淘汰与进化

功能：
1. 同时维护 N 套策略参数（变异组），每套有独立模拟资金
2. 每日运行所有变异组选股和模拟交易
3. 每月评估：按夏普率/最大回撤综合评分，淘汰最后 1-2 名
4. 引入新的随机变异参数替代被淘汰者
5. 输出竞技排名报告

使用方式：
    python strategy_arena.py
    # 或在 weekly_health_check.bat 中每月调用

输出：reports/arena_ranking_YYYYMMDD.md
"""
import os, sys, json, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION

ARENA_CONFIG = os.path.join(DATA_DIR, 'arena_config.json')
N_STRATEGIES = cfg_get('arena.n_strategies', 5)     # 同时竞技的策略数
INITIAL_CAPITAL = cfg_get('arena.initial_capital', 100_000)
REBALANCE_DAYS = cfg_get('arena.rebalance_days', 20)  # 每 20 交易日评估一次
TOP_KEEP = cfg_get('arena.top_keep', 3)               # 保留前几名
MUTATION_RATE = cfg_get('arena.mutation_rate', 0.3)   # 新参数变异幅度


def load_arena_state():
    if os.path.exists(ARENA_CONFIG):
        with open(ARENA_CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    return create_initial_state()


def create_initial_state():
    """创建初始竞技阵容：基准 + 若干变异。"""
    base = {
        'MA_LONG': 30,
        'RSI_LOW': 30,
        'RSI_HIGH': 70,
        'TOP_N': 10,
        'STOP_LOSS': -0.08,
    }
    strategies = []
    strategies.append({'id': 'base', 'name': '基准策略', 'params': base.copy(), 'capital': INITIAL_CAPITAL})

    np.random.seed(42)
    for i in range(1, N_STRATEGIES):
        params = base.copy()
        params['MA_LONG'] += int(np.random.randint(-5, 6))
        params['RSI_LOW'] += int(np.random.randint(-5, 6))
        params['RSI_HIGH'] += int(np.random.randint(-5, 6))
        params['TOP_N'] += int(np.random.randint(-3, 4))
        params['STOP_LOSS'] += round(np.random.uniform(-0.03, 0.03), 2)
        strategies.append({
            'id': f'mut_{i}',
            'name': f'变异{i}号',
            'params': params,
            'capital': INITIAL_CAPITAL,
        })

    state = {
        'created': datetime.now().strftime('%Y-%m-%d'),
        'last_eval': None,
        'strategies': strategies,
        'generation': 1,
    }
    save_arena_state(state)
    return state


def save_arena_state(state):
    with open(ARENA_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def evaluate_strategy(strategy_id, lookback_days=REBALANCE_DAYS):
    """
    评估单个策略近 N 日的模拟表现。
    从 sim_results 中提取该策略的权益曲线（如果有的话）。
    当前简化：读取统一模拟盘作为代理。
    """
    # 实际实现中，每个策略应有独立的 sim 账户
    # 此处简化：用 pick_tracker 或 equity_curve 的历史收益作为代理
    equity_file = os.path.join(SIM_DIR, 'equity_curve.csv')
    if not os.path.exists(equity_file):
        return {'sharpe': 0, 'max_dd': 0, 'return': 0, 'score': 0}

    df = pd.read_csv(equity_file)
    if '总权益' not in df.columns or len(df) < lookback_days // 2:
        return {'sharpe': 0, 'max_dd': 0, 'return': 0, 'score': 0}

    recent = df.tail(lookback_days)
    ret = recent['总权益'].pct_change().dropna()
    if len(ret) < 5 or ret.std() == 0:
        return {'sharpe': 0, 'max_dd': 0, 'return': 0, 'score': 0}

    sharpe = (ret.mean() / ret.std()) * np.sqrt(252)
    # 最大回撤
    peak = recent['总权益'].cummax()
    dd = (peak - recent['总权益']) / peak
    max_dd = dd.max()
    total_ret = recent['总权益'].iloc[-1] / recent['总权益'].iloc[0] - 1

    return {
        'sharpe': round(sharpe, 3),
        'max_dd': round(max_dd, 4),
        'return': round(total_ret, 4),
        'score': round(sharpe - max_dd * 5, 4),  # 综合评分：夏普 - 5×最大回撤
    }


def run_evaluation(state):
    """运行月度评估，淘汰末位策略，引入新变异。"""
    print(f'\n[ARENA] Generation {state["generation"]} evaluation...')
    strategies = state['strategies']

    # 评分
    for s in strategies:
        metrics = evaluate_strategy(s['id'])
        s['metrics'] = metrics
        s['score'] = metrics['score']
        print(f"  {s['name']}: return={metrics['return']:.2%}, sharpe={metrics['sharpe']:.2f}, max_dd={metrics['max_dd']:.2%}, score={metrics['score']:.3f}")

    # 排序
    strategies.sort(key=lambda x: x.get('score', 0), reverse=True)

    # 淘汰
    n_keep = min(TOP_KEEP, len(strategies))
    survivors = strategies[:n_keep]
    eliminated = strategies[n_keep:]

    if eliminated:
        print(f'\n[ARENA] Eliminated: {[e["name"] for e in eliminated]}')

    # 引入新变异（基于最优策略的变异）
    best = survivors[0]
    new_strategies = survivors.copy()
    for i in range(len(eliminated)):
        new_params = best['params'].copy()
        new_params['MA_LONG'] += int(np.random.randint(-3, 4))
        new_params['RSI_LOW'] += int(np.random.randint(-3, 4))
        new_params['RSI_HIGH'] += int(np.random.randint(-3, 4))
        new_params['TOP_N'] += int(np.random.randint(-2, 3))
        new_params['STOP_LOSS'] += round(np.random.uniform(-0.02, 0.02), 2)
        new_strategies.append({
            'id': f'gen{state["generation"]+1}_{i+1}',
            'name': f'第{state["generation"]+1}代-{i+1}号',
            'params': new_params,
            'capital': INITIAL_CAPITAL,
        })

    state['strategies'] = new_strategies
    state['generation'] += 1
    state['last_eval'] = datetime.now().strftime('%Y-%m-%d')
    save_arena_state(state)
    return state


def generate_report(state):
    lines = [
        f'# 策略竞技排名 - 第{state["generation"]}代 - {datetime.now().strftime("%Y-%m-%d")}',
        '',
        '| 排名 | 策略 | MA_LONG | RSI | TOP_N | 止损 | 收益率 | 夏普 | 最大回撤 | 综合评分 |',
        '|------|------|---------|-----|-------|------|--------|------|----------|----------|',
    ]

    for rank, s in enumerate(state['strategies'], 1):
        m = s.get('metrics', {})
        p = s['params']
        lines.append(
            f"| {rank} | {s['name']} | {p['MA_LONG']} | {p['RSI_LOW']}-{p['RSI_HIGH']} | "
            f"{p['TOP_N']} | {p['STOP_LOSS']:.0%} | {m.get('return', 0):.2%} | "
            f"{m.get('sharpe', 0):.2f} | {m.get('max_dd', 0):.2%} | {m.get('score', 0):.3f} |"
        )

    lines.extend([
        '',
        '---',
        f'*报告由 strategy_arena.py v{SYSTEM_VERSION} 自动生成*',
    ])

    path = os.path.join(RESULTS_DIR, f'arena_ranking_{datetime.now().strftime("%Y%m%d")}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[ARENA] Report: {path}')


def main():
    print(f"{'='*50}")
    print(f"  策略竞技引擎 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    # v8.6: 进化器优先级闸门——三个进化器都改 RSI/MA，arena 默认关，避免互相覆盖
    if not cfg_get('evolve_priority.arena_enabled', False):
        print('[ARENA] disabled by config (evolve_priority.arena_enabled=false). Skip.')
        print('[ARENA] 当下生效的进化路径是 evolve_daily_light（每日 ±5 微调）。')
        print('[ARENA] 如要启用 arena，请在 data/system_config.json 设 evolve_priority.arena_enabled=true。')
        return 0

    state = load_arena_state()

    # 检查是否需要评估
    if state['last_eval']:
        last = datetime.strptime(state['last_eval'], '%Y-%m-%d')
        days_since = (datetime.now() - last).days
        if days_since < REBALANCE_DAYS:
            print(f'[ARENA] Last eval {days_since}d ago, skip (threshold {REBALANCE_DAYS}d)')
            generate_report(state)
            return 0

    state = run_evaluation(state)
    generate_report(state)
    print('\n[OK] Strategy arena complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
