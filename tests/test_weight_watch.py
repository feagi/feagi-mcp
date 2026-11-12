"""Tests for watch_mapping_weights, freeze_mapping_plasticity and reset_mapping_weights."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from feagi_mcp.weight_watch import (
    MAX_WATCH_S,
    freeze_mapping,
    freeze_memory_area,
    reset_mapping,
    reset_mapping_native_first,
    watch_weights,
    weight_cap_from_rules,
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


def test_weight_cap_from_rules_uses_plastic_rule_max_weight() -> None:
    rules = [
        {"morphology_id": "a", "plasticity_flag": False, "max_weight": 99},
        {"morphology_id": "b", "plasticity_flag": True, "max_weight": 50},
        {"morphology_id": "c", "plasticity_mode": "stdp", "max_weight": 20},
    ]
    assert weight_cap_from_rules(rules) == (50.0, "rule.max_weight")
    assert weight_cap_from_rules(rules, "c") == (20.0, "rule.max_weight")
    assert weight_cap_from_rules([{"plasticity_flag": False, "max_weight": 9}]) == (None, None)
    assert weight_cap_from_rules(None) == (None, None)


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


async def test_freeze_mapping_uses_freeze_route_and_reports_read_back() -> None:
    client = AsyncMock()
    client.get_mapping_plasticity_diagnostics.side_effect = [_diag([1.0, 4.0]), _diag([1.0, 4.0])]
    client.set_mapping_plasticity_frozen.return_value = {"frozen": True}
    client.get_mapping_plasticity_frozen.return_value = {"frozen": True}
    result = await freeze_mapping(client, SRC, DST, True)
    client.set_mapping_plasticity_frozen.assert_awaited_once_with(SRC, DST, True)
    client.get_mapping_plasticity_frozen.assert_awaited_once_with(SRC, DST)
    client.update_cortical_mapping.assert_not_awaited()  # rules are never rewritten
    assert result["requested"] is True
    assert result["frozen"] is True
    assert result["weights_preserved"] is True
    assert result["weights_before"]["count"] == 2


async def test_freeze_mapping_reports_frozen_as_read_back() -> None:
    client = AsyncMock()
    client.get_mapping_plasticity_diagnostics.return_value = _diag([1.0])
    client.set_mapping_plasticity_frozen.return_value = {"frozen": False}
    client.get_mapping_plasticity_frozen.return_value = {"frozen": True}
    result = await freeze_mapping(client, SRC, DST, False)
    assert result["requested"] is False
    assert result["frozen"] is True


async def test_freeze_mapping_flags_changed_weights() -> None:
    client = AsyncMock()
    client.get_mapping_plasticity_diagnostics.side_effect = [_diag([1.0, 4.0]), _diag([1.0, 1.0])]
    client.set_mapping_plasticity_frozen.return_value = {"frozen": True}
    client.get_mapping_plasticity_frozen.return_value = {"frozen": True}
    assert (await freeze_mapping(client, SRC, DST, True))["weights_preserved"] is False


async def test_freeze_mapping_errors() -> None:
    client = AsyncMock()
    client.get_mapping_plasticity_diagnostics.return_value = {"mapping_exists": False}
    assert (await freeze_mapping(client, SRC, DST, True))["error"] == "mapping_not_found"
    client.set_mapping_plasticity_frozen.assert_not_awaited()
    client.get_mapping_plasticity_diagnostics.return_value = _diag([1.0])
    client.set_mapping_plasticity_frozen.return_value = {"error": "HTTP 400"}
    assert (await freeze_mapping(client, SRC, DST, True))["error"] == "freeze_failed"
    client.get_mapping_plasticity_frozen.assert_not_awaited()
    client.set_mapping_plasticity_frozen.return_value = {"frozen": True}
    client.get_mapping_plasticity_frozen.return_value = {"error": "HTTP 500"}
    assert (await freeze_mapping(client, SRC, DST, True))["error"] == "readback_failed"
    client.update_cortical_mapping.assert_not_awaited()


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


async def test_reset_native_first_uses_native_route() -> None:
    client = AsyncMock()
    client.reset_mapping_weights_native.return_value = {"synapses_reset": 9, "weight": 1.0}
    result = await reset_mapping_native_first(client, SRC, DST)
    assert result["method"] == "native"
    assert result["synapses_reset"] == 9
    assert result["weight"] == 1.0
    client.delete_cortical_mapping.assert_not_awaited()


async def test_reset_native_first_falls_back_when_route_missing() -> None:
    client = AsyncMock()
    client.reset_mapping_weights_native.return_value = {"route_missing": True, "status": 404}
    client.get_cortical_mapping.return_value = {"rules": [{"morphology_id": "projector"}]}
    client.delete_cortical_mapping.return_value = {"success": True}
    client.update_cortical_mapping.return_value = {"success": True}
    client.get_mapping_plasticity_diagnostics.side_effect = [_diag([1.0, 9.0]), _diag([1.0, 1.0])]
    result = await reset_mapping_native_first(client, SRC, DST)
    assert result["method"] == "recreate_fallback"
    assert result["weights_reset"] is True
    client.delete_cortical_mapping.assert_awaited_once_with(SRC, DST)


async def test_reset_native_first_reports_real_mapping_error() -> None:
    client = AsyncMock()
    client.reset_mapping_weights_native.return_value = {"error": "HTTP 404", "message": "mapping"}
    result = await reset_mapping_native_first(client, SRC, DST)
    assert result["error"] == "native_reset_failed"
    client.delete_cortical_mapping.assert_not_awaited()


async def test_freeze_memory_area_reads_back_from_bulk_get() -> None:
    client = AsyncMock()
    client.set_memory_area_learning_frozen.return_value = {"frozen": True}
    client.get_learning_frozen.return_value = {"memory_areas": ["m_a"], "mappings": []}
    out = await freeze_memory_area(client, "m_a", True)
    client.set_memory_area_learning_frozen.assert_awaited_once_with("m_a", True)
    assert out["requested"] is True and out["frozen"] is True
    assert out["frozen_memory_areas"] == ["m_a"]
    client.get_learning_frozen.return_value = {"memory_areas": [], "mappings": []}
    out = await freeze_memory_area(client, "m_a", False)
    assert out["requested"] is False and out["frozen"] is False
    client.get_learning_frozen.return_value = {"memory_areas": ["m_a"]}
    assert (await freeze_memory_area(client, "m_a", False))["frozen"] is True


async def test_freeze_memory_area_errors() -> None:
    client = AsyncMock()
    client.set_memory_area_learning_frozen.return_value = {"error": "HTTP 400", "message": "x"}
    out = await freeze_memory_area(client, "c_a", True)
    assert out["error"] == "not_a_memory_area"
    client.get_learning_frozen.assert_not_awaited()
    client.set_memory_area_learning_frozen.return_value = {"error": "HTTP 500"}
    assert (await freeze_memory_area(client, "m_a", True))["error"] == "freeze_failed"
    client.set_memory_area_learning_frozen.return_value = {"frozen": True}
    client.get_learning_frozen.return_value = {"error": "HTTP 500"}
    assert (await freeze_memory_area(client, "m_a", True))["error"] == "readback_failed"


def test_samples_one_returns_at_once_with_summary() -> None:
    import asyncio

    clock = FakeClock()
    calls = 0

    async def diagnose() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        d = _diag([0.0, 5.0, 35.0])
        d["synapse_scan"]["weight_stats"]["at_cap_count"] = 1
        return d

    out = asyncio.run(
        watch_weights(diagnose, 20.0, 2.0, cap=35.0, max_samples=1, sleep=clock.sleep, clock=clock)
    )
    assert calls == 1 and clock.t == 0.0
    assert out["summary"] == {
        "count": 3,
        "min": 0.0,
        "max": 35.0,
        "avg": out["samples"][0]["avg"],
        "count_at_zero": 1,
        "count_at_max_weight": 1,
    }


def test_max_samples_three_takes_three() -> None:
    import asyncio

    clock = FakeClock()

    async def diagnose() -> dict[str, Any]:
        return _diag([1.0, 2.0])

    out = asyncio.run(
        watch_weights(diagnose, 1.0, 1.0, cap=None, max_samples=3, sleep=clock.sleep, clock=clock)
    )
    assert len(out["samples"]) == 3
