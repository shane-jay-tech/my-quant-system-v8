"""[已迁移] 自检入口自 2026-09-09（S2 重构）起迁至 ops/health.py。

本文件仅为兼容历史调用路径（手动 `python _self_check.py`、旧测试导入）的 shim：
import 零副作用，执行请继续走 `python ops/health.py` 或 pipeline 的 self_check 步骤。
"""
from ops.health import (  # noqa: F401
    run_all,
    check,
    warn,
    is_non_trading_day,
    _trading_days_behind,
    load_prev_health,
)

if __name__ == '__main__':
    run_all()
