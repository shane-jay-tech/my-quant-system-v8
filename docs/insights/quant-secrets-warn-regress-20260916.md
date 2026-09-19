# quant secrets 读取失败一次性 stderr 告警回归核验（n916x-21）

**结论：既有 4 单测（5203274）复跑全绿；追加 2 反例（同因双失败恰告警一次／正则断言零键值形态）全绿——`-k secrets` 23 passed。告警文本零键值泄露复核成立，凭据域零改动。**

## 一、复跑与追加（命令与数字同段）

```
$ python -m pytest tests/ -k secrets -q  → 23 passed（既有 4＋追加 2＋其他 secrets 域用例）
```
- 既有 4 条（tests/test_secrets_read_failure_warn.py，5203274）：parse 失败告警且不泄露＋换指纹再失败仍一次／missing 告警一次／invalid-json 不带内容／健康路径静默。
- **追加①同因双失败**：同路径同指纹连续两次 `_load_kv` → stderr `count("read failure")==1`（去重台账 (路径,原因) 命中，core/secrets.py:26-37）。
- **追加②正则断言**：构造含 `BARK_TOKEN=SUPER-SECRET-VALUE-7742` 与 `ANOTHER_KEY=abc123` 的坏文件、注入 open 抛错，两次调用后全量 stderr 断言：`re.search(r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*\S", err) is None`（零 KEY=value 形态）＋种子密值不出现。

## 二、告警文本样例（脱敏；tmp 隔离实测，第二次同因调用零输出）

```
$ python（tmp 目录构造 missing 场景，同因调用两次）
[secrets] read failure (missing): C:\Users\…\Temp\tmpXXXX\sample.env
（第二次调用无任何输出——去重台账命中）
```
正则断言出处＝追加②用例（本报告§一），格式锚点 core/secrets.py:37 `print(f"[secrets] read failure ({reason}): {path}", file=sys.stderr)`——只含原因与路径，无值位。

## 三、验收情况

- ✅ `-k secrets` 23 passed 全绿（新增 ≥2，命令与数字同段）；✅ 告警样例脱敏同段＋正则断言出处同段；✅ 全程 tmp 隔离零真实凭据（.env 未读）；✅ secrets.py 生产逻辑零改动；测试精确路径 git add，未 push。

## 遗留问题

无。B-134 所列「失败路径仍静默」已由 66d5 修复并经本单回归锁定。
