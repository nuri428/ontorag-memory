"""P3(=계획상 P2) — find_path_transitive / summarize / remember_bulk 유닛 테스트.

Fuseki 없이 실행.

실행:
    uv run pytest tests/test_p3_transitive.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ontorag_memory.client import MemoryClient
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.registry import P
from ontorag_memory.why_result import WhyResult


class _MockStore:
    async def assert_triples(self, triples: list, *, ontology: str) -> None:
        pass

    async def aclose(self) -> None:
        pass


def _make_client() -> MemoryClient:
    store = _MockStore()
    identity = AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789")
    return MemoryClient(store, identity=identity)


# ── find_path_transitive ──────────────────────────────────────────────────────

async def test_find_path_transitive_query_uses_property_path():
    """SPARQL 쿼리에 `+` property path가 포함됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON)

    assert "+" in captured[0]
    assert P.DEPENDS_ON in captured[0]
    assert "urn:ag:proj:x" in captured[0]


async def test_find_path_transitive_out_direction():
    """direction='out': entity가 subject 위치."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON, direction="out")

    q = captured[0]
    # entity가 술어 앞에 위치
    entity_pos = q.index("urn:ag:proj:x")
    pred_pos = q.index(P.DEPENDS_ON)
    assert entity_pos < pred_pos


async def test_find_path_transitive_in_direction():
    """direction='in': entity가 object 위치."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON, direction="in")

    q = captured[0]
    # entity가 술어 뒤에 위치
    entity_pos = q.index("urn:ag:proj:x")
    pred_pos = q.index(P.DEPENDS_ON)
    assert entity_pos > pred_pos


async def test_find_path_transitive_returns_uri_list():
    """반환값은 URI 문자열 리스트."""
    mem = _make_client()
    fake_rows = [
        {"node": {"value": "urn:ag:proj:a"}},
        {"node": {"value": "urn:ag:proj:b"}},
    ]
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=fake_rows)):
        result = await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON)

    assert result == ["urn:ag:proj:a", "urn:ag:proj:b"]


async def test_find_path_transitive_applies_limit():
    """SPARQL 쿼리에 LIMIT이 설정됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON, limit=5)

    assert "LIMIT 5" in captured[0]


async def test_find_path_transitive_rejects_invalid_direction():
    """direction='both' 등 허용되지 않는 방향 — ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError, match="direction은"):
        await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON, direction="both")


async def test_find_path_transitive_rejects_invalid_limit():
    mem = _make_client()
    with pytest.raises(ValueError, match="limit은"):
        await mem.find_path_transitive("urn:ag:proj:x", P.DEPENDS_ON, limit=0)


async def test_find_path_transitive_unsafe_predicate():
    """위험 문자 포함 predicate → ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError):
        await mem.find_path_transitive(
            "urn:ag:proj:x",
            "urn:ag:rel:dep> . } # injection",
        )


async def test_find_path_transitive_resolves_entity_name():
    """_resolve() 결과가 SPARQL 쿼리에 삽입됨 (레지스트리 독립적)."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    resolved_uri = "urn:ag:proj:stubbed-entity"
    with (
        patch.object(mem, "_resolve", return_value=resolved_uri),
        patch.object(mem._lc, "_sparql_select", new=capture),
    ):
        await mem.find_path_transitive("any short name", P.DEPENDS_ON)

    assert resolved_uri in captured[0]


# ── summarize ─────────────────────────────────────────────────────────────────

async def test_summarize_combines_why_and_recall():
    """summarize 결과에 why()의 # Why 헤더가 포함됨."""
    mem = _make_client()
    why_result = WhyResult(uri="urn:ag:proj:x", rationale=["테스트 근거"])
    fake_recall = [
        {
            "predicate": "urn:ag:rel:rationale",
            "object": "테스트 근거",
            "object_is_uri": False,
            "asserted_at": "2026-01-01",
            "decay_score": 1.0,
        }
    ]
    with (
        patch.object(mem, "why", new=AsyncMock(return_value=why_result)),
        patch.object(mem, "recall", new=AsyncMock(return_value=fake_recall)),
    ):
        result = await mem.summarize("urn:ag:proj:x")

    assert "# Why: urn:ag:proj:x" in result
    assert "테스트 근거" in result


