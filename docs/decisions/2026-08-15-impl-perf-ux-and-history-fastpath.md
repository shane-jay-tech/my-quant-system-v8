# 全系统体检 + 性能/UX 优化 + 历史K线快路径（多模型协作）

> 日期：2026-08-15（会话自 2026-08-14 晚开始） · 版本 v8.6 · 协作方式按根配置 D:\code\AGENTS.md（三模型）

## 原始需求

"全面了解系统当前状态，进行 bug 寻找与系统优化，着重优化系统性能（启动速度、加载速度等）与系统人性化设计，拒绝反人类设计。"

## 现状体检结论（基线数据）

- 仪表盘：Streamlit 1.58 + plotly 6.8 + pandas 3.0；import app.pages 1.13s，市场状态页渲染 1.47s（最慢），其余 <0.9s。
- 每日流水线（日志 pipeline_20260814.log）：总耗时约 75 分钟，其中 fetch_history.py 独占约 58 分钟（逐股新浪K线，3线程+0.5-1s节流，防 456 限流）。
- 测试基线：pytest 235 passed / 2 xfailed；自检 142 项中 external 2 项 FAIL（Windows 计划任务缺失）。
- 已确认 bug 清单：流水线控制页"生成洞察/一键全流程/推送健康报告"因参数不拆分必然失败；健康页写死读 system_self_check_v75.json（陈旧数据）；新手模式开关重启后复位并删 .newbie_mode；run_pipeline_step 超时后子进程孤儿化；Python 路径写死本机用户目录；涨跌颜色中西混用；流水线日志因缓冲乱序+中文乱码。

## 快路径多模型协作（数据源改动 → 强制多模型 + 双实现触发）

### 我方方案（A，总指挥）

东财 clist 单请求全市场当日 OHLC → 只覆盖「仅缺今日」的股票（latest==market_max）→ 行级 OHLC/成交量/日期校验 + 与新浪当日快照量价交叉校验 → 写盘前备份 history.csv.bak → 追加 → 最终去重原子写；盘中（工作日 09:25-15:05）跳过快路径；失败任一环整体回退新浪逐股路径；QUANT_HISTORY_NO_FASTPATH=1 可整体关闭。

### GPT-5.6 独立实现（经 Codex CLI 直连，gpt-5.6-sol，read-only）

产出关键段（verbatim）：

~~~python
def apply_eastmoney_snapshot_fast_path(codes_to_fetch, latest_by_code, target_date, *,
    data_dir=DATA_DIR, save_func=None, minimum_candidate_coverage=0.90):
    """将"仅缺目标日"的股票通过东方财富快照一次性补齐。"""
    previous_date = _previous_local_trading_date(target_date, data_dir)
    eligible = [code for code in requested
                if str(latest_by_code.get(code, ""))[:10] == previous_date]
    ...
    candidate_coverage = len(fetched_codes) / len(eligible)
    if candidate_coverage < minimum_candidate_coverage:
        ...拒绝写入，全部切换新浪
    save_func(fast_frame)
    remaining_codes = [code for code in requested if code not in fetched_codes]
    return remaining_codes, len(fast_frame)
~~~

其使用说明要求 pip install fake-useragent；快照解析段对成交量只判 <0 即放过 0 成交量的行；未含与新浪快照的交叉校验、无 .bak 备份。

### DeepSeek V4 Pro 评审（llm_call relay，verbatim）

> 评审意见：**有条件同意**东财快照作主路径+新浪兜底，但必须收盘后运行并完成下述校验。
> 实现要点：单请求解析 clist，字段映射：f12代码、f2收盘、f15最高、f16最低、f17今开、f18昨收、f5×100转股。仅对 f5>0 且历史最新日期<目标日 的股票追加。关键校验：全量检查 OHLC 关系（低≤开/收≤高）、成交量>0、代码当日唯一；抽样对比新浪源量价偏差>1%报警；写临时文件，校验通过后原子替换，保留 history.csv.bak。
> 最危险3个坑：1. 实时口径：盘中或非盘后运行 f2 非收盘价，必须用 f124 确认当日且收盘后执行。2. 成交量单位：f5 为手需×100，但不同来源/特殊股票可能不一致，易造成量级错误。3. 双源不一致：东财与新浪回退股口径可能不同，仅抽样会漏检，需扩大交叉验证或对回退股单独复核。
> 五维度结论：正确性依赖盘后+全量校验；数据安全须校验失败不写盘；兼容性不新增依赖、适配代码格式即可；反爬合规单请求+退避，风险低；可回滚靠临时文件+备份，失败保留旧文件。
> **必修项**：增加全量 OHLC 与量级校验、确认 f124 为交易日、原子写盘与备份回退。完成后方可作为主路径。

