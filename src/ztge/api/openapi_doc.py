"""OpenAPI document loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_openapi() -> Dict[str, Any]:
    root = _repo_root()
    for candidate in (
        root / "openapi" / "openapi.json",
        Path.cwd() / "openapi" / "openapi.json",
    ):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Zero-Trust Graph Engine API",
            "version": "0.1.0",
            "description": "HTTP facade (embedded fallback document).",
        },
        "paths": {
            "/health": {"get": {"operationId": "health"}},
            "/v1/status": {"get": {"operationId": "status"}},
            "/v1/plan": {"post": {"operationId": "planIndependent"}},
            "/v1/audit": {"post": {"operationId": "auditGraph"}},
            "/openapi.json": {"get": {"operationId": "getOpenApi"}},
        },
    }
