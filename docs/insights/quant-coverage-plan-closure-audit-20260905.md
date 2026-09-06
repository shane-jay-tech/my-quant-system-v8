# 量化测试覆盖率计划闭环盘点（20260905-195600-102b，只读）

> 任务：PLAN.md（测试覆盖率计划）vs 实际落地交叉核对，为日间「计划收口还是继续扩」提供输入。零改动、零运行生产/回测脚本、无资金数值结论。
> 证据源：PLAN.md 全文、tests/ 32 个测试文件实测清点、git show --stat bd61004 / 340bb59、docs/design/decision-core-spec.md（R1–R15）、PLAN-REVIEW-LOG.md、docs/night-plans/2026-09-05-acceptance.md:35、实测复跑 pytest（只跑 tests/，未触生产）。

## 一、条目级对账表（PLAN 6 步骤 + 4 验收标准，全覆盖）

| PLAN 条目 | 状态 | 证据 |
|---|---|---|
| 步骤1 运行现有 183 项测试并记录覆盖率基线 | 部分落地 | 建计划当日（2026-07-14）已做：PLAN-REVIEW-LOG.md 记 `235 passed, 2 xfailed`、branch coverage `19% → 25%`，归档 docs/decisions/2026-07-14-test-coverage-audit.md；但「183」基线口径已过时——本次实测全量 `392 passed, 2 xfailed`（394 项） |
| 步骤2 生产模块按资金风险排序、人工核对关键分支 | 已落地（决策核心范围） | docs/design/decision-core-spec.md（quant-E2）产出 R1–R15 不变量索引，每条附 文件:行号；覆盖 position_sizer/sim_trade/exit_advisor/cost_model/portfolio_manager/broker_adapter/pipeline 七模块 |
| 步骤3 GPT 提方案、DeepSeek 独立复核 | 部分落地（例外降级） | PLAN-REVIEW-LOG.md 明记「规格偏差：多模型中转因环境缺少三模型变量而不可用，按 AGENTS.md 例外降级单模型」 |
| 步骤4 仅在 tests/ 与测试配置/归档文档新增 | 已落地 | bd61004（+tests/test_characterization_risk.py 97 行）、340bb59（+tests/test_characterization_stale.py 92 行）--stat 均只动 tests/；tests/ 现有 32 个测试文件 |
| 步骤5 每个新测试文件写完立即单独执行、失败≤5 轮 | 无法静态核验 | 过程性条款，无过程日志留存；仅结果可查（相关文件当前全绿） |
| 步骤6 全量测试+分支覆盖率检查 | 部分落地 | 全量 ✓（本次实测 392p+2xf，与昨夜验收「383 全绿」一致方向）；分支覆盖率 ✗——07-14 后（含 09-05 特征测试批次）无任何 coverage 产物，仓库内无 .coverage/htmlcov 痕迹 |
| 验收1 全量测试通过 | ✓ | 实测 `392 passed, 2 xfailed in 26s`；红线 3 包（characterization risk/stale 共 9 用例）全绿 |
| 验收2 新测试覆盖 ≥3 个高风险模块关键缺失分支 | ✓ | 四个模块被特征测试覆盖：sim_trade（R1/R3/R8）、broker_adapter（R7）、position_sizer（R2/R5） |
| 验收3 总覆盖率与关键模块分支覆盖率较基线提升 | **未闭环** | 基线 25%（07-14）之后无第二次测量；09-05 两个特征测试 commit 未跑 coverage——本验收标准当前无法判定，是「计划未闭环」的直接原因 |
| 验收4 测试结束后生产数据文件无新增改动 | ✓（测试侧） | 两个 commit 仅 tests/；注：仓库当前存在与本计划无关的既有脏状态（M README.md、?? backup/），非测试批次产物 |

## 二、R1–R8 红线特征测试专项（逐条）

