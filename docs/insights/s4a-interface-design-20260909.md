# S4-a 接口设计稿：core/paths.py 与 core/secrets.py（2026-09-09，零改码）

> 执行：GLM-5.3-Flash 夜间执行班（任务 20260909-053503-qs4d）。**凭据值一律以 `***` 占位表示，本稿未读取、未抄录任何真实凭据文件内容**。设计依据：refactor-blueprint-20260907.md S4 行、s4-batch0-inventory-20260909.md（82 文件盘点）、s4-inventory-fstring-review-20260909.md（漏检补强）。

## 一、core/paths.py API 形态

### 1.1 模块骨架（签名级）

```
core/paths.py
├── REPO_ROOT: Path                     # 唯一锚：Path(__file__).resolve().parents[1]
├── DATA_DIR / RESULTS_DIR / REPORTS_DIR / LOGS_DIR / ORDERS_DIR / BACKUP_DIR: Path
├── def ensure_dir(path: Path) -> Path            # mkdir(parents=True, exist_ok=True) 后返回原路径
├── def data_file(name: str) -> Path              # DATA_DIR / name（data/stock_*.csv 一类具名数据件）
├── def dated_file(dir_path: Path, stem: str, ext: str, day: date | None = None) -> Path
│                                                 # 统一「名_YYYYMMDD.扩展」日期件命名（现 9+ 处各自 strftime）
└── def latest_dated(dir_path: Path, stem: str, ext: str) -> Path | None
                                                  # 取最新日期件（watchdog/_latest_date 的通用化）
```

- 命名约定：目录常量大写；取值函数动词开头；**一律返回 pathlib.Path**（调用方不再手写 os.path.join）。
- 单例语义：REPO_ROOT 只算一次；禁止在 paths.py 内做 os.chdir（cwd 语义留给调用方，与 S2 的 chdir 还原纪律一致）。

### 1.2 迁移期兼容策略（新旧并存过渡，单点切换收尾）
- 过渡期 `_self_check.py` 式 shim 原则：不做旧路径 shim（路径无模块边界可 shim），改为**逐文件机械替换**——每批 commit 即切换，revert 即回。
- 迁移前在 paths.py 头部注明「唯一合法路径来源」，后续新代码禁止再写 BASE 拼接（可用 S4-e 的静态断言测试固化）。

### 1.3 典型调用改写示例（改写前 → 改写后）

```
改写前（fetch_history.py 现状形态）：
  out = os.path.join(BASE, 'data', f'stock_{today}.csv')
改写后：
  from core.paths import data_file, dated_file
  out = dated_file(DATA_DIR, 'stock', 'csv', today)

改写前（watchdog 形态）：
  for p in BASE.glob('data/stock_*.csv'): …
改写后：
  from core.paths import DATA_DIR
  for p in DATA_DIR.glob('stock_*.csv'): …
```

## 二、core/secrets.py API 形态

### 2.1 模块骨架（签名级；值全部占位示意）

```
core/secrets.py
├── def get_secret(name: str, *, required: bool = False) -> str | None
│       # 统一凭据入口：解析顺序 = 环境变量 > .env.local > data/config 中的占位配置
│       # name 取值约定（首批）：'DEEPSEEK_API_KEY' / 'GPT_API_KEY' / 'BARK_URL' / 'BARK_KEY' …
│       # required=True 且缺失 → raise MissingSecretError(name)（新增异常，含修复指引文案）
├── @dataclass SecretSpec: name / env_key / file_hint                 # 凭据注册表行
├── _REGISTRY: dict[str, SecretSpec]                                  # 全部已知凭据名单（含 '***' 占位默认）
└── 模块级 lru_cache 缓存；.env.local mtime 变化时失效重读（失效约定）
```

- **禁读禁抄红线执行**：本模块只定义「从哪读、怎么读、缺了怎么办」；设计稿/评审/日志中出现凭据值一律 `***`。
- 现状映射（11 个 secrets 相关文件 → 收敛目标）：bark_sender/config.py（BARK_URL/BARK_KEY）、core/llm.py 与 llm_analyst.py（LLM key）、fetch_history.py、core/pipeline.py、app/loaders.py、archive_old_data.py、ops/health.py（检查点改为调用 get_secret）。

### 2.2 缓存与失效约定
- 进程内 lru_cache；不落盘、不打日志（`***` 占位日志："secret resolved=yes/no"）。
- .env.local 的 mtime 指纹变化 → 下次 get_secret 重读（与 c712 的 data_version 指纹思路一致）。

## 三、每文件机械迁移步骤模板（可复制进每批执行单）

1. `from core.paths import <所需符号>`（或 secrets 同理）；
2. 逐处替换 BASE 拼接/相对路径字面量为 paths 调用（变量段拼接处改传参数化函数）；
3. 该文件 `BASE = os.path.dirname(...)` 若仅剩路径用途 → 删除；仍被 chdir 用 → 改 `os.chdir(paths.REPO_ROOT)`；
4. 自测：py_compile + 该文件相关 pytest 子集；
5. 批内最后：全量 pytest（基线 410）+ smoke 53/53 + 单批 commit（`refactor: S4-x <文件组> path consolidation`）。

## 四、R2 快审对照表框架（逐文件填三列）

| 文件 | 默认值语义点（现值） | 快审要点 | 结论（快审人/日期） |
|---|---|---|---|
| fetch_history.py | 历史数据落盘默认路径 | 迁移后数据落点不变（断档=回测失真） | 待白天快审 |
| sim_trade.py | 模拟盘数据/订单默认路径 | 账户状态文件路径不得漂移 | 待白天快审 |
| bark_sender/config.py | 推送 URL/KEY 默认值 | 凭据改走 get_secret 后无硬编码回退 | 待白天快审 |
| …（82 文件清单中标注 R2 的全量展开） | | | |

## 五、批 a（地基批）执行边界与验收口径建议
- **边界**：只新建 core/paths.py、core/secrets.py + ops/health.py、llm_call 等地基消费方切换；**不动** fetch/sim/bark 业务文件的路径（留给 b/c/d 批）。
- **验收**：①pytest 410+smoke 53/53 不变 ②`python ops/health.py` 自检 163/160/1/2 不劣化 ③新 API 单测（paths 往返/secrets 缺失报错/占位）全绿 ④grep 断言：地基消费方零 BASE 拼接残留。
- **回滚**：单 commit revert（新文件删除即净）。

## 六、零改码声明
本单只出设计；core/、src/、根级脚本零触碰；未读取任何真实凭据内容（涉及处均 `***`）。

## 七、遗留问题
- MissingSecretError 是否携带「修复指引 URL」属产品文案决策；
- datefile 命名函数是否吞并各报告生成器的私有命名规则，S4-b 时按实情收敛；
- paths/secrets 的单元测试骨架建议随批 a 一并提交（本稿只定 API 不定测试体）。
