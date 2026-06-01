"""原子 JSON 写入 — 单一真相源（v8.7 抽取）。

之前 sim_trade.py / alpha_gate.py / strategy_feedback.py 各自有 `_atomic_write_json`，
其中 alpha_gate 多了 `sort_keys=True`。统一到这里：默认不排序，需要排序的传 sort_keys=True。
"""
from __future__ import annotations

import json
import os


def atomic_write_json(path: str, data, *, sort_keys: bool = False, indent: int = 2,
                      ensure_dir: bool = False) -> None:
    """写到 .tmp 再 os.replace，断电不会留 0 字节文件。

    Args:
        path: 目标文件路径。
        data: 要 dump 的 dict / list。
        sort_keys: 是否按 key 排序（alpha_gate 流派为 True，其它为 False）。
        indent: JSON 缩进。
        ensure_dir: True 时自动 mkdir 父目录。
    """
    if ensure_dir:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, sort_keys=sort_keys)
        if sort_keys:
            f.write('\n')  # 与原 alpha_gate 行为一致
    os.replace(tmp, path)
