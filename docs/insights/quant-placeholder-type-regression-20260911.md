# quant 占位层原始类型保持回归用例（2026-09-12 夜间执行班，任务 p911r-37）

> 执行：GLM-5.3-Flash 夜间执行班 sweep-20260911-2300。背景：09437c0（S4-d 回归修复——`_load_kv` 的 str() 曾把 bark_tokens 列表打成字符串致实推失败；`core/secrets.py:79-93 _load_json_raw` 为修复函数）。**未改 core/secrets.py 逻辑；未读真实凭据明文；未 commit/push。**

## 一、新增回归用例（tests/test_placeholder_type_preserve.py，5 条 ≥4）

| 用例 | 场景 | 断言 |
|---|---|---|
| test_list_value_stays_list_of_str | bark_tokens 列表（09437c0 回归本体） | 读回仍为 list 且元素 str |
| test_dict_value_stays_dict | 嵌套 dict | 类型与内容保持 |
| test_int_value_stays_int | int 值 | 保持 int（且非 bool） |
| test_bool_value_stays_bool | True/False | `is True` / `is False` 严格判定 |
| test_missing_file_returns_empty_dict | (-1,-1) 哨兵 | 空 dict 不抛错 |

隔离：全部使用 `tmp_path` 临时 JSON + `_fingerprint`，**不读 data/secrets.json 明文**（禁令遵守）。

## 二、运行结果与基线对比

```
$ python -m pytest tests/test_placeholder_type_preserve.py -q   → 5 passed
$ python -m pytest -q                                           → 444 passed, 2 xfailed
```
- 基线对比：19-05 夜基线（00:1x）为 441 collected/439 passed；本单 +5 用例 → **446 collected / 444 passed + 2 xfailed，0 失败**。增长全部来自本单新用例，无回归。
- 未暴露真缺陷：5/5 直接过，09437c0 修复在 list/dict/int/bool 四类上均保持原始类型。

## 三、范围声明

`git diff --stat` 无触及（新测试文件为 untracked，即「只触及测试文件」✓）；`core/secrets.py` 零改动；零联网；未读真实凭据明文。
