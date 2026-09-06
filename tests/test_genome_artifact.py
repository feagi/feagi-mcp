"""Contract tests for MCP genome artifact encoding."""

import json

import pytest

from feagi_mcp.genome_artifact import (
    GENOME_ARTIFACT_MEDIA_TYPE,
    JsonGenomeArtifactCodec,
    decode_genome_artifact,
    encode_genome_artifact,
    is_genome_artifact_file_name,
)


def test_json_codec_round_trip_preserves_schema_version() -> None:
    """Artifact encoding remains independent from schema migration."""
    genome = {"genome_schema_version": 3, "version": "3.0", "blueprint": {}}

    encoded = encode_genome_artifact(genome)

    assert decode_genome_artifact(encoded) == genome
    assert JsonGenomeArtifactCodec().media_type == GENOME_ARTIFACT_MEDIA_TYPE


def test_json_codec_rejects_malformed_or_non_object_payloads() -> None:
    """Malformed JSON and non-object roots are rejected locally."""
    with pytest.raises(json.JSONDecodeError):
        decode_genome_artifact(b"not-json")

    with pytest.raises(ValueError, match="JSON object"):
        decode_genome_artifact(b"[]")


def test_filename_contract_rejects_legacy_json() -> None:
    """MCP accepts only `.genome` filenames at artifact boundaries."""
    assert is_genome_artifact_file_name("brain.genome")
    assert is_genome_artifact_file_name(r"C:\brains\brain.GENOME")
    assert not is_genome_artifact_file_name("brain.json")
