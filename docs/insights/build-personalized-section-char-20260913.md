# build_personalized_section 分支 characterization 记录（2026-09-13）

- 新增 `tests/test_build_personalized_section_char.py`（6 用例）：无文件→[]；全部对平→[]；「示例」备注过滤→[]；未平仓无行情文件→回退 entry_price 且输出持仓节；guide 含 max_consecutive_loss→出现提示行；缺键/None→不出现。
- 资金数值硬断言自查：**无**——pnl/价格/市值仅以「字段存在性与分支行为」表达，未断言任何金额（红线遵守）。
- characterization 新发现（现行为锁定，未改生产码）：备注列空值读成 NaN → `df["备注"].str.contains` 抛 AttributeError → 被函数 except 吞成 []，即**备注为空的真实持仓会被整段静默丢弃**——建议列入 S5 候选面（修法：`df["备注"].fillna("")`）。
- 全量：522 passed, 2 xfailed（516+6）。生产码零改动。
