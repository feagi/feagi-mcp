# Memory, plasticity, and modulators

Part 1 of 3: memory areas, encoding, `memory.formation`, time series, modulators. STDP and R-STDP: [memory-plasticity-stdp.md](memory-plasticity-stdp.md). Homeostatic plasticity: [memory-plasticity-homeostatic.md](memory-plasticity-homeostatic.md).

## Contents

- Memory areas
- Membrane-potential encoding modes
- Inspecting memory
- Counters, re-match rate and cleanup
- Stop new memories forming (`memory.formation`)
- Freezing learning
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
after which they become permanent. Tune these with `update_cortical_area()`
(keys `neuron_init_lifespan`, `neuron_lifespan_growth_rate`, `neuron_longterm_mem_threshold`;
the window length is `temporal_depth`). Two more keys bound growth: `memory_neuron_cap` (int,
most memory neurons this area may hold; 0 = no per-area cap) and `ltm_eviction` (`lru` or
`none`). The neuron pool is shared by all memory areas; when an area is at its cap or the pool
is full, `lru` evicts that area's least recently reactivated neuron, `none` fails the creation.
`get_memory_area_runtime_config()` shows both, `evicted_total`, `creation_failed_total` and the
`memory_pool`.

`replay_trigger` (circuit design, per memory area) sets which fires replay a neuron's stored
frames onto its twin: `any_fire` (default) or `recall_only` (associative-recall fires only;
live pattern-match and encoding fires do not replay). Design intent, not yet measured.

**Measured.** A memory neuron fires in the same burst as its matching input, on creation and
on reactivation. `temporal_depth` N makes one neuron per window position. `neuron_init_lifespan`
defaults to 9 bursts, +1 per reactivation. A neuron created at burst b and never matched
again expires at the end of burst b + init lifespan (still reactivatable in that burst, as
matching runs before aging); a longer gap loses the neuron and its synapses.
`neuron_lifespan_growth_rate` is truncated to an integer on each reactivation (1.9 grows by 1,
0.5 by 0). A self-held input reactivates it EVERY burst, so long-term thresholds count bursts of
presence.

**Reward consolidates.** On a reward-gated `associative_memory` mapping, a positive reward
that creates or strengthens a synapse between two memory neurons promotes both to long-term at
once, through the normal long-term path (cap and `ltm_eviction` apply). Expiry of a short-term
memory neuron deletes every synapse touching it, so unrewarded associations last only as long
as their neurons. Classifiers: [value-planes-and-classifiers.md](value-planes-and-classifiers.md).

## Membrane-potential encoding modes

`set_memory_mp_encoding(cortical_id, mode, delta_quantization, ratio_quantization)` sets how a
memory area treats membrane potentials (MP), and reports what FEAGI actually runs.

| Mode | A memory matches | Notes |
|---|---|---|
| `none` | Which neurons fired (pattern only) | Use when the upstream is another memory area: its spikes are feature identities, not sample values. |
| `mp_learning` | Absolute MP values, and replays them | |
| `mp_differential` | The same MP *change* across the window (2 to 4 matches 7 to 9) | Needs `temporal_depth` of at least 2. `delta_quantization` is in MP units and must match the sample scale. No replay. |
| `mp_ratio` | The same *growth ratio* (2 to 4 matches 7 to 14) | Needs `temporal_depth` of at least 2. `ratio_quantization` is percent per compounding step. No replay. |

Set `temporal_depth` (`update_cortical_area()`) before choosing a change mode. Confirm with `get_memory_area_runtime_config()`, whose `mp_encoding.effective_mode` shows what FEAGI
runs; a `warning` from the set call means FEAGI disabled the change mode.

Changing `temporal_depth`, upstream set or MP mode removes memory neurons that no longer fit
(`memory_neurons_removed`); cap, eviction and lifespan changes keep them.

## Inspecting memory

- `get_memory_area_runtime_config(cortical_id)`: lifecycle settings, encoding, and findings
  such as `memory_no_episodic_upstream` (error) and `memory_neurons_expire_unmatched`
  (neurons were created but none survived).
- `list_memory_neurons()`, `inspect_memory_neuron()`: an area's neurons, lifecycle, synapses.
- `diagnose_memory_twin_mapping(src_area, dst_area)`: why an episodic mapping did or did not
  create a twin area.

