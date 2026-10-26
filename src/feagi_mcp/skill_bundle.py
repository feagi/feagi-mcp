"""FEAGI agent skill bundle: location and generated tool index (pure; no FEAGI I/O).

The skill lives at ``skills/feagi/`` in the repository root, which is also the Claude
Code plugin root (``.claude-plugin/plugin.json``). Wheels ship the same folder as
``feagi_mcp/skills/feagi`` so hosts such as Hey FEAGI can load it from an install.

``references/tool-index.md`` is generated from the ``@mcp.tool()`` functions in
``server.py``; run ``python scripts/generate_skill_tool_index.py`` after adding,
renaming, or removing a tool. Every tool must be listed in ``TOOL_CATEGORIES``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SKILL_NAME = "feagi"
TOOL_INDEX_RELATIVE_PATH = Path("references") / "tool-index.md"

# Tools that replace or remove genome structure; the skill asks for a snapshot and a
# user confirmation first.
DESTRUCTIVE_TOOLS = frozenset(
    {
        "upload_genome",
        "load_barebones_genome",
        "load_genome_from_file",
        "restore_genome_snapshot",
        "upload_connectome",
        "delete_cortical_area",
        "delete_cortical_mapping",
        "delete_modulator",
        "delete_genome_snapshot",
        "reset_mapping_weights",
        "reset_area_incoming_weights",
    }
)

TOOL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Health and runtime diagnostics": (
        "health_check",
        "get_version_info",
        "get_runtime_metrics",
        "get_feagi_link_health",
        "diagnose_feagi_runtime",
        "get_last_failed_mutation",
        "get_log_tail",
        "get_controller_lifecycle_events",
        "get_experiment_status",
        "get_experiment_stop_cause",
        "check_live_state_drift",
    ),
    "Genome, connectome, and snapshots": (
        "get_genome_info",
        "get_genome_file_name",
        "download_genome",
        "validate_genome",
        "upload_genome",
        "load_genome_from_file",
        "load_barebones_genome",
        "save_genome_to_filesystem",
        "download_region_genome",
        "download_connectome",
        "upload_connectome",
        "snapshot_genome",
        "list_genome_snapshots",
        "restore_genome_snapshot",
        "delete_genome_snapshot",
        "queue_amalgamation_by_payload",
        "confirm_amalgamation_destination",
    ),
    "Brain regions (circuits)": (
        "get_brain_regions",
        "get_region_circuit",
        "create_brain_region",
        "validate_brain_region_hierarchy",
    ),
    "Cortical areas: find and inspect": (
        "list_cortical_areas",
        "list_cortical_area_names",
        "resolve_cortical_area_by_name",
        "get_cortical_id_name_mapping",
        "interpret_cortical_id",
        "explain_cortical_area_naming",
        "inspect_cortical_area",
        "inspect_cortical_areas_batch",
        "inspect_cortical_areas_minimal",
        "get_area_parameters",
        "get_area_semantic_info",
        "get_cortical_area_geometry",
    ),
    "Cortical areas: create and change": (
        "suggest_cortical_anchor_positions",
        "create_cortical_area",
        "update_cortical_area",
        "clone_cortical_area",
        "delete_cortical_area",
        "reset_cortical_neural_state",
        "reset_area_incoming_weights",
        "get_cortical_template",
    ),
    "Input and output areas (IPU/OPU)": (
        "list_io_areas_compact",
        "list_ipu_areas",
        "list_ipu_areas_with_metadata",
        "list_opu_areas",
        "list_opu_areas_with_metadata",
        "compute_io_cortical_id",
        "create_io_area_for_unit",
    ),
    "Connectivity: read": (
        "get_connectivity_summary",
        "get_connectivity",
        "get_cortical_mapping",
        "get_cortical_map_detailed",
        "trace_signal_path",
        "get_cortical_synapse_counts",
        "get_total_synapse_count",
        "list_area_synapses",
    ),
    "Connectivity: rules and wiring": (
        "describe_connectivity_rules",
        "recommend_connectivity_rules",
        "apply_connectivity_rule",
        "propose_connectivity_rule",
        "build_reflex_mapping",
        "update_cortical_mapping",
        "delete_cortical_mapping",
        "list_morphologies_summary",
        "list_morphologies",
        "get_morphology",
        "create_morphology",
        "update_morphology",
        "rename_morphology",
    ),
    "Memory and plasticity": (
        "get_memory_area_runtime_config",
        "set_memory_mp_encoding",
        "list_memory_neurons",
        "inspect_memory_neuron",
        "diagnose_memory_twin_mapping",
        "diagnose_mapping_plasticity",
        "watch_mapping_weights",
        "freeze_mapping_plasticity",
        "reset_mapping_weights",
        "get_fire_ledger_areas_window_config",
    ),
    "Modulators": (
        "list_modulator_types",
        "list_modulators",
        "get_modulator",
        "create_modulator",
        "update_modulator",
        "rename_modulator",
        "modulator_usage",
        "delete_modulator",
        "set_area_modulators",
        "unsubscribe_area_modulator",
        "set_mapping_modulators",
        "unsubscribe_mapping_modulator",
    ),
    "Value planes and classifiers": (
        "list_classifiers",
        "inspect_classifier",
        "create_classifier",
        "update_classifier",
        "attach_classifier_field",
        "wire_value_passthrough",
        "validate_magnitude_passthrough",
        "expand_value_to_bins",
        "decode_class_map",
        "measure_audio_io_disparity",
    ),
    "Activity, stimulation, and neurons": (
        "probe_area_response",
        "stimulate_area",
        "stimulate_area_batch",
        "monitor_activity",
        "monitor_activity_batch",
        "get_fire_queue_detailed",
        "get_sensor_snapshot_last",
        "get_motor_snapshot_last",
        "list_area_neuron_states",
        "inspect_neuron_state_at",
        "get_neuron_state_by_id",
        "get_voxel_neurons",
    ),
    "Burst engine": (
        "get_burst_engine_status",
        "get_burst_engine_config",
        "get_burst_counter",
        "control_burst_engine",
        "pause_burst_engine",
        "resume_burst_engine",
        "set_burst_engine_frequency",
    ),
    "Agents and embodiment": (
        "get_registered_agents",
        "get_agent_liveness",
        "get_agent_properties",
        "get_motor_group_summary",
        "get_agent_joint_map",
        "get_agent_device_registrations",
        "list_agent_capabilities_all",
        "compare_device_registration_store",
        "get_agent_connection_endpoints",
        "send_motor_command",
        "auto_polarity_probe",
        "list_controller_bridges",
        "get_embodiment_status",
        "embodiment_discover_introspection_endpoint",
        "embodiment_get_physics_state",
        "embodiment_set_joint_state",
        "embodiment_reset_simulation_time_stats",
        "measure_balance",
        "record_aligned_trace",
    ),
    "MuJoCo scene and simulator packs": (
        "get_mujoco_scene_config",
        "configure_mujoco_scene",
        "add_mujoco_scene_object",
        "set_mujoco_safety_boundary",
        "composer_list_simulator_packs",
        "composer_get_simulator_pack_versions",
        "composer_get_simulator_pack_resolved",
        "composer_download_simulator_pack_bundle",
    ),
    "Brain Visualizer API pass-through": (
        "list_brain_visualizer_operations",
        "brain_visualizer_api",
    ),
}

# Tools served by the neurorobotics-studio MCP server, not feagi-mcp; they exist only when
# Studio is connected. Listed in the index under their own section and accepted by the
# skill reference check even though server.py does not define them.
STUDIO_ONLY_SECTION = (
    "Studio-only tools (neurorobotics-studio server; "
    "present only when Studio is connected)"
)
STUDIO_ONLY_TOOLS: dict[str, str] = {
    "read_design_notebook": (
        "`read_design_notebook(view?, kinds?, since?, query?, limit?)`: the experiment's design "
        "notebook; the default view is a digest of goal, constraints, baseline, open hypotheses, "
        "dead ends and recent entries."
    ),
    "append_design_note": (
        "`append_design_note(kind, title, body?, metrics?, status?, refs?, amends?, tags?)`: adds "
        "one entry (goal, constraint, baseline, hypothesis, change, measurement, verdict, "
        "dead_end, idea, gap)."
    ),
}


def is_known_tool(name: str, server_tools: set[str] | frozenset[str]) -> bool:
    """True for a feagi-mcp tool or a Studio-only tool."""
    return name in server_tools or name in STUDIO_ONLY_TOOLS


def repository_root() -> Path:
    """feagi-mcp checkout root (``src/feagi_mcp`` is two levels below it)."""
    return Path(__file__).resolve().parents[2]


def skill_dir() -> Path:
    """Directory holding ``SKILL.md``: the packaged copy, else the source checkout."""
    packaged = Path(__file__).resolve().parent / "skills" / SKILL_NAME
    if (packaged / "SKILL.md").is_file():
        return packaged
    source = repository_root() / "skills" / SKILL_NAME
    if (source / "SKILL.md").is_file():
        return source
    raise FileNotFoundError(f"FEAGI skill not found at {packaged} or {source}")


def _is_tool_decorator(decorator: ast.expr) -> bool:
    """True for ``@mcp.tool()`` / ``@mcp.tool``."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == "tool"


