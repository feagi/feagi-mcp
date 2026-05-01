"""Tests for the introspection descriptor discovery layer.

Covers both the standalone discovery module
(:mod:`feagi_mcp.introspection_discovery`) and its integration with
:class:`feagi_mcp.feagi_client.FeagiClient` so that
``embodiment_get_physics_state`` / ``embodiment_set_joint_state`` can resolve
the URL via descriptor lookup when one is not passed in explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.introspection_discovery import (
    INTROSPECTION_SUBDIR,
    SUPPORTED_INTROSPECTION_SCHEMA_MAJOR,
    discover_endpoint,
    discover_endpoint_or_raise,
)


def _write_descriptor(
    runtime_root: Path,
    controller_id: str,
    *,
    port: int = 9173,
    host: str = "127.0.0.1",
    pid: int = 4242,
    schema_version: str = "1.0.0",
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a descriptor mirroring the launcher's on-disk format."""
    intro_dir = runtime_root / "controllers" / INTROSPECTION_SUBDIR
    intro_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "controller_id": controller_id,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "pid": pid,
        "controller_version": "1.0.71",
        "started_at": "2026-04-25T16:00:00Z",
    }
    if extra:
        payload.update(extra)
    path = intro_dir / f"{controller_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _ok(payload: Any) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


