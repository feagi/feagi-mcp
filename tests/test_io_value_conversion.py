"""convert_io_value and send_motor_command: bindings for the bin rule, registered physical ranges.

Only the HTTP transport is faked (:class:`tests.io_fixtures.FakeFeagi`); the registrations and
area records follow recorded shapes. Names and numbers are neutral test fixtures.
"""

from __future__ import annotations

import httpx
import pytest

from feagi_mcp.io_value_conversion import (
    convert_channel_value,
    plan_channel_command,
    validate_command_input,
    validate_conversion_input,
)
from feagi_mcp.percentage_coding import (
    INPUT_SECTION,
    OUTPUT_SECTION,
    UnitCoding,
    parse_physical_range,
)
from feagi_mcp.registration_units import (
    ChannelRegistration,
    channel_registration,
    match_unit,
)
from tests.io_fixtures import (
    AGENT_A,
    AGENT_B,
    DEPTH,
    INCREMENTAL_LINEAR,
    OPU_ID,
    RANGE,
    FakeFeagi,
    opu_area,
    registration,
    servo_coding,
    unit_definition,
)


def channel_reg(with_range: bool = True, coding=None) -> ChannelRegistration:
    """A channel registration over the servo coding, with or without a physical range."""
    return ChannelRegistration(
        coding or servo_coding(), 0, parse_physical_range(RANGE) if with_range else None, "j0"
    )


# ----------------------------------------------------------------------------- incremental

STEP_DEPTH = 512
STEP_RANGE = {"value_at_0": -1.5708, "value_at_1": 1.5708, "unit": "rad"}
SPAN = 2 * 1.5708


def incremental_area() -> dict:
    """A 2-column-per-channel incremental OPU area at depth 512."""
    return opu_area(
        coding_behavior="Incremental",
        cortical_dimensions=[6, 1, STEP_DEPTH],
        cortical_dimensions_per_device=[2, 1, STEP_DEPTH],
    )


def incremental_reg(properties: dict | None, area: dict | None = None):
    """The channel registration of an incremental servo unit with the given properties."""
    regs = registration(properties=properties, ranges={0: STEP_RANGE}, flags=INCREMENTAL_LINEAR)
    match = match_unit(regs, area or incremental_area())
    return channel_registration(match, 0)


def test_incremental_servo_bin_gives_signed_column_steps() -> None:
    reg = incremental_reg({"PositionalServoTargetSpeed": [STEP_DEPTH, "Linear", [0.5], 1.0]})
    out = convert_channel_value(incremental_area(), 0, reg, bin_value=508)
    p = 1 - 508 / 511
    assert out["framing"] == "incremental" and out["semantics"] == "step"
    assert out["p"] == pytest.approx(p, abs=1e-6) and out["fraction"] == out["p"]
    inc, dec = out["columns"]
    assert (inc["role"], inc["x"], dec["role"], dec["x"]) == ("increase", 0, "decrease", 1)
    assert dec["step_fraction"] == pytest.approx(-p, abs=1e-6)
    assert dec["step_value"] == pytest.approx(-p * SPAN, abs=1e-5)
    assert inc["step_fraction"] == pytest.approx(p, abs=1e-6)
    assert out["step_size_0_1"] == 1.0 and out["step_size_source"] == "registration"
    assert out["value"] is None and out["unit"] is None


def test_incremental_servo_without_registered_step_has_null_steps() -> None:
    out = convert_channel_value(incremental_area(), 0, incremental_reg({}), bin_value=508)
    assert out["step_size_0_1"] is None and "not registered" in out["step_size_source"]
    assert all(c["step_fraction"] is None and c["step_value"] is None for c in out["columns"])
    refused = convert_channel_value(incremental_area(), 0, incremental_reg({}), value=0.1)
    assert "step size" in refused["error"]


