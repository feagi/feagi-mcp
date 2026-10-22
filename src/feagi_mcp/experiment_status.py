"""Neurorobotics Studio experiment run status, read from disk.

Studio keeps its run slot in memory, so it mirrors every change to:

    <runtime_root>/experiment_run_state.json

(written by ``feagi-desktop/src-tauri/src/controllers/experiment_status.rs``).
Without it, a stopped experiment and a frozen simulator look the same from
here: the controller's introspection server keeps answering with the last
physics state.

``state`` in the result is one of:

* ``running``: Studio is up and an experiment is running.
* ``stopped``: Studio is up and no experiment is running. Simulator state is
  stale and motor commands will not move the robot.
* ``unknown``: no status file, or the Studio that wrote it has exited.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from feagi_mcp.introspection_discovery import _candidate_runtime_roots

logger = logging.getLogger(__name__)

# Mirrors `EXPERIMENT_STATUS_SCHEMA_VERSION` in the Rust writer.
SUPPORTED_EXPERIMENT_STATUS_SCHEMA_MAJOR = 1

EXPERIMENT_STATUS_FILE = "experiment_run_state.json"

STOPPED_WARNING = (
    "The experiment is not running in Neurorobotics Studio. Simulator state is "
    "the last frame before it stopped and motor commands will not move the "
    "robot. Ask the user to run the experiment before testing on the robot."
)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_status_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("experiment status: cannot read %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    head = str(data.get("schema_version", "")).split(".", 1)[0]
    if head != str(SUPPORTED_EXPERIMENT_STATUS_SCHEMA_MAJOR):
        logger.warning("experiment status: unsupported schema in %s", path)
        return None
    return data


def read_experiment_status(*, env_override: str | None = None) -> dict[str, Any]:
    """Return Studio's experiment run status with a ``state`` verdict."""
    for root in _candidate_runtime_roots(env_override=env_override):
        path = root / EXPERIMENT_STATUS_FILE
        data = _read_status_file(path)
        if data is None:
            continue
        studio_pid = int(data.get("studio_pid") or 0)
        result: dict[str, Any] = {
            "experiment_id": data.get("experiment_id"),
            "embodiment_id": data.get("embodiment_id"),
            "embodiment_title": data.get("embodiment_title"),
            "updated_at": data.get("updated_at"),
            "status_path": str(path),
        }
        if not _pid_alive(studio_pid):
            result["state"] = "unknown"
            result["reason"] = "The Studio process that wrote this status has exited."
        else:
            result["state"] = "running" if data.get("running") is True else "stopped"
        return result
    return {
        "state": "unknown",
        "reason": "No experiment status file; Neurorobotics Studio may not be running.",
    }


def annotate_with_experiment_status(
    payload: dict[str, Any],
    *,
    env_override: str | None = None,
) -> dict[str, Any]:
    """Attach ``_experiment`` (and a warning when stopped) to a tool result."""
    status = read_experiment_status(env_override=env_override)
    payload["_experiment"] = status
    if status["state"] == "stopped":
        payload["_experiment_warning"] = STOPPED_WARNING
    return payload
