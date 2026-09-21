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
    "fields",
    "kernel_memory_id",
    "class_memory_id",
)

# Shared assembly slots. Field twins are per binding, not a single slot.
CLASSIFIER_SLOT_FIELDS: tuple[tuple[str, str], ...] = (
    ("kernel_area", "kernel_area_id"),
    ("class_area", "class_area_id"),
    ("kernel_memory", "kernel_memory_id"),
    ("class_memory", "class_memory_id"),
)

CLASSIFIER_SHARED_MAPPINGS: tuple[tuple[str, str, str, str], ...] = (
    ("kernel_to_kernel_mem", "kernel_area", "kernel_memory", "episodic_memory"),
    ("class_to_class_mem", "class_area", "class_memory", "episodic_memory"),
    ("kernel_mem_to_class_mem", "kernel_memory", "class_memory", "associative_memory"),
)


def classifier_field_bindings(record: dict[str, Any]) -> list[dict[str, str]]:
    """Field bindings for one classifier.

    A previous genome stored one ``field_area_id`` and ``scan_twin_id``.
    That record loads as a one-element list. New records use ``fields`` only.
    """
    raw = record.get("fields")
    bindings: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            field_id = str(item.get("field_area_id", "")).strip()
            twin_id = str(item.get("scan_twin_id", "")).strip()
            if field_id and twin_id:
                bindings.append({"field_area_id": field_id, "scan_twin_id": twin_id})
    if bindings:
        return bindings
    field_id = str(record.get("field_area_id") or "").strip()
    twin_id = str(record.get("scan_twin_id") or "").strip()
    if field_id and twin_id:
        return [{"field_area_id": field_id, "scan_twin_id": twin_id}]
    return []


def project_classifier_row(record: dict[str, Any]) -> dict[str, Any]:
    """Keep classifier identity, parent, pose, shared slots, and field bindings."""
    row = {key: record.get(key) for key in CLASSIFIER_LIST_KEYS if key != "fields"}
    row["fields"] = classifier_field_bindings(record)
    return row


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
        "cortical_dimensions": area.get("cortical_dimensions") or area.get("dimensions"),
        "visible": area.get("visible"),
        "coordinates_3d": coordinates,
        "parent_region_id": area.get("parent_region_id"),
        "neuron_count": area.get("neuron_count"),
        "neuron_burst_engine_active": area.get("neuron_burst_engine_active"),
    }


def _attach_memory_runtime(
    slot: dict[str, Any],
    memory_runtime: dict[str, dict[str, Any]] | None,
) -> None:
    """Copy ST/LT counts onto a memory slot. Local; no FEAGI call."""
    area_id = slot.get("area_id")
    if not area_id or not memory_runtime:
        return
    runtime = memory_runtime.get(str(area_id))
    if not isinstance(runtime, dict):
        return
    slot["short_term_neuron_count"] = runtime.get("short_term_neuron_count")
    slot["long_term_neuron_count"] = runtime.get("long_term_neuron_count")
    params = runtime.get("memory_parameters")
    if isinstance(params, dict):
        slot["init_lifespan"] = params.get("init_lifespan")
        slot["longterm_mem_threshold"] = params.get("longterm_mem_threshold")


def _scan_slot(slots: dict[str, dict[str, Any] | bool], key: str) -> dict[str, Any]:
    """Return a slot record; non-dict values (e.g. ``fields_present``) become ``{}``."""
    raw = slots.get(key, {})
    return raw if isinstance(raw, dict) else {}


def _fields_present(slots: dict[str, dict[str, Any] | bool]) -> bool:
    """Read the optional ``fields_present`` flag from a scan-blocker slot map."""
    raw = slots.get("fields_present", True)
    return raw if isinstance(raw, bool) else True


