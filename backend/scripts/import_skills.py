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


# PoC 输入#4 补丁的哨兵，用于幂等判定（build_assets 二次运行不重复插入）。
_PATCH_SENTINEL = "dsight-patch:results-file"


def patch_report_audit(tools_dir: Path) -> None:
    """PoC 输入#4：给拷贝后的 report_audit.py 增加 --results-file 顶层参数，直读报告文件。

    上游 report_audit.py 用 argparse 子命令（extract/verdict）组织；extract 通过
    `--report <path>` 定位并读取报告。这里做确定性文本改写：
      1. 在 `sub = parser.add_subparsers(...)` 前，向顶层 parser 追加 `--results-file`
         （因此出现在顶层 `--help` 中，满足验收 grep）。
      2. 在 `args = parser.parse_args()` 后插入一个分支：当 `--results-file` 提供时，
         将其作为报告内容路径复用既有 extract 输出逻辑（args.command='extract',
         args.report=results_file），从而"跳过子命令的报告定位逻辑、直接读取该文件"，
         且原有子命令/输出格式完全不变。
    以哨兵 `dsight-patch:results-file` 保证幂等：已打补丁则直接返回，不重复插入。
    仅改写我方拷贝，不触碰上游 repo。
    """
    audit = tools_dir / "report_audit.py"
    text = audit.read_text(encoding="utf-8")
    if _PATCH_SENTINEL in text:
        return  # 幂等：补丁已存在

    arg_anchor = "    sub = parser.add_subparsers(dest='command')"
    handler_anchor = "    args = parser.parse_args()"
    if arg_anchor not in text or handler_anchor not in text:
        raise RuntimeError("report_audit.py 结构与预期不符，补丁锚点缺失")

    arg_inject = (
        "    parser.add_argument(\n"
        "        '--results-file', default=None,\n"
        "        help='PoC 输入#4：直接读取该文件作为报告内容，跳过子命令的报告定位逻辑')\n\n"
        + arg_anchor
    )
    handler_inject = (
        handler_anchor
        + "\n\n"
        + f"    # >>> {_PATCH_SENTINEL} (PoC 输入#4，幂等) —— 提供 --results-file 时直读该文件作为报告内容\n"
        + "    if getattr(args, 'results_file', None):\n"
        + "        args.command = 'extract'\n"
        + "        args.report = args.results_file\n"
        + "        args.ratio = getattr(args, 'ratio', 0.15)\n"
        + "        args.seed = getattr(args, 'seed', None)\n"
        + "        args.dry_run = getattr(args, 'dry_run', False)\n"
        + f"    # <<< {_PATCH_SENTINEL}\n"
    )

    text = text.replace(arg_anchor, arg_inject, 1)
    text = text.replace(handler_anchor, handler_inject, 1)
    audit.write_text(text, encoding="utf-8")


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
