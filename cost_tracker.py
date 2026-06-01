"""
成本审计模块 v1 — LLM调用成本追踪 + 本地计算节省估算 + 每日审计报告

功能：
1. 记录每次LLM调用的原因、耗时、预估token消耗
2. 每日生成 reports/cost_audit_YYYYMMDD.md
3. 成本预估模型（离线）：每100行代码≈2K token, 每篇研究报告≈4K token
4. 月度累计 + 优化建议
"""
import os, sys, json, glob, time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
COST_LOG_FILE = os.path.join(DATA_DIR, 'cost_log.jsonl')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION

# 成本预估模型（离线，保守估计）
# Claude API 定价参考: $3/$15 per MTok input/output (Opus)
# 实际使用DeepSeek，成本更低，这里用Claude定价做保守上限
COST_MODEL = {
    'input_per_mtok': 3.0,     # $3/MTok
    'output_per_mtok': 15.0,   # $15/MTok
    'lines_code_estimate': 2000,   # 每100行代码生成≈2K token
    'research_report_estimate': 4000,  # 每篇研究报告≈4K token
}

# 流水线步骤分类
PIPELINE_STEPS_LOCAL = [
    'fetch_stock_data', 'fetch_history', 'fetch_minute_kline',
    'strategy', 'multi_strategy', 'position_sizer', 'sim_trade',
    'broker_adapter', 'track_performance', 'newbie_instruction_card',
    'sector_classifier', 'send_to_bark',
]

PIPELINE_STEPS_LLM = [
    'research_agent', 'integrate_knowledge', 'psychology_assistant',
    'evolve_strategy', 'external_research', 'strategy_feedback',
]


def estimate_token_cost(operation, detail=''):
    """预估一次LLM调用的token和成本"""
    estimates = {
        'research_agent': (4000, 1500, '研究报告生成'),
        'integrate_knowledge': (2000, 800, '知识内化'),
        'psychology_assistant': (1000, 600, '心理助手'),
        'evolve_strategy': (3000, 1200, '策略进化A/B分析'),
        'external_research': (5000, 2000, 'arXiv论文研究'),
        'strategy_feedback': (2000, 800, '策略反馈分析'),
        'code_fix_debug': (1500, 500, '代码修复/调试'),
        'code_generation': (2000, 1500, '代码生成/重构'),
        'daily_report': (3000, 1000, '每日复盘报告'),
    }

    input_tok, output_tok, desc = estimates.get(operation, (1000, 500, operation))
    input_cost = (input_tok / 1_000_000) * COST_MODEL['input_per_mtok']
    output_cost = (output_tok / 1_000_000) * COST_MODEL['output_per_mtok']
    total_cost = input_cost + output_cost

    return {
        'operation': operation,
        'description': desc,
        'detail': detail,
        'input_tokens': input_tok,
        'output_tokens': output_tok,
        'total_tokens': input_tok + output_tok,
        'estimated_cost_usd': round(total_cost, 6),
        'estimated_cost_cny': round(total_cost * 7.2, 4),  # 汇率约7.2
    }


