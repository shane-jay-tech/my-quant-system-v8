# 量化归档：history.csv 去重长期静默失效 + 代码格式双写残留修复（2026-09-20）

## 一、起因

夜间桥/后台任务 `fetch_history.py` 跑完退出码 1，日志末尾出现：

    [WARN] Final dedupe failed: unsupported operand type(s) for +: 'WindowsPath' and 'str'
    Final: 1226445 rows, 7073 unique stocks

## 二、定位到的三个缺口（都由同一条链路串起来）

| # | 缺口 | 证据 |
|---|---|---|
| 1 | **根因**：`final_dedupe()` 里 `tmp_path = HISTORY_FILE + '.tmp'`。生产 `HISTORY_FILE = DATA_DIR / 'history.csv'` 是 **Path**，Path + str 直接 TypeError → 被 `except Exception` 吞成一行 WARN → **最终去重从未真正执行** | 变异检验退回该写法，测试精确复现同一条报错 |
| 2 | **测试掩盖**：`tests/test_fetch_history_dryrun.py` 的 fixture 把 `HISTORY_FILE` 注入成 `str(p)`（注释自称「与历史语义一致」），str + str 恰好能过 → 生产的 Path 口径永远没被跑过 | fixture 第 25 行 |
| 3 | **没有探测器**：`data_validator.check_history_csv()` 只查日期连续性与新鲜度，**不查重复** → 48.6 万行重复躺了很久没人发现 | 校验器源码 |

## 三、修复前的数据实况

- 1,226,445 行，**486,614 行重复**（243,307 组 × 恰好 2 份，**逐字段完全相同**）
- 另有 **1,492 只股票存在两种代码写法**：不补零（`1` / `10` / `100`…，各 70 行，停在 2026-05-12）与补零孪生（`000001`…，161 行，到 2026-09-18）
- `drop_duplicates(['代码','日期'])` **合并不了**这两组（字符串不同）；而下游 11 处主要消费者
  （strategy / enhanced_backtest / sim_trade / position_sizer / multi_strategy / exit_advisor /
  factor_analysis / portfolio_risk / llm_analyst / replay_picks / strategy_feedback）读进来都会
  `astype+zfill` → 早就把两者当**同一只股票**，**同一交易日被算两遍**（MA/RSI 窗口凭空多一根 K 线）

## 四、改动

- `fetch_history.py`：`tmp_path = f"{HISTORY_FILE}.tmp"`（str/Path 两种口径都成立）；
  `final_dedupe()` 增加**代码规范化**（1–6 位纯数字 → zfill 6，同键优先保留原本 6 位的行）再压平；
  失败**保持非致命**但改成醒目 `[DEGRADED]` 横幅（说清后果 + 给修复命令）——
  刻意不改成 fatal：`update_history` 在流水线注册表里是 `fatal_on_fail=True`，
  清理失败若让 rc≠0 会掐掉当天整条流水线（选股/仓位/推送全没），代价远大于多留重复行
- `data_validator.py`：`check_history_csv()` 增加 (代码,日期) 重复检测（非致命 WARN）——
  这是补上**真正的探测器**
- `tests/test_fetch_history_dryrun.py`：fixture 改按**生产口径 Path** 注入；字符串口径另开一个 fixture；
  新增 3 条回归（Path/str 双口径去重、代码规范化、失败必须醒目不静默）

## 五、数据修复（两次，均先备份后校验）

备份（`data/` 已被 gitignore，不进仓库）：

| 备份 | 大小 | sha256 |
|---|---|---|
| `data/backups/history-20260920-preDedupe.csv` | 60.1 MB | `10c68c00d4dab6aba83b000eb91a528a427bbfe504e1deec2c1aef9d65c3061b` |
| `data/backups/history-20260920-preNormalize.csv` | 48.2 MB | `e93ffc675cb1c02fdc95a71e2671568c7fbf95b440531938ed288aee2f8045e1` |

结果：**1,226,445 → 983,138 → 880,291 行**，文件 60.1 → 43.35 MB，股票 5,581 只，日期范围
2025-11-21 ~ 2026-09-18（9-18 的 3,938 行完整保留）。

