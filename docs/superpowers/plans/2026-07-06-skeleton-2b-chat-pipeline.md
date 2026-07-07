# 骨架 2b：聊天链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通完整聊天链路：React/assistant-ui 前端 ⟷ assistant-stream 协议 ⟷ FastAPI/deepagents 后端，用户登录后可选会话、发消息、看到 agent 流式执行 ai-berkshire skill。

**Architecture:** 后端在 2a 基座上新增 `app/agent`（工具、受限工作区后端、agent 组装）与 `app/chat`（assistant-transport 协议端点）；agent 从 PoC 移植并吸收全部 7 条实战输入。前端为独立 `frontend/` Vite React SPA，通过 Vite dev proxy 与后端同源（生产由 Caddy 同源反代），规避 CORS-with-credentials。协议层严格对照官方示例 `assistant-ui/python/assistant-transport-backend-langgraph/main.py`（已核实的真实 API）。

**Tech Stack:** 后端加 deepagents==0.6.12（锁定，PoC 验证版本）、langchain-deepseek、assistant-stream、langgraph-checkpoint-postgres、trafilatura、akshare；前端 Vite + React 18 + TypeScript + Tailwind + shadcn/ui + @assistant-ui/react + @assistant-ui/react-langgraph + TanStack Query + React Router + Zustand。

**对应 spec：** §4.3（执行流程，积分部分除外——计划 3）、§4.4（工具安全边界）、§4.5（失败处理）、§10 步骤 2 后半。skill 的 DB 化/市场/按用户安装/积分在计划 3；本计划所有用户共享全量官方 skill（文件系统目录）。

## PoC 实战输入落点（7 条全覆盖）

| # | PoC 输入 | 落点 |
|---|---|---|
| 1 | [P0] 虚拟 FS 与 run_python 世界隔断 | Task 2：每 thread 真实目录工作区 + 受限 FilesystemBackend（virtual_mode=False + 自实现 containment），write_file 落盘、run_python 同目录执行 |
| 2 | [P0] 抽检失败 todo 谎报 | Task 4：SYSTEM_PROMPT 硬规则（审计未通过必须如实标注）；结构化准出流程在计划 3 |
| 3 | [P1] DeepSeek 400 Content Exists Risk 重试 | Task 4：invoke 层重试包装 |
| 4 | [P1] report_audit 需 --results-file | Task 1：skill 导入脚本对我方拷贝打补丁 |
| 5 | [P2] 北交所数据源 | Task 3：移植 PoC 的 bj 代码映射；ashare_data.py 兜底随 tools 拷贝可被 run_python 调用 |
| 6 | [P2] fetch_page GBK 乱码 | Task 3：编码探测 |
| 7 | flash/pro 分工 | 维持 v4-pro（Task 4 默认）；flash 分层随计划 3 的 skill 元数据 |

## Global Constraints

- `deepagents==0.6.12` 精确锁定（PoC 验证）；`system_prompt` 参数名、`FilesystemBackend` 位于 `deepagents.backends.filesystem`
- LLM 模型 ID 只允许 `deepseek-v4-flash` / `deepseek-v4-pro`（白名单校验，PoC 已有实现可移植）
- 密钥只经 `backend/.env`：新增 `DEEPSEEK_API_KEY`、`BOCHA_API_KEY`、`DEEPSEEK_MODEL`（可选默认 deepseek-v4-pro）、`FAKE_LLM`（可选，测试/E2E）
- dev compose：postgres `localhost:5434`、redis `6381`（2a 已定）
- 每 thread 工作区在 `backend/var/workspaces/{thread_id}/`（gitignore `var/`）；agent 一切文件读写与脚本执行都被限制在其中
- 工具错误契约：任何工具异常必须转为 `错误：` 开头的字符串返回（PoC tool_guard 模式），绝不向 agent 循环抛异常
- 前端代码全部在 `frontend/`；后端新代码在 `backend/app/{agent,chat}` 与 `backend/skills_data/`
- **commit 授权沿用既定模式**：专属分支（如 `skeleton-2b`）本地 commit，绝不 push
- 协议对照物：官方示例代码已存于会话记录（ChatRequest/命令 schema、create_run/append_langgraph_event 用法、useAssistantTransportRuntime/converter 用法），实施时以已安装版本实测为准，偏差记录报告

---

### Task 1: Agent 依赖 + skill 资产导入

**Files:**
- Modify: `backend/pyproject.toml`（uv add）、`backend/.env.example`、`backend/.gitignore`（加 `var/`）
- Create: `backend/scripts/import_skills.py`、`backend/skills_data/`（生成产物，**提交入库**：19 个 skill 目录 + tools/*.py）
- Test: `backend/tests/test_import_skills.py`

**Interfaces:**
- Produces:
  - `backend/skills_data/skills/<slug>/SKILL.md` ×19（Agent Skills 规范 frontmatter）+ `backend/skills_data/tools/*.py`（含打补丁后的 `report_audit.py`）
  - `import_skills.py` 的 `extract_meta(md_text, slug) -> (title, description)`、`convert_skill(src_md, dest_root) -> Path`、`build_assets(dest_root) -> None`（全量 19 个 + tools 拷贝 + report_audit 补丁）
  - 新依赖可导入：deepagents/langchain_deepseek/assistant_stream/trafilatura/akshare/langgraph-checkpoint-postgres

- [ ] **Step 1: 安装依赖**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
uv add "deepagents==0.6.12" langchain-deepseek assistant-stream langgraph-checkpoint-postgres trafilatura akshare
uv add --dev respx
```

`.env.example` 追加：

```bash
DEEPSEEK_API_KEY=sk-xxx
BOCHA_API_KEY=sk-xxx
# 可选：deepseek-v4-pro（默认）/ deepseek-v4-flash
DEEPSEEK_MODEL=deepseek-v4-pro
# 测试/E2E：设为 1 时用脚本化假模型，不调真实 LLM
FAKE_LLM=0
```

`.gitignore` 追加一行 `var/`。

验证：`uv run python -c "import deepagents, langchain_deepseek, assistant_stream, trafilatura, akshare; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; print('ok')"` → ok

- [ ] **Step 2: 写失败测试**

`backend/tests/test_import_skills.py`：

```python
from pathlib import Path

from scripts.import_skills import convert_skill, extract_meta

DEMO = """# 演示技能：示例分析框架

对 $ARGUMENTS 进行演示分析。

## 第一步

做点什么。
"""


def test_extract_meta():
    title, desc = extract_meta(DEMO, "demo-skill")
    assert title == "演示技能：示例分析框架"
    assert "演示分析" in desc
    assert "$ARGUMENTS" not in desc


def test_convert_skill(tmp_path: Path):
    src = tmp_path / "demo-skill.md"
    src.write_text(DEMO, encoding="utf-8")
    out = convert_skill(src, tmp_path / "assets")
    assert out == tmp_path / "assets" / "skills" / "demo-skill" / "SKILL.md"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---" and lines[1] == "name: demo-skill"
    assert lines[2].startswith('description: "')


def test_generated_assets_present():
    """入库的生成产物必须存在且完整（防 fresh clone 空目录静默）。"""
    root = Path(__file__).resolve().parents[1] / "skills_data"
    skills = list((root / "skills").glob("*/SKILL.md"))
    assert len(skills) == 19
    assert (root / "tools" / "financial_rigor.py").exists()
    audit = (root / "tools" / "report_audit.py").read_text(encoding="utf-8")
    assert "--results-file" in audit  # PoC 输入#4：补丁已打
