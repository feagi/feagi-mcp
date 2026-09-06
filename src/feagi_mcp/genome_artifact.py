"""Encoding boundary for external FEAGI genome artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

GENOME_ARTIFACT_EXTENSION = ".genome"
GENOME_ARTIFACT_MEDIA_TYPE = "application/vnd.feagi.genome+json"


class GenomeArtifactCodec(Protocol):
    """Convert external bytes without interpreting genome schema versions."""

    @property
    def media_type(self) -> str:
        """Return the media type emitted by this codec."""

    def decode(self, artifact: bytes) -> dict[str, Any]:
        """Decode artifact bytes into a schema-bearing genome dictionary."""

    def encode(self, genome: dict[str, Any]) -> bytes:
        """Encode a schema-bearing genome dictionary as artifact bytes."""


class JsonGenomeArtifactCodec:
    """Encode and decode the current UTF-8 JSON artifact representation."""

    @property
    def media_type(self) -> str:
        """Return the JSON genome artifact media type."""
        return GENOME_ARTIFACT_MEDIA_TYPE

    def decode(self, artifact: bytes) -> dict[str, Any]:
        """Decode JSON bytes while leaving schema migration to FEAGI."""
        payload = json.loads(artifact)
        if not isinstance(payload, dict):
            raise ValueError("Genome artifact must contain a JSON object")
        return payload

    def encode(self, genome: dict[str, Any]) -> bytes:
        """Encode a genome dictionary as compact UTF-8 JSON."""
        return json.dumps(
            genome,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")


JSON_GENOME_ARTIFACT_CODEC = JsonGenomeArtifactCodec()


def decode_genome_artifact(artifact: bytes) -> dict[str, Any]:
    """Decode bytes using the current explicitly selected artifact codec."""
    return JSON_GENOME_ARTIFACT_CODEC.decode(artifact)


def encode_genome_artifact(genome: dict[str, Any]) -> bytes:
    """Encode a genome using the current explicitly selected artifact codec."""
    return JSON_GENOME_ARTIFACT_CODEC.encode(genome)


def is_genome_artifact_file_name(file_name: str | None) -> bool:
    """Return whether a filename uses the required `.genome` extension."""
    if not file_name:
        return False
    path = Path(file_name.replace("\\", "/"))
    return bool(path.stem) and path.suffix.lower() == GENOME_ARTIFACT_EXTENSION


__all__ = [
    "GENOME_ARTIFACT_EXTENSION",
    "GENOME_ARTIFACT_MEDIA_TYPE",
    "JSON_GENOME_ARTIFACT_CODEC",
    "GenomeArtifactCodec",
    "JsonGenomeArtifactCodec",
    "decode_genome_artifact",
    "encode_genome_artifact",
    "is_genome_artifact_file_name",
]
