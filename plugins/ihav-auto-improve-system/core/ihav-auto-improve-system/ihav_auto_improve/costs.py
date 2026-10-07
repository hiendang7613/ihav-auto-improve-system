"""Cost values as reported by the adapter. An unknown cost is recorded as unknown, never as 0."""

from __future__ import annotations

KNOWN = ("reported", "estimated")
UNKNOWN = ("pending", "unavailable")


def normalize(raw) -> dict:
    """Keep a cost only when its status, value and unit agree; anything else becomes unavailable."""
    note = raw.get("note") if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or raw.get("status") not in KNOWN + UNKNOWN:
        return {"value": None, "unit": None, "status": "unavailable", "note": note or "adapter gave no valid cost status"}
    value, unit, status = raw.get("value"), raw.get("unit"), raw["status"]
    if status in UNKNOWN:
        return {"value": None, "unit": unit, "status": status, "note": note}
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or not isinstance(unit, str):
        return {"value": None, "unit": None, "status": "unavailable", "note": f"{status} cost without a number and unit"}
    return {"value": value, "unit": unit, "status": status, "note": note}


def summarize(records: list) -> dict:
    """Sum known costs per unit and status; count unknown ones separately."""
    known, unknown = {}, {status: 0 for status in UNKNOWN}
    for record in records:
        cost = record["cost"]
        if cost["status"] in KNOWN:
            by_unit = known.setdefault(cost["unit"], {})
            by_unit[cost["status"]] = by_unit.get(cost["status"], 0) + cost["value"]
        else:
            unknown[cost["status"]] += 1
    return {"calls": len(records), "known": known, "unknown": unknown}


def text(summary: dict) -> str:
    parts = [f"{round(value, 6)} {unit} {status}" for unit, by in sorted(summary["known"].items())
             for status, value in sorted(by.items())]
    missing = sum(summary["unknown"].values())
    if missing:
        detail = ", ".join(f"{n} {s}" for s, n in summary["unknown"].items() if n)
        parts.append(f"{missing} call(s) cost unknown ({detail})")
    return f"{summary['calls']} call(s): " + ("; ".join(parts) if parts else "no cost reported")
