# Building circuits

Part 1 of 2: workflow, naming and the `build_circuit_from_spec` spec (templates, `delete`, `edit_areas`). Placement, area creation, editing, pattern sketches and worked examples: [building-circuits-placement.md](building-circuits-placement.md).

## Contents

- Build from a spec
- Workflow
- Naming policy

## Build from a spec

`build_circuit_from_spec(spec_json, dry_run=True)` creates a region, its areas, morphologies and
mappings from one JSON document instead of dozens of calls. Always dry-run first: it returns
`valid`, `errors`, `warnings`, the `sizing` numbers every template computed, the `external` areas
it will look up by name, and the full `calls` list. Then `snapshot_genome()` and run it with
`dry_run=false`. Area `properties` are checked against FEAGI's parameter schema in the dry run (unknown keys and
out-of-range values are errors; a percent such as `neuron_excitability: 100`, the form inspect
returns for some existing areas, is sent as the fraction 1.0 with a warning). The run aborts
before any create when an area name already exists. At the first failure it rolls back what the
call created (its areas, then its region; `rolled_back` lists them and anything it could not
remove; created morphologies stay) and otherwise ends with a `verification` read:
areas found, rules and synapse count per mapping, `zero_synapse` mappings.

```json
{"region": {"title": "Step Generator", "coordinates_2d": [4, 0], "coordinates_3d": [120, 80, 100]},
 "templates": [
  {"template": "port", "name": "Level", "bins": 9, "threshold": 2.5, "psp": 3, "leak": 0.04, "input": 1},
  {"template": "onset_pulse", "name": "Go", "gate": "Gate_Area"},
  {"template": "ring_cpg", "name": "Ring", "bins": 16, "threshold": 6, "psp": 1, "leak": 0.02,
   "drive": "Gate_Area", "drive_d": 0.05, "lateral_psc": 0.5,
   "seed": {"area": "Go_Onset", "bin": 0}, "readouts": [{"name": "Phase", "shift": 0}, {"name": "Phase_Shifted", "shift": 8}]}
 ]}
```

Spec keys: `region` (`{title, coordinates_3d, coordinates_2d?}` or `{region_id}`), `areas`
(`{name, dimensions, position?, properties?}`), `morphologies`, `mappings` (`{src, dst, rules,
replace?}`), `templates`, `defaults` (`origin`, `step`). Without `coordinates_2d` the region is
placed one step past its sibling regions in the same row (the result's `region_coordinates_2d`
says where); given coordinates are sent as is, read back after creation and corrected with one
update if the genome shows another position (`created.region_coordinates_2d.mismatch`).
Rules take the API keys or the shorthand `morphology`, `psc`, `delay`, `plastic`, `scalar`; the
dry run translates and validates the same payload the real run sends, so the two cannot
disagree. Names in `src`/`dst` are spec areas or
live areas; positions default to a grid (40 apart) from the region's `coordinates_3d`. The
numbers in the example are placeholders: read PSP, input per burst and thresholds from your
areas (`inspect_cortical_areas_minimal`) before you size anything.

A port's input per burst is the **source** area's PSP times the mapping's PSC, not the port's own
PSP; read the source's PSP (`inspect_cortical_areas_minimal`) before choosing `input`. Self-hold
cannot bridge gaps in the input: the membrane resets on every fire, so a port whose input drops
out for a burst goes silent. To bridge input gaps add a delay line (a chain of `[1,1,1]` relays
with `synaptic_delay_bursts`, or a second area copying the input one burst later) instead of
raising the self-hold.

| Template | What it makes | Sizing rule it applies |
|---|---|---|
| `port` | `[1,1,N]` leaky integrator, optional self-hold mapping | Self-hold `s = psp x psc` with `threshold - input <= s < threshold`; default is the middle of that interval, `hold_psc` outside it is an error |
| `onset_pulse` | `<name>_Onset`, `<name>_Delay` from a `gate` area | Delay copy inhibits Onset from the next burst; inhibition >= gate input, so Onset fires once |
| `ring_cpg` | `[1,1,N]` ring, self-hold, `lateral_+z` + `last_to_first` excitation (`lateral_psc`, required), `lateral_-z` + `first_to_last` inhibition (default `-lateral_psc`), `drive` via `0-0-0_to_all`, optional `seed`, shifted `readouts` | Self-hold `threshold - d <= s < threshold`. `predicted_step_bursts` uses `V <- V (1-leak) + (p + d)` and is **uncalibrated**: confirm the period with `record_spikes` and adjust `lateral_psc` |
| `servo_channel_two_rest` | `<name>_RestReflex`, `<name>_RestPattern` (`[channels,1,depth]`), a tonic area firing both rest voxels per channel (stance z+1 and z-1), per-source offset rows with `coactive_z` set to the other role's rest voxel, each source inhibiting its own rest neuron | Inhibition `ceil(tonic_psp x tonic_psc / source_psp)` (membrane units); a clamp warning from the offset compiler is an error unless `allow_clamp` |
| `phase_window_gate` | Gate area `<name>` (`[1,1,1]`): `pulse` and optional tonic `enable` excite it, every `phase` bin outside `window` (list or `"a..b"`, of `phase_bins`) inhibits it, it drives `target` | `V <- V (1 - leak) + I`, fire at `V >= T`, steady state with `accumulate`: enable alone < T; pulse alone < T (>= T without enable); enable + pulse >= T; enable + pulse - inhibition < T. Any violation fails the dry run; `inhibit_psc` defaults to the smallest integer that satisfies the last line |

