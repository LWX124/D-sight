# PoC：Agent 运行时门禁验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证 deepagents + deepseek-v4 能否合格地执行 ai-berkshire 的 investment-research skill，产出 go/no-go 结论（决定是否启用"重型 skill 固定图编排"降级预案）。

**Architecture:** 独立的 `poc/` Python 包：skill 转换脚本把 ai-berkshire 的 md 转成 Agent Skills 规范的 SKILL.md 工作区；四个自定义 LangChain 工具（博查搜索、网页抓取、AkShare 行情/财务、白名单 Python 脚本执行）；`create_deep_agent` 组装 + CLI 流式运行器；10 题人工评估集 + 打分规则输出验收报告。

**Tech Stack:** Python 3.12、uv、deepagents、langchain-deepseek、httpx、trafilatura、akshare、rich、pytest、respx

**对应 spec：** `docs/superpowers/specs/2026-07-06-d-sight-design.md` §4.6（PoC 门禁与降级预案）、§10 步骤 1。本计划是 6 份计划中的第 1 份，只覆盖 PoC；spec 其余章节由后续计划覆盖。

## Global Constraints

- Python 3.12，依赖用 uv 管理，`uv.lock` 提交进 git
- LLM 模型 ID 只允许 `deepseek-v4-flash` / `deepseek-v4-pro`（旧 ID deepseek-chat/reasoner 于 2026-07-24 退役，禁用）
- 密钥只放 `poc/.env`（已 gitignore），提交 `poc/.env.example` 作为模板
- 所有 PoC 代码限定在 `poc/` 目录内，不创建 `backend/`（骨架计划的事）
- `poc/workspace/` 是生成物，gitignore
- **commit 需用户授权**：用户规则为不主动提交。执行开始前一次性询问用户是否授权按任务 commit；未授权则每个 commit 步骤改为 `git add` 后停下报告
- deepagents 迭代快：安装后如遇 API 签名不符（如 `system_prompt` vs `instructions` 参数名），以 `uv run python -c "import inspect; from deepagents import create_deep_agent; print(inspect.signature(create_deep_agent))"` 的实际签名为准调整，并把最终版本号记入验收报告

---

### Task 1: 项目脚手架

**Files:**
- Create: `poc/pyproject.toml`（uv 生成）、`poc/.env.example`、`poc/.gitignore` 追加条目、`poc/src/poc/__init__.py`

**Interfaces:**
- Produces: 可运行的 uv 项目；包导入路径 `poc.*`；环境变量约定 `DEEPSEEK_API_KEY`、`BOCHA_API_KEY`、`DEEPSEEK_MODEL`（可选，默认 deepseek-v4-pro）

- [ ] **Step 1: 初始化项目**

```bash
cd /Users/weixi1/Documents/mine/D-sight
uv init --lib poc --python 3.12
cd poc
uv add deepagents langchain-deepseek langgraph httpx trafilatura akshare python-dotenv rich
uv add --dev pytest respx
```

- [ ] **Step 2: 创建 .env.example 并配置 gitignore**

`poc/.env.example`：

```bash
DEEPSEEK_API_KEY=sk-xxx
BOCHA_API_KEY=sk-xxx
# 可选：deepseek-v4-pro（默认，重型分析）或 deepseek-v4-flash
DEEPSEEK_MODEL=deepseek-v4-pro
```

在 `poc/.gitignore` 追加（uv init 已生成基础内容则追加，没有则创建）：

```
.env
workspace/
```

- [ ] **Step 3: 验证依赖可导入**

