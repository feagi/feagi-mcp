"""FEAGI MCP Server - Main server implementation."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from feagi_mcp.bv_operations import list_operation_summaries
from feagi_mcp.composer_simulator_packs import ComposerSimulatorPacksClient
from feagi_mcp.config import load_config
from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation
from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.io_cortical_id_encode import encode_io_cortical_id
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
composer_sim_packs = ComposerSimulatorPacksClient(
    base_url=config.composer_base_url,
    timeout=config.timeout_seconds,
)

mcp = FastMCP(
    name="feagi",
)

snapshot_manager = SnapshotManager()


def _positive_int_or_none(value: Any) -> int | None:
    """Return positive int value, otherwise None."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_float_or_none(value: Any) -> float | None:
    """Return positive float value, otherwise None."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@mcp.tool()
async def monitor_activity(
    area_id: str,
    duration_ms: int = 1000,
    include_lifetime_stats: bool = True,
    lifetime_neuron_cap: int = 64,
) -> dict[str, Any]:
    """Monitor real-time neural activity, plus lifetime fire-count enrichment.

    Observes firing rates, active neurons, and spike patterns over the sample
    window. The base REST endpoint reports only spikes seen in that window,
    which can incorrectly suggest a circuit is dead when it is merely silent
    at sample time. By default this tool also attaches ``lifetime_stats``
    aggregating per-neuron ``consecutive_fire_count`` across the area, so a
    "0 spikes now but lifetime_active_count > 0" result clearly distinguishes
    "currently quiet" from "never wired/never fired".

    Args:
        area_id: Cortical area identifier (e.g., "cCPGa_", "opose0").
        duration_ms: Sample window in milliseconds (default: 1000).
        include_lifetime_stats: When True (default), attach ``lifetime_stats``.
            Set False for very large areas where the extra fan-out is unwanted.
        lifetime_neuron_cap: Maximum neurons inspected for lifetime stats
            (default: 64). Caps round-trips for big areas.

    Returns:
        Activity data including ``firing_statistics`` (sample window) and,
        when enabled, ``lifetime_stats`` with ``max_consecutive_fire_count``,
        ``lifetime_active_count``, and ``top_neurons``.
    """
    result = await feagi.monitor_activity(
        area_id,
        duration_ms,
        include_lifetime_stats=include_lifetime_stats,
        lifetime_neuron_cap=lifetime_neuron_cap,
    )
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
async def get_memory_area_runtime_config(cortical_id: str, page_size: int = 1) -> dict[str, Any]:
    """Get effective runtime lifecycle config for one memory cortical area.

    This closes the MCP visibility gap where users otherwise must infer memory
    lifecycle behavior from multiple endpoints with different field names.
    Returns one normalized payload with:

    - Runtime memory counts (ST/LT/total) from ``GET /v1/cortical_area/memory``.
    - Effective lifecycle values (init lifespan, growth rate, LT threshold).
    - Source attribution for each lifecycle value (runtime vs cortical properties).
    - Consistency checks to flag mismatched values between endpoint surfaces.

    Args:
        cortical_id: Memory cortical area ID (base64 wire ID).
        page_size: Memory endpoint page size for neuron IDs (default 1; max 50).

    Returns:
        Normalized runtime memory config and diagnostics for this area.
    """
    area = await feagi.fetch_cortical_area_properties(cortical_id)
    if not isinstance(area, dict) or area.get("error"):
        return {
            "error": "cortical_properties_unavailable",
            "cortical_id": cortical_id,
            "details": area,
        }

    props = area.get("properties")
    props_dict = props if isinstance(props, dict) else {}
    is_memory = (
        str(area.get("cortical_type", "")).lower() == "memory"
        or bool(props_dict.get("is_mem_type", False))
    )
    if not is_memory:
        return {
            "error": "not_memory_area",
            "cortical_id": cortical_id,
            "cortical_type": area.get("cortical_type"),
            "message": "Tool is only valid for memory cortical areas.",
        }

    normalized_page_size = max(1, min(int(page_size), 50))
    memory_runtime = await feagi.brain_visualizer_operation(
        "get_cortical_area_memory",
        query={
            "cortical_id": cortical_id,
            "page": 0,
            "page_size": normalized_page_size,
        },
    )
    if not isinstance(memory_runtime, dict) or memory_runtime.get("error"):
        return {
            "error": "memory_runtime_unavailable",
            "cortical_id": cortical_id,
            "details": memory_runtime,
        }

    runtime_params = memory_runtime.get("memory_parameters")
    runtime_params_dict = runtime_params if isinstance(runtime_params, dict) else {}

    runtime_init = _positive_int_or_none(runtime_params_dict.get("init_lifespan"))
    runtime_growth = _positive_float_or_none(runtime_params_dict.get("lifespan_growth_rate"))
    runtime_ltm = _positive_int_or_none(runtime_params_dict.get("longterm_mem_threshold"))

    props_init = _positive_int_or_none(area.get("neuron_init_lifespan"))
    props_growth = _positive_float_or_none(area.get("neuron_lifespan_growth_rate"))
    props_ltm = _positive_int_or_none(area.get("neuron_longterm_mem_threshold"))

    def choose_value(
        runtime_value: int | float | None, props_value: int | float | None
    ) -> tuple[int | float | None, str]:
        if runtime_value is not None:
            return runtime_value, "runtime_memory_parameters"
        if props_value is not None:
            return props_value, "cortical_properties"
        return None, "missing_or_zero"

    effective_init, init_source = choose_value(runtime_init, props_init)
    effective_growth, growth_source = choose_value(runtime_growth, props_growth)
    effective_ltm, ltm_source = choose_value(runtime_ltm, props_ltm)

    mismatches: list[str] = []
    if runtime_init is not None and props_init is not None and runtime_init != props_init:
        mismatches.append("init_lifespan")
    if runtime_growth is not None and props_growth is not None and runtime_growth != props_growth:
        mismatches.append("lifespan_growth_rate")
    if runtime_ltm is not None and props_ltm is not None and runtime_ltm != props_ltm:
        mismatches.append("longterm_mem_threshold")

    st_count = int(memory_runtime.get("short_term_neuron_count", 0))
    lt_count = int(memory_runtime.get("long_term_neuron_count", 0))
    total_count = int(memory_runtime.get("total_memory_neuron_ids", 0))

    return {
        "cortical_id": cortical_id,
        "cortical_name": memory_runtime.get("cortical_name") or area.get("cortical_name"),
        "cortical_idx": memory_runtime.get("cortical_idx") or area.get("cortical_idx"),
        "runtime_counts": {
            "short_term_neuron_count": st_count,
            "long_term_neuron_count": lt_count,
            "total_memory_neuron_ids": total_count,
        },
        "effective_lifecycle": {
            "init_lifespan": {"value": effective_init, "source": init_source},
            "lifespan_growth_rate": {"value": effective_growth, "source": growth_source},
            "longterm_mem_threshold": {"value": effective_ltm, "source": ltm_source},
        },
        "consistency": {
            "st_plus_lt_matches_total": (st_count + lt_count) == total_count,
            "lifecycle_param_mismatches": mismatches,
        },
        "raw": {
            "runtime_memory_parameters": runtime_params_dict,
            "cortical_properties_lifecycle": {
                "neuron_init_lifespan": area.get("neuron_init_lifespan"),
                "neuron_lifespan_growth_rate": area.get("neuron_lifespan_growth_rate"),
                "neuron_longterm_mem_threshold": area.get("neuron_longterm_mem_threshold"),
            },
        },
    }


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
    """Get status of connected embodiment controllers (GET /v1/embodiment/status when available).

    When the **HTTP** embodiment status route is up, you get full registration
    metadata. If it is **unavailable**, the client falls back to a **static**
    read of the loaded genome (``status": "genome_info"``) and **must not** be
    used as a substitute for live ZMQ/registration state.

    For **which OPU / IPU the agent actually bound in this session** (cortical
    ids, group order, control modes), prefer
    ``get_agent_device_registrations`` with a concrete ``agent_id`` from
    ``get_registered_agents`` — that is the least ambiguous source when the
    agent is online.

    Returns:
        Online embodiment JSON, or fallback genome I/O description with a notice.
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
async def stimulate_area_batch(
    area_id: str,
    coordinates_list: list[list[int]],
    mode: str = "force_fire",
) -> dict[str, Any]:
    """Stimulate many voxels in one cortical area in a single request.

    Use this to mirror encoder patterns onto a motor OPU, fill a z-slab, or
    fire a list of test coordinates without one MCP round trip per voxel.
    The FEAGI API receives one ``manual_stimulation`` payload for the whole
    list. ``potential`` / ``duration_ms`` are not sent (same as
    :func:`stimulate_area` today).

    Args:
        area_id: Cortical area identifier (base64 wire id)
        coordinates_list: List of ``[x, y, z]`` integer coordinates; each must
            have length 3
        mode: Stimulation mode (default ``force_fire``)

    Returns:
        Success status and aggregate neuron / match counts from the API
    """
    result = await feagi.stimulate_area_batch(area_id, coordinates_list, mode)
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
async def get_version_info() -> dict[str, Any]:
    """Get FEAGI runtime and component versions (GET /v1/system/versions).

    Use this to confirm the running FEAGI build identity and detect version
    mismatches between runtime, desktop, and MCP/tooling.

    Returns:
        Version payload from FEAGI system endpoint
    """
    result = await feagi.get_version_info()
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
async def download_region_genome(region_id: str) -> dict[str, Any]:
    """Download a brain-region subtree as a standalone genome JSON.

    Exports only the cortical areas, morphologies, brain regions, and
    physiology that belong to the specified region branch.  Destination
    mappings to areas outside the branch are stripped so the result is a
    self-contained genome that can be loaded independently or shared.

    Use ``get_brain_regions`` first to discover available region IDs and
    their titles.

    Natural language: "export brain region", "save neural circuit",
    "download region as genome".

    Args:
        region_id: UUID of the root brain region to export
            (e.g. from get_brain_regions output).

    Returns:
        Region genome JSON (same shape as a full genome download).
    """
    result = await feagi.download_region_genome(region_id)
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
async def load_genome_from_file(path: str) -> dict[str, Any]:
    """Load (provision) a genome into the live FEAGI from a local JSON file path.

    Reads the genome JSON file *inside the MCP server process* and uploads it to FEAGI,
    replacing the current genome. Prefer this over ``upload_genome`` whenever the genome
    lives on disk: only the file path crosses the model boundary, not the (often very large)
    genome JSON, which avoids excessive token use.

    Use this to provision a known architecture (e.g. an IPU/OPU layout a Trainer run binds to)
    before driving a closed-loop run.

    Args:
        path: Filesystem path to a genome JSON file (absolute, or relative to the MCP server's
            working directory). ``~`` is expanded.

    Returns:
        A compact status object: ``success``, the resolved ``path``, a derived
        ``genome_title`` / ``cortical_area_count`` summary, and the FEAGI ``upload_result``.
        On a local read/parse failure, ``success`` is ``false`` with an explicit ``error`` code
        (``file_not_found`` / ``not_a_file`` / ``invalid_json`` / ``io_error``); the genome is
        not uploaded.
    """
    genome_path = Path(path).expanduser()
    if not genome_path.exists():
        return {"success": False, "error": "file_not_found", "path": str(genome_path)}
    if not genome_path.is_file():
        return {"success": False, "error": "not_a_file", "path": str(genome_path)}

    try:
        raw = genome_path.read_text(encoding="utf-8")
    except OSError as e:
        return {
            "success": False,
            "error": "io_error",
            "path": str(genome_path),
            "message": str(e),
        }

    try:
        genome_data = json.loads(raw)
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": "invalid_json",
            "path": str(genome_path),
            "message": str(e),
        }

    if not isinstance(genome_data, dict):
        return {
            "success": False,
            "error": "invalid_genome",
            "path": str(genome_path),
            "message": "genome root must be a JSON object",
        }

    upload_result = await feagi.upload_genome(genome_data)

    # Derive a small summary so the caller gets confirmation without echoing the full genome.
    blueprint = genome_data.get("blueprint")
    cortical_area_count = len(blueprint) if isinstance(blueprint, dict) else None
    success = bool(upload_result.get("success", "error" not in upload_result))

    return {
        "success": success,
        "path": str(genome_path),
        "genome_title": genome_data.get("genome_title"),
        "cortical_area_count": cortical_area_count,
        "upload_result": upload_result,
    }


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
async def rename_morphology(
    old_morphology_id: str,
    new_morphology_id: str,
) -> dict[str, Any]:
    """Rename a custom morphology (connectivity rule).

    Propagates the new id into cortical mappings on the FEAGI server. Use after creating
    a rule with a temporary name or to align naming with circuit documentation.

    Args:
        old_morphology_id: Existing morphology name
        new_morphology_id: New unique morphology name

    Returns:
        FEAGI status (``status``, ``old_morphology_id``, ``new_morphology_id`` on success)
    """
    result = await feagi.rename_morphology(old_morphology_id, new_morphology_id)
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

    **``connected_agents`` vs. ``get_registered_agents``:** The health payload may
    expose a ``connected_agents`` (or similar) field that is **stricter** than
    the agent registry (e.g. a session-level “fully streaming” counter). A value
    of **0** there does *not* automatically mean there are no embodiment clients:
    if ``get_registered_agents`` returns ids and ``get_motor_snapshot_last`` shows
    activity, the pipeline is still live. Cross-check both when debugging links.

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
async def get_fire_queue_detailed() -> dict[str, Any]:
    """Get last-burst fire queue with neuron IDs per cortical area.

    Returns deterministic, ID-level firing payload for the latest sampled burst.
    Use this for plasticity debugging when area-level counts are not enough:
    - identify exact neurons that fired in each area
    - correlate fired IDs with mapping synapse endpoints
    - inspect coordinates and membrane potentials at fire time
    """
    result = await feagi.get_fire_queue_detailed()
    return result


