"""Console entry point for ztge-status."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    clan = root / "vendor" / "clan_src"
    if clan.is_dir():
        sys.path.insert(0, str(clan))
    try:
        from clan_subnet_detector import __version__
        from clan_subnet_detector.detection.morph_adapter import morph_status
    except ImportError as e:
        print(json.dumps({"error": str(e)}))
        raise SystemExit(1)
    contracts = []
    cdir = root / "contracts"
    if cdir.is_dir():
        contracts = sorted(p.name for p in cdir.glob("*.yaml"))
    print(json.dumps({
        "engine": "zero-trust-graph-engine",
        "clan_version": __version__,
        "morph": morph_status(),
        "contracts": contracts,
    }, indent=2))


if __name__ == "__main__":
    main()