```

Run: `uv run pytest tests/test_import_skills.py -v` → FAIL（ModuleNotFoundError: scripts）

- [ ] **Step 3: 实现导入脚本**

`backend/scripts/__init__.py`：空文件。

`backend/scripts/import_skills.py`（核心转换逻辑从 `poc/src/poc/convert_skills.py` 移植，全量 19 个 skill）：

```python
"""把 ai-berkshire 全量 skill 转成 Agent Skills 规范资产目录（生成产物提交入库）。"""
from __future__ import annotations

import shutil
from pathlib import Path

AI_BERKSHIRE = Path("/Users/weixi1/Documents/Study/ai-berkshire")


def extract_meta(md_text: str, slug: str) -> tuple[str, str]:
    lines = md_text.splitlines()
    title = slug
    description = ""
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            for rest in lines[i + 1 :]:
                text = rest.strip()
                if text and not text.startswith("#"):
                    description = text
                    break
            break
    description = description or title
    description = description.replace("$ARGUMENTS", "用户指定的目标")
    return title, description[:500]


def convert_skill(src_md: Path, dest_root: Path) -> Path:
    slug = src_md.stem
    md_text = src_md.read_text(encoding="utf-8")
    title, description = extract_meta(md_text, slug)
    desc_line = f"{title}：{description}".replace('"', "'")
    skill_dir = dest_root / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    out = skill_dir / "SKILL.md"
    out.write_text(
        f'---\nname: {slug}\ndescription: "{desc_line}"\n---\n\n{md_text}', encoding="utf-8"
    )
    return out


def patch_report_audit(tools_dir: Path) -> None:
    """PoC 输入#4：report_audit.py 增加 --results-file 参数直读报告文件。

    实施说明：先读 ai-berkshire/tools/report_audit.py 的真实 argparse 结构，
    在其参数定义处追加 `--results-file`（Path，可选），存在时跳过原有的报告定位逻辑、
    直接读取该文件内容作为审计对象。保持原有子命令/输出格式不变。
    补丁以直接改写我方拷贝实现（不改上游 repo），改完必须通过 Step 4 的冒烟验证。
    """
    raise NotImplementedError("实施时按上述说明改写拷贝后的 report_audit.py，然后删除本函数占位并内联补丁逻辑")


def build_assets(dest_root: Path) -> None:
    for src_md in sorted((AI_BERKSHIRE / "skills").glob("*.md")):
        convert_skill(src_md, dest_root)
    tools_dst = dest_root / "tools"
    tools_dst.mkdir(parents=True, exist_ok=True)
    for py in (AI_BERKSHIRE / "tools").glob("*.py"):
        shutil.copy(py, tools_dst / py.name)
    patch_report_audit(tools_dst)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "skills_data"
    build_assets(root)
    print(f"assets ready: {root}")
```

注意 `patch_report_audit`：这是本任务唯一需要实证的点——先 `head -80 /Users/weixi1/Documents/Study/ai-berkshire/tools/report_audit.py` 看清其 argparse 结构，把补丁写成对拷贝文件的确定性文本改写（如在固定锚点行后插入参数定义与读取分支）。改完删除 NotImplementedError 占位。

- [ ] **Step 4: 生成资产并冒烟补丁**

```bash
uv run python -m scripts.import_skills
ls skills_data/skills/ | wc -l          # 期望 19
uv run python skills_data/tools/report_audit.py --help 2>&1 | grep results-file
```

Expected: 19；`--results-file` 出现在 help 中。

- [ ] **Step 5: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_import_skills.py -v` → 3 passed；`uv run ruff check .`

```bash
git add backend/pyproject.toml backend/uv.lock backend/.env.example backend/.gitignore backend/scripts/ backend/skills_data/ backend/tests/test_import_skills.py
git commit -m "feat(agent): import ai-berkshire skills as SKILL.md assets with patched report_audit"
```

---

### Task 2: 每会话工作区 + 受限文件系统后端（PoC P0 修复）

**Files:**
- Create: `backend/app/agent/__init__.py`、`backend/app/agent/workspace.py`
- Test: `backend/tests/test_workspace.py`

**Interfaces:**
- Produces:
  - `get_thread_workspace(thread_id: str) -> Path`：确保 `backend/var/workspaces/{thread_id}/` 存在，首次创建时把 `skills_data/tools/` 拷入 `{ws}/tools/`；返回绝对路径
  - `make_backend(workspace: Path)`：返回 deepagents 可用的 backend 实例，**写盘生效**（write_file 的产物出现在真实目录，run_python 可读）且**逃逸被拒**（绝对路径出界 / `..` 上跳返回错误而非写入）
  - `WORKSPACES_ROOT: Path`（`backend/var/workspaces`）

**背景（为什么不用 PoC 的两种现成模式）**：PoC 实测 `virtual_mode=True` 时 write_file 进内存态（与磁盘隔断，run_python 读不到，评估中 3/5 题审计链路断裂）；`virtual_mode=False` 时直接写真实文件系统但无 containment（评估中逃逸写到 `~/`）。本任务要第三种：真实落盘 + 强制 containment。

- [ ] **Step 1: 实证 deepagents 0.6.12 的 FilesystemBackend 结构**

```bash
cd backend && uv run python -c "
import inspect
from deepagents.backends.filesystem import FilesystemBackend
print(inspect.getsourcefile(FilesystemBackend))
print([m for m in dir(FilesystemBackend) if not m.startswith('_')])
"
```

然后读该源文件，确定路径解析的集中点（0.6.12 中 virtual_mode=False 路径通常经过一个 resolve/normalize 辅助方法或直接 `Path(path)`）。子类化目标：**每个对外文件操作前把路径解析为绝对路径并校验 `is_relative_to(root)`**。若存在单一 `_resolve_path` 类辅助方法则只覆写它；若没有，覆写各文件操作方法（ls/read_file/write_file/edit_file/glob/grep）做前置校验。把实际覆写点记入报告。

- [ ] **Step 2: 写失败测试**

`backend/tests/test_workspace.py`：

```python
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


def test_workspace_idempotent(ws):
    again = get_thread_workspace("t-123")
    assert again == ws


def test_backend_write_lands_on_disk(ws):
    backend = make_backend(ws)
    backend.write_file("report.md", "# 报告内容")
    assert (ws / "report.md").read_text(encoding="utf-8") == "# 报告内容"


def test_backend_blocks_absolute_escape(ws, tmp_path):
    backend = make_backend(ws)
    outside = tmp_path / "outside.txt"
    result = backend.write_file(str(outside), "越界")
    # 契约：不落盘 + 返回/抛出错误（两种实现都接受，但绝不能写出去）
    assert not outside.exists()
    if isinstance(result, str):
        assert "错误" in result or "denied" in result.lower() or "escape" in result.lower()


def test_backend_blocks_dotdot_escape(ws):
    backend = make_backend(ws)
    try:
        backend.write_file("../escape.txt", "越界")
    except Exception:
        pass
    assert not (ws.parent / "escape.txt").exists()


def test_backend_read_roundtrip(ws):
    backend = make_backend(ws)
    backend.write_file("notes/a.md", "abc")
    assert "abc" in backend.read_file("notes/a.md")
```

Run: `uv run pytest tests/test_workspace.py -v` → FAIL（ModuleNotFoundError: app.agent）

说明：`write_file`/`read_file` 的实际方法签名以 Step 1 实证为准——若 0.6.12 的方法名/返回形态不同（如返回 ToolResult 对象），按真实签名调整测试的调用方式，但**六个行为断言（落盘/幂等/绝对逃逸拒绝/../逃逸拒绝/回读）不得削弱**。

- [ ] **Step 3: 实现**

