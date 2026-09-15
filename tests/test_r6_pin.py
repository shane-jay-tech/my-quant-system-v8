# -*- coding: utf-8 -*-
"""R6 静态钉桩（d913b-45）：沪 B 900xxx 被 startswith('8'/'9') 误伤的现行为钉桩。

来源：docs/insights/quant-coverage-plan-closure-audit-20260905.md:30 R6 条目——
「构造 900xxx 样本断言下限/阈值即可，无需跑交易」；纯静态断言，不做交易、不改生产码。
钉桩目的=修复（改前缀判定逻辑）时提供回归网，两处断言值即当前误伤形态。
"""
import pytest

from sim_trade import get_limit_pct
from position_sizer import _stop_loss_floor

ENTRY = 10.0


def test_900x_hit_by_prefix_9_limit_pct():
    """沪 B 900xxx 命中 startswith('9') → 涨停阈值被当北交所 29.8%（误伤现行为钉桩）。"""
    assert get_limit_pct('900901') == 29.8


def test_900x_hit_by_prefix_9_stop_floor():
    """沪 B 900xxx 止损下限被当北交所 -30%（entry*0.70）（误伤现行为钉桩）。"""
    assert _stop_loss_floor('900901', ENTRY) == pytest.approx(7.0)


def test_control_groups_unchanged():
    """对照组：主板/科创创业阈值与下限保持各自口径（防修复时误改）。"""
    assert get_limit_pct('600000') == 9.8
    assert get_limit_pct('688001') == 19.8
    assert get_limit_pct('300001') == 19.8
    assert _stop_loss_floor('600000', ENTRY) == pytest.approx(9.0)
    assert _stop_loss_floor('688001', ENTRY) == pytest.approx(8.0)

