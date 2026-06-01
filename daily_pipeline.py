"""
每日流水线 Python 入口（DAG 编排器，版本号从 SYSTEM_VERSION 拉取）

替代 v7.6 daily_pipeline.bat 中的硬编码 24 步。所有步骤由 core.pipeline.PIPELINE_STEPS
注册表驱动，按 SYSTEM_TIER 与日程过滤；脚本本身物理保留。

用法：
    python daily_pipeline.py                 # 按当前 tier 全量执行
    python daily_pipeline.py --dry-run       # 只打印将运行的步骤
    python daily_pipeline.py --list          # 枚举注册表全状态
    QUANT_TIER=pro python daily_pipeline.py  # 临时升级 tier 跑一次

升级方式：
    1. 修改 data/system_config.json 中 "tier": {"level": "advanced"}
    2. 或设置环境变量 QUANT_TIER=advanced
"""
import sys
from core.pipeline import main

if __name__ == "__main__":
    sys.exit(main())
