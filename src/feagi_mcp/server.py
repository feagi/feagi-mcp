"""FEAGI MCP Server - Main server implementation."""

import asyncio
import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from feagi_mcp.bv_operations import list_operation_summaries
from feagi_mcp.config import load_config
from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.placement_policy import (
    LAYOUT_XY_PLANE,
    MIN_ANCHOR_SEPARATION_VOXELS,
    parse_region_coordinate_3d,
    suggest_anchor_positions,
)
from feagi_mcp.snapshots import SnapshotManager, validate_label

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

snapshot_manager = SnapshotManager()


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
async def list_cortical_area_names() -> list[str]:
    """Get a simple list of all cortical area names.

    Returns only the human-readable names of cortical areas without additional
    metadata. Use this for quick reference or when you just need area names.

    Returns:
        List of cortical area names (strings)
    """
    result = await feagi.list_cortical_area_names()
    return result


@mcp.tool()
async def list_morphologies() -> dict[str, Any]:
    """Get all morphology definitions and connectivity rules.

    Returns complete morphology catalog including:
    - vectors: Precise coordinate-based connections
    - patterns: Pattern-based connectivity rules
    - functions: Function-based connections (memory, projection, etc.)
    - composite: Multi-morphology compositions

    Each morphology defines how neurons connect between cortical areas.
    Use this to understand available connection patterns and design circuits.

    Returns:
        Dictionary mapping morphology names to their definitions
    """
    result = await feagi.list_morphologies()
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
async def load_barebones_genome() -> dict[str, Any]:
    """Load the barebones genome (minimal FEAGI core areas only).

    Resets FEAGI to a clean state with only Brain_Power and Death areas.
    Use this as a starting point to build custom networks programmatically.

    Returns:
        Load result with success status and cortical area count
    """
    result = await feagi.load_barebones_genome()
    return result


@mcp.tool()
async def create_morphology(
    morphology_name: str,
    morphology_type: str,
    morphology_parameters: dict[str, Any],
) -> dict[str, Any]:
    """Create a custom morphology for precise neuron-to-neuron connectivity.

    Morphologies define connection patterns between cortical areas.
    Use "vectors" type for precise coordinate-based mappings (e.g., joint control).

    Args:
        morphology_name: Unique name for this morphology (e.g., "to_joint_0")
        morphology_type: Type of morphology ("vectors", "patterns", "functions", "composite")
        morphology_parameters: Type-specific parameters:
            - For "vectors": {"vectors": [[dx, dy, dz], ...]}
              Each vector [dx,dy,dz] creates synapse from [x,y,z] to [x+dx,y+dy,z+dz]
            - For "patterns": {"patterns": [[pattern_x, pattern_y, pattern_z]]}
            - For "functions": {} (function-based connections)

    Returns:
        Status of morphology creation

    Examples:
        Identity mapping (preserves coordinates):
          {"vectors": [[0, 0, 0]]}

        X-axis lateral connection:
          {"vectors": [[1, 0, 0]]}

        Multi-directional:
          {"vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    """
    result = await feagi.create_morphology(morphology_name, morphology_type, morphology_parameters)
    return result


@mcp.tool()
async def get_cortical_area_geometry() -> dict[str, Any]:
    """Get full geometry info for all cortical areas including dimensions and positions.

    Returns detailed structure for each area:
    - cortical_dimensions: [x, y, z] voxel dimensions
    - position: [x, y, z] 3D coordinates
    - cortical_neuron_per_vox_count: neurons per voxel

    Use this to debug morphology connections and understand area structure.

    Returns:
        Dictionary mapping cortical_id to geometry properties
    """
    result = await feagi.get_cortical_area_geometry()
    return result


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
    """Check FEAGI server connectivity and system health (GET /v1/system/health_check).

    Includes ``amalgamation_pending`` when a merge is queued (``amalgamation_id``,
    ``genome_title``, ``circuit_size``), ``brain_regions_root`` for choosing a parent
    region when calling ``confirm_amalgamation_destination``, and usual counters
    (``brain_readiness``, ``cortical_area_count``, etc.). Falls back to a minimal
    payload if the system endpoint is unavailable.

    Returns:
        Full health_check JSON or a minimal ``status`` / ``genome_name`` object.
    """
    result = await feagi.health_check()
    return result


@mcp.tool()
async def get_burst_engine_status() -> dict[str, Any]:
    """Get burst engine runtime status.

    Returns current state: active, paused, frequency, burst count.
    Use this to verify FEAGI is running and check simulation speed.

    Returns:
        Burst engine status with active state, frequency, and burst count
    """
    result = await feagi.get_burst_engine_status()
    return result


@mcp.tool()
async def get_runtime_metrics() -> dict[str, Any]:
    """Get comprehensive runtime metrics.

    Returns neuron counts, cortical area counts, burst statistics, and brain readiness.
    Use this to understand overall system state and resource usage.

    Returns:
        Runtime metrics including neuron_count, cortical_area_count, burst_count, frequency
    """
    result = await feagi.get_runtime_metrics()
    return result


@mcp.tool()
async def get_cortical_synapse_counts(area_id: str) -> dict[str, Any]:
    """Get incoming and outgoing synapse counts for a cortical area.

    Use this to verify connections exist and diagnose signal propagation issues.

    Args:
        area_id: Cortical area identifier (e.g., "Y0NQR2FfX18=")

    Returns:
        Synapse counts: incoming, outgoing, and connection summary
    """
    result = await feagi.get_cortical_synapse_counts(area_id)
    return result


