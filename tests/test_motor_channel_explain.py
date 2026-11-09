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


GATE = "GATE0000001="
HOLD = "HOLD0000001="


def make_world(mappings: dict | None = None) -> FakeFeagi:
    """Channel 0: SRC_A at z 50 (2 synapses) and z 60, SRC_B at z 60; channel 2: SRC_A only.

    Default mappings mirror a recorded case: SRC_A is inhibited by two areas (psc -10, -50),
    SRC_B by none; an unrelated area inhibits the OPU itself (must not show up anywhere).
    """
    fake = FakeFeagi()
    fake.add_agent(AGENT_A, registration(ranges={0: RANGE}))
    fake.areas = [
        opu_area(),
        opu_area(cortical_id=OTHER_ID, cortical_name="servo-1", unit_id=1),
        opu_area(cortical_id=SRC_A, cortical_name="src-a", cortical_group="CUSTOM"),
        opu_area(cortical_id=SRC_B, cortical_name="src-b", cortical_group="CUSTOM"),
        opu_area(cortical_id=GATE, cortical_name="gate", cortical_group="CUSTOM"),
        opu_area(cortical_id=HOLD, cortical_name="hold", cortical_group="CUSTOM"),
    ]
    fake.add_incoming(OPU_ID, (0, 0, 50), SRC_A, "src-a", n=2)
    fake.add_incoming(OPU_ID, (0, 0, 60), SRC_A, "src-a")
    fake.add_incoming(OPU_ID, (0, 0, 60), SRC_B, "src-b")
    fake.add_incoming(OPU_ID, (2, 0, 5), SRC_A, "src-a")
    fake.mappings = mappings or {
        SRC_A: {OPU_ID: [rule(2)]},
        SRC_B: {OPU_ID: [rule(2)], OTHER_ID: [rule(1)]},
        GATE: {SRC_A: [rule(-10)]},
        HOLD: {SRC_A: [rule(-50)], OPU_ID: [rule(-7)]},
    }
    return fake


async def test_explain_lists_writers_decoded_destinations_and_their_inhibitors() -> None:
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
    # inhibition is read per writer: the writer's own negative inputs, names and psc
    assert [(i["area"], i["psc"]) for i in first["inhibited_by"]] == [
        ("gate", [-10]),
        ("hold", [-50]),
    ]
    assert (second["area"], second["inhibited_by"]) == ("src-b", [])
    # the inhibitor of the OPU itself (hold, psc -7) is not a writer input and is not reported
    assert "inhibitory_inputs" not in out
    # one pair of writers, nothing between them: gate/hold inhibit only src-a
    assert out["writer_relations"] == {
        "unarbitrated_pairs": ["src-a / src-b"],
        "direct": [],
        "shared_gates": [],
        "unarbitrated_count": 1,
    }
    assert "truncated" not in out
    await client.close()


async def test_explain_reads_only_the_requested_channel_columns() -> None:
    fake = make_world()
    await fake.client().explain_motor_channel(OPU_ID, 1)
    assert {key[1] for key in fake.voxel_keys} == {1} and len(fake.voxel_keys) == DEPTH
    wide = FakeFeagi()
    wide.areas = [
        opu_area(cortical_dimensions=[6, 1, DEPTH], cortical_dimensions_per_device=[2, 1, DEPTH])
    ]
    await wide.client().explain_motor_channel(OPU_ID, 2)
    assert {key[1] for key in wide.voxel_keys} == {4, 5}
    assert len(wide.voxel_keys) == 2 * DEPTH


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


async def test_lint_warns_for_the_unarbitrated_pair_of_writers() -> None:
    fake = make_world()
    out = await fake.client().lint_motor_channels("servo-0")
    assert out["channels_checked"] == 3 and out["voxel_reads"] == 3 * DEPTH
    codes = {(w["channel"], w["code"]) for w in out["warnings"]}
    assert codes == {(0, "multiple_writers"), (1, "no_writer_found")}
    multiple = next(w for w in out["warnings"] if w["code"] == "multiple_writers")
    evidence = multiple["evidence"]
    assert evidence["relations"]["unarbitrated_pairs"] == ["src-a / src-b"]
    assert "src-a / src-b" in multiple["detail"]
    assert [(w["area"], w["inhibited_by"]) for w in evidence["writers"]] == [
        ("src-a", ["gate", "hold"]),
        ("src-b", []),
    ]
    assert not any("wrong" in str(w).lower() for w in out["warnings"])
    assert "not_checked" not in out and "truncated" not in out


async def test_lint_reads_each_writers_mappings_once_across_channels() -> None:
    fake = make_world()
    await fake.client().lint_motor_channels("servo-0")
    # writers src-a (channels 0 and 2) and src-b: two mapping reads, not one per channel
    assert fake.seen.count("/v1/cortical_area/cortical_map_detailed") == 2
    assert fake.seen.count("/v1/cortical_area/cortical_id_name_mapping") >= 1


