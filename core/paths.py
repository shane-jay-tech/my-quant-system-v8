"""唯一合法路径来源（S4-a 地基批，2026-09-10）。

全仓路径收敛的单一来源：新增代码禁止再手写 os.path.join(BASE, ...) 或
相对路径字面量，一律从本模块取 Path；存量消费方由 S4-b/c/d/e 各批逐文件
机械迁移。迁移期约定：

- REPO_ROOT 只算一次（模块单例语义）；
- 本模块内禁 os.chdir（cwd 语义留给调用方，与 S2 的 chdir 还原纪律一致）；
- 目录常量大写、取值函数动词开头，一律返回 pathlib.Path。
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

DATA_DIR: Path = REPO_ROOT / 'data'
RESULTS_DIR: Path = REPO_ROOT / 'results'
REPORTS_DIR: Path = REPO_ROOT / 'reports'
LOGS_DIR: Path = REPO_ROOT / 'logs'
ORDERS_DIR: Path = REPO_ROOT / 'orders'
BACKUP_DIR: Path = REPO_ROOT / 'backup'
KB_FILE: Path = REPO_ROOT / 'docs' / 'knowledge' / 'quant-kb.md'

_DATED_SUFFIX = _re.compile(r'_(\d{8})$')


def ensure_dir(path: Path) -> Path:
    """mkdir(parents=True, exist_ok=True) 后返回原路径。"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_file(name: str) -> Path:
    """data/ 下具名数据件的规范路径（data/stock_*.csv 一类）。"""
    return DATA_DIR / name


def dated_file(dir_path: Path, stem: str, ext: str, day: _dt.date | None = None) -> Path:
    """统一「名_YYYYMMDD.扩展」日期件命名（各生成器私有 strftime 的通用化）。"""
    d = day or _dt.date.today()
    return dir_path / f'{stem}_{d:%Y%m%d}.{ext.lstrip(".")}'


def latest_dated(dir_path: Path, stem: str, ext: str) -> Path | None:
    """取「名_YYYYMMDD.扩展」系列中最新的一个；目录不存在或无匹配返回 None。"""
    ext = ext.lstrip('.')
    if not dir_path.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for p in dir_path.glob(f'{stem}_*.{ext}'):
        m = _DATED_SUFFIX.search(p.stem)
        if not m:
            continue
        key = int(m.group(1))
        if best is None or key > best[0]:
            best = (key, p)
    return best[1] if best else None
