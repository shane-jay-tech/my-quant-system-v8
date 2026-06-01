"""
回放工具 — 假设从 2026-05-12 起严格按 pick_*.md 推荐执行交易，小资金条件下的真实收益曲线（本金跟随 sim.initial_capital 配置）。

规则（与用户确认）：
- 选股：每天只买评分最高、且当日开盘价×100 ≤ 现金×50% 的 1 只
- 卖出：止损 -8% / 止盈 +20% / 持有 ≥10 个交易日（系统默认风控，等同 exit_advisor 的 fallback 规则）
- 成本：双边佣金 max(5元, 0.03%) + 卖方印花税 0.05% + 双边滑点 0.1%（单边 0.05%）
- 成交：T+1 开盘价（pick 当日生成 → 次日开盘下单）

输出：
- reports/replay_picks_{today}.md
- sim_results/replay_equity.csv
- sim_results/replay_trades.csv
"""
import os
import re
import sys
from datetime import datetime
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION
# 2026-05-28：成本常量从 cost_model 单一真相源读取，
# 避免回放和实盘佣金/印花税/滑点不一致（v8 Phase 1.2 设计）
from cost_model import (
    COMMISSION_RATE,
    COMMISSION_MIN as COMMISSION_FLOOR,
    STAMP_TAX_RATE as STAMP_TAX,
    SLIP_LARGE,
)
# cost_model 的 SLIP_* 已是单边滑点率（cost_model.py:99 直接乘 amount）
SLIPPAGE_ONE_SIDE = SLIP_LARGE

DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

INITIAL_CAPITAL = float(cfg_get('sim.initial_capital', 2400))
# 小资金最大化收益：放开 50% 单票约束至 100%（小资金客观只能集中持仓）
MAX_SINGLE_POSITION_RATIO = 1.0
STOP_LOSS = -0.08
TAKE_PROFIT = 0.20
MAX_HOLD_DAYS = 10


def parse_pick_md(path):
    """解析 pick_*.md，返回 [{rank, code, name, score, last_close}, ...]

    兼容两种表头：
    - 老：排名|代码|名称|最新价|...|评分|...
    - 新：排名|代码|名称|板块|最新价|...|评分|...
    """
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    rows = []
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 6:
            continue
        # cells[0] 必须是 rank（纯数字），cells[1] 必须是 6 位 code
        if not cells[0].isdigit():
            continue
        if not (len(cells[1]) == 6 and cells[1].isdigit()):
            continue
        rank = int(cells[0])
        code = cells[1]
        name = cells[2]
        # 找第一个像价格的浮点数（跳过非数字列如"板块"）
        last_close = None
        last_close_idx = None
        for idx in range(3, len(cells)):
            try:
                v = float(cells[idx])
                last_close = v
                last_close_idx = idx
                break
            except ValueError:
                continue
        if last_close is None:
            continue
        # 评分是后面的整数列；兼容两种格式都用倒数推算（评分→风险→选入理由 是后三列）
        score = None
        if len(cells) >= 3:
            for cell in cells[last_close_idx + 1:]:
                try:
                    iv = int(cell)
                    if 0 <= iv <= 100:
                        score = iv
                except ValueError:
                    continue
        if score is None:
            continue
        rows.append({'rank': rank, 'code': code, 'name': name, 'last_close': last_close, 'score': score})
    rows.sort(key=lambda r: r['rank'])
    return rows


def load_history():
    df = pd.read_csv(os.path.join(DATA_DIR, 'history.csv'), encoding='utf-8-sig')
    df.columns = ['code', 'date', 'open', 'high', 'low', 'close', 'volume']
    df['code'] = df['code'].astype(str).str.zfill(6)
    df['date'] = df['date'].astype(str)
    return df


def load_picks():
    """{pick_date_str: [pick rows sorted by rank]}"""
    picks = {}
    for fn in sorted(os.listdir(RESULTS_DIR)):
        m = re.match(r'pick_(\d{8})\.md$', fn)
        if not m:
            continue
        date_str = m.group(1)
        date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        rows = parse_pick_md(os.path.join(RESULTS_DIR, fn))
        if rows:
            picks[date_iso] = rows
    return picks


def trading_cost_buy(notional):
    """买入双向成本（单边）：佣金 + 滑点"""
    commission = max(notional * COMMISSION_RATE, COMMISSION_FLOOR)
    slippage = notional * SLIPPAGE_ONE_SIDE
    return commission + slippage


