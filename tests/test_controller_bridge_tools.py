"""Tests for the new controller bridge, joint map, and motor command MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from feagi_mcp.feagi_client import FeagiClient, _summarize_registered_agents
from feagi_mcp.introspection_discovery import (
    INTROSPECTION_SUBDIR,
    discover_all_endpoints,
    match_descriptor_to_registered_agents,
)


def _write_descriptor(
    runtime_root: Path,
    controller_id: str,
    *,
    port: int = 9173,
    host: str = "127.0.0.1",
    pid: int = 4242,
    schema_version: str = "1.0.0",
    agent_id: str | None = None,
) -> Path:
    intro_dir = runtime_root / "controllers" / INTROSPECTION_SUBDIR
    intro_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "controller_id": controller_id,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "pid": pid,
        "controller_version": "1.0.0",
        "started_at": "2026-06-02T20:00:00Z",
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    path = intro_dir / f"{controller_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestDiscoverAllEndpoints:
    def test_finds_multiple_controllers(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", port=9001)
        _write_descriptor(tmp_path, "xarm", port=9002)
        eps = discover_all_endpoints(env_override=str(tmp_path))
        ids = {ep.controller_id for ep in eps}
        assert "mujoco" in ids
        assert "xarm" in ids
        assert len(eps) == 2

    def test_returns_empty_when_no_descriptors(self, tmp_path: Path) -> None:
        eps = discover_all_endpoints(env_override=str(tmp_path))
        assert eps == []

    def test_skips_malformed_descriptors(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", port=9001)
        intro_dir = tmp_path / "controllers" / INTROSPECTION_SUBDIR
        (intro_dir / "broken.json").write_text("not json", encoding="utf-8")
        eps = discover_all_endpoints(env_override=str(tmp_path))
        assert len(eps) == 1
        assert eps[0].controller_id == "mujoco"

    def test_loads_optional_agent_id(self, tmp_path: Path) -> None:
        agent_id = "VdjYtJL3hmvhOZCjhKB+Tke+ZWV31+GMB+Uf7331jzLdiMI5Wsdm9vy5BMb4OmnV"
        _write_descriptor(tmp_path, "mujoco", port=9001, agent_id=agent_id)
        eps = discover_all_endpoints(env_override=str(tmp_path))
        assert len(eps) == 1
        assert eps[0].agent_id == agent_id


class TestMatchDescriptorToRegisteredAgents:
    def test_exact_id_match(self) -> None:
        agent_id = "VdjYtJL3hmvhOZCjhKB+Tke+ZWV31+GMB+Uf7331jzLdiMI5Wsdm9vy5BMb4OmnV"
        assert match_descriptor_to_registered_agents(
            agent_id,
            [agent_id, "other"],
        ) == [agent_id]

    def test_missing_descriptor_id_does_not_match(self) -> None:
        assert match_descriptor_to_registered_agents(None, ["mujoco-agent"]) == []

    def test_does_not_substring_match_controller_id(self) -> None:
        assert (
            match_descriptor_to_registered_agents(
                None,
                ["xxmujocoxx"],
            )
            == []
        )
        assert (
            match_descriptor_to_registered_agents(
                "not-registered",
                ["xxmujocoxx"],
            )
            == []
        )


class TestSummarizeRegisteredAgents:
    def test_attaches_names_and_omits_device_registrations(self) -> None:
        agents, error = _summarize_registered_agents(
            ["id-a", "id-b"],
            {
                "id-a": {
                    "agent_name": "myosuite_scene_muscl",
                    "capabilities": {"motor": True, "device_registrations": {"x": 1}},
                },
                "id-b": {
                    "agent_name": "brain-visualizer",
                    "capabilities": {"visualization": True},
                },
            },
        )
        assert error is None
        assert agents[0]["agent_name"] == "myosuite_scene_muscl"
        assert agents[0]["capabilities"] == {"motor": True}
        assert agents[1]["agent_name"] == "brain-visualizer"

    def test_preserves_ids_when_capabilities_fail(self) -> None:
        agents, error = _summarize_registered_agents(
            ["id-a"],
            {"error": "request_failed", "message": "boom"},
        )
        assert error == "boom"
        assert agents == [{"agent_id": "id-a"}]


class TestListControllerBridges:
    @pytest.mark.asyncio
    async def test_combines_descriptors_and_agents(self, tmp_path: Path) -> None:
        mujoco_agent = "VdjYtJL3hmvhOZCjhKB+Tke+ZWV31+GMB+Uf7331jzLdiMI5Wsdm9vy5BMb4OmnV"
        xarm_agent = "xarm-exact-agent-id"
        _write_descriptor(tmp_path, "mujoco", port=9001, pid=100, agent_id=mujoco_agent)
        _write_descriptor(tmp_path, "xarm", port=9002, pid=200, agent_id=xarm_agent)
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            client.get_registered_agents = AsyncMock(
                return_value={
                    "agent_ids": [mujoco_agent, xarm_agent],
                    "count": 2,
                    "agents": [
                        {
                            "agent_id": mujoco_agent,
                            "agent_name": "myosuite_scene_muscl",
                        },
                        {"agent_id": xarm_agent, "agent_name": "xarm-bridge"},
                    ],
                }
            )
            result = await client.list_controller_bridges()
        assert result["total_descriptors"] == 2
        assert len(result["controllers"]) == 2
        mujoco = next(c for c in result["controllers"] if c["controller_id"] == "mujoco")
        assert mujoco["agent_registered"] is True
        assert mujoco["matching_agent_ids"] == [mujoco_agent]
        assert mujoco["matched_agent_name"] == "myosuite_scene_muscl"
        xarm = next(c for c in result["controllers"] if c["controller_id"] == "xarm")
        assert xarm["agent_registered"] is True

    @pytest.mark.asyncio
    async def test_does_not_substring_match_opaque_ids(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", port=9001)
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            client.get_registered_agents = AsyncMock(
                return_value={
                    "agent_ids": ["xxmujocoxx"],
                    "count": 1,
                    "agents": [{"agent_id": "xxmujocoxx", "agent_name": "unrelated"}],
                }
            )
            result = await client.list_controller_bridges()
        assert result["controllers"][0]["agent_registered"] is False
        assert result["controllers"][0]["matching_agent_ids"] == []
        assert result["registered_agents"][0]["agent_name"] == "unrelated"

    @pytest.mark.asyncio
    async def test_reports_unregistered_controller(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", port=9001)
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            client.get_registered_agents = AsyncMock(
                return_value={
                    "agent_ids": [],
                    "count": 0,
                    "agents": [],
                }
            )
            result = await client.list_controller_bridges()
        assert result["total_descriptors"] == 1
        assert result["controllers"][0]["agent_registered"] is False


class TestGetAgentJointMap:
    @pytest.mark.asyncio
    async def test_extracts_joints_from_device_registrations(self) -> None:
        client = FeagiClient()
        client.get_agent_device_registrations = AsyncMock(
            return_value={
                "agent_id": "xarm-bridge",
                "agent_name": "xarm-bridge",
                "capabilities": {},
                "device_registrations": {
                    "output_units": {
                        "ServoMotor": {
                            "0": {
                                "cortical_id": "o_sm_0",
                                "channels": {
                                    "0": {
                                        "custom_name": "joint_1",
                                        "control_mode": "absolute",
                                        "min_value": -180,
                                        "max_value": 180,
                                    },
                                    "1": {
                                        "custom_name": "joint_2",
                                        "control_mode": "absolute",
                                        "min_value": -120,
                                        "max_value": 120,
                                    },
                                },
                            },
                        },
                    },
                },
            }
        )
        result = await client.get_agent_joint_map("xarm-bridge")
        assert result["total_joints"] == 2
        assert result["opu_cortical_ids"] == ["o_sm_0"]
        names = [j["joint_name"] for j in result["joints"]]
        assert "joint_1" in names
        assert "joint_2" in names

    @pytest.mark.asyncio
    async def test_returns_error_when_agent_not_found(self) -> None:
        client = FeagiClient()
        client.get_agent_device_registrations = AsyncMock(
            return_value={
                "error": "Agent missing not found in capabilities",
            }
        )
        result = await client.get_agent_joint_map("missing")
        assert "error" in result


class TestSendMotorCommand:
    @pytest.mark.asyncio
    async def test_maps_joint_to_voxel_and_stimulates(self) -> None:
        client = FeagiClient()
        client.get_agent_device_registrations = AsyncMock(
            return_value={
                "agent_id": "xarm-bridge",
                "agent_name": "xarm-bridge",
                "capabilities": {},
                "device_registrations": {
                    "output_units": {
                        "ServoMotor": {
                            "0": {
                                "cortical_id": "o_sm_0",
                                "channels": {
                                    "0": {
                                        "custom_name": "joint_1",
                                        "control_mode": "absolute",
                                        "min_value": 0,
                                        "max_value": 180,
                                    },
                                },
                            },
                        },
                    },
                },
            }
        )
        client.get_cortical_area_geometry = AsyncMock(
            return_value={
                "o_sm_0": {
                    "cortical_dimensions_per_axis": {"x": 10, "y": 1, "z": 1},
                },
            }
        )
        client.stimulate_area = AsyncMock(
            return_value={
                "success": True,
                "neurons_stimulated": 1,
            }
        )
        result = await client.send_motor_command("xarm-bridge", "joint_1", 90.0)
        assert result["success"] is True
        assert result["joint_name"] == "joint_1"
        assert result["target_value"] == 90.0
        # 90/180 * 9 = 4.5 -> round to 4 (banker's rounding)
        assert result["voxel_coordinate"][0] == 4
        assert result["cortical_id"] == "o_sm_0"

    @pytest.mark.asyncio
    async def test_clamps_value_to_range(self) -> None:
        client = FeagiClient()
        client.get_agent_device_registrations = AsyncMock(
            return_value={
                "agent_id": "xarm",
                "agent_name": "xarm",
                "capabilities": {},
                "device_registrations": {
                    "output_units": {
                        "ServoMotor": {
                            "0": {
                                "cortical_id": "o_sm_0",
                                "channels": {
                                    "0": {
                                        "custom_name": "joint_1",
                                        "min_value": 0,
                                        "max_value": 180,
                                    },
                                },
                            },
                        },
                    },
                },
            }
        )
        client.get_cortical_area_geometry = AsyncMock(
            return_value={
                "o_sm_0": {"cortical_dimensions_per_axis": {"x": 10, "y": 1, "z": 1}},
            }
        )
        client.stimulate_area = AsyncMock(return_value={"success": True})
        result = await client.send_motor_command("xarm", "joint_1", 999.0)
        assert result["clamped_value"] == 180.0
        assert result["voxel_coordinate"][0] == 9  # max X

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_joint(self) -> None:
        client = FeagiClient()
        client.get_agent_device_registrations = AsyncMock(
            return_value={
                "agent_id": "xarm",
                "agent_name": "xarm",
                "capabilities": {},
                "device_registrations": {
                    "output_units": {
                        "ServoMotor": {
                            "0": {
                                "cortical_id": "o_sm_0",
                                "channels": {
                                    "0": {"custom_name": "joint_1"},
                                },
                            },
                        },
                    },
                },
            }
        )
        result = await client.send_motor_command("xarm", "nonexistent_joint", 45.0)
        assert "error" in result
        assert "available_joints" in result
        assert "joint_1" in result["available_joints"]

    @pytest.mark.asyncio
    async def test_matches_muscle_actuator_name(self) -> None:
        client = FeagiClient()
        client.get_agent_device_registrations = AsyncMock(
            return_value={
                "agent_id": "myo_agent",
                "device_registrations": {
                    "output_units_and_decoder_properties": {
                        "PositionalServo": [
                            [
                                {
                                    "cortical_unit_index": 0,
                                    "io_configuration_flags": {"frame_change_handling": "Absolute"},
                                    "device_grouping": [
                                        {
                                            "friendly_name": "IL_L1_l",
                                            "device_properties": {
                                                "joint_name": {
                                                    "type": "String",
                                                    "value": "",
                                                },
                                                "actuator_name": {
                                                    "type": "String",
                                                    "value": "IL_L1_l",
                                                },
                                                "source_entity": {
                                                    "type": "String",
                                                    "value": "IL_L1_l",
                                                },
                                            },
                                        }
                                    ],
                                },
                                {
                                    "PositionalServo": [
                                        {"value": 0.0},
                                        {"value": 1.0},
                                    ]
                                },
                            ]
                        ]
                    }
                },
            }
        )
        client.list_cortical_areas = AsyncMock(
            return_value=[
                {
                    "cortical_id": "o_sm_0",
                    "cortical_group": "OPU",
                    "cortical_subtype": "opse",
                    "unit_id": 0,
                    "subunit_id": 0,
                }
            ]
        )
        client.get_cortical_area_geometry = AsyncMock(
            return_value={
                "o_sm_0": {"cortical_dimensions_per_axis": {"x": 11, "y": 1, "z": 1}},
            }
        )
        client.stimulate_area = AsyncMock(return_value={"success": True})
        result = await client.send_motor_command("myo_agent", "IL_L1_l", 1.0)
        assert result["success"] is True
        assert result["cortical_id"] == "o_sm_0"
        assert result["clamped_value"] == 1.0
