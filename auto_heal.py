"""
自动修复引擎（版本号从 SYSTEM_VERSION 单一事实源拉取）
读取 _self_check.py 的 JSON 输出，对可修复项自动修复，记录全过程。
"""
import os, sys, json, subprocess, time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

# v8.5: 单一版本号源
from core.config import SYSTEM_VERSION, get as cfg_get

HEAL_LOG = []
FIX_COUNT = {'attempted': 0, 'fixed': 0, 'failed': 0, 'skipped': 0}

def _flatten(text, max_len=200):
    """子进程输出折叠成单行——避免换行污染 markdown 代码块缩进，并限长。"""
    if not text:
        return ''
    # 保留最后一条非空行（更可能是真正的状态/错误信息）
    lines = [l.strip() for l in str(text).splitlines() if l.strip()]
    if not lines:
        return ''
    summary = lines[-1]
    if len(summary) > max_len:
        summary = summary[:max_len] + '…'
    return summary

def log(level, msg):
    ts = datetime.now().strftime('%H:%M:%S')
    # 防御：所有 log 输出都强制折叠为单行——任何 caller 都不会污染 markdown
    msg = _flatten(msg, max_len=300)
    HEAL_LOG.append(f"[{ts}] [{level}] {msg}")
    print(f"  [{level}] {msg}")

