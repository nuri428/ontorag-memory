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

### recall() 페이지네이션 (P2)

```python
# 첫 페이지 (decay 정렬 후 상위 10개)
page1 = await mem.recall("ontorag-memory", limit=10)

# 두 번째 페이지
page2 = await mem.recall("ontorag-memory", limit=10, offset=10)
```

### find_related() — 연결된 엔티티 탐색 (P2)

```python
# 특정 술어로 연결된 이웃 엔티티 (outgoing)
results = await mem.find_related(
    "urn:ag:proj:ontorag-memory",
    "urn:ag:rel:dependsOn",
    direction="out",   # "out" | "in" | "both"
    limit=100,
)
# [{"uri": "urn:ag:proj:fuseki", "direction": "out"}, ...]
```

CLI:
```bash
ontorag-memory find-related urn:ag:proj:ontorag-memory urn:ag:rel:dependsOn
ontorag-memory find-related urn:ag:proj:ontorag-memory urn:ag:rel:dependsOn --direction both
```

### search_by_rationale() — 전문 검색 (P2)

```python
# 근거/내용/레이블/설명에서 키워드 검색 (대소문자 무시)
results = await mem.search_by_rationale("Fuseki", limit=20)
# [{"subject": uri, "predicate": uri, "snippet": str}, ...]
```

CLI:
```bash
ontorag-memory search "Fuseki"
ontorag-memory search "온톨로지" --limit 10
```

### find_path_transitive() — 전이적 순회 (P2)

SPARQL property path `+`를 써서 술어를 따라 도달 가능한 모든 노드를 한 번에 조회.

```python
# patent-board가 involves로 연결된 모든 인시던트 URI
all_incidents = await mem.find_path_transitive(
    "urn:ag:proj:patent-board",
    "urn:ag:rel:involves",
    direction="in",   # "out" | "in" (both 불가)
    limit=100,
)
# ["urn:ag:incident:2026-06-27:api-timeout", ...]

# ontorag-memory가 의존하는 모든 기술 (전이적)
deps = await mem.find_path_transitive(
    "urn:ag:proj:ontorag-memory",
    "urn:ag:rel:dependsOn",
    direction="out",
)
```

> `direction="both"`는 지원하지 않는다 — SPARQL property path `+`는 단방향이기 때문.

### summarize() — 엔티티 요약 (P2)

`why()` + `recall()` 을 병렬로 실행하고 마크다운 요약을 반환한다.
LLM 컨텍스트 주입 시 두 번 호출하는 대신 단일 호출로 대체.

```python
summary = await mem.summarize("urn:ag:incident:2026-06-27:api-timeout")
# 반환: str (마크다운)
# # Why: urn:ag:incident:...
# ## 근거
# Fuseki 쿼리 타임아웃: IPC 분류 JOIN이 인덱스 없이 실행됨.
#
# ## 최근 트리플 (10개)
# | urn:ag:rel:rationale | Fuseki 쿼리 타임아웃... |

# LLM 컨텍스트에 주입
system_prompt = f"...\n\n{await mem.summarize(entity_uri)}"
```

### remember_bulk() — 배치 저장 (P2)

트리플 배열을 한 번에 저장. `record_incident()` 같이 여러 술어를 한꺼번에 기록할 때 사용.

```python
count = await mem.remember_bulk([
    {
        "subject": "urn:ag:incident:2026-06-27:api-timeout",
        "predicate": "urn:ag:rel:rationale",
        "object": "Fuseki 쿼리 타임아웃: IPC JOIN 인덱스 없음",
    },
    {
        "subject": "urn:ag:incident:2026-06-27:api-timeout",
        "predicate": "urn:ag:rel:involves",
        "object": "urn:ag:proj:patent-board",
        "object_is_uri": True,  # URI 객체면 True
    },
], ttl_months=24)   # 선택적 TTL
# 반환: 저장된 트리플 수 (int)
```

`object_is_uri=True`는 객체가 리터럴이 아니라 URI일 때만 설정.
생략하면 `False`(문자열 리터럴).

---

## MCP stdio 서버 (ontorag-mcp)

위 Python API를 MCP 프로토콜로 노출. Claude Desktop, Hermes 에이전트 등이 소비.

```bash
# 실행 (pyproject.toml에 entrypoint 등록됨)
ontorag-mcp

# Claude Desktop ~/.claude/claude_desktop_config.json:
{
  "mcpServers": {
    "ontorag-memory": {
      "command": "uv",
      "args": ["--directory", "/path/to/ontorag-memory", "run", "ontorag-mcp"],
      "env": {
        "FUSEKI_URL": "http://localhost:3030",
        "ONTORAG_USER": "greennuri",
        "ONTORAG_WORKSPACE": "claudecode"
      }
    }
  }
}
```

노출되는 MCP 툴 (15개):
`remember`, `recall`, `recall_recent`, `why`, `find_path`,
`find_related`, `search_by_rationale`, `diary_write`, `diary_read`,
`graph_stats`, `stats`, `prune`,
`find_path_transitive`, `summarize`, `remember_bulk`

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
ontorag-memory find-related <entity> <predicate> [--direction out|in|both] [--limit N]
ontorag-memory search <keyword> [--limit N]
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
