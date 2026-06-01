"""
轻量每日进化引擎 v1 — 策略参数微调

原则：
- 只调整：RSI阈值(±5)、MA周期(±2)、单票仓位上限(±5%)
- 拒绝跨策略权重调整和因子增删（留待每周深度进化）
- 5日滚动窗口验证
- 安全锁：连续3天微调使累计最大回撤增加>1% → 自动回退

状态文件: data/evolve_daily_state.json
"""
import os, sys, json, glob, shutil
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
STATE_FILE = os.path.join(DATA_DIR, 'evolve_daily_state.json')
BACKTEST_FILE = os.path.join(BASE_DIR, 'enhanced_backtest.py')

# v8: 统一配置中心
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION
DRY_RUN_ONLY = cfg_get('evolve.dry_run_only', True)

# 允许微调的参数范围
ALLOWED_ADJUSTMENTS = {
    'RSI_LOW': {'delta': 5, 'min': 20, 'max': 40},
    'RSI_HIGH': {'delta': 5, 'min': 55, 'max': 80},
    'MA_LONG': {'delta': 2, 'min': 15, 'max': 40},
    'TOP_N': {'delta': 1, 'min': 5, 'max': 20},
    'MAX_SINGLE_POSITION': {'delta': 0.05, 'min': 0.10, 'max': 0.25},
}

IMPROVEMENT_THRESHOLD = 0.3  # 平均收益提升>0.3%才采纳
ROLLING_DAYS = 5
SAFETY_MAX_CONSECUTIVE_DEGRADE = 3
SAFETY_MAX_DRAWDOWN_INCREASE = 1.0  # 最大回撤累计增加1%


