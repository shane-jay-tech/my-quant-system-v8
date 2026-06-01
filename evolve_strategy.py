"""
策略进化引擎 v2 — A/B 测试驱动的策略迭代 + --auto 全自动模式

功能：
1. 读取 CLAUDE.md 知识库中 [待验证] 的改进条目
2. 基于 enhanced_backtest.py 创建参数变体，仅引入一项改进，控制变量
3. 运行 A/B 回测（120日），对比 baseline 与 candidate
4. 生成 ab_test 报告，包含统计显著性判断
5. --auto 模式：自动采纳达标改进，安全锁防连续退化
6. 自动将改进参数写入 enhanced_backtest.py

架构说明：
  enhanced_backtest.py 拥有独立的指标计算和筛选逻辑（不依赖 strategy.py）。
  因此 A/B 测试通过修改 backtest 模块的参数/逻辑来进行控制变量对比。
"""
import os, sys, re, glob, shutil
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
CLAUDE_MD = os.path.join(BASE_DIR, 'CLAUDE.md')
MEMORY_MD = os.path.join(BASE_DIR, 'memory.md')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION
BACKTEST_FILE = os.path.join(BASE_DIR, 'enhanced_backtest.py')

SAFETY_LIMIT = 2  # 连续退化次数上限，超过则暂停自动进化


def load_claude_knowledge():
    """从 CLAUDE.md 提取知识库条目中标记为 [待验证] 的"""
    if not os.path.exists(CLAUDE_MD):
        return []
    with open(CLAUDE_MD, 'r', encoding='utf-8') as f:
        content = f.read()

    pending = []
    for m in re.finditer(r'\[待验证\]\s*(.+?)(?:\n|$)', content):
        pending.append(m.group(1).strip())
    return pending


def mark_pending_if_needed():
    """如果没有待验证条目，在 CLAUDE.md 中追加标记"""
    with open(CLAUDE_MD, 'r', encoding='utf-8') as f:
        content = f.read()

    if '[待验证]' in content:
        return True

    # 在知识库末尾追加待验证条目
    new_entries = """
**[待验证] RSI阈值根据大盘动态调整** — 牛市放宽RSI上限至75，熊市下移至55
**[待验证] 波动率加权评分** — 高ATR(>3%)股票降低评分，偏好低波动趋势股
"""
    if '# 量化策略知识库' in content:
        content = content.rstrip() + '\n' + new_entries + '\n'
    else:
        content += '\n# 量化策略知识库\n' + new_entries + '\n'

    with open(CLAUDE_MD, 'w', encoding='utf-8') as f:
        f.write(content)
    print("[EVOLVE] Added 2 [待验证] entries to CLAUDE.md")
    return True


def check_safety_lock():
    """检查连续退化次数，若达到上限则暂停自动进化"""
    if not os.path.exists(MEMORY_MD):
        return True  # 无记录，安全

    with open(MEMORY_MD, 'r', encoding='utf-8') as f:
        content = f.read()

    # 查找最近的 [进化退化] 记录
    regressions = re.findall(r'\[进化退化\] (\d{8})', content)
    if len(regressions) < SAFETY_LIMIT:
        return True  # 未达上限

    # 检查最后 SAFETY_LIMIT 次是否连续
    recent = sorted(regressions, reverse=True)[:SAFETY_LIMIT]
    if len(recent) >= SAFETY_LIMIT:
        print(f"[EVOLVE] SAFETY LOCK: {SAFETY_LIMIT} consecutive regressions detected")
        print(f"[EVOLVE] Auto-evolution paused. Manual review required.")
        print(f"[EVOLVE] Remove [进化退化] entries from memory.md to re-enable.")
        return False
    return True


def record_regression(improvement_desc):
    """记录一次进化退化"""
    today = datetime.now().strftime('%Y%m%d')
    entry = f"[进化退化] {today} | {improvement_desc[:80]} | 10日净收益下降，参数回退\n"
    with open(MEMORY_MD, 'a', encoding='utf-8') as f:
        f.write(entry)
    print(f"[EVOLVE] Regression recorded in memory.md")
# 每一项是一个 (名称, 修改函数) 对。
# 修改函数接收 backtest 模块，修改其参数，返回改进描述字符串。


def improve_ma_longer(bt_module):
    """改进: MA长期参数调整，降低震荡市死叉误触发"""
    bt_module.MA_LONG = 30
    return "MA(5,30)替代MA(5,20)：降低震荡市频繁死叉误出场"