@mcp.tool()
async def get_agent_connection_endpoints() -> dict[str, Any]:
    """Get the live FEAGI agent connection endpoints (ZMQ/WebSocket) and burst rate.

    Resolves where agents/connectors actually connect — registration, sensory, motor,
    and visualization endpoints — straight from FEAGI's ``/v1/network/connection_info``,
    so callers do not have to guess ZMQ ports. The result is enriched with the live burst
    ``frequency_hz`` (from the burst engine) and a ready-to-use ``remote_runtime`` block
    for driving a closed loop against this brain.

    Primary use: configuring the open ``feagi-trainer`` remote runtime. Feed
    ``remote_runtime.registration_endpoint`` to ``FEAGI_TRAINER_LIVE_REGISTRATION_ENDPOINT``
    and ``remote_runtime.burst_frequency_hz`` to ``FEAGI_TRAINER_LIVE_BURST_HZ``. FEAGI
    returns the per-capability sensory/motor data endpoints during registration, so only
    the registration endpoint and burst rate are required to start.

    Returns:
        ``connection_info`` (raw payload: ``zmq``/``websocket`` hosts, ports, endpoints,
        and ``stream_status``), ``burst`` (raw burst status), and a derived
        ``remote_runtime`` convenience block: ``registration_endpoint``,
        ``sensory_endpoint``, ``motor_endpoint``, ``burst_frequency_hz``, ``zmq_enabled``,
        and ``data_streams_started``. Fields that FEAGI did not report are ``None``.
    """
    connection_info = await feagi.get_network_connection_info()
    burst = await feagi.get_burst_engine_status()

    remote_runtime: dict[str, Any] = {
        "registration_endpoint": None,
        "sensory_endpoint": None,
        "motor_endpoint": None,
        "burst_frequency_hz": None,
        "zmq_enabled": None,
        "data_streams_started": None,
    }

    if isinstance(connection_info, dict) and "error" not in connection_info:
        zmq_info = connection_info.get("zmq")
        if isinstance(zmq_info, dict):
            remote_runtime["zmq_enabled"] = zmq_info.get("enabled")
            endpoints = zmq_info.get("endpoints")
            if isinstance(endpoints, dict):
                remote_runtime["registration_endpoint"] = endpoints.get("registration")
                remote_runtime["sensory_endpoint"] = endpoints.get("sensory")
                remote_runtime["motor_endpoint"] = endpoints.get("motor")
        stream_status = connection_info.get("stream_status")
        if isinstance(stream_status, dict):
            remote_runtime["data_streams_started"] = stream_status.get("zmq_data_streams_started")

    if isinstance(burst, dict):
        remote_runtime["burst_frequency_hz"] = burst.get("frequency_hz")

    return {
        "connection_info": connection_info,
        "burst": burst,
        "remote_runtime": remote_runtime,
    }


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
    """Get list of all registered agents and their subscriptions (agent registry).

    Use this to verify an embodiment or simulator has completed FEAGI’s
    **registration** handshake. **Do not** equate the returned ``count`` with
    *connected_agents* values from ``health_check`` — the latter is often a
    stricter, session-specific notion (e.g. fully handshaken transport) and can
    read 0 when ``get_registered_agents`` and motor taps still work.

    Returns only *which* agents are registered, not how long they will stay
    registered. If an agent keeps reappearing under a new ID, call
    ``get_agent_liveness`` — FEAGI deregisters agents that go quiet past the
    heartbeat timeout, and that teardown closes their sockets.

    Returns:
        List of registered agents with their capabilities, subscriptions, and status
    """
    result = await feagi.get_registered_agents()
    return result