def log_llm_call(operation, detail='', cost_override=None):
    """记录一次LLM调用"""
    os.makedirs(DATA_DIR, exist_ok=True)

    if cost_override:
        entry = cost_override
        entry['operation'] = operation
    else:
        entry = estimate_token_cost(operation, detail)

    entry['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry['date'] = datetime.now().strftime('%Y-%m-%d')

    with open(COST_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    return entry


def load_cost_logs(days=30):
    """加载最近的成本日志"""
    if not os.path.exists(COST_LOG_FILE):
        return pd.DataFrame()

    logs = []
    with open(COST_LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not logs:
        return pd.DataFrame()

    df = pd.DataFrame(logs)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[df['timestamp'] >= datetime.now() - timedelta(days=days)]
    return df


def generate_daily_audit():
    """生成每日成本审计报告"""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    df = load_cost_logs(days=30)
    today = datetime.now().strftime('%Y-%m-%d')

    # 今日成本
    today_df = df[df['date'] == today] if len(df) > 0 else pd.DataFrame()
    today_llm_cost = today_df['estimated_cost_cny'].sum() if len(today_df) > 0 else 0
    today_llm_count = len(today_df)

    # 本月成本
    month_start = datetime.now().strftime('%Y-%m-01')
    month_df = df[df['date'] >= month_start] if len(df) > 0 else pd.DataFrame()
    month_llm_cost = month_df['estimated_cost_cny'].sum() if len(month_df) > 0 else 0
    month_llm_count = len(month_df)

    # 本地节省估算（每次流水线运行，假设18步中12步纯本地）
    local_runs = month_df['date'].nunique() if len(month_df) > 0 else 1
    # 如果完全没有记录，假设至少1次运行
    if local_runs == 0:
        local_runs = 1
    saved_llm_calls = local_runs * len(PIPELINE_STEPS_LOCAL)
    # 预估如果每步都用LLM的成本（每步约¥0.05-0.50）
    avg_llm_step_cost = 0.10  # 平均每步¥0.10
    local_savings = saved_llm_calls * avg_llm_step_cost

    # 构建报告
    lines = [
        f"# 成本审计报告 — {today}",
        f"",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 成本优先原则：数据清洗、格式转换、简单计算 → 本地完成；LLM仅用于决策、研究和异常修复",
        f"",
        f"## 📊 今日概览",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 今日LLM调用次数 | {today_llm_count} |",
        f"| 今日LLM成本 | ¥{today_llm_cost:.4f} |",
        f"| 纯本地步骤（成本¥0） | {len(PIPELINE_STEPS_LOCAL)}步 (fetch/strategy/position等) |",
        f"| LLM步骤（成本>¥0） | {len(PIPELINE_STEPS_LLM)}步 (research/evolve等) |",
        f"",
        f"## 💰 本月累计",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 本月LLM调用次数 | {month_llm_count} |",
        f"| 本月LLM成本 | ¥{month_llm_cost:.4f} |",
        f"| 本地计算节省估算 | ¥{local_savings:.2f} (如果全用LLM) |",
        f"| 流水线运行天数 | {local_runs} 天 |",
        f"",
    ]

    # 今日调用明细
    if len(today_df) > 0:
        lines.extend([
            f"## 📋 今日LLM调用明细",
            f"",
            f"| 时间 | 操作 | 描述 | Token | 成本(¥) |",
            f"|------|------|------|-------|---------|",
        ])
        for _, row in today_df.iterrows():
            t = row.get('timestamp', '').strftime('%H:%M') if isinstance(row.get('timestamp'), pd.Timestamp) else ''
            lines.append(f"| {t} | {row.get('operation', '')} | {row.get('description', '')} | "
                        f"{row.get('total_tokens', 0):,} | ¥{row.get('estimated_cost_cny', 0):.4f} |")
        lines.append("")

    # 优化建议
    suggestions = []
    if len(month_df) > 0:
        op_counts = month_df['operation'].value_counts()
        # 检查重复调用
        for op, count in op_counts.items():
            if count > month_df['date'].nunique() * 2:
                suggestions.append(
                    f"⚠️ **{op}** 本月调用 {count} 次，日均 {count/max(1,month_df['date'].nunique()):.1f} 次，"
                    f"建议检查是否有重复调用或参数格式问题导致的重试"
                )

    if not suggestions:
        suggestions.append("✅ 本月无明显异常调用模式，成本控制良好。")

    lines.extend([
        f"## 🔍 优化建议",
        f"",
    ])
    for s in suggestions:
        lines.append(f"- {s}")
    lines.append("")

    # 成本曲线（文字版）
    if len(month_df) > 0:
        daily_costs = month_df.groupby('date')['estimated_cost_cny'].sum()
        lines.extend([
            f"## 📈 本月每日成本曲线",
            f"",
            f"```",
        ])
        max_cost = daily_costs.max() if len(daily_costs) > 0 else 1
        for date_val, cost in daily_costs.items():
            bar_len = int(cost / max(0.001, max_cost) * 40)
            lines.append(f"  {date_val} {'█' * bar_len} ¥{cost:.4f}")
        lines.extend(["```", ""])

    lines.extend([
        f"---",
        f"*报告由 cost_tracker.py v{SYSTEM_VERSION} 自动生成 | 成本模型基于API定价预估*",
        f"",
        f"### 成本预估参数",
        f"- 输入: ${COST_MODEL['input_per_mtok']}/MTok",
        f"- 输出: ${COST_MODEL['output_per_mtok']}/MTok",
        f"- 代码生成: ~{COST_MODEL['lines_code_estimate']} tokens/100行",
        f"- 研究报告: ~{COST_MODEL['research_report_estimate']} tokens/篇",
    ])

    report_path = os.path.join(REPORTS_DIR, f'cost_audit_{datetime.now().strftime("%Y%m%d")}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"[COST] Audit report: {report_path}")
    print(f"[COST] Today: {today_llm_count} LLM calls, CNY {today_llm_cost:.4f}")
    print(f"[COST] Month: {month_llm_count} LLM calls, CNY {month_llm_cost:.4f}")

    return report_path


def get_cost_summary():
    """获取成本摘要供仪表盘使用"""
    df = load_cost_logs(days=30)
    today = datetime.now().strftime('%Y-%m-%d')
    month_start = datetime.now().strftime('%Y-%m-01')

    today_df = df[df['date'] == today] if len(df) > 0 else pd.DataFrame()
    month_df = df[df['date'] >= month_start] if len(df) > 0 else pd.DataFrame()

    daily_costs = month_df.groupby('date')['estimated_cost_cny'].sum().to_dict() if len(month_df) > 0 else {}

    return {
        'today_cost': round(today_df['estimated_cost_cny'].sum(), 4) if len(today_df) > 0 else 0,
        'today_calls': len(today_df),
        'month_cost': round(month_df['estimated_cost_cny'].sum(), 4) if len(month_df) > 0 else 0,
        'month_calls': len(month_df),
        'daily_costs': daily_costs,
        'local_steps': len(PIPELINE_STEPS_LOCAL),
        'llm_steps': len(PIPELINE_STEPS_LLM),
    }


def main():
    print(f"{'='*50}")
    print(f"  成本审计模块 v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    # 记录本次调用
    log_llm_call('cost_tracker', '成本审计报告生成')

    # 生成审计报告
    report = generate_daily_audit()

    # 打印摘要
    summary = get_cost_summary()
    print(f"\n[COST] Today: {summary['today_calls']} calls, CNY {summary['today_cost']:.4f}")
    print(f"[COST] Month: {summary['month_calls']} calls, CNY {summary['month_cost']:.4f}")
    print(f"[COST] 纯本地: {summary['local_steps']}步, LLM: {summary['llm_steps']}步")

    return 0


if __name__ == '__main__':
    sys.exit(main())
