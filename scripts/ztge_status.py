#!/usr/bin/env python3
"""ZTGE status — surface MORPH discovery, contracts, and package versions."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    out = {"root": str(ROOT), "contracts": [], "morph": None, "clan_version": None}
    contracts_dir = ROOT / "contracts"
    if contracts_dir.is_dir():
        out["contracts"] = sorted(p.name for p in contracts_dir.glob("*.yaml"))
    try:
        from clan_subnet_detector import __version__
        from clan_subnet_detector.detection.morph_adapter import morph_status
        out["clan_version"] = __version__
        out["morph"] = morph_status()
    except Exception as e:
        out["error"] = str(e)
    print(json.dumps(out, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
