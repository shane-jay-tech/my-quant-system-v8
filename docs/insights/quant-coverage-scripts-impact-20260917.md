# quant coverage scripts/ 纳入影响评估（916-13，2026-09-17，零配置改动只读跑）

## 一、两条命令与覆盖数字（先命令后数字）

### 基线口径（与权威基线 quant-test-baseline-20260915.md 同命令）

```
$ python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov-report=term
TOTAL                        1321    205    84%
596 passed, 2 xfailed, 12 warnings in 32.08s
```

→ **TOTAL 84%**，与 9/15 权威基线（84%）一致 ✓（口径=branch？注：基线口径 A=两主包 TOTAL，本跑完全复现）。

### 纳入 scripts/ 口径（仅追加 --cov=scripts，其余不变）

```
$ python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov=scripts --cov-report=term
scripts\capacity_collect.py      16     16     0%
scripts\dedup_claude_md.py       53     53     0%
scripts\ops_analyzer.py         126     41    67%
TOTAL                          1516    315    79%
596 passed, 2 xfailed, 12 warnings in 25.10s
```

→ **TOTAL 79%**。

## 二、摊薄幅度（可复算）

- 基线：(1321−205)/1321 = 1116/1321 = **84.48%**（报告取 84%）
- 纳入后：(1516−315)/1516 = 1201/1516 = **79.22%**（报告取 79%）
- **摊薄 = 84.48% − 79.22% = −5.26 ≈ −5 个百分点**
- 结构：scripts/ 仅 3 文件共 195 语句，其中 capacity_collect（16 句）与 dedup_claude_md（53 句）**0%（测试从不导入的一次性工具）**、ops_analyzer 67%（已被测试导入）；摊薄主体＝两个 0% 脚本的纯分母效应（非测试质量退化：两主包语句/缺失数两跑完全一致 1321/205）。

## 三、结论：建议**不纳入**（维持 9/15 拍板「scripts 本次不纳入」）

1. **跌破门槛线**：79% < 82% 红线 → 纳入即触发「不许退步」报警，且此后每夜基线对比永久背负 −5pp 偏移，信号噪化；
2. **面不对**：scripts/ 是运维工具面非产品面，其中 2/3 文件为一次性脚本，其 0% 与产品质量无关；ops_analyzer 这类已被测试触达的例外恰恰说明「按文件性质个别纳入」比整目录纳入更合理；
3. **若日后要纳入**的可行路径（供拍板）：豁免一次性脚本（排除 capacity_collect/dedup_claude_md）后口径 = (1516−69 语句 −246 缺失) → 1201/1447 = **83.0%** ≥ 82% 勉强过线；或要求新脚本随写随测后再纳入。

## 四、验收对照

- ✅ 两条命令与覆盖数字同段（先命令后数字）；两跑均为全量 596 passed 零 failed。
- ✅ 摊薄 −5pp 可复算（分子分母全列）。
- ✅ 结论明确：不纳入＋理由＋替代路径。
- ✅ 零配置改动（pyproject/pytest.ini/CI 未动）；零业务码改动；不 push；无顺手重构。

## 五、遗留问题

无（评估型任务；是否重开「豁免清单口径」拍板留用户）。
