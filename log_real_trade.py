"""
真实交易录入 v1 — 交互式/命令行录入真实交易，写入 real_trades.csv

用法：
  交互式：python log_real_trade.py
  命令行：python log_real_trade.py --code 000001 --name 平安银行 --direction 买入 --price 11.05 --qty 100 --reason "系统推荐"
"""
import os, sys, csv, argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, 'real_trades.csv')

sys.path.insert(0, BASE_DIR)
# Round-3 修复（2026-05-30）：之前 log_real_trade 用本地常量 COMMISSION=0.00025 / STAMP=0.0005，
# 没有套用 cost_model 的 5 元最低佣金（COMMISSION_MIN）。1200 元小资金本金下：
#   - 真实代付：买入佣金强制 5 元（不足 5 元按 5 元收）
#   - 旧版 log 出来：1200 × 0.00025 = 0.3 元
# → real_trades.csv 里的 '手续费' 系统性低估 ~95%，strategy_feedback 用它算净 PnL 全部失真
# → 反馈闭环把"实际亏损的交易"当成"小幅盈利"，自动调参方向反向。
# 修复：直接走 cost_model 单一真相源（COMMISSION_RATE=0.0003 + COMMISSION_MIN=5 + STAMP_TAX_RATE=0.0005）
from cost_model import COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE


def calc_fee(direction, price, qty, amount):
    """计算预估手续费（含 5 元最低佣金）。

    买入：max(amount × COMMISSION_RATE, COMMISSION_MIN)
    卖出：max(amount × COMMISSION_RATE, COMMISSION_MIN) + amount × STAMP_TAX_RATE
    """
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp = amount * STAMP_TAX_RATE if direction == '卖出' else 0
    return round(commission + stamp, 2)


def append_trade(date_str, code, name, direction, price, qty, reason='', note=''):
    """追加一条交易记录到 real_trades.csv"""
    amount = round(price * qty, 2)
    fee = calc_fee(direction, price, qty, amount)

    # 确保CSV文件存在
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['日期', '代码', '名称', '方向', '价格', '数量', '成交额', '手续费', '下单依据', '备注'])

    with open(TRADES_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow([date_str, code, name, direction, price, qty, amount, fee, reason, note])

    confirm = (
        f"已记录：{date_str} {direction} {code} {name} {qty}股 @{price}，"
        f"成交额 {amount:,.2f}，预估手续费 {fee:.2f}"
    )
    print(confirm)
    return confirm


def interactive_mode():
    """交互式录入"""
    print("=" * 50)
    print("  真实交易录入")
    print("  按 Ctrl+C 退出")
    print("=" * 50)

    try:
        while True:
            print()
            code = input("  代码 (6位): ").strip().zfill(6)
            if not code or len(code) != 6:
                print("  [ERROR] 请输入6位股票代码")
                continue

            name = input("  名称: ").strip()
            if not name:
                print("  [ERROR] 名称不能为空")
                continue

            direction = input("  方向 (买入/卖出): ").strip()
            if direction not in ('买入', '卖出'):
                print("  [ERROR] 方向必须是'买入'或'卖出'")
                continue

            try:
                price = float(input("  价格: ").strip())
                qty = int(input("  数量(股): ").strip())
            except ValueError:
                print("  [ERROR] 价格或数量格式错误")
                continue

            reason = input("  下单依据 (如: 系统推荐/手动操作): ").strip()
            note = input("  备注 (可选 — 什么原因让你做出这个交易决定？如: 跟单系统/看见爆拉怕回调/急需用钱): ").strip()

            date_str = input(f"  日期 [默认今天 {datetime.now().strftime('%Y-%m-%d')}]: ").strip()
            if not date_str:
                date_str = datetime.now().strftime('%Y-%m-%d')

            append_trade(date_str, code, name, direction, price, qty, reason, note)

            another = input("\n  继续录入？(y/n): ").strip().lower()
            if another != 'y':
                break

    except KeyboardInterrupt:
        print("\n\n  已退出。")
    except EOFError:
        pass


def main():
    parser = argparse.ArgumentParser(description='真实交易录入')
    parser.add_argument('--code', type=str, help='股票代码')
    parser.add_argument('--name', type=str, help='股票名称')
    parser.add_argument('--direction', type=str, help='买入/卖出')
    parser.add_argument('--price', type=float, help='成交价格')
    parser.add_argument('--qty', type=int, help='成交数量')
    parser.add_argument('--reason', type=str, default='', help='下单依据')
    parser.add_argument('--note', type=str, default='', help='备注')
    parser.add_argument('--date', type=str, default='', help='日期 YYYY-MM-DD')
    args = parser.parse_args()

    # 命令行模式：所有参数齐全则直接写入
    if args.code and args.direction and args.price and args.qty:
        date_str = args.date or datetime.now().strftime('%Y-%m-%d')
        append_trade(date_str, args.code.zfill(6), args.name or '', args.direction,
                    args.price, args.qty, args.reason, args.note)
        return 0

    # 交互模式
    interactive_mode()
    return 0


if __name__ == '__main__':
    sys.exit(main())
