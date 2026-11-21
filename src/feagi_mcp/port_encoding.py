"""Region port encoding: author-entry validation and read helpers (pure; no I/O).

FEAGI stores, per designated port of a brain region, what the port's signal looks like:
``kind`` (data type), ``signed`` (negative values allowed), ``frame`` (Absolute value or
Incremental change) and ``positioning`` (Linear or Fractional bin layout). Region reads return
them under ``port_encoding`` keyed by area id, each with ``source``: ``wiring`` (derived by
FEAGI from IO areas wired directly across the region boundary) or ``author`` (set through
``PUT /v1/region/region``). A field that is null is unknown, or its wired peers disagree.

The vocabulary is the shared datasheet vocabulary (``datasheet-vocabulary.json``), which equals
feagi-core's port-encoding vocabulary.
"""

from __future__ import annotations

from typing import Any

from feagi_mcp.datasheet import FRAME_ENUM, KIND_ENUM, POSITIONING_ENUM

#: Fields of an author entry, in the order FEAGI reports them.
PORT_ENCODING_FIELDS = ("kind", "signed", "frame", "positioning")

_ENUM_FIELDS = (
    ("kind", KIND_ENUM),
    ("frame", FRAME_ENUM),
    ("positioning", POSITIONING_ENUM),
)


def author_entry_error(entry: dict[str, Any]) -> str | None:
    """Why ``entry`` is not a valid author entry, or None when it is.

    Checks the vocabulary of ``kind``, ``frame`` and ``positioning``, that ``signed`` is a
    boolean, and that unknown keys (including ``source``, which FEAGI assigns) are absent. A
    field set to None is left unknown. At least one field must be set.
    """
    extra = sorted(set(entry) - set(PORT_ENCODING_FIELDS))
    if extra:
        return f"unknown port_encoding field(s) {extra}; allowed: {list(PORT_ENCODING_FIELDS)}"
    for field, allowed in _ENUM_FIELDS:
        value = entry.get(field)
        if value is not None and value not in allowed:
            return f"{field} must be one of {list(allowed)}, got {value!r}"
    signed = entry.get("signed")
    if signed is not None and not isinstance(signed, bool):
        return f"signed must be true or false, got {signed!r}"
    if all(entry.get(field) is None for field in PORT_ENCODING_FIELDS):
        return "set at least one of kind, signed, frame, positioning, or use clear=True"
    return None


def author_entry(
    kind: str | None,
    signed: bool | None,
    frame: str | None,
    positioning: str | None,
) -> dict[str, Any]:
    """The request entry for the given fields; an unset field is sent as null."""
    return {"kind": kind, "signed": signed, "frame": frame, "positioning": positioning}


def port_encoding_of(region: Any, area_id: str) -> dict[str, Any] | None:
    """The region record's ``port_encoding`` entry for ``area_id``, or None when it has none."""
    if not isinstance(region, dict):
        return None
    table = region.get("port_encoding")
    entry = table.get(area_id) if isinstance(table, dict) else None
    return entry if isinstance(entry, dict) else None


def port_encoding_table(region: Any) -> dict[str, dict[str, Any]]:
    """The region record's whole ``port_encoding`` map (``{}`` when absent or malformed)."""
    table = region.get("port_encoding") if isinstance(region, dict) else None
    if not isinstance(table, dict):
        return {}
    return {k: v for k, v in table.items() if isinstance(k, str) and isinstance(v, dict)}
