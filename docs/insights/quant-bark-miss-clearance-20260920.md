# bark_sender 残留 miss 清零（q920-09 builders / q920-10 parsers）

- 日期：2026-09-20｜仓库：D:\code\my-quant-system-v8
- 性质：**只补测试，零生产码改动**
- 复跑命令：
  `python -m pytest tests/ -q --cov=bark_sender.builders --cov=bark_sender.parsers --cov-report=term-missing`

## 〇、锚点漂移（先说清楚：任务书里的数字已经过期）

任务书引的是 q918 时的基线（`quant-test-baseline-20260918.md`），**实测已不是那个数**：

| 模块 | 任务书写 | 本单实测（改动前） | 本单实测（改动后） |
|---|---|---|---|
| `bark_sender/builders.py` | 21 miss / 91% | **13 miss / 94%**（232 stmts） | **0 miss / 100%** |
| `bark_sender/parsers.py` | 6 miss / 96% | **5 miss / 97%**（155 stmts） | **0 miss / 100%** |

漂移原因：q918 之后已有其他批次补过一轮（本单未追溯具体单号）。按「锚点有漂移则按磁盘实况修正并留痕」执行。

## 一、q920-09 builders：13 行逐行归因（全部可测，无「不可测」项）

改动前 Missing = `25-26, 125-130, 209, 211, 213-214, 223`

| 行号 | 所在 | 分支语义 | 判定 | 归因 |
|---|---|---|---|---|
| 25-26 | `_cfg_number` | `except Exception: return float(default)` —— cfg 读取异常/返回 None/返回非数字三条都回退默认值 | **可测** | 未覆盖：既有测试全部走 cfg_get 正常返回的路径 |
| 125-130 | `build_bark_message_simple` | `if n_show > 1:` 拼「备选:」段（含备选行的风险档位） | **可测** | 未覆盖：既有 case 只传 1 只股票（n_show=1 不进分支） |
| 209 | `_build_portfolio_risk_addendum` | `if c.get('warning'):` 相关性预警行 | **可测** | 未覆盖：risk_report.json 的桩数据没带 correlation.warning |
| 211 | 同上 | `for a in (r.get('recommended_actions') or [])[:3]` 建议动作行（含 [:3] 截断） | **可测** | 同上，桩数据 recommended_actions 为空 |
| 213-214 | 同上 | `except Exception: return ""` —— 风控附录坏 JSON 时返回空串而非抛异常 | **可测** | 未覆盖：没人喂过坏 JSON |
| 223 | `_build_broker_orders_addendum` | `if not files: return ""` —— 目录存在但零文件 | **可测** | 未覆盖：既有 case 只走「目录不存在」或「有文件」 |

**新增** `tests/test_bark_builders_charac2_q920_09.py`（6 例，全绿）：
`_cfg_number` 三路回退＋正常路径不被误伤 / simple 模板备选段（2 只出现、1 只不出现、4 只只展示 2 条备选）/
组合风控附录的两行拼接＋`[:3]` 截断＋无预警反向对照 / 坏 JSON 与目录缺失两种空串 /
券商订单附录「目录在但空」＋「目录不在」＋「有文件」三态。

## 二、q920-10 parsers：5 行逐行归因

改动前 Missing = `11-13, 114-115`

| 行号 | 所在 | 分支语义 | 判定 | 归因 |
|---|---|---|---|---|
| 11-13 | `find_latest_report` | 整函数：glob `results/pick_*.md` → `sorted(reverse=True)[0]`，无文件返回 None | **可测** | 未覆盖：该函数被 `send_to_bark.py:84` 调用，但测试从没直接测过它 |
| 114-115 | `parse_performance_tracking`（def 在 `:93`） | `overall` 正则命中时补 `win_rate`/`avg_ret` | **可测** | 未覆盖：既有 case 只喂「有 previous 行、无 Overall 行」的桩 |

**新增** `tests/test_bark_parsers_charac2_q920_10.py`（5 例，全绿）：
`find_latest_report` 空目录/多文件（忽略非 `pick_*`）返回完整路径/目录不存在不炸；
`parse_performance_tracking` 的 previous＋overall 双提取、无 Overall 行时 overall 保持 `{}`、文件缺失返回 None。

## 三、结果与自证

```
$ python -m pytest tests/ -q --cov=bark_sender.builders --cov=bark_sender.parsers --cov-report=term-missing
Name                      Stmts   Miss  Cover   Missing
-------------------------------------------------------
bark_sender\builders.py     232      0   100%
bark_sender\parsers.py      155      0   100%
-------------------------------------------------------
TOTAL                       387      0   100%
848 passed, 4 skipped, 3 xfailed in 38.29s
```

**两个模块零残留 miss，全量 0 failed。** 新增 11 例（builders 6 ＋ parsers 5）全部为 characterization
（钉现行为），**未改任何生产码**，故不可能改变资金/风控/仓位相关行为。

## 四、遗留

1. 本单只清 `bark_sender.builders` / `bark_sender.parsers` 两个模块；`ops/health.py` 仍有 63 miss
   （81%，见 `quant-test-baseline-20260918.md` 的更大缺口）——属后续批次，本单未涉。
2. 两处测试都依赖 `monkeypatch.setattr(模块同名变量)` 隔离磁盘（`DATA_DIR`/`RESULTS_DIR`/`BROKER_ORDERS_DIR`），
   若将来这些常量改成函数内局部计算，测试会静默失去隔离——登记为脆弱点。