@mcp.tool()
async def get_registered_agents() -> dict[str, Any]:
    """Get list of all registered agents and their subscriptions.

    Use this to verify controllers are connected and subscribed to motor outputs.

    Returns:
        List of registered agents with their capabilities, subscriptions, and status
    """
    result = await feagi.get_registered_agents()
    return result


@mcp.tool()
async def get_agent_properties(agent_id: str) -> dict[str, Any]:
    """Get detailed properties for a specific registered agent.

    Shows agent type, capabilities, version info, and connection details.

    Args:
        agent_id: Agent identifier (from get_registered_agents)

    Returns:
        Agent properties including type, capabilities, IP, port, version
    """
    result = await feagi.get_agent_properties(agent_id)
    return result


@mcp.tool()
async def get_agent_device_registrations(agent_id: str) -> dict[str, Any]:
    """Get device registrations for an agent showing motor/sensor structure.

    Critical for understanding:
    - Motor types (ServoMotor, RotaryMotor)
    - Control modes (absolute vs incremental)
    - Group IDs and limb mappings
    - Joint names and actuator details
    - Expected OPU cortical area IDs

    Args:
        agent_id: Agent identifier (from get_registered_agents)

    Returns:
        Device registrations with input_units, output_units, and metadata
    """
    result = await feagi.get_agent_device_registrations(agent_id)
    return result


@mcp.tool()
async def list_opu_areas() -> list[str]:
    """List all OPU (Output Processing Unit) cortical area IDs.

    Filters only motor output areas. Use to find which motor areas exist.

    Returns:
        List of OPU cortical area IDs
    """
    result = await feagi.list_opu_areas()
    return result


@mcp.tool()
async def list_opu_areas_with_metadata() -> list[dict[str, Any]]:
    """List all OPU areas with detailed semantic information.

    Returns comprehensive metadata for each output area including:
    - area_type: Technical identifier (e.g., "omot", "ogaz")
    - category: High-level category (motor_control, vision_control, language, etc.)
    - purpose: What the area controls or outputs
    - capabilities: List of specific capabilities
    - supported_devices: Types of hardware this area can control
    - data_format: Format of data this area outputs
    - typical_use: Common use cases and applications

    Use this instead of list_opu_areas when you need to understand what each
    output area does and what it can control.

    Returns:
        List of OPU areas with semantic metadata
    """
    result = await feagi.list_opu_areas_with_metadata()
    return result


@mcp.tool()
async def list_ipu_areas() -> list[str]:
    """List all IPU (Input Processing Unit) cortical area IDs.

    Filters only sensory input areas. Use to find which sensor areas exist.

    Returns:
        List of IPU cortical area IDs
    """
    result = await feagi.list_ipu_areas()
    return result


@mcp.tool()
async def list_ipu_areas_with_metadata() -> list[dict[str, Any]]:
    """List all IPU areas with detailed semantic information.

    Returns comprehensive metadata for each input area including:
    - area_type: Technical identifier (e.g., "isvi", "iten")
    - category: High-level category (vision_input, language_input, etc.)
    - purpose: What the area processes or receives
    - capabilities: List of specific capabilities
    - supported_devices: Types of sensors this area can receive from
    - data_format: Format of data this area expects
    - typical_use: Common use cases and applications

    Use this instead of list_ipu_areas when you need to understand what each
    input area processes and what sensors it supports.

    Returns:
        List of IPU areas with semantic metadata
    """
    result = await feagi.list_ipu_areas_with_metadata()
    return result


@mcp.tool()
async def get_area_semantic_info(area_id: str) -> dict[str, Any]:
    """Get detailed semantic information about a specific cortical area.

    Returns comprehensive metadata including:
    - area_type: Technical identifier (e.g., "omot", "isvi", "ogaz")
    - category: High-level category (motor_control, vision_input, language, etc.)
    - purpose: Detailed description of what the area does
    - capabilities: List of specific capabilities
    - supported_devices: Types of hardware/sensors this area works with
    - data_format: Format of data the area uses
    - typical_use: Common use cases and application examples
    - name: Human-readable name from genome (if available)
    - device_count: Number of connected devices (if available)

    Use this when you need to understand what a specific cortical area does,
    what it can control, or what devices it supports.

    Args:
        area_id: Cortical area identifier (e.g., "b21vdAUAAAA=")

    Returns:
        Semantic metadata about the area
    """
    result = await feagi.get_area_semantic_info(area_id)
    return result


