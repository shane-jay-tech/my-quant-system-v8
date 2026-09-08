# S4 盘点补强：f-string/变量拼接路径漏检复核（2026-09-09）

> 执行：GLM-5.3-Flash 夜间执行班（任务 20260909-053502-qs4f，零改码）。观察时点 2026-09-09 06:4x，HEAD=22f8cdd。
> 方法：在 qs40 五类模式之外，补 5 类检索口径（f-string 路径字面量 / Path(f"…") 构造 / os.path.join 变量段（含 _dir/dir/folder/path 变量名）/ "D:/" 正斜杠混写 / open·glob 的 cwd 相对路径依赖），全仓 .py 独立扫描后与 qs40 的 79 文件清单对照。

## 一、结论：清单 79 → **82**（漏检 3 文件，均已补录归批）

| 漏检文件 | 证据（file:line + 形态） | 归批建议 |
|---|---|---|
| trade_analyzer.py | :12 `os.path.join(base_dir,…)`、:23/:191/:207 `os.path.join(base_dir,'results'/'data',…)`——base_dir 变量段拼接，qs40 的 BASE 字面模式未覆盖 | **S4-c**（策略/回测分析层） |
| fetch_stock_data.py | :367 `os.path.join(output_dir,…)`——output_dir 变量段拼接 | **S4-b**（数据入口层） |
| utils/trading_calendar.py | :23/:44 `os.path.join(data_dir,…)`——data_dir 为函数参数（路径由调用方传入），本体随调用方迁移 | 随 S4-b（其消费方 check_trading_day/watchdog 所在批）；本体只需签名兼容 |

## 二、无漏部分的抽查说明

- **f-string 路径字面量（f"…/data|results|…"）**：全仓 0 命中——本仓无 f-string 内嵌路径写法；
- **Path(f"…") 构造**：0 命中；
- **"D:/ 正斜杠混写**：0 命中（唯一盘符绝对路径仍是 tests/test_v87_review_refactors.py 的反斜杠形态，qs40 已录）；
- **cwd 相对路径依赖（open/glob 裸相对）**：0 命中——脚本层统一走 BASE 拼接，与 qs40 清单口径互证；
- **join_var_segment**：命中 64 文件，其中 61 文件已在原 79 清单（BASE 拼接模式已覆盖），净新增仅上表 3 文件——qs40 原口径对「BASE 字面量拼接」的覆盖是充分的，漏检集中在**变量段拼接**这一形态。

## 三、对分批方案的影响
- S4-b 追加 fetch_stock_data.py:367 一处；S4-c 追加 trade_analyzer.py 四处；S4-b 附加 utils/trading_calendar.py 的签名兼容注记；
- 其余批次与分批结构不变；R2 快审清单不变（新增 3 文件均无凭据/默认值语义，属纯路径迁移）。

## 四、遗留问题
- 变量段拼接的检索依赖变量命名启发式（_dir/dir/folder/path），语义级拼接（如 path = root + sub）仍可能漏——S4-a 实施时建议以 ast 的 os.path.join 调用点全量枚举做最终对账；
- 本报告与 qs40 盘点合并后，收敛面总计 **82 文件**。
