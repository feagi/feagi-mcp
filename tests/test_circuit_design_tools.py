"""Tests for Tier 1 slim listings, circuit-design helpers, and embodiment proxies.

Covers the MCP improvements added on top of the deficiency gap-fillers:

* ``list_morphologies_summary`` (filtered + paginated slim view).
* ``get_connectivity_summary`` (slim tabular view from cortical_map_detailed).
* ``inspect_cortical_areas_minimal`` (plasticity-relevant projection of the
  multi-area inspection payload).
* ``build_reflex_mapping`` (compose ``create_morphology`` + ``update_cortical_mapping``).
* ``auto_polarity_probe`` (force-fire each OPU column, compare sensor centroid
  against baseline).
* ``embodiment_get_physics_state`` / ``embodiment_set_joint_state`` HTTP proxies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feagi_mcp.feagi_client import FeagiClient


@pytest.fixture
def mock_client() -> FeagiClient:
    """FeagiClient with a mocked HTTPX client."""
    client = FeagiClient()
    client._client = AsyncMock()
    return client


def _ok(payload):
    """Build a MagicMock that mimics a 200 httpx response."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


class TestListMorphologiesSummary:
    @pytest.mark.asyncio
    async def test_returns_slim_rows_and_pagination(self, mock_client):
        full = {
            "0_0_0-1_0_0": {
                "class": "custom",
                "name": "0_0_0-1_0_0",
                "type": "patterns",
                "source": "genome",
                "parameters": {"patterns": [[[0, 0, 0], [1, 0, 0]]]},
            },
            "all_to_all": {
                "class": "core",
                "name": "all_to_all",
                "type": "patterns",
                "source": "genome",
                "parameters": {"patterns": [[["*", "*", "*"], ["*", "*", "*"]]]},
            },
            "lateral_+x": {
                "class": "core",
                "name": "lateral_+x",
                "type": "vectors",
                "source": "genome",
                "parameters": {"vectors": [[1, 0, 0]]},
            },
        }
        mock_client._client.get.return_value = _ok(full)

        out = await mock_client.list_morphologies_summary(limit=2, offset=0)

        assert out["total_unfiltered"] == 3
        assert out["total_filtered"] == 3
        assert out["returned"] == 2
        assert [r["name"] for r in out["items"]] == ["0_0_0-1_0_0", "all_to_all"]
        assert out["items"][0]["pattern_count"] == 1
        assert out["items"][1]["type"] == "patterns"
        # Each row stays small.
        for row in out["items"]:
            assert set(row.keys()) == {"name", "type", "class", "pattern_count", "source"}

    @pytest.mark.asyncio
    async def test_filters_apply_before_pagination(self, mock_client):
        full = {
            "lateral_+x": {
                "class": "core",
                "type": "vectors",
                "parameters": {"vectors": [[1, 0, 0]]},
            },
            "lateral_-x": {
                "class": "core",
                "type": "vectors",
                "parameters": {"vectors": [[-1, 0, 0]]},
            },
            "tile": {"class": "core", "type": "composite", "parameters": {}},
        }
        mock_client._client.get.return_value = _ok(full)

        out = await mock_client.list_morphologies_summary(name_substring="lateral")
        assert out["total_filtered"] == 2

        out = await mock_client.list_morphologies_summary(type_filter="vectors")
        assert out["total_filtered"] == 2

        out = await mock_client.list_morphologies_summary(
            class_filter="core",
            type_filter="composite",
        )
        assert out["total_filtered"] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_summary_when_upstream_returns_no_data(self, mock_client):
        mock_client._client.get.return_value = MagicMock(status_code=500, text="boom")
        out = await mock_client.list_morphologies_summary()
        assert out["total_unfiltered"] == 0
        assert out["total_filtered"] == 0
        assert out["items"] == []


