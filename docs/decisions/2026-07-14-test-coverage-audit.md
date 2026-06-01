# 2026-07-14 全仓测试覆盖率审查与补测

## 结论

现有测试虽然 183 项全部通过，但覆盖率集中在少数回归点，全仓分支覆盖率只有 19%。资金相关核心中，`strategy.py`、`portfolio_risk.py` 完全没有被执行，`enhanced_backtest.py` 只有 8%。本轮新增 52 个通过用例、2 个严格 `xfail` 缺陷规格，并修复 1 个旧测试污染真实模拟净值文件的问题。

最终结果：`235 passed, 2 xfailed`；全仓覆盖率 19% → 25%。关键模块覆盖率：

| 模块 | 基线 | 最终 | 重点验证 |
|---|---:|---:|---|
| `strategy.py` | 0% | 71% | 动态参数、指标、评分、ST/停牌/退市/新股/市值过滤、板块集中度 |
| `portfolio_risk.py` | 0% | 84% | 相关性、VaR/CVaR、回撤、波动率、换手率、风险动作汇总 |
| `enhanced_backtest.py` | 8% | 79% | T+1 开盘成交、same-close 对照、死叉次日开盘、成本/滑点、基准与分析 |

## 审查方法

1. 运行原始全量测试，确认 183 项通过。
2. 使用 `coverage.py` 的 branch 模式覆盖整个仓库。
3. 按“直接影响资金 > 调度与配置 > 展示与研究工具”排序。
4. 对核心函数逐分支阅读，构造离线 DataFrame、临时目录和 monkeypatch。
5. 每个新增测试文件写完立即单独执行；最终再跑全量测试和覆盖率。
6. 比较测试前后 Git 状态，检查是否污染真实数据。

## 新增测试

### 组合风控

- 历史收益文件缺失、代码补零、短历史剔除。
- 高相关持仓识别和最大相关股票对。
- 参数法 VaR 的 95%/99% 差异、历史法 VaR、CVaR 尾部损失。
- 回撤正常/预警/强制降仓三个区间及损坏文件兜底。
- 波动率样本不足、正常和强制降仓。
- 零权益、正常换手、超限拦截。
- 多项风险动作同时汇总、风险报告 JSON 落盘。

### 选股策略

- 进化参数文件缺失、损坏、允许字段过滤。
- 五档市场动态 RSI/MA 参数与关闭动态模式。
- RSI、ATR 和评分各档边界。
- 合格股票完整选入、止损价、风险等级、理由和板块。
- ST、低市值、停牌、退市、新股硬过滤。
- RSI 覆盖参数和板块集中度安全候选优先。
- Markdown 报告和 100 字摘要。

### 回测引擎

- 各股票指标分组隔离，避免跨股票滚动污染。
- 信号日收盘后，严格使用 T+1 开盘入场。
- 非法/缺失次日开盘不成交。
- same-close 仅走旧版对照路径。
- ST 和低市值硬过滤。
- 死叉在收盘确认后使用下一日开盘卖出。
- 滑点只体现在成交价，成本模型调用明确 `with_slippage=False`，防止双扣。
- 牛市 Top-N、基准收益、胜率、成本、死叉率、超额收益和连亏天数。

### 测试隔离

旧用例 `test_sim_trade_full_non_trading_day_uses_price_field` 只替换了 `SIM_DIR`，没有替换导入时固定的 `EQUITY_FILE`，导致测试向真实 `sim_results/equity_curve.csv` 写入。现已补上临时路径，并恢复被追加的数据；复跑 29 项相关测试后工作区不再出现数据变化。

## 三档问题清单

### 必修

1. `strategy.screen_stocks(target_date=...)` 没有按目标日期截断历史数据。回测或历史复盘会读取目标日之后行情，属于未来函数，可能显著夸大策略效果。已用严格 `xfail` 锁定；修复后该测试会变成 XPASS 并使流水线失败，提醒移除标记。
2. `portfolio_risk.generate_risk_report()` 在少于两只持仓时把 `correlation` 设为 `None`，随后直接调用 `.get('warning')`，会抛 `AttributeError`。小资金单票持仓正是常见场景，风险报告可能中断。已用严格 `xfail` 锁定。

### 建议修

- `sim_trade.py` 28%、`position_sizer.py` 37%、`strategy_feedback.py` 37%、`exit_advisor.py` 28%：虽有关键回归测试，但主流程和异常路径仍较薄。
- `core/pipeline.py` 13%：DAG 调度、失败返回码、only/dry-run、月份/星期调度缺系统测试。
- `_self_check.py`、`auto_heal.py` 均 0%：自愈系统本身没有回归保障，错误修复映射和失败上限应补测。
- `broker_adapter.py`、`data_validator.py` 0%：券商格式、合规检查和输入文件损坏场景未覆盖。

### 可不修

- Streamlit 页面、样式、桌面 launcher 的低覆盖可暂缓；优先用少量 smoke test 而非追求行覆盖。
- 研究报告、心理助手、归档脚本不直接下单，可在核心资金路径稳定后再补。
- 网络爬虫不应在普通单元测试中真实联网；后续应以响应样本和 mock 测试重试、403、验证码和数据源降级。

## 多模型协作状态

按项目规范尝试通过 `D:/code/scripts/llm_call.py` 调用 GPT 与 DeepSeek。共享 `D:/code/.env.local` 仅包含 `WANXIANG_*` 和 `TAVILY_API_KEY`，缺少 `GPT_*`、`DEEPSEEK_*`、`KIMI_*`，中转调用在发出请求前即失败。本轮按例外规则由单模型完成，未伪造多模型结论。

## 验证命令

```powershell
python -m pytest -q
python -m coverage erase
python -m coverage run --branch --source=. -m pytest -q
python -m coverage report --skip-empty
```

最终：235 项通过、2 项严格预期失败；无真实网络调用；无生产逻辑改动；测试结束后生产数据无新增变化。
