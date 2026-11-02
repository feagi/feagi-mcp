"""build_circuit_from_spec: template expansion, sizing, dry run and execution (mocked FEAGI)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from feagi_mcp.circuit_spec import (
    apply_property_schema,
    execute_plan,
    expand_spec,
    predicted_step_bursts,
)
from feagi_mcp.feagi_client import FeagiClient

REGION = {"title": "Test Circuit", "coordinates_2d": [0, 0], "coordinates_3d": [100, 100, 100]}


def _all_templates_spec() -> dict[str, Any]:
    return {
        "region": REGION,
        "templates": [
            {
                "template": "port",
                "name": "Port",
                "bins": 9,
                "threshold": 2.5,
                "psp": 3,
                "leak": 0.04,
                "input": 1,
            },
            {"template": "onset_pulse", "name": "Start", "gate": "Gate"},
            {
                "template": "ring_cpg",
                "name": "Ring",
                "bins": 16,
                "threshold": 6,
                "psp": 1,
                "leak": 0.02,
                "drive": "Drive",
                "drive_d": 0.05,
                "lateral_psc": 0.5,
                "seed": {"area": "Start_Onset", "bin": 0},
                "readouts": [{"name": "Phase", "shift": 0}, {"name": "PhaseShifted", "shift": 8}],
            },
            {
                "template": "servo_channel_two_rest",
                "name": "Servo",
                "opu": "Opu",
                "depth": 91,
                "tonic": "Drive",
                "tonic_psc": 2,
                "channels": [
                    {"channel": 0, "reference": 0, "range": [-90, 90]},
                    {"channel": 1, "reference": 10, "range": [-90, 90]},
                ],
                "sources": [
                    {
                        "area": "CmdA",
                        "role": "reflex",
                        "channel": 0,
                        "src_bins": 9,
                        "src_fixed": [0, 0, 0],
                        "gain": 2,
                        "max_offset": 12,
                    },
                    {
                        "area": "CmdB",
                        "role": "pattern",
                        "channel": 1,
                        "src_bins": 9,
                        "src_fixed": [0, 0, 0],
                        "gain": -2,
                        "max_offset": 12,
                    },
                ],
            },
        ],
    }


def _rules(plan: Any, src: str, dst: str) -> list[dict[str, Any]]:
    return plan.mappings[(src, dst)]["rules"]


def _morph(plan: Any, name: str) -> dict[str, Any]:
    return next(m for m in plan.morphologies if m["name"] == name)


def test_dry_run_expands_every_template() -> None:
    report, plan = expand_spec(_all_templates_spec())
    assert report["valid"], report["errors"]
    names = {a["name"] for a in plan.areas}
    assert {
        "Port",
        "Start_Onset",
        "Start_Delay",
        "Ring",
        "Phase",
        "PhaseShifted",
        "Servo_RestReflex",
        "Servo_RestPattern",
    } <= names
    assert report["external"] == ["CmdA", "CmdB", "Drive", "Gate", "Opu"]
    kinds = [c["call"] for c in report["calls"]]
    assert kinds[0] == "create_brain_region"
    assert kinds.count("create_cortical_area") == 8
    assert kinds.index("create_cortical_area") < kinds.index("create_morphology")
    assert kinds.index("create_morphology") < kinds.index("update_cortical_mapping")
    assert [c["n"] for c in report["calls"]] == list(range(1, len(kinds) + 1))
    assert set(report["sizing"]) == {"Port", "Start", "Ring", "Servo"}
    json.dumps(report)  # the whole report is JSON-serializable
    # positions come from the region origin on a grid at least 32 apart
    pos = [a["position"] for a in plan.areas]
    assert pos[0] == [100, 100, 100] and pos[1] == [140, 100, 100]
    assert all(p is not None for p in pos)


def test_port_self_hold_is_sized_inside_the_interval() -> None:
    port = {"template": "port", "name": "P", "bins": 9, "threshold": 2.5, "psp": 3, "input": 1}
    report, plan = expand_spec({"region": REGION, "templates": [port]})
    sizing = report["sizing"]["P"]
    assert sizing["hold_interval"] == [1.5, 2.5]
    assert 1.5 <= sizing["self_hold_s"] < 2.5
    rule = _rules(plan, "P", "P")[0]
    assert rule["morphology_id"] == "block_to_block"
    assert round(3 * rule["postSynapticCurrent_multiplier"], 3) == round(sizing["self_hold_s"], 3)
    props = plan.areas[0]["properties"]
    assert props["neuron_fire_threshold"] == 2.5 and props["neuron_mp_charge_accumulation"] is True


def test_port_rejects_hold_outside_interval_and_requires_inputs() -> None:
    base = {"template": "port", "name": "P", "bins": 3, "threshold": 2.5, "psp": 3, "input": 1}
    bad = {"region": REGION, "templates": [{**base, "hold_psc": 1}]}
    assert "must satisfy" in expand_spec(bad)[0]["errors"][0]
    missing = {k: v for k, v in base.items() if k != "threshold"}
    assert (
        "'threshold' is required"
        in expand_spec({"region": REGION, "templates": [missing]})[0]["errors"][0]
    )
    no_hold = {k: v for k, v in base.items() if k != "input"} | {"self_hold": False}
    report, plan = expand_spec({"region": REGION, "templates": [no_hold]})
    assert report["valid"] and not plan.mappings


def test_onset_pulse_inhibition_cancels_the_second_burst() -> None:
    tpl = {
        "template": "onset_pulse",
        "name": "S",
        "gate": "G",
        "exc_psc": 2,
        "gate_psp": 1.5,
        "psp": 1,
    }
    report, plan = expand_spec({"region": REGION, "templates": [tpl]})
    assert report["valid"], report["errors"]
    assert report["sizing"]["S"]["net_second_burst"] == 0
    assert _rules(plan, "G", "S_Onset")[0]["postSynapticCurrent_multiplier"] == 2
    assert _rules(plan, "S_Delay", "S_Onset")[0]["postSynapticCurrent_multiplier"] == -3
    assert all(a["properties"]["neuron_mp_charge_accumulation"] is False for a in plan.areas)


def test_onset_pulse_rejects_weak_gate_and_weak_inhibition() -> None:
    base = {"template": "onset_pulse", "name": "S", "gate": "G"}
    weak = {"region": REGION, "templates": [{**base, "threshold": 5}]}
    assert "never fire" in expand_spec(weak)[0]["errors"][0]
    soft = {"region": REGION, "templates": [{**base, "exc_psc": 3, "inh_psc": 1}]}
    assert "keep firing" in expand_spec(soft)[0]["errors"][0]


def test_ring_cpg_rules_and_readout_shift() -> None:
    report, plan = expand_spec(_all_templates_spec())
    ring = {
        r["morphology_id"]: r["postSynapticCurrent_multiplier"]
        for r in _rules(plan, "Ring", "Ring")
    }
    assert set(ring) == {
        "block_to_block",
        "lateral_+z",
        "last_to_first",
        "lateral_-z",
        "first_to_last",
    }
    assert ring["lateral_+z"] == ring["last_to_first"] == 0.5
    assert ring["lateral_-z"] == ring["first_to_last"] == -0.5
    assert 5.95 <= ring["block_to_block"] < 6  # T - d <= s < T with psp 1
    area = next(a for a in plan.areas if a["name"] == "Ring")
    assert area["properties"]["neuron_psp_uniform_distribution"] is True
    assert area["neurons_per_voxel"] == 1 and area["dimensions"] == [1, 1, 16]
    assert _rules(plan, "Drive", "Ring")[0]["morphology_id"] == "0-0-0_to_all"
    assert _rules(plan, "Ring", "Phase")[0]["morphology_id"] == "block_to_block"
    shifted = _rules(plan, "Ring", "PhaseShifted")[0]["morphology_id"]
    assert _morph(plan, shifted)["parameters"]["patterns"] == [
        [["*", "*", "0..7"], ["?", "?", "?+8"]],
        [["*", "*", "8..15"], ["?", "?", "?-8"]],
    ]
    assert _rules(plan, "Start_Onset", "Ring")[0]["morphology_id"] == "Ring_seed_bin0"
    assert report["sizing"]["Ring"]["predicted_step_status"].startswith("uncalibrated")


def test_ring_cpg_requires_lateral_psc_and_valid_hold() -> None:
    base = {
        "template": "ring_cpg",
        "name": "R",
        "bins": 4,
        "threshold": 6,
        "psp": 1,
        "drive": "D",
        "drive_d": 0.05,
    }
    first = expand_spec({"region": REGION, "templates": [base]})[0]["errors"][0]
    assert "'lateral_psc' is required" in first
    far = {**base, "lateral_psc": 1, "hold_psc": 3}
    assert "self-hold" in expand_spec({"region": REGION, "templates": [far]})[0]["errors"][0]


def test_ring_step_warning_when_model_disagrees() -> None:
    spec = _all_templates_spec()
    spec["templates"][2]["step_bursts"] = 6
    report, _ = expand_spec(spec)
    assert any("step_bursts 6 requested" in w for w in report["warnings"])


def test_predicted_step_leak_aware_model() -> None:
    assert predicted_step_bursts(1.0, 0.0, 6.0) == 6
    assert predicted_step_bursts(1.0, 0.5, 6.0) is None  # ceiling 2.0 < threshold
    n = predicted_step_bursts(0.615, 0.02, 6.0)
    assert n is not None
    assert sum(0.615 * 0.98**i for i in range(n)) >= 6
    assert sum(0.615 * 0.98**i for i in range(n - 1)) < 6


def test_servo_rest_voxels_offsets_and_inhibition() -> None:
    report, plan = expand_spec(_all_templates_spec())
    sizing = report["sizing"]["Servo"]
    assert sizing["stance_z"] == {"0": 45, "1": 40}
    assert sizing["rest_z_reflex"] == {"0": 46, "1": 41}
    assert sizing["rest_z_pattern"] == {"0": 44, "1": 39}
    reflex, pattern = sizing["sources"]
    assert reflex["coactive_z"] == 44 and pattern["coactive_z"] == 41
    assert reflex["inhibit_psc"] == -2  # ceil(tonic psp 1 x psc 2 / source psp 1)
    tonic = _morph(plan, "Servo_tonic_to_rest_reflex")
    assert tonic["parameters"]["patterns"] == [
        [["*", "*", "*"], [0, 0, 46]],
        [["*", "*", "*"], [1, 0, 41]],
    ]
    # reflex rows compensate against the pattern rest voxel z-1 = 44: z_w = 2 * z_target - 44
    offsets = _morph(plan, "Servo_CmdA_offset")["parameters"]["patterns"]
    dst_z = {tuple(r[0]): r[1][2] for r in offsets}
    assert dst_z[(0, 0, 8)] == 2 * 41 - 44  # gain 2 x 4 bins = +8 deg = 4 bins below stance 45
    inhibit = _morph(plan, "Servo_CmdA_inhibit_rest")["parameters"]["patterns"]
    assert inhibit == [[[0, 0, "0..3"], [0, 0, 46]], [[0, 0, "5..8"], [0, 0, 46]]]
    assert _rules(plan, "CmdA", "Servo_RestReflex")[0]["postSynapticCurrent_multiplier"] == -2
    assert _rules(plan, "Servo_RestPattern", "Opu")[0]["morphology_id"] == "Servo_rest_to_opu"


def test_servo_inhibition_scales_with_source_psp_and_clamp_is_an_error() -> None:
    spec = _all_templates_spec()
    spec["templates"][3]["sources"][0]["psp"] = 0.5
    report, _ = expand_spec(spec)
    assert report["sizing"]["Servo"]["sources"][0]["inhibit_psc"] == -4
    clamp = _all_templates_spec()
    clamp["templates"][3]["channels"][0]["reference"] = 80
    clamp["templates"][3]["sources"][0]["max_offset"] = 40
    err = expand_spec(clamp)[0]["errors"]
    assert err and "clamped" in err[0]
    clamp["templates"][3]["allow_clamp"] = True
    assert expand_spec(clamp)[0]["valid"]


def test_spec_errors_are_collected_not_raised() -> None:
    report, _ = expand_spec({"templates": [{"template": "nope"}, {"template": "port"}], "bogus": 1})
    assert not report["valid"] and len(report["errors"]) >= 3
    assert report["calls"] == []
    assert expand_spec([])[0]["errors"] == ["spec must be a JSON object"]
    no_origin = {"areas": [{"name": "A", "dimensions": [1, 1, 1]}], "region": {"region_id": "r"}}
    assert "no origin" in expand_spec(no_origin)[0]["errors"][0]


def test_explicit_areas_morphologies_and_mappings_merge_with_templates() -> None:
    spec = {
        "region": REGION,
        "areas": [
            {
                "name": "In",
                "dimensions": [1, 1, 1],
                "position": [60, 60, 60],
                "properties": {"neuron_fire_threshold": 1},
            }
        ],
        "morphologies": [
            {
                "name": "m1",
                "type": "patterns",
                "parameters": {"patterns": [[["*", "*", "*"], [0, 0, 0]]]},
            }
        ],
        "mappings": [
            {"src": "In", "dst": "Out", "rules": [{"morphology": "m1", "psc": 2}]},
            {
                "src": "In",
                "dst": "Out",
                "rules": [{"morphology_id": "block_to_block", "postSynapticCurrent_multiplier": 1}],
            },
        ],
    }
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    assert len(_rules(plan, "In", "Out")) == 2
    assert plan.areas[0]["position"] == [60, 60, 60]
    assert report["external"] == ["Out"]


class FakeBrain:
    """Records the calls of a real run; areas get ids ``id_<name>``."""

    def __init__(self, existing: dict[str, str] | None = None, fail_on: str | None = None) -> None:
        self.live = dict(existing or {})
        self.fail_on = fail_on
        self.region_moves_to: list[int] | None = None
        self.region_args: dict[str, Any] = {}
        self.log: list[tuple[str, Any]] = []

    async def get_cortical_id_name_mapping(self) -> dict[str, str]:
        return dict(self.live)

    async def create_brain_region(self, **kw: Any) -> dict[str, Any]:
        self.log.append(("region", kw["title"]))
        self.region_args = kw
        shown = self.region_moves_to or kw["coordinates_2d"]
        return {"region_id": "region-1", "coordinate_2d": shown}

    async def update_brain_region(self, region_id: str, props: dict[str, Any]) -> dict[str, Any]:
        self.log.append(("region_update", props))
        self.region_moves_to = None
        return {"message": "Brain region updated", "region_id": region_id}

    async def delete_cortical_area(self, cid: str) -> dict[str, Any]:
        self.log.append(("delete_area", cid))
        self.live.pop(cid, None)
        return {"message": "deleted"}

    async def delete_brain_region(self, region_id: str) -> dict[str, Any]:
        self.log.append(("delete_region", region_id))
        return {"message": "deleted"}

    async def get_regions_members(self) -> dict[str, Any]:
        return {"region-1": {"coordinate_2d": self.log[-1][1]["coordinate_2d"]}}

    async def create_cortical_area(self, **kw: Any) -> dict[str, Any]:
        self.log.append(("area", kw["name"]))
        if self.fail_on == kw["name"]:
            return {"error": "HTTP 500", "message": "boom"}
        cid = f"id_{kw['name']}"
        self.live[cid] = kw["name"]
        assert kw["brain_region_id"] == "region-1" and kw["cortical_type"] == "CUSTOM"
        return {
            "cortical_id": cid,
            "applied_properties": kw["properties"] or {},
            "rejected_properties": {},
        }

    async def create_morphology(
        self, name: str, _mtype: str, _params: dict[str, Any]
    ) -> dict[str, Any]:
        self.log.append(("morphology", name))
        if name.endswith("rest_to_opu"):
            return {"error": "HTTP 409", "message": "morphology already exists"}
        return {"success": True}

    async def get_cortical_mapping(self, _src: str, _dst: str) -> dict[str, Any]:
        return {"rules": [{"morphology_id": "old"}]}

    async def update_cortical_mapping(self, src: str, dst: str, rules: list[Any]) -> dict[str, Any]:
        self.log.append(("mapping", (src, dst, len(rules))))
        return {"success": True}

    async def get_cortical_map_detailed(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for kind, v in self.log:
            if kind == "mapping":
                out.setdefault(v[0], {})[v[1]] = [{}] * v[2]
        return out

    async def fetch_synapse_edges(self, area_id: str, direction: str) -> list[Any]:
        # every source has one synapse onto neuron 7; the Delay area receives none
        if direction == "outgoing":
            return [{"source_neuron_id": 1, "target_neuron_id": 7}]
        return [] if area_id.endswith("Delay") else [{"source_neuron_id": 1, "target_neuron_id": 7}]


ONSET = {"region": REGION, "templates": [{"template": "onset_pulse", "name": "S", "gate": "Gate"}]}


async def test_execute_plan_creates_in_order_and_verifies() -> None:
    brain = FakeBrain(existing={"id_Gate": "Gate"})
    _, plan = expand_spec(ONSET)
    out = await execute_plan(brain, plan)
    assert out["failed"] is None
    assert out["created"]["region_id"] == "region-1"
    assert out["created"]["areas"] == {"S_Onset": "id_S_Onset", "S_Delay": "id_S_Delay"}
    order = [k for k, _ in brain.log]
    assert order == ["region", "area", "area", "mapping", "mapping", "mapping"]
    ver = out["verification"]
    assert ver["areas"] == {"expected": 2, "found": 2}
    rows = {(r["src"], r["dst"]): r for r in ver["mappings"]}
    assert rows[("S_Delay", "S_Onset")]["synapses"] == 1
    assert rows[("Gate", "S_Delay")]["synapses"] == 0
    assert ver["zero_synapse"] == ["Gate -> S_Delay"]
    # the external edge keeps its existing rule and appends the new one
    assert ("mapping", ("id_Gate", "id_S_Onset", 2)) in brain.log


async def test_execute_plan_aborts_before_creating_on_name_conflict() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain(existing={"id_Gate": "Gate", "x": "S_Onset"})
    out = await execute_plan(brain, plan)
    assert out["failed"]["names"] == ["S_Onset"] and brain.log == []


async def test_execute_plan_missing_external_area_makes_no_change() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain()
    out = await execute_plan(brain, plan)
    assert out["failed"]["name"] == "Gate" and brain.log == []


async def test_execute_plan_stops_at_first_failure_and_rolls_back() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain(existing={"id_Gate": "Gate"}, fail_on="S_Delay")
    out = await execute_plan(brain, plan)
    assert out["failed"]["step"] == "create_cortical_area S_Delay"
    assert out["created"]["areas"] == {"S_Onset": "id_S_Onset"}
    assert [k for k, _ in brain.log] == [
        "region",
        "area",
        "area",
        "delete_area",
        "delete_region",
    ]
    assert out["rolled_back"] == {
        "areas_removed": ["S_Onset"],
        "region_removed": True,
        "leftover_morphologies": [],
        "errors": [],
    }
    assert "id_S_Onset" not in brain.live and "id_Gate" in brain.live


async def test_rollback_removes_an_area_created_with_rejected_properties() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain(existing={"id_Gate": "Gate"})
    real_create = brain.create_cortical_area

    async def rejecting(**kw: Any) -> dict[str, Any]:
        res = await real_create(**kw)
        if kw["name"] == "S_Delay":
            res["rejected_properties"] = {"neuron_excitability": "out of range"}
        return res

    brain.create_cortical_area = rejecting  # type: ignore[method-assign]
    out = await execute_plan(brain, plan)
    assert out["failed"]["step"] == "neuron properties of S_Delay"
    assert sorted(out["rolled_back"]["areas_removed"]) == ["S_Delay", "S_Onset"]
    assert not [n for n in brain.live.values() if n.startswith("S_")]


async def test_rollback_reports_what_it_could_not_remove() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain(existing={"id_Gate": "Gate"}, fail_on="S_Delay")

    async def refuse(_cid: str) -> dict[str, Any]:
        return {"error": "HTTP 500", "message": "busy"}

    brain.delete_cortical_area = refuse  # type: ignore[method-assign]
    out = await execute_plan(brain, plan)
    assert out["rolled_back"]["errors"] == ["area S_Onset: busy"]
    assert out["rolled_back"]["region_removed"] is False


async def test_preflight_failures_have_nothing_to_roll_back() -> None:
    _, plan = expand_spec(ONSET)
    out = await execute_plan(FakeBrain(), plan)
    assert "rolled_back" not in out


async def test_execute_plan_reports_reused_morphology() -> None:
    spec = _all_templates_spec()
    spec["templates"] = [spec["templates"][3]]
    live = {"id_Drive": "Drive", "id_Opu": "Opu", "id_CmdA": "CmdA", "id_CmdB": "CmdB"}
    _, plan = expand_spec(spec)
    out = await execute_plan(FakeBrain(existing=live), plan)
    assert out["failed"] is None
    assert out["created"]["morphologies_reused"] == ["Servo_rest_to_opu"]


async def test_client_tool_defaults_to_dry_run_and_rejects_bad_json() -> None:
    client = FeagiClient()
    report = await client.build_circuit_from_spec(json.dumps(ONSET))
    assert report["dry_run"] is True and report["valid"] and report["calls"]
    bad = await client.build_circuit_from_spec("{nope")
    assert bad["valid"] is False and "Invalid JSON" in bad["errors"][0]
    invalid = await client.build_circuit_from_spec('{"templates": [{"template": "x"}]}', False)
    assert invalid["valid"] is False and "created" not in invalid


@pytest.mark.parametrize("bins", [1, 0])
def test_ring_needs_two_bins(bins: int) -> None:
    tpl = {
        "template": "ring_cpg",
        "name": "R",
        "bins": bins,
        "threshold": 6,
        "psp": 1,
        "drive": "D",
        "drive_d": 0.05,
        "lateral_psc": 1,
    }
    assert not expand_spec({"region": REGION, "templates": [tpl]})[0]["valid"]


def test_rule_shorthand_is_translated_and_validated_in_the_dry_run() -> None:
    spec = {
        "region": REGION,
        "areas": [{"name": "A", "dimensions": [1, 1, 1], "position": [60, 60, 60]}],
        "mappings": [
            {
                "src": "A",
                "dst": "B",
                "rules": [{"morphology": "block_to_block", "psc": 2, "delay": 3}],
            }
        ],
    }
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    sent = report["calls"][-1]["args"]["mapping_rules"][0]
    assert sent == {
        "morphology_id": "block_to_block",
        "postSynapticCurrent_multiplier": 2,
        "synaptic_delay_bursts": 3,
        "morphology_scalar": [1, 1, 1],
        "plasticity_flag": False,
    }
    assert plan.mappings[("A", "B")]["rules"] == [sent]


@pytest.mark.parametrize(
    "bad,text",
    [
        ({"psc": 1}, "morphology_id"),
        ({"morphology": "", "psc": 1}, "morphology_id"),
        ({"morphology": "m"}, "postSynapticCurrent_multiplier"),
        ({"morphology": "m", "psc": 1, "delay": 0}, "synaptic_delay_bursts"),
        ({"morphology": "m", "psc": 1, "colour": "red"}, "unknown key"),
        ({"morphology": "m", "morphology_id": "n", "psc": 1}, "twice"),
    ],
)
def test_invalid_rules_fail_the_dry_run_not_the_real_run(bad: dict[str, Any], text: str) -> None:
    spec = {"region": REGION, "mappings": [{"src": "A", "dst": "B", "rules": [bad]}]}
    report, _ = expand_spec(spec)
    assert not report["valid"] and text in report["errors"][0]


async def test_region_without_coordinates_2d_is_placed_after_the_siblings() -> None:
    client = FeagiClient()
    regions = {
        "root": {"parent_region_id": None, "coordinate_2d": [0, 0]},
        "a": {"parent_region_id": "root", "coordinate_2d": [1610, 0]},
        "b": {"parent_region_id": "root", "coordinate_2d": [1610, 378]},
        "c": {"parent_region_id": "root", "coordinate_2d": [2446, 126]},
        "nested": {"parent_region_id": "a", "coordinate_2d": [9999, 9]},
    }

    async def members() -> dict[str, Any]:
        return regions

    client.get_regions_members = members  # type: ignore[method-assign]
    spec = {"region": {"title": "New Circuit", "coordinates_3d": [100, 100, 100]}}
    report = await client.build_circuit_from_spec(json.dumps(spec))
    assert report["valid"], report["errors"]
    assert report["region_coordinates_2d"]["placed"] == [3282, 126]
    assert report["calls"][0]["args"]["coordinates_2d"] == [3282, 126]


async def test_given_coordinates_2d_are_sent_unchanged() -> None:
    report = await FeagiClient().build_circuit_from_spec(json.dumps(ONSET))
    assert report["calls"][0]["args"]["coordinates_2d"] == [0, 0]
    assert "region_coordinates_2d" not in report


async def test_execute_plan_corrects_a_region_that_landed_elsewhere() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain(existing={"id_Gate": "Gate"})
    brain.region_moves_to = [1610, 378]
    out = await execute_plan(brain, plan)
    pos = out["created"]["region_coordinates_2d"]
    assert pos["requested"] == [0, 0] and pos["actual"] == [1610, 378]
    assert pos["mismatch"] is True and pos["update"] == "ok" and pos["after_update"] == [0, 0]
    assert ("region_update", {"coordinate_2d": [0, 0]}) in brain.log


async def test_execute_plan_does_not_touch_a_region_placed_as_asked() -> None:
    _, plan = expand_spec(ONSET)
    brain = FakeBrain(existing={"id_Gate": "Gate"})
    out = await execute_plan(brain, plan)
    assert out["created"]["region_coordinates_2d"] == {"requested": [0, 0], "actual": [0, 0]}
    assert not any(k == "region_update" for k, _ in brain.log)


SCHEMA = [
    {
        "key": "neuron_excitability",
        "aliases": ["excitability"],
        "type": "number",
        "unit": "fraction",
        "min": 0.0,
        "max": 1.0,
    },
    {"key": "neuron_fire_threshold", "type": "number", "unit": "mp", "suggested_max": 20.0},
    {"key": "neuron_refractory_period", "type": "number", "min": 0.0},
    {"key": "neuron_mp_charge_accumulation", "type": "boolean"},
]


def _with_props(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "region": REGION,
        "areas": [
            {"name": "A", "dimensions": [1, 1, 1], "position": [60, 60, 60], "properties": props}
        ],
    }


def test_percent_excitability_is_normalized_to_a_fraction() -> None:
    from feagi_mcp.circuit_spec import apply_property_schema

    _, plan = expand_spec(_with_props({"neuron_excitability": 100, "neuron_fire_threshold": 2}))
    errors, warnings = apply_property_schema(plan, SCHEMA)
    assert errors == [] and "read as a percent" in warnings[0]
    assert plan.areas[0]["properties"] == {"neuron_excitability": 1.0, "neuron_fire_threshold": 2}
    _, ok = expand_spec(_with_props({"excitability": 0.5}))
    assert apply_property_schema(ok, SCHEMA) == ([], [])


@pytest.mark.parametrize(
    "props,text",
    [
        ({"neuron_excitability": 250}, "outside the API range"),
        ({"neuron_refractory_period": -1}, "outside the API range"),
        ({"no_such_property": 1}, "unknown property"),
        ({"neuron_fire_threshold": "2"}, "must be a number"),
    ],
)
def test_out_of_range_or_unknown_properties_are_errors(props: dict[str, Any], text: str) -> None:
    from feagi_mcp.circuit_spec import apply_property_schema

    _, plan = expand_spec(_with_props(props))
    errors, _ = apply_property_schema(plan, SCHEMA)
    assert errors and text in errors[0]


async def test_dry_run_checks_properties_against_the_live_schema() -> None:
    client = FeagiClient()

    async def schema() -> list[dict[str, Any]]:
        return SCHEMA

    client.get_area_parameter_schema = schema  # type: ignore[method-assign]
    good = await client.build_circuit_from_spec(
        json.dumps(_with_props({"neuron_excitability": 100}))
    )
    assert good["valid"] and any("percent" in w for w in good["warnings"])
    sent = good["calls"][1]["args"]["properties"]
    assert sent == {"neuron_excitability": 1.0}
    bad = await client.build_circuit_from_spec(
        json.dumps(_with_props({"neuron_excitability": 500}))
    )
    assert not bad["valid"] and bad["calls"] == []

    async def no_schema() -> None:
        return None

    client.get_area_parameter_schema = no_schema  # type: ignore[method-assign]
    unchecked = await client.build_circuit_from_spec(json.dumps(_with_props({"x": 1})))
    assert unchecked["valid"] and any("not checked" in w for w in unchecked["warnings"])


# ------------------------------------------------- delete, edit_areas, phase_window_gate

GATE = {
    "template": "phase_window_gate",
    "name": "Gate",
    "pulse": "Pulse",
    "phase": "Phase",
    "target": "Target",
    "enable": "Enable",
    "phase_bins": 8,
    "window": "2..4",
    "threshold": 2,
    "enable_psc": 1,
    "pulse_psc": 1,
}


def _gate(**changes: Any) -> dict[str, Any]:
    t = {**GATE, **changes}
    return {"region": REGION, "templates": [t]}


def test_phase_window_gate_builds_inhibition_outside_the_window() -> None:
    report, plan = expand_spec(_gate())
    assert report["valid"], report["errors"]
    gate = next(a for a in plan.areas if a["name"] == "Gate")
    assert gate["dimensions"] == [1, 1, 1]
    assert gate["properties"]["neuron_fire_threshold"] == 2
    morph = _morph(plan, "Gate_out_of_window_inhibit")
    rows = morph["parameters"]["patterns"]
    assert rows == [[["*", "*", "0..1"], [0, 0, 0]], [["*", "*", "5..7"], [0, 0, 0]]]
    assert _rules(plan, "Phase", "Gate")[0]["postSynapticCurrent_multiplier"] == -1
    assert _rules(plan, "Pulse", "Gate")[0]["morphology_id"] == "all_to_0-0-0"
    assert _rules(plan, "Gate", "Target")[0]["morphology_id"] == "0-0-0_to_all"
    levels = report["sizing"]["Gate"]["levels"]
    assert levels["enable_alone"] == 1 < 2 and levels["enable_plus_pulse"] == 2
    assert levels["enable_plus_pulse_minus_inhibition"] == 1


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({"enable_psc": 2}, "enable alone"),
        ({"pulse_psc": 2}, "pulse alone"),
        ({"pulse_psc": 0.5}, "enable + pulse gives"),
        ({"pulse_psc": 1.5, "inhibit_psc": 0.25}, "enable + pulse - inhibition"),
        ({"accumulate": True}, "needs leak > 0"),
        ({"window": "0..7"}, "covers every phase bin"),
        ({"window": [9]}, "inside 0..7"),
    ],
)
def test_phase_window_gate_fails_the_dry_run_on_bad_arithmetic(
    changes: dict[str, Any], text: str
) -> None:
    report, _ = expand_spec(_gate(**changes))
    assert not report["valid"] and text in report["errors"][0]
    assert report["calls"] == []


def test_phase_window_gate_uses_the_leak_model_when_accumulating() -> None:
    # steady state of V <- V (1 - leak) + I: enable alone 0.3 / 0.2 = 1.5 < 2; +pulse = 2.5 >= 2
    report, _ = expand_spec(
        _gate(accumulate=True, leak=0.2, enable_psc=0.3, pulse_psc=1, inhibit_psc=1)
    )
    assert report["valid"], report["errors"]
    levels = report["sizing"]["Gate"]["levels"]
    assert levels["enable_alone"] == 1.5 and levels["enable_plus_pulse"] == 2.5
    assert levels["enable_plus_pulse_minus_inhibition"] == pytest.approx(-2.5)


def test_phase_window_gate_without_enable_needs_a_sufficient_pulse() -> None:
    ok, _ = expand_spec(_gate(enable=None, pulse_psc=2, inhibit_psc=1))
    assert ok["valid"], ok["errors"]
    weak, _ = expand_spec(_gate(enable=None, pulse_psc=1))
    assert not weak["valid"] and "below threshold" in weak["errors"][0]


def test_delete_lists_calls_and_externals_and_rejects_bad_entries() -> None:
    spec = {"delete": [{"src": "A", "dst": "B"}]}
    report, plan = expand_spec(spec)
    assert report["valid"] and plan.deletions == [("A", "B")]
    assert report["calls"] == [
        {"call": "delete_cortical_mapping", "args": {"src_area": "A", "dst_area": "B"}, "n": 1}
    ]
    assert report["external"] == ["A", "B"] and report["summary"]["deletions"] == 1
    bad, _ = expand_spec({"delete": [{"src": "A"}]})
    assert not bad["valid"] and "'src' and 'dst'" in bad["errors"][0]


class EditBrain(FakeBrain):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.members = ["id_Old"]

    async def get_regions_members(self) -> dict[str, Any]:
        return {"R1": {"areas": self.members, "regions": []}}

    async def update_cortical_area(self, cid: str, updates: dict[str, Any]) -> dict[str, Any]:
        self.log.append(("update_area", (cid, updates)))
        return {"message": "updated"}

    async def delete_cortical_mapping(self, src: str, dst: str) -> dict[str, Any]:
        self.log.append(("delete_mapping", (src, dst)))
        return {"message": "deleted"}


async def test_delete_runs_before_the_mapping_that_replaces_it() -> None:
    spec = {
        "region": {"region_id": "R1"},
        "delete": [{"src": "Old", "dst": "Other"}],
        "mappings": [
            {"src": "Old", "dst": "Other", "rules": [{"morphology": "block_to_block", "psc": 1}]}
        ],
    }
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    brain = EditBrain(existing={"id_Old": "Old", "id_Other": "Other"})
    out = await execute_plan(brain, plan)
    assert out["failed"] is None
    assert out["created"]["deleted_mappings"] == [{"src": "Old", "dst": "Other"}]
    kinds = [k for k, _ in brain.log]
    assert kinds.index("delete_mapping") < kinds.index("mapping")


async def test_edit_areas_updates_members_of_the_existing_region() -> None:
    spec = {
        "region": {"region_id": "R1"},
        "edit_areas": [{"name": "Old", "properties": {"neuron_fire_threshold": 3}}],
        "areas": [{"name": "New", "dimensions": [1, 1, 2], "position": [10, 10, 10]}],
    }
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    assert [c["call"] for c in report["calls"]] == ["create_cortical_area", "update_cortical_area"]
    brain = EditBrain(existing={"id_Old": "Old"})

    async def regions() -> dict[str, Any]:
        return {"R1": {"areas": brain.members, "regions": []}}

    brain.get_regions_members = regions  # type: ignore[method-assign]
    # the fake asserts new areas land in region-1; here the existing region is R1
    brain.create_cortical_area = _create_in_r1(brain)  # type: ignore[method-assign]
    out = await execute_plan(brain, plan)
    assert out["failed"] is None
    assert out["created"]["edits"] == ["Old"]
    assert ("update_area", ("id_Old", {"neuron_fire_threshold": 3})) in brain.log


def _create_in_r1(brain: EditBrain) -> Any:
    async def create(**kw: Any) -> dict[str, Any]:
        assert kw["brain_region_id"] == "R1"
        brain.log.append(("area", kw["name"]))
        brain.live[f"id_{kw['name']}"] = kw["name"]
        brain.members.append(f"id_{kw['name']}")
        return {"cortical_id": f"id_{kw['name']}", "rejected_properties": {}}

    return create


async def test_edit_areas_outside_the_region_changes_nothing() -> None:
    spec = {
        "region": {"region_id": "R1"},
        "edit_areas": [{"name": "Stranger", "properties": {"neuron_fire_threshold": 3}}],
    }
    _, plan = expand_spec(spec)
    brain = EditBrain(existing={"id_Stranger": "Stranger"})
    out = await execute_plan(brain, plan)
    assert out["failed"]["names"] == ["Stranger"] and brain.log == []


def test_edit_areas_needs_an_existing_region_and_properties() -> None:
    no_region, _ = expand_spec({"edit_areas": [{"name": "A", "properties": {"x": 1}}]})
    assert not no_region["valid"] and "region_id" in no_region["errors"][0]
    no_props, _ = expand_spec({"region": {"region_id": "R1"}, "edit_areas": [{"name": "A"}]})
    assert not no_props["valid"] and "properties" in no_props["errors"][0]


async def test_edit_properties_are_checked_against_the_live_schema() -> None:
    client = FeagiClient()

    async def schema() -> list[dict[str, Any]]:
        return SCHEMA

    client.get_area_parameter_schema = schema  # type: ignore[method-assign]
    spec = {
        "region": {"region_id": "R1"},
        "edit_areas": [{"name": "Old", "properties": {"neuron_excitability": 500}}],
    }
    bad = await client.build_circuit_from_spec(json.dumps(spec))
    assert not bad["valid"] and "outside the API range" in bad["errors"][0]


# ------------------------------------------------------------ memory and plasticity


def _mem_spec(**over: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "region": REGION,
        "areas": [
            {"name": "In", "dimensions": [1, 1, 4]},
            {"name": "Out", "dimensions": [1, 1, 4]},
            {
                "name": "Mem",
                "dimensions": [1, 1, 1],
                "cortical_type": "MEMORY",
                "properties": {
                    "temporal_depth": 4,
                    "neuron_init_lifespan": 9,
                    "ltm_eviction": "LRU",
                },
                "mp_encoding": {"mode": "mp_differential", "delta_quantization": 0.5},
            },
        ],
        "mappings": [
            {"src": "In", "dst": "Mem", "rules": [{"morphology": "episodic_memory", "psc": 1}]},
            {
                "src": "Mem",
                "dst": "Out",
                "rules": [
                    {
                        "morphology": "associative_memory",
                        "psc": 1,
                        "plasticity_mode": "stdp",
                        "plasticity_window": 3,
                        "plasticity_eta": 0.5,
                        "max_weight": 5,
                        "ltp_multiplier": 2,
                        "ltd_multiplier": 0,
                    }
                ],
            },
        ],
    }
    spec.update(over)
    return spec


def test_memory_area_and_plastic_mapping_dry_run() -> None:
    report, plan = expand_spec(_mem_spec())
    assert report["valid"], report["errors"]
    area = next(
        c
        for c in report["calls"]
        if c["call"] == "create_cortical_area" and c["args"]["name"] == "Mem"
    )
    assert area["args"]["cortical_type"] == "MEMORY"
    props = area["args"]["properties"]
    assert props["ltm_eviction"] == "lru" and props["mp_change_mode"] == "mp_differential"
    assert props["mp_delta_quantization"] == 0.5 and props["mp_learning_enabled"] is False
    assert _rules(plan, "Mem", "Out")[0]["plasticity_flag"] is True


def _assoc(**extra: Any) -> dict[str, Any]:
    rule = {"morphology": "associative_memory", "psc": 1, **extra}
    return {"mappings": [{"src": "Mem", "dst": "Out", "rules": [rule]}]}


def _epi(src: str, dst: str, **extra: Any) -> dict[str, Any]:
    rule = {"morphology": "episodic_memory", "psc": 1, **extra}
    return {"mappings": [{"src": src, "dst": dst, "rules": [rule]}]}


@pytest.mark.parametrize(
    "patch",
    [
        {"mappings": [{**_assoc()["mappings"][0], "src": "Out"}]},
        _epi("In", "Out"),
        _epi("In", "Mem", delay=0),
        _assoc(plasticity_mode="rstdp"),
        _assoc(plasticity_mode="stdp", eligibility_decay_bursts=10),
        _assoc(plasticity_eta=0.5),
    ],
)
def test_illegal_memory_and_plasticity_combinations_fail_dry_run(patch: dict[str, Any]) -> None:
    report, _ = expand_spec(_mem_spec(**patch))
    assert not report["valid"] and report["errors"]


def test_memory_params_on_custom_area_and_change_mode_depth_are_errors() -> None:
    area = {"name": "A", "dimensions": [1, 1, 1], "properties": {"temporal_depth": 4}}
    bad = _mem_spec(areas=[area])
    assert not expand_spec(bad)[0]["valid"]
    spec = _mem_spec()
    spec["areas"][2]["properties"]["temporal_depth"] = 1
    assert not expand_spec(spec)[0]["valid"]


def test_modulators_and_frozen_mapping() -> None:
    spec = _mem_spec()
    spec["areas"][2]["modulators"] = ["no_new_memory"]
    spec["mappings"][1].update({"modulators": ["reward"], "frozen": True})
    spec["mappings"][1]["rules"][0].update(
        {"plasticity_mode": "rstdp", "eligibility_decay_bursts": 10}
    )
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    r = _rules(plan, "Mem", "Out")[0]
    assert r["modulators"] == ["reward"] and r["plasticity_mode"] == "rstdp"
    assert r["plasticity_flag"] is True  # frozen through the route, never by rewriting the flag
    assert plan.mappings[("Mem", "Out")]["frozen"] is True
    freeze = [c for c in report["calls"] if c["call"] == "set_mapping_plasticity_frozen"]
    assert [c["args"] for c in freeze] == [{"src_area": "Mem", "dst_area": "Out", "frozen": True}]
    names = [c["call"] for c in report["calls"]]
    assert names[names.index("set_mapping_plasticity_frozen") - 1] == "update_cortical_mapping"
    want = {"modulators": ["no_new_memory"]}
    assert any(
        c["call"] == "update_cortical_area" and c["args"]["updates"] == want
        for c in report["calls"]
    )


class MemBrain(FakeBrain):
    async def create_cortical_area(self, **kw: Any) -> dict[str, Any]:
        self.log.append(("area", kw["name"]))
        cid = _b64_id(b"m" if kw["cortical_type"] == "MEMORY" else b"c")
        self.live[cid] = kw["name"]
        return {"cortical_id": cid, "rejected_properties": {}}

    async def update_cortical_area(self, cid: str, updates: dict[str, Any]) -> dict[str, Any]:
        self.log.append(("area_update", (cid, updates)))
        return {"success": True}


class FreezeBrain(MemBrain):
    """MemBrain with FEAGI's plasticity_frozen routes; ``read`` is what the GET route returns."""

    def __init__(self, put: dict[str, Any], read: dict[str, Any]) -> None:
        super().__init__()
        self.put, self.read = put, read

    async def set_mapping_plasticity_frozen(
        self, src: str, dst: str, frozen: bool
    ) -> dict[str, Any]:
        self.log.append(("freeze", (src, dst, frozen)))
        return self.put

    async def get_mapping_plasticity_frozen(self, src: str, dst: str) -> dict[str, Any]:
        self.log.append(("freeze_read", (src, dst)))
        return self.read