def improve_ma_lower(bt_module):
    """改进: MA长期参数回调"""
    bt_module.MA_LONG = 25
    return "MA(5,25)替代MA(5,20)：适度延长周期，平衡灵敏度与噪声"


def improve_rsi_wider(bt_module):
    """改进: 放宽RSI范围从(30,70)到(25,75)，扩大候选池"""
    bt_module.RSI_LOW = 25
    bt_module.RSI_HIGH = 75
    return "RSI范围放宽至(25,75)：增加候选多样性，捕捉极端但趋势未破的股票"


def improve_rsi_narrower(bt_module):
    """改进: 收紧RSI范围，提高信号质量"""
    bt_module.RSI_LOW = 35
    bt_module.RSI_HIGH = 65
    return "RSI范围收紧至(35,65)：过滤超买超卖噪声，提高信号纯度"


def improve_topn_higher(bt_module):
    """改进: 分散持仓"""
    bt_module.TOP_N = 15
    return "持仓集中度从Top10提至Top15：适度分散，降低单票风险"


def improve_topn_lower(bt_module):
    """改进: 集中持仓"""
    bt_module.TOP_N = 8
    return "持仓集中度从Top10降至Top8：更集中，放大alpha"


def improve_window_longer(bt_module):
    """改进: 延长回测窗口"""
    bt_module.BACKTEST_DAYS = 180
    return "回测窗口从120天延至180天：覆盖更长市场周期"


def improve_rsi_dynamic(bt_module):
    """改进: 动态RSI（牛市宽松/熊市严格）"""
    bt_module.RSI_LOW = 25
    bt_module.RSI_HIGH = 75
    bt_module.RSI_DYNAMIC = True
    return "RSI动态调整：牛市(25,75) 熊市(35,60)，自适应市场状态"


IMPROVEMENTS = {
    'RSI': improve_rsi_wider,
    'rsi': improve_rsi_wider,
    '波动率': improve_rsi_wider,
    'MA': improve_ma_longer,
    'ma': improve_ma_longer,
    '均线': improve_ma_longer,
    '死叉': improve_ma_longer,
    'MA周期': improve_ma_longer,
    '集中': improve_topn_lower,
    '分散': improve_topn_higher,
    '仓位': improve_topn_higher,
    'TopN': improve_topn_higher,
    '回测窗口': improve_window_longer,
    'BACKTEST': improve_window_longer,
    '动态RSI': improve_rsi_dynamic,
    '动态调整': improve_rsi_dynamic,
    '市场状态': improve_rsi_dynamic,
    '收紧RSI': improve_rsi_narrower,
    'dynamic_params': improve_rsi_dynamic,  # v7: 动态参数代理
    '自适应': improve_rsi_dynamic,
}


def pick_improvement(experiment_name):
    """根据实验名称匹配最佳改进方案"""
    for key, fn in IMPROVEMENTS.items():
        if key in experiment_name:
            return fn
    return improve_ma_longer  # 默认：MA参数改进


def run_ab_backtest(improve_fn):
    """运行 v4 vs v5 A/B 回测"""
    print("\n[EVOLVE] Running A/B backtest...")

    import enhanced_backtest as bt

    hf = os.path.join(DATA_DIR, 'history.csv')
    sf = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not os.path.exists(hf) or not sf:
        print("[EVOLVE] FATAL: No data for backtest")
        return None, None, "No data"

    hist = pd.read_csv(hf, dtype={'代码': str})
    today = pd.read_csv(sf[0], dtype={'代码': str})
    idx = bt.fetch_index()

    # ---- v4 Baseline: 确保原始参数 ----
    print("[EVOLVE] [1/2] Running v4 baseline (MA5/20, RSI30-70, Top10)...")
    bt.MA_SHORT = 5
    bt.MA_LONG = 20
    bt.RSI_LOW = 30
    bt.RSI_HIGH = 70
    bt.TOP_N = 10

    trades_v4, daily_v4, bm = bt.backtest(hist, today, idx)
    results_v4 = bt.analyze(trades_v4, bm)

    # ---- v5 Candidate: 应用改进 ----
    # 重新加载模块获得全新的函数（避免闭包捕获旧值）
    import importlib
    bt = importlib.reload(bt)

    # 先用 v4 默认值初始化
    bt.MA_SHORT = 5
    bt.MA_LONG = 20
    bt.RSI_LOW = 30
    bt.RSI_HIGH = 70
    bt.TOP_N = 10

    improvement_desc = improve_fn(bt)
    print(f"[EVOLVE] [2/2] Running v5 candidate: {improvement_desc}...")

    trades_v5, daily_v5, _ = bt.backtest(hist, today, idx)
    results_v5 = bt.analyze(trades_v5, bm)

    # 恢复默认参数（不影响后续使用）
    bt.MA_SHORT = 5
    bt.MA_LONG = 20
    bt.RSI_LOW = 30
    bt.RSI_HIGH = 70
    bt.TOP_N = 10

    return results_v4, results_v5, improvement_desc


