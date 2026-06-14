"""Integration tests — requires live Fuseki (localhost:3030).

실행:
    uv run pytest tests/test_integration.py -m integration --no-cov

각 테스트는 전용 AgentIdentity(user=test, workspace=itXXXX)를 사용해
기존 데이터와 충돌하지 않으며, teardown에서 해당 workspace graph를 삭제합니다.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from ontorag_memory.client import MemoryClient
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.registry import P

os.environ.setdefault("FUSEKI_URL", "http://localhost:3030")
os.environ.setdefault("FUSEKI_DATASET", "ontorag")
os.environ.setdefault("FUSEKI_USER", "admin")
os.environ.setdefault("FUSEKI_PASSWORD", "admin")


# ── Fixture ───────────────────────────────────────────────────────────────────

def _test_identity(test_name: str) -> AgentIdentity:
    """테스트별 격리된 identity — teardown 시 그래프 삭제 가능."""
    return AgentIdentity(user="test", workspace=f"it-{test_name}", session_id="s0")


async def _ask(sparql: str) -> bool:
    """Fuseki에 ASK 쿼리를 날려 boolean 반환."""
    auth = httpx.BasicAuth(
        os.environ.get("FUSEKI_USER", "admin"),
        os.environ.get("FUSEKI_PASSWORD", "admin"),
    )
    url = (
        f"{os.environ.get('FUSEKI_URL', 'http://localhost:3030')}"
        f"/{os.environ.get('FUSEKI_DATASET', 'ontorag')}/sparql"
    )
    async with httpx.AsyncClient(auth=auth, timeout=10.0) as client:
        resp = await client.post(
            url, data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        return resp.json()["boolean"]


@pytest_asyncio.fixture
async def mem(request):
    """테스트용 MemoryClient — 종료 시 workspace graph 자동 삭제."""
    identity = _test_identity(request.node.name[:20].replace("[", "").replace("]", ""))
    client = await MemoryClient.create(identity=identity)
    yield client
    await client.cleanup_workspace(confirm=True)
    await client.aclose()


# ── remember / recall ─────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_remember_stores_triple(mem: MemoryClient) -> None:
    """remember() 호출 후 Fuseki에 트리플이 저장되는지 확인."""
    subj = mem.identity.entity_uri("proj", "ontorag")
    await mem.remember(subj, P.LABEL, "ontorag framework", object_is_uri=False)

    graph = mem.identity.graph_uri
    assert await _ask(
        f'ASK {{ GRAPH <{graph}> {{ <{subj}> <{P.LABEL}> "ontorag framework" . }} }}'
    )


@pytest.mark.integration
async def test_remember_attaches_metadata(mem: MemoryClient) -> None:
    """remember()가 assertedAt / inSession / workspace 메타를 자동 부착하는지 확인."""
    subj = mem.identity.entity_uri("decision", "test")
    await mem.remember(subj, P.LABEL, "test decision")

    graph = mem.identity.graph_uri
    for meta_pred in (P.ASSERTED_AT, P.IN_SESSION, P.WORKSPACE):
        assert await _ask(
            f"ASK {{ GRAPH <{graph}> {{ <{subj}> <{meta_pred}> ?v . }} }}"
        ), f"{meta_pred} 메타 없음"


@pytest.mark.integration
async def test_remember_many_batch(mem: MemoryClient) -> None:
    """remember_many()가 여러 트리플을 한 번에 저장하는지 확인."""
    s1 = mem.identity.entity_uri("proj", "a")
    s2 = mem.identity.entity_uri("proj", "b")
    count = await mem.remember_many([
        (s1, P.LABEL, "project a"),
        (s2, P.LABEL, "project b"),
        (s1, P.DEPENDS_ON, s2),
    ])
    assert count == 3

    graph = mem.identity.graph_uri
    assert await _ask(f'ASK {{ GRAPH <{graph}> {{ <{s1}> <{P.LABEL}> "project a" . }} }}')
    assert await _ask(f'ASK {{ GRAPH <{graph}> {{ <{s1}> <{P.DEPENDS_ON}> <{s2}> . }} }}')


@pytest.mark.integration
async def test_recall_returns_stored_facts(mem: MemoryClient) -> None:
    """recall()이 저장된 사실만 (메타 제외) 반환하는지 확인."""
    subj = mem.identity.entity_uri("tech", "mcp")
    await mem.remember_many([
        (subj, P.LABEL, "MCP"),
        (subj, P.DESCRIPTION, "Model Context Protocol"),
    ])

    facts = await mem.recall(subj)
    predicates = {f["predicate"] for f in facts}

    assert P.LABEL in predicates
    assert P.DESCRIPTION in predicates
    # 메타 predicate는 recall 결과에서 제외
    assert P.ASSERTED_AT not in predicates
    assert P.IN_SESSION not in predicates


# ── find_path ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_find_path_direct(mem: MemoryClient) -> None:
    """1홉 직접 연결 경로를 find_path()가 찾는지 확인."""
    a = mem.identity.entity_uri("proj", "ontorag")
    b = mem.identity.entity_uri("tech", "fuseki")
    await mem.remember_many([(a, P.USES, b, True)])

    path = await mem.find_path(a, b)
    assert len(path) == 1
    assert path[0]["from"] == a
    assert path[0]["to"] == b
    assert path[0]["predicate"] == P.USES


@pytest.mark.integration
async def test_find_path_two_hops(mem: MemoryClient) -> None:
    """2홉 경로를 find_path()가 발견하는지 확인."""
    hermes = mem.identity.entity_uri("agent", "hermes")
    sre    = mem.identity.entity_uri("concept", "sre")
    patent = mem.identity.entity_uri("proj", "patent-board")

    await mem.remember_many([
        (hermes, P.RELATED_TO, sre,    True),
        (sre,    P.INVOLVES,   patent, True),
    ])

    path = await mem.find_path(hermes, patent, max_depth=3)
    assert len(path) == 2
    assert path[0]["from"] == hermes
    assert path[-1]["to"] == patent


@pytest.mark.integration
async def test_find_path_no_connection_returns_empty(mem: MemoryClient) -> None:
    """연결이 없는 두 엔티티에서 find_path()가 빈 리스트를 반환하는지 확인."""
    a = mem.identity.entity_uri("proj", "isolated-a")
    b = mem.identity.entity_uri("proj", "isolated-b")
    await mem.remember(a, P.LABEL, "A")
    await mem.remember(b, P.LABEL, "B")

    path = await mem.find_path(a, b, max_depth=3)
    assert path == []


# ── stats ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_stats_reflects_stored_triples(mem: MemoryClient) -> None:
    """stats()가 저장된 트리플 수를 정확히 반영하는지 확인."""
    st_before = await mem.stats()
    before_count = st_before["triples"]

    subj = mem.identity.entity_uri("proj", "x")
    await mem.remember(subj, P.LABEL, "X")

    st_after = await mem.stats()
    # assertedAt + inSession + workspace + label = 4 트리플 추가
    assert st_after["triples"] >= before_count + 4


# ── prune ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_prune_dry_run_does_not_delete(mem: MemoryClient) -> None:
    """prune(dry_run=True)가 실제 삭제를 하지 않는지 확인."""
    subj = mem.identity.entity_uri("proj", "keep-me")
    await mem.remember(subj, P.LABEL, "keep me")

    result = await mem.prune(older_than_months=0, dry_run=True)
    assert result["dry_run"] is True

    graph = mem.identity.graph_uri
    assert await _ask(f'ASK {{ GRAPH <{graph}> {{ <{subj}> <{P.LABEL}> "keep me" . }} }}')


# ── cleanup_project ───────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_cleanup_project_removes_connected_triples(mem: MemoryClient) -> None:
    """cleanup_project()가 프로젝트 관련 트리플만 삭제하는지 확인."""
    proj   = mem.identity.entity_uri("proj", "to-delete")
    keeper = mem.identity.entity_uri("proj", "keeper")

    await mem.remember_many([
        (proj,   P.LABEL, "delete me"),
        (keeper, P.LABEL, "keep me"),
        (keeper, P.DEPENDS_ON, proj, True),
    ])

    result = await mem.cleanup_project(proj, confirm=True)
    assert result["deleted"] is True

    graph = mem.identity.graph_uri
    # proj 관련 트리플 삭제됨
    assert not await _ask(f'ASK {{ GRAPH <{graph}> {{ <{proj}> ?p ?o . }} }}')
    # keeper 자체 레이블은 남아있음
    assert await _ask(f'ASK {{ GRAPH <{graph}> {{ <{keeper}> <{P.LABEL}> "keep me" . }} }}')


# ── dump ──────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_dump_turtle_creates_file(mem: MemoryClient, tmp_path: Path) -> None:
    """dump(turtle)가 내용 있는 TTL 파일을 생성하는지 확인."""
    subj = mem.identity.entity_uri("proj", "dumped")
    await mem.remember(subj, P.LABEL, "dumped project")

    out = tmp_path / "memory.ttl"
    path = await mem.dump(fmt="turtle", output_path=str(out))

    assert Path(path).exists()
    content = Path(path).read_text()
    assert "dumped project" in content


@pytest.mark.integration
async def test_dump_session_only(mem: MemoryClient, tmp_path: Path) -> None:
    """dump(session_only=True)가 현재 세션 트리플만 내보내는지 확인."""
    subj = mem.identity.entity_uri("proj", "session-test")
    await mem.remember(subj, P.LABEL, "session label")

    out = tmp_path / "session.ttl"
    path = await mem.dump(fmt="turtle", output_path=str(out), session_only=True)

    content = Path(path).read_text()
    assert "session label" in content


# ── 격리 ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_different_workspaces_are_isolated() -> None:
    """다른 workspace의 메모리가 서로 보이지 않는지 확인."""
    id_a = AgentIdentity(user="test", workspace="it-iso-ws-a", session_id="s0")
    id_b = AgentIdentity(user="test", workspace="it-iso-ws-b", session_id="s0")

    mem_a = await MemoryClient.create(identity=id_a)
    mem_b = await MemoryClient.create(identity=id_b)

    subj = "urn:test:isolation:secret"
    await mem_a.remember(subj, P.LABEL, "only in A")

    # B에서는 보이지 않아야 함
    facts_b = await mem_b.recall(subj)
    assert facts_b == []

    # A에서는 보임
    facts_a = await mem_a.recall(subj)
    assert any(f["object"] == "only in A" for f in facts_a)

    await mem_a.cleanup_workspace(confirm=True)
    await mem_b.cleanup_workspace(confirm=True)
    await mem_a.aclose()
    await mem_b.aclose()
