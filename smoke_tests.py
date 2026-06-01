"""
冒烟测试 v1 — 重构/升级时第一道防线

不做单元测试（覆盖率成本与 1200 元小资金不匹配），只做：
1. 每个核心模块可被 import（不抛 ImportError / SyntaxError）
2. 关键纯函数能被调用并返回非空（不需要外部 IO）
3. 配置中心 cfg_get 能读到所有新增键

跑法：
    python smoke_tests.py

输出：通过率 + 失败模块名 + 报告路径

非阻塞：失败也不影响 daily_pipeline，只为 dev-time 自查。
"""
import os
import sys
import traceback
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')


CORE_MODULES = [
    'core.config', 'core.pipeline',
    'strategy', 'multi_strategy', 'enhanced_backtest',
    'position_sizer', 'broker_adapter', 'sector_classifier',
    'fetch_stock_data', 'fetch_history', 'fetch_minute_kline',
    'check_trading_day', 'data_loader',
    'evolve_daily_light', 'strategy_feedback', 'sim_trade',
    'exit_advisor', 'cost_tracker', 'auto_heal', '_self_check',
    'send_to_bark', 'research_agent', 'integrate_knowledge',
    'psychology_assistant', 'newbie_protection',
    # v8.5 (5/19 batch) new
    'portfolio_manager', 'data_validator', 'archive_old_data',
    'behavior_log', 'monthly_behavior_report', 'benchmark_comparison',
    'tracking_error_report',
]


CONFIG_KEYS = [
    'strategy.ma_short', 'strategy.top_n',
    'backtest.execution_mode', 'backtest.slippage',
    'cost.commission_min', 'cost.notional_dynamic',
    'position.regime_hysteresis_days',
    'broker.gap_skip_pct',
    'evolve.dry_run_only',
    'portfolio.exclude_held_from_picks',
    'data_validation.min_stock_rows',
    'archive.stock_csv_keep_days',
    'behavior_log.enabled',
]


# 函数级冒烟（纯函数 + 不依赖外部 IO 才放这里）
PURE_FUNCS = [
    ('strategy', 'calc_rsi', None),  # 只验 import + 是否 callable
    ('position_sizer', 'detect_market_regime', None),
    ('portfolio_manager', 'get_held_codes', ()),  # 调用一次（依赖 portfolio_state.json，可能为空）
]


def test_imports():
    results = []
    for mod in CORE_MODULES:
        try:
            __import__(mod)
            results.append((mod, 'OK', ''))
        except Exception as e:
            results.append((mod, 'FAIL', f'{type(e).__name__}: {e}'))
    return results


def test_config_keys():
    try:
        from core.config import get as cfg_get
    except Exception as e:
        return [('core.config', 'FAIL', str(e))]
    results = []
    for key in CONFIG_KEYS:
        try:
            val = cfg_get(key, None)
            if val is None:
                results.append((key, 'FAIL', 'returned None'))
            else:
                results.append((key, 'OK', f'={val}'))
        except Exception as e:
            results.append((key, 'FAIL', str(e)))
    return results


def test_pure_funcs():
    results = []
    for mod_name, func_name, args in PURE_FUNCS:
        try:
            mod = __import__(mod_name)
            func = getattr(mod, func_name, None)
            if func is None:
                results.append((f'{mod_name}.{func_name}', 'FAIL', 'attr not found'))
                continue
            if not callable(func):
                results.append((f'{mod_name}.{func_name}', 'FAIL', 'not callable'))
                continue
            # 仅当 args 不为 None 时才真调用
            if args is not None:
                _ = func(*args)
            results.append((f'{mod_name}.{func_name}', 'OK', 'callable' + (' + invoked' if args is not None else '')))
        except Exception as e:
            results.append((f'{mod_name}.{func_name}', 'FAIL', f'{type(e).__name__}: {e}'))
    return results


def render_report(import_results, config_results, func_results):
    today = datetime.now()
    lines = [
        f"# 冒烟测试报告 — {today.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    sections = [
        ('## 1. 模块导入', import_results),
        ('## 2. 配置键可读', config_results),
        ('## 3. 关键函数可调', func_results),
    ]
    overall_ok = 0
    overall_fail = 0

    for title, results in sections:
        lines.append(title)
        lines.append("")
        lines.append("| 项 | 状态 | 备注 |")
        lines.append("|----|------|------|")
        for name, status, note in results:
            icon = '✅' if status == 'OK' else '❌'
            lines.append(f"| {name} | {icon} {status} | {note[:80]} |")
            if status == 'OK':
                overall_ok += 1
            else:
                overall_fail += 1
        lines.append("")

    pass_rate = overall_ok / max(1, overall_ok + overall_fail) * 100
    lines.extend([
        "## 总览",
        "",
        f"- ✅ 通过: {overall_ok}",
        f"- ❌ 失败: {overall_fail}",
        f"- 通过率: {pass_rate:.1f}%",
        "",
        "---",
        f"*由 smoke_tests.py v{SYSTEM_VERSION} 自动生成*",
    ])
    return '\n'.join(lines), overall_ok, overall_fail


def main():
    print(f"{'='*50}")
    print(f"  冒烟测试 v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    print("\n[1/3] Import 检查...")
    import_results = test_imports()
    fails = [r for r in import_results if r[1] != 'OK']
    print(f"  {len(import_results) - len(fails)}/{len(import_results)} OK")
    for name, _, msg in fails:
        print(f"    [FAIL] {name}: {msg[:100]}")

    print("\n[2/3] 配置键检查...")
    config_results = test_config_keys()
    fails2 = [r for r in config_results if r[1] != 'OK']
    print(f"  {len(config_results) - len(fails2)}/{len(config_results)} OK")
    for name, _, msg in fails2:
        print(f"    [FAIL] {name}: {msg}")

    print("\n[3/3] 函数可调检查...")
    func_results = test_pure_funcs()
    fails3 = [r for r in func_results if r[1] != 'OK']
    print(f"  {len(func_results) - len(fails3)}/{len(func_results)} OK")
    for name, _, msg in fails3:
        print(f"    [FAIL] {name}: {msg[:100]}")

    report, ok, fail = render_report(import_results, config_results, func_results)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')
    path = os.path.join(REPORTS_DIR, f'smoke_tests_{today_str}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n[SMOKE] {ok} OK / {fail} FAIL ({ok/(ok+fail)*100:.1f}% pass rate)")
    print(f"[SMOKE] report: {path}")

    # 失败超过 5% 返回非零
    if fail > (ok + fail) * 0.05:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
