"""
券商适配器 v1 — 系统订单 → 券商可执行格式

功能：
1. 将内部订单转换为券商API标准格式
2. 支持东方财富、同花顺等常见券商格式
3. 生成可导入的交易指令文件（CSV/JSON）
4. 基础合规检查（单票上限、总仓位、涨跌停限制）
5. 模拟下单预演（dry-run模式）

注意：本模块不执行真实交易，仅做格式转换和合规校验。
      真实交易需要接入券商API并获取用户授权。
"""
import os, sys, json, glob
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
DATA_DIR = os.path.join(BASE_DIR, 'data')
BROKER_DIR = os.path.join(BASE_DIR, 'broker_orders')


# v8.7: 抽到 utils/calendar.py
from utils.calendar import get_last_trading_day  # noqa: E402,F401

# ============================================================
# 合规限制
# ============================================================
# v7.5: 统一配置中心（保留本地默认值作为 fallback）
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get

COMPLIANCE = {
    'max_single_pct': cfg_get('broker.max_single_pct', 0.15),
    'max_total_pct': cfg_get('broker.max_total_pct', 0.80),
    'min_order_amount': cfg_get('broker.min_order_amount', 1000),
    'max_single_amount': cfg_get('broker.max_single_amount', 500000),
    'daily_limit_pct': cfg_get('broker.daily_limit_pct', 0.098),
    'drop_limit_pct': cfg_get('broker.drop_limit_pct', -0.098),
}


def load_latest_orders():
    """加载最新订单"""
    files = sorted(glob.glob(os.path.join(ORDERS_DIR, 'daily_orders_*.json')), reverse=True)
    if not files:
        return None, []
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
    return files[0], data


def load_stock_data():
    """加载最新行情（用于涨跌停检查）"""
    files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not files:
        return {}
    df = pd.read_csv(files[0], dtype={'代码': str})
    df['代码'] = df['代码'].astype(str).str.zfill(6)
    stock_map = {}
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        stock_map[code] = {
            'price': float(row.get('最新价', row.get('收盘', 0))),
            'change_pct': float(row.get('涨跌幅', 0)),
            'name': str(row.get('名称', '')),
        }
    return stock_map


def compliance_check(orders, stock_data, total_capital=100000):
    """
    合规检查，返回 (passed_orders, warnings, errors)

    检查项：
    - 单票金额不超过上限
    - 总仓位不超80%
    - 非涨停股（涨停无法买入）
    - 非跌停股（跌停无法卖出）
    - 最小委托金额
    """
    passed = []
    warnings = []
    errors = []

    total_amount = 0
    for order in orders:
        code = order.get('代码', '').zfill(6)
        amount = order.get('金额', 0)
        price = order.get('价格', 0)
        shares = order.get('股数', 0)
        name = order.get('名称', '')

        # 检查行情数据
        stock = stock_data.get(code, {})
        change_pct = stock.get('change_pct', 0)

        # 涨停检查
        if change_pct and change_pct >= COMPLIANCE['daily_limit_pct'] * 100:
            warnings.append(f"{name}({code})今日涨停({change_pct:+.2f}%)，可能无法买入，已跳过")
            continue

        # 跌停检查
        if change_pct and change_pct <= COMPLIANCE['drop_limit_pct'] * 100:
            warnings.append(f"{name}({code})今日跌停({change_pct:+.2f}%)，风险极高，已跳过")
            continue

        # v8: 跳空硬过滤 — 开盘跳空 > +N% 的票直接跳过避免追高接盘
        # Why: 1200 元小资金最易被高位接盘磨损；放弃 0.x% 潜在收益换 -3%~-5% 套牢风险厌恶
        gap_skip_pct = cfg_get('broker.gap_skip_pct', 3.0)
        if change_pct and change_pct > gap_skip_pct:
            warnings.append(f"{name}({code})今日跳空+{change_pct:.2f}%(>{gap_skip_pct}%)，避免追高已跳过")
            continue

        # 单票金额上限
        if amount > COMPLIANCE['max_single_amount']:
            errors.append(f"{name}({code})金额{amount:,.0f}超过单票上限{COMPLIANCE['max_single_amount']:,.0f}")
            amount = COMPLIANCE['max_single_amount']
            shares = int(amount / price / 100) * 100
            order = {**order, '金额': amount, '股数': shares}

        # 最小委托金额
        if amount < COMPLIANCE['min_order_amount']:
            warnings.append(f"{name}({code})金额{amount:,.0f}低于最小委托{COMPLIANCE['min_order_amount']}，已跳过")
            continue

        # 单票仓位上限
        position_pct = amount / total_capital
        if position_pct > COMPLIANCE['max_single_pct']:
            capped_amount = total_capital * COMPLIANCE['max_single_pct']
            capped_shares = int(capped_amount / price / 100) * 100
            capped_amount = capped_shares * price
            warnings.append(f"{name}({code})仓位{position_pct:.1%}超限，已从{shares}股降至{capped_shares}股")
            order = {**order, '金额': round(capped_amount, 2), '股数': capped_shares}

        total_amount += order.get('金额', 0)
        passed.append(order)

    # 总仓位检查
    total_pct = total_amount / total_capital
    if total_pct > COMPLIANCE['max_total_pct']:
        warnings.append(f"总仓位{total_pct:.1%}超过{COMPLIANCE['max_total_pct']:.0%}上限，建议减少买入数量")

    return passed, warnings, errors


