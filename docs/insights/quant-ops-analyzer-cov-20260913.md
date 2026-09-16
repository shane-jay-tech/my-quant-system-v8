# ops_analyzer characterization 覆盖记录（d913b-37）

- **实况**：同题已由 d913a-38 交付 `tests/test_ops_analyzer_charac.py`（5 条 characterization，516→522 全绿）；与 b-37 预期文件名 `test_ops_analyzer_characterization.py` 不同但内容完全覆盖其要求（pct/fmt_table/parse_logs 事件与过滤/analyze 分桶；tmp_path/monkeypatch 隔离；生产码零改动）。
- 覆盖记录：`python -m pytest tests/test_ops_analyzer_charac.py -q` 5 passed；全量 522 passed, 2 xfailed。coverage 分支计数未跑（仅记录类要求，a-38 报告已给模块分支清单）。
- 未重复建第二份同内容测试文件（避免双份维护漂移）。