@mcp.tool()
async def create_cortical_area(
    name: str,
    cortical_type: str,
    dimensions: list[int],
    position: list[int],
    neurons_per_voxel: int = 1,
    device_count: int = 1,
    properties: dict[str, Any] | None = None,
    cortical_id: str | None = None,
    group_id: int = 0,
    data_type_configs_by_subunit: dict[str, int] | None = None,
    per_device_dimensions: list[int] | None = None,
    brain_region_id: str | None = None,
    skip_placement_validation: bool = False,
) -> dict[str, Any]:
    """Create a new cortical area programmatically.

    Use this to add OPU areas, IPU areas, or custom processing areas to the genome
    without manual JSON editing.

    If the user asked for a "new circuit" as a named container in the brain map with no voxel
    geometry, they likely mean a brain region — use create_brain_region instead.

    Args:
        name: Human-readable name (persisted in genome / BV). Use clear role- or circuit-based
            names (e.g. OrGate_Input_A); do not prefix with Mcp/MCP (see docs NEW_TOOLS naming
            policy).
        cortical_type: "OPU", "IPU", "CUSTOM", or "MEMORY"
        dimensions: [width, height, depth] in voxels (for CUSTOM/MEMORY only)
        position: [x, y, z] 3D coordinates
        neurons_per_voxel: Number of neurons per voxel (default: 1)
        device_count: Number of devices for IPU/OPU (default: 1)
        properties: Optional additional properties (grp_id, etc.)
        brain_region_id: Parent brain region UUID for CUSTOM/MEMORY (required by API; may use
            properties[\"brain_region_id\"] instead)
        skip_placement_validation: Set True only to bypass MCP checks: (1) anchors must be
            at least 20 voxels from world origin (BV axis visibility), (2) anchors must be at
            least 32 voxels from any existing area (label overlap in BV).
        cortical_id: For OPU/IPU: type key like "opse", "isvi" (required for OPU/IPU)
        group_id: For OPU/IPU: group identifier 0-255 (default: 0)
        data_type_configs_by_subunit: For OPU/IPU: map of subunit index to config
            e.g. {"0": 256, "1": 256, "2": 256} for 3-subunit servo with absolute+linear
        per_device_dimensions: For OPU/IPU: override per-device dimensions [x,y,z]
            e.g. [1, 1, 32] for single-joint servo with 32-angle resolution
            Total X = per_device_dimensions[0] * device_count

    Returns:
        Created area info with cortical_id
    """
    result = await feagi.create_cortical_area(
        name,
        cortical_type,
        dimensions,
        position,
        neurons_per_voxel,
        device_count,
        properties,
        cortical_id,
        group_id,
        data_type_configs_by_subunit,
        per_device_dimensions,
        brain_region_id,
        skip_placement_validation,
    )
    return result