`backend/app/agent/workspace.py`（骨架，路径校验为核心，覆写点按 Step 1 实证调整）：

```python
"""每会话真实目录工作区 + 受限文件系统后端。

PoC P0 修复：write_file 必须落真实盘（run_python 同世界可读），
且一切路径被限制在工作区内（virtual_mode=False 的逃逸问题在此关死）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend

BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKSPACES_ROOT = BACKEND_DIR / "var" / "workspaces"
SKILLS_DATA = BACKEND_DIR / "skills_data"


def get_thread_workspace(thread_id: str) -> Path:
    ws = WORKSPACES_ROOT / thread_id
    if not ws.exists():
        ws.mkdir(parents=True)
        shutil.copytree(SKILLS_DATA / "tools", ws / "tools")
    return ws


class SandboxedFilesystemBackend(FilesystemBackend):
    """强制 containment 的真实落盘后端。"""

    def __init__(self, root_dir: str):
        super().__init__(root_dir=root_dir, virtual_mode=False)
        self._sandbox_root = Path(root_dir).resolve()

    def _contained(self, path: str) -> Path:
        candidate = Path(path)
        resolved = (
            candidate if candidate.is_absolute() else self._sandbox_root / candidate
        ).resolve()
        if not resolved.is_relative_to(self._sandbox_root):
            raise PermissionError(f"错误：路径越界被拒绝：{path}")
        return resolved

    # 覆写点按 Step 1 实证：若基类有集中式路径解析方法，只覆写它并在内部调用
    # self._contained()；否则逐个覆写文件操作方法，先 _contained() 再委托 super()。


def make_backend(workspace: Path) -> SandboxedFilesystemBackend:
    return SandboxedFilesystemBackend(root_dir=str(workspace))
```

- [ ] **Step 4: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_workspace.py -v` → 6 passed；全量回归 `uv run pytest -q`

```bash
git add backend/app/agent/ backend/tests/test_workspace.py
git commit -m "feat(agent): per-thread workspace with sandboxed filesystem backend"
```

---

### Task 3: Agent 工具移植（web/stock/runner + 编码修复）

**Files:**
- Create: `backend/app/agent/tools/__init__.py`、`backend/app/agent/tools/safe.py`、`backend/app/agent/tools/web.py`、`backend/app/agent/tools/stock.py`、`backend/app/agent/tools/runner.py`
- Test: `backend/tests/test_agent_tools.py`

**Interfaces:**
- Consumes: Task 2 `get_thread_workspace`
- Produces（供 Task 4 注入 agent；均为 langchain `@tool`，错误契约统一）:
  - `tool_guard(fn)` 装饰器（`tools/safe.py`，从 `poc/src/poc/tools/safe.py` 原样移植）
  - `web_search(query: str, count: int = 8) -> str`（博查；无 key 优雅降级）
  - `fetch_page(url: str) -> str`（**新增编码探测**：PoC 输入#6）
  - `stock_quote(symbol: str) -> str` / `stock_financials(symbol: str) -> str`（新浪源 + `_sina_symbol` 含 bj 映射，从 `poc/src/poc/tools/stock.py` 移植）
  - `make_run_python(workspace: Path)` → 绑定该工作区的 `run_python(script: str, argv: str = "") -> str` 工具（**与 PoC 差异**：workspace 不再是模块级常量而是按 thread 注入）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_tools.py`（PoC `test_tools.py` 的移植 + 两个新断言）：

```python
import httpx
import pytest
import respx

from app.agent.tools.runner import make_run_python
from app.agent.tools.stock import _sina_symbol
from app.agent.tools.web import BOCHA_ENDPOINT, fetch_page, web_search


@respx.mock
def test_web_search_formats_results(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    respx.post(BOCHA_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"webPages": {"value": [
                {"name": "茅台财报", "url": "https://x.com/1", "summary": "净利润增长"}
            ]}}},
        )
    )
    out = web_search.invoke({"query": "贵州茅台 财报"})
    assert "茅台财报" in out and "净利润增长" in out


def test_web_search_degrades_without_key(monkeypatch):
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    assert web_search.invoke({"query": "任意"}).startswith("错误：搜索服务未配置")


@respx.mock
def test_fetch_page_gbk_no_mojibake():
    html = "<html><body><article><p>贵州茅台营收创新高，同比增长。</p></article></body></html>"
    respx.get("https://gbk.example.com/a").mock(
        return_value=httpx.Response(
            200,
            content=html.encode("gbk"),
            headers={"content-type": "text/html"},  # 无 charset，考验探测
        )
    )
    out = fetch_page.invoke({"url": "https://gbk.example.com/a"})
    assert "贵州茅台" in out  # PoC 输入#6：GBK 页面不得乱码


@respx.mock
def test_fetch_page_error_contract():
    respx.get("https://x.example.com/403").mock(return_value=httpx.Response(403))
    out = fetch_page.invoke({"url": "https://x.example.com/403"})
    assert out.startswith("错误：")


@pytest.mark.parametrize(
    ("code", "expected"),
    [("600519", "sh600519"), ("000001", "sz000001"), ("920982", "bj920982"),
     ("830799", "bj830799"), ("430047", "bj430047"), ("900901", "sh900901")],
)
def test_sina_symbol_mapping(code, expected):
    assert _sina_symbol(code) == expected


def test_run_python_scoped_to_workspace(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi from ws')", encoding="utf-8")
    run_python = make_run_python(tmp_path)
    out = run_python.invoke({"script": "hello.py"})
    assert "exit=0" in out and "hi from ws" in out
    assert run_python.invoke({"script": "../../etc/passwd"}).startswith("错误")
```

Run: `uv run pytest tests/test_agent_tools.py -v` → FAIL（ModuleNotFoundError）

- [ ] **Step 2: 实现（以 PoC 为底本移植）**

`tools/safe.py`：从 `poc/src/poc/tools/safe.py` 原样拷贝（tool_guard 装饰器）。

`tools/web.py`：从 `poc/src/poc/tools/web.py` 移植，`fetch_page` 的正文提取前改为编码感知：

```python
@tool
def fetch_page(url: str) -> str:
    """抓取网页并提取正文文本（截断到 8000 字符）。用于阅读搜索结果的原文。"""
    return _fetch_page_impl(url)


@tool_guard
def _fetch_page_impl(url: str) -> str:
    resp = httpx.get(
        url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
    html = resp.content.decode(_detect_encoding(resp), errors="replace")
    text = trafilatura.extract(html) or ""
    return text[:8000] or "（未能提取正文）"


def _detect_encoding(resp: httpx.Response) -> str:
    """头部有 charset 用头部；否则从 meta/内容探测（中文站大量 GBK）。"""
    ctype = resp.headers.get("content-type", "")
    if "charset=" in ctype:
        return ctype.split("charset=")[-1].split(";")[0].strip()
    head = resp.content[:2048].lower()
    if b"gbk" in head or b"gb2312" in head or b"gb18030" in head:
        return "gb18030"
    return resp.encoding or "utf-8"
```

（注意 tool_guard 与 @tool 的叠放顺序沿用 PoC 结论：@tool 最外层、tool_guard 在内。web_search 保持 PoC 的无 key 早退 + guard。）

`tools/stock.py`：从 `poc/src/poc/tools/stock.py` 原样移植（`_sina_symbol` 含 92/8x/43x→bj、900→sh 规则，stock_zh_a_daily + stock_financial_abstract）。若 PoC 的 `_sina_symbol` 未覆盖 `43`/`83` 开头（老三板/北交所），补上并使 Step 1 参数化测试全绿。

`tools/runner.py`（工作区注入版）：