def trading_cost_sell(notional):
    """卖出单边成本：佣金 + 印花税 + 滑点"""
    commission = max(notional * COMMISSION_RATE, COMMISSION_FLOOR)
    stamp = notional * STAMP_TAX
    slippage = notional * SLIPPAGE_ONE_SIDE
    return commission + stamp + slippage


def get_open_price(hist_df, code, date_iso):
    rec = hist_df[(hist_df['code'] == code) & (hist_df['date'] == date_iso)]
    if rec.empty:
        return None
    return float(rec.iloc[0]['open'])


def get_close_price(hist_df, code, date_iso):
    rec = hist_df[(hist_df['code'] == code) & (hist_df['date'] == date_iso)]
    if rec.empty:
        return None
    return float(rec.iloc[0]['close'])


def get_last_available_close(hist_df, code, on_or_before_date):
    """在 <= on_or_before_date 的范围内返回最近一次有数据的收盘价"""
    rec = hist_df[(hist_df['code'] == code) & (hist_df['date'] <= on_or_before_date)].sort_values('date')
    if rec.empty:
        return None
    return float(rec.iloc[-1]['close']), str(rec.iloc[-1]['date'])


def next_trading_day(trading_days, d):
    """返回 trading_days 中第一个 > d 的日期，没有则 None"""
    for td in trading_days:
        if td > d:
            return td
    return None


