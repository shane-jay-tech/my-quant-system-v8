# ops_analyzer characterization 用例记录（2026-09-13）

- 新增 `tests/test_ops_analyzer_charac.py`（5 用例）：pct 空值/90 分位 round 索引；fmt_table 结构（含非 str 单元格 str() 化）；parse_logs 步骤解析+[WARN]/FAIL/Traceback 事件捕获+since 过滤+文件名过滤+OSError 跳过；analyze 失败计数/20260815 前后分桶/主表均耗时降序。
- characterization 过程中修正两处预期以锁真实行为：①rc!=0 不产生文本事件（事件仅来自行文本）；②主表排序按均耗时（fetch_history 52.5 > train 11.0）。
- 生产码零改动；tmp_path/monkeypatch 隔离，无网络/文件外呼。
- 全量：`python -m pytest -q` → 516 passed, 2 xfailed（511+新增 5）。
