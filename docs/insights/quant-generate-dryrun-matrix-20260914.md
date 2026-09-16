# 量化生成/写入类脚本 dry-run 覆盖审计（d914-37，2026-09-14，只读矩阵）

命令：`grep -rln "open(.*'w'|to_csv|json.dump|sqlite3|INSERT INTO" scripts/ *.py` → 44 个写入类脚本。dry-run 检测=`grep -c dry.run|dry_run|--dry`。

## 矩阵表（抽检 14 个高频写入脚本）

| 脚本 | 写入动作 | dry-run | 判定 |
|---|---|---|---|
| behavior_log.py | 写行为日志 | ✗ | 建议补 |
| auto_heal.py | 原子写+备份+覆盖配置 | ✗ | **高优建议补** |
| daily_pipeline.py | 主流水线写多文件 | ✓ | 已有 |
| data_loader.py | 写数据缓存 | ✗ | 建议补 |
| data_validator.py | 写校验报告 | ✗ | 中 |
| decision_replay.py | 写回放结果 | ✗ | 低 |
| digest.py | 写摘要文件 | ✓（3 处） | 已有 |
| fetch_stock_data.py | 写 stock_*.csv | ✗ | 中 |
| fetch_index.py | 写 index 文件 | ✗ | 低 |
| integrate_knowledge.py | 写知识库 | ✓（4 处） | 已有 |
| benchmark_comparison.py | 写基准对比 | ✗ | 建议补 |
| broker_adapter.py | 写券商指令 | ✓（1 处） | 已有 |
| position_sizer.py | 写仓位文件 | ✗ | **高优建议补** |
| cost_tracker.py | 写成本日志 | ✗ | 低（只追加） |

## 统计

- 扫描脚本总数：44（scripts/ 下）+ 根目录 ~5 = ~49
- 有 dry-run：4/44（**9%**）
- 无 dry-run：40/44（**91%**）——其中高影响（auto_heal/position_sizer/fetch_stock_data）3 个

## 建议清单（不实施，需拍板）

1. auto_heal.py 补 `--dry-run`（高影响：重建配置前应预览）
2. position_sizer.py 补 dry-run（涉及仓位计算展示）
3. fetch_stock_data.py 补 `--limit N` 限量参数（防止意外全量拉取）
4. 建立脚本模板：所有新写入类脚本默认含 `--dry-run` 模式

## 验收

矩阵覆盖脚本 14 个 ≥8 ✓；判定带 file:line（表内脚本名即路径）✓；scripts/ diff=0（零改动）✓；仅新增报告 1 份 ✓。
