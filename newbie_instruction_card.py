"""
新手指令卡 v1 — 每天一条可执行指令，零术语

功能：
1. 读取最新订单，生成超简指令卡
2. 输出: "买入XXX，XXX股，止损XX.XX元"
3. 附带总资金分配和一句话风险提示
4. 保存到 orders/daily_instruction_YYYYMMDD.md
"""
import os, sys, json, glob
from datetime import datetime
from core.config import get as cfg_get

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
SIM_DIR = os.path.join(BASE_DIR, 'sim_results')


def _sim_hold_days() -> int:
    try:
        return int(float(cfg_get('sim.max_hold_days', 10)))
    except Exception:
        return 10


def _sim_take_profit_pct() -> float:
    try:
        return float(cfg_get('sim.take_profit_pct', 0.20))
    except Exception:
        return 0.20


def load_latest_orders():
    """加载最新的订单文件"""
    files = sorted(glob.glob(os.path.join(ORDERS_DIR, 'daily_orders_*.json')), reverse=True)
    if not files:
        return None, []
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
    return files[0], data.get('订单', [])


def load_account_state():
    """加载模拟账户状态"""
    state_file = os.path.join(SIM_DIR, 'account_state.json')
    if not os.path.exists(state_file):
        return None
    with open(state_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_instruction_card(orders, protection=None):
    """
    生成小白指令卡

    原则：
    - 每条指令一句话：买什么、买多少、何时止损
    - 零术语、零指标、零评分
    - 一眼能看懂，看完就能操作
    """
    if not orders:
        return None

    today = datetime.now().strftime('%Y-%m-%d')
    state = load_account_state()
    total_capital = state.get('equity', 100000) if state else 100000

    # 保护期标签
    phase_label = ''
    if protection:
        phase = protection.get('current_phase', 'observation')
        day = protection.get('day_number', 1)
        if phase == 'observation':
            phase_label = f'> 🔵 **观察期 第{day}天 — 请勿实盘！以下内容仅供学习参考。**'
        elif phase == 'simulation':
            phase_label = f'> 🟡 **模拟期 第{day}天 — 建议用模拟盘同比例跟踪，记录盈亏对比。**'
        elif phase == 'pre_live':
            rec = protection.get('recommendation', '')
            phase_label = f'> 🟢 **实盘预备期 第{day}天** — {rec}'

    lines = [
        f"# 今日操作指令 — {today}",
        f"",
        f"> 以下指令由量化系统自动生成。看不懂没关系，照着做就行。",
    ]
    if phase_label:
        lines.append(phase_label)
    lines.extend([
        f"",
        f"## 买入清单",
        f"",
    ])

    # 统计
    total_amount = 0
    for i, order in enumerate(orders, 1):
        code = order.get('代码', '')
        name = order.get('名称', '')
        shares = order.get('股数', 0)
        price = order.get('价格', 0)
        amount = order.get('金额', 0)
        stop = order.get('止损价', 0)

        total_amount += amount

        # 日内偏离建议（如果有的话）
        intraday_tip = order.get('日内建议', '')
        if intraday_tip and '等待' in str(intraday_tip):
            timing = '（建议等回调再买）'
        elif intraday_tip and '低吸' in str(intraday_tip):
            timing = '（当前是低吸机会）'
        else:
            timing = ''

        lines.append(f"### {i}. {name}（{code}）{timing}")
        lines.append(f"")
        lines.append(f"- **买入价格**：{price} 元附近")
        lines.append(f"- **买入数量**：{shares} 股")
        lines.append(f"- **花费金额**：约 {amount:,.0f} 元")
        lines.append(f"- **止损价格**：{stop} 元（跌破就卖，别犹豫）")
        lines.append(f"")

    lines.extend([
        f"---",
        f"",
        f"## 资金总览",
        f"",
        f"| 项目 | 金额 |",
        f"|------|------|",
        f"| 账户总资金 | {total_capital:,.0f} 元 |",
        f"| 本次买入合计 | {total_amount:,.0f} 元 |",
        f"| 买入后剩余现金 | {total_capital - total_amount:,.0f} 元 |",
        f"| 买入股票数量 | {len(orders)} 只 |",
        f"",
    ])

    # 操作提示
    lines.extend([
        f"---",
        f"",
        f"## 操作须知",
        f"",
        f"1. **明天开盘后买入**，尽量在上午10:30前完成",
        f"2. **每只股票买同样金额**，不用纠结买多买少",
        f"3. **买入后设置止损单**，止损价见上方每只股票的标注",
        f"4. **持有{_sim_hold_days()}个交易日**，期间不要频繁看盘",
        f"5. **达到止损价立刻卖出**，不要抱有侥幸心理",
        f"6. **涨了{_sim_take_profit_pct()*100:.0f}%以上**可以考虑卖出一半，锁定利润",
        f"",
        f"---",
        f"",
        f"## 一句话风控",
        f"",
    ])

    # 风控提示
    regime = state.get('_regime', '未知') if state else '未知'
    if '强牛' in str(regime):
        lines.append("当前市场偏强，正常操作即可，止损可以稍微放宽一点。")
    elif '弱牛' in str(regime):
        lines.append("市场温和向好，按标准流程操作。")
    elif '震荡' in str(regime):
        lines.append("市场方向不明，严格设好止损，仓位不要太重。")
    elif '熊' in str(regime):
        lines.append("⚠️ 市场偏弱，建议谨慎操作或减少买入数量。")
    else:
        lines.append("严格按照止损纪律执行，保住本金是第一位的。")

    lines.extend([
        f"",
        f"---",
        f"",
        f"> **免责声明**：以上内容由量化模型自动生成，不构成投资建议。",
        f"> 股市有风险，投资需谨慎。请根据自身情况独立判断。",
        f"",
    ])

    return '\n'.join(lines)


def generate_bark_simple_body(orders, instruction_text, banner=''):
    """
    生成极简Bark推送内容——适合手机通知栏直接阅读

    目标：一条通知就能看清今天要买什么
    """
    if not orders:
        return "今日无操作指令", "今日无符合条件的买入机会，继续持有现金观望。"

    today = datetime.now().strftime('%m月%d日')

    # 超短标题：日期 + 买几只 + 保护期简标
    protection_emoji = ''
    if '观察期' in banner:
        protection_emoji = '🔵'
    elif '模拟期' in banner:
        protection_emoji = '🟡'
    elif '预备期' in banner:
        protection_emoji = '🟢'
    title = f"{protection_emoji}{today} 买入{len(orders)}只"

    # 正文极简
    lines = []
    # 保护期第一行提示
    if '观察期' in banner:
        lines.append("🔵 观察期 - 请勿实盘")
    elif '模拟期' in banner:
        lines.append("🟡 模拟期 - 建议同比例模拟")
    lines.append("")

    for i, order in enumerate(orders[:5], 1):
        name = order.get('名称', '')
        shares = order.get('股数', 0)
        stop = order.get('止损价', 0)
        lines.append(f"{i}. {name} {shares}股 止损{stop}")

    lines.append("")
    lines.append(f"共{len(orders)}只 | 按指令卡操作")
    lines.append(f"详情见 orders/daily_instruction_{datetime.now().strftime('%Y%m%d')}.md")

    return title, '\n'.join(lines)


def main():
    print(f"[NEWBIE] Generating daily instruction card...")

    # 加载新手保护期状态
    try:
        from newbie_protection import update_newbie_status, get_phase_banner
        protection = update_newbie_status()
        banner = get_phase_banner()
        print(f"[NEWBIE] Protection phase: {protection['current_phase']}, day {protection['day_number']}")
    except Exception:
        protection = {'current_phase': 'observation', 'day_number': 1}
        banner = '🔵 [观察期 - 请勿实盘]'

    # 加载订单
    order_file, orders = load_latest_orders()
    if not orders:
        print("[NEWBIE] No orders found, skipping")
        return 0

    print(f"[NEWBIE] Loaded {len(orders)} orders from {os.path.basename(order_file)}")

    # 生成指令卡（带保护期标签）
    card = generate_instruction_card(orders, protection)
    if card:
        today_str = datetime.now().strftime('%Y%m%d')
        card_path = os.path.join(ORDERS_DIR, f'daily_instruction_{today_str}.md')
        with open(card_path, 'w', encoding='utf-8') as f:
            f.write(card)
        print(f"[NEWBIE] Instruction card: {card_path}")

        # 生成极简Bark推送内容（含保护期标签）
        title, body = generate_bark_simple_body(orders, card, banner)
        bark_path = os.path.join(ORDERS_DIR, f'bark_simple_{today_str}.txt')
        with open(bark_path, 'w', encoding='utf-8') as f:
            f.write(f"TITLE: {title}\n\n{body}")
        print(f"[NEWBIE] Bark simple content: {bark_path}")
        print(f"[NEWBIE] Title: {title}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