def tool_summaries(server_source: str) -> dict[str, str]:
    """Map each ``@mcp.tool()`` function name to its docstring's first line."""
    summaries: dict[str, str] = {}
    for node in ast.walk(ast.parse(server_source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_tool_decorator(d) for d in node.decorator_list):
            continue
        doc = (ast.get_docstring(node) or "").strip()
        summaries[node.name] = doc.splitlines()[0].replace("``", "`") if doc else ""
    return summaries


def tool_parameters(server_source: str) -> dict[str, tuple[str, ...]]:
    """Map each ``@mcp.tool()`` function name to its parameter names."""
    params: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(ast.parse(server_source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _is_tool_decorator(d) for d in node.decorator_list
        ):
            args = node.args
            params[node.name] = tuple(a.arg for a in args.posonlyargs + args.args + args.kwonlyargs)
    return params


def category_problems(tool_names: set[str]) -> list[str]:
    """Tools missing from ``TOOL_CATEGORIES``, listed twice, or no longer registered."""
    problems: list[str] = []
    seen: set[str] = set()
    for category, names in TOOL_CATEGORIES.items():
        for name in names:
            if name in seen:
                problems.append(f"{name} is listed in more than one category")
            seen.add(name)
            if name not in tool_names:
                problems.append(f"{name} in '{category}' is not a registered tool")
    problems.extend(
        f"{name} has no category in TOOL_CATEGORIES" for name in sorted(tool_names - seen)
    )
    return problems


def render_tool_index(summaries: dict[str, str]) -> str:
    """Markdown for ``references/tool-index.md``. Uncategorized tools go under Other."""
    lines = [
        "# FEAGI MCP tool index",
        "",
        "<!-- Generated by scripts/generate_skill_tool_index.py from server.py. Do not edit. -->",
        "",
        f"All {len(summaries)} tools of the feagi MCP server, grouped by task. Tools marked",
        "**Destructive** replace or remove structure: take a `snapshot_genome()` and confirm",
        "with the user first. Use the task references for when and how to call each tool.",
        "",
    ]
    sections = [(c, [n for n in names if n in summaries]) for c, names in TOOL_CATEGORIES.items()]
    other = sorted(set(summaries) - {n for _, names in sections for n in names})
    if other:
        sections.append(("Other", other))
    for category, names in sections:
        if not names:
            continue
        lines += [f"## {category}", ""]
        for name in names:
            marker = " **Destructive.**" if name in DESTRUCTIVE_TOOLS else ""
            summary = summaries[name] or "(no description)"
            lines.append(f"- `{name}()`: {summary}{marker}")
        lines.append("")
    lines += [f"## {STUDIO_ONLY_SECTION}", ""]
    lines += [f"- {desc}" for desc in STUDIO_ONLY_TOOLS.values()]  # desc starts with `name(params)`
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