## Counters, re-match rate and cleanup

Each memory area counts, since it was created: `created_total`, `deleted_total`,
`evicted_total`, `creation_failed_total`, `formation_suppressed_total` and
`reactivated_total` (an existing neuron matched again, whichever path matched it). They
come back in `get_memory_area_runtime_config` under `lifecycle_totals`.

- **Re-match rate**: pass `interval_s` and present the stimulus during the wait. The tool
  samples twice and returns `rematch.rate = d_reactivated / (d_reactivated + d_created +
  d_creation_failed + d_formation_suppressed)` with the deltas. A rate near 1 means
  presentations land on stored neurons; near 0 means every presentation looks new. It is
  `null` when nothing was presented or the counters are absent. `interval_s` is capped at the
  foreground tool-call budget (50 s); for a longer window diff `lifecycle_totals` yourself.
- **Per-neuron history**: `list_memory_neurons(cortical_id, detail=true)` adds, for the page,
  `creation_burst`, `last_activation_burst`, `activation_count`, `lifespan` (remaining
  bursts), `is_long_term`. Default off.
- **Cleanup**: `delete_memory_neurons(area, neuron_ids)` removes the listed neurons with their
  synapses and replay frames; the area's other neurons are untouched, and ids not in that
  area are refused (nothing is deleted). Cleanup for test residue, not a learning mechanism.
  Destructive: confirm first.

## Stop new memories forming (`memory.formation`)

`memory.formation` is an area-level modulator for memory areas. With its driver active at
-100% the area forms no new memory neurons (other magnitudes do not block: -50 and any positive
value change nothing). A known pattern still reactivates its neuron; recall, ageing,
long-term conversion and eviction continue unchanged. Skipped creations count in
`formation_suppressed_total`, not `creation_failed_total`. A silent driver forms memories as
usual. Non-memory areas reject it.

**When to use it:** states you do not want remembered, or encoding gated to salient moments.
To hold a whole area fixed for a test, use a freeze (next section).

**How to wire it**
1. `create_modulator("no_new_memory", {"type": "memory.formation", "magnitude_percent": -100,
   "effect_duration_bursts": 1, "rest_bursts": 0, "graded": false})`. Read the driver area
   id from `get_modulator()`.
2. Wire the suppressing signal (or a small `1x1x1` area) into the driver area with
   `apply_connectivity_rule()`, as a reward detector is wired into a `synaptic.reward` driver.
   The driver counts as active on every burst its neuron fires. A large
   `effect_duration_bursts` keeps it on after one `stimulate_area()` (Model in
   [modulators.md](modulators.md)).
3. `set_area_modulators(memory_area_id, ["no_new_memory"])` on each memory area to suppress.
   The call replaces the list, so include the area's existing modulator ids.
4. Verify with `get_memory_area_runtime_config(memory_area_id)`:
   `lifecycle_totals.formation_suppressed_total` rises while `created_total` stays flat, and
   a `memory_formation_suppressed` finding appears. `modulator_usage()` lists the subscribers.

Suppressing is the genome designer's call; the Trainer does not drive `memory.formation`.

## Freezing learning (switch vs modulator)

`memory.formation` only blocks new memory neurons. To stop all learning use a freeze
(feagi-core behavior, not re-measured):
- `memory.freeze` (area modulator, memory areas, m > 0): frozen while the driver's combined
  signal is > 0. No new neurons, ageing, expiry, lifespan growth, long-term conversion,
  consolidation or eviction by other areas, and no learning on mappings into or out of the
  area. Existing memory neurons still fire (recognition, recall, replay).
- `synaptic.learning_rate` with a combined factor <= 0: no commits, synapse synthesis or
  trace growth (traces pause, not cleared) on the subscribed plastic mappings.
- Manual switches `set_memory_area_learning_frozen(area)` and `freeze_mapping_plasticity(src,
  dst)` belong to the running brain: kept in brain snapshots (a Hub connectome carries them),
  cleared on genome load, never in the genome. A circuit that must stay frozen is a modulator
  in the genome; a switch is for tests. Recipe: [modulators.md](modulators.md).

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
