# Building circuits

## Contents

- Workflow
- Naming policy
- Placement
- Creating areas by type
- Editing, cloning, and deleting
- Pattern sketches
- Worked example: OR gate

## Workflow

0. **Hub first** (when Studio is connected). `search_brain_hub_genomes` with the task's key
   terms; show good matches with `show_in_studio` (kind `hub_genomes`), say in one line how
   each could help, and prefer `augment_genome_from_hub` to building from scratch. None found:
   say so in one line and build. Do not repeat the search for the same goal unless the plan
   changes. Merge Hub genomes only with `augment_genome_from_hub` / `replace_genome_from_hub`
   so the download and ancestry are recorded.
1. **Name the function** the user wants (`OR Gate`, `Walk CPG`, `Sit`, `Balance`).
2. **Find or create the region.** `get_brain_regions()`; reuse a region already titled for
   this function, otherwise `create_brain_region(title, coordinates_2d, coordinates_3d)`.
   Omit `parent_region_id` to attach under the root. Coordinates:
   - `coordinates_2d` (brain map): read the sibling regions' `coordinate_2d`. They usually sit
     in a row with a regular step; place the new region one step past the largest x, with the
     same y.
   - `coordinates_3d`: near the areas the circuit will connect to (their `coordinates_3d`
     from `list_cortical_areas()`; negative values are normal), at least 32 voxels from other
     anchors.
3. **Place areas.** (With Studio, before this step append a `hypothesis` note holding the
   acceptance check as a number.) Once the region exists,
   `suggest_cortical_anchor_positions(count, parent_region_id, layout)`. Without
   `parent_region_id` it returns a default far from the rest of the brain.
4. **Create areas** with `create_cortical_area()`, passing `brain_region_id`.
5. **Wire** each edge (see [connectivity.md](connectivity.md)).
6. **Verify** with `probe_area_response()` (see [debugging.md](debugging.md)). With Studio,
   append a `measurement` with `metrics`, then a `verdict` that amends the hypothesis.
7. **Report** what you created, by name, and offer `save_genome_to_filesystem()`.
8. **Sharing nudge** (rare): only after a verified acceptance check, or a finished, verified,
   self-contained circuit (a region with clear inputs and outputs). One sentence naming what
   would be shared (genome or connectome, which region), at most once per goal or session,
   never after a decline or while troubleshooting. Published versions cannot be edited or
   deleted but can be superseded; connectomes carry learned data and need two-step consent.
   The user publishes in Studio (Publish version…); you never publish.

Choose defaults instead of asking: role-based names, the smallest dimensions that work
(`[1, 1, 1]` for boolean logic, one voxel column per channel for motor drives), and
placement from the suggestion tool. State what you chose in the summary.

## Naming policy

Names persist in the genome and appear in Brain Visualizer.

**Regions (circuits)** are named for their function: `Sit`, `Sit Drive`, `Walk CPG`,
`OR Gate`, `Balance`. The server rejects placeholder titles (`Autogen Circuit`, `Untitled`,
`New Circuit`, `Circuit`) and `MCP`-prefixed titles. `Autogen Circuit` is the placeholder
region of an untitled genome: never put new CUSTOM or MEMORY areas there.

**Areas** are short (under about 40 characters) and say which circuit and which role:

| Do | Avoid |
|---|---|
| `OrGate_Input_A`, `OrGate_Output` | `Custom1`, `Area_A`, `Test` |
| `Walk_CPG_Hip_FL`, `CPG_Rhythm_Core`, `Motor_FL_Hip` | `McpOrInput`, `FEAGI_Area`, `NewArea_2026` |

Keep one style per project (PascalCase or snake_case with underscores between facets).

## Placement

New CUSTOM and MEMORY anchors must be at least 20 voxels from the world origin and at least
32 voxels from every existing anchor, so labels stay readable in Brain Visualizer.
`create_cortical_area()` enforces this; `skip_placement_validation=True` bypasses it only when
the user insists.

`suggest_cortical_anchor_positions()` reads live geometry and returns valid anchors near the
parent region. Layouts (the Brain Visualizer camera looks toward +Z):

| `layout` | Use for |
|---|---|
| `xy_plane` (default) / `co_occurring_inputs` | Parallel inputs or peers: same Y and Z, spread along +X |
| `hierarchy_y` | Shallow hierarchies: each stage one step along +Y |
| `temporal_z` | Time or deep feedforward chains: stages along +Z |

FEAGI auto-places IPU and OPU areas, so a requested position may be overridden. The create
result's `placement` block reports requested versus actual coordinates and `relocated`.

## Creating areas by type

**CUSTOM**: `create_cortical_area(name, cortical_type="CUSTOM", dimensions=[w, h, d],
position=[x, y, z], brain_region_id=...)`. Optional `neurons_per_voxel`.

**MEMORY**: same call with `cortical_type="MEMORY"`. Memory areas are `[1, 1, 1]`. The tool
sends `sub_group_id: MEMORY`, so FEAGI assigns an ID starting with `m`. An area whose ID
starts with `c` will never form memory neurons: delete it and recreate it as MEMORY. Then
configure it (see [memory-and-plasticity.md](memory-and-plasticity.md)).

**IPU / OPU for a known device**: prefer `create_io_area_for_unit(name, subtype, channels,
depth, ...)`. It derives the canonical ID an agent's coder binds to, creates the area, and
verifies the ID. Use plain `create_cortical_area(cortical_type="OPU" or "IPU", cortical_id=<subtype>,
group_id, device_count, per_device_dimensions, data_type_configs_by_subunit)` only when you
need control the helper does not offer. `get_cortical_template()` lists the available
IPU/OPU templates. Before adding I/O for a robot, check what the agent registered (see
[embodiment.md](embodiment.md)).

