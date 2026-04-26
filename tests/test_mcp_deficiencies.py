"""Tests for MCP deficiency gap-filler tools and on-disk snapshot manager.

Covers:
* Runtime tap clients (motor / sensor snapshot, log tail).
* Burst engine control wrappers (counter, frequency, control, hold/resume).
* Neuron / synapse runtime inspection clients.
* Capabilities and batched monitoring helpers.
* SnapshotManager save/load/list/delete and label validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.snapshots import SnapshotInfo, SnapshotManager, validate_label


@pytest.fixture
def mock_client() -> FeagiClient:
    """FeagiClient with a mocked HTTPX client."""
    client = FeagiClient()
    client._client = AsyncMock()
    return client


def _ok(json_payload):
    """Build a MagicMock that mimics a 200 httpx response."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = json_payload
    return response


class TestRuntimeTaps:
    @pytest.mark.asyncio
    async def test_get_motor_snapshot_last_passes_filter(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {
                "burst_num": 42,
                "timestamp_ms": 123,
                "has_data": True,
                "total_areas": 1,
                "total_neurons": 3,
                "areas": [],
                "agents": [],
            }
        )
        result = await mock_client.get_motor_snapshot_last(agent_id="mujoco-1")
        assert result["burst_num"] == 42
        call = mock_client._client.get.call_args
        assert call.kwargs["params"] == {"agent_id": "mujoco-1"}
        assert call.args[0].endswith("/v1/output/motor_snapshot/last")

    @pytest.mark.asyncio
    async def test_get_motor_snapshot_last_no_filter(self, mock_client):
        mock_client._client.get.return_value = _ok({"has_data": False})
        result = await mock_client.get_motor_snapshot_last()
        assert result == {"has_data": False}
        assert mock_client._client.get.call_args.kwargs["params"] is None

    @pytest.mark.asyncio
    async def test_get_sensor_snapshot_last_filter(self, mock_client):
        mock_client._client.get.return_value = _ok({"has_data": True, "areas": []})
        result = await mock_client.get_sensor_snapshot_last(cortical_id="aXN2bQEAAAM=")
        assert result["has_data"] is True
        params = mock_client._client.get.call_args.kwargs["params"]
        assert params == {"cortical_id": "aXN2bQEAAAM="}

    @pytest.mark.asyncio
    async def test_get_log_tail_builds_query(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {"enabled": True, "capacity": 2000, "records": [], "returned": 0}
        )
        result = await mock_client.get_log_tail(
            level="WARN",
            target_prefix="feagi_npu",
            since_ts_ms=100,
            limit=50,
        )
        assert result["enabled"] is True
        params = mock_client._client.get.call_args.kwargs["params"]
        assert params == {
            "level": "WARN",
            "target_prefix": "feagi_npu",
            "since_ts_ms": "100",
            "limit": "50",
        }

    @pytest.mark.asyncio
    async def test_get_log_tail_handles_disabled(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {"enabled": False, "capacity": 0, "records": [], "returned": 0}
        )
        result = await mock_client.get_log_tail()
        assert result == {
            "enabled": False,
            "capacity": 0,
            "records": [],
            "returned": 0,
        }


