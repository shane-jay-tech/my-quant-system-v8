"""
新手保护期管理 v2 — 3阶段保护：观察期 → 模拟期 → 实盘预备期
- v2: 表现驱动阶段切换，4指标综合评分
- 时间保底机制防止用户卡住

阶段：
- 观察期 (第1-5天): 推送标注 [观察期 - 请勿实盘]，强化学习
- 模拟期 (第6-10天): 推送标注 [模拟期 - 建议同比例模拟]，对比收益
- 实盘预备期 (第11天起): 根据模拟结果决定是否推荐实盘

状态文件: data/newbie_status.json
活动追踪: data/user_activity.json
"""
import os, sys, json
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
PSYCH_DIR = os.path.join(BASE_DIR, 'psychology')
STATUS_FILE = os.path.join(DATA_DIR, 'newbie_status.json')
ACTIVITY_FILE = os.path.join(DATA_DIR, 'user_activity.json')

PHASES = {
    'observation': {'days': (0, 5), 'label': '观察期', 'css_class': 'observation'},
    'simulation': {'days': (6, 10), 'label': '模拟期', 'css_class': 'simulation'},
    'pre_live': {'days': (11, 999), 'label': '实盘预备期', 'css_class': 'pre_live'},
}

PHASE_ORDER = ['observation', 'simulation', 'pre_live']


def init_newbie_status():
    """初始化或加载新手状态"""
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            status = json.load(f)
        return status

    # 首次启动
    today = datetime.now().strftime('%Y-%m-%d')
    status = {
        'first_start_date': today,
        'current_phase': 'observation',
        'day_number': 1,
        'phase_start_date': today,
        'daily_pnl_history': [],
        'recommendation': '观察期 — 请勿实盘，仅学习系统操作流程',
    }
    save_newbie_status(status)
    return status


