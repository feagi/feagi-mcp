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
        genome_file = tmp_path / "iris.genome.json"
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

        result = await server.load_genome_from_file(str(tmp_path / "missing.json"))

        assert result["success"] is False
        assert result["error"] == "file_not_found"
        assert called["uploaded"] is False

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error_without_uploading(self, monkeypatch, tmp_path):
        from feagi_mcp import server

        called = {"uploaded": False}

        async def fake_upload(_data):
            called["uploaded"] = True
            return {"success": True}

        monkeypatch.setattr(server.feagi, "upload_genome", fake_upload)

        bad_file = tmp_path / "bad.json"
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
