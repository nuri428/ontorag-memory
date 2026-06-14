# ontorag-memory-context

## 설명
Claude Code가 대화 시작 시 온톨로지 그래프에서 프로젝트 컨텍스트를 자동 로드하는 스킬.
플랫 파일 메모리 대신 `urn:ontorag:greennuri_claudecode:data` named graph를 사용한다.

## 트리거 조건
- 새 대화 시작 시 (프로젝트 관련 작업이 예상될 때)
- "이전에 어떤 결정을 했지?", "왜 X를 선택했나?" 등 과거 맥락 질문 시
- 새 기능 제안 전 (기각된 대안과 충돌하는지 확인)

## 실행 절차

> **주의:** `ontology` 파라미터 없이 호출하면 union graph(전체)를 조회.
> `traverse_graph` 결과에 `urn:ag:meta:*` 엣지(inSession, assertedAt 등)가
> 포함되며 이는 메타데이터 노이즈 — 무시하고 `urn:ag:rel:*` 엣지만 사용할 것.

### Step 1 — 프로젝트 현황 로드 (병렬 호출 권장)
```
describe_entity(uri="urn:ag:proj:ontorag")
describe_entity(uri="urn:ag:proj:ontorag-flow")
describe_entity(uri="urn:ag:proj:ontorag-memory")
describe_entity(uri="urn:ag:proj:patent-board")
```

### Step 2 — 오늘 날짜 결정 조회
```
# 오늘 결정의 허브 노드에서 출발 (날짜를 YYYY-MM-DD로 교체)
traverse_graph(
  start_uri="urn:ag:decision:YYYY-MM-DD:ontology-as-memory",
  max_depth=1
)
```

### Step 3 — 핵심 관계 확인
```
find_path(uri_a="urn:ag:agent:hermes", uri_b="urn:ag:proj:patent-board", max_depth=3)
```

### Step 4 — 기각된 대안 확인 (새 제안 충돌 방지)
```
describe_entity(uri="urn:ag:decision:2026-06:rejected-stock")
describe_entity(uri="urn:ag:decision:2026-06:rejected-secom")
describe_entity(uri="urn:ag:decision:2026-06:rejected-tep")
```

## 새 메모리 저장 방법

대화 중 중요한 결정/사실이 생기면 플랫 파일 대신 MCP 툴로 저장:

```
# 단일 트리플
assert_triple(
  subject="urn:ag:decision:YYYY-MM-DD:slug",
  predicate="urn:ag:rel:label",
  object="결정 내용"
)
assert_triple(
  subject="urn:ag:decision:YYYY-MM-DD:slug",
  predicate="urn:ag:rel:rationale",
  object="왜 이 결정을 내렸나"
)
assert_triple(
  subject="urn:ag:decision:YYYY-MM-DD:slug",
  predicate="urn:ag:rel:madeAt",
  object="YYYY-MM-DD"
)

# 관계 연결
assert_triple(
  subject="urn:ag:decision:YYYY-MM-DD:slug",
  predicate="urn:ag:rel:involves",
  object="urn:ag:proj:관련프로젝트",
  object_is_uri=True
)
```

## URI 규칙

| 타입 | 패턴 |
|------|------|
| 결정 | `urn:ag:decision:YYYY-MM-DD:slug` |
| 프로젝트 | `urn:ag:proj:slug` |
| 기술 | `urn:ag:tech:slug` |
| 에이전트 | `urn:ag:agent:slug` |
| 개념 | `urn:ag:concept:slug` |

## 핵심 predicate (P 클래스)

| 의미 | URI |
|------|-----|
| 레이블 | `http://www.w3.org/2000/01/rdf-schema#label` |
| 결정 근거 | `urn:ag:rel:rationale` |
| 날짜 | `urn:ag:rel:madeAt` |
| 관련 엔티티 | `urn:ag:rel:involves` |
| 의존 관계 | `urn:ag:rel:dependsOn` |
| 사용 기술 | `urn:ag:rel:uses` |
| 관련 | `urn:ag:rel:relatedTo` |
| 레이어 | `urn:ag:rel:layer` |
| 설명 | `urn:ag:rel:description` |

## 그래프 정보

- **Named graph:** `urn:ontorag:greennuri_claudecode:data`
- **MCP 서버:** `ontorag-mcp` (stdio, Fuseki localhost:3030)
- **현재 규모:** 약 16 subject, 109 트리플
- **백업:** `ontorag-memory dump --format turtle`
