"""Clan-Subnet Detector – clique and isolated-subnet detection.

Designed for independent audit: every reported structure is re-checked
against the original graph before acceptance into the signed report.
"""

__version__ = "0.2.2"

from .graph.graph import Graph, Edge
from .graph.metrics import density, degree_sequence, connected_components
from .graph.temporal import TemporalGraph, EdgeEvent
from .detection.independent_set import plan_independent, gwmin_independent, is_independent
from .detection.morph_adapter import morph_status, MorphRunInfo
from .detection.clique import greedy_clique, is_clique
from .detection.dense import k_core, core_number, densest_subgraph_peeling
from .scoring.risk import score_clique, score_independent_set
from .audit.report import run_audit, AuditReport, write_report
from .audit.schema import SCHEMA_VERSION, validate_report
from .audit.signing import (
    sign_report_hmac,
    verify_envelope_hmac,
    generate_hmac_secret,
    attach_content_hash,
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
    "write_report",
    "SCHEMA_VERSION",
    "validate_report",
    "sign_report_hmac",
    "verify_envelope_hmac",
    "generate_hmac_secret",
    "attach_content_hash",
    "load_edge_list",
    "load_timestamped_edge_list",
    "load_netflow_summary",
    "__version__",
]
