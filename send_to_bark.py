"""
Bark 推送模块 v5 — 统一入口（瘦客户端）
业务逻辑已迁移至 bark_sender/ 子包
"""
import os, sys, argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from bark_sender.parsers import find_latest_report, parse_report_full, parse_honest_eval
from bark_sender.formatters import build_personalized_section
from bark_sender.builders import build_bark_message, build_bark_message_simple, build_bark_message_research, build_bark_message_for_tier
from bark_sender.push import send_bark, send_from_newbie_file
from bark_sender.channels import push_all

ORDERS_DIR = os.path.join(BASE_DIR, 'orders')


def load_digest(pick_date):
    """v8.7: 读取 digest.py 生成的 orders/digest_bark_YYYYMMDD.txt，返回 (title, body) 或 None。"""
    d = str(pick_date or '').replace('-', '')
    if len(d) != 8:
        return None
    path = os.path.join(ORDERS_DIR, f'digest_bark_{d}.txt')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except Exception:
        return None
    if not lines or not lines[0].startswith('TITLE: '):
        return None
    title = lines[0][7:].strip()
    body = '\n'.join(lines[1:]).strip()
    return (title, body) if body else None


def push(title, body):
    """v8.7: 走渠道注册表（Bark + 可选 webhook/飞书），逐渠道打印结果。"""
    results = push_all(title, body)
    for line in results:
        print(f"[PUSH] {line}")
    return any(line.startswith('OK') for line in results)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Bark推送工具')
    parser.add_argument('--simple', action='store_true', help='新手简单模式')
    parser.add_argument('--research', action='store_true', help='研究模式')
    parser.add_argument('--newbie', action='store_true', help='读取新手预生成文件')
    parser.add_argument('--dry-run', action='store_true', help='仅生成内容，不推送')
    parser.add_argument('--file', type=str, help='从指定文件读取内容推送')
    parser.add_argument('--no-digest', action='store_true', help='不前置当日开盘前简报')
    args = parser.parse_args()

    # v8.7 修复：.newbie_mode 存在时自动走新手指令卡推送（旧版开关与推送链路脱节）
    if not (args.simple or args.research or args.newbie or args.file) and os.path.exists(
            os.path.join(BASE_DIR, '.newbie_mode')):
        print("[BARK] .newbie_mode detected, auto --newbie")
        args.newbie = True

    if args.newbie:
        loaded = send_from_newbie_file()
        if not loaded:
            print("[BARK] No newbie instruction file found (newbie_card step 未运行或 .newbie_mode 不存在于生成时)。")
            return 1
        title, body = loaded
        if not args.dry_run:
            return 0 if push(title, body) else 1
        print(f"[DRY-RUN] Title: {title}\nBody: {body[:300]}...")
        return 0

    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            body = f.read()
        title = "量化系统通知"
        if not args.dry_run:
            return 0 if push(title, body) else 1
        print(f"[DRY-RUN] Title: {title}\nBody: {body[:200]}...")
        return 0

    report_path = find_latest_report()
    if not report_path:
        print("[BARK] No pick report found.")
        return 1

    pick_date, stocks = parse_report_full(report_path)
    bt_data = parse_honest_eval()

    if args.simple:
        title, body = build_bark_message_simple(pick_date, stocks, bt_data)
    elif args.research:
        title, body = build_bark_message_research(pick_date, stocks, bt_data)
    else:
        # v8: 按 SYSTEM_TIER 自动选模板 + 拼接 tier 附录（含摩擦成本）
        title, body = build_bark_message_for_tier(pick_date, stocks, bt_data)
        personalized = build_personalized_section()
        if personalized:
            body += "\n\n" + "\n".join(personalized)

    # v8.7: 当日四段简报前置——开盘前 5 分钟先读这 200 字，细节在下面
    if not args.no_digest:
        digest = load_digest(pick_date)
        if digest:
            d_title, d_body = digest
            title = d_title
            body = f"{d_body}\n\n────────\n{body}"
            print("[BARK] digest prepended")
        else:
            print("[BARK] no digest for today, push standard message only")

    if not args.dry_run:
        ok = push(title, body)
        return 0 if ok else 1
    print(f"[DRY-RUN] Title: {title}\nBody preview:\n{body[:500]}...")
    return 0


if __name__ == '__main__':
    exit(main())
