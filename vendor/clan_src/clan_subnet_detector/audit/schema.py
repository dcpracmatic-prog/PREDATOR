"""Minimal structural validation for ztge.audit.v1 reports.

Full JSON Schema documents live under /schemas. This module implements the
subset of checks needed at emit/verify time without requiring the ``jsonschema``
package (optional enhancement).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

SCHEMA_VERSION = "ztge.audit.v1"
FINDING_KINDS = frozenset({"clique", "independent_set", "k_core", "densest_subgraph"})
METHODS = frozenset({"auto", "morph", "gwmin"})


def validate_report(report: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("report_id", "timestamp_utc", "engine", "graph", "findings", "checks", "content_hash"):
        if key not in report:
            errors.append(f"missing required field: {key}")
    engine = report.get("engine")
    if isinstance(engine, dict):
        if engine.get("name") != "zero-trust-graph-engine":
            errors.append("engine.name must be zero-trust-graph-engine")
        if "version" not in engine:
            errors.append("engine.version required")
    else:
        errors.append("engine must be an object")
    graph = report.get("graph")
    if isinstance(graph, dict):
        for k in ("n", "m", "density", "n_components"):
            if k not in graph:
                errors.append(f"graph.{k} required")
    else:
        errors.append("graph must be an object")
    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array")
    else:
        for i, f in enumerate(findings):
            if not isinstance(f, dict):
                errors.append(f"findings[{i}] must be object")
                continue
            if f.get("kind") not in FINDING_KINDS:
                errors.append(f"findings[{i}].kind invalid")
            for req in ("nodes", "size", "verified", "score"):
                if req not in f:
                    errors.append(f"findings[{i}].{req} required")
            if f.get("kind") == "independent_set":
                extra = f.get("extra") or {}
                mr = extra.get("method_requested")
                ms = extra.get("method_resolved")
                if mr is not None and mr not in METHODS:
                    errors.append(f"findings[{i}].extra.method_requested invalid")
                if ms is not None and ms not in METHODS:
                    errors.append(f"findings[{i}].extra.method_resolved invalid")
    ch = report.get("content_hash")
    if ch is not None and not (isinstance(ch, str) and len(ch) == 64):
        errors.append("content_hash must be 64-char hex sha256")
    return (len(errors) == 0, errors)