def _frozen_spec() -> dict[str, Any]:
    spec = _mem_spec()
    spec["mappings"][1]["frozen"] = True
    spec["mappings"][1]["rules"][0].update(
        {"plasticity_mode": "rstdp", "eligibility_decay_bursts": 10, "modulators": ["reward"]}
    )
    return spec


async def test_execute_plan_freezes_through_route_after_the_rules_are_written() -> None:
    _, plan = expand_spec(_frozen_spec())
    brain = FreezeBrain({"frozen": True}, {"frozen": True})
    out = await execute_plan(brain, plan)
    assert out["failed"] is None, out
    kinds = [k for k, _ in brain.log]
    assert kinds.count("freeze") == 1
    assert kinds.index("freeze") == kinds.index("freeze_read") - 1
    assert kinds[kinds.index("freeze") - 1] == "mapping"  # the rules go in first
    assert brain.log[kinds.index("freeze")][1][2] is True
    assert out["created"]["frozen_mappings"] == [{"src": "Mem", "dst": "Out"}]


@pytest.mark.parametrize(
    ("put", "read"),
    [
        ({"error": "HTTP 400", "message": "no plastic rule"}, {"frozen": True}),
        ({"frozen": True}, {"frozen": False}),
        ({"frozen": True}, {"frozen": None}),
        ({"frozen": True}, {"error": "HTTP 500"}),
    ],
)
async def test_execute_plan_stops_when_freeze_fails_or_is_not_read_back(
    put: dict[str, Any], read: dict[str, Any]
) -> None:
    _, plan = expand_spec(_frozen_spec())
    out = await execute_plan(FreezeBrain(put, read), plan)
    assert out["failed"]["step"] == "freeze Mem -> Out"