class TestDiscoverEndpoint:
    def test_finds_descriptor_under_env_override(self, tmp_path: Path) -> None:
        path = _write_descriptor(tmp_path, "mujoco")
        ep = discover_endpoint("mujoco", env_override=str(tmp_path))
        assert ep is not None
        assert ep.controller_id == "mujoco"
        assert ep.url == "http://127.0.0.1:9173"
        assert ep.port == 9173
        assert ep.host == "127.0.0.1"
        assert ep.pid == 4242
        assert ep.controller_version == "1.0.71"
        assert ep.descriptor_path == str(path)
        assert ep.schema_version.startswith(f"{SUPPORTED_INTROSPECTION_SCHEMA_MAJOR}.")

    def test_returns_none_when_no_descriptor_present(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        ep = discover_endpoint("mujoco", env_override=str(empty_root))
        assert ep is None

    def test_returns_none_when_descriptor_is_malformed(self, tmp_path: Path) -> None:
        intro_dir = tmp_path / "controllers" / INTROSPECTION_SUBDIR
        intro_dir.mkdir(parents=True, exist_ok=True)
        (intro_dir / "mujoco.json").write_text("{ this is not valid json", encoding="utf-8")
        ep = discover_endpoint("mujoco", env_override=str(tmp_path))
        assert ep is None

    def test_returns_none_for_unsupported_schema_major(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", schema_version="2.0.0")
        ep = discover_endpoint("mujoco", env_override=str(tmp_path))
        assert ep is None

    def test_returns_none_when_required_fields_missing(self, tmp_path: Path) -> None:
        intro_dir = tmp_path / "controllers" / INTROSPECTION_SUBDIR
        intro_dir.mkdir(parents=True, exist_ok=True)
        (intro_dir / "mujoco.json").write_text(
            json.dumps({"schema_version": "1.0.0", "controller_id": "mujoco"}),
            encoding="utf-8",
        )
        ep = discover_endpoint("mujoco", env_override=str(tmp_path))
        assert ep is None

    def test_rejects_unsafe_controller_id(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            discover_endpoint("../escape", env_override=str(tmp_path))
        with pytest.raises(ValueError):
            discover_endpoint("foo/bar", env_override=str(tmp_path))
        with pytest.raises(ValueError):
            discover_endpoint(".hidden", env_override=str(tmp_path))
        with pytest.raises(ValueError):
            discover_endpoint("", env_override=str(tmp_path))

    def test_or_raise_variant_throws_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            discover_endpoint_or_raise("mujoco", env_override=str(tmp_path))

    def test_controller_version_optional(self, tmp_path: Path) -> None:
        _write_descriptor(
            tmp_path,
            "mujoco",
            extra={"controller_version": None},
        )
        ep = discover_endpoint("mujoco", env_override=str(tmp_path))
        assert ep is not None
        assert ep.controller_version is None


class TestEmbodimentAutoResolve:
    """Auto-discovery integration via FeagiClient."""

    @pytest.mark.asyncio
    async def test_get_physics_state_uses_descriptor_when_url_omitted(self, tmp_path: Path) -> None:
        descriptor_path = _write_descriptor(tmp_path, "mujoco", port=9555)
        client = FeagiClient()
        with (
            patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}),
            patch("feagi_mcp.feagi_client.httpx.AsyncClient") as ctor,
        ):
            inner = AsyncMock()
            inner.get.return_value = _ok({"time": 7.0})
            ctor.return_value.__aenter__.return_value = inner
            out = await client.embodiment_get_physics_state()
        assert out["time"] == 7.0
        assert out["_introspection_source"] == "auto-discovered"
        assert out["_descriptor_path"] == str(descriptor_path)
        inner.get.assert_awaited_once_with("http://127.0.0.1:9555/v1/state")

    @pytest.mark.asyncio
    async def test_get_physics_state_explicit_url_skips_discovery(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", port=9555)
        client = FeagiClient()
        with (
            patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}),
            patch("feagi_mcp.feagi_client.httpx.AsyncClient") as ctor,
        ):
            inner = AsyncMock()
            inner.get.return_value = _ok({"time": 1.0})
            ctor.return_value.__aenter__.return_value = inner
            out = await client.embodiment_get_physics_state(
                introspection_url="http://example.invalid:1234"
            )
        assert "_introspection_source" not in out
        inner.get.assert_awaited_once_with("http://example.invalid:1234/v1/state")

    @pytest.mark.asyncio
    async def test_get_physics_state_returns_error_when_no_url_and_no_descriptor(
        self, tmp_path: Path
    ) -> None:
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            out = await client.embodiment_get_physics_state(controller_id="mujoco-no-such-id")
        assert out["error"] == "introspection_url_unavailable"

    @pytest.mark.asyncio
    async def test_set_joint_state_uses_descriptor_when_url_omitted(self, tmp_path: Path) -> None:
        _write_descriptor(tmp_path, "mujoco", port=9777)
        client = FeagiClient()
        with (
            patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}),
            patch("feagi_mcp.feagi_client.httpx.AsyncClient") as ctor,
        ):
            inner = AsyncMock()
            inner.post.return_value = _ok({"status": "queued"})
            ctor.return_value.__aenter__.return_value = inner
            out = await client.embodiment_set_joint_state(joint_qpos={"hinge": 0.3})
        assert out["status"] == "queued"
        post_call = inner.post.await_args
        assert post_call.args[0] == "http://127.0.0.1:9777/v1/set_state"

    @pytest.mark.asyncio
    async def test_set_joint_state_returns_error_when_no_url_and_no_descriptor(
        self, tmp_path: Path
    ) -> None:
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            out = await client.embodiment_set_joint_state(
                joint_qpos={"hinge": 0.3},
                controller_id="mujoco-missing",
            )
        assert out["error"] == "introspection_url_unavailable"

    @pytest.mark.asyncio
    async def test_discover_tool_returns_full_metadata(self, tmp_path: Path) -> None:
        descriptor_path = _write_descriptor(tmp_path, "mujoco", port=9888, pid=12345)
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            payload = await client.embodiment_discover_introspection_endpoint("mujoco")
        assert payload["found"] is True
        assert payload["controller_id"] == "mujoco"
        assert payload["url"] == "http://127.0.0.1:9888"
        assert payload["port"] == 9888
        assert payload["host"] == "127.0.0.1"
        assert payload["pid"] == 12345
        assert payload["descriptor_path"] == str(descriptor_path)
        assert payload["controller_version"] == "1.0.71"
        assert payload["started_at"] == "2026-04-25T16:00:00Z"
        assert payload["schema_version"].startswith(f"{SUPPORTED_INTROSPECTION_SCHEMA_MAJOR}.")

    @pytest.mark.asyncio
    async def test_discover_tool_reports_not_found(self, tmp_path: Path) -> None:
        client = FeagiClient()
        with patch.dict("os.environ", {"FEAGI_RUNTIME_ROOT": str(tmp_path)}):
            payload = await client.embodiment_discover_introspection_endpoint("mujoco-missing")
        assert payload["found"] is False
        assert payload["controller_id"] == "mujoco-missing"
        assert "message" in payload

    @pytest.mark.asyncio
    async def test_discover_tool_reports_error_for_unsafe_id(self) -> None:
        client = FeagiClient()
        payload = await client.embodiment_discover_introspection_endpoint("../oops")
        assert payload["found"] is False
        assert "error" in payload
