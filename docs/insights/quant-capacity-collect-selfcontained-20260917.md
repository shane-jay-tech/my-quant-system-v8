# capacity_collect.py 自包含化（916p-a1-020，2026-09-17）

## 一、脆弱性复现（改前，自然发生）

```
$ python scripts/capacity_collect.py
Traceback (most recent call last):
  File "scripts\capacity_collect.py", line 10, in <module>
    dry = set(open(os.path.join(TMP, "q32_dryrun.txt")).read().split())
FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\...\\Temp\\q32_dryrun.txt'
（exit=1——任务书撰写时 %TEMP% 两名单文件「恰好存在」，核验时已被清理＝脆弱性实证）
```

基线 N 获取：任务书禁令允许新建（非覆盖）——以**空名单文件**放回 %TEMP% 后跑 HEAD 版（14e3ea2 原版）：

```
$ git show HEAD:scripts/capacity_collect.py > old_cc.py && python old_cc.py
scripts-with-write: 49 | total-points: 84 | dryrun-flagged: 0 | prior-d91437-covered: 0   (exit=0)
```

## 二、改造内容（扫描口径零改动：PAT 与 -g 排除规则逐字保留）

①argparse 化：`--dryrun-list`／`--prior-list`（默认仍指 %TEMP% 原路径，向后兼容；可传空串按空集统计）；②名单缺失打印可读中文错误（含路径与补救办法）并 **exit 2**，无裸 traceback；③`shutil.which('rg')` 检测，缺失给安装提示 exit 2；④`--no-rg` 干跑；⑤两名单可选，缺省空集时旗标列显示 `-`。

## 三、三种情形实测（命令与输出同段）

```
①正常（现 TEMP 有空名单，默认路径）：
  scripts-with-write: 49 | total-points: 84 | dryrun-flagged: 0 | prior-d91437-covered: 0
  → 与改造前 HEAD 版首行完全一致（N=49/points=84）✓
②缺输入：python scripts/capacity_collect.py --dryrun-list %TEMP%\__not_exist__.txt
  → stderr: [capacity_collect] 错误：dry-run 名单不存在：…\__not_exist__.txt。补救：…
  → exit=2，无 Traceback ✓
③--help：exit=0，输出含 --dryrun-list/--prior-list/--no-rg ✓
  （rg 屏蔽情形以 --no-rg 干跑覆盖；shutil.which 检测分支为代码路径④，本机 rg 在 PATH 无法物理屏蔽）
```

## 四、零影响自证

- `git diff -- requirements.txt` 输出为空（零新增第三方依赖）。
- `python -m pytest -q` → 660 passed, 4 skipped, 2 xfailed（failed=0，零影响）。
- 备注：本次核验在 %TEMP% 新建了**空** q32_dryrun.txt/q32_prior.txt（原不存在，未覆盖任何既有文件）。

## 五、验收对照

- ✅ 默认运行 exit=0 且首行 N 与改造前一致（两次输出同段）。
- ✅ 缺输入 exit=2 且可读提示、无 Traceback（$LASTEXITCODE 语义以 bash $? 实测贴报告）。
- ✅ --help 识别新参数。
- ✅ requirements 零 diff；全量 failed=0。不 push。
