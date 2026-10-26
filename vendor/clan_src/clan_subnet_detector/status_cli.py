"""Installed CLI entry point for ZTGE status."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    from . import __version__
    from .detection.morph_adapter import morph_status

    # Contracts are repository assets rather than package data in this release.
    contracts_dir = Path.cwd() / "contracts"
    result = {
        "engine": "predator",
        "clan_version": __version__,
        "morph": morph_status(),
        "contracts": sorted(p.name for p in contracts_dir.glob("*.yaml"))
        if contracts_dir.is_dir() else [],
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