def save_newbie_status(status):
    """保存新手状态"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def update_newbie_status():
    """每日更新新手状态（流水线中每日调用）—— v2表现驱动"""
    status = init_newbie_status()

    first_date = datetime.strptime(status['first_start_date'], '%Y-%m-%d')
    today = datetime.now()
    day_number = (today - first_date).days + 1

    # v2: 使用check_readiness评估是否升级（保留时间保底）
    status['day_number'] = day_number

    # 先按时间确定最低阶段（保底机制）
    if day_number <= 5:
        min_phase = 'observation'
    elif day_number <= 10:
        min_phase = 'simulation'
    else:
        min_phase = 'pre_live'

    # 如果时间保底阶段高于当前阶段，强制升级
    current_phase = status['current_phase']
    try:
        current_idx = PHASE_ORDER.index(current_phase)
        min_idx = PHASE_ORDER.index(min_phase)
        if min_idx > current_idx:
            status['current_phase'] = min_phase
            status['phase_start_date'] = today.strftime('%Y-%m-%d')
            status['upgrade_type'] = 'passive_time'
            current_phase = min_phase
    except ValueError:
        pass

    # 检查表现驱动升级
    readiness = check_readiness()
    if readiness['ready'] and readiness['upgrade_type'] == 'passive':
        # 被动升级（连续建议未响应或时间保底）
        new_phase = apply_upgrade()
        if new_phase:
            status = init_newbie_status()  # re-read after upgrade
            current_phase = new_phase

    # 更新推荐
    status['day_number'] = day_number
    if current_phase == 'pre_live':
        status['recommendation'] = check_sim_performance()
    elif current_phase == 'simulation':
        status['recommendation'] = '模拟期 — 建议同比例模拟，记录每日盈亏对比'
    else:
        status['recommendation'] = '观察期 — 请勿实盘，仅学习系统操作流程'

    save_newbie_status(status)
    return status


def check_sim_performance():
    """检查近5日模拟交易表现"""
    trades_file = os.path.join(SIM_DIR, 'trade_history.csv')
    equity_file = os.path.join(SIM_DIR, 'equity_curve.csv')

    if os.path.exists(equity_file):
        import pandas as pd
        try:
            eq = pd.read_csv(equity_file)
            if len(eq) >= 5:
                recent = eq.tail(5)
                start_eq = recent.iloc[0]['总权益']
                end_eq = recent.iloc[-1]['总权益']
                recent_pnl = (end_eq / start_eq - 1) * 100
                if recent_pnl > 0:
                    return f'模拟验证通过（近5日+{recent_pnl:.2f}%），可考虑实盘。建议小仓位开始，严格止损。'
                else:
                    return f'模拟亏损（近5日{recent_pnl:.2f}%），建议延长观察。继续模拟直到连续盈利。'
        except Exception:
            pass

    # 检查交易记录
    if os.path.exists(trades_file):
        import pandas as pd
        try:
            trades = pd.read_csv(trades_file)
            if len(trades) >= 3:
                recent_trades = trades.tail(5)
                win_count = (recent_trades['盈亏'] > 0).sum()
                total_pnl = recent_trades['盈亏'].sum()
                if total_pnl > 0 and win_count >= 3:
                    return f'近5笔交易：{win_count}胜，总盈亏+{total_pnl:+.0f}元。模拟验证通过，可考虑实盘。'
                else:
                    return f'近5笔交易：{win_count}胜，总盈亏{total_pnl:+.0f}元。建议继续模拟观察。'
        except Exception:
            pass

    return '模拟数据不足，继续积累交易记录后再评估。'


def get_phase_banner():
    """获取当前阶段的推送标签（v2: 区分主动/被动升级）"""
    status = init_newbie_status()
    phase = status.get('current_phase', 'observation')
    day = status.get('day_number', 1)
    upgrade_type = status.get('upgrade_type', '')

    if upgrade_type == 'passive' or upgrade_type == 'passive_time':
        extra = ' [系统自动推进]'
    elif upgrade_type == 'active':
        extra = ' [你主动迈出了这一步！]'
    else:
        extra = ''

    banners = {
        'observation': f'🔵 [观察期 第{day}天 - 请勿实盘] 以下为学习参考，不构成投资建议。请先熟悉系统操作。{extra}',
        'simulation': f'🟡 [模拟期 第{day}天 - 建议同比例模拟] 请用模拟盘或纸上记录跟踪，对比每日盈亏。{extra}',
        'pre_live': f'🟢 [实盘预备期 第{day}天] {check_sim_performance()}{extra}',
    }

    return banners.get(phase, banners['observation'])


def get_phase_psychology_tip():
    """获取当前阶段的心理学提示（v2: 含准备度评估）"""
    status = init_newbie_status()
    phase = status.get('current_phase', 'observation')
    day = status.get('day_number', 1)

    # v2: 获取准备度评估
    try:
        readiness = check_readiness()
        readiness_block = f"""

---
### 📊 你的升级准备度：{readiness['score']:.0f}/100分 ({readiness['passed_count']}/4项达标)

{readiness['summary']}

| 指标 | 得分 | 状态 |
|------|------|------|
"""
        for key, ind in readiness['indicators'].items():
            bar = '█' * int(ind['score'] / 25 * 5) + '░' * (5 - int(ind['score'] / 25 * 5))
            status_icon = '✅' if ind['score'] >= 12 else '⬜'
            readiness_block += f"| {ind['label']} | {bar} {ind['score']}/25 | {status_icon} |\n"
        readiness_block += f"\n*达标标准: 每项≥12分，总分≥50分即可升级*"
    except Exception:
        readiness_block = ''

    tips = {
        'observation': {
            'title': f'观察期第{day}天：建立交易认知',
            'body': f"""今天是你量化交易之旅的第{day}天。

核心任务：
1. 接收推送后，第二天开盘观察推荐股票的实际走势
2. 理解"止损"的含义：它不是惩罚，是保护
3. 不要着急入金，先看完5个交易日的推送和次日走势对比

