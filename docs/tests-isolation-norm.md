# 量化测试隔离规范：模块属性间接寻址的隔离范式（d914-14，2026-09-14 新建）

> 来源：d913b-42 测试隔离审计（docs/insights/quant-test-isolation-audit-20260913.md）12 条命中中 11 条误报的形态提炼。
> 适用范围：my-quant-system-v8 全部测试代码。核心原则一句话——**被测模块把依赖存进模块级属性时，测试必须经 monkeypatch.setattr(模块, "属性", 假件) 替换；对"改前/改后"敏感的路径常量尤其如此。**

## 范式一：模块属性间接寻址（fixture 已替换，扫描器仍误报）

**反例**（test_sim_trade.py 实际形态，审计 9 条误报来源）：
```python
with open(sim_trade.RISK_CONFIG_FILE, "w", encoding="utf-8") as f:  # 看似裸写生产路径
```
**为何隔离没失效**：`isolated_sim_trade` fixture 已 `monkeypatch.setattr(sim_trade, "RISK_CONFIG_FILE", tmp/…)`，open 写的是补丁后的 tmp 路径。
**扫描器为何误报**：正则只看当前行，看不到 fixture 里的属性替换（跨行上下文盲区）。
**正确写法**：保持现状即可；新用例应优先复用既有隔离 fixture，不要自造第二套。

## 范式二：直接给模块属性赋值（真违规形态——本班自纠例）

**反例**（d913b-36 初版 test_timefixture_characterization.py）：
```python
newbie_protection.ACTIVITY_FILE = _seed_activity(tmp_path, [...])   # 裸赋值！
multi_strategy.DATA_DIR = str(tmp_path)                             # 裸赋值！
```
**为何隔离失效**：裸赋值不走 monkeypatch，测试结束后属性**残留在模块上**——同进程后续用例读到被污染的路径常量（跨测试泄漏，且随执行顺序漂移）。
**正确写法**：
```python
monkeypatch.setattr(newbie_protection, "ACTIVITY_FILE", str(activity_file))
```
monkeypatch 保证用例结束自动还原；这是「模块属性间接寻址」场景的标准动作。

## 范式三：依赖注入优于属性替换（最稳形态）

**反例**（隐式依赖）：
```python
def process(df_path):            # 内部自己 open(df_path)
    ...
```
**为何脆弱**：调用方无法注入 tmp 路径之外的数据源，测试只能改全局常量，违背最小副作用。
**正确写法**（显式注入）：
```python
def process(df: pd.DataFrame):   # 数据作为参数
    ...
# 测试里直接构造 DataFrame，不碰任何路径
```
适用边界：函数式/纯计算模块优先；有 I/O 副作用的入口（读写 CSV/锁文件）保留路径参数，但路径必须可注入（参数或模块属性+monkeypatch）。

## 范式四：字符串常量的「基类白名单」误判（扫描器盲区另一例）

**反例**：`border-black/5`、`bg-slate-950/95` 这类 **alpha 档**或**组合档**在硬编码白名单外被误判（d913-T1 暗色门禁同类问题）。
**正确写法**：判定逻辑先「去 alpha 取基类」再查白名单；扫描器规则升级三处（跨行上下文/裸赋值规则/防回归哨兵）见 d913b-42 遗留。

## 范式五：临时目录一律 tmp_path（pytest 内建）

**反例**：`Path('tmp/x.json').write_text(...)`（相对路径写仓内 tmp，污染工作树且并行跑互踩）。
**正确写法**：`tmp_path / "x.json"`（pytest 每用例独立目录，自动清理）；需要多用例共享时用 session 级 fixture 建一次。

## 附：来源对照（误报形态 → 本节范式）

| d913b-42 命中 | 形态 | 归入范式 |
|---|---|---|
| test_sim_trade.py ×9 | fixture 已替换属性 | 范式一 |
| test_position_sizer.py:57 | tmp_path 派生路径 | 范式五 |
| test_v87_review_refactors.py:197 | tmp_path（跨行） | 范式五 |
| test_bark_push_charac.py:10 | import requests 但全 mock | （网络类，另行：断网哨兵可防新增裸调用） |
| test_timefixture_characterization.py ×5 | **裸赋值模块属性** | **范式二（唯一真违规，已修）** |