def test_incremental_servo_invalid_step_counts_as_not_registered() -> None:
    for bad in (0.0, 1.5, -1.0, float("nan"), "x", True):
        reg = incremental_reg({"PositionalServoTargetSpeed": [STEP_DEPTH, "Linear", [], bad]})
        out = convert_channel_value(incremental_area(), 0, reg, bin_value=3)
        assert out["step_size_0_1"] is None


def test_incremental_servo_fraction_and_value_inputs() -> None:
    reg = incremental_reg({"PositionalServoTargetSpeed": [STEP_DEPTH, "Linear", [], 0.5]})
    by_fraction = convert_channel_value(incremental_area(), 0, reg, fraction=1.0)
    assert by_fraction["bin"] == 0 and by_fraction["p"] == 1.0
    by_value = convert_channel_value(incremental_area(), 0, reg, value=SPAN * 0.5 * 0.25)
    assert by_value["requested_fraction"] == pytest.approx(0.25)
    assert by_value["p"] == pytest.approx(0.25, abs=0.002)
    too_big = convert_channel_value(incremental_area(), 0, reg, value=SPAN)
    assert "exceeds" in too_big["error"]


def test_incremental_unit_with_area_lacking_coding_behavior_is_an_error() -> None:
    area = incremental_area()
    reg = incremental_reg(None, area)
    del area["coding_behavior"]
    assert "coding_behavior" in convert_channel_value(area, 0, reg, bin_value=1)["error"]


def test_absolute_area_output_is_unchanged_by_incremental_support() -> None:
    out = convert_channel_value(opu_area(), 0, channel_reg(), bin_value=0)
    assert set(out) == {
        "area_id", "area_name", "kind", "channel", "channel_count", "depth", "variant",
        "physical_range", "bin", "fraction", "value", "unit",
    }  # fmt: skip


def test_incremental_pointer_reports_velocity_semantics_only() -> None:
    area = incremental_area()
    regs = registration("SpatialPointer", flags=INCREMENTAL_LINEAR)
    reg = channel_registration(match_unit(regs, area), 0)
    out = convert_channel_value(area, 0, reg, fraction=0.5)
    assert out["framing"] == "incremental" and out["semantics"] == "velocity"
    assert "columns" not in out


# ----------------------------------------------------------------------------- pure


def test_validate_conversion_input_requires_exactly_one() -> None:
    assert validate_conversion_input(3, None, None) is None
    assert validate_conversion_input(None, 0.5, None) is None
    assert validate_conversion_input(None, None, 1.5) is None
    assert validate_conversion_input(None, None, None) is not None
    assert validate_conversion_input(1, 0.5, None) is not None
    assert validate_conversion_input(-1, None, None) is not None
    assert validate_conversion_input(True, None, None) is not None
    assert validate_conversion_input(1.5, None, None) is not None
    assert validate_conversion_input(None, "x", None) is not None


def test_bin_to_fraction_and_physical_value() -> None:
    top = convert_channel_value(opu_area(), 0, channel_reg(), bin_value=0)
    bottom = convert_channel_value(opu_area(), 0, channel_reg(), bin_value=DEPTH - 1)
    assert top["fraction"] == 1.0 and top["value"] == 90.0 and top["unit"] == "deg"
    assert bottom["fraction"] == 0.0 and bottom["value"] == -90.0
    assert top["variant"] == "UnsignedLinear" and top["depth"] == DEPTH
    assert top["physical_range"] == RANGE and "position_fraction" not in top


def test_fraction_and_value_give_the_nearest_bin_and_what_it_decodes_to() -> None:
    by_fraction = convert_channel_value(opu_area(), 0, channel_reg(), fraction=0.5)
    assert by_fraction["bin"] == 50 and by_fraction["fraction"] == pytest.approx(0.5)
    assert by_fraction["requested_fraction"] == 0.5 and by_fraction["value"] == pytest.approx(0)
    by_value = convert_channel_value(opu_area(), 0, channel_reg(), value=45.0)
    assert by_value["requested_value"] == 45.0 and by_value["requested_fraction"] == 0.75
    assert by_value["bin"] == 25 and by_value["fraction"] == pytest.approx(0.75)
    assert "clamped" not in by_value


