"""真实交易成本模型 — 单一真相源 (single source of truth)

回测 / 模拟交易 / walk-forward 都从这里读成本逻辑。禁止在三个文件里再各自写
`max(amount * 0.00025, 5.0)` 之类的硬编码。

口径（A 股小资金）：
    佣金率   = cost.commission_rate    默认 0.0003 (万 3，保守口径)
    最低佣金 = cost.commission_min     默认 5 元 (券商常见 floor)
    印花税   = cost.stamp_tax_rate     默认 0.0005 (卖出单边)
    滑点档   = cost.slippage_*_cap     默认 0.001 / 0.002 / 0.003
    单笔交易 = cost.per_trade_notional 默认 400 元 (静态 fallback)
    动态额度 = cost.notional_dynamic   默认 True (按 regime + 持仓数动态算)

为什么 1200 元单笔成本会到 8%~10%：
    单笔 200 元 × (佣金 5 元 floor × 2 + 印花税 0.1 元 + 滑点 0.6 元) / 200 ≈ 5.4%
    单笔 100 元 × (5×2 + 0.05 + 0.3) / 100 ≈ 10.4%
    单笔 400 元 × (5×2 + 0.2 + 1.2) / 400 ≈ 2.85%
    所以"单笔越小，5 元 floor 占比越夸张"。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get


# 成本常量直接从 system_config.json 读，方便外部 import 比较
COMMISSION_RATE = cfg_get('cost.commission_rate', 0.0003)
COMMISSION_MIN = cfg_get('cost.commission_min', 5.0)
STAMP_TAX_RATE = cfg_get('cost.stamp_tax_rate', 0.0005)
SLIP_LARGE = cfg_get('cost.slippage_large_cap', 0.001)
SLIP_MID = cfg_get('cost.slippage_mid_cap', 0.002)
SLIP_SMALL = cfg_get('cost.slippage_small_cap', 0.003)
PER_TRADE_NOTIONAL = cfg_get('cost.per_trade_notional', 400.0)
NOTIONAL_DYNAMIC = cfg_get('cost.notional_dynamic', True)
DEFAULT_CAPITAL = cfg_get('position.default_capital', 2400)

# 市值分档阈值（单位：元）
MCAP_LARGE_THRESHOLD = 5e10   # 500 亿以上 = 大盘
MCAP_MID_THRESHOLD = 5e9      # 50 亿以上 = 中盘
# 不足 50 亿 = 小盘

REGIME_ALLOC = {
    '强牛': 0.80, '弱牛': 0.60, '震荡': 0.40,
    '弱熊': 0.20, '强熊': 0.0,
}


@dataclass(frozen=True)
class CostBreakdown:
    """单笔交易（双边）成本拆解，单位：元 / 占比 0~1。"""
    notional: float           # 单笔交易额（元）
    commission: float         # 双边佣金（元）
    stamp_tax: float          # 印花税（元）
    slippage: float           # 双边滑点（元）
    total: float              # 总成本（元）
    rate: float               # 占交易额的比例（0~1）

    @property
    def pct(self) -> float:
        """以百分比表示（0~100）。"""
        return self.rate * 100


def slippage_rate_by_mcap(mcap: float) -> float:
    """按市值分档返回单边滑点率（0~1）。

    mcap 单位：元（与 enhanced_backtest 现有数据一致）。
    """
    if mcap is None:
        mcap = 0
    try:
        m = float(mcap)
    except (TypeError, ValueError):
        m = 0.0
    if m >= MCAP_LARGE_THRESHOLD:
        return SLIP_LARGE
    if m >= MCAP_MID_THRESHOLD:
        return SLIP_MID
    return SLIP_SMALL


def order_cost_amount(side: str, amount: float, mcap: float = 0) -> float:
    """单边订单成本（元）。

    side: 'buy' 或 'sell'。'sell' 时加印花税。
    amount: 成交金额（元，正数）。
    mcap: 流通市值（元），决定滑点档。
    """
    if amount is None or amount <= 0:
        return 0.0
    side_lower = (side or '').lower()
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp_tax = amount * STAMP_TAX_RATE if side_lower == 'sell' else 0.0
    slippage = amount * slippage_rate_by_mcap(mcap)
    return commission + stamp_tax + slippage


def round_trip_cost(mcap: float, notional: float | None = None,
                    with_slippage: bool = True) -> CostBreakdown:
    """一买一卖的双边总成本拆解。

    with_slippage=False: 跳过滑点份额（用于已通过 entry/exit 价格调整滑点的回测引擎，
    避免双扣）。commission + stamp_tax 仍计算。
    """
    if notional is None or notional <= 0:
        notional = PER_TRADE_NOTIONAL
    n = float(notional)
    commission = max(n * COMMISSION_RATE, COMMISSION_MIN) * 2          # 双边
    stamp_tax = n * STAMP_TAX_RATE                                      # 卖出单边
    slippage = n * slippage_rate_by_mcap(mcap) * 2 if with_slippage else 0.0  # 双边
    total = commission + stamp_tax + slippage
    rate = total / n if n > 0 else 0.0
    return CostBreakdown(
        notional=n, commission=commission, stamp_tax=stamp_tax,
        slippage=slippage, total=total, rate=rate,
    )


def order_passes_cost_gate(amount, mcap=0, max_pct=None):
    """每笔订单成本门槛：往返成本率 <= max_pct 才允许买入。

    Args:
        amount: 订单成交金额（元，正数）。
        mcap: 流通市值（元），决定滑点档；缺省 0 = 按小盘最保守。
        max_pct: 门槛（0~1 比例，如 0.025=2.5%）。None 时由调用方传配置值；
                 本函数保持纯计算，不读配置/不写盘。

    Returns:
        (passed: bool, CostBreakdown)。amount <= 0 恒不过。
    """
    if amount is None or float(amount) <= 0:
        return False, CostBreakdown(
            notional=0.0, commission=0.0, stamp_tax=0.0,
            slippage=0.0, total=0.0, rate=0.0,
        )
    limit = 0.025 if max_pct is None else float(max_pct)
    cb = round_trip_cost(mcap, amount, with_slippage=True)
    return cb.rate <= limit, cb


def get_cost_by_mcap(mcap: float, notional: float | None = None,
                     with_slippage: bool = True) -> float:
    """向下兼容：返回双边总成本率（0~1，不是 %）。

    保留这个函数签名是因为 enhanced_backtest.py 一直在用它。
    with_slippage=False: 跳过滑点份额（避免与 entry/exit 价格调整双扣）。
    """
    return round_trip_cost(mcap, notional, with_slippage=with_slippage).rate


def compute_dynamic_notional(regime: str, picks_count: int) -> float:
    """按市场 regime 仓位 + 实际持仓数动态算单笔交易额。

    Why: 静态 PER_TRADE_NOTIONAL 与小资金集中持仓不匹配；
    震荡市 alloc=40% × 1200 / 3 只 = 160 元，强牛 alloc=80% × 1200 / 3 只 = 320 元。
    动态值让 cost_rate 随 regime 起伏，更贴近实盘成本。
    """
    if not NOTIONAL_DYNAMIC:
        return PER_TRADE_NOTIONAL
    alloc = REGIME_ALLOC.get(regime, 0.40)
    if alloc == 0 or picks_count <= 0:
        return PER_TRADE_NOTIONAL
    return max(100.0, DEFAULT_CAPITAL * alloc / max(1, picks_count))


def realized_cost_summary(trades_df) -> dict:
    """从回测 trades DataFrame 算真实成本（用于报告头）。

    Args:
        trades_df: pandas.DataFrame，至少要有 '成本率' 列（百分比，0~100）
            或 '毛收益' / '净收益' 两列。

    Returns:
        dict 包含 mean_pct / min_pct / max_pct / n_trades / available。
        如果 trades 为空或缺列，available=False。
    """
    empty = {'available': False, 'mean_pct': None, 'min_pct': None,
             'max_pct': None, 'n_trades': 0}
    if trades_df is None or len(trades_df) == 0:
        return empty
    df = trades_df
    if '成本率' in df.columns:
        s = df['成本率']
    elif '毛收益' in df.columns and '净收益' in df.columns:
        s = df['毛收益'] - df['净收益']
    elif 'cost_rate' in df.columns:
        s = df['cost_rate'] * 100  # 假设是 0~1，转 %
    else:
        return empty
    s = s.dropna() if hasattr(s, 'dropna') else s
    if len(s) == 0:
        return empty
    return {
        'available': True,
        'mean_pct': float(s.mean()),
        'min_pct': float(s.min()),
        'max_pct': float(s.max()),
        'n_trades': int(len(s)),
    }


def format_cost_header(summary: dict) -> str:
    """生成报告头里的成本描述（≤80 字）。

    样例：
        '真实成本 7.84%（最低 2.81%~最高 12.40%，123 笔）'
        '真实成本 N/A（本期无交易）'
    """
    if not summary or not summary.get('available'):
        return '真实成本 N/A（本期无交易）'
    return (
        f"真实成本 {summary['mean_pct']:.2f}%"
        f"（最低 {summary['min_pct']:.2f}%~最高 {summary['max_pct']:.2f}%，"
        f"{summary['n_trades']} 笔）"
    )


def format_cost_examples(notional: float | None = None) -> str:
    """生成报告附录里的三档示例（用于"为什么 1200 元成本这么高"说明）。"""
    if notional is None or notional <= 0:
        notional = PER_TRADE_NOTIONAL
    large = round_trip_cost(6e10, notional).pct
    mid = round_trip_cost(1e10, notional).pct
    small = round_trip_cost(3e9, notional).pct
    return (
        f"按单笔 {notional:.0f} 元估算：大盘股 {large:.2f}%，"
        f"中盘股 {mid:.2f}%，小盘股 {small:.2f}%"
    )


if __name__ == '__main__':
    # 烟雾测试：打印不同资金/市值/单笔的成本
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print('=== cost_model 自检 ===')
    for notional in [100, 200, 400, 800, 1200]:
        for mcap_label, mcap in [('大盘 600 亿', 6e10), ('中盘 100 亿', 1e10), ('小盘 30 亿', 3e9)]:
            cb = round_trip_cost(mcap, notional)
            print(f'  单笔 {notional:>4} 元 {mcap_label:<14} → {cb.pct:.2f}% '
                  f'(佣 {cb.commission:.2f} + 税 {cb.stamp_tax:.2f} + 滑 {cb.slippage:.2f})')
    print()
    print('  动态 notional:')
    for regime in ['强牛', '弱牛', '震荡', '弱熊', '强熊']:
        for n_pick in [1, 3, 5, 10]:
            n = compute_dynamic_notional(regime, n_pick)
            print(f'    {regime} × {n_pick} 只 = {n:.0f} 元 → '
                  f'{round_trip_cost(1e10, n).pct:.2f}% (中盘股)')
