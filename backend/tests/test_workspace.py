"""每会话工作区 + 受限文件系统后端的行为测试。

八个测试（行为断言，不得削弱）：
1. 工作区已创建 + tools 已拷入
2. get_thread_workspace 幂等
3. write_file 落真实盘
4. 绝对路径逃逸被拒（不落盘）
5. ``..`` 上跳逃逸被拒（不落盘）
6. 写后回读一致
7. glob 含 ``..`` 模式被拒（抛 ValueError，不泄漏 sandbox 外路径/元数据）
8. get_thread_workspace 拒绝含穿越的 thread_id（不在根外创建任何东西）

deepagents 0.6.12 的真实方法为 ``write(file_path, content) -> WriteResult``、
``read(file_path) -> ReadResult``（返回结果对象而非裸字符串），本测试按真实签名调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import workspace as ws_mod
from app.agent.workspace import get_thread_workspace, make_backend


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(
        ws_mod, "SKILLS_DATA", Path(__file__).resolve().parents[1] / "skills_data"
    )
    return get_thread_workspace("t-123")


def test_workspace_created_with_tools(ws):
    assert ws.is_dir()
    assert (ws / "tools" / "financial_rigor.py").exists()


def test_workspace_no_skills_copy(ws):
    # 契约变更：workspace 创建不再全量拷贝 skills（物化职责移交给 build_agent）。
    # 新 workspace 无 skills 目录；内容一律由 write_skills 按已安装 skill 从 DB 物化。
    assert not (ws / "skills").exists()


def test_workspace_idempotent(ws):
    again = get_thread_workspace("t-123")
    assert again == ws


def test_backend_write_lands_on_disk(ws):
    backend = make_backend(ws)
    result = backend.write("report.md", "# 报告内容")
    assert result.error is None
    assert (ws / "report.md").read_text(encoding="utf-8") == "# 报告内容"


def test_backend_blocks_absolute_escape(ws, tmp_path):
    backend = make_backend(ws)
    outside = tmp_path / "outside.txt"
    result = backend.write(str(outside), "越界")
    # 契约：不落盘 + 返回错误（绝不能写出去）
    assert not outside.exists()
    assert result.error is not None


def test_backend_blocks_dotdot_escape(ws):
    backend = make_backend(ws)
    result = backend.write("../escape.txt", "越界")
    assert not (ws.parent / "escape.txt").exists()
    assert result.error is not None


def test_backend_read_roundtrip(ws):
    backend = make_backend(ws)
    backend.write("notes/a.md", "abc")
    result = backend.read("notes/a.md")
    assert result.error is None
    # ReadResult 是 dataclass，其 file_data 是 TypedDict（dict 访问）
    assert "abc" in result.file_data["content"]


def test_backend_glob_blocks_dotdot_pattern(ws):
    backend = make_backend(ws)
    # 在 sandbox 外放一个诱饵文件：若守卫失效，glob 会连同其元数据一起泄漏
    secret = ws.parent / "secret.txt"
    secret.write_text("绝密", encoding="utf-8")
    # 契约：含 '..' 的 glob 模式直接抛 ValueError（镜像基类 virtual_mode 守卫），
    # 因此绝无任何 sandbox 外的路径/元数据可被返回
    with pytest.raises(ValueError):
        backend.glob("../*")
    with pytest.raises(ValueError):
        backend.glob("../../**/*")


def test_get_thread_workspace_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(
        ws_mod, "SKILLS_DATA", Path(__file__).resolve().parents[1] / "skills_data"
    )
    with pytest.raises(ValueError):
        get_thread_workspace("../../evil")
    # 根之外未创建任何东西
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path.parent / "evil").exists()
