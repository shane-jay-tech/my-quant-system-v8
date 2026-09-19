# quant `evolve_strategy.py` 写点 dry-run 设计稿（q918-21，**只设计不实现**）

- 设计：2026-09-19 21:4x（班次 `qoder-rev-20260919-1020`）。零实现、零执行、零 `.py` 改动。
- 锚点：`D:/code/docs/insights/quant-write-path-matrix-20260914.md:26` 原文
  「`| evolve_strategy.py | 6 | 无 | **高**（写策略库） |`」——矩阵里"最高优未保护项"。
- **一句话结论**：矩阵那行的"6"是**函数数**，磁盘实况是 **6 个函数里的 9 条写语句**（含 2 条 `makedirs`）；
  真正的高危不是"写策略库"这一句，而是它**用正则改写 `enhanced_backtest.py` 的源码常量**（:400-419），
  且备份名按天命名 ⇒ **同日第二次采纳会覆写第一次的备份**（:433-434）。
  好消息：仓内**已有现成的 dry-run 语义可复用**（`evolve_daily_light.py:27/270` 的 `cfg_get('evolve.dry_run_only')`），
  本设计不发明新开关。

## 一、实况核对（先纠矩阵口径，免得照着 6 去设计）

```bash
cd /d/code/my-quant-system-v8
awk 'BEGIN{fn="module"} /^def /{fn=$2; gsub(/\(.*/,"",fn)} /os\.makedirs|open\([^,]*, .[wa]|shutil\.copy/{print NR": "fn}' evolve_strategy.py
```

| # | file:line | 所在函数 | 写形态 | 目标 | 幂等／覆写风险 | 可回滚性 |
|---|---|---|---|---|---|---|
| W1 | `:79` | `mark_pending_if_needed` | `os.makedirs(dirname(KB_FILE))` | 知识库目录 | `exist_ok=True`，无风险 | 不需回滚 |
| W2 | `:80-81` | `mark_pending_if_needed` | **整文件 `'w'` 覆写** | `KB_FILE`（`core.paths`，实际 `docs/knowledge/quant-kb.md`） | 有幂等守卫：`:66` `if '[待验证]' in content: return True` ⇒ 不会重复追加 | **低**（覆写式；内容 = 读入＋追加两段硬编码文本） |
| W3 | `:113-114` | `record_regression` | 追加 `'a'` | `memory.md`（仓根，`:25`） | 每次都追加，无去重 | 中（追加可 tail 撤销，但要按行匹配） |
| W4 | `:284` | `generate_ab_report` | `os.makedirs(REPORTS_DIR)` | `reports/` | `exist_ok=True` | 不需回滚 |
| W5 | `:375-376` | `generate_ab_report` | 覆写 `'w'` | `reports/ab_test_{today}.md`（`:374`） | **同日第二次运行覆写第一份报告**（文件名只到日） | 中（丢历史报告，无备份） |
| W6 | `:417-418` | `apply_params_to_backtest` | **覆写源码 `'w'`** | `enhanced_backtest.py`（`:31 BACKTEST_FILE`） | 由 `re.sub` 逐常量替换（`:401-414`，5 个常量），`if changes:` 才写 ⇒ 无变化不写 | **最低**：改的是**生产码本体**，且 `re.sub(r'MA_LONG\s*=\s*\d+')` 这类模式**只吃整数**（`MAX_SINGLE_POSITION=0.25` 那种小数值不在其中，`evolve_daily_light.py:30-35` 允许 0.05 步进） |
| W7 | `:434` | `adopt_if_accepted` | `shutil.copy` 新建备份 | `enhanced_backtest_backup_{today}.py`（`:433`） | **同日第二次采纳 → 覆写同一备份文件** ⇒ 第一次的"改前态"永久丢失 | 高（这一步本身是回滚手段，它自己却会被覆写） |
| W8 | `:452-453` | `adopt_if_accepted` | 追加 `'a'` | `memory.md` | 无去重 | 中 |
| W9 | `:473-474` | `mark_pending_tested` | 整文件 `'w'` 覆写 | `KB_FILE` | 守卫在位：`:471 if old in content:` ⇒ 找不到就不写（不会空写） | 低 |

⇒ 矩阵的"6"＝函数数（`mark_pending_if_needed`／`record_regression`／`generate_ab_report`／
`apply_params_to_backtest`／`adopt_if_accepted`／`mark_pending_tested`），写语句数＝**9**。
**设计要按 9 条铺拦截点**，否则两条 `makedirs` 与"copy 备份"这类会被漏掉——而 W7 恰好是全套里唯一的安全网。

## 二、三个必须在设计阶段点名的危害（不是"写文件"这么轻）

1. **W6 写的是源码，不是数据。** `apply_params_to_backtest` 把 `enhanced_backtest.py` 里的
   `MA_LONG/RSI_LOW/RSI_HIGH/TOP_N/BACKTEST_DAYS` 用正则原地替换。失败模式不是"数据错"，是**回测程序本身变了**：
   下一次任何人的 A/B、任何人的日报跑的都是被改过参数的回测器。⇒ 这一条的 dry-run 优先级高于其余 8 条之和。
