"""Test new MCP tools for agent introspection and genome editing."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import FeagiClient


@pytest.fixture
def mock_client():
    """Create a FeagiClient with mocked HTTP client."""
    client = FeagiClient()
    client._client = AsyncMock()
    return client


class TestAgentIntrospection:
    """Test agent introspection tools."""

    @pytest.mark.asyncio
    async def test_get_agent_properties(self, mock_client):
        """Test fetching agent properties."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "test_agent_id": {
                "agent_name": "MuJoCo_Spot",
                "capabilities": {"motor": True},
            }
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_agent_properties("test_agent_id")

        assert result["agent_name"] == "MuJoCo_Spot"
        assert "capabilities" in result

    @pytest.mark.asyncio
    async def test_get_agent_device_registrations(self, mock_client):
        """Test fetching device registrations."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "test_agent_id": {
                "agent_name": "MuJoCo_Spot",
                "capabilities": {
                    "motor": True,
                    "device_registrations": {
                        "output_units_and_decoder_properties": {
                            "PositionalServo": [
                                [
                                    {
                                        "cortical_unit_index": 0,
                                        "device_grouping": [
                                            {
                                                "device_properties": {
                                                    "joint_name": {
                                                        "type": "String",
                                                        "value": "fl_hx",
                                                    }
                                                }
                                            }
                                        ],
                                    }
                                ]
                            ]
                        }
                    },
                },
            }
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_agent_device_registrations("test_agent_id")

        assert "device_registrations" in result
        assert "output_units_and_decoder_properties" in result["device_registrations"]

    @pytest.mark.asyncio
    async def test_get_agent_device_registrations_falls_back_to_capabilities_level(
        self, mock_client
    ):
        """Top-level capability registrations are normalized into device_registrations."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "test_agent_id": {
                "agent_name": "Lite6",
                "capabilities": {
                    "motor": True,
                    "device_registrations": {},
                    "output_units_and_decoder_properties": {
                        "SpatialPointer": [[[{"cortical_unit_index": 1}, {}]]]
                    },
                },
            }
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_agent_device_registrations("test_agent_id")

        dev_reg = result["device_registrations"]
        assert "output_units_and_decoder_properties" in dev_reg


class TestVersionInfo:
    """Test FEAGI version info retrieval."""

    @pytest.mark.asyncio
    async def test_get_version_info_success(self, mock_client):
        """Fetches version payload from /v1/system/versions."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "feagi_core": "2.0.0",
            "rust": "1.79.0",
            "build_timestamp": "2026-08-12T15:00:00Z",
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_version_info()

        assert result["feagi_core"] == "2.0.0"
        assert result["rust"] == "1.79.0"

    @pytest.mark.asyncio
    async def test_get_version_info_http_error(self, mock_client):
        """Surfaces HTTP failures from /v1/system/versions."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "not found"
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_version_info()

        assert result["error"] == "HTTP 404"
        assert "message" in result


class TestMemoryAreaRuntimeConfigTool:
    """Runtime memory lifecycle config tool (single-source diagnostic payload)."""

    @pytest.mark.asyncio
    async def test_prefers_runtime_memory_parameters(self, monkeypatch):
        """Runtime memory params should win when both endpoints provide values."""
        from feagi_mcp import server

        async def fake_props(_cortical_id: str):
            return {
                "cortical_id": "mem_id",
                "cortical_name": "mem_a",
                "cortical_idx": 9,
                "cortical_type": "memory",
                "properties": {"is_mem_type": True},
                "neuron_init_lifespan": 1,
                "neuron_lifespan_growth_rate": 1.0,
                "neuron_longterm_mem_threshold": 10,
            }

        async def fake_bv_operation(_operation_id: str, **_kwargs):
            return {
                "cortical_id": "mem_id",
                "cortical_name": "mem_a",
                "cortical_idx": 9,
                "short_term_neuron_count": 2,
                "long_term_neuron_count": 3,
                "total_memory_neuron_ids": 5,
                "memory_parameters": {
                    "init_lifespan": 9,
                    "lifespan_growth_rate": 2.0,
                    "longterm_mem_threshold": 100,
                },
            }

        monkeypatch.setattr(server.feagi, "fetch_cortical_area_properties", fake_props)
        monkeypatch.setattr(server.feagi, "brain_visualizer_operation", fake_bv_operation)

        result = await server.get_memory_area_runtime_config("mem_id")
        lifecycle = result["effective_lifecycle"]

        assert lifecycle["init_lifespan"]["value"] == 9
        assert lifecycle["init_lifespan"]["source"] == "runtime_memory_parameters"
        assert lifecycle["lifespan_growth_rate"]["value"] == 2.0
        assert lifecycle["longterm_mem_threshold"]["value"] == 100
        assert result["consistency"]["st_plus_lt_matches_total"] is True
        assert sorted(result["consistency"]["lifecycle_param_mismatches"]) == [
            "init_lifespan",
            "lifespan_growth_rate",
            "longterm_mem_threshold",
        ]

    @pytest.mark.asyncio
    async def test_falls_back_to_cortical_properties_when_runtime_zero(self, monkeypatch):
        """Zero runtime lifecycle values should fall back to cortical properties."""
        from feagi_mcp import server

        async def fake_props(_cortical_id: str):
            return {
                "cortical_id": "mem_id",
                "cortical_name": "mem_b",
                "cortical_idx": 11,
                "cortical_type": "memory",
                "properties": {"is_mem_type": True},
                "neuron_init_lifespan": 7,
                "neuron_lifespan_growth_rate": 1.5,
                "neuron_longterm_mem_threshold": 70,
            }

        async def fake_bv_operation(_operation_id: str, **_kwargs):
            return {
                "short_term_neuron_count": 0,
                "long_term_neuron_count": 4,
                "total_memory_neuron_ids": 4,
                "memory_parameters": {
                    "init_lifespan": 0,
                    "lifespan_growth_rate": 0.0,
                    "longterm_mem_threshold": 0,
                },
            }

        monkeypatch.setattr(server.feagi, "fetch_cortical_area_properties", fake_props)
        monkeypatch.setattr(server.feagi, "brain_visualizer_operation", fake_bv_operation)

        result = await server.get_memory_area_runtime_config("mem_id")
        lifecycle = result["effective_lifecycle"]

        assert lifecycle["init_lifespan"]["value"] == 7
        assert lifecycle["init_lifespan"]["source"] == "cortical_properties"
        assert lifecycle["lifespan_growth_rate"]["value"] == 1.5
        assert lifecycle["longterm_mem_threshold"]["value"] == 70


