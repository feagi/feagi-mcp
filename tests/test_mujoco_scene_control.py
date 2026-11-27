"""Tests for live MuJoCo scene settings commands."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from feagi_mcp.introspection_discovery import IntrospectionEndpoint
from feagi_mcp.mujoco_scene_control import (
    FENCE_STATUS_KEYS,
    MujocoSceneControl,
    fence_verdict,
    loopback_base_url,
    normalize_size_mm,
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


def test_short_size_lists_are_padded_to_three() -> None:
    assert normalize_size_mm("sphere", [20]) == [20, 20, 20]
    assert normalize_size_mm("capsule", [10, 40]) == [10, 40, 40]
    assert normalize_size_mm("box", [1, 2, 3]) == [1, 2, 3]
    assert normalize_size_mm("box", [1]) == [1], "the controller rejects bad box sizes itself"
    ball = scene_object_payload(
        object_id="ball", shape="sphere", size_mm=[20], position_mm=[0, 0, 0], dynamic=False
    )
    assert ball["size_mm"] == [20, 20, 20]


@pytest.mark.asyncio
async def test_apply_scene_objects_pads_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )
    posted: list[dict[str, Any]] = []

    async def poster(_url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        posted.append(payload)
        return {"ok": True, "result": {"applied": True}}

    body = {"objects": [{"id": "b", "shape": "sphere", "size_mm": [15], "position_mm": [0, 0, 0]}]}
    result = await MujocoSceneControl(poster=poster).command("apply_scene_objects", body)
    assert result["ok"] is True
    assert posted[0]["objects"][0]["size_mm"] == [15, 15, 15]
    assert body["objects"][0]["size_mm"] == [15], "the caller's body is not modified"


@pytest.mark.asyncio
async def test_controller_error_message_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 400 from the control server keeps its reason instead of the HTTP status line."""
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error": "size_mm must be a 3-element list."})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    result = await MujocoSceneControl().command("apply_scene_objects", {"objects": []})
    assert result == {
        "ok": False,
        "action": "apply_scene_objects",
        "error": "size_mm must be a 3-element list.",
    }


@pytest.mark.asyncio
async def test_non_json_http_errors_still_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    result = await MujocoSceneControl().command("list_scene_objects")
    assert result["ok"] is False
    assert "500" in result["error"]


@pytest.mark.asyncio
async def test_measure_bodies_posts_the_measure_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )
    seen: dict[str, Any] = {}

    async def poster(url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        seen.update(url=url, payload=payload)
        return {"ok": True, "result": {"bodies": {}, "contacts": [], "springs": {}}}

    contacts = [{"a_except": ["part"], "b": "world"}]
    result = await MujocoSceneControl(poster=poster).measure_bodies(["part"], contacts)
    assert result["ok"] is True and result["action"] == "measure"
    assert seen["url"] == "http://127.0.0.1:44000"
    assert seen["payload"] == {"action": "measure", "bodies": ["part"], "contacts": contacts}

    result = await MujocoSceneControl(poster=poster).measure_bodies(
        [], [], control_url="http://example.com:9"
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_reset_episode_posts_keyframe_or_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )
    seen: list[dict[str, Any]] = []

    async def poster(url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        seen.append({"url": url, "payload": payload})
        return {"ok": True, "result": {"episode_id": 3}}

    control = MujocoSceneControl(poster=poster)
    result = await control.reset_episode("stand")
    assert result == {"ok": True, "action": "reset_episode", "result": {"episode_id": 3}}
    assert seen[0]["url"] == "http://127.0.0.1:44000"
    assert seen[0]["payload"] == {"action": "reset_episode", "keyframe": "stand"}

    await control.reset_episode(None)
    await control.reset_episode("  ")
    assert seen[1]["payload"] == {"action": "reset_episode"}
    assert seen[2]["payload"] == {"action": "reset_episode"}

    bad = await control.reset_episode("home", control_url="http://example.com:9")
    assert bad["ok"] is False and len(seen) == 3


@pytest.mark.asyncio
async def test_reset_episode_reports_controller_errors_and_missing_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )

    async def rejecting(_url: str, _payload: dict[str, Any], _t: float) -> dict[str, Any]:
        return {"ok": False, "error": "Unknown keyframe 'nope'."}

    result = await MujocoSceneControl(poster=rejecting).reset_episode("nope")
    assert result["ok"] is False and "Unknown keyframe" in result["error"]

    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint", lambda _controller_id: None
    )
    result = await MujocoSceneControl(poster=rejecting).reset_episode("home")
    assert result["ok"] is False and result["error"] == "control_url_unavailable"


