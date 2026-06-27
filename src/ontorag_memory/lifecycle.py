"""메모리 생명주기 관리 — prune / cleanup / dump.

직접 사용보다 MemoryClient를 통한 사용을 권장.
"""

from __future__ import annotations

import os
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from ontorag_memory.identity import AgentIdentity
from ontorag_memory.registry import P


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cutoff_iso(months: int) -> str:
    dt = datetime.now(tz=UTC) - timedelta(days=months * 30)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class MemoryLifecycle:
    """메모리 저장 / TTL 정리 / 워크스페이스 삭제 / 덤프."""

    def __init__(self, store: Any, identity: AgentIdentity) -> None:
        self._store = store
        self._id = identity

    # ── 저장 ─────────────────────────────────────────────────────────────────

    async def assert_memory(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        object_is_uri: bool = False,
        ttl_months: int | None = None,
    ) -> None:
        """assertedAt + inSession + workspace 메타를 자동 부착해서 저장."""
        now = _now_iso()
        triples: list[tuple[str, str, str, bool]] = [
            (subject, predicate, obj, object_is_uri),
            (subject, P.ASSERTED_AT, now, False),
            (subject, P.IN_SESSION, self._id.session_uri, True),
            (subject, P.WORKSPACE, self._id.workspace, False),
        ]
        if ttl_months is not None:
            dt = datetime.now(tz=UTC) + timedelta(days=ttl_months * 30)
            triples.append((subject, P.EXPIRES_AT, dt.strftime("%Y-%m-%dT%H:%M:%SZ"), False))
        await self._store.assert_triples(triples, ontology=self._id.ontology_id)

    async def assert_memories(
        self,
        triples: list[tuple[str, str, str, bool]],
        *,
        ttl_months: int | None = None,
    ) -> int:
        """여러 트리플을 배치 저장. 각 subject에 메타 자동 부착."""
        now = _now_iso()
        enriched: list[tuple[str, str, str, bool]] = []
        seen: set[str] = set()
        for s, p, o, is_uri in triples:
            enriched.append((s, p, o, is_uri))
            if s not in seen:
                enriched.append((s, P.ASSERTED_AT, now, False))
                enriched.append((s, P.IN_SESSION, self._id.session_uri, True))
                enriched.append((s, P.WORKSPACE, self._id.workspace, False))
                if ttl_months is not None:
                    dt = datetime.now(tz=UTC) + timedelta(days=ttl_months * 30)
                    enriched.append((s, P.EXPIRES_AT, dt.strftime("%Y-%m-%dT%H:%M:%SZ"), False))
                seen.add(s)
        await self._store.assert_triples(enriched, ontology=self._id.ontology_id)
        return len(triples)

    # ── Prune ─────────────────────────────────────────────────────────────────

    async def prune(
        self,
        older_than_months: int = 6,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """N개월 이상 된 노드와 그 트리플을 삭제.

        Args:
            older_than_months: 이 기간보다 오래된 노드 삭제.
            dry_run: True이면 삭제 없이 대상 수량만 반환.

        Returns:
            {"subjects": N, "triples": M, "dry_run": bool}
        """
        cutoff = _cutoff_iso(older_than_months)
        graph = self._id.graph_uri
        xsd_dt = "http://www.w3.org/2001/XMLSchema#dateTime"

        count_q = f"""
SELECT (COUNT(DISTINCT ?s) AS ?subjects) (COUNT(*) AS ?triples)
WHERE {{
  GRAPH <{graph}> {{
    ?s <{P.ASSERTED_AT}> ?t .
    FILTER(?t < "{cutoff}"^^<{xsd_dt}>)
    ?s ?p ?o .
  }}
}}"""
        rows = await self._sparql_select(count_q)
        subjects_n = int(rows[0].get("subjects", {}).get("value", 0)) if rows else 0
        triples_n  = int(rows[0].get("triples",  {}).get("value", 0)) if rows else 0

        if dry_run or subjects_n == 0:
            return {"subjects": subjects_n, "triples": triples_n, "dry_run": True}

        delete_q = f"""
DELETE {{ GRAPH <{graph}> {{ ?s ?p ?o . }} }}
WHERE {{
  GRAPH <{graph}> {{
    ?s <{P.ASSERTED_AT}> ?t .
    FILTER(?t < "{cutoff}"^^<{xsd_dt}>)
    ?s ?p ?o .
  }}
}}"""
        await self._store._sparql_update(delete_q)
        return {"subjects": subjects_n, "triples": triples_n, "dry_run": False}

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def cleanup_workspace(self, *, confirm: bool = False) -> dict[str, Any]:
        """현재 워크스페이스 named graph 전체 삭제."""
        if not confirm:
            return {
                "graph": self._id.graph_uri,
                "deleted": False,
                "message": "confirm=True 로 재호출해야 실제 삭제됩니다.",
            }
        removed = await self._store.clear_graph("data", ontology=self._id.ontology_id)
        return {
            "graph": self._id.graph_uri,
            "deleted": True,
            "triples_removed": removed.get("data", 0),
        }

    async def cleanup_project(
        self,
        project_uri: str,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """project_uri가 subject 또는 object인 트리플 삭제 (직접 연결만)."""
        graph = self._id.graph_uri
        count_q = f"""
SELECT (COUNT(*) AS ?n) WHERE {{
  GRAPH <{graph}> {{
    {{ <{project_uri}> ?p ?o . }}
    UNION
    {{ ?s ?p <{project_uri}> . }}
  }}
}}"""
        rows = await self._sparql_select(count_q)
        count = int(rows[0].get("n", {}).get("value", 0)) if rows else 0

        if not confirm:
            return {
                "project_uri": project_uri,
                "triples_to_delete": count,
                "deleted": False,
                "message": "confirm=True 로 재호출해야 실제 삭제됩니다.",
            }
        if count == 0:
            return {"project_uri": project_uri, "triples_deleted": 0, "deleted": True}

        delete_q = f"""
DELETE {{ GRAPH <{graph}> {{ ?s ?p ?o . }} }}
WHERE {{
  GRAPH <{graph}> {{
    {{ <{project_uri}> ?p ?o . BIND(<{project_uri}> AS ?s) }}
    UNION
    {{ ?s ?p <{project_uri}> . BIND(?o AS ?o) }}
  }}
}}"""
        await self._store._sparql_update(delete_q)
        return {"project_uri": project_uri, "triples_deleted": count, "deleted": True}

    # ── Dump ─────────────────────────────────────────────────────────────────

    async def dump(
        self,
        fmt: Literal["turtle", "jsonld", "ntriples"] = "turtle",
        output_path: str | None = None,
        *,
        session_only: bool = False,
    ) -> str:
        """메모리를 파일로 내보내기.

        Args:
            fmt: 출력 포맷.
            output_path: 저장 경로. None이면 자동 생성.
            session_only: 현재 세션 트리플만 내보내기.

        Returns:
            저장된 파일 경로.
        """
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = {"turtle": "ttl", "jsonld": "jsonld", "ntriples": "nt"}[fmt]
            suffix = f"_session_{self._id.session_id}" if session_only else ""
            output_path = (
                f"memory_{self._id.user}_{self._id.workspace}{suffix}_{ts}.{ext}"
            )

        if session_only:
            session_uri = self._id.session_uri
            graph = self._id.graph_uri
            construct_q = f"""
CONSTRUCT {{ ?s ?p ?o }}
WHERE {{
  GRAPH <{graph}> {{
    ?s <{P.IN_SESSION}> <{session_uri}> .
    ?s ?p ?o .
  }}
}}"""
            content = await self._sparql_construct(construct_q, fmt)
        else:
            fmt_map = {"turtle": "turtle", "jsonld": "json-ld", "ntriples": "nt"}
            raw = await self._store.dump_graph(fmt_map[fmt], ontology=self._id.ontology_id)
            content = raw.decode() if isinstance(raw, bytes) else raw

        Path(output_path).write_text(content, encoding="utf-8")
        return output_path

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        """현재 메모리 현황 통계."""
        graph = self._id.graph_uri
        q = f"""
SELECT
  (COUNT(DISTINCT ?s) AS ?subjects)
  (COUNT(*) AS ?triples)
  (MIN(?t) AS ?oldest)
  (MAX(?t) AS ?newest)
WHERE {{
  GRAPH <{graph}> {{
    OPTIONAL {{ ?s <{P.ASSERTED_AT}> ?t . }}
    ?s ?p ?o .
  }}
}}"""
        rows = await self._sparql_select(q)
        if not rows:
            return {"subjects": 0, "triples": 0}
        row = rows[0]
        return {
            "graph":    graph,
            "identity": str(self._id),
            "subjects": int(row.get("subjects", {}).get("value", 0)),
            "triples":  int(row.get("triples",  {}).get("value", 0)),
            "oldest":   row.get("oldest", {}).get("value", "—"),
            "newest":   row.get("newest", {}).get("value", "—"),
        }

    # ── 내부 SPARQL 유틸 ──────────────────────────────────────────────────────

    def _sparql_endpoint(self) -> tuple[str, httpx.BasicAuth]:
        """Fuseki SPARQL 엔드포인트 URL과 BasicAuth를 반환.

        환경 변수가 설정되지 않으면 기본값("admin"/"admin")을 사용하되 경고 발생.
        """
        user = os.environ.get("FUSEKI_USER", "")
        password = os.environ.get("FUSEKI_PASSWORD", "")
        if not user or not password:
            warnings.warn(
                "FUSEKI_USER / FUSEKI_PASSWORD 환경 변수가 설정되지 않아 기본값 사용 중. "
                "프로덕션 배포 시 반드시 설정하세요.",
                stacklevel=3,
            )
            user = user or "admin"
            password = password or "admin"

        url = (
            f"{os.environ.get('FUSEKI_URL', 'http://localhost:3030')}"
            f"/{os.environ.get('FUSEKI_DATASET', 'ontorag')}/sparql"
        )
        return url, httpx.BasicAuth(user, password)

    async def _sparql_select(self, query: str) -> list[dict]:
        url, auth = self._sparql_endpoint()
        async with httpx.AsyncClient(auth=auth, timeout=15.0) as client:
            resp = await client.post(
                url,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            return resp.json()["results"]["bindings"]

    async def _sparql_ask(self, query: str) -> bool:
        url, auth = self._sparql_endpoint()
        async with httpx.AsyncClient(auth=auth, timeout=15.0) as client:
            resp = await client.post(
                url,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            return resp.json().get("boolean", False)

    async def _sparql_construct(self, query: str, fmt: str) -> str:
        accept = {
            "turtle":   "text/turtle",
            "jsonld":   "application/ld+json",
            "ntriples": "application/n-triples",
        }[fmt]
        url, auth = self._sparql_endpoint()
        async with httpx.AsyncClient(auth=auth, timeout=15.0) as client:
            resp = await client.post(
                url, data={"query": query}, headers={"Accept": accept}
            )
            resp.raise_for_status()
            return resp.text
