"""流水线 FATAL 回归：position_sizer 空仓 summary 契约缺失（2026-08-24 round 7）。

历史日志：20260729/30/31、20260803/04 流水线在 position_sizing 步骤
KeyError 'used_amount' 后 FATAL。根因：强熊/无候选日的早退 summary 缺
used_amount / cash_remaining / sector_distribution。
"""
import json
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import position_sizer as ps


def test_strong_bear_empty_summary_has_full_contract():
    orders, summary = ps.calculate_position_sizes(
        pd.DataFrame(), regime='强熊', total_capital=2400)

    assert orders == []
    for key in ('used_amount', 'cash_remaining', 'sector_distribution'):
        assert key in summary, f'missing {key}'
    assert summary['used_amount'] == 0.0
    assert summary['cash_remaining'] == 2400.0
    assert summary['sector_distribution'] == {}


def test_no_picks_summary_has_full_contract():
    orders, summary = ps.calculate_position_sizes(
        pd.DataFrame(), regime='震荡', total_capital=2400)
    assert orders == []
    assert summary['used_amount'] == 0.0
    assert summary['cash_remaining'] == 2400.0


def test_generate_order_file_no_keyerror_on_empty_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, 'ORDERS_DIR', str(tmp_path))
    monkeypatch.setattr(ps, '_load_today_exit_signals', lambda: [])

    orders, summary = ps.calculate_position_sizes(
        pd.DataFrame(), regime='强熊', total_capital=2400)
    path = ps.generate_order_file(
        orders, summary, {'price': 1.0, 'ma20': 1.0, 'ma60': 1.0})

    assert Path(path).exists()
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    assert data['资金分配']['已用资金'] == 0.0
    assert data['资金分配']['剩余现金'] == 2400.0
    assert '强熊市：建议空仓观望' in data['风控提示'][0]