交易的三个铁律：
- 每一笔交易都设止损
- 不要让一笔亏损影响下一笔决策
- 保护本金永远是第一位{readiness_block}""",
        },
        'simulation': {
            'title': f'模拟期第{day}天：纸上练兵',
            'body': f"""你已经观察了5天，现在进入模拟期（第{day}天）。

核心任务：
1. 在纸上或Excel记录：如果今天按推送买入，明天收盘盈亏多少
2. 连续记录5天，看看累计盈亏
3. 重点关注"止损触发频率"和"10日持有收益"

纪律建立：
- 每天只在开盘后30分钟内操作（模拟）
- 严格按照止损价执行（模拟平仓）
- 记录每笔交易的心理状态{readiness_block}""",
        },
        'pre_live': {
            'title': f'实盘预备期第{day}天：准备实战',
            'body': f"""恭喜完成10天新手训练。现在是实盘预备期（第{day}天）。

核心任务：
1. 回顾模拟期的盈亏记录
2. 如果模拟表现良好，可以考虑小仓位（总资金10-20%）实盘
3. 即使开始实盘，也要坚持先模拟、再实盘的原则

风险意识：
- 模拟盈利 ≠ 实盘盈利（滑点、手续费、心理压力）
- 前三笔实盘交易最容易犯错：过于谨慎或过于激进
- 建议：第一笔实盘不超过总资金的5%
- 永远不要追加保证金来"扳本"
{check_sim_performance()}{readiness_block}""",
        },
    }

    return tips.get(phase, tips['observation'])


# ═══════════════════════════════════════════════════════════
# v2: 表现驱动阶段切换
# ═══════════════════════════════════════════════════════════

def _load_activity():
    """加载用户活动记录"""
    if os.path.exists(ACTIVITY_FILE):
        with open(ACTIVITY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'learning_center_visits': [], 'ready_button_clicks': []}


def _save_activity(activity):
    """保存用户活动记录"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACTIVITY_FILE, 'w', encoding='utf-8') as f:
        json.dump(activity, f, ensure_ascii=False, indent=2)


def record_learning_visit():
    """记录一次学习中心访问（由app.py调用）"""
    activity = _load_activity()
    today = datetime.now().strftime('%Y-%m-%d')
    activity['learning_center_visits'].append(today)
    # 只保留最近30天
    activity['learning_center_visits'] = activity['learning_center_visits'][-100:]
    _save_activity(activity)


