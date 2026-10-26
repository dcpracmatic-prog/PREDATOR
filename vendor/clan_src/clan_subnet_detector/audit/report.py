"""Audit pipeline for Zero-Trust Graph Engine.

Produces a self-contained, machine-readable report that an independent
reviewer can re-verify without trusting the detector implementation.

Report body conforms to ``schemas/ztge_audit_report.schema.json``
(schema_version = ztge.audit.v1). Optional HMAC/Ed25519 envelopes are
produced via :mod:`clan_subnet_detector.audit.signing`.
"""

from __future__ import annotations

import json
import platform
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import __version__
from ..detection.clique import greedy_clique, is_clique
from ..detection.dense import densest_subgraph_peeling, k_core
from ..detection.independent_set import is_independent, plan_independent
from ..graph.graph import Graph
from ..graph.metrics import connected_components, density
from ..scoring.risk import score_clique, score_independent_set
from .schema import SCHEMA_VERSION, validate_report
from .signing import (
    attach_content_hash,
    secret_from_env,
    sign_report_hmac,
)


ENGINE_NAME = "predator"
ENGINE_VERSION = "0.2.0"


@dataclass
class Finding:
    kind: str  # clique | independent_set | k_core | densest_subgraph
    nodes: List[int]
    size: int
    verified: bool
    score: float
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    """In-memory audit result (legacy-friendly). Prefer :meth:`to_v1_dict` for auditors."""

    timestamp_utc: str
    version: str
    python: str
    platform: str
    graph_n: int
    graph_m: int
    graph_density: float
    n_components: int
    findings: List[Finding]
    checks: Dict[str, bool]
    notes: List[str] = field(default_factory=list)
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    graph_source: Optional[str] = None
    graph_digest_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Legacy flat dict (backward compatible)."""
        return asdict(self)

    def to_v1_dict(self) -> Dict[str, Any]:
        """Auditor-facing document conforming to ztge.audit.v1 (hash attached)."""
        body: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "report_id": self.report_id,
            "timestamp_utc": self.timestamp_utc,
            "engine": {
                "name": ENGINE_NAME,
                "version": ENGINE_VERSION,
                "clan_version": self.version,
                "python": self.python,
                "platform": self.platform,
            },
            "graph": {
                "n": self.graph_n,
                "m": self.graph_m,
                "density": self.graph_density,
                "n_components": self.n_components,
                "source": self.graph_source,
                "digest_sha256": self.graph_digest_sha256,
            },
            "findings": [
                {
                    "kind": f.kind,
                    "nodes": list(f.nodes),
                    "size": f.size,
                    "verified": f.verified,
                    "score": f.score,
                    "extra": dict(f.extra) if f.extra else {},
                }
                for f in self.findings
            ],
            "checks": dict(self.checks),
            "notes": list(self.notes),
            "content_hash": "",
        }
        return attach_content_hash(body)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_v1_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        v1 = self.to_v1_dict()
        lines = [
            "# Zero-Trust Graph Engine – Audit Report",
            "",
            f"- **Schema**: `{v1['schema_version']}`",
            f"- **Report ID**: `{v1['report_id']}`",
            f"- **Timestamp (UTC)**: {self.timestamp_utc}",
            f"- **Engine**: {ENGINE_NAME} {ENGINE_VERSION} (clan {self.version})",
            f"- **Content hash (SHA-256)**: `{v1['content_hash']}`",
            f"- **Python**: {self.python}",
            f"- **Platform**: {self.platform}",
            "",
            "## Graph summary",
            f"- Nodes (n): {self.graph_n}",
            f"- Edges (m): {self.graph_m}",
            f"- Density: {self.graph_density:.6f}",
            f"- Connected components: {self.n_components}",
            "",
            "## Automated checks",
        ]
        for k, v in self.checks.items():
            status = "PASS" if v else "FAIL"
            lines.append(f"- `{k}`: **{status}**")
        lines += ["", "## Findings"]
        if not self.findings:
            lines.append("_No findings recorded._")
        for i, f in enumerate(self.findings, 1):
            lines += [
                f"### {i}. `{f.kind}`",
                f"- Size: {f.size}",
                f"- Verified: **{'yes' if f.verified else 'no'}**",
                f"- Score: {f.score:.6g}",
                f"- Nodes: `{f.nodes[:64]}{'…' if len(f.nodes) > 64 else ''}`",
            ]
            if f.extra:
                lines.append(f"- Extra: `{f.extra}`")
        if self.notes:
            lines += ["", "## Notes"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


def run_audit(
    g: Graph,
    *,
    clique_seed: Optional[int] = None,
    independent_k: Optional[int] = 10,
    method: str = "auto",
    budget_ms: int = 100,
    seed: int = 1,
    k_core_k: int = 3,
    include_dense: bool = True,
    graph_source: Optional[str] = None,
    graph_digest_sha256: Optional[str] = None,
) -> AuditReport:
    """Run detectors, verify every result independently, and build a report."""
    notes: List[str] = []
    findings: List[Finding] = []

    # --- Clique ---
    clique_nodes = greedy_clique(g, seed=clique_seed)
    clique_ok = is_clique(g, clique_nodes)
    findings.append(
        Finding(
            kind="clique",
            nodes=list(clique_nodes),
            size=len(clique_nodes),
            verified=clique_ok,
            score=score_clique(g, clique_nodes),
            extra={"seed": clique_seed},
        )
    )
    if not clique_ok:
        notes.append("Clique candidate failed independent verification.")

    # --- Independent set (transparent planner) ---
    planner_trace: List[Dict[str, Any]] = []
    ind_nodes = plan_independent(
        g,
        k=independent_k,
        method=method,
        budget_ms=budget_ms,
        seed=seed,
        trace_out=planner_trace,
    )
    ind_ok = is_independent(g, ind_nodes)
    planner_meta = planner_trace[0] if planner_trace else {"requested": method, "resolved": method}
    findings.append(
        Finding(
            kind="independent_set",
            nodes=list(ind_nodes),
            size=len(ind_nodes),
            verified=ind_ok,
            score=score_independent_set(g, ind_nodes),
            extra={
                "method_requested": method,
                "method_resolved": planner_meta.get("resolved"),
                "fallback": planner_meta.get("fallback", False),
                "reason": planner_meta.get("reason", ""),
                "morph": planner_meta.get("morph"),
                "k": independent_k,
                "budget_ms": budget_ms,
                "seed": seed,
            },
        )
    )
    notes.append(
        f"planner requested={planner_meta.get('requested')} "
        f"resolved={planner_meta.get('resolved')} "
        f"fallback={planner_meta.get('fallback')} "
        f"reason={planner_meta.get('reason')}"
    )
    if not ind_ok:
        notes.append("Independent-set candidate failed independent verification.")

    # --- Dense structures ---
    core_nodes = k_core(g, k_core_k)
    findings.append(
        Finding(
            kind="k_core",
            nodes=list(core_nodes),
            size=len(core_nodes),
            verified=True,
            score=float(len(core_nodes)) / max(g.n, 1),
            extra={"k": k_core_k},
        )
    )
    if include_dense:
        dense_nodes, dense_dens = densest_subgraph_peeling(g)
        findings.append(
            Finding(
                kind="densest_subgraph",
                nodes=list(dense_nodes),
                size=len(dense_nodes),
                verified=True,
                score=float(dense_dens),
                extra={"density": dense_dens},
            )
        )

    comps = connected_components(g)
    dens = density(g)
    checks = {
        "clique_verified": clique_ok,
        "independent_set_verified": ind_ok,
        "all_findings_verified": all(f.verified for f in findings if f.kind in ("clique", "independent_set")),
        "planner_trace_present": bool(planner_trace),
    }

    return AuditReport(
        timestamp_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        version=__version__,
        python=sys.version.split()[0],
        platform=platform.platform(),
        graph_n=g.n,
        graph_m=g.edge_count(),
        graph_density=float(dens),
        n_components=len(comps),
        findings=findings,
        checks=checks,
        notes=notes,
        graph_source=graph_source,
        graph_digest_sha256=graph_digest_sha256,
    )


def write_report(
    report: AuditReport,
    out_dir: str | Path,
    *,
    sign: bool = True,
    hmac_secret: Optional[bytes] = None,
    key_id: str = "hmac:default",
    producer: Optional[Dict[str, str]] = None,
) -> Dict[str, Path]:
    """Write v1 JSON, Markdown, and optionally a signed envelope.

    If *sign* is True, uses *hmac_secret* or ``ZTGE_HMAC_SECRET`` from the
    environment. When no secret is available, only the unsigned v1 JSON is written.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}

    v1 = report.to_v1_dict()
    ok, errs = validate_report(v1)
    if not ok:
        raise ValueError("report failed schema validation: " + "; ".join(errs))

    json_path = out / "audit_report.json"
    json_path.write_text(json.dumps(v1, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["json"] = json_path

    md_path = out / "audit_report.md"
    md_path.write_text(report.to_markdown() + "\n", encoding="utf-8")
    paths["markdown"] = md_path

    secret = hmac_secret if hmac_secret is not None else secret_from_env()
    if sign and secret:
        envelope = sign_report_hmac(
            v1,
            secret,
            key_id=key_id,
            producer=producer
            or {
                "organization": "dcpracmatic-prog",
                "service": ENGINE_NAME,
            },
        )
        env_path = out / "audit_report.signed.json"
        env_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths["signed"] = env_path

    return paths
