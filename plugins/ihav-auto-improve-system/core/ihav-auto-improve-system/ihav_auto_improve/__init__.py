"""Standard-library core of ihav-auto-improve-system."""

from __future__ import annotations

__version__ = "0.1.0"
TOOL = "ihav-auto-improve-system"


class Refused(Exception):
    """A command was refused before it could change or spend anything; the message says why."""
