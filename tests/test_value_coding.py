"""Tests for value-coded planes: class/depth encoding, wiring, bins, decode, classifier tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.classifiers import build_classifier_inspect
from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.value_coding import (
    CODE_CLASS_COUNT_MISSING,
    CODE_MASK_NOT_SINGLE_LAYER,
    CODE_THRESHOLD_ABOVE_SMALLEST_CLASS,
    CODE_TWIN_NOT_FORWARDING,
    CODE_TWIN_NOT_SINGLE_LAYER,
    bins_geometry,
    class_count_error,
    classifier_value_findings,
    decode_class_potential,
    decode_fire_queue_classes,
    destination_threshold_finding,
    encode_class_potential,
    escalate_for_exact_values,
    passthrough_threshold,
)

TWIN = "dHdpbjAwMDE="
OSEG = "b3NlZwoAAAA="


def _ok(payload: Any) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    return response


class TestEncoding:
    def test_every_class_round_trips(self) -> None:
        for count in (1, 19, 256, 9999):
            for class_id in (0, count // 2, count - 1):
                potential = encode_class_potential(class_id, count)
                assert 0.0 < potential <= 1.0
                assert decode_class_potential(potential, count) == class_id

    def test_small_drift_still_decodes_and_zero_is_silent(self) -> None:
        potential = encode_class_potential(13, 19)
        assert decode_class_potential(potential + 0.01, 19) == 13
        assert decode_class_potential(0.0, 19) is None
        assert decode_class_potential(1.3, 19) is None
        assert decode_class_potential(True, 19) is None

    def test_class_count_limits(self) -> None:
        assert class_count_error(19) is None
        assert class_count_error(0) is not None
        assert class_count_error(10000) is not None
        assert class_count_error(True) is not None
        with pytest.raises(ValueError):
            encode_class_potential(19, 19)

    def test_threshold_admits_the_smallest_value_with_margin(self) -> None:
        assert passthrough_threshold(19, None) == pytest.approx(0.5 / 19)
        assert passthrough_threshold(None, 256) == pytest.approx(0.5 / 256)
        with pytest.raises(ValueError):
            passthrough_threshold(None, 0)


class TestBinsGeometry:
    def test_class_c_fires_bins_zero_through_c(self) -> None:
        geometry = bins_geometry(19, 1.0)
        for class_id in (0, 7, 18):
            value = encode_class_potential(class_id, 19)
            fired = [
                z
                for z in range(19)
                if value >= geometry["base_threshold"] + z * geometry["threshold_increment_z"]
            ]
            assert fired == list(range(class_id + 1))

    def test_rejects_bad_inputs(self) -> None:
        with pytest.raises(ValueError):
            bins_geometry(0, 1.0)
        with pytest.raises(ValueError):
            bins_geometry(8, 0.0)


class TestExactValueRules:
    def test_scaling_warnings_become_errors_for_class_ids(self) -> None:
        report = {
            "passes": True,
            "findings": [
                {"severity": "warning", "code": "magnitude_scaled", "message": "x", "fix": None},
                {
                    "severity": "warning",
                    "code": "destination_refractory_drops_bursts",
                    "message": "y",
                    "fix": None,
                },
            ],
        }
        escalated = escalate_for_exact_values(report, 19)
        assert escalated["passes"] is False
        assert escalated["error_count"] == 1
        assert escalated["warning_count"] == 1

    def test_destination_threshold_must_be_below_class_zero(self) -> None:
        assert destination_threshold_finding({"neuron_fire_threshold": 0.01}, OSEG, 19) is None
        finding = destination_threshold_finding({"neuron_fire_threshold": 0.06}, OSEG, 19)
        assert finding is not None
        assert finding["code"] == CODE_THRESHOLD_ABOVE_SMALLEST_CLASS
        assert finding["fix"]["updates"]["neuron_fire_threshold"] == pytest.approx(0.5 / 19)


class TestDecodeFireQueue:
    def test_histogram_pixels_and_cap(self) -> None:
        fire_queue = {
            "timestep": 42,
            "cortical_areas": {
                TWIN: {
                    "coordinates_x": [0, 1, 2, 3],
                    "coordinates_y": [0, 0, 0, 0],
                    "membrane_potentials": [
                        encode_class_potential(13, 19),
                        encode_class_potential(13, 19),
                        encode_class_potential(0, 19),
                        5.0,
                    ],
                }
            },
        }
        decoded = decode_fire_queue_classes(fire_queue, TWIN, 19, max_pixels=2)
        assert decoded["fired"] == 4
        assert decoded["class_histogram"] == {"0": 1, "13": 2}
        assert decoded["undecodable"] == 1
        assert len(decoded["pixels"]) == 2
        assert decoded["truncated"] is True
        assert decoded["timestep"] == 42

    def test_silent_area_is_empty(self) -> None:
        decoded = decode_fire_queue_classes({"cortical_areas": {}}, TWIN, 19, max_pixels=10)
        assert decoded["fired"] == 0
        assert decoded["pixels"] == []


def _scanner(**overrides: Any) -> dict[str, Any]:
    record = {
        "classifier_id": "clf-scan",
        "name": "Scan",
        "training_mode": "scanner",
        "mask_area_id": "mask",
        "kernel_size": [8, 8, 3],
        "class_count": 19,
        "kernel_memory_id": "kmem",
        "class_memory_id": "cmem",
        "fields": [{"field_area_id": "field", "scan_twin_id": "twin"}],
    }
    record.update(overrides)
    return record


def _catalog(mask_depth: int = 1, twin_depth: int = 1, **twin: Any) -> dict[str, dict[str, Any]]:
    return {
        "mask": {"cortical_id": "mask", "cortical_dimensions": [16, 8, mask_depth]},
        "twin": {"cortical_id": "twin", "cortical_dimensions": [16, 8, twin_depth], **twin},
    }


class TestClassifierValueFindings:
    def test_healthy_scanner_has_no_findings(self) -> None:
        assert classifier_value_findings(_scanner(), _catalog(), ["twin"]) == []

    def test_flags_missing_count_deep_mask_deep_twin_and_flat_twin(self) -> None:
        codes = {
            f["code"]
            for f in classifier_value_findings(
                _scanner(class_count=None),
                _catalog(mask_depth=19, twin_depth=19, neuron_mp_driven_psp=False),
                ["twin"],
            )
        }
        assert codes == {
            CODE_CLASS_COUNT_MISSING,
            CODE_MASK_NOT_SINGLE_LAYER,
            CODE_TWIN_NOT_SINGLE_LAYER,
            CODE_TWIN_NOT_FORWARDING,
        }

    def test_inspect_blocks_scanning_on_value_errors(self) -> None:
        areas = [
            {"cortical_id": "mask", "cortical_dimensions": [16, 8, 19]},
            {"cortical_id": "twin", "cortical_dimensions": [16, 8, 1], "visible": True},
        ]
        payload = build_classifier_inspect(_scanner(), areas, [], None)
        assert CODE_MASK_NOT_SINGLE_LAYER in payload["scan_blockers"]
        assert payload["scan_ready"] is False
        assert payload["value_findings"][0]["code"] == CODE_MASK_NOT_SINGLE_LAYER


@pytest.fixture
def client() -> FeagiClient:
    feagi = FeagiClient()
    feagi._client = AsyncMock()
    return feagi


class TestWireValuePassthrough:
    @pytest.mark.asyncio
    async def test_sets_both_ends_maps_and_validates(self, client) -> None:
        client.fetch_multi_cortical_area_properties = AsyncMock(
            return_value={
                TWIN: {"cortical_dimensions": [16, 8, 1]},
                OSEG: {"cortical_dimensions": [16, 8, 1]},
            }
        )
        client.update_cortical_area = AsyncMock(return_value={"success": True})
        client.update_cortical_mapping = AsyncMock(return_value={"success": True})
        client.validate_magnitude_passthrough = AsyncMock(return_value={"passes": True})

        result = await client.wire_value_passthrough(TWIN, OSEG, class_count=19)

        source_call, destination_call = client.update_cortical_area.await_args_list
        assert source_call.args == (
            TWIN,
            {"neuron_mp_driven_psp": True, "neuron_psp_uniform_distribution": True},
        )
        assert destination_call.args[0] == OSEG
        assert destination_call.args[1]["neuron_fire_threshold"] == pytest.approx(0.5 / 19)
        assert destination_call.args[1]["neuron_mp_charge_accumulation"] is False
        rule = client.update_cortical_mapping.await_args.args[2][0]
        assert rule["morphology_id"] == "projector"
        assert rule["postSynapticCurrent_multiplier"] == 1.0
        client.validate_magnitude_passthrough.assert_awaited_once_with(TWIN, OSEG, 19)
        assert result["validation"] == {"passes": True}

    @pytest.mark.asyncio
    async def test_requires_exactly_one_scale(self, client) -> None:
        both = await client.wire_value_passthrough(TWIN, OSEG, class_count=19, value_levels=8)
        neither = await client.wire_value_passthrough(TWIN, OSEG)
        assert both["error"] == neither["error"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_rejects_shape_mismatch_without_writing(self, client) -> None:
        client.fetch_multi_cortical_area_properties = AsyncMock(
            return_value={
                TWIN: {"cortical_dimensions": [16, 8, 1]},
                OSEG: {"cortical_dimensions": [16, 8, 19]},
            }
        )
        client.update_cortical_area = AsyncMock()
        result = await client.wire_value_passthrough(TWIN, OSEG, class_count=19)
        assert result["error"] == "dimension_mismatch"
        client.update_cortical_area.assert_not_awaited()


class TestExpandValueToBins:
    @pytest.mark.asyncio
    async def test_creates_ramped_bins_and_maps(self, client) -> None:
        client.fetch_cortical_area_properties = AsyncMock(
            return_value={"cortical_dimensions": [64, 48, 1]}
        )
        client.create_cortical_area = AsyncMock(return_value={"cortical_id": "YmluczAwMDE="})
        client.update_cortical_area = AsyncMock(return_value={"success": True})
        client.update_cortical_mapping = AsyncMock(return_value={"success": True})

        result = await client.expand_value_to_bins(
            "ZGVwdGgwMDE=", 16, "Depth_Bins", "region-1", [100, 0, 0]
        )

        assert client.create_cortical_area.await_args.kwargs["dimensions"] == [64, 48, 16]
        bins_updates = client.update_cortical_area.await_args_list[1].args[1]
        assert bins_updates["neuron_fire_threshold"] == pytest.approx(0.5 / 16)
        assert bins_updates["neuron_fire_threshold_increment"] == [0.0, 0.0, pytest.approx(1 / 16)]
        assert result["bins_area"] == "YmluczAwMDE="
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_rejects_multi_layer_source(self, client) -> None:
        client.fetch_cortical_area_properties = AsyncMock(
            return_value={"cortical_dimensions": [64, 48, 64]}
        )
        result = await client.expand_value_to_bins("x", 16, "n", "r", [100, 0, 0])
        assert result["error"] == "not_a_value_plane"


class TestDecodeClassMapClient:
    @pytest.mark.asyncio
    async def test_one_fire_queue_read(self, client) -> None:
        client.get_fire_queue_detailed = AsyncMock(
            return_value={
                "cortical_areas": {
                    OSEG: {
                        "coordinates_x": [3],
                        "coordinates_y": [1],
                        "membrane_potentials": [encode_class_potential(4, 6)],
                    }
                }
            }
        )
        decoded = await client.decode_class_map(OSEG, 6)
        assert decoded["pixels"] == [{"x": 3, "y": 1, "class_id": 4}]
        client.get_fire_queue_detailed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_bad_class_count(self, client) -> None:
        assert (await client.decode_class_map(OSEG, 0))["error"] == "invalid_input"


class TestClassifierWriteTools:
    @pytest.mark.asyncio
    async def test_scanner_create_posts_class_count(self, client) -> None:
        client._client.request.return_value = _ok({"classifier_id": "clf-1"})
        result = await client.create_classifier(
            "Scan",
            "region-1",
            [1, 2, 3],
            "scanner",
            mask_area_id="mask",
            kernel_size=[8, 8, 3],
            class_count=19,
        )
        method, url = client._client.request.call_args.args
        body = client._client.request.call_args.kwargs["json"]
        assert (method, url.endswith("/v1/cortical_area/classifier")) == ("POST", True)
        assert body["class_count"] == 19
        assert "kernel_area_id" not in body
        assert result == {"classifier_id": "clf-1"}

    @pytest.mark.asyncio
    async def test_scanner_create_requires_class_count(self, client) -> None:
        result = await client.create_classifier(
            "Scan", "region-1", [1, 2, 3], "scanner", mask_area_id="mask", kernel_size=[8, 8, 3]
        )
        assert result["error"] == "invalid_input"
        client._client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_and_attach_hit_classifier_routes(self, client) -> None:
        client._client.request.return_value = _ok({"success": True})
        await client.update_classifier("clf-1", {"class_count": 6})
        assert client._client.request.call_args.args[0] == "PUT"
        assert client._client.request.call_args.args[1].endswith("/classifier/clf-1")
        await client.attach_classifier_field("clf-1", "field")
        assert client._client.request.call_args.args[1].endswith("/classifier/clf-1/field")
        assert client._client.request.call_args.kwargs["json"] == {"field_area_id": "field"}
        bad = await client.update_classifier("clf-1", {"class_count": 0})
        assert bad["error"] == "invalid_input"


class TestServerDelegation:
    @pytest.mark.asyncio
    async def test_new_tools_delegate(self, monkeypatch) -> None:
        from feagi_mcp import server

        async def fake(*args: Any) -> dict[str, Any]:
            return {"args": list(args)}

        for name in (
            "wire_value_passthrough",
            "expand_value_to_bins",
            "decode_class_map",
            "create_classifier",
            "update_classifier",
            "attach_classifier_field",
        ):
            monkeypatch.setattr(server.feagi, name, fake)
        assert (await server.wire_value_passthrough(TWIN, OSEG, 19))["args"] == [
            TWIN,
            OSEG,
            19,
            None,
        ]
        assert (await server.decode_class_map(OSEG, 19))["args"] == [OSEG, 19, 200]
        assert (await server.attach_classifier_field("c", "f"))["args"] == ["c", "f"]