async def test_summarize_recent_triples_section():
    """recall 결과가 있으면 '최근 트리플' 섹션이 포함됨."""
    mem = _make_client()
    why_result = WhyResult(uri="urn:ag:proj:x")
    fake_recall = [
        {
            "predicate": "urn:ag:rel:rationale",
            "object": "value",
            "object_is_uri": False,
            "asserted_at": None,
            "decay_score": 1.0,
        }
    ]
    with (
        patch.object(mem, "why", new=AsyncMock(return_value=why_result)),
        patch.object(mem, "recall", new=AsyncMock(return_value=fake_recall)),
    ):
        result = await mem.summarize("urn:ag:proj:x")

    assert "최근 트리플" in result


async def test_summarize_empty_recall():
    """recall이 비어 있으면 '최근 트리플' 섹션 없음."""
    mem = _make_client()
    why_result = WhyResult(uri="urn:ag:proj:x")
    with (
        patch.object(mem, "why", new=AsyncMock(return_value=why_result)),
        patch.object(mem, "recall", new=AsyncMock(return_value=[])),
    ):
        result = await mem.summarize("urn:ag:proj:x")

    assert "최근 트리플" not in result


async def test_summarize_returns_string():
    """반환값이 str."""
    mem = _make_client()
    why_result = WhyResult(uri="urn:ag:proj:x")
    with (
        patch.object(mem, "why", new=AsyncMock(return_value=why_result)),
        patch.object(mem, "recall", new=AsyncMock(return_value=[])),
    ):
        result = await mem.summarize("urn:ag:proj:x")

    assert isinstance(result, str)


# ── remember_bulk ─────────────────────────────────────────────────────────────

async def test_remember_bulk_delegates_to_remember_many():
    """remember_bulk이 remember_many를 호출함."""
    mem = _make_client()
    with patch.object(mem, "remember_many", new=AsyncMock(return_value=3)) as mock:
        count = await mem.remember_bulk([
            {"subject": "urn:ag:proj:x", "predicate": "urn:ag:rel:label", "object": "X"},
            {"subject": "urn:ag:proj:y", "predicate": "urn:ag:rel:label", "object": "Y"},
            {
                "subject": "urn:ag:proj:z",
                "predicate": "urn:ag:rel:dependsOn",
                "object": "urn:ag:proj:x",
                "object_is_uri": True,
            },
        ])

    assert count == 3
    mock.assert_awaited_once()


async def test_remember_bulk_rejects_empty():
    """빈 배열 전달 시 ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError, match="비어 있습니다"):
        await mem.remember_bulk([])


async def test_remember_bulk_rejects_missing_subject():
    """subject 키 누락 시 ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError, match="subject"):
        await mem.remember_bulk([
            {"predicate": "urn:ag:rel:label", "object": "X"}
        ])


async def test_remember_bulk_rejects_missing_predicate():
    """predicate 키 누락 시 ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError, match="predicate"):
        await mem.remember_bulk([
            {"subject": "urn:ag:proj:x", "object": "X"}
        ])


async def test_remember_bulk_rejects_missing_object():
    """object 키 누락 시 ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError, match="object"):
        await mem.remember_bulk([
            {"subject": "urn:ag:proj:x", "predicate": "urn:ag:rel:label"}
        ])


async def test_remember_bulk_passes_ttl():
    """ttl_months가 remember_many에 전달됨."""
    mem = _make_client()
    with patch.object(mem, "remember_many", new=AsyncMock(return_value=1)) as mock:
        await mem.remember_bulk(
            [{"subject": "urn:ag:proj:x", "predicate": "urn:ag:rel:label", "object": "X"}],
            ttl_months=3,
        )

    _, kwargs = mock.call_args
    assert kwargs.get("ttl_months") == 3
