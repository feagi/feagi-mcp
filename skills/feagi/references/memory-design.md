# Designing with memory: which structure, how to tune it

Read this before any circuit with a MEMORY area or an `associative_memory` mapping. Wiring
recipes, worked examples and the mistakes list: [memory-design-structures.md](memory-design-structures.md).
Mechanics and parameter names: [memory-and-plasticity.md](memory-and-plasticity.md),
[STDP and R-STDP](memory-plasticity-stdp.md). Labels: (code: path:line) from feagi-core,
(measured once) from a live brain, (derived rule) reasoned from both.

## What a memory neuron is

- Upstream areas are those with an `episodic_memory` (or classifier) rule into the memory area.
  Associative-only sources do not count. (code: connectome_manager.rs:1695-1741, 12125-12134)
- Each burst, each upstream area's fired neuron ids are sorted and hashed once (xxh64). A window
  is `temporal_depth` burst-aligned hashes per upstream area. (code: plasticity service.rs:702-802;
  pattern_detector.rs:242-262)
- New window content makes a new neuron. A repeat reactivates the existing one. The
  `memory.formation` modulator blocks creation only, not reactivation; a frozen area (`memory.freeze` or the area switch) also creates none and ages none. (code: service.rs:939-1121, 1009)
- A memory neuron fires in two ways: its upstream pattern matches live fires (encoding), or a
  learned associative synapse drives it (recall, no input needed). One area alone classifies
  states; a sequence needs a chain or a hierarchy (below). (code: npu.rs:6880-6887,
  sparse_memory_lif.rs:260-277; measured once)
- A twin area is auto-created for each non-memory upstream. A firing memory neuron replays its
  stored frame onto the twin. (code: connectome_manager.rs:4878-4891; npu.rs:2505-2560)
- `mp_learning` stores and averages membrane potentials. `mp_differential` and `mp_ratio` need
  `temporal_depth` >= 2, else they run as pattern-only with no replay.
  (code: service.rs:951, 1459-1500, 2430-2437; mp_change_encoder.rs:93-130)

## Need to structure

| Need | Structure | Use when | Do NOT use when |
|---|---|---|---|
| Name the current situation | One memory area, `temporal_depth` 1, coarse upstream | The upstream has a few dozen distinct patterns | Upstream is multi-column bins: one source minted 1,475 patterns in 60 s and never levelled (measured; the measured lessons ship with Neurorobotics Studio, `behavior-playbooks` skill) |
| Recognise a short temporal shape | Memory area with `temporal_depth` N, or `mp_differential` / `mp_ratio` (ECG cascade: [memory-and-plasticity.md](memory-and-plasticity.md)) | The shape is N bursts long and repeats | The input is held still: depth > 1 adds start-up neurons (below) |
| Map a state to an action | Memory (state) -> plain output area, `associative_memory`, with a teacher or exploration | A teacher or reflex makes the output fire in the window | Nothing ever fires the output in the window: no co-firing, no synapse |
| Shape that map by outcome | Same mapping with `rstdp` plus a `synaptic.reward` modulator | A hard-wired detector pays reward | No reward modulator: R=0 and nothing is learned |
| Seed a map without reward | Same mapping with `stdp` | Teacher output is correct and you want it copied | The wrong pairings would also be copied: `stdp` has no sign |
| Bind two inputs, or complete a pattern from a cue | Assembly: two memory areas, one `associative_memory` mapping A->B, a second B->A for the other direction | Seeing A should bring back B | You need both directions and built one mapping: recall is one-directional |
| Predict the next state, replay a sequence | Chain of memory areas A -> B -> C, each link associative | The order is fixed and each step is a distinct state | Many branches: every co-fired pair links, so branches blur |
| Abstraction, sequences of states, many timescales | Hierarchy: lower memory area episodic into an upper memory area; upper `temporal_depth` = sequence length in lower states | The unit of interest is a sequence of lower patterns | The lower area's pattern count is unbounded: the upper one inherits the blow-up |

## Tuning a memory area

Defaults: depth 1, init_lifespan 9, growth 1.0, long-term threshold 100, cap 0, eviction lru.
(code: memory_neuron_array.rs; plasticity_detector.rs:350-366)