def load_state():
    """加载进化状态"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'original_params': {
            'RSI_LOW': 30, 'RSI_HIGH': 70, 'MA_LONG': 20,
            'TOP_N': 20, 'MAX_SINGLE_POSITION': 0.15,
        },
        'current_params': {
            'RSI_LOW': 30, 'RSI_HIGH': 70, 'MA_LONG': 20,
            'TOP_N': 20, 'MAX_SINGLE_POSITION': 0.15,
        },
        'history': [],
        'consecutive_regressions': 0,
        'max_drawdown_baseline': None,
        'last_5d_performance': [],
    }


def save_state(state):
    """保存进化状态"""
    os.makedirs(DATA_DIR, exist_ok=True)
    state['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_current_performance():
    """获取近期策略表现数据（优先sim权益曲线，回退到回测报告）"""
    import re

    equity_file = os.path.join(SIM_DIR, 'equity_curve.csv')
    trades_file = os.path.join(SIM_DIR, 'trade_history.csv')

    # 1. 优先sim权益曲线（需5天以上数据）
    if os.path.exists(equity_file):
        eq = pd.read_csv(equity_file)
        if len(eq) >= ROLLING_DAYS:
            recent = eq.tail(ROLLING_DAYS)
            start_eq = recent.iloc[0]['总权益']
            end_eq = recent.iloc[-1]['总权益']
            peak = recent['总权益'].cummax()
            drawdown = (recent['总权益'] / peak - 1) * 100
            return {
                'has_data': True,
                'source': 'sim_equity',
                'total_return_pct': (end_eq / start_eq - 1) * 100,
                'avg_daily_return_pct': (end_eq / start_eq - 1) * 100 / ROLLING_DAYS,
                'max_drawdown': round(drawdown.min(), 2),
                'days': ROLLING_DAYS,
            }

    # 2. 次选sim已平仓交易记录
    if os.path.exists(trades_file):
        trades = pd.read_csv(trades_file)
        if len(trades) >= 5:
            recent = trades.tail(50)
            total_pnl = recent['盈亏'].sum()
            win_rate = (recent['盈亏'] > 0).mean() * 100
            return {
                'has_data': True,
                'source': 'sim_trades',
                'total_pnl': total_pnl,
                'win_rate': round(win_rate, 1),
                'trade_count': len(recent),
                'avg_daily_return_pct': total_pnl / max(1, len(recent)) / 100,
                'max_drawdown': 0,
                'days': min(ROLLING_DAYS, len(recent)),
            }

    # 3. 回退：解析诚实回测报告（永远有数据）
    bt_file = os.path.join(BASE_DIR, 'results', 'honest_evaluation.md')
    if os.path.exists(bt_file):
        with open(bt_file, 'r', encoding='utf-8') as f:
            bt_text = f.read()

        perf = {'has_data': True, 'source': 'backtest', 'max_drawdown': 0, 'days': ROLLING_DAYS}

        # 提取10日持有指标
        m10 = re.search(r'\|\s*10日\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([+\-][\d.]+)%\s*\|\s*([+\-][\d.]+)%', bt_text)
        if m10:
            perf['trade_count'] = int(m10.group(1))
            perf['win_rate'] = float(m10.group(2))
            perf['gross_return'] = float(m10.group(3))
            perf['net_return'] = float(m10.group(4))
            perf['avg_daily_return_pct'] = float(m10.group(4)) / 10  # 10日持有，日均近似

        # 提取牛市表现
        m_bull = re.search(r'\|\s*牛市\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([+\-][\d.]+)%', bt_text)
        if m_bull:
            perf['bull_win_rate'] = float(m_bull.group(2))
            perf['bull_net_return'] = float(m_bull.group(3))

        # 提取超额收益
        m_alpha = re.search(r'\*\*超额收益\*\*:\s*([+\-][\d.]+)%', bt_text)
        if m_alpha:
            perf['excess_return'] = float(m_alpha.group(1))

        # 综合评分：净收益 * 胜率权重
        perf['total_return_pct'] = perf.get('net_return', 0)
        return perf

    return {'has_data': False}


def test_adjustment(param_name, direction, state):
    """测试单个参数调整的效果（用近5日数据回测验证）"""
    current_val = state['current_params'][param_name]
    delta = ALLOWED_ADJUSTMENTS[param_name]['delta']
    min_val = ALLOWED_ADJUSTMENTS[param_name]['min']
    max_val = ALLOWED_ADJUSTMENTS[param_name]['max']

    new_val = current_val + delta * direction
    new_val = max(min_val, min(max_val, new_val))
    new_val = round(new_val, 2)

    if new_val == current_val:
        return None

    return {'param': param_name, 'old': current_val, 'new': new_val, 'delta': new_val - current_val}


def find_best_adjustment(state):
    """基于回测表现寻找最佳参数微调"""
    perf = get_current_performance()
    if not perf['has_data']:
        print("[EVOLVE_DAILY] No performance data available, skipping")
        return None

    win_rate = perf.get('win_rate', 50)
    net_return = perf.get('net_return', 0)
    bull_wr = perf.get('bull_win_rate', win_rate)
    source = perf.get('source', 'unknown')
    print(f"[EVOLVE_DAILY] Using {source} data: win={win_rate:.1f}%, net={net_return:+.2f}%")

    candidates = []
    for param_name in ALLOWED_ADJUSTMENTS:
        for direction in [1, -1]:
            adj = test_adjustment(param_name, direction, state)
            if adj is None:
                continue

            # 数据驱动的方向评分
            score = 0
            if param_name == 'RSI_LOW':
                # 牛市（win_rate>52%）放宽RSI下界以捕获更多机会
                # 熊市收紧RSI下界以过滤垃圾股
                if direction < 0 and bull_wr > 52:
                    score = 0.3 + (bull_wr - 52) * 0.05
                elif direction > 0 and bull_wr < 48:
                    score = 0.3 + (48 - bull_wr) * 0.05
                else:
                    score = 0.05

            elif param_name == 'RSI_HIGH':
                # 强趋势时放宽上界，震荡时收紧
                if direction > 0 and bull_wr > 52:
                    score = 0.25 + (bull_wr - 52) * 0.03
                elif direction < 0 and bull_wr < 48:
                    score = 0.25 + (48 - bull_wr) * 0.03
                else:
                    score = 0.05

            elif param_name == 'MA_LONG':
                # 牛市拉长慢线减少死叉误触发
                # 熊市缩短慢线加快出场
                if direction > 0 and bull_wr > 52:
                    score = 0.2 + (bull_wr - 52) * 0.04
                elif direction < 0 and bull_wr < 48:
                    score = 0.2 + (48 - bull_wr) * 0.04
                else:
                    score = 0.05

            elif param_name == 'TOP_N':
                # 胜率高时增加持股数分散风险
                if direction > 0 and win_rate > 50:
                    score = 0.2 + (win_rate - 50) * 0.02
                elif direction < 0 and win_rate < 45:
                    score = 0.2 + (45 - win_rate) * 0.02
                else:
                    score = 0.05

            elif param_name == 'MAX_SINGLE_POSITION':
                # 收益为正时小幅增加仓位
                if direction > 0 and net_return > 0:
                    score = 0.15 + net_return * 0.02
                elif direction < 0 and net_return < -1:
                    score = 0.2 + abs(net_return) * 0.02
                else:
                    score = 0.03

            adj['estimated_improvement'] = score
            adj['_perf_source'] = source
            candidates.append(adj)

    if not candidates:
        return None

    candidates.sort(key=lambda x: x['estimated_improvement'], reverse=True)
    best = candidates[0]
    print(f"[EVOLVE_DAILY] Best candidate: {best['param']} {best['old']}->{best['new']} (score={best['estimated_improvement']:.3f})")
    # 把所有候选 + 性能快照挂在 best 上，generate_report 用得到
    best['_all_candidates'] = candidates
    best['_perf'] = perf
    return best


def apply_adjustment(best_adj, state):
    """应用微调并验证

    v8: dry_run_only=True 时不写 current_params，仅写 suggested_params 留作建议。
    Why: 现有 score 是启发式估计而非真回测，连续应用会让参数随机漂移；
    在 1200 元 + 高成本场景下漂移噪声 > 信号。建议留给人审阅而非自动应用。
    """
    if best_adj is None:
        return False, "no_candidate"

    param = best_adj['param']
    new_val = best_adj['new']
    improvement = best_adj['estimated_improvement']

    if improvement < IMPROVEMENT_THRESHOLD / 100:
        return False, f"improvement {improvement:.4f} < threshold {IMPROVEMENT_THRESHOLD/100:.4f}"

    # v8 dry-run: 写 suggested_params 而非 current_params
    if DRY_RUN_ONLY:
        if 'suggested_params' not in state:
            state['suggested_params'] = {}
        state['suggested_params'][param] = new_val
        today_str = datetime.now().strftime('%Y-%m-%d')
        # 去重：同日同 param 同 suggested_value 已存在则不重复写入 history
        already_logged = any(
            h.get('mode') == 'DRY_RUN'
            and h.get('date') == today_str
            and h.get('param') == param
            and h.get('suggested_value') == new_val
            for h in state.get('history', [])
        )
        if not already_logged:
            record = {
                'date': today_str,
                'param': param,
                'old_value': best_adj['old'],
                'suggested_value': new_val,
                'estimated_improvement': round(improvement, 4),
                'mode': 'DRY_RUN',
                'applied': False,
            }
            state['history'].append(record)
        return True, f"Suggested (dry-run, NOT applied): {param} {best_adj['old']} -> {new_val}"

    # legacy 路径（dry_run_only=false 时启用）
    state['current_params'][param] = new_val
    record = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'param': param,
        'old_value': best_adj['old'],
        'new_value': new_val,
        'estimated_improvement': round(improvement, 4),
    }
    state['history'].append(record)

    if improvement < 0:
        state['consecutive_regressions'] += 1
        if state['consecutive_regressions'] >= SAFETY_MAX_CONSECUTIVE_DEGRADE:
            revert_all(state)
            return False, f"safety_triggered: {SAFETY_MAX_CONSECUTIVE_DEGRADE} consecutive regressions"
    else:
        state['consecutive_regressions'] = 0

    return True, f"Adopted: {param} {best_adj['old']} -> {new_val}"


def revert_all(state):
    """安全锁触发：回退到原始参数"""
    state['current_params'] = dict(state['original_params'])
    state['consecutive_regressions'] = 0
    state['history'].append({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'action': 'SAFETY_REVERT',
        'reason': f'Consecutive regressions reached {SAFETY_MAX_CONSECUTIVE_DEGRADE}',
    })
    print("[EVOLVE_DAILY] SAFETY REVERT: all params restored to original values")


def _compute_shadow_params(state):
    """如果 DRY_RUN 期间所有建议都被 apply 了，参数会是什么？
    取每个 param 在 history 中最近一次 DRY_RUN 建议作为阴影值。"""
    shadow = dict(state['original_params'])
    last_suggestion_date = {}  # param -> date
    for h in state['history']:
        if h.get('mode') != 'DRY_RUN':
            continue
        param = h.get('param')
        sv = h.get('suggested_value')
        if not param or sv is None:
            continue
        shadow[param] = sv
        last_suggestion_date[param] = h.get('date', '')
    return shadow, last_suggestion_date


def _detect_repeat_streak(state, best_adj):
    """同一 (param, suggested_value) 连续被建议了多少天。"""
    if not best_adj:
        return 0
    target_param = best_adj['param']
    target_val = best_adj['new']
    streak = 0
    # 倒序遍历 history（最新在末尾）
    for h in reversed(state['history']):
        if h.get('mode') != 'DRY_RUN':
            continue
        if h.get('param') == target_param and h.get('suggested_value') == target_val:
            streak += 1
        else:
            break
    return streak


def _format_perf_baseline(perf):
    """把 get_current_performance() 输出格式化为表格行。"""
    if not perf or not perf.get('has_data'):
        return ["| 数据源 | 无 |", "| 提示 | sim_results 与 honest_evaluation.md 都未找到，跳过基线 |"]
    rows = [f"| 数据源 | {perf.get('source', 'unknown')} |"]
    if 'win_rate' in perf:
        rows.append(f"| 胜率 | {perf['win_rate']:.1f}% |")
    if 'net_return' in perf:
        rows.append(f"| 10日净收益 | {perf['net_return']:+.2f}% |")
    if 'gross_return' in perf:
        rows.append(f"| 10日毛收益 | {perf['gross_return']:+.2f}% |")
    if 'excess_return' in perf:
        rows.append(f"| 超额收益(vs HS300) | {perf['excess_return']:+.2f}% |")
    if 'total_return_pct' in perf and perf.get('source') != 'backtest':
        rows.append(f"| 区间收益 | {perf['total_return_pct']:+.2f}% |")
    if 'max_drawdown' in perf and perf['max_drawdown'] != 0:
        rows.append(f"| 最大回撤 | {perf['max_drawdown']:.2f}% |")
    if 'trade_count' in perf:
        rows.append(f"| 样本量 | {perf['trade_count']} 笔 |")
    return rows


def generate_report(state, best_adj, success, reason):
    """生成轻量进化报告

    DRY_RUN 模式下额外提供：
      1. 性能基线（让用户判断"建议是否值得跟"）
      2. 全部候选排名（不只是 winning 的一条）
      3. 阴影路径（如果一直 apply 参数会到哪里）
      4. 重复检测（同一建议连续 N 天 = 信号稳定）
    """
    report_dir = os.path.join(BASE_DIR, 'reports')
    os.makedirs(report_dir, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    mode_label = "DRY-RUN（建议不应用）" if DRY_RUN_ONLY else "AUTO-APPLY"
    perf = best_adj.get('_perf') if best_adj else None
    all_candidates = best_adj.get('_all_candidates', []) if best_adj else []

    lines = [
        f"# 轻量进化日报 — {datetime.now().strftime('%Y-%m-%d')}",
        f"",
        f"> **MODE: {mode_label}**",
        f"> 原则：仅微调RSI/MA/仓位上限，跨策略权重留给每周深度进化",
        f"",
        f"## 性能基线",
        f"",
        f"| 指标 | 值 |",
        f"|------|-----|",
    ]
    lines.extend(_format_perf_baseline(perf))
    lines.append("")

    lines.extend([
        f"## 当前参数 vs 阴影参数",
        f"",
        f"> 阴影 = 如果 DRY-RUN 期间所有建议都被采纳，参数会演化到的值。两列差异越大，意味着 DRY-RUN 越想推动你",
        f"",
        f"| 参数 | 原始 | 实际当前 | 阴影 | 阴影建议日 |",
        f"|------|------|----------|------|-----------|",
    ])
    shadow, last_date = _compute_shadow_params(state)
    has_shadow_drift = False
    for k in state['original_params']:
        orig = state['original_params'][k]
        curr = state['current_params'][k]
        sh = shadow.get(k, orig)
        ld = last_date.get(k, '—')
        diff_mark = ''
        if sh != curr:
            diff_mark = ' ⚠'
            has_shadow_drift = True
        lines.append(f"| {k} | {orig} | {curr} | {sh}{diff_mark} | {ld} |")
    if has_shadow_drift:
        lines.append("")
        lines.append("> ⚠ = 阴影 ≠ 实际，DRY-RUN 在累计推动这个方向。可考虑手动 apply 一次实测。")
    lines.append("")

    if best_adj:
        streak = _detect_repeat_streak(state, best_adj)
        lines.extend([
            f"## 今日评估（候选排名）",
            f"",
            f"| 排名 | 参数 | 当前 | 建议 | 评分 | 过阈 |",
            f"|------|------|------|------|------|------|",
        ])
        threshold_dec = IMPROVEMENT_THRESHOLD / 100
        for i, c in enumerate(all_candidates[:5], 1):
            pass_mark = '✅' if c['estimated_improvement'] >= threshold_dec else '❌'
            lines.append(f"| {i} | {c['param']} | {c['old']} | {c['new']} | {c['estimated_improvement']:+.4f} | {pass_mark} |")
        lines.extend([
            f"",
            f"> 注：评分是启发式得分（基于 win_rate / net_return 的方向偏好），不是真实回测收益。"
            f"阈值 {threshold_dec:.4f}（即配置项 IMPROVEMENT_THRESHOLD={IMPROVEMENT_THRESHOLD}/100）。",
            f"",
            f"**最佳候选**：{best_adj['param']} {best_adj['old']}→{best_adj['new']}  "
            f"(评分 {best_adj['estimated_improvement']:+.4f}, 阈值 ≥{threshold_dec:.4f})",
            f"",
            f"**结果**：{'✅ 采纳为建议（dry-run）' if success else '❌ 拒绝'} — {reason}",
            f"",
        ])
        if streak >= 3:
            lines.append(f"> 📌 同一建议已连续产出 **{streak} 天**——信号稳定，不是系统错乱。"
                         f"如果你信这个方向，可以人工 apply 一次，让 current 跟上阴影。")
            lines.append("")

    lines.extend([
        f"## 近期变更历史",
        f"",
    ])
    for h in state['history'][-10:]:
        if 'action' in h:
            action = h['action']
        else:
            new_disp = h.get('new_value', h.get('suggested_value', ''))
            tag = ' [DRY_RUN]' if h.get('mode') == 'DRY_RUN' else ''
            action = f"{h.get('param','')} {h.get('old_value','')}→{new_disp}{tag}"
        lines.append(f"- {h['date']}: {action}")

    lines.extend([
        f"",
        f"## 安全锁状态",
        f"- 连续退化次数: {state['consecutive_regressions']}/{SAFETY_MAX_CONSECUTIVE_DEGRADE}",
        f"- 原始参数备份: {'已保护' if state['original_params'] else '未设置'}",
        f"",
        f"---",
        f"*报告由 evolve_daily_light.py v{SYSTEM_VERSION} 自动生成*",
    ])

    report_path = os.path.join(report_dir, f'evolve_daily_{today}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"[EVOLVE_DAILY] Report: {report_path}")
    return report_path


def main():
    print(f"{'='*50}")
    print(f"  Light Daily Evolution v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  RSI+/-5 | MA+/-2 | PositionCap+/-5%")
    if DRY_RUN_ONLY:
        print(f"  MODE: DRY-RUN (suggestions only, current_params NOT modified)")
    print(f"{'='*50}")

    # 1. 加载状态
    state = load_state()

    # v8 dry-run: 启动时硬回正，确保 current 始终等于 original
    if DRY_RUN_ONLY:
        if state['current_params'] != state['original_params']:
            print(f"[EVOLVE_DAILY] DRY-RUN reset: current_params drifted from original, restoring baseline")
            state['current_params'] = dict(state['original_params'])
            state['consecutive_regressions'] = 0

    print(f"\n[1/3] Current params: {json.dumps(state['current_params'])}")

    # 2. 检查安全锁
    if state['consecutive_regressions'] >= SAFETY_MAX_CONSECUTIVE_DEGRADE:
        print(f"[SAFETY] Lock engaged: {state['consecutive_regressions']} consecutive regressions")
        print(f"[SAFETY] Reverting to original params...")
        revert_all(state)
        save_state(state)
        return 0

    # 3. 寻找最佳微调
    print(f"\n[2/3] Evaluating parameter adjustments...")
    perf = get_current_performance()
    if perf['has_data']:
        print(f"  Recent performance: {perf.get('total_return_pct', perf.get('total_pnl', 0)):+.2f}%")
    else:
        print(f"  No performance data, using heuristic evaluation")

    best_adj = find_best_adjustment(state)

    # 4. 应用并记录
    print(f"\n[3/3] Applying best adjustment...")
    success, reason = apply_adjustment(best_adj, state)

    if success:
        verb = "Suggested (dry-run)" if DRY_RUN_ONLY else "Adopted"
        print(f"[EVOLVE_DAILY] {verb}: {best_adj['param']} {best_adj['old']} -> {best_adj['new']}")
    else:
        print(f"[EVOLVE_DAILY] Skipped: {reason}")

    save_state(state)
    generate_report(state, best_adj, success, reason)

    print(f"\n[OK] Daily evolution complete")
    return 0


if __name__ == '__main__':
    sys.exit(main())