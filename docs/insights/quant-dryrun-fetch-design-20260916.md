# quant 数据取数类写入脚本 dry-run 保护设计稿（q916-04，2026-09-16，只出设计零实现）

- 上游：q914-32 写入路径矩阵（`docs/insights/quant-write-path-matrix-20260914.md`，根仓）——48 脚本/83 写点/dry-run 仅 6 个；本单取其「次高优」取数类一档＝fetch_history.py／fetch_minute_kline.py（矩阵 B 段「3/3 写点、无旗标、高（写行情数据文件）」两行，与本稿设计表行数一致）。
- 零实现声明：`git diff --stat` 为空（见第四节自证）；未改任何写入脚本；未碰持仓/下单/风控脚本；不 push。

## 一、逐脚本写点与副作用（静态判定，全部可判，无待核条目）

### fetch_history.py（矩阵计 3 写点＋1 备份副作用）

| # | 位置 | 写点/副作用 | 说明 |
|---|---|---|---|
| W1 | `:334`（EM fastpath 追加） | `em_new.to_csv(HISTORY_FILE, mode='a')` | write_lock 内流式追加；前置 W0 |
| W0 | `:327` | `shutil.copy2(HISTORY_FILE → .bak)` | 写盘前备份（rg to_csv 口径不计，副作用需一并拦） |
| W2 | `:361`（`save_increment`） | `df_new.to_csv(HISTORY_FILE, mode=mode)` | 抓取循环内逐批流式追加 |
| W3 | `:502-504`（Step4.5 最终去重） | `to_csv(HISTORY_FILE+'.tmp')` ＋ `os.replace(tmp, HISTORY_FILE)` | 原子重写（压平多版本） |
| S1 | `:383` main 开头 | `os.makedirs(DATA_DIR, exist_ok=True)` | 幂等目录副作用（可豁免，设计上保留） |

前置读依赖：读当日 `stock_YYYYMMDD.csv` 取股票池（`:377` 附近）；读 `history.csv` 构建 `{代码:最新日期}` 增量映射。无 argparse（裸 `main()`）。

### fetch_minute_kline.py（矩阵计 3 写点＋1 删除副作用）

| # | 位置 | 写点/副作用 | 说明 |
|---|---|---|---|
| W1 | `:229`（`save_minute_data`） | `df.to_csv(MINUTE_DIR/{code}.csv)` | 每股分钟K线逐文件写 |
| W2 | `:294` | `.minute_degraded` 标记 json 写 | 成功率低于阈值时写降级标记 |
| W2' | `:299` | `os.remove(.minute_degraded)` | 达标时删标记（删除副作用，需一并拦） |
| W3 | `:304` | `_fetch_status.json` 状态写 | 每轮收尾必写 |

前置读依赖：读股票池与已存分钟文件；主流程拉取 eastmoney/sina（网络）。无 argparse。

## 二、dry-run 契约设计（逐脚本）

### 共同契约（统一模板）

- **参数名**：`--dry-run`（argparse 互斥组亦可后接 `--dry-run-plan`，见下）；无值旗标，默认 False。
- **打印形态**：每个被拦写点一行 `[DRY-RUN] W# <动作> -> <目标路径> (<行数/文件数> rows/files, mode=append|rewrite|marker)`；收尾汇总行 `[DRY-RUN] would-write: N 个写点, 目标=<路径列表>; 实际写盘 0 字节`。
- **退出码**：0（ dry-run 预演成功也算成功，便于巡检 cron 直接复用；区别于缺前置文件时的 1）。
- **分支差异**：网络拉取照常执行（保证「将写入什么」真实）；仅写点函数体首行旗标短路。二级 `--dry-run-plan`＝零网络：只读现有盘上状态输出增量计划（股票池数、待补代码数、目标文件、追加 vs 重写判定），适合白日快速巡检。
- **幂等**：dry-run 零写盘 ⇒ 天然幂等，可重复执行；`--dry-run-plan` 同理且不产生网络流量。
- **回滚**：dry-run 无需回滚。非 dry-run 路径沿用既有保护（fetch_history 的 .bak 备份＋tmp+os.replace 原子重写；fetch_minute 的按文件覆盖＋状态 json），本设计不改动它们。

### fetch_history.py 专属

- 拦截点＝W0/W1/W2/W3 四处（W0 备份也打印 `[DRY-RUN] W0 would-backup -> history.csv.bak`）；W1/W2 拦截时照常返回内存 df 供后续计数，仅不落盘；W3 拦截时打印「将去重压平为 N 行」后跳过 tmp+replace。
- 收尾 Step5 验证段照常读盘打印现有状态，前缀不加 DRY-RUN（区分「现有」与「将写」）。

### fetch_minute_kline.py 专属

- 拦截点＝W1/W2/W2'/W3 四处；W2' 删除拦截打印 `[DRY-RUN] W2' would-remove .minute_degraded`；`is_minute_degraded()` 读取逻辑不动。
- 降级统计照常计算（基于拉取结果），只是不落标记不落状态。

## 三、统一模板与逐脚本落地切片（每片 ≤40 分钟，含依赖顺序）

**统一模板**（文字版，不附代码）：`parse_args()`（仅 `--dry-run`／`--dry-run-plan` 两旗标）→ 模块级 `DRY = False` → 每写点函数首行 `if DRY: print('[DRY-RUN] ...'); return None（或内存值）` → main 收尾汇总行。测试切片为每脚本补 1 个 tmp_path 特性测试：置 `--dry-run` 跑 main 后断言目标路径**不存在**、退出码 0、stdout 含 would-write 汇总。

| 切片 | 内容 | 预算 | 依赖 |
|---|---|---|---|
| 切片1 | fetch_history.py：argparse 骨架＋四拦截点＋汇总行＋1 特性测试 | ≤40min | 无（先行，模板定调） |
| 切片2 | fetch_minute_kline.py：argparse 骨架＋四拦截点（含 remove 拦截）＋汇总行＋1 特性测试 | ≤40min | 依赖切片1（复用模板） |
| 切片3 | 两脚本 `--dry-run-plan` 零网络档＋全量回归（pytest tests 全绿核对） | ≤40min | 依赖切片1+2 |

依赖顺序＝1 → 2 → 3 串行；切片1 未落地前切片2 不得先行（模板漂移风险）。

## 四、设计表（完成标准对齐：行数＝矩阵取数类条目 2 行）

| 脚本路径 | 写点数 | dry-run 契约 | 切片建议 |
|---|---|---|---|
| `fetch_history.py` | 3（rg 口径）＋W0 备份副作用，共拦 4 处 | `--dry-run` 拦 W0-W3 打印 would-write、退出码 0、网络照常；`--dry-run-plan` 零网络只读计划；幂等（零写盘）；回滚不适用（非 dry-run 沿用 .bak＋原子重写） | 切片1（≤40min，先行）＋切片3 的 plan 档 |
| `fetch_minute_kline.py` | 3（rg 口径）＋W2' 删除副作用，共拦 4 处 | `--dry-run` 拦 W1/W2/W2'/W3、退出码 0、网络照常；`--dry-run-plan` 零网络；幂等；回滚不适用（按文件覆盖＋状态 json 沿用） | 切片2（≤40min，依赖切片1）＋切片3 的 plan 档 |

## 五、零改动自证与声明

```
$ git diff --stat        （本单全程）
（空输出——设计稿为纯新增文档，无任何代码实现改动）
```

- 未实现 dry-run、未改任何写入脚本、未碰持仓/下单/风控相关脚本（auto_heal/position_sizer/sim_trade/evolve_strategy 均未打开写模式）、不 push。
