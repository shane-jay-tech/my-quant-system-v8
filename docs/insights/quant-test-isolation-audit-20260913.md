# quant 测试隔离规范审计（d913b-42，2026-09-13）

任务：只读扫描 tests/ 隔离违规（网络/真实 data 路径/未 tmp_path 写文件/环境变量/生产 sim_results），输出分类清单，修最严重 1 例。

## 一、工具

`tools/audit_test_isolation.py`（纯 stdlib 正则扫描，只读，退出码恒 0；`--severity` 可过滤）。
五类规则：net(high)/sim-results(high)/data-path(medium)/abs-write(medium)/env-write(low)。

## 二、实盘清单（`--root tests`，50 文件，12 命中——逐条人工核实后 **11 误报 + 1 真违规（本班新码，已修）**）

| 文件:行 | 类别 | 核实结论 |
|---|---|---|
| test_sim_trade.py ×9 | abs-write | **误报**：`isolated_sim_trade` fixture 已把 RISK_CONFIG_FILE/STATE_FILE monkeypatch 到 tmp_path，open 写的是补丁后路径 |
| test_position_sizer.py:57 | abs-write | **误报**：data_dir 为 tmp_path 派生 |
| test_v87_review_refactors.py:197 | abs-write | **误报**：state_path = tmp_path（多行上下文，扫描器同行抑制不足） |
| test_bark_push_charac.py:10 | net | **误报**：import requests 但全部走 _FakeResp+monkeypatch，零真实请求（文件头声明） |
| **tests/test_timefixture_characterization.py（d913b-36 新码）** | abs-write | **真违规**：A1/A2/A3/B1/B2 直接 `newbie_protection.ACTIVITY_FILE = ...`、`multi_strategy.DATA_DIR = ...` 裸赋值模块属性——monkeypatch 缺位导致**属性跨测试泄漏**（同会话后续用例会看到被改的 DATA_DIR） |

## 三、修例（真违规 1 例=本班新码自纠）

test_timefixture_characterization.py 五处模块属性赋值改为 `monkeypatch.setattr(...)`（A1/A2/A3/B1/B2），签名加 monkeypatch 参数；B3 经核实不落盘，不添加假隔离。修后：该文件 **19 passed**、全量 **544 passed + 2 xfailed**（与修前一致，无新增失败）。

## 四、git status 口径（完成标准④）

修例前后 `git status --porcelain data/` 输出均为空——data/ 零文件被改。

## 五、验收

- 工具退出 0 并输出分类清单 ✓；选定修例后该文件回归通过 ✓；全量无新增失败 ✓；data/ 零改动 ✓。
- 禁令遵守：未放松任何断言（修例是隔离机制非断言变更）、无资金数值断言、未联网。

## 六、遗留问题（TopN 待办）

1. 扫描器同行抑制升级为「跨行上下文」（消除 v87/position_sizer 型误报）——日间小改。
2. 扫描器增加「模块属性裸赋值」规则（本例违规类别，现靠人肉）——识别 `mod.ATTR = ...` 且 ATTR 在模块内为路径常量的形态。
3. test_bark_push_charac 可补 `requests` 未打桩即调用的防回归哨兵（monkeypatch requests.post 抛错），防未来新增用例绕过 mock。

## 七、v2 扫描器增强（d914-07，2026-09-14 补记）

tools/audit_test_isolation.py 升级：①跨行上下文（open 写路径引用 tmp_path 派生变量时跨行豁免，修复 position_sizer/v87 两例误报根因）；②裸赋值规则 bare-assign（`mod.ATTR = …` 绕过 monkeypatch 的泄漏形态，中危）；③防回归哨兵 tests/audit_test_isolation_scan.py（6 用例 golden：已知误报不报+已知违规必报）。

增强前后对比：v1（12 命中：1 真违规+11 误报，无 bare-assign 能力）→ v2（15 命中：bare-assign 新抓 1 条真违规+自扫描 golden 文件自指 2 条 data-path 文本+其余同 v1 误报群）。单测 tests/audit_test_isolation_scan.py 6 passed。