class TestBurstEngineControl:
    @pytest.mark.asyncio
    async def test_get_burst_counter_returns_int(self, mock_client):
        mock_client._client.get.return_value = _ok(12345)
        result = await mock_client.get_burst_counter()
        assert result == {"burst_counter": 12345}

    @pytest.mark.asyncio
    async def test_get_burst_engine_config(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {
                "burst_frequency_hz": 40.0,
                "burst_interval_seconds": 0.025,
                "is_running": True,
                "is_paused": False,
            }
        )
        result = await mock_client.get_burst_engine_config()
        assert result["burst_frequency_hz"] == 40.0
        assert result["is_running"] is True

    @pytest.mark.asyncio
    async def test_set_burst_engine_frequency(self, mock_client):
        mock_client._client.put.return_value = _ok({"burst_frequency_hz": 5.0})
        result = await mock_client.set_burst_engine_frequency(5.0)
        assert result["burst_frequency_hz"] == 5.0
        body = mock_client._client.put.call_args.kwargs["json"]
        assert body == {"burst_frequency_hz": 5.0}

    @pytest.mark.asyncio
    async def test_set_burst_engine_frequency_rejects_non_positive(self, mock_client):
        result = await mock_client.set_burst_engine_frequency(0)
        assert result.get("error")
        mock_client._client.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_control_burst_engine_action(self, mock_client):
        mock_client._client.post.return_value = _ok({"message": "Burst engine paused"})
        result = await mock_client.control_burst_engine("PAUSE")
        assert result["message"] == "Burst engine paused"
        body = mock_client._client.post.call_args.kwargs["json"]
        assert body == {"action": "pause"}

    @pytest.mark.asyncio
    async def test_control_burst_engine_rejects_invalid(self, mock_client):
        result = await mock_client.control_burst_engine("oops")
        assert result["error"] == "invalid_action"
        mock_client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_and_resume_burst_engine(self, mock_client):
        mock_client._client.post.return_value = _ok({"message": "Hold ack"})
        pause = await mock_client.pause_burst_engine()
        assert pause["message"] == "Hold ack"
        assert mock_client._client.post.call_args.args[0].endswith(
            "/v1/burst_engine/hold"
        )

        mock_client._client.post.return_value = _ok({"message": "Resumed"})
        resume = await mock_client.resume_burst_engine()
        assert resume["message"] == "Resumed"
        assert mock_client._client.post.call_args.args[0].endswith(
            "/v1/burst_engine/resume"
        )


class TestNeuronInspection:
    @pytest.mark.asyncio
    async def test_inspect_neuron_state_at(self, mock_client):
        mock_client._client.get.return_value = _ok(
            {"membrane_potential": 0.42, "fire_threshold": 1.0}
        )
        result = await mock_client.inspect_neuron_state_at("aXN2bQEAAAM=", 1, 2, 3)
        assert result["membrane_potential"] == 0.42
        params = mock_client._client.get.call_args.kwargs["params"]
        assert params == {"cortical_id": "aXN2bQEAAAM=", "x": "1", "y": "2", "z": "3"}

    @pytest.mark.asyncio
    async def test_get_neuron_state_by_id_validates(self, mock_client):
        result = await mock_client.get_neuron_state_by_id("   ")
        assert result["error"]
        mock_client._client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_voxel_neurons_with_pagination(self, mock_client):
        mock_client._client.get.return_value = _ok({"voxel_neurons": []})
        result = await mock_client.get_voxel_neurons("c", 0, 0, 0, synapse_page=2)
        assert result == {"voxel_neurons": []}
        params = mock_client._client.get.call_args.kwargs["params"]
        assert params["synapse_page"] == "2"
        assert params["x"] == "0"

    @pytest.mark.asyncio
    async def test_list_area_synapses_normalizes_list(self, mock_client):
        mock_client._client.get.return_value = _ok(
            [
                {"src_id": "a", "dst_id": "b", "weight": 0.1},
                {"src_id": "c", "dst_id": "d", "weight": 0.2},
            ]
        )
        result = await mock_client.list_area_synapses("aXN2bQEAAAM=")
        assert result["synapse_count"] == 2
        assert isinstance(result["synapses"], list)


class TestAgentAndMonitoring:
    @pytest.mark.asyncio
    async def test_list_agent_capabilities_all_includes_registrations(self, mock_client):
        mock_client._client.get.return_value = _ok({"agent_a": {"capabilities": {}}})
        result = await mock_client.list_agent_capabilities_all()
        assert "agent_a" in result
        params = mock_client._client.get.call_args.kwargs["params"]
        assert params["include_device_registrations"] == "true"

    @pytest.mark.asyncio
    async def test_monitor_activity_batch_fans_out(self, mock_client):
        mock_client.monitor_activity = AsyncMock(
            side_effect=[
                {"firing_rate": 1.0},
                {"firing_rate": 2.0},
            ]
        )
        result = await mock_client.monitor_activity_batch(
            ["area_a", "area_b"], duration_ms=200
        )
        assert result["area_count"] == 2
        assert result["results"]["area_a"] == {"firing_rate": 1.0}
        assert result["results"]["area_b"] == {"firing_rate": 2.0}
        assert mock_client.monitor_activity.await_count == 2

    @pytest.mark.asyncio
    async def test_monitor_activity_batch_empty(self, mock_client):
        result = await mock_client.monitor_activity_batch([])
        assert "error" in result


