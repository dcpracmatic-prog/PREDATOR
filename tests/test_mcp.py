"""MCP contract tests against the shared validated handlers."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _call(name: str, args: dict, env: dict[str, str] | None = None):
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "predator.predator_server"], env=env or os.environ.copy())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {"predator_status", "plan_independent_set", "audit_graph"} <= {t.name for t in tools.tools}
            return await session.call_tool(name, args)


def _run(name: str, args: dict, env: dict[str, str] | None = None):
    return asyncio.run(_call(name, args, env))


def _json(result):
    assert not result.isError
    return json.loads("\n".join(c.text for c in result.content if hasattr(c, "text")))


def test_mcp_status_and_planning_contract():
    status = _json(_run("predator_status", {}))
    assert status["engine"] == "predator"
    assert {"available", "binary", "reason"} <= set(status["morph"])
    result = _json(_run("plan_independent_set", {
        "n": 4, "edges": [[0, 1], [1, 2], [2, 3]], "method": "gwmin"}))
    assert result["verified"] is True
    assert "resolved" in result["trace"]
    assert _run("plan_independent_set", {"n": 2, "edges": [[0, 9]]}).isError


def test_mcp_audit_preserves_schema_and_predator_identity():
    env = os.environ.copy(); env["ZTGE_HMAC_SECRET"] = "hex:" + "ab" * 32
    body = _json(_run("audit_graph", {
        "n": 3, "edges": [[0, 1], [1, 2]], "method": "gwmin", "sign": True}, env))
    assert body["report"]["schema_version"] == "ztge.audit.v1"
    assert body["report"]["engine"]["name"] == "predator"
    assert body["signed"] is True
    assert body["envelope"]["envelope_version"] == "ztge.envelope.v1"
    assert body["envelope"]["producer"]["service"] == "predator"