def test_value_outside_the_range_is_clamped_and_flagged() -> None:
    out = convert_channel_value(opu_area(), 0, channel_reg(), value=500.0)
    assert out["bin"] == 0 and out["clamped"] is True and out["value"] == 90.0


def test_without_a_physical_range_value_is_null_and_unit_unknown() -> None:
    by_bin = convert_channel_value(opu_area(), 0, channel_reg(False), bin_value=25)
    assert by_bin["value"] is None and by_bin["unit"] == "unknown"
    assert by_bin["physical_range"] is None and 0 < by_bin["fraction"] < 1
    by_fraction = convert_channel_value(opu_area(), 0, channel_reg(False), fraction=0.3)
    assert by_fraction["value"] is None and by_fraction["unit"] == "unknown"
    refused = convert_channel_value(opu_area(), 0, channel_reg(False), value=3.0)
    assert "physical_range" in refused["error"] and "bin" not in refused


def test_out_of_range_channel_bin_and_fraction_are_errors() -> None:
    assert "error" in convert_channel_value(opu_area(), 3, channel_reg(), bin_value=0)
    assert "error" in convert_channel_value(opu_area(), 0, channel_reg(), bin_value=DEPTH)
    with pytest.raises(ValueError, match="within 0..1"):
        convert_channel_value(opu_area(), 0, channel_reg(), fraction=1.5)


def test_two_lobe_variant_returns_both_lobes_and_rejects_a_bare_bin() -> None:
    flags = {"frame_change_handling": "Incremental", "percentage_neuron_positioning": "Linear"}
    coding = UnitCoding.build(OUTPUT_SECTION, "SpatialPointer", unit_definition(flags=flags), 0, 9)
    reg = ChannelRegistration(coding, 0, None, None)
    area = opu_area(cortical_dimensions=[6, 1, 9], cortical_dimensions_per_device=[2, 1, 9])
    out = convert_channel_value(area, 0, reg, fraction=0.9)
    assert out["z_positive"] and "bin" not in out
    assert "lobe" in convert_channel_value(area, 0, reg, bin_value=2)["error"]


def test_validate_command_input() -> None:
    assert validate_command_input(0.5, None) is None
    assert validate_command_input(None, 12.0) is None
    assert validate_command_input(None, None) is not None
    assert validate_command_input(0.5, 1.0) is not None
    assert validate_command_input(True, None) is not None


def test_plan_command_fraction_always_value_needs_a_range() -> None:
    plan = plan_channel_command(opu_area(), channel_reg(False), fraction=0.5)
    assert plan["voxels"] == [[0, 0, 50]] and plan["bin"] == 50 and plan["value"] is None
    with pytest.raises(ValueError, match="physical_range"):
        plan_channel_command(opu_area(), channel_reg(False), value=10.0)
    ranged = plan_channel_command(opu_area(), channel_reg(), value=45.0)
    assert ranged["bin"] == 25 and ranged["unit"] == "deg" and ranged["value"] == pytest.approx(45)
    clamped = plan_channel_command(opu_area(), channel_reg(), value=-500.0)
    assert clamped["clamped"] is True and clamped["bin"] == DEPTH - 1


def test_plan_command_voxel_x_follows_the_channel_width() -> None:
    reg = ChannelRegistration(servo_coding(), 2, None, None)
    area = opu_area(cortical_dimensions=[6, 1, DEPTH], cortical_dimensions_per_device=[2, 1, DEPTH])
    assert plan_channel_command(area, reg, fraction=1.0)["voxels"] == [[4, 0, 0]]


# ------------------------------------------------------------------ client (fake transport)


