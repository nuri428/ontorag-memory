"""P2 기능 유닛 테스트 — Fuseki 없이 실행.

실행:
    uv run pytest tests/test_p2_features.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ontorag_memory.client import MemoryClient
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.registry import P


class _MockStore:
    async def assert_triples(self, triples: list, *, ontology: str) -> None:
        pass

    async def aclose(self) -> None:
        pass


def _make_client() -> MemoryClient:
    store = _MockStore()
    identity = AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789")
    return MemoryClient(store, identity=identity)


# ── recall() 페이지네이션 ─────────────────────────────────────────────────────

def _fake_rows(n: int) -> list[dict]:
    """n개의 더미 SPARQL 결과 행 생성 — decay_score 계산용 t 포함."""
    return [
        {
            "p": {"value": f"urn:ag:rel:pred{i}"},
            "o": {"value": f"value-{i}", "type": "literal"},
            "t": {"value": f"2026-0{(i % 9) + 1}-01T00:00:00Z"},
        }
        for i in range(n)
    ]


async def test_recall_limit_applies_after_sort():
    """limit=2이면 decay 정렬 후 상위 2개만 반환."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=_fake_rows(5))):
        results = await mem.recall("urn:ag:proj:x", limit=2)
    assert len(results) == 2


async def test_recall_offset_skips_items():
    """offset=3이면 첫 3개를 건너뛰고 반환."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=_fake_rows(5))):
        all_results = await mem.recall("urn:ag:proj:x")
        offset_results = await mem.recall("urn:ag:proj:x", offset=3)
    assert len(offset_results) == len(all_results) - 3


async def test_recall_limit_and_offset_combined():
    """offset=1, limit=2 → 두 번째부터 2개."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=_fake_rows(5))):
        all_r = await mem.recall("urn:ag:proj:x")
        page = await mem.recall("urn:ag:proj:x", offset=1, limit=2)
    assert page == all_r[1:3]


async def test_recall_limit_none_returns_all():
    """limit=None(기본)이면 전체 반환."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=_fake_rows(7))):
        results = await mem.recall("urn:ag:proj:x")
    assert len(results) == 7


async def test_recall_offset_beyond_length_returns_empty():
    """offset이 전체 결과 수보다 크면 빈 리스트 반환."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=_fake_rows(3))):
        results = await mem.recall("urn:ag:proj:x", offset=10)
    assert results == []


async def test_recall_rejects_invalid_limit():
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="limit은"):
            await mem.recall("urn:ag:proj:x", limit=0)


async def test_recall_rejects_over_limit():
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="limit은"):
            await mem.recall("urn:ag:proj:x", limit=10001)


async def test_recall_rejects_negative_offset():
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="offset은"):
            await mem.recall("urn:ag:proj:x", offset=-1)


# ── find_related() ────────────────────────────────────────────────────────────

async def test_find_related_out_includes_predicate_and_uri():
    """direction='out' 쿼리에 entity URI + predicate URI가 포함됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_related("urn:ag:proj:ontorag", P.DEPENDS_ON, direction="out")

    assert len(captured) == 1
    assert "urn:ag:proj:ontorag" in captured[0]
    assert P.DEPENDS_ON in captured[0]
    assert '"out"' in captured[0]


async def test_find_related_in_query_structure():
    """direction='in' 쿼리는 역방향 패턴 포함."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_related("urn:ag:proj:ontorag", P.DEPENDS_ON, direction="in")

    assert '"in"' in captured[0]


