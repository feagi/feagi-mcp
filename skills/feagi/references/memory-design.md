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

### Memory areas are the learning mechanism for recognition

Memory areas are how FEAGI learns to recognise and classify. A memory area fed raw high-resolution input mints a new pattern per input and does not generalise. The fix is not to drop memory areas: extract coarse features first (pooling, oriented-edge detectors, local regions) until the pattern count is bounded and the same feature patterns recur across many examples of a class, then feed those to memory. Do not reject memory areas because raw inputs are unique. A worked classification pattern ships with Neurorobotics Studio (`behavior-playbooks` skill).

Downsizing is the cheapest coarsening: map a large input onto a smaller area with the `projector` morphology (for example a W x H plane onto W/2 x H/2 or W/4 x H/4), so several source voxels land on one destination voxel and minute differences between inputs disappear. Set the destination threshold so a voxel fires only when enough of its source voxels fire (a fraction of the block, not one stray pixel), and check the fired count on a few real inputs. Downsize before feature detectors or memory; pick the size from the smallest detail that must still be told apart.

## Tuning a memory area

Defaults: depth 1, init_lifespan 9, growth 1.0, long-term threshold 100, cap 0, eviction lru.
(code: memory_neuron_array.rs; plasticity_detector.rs:350-366)

| Setting | Rule |
|---|---|
| Pattern count | Keep it bounded, a few dozen. Coarsen the upstream (fewer bins, coarser values) before building. (derived rule from measured blow-up) |
| `neuron_init_lifespan` | About 2 x the gap G, in bursts, between recurrences of the rarest pattern you want to keep (see Tuning consolidation). Lifespan starts at init; each unseen burst ages it by 1; expiry at 0. (code: memory_neuron_array.rs:597-609) |
| Growth | Each reactivation adds growth truncated to an integer, so 0.5 adds 0. It must make `r x growth` exceed the gap G (see Tuning consolidation); 1 is too small when G exceeds the hold. (code: :571-575) |
| Long-term threshold | Compared with the lifespan, which starts at `neuron_init_lifespan` (code: :521). STM becomes LTM when lifespan >= threshold; LTM never ages (code: :677-709). So the threshold must exceed init, and the lifespan must be able to reach it net of aging (see Tuning consolidation). A threshold at or below init makes every neuron LTM on creation. A rewarded weight rise or creation on a reward-gated mapping promotes its memory endpoint regardless of the threshold (code: npu.rs:6195-6202, 6617-6619). |
| `memory_neuron_cap` and eviction | Cap evicts in the creating area. A full shared pool evicts from the lru area holding most. Victim: lowest-lifespan STM, then least-recent LTM. Eviction `none` makes creation fail, so use it on areas that must not lose memories. (code: :412-424, 490-503) |
| Save and restart | Only LTM is saved and restored. A connectome snapshot keeps a synapse only when both memory endpoints are LTM. (code: :1076-1077, connectome.rs) |
| Deleting a neuron | Expiry or eviction deletes that neuron's synapses, learned ones included. (code: npu.rs:1631-1692) |
| Shape changes | Changing `temporal_depth`, the upstream set or the MP mode removes neurons that no longer fit. The change reports it. (code: [memory-and-plasticity.md](memory-and-plasticity.md)) |

### Tuning consolidation (repetition to long-term)

Repetition is the built-in way short-term memories become long-term. Tune this before designing
any new consolidation mechanism. A neuron LOSES 1 lifespan per burst its pattern is unseen (so G
per gap) and GAINS `r x growth` per presentation, so the lifespan climbs only if the gain beats
the loss. Derive the values:

1. Measure P = bursts per presentation cycle (hold + gap + pipeline) and r = reactivations of a
   matching memory neuron per presentation (`list_memory_neurons` activation counts; usually
   close to the bursts the input is held at temporal depth 1). A self-held input reactivates its memory neuron every burst (r = every burst held).
2. Choose f_min, the rarest pattern worth keeping, as a fraction of presentations (design
   choice). G = P / f_min is its gap between recurrences, in bursts.
3. `neuron_init_lifespan` about 2 x G, so a new pattern survives until it is seen again.
4. `neuron_lifespan_growth_rate` >= ceil(2 x G / r), so each recurrence nets at least +G.
5. `neuron_longterm_mem_threshold` = init + K x (r x growth - G), K = recurrences that should
   make a pattern permanent (design choice, e.g. 3-5).
6. Time to long-term for the rarest kept pattern is about K / f_min presentations; commoner
   patterns get there sooner. It must be a small fraction of the training run; if not, raise
   f_min or lower K.
7. Verify on a small batch: `long_term_neuron_count` rises within the predicted presentations and
   `neuron_count` levels off (rare patterns expire). Then adjust once, not by guessing.

With growth 1 and a gap longer than the hold, lifespan never climbs and repetition never
consolidates. Never set the threshold far above what this derivation gives: a threshold the
lifespan cannot reach disables consolidation; one at or below init makes everything permanent at
creation. Reward consolidation (a rewarded link) promotes both memory endpoints regardless of the
threshold, so in a reward-trained classifier the threshold governs unrewarded patterns only
([memory-and-plasticity.md](memory-and-plasticity.md)). Worked numbers:
[memory-design-structures.md](memory-design-structures.md) "Consolidation, worked example".

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
