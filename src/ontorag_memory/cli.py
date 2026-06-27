"""CLI — ontorag-memory 명령줄 인터페이스."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ontorag_memory.client import MemoryClient
from ontorag_memory.identity import AgentIdentity

app = typer.Typer(name="ontorag-memory", help="AI 에이전트 온톨로지 메모리 관리.")
console = Console()


def _run(coro):
    return asyncio.run(coro)


# ── status ────────────────────────────────────────────────────────────────────

@app.command()
def status() -> None:
    """현재 identity와 메모리 현황을 출력합니다."""

    async def _inner():
        async with await MemoryClient.create() as mem:
            st = await mem.stats()
            console.print("\n[bold]Identity[/bold]")
            console.print(f"  user:       {mem.identity.user}")
            console.print(f"  workspace:  {mem.identity.workspace}")
            console.print(f"  session_id: {mem.identity.session_id}")
            console.print(f"  graph:      {mem.identity.graph_uri}")
            console.print("\n[bold]Memory Stats[/bold]")
            console.print(f"  subjects:   {st['subjects']}")
            console.print(f"  triples:    {st['triples']}")
            console.print(f"  oldest:     {st.get('oldest', '—')}")
            console.print(f"  newest:     {st.get('newest', '—')}\n")

    _run(_inner())


# ── prune ─────────────────────────────────────────────────────────────────────

@app.command()
def prune(
    months: Annotated[
        int, typer.Option("--months", "-m", help="이 개월 수 이상 된 노드 삭제.")
    ] = 6,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="삭제 없이 대상 수량만 확인.")
    ] = False,
) -> None:
    """N개월 이상 된 메모리 노드를 삭제합니다."""

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
    project: Annotated[str, typer.Argument(help="프로젝트 이름 또는 URI.")],
    confirm: Annotated[bool, typer.Option("--confirm", help="실제 삭제 확인.")] = False,
) -> None:
    """특정 프로젝트와 직접 연결된 트리플을 삭제합니다."""

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
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="출력 포맷 (turtle|jsonld|ntriples).")
    ] = "turtle",
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="저장 파일 경로.")
    ] = None,
    session_only: Annotated[
        bool, typer.Option("--session-only", help="현재 세션 트리플만.")
    ] = False,
) -> None:
    """메모리를 파일로 내보냅니다."""

    async def _inner():
        async with await MemoryClient.create() as mem:
            path = await mem.dump(fmt, output, session_only=session_only)
            console.print(f"\n[green]저장됨[/green]: {path}\n")

    _run(_inner())


# ── setup ─────────────────────────────────────────────────────────────────────

@app.command()
def setup(
    agent: Annotated[
        str,
        typer.Option("--agent", "-a", help="에이전트 종류 (hermes|claude-code)."),
    ] = "claude-code",
) -> None:
    """에이전트 MCP 설정을 자동으로 구성합니다."""
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
                        "FUSEKI_URL": "http://localhost:3030",
                        "ONTORAG_USER": identity.user,
                        "ONTORAG_WORKSPACE": identity.workspace,
                    },
                }
            }
        }
        console.print(f"\n[bold]Claude Code 설정[/bold] ({config_path}에 추가):")
        console.print(json.dumps(snippet, ensure_ascii=False, indent=2))

    console.print(
        f"\n[dim]identity: {identity}[/dim]\n"
        "[dim]위 설정을 해당 파일에 병합 후 에이전트를 재시작하세요.[/dim]\n"
    )


# ── why ───────────────────────────────────────────────────────────────────────

@app.command()
def why(
    entity: Annotated[str, typer.Argument(help="엔티티 이름 또는 URI.")],
) -> None:
    """엔티티가 왜 존재하는지 — 근거·결정 맥락을 출력합니다."""

    async def _inner() -> None:
        async with await MemoryClient.create() as mem:
            result = await mem.why(entity)
            console.print(result.to_context_str())

    _run(_inner())


# ── graph-stats ───────────────────────────────────────────────────────────────

@app.command(name="graph-stats")
def graph_stats(
    hub_limit: Annotated[
        int, typer.Option("--hubs", "-n", help="허브 노드 상위 N개.")
    ] = 10,
) -> None:
    """그래프 구조 건강도 통계를 출력합니다."""

    async def _inner() -> None:
        async with await MemoryClient.create() as mem:
            stats = await mem.graph_stats(hub_limit=hub_limit)

            console.print(f"\n[bold]Graph Stats[/bold]  {stats.graph}")
            console.print(
                f"  nodes: {stats.subjects}  triples: {stats.triples}  "
                f"predicates: {stats.predicates}  avg_degree: {stats.avg_degree}"
            )

            if stats.hub_nodes:
                table = Table(title="핵심 허브 노드 (degree 상위)", show_lines=False)
                table.add_column("URI", style="cyan")
                table.add_column("degree", justify="right", style="bold")
                for hub in stats.hub_nodes:
                    table.add_row(hub.uri, str(hub.degree))
                console.print(table)

            if stats.predicate_distribution:
                table = Table(title="술어 사용 빈도 (상위)", show_lines=False)
                table.add_column("predicate", style="cyan")
                table.add_column("count", justify="right")
                for pc in stats.predicate_distribution:
                    table.add_row(pc.predicate, str(pc.count))
                console.print(table)

            if stats.isolated_nodes:
                console.print(
                    f"\n[yellow]역방향 참조 없는 노드[/yellow] "
                    f"({len(stats.isolated_nodes)}개):"
                )
                for uri in stats.isolated_nodes[:10]:
                    console.print(f"  {uri}")
                if len(stats.isolated_nodes) > 10:
                    console.print(f"  … 외 {len(stats.isolated_nodes) - 10}개\n")

    _run(_inner())


# ── diary ─────────────────────────────────────────────────────────────────────

diary_app = typer.Typer(help="에이전트 다이어리 — 자유형식 메모 관리.")
app.add_typer(diary_app, name="diary")


@diary_app.command("write")
def diary_write(
    content: Annotated[str, typer.Argument(help="메모 내용.")],
    tags: Annotated[
        list[str] | None, typer.Option("--tag", "-t", help="태그 (여러 번 사용 가능).")
    ] = None,
) -> None:
    """다이어리에 메모를 기록합니다."""

    async def _inner() -> None:
        async with await MemoryClient.create() as mem:
            uri = await mem.diary_write(content, tags=tags or None)
            console.print(f"\n[green]기록됨[/green]: {uri}\n")

    _run(_inner())


@diary_app.command("list")
def diary_list(
    limit: Annotated[int, typer.Option("--limit", "-n", help="최대 항목 수.")] = 20,
    since_days: Annotated[
        int | None, typer.Option("--since", "-d", help="최근 N일 이내.")
    ] = None,
) -> None:
    """최근 다이어리 항목을 출력합니다."""

    async def _inner() -> None:
        async with await MemoryClient.create() as mem:
            entries = await mem.diary_read(limit=limit, since_days=since_days)
            if not entries:
                console.print("\n[dim]다이어리 항목이 없습니다.[/dim]\n")
                return
            console.print(f"\n[bold]다이어리[/bold] ({len(entries)}개)\n")
            for entry in entries:
                console.print(entry.to_context_str())
            console.print()

    _run(_inner())


if __name__ == "__main__":
    app()
