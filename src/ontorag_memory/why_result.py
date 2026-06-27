"""WhyResult — why() API 반환 타입.

MCP 호출(텍스트 직렬화)과 Python 직접 호출(구조체)을 동시에 지원.

    result = await mem.why("urn:ag:decision:2026-06-27:mempalace-review")
    print(result.rationale)            # Python 직접 접근
    print(result.to_context_str())     # LLM 프롬프트 주입용
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Influence(BaseModel):
    """역방향 연결 — 이 엔티티를 object로 참조하는 다른 노드."""

    model_config = ConfigDict(frozen=True)

    predicate: str
    subject: str


class OutgoingEdge(BaseModel):
    """정방향 연결 — rationale/made_at/decided_against 외 나머지 관계."""

    model_config = ConfigDict(frozen=True)

    predicate: str
    obj: str
    obj_is_uri: bool = False


class WhyResult(BaseModel):
    """why() 반환값 — 엔티티가 존재하는 이유와 맥락.

    Attributes:
        uri: 정규화된 엔티티 URI.
        rationale: 근거 텍스트 목록 (urn:ag:rel:rationale).
        made_at: 결정 일자 (urn:ag:rel:madeAt), 없으면 None.
        decided_against: 기각한 대안 목록 (urn:ag:rel:decidedAgainst).
        influenced_by: 이 엔티티를 참조하는 역방향 연결.
        outgoing: rationale/made_at/decided_against 외 정방향 관계.
    """

    model_config = ConfigDict(frozen=True)

    uri: str
    rationale: list[str] = []
    made_at: str | None = None
    decided_against: list[str] = []
    influenced_by: list[Influence] = []
    outgoing: list[OutgoingEdge] = []

    def to_context_str(self) -> str:
        """에이전트 컨텍스트 주입용 마크다운 — 빈 섹션 생략, 토큰 효율 우선."""
        lines = [f"# Why: {self.uri}"]
        if self.rationale:
            lines.append("## 근거")
            lines.extend(f"- {r}" for r in self.rationale)
        if self.decided_against:
            lines.append("## 기각한 대안")
            lines.extend(f"- {d}" for d in self.decided_against)
        if self.influenced_by:
            lines.append("## 영향받음 (역방향)")
            lines.extend(
                f"- `{i.predicate}` ← {i.subject}" for i in self.influenced_by
            )
        if self.outgoing:
            lines.append("## 기타 관계")
            lines.extend(
                f"- `{e.predicate}` → {e.obj}" for e in self.outgoing
            )
        if self.made_at:
            lines.append(f"\n결정 시점: {self.made_at}")
        return "\n".join(lines)
