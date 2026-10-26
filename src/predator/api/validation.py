"""Request validation for the ZTGE HTTP API (no pydantic required)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _err(msg: str) -> Tuple[None, List[str]]:
    return None, [msg]


def validate_graph_input(raw: Any) -> Tuple[Dict[str, Any] | None, List[str]]:
    if not isinstance(raw, dict):
        return _err("graph must be an object")
    errors: List[str] = []
    if "n" not in raw:
        errors.append("graph.n is required")
    if "edges" not in raw:
        errors.append("graph.edges is required")
    if errors:
        return None, errors
    try:
        n = int(raw["n"])
    except (TypeError, ValueError):
        return _err("graph.n must be an integer")
    if n < 0:
        return _err("graph.n must be >= 0")
    edges = raw["edges"]
    if not isinstance(edges, list):
        return _err("graph.edges must be an array")
    parsed: List[Tuple[int, int]] = []
    for i, e in enumerate(edges):
        if not isinstance(e, (list, tuple)) or len(e) != 2:
            errors.append(f"graph.edges[{i}] must be [u, v]")
            continue
        try:
            u, v = int(e[0]), int(e[1])
        except (TypeError, ValueError):
            errors.append(f"graph.edges[{i}] endpoints must be integers")
            continue
        if u < 0 or v < 0 or u >= n or v >= n:
            errors.append(f"graph.edges[{i}] endpoints out of range for n={n}")
            continue
        parsed.append((u, v))
    directed = bool(raw.get("directed", False))
    if errors:
        return None, errors
    return {"n": n, "edges": parsed, "directed": directed}, []


def validate_plan_request(body: Any) -> Tuple[Dict[str, Any] | None, List[str]]:
    if not isinstance(body, dict):
        return _err("body must be a JSON object")
    g, errs = validate_graph_input(body.get("graph"))
    if errs:
        return None, errs
    method = str(body.get("method", "auto")).lower()
    if method not in ("auto", "morph", "gwmin"):
        return _err("method must be auto|morph|gwmin")
    try:
        budget_ms = int(body.get("budget_ms", 100))
        seed = int(body.get("seed", 1))
        auto_n_threshold = int(body.get("auto_n_threshold", 1500))
    except (TypeError, ValueError):
        return _err("budget_ms, seed, auto_n_threshold must be integers")
    if not (1 <= budget_ms <= 600_000):
        return _err("budget_ms out of range [1, 600000]")
    if auto_n_threshold < 1:
        return _err("auto_n_threshold must be >= 1")
    assert g is not None
    return {
        "graph": g,
        "method": method,
        "budget_ms": budget_ms,
        "seed": seed,
        "auto_n_threshold": auto_n_threshold,
    }, []


def validate_audit_request(body: Any) -> Tuple[Dict[str, Any] | None, List[str]]:
    base, errs = validate_plan_request(
        {
            "graph": body.get("graph") if isinstance(body, dict) else None,
            "method": body.get("method", "auto") if isinstance(body, dict) else "auto",
            "budget_ms": body.get("budget_ms", 100) if isinstance(body, dict) else 100,
            "seed": body.get("seed", 1) if isinstance(body, dict) else 1,
            "auto_n_threshold": body.get("auto_n_threshold", 1500)
            if isinstance(body, dict)
            else 1500,
        }
    )
    if errs or not isinstance(body, dict):
        return None, errs or ["body must be a JSON object"]
    assert base is not None
    try:
        k_core_k = int(body.get("k_core_k", 3))
    except (TypeError, ValueError):
        return _err("k_core_k must be an integer")
    if k_core_k < 1:
        return _err("k_core_k must be >= 1")
    base.update(
        {
            "sign": bool(body.get("sign", True)),
            "key_id": str(body.get("key_id", "hmac:default")),
            "include_dense": bool(body.get("include_dense", True)),
            "k_core_k": k_core_k,
            "graph_source": body.get("graph_source"),
        }
    )
    return base, []
