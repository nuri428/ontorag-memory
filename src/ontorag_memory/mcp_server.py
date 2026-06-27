"""ontorag-memory stdio MCP 서버.

Claude Code / Hermes 등 MCP 클라이언트가 ontorag-memory의 모든 API를
stdio 프로토콜로 호출할 수 있게 한다.

엔트리포인트: ``ontorag-mcp`` → ``ontorag_memory.mcp_server:main``

설정 예 (Claude Code ~/.claude/claude_desktop_config.json):

    {
      "mcpServers": {
        "ontorag-memory": {
          "command": "ontorag-mcp",
          "env": {
            "FUSEKI_URL": "http://localhost:3030",
            "ONTORAG_USER": "greennuri",
            "ONTORAG_WORKSPACE": "claudecode"
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _to_jsonable(obj: Any) -> Any:
    """Pydantic BaseModel, dict, list → JSON 직렬화 가능 타입으로 변환."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


_TOOLS: dict[str, dict[str, Any]] = {
    "remember": {
        "description": (
            "에이전트 메모리에 (subject, predicate, object) 트리플을 저장한다. "
            "결정, 근거, 관계, 의존 관계 등을 온톨로지 노드로 영속화한다. "
            "subject/object는 'urn:ag:...' URI 또는 레지스트리 단축명 사용 가능. "
            "predicate는 'urn:ag:rel:...' URI 권장 (rationale, dependsOn, uses, relatedTo 등)."
        ),
        "properties": {
            "subject": {"type": "string", "description": "주체 URI 또는 레지스트리 이름."},
            "predicate": {"type": "string", "description": "술어 URI (urn:ag:rel:...)."},
            "object": {"type": "string", "description": "객체 — 리터럴 문자열 또는 URI."},
            "object_is_uri": {
                "type": "boolean",
                "default": False,
                "description": "object가 URI인 경우 true.",
            },
            "ttl_months": {
                "type": "integer",
                "description": "자동 만료 개월 수 (없으면 영구 보존).",
            },
            "skip_if_exists": {
                "type": "boolean",
                "default": False,
                "description": "동일 트리플이 이미 있으면 저장 생략.",
            },
        },
        "required": ["subject", "predicate", "object"],
    },
    "recall": {
        "description": (
            "엔티티에 연결된 모든 트리플을 시간 감쇠 스코어 포함해 반환한다. "
            "decay_score = exp(-λ × days) — 최신 사실이 1.0에 가깝다. "
            "페이지네이션: limit + offset 조합."
        ),
        "properties": {
            "entity": {"type": "string", "description": "엔티티 URI 또는 레지스트리 이름."},
            "limit": {"type": "integer", "description": "최대 반환 수 (1–10000). 생략하면 전체."},
            "offset": {"type": "integer", "default": 0, "description": "결과 시작 위치."},
        },
        "required": ["entity"],
    },
    "recall_recent": {
        "description": "가장 최근에 기억된 subject URI N개를 최신순으로 반환한다.",
        "properties": {
            "n": {"type": "integer", "default": 20, "description": "반환할 항목 수 (1–1000)."},
        },
        "required": [],
    },
    "why": {
        "description": (
            "엔티티가 왜 존재하는지 — 근거(rationale), 기각 대안(decided_against), "
            "역방향 영향(influenced_by), 관련 관계(outgoing)를 반환한다. "
            "to_context_str 필드에 LLM 프롬프트 주입용 마크다운이 포함된다."
        ),
        "properties": {
            "entity": {"type": "string", "description": "엔티티 URI 또는 레지스트리 이름."},
        },
        "required": ["entity"],
    },
    "find_path": {
        "description": "두 엔티티 간 최단 경로를 반환한다 (최대 max_depth 홉).",
        "properties": {
            "from_entity": {"type": "string", "description": "출발 엔티티."},
            "to_entity": {"type": "string", "description": "도착 엔티티."},
            "max_depth": {"type": "integer", "default": 3, "description": "최대 홉 수."},
        },
        "required": ["from_entity", "to_entity"],
    },
    "find_related": {
        "description": (
            "특정 술어로 연결된 이웃 엔티티를 탐색한다. "
            "direction: out(→), in(←), both(양방향)."
        ),
        "properties": {
            "entity": {"type": "string", "description": "기준 엔티티."},
            "predicate": {"type": "string", "description": "탐색할 술어 URI."},
            "direction": {
                "type": "string",
                "enum": ["out", "in", "both"],
                "default": "out",
            },
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["entity", "predicate"],
    },
    "search_by_rationale": {
        "description": (
            "근거·내용·레이블·설명·태그 필드에서 키워드로 전문 검색한다. "
            "대소문자 구분 없음. SPARQL 인젝션 방지 이스케이프 적용."
        ),
        "properties": {
            "keyword": {"type": "string", "description": "검색할 키워드."},
            "limit": {"type": "integer", "default": 20, "description": "최대 결과 수 (1–1000)."},
        },
        "required": ["keyword"],
    },
    "diary_write": {
        "description": (
            "자유형식 메모를 urn:ag:diary: 노드로 저장한다. "
            "구조화하기 어려운 관찰, 버그, 학습 내용에 사용."
        ),
        "properties": {
            "content": {"type": "string", "description": "메모 내용."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "선택적 태그 목록.",
            },
        },
        "required": ["content"],
    },
    "diary_read": {
        "description": "최근 다이어리 항목을 조회한다.",
        "properties": {
            "limit": {"type": "integer", "default": 20, "description": "최대 항목 수 (1–1000)."},
            "since_days": {
                "type": "integer",
                "description": "최근 N일 이내 항목만. 생략하면 전체.",
            },
        },
        "required": [],
    },
    "graph_stats": {
        "description": (
            "그래프 구조 건강도 통계 — 노드 수, 트리플 수, 허브 노드, "
            "고립 노드, 술어 빈도 분포를 반환한다."
        ),
        "properties": {
            "hub_limit": {
                "type": "integer",
                "default": 10,
                "description": "허브 노드 상위 N개.",
            },
        },
        "required": [],
    },
    "stats": {
        "description": "기본 메모리 통계 — subjects, triples, oldest, newest를 반환한다.",
        "properties": {},
        "required": [],
    },
    "find_path_transitive": {
        "description": (
            "특정 술어로 전이적으로 연결된 모든 노드 URI를 반환한다. "
            "SPARQL property path `+`를 사용하므로 find_path()의 BFS와 달리 "
            "중간 경로 엣지가 아닌 '닿을 수 있는 노드' 전체를 한 번에 반환한다. "
            "direction: out(entity→) 또는 in(→entity)."
        ),
        "properties": {
            "entity": {"type": "string", "description": "시작 엔티티 URI 또는 레지스트리 이름."},
            "predicate": {"type": "string", "description": "전이적으로 따라갈 술어 URI."},
            "direction": {
                "type": "string",
                "enum": ["out", "in"],
                "default": "out",
            },
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["entity", "predicate"],
    },
    "summarize": {
        "description": (
            "엔티티에 대한 종합 마크다운 요약 반환 — why() + recall() 결합. "
            "LLM 컨텍스트 주입에 최적화된 단일 문자열로 반환한다."
        ),
        "properties": {
            "entity": {"type": "string", "description": "엔티티 URI 또는 레지스트리 이름."},
        },
        "required": ["entity"],
    },
    "remember_bulk": {
        "description": (
            "dict 배열로 여러 트리플을 한 번에 저장한다. "
            "각 항목: {subject, predicate, object, object_is_uri(선택)}. "
            "remember()의 배치 버전 — MCP 호출에 최적화."
        ),
        "properties": {
            "triples": {
                "type": "array",
                "description": "저장할 트리플 목록.",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                        "object_is_uri": {"type": "boolean", "default": False},
                    },
                    "required": ["subject", "predicate", "object"],
                },
            },
            "ttl_months": {
                "type": "integer",
                "description": "자동 만료 개월 수 (없으면 영구).",
            },
        },
        "required": ["triples"],
    },
    "prune": {
        "description": "N개월 이상 된 노드 또는 TTL이 만료된 노드를 삭제한다.",
        "properties": {
            "older_than_months": {
                "type": "integer",
                "default": 6,
                "description": "이 개월 수 이상 된 노드 삭제.",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "True이면 삭제하지 않고 대상 수만 반환.",
            },
        },
        "required": [],
    },
}


