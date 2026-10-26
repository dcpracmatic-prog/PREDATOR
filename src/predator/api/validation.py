"""Request validation for the ZTGE HTTP API (no pydantic required)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from predator.hardware import MAX_GRAPH_VERTICES, max_graph_edges, max_graph_vertices, recommended_morph_budget_ms


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
    # JSON booleans are Python ints, and int(2.9)/int("2") silently changes
    # the graph an agent asked us to solve. Accept only actual JSON integers.
    if type(raw["n"]) is not int:
        return _err("graph.n must be an integer (not a boolean, decimal, or string)")
    n = raw["n"]
    if n < 0:
        return _err("graph.n must be >= 0")
    allowed_n = min(MAX_GRAPH_VERTICES, max_graph_vertices())
    if n > allowed_n:
        return _err(f"graph.n exceeds resource-aware limit {allowed_n}")
    edges = raw["edges"]
    if not isinstance(edges, list):
        return _err("graph.edges must be an array")
    allowed_edges = max_graph_edges()
    if len(edges) > allowed_edges:
        return _err(f"graph.edges exceeds resource-aware/native limit {allowed_edges}")
    directed_raw = raw.get("directed", False)
    if type(directed_raw) is not bool:
        return _err("graph.directed must be a boolean")
    parsed: List[Tuple[int, int]] = []
    for i, e in enumerate(edges):
        if not isinstance(e, (list, tuple)) or len(e) != 2:
            errors.append(f"graph.edges[{i}] must be [u, v]")
            continue
        if type(e[0]) is not int or type(e[1]) is not int:
            errors.append(f"graph.edges[{i}] endpoints must be integers (not booleans, decimals, or strings)")
            continue
        u, v = e
        if u < 0 or v < 0 or u >= n or v >= n:
            errors.append(f"graph.edges[{i}] endpoints out of range for n={n}")
            continue
        parsed.append((u, v))
    directed = directed_raw
    if errors:
        return None, errors
    return {"n": n, "edges": parsed, "directed": directed}, []


def validate_plan_request(body: Any) -> Tuple[Dict[str, Any] | None, List[str]]:
    if not isinstance(body, dict):
        return _err("body must be a JSON object")
    g, errs = validate_graph_input(body.get("graph"))
    if errs:
        return None, errs
    method_raw = body.get("method", "auto")
    if not isinstance(method_raw, str):
        return _err("method must be a string: auto|morph|gwmin")
    method = method_raw.lower()
    if method not in ("auto", "morph", "gwmin"):
        return _err("method must be auto|morph|gwmin")
    budget_supplied = "budget_ms" in body
    budget_raw = body.get("budget_ms", 100)
    seed = body.get("seed", 1)
    auto_n_threshold = body.get("auto_n_threshold", 1500)
    if budget_supplied and type(budget_raw) is not int:
        return _err("budget_ms must be an integer (not a boolean, decimal, or string)")
    if type(seed) is not int or type(auto_n_threshold) is not int:
        return _err("seed and auto_n_threshold must be integers (not booleans, decimals, or strings)")
    budget_source = "request" if budget_supplied else "default"
    budget_ms = budget_raw
    assert g is not None
    wants_morph = method == "morph" or (method == "auto" and g["n"] >= auto_n_threshold)
    if not budget_supplied and wants_morph:
        profiled = recommended_morph_budget_ms(g["n"])
        if profiled is not None:
            budget_ms = profiled
            budget_source = "hardware_profile"
    if not (1 <= budget_ms <= 600_000):
        return _err("budget_ms out of range [1, 600000]")
    if seed < 0:
        return _err("seed must be >= 0")
    if auto_n_threshold < 1:
        return _err("auto_n_threshold must be >= 1")
    return {
        "graph": g, "method": method, "budget_ms": budget_ms,
        "budget_ms_source": budget_source, "seed": seed,
        "auto_n_threshold": auto_n_threshold,
    }, []


def validate_audit_request(body: Any) -> Tuple[Dict[str, Any] | None, List[str]]:
    base, errs = validate_plan_request(
        {
            "graph": body.get("graph") if isinstance(body, dict) else None,
            "method": body.get("method", "auto") if isinstance(body, dict) else "auto",
            **({"budget_ms": body["budget_ms"]} if isinstance(body, dict) and "budget_ms" in body else {}),
            "seed": body.get("seed", 1) if isinstance(body, dict) else 1,
            "auto_n_threshold": body.get("auto_n_threshold", 1500)
            if isinstance(body, dict)
            else 1500,
        }
    )
    if errs or not isinstance(body, dict):
        return None, errs or ["body must be a JSON object"]
    assert base is not None
    k_core_k = body.get("k_core_k", 3)
    if type(k_core_k) is not int:
        return _err("k_core_k must be an integer (not a boolean, decimal, or string)")
    if k_core_k < 1:
        return _err("k_core_k must be >= 1")
    sign = body.get("sign", True)
    include_dense = body.get("include_dense", True)
    key_id = body.get("key_id", "hmac:default")
    if type(sign) is not bool or type(include_dense) is not bool:
        return _err("sign and include_dense must be booleans")
    if not isinstance(key_id, str):
        return _err("key_id must be a string")
    graph_source = body.get("graph_source")
    if graph_source is not None and not isinstance(graph_source, str):
        return _err("graph_source must be a string or null")
    base.update(
        {
            "sign": sign,
            "key_id": key_id,
            "include_dense": include_dense,
            "k_core_k": k_core_k,
            "graph_source": graph_source,
        }
    )
    return base, []
