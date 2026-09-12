# quant S4CD-4 修复报告（h912-09，2026-09-13 夜班）：硬编码扫描提到公共路径

任务：`ops/health.py` [6] External 的硬编码 token 扫描原先只在「无 secrets 且无 secrets.json」的 elif 分支执行——token 正常配置（常态）时安全扫描从不运行。按 S4-R2 建议提为常跑检查项。

## 改动（diff 摘要）

1. 新增模块级 `_scan_hardcoded_bark_token()`——扫描循环从原 elif 分支**逐字搬移**（4 文件名单、`["\'][0-9A-Fa-f]{32}["\']` 规则、break/except 语义一字未改），仅提取成函数。
2. 原 elif 分支改 `pass`（扫描上提），扫描结果在分支块之后的**公共路径**统一输出：
```python
# S4CD-4(h912-09): 硬编码 token 扫描提到公共路径——无论走哪个分支都执行（扫描规则与名单与原分支一字未改）
hardcoded = _scan_hardcoded_bark_token()
check('External: Bark token', 'external', not hardcoded, '推送源码中仍存在 32 位硬编码 token')
```
elif 场景输出与改前完全一致（同 check 名/条件/文案）；if/else 场景**新增**该扫描检查项（即修复目标）。

## 改前/改后证据

改前基线（harness 实测）：
- if 分支（BARK_KEY 已配置）：Bark 相关检查项 = `['Import: Bark', 'External: Bark token in secrets']` → **无扫描项**（病灶实证）。
- elif 分支：有 `('External: Bark token', 'PASS')`（唯一跑扫描的分支）。

新用例改前失败输出（tests/test_health_s4cd4_h912_09.py，3 条）：
```
FAILED test_scan_runs_on_if_branch      - AssertionError: assert 0 >= 1, "if 分支未执行硬编码扫描（S4CD-4 病灶）"
FAILED test_scan_runs_on_elif_branch    - assert 0 >= 1
FAILED test_scan_runs_on_else_branch    - assert 0 >= 1, "else 分支未执行硬编码扫描（S4CD-4 病灶）"
```
（spy 挂在 `_scan_hardcoded_bark_token` 上计数；改前扫描是内联代码，spy 调用数恒 0。）

改后：**3 passed**；harness 逐分支证据：
```
if   分支 Bark 检查项: ['Import: Bark', 'External: Bark token in secrets', 'External: Bark token']
elif 分支 Bark 检查项: ['Import: Bark', 'External: Bark token']
else 分支 Bark 检查项: ['Import: Bark', 'External: Bark token in secrets', 'External: Bark token']
```
→ **三分支全部命中扫描**（每分支都有 'External: Bark token' 项）。

## 全量回归

`python -m pytest -q` → **474 passed, 2 xfailed, 0 failed**（改前基线 471 passed + 本单 3 条新测）。

## 侧修披露（本单顺带，1 行域）

- `tests/test_bark_push_h912_04.py::test_send_from_newbie_file_parses_title_and_body` 全量复跑时暴露失败——该测试（h912-04 产出）把 bark 文件名硬编码为 `20260912`，**跨午夜后** `send_from_newbie_file` 按当天日期（20260913）找文件必然落空。修为按 `datetime.now()` 生成文件名（时区无关、跨日稳定）。属测试自身时敏缺陷，非生产码问题。

## 遗留问题

- S4-R2 其余三项未动：S4CD-2（secrets 解析失败 stderr 告警）、S4CD-3（解析顺序一致性，行为变更需拍板）、S4CD-1（卫生）。
- run_all 在本机 schtasks 子进程输出有 UTF-16 解码噪音线程异常（既有，检查项照常产出），与本单无关。
- if/else 分支新增扫描检查项使 health 总检查数 +1（163→164/154→155），周报对比口径需知悉。
