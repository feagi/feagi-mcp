# Memory, plasticity, and modulators

## Contents

- Memory areas
- Membrane-potential encoding modes
- Inspecting memory
- Plasticity: STDP and R-STDP
- Time-series memory cascade (ECG and similar signals)
- Modulators

## Memory areas

FEAGI separates two kinds of memory:

- **Episodic (pattern) memory**: a MEMORY area hashes the pattern arriving over
  `episodic_memory` mappings within its temporal window and grows a **memory neuron** for each
  new pattern. Only `episodic_memory` creates memory neurons; a memory area with no episodic
  upstream stays empty.
- **Associative memory**: STDP-based learning on real synapses, wired with
  `associative_memory` mappings. Associative plasticity is legal **from** a memory area, not
  from a non-memory area into memory. Bidirectional association is two one-directional
  mappings (A to B and B to A).

An `associative_memory` mapping from a memory area to a non-memory area (for example a motor
drive) starts with **zero synapses** and that is normal. A synapse is created only when a
neuron in the memory area and a neuron in the destination area both fire inside the rule's
`plasticity_window`. If the rule subscribes to a `synaptic.reward` modulator, the reward
must also be positive in that window. A memory neuron firing on its own never produces a
synapse, so something else (babble, a reflex, or a teacher) must drive the destination
neuron during the window. Check progress with `diagnose_mapping_plasticity(src, dst)` and
`inspect_memory_neuron()` (realized synapses). `get_connectivity()` showing 0 before that
co-firing has happened is not a failure.

Create memory areas with `create_cortical_area(cortical_type="MEMORY", dimensions=[1, 1, 1],
brain_region_id=...)`. The ID must start with `m`; a `c` ID will never form memory neurons.

Memory neurons have a lifecycle: an initial lifespan, growth per re-match, and a long-term
threshold after which they become permanent. A working ECG cascade used init lifespan 9,
lifespan growth 1, and long-term threshold 100. Tune these with `update_cortical_area()`
(keys `neuron_init_lifespan`, `neuron_lifespan_growth_rate`, `neuron_longterm_mem_threshold`;
the window length is `temporal_depth`).

## Membrane-potential encoding modes

`set_memory_mp_encoding(cortical_id, mode, delta_quantization, ratio_quantization)` sets how a
memory area treats membrane potentials (MP), and reports what FEAGI actually runs.

| Mode | A memory matches | Notes |
|---|---|---|
| `none` | Which neurons fired (pattern only) | Use when the upstream is another memory area: its spikes are feature identities, not sample values. |
| `mp_learning` | Absolute MP values, and replays them | |
| `mp_differential` | The same MP *change* across the window (2 to 4 matches 7 to 9) | Needs `temporal_depth` of at least 2. `delta_quantization` is in MP units and must match the sample scale. No replay. |
| `mp_ratio` | The same *growth ratio* (2 to 4 matches 7 to 14) | Needs `temporal_depth` of at least 2. `ratio_quantization` is percent per compounding step. No replay. |

Set `temporal_depth` (with `update_cortical_area()`) before choosing a change mode. Confirm
with `get_memory_area_runtime_config()`, whose `mp_encoding.effective_mode` shows what FEAGI
runs; a `warning` from the set call means FEAGI disabled the change mode.

## Inspecting memory

- `get_memory_area_runtime_config(cortical_id)`: lifecycle settings, encoding, and findings
  such as `memory_no_episodic_upstream` (error) and `memory_neurons_expire_unmatched`
  (neurons were created but none survived).
- `list_memory_neurons()` and `inspect_memory_neuron()`: the neurons an area has grown, their
  lifecycle, and their realized synapses.
- `diagnose_memory_twin_mapping(src_area, dst_area)`: why an episodic mapping did or did not
  create a twin area.

## Plasticity: STDP and R-STDP

Plasticity is configured per mapping rule (`apply_connectivity_rule()`,
`build_reflex_mapping()`, or `update_cortical_mapping()`):

| Field | Meaning |
|---|---|
| `plasticity_flag` | Legacy switch: on means STDP |
| `plasticity_mode` | `off`, `stdp` (correlation-based), or `rstdp` (reward-modulated) |
| `plasticity_constant` | Base learning step |
| `ltp_multiplier`, `ltd_multiplier` | Potentiation and depression steps, 8-bit signed (-128 to 127) |
| `plasticity_window` | Co-activation window, in bursts |
| `max_weight` | Cap on positive weight growth (`stdp` / `rstdp` only) |
| `plasticity_eta` | Learning rate in the weight commit `w += eta * R * e`; default 1.0, use (0, 1] for fine learning |
| `eligibility_decay_bursts` | R-STDP eligibility trace decay in bursts; 0 means reward must coincide with the co-firing burst, 10 to 50 lets a later reward credit earlier co-firing |
| `modulators` | Ids of `synaptic.reward` (and `synaptic.learning_rate` / `synaptic.transmission_gain`) instances the rule subscribes to |