class TestGetConnectivitySummary:
    @pytest.mark.asyncio
    async def test_flattens_detailed_map(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {
                "src_a": {
                    "dst_x": [
                        {
                            "morphology_id": "all_to_all",
                            "postSynapticCurrent_multiplier": 5,
                            "plasticity_flag": False,
                            "plasticity_constant": 0,
                        },
                        {
                            "morphology_id": "lateral_+x",
                            "postSynapticCurrent_multiplier": 1,
                            "plasticity_flag": True,
                            "plasticity_constant": 7,
                        },
                    ],
                    "dst_y": [
                        {
                            "morphology_id": "tile",
                            "postSynapticCurrent_multiplier": -2,
                            "plasticity_flag": False,
                            "plasticity_constant": 0,
                        }
                    ],
                },
                "src_b": {
                    "dst_x": [
                        {
                            "morphology_id": "all_to_0-0-0",
                            "postSynapticCurrent_multiplier": 3,
                            "plasticity_flag": False,
                            "plasticity_constant": 0,
                        }
                    ],
                },
            }
        )

        out = await mock_client.get_connectivity_summary()
        assert out["total_filtered"] == 4
        names = [(r["src"], r["dst"], r["morphology"]) for r in out["items"]]
        assert ("src_a", "dst_x", "all_to_all") in names
        required_keys = {"src", "dst", "morphology", "psc_mult", "plasticity"}
        assert all(set(r.keys()) >= required_keys for r in out["items"])

    @pytest.mark.asyncio
    async def test_filters_and_pagination(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {
                "src_a": {
                    "dst_x": [{"morphology_id": "m1", "postSynapticCurrent_multiplier": 1}],
                    "dst_y": [{"morphology_id": "m2", "postSynapticCurrent_multiplier": 2}],
                },
                "src_b": {
                    "dst_x": [{"morphology_id": "m3", "postSynapticCurrent_multiplier": 3}],
                },
            }
        )
        out = await mock_client.get_connectivity_summary(src_filter="src_a", limit=1)
        assert out["total_filtered"] == 2
        assert out["returned"] == 1

        out2 = await mock_client.get_connectivity_summary(dst_filter="dst_x")
        assert {r["src"] for r in out2["items"]} == {"src_a", "src_b"}


class TestInspectCorticalAreasMinimal:
    @pytest.mark.asyncio
    async def test_projects_to_known_fields(self, mock_client):
        full_payload = {
            "id_a": {
                "cortical_name": "imu-0",
                "area_type": "IPU",
                "cortical_dimensions": [3, 1, 10],
                "neuron_count": 30,
                "neuron_fire_threshold": 1.0,
                "neuron_post_synaptic_potential": 5.0,
                "neuron_post_synaptic_potential_max": 50.0,
                "neuron_excitability": 100,
                "neuron_leak_coefficient": 0.0,
                "neuron_refractory_period": 1,
                "neuron_snooze_period": 0,
                "neuron_consecutive_fire_count": 1,
                "neuron_plasticity_constant": 0,
                "neuron_psp_uniform_distribution": True,
                "neuron_mp_charge_accumulation": False,
                "neuron_burst_engine_active": True,
                "incoming_synapse_count": 0,
                "outgoing_synapse_count": 30,
                "visualization_geometry": "BIG_BLOB_THAT_SHOULD_BE_DROPPED",
                "encoding_options": ["lots", "of", "stuff"],
            },
        }
        mock_client._client.post.return_value = _ok(full_payload)

        out = await mock_client.inspect_cortical_areas_minimal(["id_a"])
        assert "id_a" in out
        projected = out["id_a"]
        assert "visualization_geometry" not in projected
        assert "encoding_options" not in projected
        assert projected["neuron_post_synaptic_potential_max"] == 50.0
        assert projected["incoming_synapse_count"] == 0

    @pytest.mark.asyncio
    async def test_rejects_empty_list(self, mock_client):
        out = await mock_client.inspect_cortical_areas_minimal([])
        assert "error" in out
        mock_client._client.post.assert_not_called()


