"""
统一配置中心 v8.5（分级解锁架构 + 单一版本号源）
所有策略参数、风控阈值、合规限制集中管理；新增 Tier 分级解锁配置。

使用方式：
    from core.config import get as cfg, SYSTEM_VERSION
    MA_LONG = cfg('strategy.ma_long', 20)
    print(f"v{SYSTEM_VERSION}")  # 8.5

    from core.config import SYSTEM_TIER, SystemTier, ENABLE_PORTFOLIO_RISK
    if ENABLE_PORTFOLIO_RISK:
        run_var()

优先级（参数）：
    1. data/system_config.json（用户自定义）
    2. DEFAULTS（代码内置默认值）

优先级（Tier）：
    1. 环境变量 QUANT_TIER（最高）
    2. data/system_config.json 的 tier.level
    3. 默认 'beginner'
"""
import os
import json
from enum import Enum

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_BASE, 'data', 'system_config.json')

# ============================================================
# v8.5: 系统总版本号 — 所有模块的版本号单一事实源
# 引用方式：from core.config import SYSTEM_VERSION
# 任何 docstring / 报告底部 / health check 都应从此处拉取
# ============================================================
SYSTEM_VERSION = "8.6"
SYSTEM_RELEASED = "2026-05-23"

# v7.6: 配置单例缓存，避免每次 get() 都重新读盘
_CACHE = None
_CACHE_MTIME = 0

DEFAULTS = {
    "system": {
        "version": SYSTEM_VERSION,
        "released": SYSTEM_RELEASED
    },
    "tier": {
        "level": "beginner"
    },
    "strategy": {
        "ma_short": 5,
        "ma_long": 30,
        "rsi_period": 14,
        "rsi_low": 30,
        "rsi_high": 70,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "vol_ratio_min": 1.2,
        "mcap_min": 5000000000,
        "top_n": 20,
        "use_dynamic_params": True
    },
    "backtest": {
        "ma_short": 5,
        "ma_long": 30,
        "rsi_period": 14,
        "rsi_low": 30,
        "rsi_high": 70,
        "mcap_min": 5000000000,
        "top_n": 10,
        "cost": 0.002,
        "backtest_days": 120,
        "execution_mode": "next_open",
        "slippage": 0.001
    },
    "cost": {
        "commission_rate": 0.0003,
        "commission_min": 5.0,
        "stamp_tax_rate": 0.0005,
        "slippage_large_cap": 0.001,
        "slippage_mid_cap": 0.002,
        "slippage_small_cap": 0.003,
        "per_trade_notional": 400,
        "notional_dynamic": True,
        "order_gate_max_pct": 0.025
    },
    "position": {
        "max_single_position": 1.0,
        "atr_stop_multiplier": 2.0,
        "default_capital": 2400,
        "regime_hysteresis_days": 2
    },
    "sim": {
        "initial_capital": 2400,
        "manual_capital": None,
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.30,
        "max_hold_days": 30
    },
    "broker": {
        "max_single_pct": 1.0,
        "max_total_pct": 1.0,
        "min_order_amount": 0,
        "max_single_amount": 2400,
        "daily_limit_pct": 0.098,
        "drop_limit_pct": -0.098,
        "gap_skip_pct": 3.0
    },
    "evolve": {
        "dry_run_only": True
    },
    "portfolio": {
        "exclude_held_from_picks": True,
        "max_concurrent_holdings": 5,
        "default_holding_days": 10
    },
    "data_validation": {
        "min_stock_rows": 4000,
        "min_nonzero_price_pct": 0.99,
        "min_nonempty_volume_pct": 0.95,
        "max_history_lag_days": 5,
        "fail_on_invalid": False
    },
    "archive": {
        "stock_csv_keep_days": 7,
        "orders_keep_days": 30,
        "results_keep_days": 30,
        "reports_keep_days": 60
    },
    "behavior_log": {
        "enabled": True,
        "auto_track_recommendations": True
    },
    "feedback": {
        "min_trades_for_adjust": 30
    },
    "alpha_gate": {
        "enabled": True,
        "lookback_days": 5,
        "history_keep_count": 30
    },
    # v8.6: gate 阈值集中（alpha_gate + etf_gate 共享同一个"超额收益 vs HS300"信号）
    # severe_excess_pct: excess <= 此值 -> 红横幅 + alpha_gate 计数累加
    # warning_excess_pct: severe < excess <= 此值 -> 黄横幅（手续费会吃光）
    # max_age_days: results/honest_evaluation.md 超过这个天数视为陈旧
    # stale_lag_trading_days: hs300_index.csv 落后本地最新交易日超过这个"交易日数"
    #   视为行情基线数据陈旧（v8.7 起取代 max_age_days 的报告 mtime 判定；交易日口径，节假日安全）
    "gate": {
        "severe_excess_pct": 0.0,
        "warning_excess_pct": 1.0,
        "max_age_days": 10,
        "stale_lag_trading_days": 3
    },
    # v8.6: 进化器优先级（避免三个进化器同时改 RSI/MA 互相覆盖）
    # daily_light: 当下生效路径（每日 ±5 微调，写 evolve_daily_state.json）
    # weekly_ab:   周末实验性 A/B，结果作为 [待验证] 写回 CLAUDE.md 等人工 confirm
    # arena:       月度变异群（小资金价值低，默认关）
    "evolve_priority": {
        "daily_light_enabled": True,
        "weekly_ab_enabled": True,
        "arena_enabled": False
    }
}


