"""On-disk genome snapshot manager.

Provides labeled save/restore of FEAGI genome artifacts. Each ``<label>.genome``
file contains a standard uploadable genome document. Snapshot-only annotations
are stored separately in ``<label>.snapshot.json``.

Persisting on disk lets debug sessions span MCP restarts without losing rollback
points. Snapshots only capture the genome blueprint - they do not include live
membrane potentials, synaptic weights, or any runtime neural state. Restoring a
snapshot uploads the decoded genome via ``POST /v1/genome/upload``.
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

from feagi_mcp.genome_artifact import decode_genome_artifact, encode_genome_artifact

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
        return self._directory / f"{clean}.genome"

    def _metadata_path_for(self, label: str) -> Path:
        """Resolve the sidecar metadata path for ``label``."""
        clean = validate_label(label)
        return self._directory / f"{clean}.snapshot.json"

    def list_snapshots(self) -> list[SnapshotInfo]:
        """Return metadata for every snapshot file in the directory."""
        snapshots: list[SnapshotInfo] = []
        for entry in sorted(self._directory.glob("*.genome")):
            label = entry.stem
            try:
                stat = entry.stat()
            except OSError as e:
                logger.warning("Cannot stat snapshot %s: %s", entry, e)
                continue
            metadata_path = self._metadata_path_for(label)
            try:
                with metadata_path.open("r", encoding="utf-8") as fp:
                    metadata = json.load(fp)
                if not isinstance(metadata, dict):
                    raise ValueError("snapshot metadata must be a JSON object")
                description = str(metadata["description"])
                created_at_ms = int(metadata["created_at_ms"])
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Cannot read snapshot metadata %s: %s", metadata_path, e)
                continue
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("Invalid snapshot metadata %s: %s", metadata_path, e)
                continue
            snapshots.append(
                SnapshotInfo(
                    label=label,
                    path=entry,
                    size_bytes=stat.st_size,
                    created_at_ms=created_at_ms,
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
            description: Optional free-form annotation stored in the metadata sidecar.
            overwrite: When False, raises ``FileExistsError`` if the label already
                exists. Set True to replace an existing snapshot.

        Returns:
            ``SnapshotInfo`` describing the persisted file.
        """
        if not isinstance(genome, dict):
            raise ValueError("genome must be a dict")
        path = self._path_for(label)
        metadata_path = self._metadata_path_for(label)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Snapshot '{label}' already exists at {path}")
        metadata: dict[str, Any] = {
            "label": validate_label(label),
            "description": description or "",
            "created_at_ms": int(time.time() * 1000),
        }
        artifact_temp_path = path.with_suffix(path.suffix + ".tmp")
        metadata_temp_path = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        artifact_temp_path.write_bytes(encode_genome_artifact(genome))
        with metadata_temp_path.open("w", encoding="utf-8") as fp:
            json.dump(metadata, fp, ensure_ascii=False)
        os.replace(metadata_temp_path, metadata_path)
        os.replace(artifact_temp_path, path)
        stat = path.stat()
        return SnapshotInfo(
            label=metadata["label"],
            path=path,
            size_bytes=stat.st_size,
            created_at_ms=metadata["created_at_ms"],
            description=metadata["description"],
        )

    def load(self, label: str) -> tuple[SnapshotInfo, dict[str, Any]]:
        """Load and parse a stored snapshot."""
        path = self._path_for(label)
        metadata_path = self._metadata_path_for(label)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot '{label}' not found at {path}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"Snapshot metadata '{label}' not found at {metadata_path}")
        genome = decode_genome_artifact(path.read_bytes())
        with metadata_path.open("r", encoding="utf-8") as fp:
            metadata = json.load(fp)
        if not isinstance(metadata, dict):
            raise ValueError(f"Snapshot metadata '{label}' must be a JSON object")
        stat = path.stat()
        info = SnapshotInfo(
            label=str(metadata["label"]),
            path=path,
            size_bytes=stat.st_size,
            created_at_ms=int(metadata["created_at_ms"]),
            description=str(metadata["description"]),
        )
        return info, genome

    def delete(self, label: str) -> bool:
        """Delete a stored snapshot. Returns True if a file was removed."""
        path = self._path_for(label)
        if not path.exists():
            return False
        path.unlink()
        self._metadata_path_for(label).unlink(missing_ok=True)
        return True
