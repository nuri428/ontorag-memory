"""DiaryEntry — 에이전트 다이어리 반환 타입.

구조화하기 어려운 자유형식 메모를 RDF 노드로 저장.
MemPalace의 원문 덩어리와 달리 urn:ag:diary: 네임스페이스 노드로 온톨로지에 통합.

    await mem.diary_write("Fuseki union graph는 느림. describe_entity가 더 빠름.")
    entries = await mem.diary_read(limit=10)
    print(entries[0].to_context_str())
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DiaryEntry(BaseModel):
    """에이전트 일지 항목.

    Attributes:
        uri:      urn:ag:diary:{date}:{slug} 형식 URI.
        content:  자유형식 메모 원문.
        made_at:  기록 일자 (YYYY-MM-DD).
        tags:     선택적 태그 목록.
    """

    model_config = ConfigDict(frozen=True)

    uri: str
    content: str
    made_at: str
    tags: list[str] = []

    def to_context_str(self) -> str:
        tag_str = f"  [{', '.join(self.tags)}]" if self.tags else ""
        return f"[{self.made_at}{tag_str}] {self.content}"
