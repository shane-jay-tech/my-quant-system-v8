# requirements.txt vs 实际 import 漂移对照（916p-a1-021，2026-09-17）

## 一、第三方 import 全清单（AST 扫描，排除 stdlib 与本仓包；覆盖 *.py 含根目录/bark_sender/app/ops/core/learning/tests/tools/scripts，盲区＝.pyw 与非 ASCII 语法错误文件）

| 包名 | 被 import | 在 requirements | 判定 | 动作 |
|---|---|---|---|---|
| pandas | ✓(68 文件) | ✓ | 正常 | — |
| numpy | ✓(25) | ✓ | 正常 | — |
| requests | ✓(11) | ✓ | 正常 | — |
| pytest | ✓(40) | ✓ | 正常 | — |
| streamlit | ✓(6) | ✓ | 正常 | — |
| akshare | ✓(2) | ✓ | 正常 | — |
| plotly | ✓(1) | ✓ | 正常 | — |
| scipy | ✓(1) | ✓ | 正常 | — |
| **coverage** | ✗（命令级工具：PLAN.md:29-30 `python -m coverage run/report`） | ✗ | **缺列** | **已追加 `coverage>=7.0,<8.0`** |
| **python-dateutil** | ✗ 全仓零命中 | ✓ | 多列 | **只写建议不删（删依赖需人工裁定）** |
| **pywebview** | ✗ 零命中（AST 范围内） | ✓ | 疑多列 | 同上建议（注意 .pyw 盲区：launcher.pyw 若用 pywebview 则不算漂移——本单盲区声明） |

## 二、最小修正与验证（命令与数字同段）

```
$ grep -c '^coverage' requirements.txt
1
$ python -c "import coverage; v=...; print('in_range=', (7,0)<=v<(8,0), coverage.__version__)"
in_range= True 7.15.1        ← 7.15.1 落在 >=7.0,<8.0 ✓
$ git diff --numstat -- requirements.txt
1       0       requirements.txt   ← 删除数 0，仅追加 ✓
$ python -c "b=open('requirements.txt','rb').read(); print(b[:3]!=b'\xef\xbb\xbf')"
True                          ← 无 BOM ✓
$ python -m pytest -q
660 passed, 4 skipped, 2 xfailed   （failed=0，零影响）✓
```

## 三、python-dateutil 建议（不删）

全仓 53 个 AST 顶层名中无 dateutil（pandas 自带依赖 dateutil 系其内部需求，由 pandas 依赖树自动解析，无需显式列出但列出亦无害）。建议日间裁定：删除或移注释段「transitive」。

## 四、验收对照

- ✅ coverage 行命中 1；版本 7.15.1 在区间。
- ✅ numstat 删除数 0；无 BOM。
- ✅ 全量 failed=0。
- ✅ 未删 python-dateutil、未改既有区间、未 pip install；不 push。
