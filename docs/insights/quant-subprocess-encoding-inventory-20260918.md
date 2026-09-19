# quant subprocess 无 encoding 调用点全仓对照表（q918-17，**只读盘点，零改码**）

- 盘点：2026-09-19 23:4x（班次 `qoder-rev-20260919-1020`）。零 `.py` 改动。
- 锚点：`auto_heal.py` 的 `schtasks /create` 调用（锚点写 `:137`，现值 `:141`）＋「cb62427 只修 ops/health.py 两处；
  另 `core/pipeline.py:186`、`auto_heal.py:59/121`、`daily_pipeline.py:34` 同族」。
- **一句话结论**：全仓 subprocess 调用点 **9 处**（AST 实测），其中
  ① 锚点点名的 4 处里有 **1 处是误判**（`core/pipeline.py:186` 根本不读输出，无解码面）；
  ② `daily_pipeline.py:34` 的 `encoding`/`errors` 是**装饰参数**（没有 `capture_output`，subprocess 压根不解码）；
  ③ 真正还有暴露面的只剩 **`scripts/capacity_collect.py:60` 一处**（今天不炸，条件是仓里出现中文命名的 `.py`）；
  ④ auto_heal 三处的解码防御**今天（q918-18／768c867）刚补完**，本表把它连同"刻意不写 encoding"的理由一并登记。

## 一、口径先立住（任务书那条 grep 会给错数——实测三种数）

```bash
cd /d/code/my-quant-system-v8
G="subprocess\.\(Popen\|run\|check_output\|check_call\|call\)"
grep -rn "$G" --include='*.py' . | grep -v '\.venv' | wc -l                    # 21 行
grep -rn "$G" --include='*.py' . | grep -v '\.venv' | grep -vc encoding         # 13 行「无 encoding」
grep -rn "$G" --include='*.py' . | grep -v '\.venv' | grep -v encoding \
     | grep -v '^\./tests/'                                                     # 7 行（生产码）
```
三个数各自都不是答案，原因是同一行口径的两个反向缺陷：
1. **误算散文**：21 行里有 **12 行在 `tests/`**——是 docstring/注释和 monkeypatch 目标名（
   `test_dailypipeline_encoding.py` 一个文件就贡献 6 行），不是调用点。
2. **漏算续行**：`app/loaders.py:202` 的 `subprocess.Popen(` 出现在「无 encoding」名单里，
   但它的 `encoding=`/`errors=` 写在续行（AST 判定为**已保护**）；`auto_heal.py:59` 同理。
3. **今日新增的反向误报**：q918-18 的修法是"只补 `errors='replace'`、刻意不写 `encoding`"（§三），
   于是 `auto_heal.py:141` 这种**已经防住的行**在 `grep -v encoding` 名下仍然算"未保护"。
   ⇒ 凡用这条 grep 做门禁，会把正确修法判成漏改——这本身就是该改口径的证据。

**本表以 AST 口径为准：全仓 subprocess 调用点 9 处**（生产码，`tests/` 零命中真调用点），
逐点判定 `text`/`encoding`/`errors` 关键字；行口径的 21/13/7 只作为召回上限留档，并与本表逐条对得上
（9 处 − health 两处同行带 encoding = 那 7 行）。

## 二、九处逐点对照（AST：`ast.walk` ＋ 关键字段判 `text/encoding/errors`）

| # | 位置 | 命令 | 模式 | enc | err | 输出怎么被用 | 解析中文？ | 优先级／今日状态 |
|---|---|---|---|---|---|---|---|---|
| 1 | `app/loaders.py:202` | 子进程读清单（Popen） | text | ✅ | ✅ | `stdout` 逐行解析 | 否（路径/计数） | **已保护**，无需动 |
| 2 | `auto_heal.py:59` | `[sys.executable, script]` | text | ➖ | ✅ | `r.stdout + r.stderr` 折叠进 `heal_log` | **是**（子脚本满屏中文日志） | 今日 q918-18 补 `errors`；**刻意不写 encoding**（见 §三） |
| 3 | `auto_heal.py:125` | `schtasks /query /fo CSV` | text | ➖ | ✅ | `if task_name in r.stdout`（ASCII 名比对） | 否（比对项是 ASCII） | 同上；语义等价 |
| 4 | `auto_heal.py:141` | `schtasks /create …` | text | ➖ | ✅ | 失败时 `r.stderr[:200]` 进 WARN 日志 | **是**（中文系统报错） | 同上；**这条是锚点点名那条**，且它原先在任务书的两处清单之外 |
| 5 | `core/pipeline.py:186` | `[python, script] + args` | **bytes** | ➖ | ➖ | **只取 `.returncode`**，输出直接透传父控制台 | 不解析 | **锚点误判**：此处没有解码面，加 encoding 反而会让 bytes 模式下的返回值变成 str 而打破现有用法 ⇒ 列为"不动" |
| 6 | `daily_pipeline.py:34` | `[python, send_to_bark.py, …]` | bytes（无 `capture_output`） | ✅ | ✅ | **不读输出**，只看返回码 | 不解析 | **装饰参数**：无 `capture_output`/`text` ⇒ subprocess 不建解码包装，`encoding`/`errors` 当下无行为。代码注释（q918-39）已自陈这点，属"防未来加捕获"的预埋，不是漏改 |
| 7 | `ops/health.py:263` | `schtasks /query` | text | ✅ | ✅ | 解析任务状态行 | 否 | **cb62427 已修**（口径与 §三不一致，见遗留 1） |
| 8 | `ops/health.py:272` | `schtasks /query /tn QuantMorningPipeline` | text | ✅ | ✅ | 同上 | 否 | 同上 |
| 9 | `scripts/capacity_collect.py:60` | `rg -c PAT --glob *.py …` | text | ➖ | ➖ | `out.splitlines()` 后 `rsplit(':')` 取计数 | **条件性**：路径含中文即触发 | **唯一还值得动的一处**（中优先级）。今天实测不炸：`find . -name '*.py'` 里非 ASCII 路径 **0 条**；但 `books/反反爬实战笔记.md` 这类中文名文件已在仓内，只要有人把 `--glob` 从 `*.py` 放宽，`rg` 发 UTF-8 字节、父进程按 cp936 严格解码 ⇒ `UnicodeDecodeError` |

