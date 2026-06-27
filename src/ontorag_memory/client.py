"""MemoryClient — ontorag-memory 통합 진입점.

identity + registry + lifecycle 을 하나로 묶어 쉽게 사용.

    mem = await MemoryClient.create()
    await mem.remember("ontorag-flow", "dependsOn", "ontorag")
    await mem.remember("Hermes Agent", "relatedTo", "SRE")
    path = await mem.find_path("Hermes", "patent_board")
    st   = await mem.stats()
"""

from __future__ import annotations

import asyncio
import itertools
import os
import re
from typing import Any

from ontorag_memory.diary import DiaryEntry
from ontorag_memory.graph_stats import GraphStats, HubNode, PredicateCount
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.lifecycle import MemoryLifecycle
from ontorag_memory.registry import EntityRegistry, P
from ontorag_memory.why_result import Influence, OutgoingEdge, WhyResult


_SAFE_URI_PREFIXES = ("urn:", "http://", "https://")


def _validate_uri(uri: str) -> None:
    """SPARQL 인젝션 방지 — URI가 허용된 접두사로 시작하는지 검사."""
    if not any(uri.startswith(p) for p in _SAFE_URI_PREFIXES):
        raise ValueError(f"안전하지 않은 URI: {uri!r}. urn: 또는 http(s)://로 시작해야 합니다.")