Run: `uv run python -c "from deepagents import create_deep_agent; from langchain_deepseek import ChatDeepSeek; import akshare, trafilatura, respx; print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 4: 记录 deepagents 实际 API 签名（防版本漂移）**

Run: `uv run python -c "import inspect, deepagents; from deepagents import create_deep_agent; print(deepagents.__version__ if hasattr(deepagents,'__version__') else 'n/a'); print(inspect.signature(create_deep_agent))"`
Expected: 打印版本与签名。若后续任务中参数名与计划代码不符（`system_prompt`/`instructions`、`skills`、`backend`），以此签名为准修改代码。

- [ ] **Step 5: Commit（需用户已授权，见 Global Constraints）**

```bash
git add poc/
git commit -m "chore(poc): scaffold uv project with deepagents deps"
```

---

### Task 2: skill 转换器（ai-berkshire md → SKILL.md 工作区）

**Files:**
- Create: `poc/src/poc/convert_skills.py`
- Test: `poc/tests/test_convert_skills.py`

**Interfaces:**
- Produces:
  - `extract_meta(md_text: str, slug: str) -> tuple[str, str]` 返回 (title, description)
  - `convert_skill(src_md: Path, dest_root: Path) -> Path` 生成 `dest_root/skills/<slug>/SKILL.md`，返回其路径
  - `build_workspace(dest_root: Path, skills: list[str]) -> None` 转换指定 skill 并复制 ai-berkshire `tools/*.py` 到 `dest_root/tools/`
  - CLI：`uv run python -m poc.convert_skills` 生成 `poc/workspace/`（含 investment-research、financial-data 两个 skill）

- [ ] **Step 1: 写失败测试**

`poc/tests/test_convert_skills.py`：

```python
from pathlib import Path

from poc.convert_skills import convert_skill, extract_meta

DEMO = """# 演示技能：示例分析框架

对 $ARGUMENTS 进行演示分析。

## 第一步

做点什么。
"""


def test_extract_meta():
    title, desc = extract_meta(DEMO, "demo-skill")
    assert title == "演示技能：示例分析框架"
    assert "演示分析" in desc
    assert "$ARGUMENTS" not in desc  # 描述里不能留模板变量


def test_convert_skill(tmp_path: Path):
    src = tmp_path / "demo-skill.md"
    src.write_text(DEMO, encoding="utf-8")
    out = convert_skill(src, tmp_path / "ws")
    assert out == tmp_path / "ws" / "skills" / "demo-skill" / "SKILL.md"
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "---"
    assert lines[1] == "name: demo-skill"
    assert lines[2].startswith('description: "')
    assert lines[3] == "---"
    assert "对 $ARGUMENTS 进行演示分析。" in text  # 正文原样保留
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_convert_skills.py -v`
Expected: FAIL（ModuleNotFoundError: poc.convert_skills）

- [ ] **Step 3: 实现**

`poc/src/poc/convert_skills.py`：

```python
"""把 ai-berkshire 的 skill md 转成 Agent Skills 规范（SKILL.md + frontmatter）工作区。"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

AI_BERKSHIRE = Path("/Users/weixi1/Documents/Study/ai-berkshire")
POC_SKILLS = ["investment-research", "financial-data"]


def extract_meta(md_text: str, slug: str) -> tuple[str, str]:
    """返回 (title, description)。title 取首个一级标题，description 取标题后首段非空文本。"""
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
        f'---\nname: {slug}\ndescription: "{desc_line}"\n---\n\n{md_text}',
        encoding="utf-8",
    )
    return out


def build_workspace(dest_root: Path, skills: list[str]) -> None:
    for slug in skills:
        convert_skill(AI_BERKSHIRE / "skills" / f"{slug}.md", dest_root)
    tools_dst = dest_root / "tools"
    tools_dst.mkdir(parents=True, exist_ok=True)
    for py in (AI_BERKSHIRE / "tools").glob("*.py"):
        shutil.copy(py, tools_dst / py.name)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2] / "workspace"
    build_workspace(root, POC_SKILLS)
    print(f"workspace ready: {root}")
```

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_convert_skills.py -v`
Expected: 2 passed

- [ ] **Step 5: 生成真实工作区并抽查**

Run: `uv run python -m poc.convert_skills && head -5 workspace/skills/investment-research/SKILL.md && ls workspace/tools/ | head -3`
Expected: 打印 frontmatter（name: investment-research + 中文 description）；tools 下有 financial_rigor.py 等

- [ ] **Step 6: Commit（需用户已授权）**

```bash
git add poc/src/poc/convert_skills.py poc/tests/test_convert_skills.py
git commit -m "feat(poc): convert ai-berkshire skills to SKILL.md workspace"
```

---

### Task 3: Agent 自定义工具（搜索/抓取/行情/脚本执行）

**Files:**
- Create: `poc/src/poc/tools/__init__.py`、`poc/src/poc/tools/web.py`、`poc/src/poc/tools/stock.py`、`poc/src/poc/tools/runner.py`
- Test: `poc/tests/test_tools.py`

**Interfaces:**
- Consumes: Task 2 生成的 `poc/workspace/`（runner 的执行根目录）
- Produces: 5 个 LangChain `@tool`，供 Task 4 注入 agent：
  - `web_search(query: str, count: int = 8) -> str`
  - `fetch_page(url: str) -> str`
  - `stock_quote(symbol: str) -> str`（A 股 6 位代码）
  - `stock_financials(symbol: str) -> str`
  - `run_python(script: str, args: str = "") -> str`（workspace 内白名单脚本）

- [ ] **Step 1: 写失败测试**

`poc/tests/test_tools.py`：

```python
import httpx
import respx

from poc.tools.runner import run_python
from poc.tools.web import BOCHA_ENDPOINT, fetch_page, web_search


@respx.mock
def test_web_search_formats_results(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    respx.post(BOCHA_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "webPages": {
                        "value": [
                            {"name": "茅台财报", "url": "https://x.com/1", "summary": "净利润增长"}
                        ]
                    }
                }
            },
        )
    )
    out = web_search.invoke({"query": "贵州茅台 财报"})
    assert "茅台财报" in out and "https://x.com/1" in out and "净利润增长" in out


@respx.mock
def test_fetch_page_extracts_text():
    respx.get("https://example.com/a").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><article><p>贵州茅台2025年营收创新高，同比增长15%。</p></article></body></html>",
        )
    )
    out = fetch_page.invoke({"url": "https://example.com/a"})
    assert "贵州茅台" in out


def test_run_python_rejects_escape():
    out = run_python.invoke({"script": "../../etc/passwd"})
    assert out.startswith("错误")


def test_run_python_executes_workspace_script(tmp_path, monkeypatch):
    import poc.tools.runner as runner

    monkeypatch.setattr(runner, "WORKSPACE", tmp_path)
    (tmp_path / "hello.py").write_text("print('hi from tool')", encoding="utf-8")
    out = run_python.invoke({"script": "hello.py"})
    assert "exit=0" in out and "hi from tool" in out
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL（ModuleNotFoundError: poc.tools）

- [ ] **Step 3: 实现三个模块**

`poc/src/poc/tools/__init__.py`：空文件。

`poc/src/poc/tools/web.py`：

```python
import os

import httpx
import trafilatura
from langchain_core.tools import tool

BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"


@tool
def web_search(query: str, count: int = 8) -> str:
    """联网搜索，返回标题/链接/摘要。用于收集新闻、研报、财务数据线索、多空观点。"""
    resp = httpx.post(
        BOCHA_ENDPOINT,
        headers={"Authorization": f"Bearer {os.environ['BOCHA_API_KEY']}"},
        json={"query": query, "count": count, "summary": True},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("data", {}).get("webPages", {}).get("value", [])
    if not items:
        return "（无搜索结果）"
    return "\n".join(
        f"- {it.get('name')}\n  {it.get('url')}\n  {it.get('summary') or it.get('snippet', '')}"
        for it in items
    )


@tool
def fetch_page(url: str) -> str:
    """抓取网页并提取正文文本（截断到 8000 字符）。用于阅读搜索结果的原文。"""
    resp = httpx.get(
        url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
    text = trafilatura.extract(resp.text) or ""
    return text[:8000] or "（未能提取正文）"
```

`poc/src/poc/tools/stock.py`：

```python
from langchain_core.tools import tool


@tool
def stock_quote(symbol: str) -> str:
    """查询 A 股公司概况与实时行情。symbol 为 6 位代码，如 600519。"""
    import akshare as ak

    df = ak.stock_individual_info_em(symbol=symbol)
    return df.to_string(index=False)


@tool
def stock_financials(symbol: str) -> str:
    """查询 A 股主要财务指标（近年）。symbol 为 6 位代码，如 600519。"""
    import akshare as ak

    df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2020")
    return df.tail(12).to_string(index=False)
```

`poc/src/poc/tools/runner.py`：

```python
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

WORKSPACE = Path(__file__).resolve().parents[3] / "workspace"


@tool
def run_python(script: str, args: str = "") -> str:
    """执行 workspace 内的白名单 Python 脚本（如 tools/financial_rigor.py）。args 为空格分隔参数。"""
    script_path = (WORKSPACE / script).resolve()
    if not script_path.is_relative_to(WORKSPACE.resolve()) or script_path.suffix != ".py":
        return "错误：只能执行 workspace 内的 .py 脚本"
    if not script_path.exists():
        return f"错误：脚本不存在 {script}"
    proc = subprocess.run(
        [sys.executable, str(script_path), *args.split()],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=WORKSPACE,
    )
    return f"exit={proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-2000:]}"
```

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_tools.py -v`
Expected: 4 passed

- [ ] **Step 5: 真实 API 冒烟（需要 .env 已配置；akshare 需外网）**

Run: `uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from poc.tools.web import web_search
from poc.tools.stock import stock_quote
print(web_search.invoke({'query': '贵州茅台 2025 年报', 'count': 3})[:300])
print(stock_quote.invoke({'symbol': '600519'})[:300])
"`
Expected: 两段真实数据输出。若博查响应结构与 mock 不符，以真实响应为准修正 `web.py` 的解析路径和测试 fixture。

- [ ] **Step 6: Commit（需用户已授权）**

```bash
git add poc/src/poc/tools/ poc/tests/test_tools.py
git commit -m "feat(poc): add web/stock/runner tools for agent"
```

---

### Task 4: Agent 组装与 CLI 运行器

**Files:**
- Create: `poc/src/poc/agent.py`、`poc/src/poc/run.py`
- Test: `poc/tests/test_agent.py`

**Interfaces:**
- Consumes: Task 2 `poc/workspace/`（skills 目录）、Task 3 五个工具
- Produces:
  - `build_agent(model_name: str | None = None)` 返回可 `.stream()`/`.invoke()` 的 deepagents 实例
  - CLI：`uv run python -m poc.run "问题"` 流式打印工具调用与回答

- [ ] **Step 1: 写失败测试**

`poc/tests/test_agent.py`：

```python
import os

from poc.agent import SYSTEM_PROMPT, build_agent


def test_build_agent_compiles(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")
    agent = build_agent()
    assert hasattr(agent, "stream") and hasattr(agent, "invoke")


def test_system_prompt_has_guardrails():
    assert "工具" in SYSTEM_PROMPT  # 必须实际调用工具
    assert "来源" in SYSTEM_PROMPT  # 数字给来源
    assert "编造" in SYSTEM_PROMPT  # 禁止编造
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_agent.py -v`
Expected: FAIL（ModuleNotFoundError: poc.agent）

- [ ] **Step 3: 实现**

`poc/src/poc/agent.py`：

```python
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from poc.tools.runner import run_python
from poc.tools.stock import stock_financials, stock_quote
from poc.tools.web import fetch_page, web_search

WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"

SYSTEM_PROMPT = """你是 D-sight 投研助手，服务中文投资者。

硬性规则：
1. 涉及行情、财务、新闻的事实，必须实际调用工具获取，禁止凭记忆编造数字。
2. 报告中的关键数字必须注明来源（工具名或 URL）。
3. 任务匹配某个 skill 描述时，先读入该 skill 的 SKILL.md 并严格按其步骤执行；\
skill 指定的交叉验证步骤（如 tools/financial_rigor.py）必须用 run_python 真实执行。
4. 简单概念问答（不涉及具体标的的实时数据）直接回答，不要启动重型研究流程。
5. 信息不足或数据不存在时（如未发布的财报），明确说明，不得编造。
"""


def build_agent(model_name: str | None = None):
    load_dotenv()
    model = ChatDeepSeek(
        model=model_name or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        timeout=120,
        max_retries=3,
    )
    backend = FilesystemBackend(root_dir=str(WORKSPACE))
    return create_deep_agent(
        model=model,
        tools=[web_search, fetch_page, stock_quote, stock_financials, run_python],
        backend=backend,
        skills=[str(WORKSPACE / "skills")],
        system_prompt=SYSTEM_PROMPT,
    )
```

注意：若 `create_deep_agent` 报参数错误（版本差异），按 Task 1 Step 4 记录的真实签名调整（常见差异：`system_prompt` 旧名 `instructions`；`skills` 需要 source 对象而非路径字符串）。调整后同步更新本测试。

`poc/src/poc/run.py`：

```python
import sys

from rich.console import Console

from poc.agent import build_agent

console = Console()


def render(msg) -> None:
    for tc in getattr(msg, "tool_calls", None) or []:
        console.print(f"[cyan]→ 工具 {tc['name']}[/cyan] [dim]{str(tc['args'])[:200]}[/dim]")
    content = getattr(msg, "content", "")
    if isinstance(content, str) and content.strip():
        console.print(content)


def main() -> None:
    question = " ".join(sys.argv[1:]) or "分析贵州茅台（600519）的投资价值"
    console.print(f"[bold]问题：{question}[/bold]\n")
    agent = build_agent()
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": 200},
        stream_mode="updates",
    ):
        for _node, update in chunk.items():
            if isinstance(update, dict):
                for msg in update.get("messages", []):
                    render(msg)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_agent.py -v`
Expected: 2 passed

- [ ] **Step 5: 端到端冒烟（真实 LLM，产生费用，约 1-5 分钟）**

Run: `uv run python -m poc.run "茅台现在股价多少？"`
Expected: 能看到 `→ 工具 stock_quote` 调用及带真实价格的回答。若整轮无任何工具调用直接编数字，记为发现项（评估阶段重点观察）。

- [ ] **Step 6: Commit（需用户已授权）**

```bash
git add poc/src/poc/agent.py poc/src/poc/run.py poc/tests/test_agent.py
git commit -m "feat(poc): assemble deep agent with CLI streaming runner"
```

---

### Task 5: 评估集、打分与 go/no-go 报告

**Files:**
- Create: `poc/eval/questions.md`、`poc/eval/results-2026-07-06.md`

**Interfaces:**
- Consumes: Task 4 的 CLI
- Produces: 验收结论（go / no-go + 证据），写入 results 文件，决定骨架计划是否启用降级预案

- [ ] **Step 1: 写评估集**

`poc/eval/questions.md`：

```markdown
# PoC 评估集（10 题）

打分维度（每题 0-2 分，满分 8）：
- T 工具服从性：事实类数字全部来自工具调用（2=全部，1=部分，0=编造）
- S skill 服从性：正确触发/不触发 skill，按 SKILL.md 步骤执行（含 financial_rigor 交叉验证）
- D 数据质量：关键数字有来源标注，多源交叉一致
- Q 输出质量：结构完整、结论明确、有反面检验

一票否决项：出现严重幻觉（编造不存在的财报/数字且无来源）→ 该题记 0 并标记 ⛔

## 重型研究题（应触发 investment-research）
1. 分析贵州茅台（600519）的投资价值 —— A 级信息充裕
2. 分析宁德时代（300750）
3. 分析老铺黄金（6181.HK）—— B 级，上市时间短
4. 分析英伟达（NVDA，美股）
5. 分析锦波生物（832982，北交所）—— C 级冷门，考察第一性原理降级
6. 帮我看下拼多多值得买吗 —— 口语化触发

## 行为边界题
7. 什么是护城河？—— 应直答，不得启动重型流程
8. 对比腾讯和阿里的投资价值 —— 多标的处理
9. 茅台现在股价多少？—— 应只调行情工具秒回
10. 分析特斯拉 2026 年 Q3 财报 —— 财报未发布，应说明而非编造

## Go/No-Go 标准
- Go：题 1-6 平均 ≥ 6/8，且题 7/9/10 行为正确，且无 ⛔
- 边缘（5~6 分）：先做 prompt 调优 + 换 v4-flash 对照，复测一次再判
- No-Go：任何 ⛔，或平均 < 5 → 骨架计划启用降级预案（重型 skill 固定 LangGraph 图编排）
```

- [ ] **Step 2: 执行评估（真实 LLM，每题记录）**

对每题运行：`uv run python -m poc.run "<题目>" 2>&1 | tee eval/logs/q<N>.log`（先 `mkdir -p eval/logs`；`eval/logs/` 加入 poc/.gitignore）。
重型题每题约 3-15 分钟。至少完成题 1、3、5、7、9、10（覆盖 A/B/C 级 + 三道边界题）；时间允许则跑满 10 题。

- [ ] **Step 3: 填写结果报告**

`poc/eval/results-2026-07-06.md`（骨架，逐题填写实际观察）：

```markdown
# PoC 验收报告

- 日期：
- deepagents 版本：  langchain-deepseek 版本：  模型：
- 执行题目数：

| 题 | T | S | D | Q | 合计 | ⛔ | 备注（关键证据，引 log 行） |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |

## 主要发现
（工具调用服从性如何、skill 渐进披露是否触发、financial_rigor 是否被真实执行、幻觉案例）

## 结论：GO / 边缘复测 / NO-GO
（依据 questions.md 的标准，写明数字）

## 对骨架计划的输入
（如：需固定图降级 / prompt 修改点 / 工具缺口 / flash 与 pro 的分工建议）
```

- [ ] **Step 4: Commit（需用户已授权）**

```bash
git add poc/eval/
git commit -m "test(poc): evaluation set and go/no-go report"
```

---

## Self-Review 记录

- **Spec 覆盖**：本计划按既定拆分只覆盖 spec §4.6/§10-1（PoC）。§4.6 要求的三项验证点（工具调用服从性、步骤完整性、数据交叉验证）分别由评估维度 T/S/D 承接；降级判据已写成可操作的 Go/No-Go 标准。✅
- **占位符扫描**：无 TBD/TODO；deepagents API 签名差异不是占位符而是显式的验证-调整步骤（Task 1 Step 4 + Task 4 Step 3 注意事项）。✅
- **类型一致性**：`build_workspace`/`convert_skill`/五个工具/`build_agent` 的签名在 Interfaces 与代码块中一致；`WORKSPACE` 在 runner.py（parents[3]）与 agent.py（parents[2]）路径深度不同但都指向 `poc/workspace`（runner 在 tools/ 子包内多一层）。✅