async def test_find_related_both_has_union():
    """direction='both' 쿼리는 UNION을 포함."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_related("urn:ag:proj:ontorag", P.DEPENDS_ON, direction="both")

    assert "UNION" in captured[0]


async def test_find_related_returns_uri_and_direction():
    """반환값 구조 — uri, direction 키 포함."""
    mem = _make_client()
    fake_rows = [
        {"neighbor": {"value": "urn:ag:proj:foo"}, "dir": {"value": "out"}},
        {"neighbor": {"value": "urn:ag:proj:bar"}, "dir": {"value": "out"}},
    ]
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=fake_rows)):
        results = await mem.find_related("urn:ag:proj:ontorag", P.DEPENDS_ON)

    assert len(results) == 2
    assert results[0]["uri"] == "urn:ag:proj:foo"
    assert results[0]["direction"] == "out"


async def test_find_related_rejects_invalid_direction():
    mem = _make_client()
    with pytest.raises(ValueError, match="direction은"):
        await mem.find_related("urn:ag:proj:x", P.DEPENDS_ON, direction="sideways")


async def test_find_related_rejects_invalid_limit():
    mem = _make_client()
    with pytest.raises(ValueError, match="limit은"):
        await mem.find_related("urn:ag:proj:x", P.DEPENDS_ON, limit=0)


async def test_find_related_rejects_unsafe_predicate():
    """술어 URI에 위험 문자가 있으면 ValueError."""
    mem = _make_client()
    with pytest.raises(ValueError):
        await mem.find_related(
            "urn:ag:proj:x",
            "urn:ag:rel:dep> . } # injection",
        )


async def test_find_related_resolves_entity_name():
    """엔티티 이름이 레지스트리를 통해 URI로 변환됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.find_related("patent board", P.DEPENDS_ON)

    assert "urn:ag:proj:patent-board" in captured[0]


# ── search_by_rationale() ─────────────────────────────────────────────────────

async def test_search_by_rationale_keyword_in_query():
    """키워드가 SPARQL 쿼리의 CONTAINS 절에 포함됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.search_by_rationale("fuseki")

    assert "fuseki" in captured[0]
    assert "CONTAINS" in captured[0]
    assert "LCASE" in captured[0]


async def test_search_by_rationale_searches_text_predicates():
    """SPARQL 쿼리에 rationale, content, label 등 텍스트 술어가 포함됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.search_by_rationale("test")

    q = captured[0]
    assert P.RATIONALE in q
    assert P.CONTENT in q
    assert P.LABEL in q
    assert P.DESCRIPTION in q


async def test_search_by_rationale_returns_subject_predicate_snippet():
    """반환값 구조 — subject, predicate, snippet 키 포함."""
    mem = _make_client()
    fake_rows = [
        {
            "s": {"value": "urn:ag:decision:2026-01-01:test"},
            "p": {"value": P.RATIONALE},
            "o": {"value": "Fuseki를 선택한 이유"},
        }
    ]
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=fake_rows)):
        results = await mem.search_by_rationale("Fuseki")

    assert len(results) == 1
    assert results[0]["subject"] == "urn:ag:decision:2026-01-01:test"
    assert results[0]["predicate"] == P.RATIONALE
    assert results[0]["snippet"] == "Fuseki를 선택한 이유"


async def test_search_by_rationale_rejects_empty_keyword():
    mem = _make_client()
    with pytest.raises(ValueError, match="비어 있습니다"):
        await mem.search_by_rationale("")


async def test_search_by_rationale_rejects_whitespace_only():
    mem = _make_client()
    with pytest.raises(ValueError, match="비어 있습니다"):
        await mem.search_by_rationale("   ")


async def test_search_by_rationale_rejects_invalid_limit():
    mem = _make_client()
    with pytest.raises(ValueError, match="limit은"):
        await mem.search_by_rationale("keyword", limit=0)


async def test_search_by_rationale_escapes_double_quote():
    """키워드의 큰따옴표가 SPARQL 인젝션 방지용으로 이스케이프됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.search_by_rationale('say "hello"')

    assert '\\"hello\\"' in captured[0]


async def test_search_by_rationale_applies_limit():
    """SPARQL 쿼리에 LIMIT이 설정됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(q: str) -> list:
        captured.append(q)
        return []

    with patch.object(mem._lc, "_sparql_select", new=capture):
        await mem.search_by_rationale("test", limit=5)

    assert "LIMIT 5" in captured[0]