| Setting | Rule |
|---|---|
| Pattern count | Keep it bounded, a few dozen. Coarsen the upstream (fewer bins, coarser values) before building. (derived rule from measured blow-up) |
| `neuron_init_lifespan` | Larger than the longest gap, in bursts, between recurrences of a pattern you want to keep. Lifespan starts at init; each unseen burst ages it by 1; expiry at 0. (code: memory_neuron_array.rs:597-609) |
| Growth | At least 1. Each reactivation adds growth truncated to an integer, so 0.5 adds 0. (code: :571-575) |
| Long-term threshold | Compared with the lifespan, which starts at `neuron_init_lifespan` (code: :521). STM becomes LTM when lifespan >= threshold; LTM never ages (code: :677-709). So the threshold must exceed init: bursts of presence to LTM = (threshold - init) / growth. A threshold at or below init makes every neuron LTM on creation. A self-held input reactivates every burst. A rewarded weight rise or creation on a reward-gated mapping promotes its memory endpoint regardless of the threshold (code: npu.rs:6195-6202, 6617-6619). |
| `memory_neuron_cap` and eviction | Cap evicts in the creating area. A full shared pool evicts from the lru area holding most. Victim: lowest-lifespan STM, then least-recent LTM. Eviction `none` makes creation fail, so use it on areas that must not lose memories. (code: :412-424, 490-503) |
| Save and restart | Only LTM is saved and restored. A connectome snapshot keeps a synapse only when both memory endpoints are LTM. (code: :1076-1077, connectome.rs) |
| Deleting a neuron | Expiry or eviction deletes that neuron's synapses, learned ones included. (code: npu.rs:1631-1692) |
| Shape changes | Changing `temporal_depth`, the upstream set or the MP mode removes neurons that no longer fit. The change reports it. (code: [memory-and-plasticity.md](memory-and-plasticity.md)) |

### Tuning consolidation (repetition to long-term)

Repetition is the built-in way short-term memories become long-term: each reactivation grows
lifespan by `neuron_lifespan_growth_rate`, and reaching `neuron_longterm_mem_threshold` makes the
neuron permanent. Tune this before designing any new consolidation mechanism. (code: the refs in
the table above)

1. Measure the recurrence gap of the patterns to keep: `list_memory_neurons` with detail, read
   `last_activation_burst` and `activation_count` over a sample. Convert seconds to bursts with
   the burst rate.
2. Set `neuron_init_lifespan` to about 3 x that gap (design guidance; derive your own factor).
3. Set `neuron_longterm_mem_threshold` = init + N x growth, N being the repetitions that should
   make a memory permanent (design choice). Read both back.

Pitfalls: a very large threshold as a workaround disables consolidation; a threshold at or below
init makes everything permanent at creation; reward-gated associative commits promote both
endpoints at once whatever the threshold ([memory-and-plasticity.md](memory-and-plasticity.md)).

Temporal depth, measured: a held pattern at depth 1 gives 1 neuron; at depth 3 it gives 4 (3
start-up windows plus 1 steady). A moving 3-step cycle gives 3 neurons at depth 1 and 3 steady at
depth 3. A depth-2 hierarchy level over an A1-then-A2 sequence gives 3 neurons ({A1,-}, {A1,A2},
{-,A2}); the reversed order gives different neurons. (measured once)

## Timing and the loop budget

| Path | Latency (measured once) |
|---|---|
| Input spike to memory neuron `last_activation_burst` | the input burst |
| Input spike to memory spike in the fire ledger | +2 bursts |
| Memory spike to a plain target | + `synaptic_delay_bursts` (delay 1 gives +1, delay 4 gives +4) |
| Assembly recall hop (memory to memory, delay 1) | +1 burst |
| Chain A->B->C, recall from A's input alone | A +2, B +3, C +4 from the input spike |
| Hierarchy, memory episodic upstream of memory | +2 bursts per level (about +4 at level 2) |

Loop budget (derived rule): sum the memory path (+2 per memory level, plus each hop's delay)
and add it to the rest of the sensor-to-motor loop. The total must fit the body's response time
at the chosen burst rate ([embodiment-burst-measuring.md](embodiment-burst-measuring.md)). Example:
two hierarchy levels (+4) and a delay-1 output hop (+1) cost 5 bursts. Delay is the knob for
timing, but changing it resets learning (see the structures file).