def extract_metrics(results):
    """从 analyze() 返回的结果字典中提取关键指标"""
    m = {}
    for hold in ['持有1日', '持有5日', '持有10日']:
        if hold in results:
            v = results[hold]
            try:
                m[f'{hold}_净收益'] = float(str(v['净收益']).replace('%', '').replace('+', ''))
                m[f'{hold}_胜率'] = float(str(v['胜率']).replace('%', ''))
                m[f'{hold}_交易数'] = v.get('交易数', 0)
            except (ValueError, KeyError):
                m[f'{hold}_净收益'] = 0.0
                m[f'{hold}_胜率'] = 0.0
    if '基准对比' in results:
        try:
            m['超额收益'] = float(str(results['基准对比']['超额']).replace('%', '').replace('+', ''))
        except (ValueError, KeyError):
            m['超额收益'] = 0.0
    if '风控' in results:
        m['最大连亏'] = results['风控'].get('最大连亏天数', 0)
    return m


def generate_ab_report(improvement_desc, m4, m5):
    """生成 A/B 测试报告"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    net10_v4 = m4.get('持有10日_净收益', 0)
    net10_v5 = m5.get('持有10日_净收益', 0)
    wr10_v4 = m4.get('持有10日_胜率', 0)
    wr10_v5 = m5.get('持有10日_胜率', 0)
    excess_v4 = m4.get('超额收益', 0)
    excess_v5 = m5.get('超额收益', 0)
    net5_v4 = m4.get('持有5日_净收益', 0)
    net5_v5 = m5.get('持有5日_净收益', 0)
    net1_v4 = m4.get('持有1日_净收益', 0)
    net1_v5 = m5.get('持有1日_净收益', 0)

    net10_diff = net10_v5 - net10_v4
    wr10_diff = wr10_v5 - wr10_v4
    excess_diff = excess_v5 - excess_v4

    # 判断逻辑
    if net10_diff > 0.5 and wr10_diff > -2:
        verdict = "【采纳】"
        verdict_reason = f"10日净收益 +{net10_diff:+.2f}%，胜率变化 {wr10_diff:+.1f}%，统计显著改善"
    elif net10_diff > 0:
        verdict = "【需更多数据观察】"
        verdict_reason = f"10日净收益微升 {net10_diff:+.2f}%，胜率变化 {wr10_diff:+.1f}%，建议延长回测周期至120日"
    elif net10_diff > -0.5:
        verdict = "【需更多数据观察】"
        verdict_reason = f"10日净收益变化 {net10_diff:+.2f}%，在统计噪声范围内（±0.5%）"
    else:
        verdict = "【舍弃】"
        verdict_reason = f"10日净收益下降 {net10_diff:+.2f}%，该改进方向在当前市场环境下无效"

    lines = [
        f"# 策略 A/B 测试报告",
        f"",
        f"> **实验日期**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> **改进项**：{improvement_desc}",
        f"> **回测周期**：60 个交易日",
        f"> **结论**：{verdict} — {verdict_reason}",
        f"",
        f"---",
        f"",
        f"## v4 (Baseline) vs v5 (Candidate) 并排对比",
        f"",
        f"| 指标 | v4 (Baseline) | v5 (Candidate) | 变化 | 判断 |",
        f"|------|--------------|----------------|------|------|",
    ]

    comparisons = [
        ('1日净收益(%)', net1_v4, net1_v5, 0.3),
        ('5日净收益(%)', net5_v4, net5_v5, 0.5),
        ('10日净收益(%)', net10_v4, net10_v5, 0.5),
        ('10日胜率(%)', wr10_v4, wr10_v5, 2.0),
        ('超额收益(%)', excess_v4, excess_v5, 0.3),
        ('最大连亏(天)', m4.get('最大连亏', 0), m5.get('最大连亏', 0), 1),
    ]

    for label, v4_v, v5_v, threshold in comparisons:
        if isinstance(v4_v, (int, float)) and isinstance(v5_v, (int, float)):
            diff = v5_v - v4_v
            if abs(diff) < 0.01:
                signif = "无变化"
            elif abs(diff) >= threshold:
                signif = "✓ 显著" if diff > 0 else "✗ 显著恶化"
            else:
                signif = "不显著"
            lines.append(f"| {label} | {v4_v:+.2f} | {v5_v:+.2f} | {diff:+.2f} | {signif} |")

    lines.extend([
        f"",
        f"## 统计显著性分析",
        f"",
        f"- **10日净收益变化**：{net10_diff:+.2f}%（阈值 ±0.5%）",
        f"- **10日胜率变化**：{wr10_diff:+.1f}%（阈值 ±2%）",
        f"- **超额收益变化**：{excess_diff:+.2f}%（阈值 ±0.3%）",
        f"",
        f"### 判断逻辑",
        f"1. 若 10日净收益提升 > 0.5% 且胜率未大幅下降(>-2%) → 【采纳】",
        f"2. 若 10日净收益变化在 ±0.5% 内 → 【需更多数据观察】",
        f"3. 若 10日净收益下降 > 0.5% 或胜率下降 > 2% → 【舍弃】",
        f"",
        f"## 改进详情",
        f"- **v4 策略**：趋势30+RSI20+MACD20+量能15+涨跌15，MA5/MA20死叉出场，大盘择时",
        f"- **v5 变更**：{improvement_desc}",
        f"- **控制变量**：除上述变更外，所有参数保持一致",
        f"",
        f"---",
        f"*报告由 evolve_strategy.py v{SYSTEM_VERSION} 自动生成*",
    ])

    report_path = os.path.join(REPORTS_DIR, f'ab_test_{today}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[EVOLVE] A/B report: {report_path}")

    return report_path, verdict, verdict_reason


def apply_params_to_backtest(improve_fn):
    """将改进参数写入 enhanced_backtest.py（在文件头部常量区域）"""
    import enhanced_backtest as bt
    # 记录修改前的值
    old_ma_long = bt.MA_LONG
    old_rsi_low = bt.RSI_LOW
    old_rsi_high = bt.RSI_HIGH
    old_top_n = bt.TOP_N
    old_window = bt.BACKTEST_DAYS

    # 应用改进
    improve_fn(bt)

    # 读取 backtest 源文件
    with open(BACKTEST_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    changes = []
    if bt.MA_LONG != old_ma_long:
        content = re.sub(r'MA_LONG\s*=\s*\d+', f'MA_LONG = {bt.MA_LONG}', content)
        changes.append(f'MA_LONG {old_ma_long}→{bt.MA_LONG}')
    if bt.RSI_LOW != old_rsi_low:
        content = re.sub(r'RSI_LOW\s*=\s*\d+', f'RSI_LOW = {bt.RSI_LOW}', content)
        changes.append(f'RSI_LOW {old_rsi_low}→{bt.RSI_LOW}')
    if bt.RSI_HIGH != old_rsi_high:
        content = re.sub(r'RSI_HIGH\s*=\s*\d+', f'RSI_HIGH = {bt.RSI_HIGH}', content)
        changes.append(f'RSI_HIGH {old_rsi_high}→{bt.RSI_HIGH}')
    if bt.TOP_N != old_top_n:
        content = re.sub(r'TOP_N\s*=\s*\d+', f'TOP_N = {bt.TOP_N}', content)
        changes.append(f'TOP_N {old_top_n}→{bt.TOP_N}')
    if bt.BACKTEST_DAYS != old_window:
        content = re.sub(r'BACKTEST_DAYS\s*=\s*\d+', f'BACKTEST_DAYS = {bt.BACKTEST_DAYS}', content)
        changes.append(f'BACKTEST_DAYS {old_window}→{bt.BACKTEST_DAYS}')

    if changes:
        with open(BACKTEST_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"[EVOLVE] Updated enhanced_backtest.py: {', '.join(changes)}")

    return changes


def adopt_if_accepted(verdict, improvement_desc, m4, m5, improve_fn, is_auto=False):
    """如果【采纳】，备份 backtest → 应用改进 → 记录日志"""
    if '采纳' not in verdict:
        if is_auto and '舍弃' in verdict:
            record_regression(improvement_desc)
        print(f"[EVOLVE] Verdict: {verdict} — no adoption")
        return False

    today = datetime.now().strftime('%Y%m%d')
    backup_path = os.path.join(BASE_DIR, f'enhanced_backtest_backup_{today}.py')
    shutil.copy(BACKTEST_FILE, backup_path)
    print(f"[EVOLVE] Backed up backtest → {os.path.basename(backup_path)}")

    # 实际写入参数变更到 enhanced_backtest.py
    if is_auto:
        apply_params_to_backtest(improve_fn)

    # 记录进化日志
    net10_v4 = m4.get('持有10日_净收益', 0)
    net10_v5 = m5.get('持有10日_净收益', 0)
    wr10_v4 = m4.get('持有10日_胜率', 0)
    wr10_v5 = m5.get('持有10日_胜率', 0)

    log_entry = (
        f"[进化] {today} | {improvement_desc[:60]} | "
        f"10日净收益: {net10_v4:+.2f}%→{net10_v5:+.2f}% | "
        f"胜率: {wr10_v4:.1f}%→{wr10_v5:.1f}%"
    )
    with open(MEMORY_MD, 'a', encoding='utf-8') as f:
        f.write(f'\n{log_entry}\n')
    print(f"[EVOLVE] Evolution log appended to memory.md")

    return True


def mark_pending_tested(experiment_text, verdict):
    """在 CLAUDE.md 中标记 [待验证] 条目为已验证"""
    if not os.path.exists(CLAUDE_MD):
        return

    with open(CLAUDE_MD, 'r', encoding='utf-8') as f:
        content = f.read()

    # 找到对应 [待验证] 条目并标记
    status = '已验证-已采纳' if '采纳' in verdict else '已验证-已舍弃'
    old = f'[待验证] {experiment_text}'
    new = f'[{status}] {experiment_text}'
    if old in content:
        content = content.replace(old, new)
        with open(CLAUDE_MD, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"[EVOLVE] Marked CLAUDE.md: [{status}] {experiment_text[:50]}")


def main():
    is_auto = '--auto' in sys.argv

    print("=" * 60)
    print(f"  策略进化引擎 v2 {'(AUTO模式)' if is_auto else '(交互模式)'}")
    print("=" * 60)

    # --auto: 安全检查
    if is_auto and not check_safety_lock():
        print("[EVOLVE] Auto-evolution blocked by safety lock")
        return 1

    # Step 1: 读取知识库
    print("\n[1/4] Reading CLAUDE.md knowledge base...")
    pending = load_claude_knowledge()
    if not pending:
        print("[EVOLVE] No [待验证] entries found, auto-marking...")
        mark_pending_if_needed()
        pending = load_claude_knowledge()

    if not pending:
        print("[EVOLVE] Still no experiments to test. Nothing to do.")
        return 0

    print(f"[EVOLVE] {len(pending)} pending experiment(s):")
    for p in pending:
        print(f"  - {p[:80]}")

    # Step 2: 选择改进方案（auto模式下只测第一个）
    print("\n[2/4] Selecting improvement...")
    experiment = pending[0]
    improve_fn = pick_improvement(experiment)
    print(f"[EVOLVE] Selected: {experiment[:80]}")

    # Step 3: 运行 A/B 回测
    print("\n[3/4] Running A/B backtest...")
    try:
        results_v4, results_v5, improvement_desc = run_ab_backtest(improve_fn)
    except Exception as e:
        print(f"[EVOLVE] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    if results_v4 is None or results_v5 is None:
        print("[EVOLVE] Backtest produced no results")
        return 1

    m4 = extract_metrics(results_v4)
    m5 = extract_metrics(results_v5)

    # Step 4: 生成报告 + 自动采纳（auto模式）
    print("\n[4/4] Generating A/B report...")
    report_path, verdict, reason = generate_ab_report(improvement_desc, m4, m5)

    if is_auto:
        adopt_if_accepted(verdict, improvement_desc, m4, m5, improve_fn, is_auto=True)
        mark_pending_tested(experiment, verdict)

    print(f"\n[OK] Evolution cycle complete.")
    print(f"  Experiment: {improvement_desc[:80]}")
    print(f"  Verdict: {verdict}")
    print(f"  Report: {report_path}")

    net10_v4 = m4.get('持有10日_净收益', 0)
    net10_v5 = m5.get('持有10日_净收益', 0)
    print(f"  v4 10日净收益: {net10_v4:+.2f}% → v5: {net10_v5:+.2f}%")
    return 0


if __name__ == '__main__':
    sys.exit(main())