**独立无损证明**（不是用同一套逻辑自证）：
- 旧文件里 distinct (补零代码, 日期) 对 = **880,291**，与新文件行数**完全相等**
- 键集合相同；开盘/最高/最低/收盘/成交量 **5 列逐行一致**（差异 0）
- 1,492 个「只有不补零序列才有」的独有日期，丢失 **0** 个
- 校验器现状：`{'status':'OK','rows':880291,'unique_codes':5581,'duplicate_rows':0,'lag_days':0}`

## 六、测试

- `tests/test_fetch_history_dryrun.py`：5 → **9 例**；变异检验（退回 `Path + str`）→ 2 条转红且
  复现生产同款 TypeError
- 量化全量 pytest：**856 passed / 4 skipped / 3 xfailed**

## 七、补采一轮后的收敛结果（2026-09-20 17:18–19:05）

用户批准后重跑一轮 `fetch_history.py`（同一命令，显式捕获退出码）：

| 指标 | 首轮 | 补采后 |
|---|---|---|
| Sina 通道 | 3949 OK / 1615 FAIL | 4246 OK / **1318 FAIL** |
| 已到 2026-09-18 的股票 | 3,938 | **5,306**（+1,368） |
| 停在 2026-09-08 | 1,614 | **248**（-85%） |
| 停在 2026-05-12 | 1,486（不补零孪生） | **0** |
| 行数 | 1,226,445（含 486,614 重复） | **891,223** |
| 重复行 / 非 6 位代码 | 486,614 / 104,331 | **0 / 0** |
| 文件 | 60.1 MB | 43.89 MB |
| 退出码 | 1（不可复现） | **0** |

**修复在生产里被反向验证**：收尾日志出现
`[dedupe] 代码规范化 0 行 -> 6 位口径；压平 (代码,日期) 重复 285098 行` ——
① 「代码规范化 0 行」证明不再产生新的不补零写法；
② 「压平 285,098 行」证明**去重真的跑了**（修复前这一步是被 `except` 吞掉的）。
校验器：`{'status': 'OK', 'rows': 891223, 'duplicate_rows': 0, 'lag_days': 0}`。
日志留档：`docs/insights/fetch-history-run2-20260920.log`。

## 八、残留问题

1. **仍有 248 只停在 2026-09-08**（其中 242 只在今日池内）。样例是**连续号段**
   （`000520–000526`、`001285–001288`…），即按代码顺序抓取时被**整段限流**，不是停牌退市。
   周一 15:37 的 `update_history`（`fatal_on_fail=True`）会因 latest < target 自动再补。
   也可以随时手动再跑一轮——按两轮收敛曲线（1,614 → 248），第三轮大概率清掉大头。
2. **退出码 1 的旧悬案已基本了结**：同一条命令、同一包装形式，补采这轮**退出码为 0**，
   日志尾部同样是完整收尾。结合 `main()` 正常路径本就 `return 0`，判定首轮那个 1
   属**瞬时环境因素**（非脚本逻辑），不再追。今天流水线是周日跳过
   （`pipeline_20260920.log`：非交易日），未受影响。
3. `target_date = 2026-09-20`（周日，非交易日）——计划把非交易日当目标日，是否值得收紧口径，
   待评估。

## 八、元数据

| 项 | 值 |
|---|---|
| 任务类型 | 数据正确性修复（bug 根因 + 测试盲区 + 监控缺口 + 历史数据修复） |
| 难度分·档 | 6/12 → **L3**（影响面 2 / 风险 2 / 歧义 0 / 新颖 0 / 不可逆 1 / 长程 1） |
| 调用模型 | 未调用外部模型（证据为机械证明：逐行比对 + 键集合相等 + 变异检验） |
| 是否返工 | 否（一次定位，两次数据修复，各自先备份后校验） |
| 残留风险 | 见第七节 3 条 |

*归档：总指挥会话（DeepSeek Flash）｜ 2026-09-20*
