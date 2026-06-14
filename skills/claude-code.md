# ontorag-memory — Claude Code Skill

## 언제 사용하나
- 중요한 결정, 아키텍처 선택, 프로젝트 관계를 장기 메모리에 저장할 때
- 이전 대화에서 내린 결정의 근거를 조회할 때
- 두 개념/프로젝트의 연결 경로를 찾을 때
- N개월치 메모리를 정리하거나 덤프할 때

## 빠른 시작 (MCP 툴 사용)

### 기억 저장 (assert_triple)
```
assert_triple(
  subject="urn:ag:decision:2026-06-15:mcp-integration",
  predicate="urn:ag:rel:rationale",
  object="표준화된 인터페이스로 Hermes와 Claude Code 모두 지원",
  object_is_uri=False
)
assert_triple(
  subject="urn:ag:decision:2026-06-15:mcp-integration",
  predicate="urn:ag:rel:involves",
  object="urn:ag:tech:mcp",
  object_is_uri=True
)
```

### 배치 저장 (assert_triples)
```
assert_triples(triples=[
  {"subject": "urn:ag:proj:ontorag", "predicate": "urn:ag:rel:uses", "object": "urn:ag:tech:mcp", "object_is_uri": true},
  {"subject": "urn:ag:proj:ontorag", "predicate": "urn:ag:rel:dependsOn", "object": "urn:ag:tech:fuseki", "object_is_uri": true}
])
```

### 관계 탐색 (traverse_graph)
```
traverse_graph(start_uri="urn:ag:agent:hermes", max_depth=2)
```

### 경로 발견 (find_path)
```
find_path(uri_a="urn:ag:agent:hermes", uri_b="urn:ag:proj:patent-board", max_depth=3)
```

## URI 네임스페이스 규칙

| 타입 | URI 패턴 | 예시 |
|------|----------|------|
| 프로젝트 | `urn:ag:proj:{slug}` | `urn:ag:proj:ontorag` |
| 기술 | `urn:ag:tech:{slug}` | `urn:ag:tech:mcp` |
| 에이전트 | `urn:ag:agent:{slug}` | `urn:ag:agent:hermes` |
| 결정 | `urn:ag:decision:{date}:{slug}` | `urn:ag:decision:2026-06-15:mcp` |
| 개념 | `urn:ag:concept:{slug}` | `urn:ag:concept:acm` |

## 메타 predicate (자동 부착, 직접 지정 불필요)

- `urn:ag:meta:assertedAt` — 저장 시각 (xsd:dateTime)
- `urn:ag:meta:inSession` — 저장한 세션 URI
- `urn:ag:meta:workspace` — 워크스페이스 slug

## 표준 predicate

- `urn:ag:rel:dependsOn` — 의존 관계
- `urn:ag:rel:uses` — 사용 관계
- `urn:ag:rel:involves` — 관련 엔티티
- `urn:ag:rel:rationale` — 결정 근거 (리터럴)
- `urn:ag:rel:madeAt` — 결정 날짜 (리터럴, YYYY-MM-DD)
- `urn:ag:rel:relatedTo` — 일반 관련
- `rdfs:label` — 사람이 읽는 이름

## 생명주기 관리 (CLI)

```bash
ontorag-memory status                        # 현황 확인
ontorag-memory prune --months 6 --dry-run   # 6개월 이상 만료 예정 확인
ontorag-memory prune --months 6             # 실제 삭제
ontorag-memory cleanup project "ontorag" --confirm
ontorag-memory cleanup workspace --confirm
ontorag-memory dump --format turtle --output memory.ttl
ontorag-memory dump --session-only          # 이번 세션만
```
