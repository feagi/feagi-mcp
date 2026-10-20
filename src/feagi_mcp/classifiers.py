"""Classifier genome helpers for MCP list/inspect tools.

These functions stay local. They do not call FEAGI. The client fetches
``GET /v1/cortical_area/classifiers`` (or one classifier) plus the area catalog
and mapping table, then this module projects one compact inspect payload.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from feagi_mcp.memory_diagnostics import memory_area_diagnostics
from feagi_mcp.value_coding import classifier_value_findings

CLASSIFIER_LIST_KEYS: tuple[str, ...] = (
    "classifier_id",
    "name",
    "parent_region_id",
    "coordinates_3d",
    "sample_area_ids",
    "class_bindings",
    "sample_memory_id",
    "class_memory_id",
    "error_area_id",
    "reward_training",
    "answer_feedback_area_id",
    "pain_area_id",
    "pleasure_area_id",
    "answer_latency_bursts",
    "learn_area_id",
    "confidence_area_id",
)

CLASSIFIER_SLOT_FIELDS: tuple[tuple[str, str], ...] = (
    ("sample_memory", "sample_memory_id"),
    ("class_memory", "class_memory_id"),
    ("error", "error_area_id"),
)

CLASSIFIER_SHARED_MAPPINGS: tuple[tuple[str, str, str, str], ...] = (
    ("sample_mem_to_class_mem", "sample_memory", "class_memory", "associative_memory"),
)


def classifier_class_bindings(record: dict[str, Any]) -> list[dict[str, str]]:
    """Class input and the output created for it."""
    raw = record.get("class_bindings")
    bindings: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return bindings
    for item in raw:
        if not isinstance(item, dict):
            continue
        class_id = str(item.get("class_area_id", "")).strip()
        output_id = str(item.get("class_output_area_id", "")).strip()
        if class_id:
            bindings.append({"class_area_id": class_id, "class_output_area_id": output_id})
    return bindings


def classifier_sample_ids(record: dict[str, Any]) -> list[str]:
    """Sample inputs recorded on the classifier."""
    raw = record.get("sample_area_ids")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def project_classifier_row(record: dict[str, Any]) -> dict[str, Any]:
    """Keep classifier identity, parent, pose, inputs, and owned areas."""
    row = {key: record.get(key) for key in CLASSIFIER_LIST_KEYS}
    row["sample_area_ids"] = classifier_sample_ids(record)
    row["class_bindings"] = classifier_class_bindings(record)
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


def _scan_slot(slots: Mapping[str, dict[str, Any] | bool], key: str) -> dict[str, Any]:
    """Return a slot record; non-dict values (e.g. ``fields_present``) become ``{}``."""
    raw = slots.get(key, {})
    return raw if isinstance(raw, dict) else {}


def scan_blockers(
    slots: Mapping[str, dict[str, Any] | bool],
    missing_slots: list[str],
    missing_mappings: list[str],
) -> list[str]:
    """Missing owned areas, the associative edge, or a quiet class output."""
    blockers: list[str] = []
    if "sample_memory" in missing_slots:
        blockers.append("sample_memory_missing")
    if "class_memory" in missing_slots:
        blockers.append("class_memory_missing")
    if "error" in missing_slots:
        blockers.append("error_missing")
    if "sample_mem_to_class_mem" in missing_mappings:
        blockers.append("associative_mapping_missing")
    output = _scan_slot(slots, "class_output")
    if output.get("present") and output.get("neuron_burst_engine_active") is False:
        blockers.append("class_output_burst_engine_off")
    sample = _scan_slot(slots, "sample_memory")
    if sample.get("present") and sample.get("long_term_neuron_count") == 0:
        blockers.append("sample_memory_no_ltm")
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
    memory_area_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project classifier + slots + mappings + scan blockers.

    ``memory_area_stats`` is the health_check block keyed by cortical id; it adds
    lifetime create/delete totals to each memory slot.
    """
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

    memory_findings: list[dict[str, Any]] = []
    for memory_role in ("sample_memory", "class_memory"):
        slot = slots[memory_role]
        _attach_memory_runtime(slot, memory_runtime)
        if not slot.get("present"):
            continue
        diagnostics = memory_area_diagnostics(
            str(slot["area_id"]),
            mapping_items,
            memory_area_stats,
            slot.get("long_term_neuron_count"),
        )
        for finding in diagnostics.pop("findings"):
            memory_findings.append({"slot": memory_role, **finding})
        slot.update(diagnostics)

    sample_memory_id = slot_ids.get("sample_memory")
    class_memory_id = slot_ids.get("class_memory")
    class_rows: list[dict[str, Any]] = []
    blockers = scan_blockers(slots, missing_slots, missing_mappings)
    sample_memory_errors = [
        finding["code"]
        for finding in memory_findings
        if finding["slot"] == "sample_memory" and finding["severity"] == "error"
    ]
    for code in sample_memory_errors:
        if code not in blockers:
            blockers.append(code)
    for sample_id in classifier_sample_ids(classifier):
        morphologies = (
            mapping_lookup.get((sample_id, str(sample_memory_id)), []) if sample_memory_id else []
        )
        present = "classifier_sample" in morphologies
        mappings.append(
            {
                "role": "sample_to_sample_mem",
                "src_slot": "sample_area",
                "dst_slot": "sample_memory",
                "src": sample_id,
                "dst": sample_memory_id,
                "expected_morphology": "classifier_sample",
                "present": present,
                "actual_morphologies": morphologies,
            }
        )
        if not present:
            missing_mappings.append(f"sample_to_sample_mem:{sample_id}")
            blockers.append("sample_mapping_missing")
    for binding in classifier_class_bindings(classifier):
        class_slot = resolve_classifier_slot("class_area", binding["class_area_id"], catalog)
        output_slot = resolve_classifier_slot(
            "class_output", binding["class_output_area_id"], catalog
        )
        morphologies = (
            mapping_lookup.get((binding["class_area_id"], str(class_memory_id)), [])
            if class_memory_id
            else []
        )
        present = "classifier_class" in morphologies
        row_blockers = scan_blockers(
            {"class_output": output_slot, "sample_memory": slots.get("sample_memory", {})},
            [] if output_slot.get("present") else ["class_output"],
            [] if present else ["class_to_class_mem"],
        )
        if not output_slot.get("present") and "class_output_missing" not in row_blockers:
            row_blockers.append("class_output_missing")
        class_rows.append(
            {
                "class_area_id": binding["class_area_id"],
                "class_output_area_id": binding["class_output_area_id"],
                "class_area": class_slot,
                "class_output": output_slot,
                "mapping_present": present,
                "output_visible": bool(
                    output_slot.get("present") and output_slot.get("visible") is not False
                ),
                "blockers": row_blockers,
            }
        )
        mappings.append(
            {
                "role": "class_to_class_mem",
                "src_slot": "class_area",
                "dst_slot": "class_memory",
                "src": binding["class_area_id"],
                "dst": class_memory_id,
                "expected_morphology": "classifier_class",
                "present": present,
                "actual_morphologies": morphologies,
            }
        )
        if not present:
            missing_mappings.append(f"class_to_class_mem:{binding['class_area_id']}")
            if "class_mapping_missing" not in blockers:
                blockers.append("class_mapping_missing")
        for name in row_blockers:
            if name not in blockers:
                blockers.append(name)

    value_findings = classifier_value_findings(classifier, catalog)
    for finding in value_findings:
        if finding["severity"] == "error" and finding["code"] not in blockers:
            blockers.append(finding["code"])

    return {
        "classifier": project_classifier_row(classifier),
        "slots": slots,
        "class_bindings": class_rows,
        "mappings": mappings,
        "missing_slots": missing_slots,
        "missing_mappings": missing_mappings,
        "outputs_visible": bool(class_rows) and all(row["output_visible"] for row in class_rows),
        "value_findings": value_findings,
        "memory_findings": memory_findings,
        "blockers": blockers,
        "ready": bool(class_rows)
        and all(not row["blockers"] for row in class_rows)
        and not any(finding["severity"] == "error" for finding in value_findings)
        and not sample_memory_errors
        and "associative_mapping_missing" not in blockers,
    }