2. **W7 的安全网有洞。** 备份文件名 `enhanced_backtest_backup_{today}.py` 只到日 ⇒ 同一天两次采纳，
   第二次 `shutil.copy` 直接把第一次的备份覆盖掉（`copy` 不改名不报错）。
   设计里必须把"备份名带时分秒＋冲突则拒绝"列为**前置项**，否则 dry-run 之外还留着一条不可回滚路径。
   （注：只描述机制与文件名构造行 `:433`，不评判采纳判据本身。）
3. **W5 与 W2/W9 是"覆写 + 无原子性"。** `open(path,'w')` 先截断再写：进程在中途被杀 ⇒ 目标文件变半截甚至空。
   仓内已有 `utils/file_io.py:12 atomic_write_json`（临时文件＋`os.replace`），**文本侧没有对等函数** ⇒
   切片表里给一条"补 `atomic_write_text`"的活，W2/W5/W9 三处共用。

## 三、拦截点选择（复用既有语义，不另发明）

现成口径（实测在盘）：
```
evolve_daily_light.py:27   DRY_RUN_ONLY = cfg_get('evolve.dry_run_only', True)     # 默认 True
evolve_daily_light.py:270  if DRY_RUN_ONLY: 写 suggested_params 而非 current_params
core/pipeline.py:319       if "--dry-run" in argv: return run_all(dry_run=True)     # 步骤级 dry-run（只打印跑哪些步）
core/pipeline.py:85        "evolve_strategy": {args: ["--auto"], schedule: "thursday"}
```
⇒ 三个关键决定：
1. **同一个配置键**：`evolve_strategy.py` 用 `cfg_get('evolve.dry_run_only', True)`，与 light 驱动共用一把闸。
   两把闸意味着"改了 A 忘了 B"，而这条路径是被周四定时班触发的（`core/pipeline.py:85`）。
2. **加 `--dry-run` / `--apply` 一对 CLI**，落在 `main()`（`:479 is_auto = '--auto' in sys.argv` 旁边）。
   现在 `main()`（`:478`）只认 `--auto`（`:479`） ⇒ **定时班走的就是全写路径**，一行保护都没有。
   优先级：CLI `--apply` ＞ env/cfg ＞ 默认 dry-run（默认必须仍是 dry-run，与 `evolve.dry_run_only: True` 对齐）。
3. **写点级拦截，而不是入口级短路**。入口级（dry-run 时直接 return）会把"生成报告看看长什么样"这条
   真实需求也砍掉，人就会去关掉开关 ⇒ 拦截等于没做。契约：

| 写点 | dry-run 下的行为 | 打印口径 |
|---|---|---|
| W1/W4 | 不建目录（只打印将建的路径） | `[EVOLVE][DRY] makedirs <path>` |
| W2/W9 | 不写 KB，把"将要写入的 diff（新增段／替换段）"打到 stdout | `[EVOLVE][DRY] quant-kb.md +2 条 / 替换 [待验证]X→[已验证-已采纳]X` |
| W3/W8 | 不追加 memory.md，打印将要追加的那一行原文 | `[EVOLVE][DRY] memory.md += <entry>` |
| W5 | **报告照写，但写到临时/`reports/dry_run/` 子目录**，文件名加 `.dryrun` 后缀 | `[EVOLVE][DRY] 报告: reports/dry_run/ab_test_YYYYMMDD.dryrun.md` |
| W6 | **绝不写源码**；打印 5 个常量的 `旧值→新值` 与命中的正则数 | `[EVOLVE][DRY] enhanced_backtest.py MA_LONG 30→25 (1 hit)` |
| W7 | 不 copy；打印"若应用，将先备份到 <带时分秒的路径>" | `[EVOLVE][DRY] backup → enhanced_backtest_backup_YYYYMMDD_HHMMSS.py` |

   W5 是全表唯一的例外（"仍然写东西"），理由是报告是**只读产物、不参与后续计算**，
   而 dry-run 的价值恰恰是让人先看报告再决定；把它写进独立子目录以免与正式产物混在一起。
   `re.sub` 的"命中数"要打印：命中 0 次意味着常量名/写法漂了（`MA_LONG = 30` 变成 `MA_LONG=30` 之外的形态），
   那正是 W6 最危险的静默失败——今天 `changes` 非空但 `re.sub` 没改到东西，也照样整文件覆写。

## 四、回滚方案（按写形态分档，实现时照此配）

- **源码类（W6/W7）**：采纳前必须已经落成一个**不可覆写**的备份（W7 前置项：文件名带 `HHMMSS`，
  存在则拒绝并提示，不静默覆盖）；回滚＝copy 回来。
- **整文件覆写类（W2/W9/W5）**：`atomic_write_text`（临时文件＋`os.replace`）＋ 覆写前把旧内容留 `.bak-<ts>` 一份；
  KB 在 `docs/knowledge/` 下且**在 git 版本控制内**，所以真正的兜底是"跑之前工作树必须干净"——
  这条要写进 executor 提示词，比在脚本里再做一套快照更可靠。
