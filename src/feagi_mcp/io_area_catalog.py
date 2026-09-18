"""Compact IPU/OPU catalog for MCP (local decode, no per-area inspect).

``list_ipu_areas_with_metadata`` only knows a handful of 4-char types and attaches
purpose/capabilities text per area, so encoder IPUs (``ipro``, ``imis``, ``isvm``)
show up as ``unknown`` and a large genome blows the token budget. This module
projects one small row per I/O area and a subtype summary, including the
``cortical_dimensions`` vs ``dev_count`` mismatch that hides combined encoder
strips in Brain Visualizer.
"""

from __future__ import annotations

from typing import Any

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation

_IO_KIND_ALIASES = {
    "ipu": "ipu",
    "sensory": "ipu",
    "opu": "opu",
    "motor": "opu",
    "both": "both",
    "io": "both",
}


def validate_io_kind(io_kind: str | None) -> str:
    """Normalize ``ipu`` / ``opu`` / ``both``. Empty defaults to ``both``."""
    raw = "" if io_kind is None else str(io_kind).strip().lower()
    if not raw:
        return "both"
    mapped = _IO_KIND_ALIASES.get(raw)
    if mapped is None:
        allowed = ", ".join(sorted({"ipu", "opu", "both"}))
        raise ValueError(f"io_kind must be one of: {allowed}.")
    return mapped


