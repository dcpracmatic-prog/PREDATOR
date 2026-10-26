"""Console entry point for PREDATOR status."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    try:
        from clan_subnet_detector import __version__
        from clan_subnet_detector.detection.morph_adapter import morph_status
    except ImportError as e:
        print(json.dumps({"error": str(e)}))
        raise SystemExit(1)
    contracts = sorted(p.name for p in (root / "contracts").glob("*.yaml"))
    print(json.dumps({
        "engine": "predator",
        "clan_version": __version__,
        "morph": morph_status(),
        "contracts": contracts,
    }, indent=2))


if __name__ == "__main__":
    main()