@mcp.tool()
async def get_agent_liveness() -> dict[str, Any]:
    """How close each registered agent is to being deregistered for inactivity.

    Registration does not mean an agent stays connected. FEAGI removes any agent
    that produces no traffic for ``heartbeat_timeout_s``, and that teardown drops
    the agent's motor and visualization publishers, which closes its sockets. The
    client then reconnects and registers again under a **new** agent ID.

    Use this whenever an agent or the Brain Visualizer disconnects on a regular
    period. It separates two causes that otherwise look identical from outside:

    - ``prune_in_s`` counting down to 0 and the agent vanishing means FEAGI reaped
      it for inactivity; the client is not sending heartbeats.
    - ``last_command_control_age_s`` climbing while ``last_activity_age_s`` stays
      low means the agent sends nothing itself and is being held alive only by
      FEAGI's outbound traffic; it will drop as soon as that traffic pauses.
    - An agent disappearing while ``prune_in_s`` is still large points at the
      transport, not at liveness.

    Returns:
        ``heartbeat_timeout_s``, ``stale_check_interval_s``, ``count``, and
        ``agents`` with per-agent ages and countdown.
    """
    return await feagi.get_agent_liveness()


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

    Note:
        FEAGI auto-places IPU/OPU areas, so ``position`` is frequently overridden. The result
        carries a ``placement`` block reporting the requested vs actual coordinates and a
        ``relocated`` flag. For IPU/OPU areas whose canonical wire id must match a sensorimotor
        coder binding, prefer ``create_io_area_for_unit`` which derives the id for you.

    Returns:
        Created area info with cortical_id plus a ``placement`` summary.
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
async def compute_io_cortical_id(
    subtype: str,
    variant: str = "percentage",
    framing: str = "absolute",
    positioning: str = "linear",
    unit_index: int = 0,
    subunit_index: int = 0,
) -> dict[str, Any]:
    """Derive the canonical 8-byte IPU/OPU cortical id for a sensorimotor unit (no live call).

    Mirrors the Rust ``feagi-sensorimotor`` id derivation so a caller (e.g. a Trainer binding
    profile, or before ``create_cortical_area``) gets the exact base64 wire id and configuration
    flag a count/percentage IO unit resolves to — without probing a live brain or reverse-
    engineering bytes. This is the inverse of ``decode_cortical_id``.

    Args:
        subtype: 4-char ``cortical_subtype`` (e.g. ``icnt`` count input, ``ocnt`` count output);
            first char selects input (``i``) vs output (``o``).
        variant: Configuration variant (default ``percentage``; also ``boolean``,
            ``percentage_2d/3d/4d``, ``signed_percentage*``, ``cartesian_plane``, ``misc``).
        framing: ``absolute`` or ``incremental``.
        positioning: ``linear`` or ``fractional`` (percentage-family variants only).
        unit_index: Device / group instance index (wire byte 7).
        subunit_index: Sub-area index within the unit (wire byte 6).

    Returns:
        ``{"ok": True, "cortical_id": <base64>, "config_flag": <int>, ...}`` or
        ``{"ok": False, "error": ...}``.
    """
    return encode_io_cortical_id(
        subtype=subtype,
        variant=variant,
        framing=framing,
        positioning=positioning,
        unit_index=unit_index,
        subunit_index=subunit_index,
    )


