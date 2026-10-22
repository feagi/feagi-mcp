# FEAGI concepts and identifiers

## Contents

- Genome, connectome, and bursts
- Brain regions (circuits)
- Cortical areas and their types
- Cortical area IDs
- Neurons and key area parameters
- Presenting results to the user

## Genome, connectome, and bursts

- **Genome**: the blueprint. It lists brain regions, cortical areas with their neuron
  parameters, mapping rules between areas, morphologies, and modulators. Read its metadata
  with `get_genome_info()` and the file label with `get_genome_file_name()`.
- **Connectome**: the neurons and synapses FEAGI grows from the genome. Synapses are rebuilt
  whenever a mapping or area changes. Runtime state (membrane potentials, learned weights)
  lives here, not in the genome.
- **Burst**: one simulation step. Every burst, FEAGI reads sensor input, propagates spikes,
  and writes motor output. Read the rate with `get_burst_engine_config()` and the counter with
  `get_burst_counter()`. Durations in bursts convert to seconds as
  `bursts / burst_frequency_hz`.

Changes made through the tools apply to the running brain immediately, but are not written to
the genome file until `save_genome_to_filesystem()` runs. `health_check()` reports
`latest_changes_saved_externally: false` while there are unsaved changes.

## Brain regions (circuits)

A brain region is a node in a tree that groups cortical areas. Brain Visualizer draws each
region as a **circuit**, so users say "circuit" for a region. There is exactly one root
region (usually titled `Root Brain Region`); every other region has a parent.

Each region record from `get_brain_regions()` carries:

- `title`, `parent_region_id`, child `regions`, and member `areas` (cortical IDs).
- `designated_inputs` / `designated_outputs`: the inputs and outputs the region declares.
- `inputs` / `outputs`: boundary areas inferred from wiring.
- `coordinate_2d` (brain map position) and `coordinate_3d` (3D anchor).

`get_region_circuit(region_id)` returns one region as a graph: members with roles, boundary
input and output areas, and edges split into `internal`, `incoming`, and `outgoing`. A member
is a boundary input when it is an IPU or receives a mapping from outside the region, and a
boundary output when it is an OPU or sends a mapping outside. `isolated_area_ids` lists areas
with no mappings at all.

`validate_brain_region_hierarchy()` checks the tree invariants Brain Visualizer relies on.

## Cortical areas and their types

A cortical area is a 3D grid of voxels, `[width, height, depth]` (X, Y, Z), each holding one
or more neurons (`neurons_per_voxel`). Every area sits at a 3D anchor, `coordinates_3d`.

| Type | ID first byte | What it is |
|---|---|---|
| IPU | `i` | Input area fed by an agent's sensor (camera, joint position, IMU, text, audio). Shape follows the device: X is usually device channels. |
| OPU | `o` | Output area read by an agent's actuator (servo, motor, text out). |
| CUSTOM | `c` | General processing area you design. |
| MEMORY | `m` | Memory area. FEAGI grows memory neurons from patterns arriving over `episodic_memory` mappings. |
| CORE | `_` | Built-in system areas such as power, death, pain, pleasure, fear, fatigue, hope. Do not delete. |

`list_cortical_areas(cortical_type=...)` accepts IPU, OPU, CORE, CUSTOM, MEMORY, SENSORY, and
MOTOR. Name filters accept aliases: `vision`, `simple vision`, and `camera` match the vision
input subtypes (`iimg`, `isvi`, `isvm`, `isig`).

IPU and OPU areas carry a 4-character **subtype**, for example `iimg` simple vision, `isvi`
segmented vision, `idpt` depth map, `iseg` object segmentation mask, `iten` text input,
`icnt` count input, `imis` miscellaneous input, `opse` positional servo, `omot` motor, `oimg`
image output, `oseg` object segmentation output, `oten` text output, `ocnt` count output, and
`omis` miscellaneous output. Ask
`get_area_semantic_info()` what an unfamiliar subtype means. `list_io_areas_compact()` gives the inventory by subtype, along with `dev_count`, and
flags `dimension_dev_count_mismatch` when the width is not `per_device_x * dev_count`.

## Cortical area IDs

An ID is 8 bytes, sent as standard base64 (12 characters ending in `=`).

- Byte 0: the kind letter from the table above.
- For IPU/OPU: bytes 0-3 are the subtype, flag bits encode the I/O configuration (framing,
  positioning, `subunit_index` in bits 4-7 of bytes 4-5), and bytes 6-7 hold the
  little-endian `unit_index` (the device group).
- Decode any ID without a network call: `interpret_cortical_id()`.
- Compute the ID an agent's coder will bind to: `compute_io_cortical_id()`. Create that exact
  area with `create_io_area_for_unit()`, which also verifies the assigned ID.
- `explain_cortical_area_naming()` explains why an I/O area has its title (for example
  `ungrouped-1`).

Brain region IDs are UUIDs. Morphologies and modulators are addressed by name.

## Neurons and key area parameters

Read parameters with `get_area_parameters()` for one area or `inspect_cortical_areas_minimal()`
for several. Change them with `update_cortical_area(cortical_id, updates)`.

| Key (as returned and as passed in `updates`) | Meaning |
|---|---|
| `neuron_fire_threshold` | Membrane potential needed to fire. `neuron_fire_threshold_increment` raises it per voxel along an axis. |
| `neuron_leak_coefficient` | How fast membrane potential decays between bursts (0 = no leak). |
| `neuron_post_synaptic_potential` | Charge a spike delivers (`neuron_post_synaptic_potential_max` caps it). |
| `neuron_mp_driven_psp` | A spike delivers the sender's own potential instead of a fixed PSP. |
| `neuron_psp_uniform_distribution` | Keeps the PSP undivided when it fans out. |
| `neuron_excitability` | Fraction in 0..=1 of bursts a neuron above threshold actually fires (1 = always, 0.25 = one in four). Percent values such as 25 are rejected. |
| `neuron_refractory_period`, `neuron_snooze_period` | Bursts a neuron stays silent after firing. |
| `neuron_consecutive_fire_count` | Limit on back-to-back firing (0 = no limit). |
| `neuron_mp_charge_accumulation` | Whether potential carries over between bursts. |
| `neuron_burst_engine_active` | Whether the area is processed at all. An area with it off never fires. |
| `rate_modulated_leak` | Homeostatic leak that tunes itself toward a target firing rate (dense custom areas). |

`list_cortical_areas()` rows name their shape `cortical_dimensions` and their anchor
`coordinates_3d`.

Mapping rules add their own gain: `postsynaptic_current_multiplier` (PSC multiplier) scales
the weight of every synapse the rule creates.

## Presenting results to the user

- Name areas as `Region title > Area name`. If the region cannot be resolved, use the area name
  alone. If an area has no name, give its type and region.
- Mention type (IPU, OPU, CUSTOM, MEMORY) and subtype when it helps.
- Never print cortical IDs, region UUIDs, or genome IDs in prose, lists, or parentheses.
- For large genomes, summarize by region with counts, and list only what the user asked about.
