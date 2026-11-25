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
        "get_loop_timing",
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
    "get_loop_timing",
)
# The controller's ``status`` fields that describe the Cartesian fence (compact read).
FENCE_STATUS_KEYS = (
    "supported",
    "fence_enabled",
    "ee_pose_mm",
    "fence_violation_mm",
    "fence_violated",
    "fence_rejection_count",
    "last_rejection_at",
    "last_rejection_violation_mm",
    "workspace_min_mm",
    "workspace_max_mm",
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


def fence_verdict(before: dict[str, Any], after: dict[str, Any], waited_s: float) -> dict[str, Any]:
    """Compare two :meth:`MujocoSceneControl.fence_status` reads taken around one command.

    Returns the ``fence`` block for a command result. ``rejected`` is true when the
    controller's ``fence_rejection_count`` grew; ``violation_mm`` is then its
    ``last_rejection_violation_mm``. ``checked`` is false when either read failed or the fence
    is off, with the reason.
    """
    block: dict[str, Any] = {"checked": False, "waited_s": round(waited_s, 3)}
    for name, read in (("before", before), ("after", after)):
        if not read.get("ok"):
            block["reason"] = f"fence status {name} the command unavailable: {read.get('error')}"
            return block
    fb, fa = before["fence"], after["fence"]
    if not fa.get("fence_enabled"):
        block["reason"] = "the controller's Cartesian fence is not enabled"
        return block
    n0, n1 = fb.get("fence_rejection_count"), fa.get("fence_rejection_count")
    if not (isinstance(n0, int) and isinstance(n1, int)):
        block["reason"] = "the controller reports no fence_rejection_count"
        return block
    block.update(
        checked=True,
        rejection_count_before=n0,
        rejection_count_after=n1,
        rejected=n1 > n0,
    )
    if n1 > n0:
        block["violation_mm"] = fa.get("last_rejection_violation_mm")
        block["last_rejection_at"] = fa.get("last_rejection_at")
    return block


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
        body = dict(body or {})
        if action == "apply_scene_objects" and isinstance(body.get("objects"), list):
            body["objects"] = [
                {**obj, "size_mm": normalize_size_mm(obj.get("shape"), obj["size_mm"])}
                if isinstance(obj, dict) and isinstance(obj.get("size_mm"), list)
                else obj
                for obj in body["objects"]
            ]
        payload = {"action": action, **body}
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

    async def measure_bodies(
        self,
        bodies: list[str],
        contacts: list[dict[str, Any]],
        controller_id: str = "mujoco",
        control_url: str | None = None,
    ) -> dict[str, Any]:
        """Run the controller's read-only physics ``measure`` primitive."""
        payload = {"action": "measure", "bodies": bodies, "contacts": contacts}
        if control_url:
            try:
                base = loopback_base_url(control_url)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        else:
            target = resolve_control_target(controller_id)
            if not target.get("ok"):
                return target
            base = str(target["control_url"])
        try:
            response = await self._post(base, payload, _READ_TIMEOUT_S)
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            return {"ok": False, "error": str(exc), "action": "measure"}
        if response.get("ok") is not True:
            return {
                "ok": False,
                "action": "measure",
                "error": response.get("error") or "MuJoCo measure failed.",
            }
        return {"ok": True, "action": "measure", "result": response.get("result")}

    async def reset_episode(
        self,
        keyframe: str | None = None,
        controller_id: str = "mujoco",
        control_url: str | None = None,
        timeout_s: float = _APPLY_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Run the controller's physics ``reset_episode`` primitive.

        Resets to the named keyframe, or to the model default when ``keyframe`` is
        ``None`` or blank. Clears body springs and pulses and starts a new episode.
        """
        if keyframe is not None and not isinstance(keyframe, str):
            return {"ok": False, "error": "keyframe must be a name (string) or omitted."}
        payload: dict[str, Any] = {"action": "reset_episode"}
        if keyframe is not None and keyframe.strip():
            payload["keyframe"] = keyframe.strip()
        if control_url:
            try:
                base = loopback_base_url(control_url)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        else:
            target = resolve_control_target(controller_id)
            if not target.get("ok"):
                return target
            base = str(target["control_url"])
        try:
            response = await self._post(base, payload, timeout_s)
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            return {"ok": False, "error": str(exc), "action": "reset_episode"}
        if response.get("ok") is not True:
            return {
                "ok": False,
                "action": "reset_episode",
                "error": response.get("error") or "MuJoCo reset_episode failed.",
            }
        return {"ok": True, "action": "reset_episode", "result": response.get("result")}

    async def fence_status(self, controller_id: str = "mujoco") -> dict[str, Any]:
        """Compact fence read: only :data:`FENCE_STATUS_KEYS` of the controller's ``status``."""
        outcome = await self.command("status", controller_id=controller_id)
        if not outcome.get("ok"):
            return outcome
        status = outcome.get("result")
        if not isinstance(status, dict):
            return {"ok": False, "error": "status returned no object", "action": "status"}
        return {
            "ok": True,
            "controller_id": controller_id,
            "fence": {k: status.get(k) for k in FENCE_STATUS_KEYS},
        }

    async def read_config(
        self, controller_id: str = "mujoco", section: str | None = None
    ) -> dict[str, Any]:
        """Read the live MuJoCo settings sections the control server exposes.

        ``section`` narrows the read: ``"fence"`` returns only the compact fence status
        (:meth:`fence_status`); a name from ``_READ_ACTIONS`` returns just that section.
        """
        if section == "fence":
            return await self.fence_status(controller_id)
        if section is not None and section not in _READ_ACTIONS:
            return {
                "ok": False,
                "error": f"unknown section {section!r}; use 'fence' or one of "
                f"{list(_READ_ACTIONS)}",
            }
        sections: dict[str, Any] = {}
        absent: list[str] = []
        ok = True
        for action in _READ_ACTIONS if section is None else (section,):
            outcome = await self.command(action, controller_id=controller_id)
            if not outcome.get("ok") and _is_unknown_action(outcome):
                # An older controller lacks this action: omit the section, note it.
                absent.append(action)
                continue
            sections[action] = outcome.get("result") if outcome.get("ok") else outcome
            ok = ok and bool(outcome.get("ok"))
        result: dict[str, Any] = {"ok": ok, "controller_id": controller_id, "sections": sections}
        if absent:
            result["absent_actions"] = absent
        return result

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
        # The control server answers errors (400 bad request, 502 failure) with
        # {"ok": false, "error": "..."}; keep that message instead of the status line.
        try:
            body = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if not isinstance(body, dict):
            response.raise_for_status()
            raise ValueError("MuJoCo control response must be a JSON object.")
        if response.is_error and body.get("ok") is not False:
            response.raise_for_status()
        return body


def _is_unknown_action(outcome: dict[str, Any]) -> bool:
    """True when the controller answered that it does not know the action."""
    return str(outcome.get("error") or "").startswith("Unknown action")


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


def normalize_size_mm(shape: Any, size_mm: list[Any]) -> list[Any]:
    """Pad a short ``size_mm`` to the three numbers the controller requires.

    A sphere uses only the radius and a capsule only radius and half-length, so
    ``[r]`` and ``[r, half_length]`` are accepted and padded. Anything else is
    returned unchanged for the controller to validate.
    """
    if shape == "sphere" and len(size_mm) == 1:
        return [size_mm[0]] * 3
    if shape == "capsule" and len(size_mm) == 2:
        return [size_mm[0], size_mm[1], size_mm[1]]
    return list(size_mm)


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
        "size_mm": normalize_size_mm(shape, size_mm),
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
