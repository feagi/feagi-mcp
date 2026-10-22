"""Tests for watch_mapping_weights, freeze_mapping_plasticity and reset_mapping_weights."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from feagi_mcp.weight_watch import (
    MAX_WATCH_S,
    freeze_mapping,
    frozen_rules,
    reset_mapping,
    watch_weights,
    weight_cap_from_area,
    weight_sample,
)

SRC = "Y1N0YXRlXwI="
DST = "Y01vdG9yX/A="


def _diag(weights: list[float], plastic: int = 1) -> dict[str, Any]:
    sample = [
        {"source_neuron_id": 1000 + i, "target_neuron_id": 2000 + i, "weight": w}
        for i, w in enumerate(weights)
    ]
    return {
        "src_area": SRC,
        "dst_area": DST,
        "mapping_exists": True,
        "plastic_rules_count": plastic,
        "synapse_scan": {
            "matched_synapse_count_src_to_dst": len(weights),
            "weight_stats": {
                "min": min(weights) if weights else None,
                "max": max(weights) if weights else None,
                "avg": sum(weights) / len(weights) if weights else None,
                "zero_weight_count": sum(1 for w in weights if w == 0),
                "nonzero_weight_count": sum(1 for w in weights if w > 0),
            },
            "sample": sample,
        },
    }


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_weight_sample_extremes_and_cap_counts() -> None:
    point = weight_sample(_diag([0.0, 5.0, 35.0, 1.5, 35.0, 2.0, 9.0]), cap=35.0)
    assert point["count"] == 7
    assert point["count_at_zero"] == 1
    assert point["count_at_cap"] == 2
    assert [p["w"] for p in point["largest"]] == [35.0, 35.0, 9.0, 5.0, 2.0]
    assert [p["w"] for p in point["smallest"]] == [0.0, 1.5, 2.0, 5.0, 9.0]
    assert {p["src"] for p in point["largest"][:2]} == {1002, 1004}
    assert weight_sample(_diag([1.0]), cap=None)["count_at_cap"] is None


def test_weight_cap_from_area_reads_top_level_or_properties() -> None:
    assert weight_cap_from_area({"neuron_post_synaptic_potential_max": 35.0}) == 35.0
    assert weight_cap_from_area({"properties": {"neuron_post_synaptic_potential_max": 12}}) == 12.0
    assert weight_cap_from_area({}) is None
    assert weight_cap_from_area(None) is None


async def test_watch_weights_samples_series_and_deltas() -> None:
    clock = FakeClock()
    payloads = [_diag([1.0, 1.0]), {"error": "HTTP 500"}, _diag([1.0, 3.0]), _diag([2.0, 6.0])]
    calls = 0

    async def diagnose() -> dict[str, Any]:
        nonlocal calls
        payload = payloads[min(calls, len(payloads) - 1)]
        calls += 1
        return payload

    result = await watch_weights(diagnose, 6.0, 2.0, cap=35.0, sleep=clock.sleep, clock=clock)
    assert [p["t"] for p in result["samples"]] == [0.0, 4.0, 6.0]
    assert result["errors"] == [{"t": 2.0, "error": {"error": "HTTP 500"}}]
    assert result["avg_delta"] == 3.0
    assert result["max_delta"] == 5.0
    assert result["weight_cap"] == 35.0


async def test_watch_weights_caps_duration_and_interval() -> None:
    clock = FakeClock()

    async def diagnose() -> dict[str, Any]:
        return _diag([1.0])

    result = await watch_weights(diagnose, 100.0, 0.1, cap=None, sleep=clock.sleep, clock=clock)
    assert result["capped"] is True
    assert result["window_s"] == MAX_WATCH_S
    assert result["interval_s"] == 0.5


def test_frozen_rules_toggle_flag_only() -> None:
    rules = [
        {"morphology_id": "projector", "plasticity_flag": True, "plasticity_mode": "rstdp"},
        {"morphology_id": "block_to_block"},
    ]
    frozen = frozen_rules(rules, True)
    assert frozen[0]["plasticity_flag"] is False
    assert frozen[0]["plasticity_mode"] == "rstdp"
    assert frozen[1]["plasticity_flag"] is False
    thawed = frozen_rules(frozen, False)
    assert thawed[0]["plasticity_flag"] is True
    assert thawed[1]["plasticity_flag"] is False
    assert rules[0]["plasticity_flag"] is True  # input untouched


async def test_freeze_mapping_rewrites_rules_and_reports_weights() -> None:
    client = AsyncMock()
    rule = {"morphology_id": "projector", "plasticity_flag": True, "plasticity_mode": "rstdp"}
    client.get_cortical_mapping.return_value = {"rules": [rule]}
    client.get_mapping_plasticity_diagnostics.side_effect = [
        _diag([1.0, 4.0]),
        _diag([1.0, 4.0], 0),
    ]
    client.update_cortical_mapping.return_value = {"success": True}
    result = await freeze_mapping(client, SRC, DST, True)
    written = client.update_cortical_mapping.await_args.args[2]
    assert written[0]["plasticity_flag"] is False
    assert result["frozen"] is True
    assert result["weights_preserved"] is True
    assert result["weights_before"]["count"] == 2
    assert result["plastic_rules_after"] == 0


async def test_freeze_mapping_errors() -> None:
    client = AsyncMock()
    client.get_cortical_mapping.return_value = {"rules": []}
    client.get_mapping_plasticity_diagnostics.return_value = _diag([])
    assert (await freeze_mapping(client, SRC, DST, True))["error"] == "mapping_not_found"
    client.get_cortical_mapping.return_value = {"rules": [{"morphology_id": "p"}]}
    client.update_cortical_mapping.return_value = {"error": "HTTP 400"}
    assert (await freeze_mapping(client, SRC, DST, True))["error"] == "update_failed"


async def test_reset_mapping_reports_whether_weights_went_uniform() -> None:
    client = AsyncMock()
    rule = {"morphology_id": "projector", "plasticity_flag": True}
    client.get_cortical_mapping.return_value = {"rules": [rule]}
    client.delete_cortical_mapping.return_value = {"success": True}
    client.update_cortical_mapping.return_value = {"success": True}
    # FEAGI kept the learned weights: not reset.
    client.get_mapping_plasticity_diagnostics.side_effect = [_diag([1.0, 9.0]), _diag([1.0, 9.0])]
    kept = await reset_mapping(client, SRC, DST)
    assert kept["weights_reset"] is False
    assert kept["weights_changed"] is False
    client.delete_cortical_mapping.assert_awaited_once_with(SRC, DST)
    assert client.update_cortical_mapping.await_args.args[2] == [rule]
    # Weights returned to one value: reset.
    client.get_mapping_plasticity_diagnostics.side_effect = [_diag([1.0, 9.0]), _diag([1.0, 1.0])]
    done = await reset_mapping(client, SRC, DST)
    assert done["weights_reset"] is True
    assert done["weights_after"]["unique_weight_count_in_sample"] == 1


async def test_reset_mapping_keeps_rules_on_recreate_failure() -> None:
    client = AsyncMock()
    rule = {"morphology_id": "projector"}
    client.get_cortical_mapping.return_value = {"rules": [rule]}
    client.get_mapping_plasticity_diagnostics.return_value = _diag([1.0])
    client.delete_cortical_mapping.return_value = {"success": True}
    client.update_cortical_mapping.return_value = {"error": "HTTP 400"}
    result = await reset_mapping(client, SRC, DST)
    assert result["error"] == "recreate_failed"
    assert result["rules_to_reapply"] == [rule]
