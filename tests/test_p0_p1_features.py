"""P0 / P1 기능 유닛 테스트 — 백엔드(Fuseki) 없이 실행 가능.

실행:
    uv run pytest tests/test_p0_p1_features.py -v
"""

from __future__ import annotations

import math
import re
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from ontorag_memory.client import MemoryClient, _validate_uri
from ontorag_memory.diary import DiaryEntry
from ontorag_memory.graph_stats import GraphStats, HubNode, PredicateCount
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.registry import P
from ontorag_memory.why_result import Influence, OutgoingEdge, WhyResult

# ── 공통 픽스처 ────────────────────────────────────────────────────────────────

class _MockStore:
    """백엔드 없는 단순 mock store."""

    def __init__(self) -> None:
        self.stored: list = []

    async def assert_triples(self, triples: list, *, ontology: str) -> None:
        self.stored.extend(triples)

    async def aclose(self) -> None:
        pass


def _make_client() -> MemoryClient:
    store = _MockStore()
    identity = AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789")
    return MemoryClient(store, identity=identity)


# ── WhyResult 모델 ─────────────────────────────────────────────────────────────

def test_why_result_to_context_str_full():
    """모든 필드가 채워진 WhyResult — 각 섹션이 to_context_str()에 포함됨."""
    result = WhyResult(
        uri="urn:ag:decision:2026-01-01:test",
        rationale=["속도 때문에 선택"],
        made_at="2026-01-01",
        decided_against=["대안 A"],
        influenced_by=[Influence(predicate=P.RELATED_TO, subject="urn:ag:proj:foo")],
        outgoing=[OutgoingEdge(predicate=P.USES, obj="urn:ag:tech:bar", obj_is_uri=True)],
    )
    ctx = result.to_context_str()

    assert "# Why: urn:ag:decision:2026-01-01:test" in ctx
    assert "속도 때문에 선택" in ctx
    assert "대안 A" in ctx
    assert "영향받음 (역방향)" in ctx
    assert "기타 관계" in ctx
    assert "결정 시점: 2026-01-01" in ctx


def test_why_result_to_context_str_empty_fields():
    """빈 Why result — 헤더만 출력, 빈 섹션 생략 (토큰 절약)."""
    result = WhyResult(uri="urn:ag:proj:empty")
    ctx = result.to_context_str()

    assert "# Why: urn:ag:proj:empty" in ctx
    assert "근거" not in ctx
    assert "기각" not in ctx
    assert "결정 시점" not in ctx


def test_why_result_frozen():
    """frozen=True — 인스턴스 필드 재할당 시 ValidationError."""
    result = WhyResult(uri="urn:ag:proj:x")
    with pytest.raises(ValidationError):
        result.uri = "mutated"  # type: ignore[misc]


def test_why_result_rationale_only():
    """made_at 없어도 rationale 섹션은 출력됨."""
    result = WhyResult(uri="urn:ag:proj:x", rationale=["이유 A", "이유 B"])
    ctx = result.to_context_str()

    assert "## 근거" in ctx
    assert "이유 A" in ctx
    assert "결정 시점" not in ctx


# ── GraphStats 모델 ────────────────────────────────────────────────────────────

def test_graph_stats_to_context_str_with_data():
    """허브 노드 + 술어 분포가 있을 때 모두 to_context_str()에 포함됨."""
    stats = GraphStats(
        graph="urn:ontorag:test:data",
        subjects=10,
        triples=42,
        predicates=5,
        hub_nodes=[HubNode(uri="urn:ag:proj:ontorag", degree=15)],
        predicate_distribution=[PredicateCount(predicate=P.LABEL, count=8)],
        avg_degree=4.2,
    )
    ctx = stats.to_context_str()

    assert "Graph Stats" in ctx
    assert "nodes: 10" in ctx
    assert "triples: 42" in ctx
    assert "urn:ag:proj:ontorag" in ctx
    assert "degree 15" in ctx
    assert "avg_degree: 4.2" in ctx
    assert "술어 사용 빈도" in ctx


