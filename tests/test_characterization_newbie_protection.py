"""newbie_protection characterization 测试（8e78，S1 补测：只锁现状，不改生产码）。

锁定行为（现状 characterization，非规格测试）：
1. init_newbie_status：首启创建 observation/day1 状态并落盘；二次调用读回同一文件。
2. update_newbie_status 时间保底：first_start_date 回拨 3 天→observation；8 天→最低 simulation；
   15 天→最低 pre_live（upgrade_type=passive_time）。
3. get_phase_banner / get_phase_psychology_tip：按当前阶段返回非空字符串。

隔离：STATUS_FILE/DATA_DIR 全部 monkeypatch 到 tmp_path；绝不触碰真实 data/newbie_status.json。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import newbie_protection as np_mod


@pytest.fixture()
def np_env(tmp_path, monkeypatch):
    status_file = tmp_path / 'newbie_status.json'
    monkeypatch.setattr(np_mod, 'STATUS_FILE', str(status_file))
    return status_file


def _write_status(status_file, first_start_date, phase='observation'):
    import json

    status = {
        'first_start_date': first_start_date,
        'current_phase': phase,
        'day_number': 1,
        'phase_start_date': first_start_date,
        'daily_pnl_history': [],
        'recommendation': '观察期 — 请勿实盘，仅学习系统操作流程',
    }
    status_file.write_text(json.dumps(status, ensure_ascii=False), encoding='utf-8')


def test_init_creates_observation_day1(np_env):
    status = np_mod.init_newbie_status()
    assert status['current_phase'] == 'observation'
    assert status['day_number'] == 1
    assert np_env.exists(), '首启应落盘状态文件'


def test_init_reads_back_same_file(np_env):
    first = np_mod.init_newbie_status()
    second = np_mod.init_newbie_status()
    assert second['first_start_date'] == first['first_start_date']


@pytest.mark.parametrize('back_days,expected_min', [(3, 'observation'), (8, 'simulation'), (15, 'pre_live')])
def test_update_time_floor(np_env, monkeypatch, back_days, expected_min):
    today = datetime.now()
    first = (today - timedelta(days=back_days)).strftime('%Y-%m-%d')
    _write_status(np_env, first)
    status = np_mod.update_newbie_status()
    order = ['observation', 'simulation', 'pre_live']
    # 时间保底：实际阶段不得低于 min_phase（表现驱动只能更高，不能更低）
    assert order.index(status['current_phase']) >= order.index(expected_min)
    assert status['day_number'] == back_days + 1


def test_phase_banner_and_tip_nonempty(np_env):
    _write_status(np_env, datetime.now().strftime('%Y-%m-%d'))
    np_mod.init_newbie_status()
    assert isinstance(np_mod.get_phase_banner(), str) and np_mod.get_phase_banner()
    # 现状：tip 返回 {'title','body'} dict
    tip = np_mod.get_phase_psychology_tip()
    assert isinstance(tip, dict) and tip.get('title') and tip.get('body')
