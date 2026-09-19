# `data/risk_config.json` 键位说明（q918-29，纯文档）

- 生成：2026-09-19（夜班 `qoder-rev-20260919-1020`）。依据：根仓 `docs/insights/quant-config-key-gap-20260914.md:26`
  提出的「为 `risk_config.json` 建 schema 说明或 example（键位以 strategy_feedback.py/sim_trade.py 消费点为准）——新增建议，未实施」，
  以及 `docs/insights/quant-riskconfig-key-inventory-20260916.md:9-16` 的 key 清单。
- **本文件不含任何数值**：所有阈值一律用「代码默认见 `file:line`」的方式指路，**不抄录具体数字**。
  两个原因：① 风控阈值属红线域（资金与统计数值结论），文档不该成为第二份真相；② 抄了就一定会漂。
- ⚠ **改动任何键的值都需日间拍板**：本文件只是键位地图，不构成"照着改就行"的许可。

## 一、这个文件是什么

`data/risk_config.json` 是 **`strategy_feedback` 反向反馈循环的输出面**（"系统建议的风控覆盖值"），
不是用户配置文件。它的**基线**在另一处：`core/config.py` 的 `DEFAULTS['sim']`（`:95-101`）∪ `data/system_config.json` 的 `sim` 节。
链路是：`sim.*`（代码默认，可经 system_config 覆盖）→ 被 `risk_config.json` 里的同名键**按规则覆盖**（见第三节）→ 供出场/模拟交易/推送使用。

⚠ 别和 `cfg_get('risk.*')` 混：`portfolio_risk.py:27-30` 读的 `risk.drawdown_limit` 等 4 条是**另一个命名空间**，
`system_config.json` 与 DEFAULTS 里都没有 `risk` 节（详见 `docs/insights/quant-cfgget-audit-design-20260918.md` 第二节），
与本文件描述的 `risk_config.json` 无关。

## 二、键位表（5 个功能键 ＋ 1 个元数据键）

| 键 | 类型 | 语义 | 写入方 | 读取方 | 键缺失时的行为 |
|---|---|---|---|---|---|
| `stop_loss_pct` | number | 止损线（负百分比） | `strategy_feedback`（经 `adjustments`）；重建 `auto_heal.py:80` | `sim_trade.py:874`/`:960`（**仅当 `alert_only` 不为 True**，见第三节）；`exit_advisor.py:38` | 消费端回退代码默认（`core/config.py:97` 的 `sim.stop_loss_pct`） |
| `take_profit_pct` | number | 止盈线 | `strategy_feedback`；重建 `auto_heal.py:81` | `sim_trade.py`（同上，alert_only 时被跳过）；`exit_advisor.py` | 回退 `core/config.py:100` |
| `max_hold_days` | int | 最长持有交易日 | `strategy_feedback`；重建 `auto_heal.py:82` | `sim_trade.py:875`/`:961`（**alert_only=True 时唯一仍被读取的覆盖键**）；`exit_advisor.py:47-48` 同语义 | 回退 `core/config.py:101` |
| `position_size_mult` | number | 仓位系数（反馈循环建议的缩放） | `strategy_feedback.py:763` 写入；重建 `auto_heal.py:83` | **未见任何决策读取点**（见第四节）；`ops/health.py:283` 只做"键是否存在"的健康检查；`strategy_feedback.py:842` 把它渲染进反馈报告 | 无影响（因为没人读） |
| `alert_only` | bool | 只告警开关：True ⇒ 反馈循环**不得**覆盖止损/止盈，只允许改 `max_hold_days` | 重建 `auto_heal.py:84` 写的是 **True** | `sim_trade.py:155`；`exit_advisor.py:52`（判据 `is True`） | **两处的缺省不一致**：`sim_trade.py:155` 与 `exit_advisor.py:52` 都按 `False` 处理（键缺失 ⇒ 允许覆盖）。而 auto_heal 重建文件时写 True ⇒ **"文件被重建"与"文件不存在"两种状态下，覆盖行为相反**，改这个键前务必知道这点 |
| `updated` | string | 写入时刻（`%Y-%m-%d %H:%M:%S`），仅溯源用 | `auto_heal.py:85`；反馈写回路径 | **无人读取** | 无影响 |

任务书写"5 key"，inventory 表格给了 6 行：差的那个是 `updated`（元数据）。**本表按 5 个功能键 ＋ 1 个元数据键登记**，与两侧口径都能对上。

## 三、`alert_only` 决定"哪些键真的生效"（最容易踩的一条）

`sim_trade.load_risk_config()`（`:142-171`）的映射表是**硬编码白名单**，且随 `alert_only` 变：

