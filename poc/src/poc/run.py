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
    try:
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
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"[bold red]运行失败（{type(exc).__name__}: {exc}）[/bold red]"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