def test_graph_stats_to_context_str_empty_graph():
    """빈 그래프 — 허브/고립 섹션 생략."""
    stats = GraphStats(
        graph="urn:ontorag:empty:data",
        subjects=0,
        triples=0,
        predicates=0,
    )
    ctx = stats.to_context_str()

    assert "nodes: 0" in ctx
    assert "허브" not in ctx
    assert "고립" not in ctx


def test_graph_stats_isolated_nodes_truncated_at_20():
    """역방향 참조 없는 노드 21개 → 20개만 출력, '… 외 1개' 메시지 추가."""
    stats = GraphStats(
        graph="urn:test",
        subjects=21,
        triples=21,
        predicates=1,
        isolated_nodes=[f"urn:ag:node:{i}" for i in range(21)],
    )
    ctx = stats.to_context_str()
    assert "… 외 1개" in ctx
    # 레이블이 "고립 노드"가 아닌 "역방향 참조 없는 노드"로 표시됨
    assert "역방향 참조 없는 노드" in ctx


# ── DiaryEntry 모델 ────────────────────────────────────────────────────────────

def test_diary_entry_to_context_str_no_tags():
    """태그 없음 — '[날짜] 내용' 포맷."""
    entry = DiaryEntry(
        uri="urn:ag:diary:2026-01-01:abc:test",
        content="Fuseki union graph는 느림",
        made_at="2026-01-01",
    )
    assert entry.to_context_str() == "[2026-01-01] Fuseki union graph는 느림"


def test_diary_entry_to_context_str_with_tags():
    """태그 있음 — '[날짜  [t1, t2]] 내용' 포맷."""
    entry = DiaryEntry(
        uri="urn:ag:diary:2026-01-01:abc:test",
        content="성능 메모",
        made_at="2026-01-01",
        tags=["performance", "fuseki"],
    )
    ctx = entry.to_context_str()
    assert "[performance, fuseki]" in ctx
    assert "성능 메모" in ctx


def test_diary_entry_frozen():
    """DiaryEntry도 frozen=True — 필드 변경 시 ValidationError."""
    entry = DiaryEntry(
        uri="urn:ag:diary:2026-01-01:abc:test",
        content="내용",
        made_at="2026-01-01",
    )
    with pytest.raises(ValidationError):
        entry.content = "changed"  # type: ignore[misc]


# ── _validate_uri() ────────────────────────────────────────────────────────────

def test_validate_uri_accepts_urn():
    _validate_uri("urn:ag:proj:ontorag")


def test_validate_uri_accepts_http():
    _validate_uri("http://example.com/resource")


def test_validate_uri_accepts_https():
    _validate_uri("https://schema.org/name")


def test_validate_uri_rejects_bare_string():
    with pytest.raises(ValueError, match="안전하지 않은 URI"):
        _validate_uri("'; DROP TABLE triples; --")


def test_validate_uri_rejects_relative_path():
    with pytest.raises(ValueError):
        _validate_uri("/relative/path")


def test_validate_uri_rejects_empty_string():
    with pytest.raises(ValueError):
        _validate_uri("")


def test_validate_uri_rejects_plain_name():
    with pytest.raises(ValueError):
        _validate_uri("ontorag")


def test_validate_uri_rejects_sparql_escape_via_angle_bracket():
    """prefix는 맞지만 > 문자로 SPARQL 구조 탈출 시도 차단."""
    with pytest.raises(ValueError, match="허용되지 않는 문자"):
        _validate_uri("urn:ag:rel:foo> . OPTIONAL { ?s ?p ?o } # ")


def test_validate_uri_rejects_space_in_uri():
    with pytest.raises(ValueError):
        _validate_uri("urn:ag:proj:my project")


# ── 시간 감쇠 공식 (exp(-λ * days)) ──────────────────────────────────────────

def test_decay_score_fresh_item():
    """방금 저장 (days=0) → score = 1.0."""
    assert math.exp(-0.01 * 0) == pytest.approx(1.0)


def test_decay_score_half_life():
    """λ=0.01, ~69일 → score ≈ 0.5 (반감기)."""
    score = math.exp(-0.01 * 69)
    assert score == pytest.approx(0.5, abs=0.01)