```python
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from app.agent.tools.safe import tool_guard


def make_run_python(workspace: Path):
    root = workspace.resolve()

    @tool
    def run_python(script: str, argv: str = "") -> str:
        """执行工作区内的白名单 Python 脚本（如 tools/financial_rigor.py）。argv 为空格分隔参数。"""
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
            capture_output=True, text=True, timeout=60, cwd=root,
        )
        return f"exit={proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-2000:]}"

    return run_python
```

- [ ] **Step 3: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_agent_tools.py -v` → 全绿（≥10 例）；全量回归

```bash
git add backend/app/agent/tools/ backend/tests/test_agent_tools.py
git commit -m "feat(agent): port guarded tools with GBK detection and scoped runner"
```

---

### Task 4: Agent 组装（deepseek 重试 + Fake 模型 + checkpointer）

**Files:**
- Create: `backend/app/agent/build.py`、`backend/app/agent/fake_llm.py`
- Modify: `backend/app/core/config.py`（新增 settings 字段）
- Test: `backend/tests/test_agent_build.py`

**Interfaces:**
- Consumes: Task 2 workspace/backend、Task 3 全部工具
- Produces:
  - `build_agent(thread_id: str, checkpointer=None)` → deepagents CompiledStateGraph：SandboxedFilesystemBackend + skills=[skills_data/skills 绝对路径] + 五工具 + SYSTEM_PROMPT（PoC 五条硬规则 + **新增第 6 条防谎报** + 日期注入）
  - `SYSTEM_PROMPT: str`（模板常量）
  - 模型选择：`FAKE_LLM=1` → `FakeToolCallingModel`（脚本化）；否则 ChatDeepSeek + 白名单校验 + **Content Exists Risk 重试包装**
  - `make_checkpointer(database_url: str)` → `AsyncPostgresSaver` async context（URL 自动转换 `postgresql+asyncpg://` → `postgresql://`）；调用方负责 `.setup()`
  - Settings 新增：`deepseek_api_key: str = ""`、`deepseek_model: str = "deepseek-v4-pro"`、`bocha_api_key: str = ""`、`fake_llm: bool = False`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_build.py`：

```python
import pytest

from app.agent.build import ALLOWED_MODELS, SYSTEM_PROMPT, build_agent, make_checkpointer


def test_system_prompt_guardrails():
    for kw in ["工具", "来源", "编造", "SKILL.md", "如实标注"]:  # 第6条：防谎报
        assert kw in SYSTEM_PROMPT, kw


def test_build_agent_compiles_with_fake_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config
    config.get_settings.cache_clear()
    import app.agent.workspace as ws_mod
    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path)
    agent = build_agent("t-build-1")
    assert hasattr(agent, "astream") and hasattr(agent, "ainvoke")


def test_model_whitelist(monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "0")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")  # 已退役 ID
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")
    from app.core import config
    config.get_settings.cache_clear()
    with pytest.raises(ValueError, match="不允许的模型"):
        build_agent("t-build-2")
    assert ALLOWED_MODELS == {"deepseek-v4-flash", "deepseek-v4-pro"}


def test_checkpointer_url_conversion():
    ctx = make_checkpointer("postgresql+asyncpg://u:p@h:5434/db")
    # from_conn_string 返回 async contextmanager；只验证不抛错且 URL 已剥离 +asyncpg
    assert ctx is not None


async def test_fake_llm_end_to_end(tmp_path, monkeypatch):
    """脚本化假模型走完 agent 循环：先调 stock_quote 再答复。"""
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config
    config.get_settings.cache_clear()
    import app.agent.workspace as ws_mod
    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path)
    agent = build_agent("t-e2e-1")
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "茅台现在多少钱"}]},
        config={"recursion_limit": 50},
    )
    final = result["messages"][-1]
    assert "假回复" in final.content
```

Run: `uv run pytest tests/test_agent_build.py -v` → FAIL

（注：`test_fake_llm_end_to_end` 里 fake 模型的脚本会先发一个 `stock_quote` 工具调用——它会真调新浪接口或失败返回错误串，两者都能让循环继续到最终答复，断言只看最终文本。若网络不可用导致不稳定，把 fake 脚本第一步改为无副作用的 `write_file` 内置工具调用，报告中说明。）

- [ ] **Step 2: 实现 fake_llm.py**

`backend/app/agent/fake_llm.py`：

```python
"""脚本化假模型：支持 bind_tools 的最小 BaseChatModel，测试/E2E 用（FAKE_LLM=1）。

脚本语义：首轮返回一个工具调用（stock_quote 茅台）；之后任何一轮都返回固定文本答复。
"""
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeToolCallingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingModel":
        return self  # 工具签名忽略，脚本决定行为

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        has_tool_result = any(isinstance(m, ToolMessage) for m in messages)
        if has_tool_result:
            msg = AIMessage(content="假回复：茅台行情已查询，以上为工具返回的数据。")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[{"id": "fake-1", "name": "stock_quote", "args": {"symbol": "600519"}}],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])
```

（若 deepagents 0.6.12 对模型有额外接口要求——如 profile/attribute 探测——按实际报错补最小实现，记录报告。）

- [ ] **Step 3: 实现 build.py 与 settings**

`app/core/config.py` 的 Settings 追加四个字段（默认值见 Interfaces）。

`backend/app/agent/build.py`：

```python
import datetime as dt

from deepagents import create_deep_agent
from langchain_deepseek import ChatDeepSeek

from app.agent.fake_llm import FakeToolCallingModel
from app.agent.tools.runner import make_run_python
from app.agent.tools.stock import stock_financials, stock_quote
from app.agent.tools.web import fetch_page, web_search
from app.agent.workspace import SKILLS_DATA, get_thread_workspace, make_backend
from app.core.config import get_settings

ALLOWED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}

SYSTEM_PROMPT = """你是 D-sight 投研助手，服务中文投资者。

硬性规则：
1. 涉及行情、财务、新闻的事实，必须实际调用工具获取，禁止凭记忆编造数字。
2. 报告中的关键数字必须注明来源（工具名或 URL）。
3. 任务匹配某个 skill 描述时，先读入该 skill 的 SKILL.md 并严格按其步骤执行；\
skill 指定的交叉验证步骤（如 tools/financial_rigor.py、tools/report_audit.py）必须用 run_python 真实执行。
4. 简单概念问答（不涉及具体标的的实时数据）直接回答，不要启动重型研究流程。
5. 信息不足或数据不存在时（如未发布的财报），明确说明，不得编造。
6. todo 与结论必须如实反映执行结果：任何审计/验证步骤失败或未执行时，\
必须标注"未完成"并在答复中明确说明，严禁将失败步骤标记为完成。
"""


def _make_model():
    s = get_settings()
    if s.fake_llm:
        return FakeToolCallingModel()
    name = s.deepseek_model
    if name not in ALLOWED_MODELS:
        raise ValueError(f"不允许的模型 ID：{name}，只能用 {sorted(ALLOWED_MODELS)}")
    model = ChatDeepSeek(model=name, api_key=s.deepseek_api_key, timeout=120, max_retries=3)
    # PoC 输入#3：Content Exists Risk 是 400，SDK 默认不重试——包一层
    return model.with_retry(
        retry_if_exception_type=(_content_risk_error_types()),
        stop_after_attempt=3,
        wait_exponential_jitter=True,
    )


def _content_risk_error_types():
    """实施说明：DeepSeek 的 400 Content Exists Risk 经 langchain-deepseek 抛出的
    具体异常类型（通常是 openai.BadRequestError）需实证确认；用自定义谓词时改用
    with_retry 的对应参数或包装 Runnable。确认后内联真实类型并删除本函数。"""
    raise NotImplementedError


