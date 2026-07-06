import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from poc.tools.safe import tool_guard

WORKSPACE = Path(__file__).resolve().parents[3] / "workspace"


@tool
@tool_guard
def run_python(script: str, argv: str = "") -> str:
    """执行 workspace 内的白名单 Python 脚本（如 tools/financial_rigor.py）。argv 为空格分隔参数。"""
    script_path = (WORKSPACE / script).resolve()
    if not script_path.is_relative_to(WORKSPACE.resolve()) or script_path.suffix != ".py":
        return "错误：只能执行 workspace 内的 .py 脚本"
    if not script_path.exists():
        return f"错误：脚本不存在 {script}"
    proc = subprocess.run(
        [sys.executable, str(script_path), *argv.split()],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=WORKSPACE,
    )
    return f"exit={proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-2000:]}"
