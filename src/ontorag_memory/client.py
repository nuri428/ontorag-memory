"""MemoryClient — ontorag-memory 통합 진입점.

identity + registry + lifecycle 을 하나로 묶어 쉽게 사용.

    mem = await MemoryClient.create()
    await mem.remember("ontorag-flow", "dependsOn", "ontorag")
    await mem.remember("Hermes Agent", "relatedTo", "SRE")
    path = await mem.find_path("Hermes", "patent_board")
    st   = await mem.stats()
"""

from __future__ import annotations

import os
from typing import Any

from ontorag_memory.identity import AgentIdentity
from ontorag_memory.lifecycle import MemoryLifecycle
from ontorag_memory.registry import EntityRegistry, P


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
    ) -> None:
        """텍스트 → 노말라이즈 → 메타 자동 부착 저장.

        object_is_uri가 None이면 obj가 등록된 엔티티면 URI, 아니면 리터럴.

        Args:
            subject: 엔티티 이름 또는 URI.
            predicate: predicate URI (P.xxx 상수 사용 권장).
            obj: 객체 값 (엔티티 이름, URI, 또는 리터럴 문자열).
            object_is_uri: 명시적 URI 여부. None이면 레지스트리 검색으로 판단.
            ttl_months: 이 기간 후 자동 만료 (None이면 영구).
        """
        s = self._resolve(subject)
        if object_is_uri is None:
            object_is_uri = obj in self.registry or obj.startswith("urn:")
        o = self._resolve(obj) if object_is_uri else obj
        await self._lc.assert_memory(s, predicate, o, object_is_uri=object_is_uri, ttl_months=ttl_months)

    async def remember_many(
        self,
        triples: list[tuple[str, str, str]],
        *,
        ttl_months: int | None = None,
    ) -> int:
        """여러 (subject, predicate, object) 튜플을 배치 저장.

        object가 레지스트리에 있으면 URI로, 없으면 리터럴로 자동 판단.
        """
        resolved: list[tuple[str, str, str, bool]] = []
        for s_text, p, o_text in triples:
            s = self._resolve(s_text)
            is_uri = o_text in self.registry or o_text.startswith("urn:")
            o = self._resolve(o_text) if is_uri else o_text
            resolved.append((s, p, o, is_uri))
        return await self._lc.assert_memories(resolved, ttl_months=ttl_months)

    # ── 조회 ─────────────────────────────────────────────────────────────────

    async def recall(self, entity: str) -> list[dict[str, str]]:
        """엔티티에 연결된 모든 트리플 반환 (메타 제외).

        Returns:
            [{"predicate": uri, "object": value, "object_is_uri": bool}]
        """
        uri = self._resolve(entity)
        graph = self.identity.graph_uri
        meta_prefixes = ("urn:ag:meta:",)
        q = f"""
SELECT ?p ?o WHERE {{
  GRAPH <{graph}> {{
    <{uri}> ?p ?o .
  }}
}}"""
        rows = await self._lc._sparql_select(q)
        results = []
        for row in rows:
            p = row["p"]["value"]
            if any(p.startswith(m) for m in meta_prefixes):
                continue
            o_val  = row["o"]["value"]
            o_type = row["o"].get("type", "literal")
            results.append({
                "predicate":    p,
                "object":       o_val,
                "object_is_uri": o_type == "uri",
            })
        return results

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
            select_vars = " ".join(
                [f"?rel{i}"] + ([f"?mid{i}"] if i < depth - 1 else [])
                for i in range(depth)
            )
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
