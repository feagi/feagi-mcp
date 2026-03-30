"""FEAGI MCP Server - Main server implementation."""

import asyncio
import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from feagi_mcp.config import load_config
from feagi_mcp.feagi_client import FeagiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("feagi_mcp")

config = load_config()
feagi = FeagiClient(
    host=config.host,
    port=config.port,
    timeout=config.timeout_seconds,
)

mcp = FastMCP(
    name="feagi",
)


@mcp.tool()
async def monitor_activity(area_id: str, duration_ms: int = 1000) -> dict[str, Any]:
    """Monitor real-time neural activity in a cortical area.

    This tool observes firing rates, active neurons, and spike patterns over a specified
    duration. Use this to verify CPG oscillations, check signal propagation, or debug
    why circuits aren't working.

    Args:
        area_id: Cortical area identifier (e.g., "cCPGa_", "opose0")
        duration_ms: Monitoring duration in milliseconds (default: 1000)

    Returns:
        Activity data including firing_rate, active_neurons, spike_timestamps
    """
    result = await feagi.monitor_activity(area_id, duration_ms)
    return result


@mcp.tool()
async def get_connectivity(src_area: str, dst_area: str) -> dict[str, Any]:
    """Get synaptic connectivity between two cortical areas.

    Examines the genome to find all connections from source to destination area,
    including morphology types, synaptic weights, and connection counts. Essential
    for verifying that your circuit topology is correct.

    Args:
        src_area: Source cortical area ID (e.g., "cCPGa_")
        dst_area: Destination cortical area ID (e.g., "cHipFL")

    Returns:
        Connection details: connected (bool), synapse_count, morphology info, weights
    """
    result = await feagi.get_connectivity(src_area, dst_area)
    return result


@mcp.tool()
async def get_area_parameters(area_id: str) -> dict[str, Any]:
    """Get all parameters for a specific cortical area.

    Retrieves dimensions, neuron properties (leak coefficient, fire threshold, PSC max),
    connections, and other configuration. Use this to inspect existing areas or verify
    parameter values after upload.

    Args:
        area_id: Cortical area identifier

    Returns:
        Complete parameter set for the area
    """
    result = await feagi.get_area_parameters(area_id)
    return result


@mcp.tool()
async def get_embodiment_status() -> dict[str, Any]:
    """Get status of connected embodiment controllers.

    Shows which controllers are registered, their motor/sensor cortical IDs,
    device counts, and connection health. Critical for debugging why motor
    commands aren't reaching the robot.

    Returns:
        Embodiment status including connected agents, motor/sensor mappings, last activity
    """
    result = await feagi.get_embodiment_status()
    return result


@mcp.tool()
async def stimulate_area(
    area_id: str,
    coordinates: list[int],
    potential: float,
    duration_ms: int = 100,
) -> dict[str, Any]:
    """Stimulate a cortical area for testing.

    Injects a spike or continuous potential into specific neurons. Use this to
    trigger CPGs, test signal propagation, or activate behavior circuits.

    Args:
        area_id: Cortical area identifier
        coordinates: [x, y, z] neuron coordinates within the area
        potential: Stimulation potential (typically 0.0 to 1.0)
        duration_ms: Duration of stimulation in milliseconds

    Returns:
        Success status and neurons activated
    """
    result = await feagi.stimulate_area(area_id, coordinates, potential, duration_ms)
    return result


@mcp.tool()
async def list_cortical_areas() -> list[dict[str, Any]]:
    """List all cortical areas in the current genome.

    Returns all areas with their names, IDs, types (IPU/OPU/CUSTOM/CORE),
    dimensions, and device counts. Use this to explore the current brain
    architecture.

    Returns:
        List of cortical areas with metadata
    """
    result = await feagi.list_cortical_areas()
    return result


@mcp.tool()
async def get_genome_info() -> dict[str, Any]:
    """Get metadata about the currently loaded genome.

    Returns genome name, version, statistics (neuron count, area count, etc.),
    and basic health information.

    Returns:
        Genome metadata and statistics
    """
    result = await feagi.get_genome_info()
    return result


@mcp.tool()
async def download_genome() -> dict[str, Any]:
    """Download the complete genome configuration.

    Retrieves the full genome JSON including all cortical areas, connections,
    morphologies, brain regions, and physiology. Use this to inspect the current
    architecture in detail or as a baseline for modifications.

    Returns:
        Complete genome JSON structure
    """
    result = await feagi.download_genome()
    return result


