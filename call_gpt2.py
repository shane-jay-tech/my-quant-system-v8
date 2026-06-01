import subprocess, sys

SYSTEM = (
    "You are a senior full-stack engineer. Write clean, idiomatic well-typed code. "
    "Comments only where intent is non-obvious. "
    "After writing, self-review: find >= 3 specific issues (cite line/function). "
    "Deliver final code fixing those issues. "
    "Output structure: Assumptions / Initial implementation / Self-review / Final code"
)

TASK = open(r"D:/code/my-quant-system-v8/gpt_task2.txt", encoding="utf-8").read()

with open(r"D:/code/my-quant-system-v8/gpt_output2.txt", "w", encoding="utf-8") as out:
    r = subprocess.run(
        [sys.executable, r"D:/code/scripts/llm_call.py",
         "--model", "gpt", "--mode", "quick",
         "--system", SYSTEM,
         "--prompt", TASK],
        stdout=out,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
stderr_text = r.stderr if r.stderr else ""
print("EXIT:", r.returncode)
if stderr_text:
    print("STDERR:", stderr_text[:300])
content = open(r"D:/code/my-quant-system-v8/gpt_output2.txt", encoding="utf-8").read()
print("OUTPUT len:", len(content))
print(content[:500])