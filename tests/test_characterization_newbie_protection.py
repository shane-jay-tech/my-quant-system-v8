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
    # n916b-02：冻结生产模块时钟（消除午夜翻转依赖；断言保持现状语义）
    frozen = datetime(2026, 9, 14)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return frozen

    monkeypatch.setattr(np_mod, 'datetime', FixedDateTime)
    today = frozen
    first = (today - timedelta(days=back_days)).strftime('%Y-%m-%d')
    _write_status(np_env, first)
    status = np_mod.update_newbie_status()
    order = ['observation', 'simulation', 'pre_live']
    # 时间保底：实际阶段不得低于 min_phase（表现驱动只能更高，不能更低）
    assert order.index(status['current_phase']) >= order.index(expected_min)
    assert status['day_number'] == back_days + 1


def test_phase_banner_and_tip_nonempty(np_env):
    _write_status(np_env, datetime(2026, 9, 14).strftime('%Y-%m-%d'))  # n916b-02 冻结日
    np_mod.init_newbie_status()
    assert isinstance(np_mod.get_phase_banner(), str) and np_mod.get_phase_banner()
    # 现状：tip 返回 {'title','body'} dict
    tip = np_mod.get_phase_psychology_tip()
    assert isinstance(tip, dict) and tip.get('title') and tip.get('body')


# ---------- 升级链负例/边界 characterization（q918-04，S5 F-5：:97-101/:162-166/:472-486 分支） ----------


def _write_status_raw(status_file, extra):
    import json

    status = {
        'first_start_date': '2026-09-14',
        'current_phase': 'observation',
        'day_number': 1,
        'phase_start_date': '2026-09-14',
        'daily_pnl_history': [],
    }
    status.update(extra)
    status_file.write_text(json.dumps(status, ensure_ascii=False), encoding='utf-8')


def _force_ready(monkeypatch):
    """令 check_readiness 稳定 ready（study25+trades25+discipline25，无资金/统计数值断言）。"""
    monkeypatch.setattr(np_mod, '_count_recent_diaries', lambda days=7: 3)
    monkeypatch.setattr(np_mod, '_count_recent_learning_visits', lambda days=7: 0)
    monkeypatch.setattr(np_mod, '_count_real_trades', lambda: 2)
    monkeypatch.setattr(np_mod, '_evaluate_discipline', lambda: 25)


def test_readiness_suggestions_3_becomes_passive(np_env, monkeypatch):
    """连续建议计数：upgrade_suggestions=2 时再 ready → 第3次 → upgrade_type='passive'（:474）。"""
    _force_ready(monkeypatch)
    _write_status_raw(np_env, {'upgrade_suggestions': 2})
    result = np_mod.check_readiness()
    assert result['upgrade_type'] == 'passive'
    saved = np_mod.init_newbie_status()
    assert saved['upgrade_suggestions'] == 3


def test_readiness_active_then_apply_upgrade(np_env, monkeypatch):
    """ready+active 链：suggestions=0 首次 ready → 'active'（等确认）；apply_upgrade() 推进阶段
    并复位计数、升级类型记 active、清 ready_request（:162-166 契约的另一侧）。"""
    _force_ready(monkeypatch)
    _write_status_raw(np_env, {'upgrade_suggestions': 0, 'ready_request_date': '2026-09-14T10:00:00'})
    result = np_mod.check_readiness()
    assert result['upgrade_type'] == 'active'

    new_phase = np_mod.apply_upgrade()
    assert new_phase == 'simulation'
    saved = np_mod.init_newbie_status()
    assert saved['current_phase'] == 'simulation'
    assert saved['upgrade_suggestions'] == 0
    assert saved['upgrade_type'] == 'active'
    assert 'ready_request_date' not in saved


def test_banner_unknown_upgrade_type_has_no_suffix(np_env):
    """upgrade_type 未知值 → 横幅无「[系统自动推进]/[你主动迈出了这一步！]」后缀（:162-166 else 分支）。"""
    _write_status_raw(np_env, {'current_phase': 'simulation', 'day_number': 5, 'upgrade_type': 'mystery'})
    banner = np_mod.get_phase_banner()
    assert isinstance(banner, str) and banner
    assert '[系统自动推进]' not in banner
    assert '[你主动迈出了这一步！]' not in banner