class TestAgentJointMap:
    """Joint-map extraction from legacy and current registration payloads."""

    @pytest.mark.asyncio
    async def test_get_agent_joint_map_parses_decoder_properties_shape(self, mock_client):
        """Extract joints from output_units_and_decoder_properties payloads."""
        mock_client.get_agent_device_registrations = AsyncMock(
            return_value={
                "agent_id": "agent_a",
                "device_registrations": {
                    "output_units_and_decoder_properties": {
                        "PositionalServo": [
                            [
                                {
                                    "cortical_unit_index": 0,
                                    "io_configuration_flags": {"frame_change_handling": "Absolute"},
                                    "device_grouping": [
                                        {
                                            "channel_index_override": None,
                                            "device_properties": {
                                                "joint_name": {
                                                    "type": "String",
                                                    "value": "joint1",
                                                }
                                            },
                                            "friendly_name": "joint1",
                                        },
                                        {
                                            "channel_index_override": 5,
                                            "device_properties": {
                                                "joint_name": {
                                                    "type": "String",
                                                    "value": "joint6",
                                                }
                                            },
                                            "friendly_name": "joint6",
                                        },
                                    ],
                                },
                                {},
                            ]
                        ]
                    }
                },
            }
        )
        mock_client.list_cortical_areas = AsyncMock(
            return_value=[
                {
                    "cortical_id": "b3BzZQEAAAA=",
                    "cortical_group": "OPU",
                    "cortical_subtype": "opse",
                    "unit_id": 0,
                    "subunit_id": 0,
                }
            ]
        )

        result = await mock_client.get_agent_joint_map("agent_a")

        assert result["total_joints"] == 2
        assert result["opu_cortical_ids"] == ["b3BzZQEAAAA="]
        assert result["joints"][0]["joint_name"] == "joint1"
        assert result["joints"][0]["control_mode"] == "Absolute"
        assert result["joints"][0]["cortical_id"] == "b3BzZQEAAAA="
        assert result["joints"][1]["channel_index"] == 5


class TestGenomeEditing:
    """Test genome editing tools."""

    @pytest.mark.asyncio
    async def test_create_cortical_area_opu(self, mock_client):
        """Test creating OPU cortical area."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": "Created 1 cortical areas",
            "cortical_id": "b3BzZQEAAAA=",
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.create_cortical_area(
            name="fl_hip",
            cortical_type="OPU",
            dimensions=[3, 1, 10],
            position=[800, 400, -30],
            device_count=3,
            properties={"grp_id": 0},
            cortical_id="omot",
            data_type_configs_by_subunit={"0": 256},
        )

        assert result["message"] == "Created 1 cortical areas"
        assert "cortical_id" in result

    @pytest.mark.asyncio
    async def test_create_cortical_area_custom(self, mock_client):
        """Test creating custom cortical area."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": "Custom cortical area created successfully",
            "cortical_id": "Y0hpcEZM",
        }
        mock_client._client.post.return_value = mock_response
        mock_client.get_cortical_area_geometry = AsyncMock(return_value={})

        result = await mock_client.create_cortical_area(
            name="TestArea",
            cortical_type="CUSTOM",
            dimensions=[5, 5, 5],
            position=[50, 50, 0],
            brain_region_id="00000000-0000-0000-0000-000000000001",
        )

        assert "cortical_id" in result

    @pytest.mark.asyncio
    async def test_create_cortical_area_custom_requires_brain_region_id(self, mock_client):
        """CUSTOM/MEMORY require brain_region_id (API + client guard)."""
        result = await mock_client.create_cortical_area(
            name="TestArea",
            cortical_type="CUSTOM",
            dimensions=[5, 5, 5],
            position=[0, 0, 0],
        )
        assert result.get("error")
        assert "brain_region_id" in result["error"]

    @pytest.mark.asyncio
    async def test_update_cortical_area(self, mock_client):
        """Test updating cortical area properties."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": "Cortical area updated",
            "cortical_id": "test_id",
        }
        mock_client._client.put.return_value = mock_response

        result = await mock_client.update_cortical_area("test_id", {"neuron_fire_threshold": 50.0})

        assert result["message"] == "Cortical area updated"

    @pytest.mark.asyncio
    async def test_delete_cortical_area(self, mock_client):
        """Test deleting cortical area."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Cortical area deleted"}
        mock_client._client.request.return_value = mock_response

        result = await mock_client.delete_cortical_area("test_id")

        assert result["message"] == "Cortical area deleted"
        mock_client._client.request.assert_called_once()
        call_kw = mock_client._client.request.call_args
        assert call_kw[0][0] == "DELETE"
        assert "cortical_area/cortical_area" in str(call_kw[0][1])