**Reward comes only from `synaptic.reward` modulators.** R(t) is the sum of the subscribed
reward instances' signals (positive magnitude for reward, negative for punishment), read from
their driver areas each burst. The pre-v4 rule fields `reward_source_area` and
`punishment_source_area` are rejected by `update_cortical_mapping`; wire the detector area
into the modulator's driver area instead. A `plasticity_mode: rstdp` rule with no
`synaptic.reward` subscription is rejected too, because R(t) would stay 0 and no weight would
ever change. The usual order is: `create_modulator()` for reward and punishment, wire the
detector areas to the two driver areas, write the plastic rule, then
`set_mapping_modulators(src, dst, [reward_id, punish_id])`, which also switches the rule to
`rstdp` and reports what it changed in `notes`.

Any rule that subscribes to `synaptic.reward` is reward-gated, in `stdp` mode as well: no
potentiation while the reward driver is silent. Confirm learning with
`health_check().synaptic_plasticity_generation` moving and `list_area_synapses()` weights.

Reward and punishment detector areas must be driven only by hard-wired, non-plastic input.
FEAGI's wireheading check rejects genomes where learning can feed its own reward.

FEAGI keeps **fire ledgers** so STDP can see which sources and destinations co-fired. Check
whether a mapping is actually learning with `diagnose_mapping_plasticity(src_area, dst_area)`,
and see per-area ledger windows with `get_fire_ledger_areas_window_config()`.

Do not quote internal parameter names, kernel details, or module paths that tools or this
skill do not show; they change between releases.

## Time-series memory cascade (ECG and similar signals)

For one scalar input sampled once per burst (typically a `[1, 1, 1]` area), build a cascade of
memory areas, each `[1, 1, 1]`, in a function-named region:

| Stage | Reads | Temporal depth | Encoding | Captures |
|---|---|---|---|---|
| Slope | input | 2 | `mp_differential` | One sample-to-sample change |
| Motif | input | 8 | `mp_differential` | A short baseline-invariant shape |
| Contour | input | 32 | `mp_ratio` | A longer scale-invariant contour |
| Motif sequence | motif | 8 | `none` | Which motifs fired, in order |

Wiring:

- input to slope, input to motif, input to contour: `episodic_memory`
- motif to motif sequence: `episodic_memory` and `associative_memory`
- slope to motif, motif to contour, motif sequence to contour: `associative_memory` only
- `synaptic_delay_bursts` at least 1, and the associative `plasticity_window` set to the
  slower stage's depth (8 bursts here) so a feature and the pattern containing it co-fire.

Window length in seconds is `temporal_depth / burst_frequency_hz` (read the rate with
`get_burst_engine_config()`). The input must actually fire: samples below its threshold are
missing from the hash and count as 0 in differential mode. Retune `delta_quantization` when
samples are not order-1 potentials. Confirm the live brain before copying these depths onto an
existing circuit.

## Modulators

A modulator is a typed signal with a `1x1x1` driver area. When the driver fires, subscribed
areas or mappings are modulated for a number of bursts.

- Types (`list_modulator_types()`): `neuro.*` types (`neuro.firing_threshold`,
  `neuro.leak`, `neuro.firing_probability`) modulate neurons in subscribed areas;
  `synaptic.*` types (`synaptic.transmission_gain`, `synaptic.reward`,
  `synaptic.learning_rate`) modulate subscribed mappings.
- Create: `create_modulator(modulator_id, definition)` with `type`, `magnitude_percent`
  (at least -100), `effect_duration_bursts` (at least 1), `rest_bursts`, `graded`, and
  `full_scale_potential` when graded.
- Subscribe: `set_area_modulators(cortical_id, modulator_ids)` for areas,
  `set_mapping_modulators(src_area, dst_area, modulator_ids, morphology_id)` for mappings.
  Both replace the full subscription list.
  Remove one subscription with `unsubscribe_area_modulator()` or
  `unsubscribe_mapping_modulator()`.
- Manage: `list_modulators()`, `get_modulator()`, `update_modulator()`, `rename_modulator()`,
  `modulator_usage()`, `delete_modulator()` (refused while subscribers exist unless forced;
  confirm first).