class TestMonitorActivityLifetimeStats:
    """Verify lifetime fire-count enrichment that disambiguates 'silent now'
    from 'never fired' (the cartpole-detector misdiagnosis case)."""

    def _build_url_dispatcher(self, *, area_id: str, neuron_props: dict[int, dict[str, Any]]):
        """Return a side_effect callable that maps URL -> response by pattern."""

        async def fake_get(url: str, params: dict[str, Any] | None = None):  # noqa: ARG001
            if "/v1/monitoring/cortical_activity" in url:
                return _ok(
                    {
                        "area_id": area_id,
                        "firing_statistics": {
                            "total_spikes": 0,
                            "firing_rate_hz": 0.0,
                            "active_neurons": [],
                        },
                        "spike_history": [],
                    }
                )
            if url.endswith(f"/v1/connectome/cortical_area/{area_id}/neurons"):
                return _ok(list(neuron_props.keys()))
            for nid, props in neuron_props.items():
                if url.endswith(f"/v1/connectome/neuron/{nid}/properties"):
                    return _ok(props)
            raise AssertionError(f"unexpected URL in test: {url}")

        return fake_get

    @pytest.mark.asyncio
    async def test_lifetime_stats_distinguishes_quiet_from_dead(self, mock_client):
        """A neuron that has fired 280x lifetime but is silent in this window
        must surface ``max_consecutive_fire_count=280`` so we don't misread
        the area as broken."""
        neuron_props = {
            295: {
                "neuron_id": 295,
                "x": 0,
                "y": 0,
                "z": 0,
                "consecutive_fire_count": 280,
                "membrane_potential": 0.0,
            }
        }
        mock_client._client.get.side_effect = self._build_url_dispatcher(
            area_id="Y3BsZWFzdTE=", neuron_props=neuron_props
        )
        result = await mock_client.monitor_activity("Y3BsZWFzdTE=", duration_ms=200)
        stats = result["lifetime_stats"]
        assert stats["total_neurons_in_area"] == 1
        assert stats["neurons_inspected"] == 1
        assert stats["lifetime_active_count"] == 1
        assert stats["max_consecutive_fire_count"] == 280
        assert stats["top_neurons"][0]["neuron_id"] == 295
        assert stats["top_neurons"][0]["consecutive_fire_count"] == 280

    @pytest.mark.asyncio
    async def test_lifetime_stats_truly_dead_area(self, mock_client):
        neuron_props = {
            1: {
                "neuron_id": 1,
                "x": 0,
                "y": 0,
                "z": 0,
                "consecutive_fire_count": 0,
                "membrane_potential": 0.0,
            }
        }
        mock_client._client.get.side_effect = self._build_url_dispatcher(
            area_id="dead_area", neuron_props=neuron_props
        )
        result = await mock_client.monitor_activity("dead_area")
        stats = result["lifetime_stats"]
        assert stats["lifetime_active_count"] == 0
        assert stats["max_consecutive_fire_count"] == 0
        assert stats["top_neurons"] == []

    @pytest.mark.asyncio
    async def test_lifetime_stats_disabled_skips_extra_calls(self, mock_client):
        """``include_lifetime_stats=False`` must not issue any neuron-list /
        per-neuron property calls."""
        urls_seen: list[str] = []

        async def fake_get(url: str, params: dict[str, Any] | None = None):  # noqa: ARG001
            urls_seen.append(url)
            return _ok(
                {
                    "area_id": "x",
                    "firing_statistics": {"total_spikes": 0, "active_neurons": []},
                    "spike_history": [],
                }
            )

        mock_client._client.get.side_effect = fake_get
        result = await mock_client.monitor_activity(
            "x", duration_ms=100, include_lifetime_stats=False
        )
        assert "lifetime_stats" not in result
        assert len(urls_seen) == 1
        assert "/v1/monitoring/cortical_activity" in urls_seen[0]

    @pytest.mark.asyncio
    async def test_lifetime_stats_respects_neuron_cap(self, mock_client):
        """With many neurons, ``lifetime_neuron_cap`` must limit fan-out."""
        neuron_props = {
            i: {
                "neuron_id": i,
                "x": 0,
                "y": 0,
                "z": i,
                "consecutive_fire_count": i,
                "membrane_potential": 0.0,
            }
            for i in range(10)
        }
        mock_client._client.get.side_effect = self._build_url_dispatcher(
            area_id="big", neuron_props=neuron_props
        )
        result = await mock_client.monitor_activity(
            "big", duration_ms=100, lifetime_neuron_cap=3
        )
        stats = result["lifetime_stats"]
        assert stats["total_neurons_in_area"] == 10
        assert stats["neurons_inspected"] == 3
        assert stats["max_consecutive_fire_count"] == 2

    @pytest.mark.asyncio
    async def test_lifetime_stats_failure_isolated_from_primary(self, mock_client):
        """If the lifetime-stats fan-out fails, the primary payload must still
        return cleanly with an ``error`` recorded under ``lifetime_stats``."""

        async def fake_get(url: str, params: dict[str, Any] | None = None):  # noqa: ARG001
            if "/v1/monitoring/cortical_activity" in url:
                return _ok(
                    {
                        "area_id": "a",
                        "firing_statistics": {"total_spikes": 0, "active_neurons": []},
                        "spike_history": [],
                    }
                )
            response = MagicMock()
            response.status_code = 500
            response.text = "boom"
            return response

        mock_client._client.get.side_effect = fake_get
        result = await mock_client.monitor_activity("a")
        assert result["firing_statistics"]["total_spikes"] == 0
        assert "error" in result["lifetime_stats"]


