"""AgentIdentity 유닛 테스트."""

from __future__ import annotations

from ontorag_memory.identity import AgentIdentity, _workspace_slug
from ontorag_memory.registry import EntityRegistry


def test_ontology_id_format():
    identity = AgentIdentity(user="greennuri", workspace="ws-ontorag")
    assert identity.ontology_id == "greennuri_ws-ontorag"


def test_graph_uri_format():
    identity = AgentIdentity(user="greennuri", workspace="ws-ontorag")
    assert identity.graph_uri == "urn:ontorag:greennuri_ws-ontorag:data"


def test_session_uri_contains_session_id():
    identity = AgentIdentity(user="greennuri", workspace="ws-ontorag", session_id="abc123")
    assert "abc123" in identity.session_uri
    assert identity.uri_prefix in identity.session_uri


def test_entity_uri():
    identity = AgentIdentity(user="greennuri", workspace="ws-ontorag")
    uri = identity.entity_uri("decision", "2026-06-15", "mcp")
    assert uri.startswith(identity.uri_prefix)
    assert "decision" in uri
    assert "2026-06-15" in uri


def test_workspace_slug_two_parts():
    slug = _workspace_slug("/Users/nuri/dev/git/ws/ontorag")
    assert slug == "ws-ontorag"


def test_workspace_slug_underscores_normalized():
    slug = _workspace_slug("/Users/nuri/dev/my_project")
    assert "_" not in slug


def test_different_users_different_graphs():
    a = AgentIdentity(user="alice", workspace="ws-ontorag")
    b = AgentIdentity(user="bob",   workspace="ws-ontorag")
    assert a.graph_uri != b.graph_uri


def test_different_workspaces_different_graphs():
    a = AgentIdentity(user="greennuri", workspace="ws-ontorag")
    b = AgentIdentity(user="greennuri", workspace="ws-other")
    assert a.graph_uri != b.graph_uri


def test_same_user_workspace_same_graph_different_sessions():
    """세션이 달라도 같은 그래프 — 메모리가 공유됨 (의도된 동작)."""
    a = AgentIdentity(user="greennuri", workspace="ws-ontorag", session_id="s1")
    b = AgentIdentity(user="greennuri", workspace="ws-ontorag", session_id="s2")
    assert a.graph_uri == b.graph_uri
    assert a.session_uri != b.session_uri


def test_registry_resolve():
    reg = EntityRegistry()
    assert reg.resolve("patent board")          == "urn:ag:proj:patent-board"
    assert reg.resolve("patent_board")          == "urn:ag:proj:patent-board"
    assert reg.resolve("OntoRAG")               == "urn:ag:proj:ontorag"
    assert reg.resolve("Model Context Protocol") == "urn:ag:tech:mcp"
    assert reg.resolve("헤르메스")               == "urn:ag:agent:hermes"


def test_registry_unknown_term_auto_slug():
    reg = EntityRegistry()
    uri = reg.resolve("my unknown concept")
    assert uri.startswith("urn:ag:entity:")
    assert "unknown" in uri