async def _dispatch(mem: Any, name: str, args: dict[str, Any]) -> Any:
    """MCP 툴 이름 → MemoryClient 메서드 라우팅."""
    if name == "remember":
        stored = await mem.remember(
            args["subject"],
            args["predicate"],
            args["object"],
            object_is_uri=args.get("object_is_uri", False),
            ttl_months=args.get("ttl_months"),
            skip_if_exists=args.get("skip_if_exists", False),
        )
        return {"stored": stored}

    if name == "recall":
        kwargs: dict[str, Any] = {}
        if "limit" in args:
            kwargs["limit"] = args["limit"]
        if "offset" in args:
            kwargs["offset"] = args["offset"]
        return await mem.recall(args["entity"], **kwargs)

    if name == "recall_recent":
        return await mem.recall_recent(n=args.get("n", 20))

    if name == "why":
        result = await mem.why(args["entity"])
        payload = result.model_dump()
        payload["context"] = result.to_context_str()
        return payload

    if name == "find_path":
        return await mem.find_path(
            args["from_entity"],
            args["to_entity"],
            max_depth=args.get("max_depth", 3),
        )

    if name == "find_related":
        return await mem.find_related(
            args["entity"],
            args["predicate"],
            direction=args.get("direction", "out"),
            limit=args.get("limit", 100),
        )

    if name == "search_by_rationale":
        return await mem.search_by_rationale(
            args["keyword"],
            limit=args.get("limit", 20),
        )

    if name == "diary_write":
        uri = await mem.diary_write(
            args["content"],
            tags=args.get("tags"),
        )
        return {"uri": uri}

    if name == "diary_read":
        entries = await mem.diary_read(
            limit=args.get("limit", 20),
            since_days=args.get("since_days"),
        )
        return [e.model_dump() for e in entries]

    if name == "graph_stats":
        stats = await mem.graph_stats(hub_limit=args.get("hub_limit", 10))
        payload = stats.model_dump()
        payload["context"] = stats.to_context_str()
        return payload

    if name == "stats":
        return await mem.stats()

    if name == "find_path_transitive":
        return await mem.find_path_transitive(
            args["entity"],
            args["predicate"],
            direction=args.get("direction", "out"),
            limit=args.get("limit", 100),
        )

    if name == "summarize":
        return await mem.summarize(args["entity"])

    if name == "remember_bulk":
        count = await mem.remember_bulk(
            args["triples"],
            ttl_months=args.get("ttl_months"),
        )
        return {"stored": count}

    if name == "prune":
        return await mem.prune(
            args.get("older_than_months", 6),
            dry_run=args.get("dry_run", False),
        )

    raise ValueError(f"Unknown tool: {name}")