⇒ 与锚点对照：4 个"同族"点名里，**3 处成立**（auto_heal 三处算一个族、health 已修、capacity 未列），
**1 处不成立**（`core/pipeline.py:186`），另有 **1 处名义上算了、实为装饰**（`daily_pipeline.py:34`），
还**漏了 2 处**（`auto_heal.py:141` 与 `scripts/capacity_collect.py:60`——任务书写的 `:137` 就是前者，行号已漂）。

## 三、为什么 auto_heal 刻意只补 `errors`，而 health.py 是 `encoding='utf-8'`＋`errors`

实测（本机中文 Windows，`locale.getpreferredencoding() == 'cp936'`）：
```bash
python -c "import subprocess,sys
b=subprocess.run([sys.executable,'-c','print(\"中文标记OK\")'],capture_output=True).stdout
print(b)                    # b'\xd6\xd0\xce\xc4\xb1\xea\xbc\xc7OK'  ← 子进程发的是 cp936 字节
print(b.decode('cp936'))    # 中文标记OK
b.decode('utf-8')           # UnicodeDecodeError
"
```
- 崩溃的**充要条件是"严格解码"** ⇒ `errors='replace'` 就够。
- 再叠 `encoding='utf-8'` 会把本来能正确还原的中文（`heal_log` 里的子脚本日志、`schtasks` 中文报错）
  整片换成 U+FFFD ⇒ 把"崩溃"换成"日志不可读"，而自愈场景里人只能靠这份日志。
- **让 `encoding` 缺省（跟随 locale）才与子进程同源**；两边若都进 UTF-8 模式（`PYTHONUTF8=1`）同样同源。
- `cb62427` 的 `encoding='utf-8'` 在 health.py 里没造成实害（那里比对的是 ASCII 任务名），
  但两套写法并存就是下次改错方向的伏笔 ⇒ 见遗留 1。

## 四、要不要一条静态检查防漂（建议，本单没做）

AST 口径可以一行判定：**凡 `text=True` 或有 `capture_output=True` 的 subprocess 调用，必须带 `errors=`**。
按此规则今日实跑：9 处里 **6 处合规**（#1/#2/#3/#4/#7/#8），
不合规 **1 处**（#9 `capacity_collect.py`），**2 处豁免**（#5 bytes 不读输出、#6 无捕获参数为装饰——豁免要写进规则白名单，否则误报）。
放法同 `tests/audit_test_isolation_scan.py`：先只报告、不进断言；等 #9 修掉再升断言。

## 五、零改动自证与复现

- 本文件是**唯一新增**；`.py` 零 diff。复现：
```bash
cd /d/code/my-quant-system-v8
git status --porcelain --untracked-files=no | wc -l    # 0 ⇒ 跟踪文件零改动（本单只新增本 md）
# 注：`git status --porcelain '*.py'` 会另列 tmp/ 下两个**未跟踪**脚本（非本单产物，未碰），别把它当成本单的 diff
python - <<'PY'
import ast, os, io
BS=chr(92)
rows=[]
for root, dirs, files in os.walk('.'):
    dirs[:]=[d for d in dirs if d not in ('.venv','__pycache__','.git','tmp','archive','node_modules')]
    for fn in files:
        if not fn.endswith('.py'): continue
        p=os.path.join(root,fn); txt=io.open(p,encoding='utf-8').read()
        try: t=ast.parse(txt)
        except Exception: continue
        for n in ast.walk(t):
            f=getattr(n,'func',None)
            if not (isinstance(f,ast.Attribute) and getattr(f.value,'id','')=='subprocess'): continue
            if f.attr not in ('run','Popen','check_output','check_call','call'): continue
            kw={k.arg for k in n.keywords}
            rows.append((p.replace(BS,'/'), n.lineno, f.attr,
                         'text' if ('text' in kw or 'universal_newlines' in kw) else 'bytes',
                         'enc' if 'encoding' in kw else '-', 'err' if 'errors' in kw else '-'))
print(len(rows))
for r in sorted(rows): print('  ', r)
PY
find . -name "*.py" -not -path "./.venv/*" | LC_ALL=C grep -c -v '^[ -~]*$'      # 0 ⇒ #9 今日不炸的直接原因
```

## 六、边界（都没做）

1. **两套解码口径并存**：`ops/health.py`（`encoding='utf-8'`＋`errors`）vs `auto_heal.py`（只 `errors`）。
   按 §三 的实测，health 那两处**建议收敛成 errors-only**（改动面是两行参数），但那是别的单的产物，本单不碰。
2. `core/pipeline.py:186` 与 `daily_pipeline.py:34` 的"不读输出"是**当下事实**，不是设计保证：
   谁哪天给它们加 `capture_output=True` 读日志，就得同步补 `errors`——静态检查（§四）正是为堵这个。
3. 本表只覆盖 `subprocess.*` 五个入口；`os.popen`／`os.system`／`pty`／直接读 `sys.stdout` 的解码面未纳入。
   实测 `os.popen` 在本仓 0 处，`os.system` 未清点 ⇒ 若日间要做全量解码面审计，需另开单。
