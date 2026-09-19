# quant requirements 裁定材料：`launcher.pyw` 盲区核验（q918-28，只读）

- 执行：2026-09-19 14:2x（夜班 `qoder-rev-20260919-1020`）。**未删、未注释、未改 `requirements.txt` 一行**，只出裁定建议。
- 缘起：`docs/insights/quant-requirements-drift-20260917.md:17` 原文
  「| **pywebview** | ✗ 零命中（AST 范围内） | ✓ | 疑多列 | 同上建议（注意 .pyw 盲区：launcher.pyw 若用 pywebview 则不算漂移——本单盲区声明）」

## 一、裁定结论（两条）

| 依赖 | requirements 行 | 前判 | **本单裁定** | 一句话依据 |
|---|---|---|---|---|
| **pywebview** | `requirements.txt:21` | 疑多列 | **保留（前判不成立，是假阳性）** | `launcher.pyw:28 import webview` ＋ `:218 webview.create_window` ＋ `:284 webview.start` —— 真实使用，只是扫描器看不见 `.pyw` |
| **python-dateutil** | `requirements.txt:24` | 多列 | **不要直接删；改注为 transitive（推荐 B 方案）** | 一方代码确实零命中，但它是 pandas 的**硬依赖**（实测 `pandas 3.0.3` 元数据要求 `python-dateutil>=2.8.2`），且本文件这行写的 `>=2.8.0` 比 pandas 自己要求的还松 ⇒ 这行不但冗余、还给出一条**更弱**的约束 |

## 二、证据（命令 ＋ 命中数）

```bash
cd /d/code/my-quant-system-v8

# ① .pyw 是否存在、是否真用 pywebview
find . -name "*.pyw" -not -path "./.venv/*"        # → 1 个：./launcher.pyw（全仓唯一 .pyw，10209 B，mtime 2026-08-15）
grep -n "import webview\|webview\." launcher.pyw    # → 4 命中：:28 import webview / :218 create_window / :284 start / :290 异常日志文案
grep -in "pywebview" requirements.txt               # → :20 注释「# 桌面端套壳（PyWebView - launcher.pyw）」＋ :21 依赖行

# ② launcher.pyw 是不是死档
grep -rln "launcher.pyw" --include="*.py" --include="*.md" --include="*.bat" . | grep -v "\.venv"
#   → 4 个文件：README.md、ops/health.py、docs/decisions/2026-08-15-impl-perf-ux-and-history-fastpath.md、docs/insights/quant-requirements-drift-20260917.md
grep -n "launcher.pyw" ops/health.py                # → :127 把它列进 config_files 存在性检查表（= 它是被监控的活工件）

# ③ dateutil 一方命中
grep -rn "dateutil" --include="*.py" --include="*.pyw" . | grep -v "\.venv"    # → 0 命中
python -c "import importlib.metadata as m;print([r for r in m.requires('pandas') if 'dateutil' in r])"
#   → ['python-dateutil>=2.8.2']   （pandas 3.0.3）
grep -n "pandas" requirements.txt                   # → :7 pandas>=2.0.0,<4.0（所以 dateutil 必然被间接安装）
```

**盲区成因定位（不是玄学，是文件模式）**：`tools/audit_test_isolation.py:104` 的收集式是
`root.rglob('*.py')` —— 与前一份 requirements 审计同族的 AST 扫描都按 `*.py` 收文件，`.pyw` 天然落在范围外。
⇒ 只要有一个 GUI 套壳/托盘入口用 `.pyw`（Windows 双击不弹控制台的标准做法），这类依赖就会被系统性误判成"多列"。

## 三、两个 diff 建议（**均未执行**）

### A. pywebview：不动。建议在漂移报告上补一句勘误

```diff
--- docs/insights/quant-requirements-drift-20260917.md（:17 行）
-| **pywebview** | ✗ 零命中（AST 范围内） | ✓ | 疑多列 | 同上建议（注意 .pyw 盲区：launcher.pyw 若用 pywebview 则不算漂移——本单盲区声明）
+| **pywebview** | ✓ 命中 `launcher.pyw:28/:218/:284`（.pyw 不在 AST 的 `*.py` 收集范围内） | ✓ | **不多列** | 勘误（q918-28 复核）：盲区声明成立且已被证实——保留依赖行 `requirements.txt:21` |
```
（改的是**漂移报告**这份文档，不是 requirements；若日间不愿动历史文档，本包 §一/§二 已自带同等效力。）

### B. python-dateutil：推荐"标 transitive"而非删除

```diff
--- requirements.txt（:23-24）
 # 系统工具
-python-dateutil>=2.8.0
+# python-dateutil：一方代码零直接引用；它是 pandas 的硬依赖（pandas 3.0.3 要求 >=2.8.2），
+# 由 requirements.txt:7 的 pandas 间接安装。原行的 >=2.8.0 比 pandas 自己的下限还松，属误导。
+# 裁定建议（q918-28）：注释化保留，别删——删了 pip 仍会装，只是把"我们依赖它"这件事从账上抹掉。
```
为什么推荐 B 而不是直接删：
1. 删与不删**运行时结果相同**（pandas 会拉进来），但注释版留下"为什么这里没有它"的答案，否则下次审计又会把它当"多列"报一遍——**这正是本单被派下来的原因**。
2. `requirements.txt` 里的行同时承担"我们主动用到的能力"清单作用；dateutil 经 pandas 生效（`pd.to_datetime` 等），标注比删除更诚实。
3. 若日间坚持删，建议同时把 pandas 的下限说明补上，避免 `>=2.0.0` 与 pandas 3.x 混装时对 dateutil 版本的意外期待。

## 四、顺带纠正的一处

前一份漂移报告的表格给 pywebview 的处置写「同上建议（＝只写建议不删）」，语气是"疑似多列待裁"。
本单核验后它的状态应改为**已证实使用**。这条改的不是数字，是**下一班会不会去删一个正在用的依赖**——
所以本包优先落这条，B 方案反倒次要。

## 五、本单改动

- 新增：`docs/insights/quant-pywebview-blindspot-20260918.md`（唯一改动）
- `requirements.txt`、`launcher.pyw`、`tools/`、任何依赖：**零改动**；未安装/未卸载任何包（`importlib.metadata` 只读元数据）