### Flash 快审（第一遍审，verbatim）

> 基于所给实现要点，未发现必修问题。建议：1) 统一并校验 f124 日期格式（如去除时间部分）后再比较，避免快照日期带时间导致匹配失败；2) 明确价格/量偏差判定条件及阈值，防止覆盖率误放弃；3) 对缺失的新浪快照文件做存在性检查并优雅降级，避免 FileNotFoundError。

### 仲裁（先立标准再看方案）

验收维度与权重：正确性40% / 数据安全20% / 可维护20% / 成本10% / 体验10%。

| 维度 | A（总指挥） | B（GPT-5.6） | 裁决 |
|---|---|---|---|
| 正确性 | 行级全量校验+量价交叉校验+盘中保护 | 无交叉校验；成交量=0 行放过（一字板停板股会污染量比类因子） | A |
| 数据安全 | 写前备份 .bak + 最终去重原子写 | 直接追加，无备份 | A |
| 兼容性 | 无新依赖 | 需 pip install fake-useragent | A |
| 覆盖率口径 | 分母=eligible 阈值0.90（吸收 B） | 同口径（B 先提出） | 融合 |
| 前一交易日判定 | history.csv market_max（不依赖快照文件留存） | 扫描 stock_*.csv 文件名（7天归档窗口下长假后可能误判，会安全回退） | A |

外部 finding 处理：DeepSeek 3 条必修全部落地（全量校验 / f124 交易日 / 原子写+备份+盘中保护）；Flash 3 条建议经核对均已在设计中覆盖（f124 已归一化字符串比较、阈值有注释、新浪快照缺失走 try/except 降级）。GPT 版 2 个 MAJOR（新增依赖、0 成交量行）被仲裁规避。**override 次数：0**。

## 全部改动清单

| 文件 | 改动 | 类型 |
|---|---|---|
| fetch_history.py | 东财快路径 + fs 双变体回退 + 最终去重原子写 | 性能（58min→秒级） |
| core/pipeline.py | 每步时间戳+耗时输出（flush=True） | 可观测性 |
| daily_pipeline.bat | python -u（日志顺序正确）+ 纯 ASCII（根治乱码） | 可观测性 |
| app/loaders.py | run_pipeline_step：sys.executable/QUANT_PYTHON、shlex 拆参数、超时杀进程 | bug |
| app/pages.py | 惰性 plotly/trade_analyzer 导入；use_container_width→width=stretch ×27；一键全流程/洞察/健康推送参数修复；选股榜单过期警告；我的交易分析缓存(ttl300)；市场状态页牛熊色带合并（1.47s→0.10s）；健康页按版本读自检 JSON；涨跌颜色统一为 A 股红涨绿跌 | 性能+bug+UX |
| app/sidebar.py | 新手模式状态持久化（重启不再静默关模式）；刷新按钮改名+说明 | bug+UX |
| launcher.pyw | 启动提示文案与实际相符 | UX |

## 验证

- pytest：235 passed / 2 xfailed；smoke_tests：48/48；AppTest 八页渲染 0 异常（市场状态页 1.47s→0.10s，模拟交易 0.86s→0.51s，我的交易 0.40s→0.19s）。
- fetch_history：快路径纯函数单测全过（解析/过滤/手转股/陈旧检测/交叉校验阈值）；真实运行 exit=0；网络不可达时双 fs 变体重试→优雅回退新浪（日志验证）。
- Streamlit 真实启动：uvicorn 起服 ≈1.5s，health ready。
- 自检：142/142（此前 external 2 项 FAIL 的计划任务已在本会话重建恢复）。
- daily_pipeline.py --dry-run 正常（26 步/tier=beginner/周六）。

## 残留风险

1. 快路径完整链路（真实东财数据入库）尚未在交易日在线验证——本会话执行环境网络对东财间歇不通；已用合成数据验证全部逻辑，且运行时自带交叉校验与回退，首日实盘跑一次建议人工看一眼日志（[EM-FASTPATH] OK 或 FALLBACK）。
2. 东财接口对该网络间歇不可达时会整段回退新浪（正确但回到约 58 分钟），属预期降级而非故障。
3. history.csv.bak 每日多占 44MB 磁盘（保留最近一份）。

---
*归档：GPT 原文存于会话临时文件 temp/gpt_codex_impl.txt（要点已摘录如上）；协作中间产出均幕后，用户侧只呈现结论。*
