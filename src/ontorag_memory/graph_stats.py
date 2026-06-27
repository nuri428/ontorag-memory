"""GraphStats — 그래프 건강도 통계 반환 타입.

    stats = await mem.graph_stats()
    print(stats.to_context_str())       # 에이전트 컨텍스트 주입용
    for hub in stats.hub_nodes: ...     # Python 직접 접근
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HubNode(BaseModel):
    """시맨틱 연결이 가장 많은 노드 (in + out degree 합산)."""

    model_config = ConfigDict(frozen=True)

    uri: str
    degree: int


class PredicateCount(BaseModel):
    """술어별 사용 빈도."""

    model_config = ConfigDict(frozen=True)

    predicate: str
    count: int


class GraphStats(BaseModel):
    """graph_stats() 반환값 — 그래프 구조 건강도 요약.

    Attributes:
        graph:                  현재 named graph URI.
        subjects:               시맨틱 트리플의 고유 subject 수.
        triples:                시맨틱 트리플 총 수 (메타 제외).
        predicates:             사용된 고유 술어 수.
        hub_nodes:              연결 수 상위 노드 (in+out degree 기준).
        source_nodes:         역방향 참조가 없는 노드 URI 목록.
        predicate_distribution: 술어별 사용 빈도 (상위 15개).
        avg_degree:             노드당 평균 연결 수.
    """

    model_config = ConfigDict(frozen=True)

    graph: str
    subjects: int
    triples: int
    predicates: int
    hub_nodes: list[HubNode] = []
    source_nodes: list[str] = []
    predicate_distribution: list[PredicateCount] = []
    avg_degree: float = 0.0

    def to_context_str(self) -> str:
        """에이전트 컨텍스트 주입용 마크다운."""
        lines = [
            f"# Graph Stats: {self.graph}",
            f"- nodes: {self.subjects}  triples: {self.triples}  "
            f"predicates: {self.predicates}  avg_degree: {self.avg_degree}",
        ]
        if self.hub_nodes:
            lines.append("## 핵심 허브 노드 (degree 상위)")
            lines.extend(
                f"- {h.uri}  (degree {h.degree})" for h in self.hub_nodes
            )
        if self.source_nodes:
            lines.append(f"## 역방향 참조 없는 노드 ({len(self.source_nodes)}개)")
            lines.extend(f"- {n}" for n in self.source_nodes[:20])
            if len(self.source_nodes) > 20:
                lines.append(f"  … 외 {len(self.source_nodes) - 20}개")
        if self.predicate_distribution:
            lines.append("## 술어 사용 빈도 (상위)")
            lines.extend(
                f"- {pc.predicate}  ×{pc.count}" for pc in self.predicate_distribution
            )
        return "\n".join(lines)