def record_ready_click():
    """记录用户点击'我觉得我准备好了'"""
    activity = _load_activity()
    activity['ready_button_clicks'].append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': datetime.now().strftime('%Y-%m-%d'),
    })
    _save_activity(activity)

    # 同时更新newbie状态
    status = init_newbie_status()
    status['ready_request_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    save_newbie_status(status)
    return True


def _count_recent_diaries(days=7):
    """统计最近N天的心理日记数量"""
    count = 0
    if not os.path.exists(PSYCH_DIR):
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    for f in os.listdir(PSYCH_DIR):
        if f.startswith('daily_') and f.endswith('.md'):
            try:
                date_str = f.replace('daily_', '').replace('.md', '')
                file_date = datetime.strptime(date_str, '%Y%m%d')
                if file_date >= cutoff:
                    count += 1
            except ValueError:
                pass
    return count


def _count_recent_learning_visits(days=7):
    """统计最近N天的学习中心访问次数"""
    activity = _load_activity()
    visits = activity.get('learning_center_visits', [])
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return sum(1 for v in visits if v >= cutoff)


def _count_real_trades():
    """统计真实交易记录数（排除示例数据）"""
    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(real_file):
        return 0
    try:
        import pandas as pd
        df = pd.read_csv(real_file, dtype={'代码': str})
        if '备注' in df.columns:
            df = df[~df['备注'].str.contains('示例', na=False)]
        return len(df)
    except Exception:
        return 0


def _evaluate_discipline():
    """评估近5笔真实交易的纪律表现（满分25分）"""
    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(real_file):
        return 0
    try:
        import pandas as pd
        df = pd.read_csv(real_file, dtype={'代码': str})
        if '备注' in df.columns:
            df = df[~df['备注'].str.contains('示例', na=False)]
        if len(df) < 2:
            return 0

        recent = df.tail(min(5, len(df)))
        score = 25

        # 检查是否有止损执行记录（卖出方向=遵守纪律）
        sells = recent[recent['方向'] == '卖出'] if '方向' in recent.columns else pd.DataFrame()
        if len(sells) > 0:
            # 有卖出记录说明在遵守操作纪律
            pass
        else:
            # 没有卖出记录，检查是否有浮亏超过8%仍未卖出的
            score -= 5

        # 检查备注中是否有纪律违规标记
        if '备注' in recent.columns:
            violations = recent['备注'].str.contains('违规|冲动|追高|情绪', na=False).sum()
            score -= violations * 5

        return max(0, min(25, score))
    except Exception:
        return 0


def check_readiness():
    """综合评估用户是否准备好进入下一阶段

    4项指标各25分，总分≥50分建议升级。

    返回 dict:
        ready: bool — 是否建议升级
        score: float — 总分 (0-100)
        indicators: dict — 各项指标得分
        upgrade_type: str — 'active'(主动)/'passive'(被动)/None
        summary: str — 人类可读的评估摘要
    """
    status = init_newbie_status()
    phase = status['current_phase']
    day = status['day_number']

    indicators = {}

    # 1. 学习主动度 (25分): 心理日记 + 学习中心访问
    diary_count = _count_recent_diaries(7)
    learning_visits = _count_recent_learning_visits(7)
    if diary_count >= 3 or learning_visits >= 2:
        study_score = 25
    elif diary_count >= 1 or learning_visits >= 1:
        study_score = 12
    else:
        study_score = 0
    indicators['study'] = {
        'score': study_score, 'max': 25,
        'label': '学习主动度',
        'detail': f'日记{diary_count}篇, 学习访问{learning_visits}次(近7天)',
    }

    # 2. 交易录入度 (25分)
    trade_count = _count_real_trades()
    if phase == 'simulation':
        required = 2
    elif phase == 'pre_live':
        required = 5
    else:
        required = 2
    trade_score = min(25, int(trade_count / max(1, required) * 25))
    indicators['trades'] = {
        'score': trade_score, 'max': 25,
        'label': '交易录入度',
        'detail': f'{trade_count}/{required}笔真实交易',
    }

    # 3. 纪律表现 (25分)
    discipline_score = _evaluate_discipline()
    indicators['discipline'] = {
        'score': discipline_score, 'max': 25,
        'label': '纪律表现',
        'detail': f'{discipline_score}/25分' + (' (数据不足)' if _count_real_trades() < 2 else ''),
    }

    # 4. 自评意愿 (25分) — 权重最高的指标
    ready_request = status.get('ready_request_date')
    if ready_request:
        try:
            req_date = datetime.strptime(ready_request[:10], '%Y-%m-%d')
            if (datetime.now() - req_date).days <= 3:
                indicators['self_eval'] = {
                    'score': 25, 'max': 25,
                    'label': '自评意愿',
                    'detail': f'用户于{ready_request[:10]}主动表示准备好',
                }
            else:
                indicators['self_eval'] = {
                    'score': 10, 'max': 25,
                    'label': '自评意愿',
                    'detail': f'用户曾于{ready_request[:10]}表示准备好(已过期)',
                }
        except ValueError:
            indicators['self_eval'] = {'score': 25, 'max': 25, 'label': '自评意愿', 'detail': '用户主动表示准备好'}
    else:
        indicators['self_eval'] = {
            'score': 0, 'max': 25,
            'label': '自评意愿',
            'detail': '尚未点击"我觉得我准备好了"',
        }

    total_score = sum(v['score'] for v in indicators.values())
    passed_count = sum(1 for v in indicators.values() if v['score'] >= 12)

    # 判断是否建议升级
    ready = total_score >= 50

    # 处理连续建议计数
    suggestions = status.get('upgrade_suggestions', 0)
    upgrade_type = None

    if ready:
        suggestions += 1
        status['upgrade_suggestions'] = suggestions

        if suggestions >= 3:
            upgrade_type = 'passive'  # 连续3天建议未响应，被动升级
        else:
            upgrade_type = 'active'  # 主动达标，等待用户确认
    else:
        suggestions = 0
        status['upgrade_suggestions'] = 0

    # 时间保底：超过阶段最大天数+5天，强制升级
    phase_max_days = {'observation': 10, 'simulation': 15}
    max_days = phase_max_days.get(phase, 15)
    if day >= max_days:
        ready = True
        upgrade_type = 'passive'
        status['upgrade_suggestions'] = 99  # 标记为保底升级

    save_newbie_status(status)

    # 生成人类可读摘要
    indicator_names = ['study', 'trades', 'discipline', 'self_eval']
    passed = [indicators[k]['label'] for k in indicator_names if indicators[k]['score'] >= 12]
    not_passed = [indicators[k]['label'] for k in indicator_names if indicators[k]['score'] < 12]

    if upgrade_type == 'active':
        summary = f'恭喜！你已满足{len(passed)}/{len(indicator_names)}项指标（{passed}），建议进入下一阶段。请在仪表盘确认。'
    elif upgrade_type == 'passive':
        if status.get('upgrade_suggestions', 0) == 99:
            summary = f'时间保底触发：已在新手期{day}天，系统自动推进至下一阶段。'
        else:
            summary = f'已连续{suggestions}天建议升级但未收到确认，系统自动推进至下一阶段。'
    else:
        if total_score >= 30:
            summary = f'还需努力：已通过{passed}，还需加强{not_passed}。继续加油！'
        else:
            summary = f'刚刚开始：已通过{passed}，继续按照系统指引积累经验。'

    return {
        'ready': ready,
        'score': total_score,
        'indicators': indicators,
        'upgrade_type': upgrade_type,
        'summary': summary,
        'passed_count': passed_count,
    }


def apply_upgrade():
    """执行阶段升级（由app.py或用户确认触发）"""
    status = init_newbie_status()
    phase = status['current_phase']

    try:
        idx = PHASE_ORDER.index(phase)
        if idx < len(PHASE_ORDER) - 1:
            new_phase = PHASE_ORDER[idx + 1]
        else:
            return None  # 已经是最高阶段
    except ValueError:
        return None

    status['current_phase'] = new_phase
    status['phase_start_date'] = datetime.now().strftime('%Y-%m-%d')
    status['upgrade_suggestions'] = 0
    status['upgrade_type'] = 'active'  # will be overwritten if passive
    status.pop('ready_request_date', None)

    # 更新推荐语
    if new_phase == 'simulation':
        status['recommendation'] = '模拟期 — 建议同比例模拟，记录每日盈亏对比'
    elif new_phase == 'pre_live':
        status['recommendation'] = check_sim_performance()

    save_newbie_status(status)
    return new_phase


def main():
    print(f"{'='*50}")
    print(f"  Newbie Protection v2 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    status = update_newbie_status()

    print(f"\n[PROTECTION] Newbie status:")
    print(f"  Phase: {status['current_phase']}")
    print(f"  Day: {status['day_number']}")
    print(f"  First start: {status['first_start_date']}")
    rec = status['recommendation']
    try:
        print(f"  Recommendation: {rec}")
    except UnicodeEncodeError:
        print(f"  Recommendation: (see data/newbie_status.json)")

    banner = get_phase_banner()
    try:
        print(f"\n[PROTECTION] Push banner: {banner[:80]}...")
    except UnicodeEncodeError:
        print(f"\n[PROTECTION] Push banner saved to data/newbie_status.json")

    tip = get_phase_psychology_tip()
    print(f"\n[PROTECTION] Psychology tip:")
    try:
        print(f"  Title: {tip['title']}")
    except UnicodeEncodeError:
        print(f"  Title: (see psychology diary)")
    print(f"  Phase: {status['current_phase']}, Day: {status['day_number']}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
