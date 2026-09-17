"""系统综合自检 + 健康报告生成（S2 函数化改造 2026-09-09：原 _self_check.py 迁入 ops/）。

入口 run_all()：import 零副作用（不再模块级 os.chdir / 不在导入期执行检查）。
产物不变：reports/health_check_YYYYMMDD.md + reports/system_self_check_v<版本>.json。
旧调用路径 _self_check.py 保留为兼容 shim。
"""
import os, sys, json, glob, importlib, re
from datetime import datetime, timedelta, date
import subprocess

_REPO_ROOT_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓根引导（本文件在 ops/ 下）
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from core.paths import DATA_DIR, REPO_ROOT, REPORTS_DIR, RESULTS_DIR, data_file
from core.secrets import get_secret, get_secret_list



results = None  # 由 run_all() 初始化（check/warn 以模块级全局读写）

def check(name, category, condition, detail=''):
    r = {'name': name, 'category': category, 'status': 'PASS' if condition else 'FAIL', 'detail': detail}
    results['checks'].append(r)
    results['score']['total'] += 1
    if condition:
        results['score']['passed'] += 1
    else:
        results['score']['fail'] += 1
def warn(name, category, condition, detail=''):
    r = {'name': name, 'category': category, 'status': 'WARN' if not condition else 'PASS', 'detail': detail}
    results['checks'].append(r)
    results['score']['total'] += 1
    if not condition:
        results['score']['warn'] += 1
    else:
        results['score']['passed'] += 1

def _scan_hardcoded_bark_token() -> bool:
    """扫描推送源码是否残留 32 位硬编码 token（S4CD-4/h912-09 提为公共路径；规则与名单与原 else 分支逐字一致）。"""
    hardcoded = False
    for rel in ('send_to_bark.py', 'bark_sender/push.py', 'bark_sender/config.py', 'bark_sender/channels.py'):
        try:
            with open(REPO_ROOT / rel, 'r', encoding='utf-8') as f:
                if re.search('["\'][0-9A-Fa-f]{32}["\']', f.read()):
                    hardcoded = True
                    break
        except Exception:
            pass
    return hardcoded

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
            if hasattr(v, 'date') and (not isinstance(v, date)):
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
    prev_files = sorted(glob.glob(str(REPORTS_DIR / 'health_check_*.md')), reverse=True)
    if len(prev_files) >= 2:
        prev_path = prev_files[1]
    elif len(prev_files) == 1:
        prev_path = prev_files[0]
    else:
        return None
    prev_date = os.path.basename(prev_path).replace('health_check_', '').replace('.md', '')
    with open(prev_path, 'r', encoding='utf-8') as f:
        content = f.read()
    import re
    scores = {}
    for m in re.finditer('\\|?\\s*(\\w+)\\s*\\|\\s*█+\\s*(\\d+)/(\\d+)', content):
        scores[m.group(1)] = {'passed': int(m.group(2)), 'total': int(m.group(3))}
    return {'date': prev_date, 'scores': scores}


