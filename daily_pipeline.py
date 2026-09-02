"""
每日流水线 Python 入口（DAG 编排器，版本号从 SYSTEM_VERSION 拉取）

替代 v7.6 daily_pipeline.bat 中的硬编码 24 步。所有步骤由 core.pipeline.PIPELINE_STEPS
注册表驱动，按 SYSTEM_TIER 与日程过滤；脚本本身物理保留。

用法：
    python daily_pipeline.py                 # 按当前 tier 全量执行
    python daily_pipeline.py --dry-run       # 只打印将运行的步骤
    python daily_pipeline.py --list          # 枚举注册表全状态
    QUANT_TIER=pro python daily_pipeline.py  # 临时升级 tier 跑一次

v8.7 审查修复：fatal 失败/异常时写 data/pipeline_failed.txt 并尝试推送失败通知——
旧版在 bark_push 之前 fatal 即静默退出，无人值守时用户根本不知道管道已坏。
"""
import os
import sys
import traceback
from datetime import datetime

from core.pipeline import main

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAIL_MARKER = os.path.join(BASE_DIR, 'data', 'pipeline_failed.txt')


def _notify_failure(reason: str):
    try:
        os.makedirs(os.path.dirname(FAIL_MARKER), exist_ok=True)
        with open(FAIL_MARKER, 'w', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{reason}\n")
        msg_file = os.path.join(BASE_DIR, 'data', 'pipeline_failed.txt')
        import subprocess
        subprocess.run([sys.executable, os.path.join(BASE_DIR, 'send_to_bark.py'),
                        '--file', msg_file, '--no-digest'],
                       cwd=BASE_DIR, timeout=60)
    except Exception as exc:
        print(f"[PIPELINE] failure notify failed (non-fatal): {exc}", flush=True)


if __name__ == "__main__":
    rc = 1
    try:
        rc = int(main() or 0)
    except KeyboardInterrupt:
        reason = 'Pipeline interrupted by user (Ctrl+C)'
        print(f"[PIPELINE] {reason}", flush=True)
        _notify_failure(reason)
        rc = 130
    except Exception:
        reason = 'Pipeline crashed with exception:\n' + traceback.format_exc()[-3000:]
        print(reason, flush=True)
        _notify_failure(reason)
        rc = 1
    if rc not in (0, 130):
        _notify_failure(f'Pipeline fatal failure (rc={rc})')
    sys.exit(rc)
