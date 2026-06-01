
import subprocess, sys

SYSTEM = (
    "You are a senior full-stack engineer. Write clean, idiomatic well-typed code with tests. "
    "Prefer small functions, explicit names, minimal abstraction. "
    "Comments only where intent is non-obvious. "
    "After writing, self-review: find >= 3 specific issues (cite line/function). "
    "Deliver final code fixing those issues. "
    "Output structure: ## Assumptions / ## Initial implementation / ## Self-review (>=3 specific issues) / ## Final code"
)

TASK = open(r"D:/code/my-quant-system-v8/gpt_task.txt", encoding="utf-8").read()

r = subprocess.run(
    [sys.executable, r"D:/code/scripts/llm_call.py",
     "--model", "gpt", "--mode", "deep",
     "--system", SYSTEM,
     "--prompt", TASK],
    capture_output=False,
    text=True, encoding="utf-8",
    timeout=560
)
sys.exit(r.returncode)