def world(**regs: dict) -> FakeFeagi:
    """A fake FEAGI with the default OPU and one agent per keyword."""
    fake = FakeFeagi()
    for agent_id, reg in regs.items():
        fake.add_agent(agent_id.replace("_", "-"), reg)
    return fake


async def test_client_converts_with_the_registered_unit_and_range() -> None:
    fake = world(agent_a=registration(ranges={1: RANGE}))
    client = fake.client()
    out = await client.convert_io_value("servo-0", 1, bin=0)
    assert out["agent_id"] == AGENT_A and out["variant"] == "UnsignedLinear"
    assert out["value"] == 90.0 and out["unit"] == "deg" and out["fraction"] == 1.0
    again = await client.convert_io_value(OPU_ID, 1, value=0.0)
    assert again["bin"] == 50 and again["fraction"] == pytest.approx(0.5)
    assert fake.seen.count("/v1/agent/capabilities/all") == 2
    await client.close()


async def test_client_unstated_range_is_unknown_not_guessed() -> None:
    client = world(agent_a=registration()).client()
    out = await client.convert_io_value(OPU_ID, 0, bin=10)
    assert out["value"] is None and out["unit"] == "unknown" and out["physical_range"] is None
    assert "physical_range" in (await client.convert_io_value(OPU_ID, 0, value=1.0))["error"]
    await client.close()


async def test_client_ambiguous_agents_is_an_error_and_agent_id_resolves_it() -> None:
    other = {"value_at_0": 0.0, "value_at_1": 1.0, "unit": "rad"}
    client = world(
        agent_a=registration(ranges={0: RANGE}), agent_b=registration(ranges={0: other})
    ).client()
    assert "2 agents" in (await client.convert_io_value(OPU_ID, 0, bin=0))["error"]
    chosen = await client.convert_io_value(OPU_ID, 0, bin=0, agent_id=AGENT_B)
    assert chosen["agent_id"] == AGENT_B and chosen["value"] == 1.0 and chosen["unit"] == "rad"
    assert (
        "not registered" in (await client.convert_io_value(OPU_ID, 0, bin=0, agent_id="x"))["error"]
    )
    await client.close()


async def test_client_skips_agents_without_the_direction_capability() -> None:
    fake = world(agent_a=registration(ranges={0: RANGE}), agent_b=registration())
    fake.agents[AGENT_B]["capabilities"]["motor"] = False
    client = fake.client()
    assert (await client.convert_io_value(OPU_ID, 0, bin=0))["agent_id"] == AGENT_A
    await client.close()


async def test_client_no_registered_agent_is_an_error_naming_the_need() -> None:
    client = world().client()
    out = await client.convert_io_value(OPU_ID, 0, fraction=0.2)
    assert "no registered agent drives servo-0" in out["error"] and "bin" not in out
    await client.close()


async def test_client_ipu_uses_the_sensory_registration() -> None:
    ipu = opu_area(cortical_id="IIIIIIIIII=", cortical_name="sense-0", cortical_group="IPU")
    fake = FakeFeagi()
    fake.areas = [opu_area(), ipu]
    fake.add_agent(
        "sensor",
        {INPUT_SECTION: {"Proximity": [[unit_definition(), {}]]}},
        motor=False,
        sensory=True,
    )
    client = fake.client()
    out = await client.convert_io_value("sense-0", 0, bin=2)
    assert (
        out["kind"] == "IPU" and out["variant"] == "UnsignedLinear" and out["agent_id"] == "sensor"
    )
    assert out["value"] is None and out["unit"] == "unknown"
    await client.close()


async def test_client_rejects_bad_arguments_before_any_request() -> None:
    fake = world(agent_a=registration())
    client = fake.client()
    for kwargs in ({}, {"bin": 1, "value": 1.0}, {"bin": -1}, {"bin": 1, "fraction": 0.5}):
        assert "error" in await client.convert_io_value(OPU_ID, 0, **kwargs)
    assert "error" in await client.convert_io_value(OPU_ID, -1, bin=0)
    assert fake.seen == []
    assert "unknown cortical area" in (await client.convert_io_value("nope", 0, bin=0))["error"]
    assert "within 0..1" in (await client.convert_io_value(OPU_ID, 0, fraction=2.0))["error"]
    await client.close()


