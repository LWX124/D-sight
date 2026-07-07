"""每会话真实目录工作区 + 受限文件系统后端。

PoC P0 修复：write_file 必须落真实盘（run_python 同世界可读），
且一切路径被限制在工作区内（``virtual_mode=False`` 的逃逸问题在此关死）。

## 覆写策略（实证结论）

deepagents 0.6.12 的 ``FilesystemBackend`` 把**所有**对外文件操作
（``ls`` / ``read`` / ``write`` / ``edit`` / ``grep`` / ``glob`` /
``upload_files`` / ``download_files``）的路径解析统一收敛到单一私有辅助
方法 ``_resolve_path(key) -> Path``；异步变体（``aread``/``awrite`` 等）
经 ``asyncio.to_thread`` 委托到同名同步方法。因此**只需覆写
``_resolve_path`` 这一个集中点**即可对整个工具面强制 containment，
无需逐个覆写文件操作方法。

基类 ``_resolve_path`` 在 ``virtual_mode=False`` 下的行为（源码 211-217 行）：

    path = Path(key)
    if path.is_absolute():
        _raise_if_symlink_loop(path)
        return path              # 绝对路径原样放行 -> 可逃逸
    resolved = (self.cwd / path).resolve()
    return resolved              # 相对路径含 '..' 可上跳逃逸

本类在委托基类前，先把路径解析为绝对路径并校验
``is_relative_to(sandbox_root)``，越界即抛 ``PermissionError``。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import GlobResult

BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKSPACES_ROOT = BACKEND_DIR / "var" / "workspaces"
SKILLS_DATA = BACKEND_DIR / "skills_data"


def get_thread_workspace(thread_id: str) -> Path:
    """确保 ``{WORKSPACES_ROOT}/{thread_id}/`` 存在并返回其绝对路径。

    首次创建时把 ``skills_data/tools/`` 拷入 ``{ws}/tools/``，使
    ``run_python`` 与文件工具在同一真实目录下可见同一套工具脚本；同时把
    ``skills_data/skills/`` 拷入 ``{ws}/skills/``，使 deepagents 的 skill
    枚举指向 sandbox root 内（否则真实模式下 containment 守卫拒绝越界读取）。
    每 thread 拷 19 个 skill 目录是有意的隔离优先取舍（磁盘廉价，去重/软链为后续工作）。

    ``thread_id`` 必须是纯 token（真实值为 UUID）；含 ``/`` / ``\\`` /
    ``..`` 或绝对路径者一律拒绝，否则可 mkdir + 拷贝到 ``WORKSPACES_ROOT``
    之外（防御性纵深）。
    """
    if (
        "/" in thread_id
        or "\\" in thread_id
        or ".." in thread_id
        or Path(thread_id).is_absolute()
    ):
        raise ValueError("非法的会话 ID")
    ws = (WORKSPACES_ROOT / thread_id).resolve()
    if not ws.exists():
        ws.mkdir(parents=True)
        shutil.copytree(SKILLS_DATA / "tools", ws / "tools")
        shutil.copytree(SKILLS_DATA / "skills", ws / "skills")
    return ws


class SandboxedFilesystemBackend(FilesystemBackend):
    """真实落盘 + 强制 containment 的文件系统后端。

    第三种模式：既非 ``virtual_mode=True``（写入进 state、与磁盘隔断），
    也非裸 ``virtual_mode=False``（写真实盘但无边界）；而是真实落盘且
    把每一次路径解析都夹在 ``sandbox_root`` 之内。
    """

    def __init__(self, root_dir: str):
        super().__init__(root_dir=root_dir, virtual_mode=False)
        self._sandbox_root = Path(root_dir).resolve()

    def _contained(self, path: str) -> Path:
        """把 ``path`` 解析为绝对路径并校验落在 sandbox 内，越界即拒绝。"""
        candidate = Path(path)
        base = candidate if candidate.is_absolute() else self._sandbox_root / candidate
        resolved = base.resolve()
        if not resolved.is_relative_to(self._sandbox_root):
            msg = f"错误：路径越界被拒绝（escape denied）：{path}"
            raise PermissionError(msg)
        return resolved

    def _resolve_path(self, key: str) -> Path:
        """所有文件操作的单一路径解析点：先 containment，再委托基类。

        委托基类（传入已解析的绝对路径）以保留其符号链接环检测等语义。
        """
        contained = self._contained(key)
        return super()._resolve_path(str(contained))

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """在委托基类前，无条件拒绝含 ``..`` 的 glob 模式。

        基类的 ``..`` 守卫仅在 ``virtual_mode=True`` 时生效（本类为 False），
        故 ``glob("../*")`` 会把 ``pattern`` 直接喂给 ``rglob``，泄漏 sandbox
        外的路径及其元数据（文件名 / 大小 / mtime 侦察泄漏）。此处镜像基类
        的 virtual_mode 守卫，越界模式抛出同一 ``ValueError``，契约一致。
        """
        probe = pattern.lstrip("/") if pattern.startswith("/") else pattern
        if ".." in Path(probe).parts:
            msg = "Path traversal not allowed in glob pattern"
            raise ValueError(msg)
        return super().glob(pattern, path)


def make_backend(workspace: Path) -> SandboxedFilesystemBackend:
    """返回受限于 ``workspace`` 的 deepagents 后端实例。"""
    return SandboxedFilesystemBackend(root_dir=str(workspace))
