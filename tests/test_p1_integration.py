"""P1 기능 통합 테스트 — 실제 Fuseki 필요.

실행:
    uv run pytest tests/test_p1_integration.py -m integration --no-cov

각 테스트는 격리된 AgentIdentity를 사용해 기존 데이터와 충돌하지 않으며,
teardown에서 해당 workspace graph를 삭제합니다.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from ontorag_memory.client import MemoryClient
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.registry import P

os.environ.setdefault("FUSEKI_URL", "http://localhost:3030")
os.environ.setdefault("FUSEKI_DATASET", "ontorag")
os.environ.setdefault("FUSEKI_USER", "admin")
os.environ.setdefault("FUSEKI_PASSWORD", "admin")


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mem(request):
    """격리된 MemoryClient — teardown 시 workspace graph 삭제."""
    safe_name = request.node.name[:20].replace("[", "").replace("]", "")
    identity = AgentIdentity(user="test", workspace=f"p1-{safe_name}", session_id="s0")
    client = await MemoryClient.create(identity=identity)
    yield client
    await client.cleanup_workspace(confirm=True)
    await client.aclose()


# ── recall() — decay_score 필드 ───────────────────────────────────────────────

@pytest.mark.integration
async def test_recall_includes_decay_score_and_asserted_at(mem: MemoryClient) -> None:
    """recall() 결과에 decay_score와 asserted_at 필드가 포함됨."""
    subj = mem.identity.entity_uri("proj", "test-decay")
    await mem.remember(subj, P.LABEL, "decay test")

    facts = await mem.recall(subj)
    assert facts, "사실이 없음"

    first = facts[0]
    assert "decay_score" in first, "decay_score 필드 없음"
    assert "asserted_at" in first, "asserted_at 필드 없음"
    assert 0.0 < first["decay_score"] <= 1.0


@pytest.mark.integration
async def test_recall_sorted_by_recency(mem: MemoryClient) -> None:
    """sort_by_recency=True(기본값) 시 decay_score 내림차순 정렬."""
    subj = mem.identity.entity_uri("proj", "test-sort")
    await mem.remember_many([
        (subj, P.LABEL, "정렬 테스트"),
        (subj, P.DESCRIPTION, "설명"),
    ])

    facts = await mem.recall(subj, sort_by_recency=True)
    scores = [f["decay_score"] for f in facts]
    assert scores == sorted(scores, reverse=True)


# ── check_duplicate() ─────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_check_duplicate_false_before_remember(mem: MemoryClient) -> None:
    """remember() 전에는 check_duplicate()가 False."""
    subj = mem.identity.entity_uri("proj", "dup-test")
    result = await mem.check_duplicate(subj, P.LABEL, "my label")
    assert result is False


@pytest.mark.integration
async def test_check_duplicate_true_after_remember(mem: MemoryClient) -> None:
    """remember() 후에는 check_duplicate()가 True."""
    subj = mem.identity.entity_uri("proj", "dup-test")
    await mem.remember(subj, P.LABEL, "my label")

    result = await mem.check_duplicate(subj, P.LABEL, "my label")
    assert result is True


@pytest.mark.integration
async def test_check_duplicate_different_value_is_false(mem: MemoryClient) -> None:
    """같은 subject + predicate여도 다른 object → False."""
    subj = mem.identity.entity_uri("proj", "dup-test2")
    await mem.remember(subj, P.LABEL, "original label")

    result = await mem.check_duplicate(subj, P.LABEL, "different label")
    assert result is False


# ── remember(skip_if_exists=True) ─────────────────────────────────────────────

@pytest.mark.integration
async def test_remember_skip_if_exists_first_call_stores(mem: MemoryClient) -> None:
    """첫 번째 skip_if_exists=True 호출 → True 반환, Fuseki에 저장됨."""
    subj = mem.identity.entity_uri("proj", "skip-test")
    result = await mem.remember(subj, P.LABEL, "first insert", skip_if_exists=True)
    assert result is True

    facts = await mem.recall(subj)
    labels = [f["object"] for f in facts if f["predicate"] == P.LABEL]
    assert "first insert" in labels


@pytest.mark.integration
async def test_remember_skip_if_exists_second_call_skips(mem: MemoryClient) -> None:
    """두 번째 동일 트리플 호출 → False 반환 (저장 안 됨)."""
    subj = mem.identity.entity_uri("proj", "skip-test2")
    await mem.remember(subj, P.LABEL, "unique label", skip_if_exists=True)
    result2 = await mem.remember(subj, P.LABEL, "unique label", skip_if_exists=True)
    assert result2 is False


# ── diary_write() / diary_read() ──────────────────────────────────────────────

@pytest.mark.integration
async def test_diary_write_read_roundtrip(mem: MemoryClient) -> None:
    """diary_write() 후 diary_read()로 내용을 그대로 돌려받음."""
    content = "Fuseki GOSP 인덱스는 역방향 조회에 O(log N)"
    uri = await mem.diary_write(content)

    entries = await mem.diary_read(limit=10)
    uris = [e.uri for e in entries]
    assert uri in uris

    entry = next(e for e in entries if e.uri == uri)
    assert entry.content == content


@pytest.mark.integration
async def test_diary_read_tags_survive_roundtrip(mem: MemoryClient) -> None:
    """태그가 있는 다이어리 항목 — 태그가 diary_read()에서 복원됨."""
    tags = ["performance", "fuseki"]
    uri = await mem.diary_write("태그 있는 메모", tags=tags)

    entries = await mem.diary_read(limit=10)
    entry = next((e for e in entries if e.uri == uri), None)
    assert entry is not None
    assert sorted(entry.tags) == sorted(tags)


@pytest.mark.integration
async def test_diary_read_limit_respected(mem: MemoryClient) -> None:
    """limit 파라미터가 반환 개수를 제한함."""
    for i in range(5):
        await mem.diary_write(f"메모 {i}")

    entries = await mem.diary_read(limit=3)
    assert len(entries) <= 3


@pytest.mark.integration
async def test_diary_write_uri_is_ontology_node(mem: MemoryClient) -> None:
    """diary_write() URI가 urn:ag:diary: 접두사로 온톨로지에 통합됨."""
    uri = await mem.diary_write("온톨로지 통합 확인")
    assert uri.startswith("urn:ag:diary:")

    # recall_recent에서 diary 노드가 조회돼야 함
    recent = await mem.recall_recent(n=10)
    recent_uris = [r["uri"] for r in recent]
    assert uri in recent_uris


# ── why() ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_why_returns_rationale(mem: MemoryClient) -> None:
    """rationale 트리플 저장 후 why()가 rationale을 반환함."""
    decision = mem.identity.entity_uri("decision", "2026-01-01", "test-why")
    rationale_text = "성능이 더 좋기 때문"

    await mem.remember_many([
        (decision, P.RATIONALE, rationale_text),
        (decision, P.MADE_AT, "2026-01-01"),
    ])

    result = await mem.why(decision)
    assert rationale_text in result.rationale
    assert result.made_at == "2026-01-01"


@pytest.mark.integration
async def test_why_returns_decided_against(mem: MemoryClient) -> None:
    """decided_against 트리플 저장 후 why()에 포함됨."""
    decision = mem.identity.entity_uri("decision", "2026-01-01", "alt-why")
    await mem.remember(decision, P.DECIDED_AGAINST, "대안 X")

    result = await mem.why(decision)
    assert "대안 X" in result.decided_against


@pytest.mark.integration
async def test_why_returns_influenced_by(mem: MemoryClient) -> None:
    """다른 노드가 이 엔티티를 참조할 때 influenced_by에 역방향 연결이 포함됨."""
    target = mem.identity.entity_uri("proj", "influencee")
    influencer = mem.identity.entity_uri("proj", "influencer")

    await mem.remember_many([
        (influencer, P.DEPENDS_ON, target, True),
    ])

    result = await mem.why(target)
    subjects = [i.subject for i in result.influenced_by]
    assert influencer in subjects


@pytest.mark.integration
async def test_why_empty_entity_returns_empty_result(mem: MemoryClient) -> None:
    """아무 트리플도 없는 엔티티 → 빈 WhyResult 반환 (예외 없음)."""
    unknown = mem.identity.entity_uri("proj", "ghost-entity")
    result = await mem.why(unknown)

    assert result.uri == unknown
    assert result.rationale == []
    assert result.decided_against == []
    assert result.influenced_by == []


# ── graph_stats() ─────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_graph_stats_nonzero_after_store(mem: MemoryClient) -> None:
    """트리플 저장 후 graph_stats()의 subjects / triples가 0보다 큼."""
    subj = mem.identity.entity_uri("proj", "stats-test")
    await mem.remember(subj, P.LABEL, "stats target")

    stats = await mem.graph_stats()
    assert stats.subjects > 0
    assert stats.triples > 0


@pytest.mark.integration
async def test_graph_stats_predicates_counted(mem: MemoryClient) -> None:
    """다른 술어로 트리플 저장 → predicates 수가 1 이상."""
    subj = mem.identity.entity_uri("proj", "pred-test")
    await mem.remember_many([
        (subj, P.LABEL, "레이블"),
        (subj, P.DESCRIPTION, "설명"),
    ])

    stats = await mem.graph_stats()
    assert stats.predicates >= 1


@pytest.mark.integration
async def test_graph_stats_hub_nodes_sorted_by_degree(mem: MemoryClient) -> None:
    """hub_nodes가 degree 내림차순 정렬됨."""
    hub = mem.identity.entity_uri("proj", "hub-node")
    for i in range(3):
        leaf = mem.identity.entity_uri("proj", f"leaf-{i}")
        await mem.remember(leaf, P.DEPENDS_ON, hub, object_is_uri=True)

    stats = await mem.graph_stats(hub_limit=5)
    if len(stats.hub_nodes) >= 2:
        degrees = [h.degree for h in stats.hub_nodes]
        assert degrees == sorted(degrees, reverse=True)


@pytest.mark.integration
async def test_graph_stats_returns_graph_uri(mem: MemoryClient) -> None:
    """반환된 GraphStats의 graph 필드가 현재 identity의 graph_uri와 일치."""
    subj = mem.identity.entity_uri("proj", "graph-uri-test")
    await mem.remember(subj, P.LABEL, "그래프 URI 확인")

    stats = await mem.graph_stats()
    assert stats.graph == mem.identity.graph_uri