async def test_client_http_failure_is_an_error_not_an_empty_answer() -> None:
    fake = world(agent_a=registration())
    client = fake.client()
    original = fake.handler

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/agent/capabilities/all":
            return httpx.Response(500, text="boom")
        return original(request)

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(failing))
    assert "error" in await client.convert_io_value(OPU_ID, 0, bin=0)
    await client.close()


# ------------------------------------------------------------ send_motor_command (fake HTTP)


def with_joint(fake: FakeFeagi) -> None:
    """Register the joint-map names the registration's friendly names do not provide."""
    for entry in fake.agents[AGENT_A]["device_registrations"][OUTPUT_SECTION]["PositionalServo"][0][
        0
    ]["device_grouping"]:
        entry["device_properties"] = {
            "joint_name": {"type": "String", "value": entry["friendly_name"]}
        }


async def test_send_motor_command_fraction_always_works() -> None:
    fake = world(agent_a=registration())
    with_joint(fake)
    client = fake.client()
    out = await client.send_motor_command(AGENT_A, "joint_2", fraction=0.25)
    assert out["success"] is True and out["channel"] == 2
    assert out["bin"] == 75 and out["voxels"] == [[2, 0, 75]] and out["unit"] == "unknown"
    assert fake.stimulations[-1]["stimulation_payload"] == {OPU_ID: [[2, 0, 75]]}
    await client.close()


async def test_send_motor_command_value_needs_the_registered_range() -> None:
    fake = world(agent_a=registration(ranges={0: RANGE}))
    with_joint(fake)
    client = fake.client()
    ok = await client.send_motor_command(AGENT_A, "joint_0", value=45.0)
    assert ok["bin"] == 25 and ok["unit"] == "deg" and ok["value"] == pytest.approx(45.0)
    refused = await client.send_motor_command(AGENT_A, "joint_1", value=45.0)
    assert "physical_range" in refused["error"] and "success" not in refused
    assert len(fake.stimulations) == 1
    clamped = await client.send_motor_command(AGENT_A, "joint_0", value=999.0)
    assert clamped["clamped"] is True and clamped["bin"] == 0
    await client.close()


async def test_send_motor_command_input_and_joint_errors() -> None:
    fake = world(agent_a=registration(ranges={0: RANGE}))
    with_joint(fake)
    client = fake.client()
    assert "exactly one" in (await client.send_motor_command(AGENT_A, "joint_0"))["error"]
    both = await client.send_motor_command(AGENT_A, "joint_0", fraction=0.5, value=1.0)
    assert "exactly one" in both["error"]
    missing = await client.send_motor_command(AGENT_A, "nope", fraction=0.5)
    assert "not found" in missing["error"] and "joint_0" in missing["available_joints"]
    assert (
        "within 0..1"
        in (await client.send_motor_command(AGENT_A, "joint_0", fraction=2.0))["error"]
    )
    assert fake.stimulations == []
    await client.close()


async def test_send_motor_command_matches_actuator_names() -> None:
    fake = world(agent_a=registration(ranges={0: RANGE}))
    unit = fake.agents[AGENT_A]["device_registrations"][OUTPUT_SECTION]["PositionalServo"][0][0]
    unit["device_grouping"][0]["device_properties"] = {
        "joint_name": {"type": "String", "value": ""},
        "actuator_name": {"type": "String", "value": "actuator_x"},
    }
    client = fake.client()
    out = await client.send_motor_command(AGENT_A, "ACTUATOR_X", fraction=1.0)
    assert out["success"] is True and out["voxels"] == [[0, 0, 0]] and out["value"] == 90.0
    await client.close()
