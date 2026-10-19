"""Clan-Subnet Detector – MVP package for clique and isolated-subnet detection.

Designed for simplified independent audit: every reported structure is
re-checked against the original graph before being accepted into the report.
"""

__version__ = "0.2.1-mvp"  # transparent MORPH + auto planner

from .graph.graph import Graph, Edge
from .graph.metrics import density, degree_sequence, connected_components
from .graph.temporal import TemporalGraph, EdgeEvent
from .detection.independent_set import plan_independent, gwmin_independent, is_independent
from .detection.morph_adapter import morph_status, MorphRunInfo
from .detection.clique import greedy_clique, is_clique
from .detection.dense import k_core, core_number, densest_subgraph_peeling
from .scoring.risk import score_clique, score_independent_set
from .audit.report import run_audit, AuditReport
from .audit.signing import (
    sign_report_hmac,
    verify_report_hmac,
    SignedAudit,
    payload_digest,
)
from .ingest.edge_list import load_edge_list, load_timestamped_edge_list, load_netflow_summary

__all__ = [
    "Graph",
    "Edge",
    "TemporalGraph",
    "EdgeEvent",
    "density",
    "degree_sequence",
    "connected_components",
    "plan_independent",
    "morph_status",
    "MorphRunInfo",
    "gwmin_independent",
    "is_independent",
    "greedy_clique",
    "is_clique",
    "k_core",
    "core_number",
    "densest_subgraph_peeling",
    "score_clique",
    "score_independent_set",
    "run_audit",
    "AuditReport",
    "sign_report_hmac",
    "verify_report_hmac",
    "SignedAudit",
    "payload_digest",
    "load_edge_list",
    "load_timestamped_edge_list",
    "load_netflow_summary",
    "__version__",
]