async def test_two_writers_that_inhibit_each_other_are_not_flagged() -> None:
    fake = make_world(
        {
            SRC_A: {OPU_ID: [rule(2)], SRC_B: [rule(-5)]},
            SRC_B: {OPU_ID: [rule(2)], SRC_A: [rule(-5)]},
        }
    )
    client = fake.client()
    explained = await client.explain_motor_channel(OPU_ID, 0)
    assert explained["writer_relations"]["direct"] == ["src-a and src-b inhibit each other"]
    out = await client.lint_motor_channels(OPU_ID)
    assert {w["code"] for w in out["warnings"]} == {"no_writer_found"}


async def test_one_way_inhibition_between_writers_is_reported_and_clears_the_warning() -> None:
    fake = make_world({SRC_A: {OPU_ID: [rule(2)], SRC_B: [rule(-5)]}, SRC_B: {OPU_ID: [rule(2)]}})
    explained = await fake.client().explain_motor_channel(OPU_ID, 0)
    assert explained["writer_relations"]["direct"] == ["src-a inhibits src-b"]
    out = await fake.client().lint_motor_channels(OPU_ID)
    assert "multiple_writers" not in {w["code"] for w in out["warnings"]}


async def test_a_shared_gate_clears_the_warning_and_a_private_gate_does_not() -> None:
    shared = make_world(
        {
            SRC_A: {OPU_ID: [rule(2)]},
            SRC_B: {OPU_ID: [rule(2)]},
            GATE: {SRC_A: [rule(-10)], SRC_B: [rule(-10)]},
        }
    )
    explained = await shared.client().explain_motor_channel(OPU_ID, 0)
    assert explained["writer_relations"]["shared_gates"] == ["gate inhibits src-a, src-b"]
    out = await shared.client().lint_motor_channels(OPU_ID)
    assert "multiple_writers" not in {w["code"] for w in out["warnings"]}
    private = make_world(
        {SRC_A: {OPU_ID: [rule(2)]}, SRC_B: {OPU_ID: [rule(2)]}, GATE: {SRC_A: [rule(-10)]}}
    )
    flagged = await private.client().lint_motor_channels(OPU_ID)
    assert "multiple_writers" in {w["code"] for w in flagged["warnings"]}


async def test_unreadable_writer_mappings_are_reported_not_called_absent() -> None:
    fake = make_world()
    fake.fail_mapping = True
    out = await fake.client().lint_motor_channels(OPU_ID)
    codes = {w["code"] for w in out["warnings"]}
    assert "inhibition_unread" in codes and "multiple_writers" not in codes
    unread = next(w for w in out["warnings"] if w["code"] == "inhibition_unread")
    assert set(unread["evidence"]["unread"]) == {"src-a", "src-b"}


async def test_lint_filter_matches_the_exact_area_only() -> None:
    fake = make_world()
    fake.areas.append(
        opu_area(cortical_id="CCCCCCCCCCC=", cortical_name="servo-0-extra", unit_id=7)
    )
    client = fake.client()
    exact = await client.lint_motor_channels("servo-0")
    assert exact["areas_checked"] == 1 and exact["channels_checked"] == 3
    by_id = await client.lint_motor_channels(OPU_ID)
    assert by_id["areas_checked"] == 1
    assert "unknown cortical area" in (await client.lint_motor_channels("servo"))["error"]
    assert {key[0] for key in fake.voxel_keys} == {OPU_ID}


async def test_a_skipped_area_emits_no_warnings_and_is_listed() -> None:
    fake = make_world()
    fake.areas.append(
        opu_area(
            cortical_id="DDDDDDDDDDD=",
            cortical_name="flat-opu",
            unit_id=9,
            cortical_dimensions=[8, 1, 1],
            cortical_dimensions_per_device=None,
        )
    )
    out = await fake.client().lint_motor_channels()
    assert out["skipped"] == [
        {"area": "flat-opu", "reason": "dimensions do not state channels and depth"}
    ]
    assert not any(w["area"] == "flat-opu" for w in out["warnings"])
    assert out["areas_checked"] == 2  # servo-0 and servo-1


async def test_lint_budget_is_a_parameter_with_a_named_default() -> None:
    fake = make_world()
    out = await fake.client().lint_motor_channels(max_voxel_reads=2 * DEPTH + 10)
    assert out["channels_checked"] == 2 and out["voxel_reads"] == 2 * DEPTH
    assert out["not_checked"]["count"] == 4 and "budget" in out["not_checked"]["reason"]
    assert {(c["area"], c["channel"]) for c in out["not_checked"]["channels"]} == {
        ("servo-0", 2),
        ("servo-1", 0),
        ("servo-1", 1),
        ("servo-1", 2),
    }
    assert (
        "max_voxel_reads" in (await fake.client().lint_motor_channels(max_voxel_reads=0))["error"]
    )
    full = await fake.client().lint_motor_channels()
    assert full["channels_checked"] == 6 and "not_checked" not in full
    assert mce.LINT_VOXEL_BUDGET >= 6 * DEPTH


