"""CLI — ontorag-memory 명령줄 인터페이스."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="ontorag-memory", help="AI 에이전트 온톨로지 메모리 관리.")
console = Console()


def _run(coro):
    return asyncio.run(coro)


# ── status ────────────────────────────────────────────────────────────────────

@app.command()
def status() -> None:
    """현재 identity와 메모리 현황을 출력합니다."""
    from ontorag_memory.client import MemoryClient

    async def _inner():
        async with await MemoryClient.create() as mem:
            st = await mem.stats()
            console.print(f"\n[bold]Identity[/bold]")
            console.print(f"  user:       {mem.identity.user}")
            console.print(f"  workspace:  {mem.identity.workspace}")
            console.print(f"  session_id: {mem.identity.session_id}")
            console.print(f"  graph:      {mem.identity.graph_uri}")
            console.print(f"\n[bold]Memory Stats[/bold]")
            console.print(f"  subjects:   {st['subjects']}")
            console.print(f"  triples:    {st['triples']}")
            console.print(f"  oldest:     {st.get('oldest', '—')}")
            console.print(f"  newest:     {st.get('newest', '—')}\n")

    _run(_inner())


# ── prune ─────────────────────────────────────────────────────────────────────

@app.command()
def prune(
    months: Annotated[int,  typer.Option("--months", "-m", help="이 개월 수 이상 된 노드 삭제.")] = 6,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="삭제 없이 대상 수량만 확인.")] = False,
) -> None:
    """N개월 이상 된 메모리 노드를 삭제합니다."""
    from ontorag_memory.client import MemoryClient

    async def _inner():
        async with await MemoryClient.create() as mem:
            result = await mem.prune(months, dry_run=dry_run)
            action = "[yellow]dry-run[/yellow]" if dry_run else "[red]삭제됨[/red]"
            console.print(
                f"\n{action}: {result['subjects']}개 subject, "
                f"{result['triples']}개 트리플 (기준: {months}개월 이상)\n"
            )

    _run(_inner())


# ── cleanup ───────────────────────────────────────────────────────────────────

cleanup_app = typer.Typer(help="워크스페이스 또는 프로젝트 메모리 삭제.")
app.add_typer(cleanup_app, name="cleanup")


@cleanup_app.command("workspace")
def cleanup_workspace(
    confirm: Annotated[bool, typer.Option("--confirm", help="실제 삭제 확인.")] = False,
) -> None:
    """현재 워크스페이스 메모리 전체를 삭제합니다."""
    from ontorag_memory.client import MemoryClient

    async def _inner():
        async with await MemoryClient.create() as mem:
            if not confirm:
                console.print(
                    f"\n[yellow]주의[/yellow]: {mem.identity.graph_uri} 전체를 삭제합니다.\n"
                    "[bold]--confirm[/bold] 플래그를 추가해야 실제 삭제됩니다.\n"
                )
                return
            result = await mem.cleanup_workspace(confirm=True)
            console.print(
                f"\n[red]삭제됨[/red]: {result['graph']} "
                f"({result.get('triples_removed', 0)}개 트리플)\n"
            )

    _run(_inner())


@cleanup_app.command("project")
def cleanup_project(
    project: Annotated[str,  typer.Argument(help="프로젝트 이름 또는 URI.")],
    confirm: Annotated[bool, typer.Option("--confirm", help="실제 삭제 확인.")] = False,
) -> None:
    """특정 프로젝트와 직접 연결된 트리플을 삭제합니다."""
    from ontorag_memory.client import MemoryClient

    async def _inner():
        async with await MemoryClient.create() as mem:
            result = await mem.cleanup_project(project, confirm=confirm)
            if not confirm:
                console.print(
                    f"\n[yellow]예정[/yellow]: '{project}' 관련 "
                    f"{result['triples_to_delete']}개 트리플\n"
                    "[bold]--confirm[/bold] 플래그를 추가해야 실제 삭제됩니다.\n"
                )
            else:
                console.print(
                    f"\n[red]삭제됨[/red]: '{project}' 관련 "
                    f"{result.get('triples_deleted', 0)}개 트리플\n"
                )

    _run(_inner())


# ── dump ─────────────────────────────────────────────────────────────────────

@app.command()
def dump(
    fmt: Annotated[str,  typer.Option("--format", "-f", help="출력 포맷 (turtle|jsonld|ntriples).")] = "turtle",
    output: Annotated[str | None, typer.Option("--output", "-o", help="저장 파일 경로.")] = None,
    session_only: Annotated[bool, typer.Option("--session-only", help="현재 세션 트리플만.")] = False,
) -> None:
    """메모리를 파일로 내보냅니다."""
    from ontorag_memory.client import MemoryClient

    async def _inner():
        async with await MemoryClient.create() as mem:
            path = await mem.dump(fmt, output, session_only=session_only)
            console.print(f"\n[green]저장됨[/green]: {path}\n")

    _run(_inner())


# ── setup ─────────────────────────────────────────────────────────────────────

@app.command()
def setup(
    agent: Annotated[str, typer.Option("--agent", "-a", help="에이전트 종류 (hermes|claude-code).")] = "claude-code",
) -> None:
    """에이전트 MCP 설정을 자동으로 구성합니다."""
    import shutil
    from pathlib import Path

    from ontorag_memory.identity import AgentIdentity

    identity = AgentIdentity.auto_detect()
    ontorag_mcp_path = shutil.which("ontorag-mcp")

    if agent == "hermes":
        config_path = Path.home() / ".hermes" / "config.yaml"
        snippet = f"""
# ontorag-memory: ontorag 지식 그래프
mcp_servers:
  ontorag:
    command: "{ontorag_mcp_path or 'ontorag-mcp'}"
    env:
      GRAPH_STORE: fuseki
      FUSEKI_URL: "http://localhost:3030"
      ONTORAG_USER: "{identity.user}"
      ONTORAG_WORKSPACE: "{identity.workspace}"
"""
        console.print(f"\n[bold]Hermes 설정[/bold] ({config_path}에 추가):")
        console.print(snippet)

    elif agent == "claude-code":
        config_path = Path.home() / ".claude" / "claude_desktop_config.json"
        snippet = {
            "mcpServers": {
                "ontorag": {
                    "command": ontorag_mcp_path or "ontorag-mcp",
                    "env": {
                        "GRAPH_STORE": "fuseki",
                        "FUSEKI_URL":  "http://localhost:3030",
                        "ONTORAG_USER": identity.user,
                        "ONTORAG_WORKSPACE": identity.workspace,
                    }
                }
            }
        }
        console.print(f"\n[bold]Claude Code 설정[/bold] ({config_path}에 추가):")
        console.print(json.dumps(snippet, ensure_ascii=False, indent=2))

    console.print(
        f"\n[dim]identity: {identity}[/dim]\n"
        "[dim]위 설정을 해당 파일에 병합 후 에이전트를 재시작하세요.[/dim]\n"
    )


if __name__ == "__main__":
    app()
