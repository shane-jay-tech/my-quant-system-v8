# -*- coding: utf-8 -*-
"""特征测试（characterization）：量化红线 R1/R7/R8 的当前行为。

红线定义见 docs/optimization/2026-09-04/01-my-quant-system-v8-优化方案.md 第 6 节：
  R1 sim_trade.py:384 订单「止损价」字段存在但值为 0/None 时被原样写入
  R7 broker_adapter.py:124/136 int(amount/price/100) 对 price=0 直接除零
  R8 sim_trade.py:717 最大回撤 = (max-min)/max，不保证 min 发生在 max 之后（高估）

CHARACTERIZATION：断言固化"现状"，不是"正确值"。日间修复红线后应人工更新
期望值，以本文件 diff 作为行为变化清单。全部使用合成数据与内存 dict，
严禁触碰真实 data/ 与 sim_results/（tests/conftest.py 护栏继续生效）。
"""
import pandas as pd
import pytest

import sim_trade
from sim_trade import execute_buy_orders
from broker_adapter import compliance_check


def _state_with_position():
    return {
        'cash': 100000.0, 'total_invested': 0.0, 'total_commission': 0.0,
        'total_trade_volume': 0.0,
        'positions': [{'code': '600000', 'name': '浦发银行', 'entry_price': 10.0,
                       'shares': 1000, 'stop_loss': 9.0, 'take_profit': 12.0,
                       'current_price': 10.0, 'unrealized_pnl': 0.0,
                       'unrealized_pnl_pct': 0.0}],
    }


class TestR1StopLossZero:
    """R1：订单显式携带 止损价=0 时，现状把它原样写入仓位（而非回退默认止损）。"""

    def test_zero_stop_loss_written_verbatim(self):
        state = _state_with_position()
        orders = [{'代码': '600000', '名称': '浦发银行', '股数': 1000, '止损价': 0}]
        prices = {'600000': {'price': 10.0, 'name': '浦发银行', 'change_pct': 1.0}}

        execute_buy_orders(state, orders, prices)

        # 现状：stop_loss 从 9.0 被覆盖为 0（正确的守护逻辑应回退默认止损并告警）
        assert state['positions'][0]['stop_loss'] == 0

    def test_missing_stop_loss_falls_back_to_default(self):
        """对照场景：不携带止损价字段时回退默认百分比——钉住两条路径的差异。"""
        state = _state_with_position()
        orders = [{'代码': '600000', '名称': '浦发银行', '股数': 1000}]
        prices = {'600000': {'price': 10.0, 'name': '浦发银行', 'change_pct': 1.0}}

        execute_buy_orders(state, orders, prices)

        sl = state['positions'][0]['stop_loss']
        # 回退路径写入非零止损（成交价含滑点，精确值 = round(price*(1+STOP_LOSS_PCT),2)），
        # 与"显式 0 被原样写入"形成对照，证明两条路径行为不同
        assert sl != 0
        assert sl < 10.0  # 信号价 10.0 的默认止损低于现价


class TestR7ZeroPriceDivision:
    """R7：compliance_check 对 price=0 的订单现状直接 ZeroDivisionError。"""

    def test_zero_price_raises_zero_division(self):
        orders = [{'代码': '000001', '名称': '平安银行', '金额': 5000,
                   '价格': 0, '股数': 0}]
        stock_data = {'000001': {'name': '平安银行', 'price': 10.0}}

        # 现状：单条坏数据炸掉整批合规检查（期望修复后跳过+告警）
        with pytest.raises(ZeroDivisionError):
            compliance_check(orders, stock_data, 100000)


class TestR8DrawdownFormula:
    """R8：回撤 = (max-min)/max，未约束 min 在 max 之后。

    generate_sim_report() 直接读真实文件无法注入，故此处按
    sim_trade.py:717 的公式逐字复刻并钉住其数学行为；
    公式改动时本用例应同步更新并回到源码核对。
    """

    @staticmethod
    def _current_formula(equity: pd.DataFrame) -> float:
        # 与 sim_trade.py:717 相同的表达式（逐字复刻）
        return ((equity['总权益'].max() - equity['总权益'].min())
                / equity['总权益'].max() * 100)

    def test_dip_before_rise_overestimates_drawdown(self):
        # 先跌（0.9）后涨（1.2）：真实最大回撤应从峰值 1.2 起算=0，
        # 现状公式给出 (1.2-0.9)/1.2=25%，显著高估。
        equity = pd.DataFrame({'总权益': [1.0, 0.9, 1.0, 1.1, 1.2]})
        assert self._current_formula(equity) == pytest.approx(25.0, abs=1e-9)

    def test_monotonic_rise_still_reports_drawdown(self):
        # 对照暴露公式错误之深：纯单调上涨序列也报 16.67% "回撤"
        # （min=首值 < max=末值，(max-min)/max 恒为正）。修复后应返回 0。
        equity = pd.DataFrame({'总权益': [1.0, 1.1, 1.2]})
        assert self._current_formula(equity) == pytest.approx(16.666666666666664, abs=1e-9)