class TestBuildReflexMapping:
    @pytest.mark.asyncio
    async def test_creates_morphology_then_updates_mapping(self, mock_client):
        mock_client.create_morphology = AsyncMock(return_value={"success": True})
        mock_client.get_cortical_mapping = AsyncMock(return_value={"rules": []})
        mock_client.update_cortical_mapping = AsyncMock(return_value={"success": True})

        out = await mock_client.build_reflex_mapping(
            src_area_id="src",
            dst_area_id="dst",
            morphology_name="hinge_to_cart",
            voxel_mappings=[
                {"src": [0, 0, 0], "dst": [0, 0, 4]},
                {"src": [0, 0, 1], "dst": [0, 0, 3]},
            ],
            postsynaptic_current_multiplier=5,
            plasticity_flag=True,
            plasticity_constant=2,
        )

        assert out["patterns_count"] == 2
        assert out["rule"]["postSynapticCurrent_multiplier"] == 5
        assert out["rule"]["plasticity_flag"] is True
        assert out["rule"]["morphology_id"] == "hinge_to_cart"

        mock_client.create_morphology.assert_awaited_once()
        morph_args = mock_client.create_morphology.await_args.kwargs
        assert morph_args["morphology_name"] == "hinge_to_cart"
        assert morph_args["morphology_type"] == "patterns"
        patterns = morph_args["morphology_parameters"]["patterns"]
        assert patterns == [[[0, 0, 0], [0, 0, 4]], [[0, 0, 1], [0, 0, 3]]]

        mock_client.update_cortical_mapping.assert_awaited_once()
        rules_sent = mock_client.update_cortical_mapping.await_args.kwargs["mapping_rules"]
        assert rules_sent[0]["morphology_id"] == "hinge_to_cart"

    @pytest.mark.asyncio
    async def test_replace_existing_skips_existing_rules_fetch(self, mock_client):
        mock_client.create_morphology = AsyncMock(return_value={"success": True})
        mock_client.get_cortical_mapping = AsyncMock(return_value={"rules": []})
        mock_client.update_cortical_mapping = AsyncMock(return_value={"success": True})

        await mock_client.build_reflex_mapping(
            src_area_id="src",
            dst_area_id="dst",
            morphology_name="m",
            voxel_mappings=[{"src": [0, 0, 0], "dst": [0, 0, 0]}],
            postsynaptic_current_multiplier=1,
            replace_existing=True,
        )
        mock_client.get_cortical_mapping.assert_not_awaited()
        rules_sent = mock_client.update_cortical_mapping.await_args.kwargs["mapping_rules"]
        assert len(rules_sent) == 1

    @pytest.mark.asyncio
    async def test_appends_to_existing_rules(self, mock_client):
        mock_client.create_morphology = AsyncMock(return_value={"success": True})
        existing_rule = {
            "morphology_id": "old",
            "postSynapticCurrent_multiplier": 1,
            "plasticity_flag": False,
        }
        mock_client.get_cortical_mapping = AsyncMock(return_value={"rules": [existing_rule]})
        mock_client.update_cortical_mapping = AsyncMock(return_value={"success": True})

        await mock_client.build_reflex_mapping(
            src_area_id="src",
            dst_area_id="dst",
            morphology_name="new",
            voxel_mappings=[{"src": [0, 0, 0], "dst": [0, 0, 0]}],
            postsynaptic_current_multiplier=2,
        )
        rules_sent = mock_client.update_cortical_mapping.await_args.kwargs["mapping_rules"]
        assert len(rules_sent) == 2
        assert rules_sent[0]["morphology_id"] == "old"
        assert rules_sent[1]["morphology_id"] == "new"

    @pytest.mark.asyncio
    async def test_rejects_bad_voxel_mapping_shape(self, mock_client):
        mock_client.create_morphology = AsyncMock()
        out = await mock_client.build_reflex_mapping(
            src_area_id="s",
            dst_area_id="d",
            morphology_name="m",
            voxel_mappings=[{"src": [0, 0], "dst": [0, 0, 0]}],
            postsynaptic_current_multiplier=1,
        )
        assert "error" in out
        mock_client.create_morphology.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_propagates_morphology_create_failure(self, mock_client):
        mock_client.create_morphology = AsyncMock(return_value={"error": "duplicate"})
        mock_client.update_cortical_mapping = AsyncMock()
        out = await mock_client.build_reflex_mapping(
            src_area_id="s",
            dst_area_id="d",
            morphology_name="m",
            voxel_mappings=[{"src": [0, 0, 0], "dst": [0, 0, 0]}],
            postsynaptic_current_multiplier=1,
        )
        assert out["error"] == "create_morphology_failed"
        mock_client.update_cortical_mapping.assert_not_awaited()


