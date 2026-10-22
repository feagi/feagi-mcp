---
name: feagi
description: Inspect, build, wire, test, and debug brains in a running FEAGI instance through the feagi MCP server. Use whenever the user mentions FEAGI, a genome or connectome, cortical areas, brain regions or "circuits", IPU/OPU/CUSTOM/MEMORY areas, morphologies or connectivity rules, mappings, plasticity/STDP, the burst engine, Brain Visualizer, Neurorobotics Studio, or a robot/MuJoCo embodiment driven by FEAGI. Covers FEAGI vocabulary, naming and placement policy, reuse-first wiring, verification, and diagnostics.
license: Apache-2.0
compatibility: Requires the feagi MCP server (PyPI package feagi-mcp) connected to a reachable FEAGI API (default localhost:8000).
metadata:
  author: Neuraville Inc.
  homepage: https://feagi.org
---

# FEAGI

FEAGI (Framework for Evolutionary Artificial General Intelligence) is a platform for building
and running artificial brains made of spiking neurons arranged in 3D voxel grids. A running
FEAGI instance holds one **genome** (the blueprint) and the **connectome** grown from it, and
drives it in discrete time steps called **bursts**. Robots and simulators connect as **agents**
that feed sensor data in and read motor commands out.

You reach the running instance through the `feagi` MCP server. Every fact about the user's
brain comes from those tools. FEAGI is not human neuroscience: never answer with anatomy
(prefrontal cortex, V1, Broca's area) unless those names appear in tool results.

Tool names below end in `()`, for example `health_check()`. Depending on the host they may
appear with a prefix such as `mcp__feagi__`. If no FEAGI tools are available, read
[references/setup.md](references/setup.md) and help the user connect the server instead of
guessing.

## Start of every session

1. `health_check()` to confirm FEAGI answers and see the genome name, area count, burst
   status, and any pending amalgamation. If it fails, go to
   [references/debugging.md](references/debugging.md) and call `diagnose_feagi_runtime()`.
2. `check_live_state_drift()` when a robot or simulator is involved: it lists live state
   that no longer matches the genome or the controller (area dimensions, burst rate, agent
   id, IPU widths) with the call that restores each. Re-apply what you need before building.
3. Pull only what the request needs. Prefer filtered, compact tools (see "Keep responses
   small" below).

## Vocabulary: map the user's words to FEAGI objects

| User says | FEAGI object | Main tools |
|---|---|---|
| "circuit", "region", "group", "new circuit named X" | **Brain region**: a named container in the hierarchy, shown as a circuit in Brain Visualizer. Not a voxel area. | `get_brain_regions()`, `get_region_circuit()`, `create_brain_region()` |
| "area", "cortical area", "layer", "block" | **Cortical area**: a W x H x D voxel grid of neurons | `list_cortical_areas()`, `inspect_cortical_area()`, `create_cortical_area()` |
| "sensor", "input", "camera" | **IPU** area (input processing unit) bound to an agent's sensor | `list_io_areas_compact()`, `list_ipu_areas_with_metadata()` |
| "motor", "output", "joint", "servo" | **OPU** area (output processing unit) bound to an actuator | `list_io_areas_compact()`, `get_agent_joint_map()` |
| "memory" | **MEMORY** area: grows memory neurons from episodic patterns | `list_memory_neurons()`, `get_memory_area_runtime_config()` |
| "connection", "wiring", "mapping", "edge" | **Cortical mapping**: one or more rules from a source area to a destination area | `get_connectivity_summary()`, `get_cortical_mapping()` |
| "rule", "morphology", "connectivity pattern" | **Morphology**: a reusable connectivity pattern used by mapping rules | `describe_connectivity_rules()`, `get_morphology()` |
| "tick", "step", "frame" | **Burst**: one FEAGI time step | `get_burst_engine_status()`, `get_burst_engine_config()` |
| "robot", "simulator", "embodiment", "controller" | **Agent** registered with FEAGI | `get_registered_agents()`, `get_agent_device_registrations()` |
| "neuromodulator", "dopamine-like signal" | **Modulator**: a typed signal with a 1x1x1 driver area | `list_modulators()`, `list_modulator_types()` |

Cortical area IDs are 8-byte values sent as base64 strings (for example ending in `=`). The
first byte names the kind: `i` IPU, `o` OPU, `c` CUSTOM, `m` MEMORY, `_` core. Decode any ID
locally with `interpret_cortical_id()`. Details: [references/concepts.md](references/concepts.md).

## Rules

1. **Tools are the source of truth.** Call a tool before answering anything about the user's
   genome, areas, wiring, activity, or agents. Summarize the actual result. If a tool fails,
   say what failed; never fill the gap with invented data.
2. **Talk in names, not IDs.** Cortical IDs, region UUIDs, and genome IDs go in tool arguments
   only, never in replies, not even as "ID-type" hints. In prose, refer to an area as
   `Region title > Area name`, and mention its type when useful. `get_brain_regions()` lists
   member areas by ID only: translate them with `get_cortical_id_name_mapping()` (one small
   ID-to-name map), not with an unfiltered `list_cortical_areas()`.
3. **Resolve what the user names.** A name may be a circuit (region) or an area. Check region
   titles from `get_brain_regions()` first, then `resolve_cortical_area_by_name()` for areas.
   If both match, say which one you used.
4. **Use defaults, don't interrogate.** For "build", "add", "wire", or "implement" requests,
   pick sensible names, small dimensions, and placements yourself, then act and report what you
   chose. Ask at most one focused question, and only when the choice is genuinely exclusive or
   the genome state blocks progress.
5. **Function-named circuits.** New CUSTOM and MEMORY areas must live in a brain region whose
   title names its function (`Sit`, `Walk CPG`, `OR Gate`). Never parent new work under
   `Autogen Circuit` or `Untitled`; create a region first. Never prefix names with `MCP`,
   `Mcp`, `FEAGI`, or a tool name. See [references/building-circuits.md](references/building-circuits.md).
6. **Reuse rules before inventing them.** Wire with an existing morphology whenever one fits
   (`recommend_connectivity_rules()` then `apply_connectivity_rule()`). Author a custom rule
   only through `propose_connectivity_rule()`, using compact pattern tokens, never an
   enumerated list of voxel pairs. See [references/connectivity.md](references/connectivity.md).
7. **Verify what you build.** After wiring, prove signal flows with `probe_area_response()`
   or `stimulate_area()` plus `monitor_activity()`. Report the result, including failures.
8. **Protect the user's work.** Before anything that replaces or removes structure, take a
   snapshot with `snapshot_genome()` and confirm with the user. That covers `upload_genome()`,
   `load_barebones_genome()`, `load_genome_from_file()`, `restore_genome_snapshot()`,
   `delete_cortical_area()`, `delete_cortical_mapping()`, `delete_modulator()`, and
   `update_cortical_mapping()` or `build_reflex_mapping()` with `replace_existing`. Edits to
   the running genome are not saved to disk until `save_genome_to_filesystem()` runs
   (`health_check()` shows `latest_changes_saved_externally: false` until then); say so after
   a build.
9. **Work in stages, then report gaps.** Build one verifiable stage at a time: create, wire,
   verify with a cheap read, report numbers; stop after two failed checks instead of
   iterating. If the host can route work to other models or subagents, run stages there and
   keep design and review on the strongest model. End every task with the tool, skill,
   controller or core shortcomings that cost time or forced a worse circuit, each marked
   verified or suspected with its smallest fix. See [references/lessons.md](references/lessons.md).

## Keep responses small

Many FEAGI payloads are large. Prefer the compact tool, and widen only when needed. Issue
independent calls together in one turn, and never poll physics or logs in a loop.

| Instead of | Use |
|---|---|
| unfiltered `list_cortical_areas()` | `list_cortical_areas(name_contains=..., cortical_type=...)` or `list_cortical_area_names()` |
| `list_ipu_areas_with_metadata()` / `list_opu_areas_with_metadata()` | `list_io_areas_compact()` |
| `get_cortical_map_detailed()` + `get_brain_regions()` for one region | `get_region_circuit()` |
| `get_connectivity()` across many pairs | `get_connectivity_summary(src_filter=...)` |
| `inspect_cortical_areas_batch()` | `inspect_cortical_areas_minimal()` |
| `list_morphologies()` | `list_morphologies_summary()`, or `get_morphology()` for one rule |
| `get_agent_device_registrations()` on a large body | `get_motor_group_summary()` or `get_agent_joint_map()` |
| `get_log_tail()` unfiltered | `get_log_tail(message_contains=...)` or `get_last_failed_mutation()` |

`monitor_activity()`, `get_sensor_snapshot_last()`, `get_voxel_neurons()`, and
`list_area_synapses()` already default to summaries. Ask for raw rows only when needed.

## What do you want to do?

| Goal | Start with | Reference |
|---|---|---|
| Describe the genome, list circuits or areas | `get_genome_info()`, `get_brain_regions()`, `list_cortical_areas()` | [concepts.md](references/concepts.md) |
| Explain one circuit's inputs, outputs, and edges | `get_region_circuit()` | [concepts.md](references/concepts.md) |
| Build a new circuit (gate, CPG, reflex, controller) | `create_brain_region()`, `suggest_cortical_anchor_positions()`, `create_cortical_area()` | [building-circuits.md](references/building-circuits.md) |
| Connect area A to area B | `recommend_connectivity_rules()`, `apply_connectivity_rule()` | [connectivity.md](references/connectivity.md) |
| Learning: STDP, R-STDP, memory areas, time series | `get_memory_area_runtime_config()`, `set_memory_mp_encoding()` | [memory-and-plasticity.md](references/memory-and-plasticity.md) |
| Classifiers, segmentation, depth maps, value planes | `inspect_classifier()`, `wire_value_passthrough()` | [value-planes-and-classifiers.md](references/value-planes-and-classifiers.md) |
| Neuromodulators | `list_modulator_types()`, `create_modulator()` | [memory-and-plasticity.md](references/memory-and-plasticity.md) |
| Test or debug signal flow, a silent output, a dead FEAGI | `probe_area_response()`, `trace_signal_path()`, `diagnose_feagi_runtime()` | [debugging.md](references/debugging.md) |
| Robots, joints, MuJoCo scenes, simulator assets | `get_registered_agents()`, `get_agent_joint_map()`, `get_mujoco_scene_config()` | [embodiment.md](references/embodiment.md) |
| Measure robot behavior (balance, episodes, brain-to-body timing) | `measure_balance()`, `record_aligned_trace()` | [embodiment.md](references/embodiment.md) |
| Save, snapshot, load, or merge genomes | `snapshot_genome()`, `save_genome_to_filesystem()`, `queue_amalgamation_by_payload()` | [genome-lifecycle.md](references/genome-lifecycle.md) |
| Find a tool for anything else | | [tool-index.md](references/tool-index.md) |

## Core workflows

### Answer "what's in my brain?"

1. `get_brain_regions()` for the circuit tree (titles, member counts, designated inputs and
   outputs).
2. `get_cortical_id_name_mapping()` to name the member areas; `list_cortical_areas()` with a
   filter only when you also need types or dimensions.
3. Present circuits by title with area counts and a few representative area names. Areas that
   sit directly in the root region belong to no circuit: list them separately, typed with
   `list_io_areas_compact()` (inputs and outputs) and `list_cortical_areas(cortical_type="CORE")`.
   Do not infer types from the root region's `inputs`/`outputs` lists. No IDs.
4. Area names are not unique. When two areas share a name, qualify with the region; if they
   share a region too, add type or dimensions, or give a count ("3 areas named forward").

### Explain how one circuit is wired

1. Resolve the circuit by title in `get_brain_regions()`.
2. `get_region_circuit(region_id)`: members with names, boundary inputs and outputs, and edges
   (internal, incoming, outgoing). Edges carry no rules.
3. For rules and gains, `get_connectivity_summary(src_filter=<full cortical ID>)` per member
   that sends edges, issued in parallel. Filters match ID substrings, so always pass a
   complete ID.
4. Describe the flow in stages (input, intermediate, output) by area name, with the rule and
   sign (excitatory or inhibitory) on each edge, and where the outputs go outside the circuit.
   An edge with an excitatory and an inhibitory rule (rows sharing `edge_morphologies`) is one
   connection with surround inhibition; describe it as a pair.

### Build a circuit

1. Name the function. `get_brain_regions()` to reuse a matching region, otherwise
   `create_brain_region(title=<function>, coordinates_2d, coordinates_3d)` under the root, with
   coordinates next to the existing regions (see
   [building-circuits.md](references/building-circuits.md)).
2. After the region exists, `suggest_cortical_anchor_positions(count, parent_region_id, layout)`
   to place the new areas near it. Without a parent it falls back to a default far from the
   rest of the brain.
3. `create_cortical_area()` for each area, with `brain_region_id`, role-based names, and the
   smallest dimensions that do the job (often `[1, 1, 1]` for logic).
4. Wire each edge (next workflow), then verify with `probe_area_response()`.
5. Summarize what was created, and offer `save_genome_to_filesystem()`.

### Wire A to B

1. Resolve both IDs. Check what exists with `get_cortical_mapping(src, dst)`.
2. `recommend_connectivity_rules(src, dst, intent="...")` and pick the best existing rule.
3. `apply_connectivity_rule(src, dst, intent="...", postsynaptic_current_multiplier=...)`.
4. If no rule fits, `propose_connectivity_rule()` and then `build_reflex_mapping()` with its
   compact patterns.
5. Verify: `probe_area_response(stimulus_area=src, stimulus_voxels=[[0,0,0]], observe_area=dst)`.

### Find why an output does not respond

1. `trace_signal_path(from_area, to_area)` to find a path, and `get_connectivity_summary()`
   for the rules on it.
2. `get_cortical_synapse_counts()` and `list_area_synapses(direction="incoming")` to confirm
   synapses actually exist.
3. `inspect_cortical_areas_minimal()` along the path: thresholds, leak, refractory, and the
   burst-engine flag.
4. `probe_area_response()` hop by hop to find the first silent link.
5. For OPUs, `get_motor_snapshot_last()` to see whether commands leave FEAGI at all.

## Product context

FEAGI's desktop app is **Neurorobotics Studio**. Its 3D editor is **Brain Visualizer** (BV),
where brain regions appear as circuits. Its built-in chat assistant, **Hey FEAGI**, uses this
same MCP server. Shared genomes come from the **Brain Hub** catalog in the desktop app, and
merging one into a running brain is called **amalgamation**. More at https://feagi.org.
