"""ontorag-memory MCP 서버 유닛 테스트 — Fuseki 없이 실행.

_dispatch() 함수를 FakeMemoryClient로 테스트한다.
실제 MCP 프로토콜(stdio) 계층은 여기서 테스트하지 않는다.

실행:
    uv run pytest tests/test_mcp_server.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ontorag_memory.diary import DiaryEntry
from ontorag_memory.graph_stats import GraphStats, HubNode  # noqa: F401
from ontorag_memory.mcp_server import _TOOLS, _dispatch, _to_jsonable
from ontorag_memory.why_result import Influence, OutgoingEdge, WhyResult

# ── 공통 Fake ─────────────────────────────────────────────────────────────────

def _make_mem(**overrides):
    """MemoryClient 인터페이스를 흉내 내는 Fake 반환."""
    mem = MagicMock()
    mem.remember = AsyncMock(return_value=True)
    mem.recall = AsyncMock(return_value=[])
    mem.recall_recent = AsyncMock(return_value=[])
    mem.why = AsyncMock(return_value=WhyResult(uri="urn:ag:proj:test"))
    mem.find_path = AsyncMock(return_value=[])
    mem.find_related = AsyncMock(return_value=[])
    mem.search_by_rationale = AsyncMock(return_value=[])
    mem.diary_write = AsyncMock(return_value="urn:ag:diary:2026-06-27:120000:s0123456:test")
    mem.diary_read = AsyncMock(return_value=[])
    mem.graph_stats = AsyncMock(
        return_value=GraphStats(graph="urn:ontorag:test", subjects=5, triples=20, predicates=3)
    )
    mem.stats = AsyncMock(return_value={"subjects": 5, "triples": 20})
    mem.prune = AsyncMock(
        return_value={"subjects": 0, "triples": 0, "expired": 0, "dry_run": False}
    )
    mem.find_path_transitive = AsyncMock(return_value=["urn:ag:proj:a", "urn:ag:proj:b"])
    mem.summarize = AsyncMock(return_value="# Why: urn:ag:proj:test\n요약 내용")
    mem.remember_bulk = AsyncMock(return_value=3)
    for k, v in overrides.items():
        setattr(mem, k, v)
    return mem


# ── _to_jsonable ──────────────────────────────────────────────────────────────

def test_to_jsonable_pydantic():
    """Pydantic BaseModel이 dict로 변환됨."""
    result = _to_jsonable(WhyResult(uri="urn:ag:proj:x", rationale=["test"]))
    assert isinstance(result, dict)
    assert result["uri"] == "urn:ag:proj:x"
    assert result["rationale"] == ["test"]


def test_to_jsonable_nested_list():
    """중첩 list가 재귀 변환됨."""
    result = _to_jsonable([HubNode(uri="urn:ag:proj:x", degree=5)])
    assert isinstance(result, list)
    assert result[0]["degree"] == 5


def test_to_jsonable_dict():
    """dict가 그대로 변환됨."""
    result = _to_jsonable({"key": "value"})
    assert result == {"key": "value"}


# ── _TOOLS 스키마 ─────────────────────────────────────────────────────────────

def test_all_tools_have_required_keys():
    """모든 툴 정의에 description, properties, required 키가 있음."""
    for name, spec in _TOOLS.items():
        assert "description" in spec, f"{name}: description 없음"
        assert "properties" in spec, f"{name}: properties 없음"
        assert "required" in spec, f"{name}: required 없음"


def test_tool_count():
    """등록된 툴 수가 15개 (P0: 12 + P2: 3)."""
    assert len(_TOOLS) == 15


# ── remember ─────────────────────────────────────────────────────────────────

async def test_dispatch_remember_basic():
    """remember 기본 호출."""
    mem = _make_mem()
    result = await _dispatch(mem, "remember", {
        "subject": "urn:ag:proj:x",
        "predicate": "urn:ag:rel:rationale",
        "object": "test reason",
    })
    assert result == {"stored": True}
    mem.remember.assert_awaited_once()


async def test_dispatch_remember_skip_if_exists():
    """skip_if_exists=True 전달."""
    mem = _make_mem(remember=AsyncMock(return_value=False))
    result = await _dispatch(mem, "remember", {
        "subject": "urn:ag:proj:x",
        "predicate": "urn:ag:rel:rationale",
        "object": "test",
        "skip_if_exists": True,
    })
    assert result["stored"] is False
    _, kwargs = mem.remember.call_args
    assert kwargs["skip_if_exists"] is True


async def test_dispatch_remember_with_ttl():
    """ttl_months 전달."""
    mem = _make_mem()
    await _dispatch(mem, "remember", {
        "subject": "urn:ag:proj:x",
        "predicate": "urn:ag:rel:rationale",
        "object": "test",
        "ttl_months": 3,
    })
    _, kwargs = mem.remember.call_args
    assert kwargs["ttl_months"] == 3


# ── recall ────────────────────────────────────────────────────────────────────

async def test_dispatch_recall_no_limit():
    """limit 생략 시 kwargs에 limit 없이 호출됨."""
    mem = _make_mem()
    await _dispatch(mem, "recall", {"entity": "urn:ag:proj:x"})
    mem.recall.assert_awaited_once_with("urn:ag:proj:x")


async def test_dispatch_recall_with_pagination():
    """limit + offset 전달."""
    mem = _make_mem()
    await _dispatch(mem, "recall", {"entity": "urn:ag:proj:x", "limit": 10, "offset": 5})
    mem.recall.assert_awaited_once_with("urn:ag:proj:x", limit=10, offset=5)


# ── recall_recent ─────────────────────────────────────────────────────────────

async def test_dispatch_recall_recent_default_n():
    """n 기본값 20으로 호출됨."""
    mem = _make_mem()
    await _dispatch(mem, "recall_recent", {})
    mem.recall_recent.assert_awaited_once_with(n=20)


async def test_dispatch_recall_recent_custom_n():
    """n=5 전달."""
    mem = _make_mem()
    await _dispatch(mem, "recall_recent", {"n": 5})
    mem.recall_recent.assert_awaited_once_with(n=5)


# ── why ───────────────────────────────────────────────────────────────────────

async def test_dispatch_why_returns_context():
    """why 결과에 context 키(to_context_str)가 포함됨."""
    why_result = WhyResult(
        uri="urn:ag:proj:x",
        rationale=["test reason"],
        decided_against=["alt1"],
        influenced_by=[Influence(predicate="urn:ag:rel:uses", subject="urn:ag:agent:hermes")],
        outgoing=[
            OutgoingEdge(predicate="urn:ag:rel:dependsOn", obj="urn:ag:tech:fuseki", obj_is_uri=True)  # noqa: E501
        ],
    )
    mem = _make_mem(why=AsyncMock(return_value=why_result))
    result = await _dispatch(mem, "why", {"entity": "urn:ag:proj:x"})
    assert "context" in result
    assert "# Why: urn:ag:proj:x" in result["context"]
    assert result["uri"] == "urn:ag:proj:x"
    assert result["rationale"] == ["test reason"]


# ── find_path ─────────────────────────────────────────────────────────────────

async def test_dispatch_find_path():
    """from_entity, to_entity, max_depth 전달."""
    mem = _make_mem()
    await _dispatch(mem, "find_path", {
        "from_entity": "urn:ag:agent:hermes",
        "to_entity": "urn:ag:proj:patent-board",
        "max_depth": 2,
    })
    mem.find_path.assert_awaited_once_with(
        "urn:ag:agent:hermes", "urn:ag:proj:patent-board", max_depth=2
    )


# ── find_related ──────────────────────────────────────────────────────────────

async def test_dispatch_find_related_defaults():
    """direction 기본값 'out', limit 기본값 100."""
    mem = _make_mem()
    await _dispatch(mem, "find_related", {
        "entity": "urn:ag:proj:x",
        "predicate": "urn:ag:rel:dependsOn",
    })
    mem.find_related.assert_awaited_once_with(
        "urn:ag:proj:x", "urn:ag:rel:dependsOn", direction="out", limit=100
    )


async def test_dispatch_find_related_both():
    """direction='both' 전달."""
    mem = _make_mem()
    await _dispatch(mem, "find_related", {
        "entity": "urn:ag:proj:x",
        "predicate": "urn:ag:rel:dependsOn",
        "direction": "both",
    })
    _, kwargs = mem.find_related.call_args
    assert kwargs["direction"] == "both"


# ── search_by_rationale ───────────────────────────────────────────────────────

async def test_dispatch_search_by_rationale():
    """keyword + limit 전달."""
    mem = _make_mem()
    await _dispatch(mem, "search_by_rationale", {"keyword": "fuseki", "limit": 5})
    mem.search_by_rationale.assert_awaited_once_with("fuseki", limit=5)


# ── diary_write / diary_read ──────────────────────────────────────────────────

async def test_dispatch_diary_write_returns_uri():
    """diary_write 결과에 uri 키 포함."""
    mem = _make_mem()
    result = await _dispatch(mem, "diary_write", {"content": "test memo", "tags": ["bug"]})
    assert "uri" in result
    assert result["uri"].startswith("urn:ag:diary:")


async def test_dispatch_diary_read_returns_list():
    """diary_read 결과가 직렬화된 list."""
    entries = [
        DiaryEntry(
            uri="urn:ag:diary:2026-01-01:000000:s0000:test",
            content="test",
            made_at="2026-01-01",
        )
    ]
    mem = _make_mem(diary_read=AsyncMock(return_value=entries))
    result = await _dispatch(mem, "diary_read", {})
    assert isinstance(result, list)
    assert result[0]["content"] == "test"


# ── graph_stats / stats / prune ───────────────────────────────────────────────

async def test_dispatch_graph_stats_has_context():
    """graph_stats 결과에 context 키 포함."""
    mem = _make_mem()
    result = await _dispatch(mem, "graph_stats", {"hub_limit": 5})
    assert "context" in result
    assert "Graph Stats" in result["context"]
    mem.graph_stats.assert_awaited_once_with(hub_limit=5)


async def test_dispatch_stats():
    """stats 결과가 dict."""
    mem = _make_mem()
    result = await _dispatch(mem, "stats", {})
    assert result == {"subjects": 5, "triples": 20}


async def test_dispatch_prune_dry_run():
    """dry_run=True 전달."""
    mem = _make_mem()
    await _dispatch(mem, "prune", {"dry_run": True})
    _, kwargs = mem.prune.call_args
    assert kwargs["dry_run"] is True


async def test_dispatch_unknown_tool_raises():
    """알 수 없는 툴 이름은 ValueError."""
    mem = _make_mem()
    with pytest.raises(ValueError, match="Unknown tool"):
        await _dispatch(mem, "not_a_tool", {})


# ── find_path_transitive / summarize / remember_bulk (P2) ────────────────────

async def test_dispatch_find_path_transitive_defaults():
    """entity, predicate 전달 — direction/limit 기본값."""
    mem = _make_mem()
    result = await _dispatch(mem, "find_path_transitive", {
        "entity": "urn:ag:proj:patent-board",
        "predicate": "urn:ag:rel:involves",
    })
    assert result == ["urn:ag:proj:a", "urn:ag:proj:b"]
    mem.find_path_transitive.assert_awaited_once_with(
        "urn:ag:proj:patent-board",
        "urn:ag:rel:involves",
        direction="out",
        limit=100,
    )


async def test_dispatch_find_path_transitive_in_direction():
    """direction='in', limit=50 전달."""
    mem = _make_mem()
    await _dispatch(mem, "find_path_transitive", {
        "entity": "urn:ag:proj:patent-board",
        "predicate": "urn:ag:rel:involves",
        "direction": "in",
        "limit": 50,
    })
    _, kwargs = mem.find_path_transitive.call_args
    assert kwargs["direction"] == "in"
    assert kwargs["limit"] == 50


async def test_dispatch_summarize_returns_string():
    """summarize 결과가 str."""
    mem = _make_mem()
    result = await _dispatch(mem, "summarize", {"entity": "urn:ag:proj:test"})
    assert isinstance(result, str)
    assert "# Why:" in result
    mem.summarize.assert_awaited_once_with("urn:ag:proj:test")


async def test_dispatch_remember_bulk_returns_count():
    """remember_bulk 결과에 stored 키 포함."""
    mem = _make_mem()
    triples = [
        {"subject": "urn:ag:proj:x", "predicate": "urn:ag:rel:label", "object": "X"},
    ]
    result = await _dispatch(mem, "remember_bulk", {"triples": triples})
    assert result == {"stored": 3}
    mem.remember_bulk.assert_awaited_once_with(triples, ttl_months=None)


async def test_dispatch_remember_bulk_passes_ttl():
    """ttl_months가 remember_bulk에 전달됨."""
    mem = _make_mem()
    triples = [
        {"subject": "urn:ag:proj:x", "predicate": "urn:ag:rel:label", "object": "X"},
    ]
    await _dispatch(mem, "remember_bulk", {"triples": triples, "ttl_months": 6})
    _, kwargs = mem.remember_bulk.call_args
    assert kwargs["ttl_months"] == 6
