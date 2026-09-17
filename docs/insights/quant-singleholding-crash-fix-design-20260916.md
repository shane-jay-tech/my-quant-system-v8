# quant generate_risk_report 单持仓（correlation=None）崩溃——复现＋修复设计（n916e-05）

- 班次：日间续班（用户令继续）
- **状态备注：本单所设计的修复已由 n916d-16 落地**（提交 736a778，2026-09-17 凌晨段；同仓同 bug 的另一次制单）。本报告＝设计材料存档＋落地复核，零生产码改动（工作树仅 4 文件班前遗留脏树，与本单无关）

## 一、复现（命令在前；修前形态）

```
$ python -m pytest tests/test_portfolio_risk.py -q        （修复前实测）
..................x.    [100%]
19 passed, 1 xfailed in 2.02s
```

xfail 行：`test_generate_report_supports_single_position`（tests/test_portfolio_risk.py:202-205，strict=True，reason「generate_risk_report 对 correlation=None 直接调用 .get，单持仓会崩溃」）。触发路径：单持仓 ⇒ codes 长度 1 < 2 ⇒ `report['correlation'] = None`（:278）⇒ 汇总段 `report.get('correlation', {}).get('warning')`（:291）——**key 存在值为 None 时 dict.get 默认 `{}` 不生效** ⇒ `None.get` AttributeError。

## 二、根因（file:line）

`portfolio_risk.py:291`（修前行）：`report.get('correlation', {}).get('warning')`——对「键存在但值为 None」误用默认值语义。非动态分派，根因唯一。

## 三、三方案对比（设计材料）

| 方案 | 内容 | 优点 | 缺点 | 判定 |
|---|---|---|---|---|
| A 降级输出（`or {}` 兜底） | `(report.get('correlation') or {}).get('warning')` | 一行改动；None/缺键双兜底；告警语义不变 | 无 | **推荐（已采纳）** |
| B 显式异常 | correlation is None 时 raise | 强制上游处理 | 单持仓是**合法状态**非错误，raise 属语义错误 | 否 |
| C 单持仓专用分支 | len(codes)==1 时跳过汇总段 | 显式 | 重复表达 :278 已有分支逻辑，维护面大 | 否 |

## 四、落地复核（n916d-16，736a778）

```
$ sed -n '291,293p' portfolio_risk.py
    # correlation=None（单持仓/无数据）时 dict.get 的默认 {} 不生效——or {} 兜底
    # （n916d-16 最小修复：只防空，不改任何数值口径）
    if (report.get('correlation') or {}).get('warning'):
$ python -m pytest tests/test_portfolio_risk.py -q
......................    [100%]
22 passed in 1.64s        ← xfail 已转正＋2 边界用例（空持仓；双持仓 calc=None），0 xfail
```

修复后验收命令（任务书要求形态）：`python -m pytest tests/test_portfolio_risk.py -q` ⇒ 22 passed（原 xfail 用例现为正常 pass）。

## 五、影响面与回归

- 调用方：daily_pipeline／goal_metrics 等经 generate_risk_report 消费 recommended_actions——`or {}` 仅防空，告警产出条件与非 None 时逐字节一致 ⇒ 零行为变化（除不再崩溃）。
- 回归：全量 `python -m pytest -q` ⇒ 663 passed / 4 skipped / 1 xfailed（test_strategy_core 既有件）/ **0 failed**（n916d-16 实测记录）。

## 六、git diff --stat（本班零生产码改动）

```
$ git diff --stat
 AGENTS.md / README.md / auto_heal.py / data_loader.py   ← 4 文件班前遗留脏树（n916d-20 已 triage）
（portfolio_risk.py 无未提交改动——修复已在 736a778 提交）
```

——完。