@mcp.tool()
async def update_cortical_area(cortical_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update properties of an existing cortical area.

    Modify neural parameters, position, dimensions, or other properties.

    Args:
        cortical_id: Cortical area ID to update
        updates: Dictionary of property updates

    Returns:
        Update result with success status
    """
    result = await feagi.update_cortical_area(cortical_id, updates)
    return result


@mcp.tool()
async def delete_cortical_area(cortical_id: str) -> dict[str, Any]:
    """Delete a cortical area and all its neurons/synapses.

    Args:
        cortical_id: Cortical area ID to delete

    Returns:
        Deletion result with success status
    """
    result = await feagi.delete_cortical_area(cortical_id)
    return result


@mcp.tool()
async def get_cortical_mapping(src_area: str, dst_area: str) -> dict[str, Any]:
    """Get detailed cortical mapping configuration between two areas.

    Shows morphology rules, synaptic weights, plasticity settings.

    Args:
        src_area: Source cortical area ID
        dst_area: Destination cortical area ID

    Returns:
        Mapping configuration with morphology and synapse parameters
    """
    result = await feagi.get_cortical_mapping(src_area, dst_area)
    return result


@mcp.tool()
async def update_cortical_mapping(
    src_area: str, dst_area: str, mapping_rules: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create or update connections between two cortical areas.

    Each mapping rule defines morphology, synaptic strength, and plasticity.

    Args:
        src_area: Source cortical area ID
        dst_area: Destination cortical area ID
        mapping_rules: List of connection rules with morphology_id, psc_multiplier, etc.

    Returns:
        Update result with synapse count and success status
    """
    result = await feagi.update_cortical_mapping(src_area, dst_area, mapping_rules)
    return result


@mcp.tool()
async def delete_cortical_mapping(src_area: str, dst_area: str) -> dict[str, Any]:
    """Delete all connections between two cortical areas.

    Args:
        src_area: Source cortical area ID
        dst_area: Destination cortical area ID

    Returns:
        Deletion result with success status
    """
    result = await feagi.delete_cortical_mapping(src_area, dst_area)
    return result


@mcp.tool()
async def resolve_cortical_area_by_name(
    display_name: str,
    match_mode: str = "exact",
) -> dict[str, Any]:
    """Resolve a display name to base64 cortical_id (BV uses names; APIs use IDs).

    Natural language: call when the user names an area (e.g. \"Object Segmentation-0-0\")
    before update_cortical_area, reset_cortical_neural_state, or clone_cortical_area.

    Args:
        display_name: Human-readable cortical name from the genome.
        match_mode: \"exact\" (default), \"substring\", or \"icase\" (case-insensitive exact).

    Returns:
        matches list, and resolved_cortical_id when exactly one match exists.
    """
    result = await feagi.resolve_cortical_display_name(display_name, match_mode)
    return result


@mcp.tool()
async def get_cortical_id_name_mapping() -> dict[str, Any]:
    """Return {cortical_id: cortical_name} for all areas (GET cortical_id_name_mapping).

    Natural language: use to translate IDs to names or search names without guessing.
    """
    result = await feagi.get_cortical_id_name_mapping()
    return result


@mcp.tool()
async def get_cortical_map_detailed() -> dict[str, Any]:
    """Outgoing connectivity map per area (GET cortical_map_detailed).

    Same data Brain Visualizer loads when refreshing mappings. Natural language: use for
    \"what connects to what\" at the mapping-destination level.
    """
    result = await feagi.get_cortical_map_detailed()
    return result


@mcp.tool()
async def get_brain_regions() -> dict[str, Any]:
    """List brain regions and member cortical areas (GET region/regions_members).

    Natural language: \"which region is this area in?\", region hierarchy, relocate context.
    """
    result = await feagi.get_regions_members()
    return result


@mcp.tool()
async def create_brain_region(
    title: str,
    coordinates_2d: list[int],
    coordinates_3d: list[int],
    parent_region_id: str | None = None,
    region_type: str = "Undefined",
    region_id: str | None = None,
) -> dict[str, Any]:
    """Create a brain region (connectome hierarchy node; Brain Visualizer regional group).

    In FEAGI, users often say \"circuit\" when they mean this — a named region that can hold
    cortical areas — not an IPU/OPU/CUSTOM voxel block. For voxel areas use create_cortical_area.

    Args:
        title: Display name for the new region (e.g. user-supplied label).
        coordinates_2d: Brain-map 2D position [x, y] (API-required).
        coordinates_3d: Layout 3D anchor [x, y, z] (API-required).
        parent_region_id: Optional parent region UUID. If omitted, FEAGI attaches the new region
            under the existing root (single-root tree); only the first region in an empty genome
            becomes root without a parent.
        region_type: Region classification string (default \"Undefined\").
        region_id: Optional fixed UUID; if omitted the server assigns one.

    Returns:
        Created region record including region_id.
    """
    result = await feagi.create_brain_region(
        title,
        coordinates_2d,
        coordinates_3d,
        parent_region_id=parent_region_id,
        region_type=region_type,
        region_id=region_id,
    )
    return result


@mcp.tool()
async def suggest_cortical_anchor_positions(
    count: int = 1,
    parent_region_id: str | None = None,
    spacing_voxels: int = MIN_ANCHOR_SEPARATION_VOXELS,
    layout: str = LAYOUT_XY_PLANE,
    axis: str | None = None,
) -> dict[str, Any]:
    """Suggest 3D anchors for new CUSTOM/MEMORY cortical areas using BV placement rules.

    Call **before** ``create_cortical_area`` when adding several areas (e.g. AND gate inputs).
    Uses live ``get_cortical_area_geometry`` so suggestions avoid the origin gizmo and stay
    separated from existing areas. If ``parent_region_id`` is set, biases the chain near that
    region's ``coordinate_3d`` from ``get_brain_regions`` instead of arbitrary large coords.

    **Layout (BV camera looks toward +Z; prefer XY for visibility):**
    - ``xy_plane`` / ``co_occurring_inputs`` — same Y and Z, spread along +X (default).
    - ``hierarchy_y`` — shallow hierarchy steps along +Y (small circuits).
    - ``temporal_z`` — stages along +Z (time / deep feedforward).

    Args:
        count: Number of ``[x, y, z]`` anchors to return.
        parent_region_id: Optional brain region UUID to align the layout with (e.g. your circuit).
        spacing_voxels: Step between consecutive anchors on the primary layout axis (>= 32).
        layout: See strings above; default keeps the circuit in the XY plane for visibility.
        axis: Optional legacy override: ``x``, ``y``, or ``z`` only (prefer ``layout``).

    Returns:
        ``positions``, ``base_hint_source`` (``parent_region`` or ``default``), spacing, and layout.
    """
    geom = await feagi.get_cortical_area_geometry()
    if not isinstance(geom, dict):
        return {"error": "invalid_geometry_response"}
    if geom.get("error"):
        return geom

    base_hint = None
    base_source = "default"
    parent_c3: list[int] | None = None
    pr = parent_region_id.strip() if isinstance(parent_region_id, str) else None
    if pr:
        rm = await feagi.get_regions_members()
        if not isinstance(rm, dict):
            return {"error": "invalid_regions_response"}
        if rm.get("error"):
            return rm
        parsed = parse_region_coordinate_3d(rm, pr)
        if parsed is not None:
            base_hint = parsed
            base_source = "parent_region"
            parent_c3 = [parsed[0], parsed[1], parsed[2]]

    spacing = max(int(spacing_voxels), MIN_ANCHOR_SEPARATION_VOXELS)
    layout_key = layout if isinstance(layout, str) and layout.strip() else LAYOUT_XY_PLANE
    positions = suggest_anchor_positions(
        int(count),
        geom,
        base_hint=base_hint,
        spacing=spacing,
        layout=layout_key.strip(),
        axis=axis.strip() if isinstance(axis, str) and axis.strip() else None,
    )
    return {
        "positions": positions,
        "base_hint_source": base_source,
        "parent_region_coordinate_3d": parent_c3,
        "spacing_voxels": spacing,
        "layout": layout_key.strip(),
        "axis": axis,
    }


@mcp.tool()
async def get_genome_file_name() -> dict[str, Any]:
    """Current genome file label (GET genome/file_name)."""
    result = await feagi.get_genome_file_name()
    return result


@mcp.tool()
async def save_genome_to_filesystem(
    file_path: str | None = None,
    genome_id: str | None = None,
    genome_title: str | None = None,
) -> dict[str, Any]:
    """Save the running genome to disk (POST genome/save), same as Brain Visualizer save.

    Natural language: \"export genome\", \"save genome to file\". Optional absolute file_path;
    if omitted, FEAGI picks a default under its configured genome directory.
    """
    result = await feagi.save_genome_to_filesystem(file_path, genome_id, genome_title)
    return result


@mcp.tool()
async def inspect_cortical_area(cortical_id: str) -> dict[str, Any]:
    """Full cortical area record from connectome (POST cortical_area/cortical_area_properties).

    Natural language: prefer this over get_area_parameters when you need the same fields as
    Brain Visualizer's cortical inspector (dimensions, types, neural params from services).
    """
    result = await feagi.fetch_cortical_area_properties(cortical_id)
    return result


@mcp.tool()
async def inspect_cortical_areas_batch(cortical_ids: list[str]) -> dict[str, Any]:
    """Batch cortical area properties (POST multi/cortical_area_properties)."""
    result = await feagi.fetch_multi_cortical_area_properties(cortical_ids)
    return result


@mcp.tool()
async def reset_cortical_neural_state(cortical_ids: list[str]) -> dict[str, Any]:
    """Reset runtime neural state for areas without changing genome (PUT cortical_area/reset).

    Natural language: \"clear membrane potentials\", \"reset neurons\" for named areas —
    resolve names with resolve_cortical_area_by_name first.
    """
    result = await feagi.reset_cortical_neural_state(cortical_ids)
    return result


@mcp.tool()
async def clone_cortical_area(
    source_area_id: str,
    new_name: str,
    coordinates_3d: list[int],
    coordinates_2d: list[int],
    clone_cortical_mapping: bool = True,
    parent_region_id: str | None = None,
) -> dict[str, Any]:
    """Clone a custom (c*) or memory (m*) cortical area (POST cortical_area/clone).

    Natural language: \"duplicate area\". Only custom/memory areas are supported by the API.
    """
    result = await feagi.clone_cortical_area_via_api(
        source_area_id,
        new_name,
        coordinates_3d,
        coordinates_2d,
        clone_cortical_mapping,
        parent_region_id,
    )
    return result


@mcp.tool()
async def get_cortical_template() -> dict[str, Any]:
    """IPU/OPU cortical templates (GET genome/cortical_template), as in BV template picker."""
    result = await feagi.get_cortical_template()
    return result


@mcp.tool()
async def list_brain_visualizer_operations() -> list[dict[str, str]]:
    """List every Brain Visualizer REST operation (operation_id, method, path, description).

    Brain Visualizer routes are defined in FEAGIHTTPAddressList.gd; this is the MCP index used
    to call the same endpoints via brain_visualizer_api. Call this first when you need an
    operation that has no dedicated named tool.

    **Voxel / neuron inspection:** For questions about a specific voxel or neuron inside a
    cortical area (actual neuron IDs, per-neuron properties, incoming/outgoing synapses at that
    voxel, or debugging connectivity at a coordinate), use operation_id
    ``get_cortical_area_voxel_neurons`` (GET ``/v1/cortical_area/voxel_neurons``) via
    ``brain_visualizer_api`` with query ``cortical_id``, ``x``, ``y``, ``z``, and optional
    ``synapse_page`` for paginated synapse lists.
    """
    return list_operation_summaries()


@mcp.tool()
async def brain_visualizer_api(
    operation_id: str,
    path_params: dict[str, str] | None = None,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
) -> Any:
    """Invoke any whitelisted Brain Visualizer FEAGI API operation.

    Covers the same HTTP surface as brain-visualizer (FEAGIHTTPAddressList): genome, cortical
    areas, regions, morphologies, mappings, burst, system visualization tuning, neuroplasticity,
    insight/monitoring, agents, network, and vision input.

    **Voxel/neuron inspection:** When the user asks to inspect a particular voxel or neuron
    within a cortical area, or to debug synapses at a coordinate, call
    ``operation_id=\"get_cortical_area_voxel_neurons\"`` with ``query`` containing
    ``cortical_id`` (base64 cortical ID), ``x``, ``y``, ``z`` (voxel indices), and optional
    ``synapse_page`` (0-based) for paginated incoming/outgoing synapse detail. This maps to
    GET ``/v1/cortical_area/voxel_neurons``.

    Args:
        operation_id: From list_brain_visualizer_operations (e.g. get_system_health_check,
            get_cortical_area_voxel_neurons, put_cortical_area, post_mapping_afferents,
            put_region_relocate_members).
        path_params: Path placeholders, e.g. region_id, agent_id.
        query: URL query params (amalgamation_id, circuit_origin_*, cortical_id/x/y/z for voxel
            neurons, etc.).
        json_body: JSON body. For post_genome_amalgamation_by_upload_multipart pass
            {\"genome_json\": \"<full genome json string>\"}.

    Returns:
        Parsed JSON response, or an error object with HTTP status details.
    """
    return await feagi.brain_visualizer_operation(
        operation_id,
        path_params=path_params,
        query=query,
        json_body=json_body,
    )


@mcp.tool()
async def queue_amalgamation_by_payload(genome_json: str) -> Any:
    """Queue an incoming genome for amalgamation (POST /v1/genome/amalgamation_by_payload).

    ``genome_json`` must be a UTF-8 JSON string of the **full** genome document (same as
    ``POST /v1/genome/upload``), not a wrapped object. After success, poll
    ``health_check`` for ``amalgamation_pending``, then call
    ``confirm_amalgamation_destination`` with the returned ``amalgamation_id`` and a
    parent ``brain_region_id`` (typically ``brain_regions_root`` from health_check).

    Returns:
        API response, usually ``message`` and ``amalgamation_id``.
    """
    body = json.loads(genome_json)
    return await feagi.brain_visualizer_operation(
        "post_genome_amalgamation_by_payload",
        json_body=body,
    )


@mcp.tool()
async def confirm_amalgamation_destination(
    amalgamation_id: str,
    circuit_origin_x: int,
    circuit_origin_y: int,
    circuit_origin_z: int,
    brain_region_id: str,
    rewire_mode: str = "rewire_all",
) -> Any:
    """Complete a pending amalgamation (POST /v1/genome/amalgamation_destination).

    Query parameters match Brain Visualizer: origin offsets and ``rewire_mode``.
    JSON body must include ``brain_region_id`` (UUID of the parent region, usually root).

    Returns:
        API response including ``skipped_existing_areas`` (cortical IDs not created
        because they already existed in the host genome — expected when importing a
        genome that shares standard area IDs with the base brain).
    """
    return await feagi.brain_visualizer_operation(
        "post_genome_amalgamation_destination",
        query={
            "amalgamation_id": amalgamation_id,
            "circuit_origin_x": circuit_origin_x,
            "circuit_origin_y": circuit_origin_y,
            "circuit_origin_z": circuit_origin_z,
            "rewire_mode": rewire_mode,
        },
        json_body={"brain_region_id": brain_region_id},
    )


# ============================================================================
# MCP DEFICIENCY GAP-FILLERS
#
# These tools close the visibility gaps surfaced during inverted-pendulum
# debugging: motor/sensor runtime taps, log tail, burst control, neuron and
# synapse runtime inspection, batched monitoring, multi-agent capabilities,
# and on-disk genome snapshots.
# ============================================================================


@mcp.tool()
async def get_motor_snapshot_last(agent_id: str | None = None) -> dict[str, Any]:
    """Latest motor output produced by the burst loop (`/v1/output/motor_snapshot/last`).

    Use this to confirm whether OPU areas are firing and whether motor packets are
    actually being published to a connected agent. The response contains:

    - ``has_data`` / ``burst_num`` / ``timestamp_ms`` - freshness markers.
    - ``areas`` - per OPU cortical area firing samples (xyz + potential).
    - ``agents`` - per-agent publish stats with ``published`` and ``last_error``.

    Args:
        agent_id: Optional agent filter for the per-agent stats.
    """
    return await feagi.get_motor_snapshot_last(agent_id)


@mcp.tool()
async def get_sensor_snapshot_last(cortical_id: str | None = None) -> dict[str, Any]:
    """Latest sensory input decoded by the burst loop (`/v1/input/sensor_snapshot/last`).

    Surfaces exactly what FEAGI consumed from connected sensors this burst -
    eliminating the need to poke at the embodiment side to ground-truth IPU
    encoding direction or device wiring.

    Args:
        cortical_id: Optional base64 cortical id filter.
    """
    return await feagi.get_sensor_snapshot_last(cortical_id)


@mcp.tool()
async def get_log_tail(
    level: str | None = None,
    target_prefix: str | None = None,
    since_ts_ms: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Recent FEAGI log records (`/v1/system/log_tail`).

    Reads the in-process tracing ring buffer maintained by feagi-observability.
    Returns ``enabled=False`` when ``FEAGI_LOG_RING_BUFFER_CAPACITY`` is set to 0
    or the buffer was not installed.

    Args:
        level: Minimum severity (``TRACE``/``DEBUG``/``INFO``/``WARN``/``ERROR``).
        target_prefix: Restrict to tracing targets starting with this prefix
            (e.g. ``feagi_npu`` or ``burst_loop``).
        since_ts_ms: Unix-ms cutoff; only returns records emitted at or after this
            timestamp.
        limit: Cap on returned record count (most recent records win).
    """
    return await feagi.get_log_tail(level, target_prefix, since_ts_ms, limit)


@mcp.tool()
async def get_burst_counter() -> dict[str, Any]:
    """Current burst counter (`/v1/burst_engine/burst_counter`).

    Useful for ``A``/``B`` deltas around an action: snapshot counter before,
    apply stimulus, snapshot after, confirm bursts were processed in between.
    """
    return await feagi.get_burst_counter()


@mcp.tool()
async def get_burst_engine_config() -> dict[str, Any]:
    """Burst engine config (`/v1/burst_engine/config`).

    Returns ``burst_frequency_hz``, ``burst_interval_seconds``, ``is_running``,
    and ``is_paused``.
    """
    return await feagi.get_burst_engine_config()


@mcp.tool()
async def set_burst_engine_frequency(frequency_hz: float) -> dict[str, Any]:
    """Set the burst engine frequency in Hz (`PUT /v1/burst_engine/config`).

    Slow the engine (e.g. 1-5 Hz) to make circuit debugging deterministic;
    speed it back up (e.g. 40 Hz) when the circuit is settled.

    Args:
        frequency_hz: Target frequency in Hz (must be > 0).
    """
    return await feagi.set_burst_engine_frequency(frequency_hz)


@mcp.tool()
async def control_burst_engine(action: str) -> dict[str, Any]:
    """Burst engine control (`POST /v1/burst_engine/control`).

    Args:
        action: ``start``, ``resume``, ``pause``, or ``stop``.
    """
    return await feagi.control_burst_engine(action)


@mcp.tool()
async def pause_burst_engine() -> dict[str, Any]:
    """Hold (pause) the burst engine (`POST /v1/burst_engine/hold`)."""
    return await feagi.pause_burst_engine()


@mcp.tool()
async def resume_burst_engine() -> dict[str, Any]:
    """Resume the burst engine after a hold (`POST /v1/burst_engine/resume`)."""
    return await feagi.resume_burst_engine()


@mcp.tool()
async def inspect_neuron_state_at(
    cortical_id: str,
    x: int,
    y: int,
    z: int,
) -> dict[str, Any]:
    """Neuron runtime state at a voxel (`/v1/connectome/neuron_properties_at`).

    Returns membrane potential, threshold, refractory countdown, and other
    sub-threshold state for the neuron at ``(x, y, z)`` in the given cortical
    area. Solves the "why isn't this neuron firing" debugging question.
    """
    return await feagi.inspect_neuron_state_at(cortical_id, x, y, z)


@mcp.tool()
async def get_neuron_state_by_id(neuron_id: str) -> dict[str, Any]:
    """Neuron runtime state by stable id (`/v1/connectome/neuron/{id}/properties`)."""
    return await feagi.get_neuron_state_by_id(neuron_id)


@mcp.tool()
async def get_voxel_neurons(
    cortical_id: str,
    x: int,
    y: int,
    z: int,
    synapse_page: int | None = None,
) -> dict[str, Any]:
    """All neurons + synapses at a voxel (`/v1/cortical_area/voxel_neurons`).

    Same payload Brain Visualizer uses for its voxel inspector. ``synapse_page``
    (0-based) requests a paginated incoming/outgoing synapse list.
    """
    return await feagi.get_voxel_neurons(cortical_id, x, y, z, synapse_page)


@mcp.tool()
async def list_area_synapses(cortical_area_id: str) -> dict[str, Any]:
    """Placed synapses for one cortical area (`/v1/connectome/{area}/synapses`).

    Unlike ``get_cortical_mapping`` (which returns morphology rules), this returns
    the actual realized per-synapse list with source/target neuron ids, weights,
    PSP, and synapse type. Use this to confirm that morphologies wired the
    expected synapses after upload.
    """
    return await feagi.list_area_synapses(cortical_area_id)


@mcp.tool()
async def list_agent_capabilities_all(
    include_device_registrations: bool = True,
) -> dict[str, Any]:
    """Raw multi-agent capabilities payload (`/v1/agent/capabilities/all`).

    Diagnostic for cases where ``get_agent_device_registrations`` returns empty
    but devices are clearly active. Returns the full FEAGI response unmodified
    so the LLM can see exactly what the server reported per agent.
    """
    return await feagi.list_agent_capabilities_all(include_device_registrations)


@mcp.tool()
async def monitor_activity_batch(
    area_ids: list[str],
    duration_ms: int = 1000,
) -> dict[str, Any]:
    """Monitor multiple cortical areas concurrently.

    Composes ``GET /v1/monitoring/cortical_activity`` (no new server route) but
    fans out the calls in parallel so observing 4-6 areas takes roughly the time
    of a single call instead of N sequential round-trips.

    Args:
        area_ids: List of cortical area ids to observe simultaneously.
        duration_ms: Monitoring window applied to every area (default 1000).

    Returns:
        ``{"duration_ms", "area_count", "results": {area_id: payload}}``.
    """
    return await feagi.monitor_activity_batch(area_ids, duration_ms)


@mcp.tool()
async def snapshot_genome(
    label: str,
    description: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Save the running genome blueprint to disk under ``label``.

    Persists ``GET /v1/genome/download`` to ``feagi-mcp/var/snapshots/<label>.json``
    (or ``$FEAGI_MCP_SNAPSHOTS_DIR``). Survives MCP restarts. Captures the
    blueprint only - synaptic weights and membrane potentials are not saved.

    Args:
        label: Filename-safe identifier matching ``[A-Za-z0-9_.-]{1,128}``.
        description: Optional free-form note saved with the snapshot.
        overwrite: When False (default), refuses to clobber an existing label.
    """
    try:
        clean_label = validate_label(label)
    except ValueError as e:
        return {"error": str(e)}
    genome = await feagi.download_genome()
    if isinstance(genome, dict) and "error" in genome:
        return {"error": "download_failed", "details": genome}
    try:
        info = snapshot_manager.save(
            clean_label,
            genome,
            description=description,
            overwrite=overwrite,
        )
    except FileExistsError as e:
        return {"error": "snapshot_exists", "message": str(e)}
    except (OSError, ValueError) as e:
        return {"error": "save_failed", "message": str(e)}
    payload = info.to_dict()
    payload["snapshot_directory"] = str(snapshot_manager.directory)
    return payload


@mcp.tool()
async def restore_genome_snapshot(label: str) -> dict[str, Any]:
    """Restore a previously saved genome snapshot via ``POST /v1/genome/upload``.

    Reads the labeled file from disk, then re-uploads it to FEAGI. Replaces the
    running genome with the saved blueprint. Live runtime state (synaptic
    weights, membrane potentials) is rebuilt from scratch by FEAGI.

    Args:
        label: Snapshot label previously created with ``snapshot_genome``.
    """
    try:
        info, genome = snapshot_manager.load(label)
    except FileNotFoundError as e:
        return {"error": "snapshot_not_found", "message": str(e)}
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return {"error": "load_failed", "message": str(e)}
    upload = await feagi.upload_genome(genome)
    return {
        "snapshot": info.to_dict(),
        "upload": upload,
    }


@mcp.tool()
async def list_genome_snapshots() -> dict[str, Any]:
    """List all genome snapshots stored on disk."""
    snapshots = snapshot_manager.list_snapshots()
    return {
        "snapshot_directory": str(snapshot_manager.directory),
        "count": len(snapshots),
        "snapshots": [info.to_dict() for info in snapshots],
    }


@mcp.tool()
async def delete_genome_snapshot(label: str) -> dict[str, Any]:
    """Delete a stored genome snapshot by label."""
    try:
        validate_label(label)
    except ValueError as e:
        return {"error": str(e)}
    try:
        removed = snapshot_manager.delete(label)
    except OSError as e:
        return {"error": "delete_failed", "message": str(e)}
    return {
        "label": label.strip(),
        "removed": removed,
        "snapshot_directory": str(snapshot_manager.directory),
    }


@mcp.tool()
async def list_morphologies_summary(
    name_substring: str | None = None,
    type_filter: str | None = None,
    class_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Slim morphology listing (name + type + class + pattern_count, paginated).

    Use this instead of ``list_morphologies`` when the genome has many morphologies
    (the full listing easily exceeds the MCP response cap). Apply filters to focus
    the result and ``limit``/``offset`` to paginate.
    """
    return await feagi.list_morphologies_summary(
        name_substring=name_substring,
        type_filter=type_filter,
        class_filter=class_filter,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
async def get_connectivity_summary(
    src_filter: str | None = None,
    dst_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Tabular connectivity view: ``[{src, dst, morphology, psc_mult, plasticity}]``.

    Slim alternative to ``get_connectivity`` (which expands every blueprint key for
    a single src->dst pair). Returns a flat sorted list across all mapping rules so
    the LLM can scan src/dst topology in one shot. Filters match cortical IDs as
    substrings before pagination.
    """
    return await feagi.get_connectivity_summary(
        src_filter=src_filter,
        dst_filter=dst_filter,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
async def inspect_cortical_areas_minimal(cortical_ids: list[str]) -> dict[str, Any]:
    """Project ``inspect_cortical_areas_batch`` to ~18 plasticity-relevant fields.

    Returns one record per cortical_id with only the fields needed for circuit
    design (dimensions, fire threshold, PSP, leak, refractory, plasticity constant,
    burst engine flag, synapse counts). Discards visualization geometry and
    encoding option lists. Lets you sweep five areas at once without exhausting
    the response budget.
    """
    return await feagi.inspect_cortical_areas_minimal(cortical_ids)


@mcp.tool()
async def build_reflex_mapping(
    src_area_id: str,
    dst_area_id: str,
    morphology_name: str,
    voxel_mappings: list[dict[str, Any]],
    postsynaptic_current_multiplier: int,
    plasticity_flag: bool = False,
    plasticity_constant: int = 0,
    ltp_multiplier: int = 1,
    ltd_multiplier: int = 1,
    plasticity_window: int = 10,
    synaptic_delay_bursts: int = 0,
    morphology_scalar: list[int] | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Create a custom ``patterns`` morphology and wire src->dst with it in one call.

    Combines ``create_morphology`` + ``update_cortical_mapping`` so a reflex circuit
    can be specified by its voxel-to-voxel routing table alone:

    .. code-block:: python

        voxel_mappings = [
            {"src": [0, 0, 0], "dst": [0, 0, 0]},
            {"src": [0, 0, 1], "dst": [0, 0, 1]},
            ...
        ]

    Each entry is one row of the morphology pattern. Wildcards (``"*"``, ``"?"``,
    ``"!"``) are supported in any axis. By default the new mapping is appended to
    existing rules between the two areas; pass ``replace_existing=True`` to wipe
    them first.
    """
    return await feagi.build_reflex_mapping(
        src_area_id=src_area_id,
        dst_area_id=dst_area_id,
        morphology_name=morphology_name,
        voxel_mappings=voxel_mappings,
        postsynaptic_current_multiplier=postsynaptic_current_multiplier,
        plasticity_flag=plasticity_flag,
        plasticity_constant=plasticity_constant,
        ltp_multiplier=ltp_multiplier,
        ltd_multiplier=ltd_multiplier,
        plasticity_window=plasticity_window,
        synaptic_delay_bursts=synaptic_delay_bursts,
        morphology_scalar=morphology_scalar,
        replace_existing=replace_existing,
    )


@mcp.tool()
async def auto_polarity_probe(
    opu_id: str,
    sensor_id: str,
    columns: list[int] | None = None,
    intensity_z: int = 5,
    repeats: int = 3,
    settle_ms: int = 400,
) -> dict[str, Any]:
    """Empirically discover OPU column -> sensor direction by force-firing each column.

    For each column ``x`` in ``columns`` (default ``[0, 1]``): force-fire
    ``(x, 0, intensity_z)``, wait ``settle_ms``, snapshot the sensor, and report the
    weighted-z centroid shift. The result is an inferred direction map you can use
    to wire your reflex morphology without manually decoding the embodiment's
    motor convention.

    Requires the embodiment agent to be subscribed to motor output for ``opu_id``.
    """
    return await feagi.auto_polarity_probe(
        opu_id=opu_id,
        sensor_id=sensor_id,
        columns=columns,
        intensity_z=intensity_z,
        repeats=repeats,
        settle_ms=settle_ms,
    )


@mcp.tool()
async def embodiment_get_physics_state(
    introspection_url: str,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    """GET ground-truth physics state from the embodiment controller.

    Currently implemented for the MuJoCo controller (see
    ``nrs-embodiments/controllers/simulators/mujoco/mcp_introspection.py``). The
    controller exposes its state on a small HTTP server when launched with
    ``--mcp-introspection-port`` (or ``MUJOCO_MCP_INTROSPECTION_PORT`` env). Pass
    that base URL here, e.g. ``"http://localhost:9876"``.
    """
    return await feagi.embodiment_get_physics_state(introspection_url, timeout_s)


@mcp.tool()
async def embodiment_set_joint_state(
    introspection_url: str,
    joint_qpos: dict[str, float] | None = None,
    joint_qvel: dict[str, float] | None = None,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    """Place embodiment joints deterministically (e.g. tilt pendulum to test reflex).

    Useful to verify a reflex circuit responds correctly at a given physical state
    without waiting for the dynamics to wander there organically. Currently
    implemented for the MuJoCo controller's introspection server.
    """
    return await feagi.embodiment_set_joint_state(
        introspection_url,
        joint_qpos=joint_qpos,
        joint_qvel=joint_qvel,
        timeout_s=timeout_s,
    )


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
