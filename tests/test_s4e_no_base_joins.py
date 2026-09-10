"""S4-e 静态断言（2026-09-10）：BASE 拼接路径棘轮——存量冻结，新增即失败。

范围：根目录 *.py 与 core/ ops/ app/ bark_sender/ utils/（.venv/archive/tmp 除外）。
BASELINE = 2026-09-11 夜（S4-a~d 落地后）逐文件实测的 os.path.join(BASE…|BASE_DIR…
出现次数。规则：
1. 任何文件出现次数 > 基线 → 测试失败（禁止无感回潮/新增手写路径）；
2. 存量债务（未来批次要收敛的历史拼接，集中在 ops/ 辅助层与 bark_sender 文案层）
   以此基线冻结，收敛后应同步下调基线数字。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCAN_DIRS = ['core', 'ops', 'app', 'bark_sender', 'utils']
PATTERN = re.compile(r'os\.path\.join\(\s*BASE(?:_DIR)?\b')

BASELINE: dict[str, int] = {
    'alpha_gate.py': 1, 'archive_old_data.py': 2, 'auto_heal.py': 10, 'behavior_log.py': 3,
    'benchmark_comparison.py': 4, 'broker_adapter.py': 3, 'cost_tracker.py': 2,
    'daily_pipeline.py': 3, 'decision_replay.py': 3, 'digest.py': 4, 'etf_gate.py': 2,
    'evolve_daily_light.py': 5, 'evolve_strategy.py': 6, 'exit_advisor.py': 4,
    'external_research.py': 1, 'factor_analysis.py': 2, 'fetch_minute_kline.py': 1,
    'goal_metrics.py': 3, 'integrate_knowledge.py': 4, 'llm_analyst.py': 2,
    'log_real_trade.py': 1, 'monthly_behavior_report.py': 2, 'multi_strategy.py': 3,
    'newbie_instruction_card.py': 2, 'newbie_protection.py': 5, 'portfolio_manager.py': 2,
    'position_sizer.py': 1, 'premarket_sim.py': 2, 'psychology_assistant.py': 3,
    'replay_picks.py': 4, 'research_agent.py': 3, 'send_to_bark.py': 2, 'sim_trade.py': 2,
    'smoke_tests.py': 1, 'strategy_arena.py': 3, 'strategy_feedback.py': 5,
    'track_performance.py': 2, 'tracking_error_report.py': 4, 'core/llm.py': 1,
    'core/paths.py': 1, 'app/loaders.py': 3, 'app/pages.py': 12, 'app/sidebar.py': 2,
    'bark_sender/builders.py': 6, 'bark_sender/formatters.py': 6, 'bark_sender/parsers.py': 5,
    'bark_sender/push.py': 3, 'bark_sender/rebalancer.py': 3, 'utils/calendar.py': 1,
}


def _covered_files():
    files = sorted(REPO.glob('*.py'))
    for d in SCAN_DIRS:
        dd = REPO / d
        if dd.is_dir():
            files.extend(dd.rglob('*.py'))
    return [f for f in files if not any(part in ('.venv', 'archive', 'tmp', '__pycache__') for part in f.parts)]


def _counts():
    return {
        str(f.relative_to(REPO)).replace('\\', '/'): len(PATTERN.findall(f.read_text(encoding='utf-8', errors='ignore')))
        for f in _covered_files()
    }


def test_no_base_join_above_frozen_baseline():
    counts = _counts()
    regressions = [
        f'{rel}: {n} > 基线 {BASELINE.get(rel, 0)}'
        for rel, n in sorted(counts.items())
        if n > BASELINE.get(rel, 0)
    ]
    assert not regressions, '发现新增/回潮的 BASE 拼接路径：\n' + '\n'.join(regressions)


def test_new_files_have_zero_base_joins():
    counts = _counts()
    newcomers = [rel for rel, n in counts.items() if rel not in BASELINE and n > 0]
    assert not newcomers, '新文件出现 BASE 拼接（基线外零容忍）：' + ', '.join(newcomers)


def test_scan_scope_is_nonempty():
    files = _covered_files()
    assert len(files) > 50, f'扫描范围异常缩小：仅 {len(files)} 文件'


def test_baseline_files_still_exist_or_were_cleaned():
    """基线文件被删除/收敛属合法演进——提示同步收缩基线，不算失败。"""
    missing_cleaned = [rel for rel in BASELINE if rel not in _counts()]
    if missing_cleaned:
        pytest.skip(f'以下基线文件已删除或已收敛，请同步收缩 BASELINE：{missing_cleaned}')
