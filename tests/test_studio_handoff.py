"""Tests for the Neurorobotics Studio hand-off check."""

import asyncio
import json
import os

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from feagi_mcp import server
from feagi_mcp import studio_handoff as sh

TOKEN = "SECRET-TOKEN-123"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    for k in (sh.VIA_STUDIO_ENV, sh.ALLOW_DIRECT_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(sh.STUDIO_DIR_ENV, str(tmp_path))
    sh.clear_cache()
    yield
    sh.clear_cache()


def _write(tmp_path, **kw):
    data = {
        "endpoint": "http://127.0.0.1:9",
        "token": TOKEN,
        "pid": os.getpid(),
        "studio_version": "1",
    }
    data.update(kw)
    (tmp_path / "mcp.json").write_text(json.dumps(data))


def test_no_discovery_file():
    assert sh.studio_manages_feagi("localhost", 8000) is False


def test_stale_pid(tmp_path):
    _write(tmp_path, pid=2**22 + 12345, feagi_api="http://127.0.0.1:8000")
    assert sh.studio_manages_feagi("localhost", 8000) is False


def test_live_pid_matching_api(tmp_path):
    _write(tmp_path, feagi_api="http://127.0.0.1:8000")
    assert sh.studio_manages_feagi("localhost", 8000) is True


def test_live_pid_different_port(tmp_path):
    _write(tmp_path, feagi_api="http://127.0.0.1:8001")
    assert sh.studio_manages_feagi("localhost", 8000) is False


def test_missing_api_local_host(tmp_path):
    _write(tmp_path)
    assert sh.studio_manages_feagi("127.0.0.1", 8000) is True
    sh.clear_cache()
    assert sh.studio_manages_feagi("feagi.example.com", 8000) is False


def test_via_studio_env_skips(tmp_path, monkeypatch):
    _write(tmp_path, feagi_api="http://127.0.0.1:8000")
    monkeypatch.setenv(sh.VIA_STUDIO_ENV, "1")
    assert sh.studio_manages_feagi("localhost", 8000) is False


def test_allow_direct_env_skips(tmp_path, monkeypatch):
    _write(tmp_path, feagi_api="http://127.0.0.1:8000")
    monkeypatch.setenv(sh.ALLOW_DIRECT_ENV, "1")
    assert sh.studio_manages_feagi("localhost", 8000) is False


def test_token_never_in_message(tmp_path):
    _write(tmp_path, feagi_api="http://127.0.0.1:8000")
    assert sh.studio_manages_feagi("localhost", 8000) is True
    msg = sh.handoff_message("health_check")
    assert TOKEN not in msg and "`health_check`" in msg and "neurorobotics-studio" in msg


def test_server_call_path_returns_handoff_error(monkeypatch):
    monkeypatch.setattr(server, "studio_manages_feagi", lambda *_: True)
    with pytest.raises(ToolError) as exc:
        asyncio.run(server.mcp.call_tool("stimulate_area", {}))
    assert "neurorobotics-studio" in str(exc.value) and "`stimulate_area`" in str(exc.value)


def test_read_only_tool_passes_guard(monkeypatch):
    async def _ran(*_args):
        return "ran"

    monkeypatch.setattr(server.FastMCP, "call_tool", _ran)
    monkeypatch.setattr(server, "studio_manages_feagi", lambda *_: True)
    for name in ("embodiment_measure_bodies", "embodiment_get_physics_state", "health_check"):
        assert server.mcp._is_read_only(name), name
        assert asyncio.run(server.mcp.call_tool(name, {})) == "ran", name


def test_mutating_tools_not_read_only():
    for name in ("stimulate_area", "send_motor_command", "upload_genome", "pause_burst_engine"):
        assert not server.mcp._is_read_only(name), name


def test_snapshot_tools_hand_off_via_studio(monkeypatch, tmp_path):
    monkeypatch.setenv(sh.VIA_STUDIO_ENV, "1")
    monkeypatch.setattr(server.snapshot_manager, "_directory", tmp_path / "snaps")
    out = asyncio.run(server.snapshot_genome("x"))
    assert out["error"] == "use_studio_snapshot" and out["use_tool"] == "save_brain_snapshot"
    out = asyncio.run(server.restore_genome_snapshot("x"))
    assert out["use_tool"] == "restore_brain_snapshot"
    out = asyncio.run(server.list_genome_snapshots())
    assert out["use_tool"] == "list_brain_snapshots"
    assert not (tmp_path / "snaps").exists()


def test_snapshot_standalone_keeps_local_behavior(monkeypatch):
    out = asyncio.run(server.snapshot_genome("bad label!"))
    assert out.get("error") != "use_studio_snapshot"
    out = asyncio.run(server.list_genome_snapshots())
    assert "count" in out
