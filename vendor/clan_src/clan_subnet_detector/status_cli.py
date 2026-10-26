"""Installed CLI entry point for ZTGE status."""
from __future__ import annotations

import json
from importlib.resources import files


def main() -> int:
    from . import __version__
    from .detection.morph_adapter import morph_status

    # Contracts are shipped as PREDATOR package resources.
    contracts = sorted(p.name for p in files("predator").joinpath("contracts").iterdir() if p.name.endswith(".yaml"))
    result = {
        "engine": "predator",
        "clan_version": __version__,
        "morph": morph_status(),
        "contracts": contracts,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