def _deep_merge(base, override):
    """递归合并字典，override 覆盖 base 的同名键。"""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            base[key] = _deep_merge(base[key].copy(), val)
        else:
            base[key] = val
    return base


def _load_config(force=False):
    """加载用户自定义配置，带单例缓存。如不存在则创建默认文件。"""
    global _CACHE, _CACHE_MTIME
    if not force and _CACHE is not None:
        try:
            mtime = os.path.getmtime(_CONFIG_PATH)
            if mtime == _CACHE_MTIME:
                return _CACHE
        except OSError:
            pass

    cfg = DEFAULTS.copy()
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
            cfg = _deep_merge(cfg, user_cfg)
            _CACHE_MTIME = os.path.getmtime(_CONFIG_PATH)
        except Exception:
            pass
    else:
        try:
            os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
            with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
            _CACHE_MTIME = os.path.getmtime(_CONFIG_PATH)
        except Exception:
            pass

    _CACHE = cfg
    return cfg


def reload():
    """强制重新加载配置文件（通常在手动修改配置后调用）。"""
    return _load_config(force=True)


def set_value(path, value):
    """写入用户配置文件（data/system_config.json）的某个点分路径键，并刷新缓存。

    只改用户覆盖文件，不动 DEFAULTS；写入后强制 reload，使同进程内
    后续 get() 立即生效。原子写（先写 .tmp 再 os.replace），避免半截文件。
    """
    keys = path.split('.')
    user_cfg = {}
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
        except Exception:
            user_cfg = {}
    node = user_cfg
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]
    node[keys[-1]] = value

    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    tmp = _CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(user_cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CONFIG_PATH)
    reload()
    return value


def get_mtime():
    """返回缓存对应的文件修改时间戳，None 表示未加载。"""
    return _CACHE_MTIME


def get(path, default=None):
    """按点分路径读取配置值。"""
    cfg = _load_config()
    keys = path.split('.')
    for k in keys:
        if isinstance(cfg, dict) and k in cfg:
            cfg = cfg[k]
        else:
            return default
    return cfg


def get_dict(section):
    """读取整个配置节，如 get_dict('strategy')。"""
    cfg = _load_config()
    return cfg.get(section, {})


# ============================================================
# v8.0 分级解锁（Tier）
# ============================================================
class SystemTier(str, Enum):
    BEGINNER = "beginner"   # 小资金（当前 2400 元），手动，极简
    ADVANCED = "advanced"   # 3-10 万，多策略细化
    PRO = "pro"             # 20 万+，组合风控
    AUTO = "auto"           # 50 万+，API 自动交易


_TIER_ORDER = [SystemTier.BEGINNER, SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO]


def _resolve_tier():
    """优先级：QUANT_TIER 环境变量 > config tier.level > beginner。"""
    raw = os.getenv("QUANT_TIER") or get('tier.level', 'beginner')
    try:
        return SystemTier(str(raw).lower())
    except ValueError:
        return SystemTier.BEGINNER


SYSTEM_TIER = _resolve_tier()


def tier_at_least(min_tier):
    """SYSTEM_TIER 是否 ≥ 给定门槛。接受 SystemTier 或字符串。"""
    if isinstance(min_tier, str):
        min_tier = SystemTier(min_tier.lower())
    return _TIER_ORDER.index(SYSTEM_TIER) >= _TIER_ORDER.index(min_tier)


def tier_in(tiers):
    """SYSTEM_TIER 是否落在白名单内。tiers 接受字符串或 SystemTier 列表。"""
    normalized = {SystemTier(t.lower()) if isinstance(t, str) else t for t in tiers}
    return SYSTEM_TIER in normalized


def reload_tier():
    """配置或环境变量改动后，重新解析 tier。
    注意：模块级 ENABLE_* 标志在 import 时已固化，仅 SYSTEM_TIER 会即时刷新。
    """
    global SYSTEM_TIER
    reload()
    SYSTEM_TIER = _resolve_tier()
    return SYSTEM_TIER


# ----- 模块级开关（基于 SYSTEM_TIER 在 import 时计算）-----
ENABLE_BROKER_ADAPTER     = tier_in([SystemTier.AUTO])
ENABLE_PORTFOLIO_RISK     = tier_in([SystemTier.PRO, SystemTier.AUTO])
ENABLE_MONTE_CARLO        = tier_in([SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO])
ENABLE_WALK_FORWARD       = tier_in([SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO])
ENABLE_FUNDAMENTAL_FILTER = tier_in([SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO])
ENABLE_STRATEGY_ARENA     = tier_in([SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO])
ENABLE_FACTOR_ANALYSIS    = tier_in([SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO])
ENABLE_EVOLVE_STRATEGY    = tier_in([SystemTier.ADVANCED, SystemTier.PRO, SystemTier.AUTO])

# sim_trade 双模式：lite=极简虚拟账本只读盈亏；full=完整撮合+滑点+执行质量
SIM_MODE = "full" if tier_at_least(SystemTier.ADVANCED) else "lite"

# Bark 推送模板密度
BARK_TEMPLATE_LEVEL = SYSTEM_TIER.value


# 始终启用：小资金防亏核心 —— 任何 tier 都不得关闭
ALWAYS_ON_FEATURES = [
    "capital_filter",      # 可用资金过滤（一手价 ≤ 资金 × 50%）
    "commission_display",  # 佣金摩擦成本计算并显示
    "daily_three_check",   # 每日三问检查清单
    "exit_advisor",        # 出场建议
    "bark_push",           # Bark 推送
]
