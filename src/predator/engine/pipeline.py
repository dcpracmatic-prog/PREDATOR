"""Orchestration helpers for the Zero-Trust Graph Engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from clan_subnet_detector.audit.report import run_audit, write_report
from clan_subnet_detector.detection.morph_adapter import morph_status
from clan_subnet_detector.graph.graph import Graph


def status() -> Dict[str, Any]:
    return {
        "morph": morph_status(),
        "engine": "predator",
    }


def audit_graph(
    g: Graph,
    out_dir: Path | str,
    method: str = "auto",
    budget_ms: int = 100,
    seed: int = 1,
    independent_k: Optional[int] = 10,
) -> Dict[str, Any]:
    """Run a full audited detection pass and write reports under out_dir."""
    report = run_audit(
        g,
        method=method,
        budget_ms=budget_ms,
        seed=seed,
        independent_k=independent_k,
    )
    paths = write_report(report, out_dir)
    return {
        "checks": report.checks,
        "notes": report.notes,
        "paths": {k: str(v) for k, v in paths.items()},
        "findings": [
            {
                "kind": f.kind,
                "size": f.size,
                "verified": f.verified,
                "extra": f.extra,
            }
            for f in report.findings
        ],
    }