def make_checkpointer(database_url: str):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    return AsyncPostgresSaver.from_conn_string(url)


def build_agent(thread_id: str, checkpointer=None):
    ws = get_thread_workspace(thread_id)
    prompt = SYSTEM_PROMPT + f"\n当前日期：{dt.date.today().isoformat()}（做时效判断时以此为准）"
    return create_deep_agent(
        model=_make_model(),
        tools=[web_search, fetch_page, stock_quote, stock_financials, make_run_python(ws)],
        backend=make_backend(ws),
        skills=[str(SKILLS_DATA / "skills")],
        system_prompt=prompt,
        checkpointer=checkpointer,
    )
```

`_content_risk_error_types` 的实证：`uv run python -c "import openai; print(openai.BadRequestError)"`，并查 `with_retry` 是否支持谓词（langchain-core Runnable.with_retry 的参数为 `retry_if_exception_type`，只接受类型元组——若需按消息内容过滤"Content Exists Risk"，改为自定义 wrapper：捕获 BadRequestError、检查 `"Content Exists Risk" in str(e)`、重试至多 2 次，否则原样抛出）。实现哪种取决于实证结果，验收标准：单测里 monkeypatch 一个先抛 BadRequestError("Content Exists Risk") 再成功的桩，断言重试生效（在 Step 4 报告中补一个此测试）。

注意：`create_deep_agent` 是否接受 `checkpointer` 参数需实证（Task 1 已锁 0.6.12，`inspect.signature` 查看）；若不接受，改为 `create_deep_agent(...).compile(checkpointer=...)` 或按该版本文档的等价方式，记录报告。

- [ ] **Step 4: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_agent_build.py -v` → 全绿（含补充的重试单测）；全量回归

```bash
git add backend/app/agent/ backend/app/core/config.py backend/tests/test_agent_build.py
git commit -m "feat(agent): deepagents assembly with fake LLM, retry, and postgres checkpointer"
```

---

### Task 5: 聊天流式端点（assistant-transport 协议）

**Files:**
- Create: `backend/app/chat/__init__.py`、`backend/app/chat/schemas.py`、`backend/app/chat/router.py`
- Modify: `backend/app/main.py`（挂载 + lifespan 管理 checkpointer）
- Test: `backend/tests/test_chat_api.py`

**Interfaces:**
- Consumes: 2a `get_current_user`/`Thread`、Task 4 `build_agent`/`make_checkpointer`
- Produces:
  - `POST /api/chat`：请求体为 assistant-transport `ChatRequest`（commands: add-message/add-tool-result、threadId、state），需 Bearer；响应 `DataStreamResponse`（SSE）
  - 行为：threadId 缺失/非本人/已删 → 404；首条消息时把 thread 标题设为文本前 30 字；运行结束 touch thread.updated_at
  - `create_app()` 生命周期内持有全局 checkpointer（`AsyncPostgresSaver` context，启动时 `.setup()`）；测试可通过 `app.state` 注入替身

**协议 schema（对照官方示例 main.py 原文，直接移植）**：`MessagePart`、`UserMessage`、`AddMessageCommand`、`AddToolResultCommand`、`ChatRequest`（字段与 alias 逐字对照会话中已核实的示例代码；我们仅新增：threadId 必填校验）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_chat_api.py`：

```python
import pytest

from tests.test_auth_api import _register


def _chat_body(thread_id: str, text: str) -> dict:
    return {
        "commands": [
            {"type": "add-message", "message": {"role": "user", "parts": [{"type": "text", "text": text}]}}
        ],
        "threadId": thread_id,
        "state": None,
    }


