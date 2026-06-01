"""
系统综合自检 + 健康报告生成（版本号从 SYSTEM_VERSION 单一事实源拉取）
输出: reports/health_check_YYYYMMDD.md，含周趋势对比
"""
import os, sys, json, glob, importlib
from datetime import datetime, timedelta, date

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, 'data')
os.chdir(BASE)
sys.path.insert(0, BASE)

# v8.5: 单一版本号源
from core.config import SYSTEM_VERSION

results = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'checks': [],
           'score': {'total': 0, 'passed': 0, 'warn': 0, 'fail': 0}}

def check(name, category, condition, detail=''):
    r = {'name': name, 'category': category, 'status': 'PASS' if condition else 'FAIL', 'detail': detail}
    results['checks'].append(r)
    results['score']['total'] += 1
    if condition: results['score']['passed'] += 1
    else: results['score']['fail'] += 1

def warn(name, category, condition, detail=''):
    r = {'name': name, 'category': category, 'status': 'WARN' if not condition else 'PASS', 'detail': detail}
    results['checks'].append(r)
    results['score']['total'] += 1
    if not condition: results['score']['warn'] += 1
    else: results['score']['passed'] += 1

def is_non_trading_day():
    """简单 heuristic：周末视为非交易日；周一15:30前也视为数据可接受较旧"""
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return True
    if weekday == 0 and now.hour < 16:
        return True
    return False


def _trading_days_behind(latest, today=None, data_dir=DATA_DIR):
    """latest 落后 today 的交易日数（latest 当天=0）。

    优先 utils.calendar.count_trading_days（基于 data/stock_*.csv 文件名，
    跨周末/长假安全）；失败时回退日历天数。v8.7 修周一误报：上周五→周一
    日历差 3 天，但交易日落差只有 1 天。
    """
    if today is None:
        today = date.today()
    try:
        from utils.calendar import count_trading_days
        behind = count_trading_days(latest, today, data_dir=data_dir) - 1
        return max(int(behind), 0)
    except Exception:
        def _as_date(v):
            if isinstance(v, datetime):
                return v.date()
            if hasattr(v, 'date') and not isinstance(v, date):
                return v.date()
            if isinstance(v, date):
                return v
            for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
                try:
                    return datetime.strptime(str(v)[:10] if len(str(v)) >= 10 else str(v), fmt).date()
                except ValueError:
                    continue
            return date.today()
        return max((_as_date(today) - _as_date(latest)).days, 0)