def build_server():
    """ontorag-memory 툴이 등록된 MCP Server 인스턴스를 반환한다."""
    import mcp.types as types  # noqa: I001,PLC0415
    from mcp.server import Server  # noqa: I001,PLC0415

    server: Server = Server("ontorag-memory")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=spec["description"],
                inputSchema={
                    "type": "object",
                    "properties": spec["properties"],
                    "required": spec["required"],
                },
            )
            for name, spec in _TOOLS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        from ontorag_memory.client import MemoryClient  # noqa: I001,PLC0415

        mem = await MemoryClient.create()
        try:
            result = await _dispatch(mem, name, arguments or {})
            payload = _to_jsonable(result)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(payload, ensure_ascii=False, default=str),
                )
            ]
        except Exception as exc:
            logger.exception("ontorag-memory MCP tool %s failed", name)
            detail: dict[str, Any] = {"error": str(exc), "type": exc.__class__.__name__}
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(detail, ensure_ascii=False, default=str),
                )
            ]
        finally:
            try:
                await mem.aclose()
            except Exception:  # noqa: BLE001
                pass

    return server


def main() -> None:
    """콘솔 엔트리포인트 — stdio MCP 서버를 실행하고 블록한다."""
    import asyncio  # noqa: PLC0415

    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    async def _run() -> None:
        from mcp.server.stdio import stdio_server  # noqa: PLC0415

        server = build_server()
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
