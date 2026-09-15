import os
import subprocess

TMP = os.environ.get("TEMP", os.environ.get("TMP", "."))
PAT = r"open\(.*['\"](w|a)|to_csv|to_sql|executemany|INSERT INTO|UPDATE "
out = subprocess.run(
    ["rg", "-c", PAT, "--glob", "*.py", "-g", "!archive/**", "-g", "!**/__pycache__/**",
     "-g", "!tests/**", "-g", "!app/**"],
    capture_output=True, text=True).stdout.splitlines()
dry = set(open(os.path.join(TMP, "q32_dryrun.txt")).read().split())
prior = set(open(os.path.join(TMP, "q32_prior.txt")).read().split())
rows = []
for ln in out:
    f, n = ln.rsplit(":", 1)
    base = f.replace("\\", "/").split("/")[-1]
    rows.append((base, int(n), base in dry, base in prior))
rows.sort(key=lambda r: (-r[1], r[0]))
print("scripts-with-write:", len(rows), "| total-points:", sum(r[1] for r in rows),
      "| dryrun-flagged:", sum(1 for r in rows if r[2]),
      "| prior-d91437-covered:", sum(1 for r in rows if r[3]))
for b, n, d, p in rows:
    print(f"{b:36s} pts={n:2d} dryrun={'Y' if d else '-'} d91437={'Y' if p else '-'}")
