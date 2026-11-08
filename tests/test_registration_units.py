"""Registration lookup: which unit owns an area, its channels and physical ranges."""

from __future__ import annotations

from typing import Any

import pytest

from feagi_mcp.percentage_coding import OUTPUT_SECTION
from feagi_mcp.registration_units import (
    NoUnitError,
    RegistrationError,
    channel_entries,
    channel_registration,
    match_unit,
    resolve_owner,
)
from tests.io_fixtures import DEPTH, RANGE, opu_area, registration, unit_definition


def test_match_uses_unit_index_and_area_index() -> None:
    match = match_unit(registration(index=2), opu_area(unit_id=2, subunit_id=1))
    assert match.coding.unit_key == "PositionalServo"
    assert match.coding.area_index == 1 and match.coding.depth == DEPTH
    assert match.coding.variant == "UnsignedLinear"


def test_missing_unit_section_or_index_is_no_unit() -> None:
    with pytest.raises(NoUnitError):
        match_unit({}, opu_area())
    with pytest.raises(NoUnitError, match="cortical_unit_index 5"):
        match_unit(registration(index=0), opu_area(unit_id=5))
    with pytest.raises(RegistrationError, match="unit_id"):
        match_unit(registration(), opu_area(unit_id=None))
    with pytest.raises(RegistrationError, match="only IPU/OPU"):
        match_unit(registration(), opu_area(cortical_group="CUSTOM"))


def test_non_percentage_unit_is_rejected_by_the_binding() -> None:
    misc = {OUTPUT_SECTION: {"MiscData": [[unit_definition(), {}]]}}
    with pytest.raises(NoUnitError, match="MiscData"):
        match_unit(misc, opu_area())


def test_two_unit_kinds_on_one_index_are_ambiguous_for_a_channel() -> None:
    both = {
        OUTPUT_SECTION: {
            "PositionalServo": [[unit_definition(), {}]],
            "CountOutput": [[unit_definition(), {}]],
        }
    }
    with pytest.raises(RegistrationError, match="cannot be told"):
        match_unit(both, opu_area())
    # the decode alone is the same either way, so a coding-only lookup accepts it
    assert match_unit(both, opu_area(), coding_only=True).coding.variant == "UnsignedLinear"
    signed = {
        OUTPUT_SECTION: {
            "PositionalServo": [[unit_definition(), {}]],
            "RotaryMotor": [[unit_definition(), {}]],
        }
    }
    with pytest.raises(RegistrationError, match="cannot be told"):
        match_unit(signed, opu_area(), coding_only=True)


def test_channel_index_override_wins_and_physical_range_is_read() -> None:
    unit = unit_definition(channels=2, ranges={0: RANGE})
    unit["device_grouping"][1]["channel_index_override"] = 5
    assert sorted(channel_entries(unit)) == [0, 5]
    reg = {OUTPUT_SECTION: {"PositionalServo": [[unit, {}]]}}
    match = match_unit(reg, opu_area())
    stated = channel_registration(match, 0)
    assert stated.physical_range is not None and stated.physical_range.unit == "deg"
    assert stated.friendly_name == "joint_0"
    assert channel_registration(match, 5).physical_range is None
    with pytest.raises(RegistrationError, match="no channel 1"):
        channel_registration(match, 1)


def test_invalid_physical_range_names_the_channel() -> None:
    bad = {"value_at_0": 1.0, "value_at_1": 1.0, "unit": "deg"}
    match = match_unit(registration(ranges={1: bad}), opu_area())
    with pytest.raises(RegistrationError, match="channel 1 physical_range is invalid"):
        channel_registration(match, 1)


def test_resolve_owner_picks_the_driving_agent_and_rejects_conflicts() -> None:
    area = opu_area()
    agents: dict[str, dict[str, Any]] = {
        "a": registration(ranges={0: RANGE}),
        "b": {},
    }
    agent_id, _, reg = resolve_owner(agents, area, 0)
    assert agent_id == "a" and reg is not None and reg.physical_range is not None
    with pytest.raises(RegistrationError, match="no registered agent drives servo-0"):
        resolve_owner({"b": {}}, area, 0)
    with pytest.raises(RegistrationError, match="no channel 7"):
        resolve_owner({"a": registration()}, area, 7)
    other = {"value_at_0": 0.0, "value_at_1": 1.0, "unit": "rad"}
    conflict = {"a": registration(ranges={0: RANGE}), "b": registration(ranges={0: other})}
    with pytest.raises(RegistrationError, match="2 agents"):
        resolve_owner(conflict, area, 0)
    agreeing = {"a": registration(ranges={0: RANGE}), "b": registration(ranges={0: RANGE})}
    assert resolve_owner(agreeing, area, 0)[0] == "a"
