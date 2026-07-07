import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from app.agent.tools.safe import tool_guard

# 子进程仅继承 PATH，剥离进程级密钥（DEEPSEEK/BOCHA/JWT/DATABASE_URL 等），
# 避免脚本读到宿主密钥。注意：这是纵深防御，非完整隔离——脚本仍能读工作区外
# 磁盘（如 backend/.env）。真正的容器化/资源限制隔离归部署计划（Docker tool-runner）。
_SCRUBBED_ENV = {"PATH": os.environ.get("PATH", "")}


def make_run_python(workspace: Path):
    """返回一个绑定到 ``workspace`` 的 ``run_python`` 工具（按 thread 注入工作区）。"""
    root = workspace.resolve()

    @tool
    def run_python(script: str, argv: str = "") -> str:
        """执行工作区内的 .py 脚本（如 tools/financial_rigor.py）。argv 为空格分隔参数。"""
        return _run(script, argv)

    @tool_guard
    def _run(script: str, argv: str) -> str:
        script_path = (root / script).resolve()
        if not script_path.is_relative_to(root) or script_path.suffix != ".py":
            return "错误：只能执行工作区内的 .py 脚本"
        if not script_path.exists():
            return f"错误：脚本不存在 {script}"
        proc = subprocess.run(
            [sys.executable, str(script_path), *argv.split()],
            capture_output=True, text=True, timeout=60, cwd=root, env=_SCRUBBED_ENV,
        )
        return f"exit={proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-2000:]}"

    return run_python