@pytest.mark.asyncio
async def test_read_config_omits_actions_the_controller_does_not_know(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )

    async def poster(_url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        if payload["action"] == "get_loop_timing":
            return {"ok": False, "error": "Unknown action: 'get_loop_timing'"}
        return {"ok": True, "result": {"action": payload["action"]}}

    result = await MujocoSceneControl(poster=poster).read_config()
    assert result["ok"] is True
    assert "get_loop_timing" not in result["sections"]
    assert result["absent_actions"] == ["get_loop_timing"]
    assert result["sections"]["status"] == {"action": "status"}


def _status(count: int, enabled: bool = True) -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "supported": True,
            "fence_enabled": enabled,
            "ee_pose_mm": [1, 2, 3],
            "fence_violation_mm": 0.0,
            "fence_violated": False,
            "fence_rejection_count": count,
            "last_rejection_at": 12.5 if count else None,
            "last_rejection_violation_mm": 7.25 if count else None,
            "workspace_min_mm": [0, 0, 0],
            "workspace_max_mm": [9, 9, 9],
            "boundary_frame": "world",
        },
    }


@pytest.mark.asyncio
async def test_fence_section_returns_only_fence_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("feagi_mcp.mujoco_scene_control.discover_endpoint", lambda _c: _endpoint())
    posted: list[str] = []

    async def poster(_url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        posted.append(payload["action"])
        return _status(2)

    out = await MujocoSceneControl(poster=poster).read_config(section="fence")
    assert posted == ["status"]
    assert set(out["fence"]) == set(FENCE_STATUS_KEYS)
    assert out["fence"]["fence_rejection_count"] == 2
    assert "boundary_frame" not in out["fence"]
    bad = await MujocoSceneControl(poster=poster).read_config(section="nope")
    assert bad["ok"] is False


def test_fence_verdict_reports_rejection_between_two_reads() -> None:
    def read(n: int) -> dict[str, Any]:
        return {"ok": True, "fence": _status(n)["result"]}

    verdict = fence_verdict(read(0), read(1), 0.5)
    assert verdict["checked"] and verdict["rejected"] is True
    assert verdict["violation_mm"] == 7.25
    same = fence_verdict(read(1), read(1), 0.5)
    assert same["checked"] and same["rejected"] is False
    off = fence_verdict(read(0), {"ok": True, "fence": _status(0, enabled=False)["result"]}, 0)
    assert off["checked"] is False
    down = fence_verdict({"ok": False, "error": "no controller"}, read(0), 0)
    assert down["checked"] is False and "no controller" in down["reason"]


@pytest.mark.asyncio
async def test_send_motor_command_fails_when_the_fence_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from feagi_mcp import server

    monkeypatch.setattr("feagi_mcp.mujoco_scene_control.discover_endpoint", lambda _c: _endpoint())
    counts = iter([0, 1])

    async def poster(_url: str, _payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        return _status(next(counts))

    def fake_poster_init(self: MujocoSceneControl, *, poster_fn: Any = poster) -> None:
        self._poster = poster_fn

    monkeypatch.setattr(MujocoSceneControl, "__init__", fake_poster_init)

    async def sent(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"success": True, "joint_name": "j1"}

    async def cfg() -> dict[str, Any]:
        return {"burst_interval_seconds": 0.001}

    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(server.feagi, "send_motor_command", sent)
    monkeypatch.setattr(server.feagi, "get_burst_engine_config", cfg)
    monkeypatch.setattr(server.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(server, "annotate_with_experiment_status", lambda r: r)
    out = await server.send_motor_command("agent", "j1", fraction=0.5)
    assert out["ok"] is False and out["success"] is False
    assert out["violation_mm"] == 7.25
    assert out["fence"]["rejected"] is True


@pytest.mark.asyncio
async def test_body_appearance_is_a_live_action_with_a_read_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "feagi_mcp.mujoco_scene_control.discover_endpoint",
        lambda _controller_id: _endpoint(),
    )
    posted: list[dict[str, Any]] = []

    async def poster(_url: str, payload: dict[str, Any], _timeout: float) -> dict[str, Any]:
        posted.append(payload)
        return {"ok": True, "result": {"action": payload["action"]}}

    client = MujocoSceneControl(poster=poster)
    overrides = [{"body_name": "part_a", "rgba": [1.0, 0.0, 0.0, 1.0]}]
    applied = await client.command("apply_body_appearance", {"overrides": overrides})
    assert applied["ok"] is True
    assert posted[-1] == {"action": "apply_body_appearance", "overrides": overrides}
    read = await client.read_config(section="list_body_appearance")
    assert read["sections"]["list_body_appearance"] == {"action": "list_body_appearance"}
