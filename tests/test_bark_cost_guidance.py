"""Bark 推送成本/风控口径回归测试（2026-08-24 round 2）。

锁定的行为：
1. 摩擦成本附录读取真实字段「金额」，并按每笔订单分别套 5 元最低佣金；
2. 佣金/印花税来自 cost_model 单一真相源（0.0003 / 5 / 0.0005）；
3. simple 推送与明日操作参考的止损/止盈/持有天数/仓位文案跟随 core.config
   和 2400 元小资金模式，不再出现旧写死参数。
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from bark_sender import builders, formatters
from cost_model import COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE
import newbie_instruction_card as nic


def _write_order_file(dir_path: Path, filename: str, orders, regime='震荡'):
    data = {
        '市场状态': {'档位': regime},
        '订单': orders,
        '今日卖出': [],
    }
    (dir_path / filename).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def _fake_stocks(n=3):
    return [
        {'name': f'股{i}', 'code': f'00000{i}', 'price': '10.0',
         'change': '+1.5%', 'score': 95 + i}
        for i in range(1, n + 1)
    ]


def _config_stub(*, capital=2400.0, stop=-0.08, take=0.20, hold=10):
    def fake(key, default=None):
        mapping = {
            'sim.initial_capital': capital,
            'sim.stop_loss_pct': stop,
            'sim.take_profit_pct': take,
            'sim.max_hold_days': hold,
        }
        return mapping.get(key, default)
    return fake


# ---------- 摩擦成本附录 ----------

def test_friction_addendum_reads_amount_field_and_applies_floor_per_order(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, 'ORDERS_DIR', str(tmp_path))
    _write_order_file(tmp_path, 'daily_orders_20260821.json', [
        {'代码': '000001', '金额': 800},
        {'代码': '000002', '金额': 800},
        {'代码': '000003', '金额': 800},
    ])

    out = builders._build_friction_cost_addendum()

    # 每笔佣金 = max(800*0.0003, 5) = 5；往返 = 5*2 + 800*0.0005 = 10.4；3 笔 = 31.2
    assert out != ""
    assert '买入总额：¥2,400' in out
    assert '3 笔订单' in out
    assert '¥31.20' in out
    assert f'{COMMISSION_RATE:.2%}' in out
    assert f'¥{COMMISSION_MIN:.0f}' in out


def test_friction_addendum_empty_without_order_file(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, 'ORDERS_DIR', str(tmp_path))
    assert builders._build_friction_cost_addendum() == ""


def test_friction_addendum_silent_on_bad_json(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, 'ORDERS_DIR', str(tmp_path))
    (tmp_path / 'daily_orders_20260821.json').write_text('{broken', encoding='utf-8')
    assert builders._build_friction_cost_addendum() == ""


def test_friction_addendum_empty_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(builders, 'ORDERS_DIR', str(tmp_path))
    _write_order_file(tmp_path, 'daily_orders_20260821.json', [])
    assert builders._build_friction_cost_addendum() == ""


# ---------- simple 推送尾部风控文案 ----------

def test_simple_message_tail_uses_real_config(monkeypatch):
    monkeypatch.setattr(builders, 'cfg_get', _config_stub())
    _, body = builders.build_bark_message_simple(
        '2026-08-21', _fake_stocks(1))
    assert '止损-8% | 止盈+20% | 持10天' in body
    assert '止盈+15%' not in body
    assert '持5-10天' not in body


def test_simple_message_tail_falls_back_safely(monkeypatch):
    monkeypatch.setattr(builders, 'cfg_get', lambda key, default=None: None)
    _, body = builders.build_bark_message_simple(
        '2026-08-21', _fake_stocks(1))
    assert '止盈+20% | 持10天' in body


# ---------- 明日操作参考风控文案 ----------

def test_tomorrow_guide_small_capital_uses_real_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(formatters, 'ORDERS_DIR', str(tmp_path))
    monkeypatch.setattr(formatters, 'cfg_get', _config_stub())
    _write_order_file(tmp_path, 'daily_orders_20260821.json', [
        {'代码': '000001', '金额': 800},
    ], regime='震荡')

    out = formatters.build_tomorrow_guide(_fake_stocks(3), {})

    assert '小资金模式' in out
    assert '单票上限约 1/3' in out
    assert '-8% 硬止损' in out
    assert '+20%' in out
    assert '最长 10 个交易日' in out
    # 旧写死文案必须消失
    assert '8%-12%' not in out
    assert '牛市6-8成' not in out
    assert '-5%硬止损' not in out
    assert '+10%卖1/3' not in out
    # 候选池规模不再写死 478
    assert '478只' not in out
    assert '当前候选池规模（3只）' in out


def test_tomorrow_guide_strong_bear_says_empty_position(tmp_path, monkeypatch):
    monkeypatch.setattr(formatters, 'ORDERS_DIR', str(tmp_path))
    monkeypatch.setattr(formatters, 'cfg_get', _config_stub())
    _write_order_file(tmp_path, 'daily_orders_20260821.json', [], regime='强熊')

    out = formatters.build_tomorrow_guide([], {})

    assert '强熊市空仓观望' in out
    assert '小资金模式' not in out


def test_tomorrow_guide_empty_stocks_no_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(formatters, 'ORDERS_DIR', str(tmp_path))
    monkeypatch.setattr(formatters, 'cfg_get', _config_stub())
    _write_order_file(tmp_path, 'daily_orders_20260821.json', [], regime='震荡')

    out = formatters.build_tomorrow_guide([], {})

    assert '【仓位与风控】' in out
    assert 'Top10均涨幅' in out


def test_tomorrow_guide_large_capital_uses_tier_alloc(monkeypatch, tmp_path):
    monkeypatch.setattr(formatters, 'ORDERS_DIR', str(tmp_path))
    monkeypatch.setattr(formatters, 'cfg_get',
                        _config_stub(capital=100000.0))
    _write_order_file(tmp_path, 'daily_orders_20260821.json', [], regime='震荡')

    out = formatters.build_tomorrow_guide(_fake_stocks(1), {})

    assert '强牛80% / 弱牛60% / 震荡40% / 弱熊20% / 强熊0%' in out
    assert '8%-12%' not in out  # 旧大资金文案也不再出现，统一按分档表


# ---------- 新手指令卡 ----------

def test_newbie_card_uses_real_hold_and_take_profit(monkeypatch):
    monkeypatch.setattr(nic, 'load_account_state',
                        lambda: {'equity': 2400.0})
    monkeypatch.setattr(nic, 'cfg_get', _config_stub())

    out = nic.generate_instruction_card([
        {'代码': '000001', '名称': '测试股', '股数': 100,
         '价格': 8.0, '金额': 800.0, '止损价': 7.36},
    ], protection=None)

    assert out is not None
    assert '持有10个交易日' in out
    assert '涨了20%以上' in out
    assert '持有5-10个交易日' not in out
    assert '涨了15%以上' not in out

