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


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Bark推送工具')
    parser.add_argument('--simple', action='store_true', help='新手简单模式')
    parser.add_argument('--research', action='store_true', help='研究模式')
    parser.add_argument('--newbie', action='store_true', help='读取新手预生成文件')
    parser.add_argument('--dry-run', action='store_true', help='仅生成内容，不推送')
    parser.add_argument('--file', type=str, help='从指定文件读取内容推送')
    args = parser.parse_args()

    if args.newbie:
        return send_from_newbie_file()

    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            body = f.read()
        title = "量化系统通知"
        if not args.dry_run:
            send_bark(title, body)
        else:
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

    if not args.dry_run:
        send_bark(title, body)
    else:
        print(f"[DRY-RUN] Title: {title}\nBody preview:\n{body[:500]}...")

    return 0


if __name__ == '__main__':
    exit(main())
