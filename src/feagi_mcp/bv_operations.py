"""Brain Visualizer HTTP surface: paths and methods from FEAGIHTTPAddressList.gd.

Every path here matches what Brain Visualizer can call. Used to validate MCP requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class BvOperation:
    """One callable BV operation."""

    operation_id: str
    method: str
    path_template: str
    description: str = ""


# Path templates use {name} for substitution (e.g. {agent_id}).
BV_OPERATIONS: Final[tuple[BvOperation, ...]] = (
    # --- Genome ---
    BvOperation("get_genome_file_name", "GET", "/v1/genome/file_name", "Current genome file label"),
    BvOperation("get_genome_circuits", "GET", "/v1/genome/circuits", "Circuit list"),
    BvOperation("post_genome_save", "POST", "/v1/genome/save", "Persist genome JSON to disk"),
    BvOperation(
        "post_feagi_genome_append",
        "POST",
        "/v1/feagi/genome/append",
        "Append genome structures",
    ),
    BvOperation(
        "post_genome_amalgamation_destination",
        "POST",
        "/v1/genome/amalgamation_destination",
        "Place amalgamation (use query params)",
    ),
    BvOperation(
        "post_genome_amalgamation_by_upload_multipart",
        "POST",
        "/v1/genome/amalgamation_by_upload",
        "Multipart amalgamation upload (use multipart helper)",
    ),
    BvOperation(
        "delete_genome_amalgamation_cancellation",
        "DELETE",
        "/v1/genome/amalgamation_cancellation",
        "Cancel amalgamation (query: amalgamation_id)",
    ),
    # --- Cortical area (read) ---
    BvOperation("get_cortical_area_ipu", "GET", "/v1/cortical_area/ipu", "List IPU area IDs"),
    BvOperation(
        "get_cortical_area_ipu_types", "GET", "/v1/cortical_area/ipu/types", "IPU type metadata"
    ),
    BvOperation("get_cortical_area_opu", "GET", "/v1/cortical_area/opu", "List OPU area IDs"),
    BvOperation(
        "get_cortical_area_opu_types", "GET", "/v1/cortical_area/opu/types", "OPU type metadata"
    ),
    BvOperation(
        "get_cortical_area_id_list",
        "GET",
        "/v1/cortical_area/cortical_area_id_list",
        "All cortical IDs",
    ),
    BvOperation(
        "get_cortical_area_name_list",
        "GET",
        "/v1/cortical_area/cortical_area_name_list",
        "All cortical names",
    ),
    BvOperation(
        "get_cortical_map_detailed",
        "GET",
        "/v1/cortical_area/cortical_map_detailed",
        "Per-area outgoing mapping destinations",
    ),
    BvOperation(
        "get_cortical_id_name_mapping",
        "GET",
        "/v1/cortical_area/cortical_id_name_mapping",
        "Map cortical_id to display name",
    ),
    BvOperation(
        "get_cortical_locations_2d",
        "GET",
        "/v1/cortical_area/cortical_locations_2d",
        "2D layout coordinates",
    ),
    BvOperation(
        "get_cortical_area_geometry",
        "GET",
        "/v1/cortical_area/cortical_area/geometry",
        "3D geometry per area",
    ),
    BvOperation(
        "get_cortical_area_voxel_neurons",
        "GET",
        "/v1/cortical_area/voxel_neurons",
        "Voxel neuron inspection: neurons at (x,y,z) in a cortical area with live properties "
        "and paginated incoming/outgoing synapse details. Use when the user names a cortical "
        "area and voxel coordinates and wants neuron-level detail, connectivity at that voxel, "
        "or debugging (query: cortical_id, x, y, z; optional synapse_page for synapse lists).",
    ),
    BvOperation(
        "get_cortical_area_memory",
        "GET",
        "/v1/cortical_area/memory",
        "Memory cortical area (query params)",
    ),
    BvOperation(
        "get_connectome_memory_neuron",
        "GET",
        "/v1/connectome/memory_neuron",
        "Memory neuron details (query)",
    ),
    BvOperation(
        "get_cortical_types", "GET", "/v1/cortical_area/cortical_types", "High-level types"
    ),
    BvOperation(
        "get_cortical_visibility",
        "GET",
        "/v1/cortical_area/cortical_visibility",
        "Visibility flags",
    ),
    BvOperation(
        "get_genome_cortical_template", "GET", "/v1/genome/cortical_template", "IPU/OPU templates"
    ),
    BvOperation(
        "get_connectome_properties_dimensions",
        "GET",
        "/v1/connectome/properties/dimensions",
        "Connectome dimension properties",
    ),
    BvOperation(
        "get_connectome_properties_mappings",
        "GET",
        "/v1/connectome/properties/mappings",
        "Connectome mapping properties",
    ),
    BvOperation(
        "get_connectome_cortical_areas_list_detailed",
        "GET",
        "/v1/connectome/cortical_areas/list/detailed",
        "Detailed cortical list",
    ),
    BvOperation(
        "get_cortical_area_list",
        "GET",
        "/v1/connectome/cortical_areas/list/detailed",
        "List cortical areas (Rust API; legacy /v1/cortical_area/list in feagi-mcp fallback)",
    ),
    # --- Cortical area (write) ---
    BvOperation(
        "post_cortical_area", "POST", "/v1/cortical_area/cortical_area", "Create IO cortical area"
    ),
    BvOperation(
        "post_custom_cortical_area",
        "POST",
        "/v1/cortical_area/custom_cortical_area",
        "Create custom cortical area",
    ),
    BvOperation(
        "post_cortical_area_clone", "POST", "/v1/cortical_area/clone", "Clone custom/memory area"
    ),
    BvOperation(
        "put_cortical_area", "PUT", "/v1/cortical_area/cortical_area", "Update cortical area"
    ),
    BvOperation(
        "delete_cortical_area",
        "DELETE",
        "/v1/cortical_area/cortical_area",
        "Delete area (query/body)",
    ),
    BvOperation(
        "put_cortical_area_multi",
        "PUT",
        "/v1/cortical_area/multi/cortical_area",
        "Batch update cortical areas",
    ),
    BvOperation(
        "delete_cortical_area_multi",
        "DELETE",
        "/v1/cortical_area/multi/cortical_area",
        "Batch delete cortical areas",
    ),
    BvOperation(
        "post_cortical_area_properties",
        "POST",
        "/v1/cortical_area/cortical_area_properties",
        "Single area properties from connectome",
    ),
    BvOperation(
        "post_multi_cortical_area_properties",
        "POST",
        "/v1/cortical_area/multi/cortical_area_properties",
        "Batch properties (array or cortical_id_list)",
    ),
    BvOperation(
        "post_cortical_name_location",
        "POST",
        "/v1/cortical_area/cortical_name_location",
        "Name/location lookup",
    ),
    BvOperation(
        "put_cortical_area_coord_2d", "PUT", "/v1/cortical_area/coord_2d", "Update 2D coords"
    ),
    BvOperation("put_cortical_area_reset", "PUT", "/v1/cortical_area/reset", "Reset neural state"),
    BvOperation(
        "put_suppress_cortical_visibility",
        "PUT",
        "/v1/cortical_area/suppress_cortical_visibility",
        "Hide/show areas in visualization",
    ),
    # --- Morphology ---
    BvOperation(
        "get_morphology_morphology_list",
        "GET",
        "/v1/morphology/morphology_list",
        "Morphology name list",
    ),
    BvOperation(
        "get_morphology_morphology_types",
        "GET",
        "/v1/morphology/morphology_types",
        "Morphology type enum",
    ),
    BvOperation(
        "get_morphology_list_types", "GET", "/v1/morphology/list/types", "List morphology types"
    ),
    BvOperation(
        "get_morphology_morphologies",
        "GET",
        "/v1/morphology/morphologies",
        "Full morphology definitions",
    ),
    BvOperation("post_morphology", "POST", "/v1/morphology/morphology", "Create morphology"),
    BvOperation("put_morphology", "PUT", "/v1/morphology/morphology", "Update morphology"),
    BvOperation("put_morphology_rename", "PUT", "/v1/morphology/rename", "Rename morphology"),
    BvOperation("delete_morphology", "DELETE", "/v1/morphology/morphology", "Delete morphology"),
    BvOperation(
        "post_morphology_properties",
        "POST",
        "/v1/morphology/morphology_properties",
        "Morphology property query",
    ),
    BvOperation(
        "post_morphology_usage", "POST", "/v1/morphology/morphology_usage", "Morphology usage"
    ),
    # --- Cortical mapping ---
    BvOperation(
        "post_mapping_afferents", "POST", "/v1/cortical_mapping/afferents", "Incoming mappings"
    ),
    BvOperation(
        "post_mapping_efferents", "POST", "/v1/cortical_mapping/efferents", "Outgoing mappings"
    ),
    BvOperation(
        "post_mapping_properties",
        "POST",
        "/v1/cortical_mapping/mapping_properties",
        "Fetch mapping properties",
    ),
    BvOperation(
        "put_mapping_properties",
        "PUT",
        "/v1/cortical_mapping/mapping_properties",
        "Update mapping properties",
    ),
    BvOperation("get_mapping", "GET", "/v1/cortical_mapping/mapping", "Get mapping (query)"),
    BvOperation(
        "delete_mapping", "DELETE", "/v1/cortical_mapping/mapping", "Delete mapping (query)"
    ),
    BvOperation("get_mapping_list", "GET", "/v1/cortical_mapping/mapping_list", "List mappings"),
    BvOperation(
        "post_mapping_batch_update",
        "POST",
        "/v1/cortical_mapping/batch_update",
        "Batch mapping update",
    ),
    BvOperation("post_mapping", "POST", "/v1/cortical_mapping/mapping", "Create mapping"),
    BvOperation("put_mapping", "PUT", "/v1/cortical_mapping/mapping", "Update mapping"),
    # --- Region ---
    BvOperation(
        "get_region_regions_members", "GET", "/v1/region/regions_members", "Brain regions tree"
    ),
    BvOperation("get_region_regions", "GET", "/v1/region/regions", "List regions"),
    BvOperation("get_region_region_titles", "GET", "/v1/region/region_titles", "Region titles"),
    BvOperation(
        "get_region_region_detail",
        "GET",
        "/v1/region/region/{region_id}",
        "Region detail (path param region_id)",
    ),
    BvOperation("post_region_region", "POST", "/v1/region/region", "Create region"),
    BvOperation("put_region_region", "PUT", "/v1/region/region", "Update region"),
    BvOperation("delete_region_region", "DELETE", "/v1/region/region", "Delete region"),
    BvOperation(
        "delete_region_region_and_members",
        "DELETE",
        "/v1/region/region_and_members",
        "Delete region and members",
    ),
    BvOperation(
        "put_region_relocate_members",
        "PUT",
        "/v1/region/relocate_members",
        "Relocate cortical members",
    ),
    BvOperation("post_region_clone", "POST", "/v1/region/clone", "Clone region"),
    BvOperation(
        "put_change_region_parent",
        "PUT",
        "/v1/region/change_region_parent",
        "Change region parent (FEAGI API uses PUT)",
    ),
    BvOperation(
        "put_change_cortical_area_region",
        "PUT",
        "/v1/region/change_cortical_area_region",
        "Move area to region (FEAGI API uses PUT)",
    ),
    # --- Burst engine ---
    BvOperation(
        "get_burst_engine_simulation_timestep",
        "GET",
        "/v1/burst_engine/simulation_timestep",
        "Read simulation timestep",
    ),
    BvOperation(
        "post_burst_engine_simulation_timestep",
        "POST",
        "/v1/burst_engine/simulation_timestep",
        "Set simulation timestep",
    ),
    BvOperation("get_burst_engine_status", "GET", "/v1/burst_engine/status", "Burst engine status"),
    # --- System ---
    BvOperation("get_system_health_check", "GET", "/v1/system/health_check", "Full health payload"),
    BvOperation(
        "get_system_cortical_area_visualization_skip_rate",
        "GET",
        "/v1/system/cortical_area_visualization_skip_rate",
        "Visualization skip rate",
    ),
    BvOperation(
        "put_system_cortical_area_visualization_skip_rate",
        "PUT",
        "/v1/system/cortical_area_visualization_skip_rate",
        "Set visualization skip rate",
    ),
    BvOperation(
        "get_system_cortical_area_visualization_suppression_threshold",
        "GET",
        "/v1/system/cortical_area_visualization_suppression_threshold",
        "Suppression threshold",
    ),
    BvOperation(
        "put_system_cortical_area_visualization_suppression_threshold",
        "PUT",
        "/v1/system/cortical_area_visualization_suppression_threshold",
        "Set suppression threshold",
    ),
    # --- Neuroplasticity ---
    BvOperation(
        "get_neuroplasticity_plasticity_queue_depth",
        "GET",
        "/v1/neuroplasticity/plasticity_queue_depth",
        "Plasticity queue depth",
    ),
    BvOperation(
        "put_neuroplasticity_plasticity_queue_depth",
        "PUT",
        "/v1/neuroplasticity/plasticity_queue_depth",
        "Set queue depth (query: queue_depth)",
    ),
    # --- Insight / monitoring (BV names) ---
    BvOperation(
        "post_insight_neurons_membrane_potential_status",
        "POST",
        "/v1/insight/neurons/membrane_potential_status",
        "Query membrane potential status",
    ),
    BvOperation(
        "post_insight_neuron_synaptic_potential_status",
        "POST",
        "/v1/insight/neuron/synaptic_potential_status",
        "Query synaptic potential status",
    ),
    BvOperation(
        "post_insight_neurons_membrane_potential_set",
        "POST",
        "/v1/insight/neurons/membrane_potential_set",
        "Set membrane potential",
    ),
    BvOperation(
        "post_insight_neuron_synaptic_potential_set",
        "POST",
        "/v1/insight/neuron/synaptic_potential_set",
        "Set synaptic potential",
    ),
    # --- Agent ---
    BvOperation("get_agent_list", "GET", "/v1/agent/list", "List agent IDs"),
    BvOperation("get_agent_properties", "GET", "/v1/agent/properties", "All agent properties"),
    BvOperation(
        "get_agent_capabilities_all",
        "GET",
        "/v1/agent/capabilities/all",
        "Capabilities (query: include_device_registrations)",
    ),
    BvOperation("get_agent_shared_mem", "GET", "/v1/agent/shared_mem", "Shared memory block"),
    BvOperation("post_agent_register", "POST", "/v1/agent/register", "Register agent"),
    BvOperation("post_agent_heartbeat", "POST", "/v1/agent/heartbeat", "Agent heartbeat"),
    BvOperation(
        "post_agent_manual_stimulation",
        "POST",
        "/v1/agent/manual_stimulation",
        "Manual stimulation",
    ),
    BvOperation(
        "post_agent_device_registrations",
        "POST",
        "/v1/agent/{agent_id}/device_registrations",
        "Device registrations (path: agent_id)",
    ),
    # --- Network / input ---
    BvOperation(
        "get_network_connection_info",
        "GET",
        "/v1/network/connection_info",
        "Network connection info",
    ),
    BvOperation("get_input_vision", "GET", "/v1/input/vision", "Vision input config/state"),
    BvOperation("post_input_vision", "POST", "/v1/input/vision", "Configure vision input"),
    # --- Genome download/upload (API) ---
    BvOperation("get_genome_download", "GET", "/v1/genome/download", "Download genome JSON"),
    BvOperation("post_genome_upload", "POST", "/v1/genome/upload", "Upload genome JSON"),
    BvOperation("get_genome_name", "GET", "/v1/genome/name", "Genome name"),
)

BV_OPERATION_BY_ID: Final[dict[str, BvOperation]] = {op.operation_id: op for op in BV_OPERATIONS}


def list_operation_summaries() -> list[dict[str, str]]:
    """Return all operations for MCP discovery."""
    return [
        {
            "operation_id": op.operation_id,
            "method": op.method,
            "path": op.path_template,
            "description": op.description,
        }
        for op in BV_OPERATIONS
    ]


def resolve_path(path_template: str, path_params: dict[str, str] | None) -> str:
    """Fill {placeholders} in path_template."""
    if not path_params:
        if "{" in path_template:
            raise ValueError(f"path_params required for template: {path_template}")
        return path_template
    out = path_template
    for key, value in path_params.items():
        out = out.replace("{" + key + "}", value)
    if "{" in out:
        raise ValueError(f"unresolved placeholders in path: {out}")
    return out