```python
sim_trade.py:155   alert_only = config.get('alert_only', False) is True
:156-158           alert_only=True  → config_items = [('max_hold_days', 'MAX_HOLD_DAYS')]        # 只接管持有天数
:159-164           否则             → [('stop_loss_pct','STOP_LOSS_PCT'), ('take_profit_pct','TAKE_PROFIT_PCT'),
                                       ('max_hold_days','MAX_HOLD_DAYS')]
:166-171           只有 config 里存在该键才放进 applied，返回【大写键】字典
```
⇒ 调用方读的是**大写名**：`sim_trade.py:874-876` 与 `:960-962` 用 `risk.get('STOP_LOSS_PCT', STOP_LOSS_PCT)` 等，
这是 `load_risk_config()` 设计的输出接口（**不是大小写 bug**，别照着文件里的小写键去改调用方）。
⇒ `position_size_mult` **不在这个白名单里**，所以无论 `alert_only` 取什么值，它都不会经 sim_trade 生效。
⇒ `exit_advisor.effective_risk_config()`（`:44-63`）另有一套对齐逻辑（注释自称"与 sim_trade.load_risk_config 的 alert_only 语义对齐"），
但它是**独立实现**，且 `exit_advisor.py:65` 有自己的 `load_risk_config()` —— 同一个 JSON 文件有**三份读取实现**
（`sim_trade.py:142`、`exit_advisor.py:65`＋`:44`、以及 `ops/health.py:283` 的裸读）。改语义时必须三处一起看。

## 四、一条值得日间确认的键位事实（不判定，只登记）

`position_size_mult`：**写入方、健康检查、报告渲染都在，唯独没有决策读取方**。
穷举依据（本单实测，命令在第六节）：全仓 `*.py`（去掉 `.venv/archive/backup`）里 `position_size_mult` 只出现在
`auto_heal.py:83`、`ops/health.py:283`、`strategy_feedback.py:419/473/480/487/577/584/655/662/669/763/842`、以及 `tests/test_strategy_feedback.py` 的 5 处断言。
`position_sizer.py`、`sim_trade.py`、`exit_advisor.py` **均无该键**。
⇒ 反馈循环"调整仓位系数"并把它写进 `risk_config.json`、写进报告表格，但当前没有任何下单/仓位代码消费它。
**这是设计缺口还是尚未接线，涉及仓位计算（红线），本文件只登记事实，不下结论、不改码。**

## 五、改动规程（拍板要求）

1. 改任何键的**值** ⇒ 属风控/仓位参数变更，按根配置必须走多模型评审；本文件不给"可以直接改"的许可。
2. 改任何键的**名或语义** ⇒ 必须先同步第三节的三份读取实现（`sim_trade.py:142`、`exit_advisor.py:44/65`、`ops/health.py:283`），
   并注意 `sim_trade.load_risk_config()` 的大写输出接口。
3. 想让 `position_size_mult` 真正生效 ⇒ 需要新增消费点（仓位计算），属策略逻辑改动，另出稿评审。
4. `alert_only` 的双默认不一致（第二节末）若要统一，先确认哪一侧是想要的语义，再改另一侧——两个改法行为相反，别顺手。

## 六、复现命令

```bash
cd /d/code/my-quant-system-v8
# 键位与消费点
for k in stop_loss_pct take_profit_pct max_hold_days position_size_mult alert_only updated; do
  echo "--- $k"; grep -rn "$k" --include="*.py" . | grep -v "\.venv\|^\./archive\|^\./backup\|^\./tests"
done
# 只列当前文件里有哪些键（不看值）
python -c "import json;print(sorted(json.load(open('data/risk_config.json',encoding='utf-8'))))"
# 代码默认（sim 基线）
sed -n '95,101p' core/config.py
```

## 七、与 inventory 的差异（09-16 → 09-19 的漂移）

| inventory（`:9-16`）说法 | 本单实测 |
|---|---|
| `position_size_mult` 读取点「sim_trade.py（经 cfg_get）」 | **不成立**：`sim_trade.py` 全文无 `position_size_mult`（见第四节穷举）；`load_risk_config` 的白名单（`:159-164`）也不含它 |
| `alert_only` 默认「false」 | 消费端缺省确实是 False（`sim_trade.py:155`、`exit_advisor.py:52`），但**重建路径写 True**（`auto_heal.py:84`）——inventory 未记这层不一致 |
| `stop_loss_pct` 等「core/config.py:97, sim_trade.py:111」 | `core/config.py:97` ✓ 未漂；sim_trade 侧现为 **:111-113 常量** ＋ **:874-876/:960-962 覆盖点**（inventory 只给了常量那处） |
| 表共 6 行 | 与本文件第二节一致（5 功能键 ＋ `updated`） |
