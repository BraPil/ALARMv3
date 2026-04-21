"""MCP smoke tests — verify tool/resource/prompt registration without stdio."""

import asyncio
import json
import os

import pytest

# Import the assembled FastMCP instance
from alarmv3.mcp.server import mcp


# ── Server identity ───────────────────────────────────────────────────────────

def test_server_name():
    assert mcp.name == "alarmv3"


# ── Tool registration ─────────────────────────────────────────────────────────

EXPECTED_TOOLS = {
    "attach_repository",
    "confirm_guardrails",
    "start_full_mapping",
    "get_job_status",
    "run_analysis",
    "generate_recommendations",
    "query_codebase",
    "review_recommendations",
    "plan_implementation",
    "clone_for_implementation",
    "implement_next",
    "accept_change",
    "reject_change",
    # Phase 5
    "implement_batch",
    "record_project_memory",
    "list_project_memory",
    "get_autopilot_policy",
    "register_repo",
    "query_cross_repo",
}


def test_all_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    registered = {t.name for t in tools}
    assert EXPECTED_TOOLS <= registered


def test_tool_count():
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == len(EXPECTED_TOOLS)


def test_attach_repository_has_description():
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "attach_repository")
    assert tool.description
    assert len(tool.description) > 20


def test_attach_repository_has_source_path_param():
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "attach_repository")
    schema = tool.inputSchema
    assert "source_path" in schema.get("properties", {})


# ── Resource registration ─────────────────────────────────────────────────────

EXPECTED_RESOURCES = {
    "session://current",
    "manifest://files",
    "recommendations://latest",
    "recommendations://evaluated",
    "implementation://plan",
    "implementation://changes",
}


def test_all_resources_registered():
    resources = asyncio.run(mcp.list_resources())
    registered = {str(r.uri) for r in resources}
    assert EXPECTED_RESOURCES <= registered


# ── Prompt registration ───────────────────────────────────────────────────────

EXPECTED_PROMPTS = {"analyze_codebase", "explain_component"}


def test_all_prompts_registered():
    prompts = asyncio.run(mcp.list_prompts())
    registered = {p.name for p in prompts}
    assert EXPECTED_PROMPTS <= registered


# ── Resource callables (no active session) ────────────────────────────────────

def test_session_resource_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv("ALARMV3_WORKSPACE", str(tmp_path))
    resources = asyncio.run(mcp.list_resources())
    uri = next(r.uri for r in resources if str(r.uri) == "session://current")
    result = asyncio.run(mcp.read_resource(uri))
    data = json.loads(result[0].text if hasattr(result[0], "text") else result[0].content)
    assert data["state"] == "UNATTACHED"


def test_manifest_resource_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv("ALARMV3_WORKSPACE", str(tmp_path))
    resources = asyncio.run(mcp.list_resources())
    uri = next(r.uri for r in resources if str(r.uri) == "manifest://files")
    result = asyncio.run(mcp.read_resource(uri))
    content = result[0].text if hasattr(result[0], "text") else result[0].content
    assert json.loads(content) == []


def test_recommendations_resource_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv("ALARMV3_WORKSPACE", str(tmp_path))
    resources = asyncio.run(mcp.list_resources())
    uri = next(r.uri for r in resources if str(r.uri) == "recommendations://latest")
    result = asyncio.run(mcp.read_resource(uri))
    content = result[0].text if hasattr(result[0], "text") else result[0].content
    assert json.loads(content) == []