| 红线 | 内容（decision-core-spec 口径） | 钉桩状态 | 证据 |
|---|---|---|---|
| R1 | 止损价 0/None 原样写入（sim_trade.py:384） | ✅ 已钉 | tests/test_characterization_risk.py::TestR1StopLossZero |
| R2 | 陈旧 multi_vote 无日期校验被消费（position_sizer.py:841 + core/pipeline.py:44） | ✅ 已钉 | tests/test_characterization_stale.py::TestR2StaleMultiVote |
| R3 | 旧订单文件新交易日重复成交（sim_trade.py:276-283） | ✅ 已钉 | tests/test_characterization_stale.py::TestR3StaleDailyOrders |
| R4 | 同日重跑买回当日已卖票据（sim_trade.py:894-898，spec 标「部分违反+待确认」） | ❌ 未钉 | 无对应测试；动态验证需同日双跑 pipeline（红线任务禁跑，未钉有客观原因） |
| R5 | 多源全缺失兜底 head(10) 买任意票（position_sizer.py:913-926） | ✅ 已钉 | tests/test_characterization_stale.py::TestR5FallbackTop10 |
| R6 | 沪 B 900xxx 被 `startswith('8'/'9')` 误伤（position_sizer.py:577 止损下限 + sim_trade.py:124-133 涨跌停 29.8） | ❌ 未钉 | 无对应测试；**纯静态可钉**（构造 900xxx 样本断言下限/阈值即可，无需跑交易） |
| R7 | 合规检查 price=0 整批 ZeroDivisionError（broker_adapter.py:124,136） | ✅ 已钉 | tests/test_characterization_risk.py::TestR7ZeroPriceDivision |
| R8 | 最大回撤公式不保证 min 在 max 后（sim_trade.py:716-717） | ✅ 已钉 | tests/test_characterization_risk.py::TestR8DrawdownFormula |

**未钉红线风险排序**：
1. **R6（建议先钉）**——纯静态可钉、成本低；直接关联止损下限与涨跌停判定的资金风险；触发样本明确（900xxx）。
2. **R4**——影响交易历史正确性，但需双进程/状态重放设计（mock `closed` 集合的跨进程语义），成本高于 R6；spec 自身也标「待确认」，宜与修复方案同批设计。

## 三、差距分析

### 高价值未落地 top3

1. **覆盖率复测一步之遥（验收3 闭环）**：PLAN 唯一无法判定的是「覆盖率较基线提升」，而补测量事实巨大（183→394 项，07-14 后新增 9 个测试文件）。07-14 的 19%→25% 方法论已在案（验收命令三连），补跑一次 `coverage run --branch` + report 即可让整个计划闭环——成本一条命令，收益是把「计划」变成「已验收」。建议日间立即安排。
2. **R6 钉桩**：见上，八个红线里唯一的纯静态缺口，一个测试文件内可完成。
3. **R4 的可测化设计**：当前 R4 无法用现有单测框架钉（跨进程状态），值得先把 spec 里的「待确认」验证方法落成可自动化用例（mock closed 状态注入），否则该红线永远裸奔。

### 计划本身过时的条目

- 「运行现有 **183** 项测试」：现全量 394（392p+2xf），基线数字失效，应改为「以最近一次全量数为准的滚动基线」。
- 边界「**不提交、不推送**最终测试改动；由用户检查后决定」：与 09-05 实践冲突——bd61004/340bb59 已直接提交入库，说明用户口径已改为提交制，PLAN 边界条款需修订，否则下个执行方会困惑。
- 验收命令为 PowerShell 口径 + coverage 三连：命令仍有效，但 07-14 之后从未例行执行，建议把「每次测试批次提交前跑 coverage report 并把两行数字写进 commit message 或 PLAN-REVIEW-LOG」写进计划，替代一次性验收。

## 四、零改动声明

本次仅新增本报告文件；未修改任何生产代码、测试文件或计划文档；只运行了 `pytest`（tests/ 目录）与 `git show --stat`；未运行任何回测/交易/流水线脚本；报告不含任何资金数值结论（仅测试数量与状态）。