class TestConnectionManagement:
    """Test connection management tools."""

    @pytest.mark.asyncio
    async def test_get_cortical_mapping(self, mock_client):
        """Test fetching cortical mapping."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "morphology_id": "all_to_all",
                "postSynapticCurrent_multiplier": 25.0,
            }
        ]
        mock_client._client.post.return_value = mock_response

        result = await mock_client.get_cortical_mapping("src_area", "dst_area")

        assert result["src_area"] == "src_area"
        assert result["dst_area"] == "dst_area"
        assert len(result["rules"]) > 0

    @pytest.mark.asyncio
    async def test_update_cortical_mapping(self, mock_client):
        """Test updating cortical mapping."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": "Cortical mapping properties updated successfully",
            "synapse_count": 100,
        }
        mock_client._client.put.return_value = mock_response

        mapping_rules = [
            {
                "morphology_id": "all_to_all",
                "morphology_scalar": [1, 1, 1],
                "postSynapticCurrent_multiplier": 25.0,
                "plasticity_flag": False,
                "plasticity_constant": 1,
                "ltp_multiplier": 1,
                "ltd_multiplier": 1,
                "plasticity_window": 0,
            }
        ]

        result = await mock_client.update_cortical_mapping("cHipFL", "opose1", mapping_rules)

        assert "synapse_count" in result

    @pytest.mark.asyncio
    async def test_delete_cortical_mapping(self, mock_client):
        """Test deleting cortical mapping."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Mapping deletion not yet implemented"}
        mock_client._client.delete.return_value = mock_response

        result = await mock_client.delete_cortical_mapping("src_area", "dst_area")

        assert "message" in result

    @pytest.mark.asyncio
    async def test_get_memory_twin_diagnostic(self, mock_client):
        """Test fetching memory twin diagnostic."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "src_cortical_area": "src_area",
            "dst_cortical_area": "dst_area",
            "mapping_exists": True,
            "episodic_rule_count": 1,
            "twin_expected": True,
            "twin_present": False,
            "reason": "twin_expected_but_missing",
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_memory_twin_diagnostic("src_area", "dst_area")

        assert result["mapping_exists"] is True
        assert result["twin_expected"] is True
        assert result["twin_present"] is False
        assert result["reason"] == "twin_expected_but_missing"
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/cortical_mapping/twin_diagnostic",
            params={
                "src_cortical_area": "src_area",
                "dst_cortical_area": "dst_area",
            },
        )

    @pytest.mark.asyncio
    async def test_server_diagnose_memory_twin_mapping_tool(self, monkeypatch):
        """Server tool should delegate twin diagnostics to FeagiClient."""
        from feagi_mcp import server

        async def fake_diag(src: str, dst: str):
            return {
                "src_cortical_area": src,
                "dst_cortical_area": dst,
                "twin_expected": True,
                "twin_present": True,
            }

        monkeypatch.setattr(server.feagi, "get_memory_twin_diagnostic", fake_diag)
        result = await server.diagnose_memory_twin_mapping("A", "B")
        assert result["src_cortical_area"] == "A"
        assert result["dst_cortical_area"] == "B"
        assert result["twin_present"] is True

    @pytest.mark.asyncio
    async def test_get_mapping_plasticity_diagnostics_filters_src_dst_weights(self, mock_client):
        """Mapping plasticity diagnostics should isolate realized src->dst synapses."""
        mock_client.get_cortical_mapping = AsyncMock(
            return_value={
                "src_area": "src_area",
                "dst_area": "dst_area",
                "rules": [
                    {
                        "morphology_id": "associative_memory",
                        "plasticity_flag": True,
                        "plasticity_constant": 1,
                    }
                ],
            }
        )
        mock_client.fetch_cortical_area_properties = AsyncMock(
            return_value={
                "cortical_id": "dst_area",
                "cortical_idx": 99,
                "cortical_name": "Destination memory",
            }
        )
        mock_client.list_area_synapses = AsyncMock(
            return_value={
                "cortical_area_id": "src_area",
                "direction": "outgoing",
                "synapse_count": 3,
                "synapses": [
                    {
                        "source_neuron_id": 1,
                        "target_neuron_id": 10,
                        "weight": 1.5,
                        "postsynaptic_potential": 500.0,
                        "target_cortical_id": None,
                        "target_cortical_idx": 0,
                    },
                    {
                        "source_neuron_id": 2,
                        "target_neuron_id": 11,
                        "weight": 0.0,
                        "postsynaptic_potential": 500.0,
                    },
                    {
                        "source_neuron_id": 3,
                        "target_neuron_id": 12,
                        "weight": 4.0,
                        "postsynaptic_potential": 500.0,
                    },
                ],
            }
        )
        neuron_list_response = MagicMock()
        neuron_list_response.status_code = 200
        neuron_list_response.json.return_value = [10, 11]
        mock_client._client.get.return_value = neuron_list_response

        result = await mock_client.get_mapping_plasticity_diagnostics("src_area", "dst_area")

        assert result["mapping_exists"] is True
        assert result["plastic_rules_count"] == 1
        assert result["is_associative_memory_mapping"] is True
        scan = result["synapse_scan"]
        assert scan["outgoing_synapse_count_from_src"] == 3
        assert scan["matched_synapse_count_src_to_dst"] == 2
        stats = scan["weight_stats"]
        assert stats["min"] == 0.0
        assert stats["max"] == 1.5
        assert stats["sum"] == 1.5
        assert stats["zero_weight_count"] == 1
        assert stats["nonzero_weight_count"] == 1
        assert scan["sample"][0]["target_cortical_id"] == "dst_area"
        assert scan["sample"][0]["target_cortical_idx"] == 99
        assert scan["sample"][0]["target_identity_source"] == "destination_neuron_membership"
        assert scan["sample"][0]["reported_target_cortical_id"] is None
        assert scan["sample"][0]["reported_target_cortical_idx"] == 0
        assert result["resolution"]["destination_cortical_idx"] == 99

    @pytest.mark.asyncio
    async def test_mapping_diagnostic_resolves_paginated_memory_destination_ids(self, mock_client):
        """Dynamic memory IDs must come from the memory endpoint, not dense neurons."""
        mock_client.get_cortical_mapping = AsyncMock(
            return_value={
                "rules": [
                    {
                        "morphology_id": "associative_memory",
                        "plasticity_flag": True,
                    }
                ]
            }
        )
        mock_client.fetch_cortical_area_properties = AsyncMock(
            return_value={
                "cortical_id": "memory_dst",
                "cortical_idx": 16,
                "cortical_type": "memory",
                "properties": {"is_mem_type": True},
            }
        )
        mock_client.list_area_synapses = AsyncMock(
            return_value={
                "synapses": [
                    {
                        "source_neuron_id": 50000001,
                        "target_neuron_id": 50000002,
                        "weight": 2.5,
                        "target_cortical_id": None,
                        "target_cortical_idx": 0,
                    }
                ]
            }
        )
        mock_client.list_memory_neurons = AsyncMock(
            side_effect=[
                {"memory_neuron_ids": [50000001], "has_more": True},
                {"memory_neuron_ids": [50000002], "has_more": False},
            ]
        )

        result = await mock_client.get_mapping_plasticity_diagnostics("memory_src", "memory_dst")

        assert result["synapse_scan"]["matched_synapse_count_src_to_dst"] == 1
        sample = result["synapse_scan"]["sample"][0]
        assert sample["target_neuron_id"] == 50000002
        assert sample["target_cortical_id"] == "memory_dst"
        assert sample["target_cortical_idx"] == 16
        assert sample["target_identity_source"] == "destination_neuron_membership"
        assert result["resolution"]["destination_neuron_count"] == 2
        assert result["resolution"]["destination_is_memory_area"] is True
        assert mock_client.list_memory_neurons.await_count == 2
        mock_client._client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_server_diagnose_mapping_plasticity_tool(self, monkeypatch):
        """Server tool should delegate mapping plasticity diagnostics to FeagiClient."""
        from feagi_mcp import server

        async def fake_diag(src: str, dst: str, sample_limit: int = 20):
            return {
                "src_area": src,
                "dst_area": dst,
                "sample_limit": sample_limit,
                "mapping_exists": True,
            }

        monkeypatch.setattr(server.feagi, "get_mapping_plasticity_diagnostics", fake_diag)
        result = await server.diagnose_mapping_plasticity("S", "D", sample_limit=7)
        assert result["src_area"] == "S"
        assert result["dst_area"] == "D"
        assert result["sample_limit"] == 7


