# quant-kb「待验证」条目 × strategy.py 实参漂移核对（q918-36，执行 2026-09-19）

> **红线声明**：本单全程只读。未改 `docs/knowledge/quant-kb.md` 一个字，未改 `strategy.py`／`core/config.py`／
> `data/system_config.json` 的任何参数值，也没有执行 confirm/整合动作——只出核对记录与建议。
> RSI/MA/ATR 这些数值的**取舍**属策略参数结论，按根配置必须走多模型评审，不在夜班权限内。

## 一、锚点复核

| 任务书锚点 | 磁盘实况 |
|---|---|
| `docs/knowledge/quant-kb.md:6`「**[待验证] RSI阈值根据大盘动态调整** — 牛市放宽RSI上限至75」 | ✓ 第 6 行逐字一致（文件共 8 行，:6 与 :7 就是那两条待验证） |
| `strategy.py:96 get_adaptive_params` 实参表「强牛：RSI(25,75)」 | △ 半对：`def get_adaptive_params` 在 **:91**，:96 是它 docstring 里的「- 强牛：RSI(25,75), MA(5,30)」注释行；**真实参表在 :110-114 的 `param_map` 字典**，与注释一致 |
| 隐含前提：条目是"某次实测得到的待验证结论" | ✗ **不成立**，见第三节（比参数漂移更值得看） |
| 完成标准 `pytest tests/test_integrate_dedup.py -q` → 3 passed | ✗ 漂移：实测 **8 passed in 1.62s**（该文件已长到 8 例）。结论"confirm/去重流程未破坏"仍成立 |

## 二、逐条对照

### 条目一：「牛市放宽RSI上限至75，熊市下移至55」 vs `strategy.py:110-114`

| 市场状态 | KB 条目说法 | `param_map` 实值（rsi_low, rsi_high） | 判定 |
|---|---|---|---|
| 强牛 | 上限放宽至 **75** | (25, **75**) | ✓ 吻合 |
| 弱牛 | （条目未提） | (28, 72) | — |
| 震荡 | （条目未提） | (30, 70) | — |
| 弱熊 | （条目未提） | (35, 65) | — |
| 强熊 | 「熊市下移至 **55**」 | (38, **60**) | ✗ **代码里没有任何一档是 55** |

补充两条，防止下一班误判：
1. `55` 在 `strategy.py` 里**确实出现**，但出现在完全不同的位置——`:176-177` 与 `:365` 的「RSI 合理性 20 分：45≤rsi≤55 最健康」评分区间。
   ⇒ **谁用 `grep 55` 去"证实"这条 KB，会得到假阳性**。
2. 「下移至 55」无论按上限还是下限解都对不上：上限最低档是 60（强熊），下限最低档是 25（强牛，方向相反）。
3. 这条参数**是否生效**也已核：`USE_DYNAMIC_PARAMS = cfg_get('strategy.use_dynamic_params', True)`（`strategy.py:55`），
   且 `data/system_config.json` 里 `strategy.use_dynamic_params = true`、静态 `rsi_low/rsi_high = 30/70`
   ⇒ 动态档当前**是开着的**，强牛 75 是活路径，不是死配置。

**结论**：条目一属"**半实现＋半错位**"，不能整体 confirm。
可核实的部分只有"牛市侧 75"；"熊市 55" 既不在代码里、也推不出来源。

### 条目二：「高ATR(>3%)股票降低评分，偏好低波动趋势股」 vs 评分函数

| KB 说法的构成要素 | 代码实况 | 判定 |
|---|---|---|
| 算 ATR | 有：`calc_atr()` `strategy.py:143`，`:300` 给每只股票加 `ATR` 列 | ✓ 存在 |
| ATR 用于**降低评分** | ✗ **没有**。ATR 的下游只有两处：`:347` 止损参考 `price - 2*atr_v`（ATR 缺失才回退系统止损），和 `:468` 报告里的一行说明文字。`score_stock` 的签名（`:154-155`）是 `(ma5, ma20, price, rsi, dif, dea, macd_bar, vol_ratio, change_pct, rsi_low, rsi_high)`——**没有 ATR 项**；其中 `vol_ratio` 是**量能比**不是波动率 | ✗ 未实现 |
| 「>3%」这个阈值 | 全仓评分路径里不存在 ATR 百分比门槛 | ✗ 无对应 |
| 「偏好低波动」的意图 | **换了形态实现**：`multi_strategy.py:229 LowVolatilityStrategy` 是框架注册的三个并列策略之一（趋势跟随／均值回归／低波动率），按 **年化波动 `ann_vol`** 分档给分（`<0.20` 得 35、`<0.28` 得 28、`<0.35` 得 18、`≤0.45` 得 8），并配 `test_high_volatility_excluded` 等用例 | △ 意图有、形态不同（不是"降权"而是"独立策略＋分档加分"，且用的是 ann_vol 不是 ATR%） |

**结论**：条目二按字面**未实现**；其意图以另一种结构落地。既不能 confirm，也不宜按字面去"补实现"（那会改评分函数＝策略逻辑变更）。

## 三、比参数漂移更值得看的一条：这两条根本不是"实测待验证"，是代码里的硬编码种子