@pytest.fixture
async def auth_and_thread(client, db_session, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config
    config.get_settings.cache_clear()
    token = await _register(client, db_session, "chat-user@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    tid = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    return headers, tid


async def test_chat_streams_fake_reply(auth_and_thread, client):
    headers, tid = auth_and_thread
    async with client.stream(
        "POST", "/api/chat", json=_chat_body(tid, "茅台现在多少钱"), headers=headers
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    assert "假回复" in body  # fake 模型的最终文本进入了流


async def test_chat_requires_auth(client):
    resp = await client.post("/api/chat", json=_chat_body("00000000-0000-0000-0000-000000000000", "hi"))
    assert resp.status_code == 401


async def test_chat_rejects_foreign_thread(auth_and_thread, client, db_session):
    headers, _ = auth_and_thread
    other = await _register(client, db_session, "chat-other@test.dev")
    other_tid = (
        await client.post("/api/threads/", json={}, headers={"Authorization": f"Bearer {other}"})
    ).json()["id"]
    resp = await client.post("/api/chat", json=_chat_body(other_tid, "hi"), headers=headers)
    assert resp.status_code == 404


async def test_chat_sets_title_and_touches_thread(auth_and_thread, client):
    headers, tid = auth_and_thread
    async with client.stream(
        "POST", "/api/chat", json=_chat_body(tid, "分析贵州茅台的投资价值，重点看护城河"), headers=headers
    ) as resp:
        async for _ in resp.aiter_text():
            pass
    threads = (await client.get("/api/threads/", headers=headers)).json()
    me = next(t for t in threads if t["id"] == tid)
    assert me["title"].startswith("分析贵州茅台")
    assert len(me["title"]) <= 30
```

Run: `uv run pytest tests/test_chat_api.py -v` → FAIL（404）

（测试用 FAKE_LLM，无真实 LLM/网络依赖——fake 模型首轮调 stock_quote 可能真联网，若 CI 无外网导致不稳，参照 Task 4 Step 1 的注记调整 fake 脚本，两处保持一致。checkpointer 在测试中不设（None→deepagents 默认内存），端点代码需容忍 app.state 无 checkpointer 的情形。）

- [ ] **Step 2: 实现**

`backend/app/chat/schemas.py`：把官方示例的五个 pydantic 模型逐字移植（MessagePart/UserMessage/AddMessageCommand/AddToolResultCommand/ChatRequest，保留 alias 与 populate_by_name 配置）。

`backend/app/chat/router.py`：

```python
import uuid

from assistant_stream import RunController, create_run
from assistant_stream.modules.langgraph import append_langgraph_event
from assistant_stream.serialization import DataStreamResponse
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.build import build_agent
from app.auth.deps import get_current_user
from app.auth.models import User
from app.chat.schemas import ChatRequest
from app.core.db import get_db, get_sessionmaker
from app.threads.models import Thread

router = APIRouter(prefix="/api/chat", tags=["chat"])

TITLE_MAX = 30


async def _owned_thread(db: AsyncSession, user: User, thread_id: str | None) -> Thread:
    if not thread_id:
        raise HTTPException(404, "会话不存在")
    try:
        tid = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(404, "会话不存在")
    t = await db.get(Thread, tid)
    if t is None or t.user_id != user.id or t.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return t


def _extract_inputs(request: ChatRequest) -> tuple[list, str]:
    """commands → langchain 消息列表 + 首条文本（供标题）。"""
    messages, first_text = [], ""
    for command in request.commands:
        if command.type == "add-message":
            texts = [p.text for p in command.message.parts if p.type == "text" and p.text]
            if texts:
                joined = " ".join(texts)
                first_text = first_text or joined
                messages.append(HumanMessage(content=joined))
        elif command.type == "add-tool-result":
            content = command.model_content if command.model_content is not None else command.result
            messages.append(
                ToolMessage(
                    content=content if isinstance(content, str) else str(content),
                    tool_call_id=command.tool_call_id,
                    status="error" if command.is_error else "success",
                )
            )
    return messages, first_text


@router.post("")
async def chat(
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    thread = await _owned_thread(db, user, request.thread_id)
    input_messages, first_text = _extract_inputs(request)
    if thread.title == "新对话" and first_text:
        thread.title = first_text[:TITLE_MAX]
    await db.commit()

    thread_id = str(thread.id)
    agent = build_agent(thread_id)  # checkpointer 接入见 main.py lifespan 说明

    async def run_callback(controller: RunController):
        if controller.state is None:
            controller.state = {}
        controller.state.setdefault("messages", [])
        for m in input_messages:
            controller.state["messages"].append(m.model_dump())

        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 200}
        async for namespace, event_type, chunk in agent.astream(
            {"messages": input_messages},
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            append_langgraph_event(controller.state, namespace, event_type, chunk)

        # 结束后 touch updated_at（新 session，流回调里不能复用请求级 session）
        async with get_sessionmaker()() as s:
            t = await s.get(Thread, thread.id)
            if t is not None:
                t.title = t.title  # 触发 UPDATE → onupdate 刷新 updated_at
                await s.commit()

    return DataStreamResponse(create_run(run_callback, state=request.state))
```

实施注意（按实测调整，记录报告）：
- `agent.astream(..., subgraphs=True)` 的产物形态（是否恒为三元组）以实测为准；官方示例即此写法，deepagents 底层同为 LangGraph。
- checkpointer：`main.py` 的 lifespan 中 `make_checkpointer(settings.database_url)` 进入 context + `.setup()`，存 `app.state.checkpointer`；本端点从 `request.app.state` 取（不存在则 None）传给 `build_agent`。测试（ASGITransport 不跑 lifespan 的情况下）自然走 None 分支。
- "触发 UPDATE" 若 `t.title = t.title` 不产生脏标记（SQLAlchemy 同值不脏），改用 `t.updated_at = datetime.now(UTC)` 直接赋值——两者选实测有效的，并在 threads 测试锁定的约定下运行全量回归确认。

`main.py`：挂载 chat router；lifespan 里初始化/关闭 checkpointer（参照官方示例 `configure_checkpointer_from_env` 的 aenter/aexit 模式，但走 `get_settings().database_url`）。

- [ ] **Step 3: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_chat_api.py -v` → 4 passed；全量回归 + ruff

```bash
git add backend/app/chat/ backend/app/main.py backend/tests/test_chat_api.py
git commit -m "feat(chat): assistant-transport streaming endpoint with thread ownership"
```

---

### Task 6: 前端脚手架（认证页 + API 层 + 路由）

**Files:**
- Create: `frontend/`（Vite React TS 项目）：`vite.config.ts`（含 /api 代理）、`src/lib/api.ts`、`src/lib/auth.ts`、`src/pages/{LoginPage,RegisterPage}.tsx`、`src/pages/ChatPage.tsx`（占位）、`src/App.tsx`（路由 + 守卫）、Tailwind + shadcn 初始化
- Test: `frontend/src/lib/auth.test.ts`（vitest）

**Interfaces:**
- Produces:
  - `npm run dev` 起 5173，`/api/*` 代理到 `http://localhost:8000`（同源方案，cookie/CORS 免配）
  - `api.ts`：`apiFetch(path, init?) -> Response`——自动带 `Authorization: Bearer <access>`；401 时先调 `/api/auth/refresh`（携 cookie）拿新 access 重试一次，仍 401 则清 token 跳登录
  - `auth.ts`（zustand store）：`{accessToken, setToken, clearToken}` + `login(email, pw)`、`register(email, code, pw)`、`requestCode(email)`、`logout()`
  - 路由：`/login`、`/register`、`/`（ChatPage，未登录重定向 /login）
  - **Task 7 消费**：`useAuthStore.getState().accessToken`（runtime headers 注入）、`apiFetch`

- [ ] **Step 1: 脚手架**

```bash
cd /Users/weixi1/Documents/mine/D-sight
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-router-dom zustand @tanstack/react-query
npm install tailwindcss @tailwindcss/vite
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
npx shadcn@latest init -d
npx shadcn@latest add button input card label
```

（shadcn init 若询问配置，取默认；Tailwind v4 用 `@tailwindcss/vite` 插件方式，跟 shadcn 当前文档走。若 shadcn 与 Vite/Tailwind v4 组合有向导差异，以 `npx shadcn@latest init` 实际向导为准，记录报告。）

`vite.config.ts` 加代理与 vitest 配置：

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  // @ts-expect-error vitest 扩展字段
  test: { environment: "jsdom", globals: true },
});
```

- [ ] **Step 2: 写失败测试（token 刷新语义）**

`frontend/src/lib/auth.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";
import { useAuthStore } from "./auth";

describe("apiFetch 401 刷新重试", () => {
  beforeEach(() => {
    useAuthStore.getState().setToken("old-token");
    vi.restoreAllMocks();
  });

  it("401 时刷新并用新 token 重试一次", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: any, init?: any) => {
        calls.push(`${url}|${init?.headers?.Authorization ?? ""}`);
        if (String(url).endsWith("/api/auth/refresh"))
          return new Response(JSON.stringify({ access_token: "new-token" }), { status: 200 });
        const auth = init?.headers?.Authorization;
        return new Response(auth === "Bearer new-token" ? "{}" : "unauthorized", {
          status: auth === "Bearer new-token" ? 200 : 401,
        });
      }),
    );
    const resp = await apiFetch("/api/threads/");
    expect(resp.status).toBe(200);
    expect(useAuthStore.getState().accessToken).toBe("new-token");
    expect(calls.some((c) => c.includes("/api/auth/refresh"))).toBe(true);
  });

  it("刷新失败则清空 token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: any) =>
        new Response("no", { status: 401 }),
      ),
    );
    const resp = await apiFetch("/api/threads/");
    expect(resp.status).toBe(401);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});
```

Run: `npx vitest run src/lib/auth.test.ts` → FAIL（模块不存在）

- [ ] **Step 3: 实现 auth store 与 api 层**

`frontend/src/lib/auth.ts`：

```ts
import { create } from "zustand";

type AuthState = {
  accessToken: string | null;
  setToken: (t: string) => void;
  clearToken: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  setToken: (t) => set({ accessToken: t }),
  clearToken: () => set({ accessToken: null }),
}));

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
}

export async function requestCode(email: string) {
  const r = await post("/api/auth/request-code", { email });
  if (!r.ok) throw new Error((await r.json()).detail ?? "发送失败");
}

export async function register(email: string, code: string, password: string) {
  const r = await post("/api/auth/register", { email, code, password });
  if (!r.ok) throw new Error((await r.json()).detail ?? "注册失败");
  useAuthStore.getState().setToken((await r.json()).access_token);
}

export async function login(email: string, password: string) {
  const r = await post("/api/auth/login", { email, password });
  if (!r.ok) throw new Error((await r.json()).detail ?? "登录失败");
  useAuthStore.getState().setToken((await r.json()).access_token);
}

export async function logout() {
  await post("/api/auth/logout", {});
  useAuthStore.getState().clearToken();
}
```

`frontend/src/lib/api.ts`：

```ts
import { useAuthStore } from "./auth";