async def test_lint_reports_truncated_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = make_world()
    fake.page_size = 1
    monkeypatch.setattr(mce, "MAX_SYNAPSE_PAGES", 1)
    out = await fake.client().lint_motor_channels(OPU_ID)
    assert out["truncated"] and out["truncated"][0]["channel"] == 0
    assert "OPU" in (await fake.client().lint_motor_channels(SRC_A))["error"]
    assert (
        "not registered" in (await fake.client().lint_motor_channels(OPU_ID, agent_id="x"))["error"]
    )


async def test_long_inhibitor_lists_are_capped_with_counts() -> None:
    gates = {f"GATE{i:07d}=": {SRC_A: [rule(-1)]} for i in range(mce.MAX_INHIBITORS_LISTED + 4)}
    fake = make_world({SRC_A: {OPU_ID: [rule(2)]}, SRC_B: {OPU_ID: [rule(2)]}, **gates})
    out = await fake.client().explain_motor_channel(OPU_ID, 0)
    first = out["writers"][0]
    assert len(first["inhibited_by"]) == mce.MAX_INHIBITORS_LISTED
    assert first["inhibited_by_count"] == mce.MAX_INHIBITORS_LISTED + 4


SRC_C = "SRCC0000001="


def three_writers(mappings: dict) -> FakeFeagi:
    """Channel 0 written by src-a (z 50), src-b (z 60) and src-c (z 70)."""
    fake = make_world(mappings)
    fake.voxels.clear()
    fake.areas.append(opu_area(cortical_id=SRC_C, cortical_name="src-c", cortical_group="CUSTOM"))
    fake.add_incoming(OPU_ID, (0, 0, 50), SRC_A, "src-a")
    fake.add_incoming(OPU_ID, (0, 0, 60), SRC_B, "src-b")
    fake.add_incoming(OPU_ID, (0, 0, 70), SRC_C, "src-c")
    return fake


async def test_three_writers_warn_only_for_the_pair_nothing_arbitrates() -> None:
    # a and b inhibit each other; c inhibits b; nothing relates a and c (b inhibits only a)
    fake = three_writers(
        {
            SRC_A: {OPU_ID: [rule(2)], SRC_B: [rule(-5)]},
            SRC_B: {OPU_ID: [rule(2)], SRC_A: [rule(-5)]},
            SRC_C: {OPU_ID: [rule(2)], SRC_B: [rule(-5)]},
        }
    )
    client = fake.client()
    relations = (await client.explain_motor_channel(OPU_ID, 0))["writer_relations"]
    assert relations["unarbitrated_pairs"] == ["src-a / src-c"]
    assert relations["direct"] == ["src-a and src-b inhibit each other", "src-c inhibits src-b"]
    out = await client.lint_motor_channels(OPU_ID)
    warning = next(w for w in out["warnings"] if w["code"] == "multiple_writers")
    assert warning["channel"] == 0 and "src-a / src-c" in warning["detail"]
    assert warning["evidence"]["relations"]["unarbitrated_pairs"] == ["src-a / src-c"]
    assert "src-a / src-b" not in warning["detail"] and "src-b / src-c" not in warning["detail"]


async def test_a_gate_inhibiting_only_one_member_does_not_arbitrate_the_pair() -> None:
    # live-shaped: cmd inhibits rest-reflex but not rest-pattern; both rests share a gate
    cmd, reflex, pattern = "cmd", "rest-reflex", "rest-pattern"
    fake = three_writers(
        {
            SRC_A: {OPU_ID: [rule(2)], SRC_B: [rule(-2)]},
            SRC_B: {OPU_ID: [rule(2)]},
            SRC_C: {OPU_ID: [rule(2)]},
            GATE: {SRC_B: [rule(-2)], SRC_C: [rule(-2)]},
            HOLD: {SRC_A: [rule(-50)]},
        }
    )
    for area_id, name in ((SRC_A, cmd), (SRC_B, reflex), (SRC_C, pattern)):
        for row in fake.voxels.values():
            for syn in row:
                if syn["source_cortical_id"] == area_id:
                    syn["source_cortical_name"] = name
        next(a for a in fake.areas if a["cortical_id"] == area_id)["cortical_name"] = name
    out = await fake.client().lint_motor_channels(OPU_ID)
    warning = next(w for w in out["warnings"] if w["code"] == "multiple_writers")
    relations = warning["evidence"]["relations"]
    assert relations["unarbitrated_pairs"] == ["cmd / rest-pattern"]
    assert relations["direct"] == ["cmd inhibits rest-reflex"]
    assert relations["shared_gates"] == ["gate inhibits rest-pattern, rest-reflex"]


async def test_unarbitrated_pair_list_is_capped_with_a_count() -> None:
    fake = three_writers({SRC_A: {OPU_ID: [rule(2)]}})
    explained = await fake.client().explain_motor_channel(OPU_ID, 0)
    assert explained["writer_relations"]["unarbitrated_count"] == 3
    original = mce.MAX_INHIBITORS_LISTED
    mce.MAX_INHIBITORS_LISTED = 2
    try:
        capped = (await fake.client().explain_motor_channel(OPU_ID, 0))["writer_relations"]
    finally:
        mce.MAX_INHIBITORS_LISTED = original
    assert len(capped["unarbitrated_pairs"]) == 2 and capped["counts"]["unarbitrated_pairs"] == 3