def run_all():
    """执行全部自检项，返回 results（含 score 统计）；运行期 chdir(REPO_ROOT)，结束还原。"""
    global results
    results = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'checks': [], 'score': {'total': 0, 'passed': 0, 'warn': 0, 'fail': 0}}
    _old_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from core.config import SYSTEM_VERSION
        print('=' * 60)
        print(f"  v{SYSTEM_VERSION} Health Check @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print('=' * 60)
        print('\n[1] File Integrity')
        core_modules = ['strategy.py', 'multi_strategy.py', 'enhanced_backtest.py', 'fetch_minute_kline.py', 'position_sizer.py', 'sim_trade.py', 'strategy_feedback.py', 'broker_adapter.py', 'research_agent.py', 'integrate_knowledge.py', 'psychology_assistant.py', 'newbie_instruction_card.py', 'send_to_bark.py', 'fetch_stock_data.py', 'fetch_history.py', 'check_trading_day.py', 'sector_classifier.py', 'track_performance.py', 'evolve_strategy.py', 'external_research.py', 'data_loader.py', 'factor_analysis.py', 'portfolio_risk.py', 'premarket_sim.py', 'walk_forward.py', 'monte_carlo.py', 'strategy_arena.py']
        v75_new = ['cost_tracker.py', 'newbie_protection.py', 'evolve_daily_light.py', 'log_real_trade.py', 'auto_heal.py', 'trade_analyzer.py', 'exit_advisor.py']
        v85_new = ['portfolio_manager.py', 'data_validator.py', 'archive_old_data.py', 'behavior_log.py', 'monthly_behavior_report.py', 'benchmark_comparison.py', 'tracking_error_report.py', 'smoke_tests.py']
        v86_new = ['fetch_etf_data.py']
        v87_new = ['digest.py', 'decision_replay.py', 'llm_analyst.py', 'core/llm.py', 'bark_sender/channels.py', 'utils/trading_calendar.py']
        config_files = ['daily_pipeline.bat', 'morning_pipeline.bat', 'weekly_health_check.bat', 'run.bat', 'start-bg.bat', 'launcher.pyw', 'app.py', 'CLAUDE.md', 'AGENTS.md', 'requirements.txt', 'core/config.py', 'real_trades.csv', 'learning/first_week_guide.md', 'tests/conftest.py']
        sub_packages = ['bark_sender/__init__.py', 'bark_sender/config.py', 'bark_sender/parsers.py', 'bark_sender/formatters.py', 'bark_sender/rebalancer.py', 'bark_sender/builders.py', 'bark_sender/push.py', 'app/__init__.py', 'app/styles.py', 'app/sidebar.py', 'app/loaders.py', 'app/pages.py']
        for mod in core_modules + v75_new + v85_new + v86_new + v87_new + config_files + sub_packages:
            exists = (REPO_ROOT / mod).exists()
            check(f'File: {mod}', 'file', exists)
        print('\n[2] Data')
        data_checks = {'history.csv': 'K-line history', 'hs300_index.csv': 'HS300 index', 'risk_config.json': 'Risk config', 'good_trades.json': 'Cold-start good', 'bad_trades.json': 'Cold-start bad', 'newbie_status.json': 'Newbie protection', 'evolve_daily_state.json': 'Daily evolution', 'pick_performance.json': 'Pick performance', 'factor_weights.json': 'Factor weights', 'arena_config.json': 'Arena config', 'portfolio_state.json': 'Portfolio state', 'behavior_log.csv': 'Behavior log', 'strategy_forward_returns.csv': 'Forward returns', 'regime_state.json': 'Regime state', 'system_config.json': 'System config', 'etf_watchlist.json': 'ETF watchlist', 'alpha_gate_state.json': 'Alpha gate state', 'strategy_weights.json': 'Strategy weights', 'cost_log.jsonl': 'Cost log'}
        for fname, desc in data_checks.items():
            path = data_file(fname)
            ok = os.path.exists(path) and os.path.getsize(path) > 0
            check(f'Data: {desc}', 'data', ok)
        try:
            import pandas as pd
            stock_files = sorted(glob.glob(str(DATA_DIR / 'stock_*.csv')), reverse=True)
            if stock_files:
                mtime = datetime.fromtimestamp(os.path.getmtime(stock_files[0]))
                age_h = (datetime.now() - mtime).total_seconds() / 3600
                freshness_thresh = 72 if is_non_trading_day() else 24
                check('Data: stock freshness', 'data', age_h < freshness_thresh, f'{age_h:.1f}h old (threshold={freshness_thresh}h)')
            hist_path = data_file('history.csv')
            if os.path.exists(hist_path):
                hist = pd.read_csv(hist_path, dtype={'代码': str})
                hist['日期'] = pd.to_datetime(hist['日期'])
                latest = hist['日期'].max()
                days_behind = _trading_days_behind(latest, today=date.today(), data_dir=DATA_DIR)
                check('Data: K-line freshness', 'data', days_behind <= 2, f"{latest.strftime('%Y-%m-%d')}, {days_behind} trading day(s) behind")
            try:
                from data_validator import check_stock_csv as _v_stock, check_history_csv as _v_hist
                for label, dv_result in [('Data: stock quality', _v_stock()), ('Data: history lag', _v_hist())]:
                    status = dv_result.get('status', 'FAIL')
                    detail = dv_result.get('reason', '') or ' '.join((f'{k}={v}' for k, v in dv_result.get('metrics', {}).items()))
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
        minute_dir = DATA_DIR / 'minute_kline'
        if os.path.exists(minute_dir):
            mf = [f for f in os.listdir(minute_dir) if f.endswith('.csv')]
            check('Data: minute K-line', 'data', len(mf) >= 20, f'{len(mf)} stocks')
        print('\n[3] Imports')
        modules_import = [('strategy', 'Trend Following'), ('enhanced_backtest', 'Backtest'), ('fetch_minute_kline', 'Minute K-line'), ('position_sizer', 'Position'), ('sector_classifier', 'Sector'), ('cost_tracker', 'Cost'), ('newbie_protection', 'Protection'), ('evolve_daily_light', 'DailyEvolve'), ('strategy_feedback', 'Feedback'), ('newbie_instruction_card', 'NewbieCard'), ('psychology_assistant', 'Psychology'), ('send_to_bark', 'Bark'), ('sim_trade', 'SimTrade'), ('broker_adapter', 'Broker'), ('auto_heal', 'AutoHeal'), ('trade_analyzer', 'TradeAnalyzer'), ('exit_advisor', 'ExitAdvisor'), ('data_loader', 'DataLoader'), ('factor_analysis', 'FactorAnalysis'), ('portfolio_risk', 'PortfolioRisk'), ('premarket_sim', 'PremarketSim'), ('walk_forward', 'WalkForward'), ('monte_carlo', 'MonteCarlo'), ('strategy_arena', 'StrategyArena'), ('portfolio_manager', 'PortfolioMgr'), ('data_validator', 'DataValidator'), ('archive_old_data', 'Archive'), ('behavior_log', 'BehaviorLog'), ('monthly_behavior_report', 'MonthlyBehavior'), ('benchmark_comparison', 'Benchmark'), ('tracking_error_report', 'TrackingError'), ('smoke_tests', 'SmokeTests'), ('core.llm', 'LLM'), ('digest', 'Digest'), ('decision_replay', 'Replay'), ('llm_analyst', 'LLMAnalyst'), ('bark_sender.channels', 'Channels')]
        for mod_name, desc in modules_import:
            try:
                importlib.import_module(mod_name)
                check(f'Import: {desc}', 'import', True)
            except Exception as e:
                check(f'Import: {desc}', 'import', False, str(e)[:80])
        print('\n[4] Metrics')
        try:
            import pandas as pd
            hist = pd.read_csv(data_file('history.csv'), dtype={'代码': str})
            hist['日期'] = pd.to_datetime(hist['日期'])
            check('Metric: stock count', 'metric', hist['代码'].nunique() > 5000, f"{hist['代码'].nunique()} stocks")
            check('Metric: K-line rows', 'metric', len(hist) > 400000, f'{len(hist):,} rows')
            eval_path = RESULTS_DIR / 'honest_evaluation.md'
            if os.path.exists(eval_path):
                with open(eval_path, 'r', encoding='utf-8') as f:
                    ev = f.read()
                check('Metric: backtest report', 'metric', '10日' in ev and '牛市' in ev)
            exit_files = sorted(glob.glob(str(RESULTS_DIR / 'exit_advisor_*.md')), reverse=True)
            if exit_files:
                exit_mtime = datetime.fromtimestamp(os.path.getmtime(exit_files[0]))
                exit_age_h = (datetime.now() - exit_mtime).total_seconds() / 3600
                freshness_thresh = 72 if is_non_trading_day() else 24
                check('Metric: exit advisor', 'metric', exit_age_h < freshness_thresh, f'{exit_age_h:.1f}h old (threshold={freshness_thresh}h)')
            else:
                warn('Metric: exit advisor', 'metric', False, 'No report found')
        except Exception as e:
            warn('Metric: analysis', 'metric', False, str(e)[:80])
        sim_state = REPO_ROOT / 'sim_results' / 'account_state.json'
        if os.path.exists(sim_state):
            try:
                with open(sim_state, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                check('Metric: sim equity', 'metric', st.get('equity', 0) > 0)
                pos_count = len(st.get('positions', []))
                warn('Metric: sim positions', 'metric', pos_count > 0, f'{pos_count} positions (fresh account OK)')
            except Exception as e:
                warn('Metric: sim account', 'metric', False, f'account_state.json 读取失败: {e}')
        real_file = REPO_ROOT / 'real_trades.csv'
        if os.path.exists(real_file):
            try:
                import pandas as pd
                rt = pd.read_csv(real_file)
                real_count = len(rt[~rt['备注'].str.contains('示例数据', na=False)]) if '备注' in rt.columns else len(rt)
                check('Metric: real trades', 'metric', real_count > 0, f'{real_count} real trades')
            except Exception as e:
                warn('Metric: real trades', 'metric', False, f'real_trades.csv 读取失败: {e}')
        nbf = data_file('newbie_status.json')
        if os.path.exists(nbf):
            try:
                with open(nbf, 'r', encoding='utf-8') as f:
                    nb = json.load(f)
                check('Metric: protection phase', 'metric', nb['current_phase'] in ['observation', 'simulation', 'pre_live'], f"Phase: {nb['current_phase']}, Day: {nb['day_number']}")
            except Exception as e:
                warn('Metric: protection phase', 'metric', False, f'newbie_status.json 读取失败: {e}')
        print('\n[5] Data Quality')
        try:
            stock_files = sorted(glob.glob(str(DATA_DIR / 'stock_*.csv')), reverse=True)
            if stock_files:
                sdf = pd.read_csv(stock_files[0], dtype={'代码': str})
                zero_price = (sdf['最新价'] <= 0).sum() if '最新价' in sdf.columns else 0
                zero_vol = (sdf['成交量'] == 0).sum() if '成交量' in sdf.columns else 0
                warn('Data: zero price stocks', 'data', zero_price <= 30, f'{zero_price} stocks (strategy.py filters these)')
                warn('Data: halted stocks (vol=0)', 'data', zero_vol <= 50, f'{zero_vol} stocks (strategy.py filters these)')
            if data_file('history.csv').exists():
                hdf = pd.read_csv(data_file('history.csv'), dtype={'代码': str})
                if '收盘' in hdf.columns:
                    null_close = hdf['收盘'].isna().sum()
                    neg_close = (hdf['收盘'] <= 0).sum()
                    warn('Data: history null close', 'data', null_close == 0, f'{null_close} rows')
                    warn('Data: history negative close', 'data', neg_close == 0, f'{neg_close} rows')
        except Exception as e:
            warn('Data: quality check', 'data', False, str(e)[:80])
        print('\n[6] External')
        if bool(get_secret('BARK_KEY')) or bool(get_secret_list('BARK_TOKENS')):
            check('External: Bark token in secrets', 'external', True)
        elif not data_file('secrets.json').exists():
            pass  # S4CD-4(h912-09): 原扫描分支提为下方公共路径，结果统一出口输出
        else:
            check('External: Bark token in secrets', 'external', False, 'secrets.json parse error or no token')
        # S4CD-4(h912-09): 硬编码 token 扫描提到公共路径——无论走哪个分支都执行（扫描规则与名单与原分支一字未改）
        hardcoded = _scan_hardcoded_bark_token()
        check('External: Bark token', 'external', not hardcoded, '推送源码中仍存在 32 位硬编码 token')
        TASK_ALIASES = {'Daily pipeline': ['QuantDailyPipeline_v5', 'QuantDailyPipeline'], 'Weekly health': ['QuantWeeklyHealthCheck']}
        for desc, aliases in TASK_ALIASES.items():
            found = False
            for task_name in aliases:
                try:
                    # n916d-16 同族解码防御：schtasks 输出为 GBK，UTF-8 模式下 text=True 读线程会炸
                    r = subprocess.run(['schtasks', '/query', '/tn', task_name, '/fo', 'CSV'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
                    if r.returncode == 0 and task_name in r.stdout:
                        found = True
                        break
                except Exception:
                    continue
            check(f'External: {desc} task', 'external', found)
        _morning_found = False
        try:
            _r = subprocess.run(['schtasks', '/query', '/tn', 'QuantMorningPipeline', '/fo', 'CSV'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
            _morning_found = _r.returncode == 0 and 'QuantMorningPipeline' in _r.stdout
        except Exception:
            pass
        warn('External: morning pipeline task', 'external', _morning_found, 'QuantMorningPipeline 未注册（09:15 盘前推送不会自动运行）。注册命令：schtasks /create /tn QuantMorningPipeline /tr "<项目路径>\\morning_pipeline.bat" /sc DAILY /st 09:15 /f')
        print('\n[7] Config')
        risk_path = data_file('risk_config.json')
        if os.path.exists(risk_path):
            with open(risk_path, 'r', encoding='utf-8') as f:
                risk = json.load(f)
            check('Config: stop_loss', 'config', 'stop_loss_pct' in risk)
            check('Config: position_mult', 'config', 'position_size_mult' in risk)
        try:
            from core.pipeline import PIPELINE_STEPS
            pipeline_scripts = ' '.join((s.get('script', '') for s in PIPELINE_STEPS.values()))
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
        prev = load_prev_health()
        current_scores = {}
        for c in results['checks']:
            cat = c['category']
            if cat not in current_scores:
                current_scores[cat] = {'total': 0, 'passed': 0}
            current_scores[cat]['total'] += 1
            if c['status'] == 'PASS':
                current_scores[cat]['passed'] += 1
        total = results['score']['total']
        passed = results['score']['passed']
        warn_n = results['score']['warn']
        fail_n = results['score']['fail']
        overall_pct = passed / total * 100 if total > 0 else 0
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
        report = [f"# 系统健康检查报告 — {datetime.now().strftime('%Y-%m-%d')}", f'', f"> 检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f'> 整体状态：{status_icon} **{status_text}** | 通过率：{passed}/{total} ({overall_pct:.0f}%)', f'> 版本：v{SYSTEM_VERSION}', f'', f'## 各维度得分', f'', f'| 维度 | 得分 | 状态 |', f'|------|------|------|']
        for cat in ['file', 'data', 'import', 'metric', 'external', 'config']:
            if cat in current_scores:
                cs = current_scores[cat]
                pct = cs['passed'] / cs['total'] * 100 if cs['total'] > 0 else 0
                bar = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
                s = '✅' if pct >= 90 else '⚠️' if pct >= 70 else '🚨'
                report.append(f"| {cat:12s} | {bar} {cs['passed']}/{cs['total']} ({pct:.0f}%) | {s} |")
        report.extend(['', f'## 趋势对比'])
        if prev and prev.get('scores'):
            report.extend([f'', f"| 维度 | 上周 ({prev['date']}) | 本周 | 变化 |", f'|------|---------------------|------|------|'])
            for cat in ['file', 'data', 'import', 'metric', 'external', 'config']:
                prev_s = prev['scores'].get(cat, {'passed': 0, 'total': 1})
                curr_s = current_scores.get(cat, {'total': 0, 'passed': 0})
                prev_pct = prev_s['passed'] / max(1, prev_s['total']) * 100
                curr_pct = curr_s['passed'] / max(1, curr_s['total']) * 100
                diff = curr_pct - prev_pct
                arrow = '↗' if diff > 0 else '↘' if diff < 0 else '→'
                flag = '🚨' if diff < -10 else ''
                report.append(f"| {cat:12s} | {prev_pct:.0f}% ({prev_s['passed']}/{prev_s['total']}) | {curr_pct:.0f}% ({curr_s['passed']}/{curr_s['total']}) | {arrow} {diff:+.0f}% {flag} |")
        else:
            report.extend(['', '（无历史数据，首次运行。下周起将显示趋势对比。）'])
        alerts = [c for c in results['checks'] if c['status'] in ('FAIL', 'WARN')]
        if alerts:
            report.extend(['', f'## 告警项 ({len(alerts)})', ''])
            for a in alerts:
                flag = '🚨' if a['status'] == 'FAIL' else '⚠️'
                report.append(f"- {flag} **{a['name']}** — {a['detail']}")
        report.extend([f'', f'---', f'*报告由 _self_check.py v{SYSTEM_VERSION} 自动生成*', f'*下次检查：下周自动运行*'])
        report_path = REPORTS_DIR / f'health_check_{today_str}.md'
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
        json_path = REPORTS_DIR / f"system_self_check_v{SYSTEM_VERSION.replace('.', '')}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n{'=' * 60}")
        print(f'  TOTAL: {total} | PASS: {passed} | WARN: {warn_n} | FAIL: {fail_n}')
        print(f'  SCORE: {passed}/{total} ({overall_pct:.0f}%) | Status: {status_text}')
        print(f'  Report: {os.path.basename(report_path)}')
        for cat, cs in sorted(current_scores.items()):
            pct = cs['passed'] / cs['total'] * 100 if cs['total'] > 0 else 0
            bar = '#' * int(pct / 10) + '-' * (10 - int(pct / 10))
            print(f"  {cat:12s} [{bar}] {cs['passed']}/{cs['total']} ({pct:.0f}%)")
        print(f"{'=' * 60}")
    finally:
        os.chdir(_old_cwd)
    return results


if __name__ == '__main__':
    run_all()
