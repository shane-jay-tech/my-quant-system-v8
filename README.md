# my-quant-system-v8

本地优先的量化研究与交易辅助系统，面向小资金 A 股场景。覆盖数据抓取、策略选股、回测、仓位计算、组合风控、模拟交易、行为复盘与系统自检，并把每个交易日的执行收敛为一条可追踪的流水线。当前主线版本 v8.6（版本单一事实源：`core/config.py:SYSTEM_VERSION`）。

## 技术架构

- Python + Streamlit 仪表盘，Plotly 可视化
- pandas / NumPy / SciPy 本地计算
- AKShare 获取 A 股、指数与 ETF 行情
- 插件式 DAG 流水线注册表 `core/pipeline.py`，按 tier 与 schedule 自动过滤步骤
- 分档成本模型（含 A 股 5 元最低佣金与 0.05% 卖出印花税）
- DeepSeek 兼容的 OpenAI API 用于市场研究、策略进化与异常修复
- Bark 推送（可选，凭据只从本地环境变量读取）

行情、持仓、订单、心理日记、报告和模拟账户等运行时数据均被 Git 忽略，不会进入公开仓库。

## 环境要求

- Python 3.10+
- pip
- Windows 定时任务可选：`morning_pipeline.bat`（交易日 09:15，需手动注册 QuantMorningPipeline 任务）与 `daily_pipeline.bat`（交易日 15:37，任务名 QuantDailyPipeline_v5）

安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 启动

仪表盘：

```powershell
streamlit run app.py
```

桌面模式：

```powershell
python launcher.pyw
```

环境变量（或本地 `.env`）：

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-pro
```

不要提交 `.env`、`.env.local` 或 `data/secrets.json`。真实交易记录、券商订单和模拟账户结果只保留在本机。

## 每日流水线

流水线由 `core/pipeline.py` 的步骤注册表驱动，按 `SYSTEM_TIER`（beginner / advanced / pro / auto）与周期过滤：

- **每日核心**：交易日检测 → 行情/ETF/指数抓取 → 数据层 → 数据校验 → 选股策略 → 多策略对比 → 回测(分档成本) → 分钟 K 线 → 出场顾问 → 仓位计算 → 轻量进化 → 模拟交易 → 策略反馈 → shadow 多空分析 → 券商导出 → 研究复盘 → 追踪 → 知识内化 → 交易心理 → 新手保护 → 新手指令卡 → 成本审计 → 持仓同步 → 行为日志 → 开盘前简报 → 决策回放 → 推送（Bark / webhook / 飞书）→ 目标指标 → 自检 → 自动修复 → 数据归档。
- **周期任务**：周一因子 IC/IR 与 arXiv 研究；周三 Walk-Forward；周四策略自动进化；周五策略竞技与基准对比；月末蒙特卡洛、Tracking Error 与月度行为报告。
- **风控门**：Alpha Gate 在连续 5 个交易日跑输沪深 300 时自动暂停选股并提示 ETF；净值回撤与波动率触发组合风控锁；每笔订单过成本门槛。
- **新手保护**：观察期 / 模拟期 / 实盘预备期三阶段，由学习、录入、纪律和自评四项指标综合推进。

## 当前能力亮点

- **数据**：A 股全市场行情、历史 K 线、ETF、分钟线与沪深 300 基准，数据源失败自动降级重试。
- **策略**：五维因子评分、多策略加权投票、动态参数（RSI/MA 随 5 档市场状态切换）、分档成本回测。
- **风控**：ATR 止损、板块集中度、仓位五档、VaR/CVaR、Walk-Forward 与蒙特卡洛过拟合检查。
- **闭环**：选股表现追踪、策略反馈、出场顾问、交易分析器、心理助手、行为偏差报告。
- **自愈**：`ops/health.py` 自检 + `auto_heal.py` 自动修复；目标指标追踪流水线成功率、数据完整率与自检通过率。
- **交付层（v8.7 预备）**：`digest.py` 把当日全部产出提炼成【结论/信号/风险/动作】四段 200 字简报（无 LLM key 走规则兜底）；`decision_replay.py` 生成纯本地单文件 HTML 决策回放；`bark_sender/channels.py` 渠道注册表，Bark 之外可加 webhook / 飞书，逐渠道失败隔离。
- **LLM 融合层（shadow）**：`llm_analyst.py` 对规则筛出的 top3 跑多头→空头→裁决三角色，观点只能引用当日数据快照，**不改任何订单**，`--evaluate` 与 5 日前瞻收益对账；统一通道 `core/llm.py`，密钥零硬编码，每次调用计入成本审计。

> **当前状态（2026-09-17 核验更新）**：① LLM 融合层仍待配置 `DEEPSEEK_API_KEY`（llm_available=False）；
② QuantMorningPipeline（09:15）与 QuantStallWatchdog（21:00）两个计划任务均已注册就绪；
③ 日终流水线已恢复（b828b9a），logs/pipeline_20260916.log 起 15:37 档每日运行正常；
④ 4 个 bat 行尾问题（计划任务 9009）已于 2026-09-04 重写修复并验证。

## 验证

```powershell
python -m pytest                # 单元与回归测试（需 pip install pytest，见 requirements.txt）
python ops/health.py            # 系统自检（含环境、密钥、文件、数据新鲜度，报告写入 reports/）
python smoke_tests.py           # 冒烟测试
python goal_metrics.py          # 目标指标
python daily_pipeline.py        # 手动执行一次日终流水线
python check_trading_day.py     # 交易日检测
python digest.py --dry-run      # 预览开盘前四段简报（无 LLM key 走规则兜底）
python decision_replay.py       # 生成当日决策回放 HTML（results/replay_YYYYMMDD.html）
python llm_analyst.py --evaluate # 评估 shadow 多空分析历史命中率
```

## 目录

```text
app/                  Streamlit 仪表盘页面与加载器
core/                 配置、流水线注册表与共享逻辑
bark_sender/          Bark 推送构建与重平衡
tests/                单元与回归测试
scripts/              桌面快捷方式与维护脚本
books/                策略与数据工程笔记
docs/decisions/       设计决策与评审归档
data/                 本地行情与账户状态（不进入 Git）
```

## 风险声明

这是研究和纪律训练工具，不构成投资建议，也不能保证盈利。任何真实交易决定都必须由使用者独立判断，并自行承担风险。
