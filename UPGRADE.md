# 量化交易系统 v8.6 — 升级手册

> **当前版本**：v8.6（2026-05-23）— 反向反馈循环修复 + Alpha Gate 自动暂停 + 测试覆盖
> 历史版本：v8.0（5/17 DAG）→ v8.5（5/18 P0 + 5/19 工程债）→ v8.6（5/23 P0/P1 + 32 测试）
>
> 本手册说明「分级解锁架构」如何随本金增长激活更多模块。
> **核心原则：所有代码物理保留；升级 = 改一行配置 + 重启**。

---

## 1. Tier 总览

| Tier | 适用资金 | 自动激活模块 | 升级触发动作 |
|------|----------|--------------|--------------|
| `beginner` | 1,200 ~ 30,000 元 | 行情·选股·仓位·出场·Bark 推送·成本审计·心理助手·新手保护 | （初始默认） |
| `advanced` | 30,000 ~ 200,000 元 | + 基本面/资金流·增强回测·因子分析·Walk-Forward·蒙特卡洛·策略竞技·策略自动进化·sim_trade `full` 模式 | 本金 ≥ 3 万 |
| `pro` | 200,000 ~ 500,000 元 | + 组合风控（CVaR/VaR/相关性）+ Bark 风控附录 | 本金 ≥ 20 万 |
| `auto` | 500,000+ 元 + 量化 API | + 券商订单生成 + Bark 订单附件 | 本金 ≥ 50 万 且开通券商 API |

> Tier 之间是「累加」关系：高 tier 自动包含低 tier 的全部功能。

---

## 2. 切换 Tier 的两种方式（任选其一）

### 方式 A：环境变量（临时 / 测试推荐）

```bash
# Windows PowerShell
$env:QUANT_TIER = "advanced"

# Windows CMD
set QUANT_TIER=advanced

# Git Bash / Linux / Mac
export QUANT_TIER=advanced
```

只对当前 shell 会话生效，重启即失效。适合**先临时跑一次验证**。

### 方式 B：持久配置（生产推荐）

修改 `data/system_config.json`：

```json
{
  "tier": {
    "level": "advanced"
  }
}
```

文件不存在时，首次运行 `python daily_pipeline.py` 会自动创建 `DEFAULTS` 副本，再编辑即可。

> 优先级：环境变量 `QUANT_TIER` > 配置文件 `tier.level` > 默认 `beginner`。

---

## 3. 升级路径详解

### 🌱 1,200 → 30,000 元（保持 beginner）

资金未到 3 万门槛前，**无需任何配置改动**。系统在 beginner tier 自动跑：

- 仅运行 20 步精简流水线（行情/选股/仓位/出场/推送 等）
- `sim_trade` 走 `lite` 模式（只读 CSV 算盈亏，不模拟撮合/滑点）
- Bark 推送用「新手简洁卡」：买什么/多少钱/止损/摩擦成本
- 不跑回测/因子分析/walk-forward/蒙特卡洛/策略竞技

**资金成长建议**：把仓位日志同步进 `real_trades.csv`，让 `strategy_feedback.py` 学习你真实的胜率。

---

### 🌿 30,000 元 → 切到 `advanced`

```json
{ "tier": { "level": "advanced" } }
```

激活：
- ✅ `data_loader` —— 加载基本面 + 资金流数据
- ✅ `enhanced_backtest` —— 每日严格回测
- ✅ `factor_analysis` —— 周一跑 IC/IR
- ✅ `walk_forward` —— 周三跑滚动验证
- ✅ `monte_carlo` —— 月末跑情景模拟
- ✅ `strategy_arena` —— 周五跑策略竞技
- ✅ `evolve_strategy --auto` —— 周四自动进化
- ✅ `external_research` —— 周一拉 arXiv
- ✅ `sim_trade` —— 切到 `full` 模式（撮合/滑点/执行质量）
- ✅ Bark 推送切到「标准模板」+ 多策略对比

> 验证命令：`QUANT_TIER=advanced python daily_pipeline.py --dry-run`，应看到 ~28 步激活。

---

### 🌳 200,000 元 → 切到 `pro`

```json
{ "tier": { "level": "pro" } }
```

