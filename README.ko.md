# ontorag-memory

> **[English](README.md) | 한국어**

![status](https://img.shields.io/badge/status-alpha-orange)
![python](https://img.shields.io/badge/python-3.12+-blue)
![license](https://img.shields.io/badge/license-MIT-green)

> ⚠️ **개인 탐구 프로젝트입니다. 프로덕션 지원 제품이 아닙니다.** 코드는 MIT
> 라이선스이며 포크, 학습, 수정이 자유롭습니다 — 단, **프로덕션 지원, SLA,
> 하위 호환성 보장이 없습니다**.

**[ontorag](https://github.com/nuri428/ontorag) 위에 구축된 AI 에이전트 구조화 메모리 레이어 —
Claude Code, Hermes 등 MCP 호환 에이전트를 위한 온톨로지 기반 장기 메모리.**

```
에이전트 (Claude Code / Hermes / MCP 클라이언트)
          │
          │  MCP  (assert_triple / retract_triple / traverse_graph / find_path …)
          ▼
  ontorag-memory
  ├── EntityRegistry   free-text → canonical URI  (용어 노말라이즈)
  ├── AgentIdentity    user + workspace + session  (인스턴스 격리)
  ├── MemoryClient     remember / recall / find_path  (고수준 API)
  └── MemoryLifecycle  prune / cleanup / dump  (생명주기 관리)
          │
          │  ontorag[mcp]
          ▼
  Apache Jena Fuseki  (user+workspace별 RDF named graph)
```

---

## 왜 플랫 파일 메모리가 부족한가

대부분의 에이전트 프레임워크는 메모리를 평문 파일로 저장합니다 (`~/.hermes/`, Claude의
`memory/*.md` 등). 이는 구조 없는 경험의 더미일 뿐입니다:

| 기능 | 플랫 파일 메모리 | ontorag-memory |
|---|---|---|
| 단순 사실 조회 | ✓ 키워드 검색 | ✓ SPARQL |
| 날짜 기반 쿼리 ("2026-06-15에 내린 결정") | ✗ 파싱 불가 텍스트 | ✓ 구조화된 predicate |
| 다단계 경로 발견 | ✗ 불가능 | ✓ `find_path` / `traverse_graph` |
| 결정 근거 추적 ("왜 X를 선택했나?") | ✗ 구조 없음 | ✓ `rationale` 트리플 |
| 토큰 효율적 조회 | ✗ 파일 전체 읽기 | ✓ 쿼리 결과만 반환 |
| 다중 인스턴스 격리 | ✗ 디렉토리 공유 | ✓ user+workspace별 named graph |
| TTL / 만료 | ✗ 수동 | ✓ `prune(older_than_months=6)` |

구조적 이점은 **다단계 추론**, **결정 출처 추적**, **세션 간 연속성**에서 나타납니다 — 단순 조회는 벡터 검색으로 충분합니다.

---

## 빠른 시작

### 설치

```bash
pip install ontorag-memory
# 또는
uv add ontorag-memory
```

ontorag 인스턴스(Fuseki 백엔드)가 실행 중이어야 합니다:

```bash
# ontorag 레포 안에서
docker compose up -d
```

### 에이전트 설정 (명령어 하나)

```bash
# Claude Code
ontorag-memory setup --agent claude-code

# Hermes Agent
ontorag-memory setup --agent hermes
```

setup 명령어가 `git config user.email`과 현재 디렉토리를 자동 감지해
에이전트 MCP 설정 파일에 추가할 스니펫을 출력합니다.

### Python API

```python
from ontorag_memory import MemoryClient, P

async with await MemoryClient.create() as mem:
    # 타임스탬프 + 세션 태그 자동 부착으로 저장
    await mem.remember("ontorag-flow", P.DEPENDS_ON, "ontorag")
    await mem.remember(
        "urn:ag:decision:2026-06-15:mcp-integration",
        P.RATIONALE,
        "표준화된 인터페이스로 Claude Code와 Hermes 모두 지원",
    )

    # 엔티티 관련 모든 사실 조회
    facts = await mem.recall("ontorag-flow")

    # 다단계 경로 발견 — 플랫 파일로는 불가능
    path = await mem.find_path("Hermes Agent", "patent_board")
    # → Hermes Agent --[relatedTo]--> SRE --[involves]--> patent_board

    # 생명주기
    await mem.prune(older_than_months=6, dry_run=True)
    await mem.dump(fmt="turtle", output_path="backup.ttl")
```

---

## 식별자와 격리

같은 서버에서 여러 Claude Code 또는 Hermes 인스턴스가 실행되어도
각자 Fuseki에 별도 **named graph**를 가집니다 — 메모리 교차 오염 없음.

```
user + workspace  →  ontology_id  →  named graph
────────────────────────────────────────────────────────────────────────
greennuri + ws-ontorag  →  greennuri_ws-ontorag  →  urn:ontorag:greennuri_ws-ontorag:data
greennuri + other-proj  →  greennuri_other-proj   →  urn:ontorag:greennuri_other-proj:data
alice     + ws-ontorag  →  alice_ws-ontorag        →  urn:ontorag:alice_ws-ontorag:data
```

`session_id`는 프로세스별 태그 — 같은 user+workspace 메모리는
**세션이 달라도 조회 가능**합니다(장기 기억). 특정 세션만 필터링도 가능합니다.

신원은 `git config user.email`과 `os.getcwd()`에서 자동 감지.
환경 변수로 명시적 설정:

```bash
export ONTORAG_USER=greennuri
export ONTORAG_WORKSPACE=ws-ontorag
```

---

## 용어 노말라이즈

저장 전 free-text → canonical URI 변환. `"patent board"`, `"patent_board"`,
`"PatentBoard"`가 세 개의 다른 노드가 되는 문제를 방지합니다.

```python
from ontorag_memory import EntityRegistry

reg = EntityRegistry()
reg.resolve("patent board")            # → urn:ag:proj:patent-board
reg.resolve("Model Context Protocol")  # → urn:ag:tech:mcp
reg.resolve("헤르메스")                # → urn:ag:agent:hermes
reg.resolve("hemes")                   # → urn:ag:agent:hermes  (오타도 해결)
```

기본 `registry.yaml`은 일반적인 AI/기술 용어를 포함합니다. 도메인별 확장:

```python
reg = EntityRegistry.merged("my_domain.yaml")
```

---

## 생명주기 관리

```bash
ontorag-memory status                            # 현황 확인

ontorag-memory prune --months 6 --dry-run       # 삭제 예정 미리보기
ontorag-memory prune --months 6                 # 6개월 이상 노드 삭제

ontorag-memory cleanup project "ontorag" --confirm   # 프로젝트 트리플 삭제
ontorag-memory cleanup workspace --confirm           # 워크스페이스 전체 삭제

ontorag-memory dump --format turtle --output backup.ttl
ontorag-memory dump --format jsonld
ontorag-memory dump --session-only              # 현재 세션만 내보내기
```

---

## URI 네임스페이스 규칙

| 타입 | 패턴 | 예시 |
|---|---|---|
| 프로젝트 | `urn:ag:proj:{slug}` | `urn:ag:proj:ontorag` |
| 기술 | `urn:ag:tech:{slug}` | `urn:ag:tech:mcp` |
| 에이전트 | `urn:ag:agent:{slug}` | `urn:ag:agent:hermes` |
| 결정 | `urn:ag:decision:{date}:{slug}` | `urn:ag:decision:2026-06-15:mcp` |
| 개념 | `urn:ag:concept:{slug}` | `urn:ag:concept:acm` |

표준 predicate는 `ontorag_memory.registry.P`에 상수로 정의:
`P.DEPENDS_ON`, `P.USES`, `P.INVOLVES`, `P.RATIONALE`, `P.MADE_AT`, …

생명주기 메타 predicate는 `MemoryClient.remember()` 호출 시 자동 부착:
`urn:ag:meta:assertedAt`, `urn:ag:meta:inSession`, `urn:ag:meta:workspace`.

---

## 스택 내 위치

```
┌────────────────────────────┐   ┌────────────────────────────┐
│  ontorag                   │   │  ontorag-flow              │
│  Semantic + Dynamic 레이어  │   │  Kinetic 레이어 (ACM)       │
│  RDF / Bayesian / Causal   │ ← │  액션 / 오케스트레이션       │
└────────────────────────────┘   └────────────────────────────┘
             ↑                                ↑
             └──────────── MCP ───────────────┘
                              ↑
             ┌────────────────┴──────────────────┐
             │  ontorag-memory  (이 레포)          │
             │  에이전트 메모리 레이어              │
             │  Claude Code · Hermes · 모든 에이전트│
             └───────────────────────────────────┘
```

ontorag-memory는 ontorag **위에** 위치하며(MCP write 툴 사용),
ontorag-flow와는 독립적입니다. Kinetic 레이어 없이도 사용 가능합니다.

---

## 관련 프로젝트

- [ontorag](https://github.com/nuri428/ontorag) — Ontology-aware RAG 프레임워크 (Semantic + Dynamic 레이어)
- [ontorag-flow](https://github.com/nuri428/ontorag-flow) — 적응형 케이스 관리 (Kinetic 레이어)
- [Hermes Agent](https://hermes-agent.org) — MCP 지원 자체 호스팅 자율 AI 에이전트

---

## 라이선스

MIT — [LICENSE](LICENSE) 참조.
