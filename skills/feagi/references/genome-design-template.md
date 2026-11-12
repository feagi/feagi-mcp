# Genome design: document template

Copy this structure for every design from [genome-design.md](genome-design.md). The section
order and table headers are fixed: the user, the architect and the next stage read the same
columns every time, and a missing cell is visible. Fill the tables before the first create
call. No cortical IDs anywhere: region and area names only.

## Contents

- Section order
- Intake
- Modules, ports, budget, influence
- Layout: 2D map and 3D scene
- Schematic
- Stages and cost line

## Section order

1. Answer first (two sentences: the design in one line, the one open question or "none")
2. Intake
3. Modules
4. Ports
5. Budget
6. Influence
7. Layout
8. Schematic
9. Stages
10. Cost line

Length: about 6-9k characters when condensed, 12-18k in full. Cut prose, never a table row.

## Intake

Goal: one measurable outcome as a number, the tool that reads it, the baseline value.

| Never | Hard-wired veto |
|---|---|

One row per item that must never happen (fall wired to Death, servo range, runaway or silent
population, reward wireheading, full memory pool). A row without a veto is not done.

| Fact | Value | Read or assumed | Read with |
|---|---|---|---|

One row per fact the design depends on (burst rate and its derivation, neuron and synapse caps,
joint list, registered I/O areas, existing regions, Hub result). Write `read` only when a call in
this task returned it; otherwise `assumed`, and say how the first stage confirms it.

## Modules, ports, budget, influence

**Modules:** one row per region, no empty cells (write `none` or `n/a`).

| Region | Function | Inputs | Outputs | Mechanism | Learns? | Acceptance (number) | Measured with (tool) |
|---|---|---|---|---|---|---|---|

Every region needs its own acceptance number and tool, including adapter, safety and
learning-harness regions. Learns? is `no`, or the plastic rule and the modulator that freezes it.

**Ports:** one row per module port.

| Port | Shape | Code | Sign | Latency (bursts) | Driven by |
|---|---|---|---|---|---|

**Budget:** one row per mapping rule, not per module, then the totals line.

| Src | Dst | Rule | Synapses | Active fraction | Plastic? |
|---|---|---|---|---|---|

Totals line: neurons, synapses, events per burst, estimated ms per burst, loop latency in bursts
and seconds. Formulas per rule: "Efficiency budget" in [genome-design-budget.md](genome-design-budget.md).
Mark estimates `[model]` and measured values `[measured]`.

**Influence:** one row per module output that feeds a modulator driver or a shared command.

| Module output | Modules affected | Intended? | Mitigation | Lag (bursts) | Subscribed mapping |
|---|---|---|---|---|---|

Subscribed mapping is `src -> dst, rule` for the mapping the modulator is subscribed to (made
with `set_mapping_modulators(src_area, dst_area, modulator_ids, morphology_id)`), or the area for
`set_area_modulators(cortical_id, modulator_ids)`. `none` for an output that only feeds a
command.

## Layout: 2D map and 3D scene

Decide positions before any create call: a circuit that reads left to right in the 2D brain
map and module by module in the 3D scene is easy to review and stays uncluttered. Mechanics:
[building-circuits.md](building-circuits.md) "Workflow" step 2 and [building-circuits-placement.md](building-circuits-placement.md) "Placement".

| Region | 2D (x, y) | 3D anchor | Layout | Areas |
|---|---|---|---|---|

One row per region, plus one row for modulator drivers and vetoes and one for I/O. Layout is
the `suggest_cortical_anchor_positions()` value (`xy_plane`, `hierarchy_y`, `temporal_z`).

**2D brain map**

- One row per layer in signal-flow order: sense, feature, decide, act, adapt. A row is one y
  value; regions in the row run left to right in signal-flow order.
- The step between regions is one map step, about 120 voxels
  ([building-circuits-placement.md](building-circuits-placement.md) "Placement"). Do not multiply it by the
  title length. Read `coordinate_2d` with `get_brain_regions()` first. If the next region
  on a row would land within one map step of another title, put it on the next y instead.
