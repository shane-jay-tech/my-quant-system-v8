# quant S4 批 c/d R2 快审 4 条 MINOR/SUGGESTION 处置清单（2026-09-12 夜间执行班，任务 p911r-38，零改码）

> 执行：GLM-5.3-Flash 夜间执行班 sweep-20260911-2300。来源：`docs/insights/s4-cd-r2-diff-review-20260911.md（量化仓）`（38b08c4）。**未改任何代码；未 commit/push。** 现状核对均以只读 grep 实查（标注「现值」）。

## 一、处置表（4/4 条）

| ID | 问题原文（摘） | 影响 | 处置选项 | 现状核对（现值） | 需拍板 |
|---|---|---|---|---|---|
| S4CD-1 (MINOR·可维护) | `bark_sender/config.py:17` 顶层 `sys.path.insert(0, _PROJECT_ROOT)` 污染 sys.path | 导入副作用；理论上同名模块遮蔽 | ①改 importlib 按绝对路径加载（config.py:17 替换）②由调用方保证仓根 ③不改（卫生问题） | **仍在**（grep 实查 :17 命中） | 否（低危卫生项，随下次 bark 改造顺手处理） |
| S4CD-2 (MINOR·可观测) | `core/secrets.py` 解析失败告警 print 被删（channels.py 原告警改走 get_secret_object），损坏时线索变少 | 排障线索变少 | 在 `core/secrets.py` `_load_kv` 失败路径（:97 起，except 分支）加一次性 stderr 告警（不落密钥值） | **仍在**（:97-96 无 stderr 输出，grep 无告警点） | 否；建议 S5 补测批顺带加（与可观测性一起） |
| S4CD-3 (SUGGESTION·一致性) | `get_secret` 走 env→.env.local→JSON，`get_secret_list`(:158)/`get_secret_object`(:177) 只走 env→JSON，解析顺序不一致埋坑 | 只写 .env.local 的 BARK_TOKENS 读不到（非回归） | list/object 复用 get_secret 解析顺序（保留列表/对象分支） | **仍在**（:158/:177 现值未变） | **是**（改解析顺序=行为变更，需确认无既有 .env.local 依赖方） |
| S4CD-4 (SUGGESTION·功能) | `ops/health.py` 硬编码 token 扫描仍只在 secrets.json 缺失时执行（else 分支） | 安全扫描时机不足 | 把扫描从 else 提为独立常跑检查项（`ops/health.py:234-246` 区域重组） | **仍在**（:237 hardcoded=False 初始化、:242 扫描在缺失分支内） | 否；建议随安全清单批 |

## 二、已被其他提交顺手解决的条目

- **无**。4 条现值全部仍以原形态存在（grep 复核 :17 / :97-96 / :158,177 / :234-246 均未变）。
- 相关但不同项：Bark 实推验证（唯一需实机项）已由 09437c0 的实推证据覆盖（修复后 BARK-1/BARK-2 双通道 Success，commit message 记录），k70a 时代的「环境变量层未验证」遗留实质闭合。

## 三、汇总建议

- S4CD-2/4（可观测+安全扫描）可并入 S5 补测/卫生批一次处理；S4CD-3 需拍板后单独小改；S4CD-1 随 bark 改造顺带。
- 优先级排序建议：S4CD-2（排障线索）> S4CD-3（一致性）> S4CD-4（安全扫描时机）> S4CD-1（卫生）。

## 四、零改动声明

仅只读 grep/git show；未改任何代码；未 commit/push；`git status --short` 无代码变更。
