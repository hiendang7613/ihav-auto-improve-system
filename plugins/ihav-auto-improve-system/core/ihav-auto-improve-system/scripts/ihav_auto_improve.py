#!/usr/bin/env python3
"""Portable entry point for Claude Code, Codex and direct terminal use."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 9):
    print("ihav-auto-improve-system requires Python 3.9 or later.", file=sys.stderr)
    raise SystemExit(64)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ihav_auto_improve.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