async function tryRefresh(): Promise<string | null> {
  const r = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
  if (!r.ok) return null;
  const token = (await r.json()).access_token as string;
  useAuthStore.getState().setToken(token);
  return token;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const withAuth = (token: string | null): RequestInit => ({
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: "same-origin",
  });
  let resp = await fetch(path, withAuth(useAuthStore.getState().accessToken));
  if (resp.status === 401) {
    const fresh = await tryRefresh();
    if (fresh) {
      resp = await fetch(path, withAuth(fresh));
    } else {
      useAuthStore.getState().clearToken();
    }
  }
  return resp;
}
```

- [ ] **Step 4: 页面与路由**

`src/pages/LoginPage.tsx` / `RegisterPage.tsx`：shadcn Card + Input + Button 的表单（注册页含"获取验证码"按钮 60 秒倒计时），成功后 `navigate("/")`；错误用红色文本显示 `detail`。`src/pages/ChatPage.tsx` 本任务占位（居中显示"聊天界面（Task 7）"+ 退出按钮）。`src/App.tsx`：

```tsx
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/auth";
import ChatPage from "@/pages/ChatPage";
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";

const qc = new QueryClient();

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.accessToken);
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/" element={<RequireAuth><ChatPage /></RequireAuth>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

（页面组件代码由实施者按此结构+shadcn 组件完成，验收看 Step 5 手工冒烟。刷新页面时 access 在内存会丢——RequireAuth 首次挂载时若无 token 先尝试一次 `tryRefresh()` 再决定跳转，避免刷新即登出；把这个逻辑写进 RequireAuth。）

- [ ] **Step 5: 验证 + Commit（需用户已授权）**

Run: `npx vitest run` → 2 passed；`npm run build` → 成功。
手工冒烟（后端 `uv run uvicorn app.main:create_app --factory --port 8000` + 前端 `npm run dev`）：注册（验证码看后端 stdout）→ 跳转聊天占位页 → 刷新页面仍保持登录（refresh cookie 生效）→ 退出回登录页。把每步结果记入报告。

```bash
git add frontend/
git commit -m "feat(frontend): scaffold with auth pages, token refresh, and api proxy"
```

---

### Task 7: 聊天界面（assistant-ui 接入）

**Files:**
- Create: `frontend/src/chat/RuntimeProvider.tsx`、`frontend/src/chat/Thread.tsx`（assistant-ui 组件组装）、`frontend/src/chat/ThreadListSidebar.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/chat/threads.test.tsx`（列表渲染）

**Interfaces:**
- Consumes: Task 5 `POST /api/chat`（assistant-transport 协议）、2a threads CRUD、Task 6 `apiFetch`/`useAuthStore`
- Produces: 完整聊天页：左侧会话列表（新建/重命名/删除/选中），右侧 assistant-ui Thread（流式文本 + 工具调用过程可见）

- [ ] **Step 1: 安装 assistant-ui**

```bash
cd frontend
npm install @assistant-ui/react @assistant-ui/react-langgraph @assistant-ui/react-markdown
npx shadcn@latest add "https://r.assistant-ui.com/thread"
```

（assistant-ui 提供 shadcn registry 组件；若 registry URL 变化，以 assistant-ui 文档 Getting Started 为准，记录报告。）

- [ ] **Step 2: RuntimeProvider（对照官方 with-assistant-transport 示例移植）**

`frontend/src/chat/RuntimeProvider.tsx`——以会话中核实的官方示例 `MyRuntimeProvider.tsx` 为底本，做四处适配：

```tsx
"use client 指令删除（Vite 无需）";
// 1) api 指向同源代理：api: "/api/chat"
// 2) headers 注入 JWT：headers: async () => ({ Authorization: `Bearer ${useAuthStore.getState().accessToken}` })
// 3) body 携带 threadId：body: { threadId: activeThreadId }（由 props 传入；threadId 变化时用 key={threadId} 重建 runtime）
// 4) 无前端工具：去掉 toolkit/Tools 相关代码
// converter 与 LangChainMessageConverter 逐字保留（state.messages + pendingCommands 乐观更新）
```

完整文件以官方示例为底本 + 上述四处适配写出（示例代码已在会话记录中，含 `useAssistantTransportRuntime`、`unstable_createMessageConverter`、`convertLangChainMessages` 的确切 import）。若安装版本的 API 名与示例有出入（unstable_ 前缀变动等），以 `node_modules/@assistant-ui/react` 的类型定义实测为准，记录报告。

- [ ] **Step 3: 会话列表 + 页面组装**

`ThreadListSidebar.tsx`：TanStack Query 拉 `GET /api/threads/`；新建（POST）、重命名（PATCH，双击标题内联编辑）、删除（DELETE，确认后）；点击切换 `activeThreadId`。`ChatPage.tsx`：左 sidebar + 右 `<RuntimeProvider threadId={activeThreadId}><Thread /></RuntimeProvider>`；无会话时自动建一个。

`threads.test.tsx`：mock `apiFetch` 返回两条 thread，断言列表渲染标题与新建按钮存在（组件测试，不接真后端）。

- [ ] **Step 4: 端到端手工冒烟（FAKE_LLM）**

后端 `FAKE_LLM=1 uv run uvicorn app.main:create_app --factory --port 8000`，前端 dev：登录 → 新建会话 → 发"茅台现在多少钱" → 观察：流式出现工具调用（stock_quote）与"假回复"文本；会话标题变为消息前缀；刷新页面历史仍在（checkpointer）。**再切真实模型冒烟一次**（去掉 FAKE_LLM，用真实 DEEPSEEK_API_KEY 发同一问题，确认真实链路流式正常）。两次结果均记入报告。

- [ ] **Step 5: 验证 + Commit（需用户已授权）**

Run: `npx vitest run` → 全绿；`npm run build` 成功；`cd ../backend && uv run pytest -q` 回归全绿

```bash
git add frontend/
git commit -m "feat(frontend): assistant-ui chat with thread sidebar over assistant-transport"
```

---

### Task 8: 聊天历史恢复 + 会话内 401 刷新（T7 遗留缺陷）

**Files:**
- Create: `backend/app/chat/history.py`、`backend/tests/test_chat_history.py`
- Modify: `backend/app/chat/router.py`（新增 GET messages 端点）、`frontend/src/chat/RuntimeProvider.tsx`（initialState 从历史加载 + 401 刷新）
- Test: `backend/tests/test_chat_history.py`、`frontend/src/chat/history.test.ts`

**背景**：T7 暴露两个真实缺陷——(a) 刷新页面聊天历史不恢复（assistant-transport initialState 为空，checkpointer 只存服务端 LLM 上下文，未暴露给 UI）；(b) 聊天请求走 assistant-transport 自己的 fetch，绕过 apiFetch 单飞刷新，access token（15min）过期后发消息直接 401 失败。

**Interfaces:**
- Consumes: Task 5 端点、`build_agent`/checkpointer、2a `get_current_user`/`Thread`；前端 T6 `apiFetch`/`useAuthStore`
- Produces:
  - `GET /api/threads/{thread_id}/messages`（需 Bearer，归属 404）→ `{"messages": [LangChainMessage...]}`：从 checkpointer 读该 thread 最新 state 的 messages，转成前端 `convertLangChainMessages` 可消费的形态（`{type, content}`，type ∈ human/ai；工具消息可略过或作为 ai 附注——按渐进披露，UI 恢复只需 human/ai 文本轮）
  - `load_thread_messages(thread_id, checkpointer) -> list[dict]`（`app/chat/history.py`，从 checkpointer aget 提取，无历史返回 []）
  - 前端 RuntimeProvider：挂载时先 `apiFetch(GET messages)` 填充 `initialState.messages`（走 apiFetch → 自动刷新）；assistant-transport 的 `headers` 改为在发送前确保 token 新鲜——用 `apiFetch("/api/auth/me")` 探测或直接在 headers async fn 内复用一个"确保有效 token"helper（401 时先 tryRefresh 再返回）