- Always pass `coordinates_2d` to `create_brain_region()` and to spec builds. A
  `build_circuit_from_spec()` region without `coordinates_2d` extends the existing row, which
  breaks the layer rows.

**3D scene** (the Brain Visualizer camera looks toward +Z)

- One layer per Y, one map step (about 120 voxels) above the layer below. Do not multiply
  that step by the title length.
- If a module on that Y would land within one map step of another title, a core area, or
  an I/O area, put it on the next Y. Do not stretch X to escape the cluster.
- A module's stages run along one axis, chosen by the `suggest_cortical_anchor_positions()`
  layout: `hierarchy_y` for shallow stages, `temporal_z` for chains. Area anchors inside
  the module are 32 voxels apart. That area gap is not the gap between modules.
- IPU and OPU areas are auto-placed by FEAGI: the layout table marks them `auto-placed`. Only
  the adapter region is positioned, next to the agent's existing I/O areas (read them with
  `list_io_areas_compact()`).
- Modulator drivers and vetoes get a row of their own above the module they gate (higher Y than
  its stages), so a gate is visible next to what it gates.
- Every area belongs to its module's region. Stray areas (a create call without
  `brain_region_id`) move with
  `brain_visualizer_api(operation_id="put_region_relocate_members", ...)`.
- The schematic's node order equals the scene order, so Brain Visualizer reads like the diagram.

## Schematic

`show_in_studio` kind `circuit`, one fenced block in the document. Allowed layouts, fields and limits:
[building-circuits.md](building-circuits.md) "Circuit diagram format".

```json
{"v": 1, "title": "<design name> (design)", "layout": "horizontal",
 "nodes": [
  {"id": "in_a", "label": "<Region> > <area>", "layer": 0},
  {"id": "feat_a", "label": "<Region> > <area>", "layer": 1},
  {"id": "dec_a", "label": "<Region> > <area>", "layer": 2},
  {"id": "drv", "label": "<Region> > <driver area>", "layer": 3}],
 "edges": [
  {"from": "in_a", "to": "feat_a", "label": "block_to_block, +"},
  {"from": "feat_a", "to": "dec_a", "label": "<custom morphology name>, -, plastic"},
  {"from": "drv", "to": "dec_a", "label": "modulator synaptic.reward, +"}]}
```

- **Node:** `{id, label, layer}`. `id` is a slug, `label` is `Region > area`, `layer` is 0 sense,
  1 feature, 2 decide, 3 act, 4 adapt. List nodes in scene order (Layout).
- **Edge label is exactly `<rule>, <sign>`.** Rule is a core morphology name or the name of the
  custom morphology you create (a purpose word, a mechanism or a pattern string is not a
  rule). Sign is the sign of that rule's `postSynapticCurrent_multiplier`: `+` or `-`. One sign
  per rule, so draw one edge per rule. `+/-` is allowed only when one edge stands for two
  rules (for example centre excitation plus surround inhibition), and then each rule has its own
  row in the budget table.
- **Plastic rules** append `, plastic`: `<rule>, <sign>, plastic`.
- **Modulator driver edges** are not rules: a driver reaches a mapping through
  `set_mapping_modulators()`, not a morphology. Label them `modulator <type>, <sign>` (for
  example `modulator synaptic.reward, +`, the sign of the modulator's `magnitude_percent`) and
  draw them to the destination node of the subscribed mapping. The Influence table names that
  mapping.
- Every budget-table row appears as an edge (or as half of a `+/-` edge), and the reverse.

## Stages and cost line

| Stage | Level | Builds | Acceptance (number) | Measured with (tool) |
|---|---|---|---|---|

One row per stage, in build order: baseline first, then each module (sense to act), safety
vetoes, learning last. Level is behavior, region, mapping or synapse. Every row has a number
and the tool that reads it; no region is left without a row. Stop rule per stage: two failed
checks stop and report.

End the report with one line:

`Design cost: N tool calls, N reference reads`

Count tool calls from this task's own call log, one per call, and reference reads as the
skill files and sections loaded. The user sees what each design cost.
