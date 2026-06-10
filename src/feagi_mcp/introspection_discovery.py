"""Out-of-process discovery for controller introspection HTTP endpoints.

Some FEAGI controllers (currently MuJoCo) expose a small HTTP server for
ground-truth state introspection. The desktop launcher allocates an ephemeral
port at spawn time and writes a JSON descriptor to a well-known location:

    <runtime_root>/controllers/.introspection/<controller_id>.json

This module locates that descriptor without invoking any FEAGI/desktop
internals so the FEAGI MCP can be used from arbitrary host environments
(packaging, CI, remote shells).

Lookup precedence for the runtime root:

1. ``FEAGI_RUNTIME_ROOT`` environment variable, if set and non-empty.
2. ``~/.feagi-staging`` (matches feagi-desktop's non-production builds).
3. ``~/.feagi`` (matches feagi-desktop's production builds).

The first directory that actually contains a matching descriptor wins. If
none are present, the lookup returns ``None`` so callers can fall back to
explicit ``introspection_url`` arguments.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors `INTROSPECTION_SCHEMA_VERSION` in
# feagi-desktop/src-tauri/src/controllers/introspection.rs
SUPPORTED_INTROSPECTION_SCHEMA_MAJOR = 1

# Subdirectory layout inside <runtime_root> (must mirror the Rust writer).
INTROSPECTION_SUBDIR = ".introspection"

# Conservative controller-id charset matching the Rust sanitizer.
_CONTROLLER_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class IntrospectionEndpoint:
    """Parsed introspection descriptor.

    Mirrors the Rust ``IntrospectionEndpoint`` struct field-for-field. Use
    :py:meth:`as_dict` for serialization back over the MCP wire (we don't
    want to leak ``dataclass`` artifacts into the protocol payload).
    """

    schema_version: str
    controller_id: str
    host: str
    port: int
    url: str
    pid: int
    controller_version: str | None
    started_at: str
    descriptor_path: str

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON/MCP transport."""
        return asdict(self)


def _sanitize_controller_id(controller_id: str) -> str:
    """Reject path-traversal / separator characters; mirrors Rust sanitizer.

    Raises ``ValueError`` so callers always see a deterministic failure mode
    rather than an opaque "file not found" later on.
    """
    if not controller_id:
        raise ValueError("controller_id must be non-empty")
    if controller_id.startswith("."):
        raise ValueError(f"controller_id must not start with '.': {controller_id!r}")
    if not _CONTROLLER_ID_RE.match(controller_id):
        raise ValueError(f"controller_id contains unsafe characters: {controller_id!r}")
    return controller_id


def _candidate_runtime_roots(env_override: str | None = None) -> list[Path]:
    """Return candidate runtime roots in lookup order.

    Honors ``FEAGI_RUNTIME_ROOT`` first (overriding all defaults), then the
    staging and production conventions used by feagi-desktop.
    """
    candidates: list[Path] = []
    override = env_override if env_override is not None else os.environ.get("FEAGI_RUNTIME_ROOT")
    if override:
        override_path = Path(override).expanduser()
        if override_path.as_posix().strip():
            candidates.append(override_path)
    home = Path.home()
    # Staging first because that's what active development uses; production
    # builds are usually installed only on end-user machines.
    candidates.append(home / ".feagi-staging")
    candidates.append(home / ".feagi")
    return candidates


def _descriptor_path(root: Path, controller_id: str) -> Path:
    return root / "controllers" / INTROSPECTION_SUBDIR / f"{controller_id}.json"


def _load_descriptor(path: Path) -> IntrospectionEndpoint | None:
    """Read a descriptor; return ``None`` for missing or malformed files.

    A malformed file is logged and treated as missing so a corrupt cache from
    an aborted launcher can never break discovery.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("introspection: cannot read %s: %s", path, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("introspection: malformed descriptor %s: %s", path, exc)
        return None

    schema_version = str(data.get("schema_version", ""))
    major = _parse_schema_major(schema_version)
    if major is None or major != SUPPORTED_INTROSPECTION_SCHEMA_MAJOR:
        logger.warning(
            "introspection: unsupported schema_version=%r in %s (expected major=%d)",
            schema_version,
            path,
            SUPPORTED_INTROSPECTION_SCHEMA_MAJOR,
        )
        return None

    try:
        return IntrospectionEndpoint(
            schema_version=schema_version,
            controller_id=str(data["controller_id"]),
            host=str(data["host"]),
            port=int(data["port"]),
            url=str(data["url"]),
            pid=int(data["pid"]),
            controller_version=(
                str(data["controller_version"])
                if data.get("controller_version") is not None
                else None
            ),
            started_at=str(data["started_at"]),
            descriptor_path=str(path),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "introspection: descriptor missing required fields (%s): %s",
            path,
            exc,
        )
        return None


def _parse_schema_major(schema_version: str) -> int | None:
    if not schema_version:
        return None
    head = schema_version.split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def discover_endpoint(
    controller_id: str,
    *,
    env_override: str | None = None,
) -> IntrospectionEndpoint | None:
    """Locate the introspection endpoint for a given controller id.

    Args:
        controller_id: e.g. ``"mujoco"``. Must match the id passed to the
            desktop launcher.
        env_override: Optional explicit runtime root override; primarily for
            tests. When ``None`` we read ``FEAGI_RUNTIME_ROOT`` from the
            process environment.

    Returns:
        The parsed descriptor, or ``None`` if no descriptor was found in any
        candidate root. ``ValueError`` is raised for unsafe ``controller_id``
        values (matching the Rust sanitizer).
    """
    safe_id = _sanitize_controller_id(controller_id)
    for root in _candidate_runtime_roots(env_override):
        path = _descriptor_path(root, safe_id)
        descriptor = _load_descriptor(path)
        if descriptor is not None:
            return descriptor
    return None


def discover_all_endpoints(
    *,
    env_override: str | None = None,
) -> list[IntrospectionEndpoint]:
    """Scan all runtime roots and return every valid introspection descriptor.

    Iterates over ``<root>/controllers/.introspection/*.json`` for each
    candidate root. Duplicate ``controller_id`` values across roots are
    resolved by first-match-wins (same precedence as :func:`discover_endpoint`).
    """
    seen: set[str] = set()
    results: list[IntrospectionEndpoint] = []
    for root in _candidate_runtime_roots(env_override):
        introspection_dir = root / "controllers" / INTROSPECTION_SUBDIR
        if not introspection_dir.is_dir():
            continue
        for child in sorted(introspection_dir.iterdir()):
            if child.suffix != ".json" or not child.is_file():
                continue
            controller_id = child.stem
            if controller_id in seen:
                continue
            descriptor = _load_descriptor(child)
            if descriptor is not None:
                seen.add(controller_id)
                results.append(descriptor)
    return results


def discover_endpoint_or_raise(
    controller_id: str,
    *,
    env_override: str | None = None,
) -> IntrospectionEndpoint:
    """Discovery variant that raises if no endpoint is found.

    Useful for code paths that want a hard failure mode rather than threading
    ``Optional`` through a chain of callers (e.g. MCP tool entry points).
    """
    found = discover_endpoint(controller_id, env_override=env_override)
    if found is None:
        roots = ", ".join(str(p) for p in _candidate_runtime_roots(env_override))
        raise FileNotFoundError(
            "No introspection descriptor found for controller "
            f"{controller_id!r}. Searched: {roots}. "
            "Ensure the controller was launched via feagi-desktop with "
            "introspection enabled, or pass an explicit introspection_url."
        )
    return found