Template options `ring_cpg` `wrap: false` and `servo_channel_two_rest` `exclusive: true`: see [building-circuits-placement.md](building-circuits-placement.md), "Template options".

Spec keys beyond templates: `delete` (`[{src, dst}]`, removes those mappings before the new ones
are written, so a pair can be deleted and rebuilt in one spec) and `edit_areas` (`[{name,
properties}]` on live areas that are members of `region.region_id`, checked against the parameter
schema). New areas in an existing region are ordinary `areas` entries with a `position` under
`region: {region_id}`. A real run does not roll back deletes or edits: `snapshot_genome()` first.

Memory and plasticity in a spec: an area takes `cortical_type: "MEMORY"` (the real run fails
if the id does not start with `m`), memory `properties` (`temporal_depth`, `neuron_init_lifespan`,
`neuron_lifespan_growth_rate`, `neuron_longterm_mem_threshold`, `memory_neuron_cap`,
`ltm_eviction`), `mp_encoding` (`"mp_differential"` or `{mode, delta_quantization}`; change modes
need `temporal_depth` >= 2) and `modulators` (area ids, e.g. `memory.formation`). Rules take
`episodic_memory` (must end in a MEMORY area), `associative_memory` (must start in one),
`plasticity_mode` `stdp`/`rstdp` with `plasticity_window`, `plasticity_eta`, `max_weight`,
`ltp_multiplier`, `ltd_multiplier`, `eligibility_decay_bursts` (rstdp only; rstdp needs
`modulators`) and `delay` >= 1. A mapping can carry `modulators` and `frozen: true`
(frozen through FEAGI's `plasticity_frozen` route after its rules are written and read back;
flag and mode kept; the mapping needs a plastic rule). Illegal combinations fail the dry run; live source/destination
areas are checked for the `m` prefix before anything is created.

Limits: the builder makes CUSTOM and MEMORY areas in one region, sets neuron parameters through
the create path, and does not make IPU/OPU areas (those stay external names). A morphology that already exists is reported `morphologies_reused` and not compared with
the spec's version.

## Workflow

0. **Hub first** (when Studio is connected). `search_brain_hub_genomes` with the task's key
   terms. Show matches with `show_in_studio` (kind `hub_genomes`) only when one is worth
   acting on, and give the user the one-line reason with them; do not assume they saw it. Prefer
   `augment_genome_from_hub` to building from scratch. No match worth acting on: say so in one
   line and build. Do not repeat the search for the same goal unless the plan
   changes. Merge Hub genomes only with `augment_genome_from_hub` / `replace_genome_from_hub`
   so the download and ancestry are recorded.
1. **Name the function** the user wants (`OR Gate`, `Walk CPG`, `Sit`, `Balance`).
2. **Find or create the region.** `get_brain_regions()`; reuse a region already titled for
   this function, otherwise `create_brain_region(title, coordinates_2d, coordinates_3d)`.
   Omit `parent_region_id` to attach under the root. Coordinates:
   - `coordinates_2d` (brain map): read the sibling regions' `coordinate_2d`. Place the new
     region on its signal-flow row (see genome-design-template "Layout"), one map step
     (about 120 voxels) past the previous circuit. Do not multiply that step by the title
     length.
   - `coordinates_3d`: on the next free row for its layer, one map step in Y from the
     circuit below. Area anchors inside the circuit stay 32 voxels apart. Negative values
     are normal. If the same Y would leave it within one map step of another title, a core
     area, or an I/O area, take the next Y instead of stretching X.
3. **Place areas.** (With Studio, before this step append a `hypothesis` note holding the
   acceptance check as a number.) Once the region exists,
   `suggest_cortical_anchor_positions(count, parent_region_id, layout)`. Without
   `parent_region_id` it returns a default far from the rest of the brain.
4. **Create areas** with `create_cortical_area()`, passing `brain_region_id`. Size each input
   against its target's threshold: a source with `neuron_psp_uniform_distribution` off splits its
   PSP over its fan-out, so per-synapse drive is weight x PSP / fan-out (see
   [lessons.md](lessons.md), "PSP is divided across fan-out"). A port that never fires is
   usually subthreshold, not an excitability or core fault.
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

To rescale a pattern morphology's destination z rows by a gain (new morphology, original and mappings untouched), use `scale_morphology_rows(..., dry_run=True)` first: it lists old/new z, clamped rows and the largest gain with no clamp over the used bins.

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
