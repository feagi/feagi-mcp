"""explain_motor_channel and lint_motor_channels over a fake FEAGI HTTP surface.

Neutral fixture: one 3-channel OPU area (101 bins per channel), two source areas writing
channel 0, one of which also inhibits the area; channel 1 has no writer.
"""

from __future__ import annotations

import pytest

from feagi_mcp import motor_channel_explain as mce
from tests.io_fixtures import (
    AGENT_A,
    DEPTH,
    OPU_ID,
    OTHER_ID,
    RANGE,
    SRC_A,
    SRC_B,
    FakeFeagi,
    opu_area,
    registration,
)


def rule(psc: float) -> dict:
    """One recorded mapping rule with the given psc multiplier."""
    return {"morphology_id": "m", "postSynapticCurrent_multiplier": psc, "synaptic_delay_bursts": 1}


def make_world() -> FakeFeagi:
    """Channel 0: SRC_A at z 50 (2 synapses) and z 60, SRC_B at z 60; B inhibits the area."""
    fake = FakeFeagi()
    fake.add_agent(AGENT_A, registration(ranges={0: RANGE}))
    fake.areas = [
        opu_area(),
        opu_area(cortical_id=OTHER_ID, cortical_name="servo-1", unit_id=1),
        opu_area(cortical_id=SRC_A, cortical_name="src-a", cortical_group="CUSTOM"),
        opu_area(cortical_id=SRC_B, cortical_name="src-b", cortical_group="CUSTOM"),
    ]
    fake.add_incoming(OPU_ID, (0, 0, 50), SRC_A, "src-a", n=2)
    fake.add_incoming(OPU_ID, (0, 0, 60), SRC_A, "src-a")
    fake.add_incoming(OPU_ID, (0, 0, 60), SRC_B, "src-b")
    fake.mappings = {
        SRC_A: {OPU_ID: [rule(2)]},
        SRC_B: {OPU_ID: [rule(2), rule(-3)], OTHER_ID: [rule(1)]},
    }
    return fake


async def test_explain_lists_writers_decoded_destinations_and_inhibition() -> None:
    fake = make_world()
    client = fake.client()
    out = await client.explain_motor_channel("servo-0", 0)
    assert out["agent_id"] == AGENT_A and out["variant"] == "UnsignedLinear"
    assert out["voxels_read"] == DEPTH == fake.voxel_calls and out["physical_range"] == RANGE
    first, second = out["writers"]
    assert (first["area"], first["synapses"], first["dst_voxel_count"]) == ("src-a", 3, 2)
    assert first["dst_z_runs"] == [[50, 50], [60, 60]]
    by_z = {d["voxel"][2]: d for d in first["dst_decoded"]}
    assert by_z[50]["fraction"] == pytest.approx(0.5) and by_z[50]["value"] == pytest.approx(0)
    assert by_z[60]["fraction"] == pytest.approx(0.4) and by_z[60]["unit"] == "deg"
    assert (second["area"], second["synapses"]) == ("src-b", 1)
    assert second["also_inhibits_area"] == [{"morphology": "m", "psc": -3}]
    assert out["inhibitory_inputs"] == [
        {
            "area": "src-b",
            "area_id": SRC_B,
            "rules": [{"morphology": "m", "psc": -3}],
            "writes_channel": True,
        }
    ]
    assert "truncated" not in out
    await client.close()


async def test_explain_pages_synapses_and_reports_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFeagi()
    fake.add_agent(AGENT_A, registration())
    fake.page_size = 2
    fake.add_incoming(OPU_ID, (0, 0, 5), SRC_A, "src-a", n=5)
    client = fake.client()
    full = await client.explain_motor_channel(OPU_ID, 0)
    assert full["writers"][0]["synapses"] == 5 and "truncated" not in full
    assert fake.voxel_calls == DEPTH + 2  # voxel (0,0,5) needs 3 pages
    monkeypatch.setattr(mce, "MAX_SYNAPSE_PAGES", 2)
    capped = await client.explain_motor_channel(OPU_ID, 0)
    assert capped["writers"][0]["synapses"] == 4
    assert capped["truncated"]["voxels_with_more_synapses"] == [[0, 0, 5]]
    assert capped["truncated"]["synapse_pages_capped_at"] == 2
    await client.close()


async def test_explain_reports_voxel_read_failures() -> None:
    fake = make_world()
    fake.fail_voxel = {(0, 0, 7)}
    out = await fake.client().explain_motor_channel(OPU_ID, 0)
    assert out["truncated"]["voxel_read_error_count"] == 1
    assert "[0, 0, 7]" in out["truncated"]["voxel_read_errors"][0]
    assert out["writers"]  # the other voxels still answered


async def test_explain_without_a_registration_lists_raw_voxels() -> None:
    fake = make_world()
    fake.agents.clear()
    out = await fake.client().explain_motor_channel(OPU_ID, 0)
    assert out["registration"]["decode"] == "unavailable" and "variant" not in out
    assert out["writers"][0]["dst_voxels"] == [[0, 0, 50], [0, 0, 60]]
    assert "dst_decoded" not in out["writers"][0]


