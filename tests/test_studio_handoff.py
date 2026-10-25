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
        asyncio.run(server.mcp.call_tool("health_check", {}))
    assert "neurorobotics-studio" in str(exc.value) and "`health_check`" in str(exc.value)
