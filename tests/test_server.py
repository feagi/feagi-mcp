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


@pytest.mark.asyncio
async def test_stimulate_area_batch_tool_delegates_to_client(monkeypatch):
    """MCP tool stimulate_area_batch calls FeagiClient.stimulate_area_batch."""
    from feagi_mcp import server

    called: list[tuple[str, list, str]] = []

    async def fake_batch(area_id: str, coordinates_list, mode: str = "force_fire"):
        called.append((area_id, list(coordinates_list), mode))
        return {"success": True, "neurons_stimulated": 1}

    monkeypatch.setattr(server.feagi, "stimulate_area_batch", fake_batch)
    out = await server.stimulate_area_batch(
        "b3BzZQEAAAA=",
        [[0, 0, 0], [1, 0, 0]],
    )
    assert out["success"] is True
    assert called == [
        (
            "b3BzZQEAAAA=",
            [[0, 0, 0], [1, 0, 0]],
            "force_fire",
        )
    ]


@pytest.mark.asyncio
async def test_download_region_genome_delegates_to_client(monkeypatch):
    """MCP tool download_region_genome calls FeagiClient.download_region_genome."""
    from feagi_mcp import server

    fake_region_genome = {
        "blueprint": {"_____10c-test__-cx-__name-t": "TestArea"},
        "neuron_morphologies": {},
        "brain_regions": {"region-abc": {"title": "Sub Region"}},
        "physiology": {"simulation_timestep": 0.025},
        "version": "2.0",
    }

    async def fake_download(_region_id: str):
        return fake_region_genome

    monkeypatch.setattr(server.feagi, "download_region_genome", fake_download)
    result = await server.download_region_genome("region-abc")
    assert result == fake_region_genome
    assert "blueprint" in result
    assert "brain_regions" in result


@pytest.mark.asyncio
async def test_download_region_genome_propagates_error(monkeypatch):
    """download_region_genome surfaces FEAGI API errors."""
    from feagi_mcp import server

    async def fake_download_err(_region_id: str):
        return {"error": "HTTP 404", "message": "Region not found"}

    monkeypatch.setattr(server.feagi, "download_region_genome", fake_download_err)
    result = await server.download_region_genome("nonexistent-id")
    assert "error" in result


@pytest.mark.asyncio
async def test_get_version_info_delegates_to_client(monkeypatch):
    """MCP tool get_version_info calls FeagiClient.get_version_info."""
    from feagi_mcp import server

    expected = {
        "feagi_core": "2.0.0",
        "rust": "1.79.0",
        "build_timestamp": "2026-08-12T15:00:00Z",
    }

    async def fake_get_version_info():
        return expected

    monkeypatch.setattr(server.feagi, "get_version_info", fake_get_version_info)
    result = await server.get_version_info()
    assert result == expected
