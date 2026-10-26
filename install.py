"""Cross-platform installer for PREDATOR and its official MCP SDK dependency."""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    root = __import__("pathlib").Path(__file__).resolve().parent
    command = [sys.executable, "-m", "pip", "install", "-e", ".[mcp]"]
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
