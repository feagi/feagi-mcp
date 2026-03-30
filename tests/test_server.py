"""Tests for FEAGI MCP server."""

import json

import pytest

from feagi_mcp.feagi_client import FeagiClient


@pytest.mark.asyncio
async def test_feagi_client_init():
    """Test FeagiClient initialization."""
    client = FeagiClient(host="localhost", port=8000)
    assert client.base_url == "http://localhost:8000"
    await client.close()


@pytest.mark.asyncio
async def test_validate_genome_invalid_json():
    """Test genome validation with invalid JSON."""
    from feagi_mcp.server import validate_genome

    result = await validate_genome('{"invalid": json}')
    assert result["valid"] is False
    assert len(result["issues"]) > 0


@pytest.mark.asyncio
async def test_validate_genome_missing_keys():
    """Test genome validation with missing required keys."""
    from feagi_mcp.server import validate_genome

    minimal_genome = json.dumps({"genome_title": "Test"})
    result = await validate_genome(minimal_genome)
    assert result["valid"] is False
    assert any("version" in issue for issue in result["issues"])


@pytest.mark.asyncio
async def test_validate_genome_valid():
    """Test genome validation with valid structure."""
    from feagi_mcp.server import validate_genome

    valid_genome = json.dumps(
        {
            "genome_title": "Test Genome",
            "version": "2.1",
            "blueprint": {
                "_____10c-test__-cx-__name-t": "TestArea",
                "_____10c-test__-cx-_group-t": "CUSTOM",
            },
            "neuron_morphologies": {"test_morph": {"patterns": [[0, 0, 0]]}},
        }
    )
    result = await validate_genome(valid_genome)
    assert result["valid"] is True
    assert len(result["issues"]) == 0


@pytest.mark.asyncio
async def test_connectivity_check():
    """Test connectivity checking logic."""
    client = FeagiClient(host="localhost", port=8000)

    try:
        result = await client.get_connectivity("test_src", "test_dst")
        assert "error" in result or "connected" in result
    finally:
        await client.close()