async def test_explain_argument_errors() -> None:
    fake = make_world()
    client = fake.client()
    assert "channel" in (await client.explain_motor_channel(OPU_ID, -1))["error"]
    assert "burst" in (await client.explain_motor_channel(OPU_ID, 0, burst=-2))["error"]
    assert "unknown cortical area" in (await client.explain_motor_channel("nope", 0))["error"]
    assert "OPU" in (await client.explain_motor_channel(SRC_A, 0))["error"]
    assert "out of range" in (await client.explain_motor_channel(OPU_ID, 3))["error"]
    assert (
        "not registered" in (await client.explain_motor_channel(OPU_ID, 0, agent_id="x"))["error"]
    )


def ledger(fake: FakeFeagi, window: int = 20) -> None:
    """Track the OPU and both writers; channel 0 fired z=50 and z=60 at burst 95."""
    fake.ledger_windows = {OPU_ID: window, SRC_A: window, SRC_B: window}
    fake.ledger_frames = {
        OPU_ID: {95: [[0, 0, 50], [0, 0, 60], [1, 0, 3]]},
        SRC_A: {95: [[0, 0, 0]]},
        SRC_B: {},
    }


async def test_burst_decodes_the_recorded_command_without_resizing_windows() -> None:
    fake = make_world()
    ledger(fake)
    out = await fake.client().explain_motor_channel(OPU_ID, 0, burst=95)
    view = out["at_burst"]
    assert view["channel_fired_voxels"] == [[0, 0, 50], [0, 0, 60]]
    assert view["command"]["fraction"] == pytest.approx(0.45)
    assert view["command"]["value"] == pytest.approx(-9.0) and view["command"]["unit"] == "deg"
    assert view["writers_fired"] == {SRC_A: 1}
    assert fake.ledger_reads and all(bursts == 20 for _, bursts in fake.ledger_reads)


async def test_burst_errors_when_untracked_or_outside_the_window() -> None:
    fake = make_world()
    ledger(fake)
    del fake.ledger_windows[SRC_B]
    untracked = (await fake.client().explain_motor_channel(OPU_ID, 0, burst=95))["at_burst"]
    assert "not tracked" in untracked["error"] and SRC_B in untracked["error"]
    assert fake.ledger_reads == []  # nothing was read, so nothing was subscribed
    ledger(fake)
    old = (await fake.client().explain_motor_channel(OPU_ID, 0, burst=10))["at_burst"]
    assert "outside the recorded window" in old["error"]
    future = (await fake.client().explain_motor_channel(OPU_ID, 0, burst=500))["at_burst"]
    assert "outside the recorded window" in future["error"]


async def test_burst_with_no_channel_voxel_fired_has_no_command() -> None:
    fake = make_world()
    ledger(fake)
    view = (await fake.client().explain_motor_channel(OPU_ID, 0, burst=96))["at_burst"]
    assert view["command"] is None and "no voxel" in view["note"]


async def test_lint_warns_with_evidence_and_never_calls_a_channel_wrong() -> None:
    fake = make_world()
    out = await fake.client().lint_motor_channels("servo-0")
    assert out["channels_checked"] == 3 and out["voxel_reads"] == 3 * DEPTH
    codes = {(w["channel"], w["code"]) for w in out["warnings"]}
    assert codes == {(0, "multiple_writers"), (1, "no_writer_found"), (2, "no_writer_found")}
    multiple = next(w for w in out["warnings"] if w["code"] == "multiple_writers")
    assert [w["area"] for w in multiple["evidence"]["writers"]] == ["src-a", "src-b"]
    assert multiple["evidence"]["inhibitory_inputs"] == ["src-b"]
    assert "inhibitory input area(s) found" in multiple["detail"]
    assert not any("wrong" in str(w).lower() for w in out["warnings"])
    assert "not_checked" not in out and "truncated" not in out


async def test_lint_without_inhibition_says_none_found() -> None:
    fake = make_world()
    fake.mappings = {SRC_A: {OPU_ID: [rule(2)]}, SRC_B: {OPU_ID: [rule(2)]}}
    out = await fake.client().lint_motor_channels(OPU_ID)
    multiple = next(w for w in out["warnings"] if w["code"] == "multiple_writers")
    assert "no inhibitory input found" in multiple["detail"]
    assert multiple["evidence"]["inhibitory_inputs"] == []


async def test_lint_all_areas_checks_opu_only_and_reports_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_world()
    monkeypatch.setattr(mce, "LINT_VOXEL_BUDGET", 2 * DEPTH + 10)
    out = await fake.client().lint_motor_channels()
    assert out["areas_checked"] == 2  # both OPU areas; the CUSTOM sources are not linted
    assert out["channels_checked"] == 2 and out["voxel_reads"] == 2 * DEPTH
    assert out["not_checked"]["count"] == 4 and "budget" in out["not_checked"]["reason"]
    assert {(c["area"], c["channel"]) for c in out["not_checked"]["channels"]} == {
        ("servo-0", 2),
        ("servo-1", 0),
        ("servo-1", 1),
        ("servo-1", 2),
    }


async def test_lint_reports_truncated_scans_and_bad_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_world()
    fake.page_size = 1
    monkeypatch.setattr(mce, "MAX_SYNAPSE_PAGES", 1)
    out = await fake.client().lint_motor_channels(OPU_ID)
    assert out["truncated"] and out["truncated"][0]["channel"] == 0
    assert "OPU" in (await fake.client().lint_motor_channels(SRC_A))["error"]
    assert "unknown cortical area" in (await fake.client().lint_motor_channels("nope"))["error"]
    assert (
        "not registered" in (await fake.client().lint_motor_channels(OPU_ID, agent_id="x"))["error"]
    )
