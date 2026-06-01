"""
流水线注册表（插件式 DAG，版本号从 SYSTEM_VERSION 单一事实源拉取）
将 v7.6 的 24 步硬编码 .bat 改为配置驱动的步骤注册表。

设计原则：
- 每个步骤是 PIPELINE_STEPS 中的一个条目，包含 tiers / schedule / 调用方式
- 当前 SYSTEM_TIER 决定哪些步骤参与运行；不在白名单的步骤"休眠"
- 步骤的 .py 脚本本身物理保留，且仍可手动 python xxx.py 执行（受各自 tier gate 约束）
- 升级时只需改 QUANT_TIER 环境变量或 data/system_config.json 的 tier.level
"""
import os
import sys
import time
import subprocess
from datetime import datetime

from .config import SYSTEM_TIER, SystemTier, SYSTEM_VERSION


# ============================================================
# 步骤注册表（核心数据结构）
# ============================================================
# 每条记录字段：
#   script        - 相对于项目根目录的 .py 文件名
#   tiers         - 哪些 tier 自动包含此步骤
#   schedule      - daily | monday/tuesday/.../friday | month-end | weekday
#   args          - 传给脚本的额外命令行参数
#   fatal_on_fail - True 表示失败立即终止流水线，False 仅警告继续
#   retry         - 重试次数，默认 1
#   retry_wait    - 重试间隔秒数，默认 0
#   if_file_exists- 仅当指定文件存在时才运行（相对项目根）
#   always_on     - 标记为始终启用的核心功能（用于自检与提示，运行决策仍以 tiers 为准）
#   label         - 健康面板显示用的中文标题
#   unlock_hint   - 当 tier 不满足时，向用户显示的解锁条件
PIPELINE_STEPS = {
    "check_trading_day":   {"script": "check_trading_day.py",     "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "fatal_on_fail": True,  "label": "交易日检测",        "unlock_hint": "始终启用"},
    "fetch_quote":         {"script": "fetch_stock_data.py",      "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "fatal_on_fail": True, "retry": 3, "retry_wait": 60, "label": "实时行情获取",      "unlock_hint": "始终启用"},
    "fetch_etf":           {"script": "fetch_etf_data.py",        "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "ETF 行情获取",      "unlock_hint": "始终启用（v8.6 新增）"},
    "update_history":      {"script": "fetch_history.py",         "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "fatal_on_fail": True,  "label": "历史K线更新",       "unlock_hint": "始终启用"},
    "fetch_index":         {"script": "fetch_index.py",           "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "retry": 2, "retry_wait": 30, "label": "基准指数刷新",      "unlock_hint": "始终启用（v8.7：全档每日刷新沪深300基准，非致命）"},
    "data_validator":      {"script": "data_validator.py",        "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "数据健康校验",      "unlock_hint": "始终启用"},
    "data_loader":         {"script": "data_loader.py",           "tiers": ["advanced", "pro", "auto"],             "schedule": "daily",                          "label": "基本面/资金流加载", "unlock_hint": "Advanced 级（3万+）"},
    "stock_pick":          {"script": "strategy.py",              "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "fatal_on_fail": True,  "label": "选股策略",          "unlock_hint": "始终启用"},
    "multi_strategy":      {"script": "multi_strategy.py",        "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "多策略对比",        "unlock_hint": "始终启用"},
    "backtest":            {"script": "enhanced_backtest.py",     "tiers": ["advanced", "pro", "auto"],             "schedule": "daily",                          "label": "增强回测",          "unlock_hint": "Advanced 级（3万+）"},
    "factor_analysis":     {"script": "factor_analysis.py",       "tiers": ["advanced", "pro", "auto"],             "schedule": "monday",                         "label": "因子IC/IR分析",     "unlock_hint": "Advanced 级（3万+）/ 周一"},
    "minute_kline":        {"script": "fetch_minute_kline.py",    "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "分钟K线抓取",       "unlock_hint": "始终启用"},
    # v8.7+: exit_advisor 提前到 position_sizing 之前 — Why: position_sizer.generate_order_file
    # 调 _load_today_exit_signals 读今天的 exit_advisor_*.json 合并到 daily_orders.md。
    # 之前 exit_advisor 排在最后，position_sizer 永远只能合并昨天的卖出建议，晚 1 个交易日。
    # exit_advisor 自身依赖昨天的 sim 持仓（account_state.json），不依赖今天 sim_trade 输出，所以可以提前。
    "exit_advisor":        {"script": "exit_advisor.py",          "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "always_on": True,       "label": "出场顾问",          "unlock_hint": "始终启用"},
    "position_sizing":     {"script": "position_sizer.py",        "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "fatal_on_fail": True,  "label": "仓位计算",          "unlock_hint": "始终启用（含资金过滤+佣金）"},
    "evolve_daily_light":  {"script": "evolve_daily_light.py",    "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "轻量每日进化",      "unlock_hint": "始终启用"},
    "track_performance":   {"script": "track_performance.py",     "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "选股表现追踪",      "unlock_hint": "始终启用"},
    "sim_trade":           {"script": "sim_trade.py",             "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "模拟交易",          "unlock_hint": "始终启用（lite/full 由 tier 切换）"},
    "portfolio_risk":      {"script": "portfolio_risk.py",        "tiers": ["pro", "auto"],                         "schedule": "daily",                          "label": "组合风控 CVaR",     "unlock_hint": "Pro 级（20万+）"},
    "strategy_feedback":   {"script": "strategy_feedback.py",     "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "策略反馈闭环",      "unlock_hint": "始终启用"},
    "broker_export":       {"script": "broker_adapter.py",        "tiers": ["auto"],                                "schedule": "daily",                          "label": "券商订单生成",      "unlock_hint": "Auto 级（50万+API）"},
    "research_agent":      {"script": "research_agent.py",        "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "args": ["--daily", "今日市场特征复盘 v8策略未来3天胜率预估 大盘择时信号"], "label": "市场研究复盘", "unlock_hint": "始终启用"},
    "integrate_knowledge": {"script": "integrate_knowledge.py",   "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "知识内化",          "unlock_hint": "始终启用"},
    "psychology":          {"script": "psychology_assistant.py",  "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "交易心理助手",      "unlock_hint": "始终启用"},
    "newbie_protection":   {"script": "newbie_protection.py",     "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "新手保护期",        "unlock_hint": "始终启用"},
    "newbie_card":         {"script": "newbie_instruction_card.py","tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "if_file_exists": ".newbie_mode", "label": "新手指令卡", "unlock_hint": "需 .newbie_mode 标记"},
    "cost_tracker":        {"script": "cost_tracker.py",          "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "always_on": True,       "label": "佣金/成本审计",     "unlock_hint": "始终启用"},
    "portfolio_sync":      {"script": "portfolio_manager.py",     "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "持仓状态同步",      "unlock_hint": "始终启用（exit/订单 → 持仓）"},
    "behavior_log":        {"script": "behavior_log.py",          "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "行为日志记录",      "unlock_hint": "始终启用"},
    "bark_push":           {"script": "send_to_bark.py",          "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "always_on": True,       "label": "Bark 推送",         "unlock_hint": "始终启用"},
    "goal_metrics":        {"script": "goal_metrics.py",          "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily", "always_on": True,       "label": "目标指标",          "unlock_hint": "始终启用（流水线成功率/数据完整率/自检通过率）"},
    "self_check":          {"script": "_self_check.py",           "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "系统自检",          "unlock_hint": "始终启用"},
    "auto_heal":           {"script": "auto_heal.py",             "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "自动修复",          "unlock_hint": "始终启用"},
    "walk_forward":        {"script": "walk_forward.py",          "tiers": ["advanced", "pro", "auto"],             "schedule": "wednesday",                      "label": "Walk-Forward 验证", "unlock_hint": "Advanced 级（3万+）/ 周三"},
    "monte_carlo":         {"script": "monte_carlo.py",           "tiers": ["advanced", "pro", "auto"],             "schedule": "month-end",                      "label": "蒙特卡洛模拟",      "unlock_hint": "Advanced 级（3万+）/ 月末"},
    "strategy_arena":      {"script": "strategy_arena.py",        "tiers": ["advanced", "pro", "auto"],             "schedule": "friday",                         "label": "策略竞技",          "unlock_hint": "Advanced 级（3万+）/ 周五"},
    "external_research":   {"script": "external_research.py",     "tiers": ["advanced", "pro", "auto"],             "schedule": "monday",                         "label": "arXiv 外部研究",    "unlock_hint": "Advanced 级（3万+）/ 周一"},
    "evolve_strategy":     {"script": "evolve_strategy.py",       "tiers": ["advanced", "pro", "auto"],             "schedule": "thursday", "args": ["--auto"],   "label": "策略自动进化",      "unlock_hint": "Advanced 级（3万+）/ 周四"},
    "archive":             {"script": "archive_old_data.py",      "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "daily",                          "label": "老数据归档",        "unlock_hint": "始终启用（每天兜底归档）"},
    "benchmark_compare":   {"script": "benchmark_comparison.py",  "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "friday",                         "label": "v8 vs HS300 对比",  "unlock_hint": "始终启用 / 周五"},
    "tracking_error":      {"script": "tracking_error_report.py", "tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "month-end",                      "label": "Tracking Error",    "unlock_hint": "始终启用 / 月末"},
    "monthly_behavior":    {"script": "monthly_behavior_report.py","tiers": ["beginner", "advanced", "pro", "auto"], "schedule": "month-end",                      "label": "月度行为偏差报告",  "unlock_hint": "始终启用 / 月末"},
}


# ============================================================
# 调度逻辑
# ============================================================
_DOW_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _today_dow():
    """返回今天星期名（lowercase）。"""
    return _DOW_NAMES[datetime.now().weekday()]


def _is_month_end():
    """简化口径：≥25 日视为月末窗口（v7.6 沿用）。"""
    return datetime.now().day >= 25


def _schedule_match(schedule):
    if schedule == "daily":
        return True
    if schedule == "month-end":
        return _is_month_end()
    if schedule in _DOW_NAMES:
        return _today_dow() == schedule
    if schedule == "weekday":
        return _today_dow() in _DOW_NAMES[:5]
    return True  # 未知 schedule 容错按 daily


def _step_status(step, base_dir):
    """返回 (active, reason)。reason 之一：active / tier-skip / schedule-skip / file-cond-skip。"""
    if SYSTEM_TIER.value not in step.get("tiers", []):
        return False, "tier-skip"
    if not _schedule_match(step.get("schedule", "daily")):
        return False, "schedule-skip"
    cond = step.get("if_file_exists")
    if cond and not os.path.exists(os.path.join(base_dir, cond)):
        return False, "file-cond-skip"
    return True, "active"


# ============================================================
# 公开查询接口（供 Streamlit 健康面板/CLI 使用）
# ============================================================
def list_steps():
    """枚举所有步骤的当前 active/reason，便于健康面板渲染。"""
    base_dir = _project_root()
    result = []
    for name, step in PIPELINE_STEPS.items():
        active, reason = _step_status(step, base_dir)
        result.append({
            "id": name,
            "label": step.get("label", name),
            "script": step["script"],
            "tiers": step["tiers"],
            "schedule": step.get("schedule", "daily"),
            "active": active,
            "reason": reason,
            "unlock_hint": step.get("unlock_hint", ""),
            "always_on": step.get("always_on", False),
        })
    return result


def active_steps():
    return [s for s in list_steps() if s["active"]]


def dormant_steps():
    """tier 不达标的步骤（不含调度跳过）—— 用于"未来解锁"提示。"""
    return [s for s in list_steps() if not s["active"] and s["reason"] == "tier-skip"]


# ============================================================
# 执行引擎
# ============================================================
def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python():
    return os.environ.get("QUANT_PYTHON") or sys.executable


def _run_script(name, step, base_dir):
    script_path = os.path.join(base_dir, step["script"])
    if not os.path.exists(script_path):
        print(f"[MISS] {name}: {script_path} not found")
        return 127
    cmd = [_python(), script_path] + step.get("args", [])
    retries = max(1, int(step.get("retry", 1)))
    wait = int(step.get("retry_wait", 0))
    rc = 1
    for attempt in range(1, retries + 1):
        rc = subprocess.run(cmd, cwd=base_dir).returncode
        if rc == 0:
            return 0
        if attempt < retries:
            print(f"[RETRY] {name} attempt {attempt} failed (rc={rc}); waiting {wait}s")
            if wait > 0:
                time.sleep(wait)
    return rc


def _check_trading_day_inline():
    """内联交易日检测（fail-open）。返回 (is_trading_day: bool, reason: str)。

    Why 放在 run_all 而不是依赖注册表里的 check_trading_day 子进程：
    子进程 rc=1 会被记成 FATAL，周末/节假日流水线日志全是失败；
    内联检测拿到 False 时由 run_all 干净跳过并返回 0。
    """
    try:
        from check_trading_day import is_trading_day
        ok, reason = is_trading_day()
        return bool(ok), str(reason)
    except Exception as exc:
        print(f"[TRADING-DAY] check failed (fail-open): {exc}")
        return True, f'check failed (fail-open): {exc}'


def _alpha_gate_precheck(trading_day_ok: bool = True):
    """已确认交易日后再跑一次 alpha_gate.check_alpha_gate()，决定是否让流水线继续。

    v8.6 设计意图是「每天调用 evaluate_etf_gate() 计数」，但旧实现只读
    is_paused()、从不更新状态，导致连续 severe 天数永远停在历史值、门永远不会触发。
    v8.7 补两点：① run_all 先确认交易日；② 确认后传 trading_day_ok=True，
    alpha_gate 不再重复联网判交易日。任何异常都 fail-open（打印告警，不阻断流水线）。

    Returns:
        (paused: bool, reason: str)
    """
    try:
        from alpha_gate import check_alpha_gate
        result = check_alpha_gate(trading_day_ok=trading_day_ok)
        print(f"[ALPHA-GATE] checked: severity={result.severity}, "
              f"counted={result.counted}, "
              f"consecutive_severe_days={result.consecutive_severe_days}, "
              f"paused={result.paused}")
        if result.paused:
            return True, result.pause_reason
        return False, ''
    except Exception as exc:
        print(f"[ALPHA-GATE] check failed (non-fatal): {exc}")
        return False, ''


def run_all(only=None, dry_run=False):
    """执行流水线。
    only: 可选 step id 列表，仅运行这些步骤（仍受 tier/schedule 限制）。
    dry_run: 只打印将运行哪些步骤，不真的执行。
    """
    base_dir = _project_root()
    all_steps = list_steps()

    if only:
        all_steps = [s for s in all_steps if s["id"] in set(only)]

    active = [s for s in all_steps if s["active"]]
    tier_skipped = [s for s in all_steps if not s["active"] and s["reason"] == "tier-skip"]
    sched_skipped = [s for s in all_steps if not s["active"] and s["reason"] in ("schedule-skip", "file-cond-skip")]

    print("=" * 60)
    print(f"  量化交易系统 v{SYSTEM_VERSION} - 流水线 DAG | tier={SYSTEM_TIER.value}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {_today_dow()}")
    print("=" * 60)
    print(f"  运行: {len(active)} 步 | tier 跳过: {len(tier_skipped)} | 调度跳过: {len(sched_skipped)}")
    if tier_skipped:
        print(f"  tier 升级解锁: {', '.join(s['id'] + '→' + s['unlock_hint'] for s in tier_skipped[:5])}{'...' if len(tier_skipped) > 5 else ''}")
    print("=" * 60)

    # v8.7: 非交易日先干净跳过（rc=0）—— 周末计划任务不再产生 FATAL 失败日志。
    # 交易日确认后 Alpha Gate 才会计数；顺序不能反，否则周末会把 severe 计成新交易日。
    if not dry_run:
        is_trading_day, _reason = _check_trading_day_inline()
        if not is_trading_day:
            print(f"[SKIP] 非交易日，流水线跳过（{_reason}）")
            return 0

        # v8.6: Alpha Gate early-return — 交易日每日计数，paused 时不跑选股流水线
        # Why: 连续 5 个交易日跑输 HS300 自动暂停，避免在熊市/系统失效期继续磨损资金
        from core.config import get as _cfg_get
        if _cfg_get('alpha_gate.enabled', True):
            paused, reason = _alpha_gate_precheck(trading_day_ok=True)
            if paused:
                print(f"[ALPHA-GATE] PAUSED: {reason}")
                print("[ALPHA-GATE] Run 'python alpha_gate.py --reset' to resume")
                return 0

        # 交易日检测已内联完成，注册表里的同名子进程不再重复执行（避免再次联网 + rc 语义冲突）
        active = [s for s in active if s["id"] != "check_trading_day"]

    if dry_run:
        for i, s in enumerate(active, 1):
            print(f"  [{i}/{len(active)}] {s['id']:<22} {s['script']}")
        return 0

    _t0_all = datetime.now()
    for i, s in enumerate(active, 1):
        _t0 = datetime.now()
        print(f"\n[{_t0.strftime('%H:%M:%S')}] [{i}/{len(active)}] {s['id']} ({s['script']})", flush=True)
        step = PIPELINE_STEPS[s["id"]]
        rc = _run_script(s["id"], step, base_dir)
        _dt = (datetime.now() - _t0).total_seconds()
        print(f"      -> {s['id']} finished in {_dt:.0f}s, rc={rc}", flush=True)
        if rc != 0:
            if step.get("fatal_on_fail"):
                print(f"[FATAL] {s['id']} failed (rc={rc}); aborting pipeline")
                return rc
            print(f"[WARN] {s['id']} failed (rc={rc}); continuing")

    print("\n" + "=" * 60)
    print(f"  Pipeline complete | v{SYSTEM_VERSION} | tier={SYSTEM_TIER.value} | "
          f"{datetime.now().strftime('%H:%M:%S')} | 总耗时 {(datetime.now() - _t0_all).total_seconds() / 60:.1f} 分钟")
    print("=" * 60)
    return 0


# ============================================================
# CLI 入口
# ============================================================
def main(argv=None):
    argv = argv or sys.argv[1:]
    if "--list" in argv or "list" in argv:
        for s in list_steps():
            mark = "[ON]" if s["active"] else ("[..]" if s["reason"] != "tier-skip" else "[--]")
            print(f"  {mark} {s['id']:<22} {s['label']:<22} tiers={s['tiers']} sched={s['schedule']} ({s['reason']})")
        return 0
    if "--dry-run" in argv:
        return run_all(dry_run=True)
    return run_all()


if __name__ == "__main__":
    sys.exit(main())