## Editing, cloning, and deleting

- `update_cortical_area(cortical_id, updates)` changes neuron parameters, dimensions,
  position, name, or flags. Changes rebuild affected synapses.
- `clone_cortical_area(source_area_id, new_name, coordinates_3d, coordinates_2d,
  parent_region_id, clone_cortical_mapping)` duplicates a CUSTOM or MEMORY area, optionally
  with its mappings.
- `reset_cortical_neural_state(cortical_ids)` clears membrane potentials without touching the
  genome. It keeps learned weights; to reset weights use `reset_area_incoming_weights(cortical_ids)`
  (all incoming mappings of each area; synapse weights back to the rule's initial value, plasticity
  traces cleared, neuron state untouched; snapshot first).
- `delete_cortical_area(cortical_id)` removes the area with all its neurons and synapses.
  Snapshot and confirm first.
- To move areas between regions, use `brain_visualizer_api(operation_id="put_region_relocate_members", ...)`.
  `list_brain_visualizer_operations()` lists every Brain Visualizer operation available
  through that pass-through.

## Pattern sketches

These are starting shapes, not fixed recipes. Confirm rule names with
`describe_connectivity_rules()` and tune against live activity.

- **Logic gate (OR/AND)**: two `[1,1,1]` inputs into one `[1,1,1]` output. OR: each input
  alone drives the output past threshold. AND: tune the output's threshold so one input is
  not enough but two are (worked example below). PSC multipliers are integers, so balance
  with thresholds, not fractional gains.
- **Central pattern generator (CPG)**: a small ring of neurons along Z with a lateral
  (`lateral_+z`-style) self-mapping so activity steps around the ring; leak and PSC set the
  rhythm. Two CPGs with mutual inhibition (negative PSC multiplier) lock in anti-phase for
  left/right or diagonal gaits.
- **Pattern to motor**: CPG phases mapped onto joint drive areas, then onto OPU channels.
  On positional servo OPUs, depth `z=0` is the maximum command (see
  [connectivity.md](connectivity.md)).
- **Sensorimotor loop**: IPU (joint position, IMU) to an error area to a controller area to
  the OPU.
- **Trigger / gate**: a `[1,1,1]` trigger area that enables a behavior circuit; stimulate it
  with `stimulate_area()` to start the behavior.
- **Reflex**: an IPU mapped straight to an OPU with a custom rule
  (`build_reflex_mapping()`); `auto_polarity_probe()` finds which OPU column moves the
  sensor in which direction before you wire it.

## Worked example: OR gate

1. `get_brain_regions()`: no region titled `OR Gate`, root region at a known UUID.
2. `create_brain_region(title="OR Gate", coordinates_2d=[<right of existing>, 0],
   coordinates_3d=[<near related areas>])` returns `region_id`.
3. `suggest_cortical_anchor_positions(count=3, parent_region_id=region_id, layout="xy_plane")`.
4. `create_cortical_area()` three times: `OrGate_Input_A`, `OrGate_Input_B`, `OrGate_Output`,
   each CUSTOM `[1, 1, 1]` in the region.
5. `apply_connectivity_rule(src_area=<input A>, dst_area=<output>, intent="one-to-one identity")`, and
   the same for input B.
6. `probe_area_response(stimulus_area=<input A>, stimulus_voxels=[[0, 0, 0]],
   observe_area=<output>)`, then the same for input B. Both should report `responded: true`.
7. Tell the user: "Created the OR Gate circuit with OR Gate > OrGate_Input_A,
   OR Gate > OrGate_Input_B, and OR Gate > OrGate_Output; each input alone fires the output.
   Changes are live but unsaved." Offer `save_genome_to_filesystem()`.

## Worked example: AND gate

Same structure as the OR gate, in a region titled `AND Gate`, with `AndGate_Input_A`,
`AndGate_Input_B`, and `AndGate_Output`. The difference is the output's threshold.

1. Steps 1 to 4 of the OR gate, with the AND names.
2. Read the inputs' spike strength: `inspect_cortical_areas_minimal(cortical_ids=[<input A>, <input B>])`
   gives `neuron_post_synaptic_potential` (PSP, often 1).
3. Wire each input with `apply_connectivity_rule(src_area=<input>, dst_area=<output>,
   intent="one-to-one identity", postsynaptic_current_multiplier=1)`. One input then delivers
   about PSP x 1 to the output.
4. Make one input insufficient and two sufficient, with no carry-over between bursts:
   `update_cortical_area(cortical_id=<output>, updates={"neuron_fire_threshold": 1.5 * PSP,
   "neuron_mp_charge_accumulation": false})`. If the area leaks
   (`neuron_leak_coefficient` above 0), keep the threshold between one and two inputs' worth
   after leak.
5. Verify all three cases. Input A alone and input B alone:
   `probe_area_response()` should report `responded: false`. Both together:
   `run_stimulus_protocol(steps=[{"label": "A+B", "bursts": 5, "stimuli":
   [{"area_id": <input A>, "coordinates": [[0, 0, 0]]}, {"area_id": <input B>,
   "coordinates": [[0, 0, 0]]}]}], record_areas=[<output>], tail_bursts=3)` should show the
   output firing. Two `stimulate_area()` calls would run one after the other and never overlap.
   (If A and B are voxels of one area, use one stimulus entry with both coordinates.)
6. Report the threshold you chose and why, and that changes are unsaved. PSP and leak are only
   known once the areas exist, so read them after creating instead of assuming.