- **追加类（W3/W8）**：追加单行，回滚＝删掉那一行；给 `record_regression` 加一条"同日同描述已存在则不重复写"
  的守卫（对齐 `evolve_daily_light.py:275-280` 已有的去重写法）。
- **目录类（W1/W4）**：不需要回滚。

## 五、切片表（实现顺序；每片可独立验收，仿 q916-04 切片体例）

| 切片 | 内容 | 触及写点 | 验收口径（实现单用） |
|---|---|---|---|
| S1 | 把 W7 备份名改成带时分秒＋冲突即拒绝 | W7 | 同日连跑两次采纳 ⇒ 两个不同备份文件，第二个不覆写第一个 |
| S2 | `cfg_get('evolve.dry_run_only', True)` ＋ `--dry-run/--apply` 接入 `main()`，默认 dry-run | 全部 | 无 flag 直跑 ⇒ 9 个写点零落盘（用 `git status --porcelain` 与 `ls reports/` 双向证明） |
| S3 | 写点级 stub：把 9 条写语句收进一个 `_emit(kind, target, payload)` 出口 | W1-W9 | `grep -c "open(.*, .w." evolve_strategy.py` 由 5 降为 0（写只剩 helper）；`grep -c 'shutil.copy'` 同理 |
| S4 | `utils/file_io.atomic_write_text`（现只有 json 版）＋ W2/W5/W9 改用它 | W2/W5/W9 | 中途 kill 测试：目标文件要么是旧的要么是新的，不得出现半截 |
| S5 | `re.sub` 命中数断言（命中 0 视为异常，拒绝写 W6） | W6 | 构造一个常量写法变形的样例 ⇒ 不写文件且退出码非 0 |
| S6 | W3/W8 追加去重（同日同描述） | W3/W8 | 连跑两次 ⇒ memory.md 只多一行 |

S1 先行的理由：它是**唯一的安全网**，现在却在覆写；顺序反了的话，做 S2 的验证过程中一次误采纳就丢了备份。

## 六、测试策略（本单一条都不写，只给桩法）

- 桩法与 `tests/test_kb_missing_sentinel.py:23`（已 import 本模块）同构：`import evolve_strategy as ev` ＋ `monkeypatch.setattr(ev, 'KB_FILE', str(tmp_path/'kb.md'))`
  之类，把 `KB_FILE / MEMORY_MD / REPORTS_DIR / BACKTEST_FILE` 四个模块级常量全部指到 `tmp_path`
  ——**绝不允许测试写真实 `enhanced_backtest.py` 或 `memory.md`**（W6 是源码）。
- 需要一条"负例"钉死默认值：`evolve.dry_run_only` 缺失时（`cfg_get` 走默认）必须落在 dry-run 分支。
- 现有 `tests/test_s4e_no_base_joins.py:25` 对本文件钉着 `6` 这个数（路径拼接计数）；S3 改写出入口时
  要顺手确认那条断言的口径不被误动，别把它改成"跟着本设计走"的活断言。

## 七、边界与非目标

- **不改进化判据**：`check_safety_lock`（`:86` 起）、A/B 指标解析（`:266-274` 一带的"字符串转数值"）、`SAFETY_LIMIT`（`:33`）
  与所有阈值/数值一字不碰——那些属"资金与统计数值结论"红线域，本稿只谈**落盘副作用**。
- 不引入新依赖、不引模板引擎；`re.sub` 改写源码这条路本身是否该换成"参数外置到配置文件"
  是个**架构问题**（换掉后 W6 整类消失），本稿标注但不纳入切片：那需要 `enhanced_backtest.py` 侧配合，跨两个入口。
- `mark_pending_if_needed` 追加的两条 `[待验证]` 是**硬编码文本**（`:70-73`）——意味着知识库的新实验条目
  不是由进化产生，而是人写死在脚本里。这不是 dry-run 问题，但会影响 S2 的"零落盘"验收口径
  （第一次真跑必然写这两条）。留给日间判断是否改成读外部输入。

## 八、零改动自证与复现

- 本文件是**唯一新增**；`evolve_strategy.py`、`enhanced_backtest.py`、`memory.md`、`reports/` 一字未动，
  **零 `.py` diff**（完成标准）。复现：
```bash
cd /d/code/my-quant-system-v8
git status --porcelain evolve_strategy.py enhanced_backtest.py memory.md reports/ | wc -l   # 期望 0（未动）
wc -l docs/insights/quant-dryrun-evolve-design-20260918.md                                   # 本稿
grep -n "BACKTEST_FILE\|MEMORY_MD\|REPORTS_DIR =" evolve_strategy.py                         # :23/:25/:31 路径常量
sed -n '433,434p;401,419p' evolve_strategy.py                                                # W7 备份名 / W6 正则改写
grep -n "dry_run_only" evolve_daily_light.py | head -2                                        # :27 现成开关
grep -n '"evolve_strategy"' core/pipeline.py | head -1                                        # :85 定时班入口（args --auto）
```