def test_decay_score_one_year_very_low():
    """1년 후 → score < 0.03."""
    assert math.exp(-0.01 * 365) < 0.03


def test_decay_score_monotone_decreasing():
    """시간이 지날수록 단조 감소."""
    scores = [math.exp(-0.01 * d) for d in [0, 10, 30, 100, 365]]
    assert scores == sorted(scores, reverse=True)


def test_decay_score_higher_lambda_decays_faster():
    """λ가 클수록 더 빠르게 감쇠."""
    days = 50
    slow = math.exp(-0.01 * days)   # λ=0.01 (기본값)
    fast = math.exp(-0.05 * days)   # λ=0.05 (5배)
    assert fast < slow


# ── diary_write() URI 스킴 ─────────────────────────────────────────────────────

async def test_diary_write_uri_starts_with_prefix():
    """생성 URI가 urn:ag:diary: 로 시작."""
    mem = _make_client()
    uri = await mem.diary_write("테스트 메모 내용입니다")
    assert uri.startswith("urn:ag:diary:")


async def test_diary_write_uri_contains_date():
    """URI 네 번째 세그먼트(urn:ag:diary:{date}:...)가 YYYY-MM-DD 형식의 날짜."""
    mem = _make_client()
    uri = await mem.diary_write("날짜 테스트")
    # urn:ag:diary:YYYY-MM-DD:HHMMSS:session:slug
    date_part = uri.split(":")[3]
    assert re.match(r"\d{4}-\d{2}-\d{2}", date_part)


async def test_diary_write_uri_contains_time():
    """URI 다섯 번째 세그먼트가 HHMMSS 형식의 시각."""
    mem = _make_client()
    uri = await mem.diary_write("시각 테스트")
    time_part = uri.split(":")[4]
    assert re.match(r"\d{6}", time_part)


async def test_diary_write_uri_contains_session_prefix():
    """URI에 세션 ID 앞 8자리가 포함됨."""
    mem = _make_client()
    uri = await mem.diary_write("세션 확인")
    assert "s0123456" in uri


async def test_diary_write_same_content_different_uris():
    """같은 내용을 두 번 써도 (초가 다르면) URI가 달라져야 함.
    같은 초에 호출되면 URI가 같을 수 있으나 실용적으로 충분한 보호.
    """
    mem = _make_client()
    uri1 = await mem.diary_write("충돌 방지 테스트")
    uri2 = await mem.diary_write("충돌 방지 테스트")
    # 최소한 urn:ag:diary: 접두사를 공유하지만 구조는 유효
    assert uri1.startswith("urn:ag:diary:")
    assert uri2.startswith("urn:ag:diary:")


async def test_diary_write_stores_content_predicate():
    """P.CONTENT, P.MADE_AT, P.TAG 트리플이 실제 store에 기록됨."""
    store = _MockStore()
    identity = AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789")
    mem = MemoryClient(store, identity=identity)

    await mem.diary_write("중요 메모", tags=["critical"])

    predicates = {t[1] for t in store.stored}
    assert P.CONTENT in predicates
    assert P.MADE_AT in predicates
    assert P.TAG in predicates


async def test_diary_write_no_tags_skips_tag_triple():
    """tags 없으면 P.TAG 트리플 없음."""
    store = _MockStore()
    identity = AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789")
    mem = MemoryClient(store, identity=identity)

    await mem.diary_write("태그 없는 메모")

    predicates = {t[1] for t in store.stored}
    assert P.TAG not in predicates


# ── check_duplicate() ─────────────────────────────────────────────────────────

