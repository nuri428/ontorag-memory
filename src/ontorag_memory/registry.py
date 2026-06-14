"""EntityRegistry — free-text → canonical URI 노말라이저.

사용자 정의 registry.yaml을 추가하거나 기본 레지스트리를 확장 가능.

    registry = EntityRegistry()                         # 기본 레지스트리
    registry = EntityRegistry("/path/to/custom.yaml")  # 커스텀
    registry = EntityRegistry.merged("custom.yaml")    # 기본 + 커스텀 병합

    registry.resolve("patent board")  # → "urn:ag:proj:patent-board"
    registry.resolve("MCP 서버")       # → "urn:ag:tech:mcp"
    registry.label_of("urn:ag:tech:mcp")  # → "MCP"
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_REGISTRY = Path(__file__).parent / "default" / "registry.yaml"


class EntityRegistry:
    """엔티티 alias → canonical URI 매핑 레지스트리."""

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self._canonical: dict[str, dict[str, Any]] = {}
        self._alias_map: dict[str, str] = {}
        path = Path(registry_path) if registry_path else _DEFAULT_REGISTRY
        self._load(path)

    def _load(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for entry in data.get("entities", []):
            uri = entry["uri"]
            self._canonical[uri] = entry
            for alias in entry.get("aliases", []):
                self._alias_map[alias] = uri
                self._alias_map[alias.lower()] = uri

    @classmethod
    def merged(cls, extra_path: str | Path) -> "EntityRegistry":
        """기본 레지스트리에 추가 YAML을 병합한 레지스트리."""
        instance = cls()           # 기본 먼저
        instance._load(Path(extra_path))  # 추가 항목 덮어쓰기
        return instance

    def resolve(self, text: str) -> str:
        """free-text → canonical URI. 미등록 시 자동 slug URI 생성."""
        if text in self._alias_map:
            return self._alias_map[text]
        lower = text.lower()
        if lower in self._alias_map:
            return self._alias_map[lower]
        slug = re.sub(r"[^a-z0-9가-힣]+", "-", lower).strip("-")
        return f"urn:ag:entity:{slug}"

    def label_of(self, uri: str) -> str:
        """canonical URI → 사람이 읽을 수 있는 레이블."""
        meta = self._canonical.get(uri)
        return meta["label"] if meta else uri.split(":")[-1]

    def all_uris(self) -> list[str]:
        return list(self._canonical.keys())

    def __contains__(self, text: str) -> bool:
        return text in self._alias_map or text.lower() in self._alias_map


class P:
    """Predicate URI 상수 모음 — SPARQL injection 방지용."""

    # 표준
    LABEL        = "http://www.w3.org/2000/01/rdf-schema#label"
    TYPE         = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    # 관계
    DEPENDS_ON   = "urn:ag:rel:dependsOn"
    USES         = "urn:ag:rel:uses"
    INVOLVES     = "urn:ag:rel:involves"
    ENABLES      = "urn:ag:rel:enables"
    RELATED_TO   = "urn:ag:rel:relatedTo"
    LAYER        = "urn:ag:rel:layer"
    TARGET       = "urn:ag:rel:dogfoodTarget"
    RATIONALE    = "urn:ag:rel:rationale"
    MADE_AT      = "urn:ag:rel:madeAt"
    REJECTED     = "urn:ag:rel:rejectedAlternative"
    DESCRIPTION  = "urn:ag:rel:description"
    VERSION      = "urn:ag:rel:version"
    CONCEPT      = "urn:ag:rel:concept"
    # 생명주기 메타
    ASSERTED_AT  = "urn:ag:meta:assertedAt"
    IN_SESSION   = "urn:ag:meta:inSession"
    WORKSPACE    = "urn:ag:meta:workspace"
    EXPIRES_AT   = "urn:ag:meta:expiresAt"