class TestMemoryNeuronTools:
    """Direct MCP coverage for runtime memory-neuron inspection."""

    @pytest.mark.asyncio
    async def test_server_list_memory_neurons_tool(self, monkeypatch):
        """Server tool should return the paginated memory-area payload."""
        from feagi_mcp import server

        list_memory_neurons = AsyncMock(
            return_value={"memory_neuron_ids": [50000001], "has_more": False}
        )
        monkeypatch.setattr(server.feagi, "list_memory_neurons", list_memory_neurons)

        result = await server.list_memory_neurons("memory_area", page=2, page_size=10)

        assert result["memory_neuron_ids"] == [50000001]
        list_memory_neurons.assert_awaited_once_with("memory_area", 2, 10)

    @pytest.mark.asyncio
    async def test_server_inspect_memory_neuron_tool(self, monkeypatch):
        """Server tool should expose lifecycle and synapse details for one memory neuron."""
        from feagi_mcp import server

        inspect_memory_neuron = AsyncMock(
            return_value={"neuron_id": 50000001, "is_longterm_memory": True}
        )
        monkeypatch.setattr(server.feagi, "inspect_memory_neuron", inspect_memory_neuron)

        result = await server.inspect_memory_neuron(50000001)

        assert result["is_longterm_memory"] is True
        inspect_memory_neuron.assert_awaited_once_with(50000001)


class TestFilteredLists:
    """Test filtered list tools."""

    @pytest.mark.asyncio
    async def test_list_opu_areas(self, mock_client):
        """Test listing OPU areas."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["b3BzZQEAAAA=", "b3BzZQEAAAE="]
        mock_client._client.get.return_value = mock_response

        result = await mock_client.list_opu_areas()

        assert len(result) == 2
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/cortical_area/opu"
        )

    @pytest.mark.asyncio
    async def test_list_ipu_areas(self, mock_client):
        """Test listing IPU areas."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["Y2lpcHJvMF8="]
        mock_client._client.get.return_value = mock_response

        result = await mock_client.list_ipu_areas()

        assert len(result) == 1
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/cortical_area/ipu"
        )


