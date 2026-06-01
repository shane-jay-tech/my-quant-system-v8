"""
交易心理助手 v1 — 新手引导 + 每日心态检查 + 亏损安慰 + 周末学习

功能：
1. 首次使用引导：交易心理学基础 + 常见误区
2. 每日心态检查：根据账户盈亏生成心理提示
3. 亏损安慰：持仓浮亏时提供情绪支持
4. 周末学习任务：推荐阅读 + 复盘练习
5. 生成心理日记 psychology/daily_YYYYMMDD.md
"""
import os, sys, json, random
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')
PSYCH_DIR = os.path.join(BASE_DIR, 'psychology')
STATE_FILE = os.path.join(SIM_DIR, 'account_state.json')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION

# ── 心理学素材库 ──

ONBOARDING_GUIDE = """
# 新手交易心理指南

## 你即将开始量化交易之旅

在开始之前，请先接受三个事实：

### 事实1：你会亏钱
每一笔交易都有亏损的可能。这不是你的问题，这是市场的基本属性。
即使是华尔街最顶级的基金经理，胜率也就在50-55%左右。
我们的v5系统，10日胜率约54.5%，意味着每2笔交易中就有1笔会亏损。

### 事实2：盈亏比比胜率更重要
趋势跟踪策略天然"低胜率、高盈亏比"。什么意思？
- 你10次交易中可能亏5-6次
- 但盈利的那几次会涨很多（比如+15%、+20%）
- 亏损的那几次会被及时斩断（比如-5%、-8%）
- 最终，赚的比亏的多

### 事实3：情绪是你最大的敌人
- 贪婪会让你在该卖的时候不卖
- 恐惧会让你在该买的时候不敢买
- 过度交易会让你频繁进出，磨损本金

## 新手铁律（请遵守至少1个月）

1. **每只股票一样多的钱**：不要重仓某一只
2. **买入后设好止损单**：亏8%就卖，不要犹豫
3. **不要盯盘**：每天收盘后看一眼就够了
4. **不要补仓**：亏损的股票不是"便宜了"，是"趋势坏了"
5. **记录每一笔交易**：为什么买？为什么卖？情绪如何？

## 常见误区

- "跌了这么多应该到底了吧？" → 趋势跟踪不抄底
- "已经赚了10%该卖了吧？" → 让利润奔跑，直到趋势反转
- "今天大盘跌，我要赶紧卖出！" → 系统有止损，相信系统
"""

COMFORT_MESSAGES = {
    'big_loss': [
        """今天市场表现不好，账户有较大回撤。深呼吸——这是交易的一部分。

回顾交易的唯一标准：你遵守了系统规则吗？如果遵守了，就不要自责。

趋势跟踪策略中，30-40%的交易都会亏损，这是正常现象。""",
        """亏损的日子很难熬，但请记住：

1. 不要急于"扳本"——明天不要加大仓位
2. 不要修改止损线——那是保护你的安全网
3. 关掉交易软件，去做点别的事情

明天又是新的一天。""",
    ],
    'small_loss': [
        """小幅回撤是正常的市场波动。

策略需要时间才能体现出统计优势，单日涨跌不能说明问题。

建议：今天不要做任何操作决策。""",
    ],
    'profit': [
        """今天账户盈利，恭喜！

但要警惕一种心理：过度自信。

盈利后最常见的错误是：加大仓位、放宽止损、频繁交易。

保持纪律，像亏损时一样谨慎。""",
    ],
    'big_profit': [
        """今天赚了不少！给自己一个肯定，但不要过度兴奋。

研究表明：大赚之后的那一笔交易，亏损概率最高。

原因是：大赚后的交易者倾向于承担更大风险。

建议：今天早点休息，不要研究下一只股票。""",
    ],
}

WEEKEND_TASKS = [
    {
        'title': '核对真实交易记录',
        'task': """打开 real_trades.csv，确认本周所有真实交易都已录入。
如果遗漏了某笔交易：
- 运行 python log_real_trade.py 补录
- 或直接编辑 real_trades.csv（格式参考第一行）
记录完整的数据是策略进化的基础——系统会根据你的真实交易优化参数。""",
        'duration': '15分钟',
    },
    {
        'title': '复盘本周交易',
        'task': """打开 sim_results/sim_report.md，回顾本周的每一笔交易。
问自己三个问题：
1. 哪些交易是"系统告诉我的"？哪些是"我自己决定"的？
2. 亏损的交易中，我是否遵守了止损纪律？
3. 如果重来一次，我会做同样的选择吗？""",
        'duration': '30分钟',
    },
    {
        'title': '学习：趋势跟踪的本质',
        'task': """阅读《海龟交易法则》第一章。
核心观点：趋势跟踪靠的是"少数大赢家填补大量小亏损"。
思考：你能接受10次交易中亏损6次，但最终仍赚钱的策略吗？如果不能，为什么？""",
        'duration': '45分钟',
    },
    {
        'title': '检查你的情绪日志',
        'task': """回顾本周每天的心理日记。
找出情绪波动最大的那一天，写下：
- 发生了什么？
- 我当时的感觉是什么？
- 我做了什么操作？
- 回头看，这个操作对吗？""",
        'duration': '20分钟',
    },
    {
        'title': '测试：移除一个指标',
        'task': """思考一个问题：如果只能保留3个选股指标（目前是5个），你会保留哪3个？为什么？

写下来，这是一个很好的策略理解练习。""",
        'duration': '15分钟',
    },
]


