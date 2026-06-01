# 2026-05-23 v8.6 — 反向反馈循环修复（P0-2）

## 问题

`strategy_feedback.py:analyze_risk_adjustments()` 在两个分支（冷启动 + 实盘）有反向风控逻辑：

- **死叉率高** → 自动放宽止损 (-8% → -10%)，让亏损更大
- **死叉率低** → 自动收紧止损 (-8% → -6%)，让你被洗出去
- **盈亏比高** → 自动升高止盈 (20% → 25%)，让强势股可能回吐

更严重：触发门槛只有 5/10 笔，n=5 的胜率标准误约 22% — 完全是统计噪音却在自动改 risk_config.json，sim_trade 下次跑直接读这个文件。

## 决策

**Alert-only 模式 + 30 笔门槛**：

1. `adjustments['stop_loss_pct']` / `take_profit_pct` 不再被自动修改，保持代码默认 `-0.08` / `0.20`
2. 仍计算"按旧逻辑会建议什么"，但只 append 到 `actions` 列表当提醒（标 `[Alert-only]`）
3. 仓位调整 (`position_size_mult`) 门槛从 5/10 提到 `MIN_TRADES_FOR_ADJUST=30`（统计显著性）
4. `adjustments['alert_only'] = True` 写入 risk_config.json
5. `sim_trade.load_risk_config()` 检测 `alert_only=True` 时跳过读取 stop_loss_pct/take_profit_pct，仅读 max_hold_days
6. `core/config.py` DEFAULTS 新增 `feedback.min_trades_for_adjust=30`（可在 system_config.json 覆盖）

为什么不"反一下符号"就行：
- 真正"正确"的方向（止损率高 → 收紧止损 / 胜率低 → 减仓）也可能是统计噪音驱动的伪信号
- alert-only 把决策权交回给用户：系统提醒"按某种逻辑会建议..."，用户决定要不要改 system_config.json
- 30 笔门槛后，等积累足够样本再考虑重启自动调整（届时 alert_only=False）

## 实施

### Files modified

- `strategy_feedback.py` — 顶部 import + adjustments init dict + 冷启动分支 (line 356-372) + 实盘分支 (line 410-432)
- `sim_trade.py` — `load_risk_config()` 函数（line 72-89）
- `core/config.py` — DEFAULTS 新增 `feedback` 节

### GPT-5.5 patch（节选关键块）

**实盘分支（line 410-432 替换）**：

```python
alert_only = adjustments.get('alert_only') is True
if stop_loss_rate > 0.5 and total_trades >= MIN_TRADES_FOR_ADJUST:
    action = f'止损率{stop_loss_rate:.0%}偏高，止损从-8%放宽到-10%'
    if alert_only:
        adjustments['actions'].append(f'[Alert-only] {action}（自动调整已禁用）')
    else:
        adjustments['stop_loss_pct'] = -0.10
        adjustments['actions'].append(action)
# ... 同样模式覆盖 win_rate / profit_factor 三档判断
```

**sim_trade load_risk_config**：

```python
alert_only = config.get('alert_only', False) is True
if alert_only:
    print('[SIM] Risk config alert-only mode, skipping stop/take adjustments')
    config_items = [('max_hold_days', 'MAX_HOLD_DAYS')]
else:
    config_items = [('stop_loss_pct', 'STOP_LOSS_PCT'),
                    ('take_profit_pct', 'TAKE_PROFIT_PCT'),
                    ('max_hold_days', 'MAX_HOLD_DAYS')]
```

## 仲裁要点（Opus）

GPT 原版 BLOCK 4（`MIN_TRADES_FOR_ADJUST = 5` 硬编码 5）被覆盖：改为从 `core.config` 读取 `feedback.min_trades_for_adjust`，默认 30。这样以后用户改 system_config.json 不用动代码。

GPT 原版还把 `adjustments` 初始化里的 `stop_loss_pct` 改成 `None`（gpt-coder agent 已自纠这点），仲裁保留原默认 `-0.08 / 0.20`，外加 `alert_only: True` 字段——这样 `generate_feedback_report` 里 `adjustments['stop_loss_pct']*100` 不会 TypeError，报告里仍显示"当前生效参数"。

## DeepSeek 评审

DeepSeek V4 Pro 评审仍在运行（reasoning 模型 7+ 分钟），结果回来后追加到本文末尾。

## 验证

- Python AST 语法检查通过（3 个文件）
- 模块 import + smoke test 通过：`alert_only=True / stop_loss=-0.08 / take_profit=0.20 / actions=0`
- `pytest tests/ -v` 64 passed（无回归）

## 风险

- 30 笔门槛意味着小资金用户可能永远无法触发自适应仓位调整（一年也就 ~50 笔）。这是有意为之 — 30 笔以下的胜率波动主要是噪音。后续若想恢复自适应，等历史交易够多再 set `alert_only=False`。
- 老 `risk_config.json` 没有 `alert_only` 字段时回退到 `False` — 这是正确的（保持向后兼容）。`apply_risk_adjustments` 下次运行就会写入 `True`。
