"""Compact I/O area naming provenance for MCP agents.

``get_agent_device_registrations`` can be megabytes for musculoskeletal
bodies. These helpers answer "why is this area titled X?" from already-fetched
registration dicts without returning per-channel dumps.
"""

from __future__ import annotations

from typing import Any

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation

SAMPLE_CHANNEL_LIMIT = 8
CATCH_ALL_GROUP_NAME = "ungrouped"


def _unwrap_value(raw: Any) -> Any:
    """Unwrap FEAGI typed-value objects like ``{"type": "...", "value": ...}``."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _nonempty_str(raw: Any) -> str | None:
    """Return a stripped non-empty string, unwrapping typed values."""
    value = _unwrap_value(raw)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def split_registration_title(name: str | None, subunit_id: int | None) -> dict[str, Any]:
    """Split ``{group}-{subunit}`` titles used by PositionalServo auto-naming."""
    title = (name or "").strip()
    group_title = title
    subunit_suffix: str | None = None
    if (
        isinstance(subunit_id, int)
        and title.endswith(f"-{subunit_id}")
        and title != f"-{subunit_id}"
    ):
        group_title = title[: -(len(str(subunit_id)) + 1)]
        subunit_suffix = str(subunit_id)
    return {
        "title": title,
        "group_title": group_title,
        "subunit_suffix": subunit_suffix,
    }


def summarize_motor_groups_from_registrations(
    device_registrations: dict[str, Any],
) -> list[dict[str, Any]]:
    """One compact row per motor unit, not per actuator channel."""
    if not isinstance(device_registrations, dict):
        return []
    output_units = device_registrations.get("output_units_and_decoder_properties")
    if not isinstance(output_units, dict):
        return []

    groups: list[dict[str, Any]] = []
    for device_type, entries in output_units.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, list) or not entry:
                continue
            meta = entry[0]
            if not isinstance(meta, dict):
                continue
            grouping = meta.get("device_grouping")
            if not isinstance(grouping, list):
                grouping = []
            sample_names: list[str] = []
            bundle_ids: list[str] = []
            empty_joint_name_count = 0
            for channel in grouping:
                if not isinstance(channel, dict):
                    continue
                props = channel.get("device_properties")
                if not isinstance(props, dict):
                    props = {}
                if not _nonempty_str(props.get("joint_name")):
                    empty_joint_name_count += 1
                bundle_id = _nonempty_str(props.get("bundle_id"))
                if bundle_id and bundle_id not in bundle_ids:
                    bundle_ids.append(bundle_id)
                sample = (
                    _nonempty_str(props.get("actuator_name"))
                    or _nonempty_str(channel.get("friendly_name"))
                    or _nonempty_str(props.get("source_entity"))
                )
                if (
                    sample
                    and sample not in sample_names
                    and len(sample_names) < SAMPLE_CHANNEL_LIMIT
                ):
                    sample_names.append(sample)
            friendly_name = _nonempty_str(meta.get("friendly_name"))
            unit_index = meta.get("cortical_unit_index")
            is_catch_all = (
                friendly_name == CATCH_ALL_GROUP_NAME or CATCH_ALL_GROUP_NAME in bundle_ids
            )
            io_flags = meta.get("io_configuration_flags")
            frame_handling = None
            if isinstance(io_flags, dict):
                frame_handling = _nonempty_str(io_flags.get("frame_change_handling"))
            groups.append(
                {
                    "device_type": str(device_type),
                    "friendly_name": friendly_name,
                    "bundle_ids": bundle_ids,
                    "unit_id": unit_index if isinstance(unit_index, int) else None,
                    "channel_count": len(grouping),
                    "empty_joint_name_count": empty_joint_name_count,
                    "sample_actuator_names": sample_names,
                    "frame_change_handling": frame_handling,
                    "is_catch_all": is_catch_all,
                }
            )
    return groups


def compose_naming_cause(
    *,
    title_parts: dict[str, Any],
    subunit_id: int | None,
    encoding: str | None,
    matched_group: dict[str, Any] | None,
) -> str:
    """One-sentence explanation of how the cortical title was produced."""
    pieces: list[str] = []
    group_title = title_parts.get("group_title")
    if matched_group and matched_group.get("is_catch_all"):
        pieces.append(
            "Group title is the controller catch-all "
            f"'{CATCH_ALL_GROUP_NAME}' for actuators with no joint or limb mapping"
        )
    elif isinstance(group_title, str) and group_title:
        pieces.append(f"Group title '{group_title}' comes from the embodiment motor bundle name")
    suffix = title_parts.get("subunit_suffix")
    if suffix is not None and isinstance(subunit_id, int):
        encoding_note = f" ({encoding})" if encoding else ""
        pieces.append(f"suffix '-{suffix}' is PositionalServo sub-area {subunit_id}{encoding_note}")
    if not pieces:
        return "Title is the connectome cortical_name with no matching motor registration group."
    return "; ".join(pieces) + "."


def build_area_naming_explanation(
    cortical_id: str,
    area: dict[str, Any] | None,
    agent_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the compact explain_cortical_area_naming payload."""
    interpretation = decode_cortical_id_interpretation(cortical_id)
    area_record = area if isinstance(area, dict) else {}
    name = _nonempty_str(area_record.get("cortical_name")) or _nonempty_str(area_record.get("name"))
    subunit_id = area_record.get("subunit_id")
    if not isinstance(subunit_id, int):
        decoded_sub = interpretation.get("cortical_subunit_index")
        subunit_id = decoded_sub if isinstance(decoded_sub, int) else None
    unit_id = area_record.get("unit_id")
    if not isinstance(unit_id, int):
        decoded_unit = interpretation.get("cortical_unit_index")
        unit_id = decoded_unit if isinstance(decoded_unit, int) else None
    encoding = _nonempty_str(area_record.get("encoding_type")) or _nonempty_str(
        area_record.get("coding_behavior")
    )
    title_parts = split_registration_title(name, subunit_id)

    matched: list[dict[str, Any]] = []
    for row in agent_groups:
        group = row.get("group")
        if not isinstance(group, dict):
            continue
        group_unit = group.get("unit_id")
        friendly = group.get("friendly_name")
        if group_unit == unit_id or friendly == title_parts.get("group_title"):
            matched.append(row)

    primary = matched[0]["group"] if matched else None
    return {
        "cortical_id": cortical_id,
        "area": {
            "name": name,
            "cortical_type": area_record.get("cortical_type") or area_record.get("area_type"),
            "cortical_subtype": area_record.get("cortical_subtype"),
            "unit_id": unit_id,
            "subunit_id": subunit_id,
            "encoding": encoding,
            "dev_count": area_record.get("dev_count"),
        },
        "id_layout": interpretation,
        "name_parts": title_parts,
        "matching_groups": matched,
        "naming_cause": compose_naming_cause(
            title_parts=title_parts,
            subunit_id=subunit_id,
            encoding=encoding,
            matched_group=primary if isinstance(primary, dict) else None,
        ),
    }