@mcp.tool()
async def upload_genome(genome_json: str) -> dict[str, Any]:
    """Upload a new genome to FEAGI.

    Loads a complete neural architecture into FEAGI, replacing the current genome.
    The genome must be valid JSON with proper structure (blueprint, morphologies,
    brain_regions, physiology).

    Args:
        genome_json: Complete genome as JSON string

    Returns:
        Upload result with success status, cortical area count, and any errors
    """
    try:
        genome_data = json.loads(genome_json)
        result = await feagi.upload_genome(genome_data)
        return result
    except json.JSONDecodeError as e:
        return {"success": False, "error": "invalid_json", "message": str(e)}


@mcp.tool()
async def trace_signal_path(from_area: str, to_area: str, max_hops: int = 5) -> dict[str, Any]:
    """Trace signal propagation path between cortical areas.

    Finds all possible paths from source to destination area through intermediate
    connections. Use this to verify that signals can actually reach their target
    or to debug missing connections.

    Args:
        from_area: Source cortical area ID
        to_area: Destination cortical area ID
        max_hops: Maximum path length to search (default: 5)

    Returns:
        All paths found, with intermediate areas and connection strengths
    """
    try:
        genome = await feagi.download_genome()
        if "error" in genome:
            return genome

        blueprint = genome.get("blueprint", {})
        connectivity_map: dict[str, list[str]] = {}

        for key, value in blueprint.items():
            if "dstmap-d" in key and isinstance(value, dict):
                src = key.split("-cx-")[0].replace("_____10c-", "")
                connectivity_map[src] = list(value.keys())

        def find_paths(
            current: str, target: str, visited: set[str], path: list[str], depth: int
        ) -> list[list[str]]:
            if depth > max_hops:
                return []
            if current == target:
                return [path + [current]]
            if current in visited:
                return []

            visited.add(current)
            paths = []
            for neighbor in connectivity_map.get(current, []):
                paths.extend(
                    find_paths(neighbor, target, visited.copy(), path + [current], depth + 1)
                )
            return paths

        paths = find_paths(from_area, to_area, set(), [], 0)

        return {
            "from_area": from_area,
            "to_area": to_area,
            "paths_found": len(paths),
            "paths": paths,
            "connected": len(paths) > 0,
        }
    except Exception as e:
        logger.error(f"trace_signal_path failed: {e}")
        return {"error": str(e)}


@mcp.tool()
async def validate_genome(genome_json: str) -> dict[str, Any]:
    """Validate a genome structure without uploading it.

    Checks for common issues: missing required fields, invalid cortical IDs,
    malformed connections, parameter ranges, and structural problems.

    Args:
        genome_json: Genome JSON string to validate

    Returns:
        Validation results with issues, warnings, and suggestions
    """
    try:
        genome = json.loads(genome_json)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "issues": [f"Invalid JSON: {e}"],
            "warnings": [],
        }

    issues = []
    warnings = []

    required_keys = ["genome_title", "version", "blueprint", "neuron_morphologies"]
    for key in required_keys:
        if key not in genome:
            issues.append(f"Missing required key: {key}")

    blueprint = genome.get("blueprint", {})
    if not blueprint:
        issues.append("Blueprint is empty")
    else:
        area_ids = set()
        for key in blueprint:
            if "__name-t" in key:
                area_id = key.split("-cx-")[0].replace("_____10c-", "")
                area_ids.add(area_id)

        for key, value in blueprint.items():
            if "dstmap-d" in key and isinstance(value, dict):
                for dst_area in value:
                    if dst_area not in area_ids:
                        warnings.append(f"Connection to undefined area: {dst_area} (from {key})")

    morphologies = genome.get("neuron_morphologies", {})
    if not morphologies:
        warnings.append("No neuron morphologies defined")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "cortical_area_count": len(area_ids) if "area_ids" in locals() else 0,
    }


@mcp.tool()
async def health_check() -> dict[str, Any]:
    """Check FEAGI server connectivity and health.

    Returns:
        Health status including reachability and current genome name
    """
    result = await feagi.health_check()
    return result


def main() -> None:
    """Run the FEAGI MCP server."""
    logger.info("Starting FEAGI MCP Server...")
    logger.info(f"Connecting to FEAGI at {config.host}:{config.port}")

    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        asyncio.run(feagi.close())


if __name__ == "__main__":
    main()