def _optional_int(value: Any) -> int | None:
    """Parse a JSON number as int; reject bools."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _optional_int_triplet(value: Any) -> list[int] | None:
    """Return ``[x, y, z]`` when the payload is a 3-int voxel size."""
    if not isinstance(value, list) or len(value) < 3:
        return None
    parsed: list[int] = []
    for item in value[:3]:
        number = _optional_int(item)
        if number is None:
            return None
        parsed.append(number)
    return parsed


def extract_dev_count(area: dict[str, Any]) -> int | None:
    """Device count from the area record or nested ``properties``."""
    for key in ("dev_count", "device_count"):
        parsed = _optional_int(area.get(key))
        if parsed is not None:
            return parsed
    bag = area.get("properties")
    if isinstance(bag, dict):
        for key in ("dev_count", "device_count"):
            parsed = _optional_int(bag.get(key))
            if parsed is not None:
                return parsed
    return None


def extract_cortical_dimensions(area: dict[str, Any]) -> list[int] | None:
    """Total voxel size from ``cortical_dimensions`` or ``dimensions``."""
    for key in ("cortical_dimensions", "dimensions"):
        parsed = _optional_int_triplet(area.get(key))
        if parsed is not None:
            return parsed
    return None


def extract_per_device_dimensions(area: dict[str, Any]) -> list[int] | None:
    """Per-device voxel size when the API provides it."""
    return _optional_int_triplet(area.get("cortical_dimensions_per_device"))


def dimension_dev_count_mismatch(
    dimensions: list[int] | None,
    per_device: list[int] | None,
    dev_count: int | None,
) -> bool:
    """True when total width is not ``per_device_x * dev_count``.

    Combined encoder IPUs that auto-create as 1-voxel cubes with ``dev_count`` N
    fail this check; motor OPUs that expand width to N pass.
    """
    if dev_count is None or dev_count <= 1:
        return False
    if dimensions is None:
        return False
    if per_device is not None:
        expected_x = per_device[0] * dev_count
        return dimensions[0] != expected_x
    return dimensions[0] < dev_count


def _area_io_group(area: dict[str, Any]) -> str | None:
    """Return ``ipu`` or ``opu`` from FEAGI type fields, else None."""
    tokens: set[str] = set()
    for key in ("cortical_type", "cortical_group", "area_type"):
        raw = area.get(key)
        if isinstance(raw, str) and raw.strip():
            tokens.add(raw.strip().lower())
    if "ipu" in tokens or "sensory" in tokens:
        return "ipu"
    if "opu" in tokens or "motor" in tokens:
        return "opu"
    return None


def project_io_area_compact_row(area: dict[str, Any]) -> dict[str, Any]:
    """One compact I/O row: id, name, decoded subtype, dimensions, dev_count."""
    cortical_id = area.get("cortical_id")
    if not isinstance(cortical_id, str) or not cortical_id.strip():
        fallback = area.get("cortical_id_s")
        cortical_id = fallback if isinstance(fallback, str) else ""
    cortical_id = str(cortical_id).strip()
    decoded = decode_cortical_id_interpretation(cortical_id) if cortical_id else {"ok": False}
    name = ""
    for key in ("cortical_name", "name", "friendly_name"):
        raw = area.get(key)
        if isinstance(raw, str) and raw.strip():
            name = raw.strip()
            break
    dimensions = extract_cortical_dimensions(area)
    per_device = extract_per_device_dimensions(area)
    dev_count = extract_dev_count(area)
    io_group = _area_io_group(area)
    subtype = None
    unit_index = None
    subunit_index = None
    io_kind = io_group
    if decoded.get("ok") is True:
        subtype = decoded.get("subtype_4char")
        unit_index = decoded.get("cortical_unit_index")
        subunit_index = decoded.get("cortical_subunit_index")
        decoded_kind = decoded.get("io_kind")
        if decoded_kind == "sensory":
            io_kind = "ipu"
        elif decoded_kind == "motor_output":
            io_kind = "opu"
    record_subtype = area.get("cortical_subtype")
    if subtype is None and isinstance(record_subtype, str) and record_subtype.strip():
        subtype = record_subtype.strip()
    return {
        "cortical_id": cortical_id or None,
        "name": name,
        "io_kind": io_kind,
        "subtype": subtype,
        "unit_index": unit_index,
        "subunit_index": subunit_index,
        "cortical_dimensions": dimensions,
        "cortical_dimensions_per_device": per_device,
        "dev_count": dev_count,
        "neuron_count": _optional_int(area.get("neuron_count")),
        "dimension_dev_count_mismatch": dimension_dev_count_mismatch(
            dimensions, per_device, dev_count
        ),
    }


def build_io_areas_compact_payload(
    areas: list[dict[str, Any]],
    *,
    io_kind: str = "both",
    subtype: str | None = None,
    include_areas: bool = True,
    mismatches_only: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Summarize IPU/OPU areas and optionally return compact rows.

    ``limit`` caps the ``areas`` list only. ``by_subtype`` always covers the
    filtered I/O set before that cap.
    """
    kind = validate_io_kind(io_kind)
    subtype_needle = "" if subtype is None else str(subtype).strip().lower()
    if limit is not None:
        try:
            limit_int = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer >= 1.") from exc
        if limit_int < 1:
            raise ValueError("limit must be an integer >= 1.")
    else:
        limit_int = None

    rows: list[dict[str, Any]] = []
    for area in areas:
        if not isinstance(area, dict):
            continue
        row = project_io_area_compact_row(area)
        row_kind = row.get("io_kind")
        if kind == "ipu" and row_kind != "ipu":
            continue
        if kind == "opu" and row_kind != "opu":
            continue
        if kind == "both" and row_kind not in {"ipu", "opu"}:
            continue
        row_subtype = row.get("subtype")
        if subtype_needle and (
            not isinstance(row_subtype, str) or row_subtype.lower() != subtype_needle
        ):
            continue
        rows.append(row)

    by_subtype: dict[str, dict[str, Any]] = {}
    mismatch_count = 0
    for row in rows:
        key = row.get("subtype") or "unknown"
        bucket = by_subtype.setdefault(
            str(key),
            {"count": 0, "mismatch_count": 0, "example_name": row.get("name") or ""},
        )
        bucket["count"] += 1
        if row.get("dimension_dev_count_mismatch") is True:
            bucket["mismatch_count"] += 1
            mismatch_count += 1
            if not bucket.get("example_mismatch_name"):
                bucket["example_mismatch_name"] = row.get("name") or ""

    visible = rows
    if mismatches_only:
        visible = [row for row in rows if row.get("dimension_dev_count_mismatch") is True]
    total_visible = len(visible)
    if limit_int is not None:
        visible = visible[:limit_int]

    payload: dict[str, Any] = {
        "io_kind": kind,
        "count": len(rows),
        "mismatch_count": mismatch_count,
        "by_subtype": dict(sorted(by_subtype.items())),
        "returned": 0,
        "areas": [],
    }
    if include_areas:
        payload["returned"] = len(visible)
        payload["areas"] = visible
    else:
        payload["returned"] = 0
        payload["areas"] = []
    payload["total_matching_rows"] = total_visible
    return payload