def _classify_exchange(code):
    """v8.6: 按代码前缀归类交易所 — 沪/深/北。

    SH: 主板 60xxxx, 科创 68xxxx
    SZ: 主板 00xxxx, 创业 30xxxx, 创业新规 301xxx
    BJ: 北交所 43xxxx/83xxxx/87xxxx/88xxxx/92xxxx
    其余：fallback SZ（极少见）
    """
    code = str(code).zfill(6)
    if code.startswith(('60', '68')):
        return 'SH'
    if code.startswith(('00', '30')):
        return 'SZ'
    if code.startswith(('43', '83', '87', '88', '92')):
        return 'BJ'
    return 'SZ'


def to_eastmoney_format(orders):
    """
    转换为东方财富API委托格式

    东方财富标准委托字段：
    code, name, price, amount, volume(股), direction(1买/2卖),
    price_type(0限价/1市价), exchange(sh/sz/bj)
    """
    rows = []
    for order in orders:
        code = order.get('代码', '').zfill(6)
        exchange = _classify_exchange(code)
        rows.append({
            '证券代码': code,
            '证券名称': order.get('名称', ''),
            '委托方向': '买入',
            '委托价格': order.get('价格', 0),
            '委托数量': order.get('股数', 0),
            '委托金额': order.get('金额', 0),
            '价格类型': '限价委托',
            '交易市场': exchange,
            '止损价': order.get('止损价', 0),
            '止损方式': order.get('止损方式', '固定-5%'),
            '板块': order.get('板块', ''),
        })
    return rows


def to_flush_format(orders):
    """转换为同花顺可导入的CSV格式"""
    rows = []
    for i, order in enumerate(orders, 1):
        code = order.get('代码', '').zfill(6)
        rows.append({
            '序号': i,
            '代码': code,
            '名称': order.get('名称', ''),
            '买卖标志': 1,  # 1=买入
            '委托价格': order.get('价格', 0),
            '委托数量': order.get('股数', 0),
            '委托金额': order.get('金额', 0),
            '止损价格': order.get('止损价', 0),
        })
    return rows


def to_generic_csv(orders):
    """通用CSV — 可导入任何交易软件"""
    rows = []
    for order in orders:
        code = order.get('代码', '').zfill(6)
        rows.append({
            'code': code,
            'name': order.get('名称', ''),
            'side': 'BUY',
            'price': order.get('价格', 0),
            'qty': order.get('股数', 0),
            'amount': order.get('金额', 0),
            'stop_loss': order.get('止损价', 0),
            'sector': order.get('板块', ''),
        })
    return rows