class MemoryClient:
    """AI 에이전트 메모리의 단일 진입점."""

    def __init__(
        self,
        store: Any,
        *,
        identity: AgentIdentity | None = None,
        registry: EntityRegistry | None = None,
    ) -> None:
        self.identity  = identity or AgentIdentity.auto_detect()
        self.registry  = registry or EntityRegistry()
        self._lc       = MemoryLifecycle(store, self.identity)
        self._store    = store

    @classmethod
    async def create(
        cls,
        *,
        identity: AgentIdentity | None = None,
        registry: EntityRegistry | None = None,
        extra_registry: str | None = None,
    ) -> "MemoryClient":
        """FusekiStore를 환경 변수에서 생성해 연결까지 수행.

        Args:
            identity: 명시적 AgentIdentity. None이면 자동 감지.
            registry: 커스텀 EntityRegistry.
            extra_registry: 기본 레지스트리에 병합할 추가 YAML 경로.
        """
        from ontorag.stores.fuseki import FusekiStore

        store = FusekiStore.from_env()
        reg = (
            EntityRegistry.merged(extra_registry)
            if extra_registry
            else (registry or EntityRegistry())
        )
        return cls(store, identity=identity, registry=reg)

    # ── 저장 ─────────────────────────────────────────────────────────────────

    async def remember(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        object_is_uri: bool | None = None,
        ttl_months: int | None = None,
        skip_if_exists: bool = False,
    ) -> bool:
        """텍스트 → 노말라이즈 → 메타 자동 부착 저장.

        object_is_uri가 None이면 obj가 등록된 엔티티면 URI, 아니면 리터럴.

        Args:
            subject: 엔티티 이름 또는 URI.
            predicate: predicate URI (P.xxx 상수 사용 권장).
            obj: 객체 값 (엔티티 이름, URI, 또는 리터럴 문자열).
            object_is_uri: 명시적 URI 여부. None이면 레지스트리 검색으로 판단.
            ttl_months: 이 기간 후 자동 만료 (None이면 영구).
            skip_if_exists: True이면 동일 트리플이 이미 존재할 경우 저장 생략.

        Returns:
            True이면 저장됨, False이면 skip_if_exists로 건너뜀.
        """
        s = self._resolve(subject)
        if object_is_uri is None:
            object_is_uri = obj in self.registry or obj.startswith("urn:")
        o = self._resolve(obj) if object_is_uri else obj
        if skip_if_exists and await self.check_duplicate(s, predicate, o, object_is_uri=object_is_uri):
            return False
        await self._lc.assert_memory(s, predicate, o, object_is_uri=object_is_uri, ttl_months=ttl_months)
        return True

    async def remember_many(
        self,
        triples: list[tuple[str, str, str] | tuple[str, str, str, bool]],
        *,
        ttl_months: int | None = None,
    ) -> int:
        """여러 (subject, predicate, object[, object_is_uri]) 튜플을 배치 저장.

        4-튜플: object_is_uri를 명시적으로 지정.
        3-튜플: object가 레지스트리에 있거나 urn:/http로 시작하면 URI, 아니면 리터럴.
        """
        resolved: list[tuple[str, str, str, bool]] = []
        for item in triples:
            if len(item) == 4:
                s_text, p, o_text, is_uri = item  # type: ignore[misc]
            else:
                s_text, p, o_text = item  # type: ignore[misc]
                is_uri = o_text in self.registry or o_text.startswith(("urn:", "http"))
            s = self._resolve(s_text)
            o = self._resolve(o_text) if is_uri else o_text
            resolved.append((s, p, o, is_uri))
        return await self._lc.assert_memories(resolved, ttl_months=ttl_months)

    # ── 조회 ─────────────────────────────────────────────────────────────────

    async def recall(
        self,
        entity: str,
        *,
        sort_by_recency: bool = True,
        decay_lambda: float = 0.01,
    ) -> list[dict[str, Any]]:
        """엔티티에 연결된 모든 트리플 반환 (메타 제외).

        assertedAt 기반 시간 감쇠 스코어를 계산해 최신 사실이 상위에 온다.
        decay_score = exp(-λ * days_since_assertion), λ 기본값 0.01 → 반감기 ~69일.

        Args:
            entity: 엔티티 이름 또는 URI.
            sort_by_recency: True이면 decay_score 내림차순 정렬.
            decay_lambda: 시간 감쇠 계수. 클수록 오래된 사실이 더 빨리 낮아짐.

        Returns:
            [{"predicate": uri, "object": value, "object_is_uri": bool,
              "asserted_at": iso_str|None, "decay_score": float}]
        """
        import math
        from datetime import datetime, timezone

        uri = self._resolve(entity)
        graph = self.identity.graph_uri
        q = f"""
SELECT ?p ?o ?t WHERE {{
  GRAPH <{graph}> {{
    <{uri}> ?p ?o .
    OPTIONAL {{ <{uri}> <{P.ASSERTED_AT}> ?t . }}
  }}
  FILTER(!STRSTARTS(STR(?p), "urn:ag:meta:"))
}}"""
        rows = await self._lc._sparql_select(q)
        now = datetime.now(tz=timezone.utc)
        results = []
        for row in rows:
            p_val = row["p"]["value"]
            o_val = row["o"]["value"]
            o_is_uri = row["o"].get("type") == "uri"
            asserted_raw = row.get("t", {}).get("value")
            if asserted_raw:
                try:
                    asserted_dt = datetime.fromisoformat(asserted_raw.rstrip("Z")).replace(
                        tzinfo=timezone.utc
                    )
                    days = (now - asserted_dt).total_seconds() / 86400
                    decay_score = math.exp(-decay_lambda * days)
                except ValueError:
                    decay_score = 1.0
            else:
                decay_score = 1.0
            results.append({
                "predicate": p_val,
                "object": o_val,
                "object_is_uri": o_is_uri,
                "asserted_at": asserted_raw,
                "decay_score": round(decay_score, 4),
            })
        if sort_by_recency:
            results.sort(key=lambda r: r["decay_score"], reverse=True)
        return results

    async def check_duplicate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        object_is_uri: bool = False,
    ) -> bool:
        """동일한 (subject, predicate, object) 트리플이 이미 존재하는지 확인.

        SPARQL ASK로 exact match만 검사한다. 중복 저장 시 assertedAt이
        새 값으로 추가되는 것을 방지하기 위해 remember(skip_if_exists=True)와
        함께 사용한다.

        Args:
            subject: URI (already resolved).
            predicate: predicate URI.
            obj: 객체 값 (리터럴 또는 URI).
            object_is_uri: obj가 URI인지 여부.

        Returns:
            True이면 이미 존재.
        """
        _validate_uri(subject)
        graph = self.identity.graph_uri
        if object_is_uri:
            obj_term = f"<{obj}>"
        else:
            escaped = obj.replace("\\", "\\\\").replace('"', '\\"')
            obj_term = f'"{escaped}"'
        q = f'ASK {{ GRAPH <{graph}> {{ <{subject}> <{predicate}> {obj_term} . }} }}'
        return await self._lc._sparql_ask(q)

    async def recall_recent(self, n: int = 20) -> list[dict[str, str]]:
        """가장 최근에 기억된 주체 N개를 반환.

        assertedAt 기준 내림차순 정렬. 에이전트가 "최근에 무엇을 기억했나"를
        빠르게 파악하는 용도.

        Returns:
            [{"uri": str, "latest_asserted_at": iso_str}]
        """
        graph = self.identity.graph_uri
        q = f"""
SELECT ?s (MAX(?t) AS ?latest) WHERE {{
  GRAPH <{graph}> {{
    ?s <{P.ASSERTED_AT}> ?t .
    FILTER(STRSTARTS(STR(?s), "urn:ag:"))
  }}
}} GROUP BY ?s ORDER BY DESC(?latest) LIMIT {n}"""
        rows = await self._lc._sparql_select(q)
        return [
            {
                "uri": row["s"]["value"],
                "latest_asserted_at": row.get("latest", {}).get("value", ""),
            }
            for row in rows
        ]

    async def why(self, entity: str) -> WhyResult:
        """'왜 이 결정/개념이 존재하는가'를 설명하는 컨텍스트 반환.

        단일 UNION 쿼리로 정방향(subject 기준)과 역방향(object 기준) 트리플을
        원자적 스냅샷으로 가져온다. Fuseki TDB2의 GOSP 인덱스 덕에 역방향도
        full scan 없이 O(log N) range scan으로 처리된다.

        Args:
            entity: 엔티티 이름 또는 URI.

        Returns:
            WhyResult — rationale, made_at, decided_against, influenced_by, outgoing.
            에이전트 컨텍스트 주입은 result.to_context_str() 사용.
        """
        uri = self._resolve(entity)
        _validate_uri(uri)
        graph = self.identity.graph_uri
        meta_prefix = "urn:ag:meta:"

        q = f"""
SELECT ?dir ?s ?p ?o WHERE {{
  GRAPH <{graph}> {{
    {{
      BIND("fwd" AS ?dir)
      <{uri}> ?p ?o .
      BIND(<{uri}> AS ?s)
    }}
    UNION
    {{
      BIND("bwd" AS ?dir)
      ?s ?p <{uri}> .
      BIND(<{uri}> AS ?o)
    }}
  }}
  FILTER(!STRSTARTS(STR(?p), "{meta_prefix}"))
}}"""

        rows = await self._lc._sparql_select(q)

        rationale: list[str] = []
        made_at: str | None = None
        decided_against: list[str] = []
        influenced_by: list[Influence] = []
        outgoing: list[OutgoingEdge] = []

        for row in rows:
            direction = row.get("dir", {}).get("value", "fwd")
            p_val = row["p"]["value"]
            if direction == "bwd":
                influenced_by.append(
                    Influence(predicate=p_val, subject=row["s"]["value"])
                )
                continue
            o_node = row["o"]
            o_val = o_node["value"]
            o_is_uri = o_node.get("type") == "uri"
            if p_val == P.RATIONALE:
                rationale.append(o_val)
            elif p_val == P.MADE_AT:
                made_at = o_val
            elif p_val in (P.DECIDED_AGAINST, P.REJECTED):
                decided_against.append(o_val)
            else:
                outgoing.append(OutgoingEdge(predicate=p_val, obj=o_val, obj_is_uri=o_is_uri))

        return WhyResult(
            uri=uri,
            rationale=rationale,
            made_at=made_at,
            decided_against=decided_against,
            influenced_by=influenced_by,
            outgoing=outgoing,
        )

    async def find_path(
        self,
        from_entity: str,
        to_entity:   str,
        max_depth:   int = 3,
    ) -> list[dict[str, str]]:
        """두 엔티티 간 최단 경로 탐색 (최대 max_depth 홉).

        Returns:
            [{"from": uri, "predicate": uri, "to": uri}] 경로 엣지 목록.
            경로 없으면 빈 리스트.
        """
        from_uri = self._resolve(from_entity)
        to_uri   = self._resolve(to_entity)
        graph    = self.identity.graph_uri

        # BFS — 최대 3홉 SPARQL (깊이별 UNION)
        unions = []
        for depth in range(1, max_depth + 1):
            chain_s = " ".join(f"?n{i}" for i in range(depth - 1))
            chain_p = " ".join(f"?p{i}" for i in range(depth))
            if depth == 1:
                pattern = f"<{from_uri}> ?p0 <{to_uri}> ."
                select  = f"<{from_uri}> AS ?n0_s, ?p0, <{to_uri}> AS ?n0_e"
            else:
                nodes = [f"<{from_uri}>"] + [f"?mid{i}" for i in range(depth - 1)] + [f"<{to_uri}>"]
                preds = [f"?rel{i}" for i in range(depth)]
                pattern = " .\n    ".join(
                    f"{nodes[i]} {preds[i]} {nodes[i+1]}" for i in range(depth)
                ) + " ."
                select = ", ".join(
                    f"{nodes[i]} AS ?a{i}, {preds[i]} AS ?r{i}, {nodes[i+1]} AS ?b{i}"
                    for i in range(depth)
                )
            unions.append((depth, pattern))

        results: list[dict[str, str]] = []
        for depth, pattern in unions:
            nodes = [f"<{from_uri}>"] + [f"?mid{i}" for i in range(depth - 1)] + [f"<{to_uri}>"]
            preds = [f"?rel{i}" for i in range(depth)]
            pattern_str = "\n    ".join(
                f"{nodes[i]} {preds[i]} {nodes[i+1]} ." for i in range(depth)
            )
            select_vars = " ".join(itertools.chain.from_iterable(
                [f"?rel{i}"] + ([f"?mid{i}"] if i < depth - 1 else [])
                for i in range(depth)
            ))
            q = f"""
SELECT {select_vars} WHERE {{
  GRAPH <{graph}> {{
    {pattern_str}
  }}
}} LIMIT 1"""
            rows = await self._lc._sparql_select(q)
            if rows:
                row = rows[0]
                path_nodes = [from_uri]
                for i in range(depth - 1):
                    mid = row.get(f"mid{i}", {}).get("value", "")
                    path_nodes.append(mid)
                path_nodes.append(to_uri)
                for i in range(depth):
                    rel = row.get(f"rel{i}", {}).get("value", "")
                    results.append({
                        "from":      path_nodes[i],
                        "predicate": rel,
                        "to":        path_nodes[i + 1],
                    })
                return results  # 가장 짧은 경로만

        return []

    async def graph_stats(self, *, hub_limit: int = 10) -> GraphStats:
        """그래프 구조 건강도 통계 반환.

        시맨틱 트리플(메타 제외)만 대상으로 허브 노드, 고립 노드, 술어 분포를
        분석한다. 4개의 독립 쿼리를 asyncio.gather로 병렬 실행.

        Args:
            hub_limit: 반환할 허브 노드 상위 N개 수.

        Returns:
            GraphStats — hub_nodes, isolated_nodes, predicate_distribution 포함.
        """
        graph = self.identity.graph_uri
        meta = "urn:ag:meta:"

        counts_q = f"""
SELECT
  (COUNT(DISTINCT ?s) AS ?subjects)
  (COUNT(*) AS ?triples)
  (COUNT(DISTINCT ?p) AS ?predicates)
WHERE {{
  GRAPH <{graph}> {{
    ?s ?p ?o .
    FILTER(!STRSTARTS(STR(?p), "{meta}"))
    FILTER(STRSTARTS(STR(?s), "urn:"))
  }}
}}"""

        out_q = f"""
SELECT ?node (COUNT(*) AS ?cnt) WHERE {{
  GRAPH <{graph}> {{
    ?node ?p ?o .
    FILTER(!STRSTARTS(STR(?p), "{meta}"))
    FILTER(STRSTARTS(STR(?node), "urn:"))
  }}
}} GROUP BY ?node"""

        in_q = f"""
SELECT ?node (COUNT(*) AS ?cnt) WHERE {{
  GRAPH <{graph}> {{
    ?s ?p ?node .
    FILTER(!STRSTARTS(STR(?p), "{meta}"))
    FILTER(isURI(?node))
    FILTER(STRSTARTS(STR(?node), "urn:"))
  }}
}} GROUP BY ?node"""

        pred_q = f"""
SELECT ?p (COUNT(*) AS ?cnt) WHERE {{
  GRAPH <{graph}> {{
    ?s ?p ?o .
    FILTER(!STRSTARTS(STR(?p), "{meta}"))
  }}
}} GROUP BY ?p ORDER BY DESC(?cnt) LIMIT 15"""

        counts_rows, out_rows, in_rows, pred_rows = await asyncio.gather(
            self._lc._sparql_select(counts_q),
            self._lc._sparql_select(out_q),
            self._lc._sparql_select(in_q),
            self._lc._sparql_select(pred_q),
        )

        cr = counts_rows[0] if counts_rows else {}
        subjects = int(cr.get("subjects", {}).get("value", 0))
        triples = int(cr.get("triples", {}).get("value", 0))
        predicates = int(cr.get("predicates", {}).get("value", 0))

        out_degree: dict[str, int] = {
            row["node"]["value"]: int(row["cnt"]["value"]) for row in out_rows
        }
        in_degree: dict[str, int] = {
            row["node"]["value"]: int(row["cnt"]["value"]) for row in in_rows
        }

        degree: dict[str, int] = {}
        for uri, cnt in out_degree.items():
            degree[uri] = degree.get(uri, 0) + cnt
        for uri, cnt in in_degree.items():
            degree[uri] = degree.get(uri, 0) + cnt

        hub_nodes = [
            HubNode(uri=uri, degree=deg)
            for uri, deg in sorted(degree.items(), key=lambda x: x[1], reverse=True)[
                :hub_limit
            ]
        ]

        isolated_nodes = [
            uri
            for uri, out in out_degree.items()
            if in_degree.get(uri, 0) == 0
        ]

        avg_degree = round(sum(degree.values()) / len(degree), 2) if degree else 0.0

        pred_dist = [
            PredicateCount(predicate=row["p"]["value"], count=int(row["cnt"]["value"]))
            for row in pred_rows
        ]

        return GraphStats(
            graph=graph,
            subjects=subjects,
            triples=triples,
            predicates=predicates,
            hub_nodes=hub_nodes,
            isolated_nodes=isolated_nodes,
            predicate_distribution=pred_dist,
            avg_degree=avg_degree,
        )

    # ── 다이어리 ─────────────────────────────────────────────────────────────

    async def diary_write(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
    ) -> str:
        """자유형식 메모를 urn:ag:diary: RDF 노드로 저장.

        MemPalace의 원문 덩어리와 달리 온톨로지에 통합된 노드로 저장되어
        prune / traverse_graph / graph_stats 의 대상이 된다.

        Args:
            content: 메모 원문. 길이 제한 없음.
            tags: 선택적 태그 목록 (P.TAG 술어로 저장).

        Returns:
            생성된 다이어리 항목 URI.
        """
        from datetime import datetime, timezone

        now = datetime.now(tz=timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        slug = re.sub(r"[^a-z0-9가-힣]+", "-", content[:40].lower()).strip("-")
        session_short = self.identity.session_id[:8]
        entry_uri = f"urn:ag:diary:{date_str}:{session_short}:{slug}"

        triples: list[tuple[str, str, str, bool]] = [
            (entry_uri, P.CONTENT, content, False),
            (entry_uri, P.MADE_AT, date_str, False),
            (entry_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", P.DIARY_ENTRY, True),
        ]
        for tag in (tags or []):
            triples.append((entry_uri, P.TAG, tag, False))

        await self._lc.assert_memories(triples)
        return entry_uri

    async def diary_read(
        self,
        *,
        limit: int = 20,
        since_days: int | None = None,
    ) -> list[DiaryEntry]:
        """최근 다이어리 항목 반환.

        Args:
            limit: 반환할 최대 항목 수.
            since_days: 이 일수 이내 항목만 반환. None이면 전체.

        Returns:
            DiaryEntry 목록 (최신순).
        """
        from datetime import datetime, timedelta, timezone

        graph = self.identity.graph_uri
        rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

        date_filter = ""
        if since_days is not None:
            cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=since_days)).strftime(
                "%Y-%m-%d"
            )
            date_filter = f'FILTER(?made_at >= "{cutoff}")'

        q = f"""
SELECT ?entry ?content ?made_at WHERE {{
  GRAPH <{graph}> {{
    ?entry <{rdf_type}> <{P.DIARY_ENTRY}> .
    ?entry <{P.CONTENT}> ?content .
    ?entry <{P.MADE_AT}> ?made_at .
    {date_filter}
  }}
}} ORDER BY DESC(?made_at) LIMIT {limit}"""

        rows = await self._lc._sparql_select(q)
        if not rows:
            return []

        entry_uris = [row["entry"]["value"] for row in rows]
        base_entries = {
            row["entry"]["value"]: DiaryEntry(
                uri=row["entry"]["value"],
                content=row["content"]["value"],
                made_at=row["made_at"]["value"],
            )
            for row in rows
        }

        tags_q = f"""
SELECT ?entry ?tag WHERE {{
  GRAPH <{graph}> {{
    VALUES ?entry {{ {" ".join(f"<{u}>" for u in entry_uris)} }}
    ?entry <{P.TAG}> ?tag .
  }}
}}"""
        tag_rows = await self._lc._sparql_select(tags_q)
        tags_by_entry: dict[str, list[str]] = {}
        for tr in tag_rows:
            uri = tr["entry"]["value"]
            tags_by_entry.setdefault(uri, []).append(tr["tag"]["value"])

        return [
            base_entries[uri].model_copy(update={"tags": tags_by_entry.get(uri, [])})
            for uri in entry_uris
            if uri in base_entries
        ]

    # ── 생명주기 위임 ────────────────────────────────────────────────────────

    async def prune(self, older_than_months: int = 6, *, dry_run: bool = False) -> dict:
        return await self._lc.prune(older_than_months, dry_run=dry_run)

    async def cleanup_workspace(self, *, confirm: bool = False) -> dict:
        return await self._lc.cleanup_workspace(confirm=confirm)

    async def cleanup_project(self, project: str, *, confirm: bool = False) -> dict:
        uri = self._resolve(project)
        return await self._lc.cleanup_project(uri, confirm=confirm)

    async def dump(
        self,
        fmt: str = "turtle",
        output_path: str | None = None,
        *,
        session_only: bool = False,
    ) -> str:
        return await self._lc.dump(fmt, output_path, session_only=session_only)  # type: ignore[arg-type]

    async def stats(self) -> dict:
        return await self._lc.stats()

    async def aclose(self) -> None:
        await self._store.aclose()

    async def __aenter__(self) -> "MemoryClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _resolve(self, text: str) -> str:
        if text.startswith("urn:") or text.startswith("http"):
            return text
        return self.registry.resolve(text)
