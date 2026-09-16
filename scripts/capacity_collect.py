"""capacity_collect.py 自包含化（916p-a1-020）。

统计仓内脚本写点（正则与排除规则保持原样，统计口径不变）。
改造点：①argparse 化（--dryrun-list/--prior-list，默认仍指 %TEMP% 原路径，向后兼容）；
②输入缺失打印可读错误并 exit 2（不再裸 traceback）；③rg 不可用给出明确提示；
④两名单可选，缺省按空集处理（dryrun/d91437 列显示 '-'）。
"""
import argparse
import os
import shutil
import subprocess
import sys

TMP = os.environ.get("TEMP", os.environ.get("TMP", "."))
PAT = r"open\(.*['\"](w|a)|to_csv|to_sql|executemany|INSERT INTO|UPDATE "


def _load_list(path):
    """读名单文件；空串（未提供）返回空集；文件缺失抛 FileNotFoundError 由调用方转可读错误。"""
    if not path:
        return set()
    with open(path) as f:
        return set(f.read().split())


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="统计 scripts 写点分布（rg 词边界口径不变）。"
                    "dryrun/prior 名单可选；缺省按空集（列显示 -）。")
    ap.add_argument("--dryrun-list", default=os.path.join(TMP, "q32_dryrun.txt"),
                    help="dry-run 名单文件（默认 %%TEMP%%\\q32_dryrun.txt；可传空串跳过）")
    ap.add_argument("--prior-list", default=os.path.join(TMP, "q32_prior.txt"),
                    help="d914-37 已覆盖名单文件（默认 %%TEMP%%\\q32_prior.txt；可传空串跳过）")
    ap.add_argument("--no-rg", action="store_true",
                    help="只校验环境与参数，不做 rg 扫描（干跑）")
    args = ap.parse_args(argv)

    if not shutil.which("rg"):
        print("[capacity_collect] 错误：未找到 rg 可执行文件（ripgrep）。"
              "请安装 ripgrep 或将其加入 PATH 后重试。", file=sys.stderr)
        return 2

    if args.no_rg:
        print("[capacity_collect] 干跑（--no-rg）：参数解析 OK，跳过扫描。")
        return 0

    try:
        dry = _load_list(args.dryrun_list)
    except FileNotFoundError as e:
        print(f"[capacity_collect] 错误：dry-run 名单不存在：{e.filename}。"
              f"补救：用 --dryrun-list 指向现有文件，或传 --dryrun-list '' 按空集统计。", file=sys.stderr)
        return 2
    try:
        prior = _load_list(args.prior_list)
    except FileNotFoundError as e:
        print(f"[capacity_collect] 错误：prior 名单不存在：{e.filename}。"
              f"补救：用 --prior-list 指向现有文件，或传 --prior-list '' 按空集统计。", file=sys.stderr)
        return 2

    out = subprocess.run(
        ["rg", "-c", PAT, "--glob", "*.py", "-g", "!archive/**", "-g", "!**/__pycache__/**",
         "-g", "!tests/**", "-g", "!app/**"],
        capture_output=True, text=True).stdout
    rows = []
    for ln in out.splitlines():
        f, n = ln.rsplit(":", 1)
        base = f.replace("\\", "/").split("/")[-1]
        rows.append((base, int(n), base in dry, base in prior))
    rows.sort(key=lambda r: (-r[1], r[0]))
    print("scripts-with-write:", len(rows), "| total-points:", sum(r[1] for r in rows),
          "| dryrun-flagged:", sum(1 for r in rows if r[2]),
          "| prior-d91437-covered:", sum(1 for r in rows if r[3]))
    for b, n, d, p in rows:
        print(f"{b:36s} pts={n:2d} dryrun={'Y' if d else '-'} d91437={'Y' if p else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
