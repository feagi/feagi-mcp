"""Tests for reading Studio's experiment run status file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from feagi_mcp.experiment_status import (
    EXPERIMENT_STATUS_FILE,
    STOPPED_WARNING,
    annotate_with_experiment_status,
    read_experiment_status,
)


def _write_status(root: Path, **fields: Any) -> None:
    data = {
        "schema_version": "1.0.0",
        "running": False,
        "experiment_id": None,
        "studio_pid": os.getpid(),
        "updated_at": "2026-10-21T21:00:00+00:00",
    }
    data.update(fields)
    (root / EXPERIMENT_STATUS_FILE).write_text(json.dumps(data), encoding="utf-8")


def test_running(tmp_path: Path) -> None:
    _write_status(tmp_path, running=True, experiment_id="ex-1", embodiment_id="microduck")
    status = read_experiment_status(env_override=str(tmp_path))
    assert status["state"] == "running"
    assert status["experiment_id"] == "ex-1"
    assert status["embodiment_id"] == "microduck"


def test_stopped_annotates_warning(tmp_path: Path) -> None:
    _write_status(tmp_path, running=False)
    payload = annotate_with_experiment_status({"time": 93.04}, env_override=str(tmp_path))
    assert payload["_experiment"]["state"] == "stopped"
    assert payload["_experiment_warning"] == STOPPED_WARNING
    assert payload["time"] == 93.04


def test_dead_studio_is_unknown(tmp_path: Path) -> None:
    _write_status(tmp_path, running=True, studio_pid=0)
    payload = annotate_with_experiment_status({}, env_override=str(tmp_path))
    assert payload["_experiment"]["state"] == "unknown"
    assert "_experiment_warning" not in payload


def test_missing_file_is_unknown(tmp_path: Path) -> None:
    assert read_experiment_status(env_override=str(tmp_path))["state"] == "unknown"


def test_unsupported_schema_is_ignored(tmp_path: Path) -> None:
    _write_status(tmp_path, running=True, schema_version="2.0.0")
    assert read_experiment_status(env_override=str(tmp_path))["state"] == "unknown"
