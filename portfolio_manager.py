"""
持仓状态管理 v1 — 维护理论持仓追踪 portfolio_state.json

设计：
- 假设用户按 v8 推荐执行（理论持仓），实际偏离由 behavior_log.py 单独追踪
- 每天 daily_pipeline 末尾根据当日订单更新持仓
- exit_advisor 标记卖出后从持仓中移除
- position_sizer 加载持仓，从 picks 中 exclude 已持仓代码避免重复买入

格式：
{
  "as_of": "2026-05-19",
  "positions": [
    {"代码":"600050","名称":"中国联通","买入日期":"2026-05-18","买入价":4.64,
     "股数":100,"成本":464,"止损价":4.46,"持有日数":1}
  ],
  "history": [
    {"代码":"...","买入日期":"...","卖出日期":"...","盈亏%":1.5,"出场原因":"..."}
  ]
}
"""
import os
import sys
import json
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATE_FILE = os.path.join(DATA_DIR, 'portfolio_state.json')

import sys
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION


def _today_str():
    return datetime.now().strftime('%Y-%m-%d')


def load_state():
    """加载持仓状态。无文件时返回空模板。"""
    if not os.path.exists(STATE_FILE):
        return {'as_of': _today_str(), 'positions': [], 'history': []}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        # 兼容性兜底
        state.setdefault('positions', [])
        state.setdefault('history', [])
        return state
    except Exception as e:
        print(f"[PORTFOLIO] state load failed: {e}; reset to empty")
        return {'as_of': _today_str(), 'positions': [], 'history': []}


def save_state(state):
    """保存持仓状态。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    state['as_of'] = _today_str()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_held_codes():
    """快速获取当前持仓代码集合（供 position_sizer exclude 用）。"""
    state = load_state()
    return {p['代码'] for p in state.get('positions', [])}


def add_positions_from_orders(orders):
    """根据当日订单（理论上已成交）添加到持仓。

    Args:
        orders: list of dicts，至少含 代码/名称/价格/股数/金额/止损价
    Returns:
        新增持仓数
    """
    state = load_state()
    held = {p['代码'] for p in state['positions']}
    added = 0
    today = _today_str()
    for o in orders:
        code = str(o.get('代码', '')).zfill(6)
        if not code or code in held:
            continue
        state['positions'].append({
            '代码': code,
            '名称': o.get('名称', ''),
            '买入日期': today,
            '买入价': float(o.get('价格', 0)),
            '股数': int(o.get('股数', 0)),
            '成本': float(o.get('金额', 0)),
            '止损价': float(o.get('止损价', 0) or 0),
            '持有日数': 0,
        })
        added += 1
        held.add(code)
    save_state(state)
    return added


def remove_position(code, exit_price, exit_reason):
    """卖出后从持仓移除并写入 history。

    Returns: dict（被移除的 position with 盈亏）or None
    """
    state = load_state()
    code = str(code).zfill(6)
    target = None
    new_positions = []
    for p in state['positions']:
        if p['代码'] == code:
            target = p
        else:
            new_positions.append(p)
    if target is None:
        return None
    state['positions'] = new_positions

    pnl_pct = (exit_price / target['买入价'] - 1) * 100 if target['买入价'] > 0 else 0
    record = {
        **target,
        '卖出日期': _today_str(),
        '卖出价': exit_price,
        '盈亏%': round(pnl_pct, 2),
        '出场原因': exit_reason,
    }
    state['history'].append(record)
    save_state(state)
    return record


def increment_holding_days():
    """每个交易日开始时调用一次，把所有持仓的'持有日数' +1。"""
    state = load_state()
    for p in state['positions']:
        p['持有日数'] = p.get('持有日数', 0) + 1
    save_state(state)
    return len(state['positions'])


def get_portfolio_summary():
    """返回当前持仓的简要 summary（供报告/Bark 推送用）。"""
    state = load_state()
    total_cost = sum(p.get('成本', 0) for p in state['positions'])
    return {
        'count': len(state['positions']),
        'total_cost': round(total_cost, 2),
        'codes': [p['代码'] for p in state['positions']],
        'history_count': len(state['history']),
    }


def sync_daily():
    """每日同步入口（pipeline 中一步即可完成所有持仓维护）

    1. 所有持仓 持有日数 +1
    2. 读 results/exit_advisor_*.json 最新一份，对 action 含 'sell' 的 → remove_position
    3. 读 orders/daily_orders_*.json 最新一份，对每个订单 → add_positions_from_orders（已内置 dedup）

    设计理念：理论持仓追踪 — 假设用户始终按系统推荐执行
    （实际偏离由 behavior_log.py 单独记录）
    """
    import glob
    base = os.path.dirname(os.path.abspath(__file__))

    # 1. +1 持有日数
    n_held = increment_holding_days()

    # 2. 处理 exit_advisor 卖出建议
    advisor_files = sorted(glob.glob(os.path.join(base, 'results', 'exit_advisor_*.json')), reverse=True)
    n_sold = 0
    if advisor_files:
        try:
            with open(advisor_files[0], 'r', encoding='utf-8') as f:
                advice = json.load(f)
            for entry in advice:
                action = entry.get('action', '')
                if 'sell' in action:
                    code = entry.get('code') or entry.get('代码')
                    exit_price = entry.get('current_price', 0) or entry.get('最新价', 0)
                    reason = entry.get('action_label', action)
                    rec = remove_position(code, exit_price, reason)
                    if rec:
                        n_sold += 1
                        print(f"[PORTFOLIO] sold: {code} @ {exit_price} ({reason}) pnl={rec['盈亏%']}%")
        except Exception as e:
            print(f"[PORTFOLIO] exit_advisor sync skipped: {e}")

    # 3. 处理新订单加入持仓
    order_files = sorted(glob.glob(os.path.join(base, 'orders', 'daily_orders_*.json')), reverse=True)
    n_added = 0
    if order_files:
        try:
            with open(order_files[0], 'r', encoding='utf-8') as f:
                order_data = json.load(f)
            orders = order_data.get('订单', []) if isinstance(order_data, dict) else order_data
            n_added = add_positions_from_orders(orders)
            if n_added > 0:
                print(f"[PORTFOLIO] added {n_added} new position(s) from latest orders")
        except Exception as e:
            print(f"[PORTFOLIO] order sync skipped: {e}")

    print(f"[PORTFOLIO] sync_daily: held={n_held}, sold={n_sold}, added={n_added}")
    return 0


def main():
    """命令行调用：默认跑 sync_daily 然后打印摘要"""
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'summary':
        # 仅打印摘要不同步
        pass
    else:
        sync_daily()

    state = load_state()
    summary = get_portfolio_summary()
    print(f"[PORTFOLIO] as_of={state['as_of']} | holdings={summary['count']} | "
          f"total_cost={summary['total_cost']} | history_records={summary['history_count']}")
    for p in state['positions']:
        print(f"  {p['代码']} {p['名称']} | 买入 {p['买入价']} × {p['股数']} = {p['成本']} | "
              f"持有 {p['持有日数']}日 | 止损 {p.get('止损价', 'N/A')}")
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
