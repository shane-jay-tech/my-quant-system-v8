"""goal_metrics.py 目标验收三指标回归测试（2026-08-24 round 6）。"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import goal_metrics


def _write_log(logs_dir: Path, name: str, text: str):
    (logs_dir / name).write_text(text, encoding='utf-8')


def _data_health_text(rows=5554, nonzero=0.9991, volume=1.0, lag=0):
    return (
        "# 数据健康检查\n\n"
        f"| stock_csv | ✅ OK | file=stock_20260821.csv rows={rows} "
        f"nonzero_price_ratio={nonzero} nonempty_volume_ratio={volume} |\n"
        f"| history_csv | ✅ OK | rows=884982 unique_codes=7054 "
        f"latest_date=2026-08-21 lag_days={lag} |\n"
        f"| multi_vote | ✅ OK | file=multi_vote_20260821.json count=20 |\n"
    )


# ---------- pipeline success rate ----------

def test_pipeline_metrics_classifies_all_states(tmp_path):
    _write_log(tmp_path, 'pipeline_20260820.log', 'started but crashed, no final marker')
    _write_log(tmp_path, 'pipeline_20260821.log', 'Pipeline complete')
    _write_log(tmp_path, 'pipeline_20260822.log', '[FATAL] check_trading_day failed')
    _write_log(tmp_path, 'pipeline_20260823.log', '[SKIP] 非交易日，流水线跳过（周末）')
    _write_log(tmp_path, 'pipeline_20260824.log', 'running, no marker yet')

    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')

    assert m['success'] == 1
    assert m['failed'] == 1          # 20 号旧文件无终态（22 号周六 FATAL 归为 skip）
    assert m['skipped_non_trading'] == 2
    assert m['in_progress'] == 1
    assert m['attempts'] == 2
    assert m['success_rate_pct'] == 50.0
    assert m['status'] == 'DEGRADED'


def test_pipeline_alpha_pause_counts_as_success(tmp_path):
    _write_log(tmp_path, 'pipeline_20260821.log',
               '[ALPHA-GATE] PAUSED: underperform\nRun python alpha_gate.py --reset')
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    assert m['success'] == 1
    assert m['success_rate_pct'] == 100.0


def test_old_weekend_fatal_is_counted_as_skip(tmp_path):
    # 修复前周六日志以 check_trading_day FATAL 结束，应算非交易日 skip
    _write_log(tmp_path, 'pipeline_20260822.log',
               '[FATAL] check_trading_day failed (rc=1); aborting pipeline')
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    assert m['skipped_non_trading'] == 1
    assert m['failed'] == 0
    assert m['attempts'] == 0


def test_appended_last_failure_wins_after_earlier_success(tmp_path):
    text = ('=== RUN START [08:00] ===\nPipeline complete\n'
            '=== RUN START [18:00] ===\n[FATAL] position_sizing failed')
    _write_log(tmp_path, 'pipeline_20260821.log', text)
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    assert m['failed'] == 1
    assert m['success'] == 0


def test_appended_last_success_wins_after_earlier_failure(tmp_path):
    text = ('=== RUN START [08:00] ===\n[FATAL] fetch_quote failed\n'
            '=== RUN START [18:00] ===\nPipeline complete')
    _write_log(tmp_path, 'pipeline_20260821.log', text)
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    assert m['success'] == 1
    assert m['failed'] == 0


def test_appended_interrupt_after_success_is_interrupted(tmp_path):
    text = ('=== RUN START [08:00] ===\nPipeline complete\n'
            '=== RUN START [18:00] ===\nstarting fetch_history\n^C')
    _write_log(tmp_path, 'pipeline_20260821.log', text)
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    assert m['interrupted'] == 1
    assert m['attempts'] == 0
    assert m['success_rate_pct'] is None


def test_appended_empty_last_segment_does_not_reuse_earlier_terminal(tmp_path):
    text = ('=== RUN START [08:00] ===\nPipeline complete\n'
            '=== RUN START [18:00] ===\nstarting fetch_history (no terminal yet)')
    _write_log(tmp_path, 'pipeline_20260821.log', text)
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    # 最后一段没有终态；这是旧日期 → 截断失败，不能复用上一段的 success
    assert m['failed'] == 1
    assert m['success'] == 0


def test_pipeline_metrics_no_logs_unknown(tmp_path):
    m = goal_metrics.compute_pipeline_metrics(
        logs_dir=str(tmp_path), today_str='20260824')
    assert m['status'] == 'UNKNOWN'
    assert m['success_rate_pct'] is None


# ---------- data completeness ----------

def _ok_coverage():
    return {'status': 'OK', 'coverage_pct': 100.0,
            'expected_days': [], 'missing_days': [], 'raw_evidence': []}


def test_data_completeness_ok(tmp_path, monkeypatch):
    (tmp_path / 'data_health_20260821.md').write_text(
        _data_health_text(), encoding='utf-8')
    monkeypatch.setattr(goal_metrics, 'compute_data_coverage',
                        lambda data_dir=goal_metrics.DATA_DIR: _ok_coverage())
    m = goal_metrics.compute_data_completeness(
        reports_dir=str(tmp_path), data_dir=str(tmp_path / 'data'))
    assert m['status'] == 'OK'
    assert m['rows'] == 5554
    assert m['lag_days'] == 0
    assert m['completeness_pct'] == 99.95


def test_data_completeness_degraded_on_low_volume_ratio(tmp_path, monkeypatch):
    (tmp_path / 'data_health_20260821.md').write_text(
        _data_health_text(volume=0.8), encoding='utf-8')
    monkeypatch.setattr(goal_metrics, 'compute_data_coverage',
                        lambda data_dir=goal_metrics.DATA_DIR: _ok_coverage())
    m = goal_metrics.compute_data_completeness(
        reports_dir=str(tmp_path), data_dir=str(tmp_path / 'data'))
    assert m['status'] == 'DEGRADED'
    assert m['completeness_pct'] < 95.0


def test_data_completeness_fail_on_low_rows(tmp_path, monkeypatch):
    (tmp_path / 'data_health_20260821.md').write_text(
        _data_health_text(rows=3000), encoding='utf-8')
    monkeypatch.setattr(goal_metrics, 'compute_data_coverage',
                        lambda data_dir=goal_metrics.DATA_DIR: _ok_coverage())
    m = goal_metrics.compute_data_completeness(
        reports_dir=str(tmp_path), data_dir=str(tmp_path / 'data'))
    assert m['status'] == 'FAIL'
    assert m['rows_ok'] is False


def test_data_completeness_unknown_without_report(tmp_path):
    m = goal_metrics.compute_data_completeness(
        reports_dir=str(tmp_path), data_dir=str(tmp_path / 'data'))
    assert m['status'] == 'UNKNOWN'
    assert m['completeness_pct'] is None


def test_data_coverage_full_and_missing(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    days = ['20260817', '20260818', '20260819', '20260820', '20260821']
    for day in days:
        (data_dir / f'stock_{day}.csv').write_text(
            '代码,最新价\n' + '\n'.join('000001,10' for _ in range(4000)),
            encoding='utf-8')
    # history 提供独立于 stock 文件的期望交易日（避免删除 stock 后 expected 缩水）
    (data_dir / 'history.csv').write_text(
        '日期\n' + '\n'.join(f'{d[:4]}-{d[4:6]}-{d[6:]}' for d in days),
        encoding='utf-8')
    m = goal_metrics.compute_data_coverage(data_dir=str(data_dir))
    assert m['coverage_pct'] == 100.0
    assert m['status'] == 'OK'
    assert m['missing_days'] == []

    # 删除 2 天 stock 快照，但 history 仍在 → 期望 5 天、覆盖 3/5
    (data_dir / 'stock_20260818.csv').unlink()
    (data_dir / 'stock_20260819.csv').unlink()
    m2 = goal_metrics.compute_data_coverage(data_dir=str(data_dir))
    assert m2['coverage_pct'] == 60.0
    assert m2['status'] == 'FAIL'
    assert set(m2['missing_days']) == {'20260818', '20260819'}


# ---------- self check pass rate ----------

def test_self_check_pass_rate(tmp_path):
    (tmp_path / 'system_self_check_v86.json').write_text(
        json.dumps({'score': {'passed': 142, 'total': 142}}), encoding='utf-8')
    m = goal_metrics.compute_self_check_pass_rate(reports_dir=str(tmp_path))
    assert m['status'] == 'OK'
    assert m['pass_rate_pct'] == 100.0


def test_self_check_bad_json_unknown(tmp_path):
    (tmp_path / 'system_self_check_v86.json').write_text('{broken', encoding='utf-8')
    m = goal_metrics.compute_self_check_pass_rate(reports_dir=str(tmp_path))
    assert m['status'] == 'UNKNOWN'
    assert m['pass_rate_pct'] is None


# ---------- report & registry ----------

def test_build_and_write_report(tmp_path, monkeypatch):
    logs = tmp_path / 'logs'
    reports = tmp_path / 'reports'
    logs.mkdir(); reports.mkdir()
    _write_log(logs, 'pipeline_20260821.log', 'Pipeline complete')
    (reports / 'data_health_20260821.md').write_text(
        _data_health_text(), encoding='utf-8')
    (reports / 'system_self_check_v86.json').write_text(
        json.dumps({'score': {'passed': 142, 'total': 142}}), encoding='utf-8')
    monkeypatch.setattr(goal_metrics, 'compute_data_coverage',
                        lambda data_dir=goal_metrics.DATA_DIR: _ok_coverage())

    report = goal_metrics.build_report(
        logs_dir=str(logs), reports_dir=str(reports),
        data_dir=str(tmp_path / 'data'), date_str='20260824')
    md_path, js_path = goal_metrics.write_report(report, reports_dir=str(reports))

    assert '流水线成功率' in Path(md_path).read_text(encoding='utf-8')
    loaded = json.loads(Path(js_path).read_text(encoding='utf-8'))
    assert loaded['metrics']['data_completeness']['status'] == 'OK'


def test_pipeline_registry_has_goal_metrics_before_self_check():
    from core import pipeline
    keys = list(pipeline.PIPELINE_STEPS.keys())
    assert 'goal_metrics' in keys
    assert keys.index('goal_metrics') < keys.index('self_check')
    assert pipeline.PIPELINE_STEPS['goal_metrics']['label'] == '目标指标'
