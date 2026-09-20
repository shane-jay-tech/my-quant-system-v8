# `fetch_stock_data.py` 副作用点全量清点（q920-03，只读）

生成：2026-09-20 11:0x（任务单编号日期 20260919，执行落在当日白天）｜执行：Qoder 会话直执
口径：**只读审计**——`src`/脚本零改动，只产出本报告。上游：`q918-20-quant-dryrun-stockdata-index` 遗留 2
「其余副作用点没查全……可跑全文件 grep 对照复核」。

## 一句话结论

这个 417 行的爬虫**只有一个落盘写点**（当日快照 CSV），而且它是三处同类脚本里**唯一从一开始就把
`makedirs` 放在 `DRY` 判定之后**的（对照：`fetch_minute_kline.py` 的同类漏洞刚由 q920-02 修掉）。
dry-run 实跑零留痕、`would-write` 计数与 `DRY_HITS` 对账一致。真正没被 dry-run 管的不是"写盘"，
是**网络与延时**（契约如此）和**进程级可变全局 `DRY`/`DRY_HITS`**（被嵌套调用时会互相清账）。

## 二、清点方法（两套口径互校，不靠单一 grep）

| 口径 | 命令 | 抓到什么 |
|---|---|---|
| 正则 | `grep -nE "open\(\|to_csv\|makedirs\|..."` | 文本层面的写/删调用 |
| AST | 扫 `ast.Call` 的属性名 ∈ {`to_csv,to_json,makedirs,mkdir,remove,unlink,rename,replace,touch,dump,write_text,write_bytes,savefig,copy,copy2,copyfile,rmtree,open`} | 带**所属函数**归属，能识别"这行在哪个函数里" |
| 实跑对账 | 把 `DATA_DIR` 指到 tmp、三个 `fetch_*` 换成桩、`print` 截流，分别跑 `main(["--dry-run"])` 与 `main([])` | 目录真实留痕、`DRY_HITS` 内容、汇总行数 |

## 三、写点 × 已拦/未拦 矩阵（行号为磁盘实测）

| # | 行号 | 调用 | 所属函数 | dry-run 是否拦 | 证据 |
|---|---|---|---|---|---|
| W1 | **`:348`** | `df.to_csv(output_path, ...)` | `save_stock_snapshot:336` | ✅ 已拦（`:343` 的 `if DRY:` 早退，并记 `DRY_HITS`） | dry-run 跑完 tmp 目录 `[]`；默认跑完 `['stock_20260920.csv']` |
| W1′ | **`:347`** | `os.makedirs(out_dir, exist_ok=True)` | 同上 | ✅ 已拦（**位于 `if DRY` 之后**，与 q920-02 修复后的 `fetch_minute_kline` 同形态） | dry-run 后目录树为空（连空目录都没建） |
| — | `:313` | `... .replace(...)` | `fetch_10jqka:283` | ⚪ 非文件操作 | AST 里名字撞 `str.replace`，**误报**，实测是同花顺字段清洗的字符串替换 |
| — | 全文件 | 无 `open(`／`shutil.*`／`unlink`／`rename`／`touch`／`json.dump` | — | — | 两套口径均零命中 ⇒ **三个数据源函数一个盘都不碰** |

函数清单（8 个）：`get_sina_headers:18`、`get_em_headers:29`、`safe_request:41`、`fetch_sina:63`、
`fetch_eastmoney:184`、`fetch_10jqka:283`、`save_stock_snapshot:336`、`main:352`——
写点全部集中在 `save_stock_snapshot` 一个函数里，没有"藏在 fetch 中途顺手落盘"的情况。

## 四、`would-write` 计数对账（实跑，不是读代码猜）

```
main(["--dry-run"])  →  返回码 0
  DRY_HITS = [('W1', '<tmp>/stock_20260920.csv')]        ← 1 条
  汇总行   = "[DRY-RUN] would-write: 1 个写点, 目标=W1->...; 实际写盘 0 字节"
  tmp 目录内容 = []                                       ← 与"0 字节"自述一致
  [DONE] 行     = "150 stocks would save to ..."          ← 走的是 would-save 分支
main([])             →  返回码 0
  DRY_HITS = []                                          ← 非预演不记账（口径：hits 只记被拦的）
  tmp 目录内容 = ['stock_20260920.csv']
```
⇒ 声明的写点数（1）＝ `DRY_HITS` 长度 ＝ AST/正则扫到的盘操作数，**三方对齐**。

## 五、未拦项与建议（本单一律不改码，建议交日间拍板）

| 项 | 现状 | 建议 | 为什么现在不动 |
|---|---|---|---|
| N1 网络与延时 | dry-run 照拉三源、`safe_request` 每源最多 3 次退避、源间还 `sleep(2~4)` | 若要"零网络预演"，加 `--offline`（与 `--dry-run` 正交），并和 `fetch_history --dry-run-plan` 的"零网络"口径统一 | 现有契约明写"网络请求照常"（`:356` help 文本），改了就是改契约；且预演能看到数据源真实健康度，有独立价值 |
| N2 进程级可变全局 | `DRY`（`:332`）＋ `DRY_HITS`（`:333`）是模块级，`main` 进来先 `DRY_HITS.clear()`（`:360`） | 让 `main()` 返回本次 hits 快照，或把它们收进一个上下文对象 | 仪表盘/流水线若在同进程嵌套调用 `main()`，账会被内层清掉——属调用契约问题，牵连 `core/pipeline.py`，需协作评审 |
| N3 `sys.exit(1)` | 三源全挂时（`:401` 附近）无论是否 dry-run 都以 1 退出 | 保持 | 预演的目的之一就是暴露"今天数据源全挂"，把它改成 0 反而是掩盖 |
| N4 `[DONE]` 行取值 | `df['代码'].iloc[0]`／`df['涨跌幅'].min()` 等真跑统计 | 保持（dry-run 也已拉到真数据才有这些数） | 不涉及写盘；且统计口径归 AGENTS.md 的资金类护栏管，本单不碰 |

## 六、零改动自证与复现

- 本报告是唯一产出：`git status --porcelain fetch_stock_data.py` 为空；未新增测试文件（探针在临时目录里跑完即弃）。
- 探针要点（可粘贴，不落盘于仓内）：
  `fetch_stock_data` 的 `DATA_DIR` 在模块导入时由 `core.paths` 绑定，测试里必须
  `fs.DATA_DIR = str(tmp)` **改模块属性**（改 `core.paths` 无效，因为这里是 `from ... import` 的一次性绑定）；
  三个源函数直接换成返回 150 行桩数据的 lambda（**零网络**）；`print` 临时截流才能读到汇总行。
  目录留痕用 `sorted(p.name for p in tmp.rglob("*"))` 判空。
- AST 扫描脚本：第二节表格里那条属性名集合可直接复用；注意 `str.replace` 会撞名，需按接收者类型复核（本例 `:313` 即误报）。
