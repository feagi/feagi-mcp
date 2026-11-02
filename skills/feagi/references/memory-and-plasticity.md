# Memory, plasticity, and modulators

Part 1 of 3: memory areas, encoding, `memory.formation`, time series, modulators. STDP and R-STDP: [memory-plasticity-stdp.md](memory-plasticity-stdp.md). Homeostatic plasticity: [memory-plasticity-homeostatic.md](memory-plasticity-homeostatic.md).

## Contents

- Memory areas
- Membrane-potential encoding modes
- Inspecting memory
- Stop new memories forming (`memory.formation`)
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

Memory neurons have an initial lifespan, growth per re-match, and a long-term threshold
after which they become permanent. A working ECG cascade used init lifespan 9,
lifespan growth 1, and long-term threshold 100. Tune these with `update_cortical_area()`
(keys `neuron_init_lifespan`, `neuron_lifespan_growth_rate`, `neuron_longterm_mem_threshold`;
the window length is `temporal_depth`). Two more keys bound growth: `memory_neuron_cap` (int,
most memory neurons this area may hold; 0 = no per-area cap) and `ltm_eviction` (`lru` or
`none`). The neuron pool is shared by all memory areas; when an area is at its cap or the pool
is full, `lru` evicts that area's least recently reactivated neuron, `none` fails the creation.
`get_memory_area_runtime_config()` shows both, `evicted_total`, `creation_failed_total` and the
`memory_pool`.

**Measured.** A memory neuron fires in the same burst as its matching input, on creation and
on reactivation. `temporal_depth` N makes one neuron per window position. `neuron_init_lifespan`
defaults to 9 bursts, +1 per reactivation; a gap >= the lifespan loses the neuron and its
synapses. A self-held input reactivates it EVERY burst, so long-term thresholds count bursts of
presence.

**Reward consolidates.** On a reward-gated `associative_memory` mapping, a positive reward
that creates or strengthens a synapse between two memory neurons promotes both to long-term at
once, through the normal long-term path (cap and `ltm_eviction` apply). Expiry of a short-term
memory neuron deletes every synapse touching it, so without reward a learned association lasts
only as long as its neurons. Classifier use: [value-planes-and-classifiers.md](value-planes-and-classifiers.md).

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

Changing `temporal_depth`, upstream set or MP mode removes memory neurons that no longer fit
(`memory_neurons_removed`); cap, eviction and lifespan changes keep them.

## Inspecting memory

- `get_memory_area_runtime_config(cortical_id)`: lifecycle settings, encoding, and findings
  such as `memory_no_episodic_upstream` (error) and `memory_neurons_expire_unmatched`
  (neurons were created but none survived).
- `list_memory_neurons()` and `inspect_memory_neuron()`: the neurons an area has grown, their
  lifecycle, and their realized synapses.
- `diagnose_memory_twin_mapping(src_area, dst_area)`: why an episodic mapping did or did not
  create a twin area.

## Stop new memories forming (`memory.formation`)

`memory.formation` is an area-level modulator for memory areas. With its driver active at
-100% the area forms no new memory neurons (other magnitudes do not block: -50 and any positive
value change nothing). Pattern detection still runs, so a known pattern
still reactivates its neuron. Recall and firing of existing memory neurons, short-term aging,
long-term conversion and eviction continue unchanged. Skipped creations are not failures:
they count in `formation_suppressed_total`, not `creation_failed_total`. With no
subscription or a silent driver the area forms memories as usual. Non-memory areas reject it.

**When to use it**
- Hold memory fixed while you measure or test a brain.
- Stop storing patterns during states you do not want remembered (fallen, reset, idle).
- Gate encoding to salient moments: keep the driver active except when something worth
  remembering happens.

**How to wire it**
1. `create_modulator("no_new_memory", {"type": "memory.formation", "magnitude_percent": -100,
   "effect_duration_bursts": 1, "rest_bursts": 0, "graded": false})`. Read the driver area
   id from `get_modulator()`.
2. Pick the signal that should suppress formation (or create a small `1x1x1` area for it) and
   wire it into the driver area with `apply_connectivity_rule()`, the same way the reward
   detector is wired into a `synaptic.reward` driver. The driver counts as active on every
   burst its neuron fires. For a manual hold during a test, a large `effect_duration_bursts`
   keeps the driver on after one `stimulate_area()` (see Model in [modulators.md](modulators.md));
   it stops after that many bursts and then rests `rest_bursts`.
3. `set_area_modulators(memory_area_id, ["no_new_memory"])` on each memory area to suppress.
   The call replaces the list, so include the area's existing modulator ids.
4. Verify with `get_memory_area_runtime_config(memory_area_id)`:
   `lifecycle_totals.formation_suppressed_total` rises while `created_total` stays flat, and
   a `memory_formation_suppressed` finding appears. `modulator_usage()` lists the subscribers.

**Pairing with plastic mappings.** A memory area is not the only learner. For plastic
mappings (`stdp` / `rstdp`) subscribe the rule to a `synaptic.learning_rate` modulator at
-100% on the same driver area (a second `create_modulator()` whose driver is that area, then
`set_mapping_modulators()`). One driver then stops both memory formation and the weight
commits of those mappings; a plain `stdp` associative rule can still create synapses
([modulators.md](modulators.md), recipe 2).

**Design choice.** Whether to suppress is the genome designer's call. The Trainer does not
drive `memory.formation`, and learning on-line during a test may be what you want. Do not add
the modulator to freeze a brain unless the task says to.

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

A modulator is a typed signal with a driver area that retunes subscribed areas, mappings or
memory areas for a few bursts: eight types, from excitability and gain to gating, reward and
`memory.formation`. Model, per-type magnitude semantics, circuit recipes and pitfalls:
[modulators.md](modulators.md).