def load_account_state():
    """加载账户状态"""
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def daily_psychology_check(state):
    """根据账户状态生成每日心态检查"""
    if state is None:
        return "今天还没有开始交易。心态平和是交易的第一课。耐心等待系统信号。"

    equity = state.get('equity', 100000)
    cash = state.get('cash', 100000)
    positions = state.get('positions', [])
    total_pnl = state.get('total_pnl', 0)
    winning = state.get('winning_trades', 0)
    total = state.get('total_trades', 0)

    # 计算今日浮盈
    floating_pnl = 0
    for p in positions:
        floating_pnl += p.get('unrealized_pnl', 0)

    daily_change_pct = floating_pnl / 100000 * 100

    messages = []

    # 心态状态判断
    if len(positions) == 0:
        messages.append("当前空仓或全现金。\n等待信号也是一种交易决策——不要因为\"闲着\"而勉强入场。")
    else:
        messages.append(f"当前持有 {len(positions)} 只股票。")

    if total > 0:
        wr = winning / total * 100
        messages.append(f"累计交易 {total} 笔，胜率 {wr:.1f}%，累计盈亏 {total_pnl:+.0f}元。")

    # 情绪提示
    if daily_change_pct < -2:
        messages.append(random.choice(COMFORT_MESSAGES['big_loss']))
    elif daily_change_pct < -0.5:
        messages.append(random.choice(COMFORT_MESSAGES['small_loss']))
    elif daily_change_pct > 3:
        messages.append(random.choice(COMFORT_MESSAGES['big_profit']))
    elif daily_change_pct > 0:
        messages.append(random.choice(COMFORT_MESSAGES['profit']))
    else:
        messages.append("今天市场平淡。平淡的日子最考验耐心——坚持执行系统，不要手痒。")

    # 仓位过重提醒
    if cash < 10000 and len(positions) > 0:
        messages.append("\n提醒：现金已不足1万元，仓位较重。如果市场回调，你可能没有弹药补仓。\n\n但记住：不要因为担心而提前卖出——按系统信号来。")

    return '\n\n'.join(messages)


def is_weekend():
    """判断今天是不是周末"""
    return datetime.now().weekday() >= 5  # 5=Sat, 6=Sun


def get_weekend_task():
    """获取周末学习任务"""
    # 根据当前是第几周轮换任务
    week_num = datetime.now().isocalendar()[1]
    task = WEEKEND_TASKS[week_num % len(WEEKEND_TASKS)]
    return task


