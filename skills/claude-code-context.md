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

---

## Python API (ontorag-memory 패키지)

ontorag-memory를 직접 사용하는 에이전트 코드(예: Hermes, ontorag-flow)에서는
`MemoryClient`로 아래 API를 호출한다.

### 기본 패턴

```python
from ontorag_memory.client import MemoryClient

async with await MemoryClient.create() as mem:
    # 아래 모든 API 사용 가능
    ...
```

### why() — 엔티티 존재 근거 조회

```python
result = await mem.why("urn:ag:proj:ontorag-memory")
# 또는 레지스트리 단축명도 가능
result = await mem.why("ontorag-memory")

print(result.rationale)         # "Why-first 온톨로지 메모리"
print(result.decided_against)   # ["flat-file", "vector-db"]
print(result.influenced_by)     # ["urn:ag:agent:hermes"]
print(result.to_context_str())  # 마크다운 형식 (LLM 컨텍스트 주입용)
```

CLI:
```bash
ontorag-memory why urn:ag:proj:ontorag-memory
ontorag-memory why ontorag-memory   # 레지스트리 단축명
```

### graph_stats() — 그래프 구조 건강도

```python
stats = await mem.graph_stats(hub_limit=10)

print(stats.subjects)    # 노드 수
print(stats.triples)     # 트리플 수
print(stats.avg_degree)  # 평균 연결 수
print(stats.hub_nodes)   # [HubNode(uri=..., degree=N), ...]
print(stats.isolated_nodes)          # 역방향 참조 없는 노드 목록
print(stats.predicate_distribution)  # [PredicateCount(predicate=..., count=N)]
print(stats.to_context_str())        # 마크다운 (LLM 주입용)
```

CLI:
```bash
ontorag-memory graph-stats
ontorag-memory graph-stats --hubs 20  # 상위 20개 허브 노드
```

### diary_write() / diary_read() — 자유형식 메모

```python
# 기록
uri = await mem.diary_write(
    "오늘 SPARQL OPTIONAL 버그를 찾았다",
    tags=["bug", "sparql"]
)

# 조회
entries = await mem.diary_read(limit=20, since_days=7)
for entry in entries:
    print(entry.content)
    print(entry.tags)
    print(entry.created_at)
    print(entry.to_context_str())  # 마크다운 (LLM 주입용)
```

CLI:
```bash
ontorag-memory diary write "오늘 발견한 것" --tag bug --tag sparql
ontorag-memory diary list --limit 10 --since 7
```

### check_duplicate() — 중복 존재 여부 확인

```python
exists = await mem.check_duplicate(
    "urn:ag:proj:ontorag",   # subject
    "urn:ag:rel:label",      # predicate
    "ontorag"                # object
)
# True이면 이미 동일 트리플 존재
```

### remember(skip_if_exists=True) — 중복 방지 저장

```python
await mem.remember(
    "urn:ag:decision:2026-06-27:why-fuseki",
    "urn:ag:rel:rationale",
    "SPARQL 표준 준수 및 named graph 지원",
    skip_if_exists=True  # 이미 있으면 저장 생략
)
```

### recall() — 시간 감쇠 점수 포함 조회

```python
results = await mem.recall("ontorag-memory")

for r in results:
    print(r.subject)       # URI
    print(r.predicate)
    print(r.object)
    print(r.asserted_at)   # ISO 날짜
    print(r.decay_score)   # exp(-λ * days) — 최신일수록 1.0에 가까움
```

### recall_recent() — 최근 N개 트리플

```python
triples = await mem.recall_recent(n=50)  # 기본 20, 최대 1000
```

---

## CLI 명령 전체 목록

```bash
ontorag-memory status          # identity + 메모리 현황
ontorag-memory prune           # 오래된 노드 삭제 (기본 6개월)
ontorag-memory prune --dry-run # 삭제 대상 수량만 확인
ontorag-memory why <entity>    # 엔티티 존재 근거 출력
ontorag-memory graph-stats     # 그래프 건강도 통계
ontorag-memory diary write <content> [--tag TAG ...]
ontorag-memory diary list [--limit N] [--since DAYS]
ontorag-memory cleanup workspace --confirm
ontorag-memory cleanup project <uri> --confirm
ontorag-memory dump [--format turtle|jsonld|ntriples] [--output FILE]
ontorag-memory setup [--agent hermes|claude-code]
```

---

## URI 규칙

| 타입 | 패턴 |
|------|------|
| 결정 | `urn:ag:decision:YYYY-MM-DD:slug` |
| 프로젝트 | `urn:ag:proj:slug` |
| 기술 | `urn:ag:tech:slug` |
| 에이전트 | `urn:ag:agent:slug` |
| 개념 | `urn:ag:concept:slug` |
| 다이어리 | `urn:ag:diary:YYYY-MM-DD:HHMMSS:session:slug` |

## 핵심 predicate (P 클래스)

| 의미 | URI |
|------|-----|
| 레이블 | `http://www.w3.org/2000/01/rdf-schema#label` |
| 결정 근거 | `urn:ag:rel:rationale` |
| 기각된 대안 | `urn:ag:rel:decidedAgainst` |
| 영향받은 엔티티 | `urn:ag:rel:influencedBy` |
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