在 advanced 基础上**额外**激活：
- ✅ `portfolio_risk` —— 每日跑 CVaR/VaR/回撤/波动率/相关性
  - `sim_trade.py:759-780` 接入风控决策：回撤超限自动取消买单
  - 健康面板会显示 `数据/risk_report.json` 摘要
- ✅ Bark 推送附加「组合风控」区块（回撤、波动率、相关性预警、建议）

> 此时建议同步把 `data/system_config.json` 中 `position.default_capital` 改为实际资金，防止 `position_sizer.py` 仍按小资金路径下单。

---

### 🚀 500,000 元 + 量化 API → 切到 `auto`

```json
{
  "tier": { "level": "auto" },
  "broker": {
    "max_single_amount": 50000
  }
}
```

在 pro 基础上**额外**激活：
- ✅ `broker_adapter` —— 生成东方财富/同花顺/通用 CSV 订单文件到 `broker_orders/`
- ✅ Bark 推送附加「券商订单」附录（列出当日生成的订单文件）
- ⚠️ 真正接 API 自动下单需另外接券商 SDK，本系统只生成订单文件供导入

**额外检查清单（接入 API 前）**：
1. 把 `broker.max_single_amount` 调到实际资金的 5-15%
2. 确认 `position.default_capital` 与真实账户匹配
3. 先在测试账户跑一周，比对 `sim_results/sim_state.json` 与真实账户净值

---

## 4. 升级前后对照速查

| 配置改动 | 影响的步骤数（v8 注册表） | sim 模式 | Bark 模板 |
|----------|--------------------------|----------|-----------|
| 默认 beginner | ~20 / 31 步 | lite | newbie-simple |
| advanced | ~28 / 31 步 | full | standard |
| pro | ~29 / 31 步 | full | standard + risk |
| auto | ~30 / 31 步 | full | standard + risk + broker |

> 调度敏感步骤（factor_analysis 周一 / walk_forward 周三 / strategy_arena 周五 / monte_carlo 月末 / external_research 周一 / evolve_strategy 周四）受当日日期影响。

---

## 5. 验证升级是否成功

每次切 tier 后，按顺序执行：

```bash
# 1. 看 tier 是否被识别
python -c "from core.config import SYSTEM_TIER; print(SYSTEM_TIER)"

# 2. 看流水线列表（每步状态）
python -m core.pipeline --list

# 3. 看流水线 dry-run（哪些会跑、哪些休眠）
python daily_pipeline.py --dry-run

# 4. 看 Streamlit 健康页"系统能力图"
streamlit run app.py
# → 进入"系统健康"页，顶部即为能力图
```

---

## 6. 回退（降级）

直接把 `tier.level` 改回低 tier，所有高级模块自动休眠，数据保留。
休眠模块的代码物理不动，调用其函数（如 `from portfolio_risk import calc_cvar`）依然可用，
仅是它们不参与每日自动流水线。

---

## 7. 常见误区

❌ **误区**：以为升级要重新部署
✅ **真相**：改 `data/system_config.json` 一行 + 重启 `daily_pipeline` 即可

❌ **误区**：以为低 tier 关掉的模块代码会被删
✅ **真相**：所有 .py 文件物理保留，可手动 `python xxx.py` 跑（受各自 tier gate 提示）

❌ **误区**：以为佣金/资金过滤跟着 tier 走
✅ **真相**：`position_sizer.py / cost_tracker.py / exit_advisor.py / send_to_bark.py` 都在
`ALWAYS_ON_FEATURES`，所有 tier 都启用，小资金防亏核心永不休眠

---

## 8. 参考链接（项目内）

- 配置中心：`core/config.py`（DEFAULTS / SystemTier / ENABLE_* 标志）
- 步骤注册表：`core/pipeline.py`（PIPELINE_STEPS）
- Python 入口：`daily_pipeline.py`
- Bat 包装：`daily_pipeline.bat`（仍可被 Windows 任务计划程序调用）
- Bark 模板：`bark_sender/builders.py`（含 `build_bark_message_for_tier`）
- 健康面板：`app/pages.py:render_system_health_page` 顶部新增"系统能力图"