class TestAutoPolarityProbe:
    @pytest.mark.asyncio
    async def test_infers_direction_from_z_centroid_shift(self, mock_client):
        # Sequence of sensor snapshots: baseline, after col0, after col1.
        snapshots = [
            {"areas": [{"samples": [{"z": 5, "potential": 1.0}]}]},
            {"areas": [{"samples": [{"z": 7, "potential": 1.0}]}]},
            {"areas": [{"samples": [{"z": 3, "potential": 1.0}]}]},
        ]
        mock_client.get_sensor_snapshot_last = AsyncMock(side_effect=snapshots)
        mock_client.stimulate_areas = AsyncMock(return_value={"success": True})

        with patch("asyncio.sleep", new=AsyncMock()):
            out = await mock_client.auto_polarity_probe(
                opu_id="opu",
                sensor_id="sensor",
                columns=[0, 1],
                intensity_z=5,
                repeats=1,
                settle_ms=10,
            )

        assert out["baseline_z_centroid"] == pytest.approx(5.0)
        assert out["inferred_direction_map"]["col_0"] == "positive_z"
        assert out["inferred_direction_map"]["col_1"] == "negative_z"
        assert mock_client.stimulate_areas.await_count == 2

    @pytest.mark.asyncio
    async def test_marks_indeterminate_when_sensor_silent(self, mock_client):
        mock_client.get_sensor_snapshot_last = AsyncMock(
            side_effect=[
                {"areas": []},
                {"areas": []},
            ]
        )
        mock_client.stimulate_areas = AsyncMock(return_value={"success": True})

        with patch("asyncio.sleep", new=AsyncMock()):
            out = await mock_client.auto_polarity_probe(
                opu_id="opu",
                sensor_id="sensor",
                columns=[0],
                repeats=1,
                settle_ms=0,
            )
        assert out["inferred_direction_map"]["col_0"] == "indeterminate"


class TestEmbodimentProxies:
    @pytest.mark.asyncio
    async def test_get_physics_state_calls_introspection_url(self):
        client = FeagiClient()
        with patch("feagi_mcp.feagi_client.httpx.AsyncClient") as ctor:
            inner = AsyncMock()
            inner.get.return_value = _ok({"time": 1.5, "joints": {}})
            ctor.return_value.__aenter__.return_value = inner
            out = await client.embodiment_get_physics_state("http://localhost:9876")
        assert out == {"time": 1.5, "joints": {}}
        inner.get.assert_awaited_once_with("http://localhost:9876/v1/state")

    @pytest.mark.asyncio
    async def test_set_joint_state_posts_payload(self):
        client = FeagiClient()
        with patch("feagi_mcp.feagi_client.httpx.AsyncClient") as ctor:
            inner = AsyncMock()
            inner.post.return_value = _ok({"status": "queued", "request_id": 1})
            ctor.return_value.__aenter__.return_value = inner
            out = await client.embodiment_set_joint_state(
                "http://localhost:9876/",
                joint_qpos={"hinge": 0.3},
                joint_qvel={"slider": 0.0},
            )
        assert out["status"] == "queued"
        post_call = inner.post.await_args
        assert post_call.args[0] == "http://localhost:9876/v1/set_state"
        body = post_call.kwargs["json"]
        assert body == {"joint_qpos": {"hinge": 0.3}, "joint_qvel": {"slider": 0.0}}

    @pytest.mark.asyncio
    async def test_set_joint_state_rejects_empty(self):
        client = FeagiClient()
        out = await client.embodiment_set_joint_state("http://localhost:9876")
        assert "error" in out
