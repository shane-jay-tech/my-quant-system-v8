"""v8.7 审查修复回归测试（2026-09-02，全部离线）。

锁定本轮前端/后端重构的安全修复：
- app.loaders.parse_pick_line 统一解析（新老表头）
- app.loaders.load_current_prices 向量化后输出不变
- goal_metrics 自检报告文件名跟随 SYSTEM_VERSION
- smoke_tests 覆盖 v8.7 新模块
- auto_heal 不再把 'python "..."' 字符串当脚本名
- cost_tracker 不再把本地审计记为 LLM 调用
- bark_sender.parsers 删除重复 _lookup_position_shares（唯一实现留在 rebalancer）
- 状态 JSON 原子写：portfolio_manager / track_performance / data_loader 缓存
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import app.loaders as loaders  # noqa: E402
import goal_metrics  # noqa: E402
import smoke_tests  # noqa: E402
import portfolio_manager  # noqa: E402
import track_performance  # noqa: E402
import data_loader  # noqa: E402
import bark_sender.parsers as parsers  # noqa: E402


# ------------------------------------------------------------
# app.loaders：统一选股解析 + 向量化
# ------------------------------------------------------------
def _parts_new14():
    return ['1', '605018', '长华集团', '其他综合', '12.86', '+5.32', '12.61', '12.39',
            '52.78', '2.60', '60.45', '100', '中', '显著放量 + MACD正向']


def _parts_old13():
    return ['1', '605018', '长华集团', '12.86', '+5.32', '12.61', '12.39',
            '52.78', '2.60', '60.45', '100', '中', '显著放量 + MACD正向']


def test_parse_pick_line_new_and_old_formats():
    new = loaders.parse_pick_line(_parts_new14())
    old = loaders.parse_pick_line(_parts_old13())
    assert new['代码'] == old['代码'] == '605018'
    assert new['名称'] == old['名称'] == '长华集团'
    assert new['最新价'] == old['最新价'] == 12.86
    assert new['RSI'] == old['RSI'] == 52.78
    assert new['评分'] == old['评分'] == 100
    assert new['选入理由'] == old['选入理由'] == '显著放量 + MACD正向'


def test_parse_pick_line_rejects_bad_rows():
    assert loaders.parse_pick_line(['1', '605018']) is None
    assert loaders.parse_pick_line([]) is None
    assert loaders.parse_pick_line(['x', 'abc', '名称', '板块', '价格']) is None  # 代码列不是 6 位数字格式时由调用方过滤，这里只验解析不回抛


def test_load_current_prices_vectorized(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, 'DATA_DIR', str(tmp_path))
    df = pd.DataFrame({'代码': ['1', '000002'], '名称': ['平安银行', '万科A'], '最新价': [11.41, 8.2]})
    df.to_csv(tmp_path / 'stock_20260902.csv', index=False, encoding='utf-8-sig')
    if hasattr(loaders.load_current_prices, 'clear'):
        loaders.load_current_prices.clear()
    prices = loaders.load_current_prices()
    assert prices == {'000001': {'name': '平安银行', 'price': 11.41},
                      '000002': {'name': '万科A', 'price': 8.2}}


def test_load_index_data_bad_file(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, 'DATA_DIR', str(tmp_path))
    (tmp_path / 'hs300_index.csv').write_text('日期,收盘\n2026-01-01,10\n', encoding='utf-8')
    if hasattr(loaders.load_index_data, 'clear'):
        loaders.load_index_data.clear()
    assert loaders.load_index_data() is None  # <2 行 → 提示数据不足，不崩


# ------------------------------------------------------------
# goal_metrics / smoke_tests / auto_heal / cost_tracker
# ------------------------------------------------------------
def test_goal_metrics_self_check_name_follows_version():
    assert goal_metrics.self_check_report_name() == f"system_self_check_v{goal_metrics.SYSTEM_VERSION.replace('.', '')}.json"
    assert 'v86.json' in goal_metrics.self_check_report_name()


def test_smoke_covers_v87_modules():
    assert {'core.llm', 'digest', 'decision_replay', 'llm_analyst', 'bark_sender.channels'} <= set(smoke_tests.CORE_MODULES)


def test_auto_heal_calls_script_by_name_not_command_string():
    src = (BASE_DIR / 'auto_heal.py').read_text(encoding='utf-8')
    assert src.count('run_script(\'_self_check.py\', timeout=60)') == 2
    assert "run_script(f'python" not in src  # 不再把整个命令字符串当文件名


def test_cost_tracker_no_longer_logs_itself_as_llm():
    src = (BASE_DIR / 'cost_tracker.py').read_text(encoding='utf-8')
    assert "log_llm_call('cost_tracker'" not in src


def test_parsers_duplicate_position_lookup_removed():
    assert not hasattr(parsers, '_lookup_position_shares')


# ------------------------------------------------------------
# 原子写 / 读容错
# ------------------------------------------------------------
def test_portfolio_manager_save_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_manager, 'STATE_FILE', str(tmp_path / 'portfolio_state.json'))
    monkeypatch.setattr(portfolio_manager, 'DATA_DIR', str(tmp_path))
    portfolio_manager.save_state({'positions': [{'代码': '000001'}]})
    data = json.loads((tmp_path / 'portfolio_state.json').read_text(encoding='utf-8'))
    assert data['positions'][0]['代码'] == '000001'
    assert not list(tmp_path.glob('*.tmp'))  # 无 .tmp 残留


def test_track_performance_corrupted_file_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(track_performance, 'TRACK_FILE', str(tmp_path / 'pick_performance.json'))
    (tmp_path / 'pick_performance.json').write_text('{broken', encoding='utf-8')
    tracker = track_performance.load_tracker()
    assert tracker == {'records': [], 'summary': {}, 'updated': None}


def test_data_loader_cache_write_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(data_loader, 'CACHE_DIR', str(tmp_path))
    df = pd.DataFrame({'代码': ['000001', '000002'], '名称': ['a', 'b']})
    data_loader._save_cache('fundamental', df)
    files = list(tmp_path.glob('fundamental_*.csv'))
    assert len(files) == 1 and not list(tmp_path.glob('*.tmp'))
    loaded = data_loader._load_cache('fundamental')
    assert loaded is not None and len(loaded) == 2


def test_tests_cannot_reset_production_sim_account():
    """conftest 护栏：任何测试直接对生产 sim_results 调用 _reset_sim_account 都必须失败。"""
    import app.pages as pages
    prod_state = BASE_DIR / 'sim_results' / 'account_state.json'
    with pytest.raises(AssertionError):
        pages._reset_sim_account(str(prod_state), 2400.0)
