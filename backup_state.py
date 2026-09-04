#!/usr/bin/env python3
"""Copy key sim state files into backup/state/<YYYYMMDD>/ with 30-day retention.

Idempotent: re-running for the same day overwrites the day's copies in place.
Read-only for the sources; only prunes backup/state/ dirs older than 30 days.
"""
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent

SOURCES = [
    "sim_results/account_state.json",
    "data/system_config.json",
    "data/risk_config.json",
    "data/regime_state.json",
]

RETENTION_DAYS = 30


def main():
    stamp = date.today().strftime("%Y%m%d")
    dest_dir = BASE / "backup" / "state" / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    missing = []
    for rel in SOURCES:
        src = BASE / rel
        if not src.exists():
            missing.append(rel)
            continue
        shutil.copy2(src, dest_dir / src.name)
        copied.append(rel)

    # retention: only touch date-named dirs inside backup/state/
    state_root = BASE / "backup" / "state"
    cutoff = (date.today() - timedelta(days=RETENTION_DAYS)).strftime("%Y%m%d")
    pruned = []
    for d in state_root.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{8}", d.name) and d.name < cutoff:
            shutil.rmtree(d)
            pruned.append(d.name)

    print(f"[backup_state] date={stamp} copied={len(copied)} missing={len(missing)} pruned={pruned}")
    for rel in copied:
        print(f"[backup_state]   ok {rel} -> backup/state/{stamp}/{Path(rel).name}")
    for rel in missing:
        print(f"[backup_state]   MISSING {rel}")
    return 0 if copied else 1


if __name__ == "__main__":
    sys.exit(main())