class TestSnapshotManager:
    def test_validate_label_accepts_valid(self):
        assert validate_label("baseline_v1") == "baseline_v1"
        assert validate_label("  trimmed.label-2  ") == "trimmed.label-2"

    @pytest.mark.parametrize(
        "label",
        ["", " ", "has space", "/etc/passwd", "../escape", "weird?char"],
    )
    def test_validate_label_rejects_invalid(self, label):
        with pytest.raises(ValueError):
            validate_label(label)

    def test_save_load_cycle(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        info = manager.save(
            "alpha",
            {"genome_title": "demo", "blueprint": {"a": 1}},
            description="first",
        )
        assert isinstance(info, SnapshotInfo)
        assert info.label == "alpha"
        assert info.path.exists()

        loaded_info, loaded_genome = manager.load("alpha")
        assert loaded_info.description == "first"
        assert loaded_genome == {"genome_title": "demo", "blueprint": {"a": 1}}

    def test_save_refuses_overwrite_by_default(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        manager.save("alpha", {"v": 1})
        with pytest.raises(FileExistsError):
            manager.save("alpha", {"v": 2})

    def test_save_overwrite_replaces_payload(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        manager.save("alpha", {"v": 1})
        manager.save("alpha", {"v": 2}, overwrite=True)
        _, genome = manager.load("alpha")
        assert genome == {"v": 2}

    def test_list_snapshots_returns_metadata(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        manager.save("first", {"k": 1}, description="one")
        manager.save("second", {"k": 2}, description="two")
        snapshots = manager.list_snapshots()
        labels = [s.label for s in snapshots]
        assert labels == ["first", "second"]
        descriptions = {s.label: s.description for s in snapshots}
        assert descriptions == {"first": "one", "second": "two"}

    def test_delete_returns_false_when_missing(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        assert manager.delete("ghost") is False

    def test_delete_removes_existing(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        manager.save("alpha", {"v": 1})
        assert manager.delete("alpha") is True
        with pytest.raises(FileNotFoundError):
            manager.load("alpha")

    def test_load_rejects_malformed_envelope(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        bad_path = tmp_path / "bad.json"
        bad_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError):
            manager.load("bad")

    def test_load_rejects_missing_genome_object(self, tmp_path: Path):
        manager = SnapshotManager(directory=tmp_path)
        bad_path = tmp_path / "bad.json"
        bad_path.write_text(json.dumps({"label": "bad"}), encoding="utf-8")
        with pytest.raises(ValueError):
            manager.load("bad")
