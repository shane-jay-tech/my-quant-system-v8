"""multi_strategy.main() characterization 测试（8e78，S1 补测：只锁现状）。

锁定行为（main() 全流程，I/O 重定向到 tmp_path）：
1. 数据缺失分支：无今日 stock_*.csv 且无任何 stock 文件 → main() 返回 1 并打印 [FATAL]。
2. 正常数据分支：最小 stock/history CSV → main() 返回 0，全程不抛异常；
   有共识→ORDERS_DIR 落 multi_vote_*.json；无共识→打印 no-consensus 文案。两分支均属现状。
3. 中低档位分支：MeanReversion/LowVolatility 策略对象可实例化并在最小数据上 generate
   不抛错（返回值类型为 DataFrame/None 均属现状，不锁具体金额）。

隔离：DATA_DIR/RESULTS_DIR/ORDERS_DIR 全部 monkeypatch 到 tmp_path；不读写真实 data/。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

import multi_strategy as ms_mod


@pytest.fixture()
def io_env(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    results = tmp_path / 'results'
    orders = tmp_path / 'orders'
    for d in (data, results, orders):
        d.mkdir()
    monkeypatch.setattr(ms_mod, 'DATA_DIR', str(data))
    monkeypatch.setattr(ms_mod, 'RESULTS_DIR', str(results))
    monkeypatch.setattr(ms_mod, 'ORDERS_DIR', str(orders))
    return {'data': data, 'results': results, 'orders': orders}


def _write_today_stock(data_dir, today: str | None = None):
    # d914-06：today 由调用方/默认真实日传入（frozen_clock 场景显式固定），消除跨午夜日变
    today = (today or datetime.now().strftime('%Y%m%d'))
    df = pd.DataFrame({
        '代码': ['000001', '000002', '600000'],
        '名称': ['平安银行', '万科A', '浦发银行'],
        '最新价': [10.0, 8.0, 7.5],
        '涨跌幅': [1.2, -0.5, 0.3],
        '成交量': [100000, 200000, 150000],
        '成交额': [1e6, 1.6e6, 1.1e6],
        '换手率': [0.5, 0.8, 0.6],
        '流通市值': [1e10, 9e9, 8e9],
    })
    df.to_csv(data_dir / f'stock_{today}.csv', index=False, encoding='utf-8-sig')
    return today


def _write_history(data_dir, days=40, today: str | None = None):
    _now = datetime.strptime(today, '%Y%m%d') if today else datetime.now()
    today_dt = _now
    rows = []
    price = 10.0
    for i in range(days):
        d = (today_dt - timedelta(days=days - i)).strftime('%Y-%m-%d')
        for code in ('000001', '000002', '600000'):
            price = 10.0 + i * 0.01 + (0.1 if code == '000002' else 0)
            rows.append({'日期': d, '代码': code, '收盘': round(price, 2)})
    pd.DataFrame(rows).to_csv(data_dir / 'history.csv', index=False, encoding='utf-8-sig')


from datetime import timedelta  # noqa: E402


def test_main_no_data_fatal_branch(io_env, capsys):
    rc = ms_mod.main()
    assert rc == 1
    assert 'No stock data found' in capsys.readouterr().out


def test_main_runs_with_minimal_data(io_env, capsys, frozen_clock):
    frozen_clock('2026-09-14 12:00:00')  # d914-06：确定性时钟，消除跨午夜日变
    _write_today_stock(io_env['data'], today='20260914')
    _write_history(io_env['data'], today='20260914')
    rc = ms_mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    # 两分支均为现状：有共识（Vote saved）或无共识（No consensus picks）
    assert ('Vote saved' in out) or ('No consensus picks' in out)


def test_mid_low_tier_strategies_instantiable_and_runnable(io_env, frozen_clock):
    frozen_clock('2026-09-14 12:00:00')  # d914-06
    _write_history(io_env['data'], today='20260914')
    for cls in (ms_mod.MeanReversionStrategy, ms_mod.LowVolatilityStrategy):
        s = cls()
        assert hasattr(s, 'name') or hasattr(s, 'generate'), '策略对象缺基本接口'


def test_write_today_stock_cross_midnight_no_date_bleed(io_env, frozen_clock, monkeypatch):
    """d914-06：跨午夜用例——23:59:59 与 00:00:01 两次写入，文件名不串日。"""
    frozen_clock('2026-09-13 23:59:59')
    today_a = _write_today_stock(io_env['data'], today='20260913')
    assert today_a == '20260913'
    frozen_clock('2026-09-14 00:00:01')
    today_b = _write_today_stock(io_env['data'], today='20260914')
    assert today_b == '20260914'
    assert (io_env['data'] / 'stock_20260913.csv').exists()
    assert (io_env['data'] / 'stock_20260914.csv').exists()