def recreate_default_json(path, defaults):
    """创建默认 JSON 配置文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2)
    return os.path.exists(path)

def run_script(script_name, timeout=120):
    """运行项目内的 Python 脚本，返回 (success, output)。shell=False 避免注入风险。"""
    script_path = os.path.join(BASE, script_name)
    if not os.path.exists(script_path):
        return False, f"Script not found: {script_path}"
    try:
        r = subprocess.run(
            [sys.executable, script_path],
            cwd=BASE, capture_output=True, text=True, timeout=timeout
        )
        # 折叠为单行——防止子进程的换行/进度条污染 heal_log
        return r.returncode == 0, _flatten(r.stdout + r.stderr, max_len=200)
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, _flatten(str(e), max_len=200)

def fix_missing_risk_config():
    """重建 risk_config.json 默认值，必须与 core.config sim.* 单一真相源一致。

    2026-08-24：旧默认 take_profit_pct=0.3 / max_hold_days=30 与
    system_config（0.20 / 10）冲突；且缺少 alert_only=True 会让 sim_trade
    在重建后意外启用反馈循环对 stop/take 的覆盖。
    """
    return recreate_default_json(
        os.path.join(BASE, 'data', 'risk_config.json'),
        {
            "stop_loss_pct": cfg_get('sim.stop_loss_pct', -0.08),
            "take_profit_pct": cfg_get('sim.take_profit_pct', 0.20),
            "max_hold_days": cfg_get('sim.max_hold_days', 10),
            "position_size_mult": 1.0,
            "alert_only": True,
            "updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    )

def fix_missing_newbie_status():
    today = datetime.now().strftime('%Y-%m-%d')
    return recreate_default_json(
        os.path.join(BASE, 'data', 'newbie_status.json'),
        {"current_phase": "observation", "day_number": 1, "start_date": today,
         "trade_count": 0, "win_count": 0, "total_pnl": 0.0,
         "phase_transitions": [], "last_updated": today}
    )

def fix_missing_good_trades():
    return recreate_default_json(
        os.path.join(BASE, 'data', 'good_trades.json'),
        {"version": "1.0", "description": "Cold-start good trade patterns",
         "trades": [], "last_updated": datetime.now().strftime('%Y-%m-%d')}
    )

def fix_missing_bad_trades():
    return recreate_default_json(
        os.path.join(BASE, 'data', 'bad_trades.json'),
        {"version": "1.0", "description": "Cold-start bad trade patterns",
         "trades": [], "last_updated": datetime.now().strftime('%Y-%m-%d')}
    )

def fix_missing_evolve_state():
    return recreate_default_json(
        os.path.join(BASE, 'data', 'evolve_daily_state.json'),
        {"version": "7.5", "generation": 1, "rsi_adj": 0, "ma_adj": 0, "pos_adj": 0,
         "history": [], "last_updated": datetime.now().strftime('%Y-%m-%d')}
    )

def fix_scheduled_task(task_name, bat_path, desc):
    """重建 Windows 计划任务"""
    r = subprocess.run(['schtasks', '/query', '/tn', task_name, '/fo', 'CSV'],
                      capture_output=True, text=True, timeout=10)
    if task_name in r.stdout:
        log('INFO', f'Scheduled task already exists: {task_name}')
        return True

    if not os.path.exists(bat_path):
        log('WARN', f'Batch file missing: {bat_path}, cannot create task')
        return False

    if 'Daily' in task_name:
        cmd = f'schtasks /create /tn {task_name} /tr "{bat_path}" /sc DAILY /st 15:37 /f'
    else:
        cmd = f'schtasks /create /tn {task_name} /tr "{bat_path}" /sc WEEKLY /d SUN /st 10:00 /f'

    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    success = r.returncode == 0
    if not success:
        log('WARN', f'schtasks create failed: {r.stderr[:200]}')
    return success


# 修复策略映射：check_name → (fix_function, description)
FIX_MAP = {
    'Data: K-line history':            ('fetch_history', 'Re-fetch all history K-line data'),
    'Data: Risk config':               ('recreate_risk_config', 'Recreate risk_config.json with defaults'),
    'Data: Cold-start good':           ('recreate_good_trades', 'Recreate good_trades.json template'),
    'Data: Cold-start bad':            ('recreate_bad_trades', 'Recreate bad_trades.json template'),
    'Data: Newbie protection':         ('recreate_newbie_status', 'Recreate newbie_status.json (day 1)'),
    'Data: Daily evolution':           ('recreate_evolve_state', 'Recreate evolve_daily_state.json'),
    'Data: stock freshness':           ('re_fetch_stock', 'Re-fetch today stock data'),
    'Data: K-line freshness':          ('fetch_history', 'Re-fetch history to latest date'),
    'Data: minute K-line':             ('re_fetch_minute', 'Re-fetch minute K-line data'),
    'Metric: stock count':             ('re_fetch_all', 'Re-fetch stock + history data'),
    'Metric: K-line rows':             ('fetch_history', 'Re-fetch history K-line data'),
    'Metric: backtest report':         ('re_backtest', 'Re-run honest backtest'),
    'Metric: sim equity':              ('re_sim', 'Re-run sim trade update'),
    'Metric: sim positions':           ('re_strategy_sim', 'Re-run strategy + sim trade'),
    'Metric: real trades':             ('warn_real_trades', 'Remind user to log real trades'),
    'Metric: protection phase':        ('recreate_newbie_status', 'Recreate newbie status'),
    'External: Daily pipeline task':   ('recreate_daily_task', 'Recreate daily scheduled task'),
    'External: Weekly health task':    ('recreate_weekly_task', 'Recreate weekly scheduled task'),
    'Config: stop_loss':               ('recreate_risk_config', 'Recreate risk config with defaults'),
    'Config: position_mult':           ('recreate_risk_config', 'Recreate risk config with defaults'),
}

# 不可自动修复的项——只记录，不操作
SKIP_CHECKS = {
    'External: Bark token',   # 需要用户手动提供token
    'Config: pipeline steps', 'Config: cost_tracker in pipeline',
    'Config: newbie_protection in pipeline', 'Config: evolve_daily in pipeline',
}
SKIP_PREFIXES = ['File:', 'Import:']  # 代码文件/导入问题太复杂，不自动修


def _validate_fix_map() -> None:
    """v8.5: 启动时校验 FIX_MAP 里所有策略名都被 dispatcher 注册——防止未来再出现
    'Unknown repair strategy' 默默吃掉错误。"""
    KNOWN_STRATEGIES = {
        'fetch_history', 're_fetch_stock', 're_fetch_all', 're_fetch_minute',
        're_backtest', 're_sim', 're_strategy_sim',
        'recreate_risk_config', 'recreate_newbie_status',
        'recreate_good_trades', 'recreate_bad_trades', 'recreate_evolve_state',
        'recreate_daily_task', 'recreate_weekly_task',
        'warn_real_trades',
    }
    declared = {strategy for strategy, _desc in FIX_MAP.values()}
    missing = declared - KNOWN_STRATEGIES
    if missing:
        raise RuntimeError(
            f'auto_heal.py FIX_MAP 中存在 dispatcher 未注册的策略名：{sorted(missing)}。'
            f'修复方法：要么在 execute_fix() 中加 elif 分支，要么改 FIX_MAP 用已有名字。'
        )


# 启动时立即校验
_validate_fix_map()


def can_fix(check_name):
    if check_name in SKIP_CHECKS:
        return False
    for prefix in SKIP_PREFIXES:
        if check_name.startswith(prefix):
            return False
    return check_name in FIX_MAP


def execute_fix(check_name):
    """执行修复，返回 (success, message)"""
    strategy, desc = FIX_MAP[check_name]
    log('ACTION', desc)

    if strategy == 'fetch_history':
        ok, out = run_script('fetch_history.py', timeout=180)
        return ok, out[-200:] if not ok else 'OK'

    elif strategy == 're_fetch_stock':
        ok, out = run_script('fetch_stock_data.py', timeout=120)
        return ok, out[-200:] if not ok else 'OK'

    elif strategy == 're_fetch_all':
        ok1, out1 = run_script('fetch_stock_data.py', timeout=120)
        ok2, out2 = run_script('fetch_history.py', timeout=180)
        return ok1 and ok2, _flatten(f"{out1} | {out2}", max_len=200)

    elif strategy == 're_fetch_minute':
        ok, out = run_script('fetch_minute_kline.py', timeout=120)
        return ok, out[-200:] if not ok else 'OK'

    elif strategy == 're_backtest':
        ok, out = run_script('enhanced_backtest.py', timeout=120)
        return ok, out[-200:] if not ok else 'OK'

    elif strategy == 're_sim':
        ok, out = run_script('sim_trade.py', timeout=60)
        return ok, out[-200:] if not ok else 'OK'

    elif strategy == 're_strategy_sim':
        ok1, out1 = run_script('strategy.py', timeout=120)
        ok2, out2 = run_script('sim_trade.py', timeout=60)
        return ok1 and ok2, _flatten(f"{out1} | {out2}", max_len=200)

    elif strategy == 'recreate_risk_config':
        ok = fix_missing_risk_config()
        return ok, 'risk_config.json recreated' if ok else 'Failed'

    elif strategy == 'recreate_newbie_status':
        ok = fix_missing_newbie_status()
        return ok, 'newbie_status.json recreated' if ok else 'Failed'

    elif strategy == 'recreate_good_trades':
        ok = fix_missing_good_trades()
        return ok, 'good_trades.json recreated' if ok else 'Failed'

    elif strategy == 'recreate_bad_trades':
        ok = fix_missing_bad_trades()
        return ok, 'bad_trades.json recreated' if ok else 'Failed'

    elif strategy == 'recreate_evolve_state':
        ok = fix_missing_evolve_state()
        return ok, 'evolve_daily_state.json recreated' if ok else 'Failed'

    elif strategy == 'recreate_daily_task':
        bat = os.path.join(BASE, 'daily_pipeline.bat')
        # v8.5: 与 _self_check.py TASK_ALIASES 保持一致——重建时用 _v5 后缀名
        ok = fix_scheduled_task('QuantDailyPipeline_v5', bat, 'Daily quant pipeline')
        return ok, 'Daily task recreated' if ok else 'Failed to recreate daily task'

    elif strategy == 'recreate_weekly_task':
        bat = os.path.join(BASE, 'weekly_health_check.bat')
        ok = fix_scheduled_task('QuantWeeklyHealthCheck', bat, 'Weekly health check')
        return ok, 'Weekly task recreated' if ok else 'Failed to recreate weekly task'

    elif strategy == 'warn_real_trades':
        log('INFO', 'Real trade count low — user needs to log trades manually')
        return True, 'Cannot auto-fix: user must log trades in dashboard or CSV'

    else:
        return False, f'Unknown repair strategy: {strategy}'


def run_heal(json_path=None):
    """主入口：加载自检结果 → 逐项修复 → 输出修复报告"""
    if json_path is None:
        # v8.5: 文件名跟随 SYSTEM_VERSION（与 _self_check.py 保持一致）
        version_tag = SYSTEM_VERSION.replace('.', '')
        json_path = os.path.join(BASE, 'reports', f'system_self_check_v{version_tag}.json')

    print(f"\n{'='*60}")
    print(f"  Auto-Heal Engine v{SYSTEM_VERSION} @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 1. 先运行自检（如果没有 JSON 文件）
    if not os.path.exists(json_path):
        log('INFO', 'No self-check JSON found, running _self_check.py...')
        run_script(f'python "{BASE}/_self_check.py"', timeout=60)
        time.sleep(1)

    # 2. 加载自检结果
    if not os.path.exists(json_path):
        log('FATAL', 'Self-check JSON still missing, cannot heal')
        return 1

    with open(json_path, 'r', encoding='utf-8') as f:
        report = json.load(f)

    checks = report.get('checks', [])
    failures = [c for c in checks if c['status'] in ('FAIL', 'WARN')]

    if not failures:
        log('OK', f'All {len(checks)} checks passed. Nothing to heal.')
        return 0

    log('INFO', f'Found {len(failures)} issues ({sum(1 for c in failures if c["status"]=="FAIL")} FAIL, {sum(1 for c in failures if c["status"]=="WARN")} WARN)')

    # 3. 逐项修复
    print(f"\n  --- Repair Phase ---")
    for item in failures:
        name = item['name']
        status = item['status']
        detail = item.get('detail', '')

        print(f"\n  [{status}] {name}")
        if detail:
            print(f"         Detail: {detail}")

        if not can_fix(name):
            FIX_COUNT['skipped'] += 1
            log('SKIP', f'{name} — not auto-fixable (needs manual intervention)')
            HEAL_LOG.append(f"         Reason: code file, import, or config requiring manual edit")
            continue

        FIX_COUNT['attempted'] += 1
        success, msg = execute_fix(name)

        if success:
            FIX_COUNT['fixed'] += 1
            log('FIXED', f'{name} → {msg[:120]}')
        else:
            FIX_COUNT['failed'] += 1
            log('FAIL', f'{name} → {msg[:120]}')

    # 4. 修复后重新自检
    print(f"\n  --- Post-Repair Verification ---")
    run_script(f'python "{BASE}/_self_check.py"', timeout=60)
    time.sleep(1)

    # 5. 读取修复后结果
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            new_report = json.load(f)
        new_failures = [c for c in new_report.get('checks', []) if c['status'] in ('FAIL', 'WARN')]
        remaining = len(new_failures)
    else:
        remaining = 'unknown'

    # 6. 生成修复日志
    today_str = datetime.now().strftime('%Y%m%d')
    heal_report_path = os.path.join(BASE, 'reports', f'heal_log_{today_str}.md')

    lines = [
        f"# 自动修复日志 — {datetime.now().strftime('%Y-%m-%d')}",
        f"",
        f"> 触发时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 发现问题：{len(failures)} 项",
        f"> 尝试修复：{FIX_COUNT['attempted']} 项",
        f"> 修复成功：{FIX_COUNT['fixed']} 项",
        f"> 修复失败：{FIX_COUNT['failed']} 项",
        f"> 跳过（需人工）：{FIX_COUNT['skipped']} 项",
        f"> 修复后剩余问题：{remaining} 项",
        f"",
        f"## 详细日志",
        f"",
    ]
    lines.extend([f"    {l}" for l in HEAL_LOG])

    if FIX_COUNT['skipped'] > 0:
        lines.extend(["", "## 需人工处理", ""])
        for item in failures:
            if not can_fix(item['name']):
                lines.append(f"- {item['status']} **{item['name']}**: {item.get('detail', 'N/A')}")

    lines.extend(["", "---", f"*报告由 auto_heal.py v{SYSTEM_VERSION} 自动生成*"])

    with open(heal_report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\n{'='*60}")
    print(f"  HEAL SUMMARY: {FIX_COUNT['fixed']} fixed / {FIX_COUNT['attempted']} attempted")
    print(f"  Skipped: {FIX_COUNT['skipped']} | Remaining: {remaining}")
    print(f"  Log: reports/heal_log_{today_str}.md")
    print(f"{'='*60}")

    return 0 if FIX_COUNT['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(run_heal())