class TestBrainVisualizerParity:
    """Endpoints aligned with Brain Visualizer (FEAGIHTTPAddressList / FEAGIRequests)."""

    @pytest.mark.asyncio
    async def test_get_cortical_area_geometry_uses_bv_path(self, mock_client):
        """Geometry must use /cortical_area/geometry (not cortical_area_geometry)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"abc": {"position": [0, 0, 0]}}
        mock_client._client.get.return_value = mock_response

        await mock_client.get_cortical_area_geometry()

        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/cortical_area/cortical_area/geometry"
        )

    @pytest.mark.asyncio
    async def test_resolve_cortical_display_name_exact(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Y2lk": "Area One", "Y2lkMg": "Area Two"}
        mock_client._client.get.return_value = mock_response

        result = await mock_client.resolve_cortical_display_name("Area One", "exact")

        assert result["resolved_cortical_id"] == "Y2lk"
        assert result["match_count"] == 1

    @pytest.mark.asyncio
    async def test_save_genome_to_filesystem(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": "Genome saved successfully",
            "file_path": "/tmp/out.genome",
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.save_genome_to_filesystem(file_path="/tmp/out.genome")

        assert result["file_path"] == "/tmp/out.genome"
        mock_client._client.post.assert_called_once_with(
            "http://localhost:8000/v1/genome/save",
            json={"file_path": "/tmp/out.genome"},
        )

    @pytest.mark.asyncio
    async def test_download_connectome(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "file_path": "/tmp/connectome/saved_connectome_2026_09_02-17_45_37.connectome",
            "message": "Connectome saved successfully",
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.download_connectome()

        assert result["file_path"].endswith(".connectome")
        assert "saved_connectome" in result["file_path"]
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/connectome/download"
        )

    @pytest.mark.asyncio
    async def test_upload_connectome(self, mock_client, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Connectome imported successfully"}
        mock_client._client.post.return_value = mock_response
        connectome_path = tmp_path / "saved_connectome_test.connectome"
        connectome_path.write_bytes(b"FEAGI")

        result = await mock_client.upload_connectome(str(connectome_path))

        assert "imported" in result["message"]
        mock_client._client.post.assert_called_once()
        call_kwargs = mock_client._client.post.call_args
        assert call_kwargs.args[0] == "http://localhost:8000/v1/connectome/upload"
        assert "file" in call_kwargs.kwargs["files"]


class TestGenomeCompleteness:
    def test_analyze_genome_completeness_flat_memory_plastic_regions(self):
        from feagi_mcp.feagi_client import analyze_genome_completeness

        genome = {
            "blueprint": {
                "_____10c-mmem01-cx-memory-b": True,
                "_____10c-csrc01-cx-dstmap-d": {
                    "mmem01": [{"morphology_id": "projector", "plasticity_flag": True}]
                },
            },
            "brain_regions": {"root": {"title": "Root"}},
            "neuron_morphologies": {"projector": {"type": "functions"}},
            "physiology": {"simulation_timestep": 0.025},
        }
        result = analyze_genome_completeness(genome)
        assert result["complete"] is True
        assert result["memory_area_count"] == 1
        assert result["plastic_mapping_count"] == 1
        assert result["brain_region_count"] == 1


class TestValidateBrainRegionHierarchyTool:
    """Hierarchy validation helper for BV root-region assumptions."""

    @pytest.mark.asyncio
    async def test_reports_valid_single_root_hierarchy(self, monkeypatch):
        from feagi_mcp import server

        async def fake_regions():
            return {
                "root-1": {
                    "title": "Root Brain Region",
                    "parent_region_id": None,
                    "regions": ["child-1"],
                },
                "child-1": {
                    "title": "Child",
                    "parent_region_id": "root-1",
                    "regions": [],
                },
            }

        async def fake_genome():
            return {"brain_regions_root": "root-1"}

        monkeypatch.setattr(server.feagi, "get_regions_members", fake_regions)
        monkeypatch.setattr(server.feagi, "download_genome", fake_genome)

        result = await server.validate_brain_region_hierarchy()

        assert result["valid"] is True
        assert result["root_region_id"] == "root-1"
        assert result["issues"] == []
        assert result["missing_parent_references"] == []
        assert result["cycles"] == []

    @pytest.mark.asyncio
    async def test_reports_missing_parent_and_cycle(self, monkeypatch):
        from feagi_mcp import server

        async def fake_regions():
            return {
                "A": {"title": "A", "parent_region_id": "B", "regions": []},
                "B": {"title": "B", "parent_region_id": "A", "regions": []},
                "C": {
                    "title": "C",
                    "parent_region_id": "missing-parent",
                    "regions": [],
                },
            }

        async def fake_genome():
            return {}

        monkeypatch.setattr(server.feagi, "get_regions_members", fake_regions)
        monkeypatch.setattr(server.feagi, "download_genome", fake_genome)

        result = await server.validate_brain_region_hierarchy()

        assert result["valid"] is False
        assert result["root_region_id"] is None
        assert result["missing_parent_references"] == [
            {"region_id": "C", "missing_parent_region_id": "missing-parent"}
        ]
        assert len(result["cycles"]) >= 1
        assert any("No root region detected" in issue for issue in result["issues"])


class TestStimulation:
    """Manual stimulation API."""

    @pytest.mark.asyncio
    async def test_stimulate_areas_posts_combined_payload(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "unique_neuron_ids": 2,
            "matched_coordinates": 2,
            "mode": "force_fire",
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.stimulate_areas(
            {"areaA": [[0, 0, 0]], "areaB": [[0, 0, 0]]},
        )

        assert result["success"] is True
        mock_client._client.post.assert_called_once_with(
            "http://localhost:8000/v1/agent/manual_stimulation",
            json={
                "stimulation_payload": {
                    "areaA": [[0, 0, 0]],
                    "areaB": [[0, 0, 0]],
                },
                "mode": "force_fire",
            },
        )


class TestStimulateAreaBatch:
    """Batch stimulation within one cortical area."""

    @pytest.mark.asyncio
    async def test_stimulate_area_batch_empty_returns_error(self, mock_client):
        result = await mock_client.stimulate_area_batch("areaX", [])
        assert result["success"] is False
        assert "non-empty" in result["error"]
        mock_client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_stimulate_area_batch_invalid_coord_length(self, mock_client):
        result = await mock_client.stimulate_area_batch(
            "areaX",
            [[0, 0, 0], [1, 2]],
        )
        assert result["success"] is False
        assert "coordinates_list[1]" in result["error"]
        mock_client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_stimulate_area_batch_posts_single_payload(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "unique_neuron_ids": 7,
            "matched_coordinates": 7,
            "mode": "force_fire",
        }
        mock_client._client.post.return_value = mock_response

        coords = [[i, 0, 4] for i in range(7)]
        result = await mock_client.stimulate_area_batch("opse_left", coords)

        assert result["success"] is True
        mock_client._client.post.assert_called_once_with(
            "http://localhost:8000/v1/agent/manual_stimulation",
            json={
                "stimulation_payload": {"opse_left": coords},
                "mode": "force_fire",
            },
        )


class TestCreateBrainRegion:
    """POST /v1/region/region via FeagiClient.create_brain_region."""

    @pytest.mark.asyncio
    async def test_create_brain_region_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "region_id": "abc-uuid",
            "title": "Mohammad",
            "parent_region_id": None,
            "coordinate_2d": [10, 20],
            "coordinate_3d": [0, 0, 0],
            "areas": [],
            "regions": [],
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.create_brain_region(
            "Mohammad",
            [10, 20],
            [0, 0, 0],
            parent_region_id=None,
        )

        assert result["title"] == "Mohammad"
        assert result["region_id"] == "abc-uuid"
        mock_client._client.post.assert_called_once()
        call_kw = mock_client._client.post.call_args
        assert call_kw[0][0].endswith("/v1/region/region")
        body = call_kw[1]["json"]
        assert body["title"] == "Mohammad"
        assert body["coordinates_2d"] == [10, 20]
        assert body["coordinates_3d"] == [0, 0, 0]

    @pytest.mark.asyncio
    async def test_create_brain_region_rejects_empty_title(self, mock_client):
        result = await mock_client.create_brain_region(
            "   ",
            [0, 0],
            [0, 0, 0],
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_brain_region_rejects_bad_dimensions(self, mock_client):
        r1 = await mock_client.create_brain_region("X", [0], [0, 0, 0])
        assert "error" in r1
        r2 = await mock_client.create_brain_region("X", [0, 0], [0, 0])
        assert "error" in r2


class TestBrainVisualizerRouter:
    """Unified BV API router."""

    @pytest.mark.asyncio
    async def test_brain_visualizer_operation_unknown_id(self, mock_client):
        result = await mock_client.brain_visualizer_operation("not_a_real_op")
        assert result.get("error") == "unknown_operation_id"

    @pytest.mark.asyncio
    async def test_brain_visualizer_operation_get_health(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"ok":true}'
        mock_response.json.return_value = {"ok": True}
        mock_client._client.get.return_value = mock_response

        result = await mock_client.brain_visualizer_operation("get_system_health_check")
        assert result == {"ok": True}
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/system/health_check",
        )


class TestAgentLiveness:
    """GET /v1/agent/liveness via FeagiClient.get_agent_liveness.

    Registration alone does not keep an agent connected: FEAGI reaps agents that stay
    quiet past the heartbeat timeout, closing their sockets. These fields are what let a
    caller tell inactivity pruning apart from a transport failure.
    """

    @pytest.mark.asyncio
    async def test_returns_ages_and_countdown(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "heartbeat_timeout_s": 30.0,
            "stale_check_interval_s": 0.1,
            "count": 1,
            "agents": [
                {
                    "agent_id": "abc123",
                    "agent_name": "brain-visualizer",
                    "manufacturer": "neuraville",
                    "agent_version": 1,
                    "capabilities": ["receive_neuron_visualizations"],
                    "last_activity_age_s": 27.4,
                    "last_command_control_age_s": 27.4,
                    "prune_in_s": 2.6,
                }
            ],
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_agent_liveness()

        assert result["heartbeat_timeout_s"] == 30.0
        agent = result["agents"][0]
        assert agent["agent_id"] == "abc123"
        assert agent["prune_in_s"] == 2.6
        # A command/control age tracking the activity age means the agent sends nothing
        # of its own and is about to be reaped.
        assert agent["last_command_control_age_s"] == agent["last_activity_age_s"]
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/agent/liveness",
        )

    @pytest.mark.asyncio
    async def test_reports_no_agents_without_error(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "heartbeat_timeout_s": 30.0,
            "stale_check_interval_s": 0.1,
            "count": 0,
            "agents": [],
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_agent_liveness()

        assert result["count"] == 0
        assert result["agents"] == []

    @pytest.mark.asyncio
    async def test_non_200_returns_error_payload(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "boom"
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_agent_liveness()

        assert result["error"] == "HTTP 500"
        assert result["endpoint"] == "/v1/agent/liveness"


class TestLogTailDisabledHint:
    """A disabled log ring buffer must say how to enable it.

    Without the hint the payload reads as "no logs exist", which invites retries against
    an endpoint that can never return anything until FEAGI is restarted.
    """

    @pytest.mark.asyncio
    async def test_disabled_buffer_carries_actionable_hint(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "enabled": False,
            "capacity": 0,
            "records": [],
            "returned": 0,
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_log_tail()

        assert result["enabled"] is False
        assert "FEAGI_LOG_RING_BUFFER_CAPACITY" in result["hint"]
        assert "stdout" in result["hint"]

    @pytest.mark.asyncio
    async def test_enabled_buffer_has_no_hint(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "enabled": True,
            "capacity": 2000,
            "records": [{"level": "INFO", "message": "burst"}],
            "returned": 1,
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_log_tail()

        assert "hint" not in result
        assert result["returned"] == 1


class TestFireQueueDetailed:
    """Detailed fire-queue diagnostics endpoint + MCP tool delegation."""

    @pytest.mark.asyncio
    async def test_client_get_fire_queue_detailed_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "timestep": 42,
            "total_fired": 2,
            "cortical_areas": {
                "bWFhYV9fX0M=": {
                    "cortical_idx": 10,
                    "fired_count": 1,
                    "neuron_ids": [16393],
                    "coordinates_x": [0],
                    "coordinates_y": [0],
                    "coordinates_z": [0],
                    "membrane_potentials": [100.0],
                }
            },
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_fire_queue_detailed()

        assert result["timestep"] == 42
        assert result["total_fired"] == 2
        assert "bWFhYV9fX0M=" in result["cortical_areas"]
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/burst_engine/fire_queue/detailed"
        )

    @pytest.mark.asyncio
    async def test_client_get_fire_queue_detailed_http_error(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "not found"
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_fire_queue_detailed()

        assert result["error"] == "HTTP 404"
        assert result["endpoint"] == "/v1/burst_engine/fire_queue/detailed"

    @pytest.mark.asyncio
    async def test_server_get_fire_queue_detailed_tool(self, monkeypatch):
        from feagi_mcp import server

        expected = {
            "timestep": 7,
            "total_fired": 1,
            "cortical_areas": {
                "bXNkZl9fX1I=": {
                    "cortical_idx": 8,
                    "fired_count": 1,
                    "neuron_ids": [8],
                    "coordinates_x": [0],
                    "coordinates_y": [0],
                    "coordinates_z": [0],
                    "membrane_potentials": [128.0],
                }
            },
        }

        async def fake_get_fire_queue_detailed():
            return expected

        monkeypatch.setattr(server.feagi, "get_fire_queue_detailed", fake_get_fire_queue_detailed)
        result = await server.get_fire_queue_detailed()
        assert result == expected


class TestNetworkConnectionInfo:
    """GET /v1/network/connection_info via FeagiClient.get_network_connection_info."""

    @pytest.mark.asyncio
    async def test_returns_parsed_payload(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "zmq": {
                "enabled": True,
                "host": "127.0.0.1",
                "endpoints": {
                    "registration": "tcp://127.0.0.1:30001",
                    "sensory": "tcp://127.0.0.1:5558",
                    "motor": "tcp://127.0.0.1:5564",
                },
            },
            "stream_status": {"zmq_data_streams_started": True},
        }
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_network_connection_info()

        assert result["zmq"]["endpoints"]["registration"] == "tcp://127.0.0.1:30001"
        mock_client._client.get.assert_called_once_with(
            "http://localhost:8000/v1/network/connection_info",
        )

    @pytest.mark.asyncio
    async def test_non_200_returns_error_payload(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "boom"
        mock_client._client.get.return_value = mock_response

        result = await mock_client.get_network_connection_info()

        assert result["error"] == "HTTP 500"
        assert result["endpoint"] == "/v1/network/connection_info"


class TestLoadGenomeFromFileTool:
    """MCP tool that provisions a genome from a local file path."""

    @pytest.mark.asyncio
    async def test_uploads_file_and_returns_summary(self, monkeypatch, tmp_path):
        from feagi_mcp import server

        genome = {
            "genome_title": "iris_classifier",
            "blueprint": {"iv00_C": {}, "o____C": {}},
        }
        genome_file = tmp_path / "iris.genome"
        genome_file.write_text(json.dumps(genome), encoding="utf-8")

        captured = {}

        async def fake_upload(data):
            captured["data"] = data
            return {"success": True, "cortical_area_count": 2}

        monkeypatch.setattr(server.feagi, "upload_genome", fake_upload)

        result = await server.load_genome_from_file(str(genome_file))

        assert result["success"] is True
        assert result["genome_title"] == "iris_classifier"
        assert result["cortical_area_count"] == 2
        assert result["upload_result"]["success"] is True
        # The full genome was uploaded, not just the summary.
        assert captured["data"] == genome

    @pytest.mark.asyncio
    async def test_missing_file_returns_error_without_uploading(self, monkeypatch, tmp_path):
        from feagi_mcp import server

        called = {"uploaded": False}

        async def fake_upload(_data):
            called["uploaded"] = True
            return {"success": True}

        monkeypatch.setattr(server.feagi, "upload_genome", fake_upload)

        result = await server.load_genome_from_file(str(tmp_path / "missing.genome"))

        assert result["success"] is False
        assert result["error"] == "file_not_found"
        assert called["uploaded"] is False

    @pytest.mark.asyncio
    async def test_json_extension_is_rejected(self, tmp_path):
        from feagi_mcp import server

        genome_file = tmp_path / "legacy.json"
        genome_file.write_text("{}", encoding="utf-8")

        result = await server.load_genome_from_file(str(genome_file))

        assert result["success"] is False
        assert result["error"] == "invalid_extension"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error_without_uploading(self, monkeypatch, tmp_path):
        from feagi_mcp import server

        called = {"uploaded": False}

        async def fake_upload(_data):
            called["uploaded"] = True
            return {"success": True}

        monkeypatch.setattr(server.feagi, "upload_genome", fake_upload)

        bad_file = tmp_path / "bad.genome"
        bad_file.write_text("{ not valid json", encoding="utf-8")

        result = await server.load_genome_from_file(str(bad_file))

        assert result["success"] is False
        assert result["error"] == "invalid_json"
        assert called["uploaded"] is False


class TestGetAgentConnectionEndpointsTool:
    """MCP tool that surfaces ZMQ endpoints + burst rate for the remote runtime."""

    @pytest.mark.asyncio
    async def test_derives_remote_runtime_block(self, monkeypatch):
        from feagi_mcp import server

        async def fake_connection_info():
            return {
                "zmq": {
                    "enabled": True,
                    "endpoints": {
                        "registration": "tcp://127.0.0.1:30001",
                        "sensory": "tcp://127.0.0.1:5558",
                        "motor": "tcp://127.0.0.1:5564",
                    },
                },
                "stream_status": {"zmq_data_streams_started": True},
            }

        async def fake_burst_status():
            return {"active": True, "paused": False, "frequency_hz": 15.0}

        monkeypatch.setattr(server.feagi, "get_network_connection_info", fake_connection_info)
        monkeypatch.setattr(server.feagi, "get_burst_engine_status", fake_burst_status)

        result = await server.get_agent_connection_endpoints()

        remote = result["remote_runtime"]
        assert remote["registration_endpoint"] == "tcp://127.0.0.1:30001"
        assert remote["sensory_endpoint"] == "tcp://127.0.0.1:5558"
        assert remote["motor_endpoint"] == "tcp://127.0.0.1:5564"
        assert remote["burst_frequency_hz"] == 15.0
        assert remote["zmq_enabled"] is True
        assert remote["data_streams_started"] is True

    @pytest.mark.asyncio
    async def test_tolerates_connection_info_error(self, monkeypatch):
        from feagi_mcp import server

        async def fake_connection_info():
            return {"error": "HTTP 500", "endpoint": "/v1/network/connection_info"}

        async def fake_burst_status():
            return {"frequency_hz": 15.0}

        monkeypatch.setattr(server.feagi, "get_network_connection_info", fake_connection_info)
        monkeypatch.setattr(server.feagi, "get_burst_engine_status", fake_burst_status)

        result = await server.get_agent_connection_endpoints()

        assert result["connection_info"]["error"] == "HTTP 500"
        # Endpoints unknown, but burst rate still surfaced.
        assert result["remote_runtime"]["registration_endpoint"] is None
        assert result["remote_runtime"]["burst_frequency_hz"] == 15.0


class TestFireLedgerWindowConfigTool:
    """MCP tool for FireLedger per-area window diagnostics."""

    @pytest.mark.asyncio
    async def test_server_get_fire_ledger_areas_window_config(self, monkeypatch):
        from feagi_mcp import server

        expected = {
            "total_configured_areas": 2,
            "default_window_size": 20,
            "areas": {"bWFhYV9fX0M=": 3, "bXNkZl9fX1I=": 3},
        }

        async def fake_get_fire_ledger_areas_window_config():
            return expected

        monkeypatch.setattr(
            server.feagi,
            "get_fire_ledger_areas_window_config",
            fake_get_fire_ledger_areas_window_config,
        )

        result = await server.get_fire_ledger_areas_window_config()
        assert result == expected


class TestRenameMorphology:
    """Dedicated MCP tool for PUT /v1/morphology/rename."""

    @pytest.mark.asyncio
    async def test_rename_morphology_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "old_morphology_id": "rule_a",
            "new_morphology_id": "rule_b",
        }
        mock_client._client.put.return_value = mock_response

        result = await mock_client.rename_morphology("rule_a", "rule_b")

        assert result["status"] == "success"
        assert result["new_morphology_id"] == "rule_b"
        mock_client._client.put.assert_awaited_once()
        call_kwargs = mock_client._client.put.await_args.kwargs
        assert call_kwargs["json"] == {
            "old_morphology_id": "rule_a",
            "new_morphology_id": "rule_b",
        }

    @pytest.mark.asyncio
    async def test_rename_morphology_strips_whitespace(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_client._client.put.return_value = mock_response

        await mock_client.rename_morphology("  old  ", "  new  ")

        call_kwargs = mock_client._client.put.await_args.kwargs
        assert call_kwargs["json"]["old_morphology_id"] == "old"
        assert call_kwargs["json"]["new_morphology_id"] == "new"

    @pytest.mark.asyncio
    async def test_rename_morphology_http_error(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "not found"
        mock_client._client.put.return_value = mock_response

        result = await mock_client.rename_morphology("missing", "new_name")

        assert result["success"] is False
        assert "HTTP 404" in result["error"]

    @pytest.mark.asyncio
    async def test_server_rename_morphology_tool(self, monkeypatch):
        from feagi_mcp import server

        async def fake_rename(old_id: str, new_id: str):
            return {
                "status": "success",
                "old_morphology_id": old_id,
                "new_morphology_id": new_id,
            }

        monkeypatch.setattr(server.feagi, "rename_morphology", fake_rename)

        result = await server.rename_morphology("x", "y")

        assert result["new_morphology_id"] == "y"


class TestBuildReflexMappingDelayValidation:
    """Gap 1: a zero axonal delay is rejected before any morphology is created."""

    @pytest.mark.asyncio
    async def test_zero_delay_rejected_without_creating_morphology(self, mock_client):
        mock_client.create_morphology = AsyncMock()
        mock_client.update_cortical_mapping = AsyncMock()

        result = await mock_client.build_reflex_mapping(
            src_area_id="aWNudAEAAAA=",
            dst_area_id="b2NudAEAAAA=",
            morphology_name="reflex",
            voxel_mappings=[{"src": [0, 0, 0], "dst": [0, 0, 0]}],
            postsynaptic_current_multiplier=50,
            synaptic_delay_bursts=0,
        )

        assert "error" in result
        assert "synaptic_delay_bursts must be >= 1" in result["error"]
        mock_client.create_morphology.assert_not_awaited()
        mock_client.update_cortical_mapping.assert_not_awaited()


class TestCreateCorticalAreaPlacement:
    """Gap 3: requested vs actual placement is surfaced, not silently discarded."""

    @pytest.mark.asyncio
    async def test_relocation_reported(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "cortical_id": "aWNudAEAAAA=",
            "areas": [{"cortical_id": "aWNudAEAAAA=", "coordinates_3d": [160, 0, -30]}],
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.create_cortical_area(
            name="Iris_Count_Input",
            cortical_type="IPU",
            dimensions=[3, 1, 10],
            position=[50, 0, 0],
            cortical_id="icnt",
            data_type_configs_by_subunit={"0": 1},
            per_device_dimensions=[3, 1, 10],
        )

        assert result["placement"]["requested"] == [50, 0, 0]
        assert result["placement"]["actual"] == [160, 0, -30]
        assert result["placement"]["relocated"] is True


class TestCreateIoAreaForUnit:
    """Gap 2: the canonical id is derived and verified against the server-assigned id."""

    @pytest.mark.asyncio
    async def test_computes_and_verifies_count_input_id(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "cortical_id": "aWNudAEAAAA=",
            "areas": [{"cortical_id": "aWNudAEAAAA=", "coordinates_3d": [160, 0, -30]}],
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.create_io_area_for_unit(
            name="Iris_Count_Input",
            subtype="icnt",
            channels=3,
            depth=10,
        )

        assert result["computed_cortical_id"] == "aWNudAEAAAA="
        assert result["assigned_cortical_id"] == "aWNudAEAAAA="
        assert result["verified"] is True
        assert result["config_flag"] == 1
        assert result["cortical_type"] == "IPU"

    @pytest.mark.asyncio
    async def test_invalid_subtype_does_not_create(self, mock_client):
        mock_client._client.post = AsyncMock()
        result = await mock_client.create_io_area_for_unit(
            name="bad",
            subtype="nope_too_long",
            channels=3,
            depth=10,
        )
        assert result["error"] == "invalid_io_cortical_id"
        mock_client._client.post.assert_not_awaited()


class TestProbeAreaResponse:
    """Gap 4: stimulate-then-observe detects whether a connection drives the target."""

    @pytest.mark.asyncio
    async def test_detects_response_from_fire_count_increase(self, mock_client):
        mock_client.monitor_activity = AsyncMock(
            side_effect=[
                {"lifetime_stats": {"max_consecutive_fire_count": 0}},
                {"lifetime_stats": {"max_consecutive_fire_count": 4}},
            ]
        )
        mock_client.stimulate_area_batch = AsyncMock(return_value={"success": True})

        result = await mock_client.probe_area_response(
            stimulus_area="aWNudAEAAAA=",
            stimulus_voxels=[[0, 0, 9]],
            observe_area="b2NudAEAAAA=",
            settle_ms=1,
        )

        assert result["responded"] is True
        assert result["delta_max_consecutive_fire_count"] == 4

    @pytest.mark.asyncio
    async def test_no_response_when_counter_unchanged(self, mock_client):
        mock_client.monitor_activity = AsyncMock(
            side_effect=[
                {"lifetime_stats": {"max_consecutive_fire_count": 2}},
                {"lifetime_stats": {"max_consecutive_fire_count": 2}},
            ]
        )
        mock_client.stimulate_area_batch = AsyncMock(return_value={"success": True})

        result = await mock_client.probe_area_response(
            stimulus_area="aWNudAEAAAA=",
            stimulus_voxels=[[0, 0, 9]],
            observe_area="b2NudAEAAAA=",
            settle_ms=1,
        )

        assert result["responded"] is False
        assert result["delta_max_consecutive_fire_count"] == 0

    @pytest.mark.asyncio
    async def test_stimulation_failure_short_circuits(self, mock_client):
        mock_client.monitor_activity = AsyncMock(
            return_value={"lifetime_stats": {"max_consecutive_fire_count": 0}}
        )
        mock_client.stimulate_area_batch = AsyncMock(
            return_value={"success": False, "error": "HTTP 400"}
        )

        result = await mock_client.probe_area_response(
            stimulus_area="aWNudAEAAAA=",
            stimulus_voxels=[[0, 0, 9]],
            observe_area="b2NudAEAAAA=",
            settle_ms=1,
        )

        assert result["error"] == "stimulation_failed"