def main():
    print(f"=" * 60)
    print(f"  Replay Picks @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Capital: {INITIAL_CAPITAL} | StopLoss: {STOP_LOSS:.0%} | TakeProfit: {TAKE_PROFIT:.0%} | MaxHold: {MAX_HOLD_DAYS}d")
    print(f"=" * 60)

    hist = load_history()
    picks = load_picks()
    trading_days = sorted(hist['date'].unique())

    start_date = '2026-05-12'
    trading_days = [d for d in trading_days if d >= start_date]
    print(f"\n[1/3] Loaded {len(trading_days)} trading days, {len(picks)} pick files")

    cash = INITIAL_CAPITAL
    positions = []  # list of {'code','name','shares','entry_price','entry_date','entry_idx','entry_cost'}
    trades = []
    equity_curve = []

    print(f"\n[2/3] Replaying {trading_days[0]} -> {trading_days[-1]}...")

    for i, today in enumerate(trading_days):
        # ===== 盘前结算（在今天开盘价）=====
        # 1) SELL: 逐个检查持仓是否触发出场
        kept = []
        for pos in positions:
            today_open = get_open_price(hist, pos['code'], today)
            # 数据缺失日：fallback 到最近可用收盘价检查止损止盈
            sell_price_source = None
            if today_open is None:
                last = get_last_available_close(hist, pos['code'], today)
                if last is None:
                    kept.append(pos)
                    continue
                today_open = last[0]
                sell_price_source = f"fallback_close@{last[1]}"

            held_days = i - pos['entry_idx']  # 含今日
            ret_at_open = (today_open - pos['entry_price']) / pos['entry_price']

            sell_reason = None
            if ret_at_open <= STOP_LOSS:
                sell_reason = f"止损 {ret_at_open:+.2%}"
            elif ret_at_open >= TAKE_PROFIT:
                sell_reason = f"止盈 {ret_at_open:+.2%}"
            elif held_days >= MAX_HOLD_DAYS:
                sell_reason = f"到期 {held_days}日"

            if sell_reason and sell_price_source:
                sell_reason += f" [{sell_price_source}]"
            if sell_reason:
                notional = today_open * pos['shares']
                cost = trading_cost_sell(notional)
                proceeds = notional - cost
                cash += proceeds
                pnl = proceeds - (pos['entry_price'] * pos['shares'] + pos['entry_cost'])
                trades.append({
                    'code': pos['code'],
                    'name': pos['name'],
                    'entry_date': pos['entry_date'],
                    'exit_date': today,
                    'entry_price': pos['entry_price'],
                    'exit_price': today_open,
                    'shares': pos['shares'],
                    'pnl': round(pnl, 2),
                    'pnl_pct': round((today_open / pos['entry_price'] - 1) * 100, 2),
                    'reason': sell_reason,
                    'held_days': held_days,
                })
                print(f"  [{today}] SELL {pos['code']} {pos['name']} @ {today_open:.2f} | pnl={pnl:+.2f} ({sell_reason})")
            else:
                kept.append(pos)
        positions = kept

        # 2) BUY: 每天买 1 只（评分最高、一手价 ≤ 现金×50%、不在已持仓）
        avail_picks = sorted([d for d in picks if d < today])
        if avail_picks:
            pick_date = avail_picks[-1]
            held_codes = {p['code'] for p in positions}
            for row in picks[pick_date]:
                code = row['code']
                if code in held_codes:
                    continue
                today_open = get_open_price(hist, code, today)
                if today_open is None:
                    continue
                one_lot_price = today_open * 100
                if one_lot_price > cash * MAX_SINGLE_POSITION_RATIO:
                    continue
                cost = trading_cost_buy(one_lot_price)
                total_cost = one_lot_price + cost
                if total_cost > cash:
                    continue
                cash -= total_cost
                positions.append({
                    'code': code,
                    'name': row['name'],
                    'shares': 100,
                    'entry_price': today_open,
                    'entry_date': today,
                    'entry_idx': i,
                    'entry_cost': cost,
                })
                print(f"  [{today}] BUY  {code} {row['name']} @ {today_open:.2f} x100 (rank{row['rank']} score{row['score']}) | cost={cost:.2f} cash_left={cash:.2f}")
                break

        # 收盘记账：缺数据回退到最近可用收盘价
        pos_value = 0.0
        for pos in positions:
            close_p = get_close_price(hist, pos['code'], today)
            if close_p is None:
                last = get_last_available_close(hist, pos['code'], today)
                close_p = last[0] if last else pos['entry_price']
            pos_value += close_p * pos['shares']
        equity = cash + pos_value
        holdings_str = ' / '.join(f"{p['code']}" for p in positions) if positions else ''
        equity_curve.append({
            'date': today,
            'cash': round(cash, 2),
            'position_value': round(pos_value, 2),
            'equity': round(equity, 2),
            'return_pct': round((equity / INITIAL_CAPITAL - 1) * 100, 2),
            'holding': holdings_str,
        })

    # 强制收盘日清仓（用最后一日收盘价估值，但不平仓——用户当前实际持有）
    # 让最终持仓保留显示

    print(f"\n[3/3] Writing reports...")

    # ===== 输出 =====
    eq_df = pd.DataFrame(equity_curve)
    tr_df = pd.DataFrame(trades)
    os.makedirs(SIM_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    eq_path = os.path.join(SIM_DIR, 'replay_equity.csv')
    tr_path = os.path.join(SIM_DIR, 'replay_trades.csv')
    eq_df.to_csv(eq_path, index=False, encoding='utf-8-sig')
    tr_df.to_csv(tr_path, index=False, encoding='utf-8-sig')

    # HS300 基准（尝试多种 code，兼容 history.csv 不同入库方式）
    hs_return = None
    for hs_code in ['000300', '510300', '159919']:
        hs_rec = hist[(hist['code'] == hs_code) & (hist['date'] >= trading_days[0])].sort_values('date')
        if not hs_rec.empty:
            hs_start = float(hs_rec.iloc[0]['open'])
            hs_end = float(hs_rec.iloc[-1]['close'])
            hs_return = (hs_end / hs_start - 1) * 100
            break

    final_equity = equity_curve[-1]['equity']
    final_ret = (final_equity / INITIAL_CAPITAL - 1) * 100
    n_trades = len(trades)
    win_trades = sum(1 for t in trades if t['pnl'] > 0)
    win_rate = (win_trades / n_trades * 100) if n_trades else 0
    total_pnl = sum(t['pnl'] for t in trades)

    today_str = datetime.now().strftime('%Y%m%d')
    today_disp = datetime.now().strftime('%Y-%m-%d')

    lines = [
        f"# 严格按系统推荐执行 — 回放报告",
        f"",
        f"> 生成时间：{today_disp}",
        f"> 起始资金：CNY{INITIAL_CAPITAL:.0f} | 起始日：{trading_days[0]} | 截止：{trading_days[-1]}",
        f"> 规则：交给系统智能判断（不强制每日交易）。买入 = pick 评分最高且一手价 ≤ 全部现金的 1 只；卖出 = 止损-8%/止盈+20%/持10日（任一触发）。",
        f"> 成本：佣金max(5元,0.03%) + 卖方印花0.05% + 双边滑点0.1%。成交价：T+1 开盘价。数据缺失日按最近可用收盘价 fallback。",
        f"",
        f"## 总结",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 起始权益 | CNY{INITIAL_CAPITAL:.2f} |",
        f"| 当前权益 | CNY{final_equity:.2f} |",
        f"| **绝对收益** | **CNY{final_equity - INITIAL_CAPITAL:+.2f}** |",
        f"| **累计收益率** | **{final_ret:+.2f}%** |",
        f"| 同期 HS300 持有 | {hs_return:+.2f}% | " if hs_return is not None else "| 同期 HS300 持有 | 数据缺失 |",
        f"| 超额收益 | {final_ret - hs_return:+.2f}% |" if hs_return is not None else "",
        f"| 总交易（已平仓） | {n_trades} 笔 |",
        f"| 胜率 | {win_rate:.1f}% ({win_trades}/{n_trades}) |",
        f"| 总实现盈亏 | CNY{total_pnl:+.2f} |",
        f"| 当前持仓 | {('、'.join(p['code']+' '+p['name'] for p in positions)) if positions else '空仓'} |",
        f"",
        f"## 权益曲线",
        f"",
        f"| 日期 | 现金 | 持仓市值 | 总权益 | 累计收益% | 当日持仓 |",
        f"|------|------|----------|--------|-----------|----------|",
    ]
    for r in equity_curve:
        lines.append(f"| {r['date']} | {r['cash']:.2f} | {r['position_value']:.2f} | {r['equity']:.2f} | {r['return_pct']:+.2f}% | {r['holding']} |")

    lines.extend([
        f"",
        f"## 完整交易明细",
        f"",
    ])
    if trades:
        lines.append(f"| 代码 | 名称 | 入场日期 | 入场价 | 出场日期 | 出场价 | 股数 | 盈亏 | 盈亏% | 持有天数 | 出场原因 |")
        lines.append(f"|------|------|----------|--------|----------|--------|------|------|--------|----------|----------|")
        for t in trades:
            lines.append(f"| {t['code']} | {t['name']} | {t['entry_date']} | {t['entry_price']:.2f} | {t['exit_date']} | {t['exit_price']:.2f} | {t['shares']} | {t['pnl']:+.2f} | {t['pnl_pct']:+.2f}% | {t['held_days']} | {t['reason']} |")
    else:
        lines.append("（暂无平仓交易）")

    if positions:
        lines.extend([
            f"",
            f"## 当前持仓（未平仓）",
            f"",
            f"| 代码 | 名称 | 入场日期 | 入场价 | 最新价 | 当前估值 | 浮盈% | 已持 |",
            f"|------|------|----------|--------|--------|----------|-------|------|",
        ])
        last_idx = len(trading_days) - 1
        for pos in positions:
            last_close = get_close_price(hist, pos['code'], trading_days[-1])
            if last_close is None:
                fb = get_last_available_close(hist, pos['code'], trading_days[-1])
                last_close = fb[0] if fb else pos['entry_price']
            cur_val = last_close * pos['shares']
            floating = (last_close / pos['entry_price'] - 1) * 100
            held = last_idx - pos['entry_idx'] + 1
            lines.append(f"| {pos['code']} | {pos['name']} | {pos['entry_date']} | {pos['entry_price']:.2f} | {last_close:.2f} | {cur_val:.2f} | {floating:+.2f}% | {held}日 |")

    lines.extend([
        f"",
        f"---",
        f"*报告由 replay_picks.py v{SYSTEM_VERSION} 自动生成*",
    ])

    md_path = os.path.join(REPORTS_DIR, f'replay_picks_{today_str}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\n[OK] Report: {md_path}")
    print(f"     Equity: {eq_path}")
    print(f"     Trades: {tr_path}")
    print(f"\n=== SUMMARY ===")
    print(f"Final Equity:  {final_equity:.2f} (start {INITIAL_CAPITAL:.2f})")
    print(f"Cumulative:    {final_ret:+.2f}%")
    if hs_return is not None:
        print(f"HS300 same:    {hs_return:+.2f}%")
        print(f"Excess:        {final_ret - hs_return:+.2f}%")
    print(f"Trades closed: {n_trades} (win {win_trades})")
    print(f"Holdings now:  {len(positions)} - {', '.join(p['code']+' '+p['name'] for p in positions) if positions else 'None'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
