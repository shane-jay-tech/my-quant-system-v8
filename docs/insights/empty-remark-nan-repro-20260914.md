# build_personalized_section「空备注」缺陷复现与定性（d913-5934，2026-09-14）

复现脚本：`python tmp/repro_5934.py`（可重复运行、输出稳定；tmp 隔离数据，真实 real_trades.csv 零触碰）。

## 结论：② d913a-41 机制描述错误——但真缺陷存在，真实机制如下

**d913a-41 的描述错误**：「备注列空值（单元格级 NaN）致 `.str.contains` 崩」不成立——formatters.py:262 的 `.str.contains('示例', na=False)` 的 `na=False` 正是为单元格 NaN 兜底，S1（混合空备注）实测正常：持仓保留、无异常。

**真实机制（实测坐实，S2）**：当**备注列整列为空**（如 CSV 里只有表头+空尾列）时，`pd.read_csv` 把该列推断为 **float64（全 NaN）**，而非 str——float64 列上调 `.str.contains` 抛 `AttributeError: Can only use .str accessor with string values!` → 被函数入口的 `except Exception: return []`（formatters.py:271-272）吞掉 → **返回空列表，全部真实持仓被静默丢弃**（连报错都没有）。

## 实测（pandas 3.0.3）

| 场景 | 备注 dtype | 实测行为 |
|---|---|---|
| S1 混合（空单元格/示例/正常） | str | 正常：示例行被滤、空备注持仓保留、无异常 |
| **S2 备注列全空** | **float64** | **`.str` AttributeError → except → 返回 []，持仓静默丢弃** |
| S3 备注列缺失 | （无列） | `if '备注' in df.columns` 守卫生效，正常 |
| S4 全示例行 | str | 正常过滤后返回 []（设计内） |

调用方核查：builders.py:51 与 send_to_bark.py:99 处 `if personal:` 只做非空拼接，**无外层 try**——丢弃后无任何日志/告警（静默）。 except 块本体在 formatters.py:271-272。

## 补丁草案（资金域：**不 apply，须日间授权后落地**）

`bark_sender/formatters.py:260` 后（读入 df 之后、过滤之前）加一行：
```python
if '备注' in df.columns:
    df['备注'] = df['备注'].fillna('')
```
（或 read_csv 的 dtype dict 增加 `'备注': str`，二选一；前者同时消除单元格 NaN 语义歧义。）
配套复现用例：S2 场景断言「返回非空且含 000001」——可挂进 tests/test_build_personalized_section_char.py（d913a-41 的 6 用例文件）。

## 验收

- 复现脚本可重复运行、输出稳定（含 pandas 3.0.3 与四场景实测行为）✓
- 结论三选一明确（②），file:line 齐全（:262 崩点 / :271-272 吞点）✓
- 真实 real_trades.csv 与生产码 diff=0（git status 实测：仅 bark_sender/parsers.py 的 M 为**先前会话既有**工作树改动，与本班无关；formatters.py 零 diff）✓
- 复现命令原文：`python tmp/repro_5934.py` ✓

## 遗留问题

- fillna 补丁涉资金域（real_trades 消费链），须日间授权后落地并补 S2 用例。
- d913a-41 的 6 条 characterization 用例基于错误机制描述，建议随补丁一并订正（保留隔离与红线纪律）。