- [ ] **Step 1: 后端历史提取（失败测试）**

`backend/tests/test_chat_history.py`：先跑一轮 FAKE_LLM 聊天（复用 test_chat_api 的方式）产生 checkpointer 状态，再 `GET /api/threads/{tid}/messages` 断言：200、messages 含刚发的 human 文本与 ai "假回复"；非本人 thread → 404；无历史的新 thread → 200 `{"messages": []}`。

（测试用 FAKE_LLM；checkpointer 在 ASGITransport 测试下为 None → deepagents 内存 checkpointer，跨请求不共享内存态，所以**测试需在同一进程内先 POST /api/chat 再 GET**——若内存 checkpointer 不跨请求保留，改用 lifespan 注入的持久 checkpointer 或在测试夹具里注入一个共享的 InMemorySaver 到 app.state，使 build_agent 两次调用共享它。实现时按实际 checkpointer 生命周期选定，报告说明。）

- [ ] **Step 2: 实现 history.py + 端点**

`load_thread_messages`：用 checkpointer 的 `aget_tuple`/`aget` 按 `{"configurable":{"thread_id":tid}}` 取最新 checkpoint，从 channel_values["messages"] 提取，映射为 `{"type": "human"|"ai", "content": <text>}`（BaseMessage.type 已是 human/ai/tool；tool 消息按需过滤）。端点复用 Task 5 的 `_owned_thread` 归属校验，checkpointer 从 `request.app.state` 取（None → 空历史，因为无持久 checkpointer 时本就无跨会话历史）。

- [ ] **Step 3: 前端历史加载 + 401 刷新（失败测试 + 实现）**

`frontend/src/chat/history.test.ts`：mock `apiFetch` 返回两条历史消息，断言 `loadInitialState(threadId)` 返回 `{messages: [...]}`；mock 首次 401→刷新→重试（复用 apiFetch 单飞）路径不额外发起并发刷新。
RuntimeProvider：新增 `loadInitialState(threadId)` 用 `apiFetch` 拉历史填 initialState；`headers` async fn 改为调用一个 `ensureFreshToken()`（内部：若近期无 token 则 `apiFetch("/api/auth/me")` 触发刷新链路，返回最新 `getState().accessToken`）。key={threadId} 重建时重新加载。

- [ ] **Step 4: 全量验证 + Commit（需用户已授权）**

Run: 后端 `uv run pytest -q` 全绿；前端 `npx vitest run` 全绿 + `npm run build`。

```bash
git add backend/app/chat/ backend/tests/test_chat_history.py frontend/src/chat/
git commit -m "feat(chat): restore thread history on reload and refresh token mid-session"
```

---

### Task 9: E2E 冒烟 + CI 扩展

**Files:**
- Create: `frontend/e2e/chat.spec.ts`、`frontend/playwright.config.ts`
- Modify: `.github/workflows/ci.yml`（加 frontend job）、`backend/README.md`（补 2b 启动说明）

**Interfaces:**
- Produces:
  - `npx playwright test`：注册→登录→发消息→断言流式回复出现（后端 FAKE_LLM=1，验证码从后端 stdout 不可取——改用**测试后门**：`FAKE_LLM=1` 时 `/api/auth/request-code` 的响应体附带 `{"debug_code": "..."}`，仅该模式生效，实现放本任务）
  - CI：frontend job（npm ci + vitest + build）；E2E 只在本地跑（CI 需起全栈，留到部署计划）

- [ ] **Step 1: 测试后门（FAKE_LLM 模式下返回验证码）**

`backend/app/auth/router.py` 的 `request_code`：当 `get_settings().fake_llm` 为真时返回 `{"debug_code": code}`（service.request_code 需返回 code 值；正常模式仍 204 无体）。补后端测试：FAKE_LLM=1 时响应含 6 位 debug_code；FAKE_LLM=0 时 204 无体。

- [ ] **Step 2: Playwright 用例**

```bash
cd frontend && npm install -D @playwright/test && npx playwright install chromium
```

`frontend/e2e/chat.spec.ts`：

```ts
import { expect, test } from "@playwright/test";

test("注册登录并收到流式回复", async ({ page, request }) => {
  const email = `e2e-${Date.now()}@test.dev`;
  const codeResp = await request.post("http://localhost:8000/api/auth/request-code", {
    data: { email },
  });
  const { debug_code } = await codeResp.json();

  await page.goto("http://localhost:5173/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("验证码").fill(debug_code);
  await page.getByLabel("密码").fill("e2e-password-1");
  await page.getByRole("button", { name: /注册/ }).click();

  await page.getByPlaceholder(/发送|输入/).fill("茅台现在多少钱");
  await page.keyboard.press("Enter");
  await expect(page.getByText("假回复")).toBeVisible({ timeout: 30_000 });
});
```

`playwright.config.ts`：baseURL 5173、单 worker、`webServer` 数组同时起后端（`FAKE_LLM=1 uv run uvicorn ... --port 8000`，cwd backend）与前端 dev server（表单 label/placeholder 以 Task 6/7 实际实现为准微调 selector）。

- [ ] **Step 3: 跑通 E2E**

Run: `npx playwright test`
Expected: 1 passed（需要本机 dev postgres 5434 在跑；报告贴输出）

- [ ] **Step 4: CI 扩展 + README**

`.github/workflows/ci.yml` 追加 job：

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npx vitest run
      - run: npm run build
```

`backend/README.md` 补一节"聊天链路（2b）"：FAKE_LLM 用途、前端启动、E2E 命令、真实模型需要的 env。

- [ ] **Step 5: 验证 + Commit（需用户已授权）**

Run: 后端 `uv run pytest -q` 全绿；`npx vitest run` 全绿；`npx playwright test` 1 passed

```bash
git add frontend/ .github/workflows/ci.yml backend/app/auth/ backend/tests/ backend/README.md
git commit -m "feat: e2e chat smoke with fake LLM and frontend CI"
```

---

## Self-Review 记录

- **Spec 覆盖**：§4.3 执行流程（鉴权→组装→渐进披露→流式→会话管理；积分预检/记账明确划归计划 3）✅；§4.4 安全边界（工作区 containment + 白名单脚本 + 60s 超时；Docker tool-runner 容器隔离归部署，工作区方案是其单机前身，spec §4.4 的"资源受限容器"在计划 6 部署时落）⚠️→ 已在 Task 2 背景段说明取舍；§4.5 失败处理（tool_guard、LLM max_retries=3、Content Risk 重试、15 分钟级 recursion_limit 控制——绝对时长超时在端点层未做，依赖 LangGraph recursion_limit + LLM timeout，差异记录：绝对超时归计划 3 与积分结算一起做）✅；PoC 7 条输入全落点（映射表见头部）✅。
- **占位符扫描**：两处 NotImplementedError（report_audit 补丁、Content Risk 异常类型）均为**显式实证-替换步骤**，带完成判据（--help 冒烟 / 重试单测），非未完成项 ✅；Task 6/7 页面组件给结构+验收不给逐行 JSX，验收由手工冒烟+组件测试兜底 ✅。
- **类型一致性**：`build_agent(thread_id, checkpointer=None)` Task 4 定义 / Task 5 消费一致；`make_run_python(workspace) -> tool` Task 3/4 一致；`get_thread_workspace`/`make_backend`/`SKILLS_DATA` Task 2 定义 Task 4 消费一致；前端 `useAuthStore`/`apiFetch` Task 6 定义 Task 7 消费一致；fake 模型行为（首轮 stock_quote → 次轮"假回复"）Task 4/5/8 三处一致 ✅。