@mcp.tool()
async def create_io_area_for_unit(
    name: str,
    subtype: str,
    channels: int,
    depth: int,
    variant: str = "percentage",
    framing: str = "absolute",
    positioning: str = "linear",
    unit_index: int = 0,
    subunit_index: int = 0,
    device_count: int = 1,
    position: list[int] | None = None,
) -> dict[str, Any]:
    """Create the IPU/OPU area a sensorimotor unit binds to, with its canonical id derived.

    One call that (1) computes the canonical wire id + configuration flag for the unit (the
    same derivation the Rust register functions use), (2) creates the matching IPU/OPU area,
    and (3) verifies the server-assigned id equals the computed one. Use this to provision the
    exact area a coder (e.g. a Trainer population encoder / class decoder, or a robot device)
    will publish to / read from, instead of hand-picking ``cortical_id`` +
    ``data_type_configs_by_subunit`` for ``create_cortical_area``.

    Args:
        name: Human-readable area name (BV / genome label).
        subtype: 4-char ``cortical_subtype`` (e.g. ``icnt`` count input, ``ocnt`` count output).
        channels: Number of channels (the area's x-width per device).
        depth: Neuron depth / bins (z-extent); must match the coder's bins.
        variant: IO configuration variant (default ``percentage`` for the count family).
        framing: ``absolute`` or ``incremental``.
        positioning: ``linear`` or ``fractional``.
        unit_index: Device / group instance index (wire byte 7).
        subunit_index: Sub-area index within the unit (wire byte 6).
        device_count: Number of devices for the area.
        position: Optional ``[x, y, z]`` request (FEAGI may auto-place; see ``placement``).

    Returns:
        ``{"computed_cortical_id", "assigned_cortical_id", "verified", "config_flag",
        "create_result"}`` on success, or ``{"error": ...}``.
    """
    return await feagi.create_io_area_for_unit(
        name=name,
        subtype=subtype,
        channels=channels,
        depth=depth,
        variant=variant,
        framing=framing,
        positioning=positioning,
        unit_index=unit_index,
        subunit_index=subunit_index,
        device_count=device_count,
        position=position,
    )


