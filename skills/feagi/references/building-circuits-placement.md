# Building circuits: placement, areas and examples

Part 2 of 2. Workflow, naming and `build_circuit_from_spec` (templates incl. `phase_window_gate`, `delete`, `edit_areas`): [building-circuits.md](building-circuits.md).

## Contents

- Placement
- Creating areas by type
- Editing, cloning, and deleting
- Pattern sketches
- Worked example: OR gate
- Worked example: AND gate
- Template options

## Placement

Two different gaps. Do not use the area gap as the circuit gap.

**Area anchors.** New CUSTOM and MEMORY anchors must be at least 20 voxels from the world
origin and at least 32 voxels from every existing anchor. `create_cortical_area()` enforces
this; `skip_placement_validation=True` bypasses it only when the user insists. Inside one
circuit, keep this grid (40 voxels is the usual step). It keeps areas from sitting on each
other. It does not keep circuit titles readable.

**Circuit titles.** Brain Visualizer draws a region title as a fixed-size billboard
(`REGION_TITLE`, `fixed_size = true` in `UI_BrainMonitor_SceneLabel3D.gd`). The glyphs stay
the same size on screen, and their world width grows with camera distance. There is no
world pitch that keeps those titles apart when the camera frames the whole brain. Do not
spread circuits hundreds of voxels apart to chase that. Zoom in to read a title. Seen
2026-11-01: a pitch of 40 voxels times the title length (720 and up) only hid the overlap
by leaving the brain empty.

- One signal-flow layer per horizontal line. The camera looks toward +Z, so one Y is one line.
- The gap between circuit rows is one map step, about 120 voxels. That is three area steps.
  It is not a multiple of the title length.
- **Close clusters go vertical.** If the next circuit on the same Y would land within one
  map step of another title, a core area, or an I/O area, it is clustered. Put it on the
  next Y, one map step up. Do not stretch X to escape the cluster. Areas inside one
  circuit may still share a Y.
- Modulator drivers sit one map step above the circuit they gate.

**Place by wiring, not by list order.** Read `get_connectivity_summary` before choosing
positions; each circuit goes next to what it connects to. Seen 2026-11-01: all circuits
stacked in one column beside the I/O, with the body adapter at the top, sent every motor
wire across the whole scene.

- Put motor OPUs on one side of the I/O row and IPUs on the other. Signal flows from the
  IPU side toward the OPU side, a layer per row above them.
- The lowest circuit row holds the circuits that write OPUs (body adapter, reflexes,
  posture), each above the OPUs or IPUs it touches.
- A chain (contact gate, then CPG, then pattern former) shares one row and runs toward the
  OPU side. Command and modulator drivers go on the row above the circuit they feed or gate.
  A driver with no mappings sits above the circuit holding the plastic mappings its
  modulator acts on (`list_modulators`).
- Spacing has two values. Inside a circuit and between I/O areas, use the 40-voxel step.
  Between circuit rows, and between the I/O row and the first circuit row, use one map
  step. Measure the row gap from the tallest area of the row below, not from its title.
- Check bounding boxes, not only anchors. I/O areas placed by FEAGI can overlap by width
  (seen: IPUs 5 wide at X 25 to 37), and CORE areas can line up along Z so the camera
  sees one stack. Re-grid them on the 40-voxel step, CORE on its own row (negative Y is
  accepted).
- Move a circuit by one delta applied to its region and every area in it, so its internal
  layout survives.

`suggest_cortical_anchor_positions()` reads live geometry and returns valid anchors near the
parent region. Use it for areas inside a circuit, then check the circuit pitch above before
accepting a position. Layouts (the Brain Visualizer camera looks toward +Z):

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

## Template options

Options of the `build_circuit_from_spec` templates in [building-circuits.md](building-circuits.md).

`ring_cpg` option `wrap: false` (default true) builds a one-shot chain with no `last_to_first` / `first_to_last`; the last bin holds while its drive lasts. Release check: with the drive off every bin must fall silent (self-hold plus next-bin inhibition sized for it, adjacent active bins can latch), confirm with `record_spikes`; a chain with no `seed` warns.

`servo_channel_two_rest` source option `exclusive: true`: rows target `z_target` with no two-rest compensation (edges allowed, `role` optional), and the source inhibits BOTH rest neurons with `exclusive_inhibition_psc` (default `ceil(rest drive / psp)`, must give `psp x psc >= rest drive`). Two exclusive sources on one channel warn unless declared with `mutually_exclusive_with: [area]`.