def scan_blockers(
    slots: dict[str, dict[str, Any] | bool],
    missing_slots: list[str],
    missing_mappings: list[str],
) -> list[str]:
    """Shared plus single-field blockers. ``slots`` may include field_area and scan_twin."""
    blockers: list[str] = []
    if "kernel_memory" in missing_slots:
        blockers.append("kernel_memory_missing")
    if not _fields_present(slots):
        blockers.append("no_field_mappings")
    if "scan_twin" in missing_slots:
        blockers.append("twin_missing")
    if "field_area" in missing_slots:
        blockers.append("field_missing")
    if "field_to_kernel_mem" in missing_mappings:
        blockers.append("field_to_kernel_mem_mapping_missing")
    field = _scan_slot(slots, "field_area")
    if field.get("present") and field.get("neuron_burst_engine_active") is False:
        blockers.append("field_burst_engine_off")
    twin = _scan_slot(slots, "scan_twin")
    if twin.get("present") and twin.get("neuron_burst_engine_active") is False:
        blockers.append("twin_burst_engine_off")
    kmem = _scan_slot(slots, "kernel_memory")
    if kmem.get("present") and kmem.get("long_term_neuron_count") == 0:
        blockers.append("kernel_memory_no_ltm")
    return blockers


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
    memory_runtime: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project classifier + slots + mappings + scan blockers."""
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
    for role, src_slot, dst_slot, expected in CLASSIFIER_SHARED_MAPPINGS:
        src_id = slot_ids.get(src_slot)
        dst_id = slot_ids.get(dst_slot)
        morphologies = (
            mapping_lookup.get((str(src_id), str(dst_id)), []) if src_id and dst_id else []
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

    for memory_role in ("kernel_memory", "class_memory"):
        _attach_memory_runtime(slots[memory_role], memory_runtime)

    kernel_memory_id = slot_ids.get("kernel_memory")
    field_rows: list[dict[str, Any]] = []
    blockers = scan_blockers(
        {**slots, "fields_present": bool(classifier_field_bindings(classifier))},
        missing_slots,
        missing_mappings,
    )
    for binding in classifier_field_bindings(classifier):
        field_slot = resolve_classifier_slot("field_area", binding["field_area_id"], catalog)
        twin_slot = resolve_classifier_slot("scan_twin", binding["scan_twin_id"], catalog)
        field_missing = [] if field_slot.get("present") else ["field_area"]
        twin_missing = [] if twin_slot.get("present") else ["scan_twin"]
        morphologies = (
            mapping_lookup.get((binding["field_area_id"], str(kernel_memory_id)), [])
            if kernel_memory_id
            else []
        )
        mapping_present = "episodic_scan" in morphologies
        field_mapping_missing = [] if mapping_present else ["field_to_kernel_mem"]
        field_blockers = scan_blockers(
            {
                "field_area": field_slot,
                "scan_twin": twin_slot,
                "kernel_memory": slots.get("kernel_memory", {}),
                "fields_present": True,
            },
            [*missing_slots, *field_missing, *twin_missing],
            [*missing_mappings, *field_mapping_missing],
        )
        field_rows.append(
            {
                "field_area_id": binding["field_area_id"],
                "scan_twin_id": binding["scan_twin_id"],
                "field_area": field_slot,
                "scan_twin": twin_slot,
                "mapping_present": mapping_present,
                "twin_visible": bool(
                    twin_slot.get("present") and twin_slot.get("visible") is not False
                ),
                "scan_blockers": field_blockers,
                "scan_ready": field_blockers == [],
            }
        )
        mappings.append(
            {
                "role": "field_to_kernel_mem",
                "src_slot": "field_area",
                "dst_slot": "kernel_memory",
                "src": binding["field_area_id"],
                "dst": kernel_memory_id,
                "expected_morphology": "episodic_scan",
                "present": mapping_present,
                "actual_morphologies": morphologies,
            }
        )
        if not mapping_present:
            missing_mappings.append(f"field_to_kernel_mem:{binding['field_area_id']}")
        for name in field_blockers:
            if name not in blockers:
                blockers.append(name)

    if not field_rows and "no_field_mappings" not in blockers:
        blockers.insert(0, "no_field_mappings")

    return {
        "classifier": project_classifier_row(classifier),
        "slots": slots,
        "fields": field_rows,
        "mappings": mappings,
        "missing_slots": missing_slots,
        "missing_mappings": missing_mappings,
        "twin_visible": bool(field_rows) and all(row["twin_visible"] for row in field_rows),
        "scan_blockers": blockers,
        "scan_ready": bool(field_rows) and all(row["scan_ready"] for row in field_rows),
    }
