"""Tests for magnitude-passthrough validation (io_passthrough + client/server wiring).

Fixtures mirror a live audio genome: ``Audio Input Unit 0`` (2049x16) mapped
block_to_block onto ``Audio Output Unit 0``. The broken variant is the state
that made the Perception Inspector play full-scale noise.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.io_passthrough import (
    CODE_ACCUMULATION,
    CODE_DIMENSION_MISMATCH,
    CODE_EDGE_VOXEL_UNWIRED,
    CODE_EXCITABILITY,
    CODE_FAN_OUT_DIVIDES,
    CODE_MAGNITUDE_DISCARDED,
    CODE_MAGNITUDE_SCALED,
    CODE_MAPPING_MISSING,
    CODE_OUTPUT_THRESHOLD_GATES,
    CODE_REFRACTORY,
    CODE_RUNTIME_THRESHOLD_DRIFT,
    CODE_SNOOZE,
    CODE_SOURCE_SILENCED,
    edge_voxel,
    evaluate_magnitude_passthrough,
)

SRC = "aWF1ZAoAAAA="
DST = "b2F1ZAoAAAA="
F32_POINT_01 = 0.009999999776482582


def _area(name: str, dims: list[int], **neuron: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "cortical_name": name,
        "cortical_dimensions": dims,
        "neuron_fire_threshold": 0.01,
        "neuron_mp_driven_psp": True,
        "neuron_post_synaptic_potential": 1.0,
        "neuron_mp_charge_accumulation": False,
        "neuron_refractory_period": 0,
        "neuron_excitability": 1.0,
        "properties": {},
    }
    record.update(neuron)
    return record


def _healthy_src() -> dict[str, Any]:
    src = _area("Audio Input Unit 0", [2049, 16, 1])
    src["properties"]["cortical_mapping_dst"] = {
        DST: [
            {
                "morphology_id": "block_to_block",
                "morphology_scalar": [1, 1, 1],
                "postSynapticCurrent_multiplier": 1.0,
                "plasticity_flag": False,
            }
        ]
    }
    return src


def _healthy_dst() -> dict[str, Any]:
    return _area("Audio Output Unit 0", [2049, 16, 1], neuron_mp_driven_psp=False)


def _voxel(
    *,
    threshold: float = F32_POINT_01,
    incoming_from: list[str] | None = None,
    weights: list[float] | None = None,
    outgoing: int = 0,
) -> dict[str, Any]:
    return {
        "neuron_count": 1,
        "neurons": [
            {
                "threshold": threshold,
                "outgoing_synapse_count": outgoing,
                "incoming": {
                    "unique_cortical_ids": incoming_from or [],
                    "unique_weights": weights if weights is not None else [1.0],
                },
            }
        ],
    }


def _healthy_voxels() -> tuple[dict[str, Any], dict[str, Any]]:
    return _voxel(outgoing=1), _voxel(incoming_from=[SRC])


def _codes(report: dict[str, Any]) -> list[str]:
    return [f["code"] for f in report["findings"]]


def _evaluate(src, dst, src_voxel=None, dst_voxel=None) -> dict[str, Any]:
    default_src_voxel, default_dst_voxel = _healthy_voxels()
    return evaluate_magnitude_passthrough(
        SRC,
        DST,
        src,
        dst,
        default_src_voxel if src_voxel is None else src_voxel,
        default_dst_voxel if dst_voxel is None else dst_voxel,
    )


class TestEvaluateMagnitudePassthrough:
    def test_healthy_mirror_passes_with_no_findings(self):
        report = _evaluate(_healthy_src(), _healthy_dst())
        assert report["passes"] is True
        assert report["findings"] == []
        assert report["edge_voxel"] == [2048, 15, 0]

    def test_live_audio_genome_before_fix_reports_both_root_causes(self):
        src = _healthy_src()
        src["neuron_mp_driven_psp"] = False
        dst = _healthy_dst()
        dst["neuron_fire_threshold"] = 1.0
        report = _evaluate(src, dst, dst_voxel=_voxel(threshold=1.0, incoming_from=[SRC]))
        assert report["passes"] is False
        assert report["error_count"] == 2
        assert set(_codes(report)) == {CODE_MAGNITUDE_DISCARDED, CODE_OUTPUT_THRESHOLD_GATES}
        fixes = {f["code"]: f["fix"] for f in report["findings"]}
        assert fixes[CODE_MAGNITUDE_DISCARDED] == {
            "cortical_id": SRC,
            "updates": {"neuron_mp_driven_psp": True},
        }
        assert fixes[CODE_OUTPUT_THRESHOLD_GATES] == {
            "cortical_id": DST,
            "updates": {"neuron_fire_threshold": 0.01},
        }

    def test_f32_rounded_threshold_is_not_flagged(self):
        dst = _healthy_dst()
        dst["neuron_fire_threshold"] = F32_POINT_01
        assert _evaluate(_healthy_src(), dst)["findings"] == []

    def test_lower_destination_threshold_is_allowed(self):
        dst = _healthy_dst()
        dst["neuron_fire_threshold"] = 0.001
        report = _evaluate(
            _healthy_src(), dst, dst_voxel=_voxel(threshold=0.001, incoming_from=[SRC])
        )
        assert CODE_OUTPUT_THRESHOLD_GATES not in _codes(report)

    def test_missing_mapping_is_error_and_skips_topology(self):
        src = _healthy_src()
        src["properties"]["cortical_mapping_dst"] = {}
        report = _evaluate(src, _healthy_dst(), dst_voxel=_voxel(incoming_from=[]))
        assert _codes(report) == [CODE_MAPPING_MISSING]
        assert report["passes"] is False

    def test_top_level_mapping_bag_is_read(self):
        src = _healthy_src()
        src["cortical_mapping_dst"] = src["properties"].pop("cortical_mapping_dst")
        assert _evaluate(src, _healthy_dst())["passes"] is True

    def test_dimension_mismatch_uses_smaller_edge(self):
        dst = _healthy_dst()
        dst["cortical_dimensions"] = [513, 16, 1]
        report = _evaluate(_healthy_src(), dst)
        assert CODE_DIMENSION_MISMATCH in _codes(report)
        assert report["edge_voxel"] == [512, 15, 0]

    def test_stale_resize_leaves_edge_voxel_unwired(self):
        report = _evaluate(_healthy_src(), _healthy_dst(), dst_voxel=_voxel(incoming_from=[]))
        assert CODE_EDGE_VOXEL_UNWIRED in _codes(report)
        assert report["passes"] is False

    def test_empty_destination_voxel_is_unwired(self):
        report = _evaluate(_healthy_src(), _healthy_dst(), dst_voxel={"neurons": []})
        assert CODE_EDGE_VOXEL_UNWIRED in _codes(report)

    def test_psc_multiplier_and_weight_scaling_are_warnings(self):
        src = _healthy_src()
        src["properties"]["cortical_mapping_dst"][DST][0]["postSynapticCurrent_multiplier"] = 0.5
        report = _evaluate(
            src, _healthy_dst(), dst_voxel=_voxel(incoming_from=[SRC], weights=[0.25])
        )
        scaled = [f for f in report["findings"] if f["code"] == CODE_MAGNITUDE_SCALED]
        assert len(scaled) == 2
        assert all(f["severity"] == "warning" for f in scaled)
        assert report["passes"] is True

    def test_fan_out_divides_magnitude(self):
        report = _evaluate(_healthy_src(), _healthy_dst(), src_voxel=_voxel(outgoing=9))
        assert CODE_FAN_OUT_DIVIDES in _codes(report)

    def test_destination_dynamics_that_distort_frames(self):
        dst = _healthy_dst()
        dst.update(
            neuron_mp_charge_accumulation=True,
            neuron_refractory_period=2,
            neuron_excitability=0.5,
        )
        codes = _codes(_evaluate(_healthy_src(), dst))
        assert {CODE_ACCUMULATION, CODE_REFRACTORY, CODE_EXCITABILITY} <= set(codes)

    def test_source_refractory_and_snooze_fail_with_one_fix(self):
        # State after a genome reload: 16.7% of columns never reached the output.
        src = _healthy_src()
        src.update(neuron_refractory_period=15, neuron_snooze_period=11)
        report = _evaluate(src, _healthy_dst())
        assert report["passes"] is False
        finding = next(f for f in report["findings"] if f["code"] == CODE_SOURCE_SILENCED)
        assert finding["severity"] == "error"
        assert finding["fix"] == {
            "cortical_id": SRC,
            "updates": {"neuron_refractory_period": 0, "neuron_snooze_period": 0},
        }

    def test_source_reduced_excitability_is_flagged(self):
        src = _healthy_src()
        src["neuron_excitability"] = 0.5
        assert CODE_SOURCE_SILENCED in _codes(_evaluate(src, _healthy_dst()))

    def test_destination_snooze_is_a_warning(self):
        dst = _healthy_dst()
        dst["neuron_snooze_period"] = 3
        report = _evaluate(_healthy_src(), dst)
        assert report["passes"] is True
        assert CODE_SNOOZE in _codes(report)

    def test_runtime_threshold_drift(self):
        report = _evaluate(
            _healthy_src(), _healthy_dst(), dst_voxel=_voxel(threshold=1.0, incoming_from=[SRC])
        )
        assert CODE_RUNTIME_THRESHOLD_DRIFT in _codes(report)

    def test_edge_voxel_defaults_when_dimensions_missing(self):
        assert edge_voxel({}, {}) == (0, 0, 0)


def _ok(payload: Any) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


@pytest.fixture
def client() -> FeagiClient:
    """FeagiClient with only the FEAGI HTTP transport replaced."""
    feagi = FeagiClient()
    feagi._client = AsyncMock()
    return feagi


def _raw_voxel(summary: dict[str, Any]) -> dict[str, Any]:
    """Raw /voxel_neurons payload that projects to ``summary``."""
    neuron = copy.deepcopy(summary["neurons"][0])
    incoming = neuron.pop("incoming")
    neuron["incoming_synapses"] = [
        {"source_cortical_id": cid, "weight": w, "source_z": 0}
        for cid in incoming["unique_cortical_ids"]
        for w in incoming["unique_weights"]
    ]
    neuron["outgoing_synapses"] = [
        {"target_cortical_id": DST, "weight": 1.0, "target_z": 0}
    ] * neuron["outgoing_synapse_count"]
    neuron["incoming_synapse_count"] = len(neuron["incoming_synapses"])
    return {"neurons": [neuron]}


class TestClientValidateMagnitudePassthrough:
    @pytest.mark.asyncio
    async def test_fetches_properties_and_edge_voxels(self, client):
        src = _healthy_src()
        src["neuron_mp_driven_psp"] = False
        client._client.post.return_value = _ok({SRC: src, DST: _healthy_dst()})
        src_voxel, dst_voxel = _healthy_voxels()
        client._client.get.side_effect = [_ok(_raw_voxel(src_voxel)), _ok(_raw_voxel(dst_voxel))]

        report = await client.validate_magnitude_passthrough(SRC, DST)

        assert client._client.post.call_args.args[0].endswith(
            "/v1/cortical_area/multi/cortical_area_properties"
        )
        assert client._client.post.call_args.kwargs["json"] == [SRC, DST]
        voxel_params = [c.kwargs["params"] for c in client._client.get.call_args_list]
        assert {p["cortical_id"] for p in voxel_params} == {SRC, DST}
        assert all((p["x"], p["y"], p["z"]) == ("2048", "15", "0") for p in voxel_params)
        assert _codes(report) == [CODE_MAGNITUDE_DISCARDED]

    @pytest.mark.asyncio
    async def test_missing_area_is_reported(self, client):
        client._client.post.return_value = _ok({SRC: _healthy_src()})
        report = await client.validate_magnitude_passthrough(SRC, DST)
        assert report == {"error": "cortical_area_not_found", "missing": [DST]}
        client._client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_blank_ids_rejected(self, client):
        assert "error" in await client.validate_magnitude_passthrough(" ", DST)
        client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_voxel_fetch_error_is_surfaced(self, client):
        client._client.post.return_value = _ok({SRC: _healthy_src(), DST: _healthy_dst()})
        failure = MagicMock(status_code=404, text="not found")
        client._client.get.side_effect = [failure, failure]
        report = await client.validate_magnitude_passthrough(SRC, DST)
        assert report["dst_voxel_error"]["error"] == "HTTP 404"
        assert CODE_EDGE_VOXEL_UNWIRED in _codes(report)


class TestClientSynapseCounts:
    @pytest.mark.asyncio
    async def test_reads_counts_from_area_properties(self, client):
        client._client.post.return_value = _ok(
            {
                "cortical_name": "Audio Output Unit 0",
                "incoming_synapse_count": 32784,
                "outgoing_synapse_count": 0,
                "neuron_count": 32784,
            }
        )
        result = await client.get_cortical_synapse_counts(DST)
        assert client._client.post.call_args.args[0].endswith(
            "/v1/cortical_area/cortical_area_properties"
        )
        assert result == {
            "area_id": DST,
            "cortical_name": "Audio Output Unit 0",
            "incoming_synapses": 32784,
            "outgoing_synapses": 0,
            "neuron_count": 32784,
            "source": "cortical_area_properties",
        }
        client._client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_propagates_http_failure(self, client):
        client._client.post.return_value = MagicMock(status_code=404, text="missing")
        result = await client.get_cortical_synapse_counts(DST)
        assert result["error"] == "HTTP 404"


class TestServerTool:
    @pytest.mark.asyncio
    async def test_server_tool_delegates(self, monkeypatch):
        from feagi_mcp import server

        calls: list[tuple[str, str, int | None]] = []

        async def fake(src_area: str, dst_area: str, class_count: int | None) -> dict[str, Any]:
            calls.append((src_area, dst_area, class_count))
            return {"passes": True}

        monkeypatch.setattr(server.feagi, "validate_magnitude_passthrough", fake)
        assert await server.validate_magnitude_passthrough(SRC, DST) == {"passes": True}
        assert await server.validate_magnitude_passthrough(SRC, DST, 19) == {"passes": True}
        assert calls == [(SRC, DST, None), (SRC, DST, 19)]
