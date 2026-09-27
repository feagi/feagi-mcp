"""Live MuJoCo scene settings via the controller control server.

Posts the same actions the controller accepts at ``POST {control_url}/command``.
``control_url`` is an optional field on the introspection descriptor written
when the controller is launched. Saving those settings onto an experiment is
outside this package.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from feagi_mcp.introspection_discovery import discover_endpoint

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_READ_TIMEOUT_S = 5.0
_APPLY_TIMEOUT_S = 15.0
_APPLY_ACTIONS = frozenset(
    {
        "apply_scene_objects",
        "apply_scene_cameras",
        "apply_embodiment_attachments",
    }
)
LIVE_ACTIONS = frozenset(
    {
        "status",
        "set_cartesian_safety_boundary",
        "list_scene_objects",
        "apply_scene_objects",
        "list_scene_cameras",
        "apply_scene_cameras",
        "list_embodiment_bodies",
        "apply_embodiment_attachments",
        "get_simulation_rate",
        "get_environment_feedback",
        "set_environment_feedback",
    }
)
_READ_ACTIONS = (
    "status",
    "list_scene_objects",
    "list_scene_cameras",
    "list_embodiment_bodies",
    "get_environment_feedback",
    "get_simulation_rate",
)
_DEFAULT_RGBA = [0.2, 0.6, 1.0, 1.0]

Poster = Callable[[str, dict[str, Any], float], Awaitable[dict[str, Any]]]


def loopback_base_url(url: str) -> str:
    """Return a loopback HTTP base URL, or raise ValueError."""
    parsed = urlparse(url.strip())
    host = parsed.hostname
    if parsed.scheme != "http" or host not in _LOOPBACK_HOSTS or parsed.port is None:
        raise ValueError(f"MuJoCo control URL must be loopback http: {url!r}")
    return f"http://{host}:{parsed.port}"


def resolve_control_target(controller_id: str) -> dict[str, Any]:
    """Read the introspection descriptor for this controller's control server."""
    try:
        descriptor = discover_endpoint(controller_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "controller_id": controller_id}
    if descriptor is None or not descriptor.control_url:
        return {
            "ok": False,
            "error": "control_url_unavailable",
            "controller_id": controller_id,
            "message": (
                "This MuJoCo controller has no control-server URL in its "
                "introspection descriptor. Relaunch the controller so the "
                "descriptor includes control_url."
            ),
        }
    try:
        base = loopback_base_url(descriptor.control_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "controller_id": controller_id}
    return {
        "ok": True,
        "control_url": base,
        "controller_id": controller_id,
    }


class MujocoSceneControl:
    """HTTP client for one MuJoCo control server."""

    def __init__(self, *, poster: Poster | None = None) -> None:
        self._poster = poster

    async def command(
        self,
        action: str,
        body: dict[str, Any] | None = None,
        controller_id: str = "mujoco",
    ) -> dict[str, Any]:
        """Run one allowlisted settings action on the running controller."""
        if action not in LIVE_ACTIONS:
            return {
                "ok": False,
                "error": f"Unsupported MuJoCo scene action: {action!r}",
            }
        payload = {"action": action, **(body or {})}
        target = resolve_control_target(controller_id)
        if not target.get("ok"):
            return target
        timeout = _APPLY_TIMEOUT_S if action in _APPLY_ACTIONS else _READ_TIMEOUT_S
        try:
            response = await self._post(str(target["control_url"]), payload, timeout)
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            return {"ok": False, "error": str(exc), "action": action}
        if response.get("ok") is not True:
            return {
                "ok": False,
                "action": action,
                "error": response.get("error") or "MuJoCo control command failed.",
            }
        return {
            "ok": True,
            "action": action,
            "result": response.get("result"),
        }

    async def read_config(self, controller_id: str = "mujoco") -> dict[str, Any]:
        """Read every live MuJoCo settings section the control server exposes."""
        sections: dict[str, Any] = {}
        ok = True
        for action in _READ_ACTIONS:
            outcome = await self.command(action, controller_id=controller_id)
            sections[action] = outcome.get("result") if outcome.get("ok") else outcome
            ok = ok and bool(outcome.get("ok"))
        return {"ok": ok, "controller_id": controller_id, "sections": sections}

    async def add_scene_object(
        self,
        scene_object: dict[str, Any],
        controller_id: str = "mujoco",
    ) -> dict[str, Any]:
        """Append or replace one scene object, keeping every other object."""
        current = await self.command("list_scene_objects", controller_id=controller_id)
        if not current.get("ok"):
            return current
        listed = current.get("result") or {}
        objects = listed.get("objects")
        if not isinstance(objects, list):
            return {"ok": False, "error": "Scene object list was not returned."}
        object_id = scene_object.get("id")
        kept = [
            item for item in objects if not isinstance(item, dict) or item.get("id") != object_id
        ]
        kept.append(scene_object)
        return await self.command(
            "apply_scene_objects",
            {"objects": kept},
            controller_id=controller_id,
        )

    async def _post(
        self, control_url: str, payload: dict[str, Any], timeout_s: float
    ) -> dict[str, Any]:
        if self._poster is not None:
            return await self._poster(control_url, payload, timeout_s)
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(f"{control_url}/command", json=payload)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("MuJoCo control response must be a JSON object.")
        return body


def _friction_or_none(friction: list[float] | None) -> list[float] | None:
    """Validate MuJoCo ``[sliding, torsional, rolling]``, or ``None`` if omitted."""
    if friction is None:
        return None
    if len(friction) != 3:
        raise ValueError("friction must be [sliding, torsional, rolling].")
    parsed: list[float] = []
    for value in friction:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("friction values must be numbers.")
        number = float(value)
        if not math.isfinite(number) or number < 0.0:
            raise ValueError("friction values must be >= 0.")
        parsed.append(number)
    return parsed


def scene_object_payload(
    *,
    object_id: str,
    shape: str,
    size_mm: list[float],
    position_mm: list[float],
    dynamic: bool,
    mass_g: float | None = None,
    rgba: list[float] | None = None,
    friction: list[float] | None = None,
) -> dict[str, Any]:
    """Build one scene-object document in the control-server shape."""
    if shape not in ("sphere", "box", "capsule"):
        raise ValueError("shape must be sphere, box, or capsule.")
    if not object_id.strip():
        raise ValueError("id must be a non-empty string.")
    payload: dict[str, Any] = {
        "id": object_id.strip(),
        "shape": shape,
        "size_mm": size_mm,
        "position_mm": position_mm,
        "rgba": list(rgba) if rgba is not None else list(_DEFAULT_RGBA),
        "dynamic": dynamic,
    }
    if dynamic:
        if mass_g is None:
            raise ValueError("mass_g is required when dynamic is true.")
        payload["mass_g"] = mass_g
    elif mass_g is not None:
        payload["mass_g"] = mass_g
    parsed_friction = _friction_or_none(friction)
    if parsed_friction is not None:
        payload["friction"] = parsed_friction
    return payload
