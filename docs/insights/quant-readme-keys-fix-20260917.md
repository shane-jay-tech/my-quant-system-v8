# quant README 链条缺 6 键补齐＋4 条时效订正（917-30）

**结论：README:59 链条补齐 6 缺步（data_loader 数据层／backtest 回测(分档成本)／track_performance 追踪／portfolio_risk 组合风控〔风控门段既有叙述〕／broker_export 券商导出／newbie_card 新手指令卡）——按 a1-018 §四草稿逐字落地；:74 四条时效注记按同稿订正。复核＝注册表 daily 35 键逐一对照 README 叙及「无未叙及」（35/35）。git diff --stat 仅 README（+8/−3，其中含班前既有脏行并入）。**

## 一、改前/改后（命令与数字同段）

```
改前差集（a1-018 报告口径）：缺 6 键＝data_loader, backtest, track_performance, portfolio_risk, broker_export, newbie_card
改后复算：35/35 全叙及，未叙及 key = 无
$ git diff --stat README.md → 8+/3-（链条行 1 处重写＋时效注记 4 行订正）
```

## 二、4 条时效注记逐条结论（README:74 已按草稿更新）

| # | 原注记 | 订正后 |
|---|---|---|
| ① | LLM 融合层待配置 DEEPSEEK_API_KEY | 保留（llm_available=False 仍成立） |
| ② | 晨间任务尚未注册 | 两任务（09:15／21:00）均已注册就绪 |
| ③ | 流水线 2026-08-21 起停摆 | 已恢复（b828b9a），9/16 起 15:37 档每日运行 |
| ④ | 4 个 bat 行尾待验证 | 已于 9/4 重写修复并验证 |

（a1-018 §三 已有证据：schtasks 双任务查询、pipeline_20260916.log 15:37 档、b828b9a 提交。）

## 三、验收情况

- ✅ 缺口数 6→0（35/35 复算同段）；✅ 4 条时效注记逐条有结论（同段）；✅ git diff --stat 仅 README.md（+8/−3，本单改动）；✅ 不改代码与配置、不 push；README 精确路径 git add。

## 遗留问题

无。README 班前既有脏行（a1-015 已归因）随本单暂存一并呈现，归属区分以本报告为准。
