"""Classifier genome helpers for MCP list/inspect tools.

These functions stay local. They do not call FEAGI. The client fetches
``GET /v1/cortical_area/classifiers`` (or one classifier) plus the area catalog
and mapping table, then this module projects one compact inspect payload.
"""

from __future__ import annotations

from typing import Any

CLASSIFIER_LIST_KEYS: tuple[str, ...] = (
    "classifier_id",
    "name",
    "parent_region_id",
    "coordinates_3d",
    "kernel_area_id",
    "class_area_id",
    "field_area_id",
    "kernel_memory_id",
    "class_memory_id",
    "scan_twin_id",
)

# Genome contract: referenced inputs, owned internals, required mappings.
CLASSIFIER_SLOT_FIELDS: tuple[tuple[str, str], ...] = (
    ("kernel_area", "kernel_area_id"),
    ("class_area", "class_area_id"),
    ("field_area", "field_area_id"),
    ("kernel_memory", "kernel_memory_id"),
    ("class_memory", "class_memory_id"),
    ("scan_twin", "scan_twin_id"),
)

CLASSIFIER_EXPECTED_MAPPINGS: tuple[tuple[str, str, str, str], ...] = (
    ("kernel_to_kernel_mem", "kernel_area", "kernel_memory", "episodic_memory"),
    ("class_to_class_mem", "class_area", "class_memory", "episodic_memory"),
    ("kernel_mem_to_class_mem", "kernel_memory", "class_memory", "associative_memory"),
    ("field_to_kernel_mem", "field_area", "kernel_memory", "episodic_scan"),
)


def project_classifier_row(record: dict[str, Any]) -> dict[str, Any]:
    """Keep classifier identity, parent, pose, and slot IDs."""
    return {key: record.get(key) for key in CLASSIFIER_LIST_KEYS}


def filter_classifier_records(
    records: list[dict[str, Any]],
    name_contains: str | None = None,
    classifier_id: str | None = None,
) -> list[dict[str, Any]]:
    """Filter classifier DTOs locally after one FEAGI list fetch."""
    wanted_id = (classifier_id or "").strip()
    needle = (name_contains or "").strip().lower()
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if wanted_id and str(record.get("classifier_id", "")).strip() != wanted_id:
            continue
        if needle and needle not in str(record.get("name", "")).lower():
            continue
        out.append(record)
    return out


def select_classifier_record(
    records: list[dict[str, Any]],
    classifier_id: str | None = None,
    name_contains: str | None = None,
) -> dict[str, Any]:
    """Pick exactly one classifier or return a structured error."""
    wanted_id = (classifier_id or "").strip()
    needle = (name_contains or "").strip()
    if not wanted_id and not needle:
        return {
            "error": "invalid_input",
            "message": "classifier_id or name_contains is required",
        }
    matches = filter_classifier_records(
        records,
        name_contains=needle or None,
        classifier_id=wanted_id or None,
    )
    if not matches:
        return {
            "error": "not_found",
            "message": "No classifier matched classifier_id or name_contains",
            "classifier_id": wanted_id or None,
            "name_contains": needle or None,
        }
    if len(matches) > 1:
        return {
            "error": "ambiguous",
            "message": "Multiple classifiers matched; pass classifier_id",
            "matches": [project_classifier_row(item) for item in matches],
        }
    return {"classifier": matches[0]}


def _area_name(area: dict[str, Any]) -> str:
    for key in ("cortical_name", "name", "friendly_name"):
        value = area.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return str(area.get("cortical_id", ""))


def _catalog_by_id(areas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for area in areas:
        if not isinstance(area, dict):
            continue
        area_id = str(area.get("cortical_id", "")).strip()
        if area_id:
            catalog[area_id] = area
    return catalog


def resolve_classifier_slot(
    role: str,
    area_id: Any,
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve one classifier slot against the cortical-area catalog."""
    cleaned = "" if area_id is None else str(area_id).strip()
    if not cleaned:
        return {
            "role": role,
            "area_id": None,
            "present": False,
        }
    area = catalog.get(cleaned)
    if area is None:
        return {
            "role": role,
            "area_id": cleaned,
            "present": False,
        }
    coordinates = area.get("coordinates_3d")
    if coordinates is None:
        coordinates = area.get("position")
    return {
        "role": role,
        "area_id": cleaned,
        "present": True,
        "name": _area_name(area),
        "cortical_type": area.get("cortical_type") or area.get("area_type"),
        "cortical_dimensions": area.get("cortical_dimensions")
        or area.get("dimensions"),
        "visible": area.get("visible"),
        "coordinates_3d": coordinates,
        "parent_region_id": area.get("parent_region_id"),
        "neuron_count": area.get("neuron_count"),
        "neuron_burst_engine_active": area.get("neuron_burst_engine_active"),
    }


def _mapping_index(
    items: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        src = str(item.get("src", "")).strip()
        dst = str(item.get("dst", "")).strip()
        if not src or not dst:
            continue
        morphology = str(item.get("morphology", "")).strip()
        index.setdefault((src, dst), []).append(morphology)
    return index


def build_classifier_inspect(
    classifier: dict[str, Any],
    areas: list[dict[str, Any]],
    mapping_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project classifier + resolved slots + required mapping presence."""
    catalog = _catalog_by_id(areas)
    slots: dict[str, dict[str, Any]] = {}
    slot_ids: dict[str, str | None] = {}
    missing_slots: list[str] = []
    for role, field in CLASSIFIER_SLOT_FIELDS:
        resolved = resolve_classifier_slot(role, classifier.get(field), catalog)
        slots[role] = resolved
        slot_ids[role] = resolved.get("area_id")
        if not resolved.get("present"):
            missing_slots.append(role)

    mapping_lookup = _mapping_index(mapping_items)
    mappings: list[dict[str, Any]] = []
    missing_mappings: list[str] = []
    for role, src_slot, dst_slot, expected in CLASSIFIER_EXPECTED_MAPPINGS:
        src_id = slot_ids.get(src_slot)
        dst_id = slot_ids.get(dst_slot)
        morphologies = (
            mapping_lookup.get((str(src_id), str(dst_id)), [])
            if src_id and dst_id
            else []
        )
        present = expected in morphologies
        row = {
            "role": role,
            "src_slot": src_slot,
            "dst_slot": dst_slot,
            "src": src_id,
            "dst": dst_id,
            "expected_morphology": expected,
            "present": present,
            "actual_morphologies": morphologies,
        }
        mappings.append(row)
        if not present:
            missing_mappings.append(role)

    twin = slots["scan_twin"]
    return {
        "classifier": project_classifier_row(classifier),
        "slots": slots,
        "mappings": mappings,
        "missing_slots": missing_slots,
        "missing_mappings": missing_mappings,
        "twin_visible": bool(twin.get("present") and twin.get("visible") is not False),
    }
