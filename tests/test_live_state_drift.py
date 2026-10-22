"""Tests for check_live_state_drift against fake genome, connectome, burst and agent payloads."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from feagi_mcp.live_state_drift import (
    agent_finding,
    blueprint_dimensions,
    burst_rate_finding,
    compare_live_state,
    dimension_findings,
    gather_live_state_drift,
    ipu_width_findings,
    sensor_columns,
)

IMU = "aXJpbQcABQA="
MOTOR = "Y01vdG9yX/A="
AGENT = "WKpe025ldXJhdmlsbGUAAAAAAAAAAAAAc2NlbmUAAAAAAAAAAAAAAAAAAAABAAAA"


def _blueprint(dims: dict[str, list[int]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cid, (x, y, z) in dims.items():
        out[f"_____10c-{cid}-cx-___bbx-i"] = x
        out[f"_____10c-{cid}-cx-___bby-i"] = y
        out[f"_____10c-{cid}-cx-___bbz-i"] = z
        out[f"_____10c-{cid}-cx-__name-t"] = "name"
    return out


def _live(dims: dict[str, list[int]]) -> dict[str, dict[str, Any]]:
    return {
        cid: {"cortical_dimensions": d, "cortical_name": f"n-{cid[:3]}"} for cid, d in dims.items()
    }


def _snapshot(columns: dict[str, int]) -> dict[str, Any]:
    return {
        "areas": [
            {
                "cortical_id": cid,
                "samples": [{"x": x, "y": 0, "z": 4, "potential": 1.0} for x in range(n)],
            }
            for cid, n in columns.items()
        ]
    }


def test_blueprint_dimensions_parses_flat_keys_with_slashes_in_ids() -> None:
    dims = blueprint_dimensions(_blueprint({MOTOR: [5, 1, 2], IMU: [6, 1, 10]}))
    assert dims == {MOTOR: [5, 1, 2], IMU: [6, 1, 10]}


def test_dimension_findings_name_restore_call() -> None:
    findings = dimension_findings(
        _live({IMU: [8, 1, 10], MOTOR: [5, 1, 2]}), _blueprint({IMU: [6, 1, 10], MOTOR: [5, 1, 2]})
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding["cortical_id"] == IMU
    assert finding["live"] == [8, 1, 10]
    assert finding["genome"] == [6, 1, 10]
    assert finding["restore"]["tool"] == "update_cortical_area"
    assert finding["restore"]["args"]["updates"] == {"cortical_dimensions": [8, 1, 10]}


def test_sensor_columns_and_ipu_width_findings() -> None:
    snapshot = _snapshot({IMU: 8})
    assert sensor_columns(snapshot) == {IMU: 8}
    findings, table = ipu_width_findings(_live({IMU: [6, 1, 10]}), snapshot)
    assert table == {IMU: {"width": 6, "columns_in_snapshot": 8}}
    assert findings[0]["check"] == "ipu_width"
    assert findings[0]["restore"]["args"]["updates"] == {"cortical_dimensions": [8, 1, 10]}
    assert ipu_width_findings(_live({IMU: [8, 1, 10]}), snapshot)[0] == []


def test_burst_rate_finding_only_outside_tolerance() -> None:
    assert burst_rate_finding({"burst_frequency_hz": 40.0}, 0.025) is None
    assert burst_rate_finding({"burst_frequency_hz": 40.2}, 0.025) is None
    finding = burst_rate_finding({"burst_frequency_hz": 10.0}, 0.025)
    assert finding is not None
    assert finding["live_hz"] == 10.0
    assert finding["genome_hz"] == 40.0
    assert finding["restore"] == {
        "tool": "set_burst_engine_frequency",
        "args": {"frequency_hz": 40.0},
    }
    assert burst_rate_finding({}, 0.025) is None
    assert burst_rate_finding({"burst_frequency_hz": 40.0}, None) is None


def test_agent_finding_states() -> None:
    assert agent_finding({"found": True, "agent_id": AGENT}, [AGENT, "other"]) is None
    missing = agent_finding(
        {"found": True, "agent_id": AGENT, "controller_id": "mujoco"}, ["other"]
    )
    assert missing is not None
    assert missing["descriptor_agent_id"] == AGENT
    assert missing["restore"]["tool"] is None
    assert (
        agent_finding({"found": False, "controller_id": "mujoco"}, [])["descriptor_agent_id"]
        is None
    )
    assert "cannot verify" in agent_finding({"found": True}, [])["message"]


def test_compare_live_state_reports_all_checks() -> None:
    result = compare_live_state(
        live_areas=_live({IMU: [6, 1, 10], MOTOR: [5, 1, 2]}),
        blueprint=_blueprint({IMU: [6, 1, 10], MOTOR: [5, 1, 2]}),
        burst_config={"burst_frequency_hz": 40.0},
        simulation_timestep=0.025,
        descriptor={"found": True, "agent_id": AGENT},
        registered_agent_ids=[AGENT],
        sensor_snapshot=_snapshot({IMU: 6}),
    )
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["checked"]["areas_compared"] == 2
    assert result["checked"]["ipu_columns"] == {IMU: {"width": 6, "columns_in_snapshot": 6}}


async def test_gather_live_state_drift_uses_client_and_reports_fetch_errors() -> None:
    client = AsyncMock()
    client.download_genome.return_value = {"blueprint": _blueprint({IMU: [6, 1, 10]})}
    client.list_cortical_areas_detailed.return_value = _live({IMU: [8, 1, 10]})
    client.get_burst_engine_config.return_value = {"burst_frequency_hz": 20.0}
    client.health_check.return_value = {"simulation_timestep": 0.025}
    client.get_registered_agents.return_value = {"agent_ids": ["other"]}
    client.embodiment_discover_introspection_endpoint.return_value = {
        "found": True,
        "controller_id": "mujoco",
        "agent_id": AGENT,
    }
    client.get_sensor_snapshot_last.return_value = {"error": "HTTP 500"}
    result = await gather_live_state_drift(client, controller_id="mujoco")
    checks = sorted(f["check"] for f in result["findings"])
    assert checks == ["agent_registration", "burst_frequency", "cortical_dimensions"]
    assert result["fetch_errors"] == {"sensor_snapshot": {"error": "HTTP 500"}}
    client.embodiment_discover_introspection_endpoint.assert_awaited_once_with("mujoco")
    client.get_sensor_snapshot_last.assert_awaited_once_with(summary_only=False)