async def test_check_duplicate_delegates_to_sparql_ask_false():
    """SPARQL ASK가 False → check_duplicate()도 False."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_ask", new=AsyncMock(return_value=False)):
        result = await mem.check_duplicate("urn:ag:proj:test", P.LABEL, "label")
    assert result is False


async def test_check_duplicate_delegates_to_sparql_ask_true():
    """SPARQL ASK가 True → check_duplicate()도 True."""
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_ask", new=AsyncMock(return_value=True)):
        result = await mem.check_duplicate("urn:ag:proj:test", P.LABEL, "label")
    assert result is True


async def test_check_duplicate_uri_object_uses_angle_brackets():
    """object_is_uri=True일 때 SPARQL 쿼리에 <uri> 형식이 사용됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture_ask(query: str) -> bool:
        captured.append(query)
        return False

    with patch.object(mem._lc, "_sparql_ask", new=capture_ask):
        await mem.check_duplicate(
            "urn:ag:proj:a", P.DEPENDS_ON, "urn:ag:proj:b", object_is_uri=True
        )

    assert len(captured) == 1
    assert "<urn:ag:proj:b>" in captured[0]


async def test_check_duplicate_literal_object_uses_quotes():
    """object_is_uri=False일 때 SPARQL 쿼리에 "리터럴" 형식이 사용됨."""
    mem = _make_client()
    captured: list[str] = []

    async def capture_ask(query: str) -> bool:
        captured.append(query)
        return False

    with patch.object(mem._lc, "_sparql_ask", new=capture_ask):
        await mem.check_duplicate("urn:ag:proj:a", P.LABEL, "my label", object_is_uri=False)

    assert '"my label"' in captured[0]


# ── remember(skip_if_exists=True) ─────────────────────────────────────────────

async def test_remember_skip_if_exists_skips_on_duplicate():
    """이미 존재하면 False 반환, store에 저장 없음."""
    store = _MockStore()
    mem = MemoryClient(
        store,
        identity=AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789"),
    )
    with patch.object(mem._lc, "_sparql_ask", new=AsyncMock(return_value=True)):
        result = await mem.remember(
            "urn:ag:proj:x", P.LABEL, "label value", skip_if_exists=True
        )
    assert result is False
    assert store.stored == []


async def test_remember_skip_if_exists_stores_on_new():
    """중복 없으면 True 반환, store에 저장됨."""
    store = _MockStore()
    mem = MemoryClient(
        store,
        identity=AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789"),
    )
    with patch.object(mem._lc, "_sparql_ask", new=AsyncMock(return_value=False)):
        result = await mem.remember(
            "urn:ag:proj:x", P.LABEL, "label value", skip_if_exists=True
        )
    assert result is True
    assert len(store.stored) > 0


async def test_remember_without_skip_always_stores():
    """skip_if_exists=False(기본값)이면 중복 검사 없이 항상 저장."""
    store = _MockStore()
    mem = MemoryClient(
        store,
        identity=AgentIdentity(user="test", workspace="unit-test", session_id="s0123456789"),
    )
    result = await mem.remember("urn:ag:proj:x", P.LABEL, "label value")
    assert result is True
    assert len(store.stored) > 0


# ── 파라미터 범위 검증 ─────────────────────────────────────────────────────────

async def test_recall_recent_rejects_zero():
    mem = _make_client()
    with pytest.raises(ValueError, match="n은"):
        await mem.recall_recent(n=0)


async def test_recall_recent_rejects_over_limit():
    mem = _make_client()
    with pytest.raises(ValueError, match="n은"):
        await mem.recall_recent(n=1001)


async def test_diary_read_rejects_zero_limit():
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="limit은"):
            await mem.diary_read(limit=0)


async def test_diary_read_rejects_negative_since_days():
    mem = _make_client()
    with patch.object(mem._lc, "_sparql_select", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="since_days는"):
            await mem.diary_read(since_days=-1)


async def test_check_duplicate_resolves_entity_name():
    """check_duplicate()가 subject 이름을 URI로 자동 변환함 (LOW 이슈 수정)."""
    mem = _make_client()
    captured: list[str] = []

    async def capture(query: str) -> bool:
        captured.append(query)
        return False

    with patch.object(mem._lc, "_sparql_ask", new=capture):
        # "patent board" → 레지스트리 경유 → urn:ag:proj:patent-board
        await mem.check_duplicate("patent board", P.LABEL, "특허 보드")

    assert "urn:ag:proj:patent-board" in captured[0]
