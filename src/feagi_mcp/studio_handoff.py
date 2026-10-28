"""Hand FEAGI tool calls off to Neurorobotics Studio when it is running.

When Studio runs and manages the same FEAGI, every AI-assistant call should go through
Studio's MCP server (activity log, approvals, genome snapshots). The standalone server
detects Studio via its discovery file and refuses with a hand-off message.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

VIA_STUDIO_ENV = "FEAGI_MCP_VIA_STUDIO"
ALLOW_DIRECT_ENV = "FEAGI_MCP_ALLOW_DIRECT"
STUDIO_DIR_ENV = "FEAGI_STUDIO_DIR"
CACHE_TTL_SECONDS = 2.0
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"}

_cache: dict[tuple[str, int], tuple[float, bool]] = {}


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _norm_host(host: str) -> str:
    h = (host or "").strip().lower().strip("[]")
    return "localhost" if h in {x.strip("[]") for x in _LOCAL_HOSTS} else h


def _discovery_paths() -> list[Path]:
    override = os.environ.get(STUDIO_DIR_ENV, "").strip()
    if override:
        return [Path(override).expanduser() / "mcp.json"]
    home = Path.home()
    return [home / ".feagi/studio/mcp.json", home / ".feagi-staging/studio/mcp.json"]


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False
    return True


def _same_feagi(feagi_api: Any, host: str, port: int) -> bool:
    if not feagi_api:
        return _norm_host(host) == "localhost"
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(str(feagi_api) if "//" in str(feagi_api) else f"//{feagi_api}")
        studio_host = parts.hostname or ""
        studio_port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    return _norm_host(studio_host) == _norm_host(host) and studio_port == int(port)


def studio_manages_feagi(host: str, port: int) -> bool:
    """True when a live Studio's discovery file points at the FEAGI at ``host:port``."""
    if _truthy(VIA_STUDIO_ENV) or _truthy(ALLOW_DIRECT_ENV):
        return False
    now = time.monotonic()
    key = (_norm_host(host), int(port))
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    result = False
    for path in _discovery_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not _pid_alive(data.get("pid")):
            continue
        if _same_feagi(data.get("feagi_api"), host, port):
            result = True
            break
    _cache[key] = (now, result)
    return result


def studio_present(host: str, port: int) -> bool:
    """True when running as Studio's in-process upstream or a live Studio manages this FEAGI."""
    return _truthy(VIA_STUDIO_ENV) or studio_manages_feagi(host, port)


def snapshot_handoff(use_tool: str) -> dict[str, str]:
    """Structured result for local snapshot tools when Studio owns snapshots."""
    return {
        "error": "use_studio_snapshot",
        "message": (
            "Neurorobotics Studio is present, so brain snapshots are saved through the "
            "experiment in Composer (genome + connectome, team-aware, synced) instead of "
            f"local files. Call `{use_tool}` on the `neurorobotics-studio` MCP server."
        ),
        "use_tool": use_tool,
    }


def handoff_message(tool: str) -> str:
    """Error text returned instead of running ``tool`` (never includes the token)."""
    return (
        "Neurorobotics Studio is running and manages this FEAGI, so FEAGI calls go through "
        "Studio, where they are logged, approved and snapshotted. Call "
        f"`{tool}` on the `neurorobotics-studio` MCP server instead (same name and arguments). "
        "If it is missing there, set this assistant's tool set to 'Everything' in "
        "Studio → Settings → AI assistants. To bypass, set FEAGI_MCP_ALLOW_DIRECT=1."
    )


def clear_cache() -> None:
    _cache.clear()
