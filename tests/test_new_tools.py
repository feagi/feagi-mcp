"""Test new MCP tools for agent introspection and genome editing."""

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

        result = await mock_client.create_cortical_area(
            name="TestArea",
            cortical_type="CUSTOM",
            dimensions=[5, 5, 5],
            position=[0, 0, 0],
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

        result = await mock_client.update_cortical_area(
            "test_id", {"neuron_fire_threshold": 50.0}
        )

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

        result = await mock_client.update_cortical_mapping(
            "cHipFL", "opose1", mapping_rules
        )

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
            "file_path": "/tmp/out.json",
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.save_genome_to_filesystem(file_path="/tmp/out.json")

        assert result["file_path"] == "/tmp/out.json"
        mock_client._client.post.assert_called_once_with(
            "http://localhost:8000/v1/genome/save",
            json={"file_path": "/tmp/out.json"},
        )


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