`docs/knowledge/quant-kb.md` 的那两行，与 `evolve_strategy.py:71-72` 的字符串**逐字相同**：

```python
# evolve_strategy.py:62 def mark_pending_if_needed()
#   :66  if '[待验证]' in content: return True        ← 只要 KB 里还有任意待验证条目就不动
#   :69-72 new_entries = """**[待验证] RSI阈值根据大盘动态调整** — …75，…55
#                          **[待验证] 波动率加权评分** — 高ATR(>3%)…偏好低波动趋势股"""
#   :80  open(KB_FILE, 'w').write(content)            ← 整文件重写
# 调用点：:491-495  pending = load_claude_knowledge()
#                  if not pending: mark_pending_if_needed(); pending = load_claude_knowledge()
```

⇒ 机制是：**进化器发现 KB 里没有待验证条目时，就把这两条硬编码文本重新写进去**，然后继续拿它们当 A/B 方向。
后果有两条，都影响任务书的处置建议：

1. **从 KB 里"confirm 掉"这两条是无效的**：清空后下一次 `evolve_strategy --auto` 会原样再长出来。
   真要清账，得先改 `evolve_strategy.py` 的 seeder（删掉、或改成"只写带真实来源的条目"）。
2. **它们不代表任何一次回测结论**，所以"滞留待验证态＝已实现待确认"这个判断只对了一半：
   吻合代码是巧合（种子文本当初照 v7 动态参数规则写的），不是有实测记录待转正。
   注：`# 量化策略知识库` 一节自述「本节为机器管理区…条目经人工 confirm 后应并入 AGENTS.md」——
   目前 AGENTS.md 里另有 8 处 `[待验证]`（人工/学习来源），与 KB 的 2 处机器种子是两批东西。

## 四、建议（只出建议，一条都没执行）

1. **条目一不要 confirm**。要么把 KB 文本改成与代码同口径（"牛市上限 75 已落地；熊市侧代码为 60"），
   要么删掉"55"这半句。**不要反过来把代码改成 55**——那是策略参数变更，需多模型评审＋回测，不在本单范围。
2. **条目二改写成"已落地（异形态）"**：把落点指到 `multi_strategy.py:229 LowVolatilityStrategy` ＋ `ann_vol` 分档，
   并注明"与字面 ATR>3% 降权的差别"。若确实想要 ATR 降权，那是新需求，得单独出稿。
3. 任务书建议的「补 `Added: 日期` 元数据」**与本仓约定不符**，别照做：
   - 工具自己写的格式是 `### <主题>` ＋ `> 来源：\`reports/xxx.md\` | 整合日期：YYYYMMDD` ＋ `- [待验证] <要点>`
     （`integrate_knowledge.py:110-125`），没有 `Added:` 这个字段；
   - 更实际的约束是去重指纹：`integrate_knowledge.py:165-181 _content_fingerprint` 只对
     **`### ` 分块**里的 **`- ` 开头的行**取指纹（并剥掉 `[待验证]` 与日期/来源行），
     而现在这两条 KB 条目是**粗体整行、非 `- ` 项目符号** ⇒ **它们落在指纹口径之外**。
     给它们追加任何日期文本都不会被指纹看见，反而将来若工具按自己的格式再写一遍同样内容，
     **指纹去重拦不住**（新旧两版格式不同）。
   - 所以：要补元数据，应当**顺手把这两条改写成工具格式**（`### ` ＋ `> 来源/整合日期` ＋ `- [待验证]`），
     而不是在粗体行尾贴 `Added:`。
4. **修 seeder 与格式漂移**（代码变更，需日间确认，本单不动）：
   `mark_pending_if_needed` 生成的文本格式与 `integrate_knowledge` 的条目格式不一致，是上面第 3 点问题的根；
   两者应统一，否则 KB 永远是"一半机器格式、一半种子格式"。
5. 另一处小风险一并登记：`mark_pending_if_needed` 用 `open(KB_FILE, 'w')` 整文件重写，
   且它的读路径在 KB_FILE 缺失时会回退读 CLAUDE.md 旧节（`:36-47`）——
   那条回退分支一旦命中，会把 **CLAUDE.md 的全文**当内容写进 `quant-kb.md`，等于把旧节整体复制一份。
   本单没构造该场景（属写路径实验，且是迁移过渡期代码），只登记。

## 五、复跑

```bash
cd /d/code/my-quant-system-v8
sed -n '5,8p' docs/knowledge/quant-kb.md                       # 两条待验证原文
sed -n '108,116p' strategy.py                                  # param_map 真值
grep -n "\b55\b" strategy.py                                   # 只有 45-55 评分带，与 KB 的 55 无关
sed -n '154,156p;296,310p;340,350p' strategy.py                # score_stock 签名 / ATR 用途
sed -n '62,83p;491,495p' evolve_strategy.py                    # 硬编码种子与调用点
grep -n "ann_vol" multi_strategy.py | head                     # 条目二的实际落地形态
python -m pytest tests/test_integrate_dedup.py -q              # 8 passed（任务书写 3，已漂移）
```

## 六、本单改动

**零生产改动、零 KB 改动**。唯一新增文件即本报告 `docs/insights/quant-kb-drift-check-20260918.md`
（文件名按任务书给的字样保留 `20260918`，实际执行日为 2026-09-19）。
