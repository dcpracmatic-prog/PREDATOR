"""PREDATOR MCP adapter. Install with ``pip install 'predator[mcp]'`` and run ``predator-mcp``.

The adapter deliberately calls the same validated request handlers as the HTTP API.
It uses stdio transport so an MCP client can launch it as a local subprocess.
"""
from __future__ import annotations

from typing import Any


def _handlers():
    from predator.api.app import handle_request
    return handle_request


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit(
            "PREDATOR MCP needs the official MCP SDK. Install it with: "
            "python -m pip install 'predator[mcp]'"
        ) from exc

    server = FastMCP("PREDATOR")

    @server.tool()
    def predator_status() -> dict[str, Any]:
        """Return PREDATOR engine and MORPH availability status."""
        code, _, body = _handlers()("GET", "/v1/status")
        if code >= 400:
            raise ValueError(body.get("error", "status request failed"))
        return body

    @server.tool()
    def plan_independent_set(
        n: int,
        edges: list[list[int]],
        directed: bool = False,
        method: str = "auto",
        budget_ms: int = 100,
        seed: int = 1,
        auto_n_threshold: int = 1500,
    ) -> dict[str, Any]:
        """Plan and verify an independent node set for a graph.

        Nodes must be numbered 0..n-1; edges are [source, target] pairs.
        Methods are auto, gwmin, or morph. The result includes verified and trace.
        """
        request = {"graph": {"n": n, "edges": edges, "directed": directed},
                   "method": method, "budget_ms": budget_ms, "seed": seed,
                   "auto_n_threshold": auto_n_threshold}
        code, _, body = _handlers()("POST", "/v1/plan", request)
        if code >= 400:
            raise ValueError(f"{body.get('error')}: {body.get('details', [])}")
        return body

    @server.tool()
    def audit_graph(
        n: int,
        edges: list[list[int]],
        directed: bool = False,
        method: str = "auto",
        budget_ms: int = 100,
        seed: int = 1,
        include_dense: bool = True,
        k_core_k: int = 3,
        graph_source: str | None = None,
        sign: bool = True,
        key_id: str = "hmac:default",
    ) -> dict[str, Any]:
        """Run validated graph audit and return the ztge.audit.v1 report.

        Signing uses the existing ZTGE_HMAC_SECRET environment setting. If no
        signing key is configured, the report is returned unsigned.
        """
        request = {"graph": {"n": n, "edges": edges, "directed": directed},
                   "method": method, "budget_ms": budget_ms, "seed": seed,
                   "include_dense": include_dense, "k_core_k": k_core_k,
                   "graph_source": graph_source, "sign": sign, "key_id": key_id}
        code, _, body = _handlers()("POST", "/v1/audit", request)
        if code >= 400:
            raise ValueError(f"{body.get('error')}: {body.get('details', [])}")
        return body

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
