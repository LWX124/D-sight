"""Agent 运行时：每会话工作区 + 受限文件系统后端。"""

from app.agent.workspace import (
    WORKSPACES_ROOT,
    SandboxedFilesystemBackend,
    get_thread_workspace,
    make_backend,
)

__all__ = [
    "WORKSPACES_ROOT",
    "SandboxedFilesystemBackend",
    "get_thread_workspace",
    "make_backend",
]