@mcp.tool()
async def update_cortical_area(cortical_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update properties of an existing cortical area.

    Modify neural parameters, position, dimensions, or other properties. For
    **rate-modulated (homeostatic) leak** on dense custom LIF areas, set
    ``rate_modulated_leak`` to an object with fields such as ``enabled``,
    ``target_firing_per_burst``, ``rate_ema_tau_bursts``, ``gain``,
    ``leak_min``, ``leak_max``, and ``update_every_n_bursts`` (see API docs for
    example JSON);
    use ``enabled: false`` to disable. Flat genome suffix ``cx-hmlk-d`` maps to the same
    key.

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
async def diagnose_memory_twin_mapping(src_area: str, dst_area: str) -> dict[str, Any]:
    """Diagnose memory twin eligibility/status for one mapping pair.

    One-call answer for "why was no twin created?" when wiring episodic mappings
    into memory areas. Wraps FEAGI ``GET /v1/cortical_mapping/twin_diagnostic`` and
    returns structured fields including:
    - ``mapping_exists`` / ``episodic_rule_count``
    - ``twin_expected`` / ``twin_present`` / ``twin_cortical_area``
    - ``reason`` (machine-readable blocker)
    - parent-region relationship fields to detect circuit-placement mismatches.

    Args:
        src_area: Source cortical area ID (base64).
        dst_area: Destination cortical area ID (base64).

    Returns:
        Twin diagnostic payload from FEAGI.
    """
    return await feagi.get_memory_twin_diagnostic(src_area, dst_area)


@mcp.tool()
async def diagnose_mapping_plasticity(
    src_area: str,
    dst_area: str,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Diagnose live plasticity state for one mapping pair.

    Designed for questions like "why is weight not increasing?":
    - mapping rule presence and plasticity flags/modes
    - realized synapse count from src filtered to dst
    - weight statistics (min/max/avg/sum, zero/nonzero counts)
    - sample of matched synapses for direct inspection

    Args:
        src_area: Source cortical area ID (base64).
        dst_area: Destination cortical area ID (base64).
        sample_limit: Max matched synapses echoed in ``sample`` (1..200).

    Returns:
        Structured diagnostics combining rule and runtime synapse state.
    """
    return await feagi.get_mapping_plasticity_diagnostics(
        src_area,
        dst_area,
        sample_limit=sample_limit,
    )


@mcp.tool()
async def update_cortical_mapping(
    src_area: str, dst_area: str, mapping_rules: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create or update connections between two cortical areas.

    For plastic rules, optional fields include ``max_weight`` (cap on positive weight
    commits) and ``plasticity_eta`` (scales ``w += eta * R * e``). LTP/LTD
    multipliers are ``i8`` in the runtime. See ``build_reflex_mapping`` and
    ``docs/FAQ.md`` (Circuit design & plasticity).

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
async def validate_brain_region_hierarchy() -> dict[str, Any]:
    """Validate FEAGI brain-region hierarchy invariants used by Brain Visualizer.

    Runs a lightweight consistency check against live ``region/regions_members`` and
    reports whether the hierarchy satisfies BV expectations:
    - exactly one root (``parent_region_id`` is null)
    - no missing parent references
    - no cycles in parent links
    - optional cross-check against exported ``brain_regions_root`` metadata

    Returns:
        Summary dict with ``valid`` flag, derived ``root_region_id``, issue lists,
        and per-region ``parent_map`` details for debugging.
    """
    regions_summary = await feagi.get_regions_members()
    if not isinstance(regions_summary, dict):
        return {"valid": False, "error": "invalid_regions_response"}
    if regions_summary.get("error"):
        return {
            "valid": False,
            "error": "regions_fetch_failed",
            "details": regions_summary,
        }

    region_ids = list(regions_summary.keys())
    parent_map: dict[str, str | None] = {}
    root_candidates: list[str] = []
    missing_parent_refs: list[dict[str, str]] = []
    non_dict_regions: list[str] = []

    for region_id, raw_region in regions_summary.items():
        if not isinstance(raw_region, dict):
            non_dict_regions.append(str(region_id))
            parent_map[str(region_id)] = None
            continue
        parent_id = raw_region.get("parent_region_id")
        if parent_id is None:
            parent_map[str(region_id)] = None
            root_candidates.append(str(region_id))
        else:
            parent_id_str = str(parent_id)
            parent_map[str(region_id)] = parent_id_str
            if parent_id_str not in regions_summary:
                missing_parent_refs.append(
                    {
                        "region_id": str(region_id),
                        "missing_parent_region_id": parent_id_str,
                    }
                )

    cycle_paths: list[list[str]] = []
    cycle_seen_signatures: set[tuple[str, ...]] = set()
    for start in region_ids:
        cur: str | None = str(start)
        path: list[str] = []
        index_by_region: dict[str, int] = {}
        while cur is not None:
            if cur in index_by_region:
                cycle = path[index_by_region[cur] :] + [cur]
                signature = tuple(cycle)
                if signature not in cycle_seen_signatures:
                    cycle_seen_signatures.add(signature)
                    cycle_paths.append(cycle)
                break
            if cur not in parent_map:
                break
            index_by_region[cur] = len(path)
            path.append(cur)
            cur = parent_map[cur]

    genome_meta_root: str | None = None
    genome_download_error: str | None = None
    genome = await feagi.download_genome()
    if isinstance(genome, dict):
        if genome.get("error"):
            genome_download_error = str(genome.get("error"))
        else:
            meta_root = genome.get("brain_regions_root")
            if isinstance(meta_root, str) and meta_root.strip():
                genome_meta_root = meta_root.strip()
    else:
        genome_download_error = "invalid_genome_response"

    root_region_id = root_candidates[0] if len(root_candidates) == 1 else None
    issues: list[str] = []
    if non_dict_regions:
        issues.append("Some regions are not dictionaries and cannot be fully validated.")
    if len(root_candidates) == 0:
        issues.append("No root region detected (no parent_region_id == null).")
    elif len(root_candidates) > 1:
        issues.append(f"Multiple root candidates detected: {len(root_candidates)}")
    if missing_parent_refs:
        issues.append(f"Found {len(missing_parent_refs)} region(s) with missing parent references.")
    if cycle_paths:
        issues.append(f"Detected {len(cycle_paths)} parent cycle(s) in region hierarchy.")
    if (
        genome_meta_root is not None
        and root_region_id is not None
        and genome_meta_root != root_region_id
    ):
        issues.append("brain_regions_root metadata does not match live root parent map.")

    return {
        "valid": len(issues) == 0,
        "region_count": len(region_ids),
        "root_region_id": root_region_id,
        "root_candidates": root_candidates,
        "brain_regions_root_metadata": genome_meta_root,
        "issues": issues,
        "missing_parent_references": missing_parent_refs,
        "cycles": cycle_paths,
        "non_dict_regions": non_dict_regions,
        "genome_download_error": genome_download_error,
        "parent_map": parent_map,
    }


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
async def interpret_cortical_id(cortical_id: str) -> dict[str, Any]:
    """Decode an 8-byte FEAGI cortical ID without calling FEAGI (pure client-side).

    Returns hex bytes, ``cortical_subunit_index`` (byte 6), ``cortical_unit_index`` (byte 7),
    ``mapping_hints`` for BV ``unit_id`` / ROS ``deviceGroupId`` / Python motor XYZP grouping,
    and notes. Accepts standard base64 wire IDs or legacy 8-character latin-1 keys.

    Natural language: \"decode cortical id\", \"what unit index is this id\", \"device group
    for base64 cortical area\".
    """
    return decode_cortical_id_interpretation(cortical_id)


@mcp.tool()
async def inspect_cortical_area(cortical_id: str) -> dict[str, Any]:
    """Full cortical area record from connectome (POST cortical_area/cortical_area_properties).

    Natural language: prefer this over get_area_parameters when you need the same fields as
    Brain Visualizer's cortical inspector (dimensions, types, neural params from services).

    The response always includes ``cortical_id_interpretation`` (see ``interpret_cortical_id``)
    so agents can align ``deviceGroupId`` / BV unit index with byte 7 without manual base64 work.
    """
    result = await feagi.fetch_cortical_area_properties(cortical_id)
    interpretation = decode_cortical_id_interpretation(cortical_id)
    if isinstance(result, dict):
        return {**result, "cortical_id_interpretation": interpretation}
    return {"cortical_id_interpretation": interpretation, "raw": result}


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
async def get_motor_snapshot_last(
    agent_id: str | None = None,
    cortical_id: str | None = None,
) -> dict[str, Any]:
    """Latest motor output produced by the burst loop (`/v1/output/motor_snapshot/last`).

    Use this to confirm whether OPU areas are firing and whether motor packets are
    actually being published to a connected agent. The response contains:

    - ``has_data`` / ``burst_num`` / ``timestamp_ms`` - freshness markers.
    - ``areas`` - per OPU cortical area firing samples (xyz + potential).
    - ``agents`` - per-agent publish stats with ``published`` and ``last_error``.

    Args:
        agent_id: Optional agent filter for the per-agent stats.
        cortical_id: Optional **base64** OPU id to return **only** that area in
            ``areas`` and adjust ``total_areas`` / ``total_neurons`` (same id as
            the JSON ``cortical_id`` in each area row). Use to isolate a cart or
            hinge motor when multiple OPUs and internal areas appear together.
    """
    return await feagi.get_motor_snapshot_last(agent_id, cortical_id=cortical_id)


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
    Returns ``enabled=False`` when the running FEAGI build never installed the
    buffer or ``FEAGI_LOG_RING_BUFFER_CAPACITY`` is set to 0; in that case the
    response carries a ``hint`` describing how to turn it on. An ``enabled=False``
    result will not change on retry — read the FEAGI process stdout instead.

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
async def get_fire_ledger_areas_window_config() -> dict[str, Any]:
    """FireLedger per-area window configuration.

    Route: ``/v1/burst_engine/fire_ledger/areas_window_config``.

    Use this before debugging STDP/associative plasticity. If source/destination
    areas are missing or the configured windows are too small relative to
    ``plasticity_window``, weight updates can appear "stuck".
    """
    return await feagi.get_fire_ledger_areas_window_config()


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
async def list_area_synapses(
    cortical_area_id: str,
    direction: str = "outgoing",
) -> dict[str, Any]:
    """Realized synapse **edges** for a cortical area (not morphology rules only).

    **``direction`` (important):** The default path lists **efferent** (outgoing)
    synapses from this area. IPU→OPU plastic synapses for a **motor** area are
    **afferent** (into the OPU); for those, pass ``direction="incoming"`` or
    ``direction="both"``. Otherwise you will see 200 with an empty list even when
    ``inspect_cortical_areas_minimal`` reports a large ``incoming_synapse_count``.

    ``direction=both`` returns one dict with ``outgoing`` and ``incoming`` keys.

    For morphology **rules** (morphology id, PSC, plasticity mode), use
    ``get_cortical_mapping`` or ``get_connectivity_summary`` instead of this tool.
    """
    return await feagi.list_area_synapses(cortical_area_id, direction=direction)


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
    include_lifetime_stats: bool = True,
    lifetime_neuron_cap: int = 64,
) -> dict[str, Any]:
    """Monitor multiple cortical areas concurrently.

    Composes ``GET /v1/monitoring/cortical_activity`` (no new server route) but
    fans out the calls in parallel so observing 4-6 areas takes roughly the time
    of a single call instead of N sequential round-trips. Each per-area payload
    is enriched with the same ``lifetime_stats`` block as ``monitor_activity``
    when ``include_lifetime_stats`` is True.

    Args:
        area_ids: List of cortical area ids to observe simultaneously.
        duration_ms: Monitoring window applied to every area (default 1000).
        include_lifetime_stats: Forward to per-area enrichment (default True).
        lifetime_neuron_cap: Per-area neuron sampling cap (default 64).

    Returns:
        ``{"duration_ms", "area_count", "results": {area_id: payload}}``.
    """
    return await feagi.monitor_activity_batch(
        area_ids,
        duration_ms,
        include_lifetime_stats=include_lifetime_stats,
        lifetime_neuron_cap=lifetime_neuron_cap,
    )


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
    """Project ``inspect_cortical_areas_batch`` to a fixed, compact field set per area.

    Returns one record per cortical_id with only the fields needed for circuit
    design (dimensions, fire threshold, PSP, leak, ``rate_modulated_leak`` when
    present, refractory, plasticity constant, burst engine flag, synapse counts).
    Discards visualization geometry and encoding option lists. Lets you sweep
    several areas at once without exhausting the response budget.
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
    synaptic_delay_bursts: int = 1,
    morphology_scalar: list[int] | None = None,
    replace_existing: bool = False,
    plasticity_mode: str | None = None,
    eligibility_decay_bursts: int | None = None,
    reward_source_area: str | None = None,
    punishment_source_area: str | None = None,
    max_weight: float | None = None,
    plasticity_eta: float | None = None,
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

    ``synaptic_delay_bursts`` must be >= 1 (the backend rejects a zero axonal delay during
    synapse regeneration); it defaults to 1. A value < 1 is rejected up front, before the
    morphology is created, so no orphan morphology is left behind.

    Plasticity controls:
        ``plasticity_flag`` enables learning on the mapping (legacy STDP path).
        ``plasticity_mode`` is the new explicit selector:
            * ``"off"`` - no learning (equivalent to ``plasticity_flag=False``);
            * ``"stdp"`` - classic correlation-based Hebbian STDP;
            * ``"rstdp"`` - reward-modulated STDP. Requires
              ``eligibility_decay_bursts`` (>=1) and at least one of
              ``reward_source_area`` / ``punishment_source_area`` (base64 IDs of
              detector cortical areas). The detector areas must be driven by
              hard-wired (non-plastic) input only; the server's wireheading lint
              rejects genomes that violate this.

    When ``plasticity_mode`` is omitted, the server falls back to ``"stdp"`` if
    ``plasticity_flag=True``, otherwise ``"off"``.

    Optional ``max_weight`` and ``plasticity_eta`` forward to the same mapping rule
    keys accepted by :func:`update_cortical_mapping`. LTP/LTD are ``i8``; use
    ``plasticity_eta`` to scale the weight update when a fractional learning rate
    is needed.
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
        plasticity_mode=plasticity_mode,
        eligibility_decay_bursts=eligibility_decay_bursts,
        reward_source_area=reward_source_area,
        punishment_source_area=punishment_source_area,
        max_weight=max_weight,
        plasticity_eta=plasticity_eta,
    )


@mcp.tool()
async def auto_polarity_probe(
    opu_id: str,
    sensor_id: str,
    columns: list[int] | None = None,
    intensity_z: int = 5,
    repeats: int = 3,
    settle_ms: int = 400,
    include_mujoco_physics: bool = False,
    controller_id: str = "mujoco",
) -> dict[str, Any]:
    """Empirically discover OPU column -> sensor direction by force-firing each column.

    For each column ``x`` in ``columns`` (default ``[0, 1]``): force-fire
    ``(x, 0, intensity_z)``, wait ``settle_ms``, snapshot the sensor, and report the
    weighted-z centroid shift. The result is an inferred direction map you can use
    to wire your reflex morphology without manually decoding the embodiment's
    motor convention.

    Set ``include_mujoco_physics=True`` to append MuJoCo
    ``embodiment_get_physics_state`` samples (actuator ``ctrl`` / joint ``qpos``)
    per column so a ``no_change`` in FEAGI’s sensor frame can be compared to
    ground truth from the simulator’s introspection server (requires
    auto-discovered or reachable controller URL).

    Requires the embodiment agent to be subscribed to motor output for ``opu_id``.
    """
    return await feagi.auto_polarity_probe(
        opu_id=opu_id,
        sensor_id=sensor_id,
        columns=columns,
        intensity_z=intensity_z,
        repeats=repeats,
        settle_ms=settle_ms,
        include_mujoco_physics=include_mujoco_physics,
        controller_id=controller_id,
    )


@mcp.tool()
async def probe_area_response(
    stimulus_area: str,
    stimulus_voxels: list[list[int]],
    observe_area: str,
    settle_ms: int = 400,
    observe_window_ms: int = 500,
    lifetime_neuron_cap: int = 64,
) -> dict[str, Any]:
    """Force-fire one cortical area and measure whether a downstream area responds.

    Validates a connection end-to-end without an embodiment agent: it samples the observed
    area's lifetime fire counters, force-fires ``stimulus_voxels`` in ``stimulus_area``, waits
    ``settle_ms`` for propagation, then re-samples. ``responded`` is True when the observed
    area's max consecutive-fire counter increased. Use this after wiring a mapping (e.g. with
    ``build_reflex_mapping`` / ``update_cortical_mapping``) to confirm the circuit actually
    drives the destination before relying on it.

    Args:
        stimulus_area: Cortical id to force-fire (e.g. the source IPU).
        stimulus_voxels: Non-empty list of ``[x, y, z]`` voxels to fire in ``stimulus_area``.
        observe_area: Cortical id to watch for a response (e.g. the destination OPU).
        settle_ms: Wall-clock wait between stimulus and the after-sample.
        observe_window_ms: Sample window (ms) for each activity read.
        lifetime_neuron_cap: Max neurons inspected for lifetime stats per sample.

    Returns:
        ``{"responded": bool|None, "delta_max_consecutive_fire_count", "before", "after",
        "stimulation"}`` or ``{"error": ...}`` on a stimulation failure.
    """
    return await feagi.probe_area_response(
        stimulus_area=stimulus_area,
        stimulus_voxels=stimulus_voxels,
        observe_area=observe_area,
        settle_ms=settle_ms,
        observe_window_ms=observe_window_ms,
        lifetime_neuron_cap=lifetime_neuron_cap,
    )


@mcp.tool()
async def list_controller_bridges() -> dict[str, Any]:
    """List all active controller bridges (xARM, MuJoCo, ROS2, etc.) discovered on this machine.

    Combines two sources:
    1. **Introspection descriptors** written by feagi-desktop when launching
       controllers (scans ``<runtime_root>/controllers/.introspection/``).
    2. **Registered agents** from the FEAGI agent registry (``/v1/agent/list``).

    Use this to check which controllers are running before issuing motor
    commands, stimulating OPU areas, or using embodiment introspection tools.

    Returns:
        ``controllers`` list with introspection URLs, PIDs, matching agent
        registrations, and ``registered_agent_ids`` for cross-reference.
    """
    return await feagi.list_controller_bridges()


@mcp.tool()
async def get_feagi_link_health(controller_id: str = "mujoco") -> dict[str, Any]:
    """Get a compact FEAGI connectivity and registration health snapshot.

    Aggregates:
    - FEAGI core reachability (health endpoint),
    - agent registry and capability registry accessibility,
    - burst engine endpoint accessibility,
    - controller descriptor + matching registration state.

    Use this first when MCP calls start failing intermittently.
    """
    return await feagi.get_feagi_link_health(controller_id=controller_id)


@mcp.tool()
async def get_controller_lifecycle_events(
    controller_id: str = "mujoco",
    since_ts_ms: int | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Read recent desktop/controller lifecycle events from runtime log files.

    This is a read-only diagnostic tool that correlates:
    - desktop lifecycle actions (controller stop/start + experiment stop POST),
    - controller recovery transitions (feagi_unreachable/back_online),
    - Python SDK reconnect markers (disconnect/connect events).

    Use this when a running embodiment appears to stop unexpectedly and you need
    a normalized event timeline without manually parsing multiple log files.

    Args:
        controller_id: Controller bundle id, defaults to ``mujoco``.
        since_ts_ms: Optional unix-ms lower bound filter.
        limit: Maximum events returned (most recent retained).
    """
    return await feagi.get_controller_lifecycle_events(
        controller_id=controller_id,
        since_ts_ms=since_ts_ms,
        limit=limit,
    )


@mcp.tool()
async def get_experiment_stop_cause(
    controller_id: str = "mujoco",
    since_ts_ms: int | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    """Infer likely experiment-stop cause from lifecycle event chronology.

    Produces a compact verdict + evidence window around the latest stop marker.
    Typical outcomes:
    - ``manual_or_external_stop_command``
    - ``recovery_reconnect_transition_then_stop``
    - ``no_stop_events_found``
    """
    return await feagi.get_experiment_stop_cause(
        controller_id=controller_id,
        since_ts_ms=since_ts_ms,
        limit=limit,
    )


@mcp.tool()
async def get_agent_joint_map(agent_id: str) -> dict[str, Any]:
    """Get a focused joint-to-OPU cortical area mapping for a registered agent.

    Parses the agent's device registrations and extracts a flat list of joints
    with their OPU cortical area IDs, group/channel indices, control modes,
    and angle ranges. Use this to understand which cortical areas to stimulate
    in order to drive specific robot joints.

    Args:
        agent_id: Agent identifier (from ``get_registered_agents``).

    Returns:
        ``joints`` list with per-joint metadata and ``opu_cortical_ids`` for
        stimulation targeting.
    """
    return await feagi.get_agent_joint_map(agent_id)


@mcp.tool()
async def send_motor_command(
    agent_id: str,
    joint_name: str,
    target_value: float,
) -> dict[str, Any]:
    """Drive a specific robot joint to a target angle/position via OPU stimulation.

    This is a high-level convenience tool that:
    1. Looks up the joint's OPU cortical area from the agent's device registrations.
    2. Retrieves the OPU geometry to determine voxel resolution.
    3. Maps the target value to a voxel X coordinate using the joint's range.
    4. Fires that voxel via ``stimulate_area``.

    **Prerequisites:**
    - The controller bridge must be running (check with ``list_controller_bridges``).
    - The agent must be registered (check with ``get_registered_agents``).
    - The burst engine must be running (check with ``get_burst_engine_status``).

    Use ``get_agent_joint_map`` first to discover available joint names and
    their value ranges.

    Args:
        agent_id: Agent identifier (from ``get_registered_agents``).
        joint_name: Joint name as reported by ``get_agent_joint_map``
            (case-insensitive match).
        target_value: Target angle/position in the joint's native units
            (degrees for servo motors).

    Returns:
        Stimulation result with resolved cortical area, voxel coordinate,
        and the value-to-voxel mapping used.
    """
    return await feagi.send_motor_command(agent_id, joint_name, target_value)


@mcp.tool()
async def embodiment_discover_introspection_endpoint(
    controller_id: str = "mujoco",
) -> dict[str, Any]:
    """Locate a controller's introspection HTTP endpoint via the launcher descriptor.

    feagi-desktop's launcher allocates an ephemeral port for each controller
    that supports introspection and writes a descriptor at
    ``<runtime_root>/controllers/.introspection/<controller_id>.json``. This
    tool reads that descriptor so the MCP can talk to the controller without
    requiring the URL to be configured up front.

    Use ``list_controller_bridges`` to discover all controller IDs with
    descriptors on this machine.

    Returns ``{"found": True, "url": "http://127.0.0.1:<port>", ...}`` when
    the controller is up, or ``{"found": False, ...}`` otherwise. The
    descriptor metadata (PID, controller version, started_at) is included
    when present so callers can sanity-check the endpoint.
    """
    return await feagi.embodiment_discover_introspection_endpoint(controller_id)


@mcp.tool()
async def embodiment_get_physics_state(
    introspection_url: str | None = None,
    timeout_s: float = 2.0,
    controller_id: str = "mujoco",
) -> dict[str, Any]:
    """GET ground-truth physics state from an embodiment controller.

    Works with any controller that exposes ``GET /v1/state`` on its
    introspection server (e.g. MuJoCo, xARM when introspection is enabled).
    When ``introspection_url`` is omitted, the URL is auto-discovered via the
    descriptor that feagi-desktop writes at controller spawn time. Pass an
    explicit URL to bypass discovery.
    """
    return await feagi.embodiment_get_physics_state(
        introspection_url=introspection_url,
        timeout_s=timeout_s,
        controller_id=controller_id,
    )


@mcp.tool()
async def embodiment_set_joint_state(
    introspection_url: str | None = None,
    joint_qpos: dict[str, float] | None = None,
    joint_qvel: dict[str, float] | None = None,
    timeout_s: float = 2.0,
    controller_id: str = "mujoco",
) -> dict[str, Any]:
    """Place embodiment joints deterministically (e.g. tilt pendulum, position arm).

    Useful to verify a reflex circuit responds correctly at a given physical
    state without waiting for the dynamics to wander there organically. Works
    with any controller exposing ``POST /v1/set_state`` on its introspection
    server. When ``introspection_url`` is omitted, the URL is auto-discovered
    via the launcher-written descriptor.
    """
    return await feagi.embodiment_set_joint_state(
        introspection_url=introspection_url,
        joint_qpos=joint_qpos,
        joint_qvel=joint_qvel,
        timeout_s=timeout_s,
        controller_id=controller_id,
    )


@mcp.tool()
async def embodiment_reset_simulation_time_stats(
    introspection_url: str | None = None,
    timeout_s: float = 2.0,
    controller_id: str = "mujoco",
) -> dict[str, Any]:
    """Reset the session max simulation clock (benchmark high-water mark).

    Proxies to ``POST <introspection_url>/v1/reset_simulation_time_stats`` on
    the controller's introspection server. Use before a new "longest time
    upright" trial. Auto-discovery matches ``embodiment_get_physics_state``.
    """
    return await feagi.embodiment_reset_simulation_time_stats(
        introspection_url=introspection_url,
        timeout_s=timeout_s,
        controller_id=controller_id,
    )


@mcp.tool()
async def composer_list_simulator_packs(
    engine: str | None = None,
    kind: str | None = None,
    state: str = "active",
) -> dict[str, Any]:
    """Query Composer public catalog of shared simulator asset packs (GCS-backed).

    Maps to Composer ``GET /v1/public/global/simulator-packs`` (staging/production).
    Requires ``FEAGI_COMPOSER_BASE_URL``. Use filters to shrink results (e.g. ``engine=mujoco``).

    Returns:
        Composer JSON body (typically ``data`` array) plus ``http_status`` when non-success.
    """
    return await composer_sim_packs.list_simulator_packs(engine=engine, kind=kind, state=state)


@mcp.tool()
async def composer_get_simulator_pack_versions(
    pack_id: str,
    engine: str | None = None,
) -> dict[str, Any]:
    """List semver versions indexed for ``pack_id`` on Composer.

    ``GET .../simulator-packs/{pack_id}``. Use before requesting a resolved manifest.
    """
    return await composer_sim_packs.get_pack_version_summary(pack_id, engine=engine)


@mcp.tool()
async def composer_get_simulator_pack_resolved(
    pack_id: str,
    semver: str,
    engine: str | None = None,
) -> dict[str, Any]:
    """Resolved pack manifest with per-file HTTPS URLs (include.xml, LICENSE, etc.).

    ``GET .../simulator-packs/{pack_id}/versions/{semver}/resolved``.
    After ``composer_download_simulator_pack_bundle``, point MJCF ``include``
    entries at paths under ``output_directory``.
    """
    return await composer_sim_packs.get_pack_resolved(pack_id, semver, engine=engine)


@mcp.tool()
async def composer_download_simulator_pack_bundle(
    output_directory: str,
    pack_id: str,
    semver: str,
    engine: str | None = None,
) -> dict[str, Any]:
    """Download every file listed in the resolved manifest into ``output_directory``.

    Creates the directory tree as needed; writes ONLY flat basename keys from Composer
    (e.g. ``include.xml``, ``manifest.json``, ``LICENSE``).

    Useful to place pack assets beside an embodiment ``scene.xml`` for MuJoCo ``include``.
    Requires network access from the MCP process to ``storage.googleapis.com``.
    """
    return await composer_sim_packs.download_pack_bundle(
        output_directory,
        pack_id,
        semver,
        engine=engine,
    )


def main() -> None:
    """Run the FEAGI MCP server."""
    logger.info("Starting FEAGI MCP Server...")
    logger.info(f"Connecting to FEAGI at {config.host}:{config.port}")
    if composer_sim_packs.enabled:
        logger.info(
            "Composer simulator packs: FEAGI_COMPOSER_BASE_URL is set (%s)",
            config.composer_base_url.strip().rstrip("/"),
        )

    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:

        async def _shutdown_clients() -> None:
            await feagi.close()
            await composer_sim_packs.close()

        asyncio.run(_shutdown_clients())


if __name__ == "__main__":
    main()