def load_prev_health():
    """加载上周健康报告用于趋势对比"""
    prev_files = sorted(glob.glob(os.path.join(BASE, 'reports', 'health_check_*.md')), reverse=True)
    if len(prev_files) >= 2:
        prev_path = prev_files[1]  # 上一份（非当前）
    elif len(prev_files) == 1:
        prev_path = prev_files[0]
    else:
        return None

    prev_date = os.path.basename(prev_path).replace('health_check_', '').replace('.md', '')
    with open(prev_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract scores
    import re
    scores = {}
    for m in re.finditer(r'(\w+)\s+█+\s+(\d+)/(\d+)', content):
        scores[m.group(1)] = {'passed': int(m.group(2)), 'total': int(m.group(3))}
    return {'date': prev_date, 'scores': scores}


print("="*60)
print(f"  v{SYSTEM_VERSION} Health Check @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("="*60)

# ── 1. File Integrity ──
print("\n[1] File Integrity")
core_modules = [
    'strategy.py', 'multi_strategy.py', 'enhanced_backtest.py',
    'fetch_minute_kline.py', 'position_sizer.py', 'sim_trade.py',
    'strategy_feedback.py', 'broker_adapter.py', 'research_agent.py',
    'integrate_knowledge.py', 'psychology_assistant.py',
    'newbie_instruction_card.py', 'send_to_bark.py',
    'fetch_stock_data.py', 'fetch_history.py', 'check_trading_day.py',
    'sector_classifier.py', 'track_performance.py',
    'evolve_strategy.py', 'external_research.py',
    'data_loader.py', 'factor_analysis.py', 'portfolio_risk.py',
    'premarket_sim.py', 'walk_forward.py', 'monte_carlo.py', 'strategy_arena.py',
]
v75_new = ['cost_tracker.py', 'newbie_protection.py', 'evolve_daily_light.py', 'log_real_trade.py',
           'auto_heal.py', 'trade_analyzer.py', 'exit_advisor.py']
v85_new = ['portfolio_manager.py', 'data_validator.py', 'archive_old_data.py',
           'behavior_log.py', 'monthly_behavior_report.py',
           'benchmark_comparison.py', 'tracking_error_report.py', 'smoke_tests.py']
v86_new = ['fetch_etf_data.py']
config_files = ['daily_pipeline.bat', 'app.py', 'CLAUDE.md',
                'requirements.txt', 'core/config.py', 'real_trades.csv',
                'weekly_health_check.bat', 'learning/first_week_guide.md']

# v7.6: 拆分后的子包文件
sub_packages = [
    'bark_sender/__init__.py', 'bark_sender/config.py', 'bark_sender/parsers.py',
    'bark_sender/formatters.py', 'bark_sender/rebalancer.py', 'bark_sender/builders.py',
    'bark_sender/push.py',
    'app/__init__.py', 'app/styles.py', 'app/sidebar.py', 'app/loaders.py', 'app/pages.py',
]

for mod in core_modules + v75_new + v85_new + v86_new + config_files + sub_packages:
    exists = os.path.exists(os.path.join(BASE, mod))
    check(f'File: {mod}', 'file', exists)

# ── 2. Data Files ──
print("\n[2] Data")
data_checks = {
    'history.csv': 'K-line history', 'hs300_index.csv': 'HS300 index',
    'risk_config.json': 'Risk config', 'good_trades.json': 'Cold-start good',
    'bad_trades.json': 'Cold-start bad', 'newbie_status.json': 'Newbie protection',
    'evolve_daily_state.json': 'Daily evolution', 'pick_performance.json': 'Pick performance',
    'factor_weights.json': 'Factor weights', 'arena_config.json': 'Arena config',
    # v8.5 新增产物
    'portfolio_state.json': 'Portfolio state',
    'behavior_log.csv': 'Behavior log',
    'strategy_forward_returns.csv': 'Forward returns',
    'regime_state.json': 'Regime state',
    'system_config.json': 'System config',
    'etf_watchlist.json': 'ETF watchlist',
}
for fname, desc in data_checks.items():
    path = os.path.join(BASE, 'data', fname)
    ok = os.path.exists(path) and os.path.getsize(path) > 0
    check(f'Data: {desc}', 'data', ok)

# Data freshness
try:
    import pandas as pd
    stock_files = sorted(glob.glob(os.path.join(BASE, 'data', 'stock_*.csv')), reverse=True)
    if stock_files:
        mtime = datetime.fromtimestamp(os.path.getmtime(stock_files[0]))
        age_h = (datetime.now() - mtime).total_seconds() / 3600
        freshness_thresh = 72 if is_non_trading_day() else 24
        check('Data: stock freshness', 'data', age_h < freshness_thresh, f'{age_h:.1f}h old (threshold={freshness_thresh}h)')

    hist_path = os.path.join(BASE, 'data', 'history.csv')
    if os.path.exists(hist_path):
        hist = pd.read_csv(hist_path, dtype={'代码': str})
        hist['日期'] = pd.to_datetime(hist['日期'])
        latest = hist['日期'].max()
        days_behind = _trading_days_behind(latest, today=date.today(), data_dir=DATA_DIR)
        check('Data: K-line freshness', 'data', days_behind <= 2,
              f'{latest.strftime("%Y-%m-%d")}, {days_behind} trading day(s) behind')

    # v8.6: 复用 data_validator 的深度校验（行数/非零价/成交量/lag），避免阈值在两处漂移
    try:
        from data_validator import check_stock_csv as _v_stock, check_history_csv as _v_hist
        for label, dv_result in [('Data: stock quality', _v_stock()),
                                 ('Data: history lag', _v_hist())]:
            status = dv_result.get('status', 'FAIL')
            detail = dv_result.get('reason', '') or ' '.join(f"{k}={v}" for k, v in dv_result.get('metrics', {}).items())
            if status == 'OK':
                check(label, 'data', True, detail)
            elif status == 'WARN':
                warn(label, 'data', False, detail)
            else:
                check(label, 'data', False, detail)
    except Exception as e:
        warn('Data: validator integration', 'data', False, str(e)[:80])
except Exception as e:
    warn('Data: analysis', 'data', False, str(e)[:80])

# Minute K-line coverage
minute_dir = os.path.join(BASE, 'data', 'minute_kline')
if os.path.exists(minute_dir):
    mf = [f for f in os.listdir(minute_dir) if f.endswith('.csv')]
    check('Data: minute K-line', 'data', len(mf) >= 20, f'{len(mf)} stocks')

# ── 3. Module Imports ──
print("\n[3] Imports")
modules_import = [
    ('strategy', 'Trend Following'), ('enhanced_backtest', 'Backtest'),
    ('fetch_minute_kline', 'Minute K-line'), ('position_sizer', 'Position'),
    ('sector_classifier', 'Sector'), ('cost_tracker', 'Cost'),
    ('newbie_protection', 'Protection'), ('evolve_daily_light', 'DailyEvolve'),
    ('strategy_feedback', 'Feedback'), ('newbie_instruction_card', 'NewbieCard'),
    ('psychology_assistant', 'Psychology'), ('send_to_bark', 'Bark'),
    ('sim_trade', 'SimTrade'), ('broker_adapter', 'Broker'),
    ('auto_heal', 'AutoHeal'), ('trade_analyzer', 'TradeAnalyzer'),
    ('exit_advisor', 'ExitAdvisor'),
    ('data_loader', 'DataLoader'), ('factor_analysis', 'FactorAnalysis'),
    ('portfolio_risk', 'PortfolioRisk'), ('premarket_sim', 'PremarketSim'),
    ('walk_forward', 'WalkForward'), ('monte_carlo', 'MonteCarlo'),
    ('strategy_arena', 'StrategyArena'),
    # v8.5 新增
    ('portfolio_manager', 'PortfolioMgr'), ('data_validator', 'DataValidator'),
    ('archive_old_data', 'Archive'), ('behavior_log', 'BehaviorLog'),
    ('monthly_behavior_report', 'MonthlyBehavior'),
    ('benchmark_comparison', 'Benchmark'), ('tracking_error_report', 'TrackingError'),
    ('smoke_tests', 'SmokeTests'),
]
for mod_name, desc in modules_import:
    try:
        importlib.import_module(mod_name)
        check(f'Import: {desc}', 'import', True)
    except Exception as e:
        check(f'Import: {desc}', 'import', False, str(e)[:80])

# ── 4. Key Metrics ──
print("\n[4] Metrics")
try:
    import pandas as pd
    hist = pd.read_csv(os.path.join(BASE, 'data', 'history.csv'), dtype={'代码': str})
    hist['日期'] = pd.to_datetime(hist['日期'])
    check('Metric: stock count', 'metric', hist['代码'].nunique() > 5000, f'{hist["代码"].nunique()} stocks')
    check('Metric: K-line rows', 'metric', len(hist) > 400000, f'{len(hist):,} rows')

    eval_path = os.path.join(BASE, 'results', 'honest_evaluation.md')
    if os.path.exists(eval_path):
        with open(eval_path, 'r', encoding='utf-8') as f:
            ev = f.read()
        check('Metric: backtest report', 'metric', '10日' in ev and '牛市' in ev)
    # Exit advisor report freshness
    exit_files = sorted(glob.glob(os.path.join(BASE, 'results', 'exit_advisor_*.md')), reverse=True)
    if exit_files:
        exit_mtime = datetime.fromtimestamp(os.path.getmtime(exit_files[0]))
        exit_age_h = (datetime.now() - exit_mtime).total_seconds() / 3600
        freshness_thresh = 72 if is_non_trading_day() else 24
        check('Metric: exit advisor', 'metric', exit_age_h < freshness_thresh, f'{exit_age_h:.1f}h old (threshold={freshness_thresh}h)')
    else:
        warn('Metric: exit advisor', 'metric', False, 'No report found')
except Exception as e:
    warn('Metric: analysis', 'metric', False, str(e)[:80])

# Sim account
sim_state = os.path.join(BASE, 'sim_results', 'account_state.json')
if os.path.exists(sim_state):
    with open(sim_state, 'r', encoding='utf-8') as f:
        st = json.load(f)
    check('Metric: sim equity', 'metric', st.get('equity', 0) > 0)
    pos_count = len(st.get('positions', []))
    warn('Metric: sim positions', 'metric', pos_count > 0, f'{pos_count} positions (fresh account OK)')

# Real trades
real_file = os.path.join(BASE, 'real_trades.csv')
if os.path.exists(real_file):
    import pandas as pd
    rt = pd.read_csv(real_file)
    real_count = len(rt[~rt['备注'].str.contains('示例数据', na=False)]) if '备注' in rt.columns else len(rt)
    check('Metric: real trades', 'metric', real_count > 0, f'{real_count} real trades')

# Newbie status
nbf = os.path.join(BASE, 'data', 'newbie_status.json')
if os.path.exists(nbf):
    with open(nbf, 'r', encoding='utf-8') as f:
        nb = json.load(f)
    check('Metric: protection phase', 'metric', nb['current_phase'] in ['observation', 'simulation', 'pre_live'],
          f'Phase: {nb["current_phase"]}, Day: {nb["day_number"]}')

# ── 5. Data Quality ──
print("\n[5] Data Quality")
try:
    stock_files = sorted(glob.glob(os.path.join(BASE, 'data', 'stock_*.csv')), reverse=True)
    if stock_files:
        sdf = pd.read_csv(stock_files[0], dtype={'代码': str})
        zero_price = (sdf['最新价'] <= 0).sum() if '最新价' in sdf.columns else 0
        zero_vol = (sdf['成交量'] == 0).sum() if '成交量' in sdf.columns else 0
        # strategy.py 已自动过滤停牌/零价股票，此处仅监控极端数据异常
        warn('Data: zero price stocks', 'data', zero_price <= 30, f'{zero_price} stocks (strategy.py filters these)')
        warn('Data: halted stocks (vol=0)', 'data', zero_vol <= 50, f'{zero_vol} stocks (strategy.py filters these)')

    if os.path.exists(os.path.join(BASE, 'data', 'history.csv')):
        hdf = pd.read_csv(os.path.join(BASE, 'data', 'history.csv'), dtype={'代码': str})
        if '收盘' in hdf.columns:
            null_close = hdf['收盘'].isna().sum()
            neg_close = (hdf['收盘'] <= 0).sum()
            warn('Data: history null close', 'data', null_close == 0, f'{null_close} rows')
            warn('Data: history negative close', 'data', neg_close == 0, f'{neg_close} rows')
except Exception as e:
    warn('Data: quality check', 'data', False, str(e)[:80])

# ── 6. External Connectivity ──
print("\n[6] External")
# Bark token (v7.5: 优先检查 secrets.json)
secrets_path = os.path.join(BASE, 'data', 'secrets.json')
if os.path.exists(secrets_path):
    try:
        with open(secrets_path, 'r', encoding='utf-8') as f:
            sec = json.load(f)
        check('External: Bark token in secrets', 'external', bool(sec.get('bark_token')))
    except Exception:
        check('External: Bark token in secrets', 'external', False, 'secrets.json parse error')
else:
    # 旧系统兼容：检查源码中是否还有硬编码
    with open(os.path.join(BASE, 'send_to_bark.py'), 'r', encoding='utf-8') as f:
        check('External: Bark token', 'external', 'C2910EED8E6540BEBFE994A01A107C58' not in f.read(),
              'Token still hardcoded in source')

# Scheduled tasks
import subprocess
# v8.5: 与实际部署的计划任务名保持一致（去重后保留 _v5 后缀的任务）
# 接受任一别名存在即通过——避免重命名/去重时 self-check 失配
TASK_ALIASES = {
    'Daily pipeline': ['QuantDailyPipeline_v5', 'QuantDailyPipeline'],
    'Weekly health': ['QuantWeeklyHealthCheck'],
}
for desc, aliases in TASK_ALIASES.items():
    found = False
    for task_name in aliases:
        try:
            r = subprocess.run(['schtasks', '/query', '/tn', task_name, '/fo', 'CSV'],
                              capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and task_name in r.stdout:
                found = True
                break
        except Exception:
            continue
    check(f'External: {desc} task', 'external', found)

# ── 7. Configuration ──
print("\n[7] Config")
risk_path = os.path.join(BASE, 'data', 'risk_config.json')
if os.path.exists(risk_path):
    with open(risk_path, 'r', encoding='utf-8') as f:
        risk = json.load(f)
    check('Config: stop_loss', 'config', 'stop_loss_pct' in risk)
    check('Config: position_mult', 'config', 'position_size_mult' in risk)

# v8: 流水线已迁移到 core/pipeline.py 注册表。检查注册表内容而非 .bat
try:
    from core.pipeline import PIPELINE_STEPS
    pipeline_scripts = ' '.join(s.get('script', '') for s in PIPELINE_STEPS.values())
    check('Config: pipeline steps', 'config', len(PIPELINE_STEPS) >= 20, f'{len(PIPELINE_STEPS)} steps')
    check('Config: cost_tracker in pipeline', 'config', 'cost_tracker' in pipeline_scripts)
    check('Config: newbie_protection in pipeline', 'config', 'newbie_protection' in pipeline_scripts)
    check('Config: evolve_daily in pipeline', 'config', 'evolve_daily_light' in pipeline_scripts)
    check('Config: data_loader in pipeline', 'config', 'data_loader' in pipeline_scripts)
    check('Config: portfolio_risk in pipeline', 'config', 'portfolio_risk' in pipeline_scripts)
    check('Config: walk_forward in pipeline', 'config', 'walk_forward' in pipeline_scripts)
    check('Config: monte_carlo in pipeline', 'config', 'monte_carlo' in pipeline_scripts)
    check('Config: strategy_arena in pipeline', 'config', 'strategy_arena' in pipeline_scripts)
except Exception as e:
    check('Config: pipeline registry', 'config', False, f'load failed: {e}')

# ── 7. Weekly trend comparison ──
prev = load_prev_health()
current_scores = {}
for c in results['checks']:
    cat = c['category']
    if cat not in current_scores:
        current_scores[cat] = {'total': 0, 'passed': 0}
    current_scores[cat]['total'] += 1
    if c['status'] == 'PASS':
        current_scores[cat]['passed'] += 1

# ── Generate Health Report ──
total = results['score']['total']
passed = results['score']['passed']
warn_n = results['score']['warn']
fail_n = results['score']['fail']
overall_pct = passed / total * 100 if total > 0 else 0

# Determine overall status
if fail_n == 0 and overall_pct >= 95:
    status_text = '正常'
    status_icon = '✅'
elif fail_n <= 2 and overall_pct >= 85:
    status_text = '警告'
    status_icon = '⚠️'
else:
    status_text = '异常'
    status_icon = '🚨'

today_str = datetime.now().strftime('%Y%m%d')
report = [
    f"# 系统健康检查报告 — {datetime.now().strftime('%Y-%m-%d')}",
    f"",
    f"> 检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"> 整体状态：{status_icon} **{status_text}** | 通过率：{passed}/{total} ({overall_pct:.0f}%)",
    f"> 版本：v{SYSTEM_VERSION}",
    f"",
    f"## 各维度得分",
    f"",
    f"| 维度 | 得分 | 状态 |",
    f"|------|------|------|",
]

for cat in ['file', 'data', 'import', 'metric', 'external', 'config']:
    if cat in current_scores:
        cs = current_scores[cat]
        pct = cs['passed'] / cs['total'] * 100 if cs['total'] > 0 else 0
        bar = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
        s = '✅' if pct >= 90 else ('⚠️' if pct >= 70 else '🚨')
        report.append(f"| {cat:12s} | {bar} {cs['passed']}/{cs['total']} ({pct:.0f}%) | {s} |")

report.extend(["", f"## 趋势对比"])

if prev and prev.get('scores'):
    report.extend([
        f"",
        f"| 维度 | 上周 ({prev['date']}) | 本周 | 变化 |",
        f"|------|---------------------|------|------|",
    ])
    for cat in ['file', 'data', 'import', 'metric', 'external', 'config']:
        prev_s = prev['scores'].get(cat, {'passed': 0, 'total': 1})
        curr_s = current_scores.get(cat, {'total': 0, 'passed': 0})
        prev_pct = prev_s['passed'] / max(1, prev_s['total']) * 100
        curr_pct = curr_s['passed'] / max(1, curr_s['total']) * 100
        diff = curr_pct - prev_pct
        arrow = '↗' if diff > 0 else ('↘' if diff < 0 else '→')
        flag = '🚨' if diff < -10 else ''
        report.append(f"| {cat:12s} | {prev_pct:.0f}% ({prev_s['passed']}/{prev_s['total']}) | {curr_pct:.0f}% ({curr_s['passed']}/{curr_s['total']}) | {arrow} {diff:+.0f}% {flag} |")
else:
    report.extend(["", "（无历史数据，首次运行。下周起将显示趋势对比。）"])

# Alerts section
alerts = [c for c in results['checks'] if c['status'] in ('FAIL', 'WARN')]
if alerts:
    report.extend(["", f"## 告警项 ({len(alerts)})", ""])
    for a in alerts:
        flag = '🚨' if a['status'] == 'FAIL' else '⚠️'
        report.append(f"- {flag} **{a['name']}** — {a['detail']}")

report.extend([
    f"",
    f"---",
    f"*报告由 _self_check.py v{SYSTEM_VERSION} 自动生成*",
    f"*下次检查：下周自动运行*",
])

report_path = os.path.join(BASE, 'reports', f'health_check_{today_str}.md')
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report))

# Save JSON（v8.5: 文件名跟随 SYSTEM_VERSION）
json_path = os.path.join(BASE, 'reports', f'system_self_check_v{SYSTEM_VERSION.replace(".", "")}.json')
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# Console summary
print(f"\n{'='*60}")
print(f"  TOTAL: {total} | PASS: {passed} | WARN: {warn_n} | FAIL: {fail_n}")
print(f"  SCORE: {passed}/{total} ({overall_pct:.0f}%) | Status: {status_text}")
print(f"  Report: {os.path.basename(report_path)}")
for cat, cs in sorted(current_scores.items()):
    pct = cs['passed'] / cs['total'] * 100 if cs['total'] > 0 else 0
    bar = '#' * int(pct / 10) + '-' * (10 - int(pct / 10))
    print(f"  {cat:12s} [{bar}] {cs['passed']}/{cs['total']} ({pct:.0f}%)")
print(f"{'='*60}")