def generate_psychology_diary(state):
    """生成每日心理日记"""
    os.makedirs(PSYCH_DIR, exist_ok=True)
    today = datetime.now()
    date_str = today.strftime('%Y%m%d')

    lines = [
        f"# 交易心理日记 — {today.strftime('%Y-%m-%d')} ({today.strftime('%A')})",
        f"",
        f"---",
        f"",
    ]

    # 新手保护期心理提示（v2: 区分主动/被动升级）
    try:
        from newbie_protection import get_phase_psychology_tip, init_newbie_status, check_readiness
        newbie_status = init_newbie_status()
        tip = get_phase_psychology_tip()
        upgrade_type = newbie_status.get('upgrade_type', '')

        # 区分主动/被动升级的鼓励语
        if upgrade_type == 'active':
            upgrade_cheer = '🌟 恭喜，你主动迈出了这一步！新阶段将给你更真实的交易体验。继续保持这份主动性。'
        elif upgrade_type in ('passive', 'passive_time'):
            upgrade_cheer = '⏰ 时间到了，系统已自动将你推进至新阶段。别担心，跟着节奏走，你会适应的。'
        else:
            upgrade_cheer = ''

        lines.extend([
            f"## 🆕 新手阶段心理提示：{tip['title']}",
            f"",
        ])
        if upgrade_cheer:
            lines.append(upgrade_cheer)
            lines.append("")
        lines.extend([
            tip['body'],
            f"",
            f"---",
            f"",
        ])
    except Exception:
        pass

    lines.extend([
        f"## 今日心态检查",
        f"",
    ])

    check = daily_psychology_check(state)
    lines.append(check)
    lines.append("")

    # 账户快照
    if state:
        equity = state.get('equity', 100000)
        pnl = state.get('total_pnl', 0)
        total = state.get('total_trades', 0)
        winning = state.get('winning_trades', 0)

        lines.extend([
            f"## 账户快照",
            f"",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 总权益 | {equity:,.0f}元 |",
            f"| 累计盈亏 | {pnl:+,.0f}元 |",
            f"| 累计交易 | {total}笔 |",
            f"| 胜率 | {winning/max(1,total)*100:.1f}% |",
            f"| 持仓数 | {len(state.get('positions', []))}只 |",
            f"",
        ])

    # 周末特别内容
    if is_weekend():
        # v7.5: 本周心情回顾
        mood_file = os.path.join(BASE_DIR, 'data', 'trading_mood.csv')
        if os.path.exists(mood_file):
            try:
                import pandas as pd
                mood_df = pd.read_csv(mood_file)
                mood_df['日期'] = pd.to_datetime(mood_df['日期'])
                week_ago = datetime.now() - timedelta(days=7)
                week_mood = mood_df[mood_df['日期'] >= week_ago]
                if len(week_mood) > 0:
                    mood_counts = week_mood['心情'].value_counts()
                    total = len(week_mood)
                    anxious_pct = mood_counts.get('焦虑', 0) / total * 100
                    happy_pct = mood_counts.get('开心', 0) / total * 100
                    neutral_pct = mood_counts.get('平静', 0) / total * 100

                    lines.extend(["## 本周心情回顾", ""])
                    if anxious_pct > 50:
                        lines.append("本周情绪偏沮丧。如果你感到焦虑，请记住：系统回测胜率54%，连续亏损是正常波动。不要让短期结果动摇你的纪律。")
                    elif happy_pct == 100:
                        lines.append("本周心态不错，每天都开心！继续保持纪律，不要让过度自信影响下一周的操作。")
                    elif happy_pct >= 60:
                        lines.append("本周心情总体积极。好的心态是交易成功的一半，继续保持。")
                    elif neutral_pct >= 50:
                        lines.append("本周心情以平静为主。平淡的交易日子最考验耐心，你在正确的轨道上。")
                    lines.append("")
                    lines.append(f"| 心情 | 天数 | 占比 |")
                    lines.append(f"|------|------|------|")
                    for mood_name in ['开心', '平静', '焦虑']:
                        cnt = mood_counts.get(mood_name, 0)
                        lines.append(f"| {mood_name} | {cnt}天 | {cnt/total*100:.0f}% |")
                    lines.append("")
            except Exception:
                pass

        task = get_weekend_task()
        lines.extend([
            f"## 周末学习任务：{task['title']}",
            f"",
            f"**预计时间**：{task['duration']}",
            f"",
            task['task'],
            f"",
            f"---",
            f"",
            f"完成这次学习后，给自己一个奖励。持续学习是交易者最重要的品质。",
            f"",
        ])

    lines.extend(["", "---", f"*日记由 psychology_assistant.py v{SYSTEM_VERSION} 自动生成*"])

    report_path = os.path.join(PSYCH_DIR, f'daily_{date_str}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"[PSYCH] Diary: {report_path}")
    return report_path, check


def main():
    print(f"{'='*50}")
    print(f"  交易心理助手 v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    state = load_account_state()

    # 首次使用检测
    if state is None and not os.path.exists(os.path.join(PSYCH_DIR, 'onboarding_complete')):
        print("\\n[PSYCH] First-time user detected! Generating onboarding guide...")
        guide_path = os.path.join(PSYCH_DIR, 'newbie_guide.md')
        os.makedirs(PSYCH_DIR, exist_ok=True)
        with open(guide_path, 'w', encoding='utf-8') as f:
            f.write(ONBOARDING_GUIDE)
        # 标记已完成引导
        with open(os.path.join(PSYCH_DIR, 'onboarding_complete'), 'w', encoding='utf-8') as f:
            f.write(datetime.now().strftime('%Y-%m-%d'))
        print(f"[PSYCH] Newbie guide: {guide_path}")
        print("[PSYCH] Please read the guide before your first trade!")

    # 每日心态检查
    print("\\n[PSYCH] Daily psychology check...")
    diary_path, check_msg = generate_psychology_diary(state)

    # 打印摘要
    preview = check_msg[:200].replace('\\n', ' ')
    print(f"[PSYCH] {preview}...")

    if is_weekend():
        task = get_weekend_task()
        print(f"[PSYCH] Weekend task: {task['title']} ({task['duration']})")

    print(f"\\n[OK] Psychology check complete")
    return 0


if __name__ == '__main__':
    sys.exit(main())
