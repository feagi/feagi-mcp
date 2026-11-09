"""Find the registered unit behind a cortical area and its channels (local, no HTTP).

An I/O cortical area (IPU/OPU) is described by the agent's device registration: a unit key
(for example a servo kind) in ``output_units_and_decoder_properties`` or
``input_units_and_encoder_properties``, a ``cortical_unit_index`` that equals the area's
``unit_id``, and one ``device_grouping`` entry per channel. The area's ``subunit_id`` is the
index of the area within its unit (the binding's ``area_index``).

The bindings take the unit as the registration carries it, but nothing in them says which unit
key owns a given cortical id. This module therefore keeps the units of the area's section whose
``cortical_unit_index`` matches and lets the binding accept or reject each one for the area
index; when several kinds with different codings still match, the answer is an explicit error
and never a pick (see the report gap: a binding deriving the owning unit from a cortical id
would remove it).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from feagi_mcp.percentage_coding import (
    INPUT_SECTION,
    OUTPUT_SECTION,
    PhysicalRange,
    UnitCoding,
    parse_physical_range,
)


class RegistrationError(ValueError):
    """The registration does not state what the lookup needs (the message says what)."""


class NoUnitError(RegistrationError):
    """The registration has no unit for the area (another agent may own it)."""


@dataclass(frozen=True)
class UnitMatch:
    """The registered unit of one cortical area: its coding and the unit definition."""

    coding: UnitCoding
    unit_definition: dict[str, Any]
    #: The unit's registered decoder properties (``entry[1]``), ``None`` when not a dict.
    decoder_properties: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChannelRegistration:
    """One channel of a registered unit: the unit coding and its optional physical range."""

    coding: UnitCoding
    channel: int
    physical_range: PhysicalRange | None
    friendly_name: str | None
    #: Registered decoder properties of the unit (carries the incremental step size, if any).
    decoder_properties: dict[str, Any] | None = None
    #: The unit-level ``frame_change_handling`` flag (``Absolute``/``Incremental``), if stated.
    unit_frame_change: str | None = None


#: Decoder-properties key whose list carries ``[depth, positioning, speeds, step_size]``.
_STEP_PROPERTIES_KEY = "PositionalServoTargetSpeed"
_STEP_INDEX = 3


def registered_step_size(properties: dict[str, Any] | None) -> float | None:
    """The incremental step size (0 < step <= 1) the registration states, else ``None``.

    Read positionally (index 3 of the ``PositionalServoTargetSpeed`` properties); a missing,
    non-numeric, non-finite or out-of-range entry counts as not registered.
    """
    if not isinstance(properties, dict):
        return None
    raw = properties.get(_STEP_PROPERTIES_KEY)
    if not isinstance(raw, list) or len(raw) <= _STEP_INDEX:
        return None
    step = raw[_STEP_INDEX]
    if isinstance(step, bool) or not isinstance(step, (int, float)):
        return None
    step = float(step)
    return step if math.isfinite(step) and 0.0 < step <= 1.0 else None


def section_for_group(group: str) -> str:
    """Registration section that lists the units of an IPU or OPU area."""
    kind = str(group).upper()
    if kind == "OPU":
        return OUTPUT_SECTION
    if kind == "IPU":
        return INPUT_SECTION
    raise RegistrationError(f"only IPU/OPU areas have registered units, not {kind or '?'}")


def _unit_entries(units: Any) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """``(definition, properties)`` of one unit key (registered as ``[definition, properties]``)."""
    found: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    if isinstance(units, list):
        for entry in units:
            meta = entry[0] if isinstance(entry, list) and entry else None
            if isinstance(meta, dict):
                props = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else None
                found.append((meta, props))
    return found


def match_unit(
    device_registrations: dict[str, Any], area: dict[str, Any], *, coding_only: bool = False
) -> UnitMatch:
    """The registered unit that owns ``area`` (an area record with ``unit_id``/``subunit_id``).

    Raises :class:`RegistrationError` when the registration has no such unit, or when several
    unit kinds match the same unit index: that is accepted only with ``coding_only`` (the
    caller needs the decode alone, not the unit's channels) and identical codings.
    """
    section = section_for_group(str(area.get("cortical_group", "")))
    unit_id, subunit_id = area.get("unit_id"), area.get("subunit_id")
    depth = channel_depth(area)
    if not isinstance(unit_id, int) or not isinstance(subunit_id, int) or depth is None:
        raise RegistrationError("the area record does not state unit_id, subunit_id and a z depth")
    units = device_registrations.get(section)
    if not isinstance(units, dict) or not units:
        raise NoUnitError(f"the registration has no {section}")
    matches: list[UnitMatch] = []
    rejected: list[str] = []
    for unit_key, entries in units.items():
        for meta, props in _unit_entries(entries):
            if meta.get("cortical_unit_index") != unit_id:
                continue
            try:
                coding = UnitCoding.build(section, str(unit_key), meta, subunit_id, depth)
            except ValueError as e:
                rejected.append(f"{unit_key}: {e}")
                continue
            matches.append(UnitMatch(coding, meta, props))
    if not matches:
        detail = f" ({'; '.join(rejected)})" if rejected else ""
        raise NoUnitError(
            f"no registered unit with cortical_unit_index {unit_id} codes area index "
            f"{subunit_id} as a percentage{detail}"
        )
    ambiguous = len(matches) > 1 and (
        not coding_only or any(not m.coding.same_coding(matches[0].coding) for m in matches[1:])
    )
    if ambiguous:
        kinds = sorted({m.coding.unit_key for m in matches})
        raise RegistrationError(
            f"units {kinds} share cortical_unit_index {unit_id}; the owner of the area cannot "
            "be told from the registration alone"
        )
    return matches[0]


def channel_count(area: dict[str, Any]) -> int | None:
    """Channels in an area (x extent divided by the per-device x extent), ``None`` if unstated."""
    dims = area.get("cortical_dimensions")
    per_device = area.get("cortical_dimensions_per_device")
    if not (isinstance(dims, list) and len(dims) == 3 and isinstance(per_device, list)):
        return None
    if len(per_device) != 3 or not isinstance(per_device[0], int) or per_device[0] < 1:
        return None
    if not isinstance(dims[0], int):
        return None
    return dims[0] // per_device[0]


def channel_depth(area: dict[str, Any]) -> int | None:
    """z extent of one channel (per-device z when stated, else the area z), ``None`` if unstated."""
    for dims in (area.get("cortical_dimensions_per_device"), area.get("cortical_dimensions")):
        if isinstance(dims, list) and len(dims) == 3 and isinstance(dims[2], int) and dims[2] >= 2:
            return int(dims[2])
    return None


def channel_entries(unit_definition: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """``device_grouping`` entries keyed by channel index (``channel_index_override`` wins)."""
    grouping = unit_definition.get("device_grouping")
    channels: dict[int, dict[str, Any]] = {}
    if not isinstance(grouping, list):
        return channels
    for position, entry in enumerate(grouping):
        if not isinstance(entry, dict):
            continue
        override = entry.get("channel_index_override")
        index = (
            override if isinstance(override, int) and not isinstance(override, bool) else position
        )
        channels[index] = entry
    return channels


def channel_registration(match: UnitMatch, channel: int) -> ChannelRegistration:
    """The channel's registration entry with its validated ``physical_range`` (if any).

    Raises :class:`RegistrationError` when the unit registers no such channel or states an
    invalid ``physical_range``.
    """
    entry = channel_entries(match.unit_definition).get(channel)
    if entry is None:
        raise RegistrationError(f"the registered unit has no channel {channel}")
    try:
        physical_range = parse_physical_range(entry.get("physical_range"))
    except ValueError as e:
        raise RegistrationError(f"channel {channel} physical_range is invalid: {e}") from e
    name = entry.get("friendly_name")
    flags = match.unit_definition.get("io_configuration_flags")
    frame = flags.get("frame_change_handling") if isinstance(flags, dict) else None
    return ChannelRegistration(
        match.coding,
        channel,
        physical_range,
        name if isinstance(name, str) and name else None,
        match.decoder_properties,
        frame if isinstance(frame, str) else None,
    )


def resolve_owner(
    agents: dict[str, dict[str, Any]], area: dict[str, Any], channel: int | None = None
) -> tuple[str, UnitMatch, ChannelRegistration | None]:
    """The one agent whose registration drives ``area`` (and ``channel`` when given).

    ``agents`` maps agent id to its normalized device-registrations map. Several agents are
    accepted only when they state the same coding (and the same physical range for a channel);
    otherwise it is an error asking for ``agent_id``. Raises :class:`RegistrationError`.
    """
    label = area.get("cortical_name") or area.get("cortical_id")
    owners: list[tuple[str, UnitMatch, ChannelRegistration | None]] = []
    notes: list[str] = []
    for agent_id, registrations in agents.items():
        try:
            match = match_unit(registrations, area, coding_only=channel is None)
        except NoUnitError as e:
            notes.append(f"{agent_id}: {e}")
            continue
        if channel is None:
            owners.append((agent_id, match, None))
            continue
        if channel not in channel_entries(match.unit_definition):
            notes.append(f"{agent_id}: its unit registers no channel {channel}")
            continue
        owners.append((agent_id, match, channel_registration(match, channel)))
    if not owners:
        detail = f" ({'; '.join(notes)})" if notes else ""
        raise RegistrationError(
            f"no registered agent drives {label}{detail}; the coding comes from a device "
            "registration, so a connected controller (or agent_id) is needed"
        )
    first = owners[0]
    for _, match, reg in owners[1:]:
        same_range = (
            reg is None or first[2] is None or reg.physical_range == first[2].physical_range
        )
        if not (match.coding.same_coding(first[1].coding) and same_range):
            ids = ", ".join(agent_id for agent_id, _, _ in owners)
            raise RegistrationError(
                f"{label} is registered by {len(owners)} agents ({ids}) with different "
                "registrations; pass agent_id"
            )
    return first
