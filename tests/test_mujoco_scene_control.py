"""Tests for live MuJoCo scene settings commands."""

from __future__ import annotations

from typing import Any

import pytest

from feagi_mcp.introspection_discovery import IntrospectionEndpoint
from feagi_mcp.mujoco_scene_control import (
    MujocoSceneControl,
    loopback_base_url,
    scene_object_payload,
)


def _endpoint() -> IntrospectionEndpoint:
    return IntrospectionEndpoint(
        schema_version="1.0.0",
        controller_id="mujoco",
        host="127.0.0.1",
        port=9173,
        url="http://127.0.0.1:9173",
        pid=1,
        controller_version="1.0.122",
        started_at="2026-09-23T00:00:00Z",
        descriptor_path="/tmp/mujoco.json",
        control_url="http://127.0.0.1:44000",
    )


def test_loopback_base_url_rejects_non_loopback() -> None:
    with pytest.raises(ValueError):
        loopback_base_url("http://example.com:9")


def test_scene_object_accepts_friction() -> None:
    payload = scene_object_payload(
        object_id="ramp",
        shape="box",
        size_mm=[40, 20, 5],
        position_mm=[0, 0, 0],
        dynamic=False,
        friction=[0.2, 0.01, 0.0],
    )
    assert payload["friction"] == [0.2, 0.01, 0.0]


def test_scene_object_rejects_bad_friction() -> None:
    with pytest.raises(ValueError, match="friction"):
        scene_object_payload(
            object_id="ramp",
            shape="box",
            size_mm=[40, 20, 5],
            position_mm=[0, 0, 0],
            dynamic=False,
            friction=[-1.0, 0.0, 0.0],
        )


def test_scene_object_requires_mass_when_dynamic() -> None:
    with pytest.raises(ValueError):
        scene_object_payload(
            object_id="ball1",
            shape="sphere",
            size_mm=[50, 0, 0],
            position_mm=[100, 120, 100],
            dynamic=True,
        )


@pytest.mark.asyncio
async def test_add_scene_object_keeps_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )
    posted: list[dict[str, Any]] = []

    async def poster(_url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        posted.append(payload)
        if payload["action"] == "list_scene_objects":
            return {
                "ok": True,
                "result": {
                    "objects": [
                        {
                            "id": "kept",
                            "shape": "box",
                            "size_mm": [10, 10, 10],
                            "position_mm": [0, 0, 0],
                            "rgba": [1, 1, 1, 1],
                            "dynamic": False,
                            "mass_g": None,
                        }
                    ]
                },
            }
        return {"ok": True, "result": {"applied": True, "objects": payload["objects"]}}

    client = MujocoSceneControl(poster=poster)
    scene_object = scene_object_payload(
        object_id="ball1",
        shape="sphere",
        size_mm=[50, 0, 0],
        position_mm=[120, 140, 100],
        dynamic=True,
        mass_g=200,
    )
    result = await client.add_scene_object(scene_object)
    assert result["ok"] is True
    assert "persisted" not in result
    applied = posted[-1]
    assert applied["action"] == "apply_scene_objects"
    assert [item["id"] for item in applied["objects"]] == ["kept", "ball1"]
    assert applied["objects"][1]["mass_g"] == 200


@pytest.mark.asyncio
async def test_experiment_save_action_is_not_a_controller_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def poster(_url: str, _payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"ok": True, "result": {}}

    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )
    result = await MujocoSceneControl(poster=poster).command(
        "save_mujoco_general",
        {"loopRateSource": "model"},
    )
    assert result["ok"] is False
    assert called is False
