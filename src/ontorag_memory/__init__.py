"""ontorag-memory — AI 에이전트를 위한 온톨로지 기반 구조화 메모리 레이어.

Quick start:
    from ontorag_memory import MemoryClient
    from ontorag.stores.fuseki import FusekiStore

    store = FusekiStore.from_env()
    mem = MemoryClient(store)                  # 자동 identity 감지
    await mem.remember("ontorag", "uses", "MCP", object_is_uri=True)
    path = await mem.find_path("Hermes Agent", "patent_board")
"""

from ontorag_memory.client import MemoryClient
from ontorag_memory.identity import AgentIdentity
from ontorag_memory.lifecycle import MemoryLifecycle
from ontorag_memory.registry import EntityRegistry, P

__version__ = "0.1.0"
__all__ = [
    "MemoryClient",
    "AgentIdentity",
    "MemoryLifecycle",
    "EntityRegistry",
    "P",
]