def save_broker_orders(orders, order_data):
    """保存各种格式的券商订单"""
    os.makedirs(BROKER_DIR, exist_ok=True)
    today_str = get_last_trading_day(fmt='%Y%m%d')
    date_str = get_last_trading_day(fmt='%Y-%m-%d')

    saved_files = []

    # 1. 东方财富格式 (JSON)
    em_orders = to_eastmoney_format(orders)
    em_path = os.path.join(BROKER_DIR, f'eastmoney_{today_str}.json')
    em_data = {
        '生成时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '市场状态': order_data.get('市场状态', {}),
        '资金分配': order_data.get('资金分配', {}),
        '订单': em_orders,
        '风控提示': order_data.get('风控提示', []),
    }
    with open(em_path, 'w', encoding='utf-8') as f:
        json.dump(em_data, f, ensure_ascii=False, indent=2)
    saved_files.append(em_path)

    # 2. 同花顺导入格式 (CSV)
    flush_orders = to_flush_format(orders)
    flush_path = os.path.join(BROKER_DIR, f'flush_{today_str}.csv')
    pd.DataFrame(flush_orders).to_csv(flush_path, index=False, encoding='utf-8-sig')
    saved_files.append(flush_path)

    # 3. 通用格式 (CSV)
    gen_orders = to_generic_csv(orders)
    gen_path = os.path.join(BROKER_DIR, f'generic_{today_str}.csv')
    pd.DataFrame(gen_orders).to_csv(gen_path, index=False, encoding='utf-8-sig')
    saved_files.append(gen_path)

    # 4. 可读摘要 (MD)
    md_path = os.path.join(BROKER_DIR, f'broker_summary_{today_str}.md')
    lines = [
        f"# 券商委托指令 — {date_str}",
        f"",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 此文件仅供手动导入参考，不执行自动下单",
        f"",
        f"## 订单列表",
        f"",
        f"| # | 代码 | 名称 | 方向 | 价格 | 股数 | 金额 | 止损 |",
        f"|----|------|------|------|------|------|------|------|",
    ]
    for i, o in enumerate(orders, 1):
        lines.append(f"| {i} | {o.get('代码','')} | {o.get('名称','')} | 买入 | "
                     f"{o.get('价格',0)} | {o.get('股数',0)} | {o.get('金额',0):,.0f} | {o.get('止损价',0)} |")
    lines.extend([
        f"",
        f"## 导入说明",
        f"",
        f"- **东方财富**：复制 `eastmoney_{today_str}.json` 内容到交易终端",
        f"- **同花顺**：导入 `flush_{today_str}.csv` 到条件单/批量委托",
        f"- **通用**：`generic_{today_str}.csv` 可导入大部分交易软件",
        f"",
        f"---",
        f"*操作前请仔细核对，确认无误后再下单*",
    ])
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    saved_files.append(md_path)

    return saved_files


def main():
    # v8 tier gate：只在 AUTO 级运行；其他 tier 早退保留代码
    from core.config import ENABLE_BROKER_ADAPTER, SYSTEM_TIER
    if not ENABLE_BROKER_ADAPTER:
        print(f"[BROKER] Dormant on tier={SYSTEM_TIER.value}; activates at Auto (50万+ API). "
              f"Code preserved, no orders generated.")
        return 0

    print(f"{'='*50}")
    print(f"  券商适配器 v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 1. 加载订单
    order_file, order_data = load_latest_orders()
    if not order_file:
        print("[BROKER] No order file found")
        return 1

    orders = order_data.get('订单', [])
    capital = order_data.get('资金分配', {}).get('总资金', 100000)
    print(f"[1/4] Loaded {len(orders)} orders | Capital: {capital:,.0f}")

    # 2. 加载行情做合规检查
    stock_data = load_stock_data()
    print(f"[2/4] Loaded {len(stock_data)} stocks for compliance check")

    passed, warnings, errors = compliance_check(orders, stock_data, capital)

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e}")

    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    {w}")
    else:
        print(f"  All checks passed")

    print(f"\n[3/4] After compliance: {len(passed)}/{len(orders)} orders")

    # 3. 生成券商格式文件
    print(f"\n[4/4] Generating broker order files...")
    if passed:
        files = save_broker_orders(passed, order_data)
        for f in files:
            print(f"  {f}")
    else:
        print("  No orders to save (all filtered out)")

    print(f"\n[OK] Broker adapter complete")
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())