async def test_execute_plan_builds_memory_area_with_modulators() -> None:
    spec = _mem_spec()
    spec["areas"][2]["modulators"] = ["m1"]
    _, plan = expand_spec(spec)
    out = await execute_plan(MemBrain(), plan)
    assert out["failed"] is None, out
    assert out["created"]["areas"]["Mem"] == _b64_id(b"m")


async def test_execute_plan_rejects_associative_from_a_live_non_memory_area() -> None:
    spec = {
        "region": REGION,
        "areas": [{"name": "Out", "dimensions": [1, 1, 1], "position": [1, 1, 1]}],
        "mappings": [
            {"src": "Live", "dst": "Out", "rules": [{"morphology": "associative_memory", "psc": 1}]}
        ],
    }
    report, plan = expand_spec(spec)
    assert report["valid"]
    out = await execute_plan(MemBrain(existing={_b64_id(b"c"): "Live"}), plan)
    assert out["failed"]["step"] == "preflight" and not out["created"]["areas"]


# ------------------------------------------- real base64 ids, property keys, defaults


def _b64_id(first: bytes) -> str:
    import base64

    return base64.b64encode(first + b"Mem___\x07").decode()


class RealIdBrain(MemBrain):
    async def create_cortical_area(self, **kw: Any) -> dict[str, Any]:
        self.log.append(("area", kw["name"]))
        cid = _b64_id(b"m" if kw["cortical_type"] == "MEMORY" else b"c")
        self.live[cid] = kw["name"]
        return {"cortical_id": cid, "rejected_properties": {}}


