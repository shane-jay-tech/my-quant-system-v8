# 量化 S4 批 c/d R2 日间快审记录（2026-09-11，只读复核）

> 触发：2026-09-11 晨报栏目六-8「S4 批 c/d 待 R2 逐文件 diff 快审」；用户当日批准「按建议进行」。审阅者：dsh 日间总指挥（只读，未改任何量化代码）。
> 范围：my-quant-system-v8 的 S4 五批提交 0a38783 / 69db7f0 / cd33e6d / 38e111d / 11a95be（重点 c/d 两批高敏），当前 HEAD=11a95be，分支 main。

## 一、结论

**批 c（路径收敛）与批 d（凭据收敛）通过日间快审**：类型变更（str→pathlib.Path）与调用点改造无回归，全量测试 437 passed + 2 xfailed；发现的 4 条问题全部为 MINOR/SUGGESTION（不阻塞），见下表。**唯一需要实机验证的遗留**：Bark 令牌读取路径新增了环境变量层，需按晨报建议做一次真实推送验证（需用户在场授权）。

## 二、核验证据

| 项 | 做法 | 结果 |
|---|---|---|
| 类型变更面 | grep `DATA_DIR/RESULTS_DIR/ORDERS_DIR/SIM_DIR/REAL_TRADES_FILE` 后接 `+` `%` `.startswith` `.endswith` `.split` | 0 命中（无「假设 str」的用法） |
| 迁移覆盖面 | grep `from core.paths import` | 17 个 import 点，含 ops/health、data_loader、fetch_*、strategy/backtest/risk/sizer/sim_trade |
| 行为等价（批 c） | 逐文件看 diff：常量替换 + 两处保留 `BASE_DIR` 作为 monkeypatch 接缝（position_sizer `_resolve_default_capital`、sim_trade `calc_execution_quality`） | 与提交信息一致，接缝未被破坏 |
| 行为等价（批 d） | 逐段看 `bark_sender/config.py`、`channels.py`、`ops/health.py` 改造 | 语义等价，详见第三节 |
| 棘轮断言 | 读 `tests/test_s4e_no_base_joins.py`（81 行） | 存量 49 文件/155 处冻结、新增即失败 |
| 回归 | `python -m pytest tests -q`（仓内） | **437 passed, 2 xfailed, 10.44s** |

## 三、发现（按评审格式）

```
ID: S4CD-1
严重级别: MINOR
类别: 可维护
证据: bark_sender/config.py（38e111d）：模块顶层新增 sys.path.insert(0, _PROJECT_ROOT) 以 import core.secrets
触发条件: 任何进程在导入 bark_sender.config 时（含测试、CLI）
影响: 导入有副作用（污染 sys.path）；同仓其它入口若路径顺序不同，理论上可能引用到同名模块
建议修复: 由调用方（send_to_bark / 测试）保证仓根在 sys.path，或在 config.py 内用 importlib 按绝对路径加载（不改也行，属卫生问题）
置信度: 中

ID: S4CD-2
严重级别: MINOR
类别: 可维护 / 可观测
证据: bark_sender/channels.py（38e111d）：原 `secrets.json 解析失败` 的告警 print 被删除，改为 get_secret_object('NOTIFY_CHANNELS')
触发条件: data/secrets.json 存在但损坏时
影响: 运营者不再在日志里看到「解析失败」，只会看到「没有可用渠道」——排障线索变少
建议修复: 在 core.secrets._load_kv 失败路径加一条一次性 stderr 告警（保持密钥值不落日志）
置信度: 高

ID: S4CD-3
严重级别: SUGGESTION
类别: 一致性
证据: core/secrets.py：get_secret() 走 env→.env.local→JSON；新增 get_secret_list() 只走 env→JSON（未查 .env.local）
触发条件: 只在 .env.local 里写 BARK_TOKENS 时
影响: 该值读不到（旧实现同样只读 JSON，故非回归；但两个函数解析顺序不一致会埋坑）
建议修复: get_secret_list/get_secret_object 复用 get_secret 的解析顺序（列表/对象分支除外）
置信度: 高

ID: S4CD-4
严重级别: SUGGESTION
类别: 功能
证据: ops/health.py（38e111d）：`External: Bark token in secrets` 的判据改为 get_secret('BARK_KEY') or get_secret_list('BARK_TOKENS')；「源码硬编码 token 扫描」仍只在 secrets.json 缺失时执行
触发条件: secrets.json 存在但 key 只放在环境变量时
影响: 无（判据更宽，扫描时机与旧版一致）；仅提示：硬编码扫描是安全项，建议提升为常跑
建议修复: 把硬编码扫描从 else 分支提出来，作为独立检查项
置信度: 中
```

## 四、待办（需用户或日间后续）

1. **Bark 实推验证**（阻塞在用户授权）：`send_to_bark.py` 走一次真实推送，确认「环境变量层新增生效」没有改变端到端行为；建议先在测试频道推一条。
2. 上述 4 条 MINOR/SUGGESTION 可并入下一次 S4 收尾批或独立小单（均非阻塞）。
3. 批 a/b/e 已由夜间班自查（q4bc 全量 pytest 抓出 1 例 monkeypatch 语义破坏并修复；批 e 棘轮冻结 49/155）——本记录不重复覆盖。

## 五、口径与遗留

- 本记录**只读**：未改动任何代码、未跑业务脚本、未动数据库与配置。
- 复核用的全量测试为仓内 `tests/`（437 项），未含需要联网/行情数据的长跑项。
- 归档：`my-quant-system-v8/docs/insights/s4-cd-r2-diff-review-20260911.md`（本文件）。