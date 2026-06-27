# ontorag-memory

> **English | [한국어](README.ko.md)**

![status](https://img.shields.io/badge/status-alpha-orange)
![python](https://img.shields.io/badge/python-3.12+-blue)
![license](https://img.shields.io/badge/license-MIT-green)

> ⚠️ **Personal exploration, not a supported product.** ontorag-memory is a
> solo open-source project. The code is MIT-licensed and you are welcome to
> fork, read, and adapt it — but there is **no production support, no SLA,
> and no commitment to backwards compatibility**.

**Structured agent memory layer over [ontorag](https://github.com/nuri428/ontorag) —
ontology-backed persistent memory for AI agents (Claude Code, Hermes, and any MCP-compatible agent).**

```
Agent (Claude Code / Hermes / any MCP-compatible client)
          │
          │  MCP stdio  (ontorag-mcp — 15 tools)
          ▼
  ontorag-memory
  ├── EntityRegistry   free-text → canonical URI  (normalisation)
  ├── AgentIdentity    user + workspace + session  (isolation)
  ├── MemoryClient     remember / recall / find_path / summarize / …  (high-level API)
  └── MemoryLifecycle  prune / cleanup / dump  (lifecycle management)
          │
          │  ontorag[mcp]
          ▼
  Apache Jena Fuseki  (RDF named-graph per user+workspace)
```

---

## The problem with flat-file agent memory

Most agent frameworks store memory as plain-text files (`~/.hermes/`, Claude's
`memory/*.md`, etc.). These are unstructured heaps of experience:

| Capability | Flat-file memory | ontorag-memory |
|---|---|---|
| Single-fact lookup | ✓ keyword search | ✓ SPARQL |
| Date-scoped queries ("decisions on 2026-06-15") | ✗ unparsed text | ✓ structured predicate |
| Multi-hop path discovery | ✗ impossible | ✓ `find_path` / `find_path_transitive` |
| Decision provenance ("why did we choose X?") | ✗ no structure | ✓ `why()` + `rationale` triple |
| Token-efficient retrieval | ✗ reads whole files | ✓ returns only query results |
| Per-agent isolation (multi-instance) | ✗ shared directory | ✓ named graph per user+workspace |
| TTL / expiry | ✗ manual | ✓ `prune(older_than_months=6)` |
| LLM context injection | ✗ paste raw text | ✓ `summarize()` → single markdown call |
| Bulk write | ✗ loop + error-prone | ✓ `remember_bulk([...])` |

The structural advantage appears on **multi-hop reasoning**, **provenance tracking**,
and **cross-session continuity** — not simple lookups.

---

## Quick start

### Install

```bash
pip install ontorag-memory
# or
uv add ontorag-memory
```

Requires a running ontorag instance (Fuseki backend):

```bash
# inside the ontorag repo
docker compose up -d
```

### Configure your agent (one command)

```bash
# Claude Code
ontorag-memory setup --agent claude-code

# Hermes Agent
ontorag-memory setup --agent hermes
```

The setup command auto-detects your `git config user.email` and current
working directory, then prints the exact snippet to add to your agent's
MCP config.

### MCP stdio server (`ontorag-mcp`)

`ontorag-mcp` is the stdio entrypoint that exposes all 15 memory tools
over the MCP protocol. Any MCP-compatible client can consume it.

**Claude Desktop** — add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ontorag-memory": {
      "command": "uv",
      "args": ["--directory", "/path/to/ontorag-memory", "run", "ontorag-mcp"],
      "env": {
        "FUSEKI_URL": "http://localhost:3030",
        "ONTORAG_USER": "yourname",
        "ONTORAG_WORKSPACE": "myproject"
      }
    }
  }
}
```

**Exposed tools (15):**
`remember`, `recall`, `recall_recent`, `why`, `find_path`,
`find_related`, `search_by_rationale`, `diary_write`, `diary_read`,
`graph_stats`, `stats`, `prune`,
`find_path_transitive`, `summarize`, `remember_bulk`

### Python API

```python
from ontorag_memory import MemoryClient, P

async with await MemoryClient.create() as mem:
    # Store a decision with automatic timestamp + session tag
    await mem.remember("ontorag-flow", P.DEPENDS_ON, "ontorag")
    await mem.remember(
        "urn:ag:decision:2026-06-15:mcp-integration",
        P.RATIONALE,
        "Standardised interface supports both Claude Code and Hermes",
    )

    # Bulk write — store multiple triples in one call
    await mem.remember_bulk([
        {"subject": "urn:ag:incident:2026-06-27:api-timeout",
         "predicate": P.RATIONALE, "object": "Fuseki IPC JOIN missing index"},
        {"subject": "urn:ag:incident:2026-06-27:api-timeout",
         "predicate": P.INVOLVES, "object": "urn:ag:proj:patent-board",
         "object_is_uri": True},
    ])

    # Recall everything about an entity
    facts = await mem.recall("ontorag-flow")

    # Multi-hop path discovery
    path = await mem.find_path("Hermes Agent", "patent_board")
    # → Hermes Agent --[relatedTo]--> SRE --[involves]--> patent_board

    # Transitive closure — all nodes reachable via a predicate chain
    incidents = await mem.find_path_transitive(
        "urn:ag:proj:patent-board", P.INVOLVES, direction="in"
    )
    # → ["urn:ag:incident:2026-06-27:api-timeout", ...]

    # Single-call LLM context injection (why + recent triples combined)
    summary = await mem.summarize("urn:ag:proj:ontorag-memory")
    # → "# Why: urn:ag:proj:ontorag-memory\n## 근거\n..."

    # Graph health stats
    stats = await mem.graph_stats()
    print(stats.source_nodes)   # nodes with no incoming edges

    # Lifecycle
    await mem.prune(older_than_months=6, dry_run=True)
    await mem.dump(fmt="turtle", output_path="backup.ttl")
```

---

## Identity and isolation

Multiple Claude Code or Hermes instances on the same server each get their
own **named graph** in Fuseki — no memory cross-contamination.

```
user + workspace  →  ontology_id  →  named graph
─────────────────────────────────────────────────────────────────────────
greennuri + ws-ontorag  →  greennuri_ws-ontorag  →  urn:ontorag:greennuri_ws-ontorag:data
greennuri + other-proj  →  greennuri_other-proj   →  urn:ontorag:greennuri_other-proj:data
alice     + ws-ontorag  →  alice_ws-ontorag        →  urn:ontorag:alice_ws-ontorag:data
```

`session_id` is a per-process tag — same user+workspace memories are visible
**across sessions** (persistent long-term memory), but you can filter by
session for "what did this conversation do?".

Identity is auto-detected from `git config user.email` and `os.getcwd()`.
Override with env vars:

```bash
export ONTORAG_USER=greennuri
export ONTORAG_WORKSPACE=ws-ontorag
```

---

## Entity normalisation

Raw text → canonical URI before storage. Prevents `"patent board"`, `"patent_board"`,
and `"PatentBoard"` from becoming three different graph nodes.

```python
from ontorag_memory import EntityRegistry

reg = EntityRegistry()
reg.resolve("patent board")           # → urn:ag:proj:patent-board
reg.resolve("Model Context Protocol") # → urn:ag:tech:mcp
reg.resolve("헤르메스")               # → urn:ag:agent:hermes
```

The default `registry.yaml` covers common AI/tech terms. Extend it:

```python
reg = EntityRegistry.merged("my_domain.yaml")
```

---

## Lifecycle management

```bash
ontorag-memory status                           # identity + stats

ontorag-memory prune --months 6 --dry-run      # preview expiry
ontorag-memory prune --months 6                # delete old nodes

ontorag-memory cleanup project "ontorag" --confirm   # project triples
ontorag-memory cleanup workspace --confirm           # entire graph

ontorag-memory dump --format turtle --output backup.ttl
ontorag-memory dump --session-only             # current session only
```

---

## URI namespace convention

| Type | Pattern | Example |
|---|---|---|
| Project | `urn:ag:proj:{slug}` | `urn:ag:proj:ontorag` |
| Technology | `urn:ag:tech:{slug}` | `urn:ag:tech:mcp` |
| Agent | `urn:ag:agent:{slug}` | `urn:ag:agent:hermes` |
| Decision | `urn:ag:decision:{date}:{slug}` | `urn:ag:decision:2026-06-15:mcp` |
| Concept | `urn:ag:concept:{slug}` | `urn:ag:concept:acm` |

Standard predicates live in `ontorag_memory.registry.P`:
`P.DEPENDS_ON`, `P.USES`, `P.INVOLVES`, `P.RATIONALE`, `P.MADE_AT`, …

Lifecycle meta-predicates are auto-attached by `MemoryClient.remember()`:
`urn:ag:meta:assertedAt`, `urn:ag:meta:inSession`, `urn:ag:meta:workspace`.

---

## Stack position

```
┌────────────────────────────┐   ┌────────────────────────────┐
│  ontorag                   │   │  ontorag-flow              │
│  Semantic + Dynamic layer  │   │  Kinetic layer (ACM)       │
│  RDF / Bayesian / Causal   │ ← │  Actions / Orchestration   │
└────────────────────────────┘   └────────────────────────────┘
             ↑                                ↑
             └──────────── MCP ───────────────┘
                              ↑
             ┌────────────────┴──────────────────┐
             │  ontorag-memory  (this repo)       │
             │  Agent memory layer                │
             │  Claude Code · Hermes · any agent  │
             └───────────────────────────────────┘
```

ontorag-memory sits **above** ontorag (uses its MCP write tools) and is
independent of ontorag-flow. It works with or without the Kinetic layer.

---

## Contributing

```bash
# Install dev dependencies
uv sync --extra dev

# Unit tests only — no live backend required
uv run pytest tests/ -m "not integration"

# Integration tests — requires live backends
#   Fuseki:   docker compose up -d   (inside the ontorag repo)
#   ontorag:  ontorag serve          (inside the ontorag repo)
uv run pytest tests/ -m integration
```

### Integration test mark

Tests marked `integration` require live backends and are excluded by default:

| Mark target | Backend required |
|---|---|
| `assert_triple` / `retract_triple` round-trip | Fuseki on `:3030` |
| `MemoryClient.remember` / `recall` / `find_path` | Fuseki on `:3030` |
| `MemoryLifecycle.dump` (full graph export) | Fuseki on `:3030` |
| ontorag HTTP MCP tools | ontorag API on `:8000` |

```bash
# CI default — unit tests only
uv run pytest -m "not integration"

# Full suite with live Fuseki
FUSEKI_URL=http://localhost:3030 uv run pytest -m integration
```

---

## Related

- [ontorag](https://github.com/nuri428/ontorag) — Ontology-aware RAG framework (Semantic + Dynamic layer)
- [ontorag-flow](https://github.com/nuri428/ontorag-flow) — Adaptive Case Management (Kinetic layer)
- [Hermes Agent](https://hermes-agent.org) — Self-hosted autonomous AI agent with MCP support

---

## License

MIT — see [LICENSE](LICENSE).