def test_is_memory_cortical_id_decodes_bytes_not_text() -> None:
    from feagi_mcp.circuit_spec import is_memory_cortical_id

    assert is_memory_cortical_id(_b64_id(b"m"))
    assert not is_memory_cortical_id(_b64_id(b"c"))
    # base64 text of a custom id that happens to start with the letter 'm'
    import base64

    tricky = base64.b64encode(b"cmmmmmm\x01").decode()
    assert not is_memory_cortical_id(tricky)
    assert not is_memory_cortical_id("m_Mem") and not is_memory_cortical_id(None)


async def test_execute_plan_builds_memory_area_with_real_base64_id() -> None:
    _, plan = expand_spec(_mem_spec())
    out = await execute_plan(RealIdBrain(), plan)
    assert out["failed"] is None, out
    assert out["created"]["areas"]["Mem"] == _b64_id(b"m")


async def test_live_real_memory_area_is_a_valid_episodic_destination() -> None:
    spec = {
        "region": REGION,
        "areas": [{"name": "In", "dimensions": [1, 1, 1], "position": [1, 1, 1]}],
        "mappings": [
            {"src": "In", "dst": "LiveMem", "rules": [{"morphology": "episodic_memory", "psc": 1}]}
        ],
    }
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    ok = await execute_plan(RealIdBrain(existing={_b64_id(b"m"): "LiveMem"}), plan)
    assert ok["failed"] is None, ok
    _, plan2 = expand_spec(spec)
    bad = await execute_plan(RealIdBrain(existing={_b64_id(b"c"): "LiveMem"}), plan2)
    assert bad["failed"]["step"] == "preflight"


