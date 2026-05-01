"""On-disk genome snapshot manager.

Provides labeled save/restore of FEAGI genome blueprints (the JSON document returned
by ``GET /v1/genome/download``). Snapshots are stored under ``var/snapshots/`` inside
the feagi-mcp project root by default, or under ``$FEAGI_MCP_SNAPSHOTS_DIR`` when set.

Persisting on disk lets debug sessions span MCP restarts without losing rollback
points. Snapshots only capture the genome blueprint - they do not include live
membrane potentials, synaptic weights, or any runtime neural state. Restoring a
snapshot uploads the saved JSON via ``POST /v1/genome/upload``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _resolve_default_dir() -> Path:
    """Resolve the default snapshots directory.

    Priority:
      1. ``FEAGI_MCP_SNAPSHOTS_DIR`` env var (absolute or relative to cwd).
      2. ``<feagi-mcp project root>/var/snapshots`` derived from this module path.
    """
    override = os.environ.get("FEAGI_MCP_SNAPSHOTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    module_path = Path(__file__).resolve()
    project_root = module_path.parent.parent.parent
    return (project_root / "var" / "snapshots").resolve()


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """Metadata for a stored genome snapshot."""

    label: str
    path: Path
    size_bytes: int
    created_at_ms: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "label": self.label,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "created_at_ms": self.created_at_ms,
            "description": self.description,
        }


def validate_label(label: str) -> str:
    """Normalize and validate a snapshot label.

    Labels must match ``[A-Za-z0-9_.-]{1,128}`` to keep them safe as filenames
    across operating systems. Raises ``ValueError`` for invalid labels.
    """
    if not isinstance(label, str):
        raise ValueError("label must be a string")
    trimmed = label.strip()
    if not _LABEL_PATTERN.match(trimmed):
        raise ValueError(f"label must match [A-Za-z0-9_.-] (1-128 chars); got: '{label}'")
    return trimmed


class SnapshotManager:
    """Manage on-disk genome snapshots keyed by human-readable label."""

    def __init__(self, directory: Path | str | None = None) -> None:
        """Initialize the manager and ensure the snapshot directory exists."""
        self._directory: Path = (
            _resolve_default_dir() if directory is None else Path(directory).expanduser().resolve()
        )
        self._directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        """Filesystem path where snapshots are stored."""
        return self._directory

    def _path_for(self, label: str) -> Path:
        """Resolve the filesystem path for ``label`` (after validation)."""
        clean = validate_label(label)
        return self._directory / f"{clean}.json"

    def list_snapshots(self) -> list[SnapshotInfo]:
        """Return metadata for every snapshot file in the directory."""
        snapshots: list[SnapshotInfo] = []
        for entry in sorted(self._directory.glob("*.json")):
            label = entry.stem
            try:
                stat = entry.stat()
            except OSError as e:
                logger.warning("Cannot stat snapshot %s: %s", entry, e)
                continue
            description = ""
            try:
                with entry.open("r", encoding="utf-8") as fp:
                    payload = json.load(fp)
                if isinstance(payload, dict):
                    raw_desc = payload.get("description")
                    if isinstance(raw_desc, str):
                        description = raw_desc
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Cannot read snapshot %s: %s", entry, e)
            snapshots.append(
                SnapshotInfo(
                    label=label,
                    path=entry,
                    size_bytes=stat.st_size,
                    created_at_ms=int(stat.st_mtime * 1000),
                    description=description,
                )
            )
        return snapshots

    def save(
        self,
        label: str,
        genome: dict[str, Any],
        description: str | None = None,
        overwrite: bool = False,
    ) -> SnapshotInfo:
        """Persist ``genome`` under ``label``.

        Args:
            label: Human-readable identifier (filename-safe).
            genome: JSON-serializable genome blueprint payload.
            description: Optional free-form annotation stored with the snapshot.
            overwrite: When False, raises ``FileExistsError`` if the label already
                exists. Set True to replace an existing snapshot.

        Returns:
            ``SnapshotInfo`` describing the persisted file.
        """
        if not isinstance(genome, dict):
            raise ValueError("genome must be a dict")
        path = self._path_for(label)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Snapshot '{label}' already exists at {path}")
        envelope: dict[str, Any] = {
            "label": validate_label(label),
            "description": description or "",
            "created_at_ms": int(time.time() * 1000),
            "genome": genome,
        }
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(envelope, fp, ensure_ascii=False)
        os.replace(tmp_path, path)
        stat = path.stat()
        return SnapshotInfo(
            label=envelope["label"],
            path=path,
            size_bytes=stat.st_size,
            created_at_ms=envelope["created_at_ms"],
            description=envelope["description"],
        )

    def load(self, label: str) -> tuple[SnapshotInfo, dict[str, Any]]:
        """Load and parse a stored snapshot."""
        path = self._path_for(label)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot '{label}' not found at {path}")
        with path.open("r", encoding="utf-8") as fp:
            envelope = json.load(fp)
        if not isinstance(envelope, dict):
            raise ValueError(f"Snapshot '{label}' is malformed (expected JSON object)")
        genome = envelope.get("genome")
        if not isinstance(genome, dict):
            raise ValueError(f"Snapshot '{label}' is missing 'genome' object")
        stat = path.stat()
        info = SnapshotInfo(
            label=str(envelope.get("label", label)),
            path=path,
            size_bytes=stat.st_size,
            created_at_ms=int(envelope.get("created_at_ms", int(stat.st_mtime * 1000))),
            description=str(envelope.get("description", "")),
        )
        return info, genome

    def delete(self, label: str) -> bool:
        """Delete a stored snapshot. Returns True if a file was removed."""
        path = self._path_for(label)
        if not path.exists():
            return False
        path.unlink()
        return True
