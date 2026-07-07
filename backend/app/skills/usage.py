import re

_SKILL_RE = re.compile(r"(?:^|/)skills/([^/]+)/SKILL\.md$")
_READ_TOOLS = {"read_file"}  # deepagents 0.6.12 文件读工具名（filesystem.py 实证）


def extract_used_skills(messages: list) -> set[str]:
    used: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("name") not in _READ_TOOLS:
                continue
            args = tc.get("args") or {}
            path = args.get("file_path") or args.get("path") or ""
            match = _SKILL_RE.search(str(path))
            if match:
                used.add(match.group(1))
    return used