def test_firing_threshold_alias_maps_and_memory_psp_default_warns() -> None:
    spec = _mem_spec()
    spec["areas"][0]["properties"] = {"firing_threshold": 2.5}
    report, _ = expand_spec(spec)
    assert report["valid"], report["errors"]
    args = next(c for c in report["calls"] if c["args"].get("name") == "In")["args"]
    assert args["properties"] == {"neuron_fire_threshold": 2.5}
    assert any("postsynaptic_current 500" in w and "'Mem'" in w for w in report["warnings"])
    spec["areas"][2]["properties"]["neuron_post_synaptic_potential"] = 1.0
    report, _ = expand_spec(spec)
    assert not any("postsynaptic_current 500" in w for w in report["warnings"])


def test_schema_unknown_key_error_lists_valid_keys() -> None:
    spec = _mem_spec()
    spec["areas"][0]["properties"] = {"bogus_key": 1}
    _, plan = expand_spec(spec)
    errs, _ = apply_property_schema(plan, [{"key": "neuron_fire_threshold", "type": "number"}])
    assert errs and "valid keys" in errs[0] and "neuron_fire_threshold" in errs[0]


def test_create_applies_memory_keys_via_followup_update() -> None:
    from feagi_mcp.feagi_client import _is_neuron_parameter_key

    for k in ("temporal_depth", "neuron_init_lifespan", "ltm_eviction", "mp_change_mode"):
        assert _is_neuron_parameter_key(k)
