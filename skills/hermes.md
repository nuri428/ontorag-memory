# ontorag-memory — Hermes Agent Skill

## 설명
ontorag 지식 그래프를 Hermes의 구조화 메모리로 사용.
태스크 시작/완료를 케이스로 기록하고, 과거 결정을 관계 탐색으로 조회.

## 설치
```bash
pip install ontorag-memory
ontorag-memory setup --agent hermes   # ~/.hermes/config.yaml에 MCP 설정 추가
```

## 언제 쓰나
- 중요한 결정을 내렸을 때: `assert_triple`로 기록
- "전에 이 문제 어떻게 풀었지?": `traverse_graph`로 관련 결정 조회
- 두 개념의 연결이 궁금할 때: `find_path`로 경로 탐색

## 사용 패턴

### 1. 태스크 시작 시 기록
```
assert_triple(
  subject="urn:ag:task:2026-06-15:hermes-setup",
  predicate="rdfs:label",
  object="Hermes + ontorag MCP 연동 설정"
)
assert_triple(
  subject="urn:ag:task:2026-06-15:hermes-setup",
  predicate="urn:ag:rel:involves",
  object="urn:ag:agent:hermes",
  object_is_uri=true
)
```

### 2. 완료 후 결과 기록
```
assert_triple(
  subject="urn:ag:task:2026-06-15:hermes-setup",
  predicate="urn:ag:rel:rationale",
  object="~/.hermes/config.yaml에 ontorag MCP 서버 추가로 해결"
)
```

### 3. 유사 과거 케이스 조회
```
traverse_graph(
  start_uri="urn:ag:tech:mcp",
  max_depth=2
)
```

## MCP 서버 설정 (자동 생성된 값)

ontorag-memory setup --agent hermes 실행 결과를 ~/.hermes/config.yaml에 추가.
