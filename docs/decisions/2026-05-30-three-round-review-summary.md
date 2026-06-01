# 三轮全面审查 — 汇总（2026-05-30）

**审查时长**：3 轮 × (优化 + 健康 + 冗余) = 9 个维度全覆盖
**审查方**：DeepSeek V4 Pro + Kimi K2.6 (a/b) + Opus self-review（GPT relay 中途 RemoteProtocolError，由 Opus 替补补齐）
**目标**：D:\code\my-quant-system-v8 全系统体检

## 累计修复（10 处 critical）

| # | 轮次 | 模块 | 影响 |
|---|---|---|---|
| 1 | R1 | enhanced_backtest + cost_model | SLIPPAGE 双扣 → 回测净收益虚低，加 `with_slippage` 开关 |
| 2 | R1 | enhanced_backtest | regime label "牛市/熊市" 落不进 5 档 → dyn_notional 永远 0.40 fallback |
| 3 | R1 | sim_trade | 跌穿止损用 stop_loss 价记账 → 低估真实穿透损失 |
| 4 | R1 | sim_trade vs exit_advisor | sim 死叉判 MA5/MA30，advisor 判 MA5/MA20 → 两套口径 |
| 5 | R1 | position_sizer.calc_gap_deviation | prev_close 取 iloc[-1]（今天）→ gap 永远≈0 |
| 6 | R2 | walk_forward.MA_LONG | 用全局常量 + 硬编码列名 'MA20'，grid search 退化为 RSI×RSI 二维 |
| 7 | R2 | alpha_gate | 同日重复运行 +2/天 → 5 日警戒在 3 日内误触发 |
| 8 | R2 | fetch_history.code_to_sina_symbol | 110/113/118 沪市可转债误归 sz → 全部 404 静默失败 |
| 9 | R2 | fetch_history 双倍内存 | existing_full + disk_df 同时驻留 → 4G 机器 OOM 风险 |
| 10 | R2 | data_loader stock_yjbb_em / 北向 API | 两个数据源因 API 用错永远空 → 基本面+北向因子失能 |
| 11 | R3 | log_real_trade.calc_fee | 不套 5 元最低佣金 → 1200 元交易记录的费用低估 95% → 反馈闭环净 PnL 全部失真 |
| 12 | R3 | app/pages 录入面板 | 显示佣金分项与总额不自洽 |

## 健康指标

- **测试**：pytest 136 → 154（+18 条 Round-3 回归测试，锁定 8 处修复点）
- **自检**：142/142（100%）
- **流水线**：38 步骤注册表，全部脚本物理存在

## 留作下一阶段的 Quality 项（不阻塞）

- RSI 三处实现不一致（Wilder vs SMA）—— 抽到 `utils/indicators.py`，需先评估对历史回测影响
- fee 常量散落（bark_sender/builders + replay_picks 仍硬编码）—— 下一次重构统一走 cost_model
- fetch_history target_date 取文件名（长假后浪费抓取）—— 改用 trading_calendar
- alpha_gate state 损坏静默重置 —— 至少 print warning
- broker_adapter price=0 保护 + 缺代码兜底
- enhanced_backtest 与 sim_trade lite/full 90% 代码重复 —— v8.8 候选

## 风险（≥2）

1. **Round-3 fee 修复改了真实交易记录的 fee 字段计算逻辑** —— 历史 real_trades.csv 里之前用 0.025% 写入的 fee 现在仍然是旧值；只有"新追加"的交易记录才是新算法。下次跑 strategy_feedback 的 FIFO PnL 计算会把"新交易低 fee + 旧交易低 fee"混合，需要用户判断是否回填。
2. **data_loader 的 stock_hsgt_hold_stock_em 是新接口** —— 取决于 akshare 版本；本机若 akshare < 1.16 会回退到旧 API（仍然是错的）。建议在 .env 或 system_config.json 里加 `akshare_version >= 1.16` 的健康检查。

## 反方观点（≥1）

- **不是所有 critical 都需要立即修**：例如 R2#10 的 stock_yjbb_em 用了错误日期参数，导致基本面因子永远空——但流水线 graceful fallback 保住了选股不挂；用户的 1200 元小本金当下根本不会因为 ROE 因子丢失而错过赚钱机会，重要性低于 fee 漂移。换句话说：本次三轮审查最大的价值在 R3#1（log_real_trade fee）和 R1（回测/sim 的 5 处一致性），其余可视作长期债务清理。

## 置信度

**中-高**：

- 8 处修复都有 pytest 回归测试锁定 → 不会再悄悄退化（高置信）
- GPT relay 失败导致 Round 1 部分由 Opus 自审替代 → 缺一份独立视角，可能有眼盲点（中置信）
- 改变结论的证据：实际跑 1 个交易日 daily_pipeline 后，对比 strategy_feedback 输出的 win_rate/profit_factor 是否更接近用户主观感知

## 归档路径

- `docs/decisions/2026-05-30-three-round-review-r1.md`（Round 1 详记）
- `docs/decisions/2026-05-30-three-round-review-r2.md`（Round 2 详记）
- `docs/decisions/2026-05-30-three-round-review-r3.md`（Round 3 详记）
- `docs/decisions/_round1/_deepseek_output.txt` / `_kimi_output_a.txt` / `_kimi_output_b.txt`（原始多模型输出）
- `tests/test_three_round_review_regressions.py`（18 条回归测试）
