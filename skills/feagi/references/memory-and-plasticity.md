# Memory, plasticity, and modulators

## Contents

- Memory areas
- Membrane-potential encoding modes
- Inspecting memory
- Plasticity: STDP and R-STDP
- Homeostatic plasticity (`rate_modulated_leak`)
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

Memory neurons have a lifecycle: an initial lifespan, growth per re-match, and a long-term
threshold after which they become permanent. A working ECG cascade used init lifespan 9,
lifespan growth 1, and long-term threshold 100. Tune these with `update_cortical_area()`
(keys `neuron_init_lifespan`, `neuron_lifespan_growth_rate`, `neuron_longterm_mem_threshold`;
the window length is `temporal_depth`). Two more keys bound growth: `memory_neuron_cap` (int,
most memory neurons this area may hold; 0 = no per-area cap) and `ltm_eviction` (`lru` or
`none`). The neuron pool is shared by all memory areas; when an area is at its cap or the pool
is full, `lru` evicts that area's least recently reactivated neuron, `none` fails the creation.
`get_memory_area_runtime_config()` shows both, `evicted_total`, `creation_failed_total` and the
`memory_pool`.

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

**How a reward reaches a synapse.**
- A modulator's driver firing on burst t sets R for burst t+1 (one burst later).
- New synapses on a reward-gated mapping need R > 0 on the burst where both endpoints fire
  inside `plasticity_window`. `eligibility_decay_bursts` does not help creation: a synapse
  that does not exist has no trace.
- An existing synapse keeps an eligibility trace; a reward up to about
  `eligibility_decay_bursts` later still moves it (`w += eta * R * e`).
- Only synapses whose own endpoint neurons fired get credit. For memory areas the exception
  is the placeholder seed edge between the memory voxels, which counts any activity in its
  areas.
- Punishment never potentiates; it lowers weights to a floor of 0.
- Several reward modulators on one rule sum into one R per burst (correct +100% and error
  -100% firing together give 0).

Reward and punishment detector areas must be driven only by hard-wired, non-plastic input.
FEAGI's wireheading check rejects genomes where learning can feed its own reward.

FEAGI keeps **fire ledgers** so STDP can see which sources and destinations co-fired. Check
whether a mapping is actually learning with `diagnose_mapping_plasticity(src_area, dst_area)`,
and see per-area ledger windows with `get_fire_ledger_areas_window_config()`.

### Credit assignment (read before training with reward)

- The weight commit is `w += eta * R * e`, applied only when R is not 0 and e is not 0. The
  trace `e` gains LTP on co-firing and loses LTD on one-sided firing (source or destination
  fired alone in the window).
- Potentiation happens only when R > 0, e > 0 and LTP > 0. Punishment never potentiates.
- With LTD > 0, `e` goes negative on one-sided firing, so a positive reward then lowers the
  weight. Reward that arrives while the postsynaptic area is quiet wears weights down.
- With LTD 0, `e` never goes negative, so every reward potentiates co-firing until
  `max_weight`. The weights saturate.
- A one-to-one mapping per direction means R-STDP only gates a fixed direction. It can mute
  a wrong one; it cannot flip it.
- A reward that pays for an outcome produced by external support teaches dependence on the
  support.
- Before training, read `plasticity_flag` back on the plastic mappings. A test-run freeze can
  leave it off, and nothing learns.
- `eligibility_decay_bursts` sets the credit window. Match it to the reward latency in
  bursts.

Do not quote internal parameter names, kernel details, or module paths that tools or this
skill do not show; they change between releases.

## Homeostatic plasticity (`rate_modulated_leak`)

FEAGI's homeostasis is **intrinsic**: each neuron's leak follows its own firing rate. Firing
above the set-point raises the leak (less charge carries over, the neuron fires less); firing
below it lowers the leak. It never changes synapse weights. FEAGI has no synaptic scaling or
weight normalization, so it does not fix STDP weights that saturate or collapse.

### What it can and cannot do

- Charge per burst is `V = V_prev * (1 - g) + I`, where `g` is the leak (fraction lost per
  burst). An area integrates over about `1/g` bursts: `g = 0.02` sums about 50 bursts of
  input, `g = 0.5` about 2.
- So the homeostat only changes how much **sub-threshold** input adds up across bursts. A
  neuron whose input in a single burst reaches threshold fires at any leak. Input-driven
  saturation needs a higher threshold, a smaller PSC, or inhibition, not homeostasis. The
  sign: a leak pinned at `leak_max` with the rate still above target means the input is too
  strong for the homeostat.
- A silent neuron with no input stays silent at any leak. A leak pinned at `leak_min` with
  the rate still below target means the input is too weak or missing; fix the wiring.
- It works only on dense custom (LIF) areas. Memory neurons are skipped.
- Use it on hidden populations that must stay in a working range while weights or inputs
  drift: reservoirs, feature layers, recurrent loops at risk of runaway or silence, and
  areas receiving plastic mappings.
- Do not use it on areas that carry a graded value (value planes, magnitude passthrough),
  on motor output areas, on modulator drivers, or on detectors whose firing **is** the
  signal. The homeostat would treat the signal as an error: a sustained stimulus makes the
  area adapt to it, and the output fades over about `rate_ema_tau_bursts`.

### Parameters

| Field | Default | Meaning |
|-------|---------|---------|
| `enabled` | false | Off unless true. `{"enabled": false}` disables and keeps the tuning. |
| `target_mode` | `area` | `area`: one set-point for all neurons. `per_neuron`: each neuron keeps the rate it had while arming. |
| `target_firing_per_burst` | 0.1 | `area` mode set-point, as fires per burst (0 to 1). Ignored in `per_neuron`. |
| `rate_ema_tau_bursts` | 50 | Time constant of the rate estimate, in bursts. |
| `gain` | 0.2 | Leak change per unit of rate error per update. |
| `leak_min`, `leak_max` | 0.02, 0.5 | Range the homeostat may move the leak in. |
| `update_every_n_bursts` | 1 | Leak update cadence. The rate is sampled every burst. |
| `arm_bursts` | 500 | `per_neuron`: bursts spent measuring each neuron's target. |
| `arm_tau_bursts` | `arm_bursts / 4` | `per_neuron`: averaging time constant while arming. |
| `min_target_firing_per_burst` | 0.001 | `per_neuron`: neurons armed below this count as silent. |
| `silent_neurons` | `one_sided` | `per_neuron`: `one_sided` lets a silent-armed neuron's leak only rise (back down to the base leak at rest), which stops a disturbance from recruiting it; `unregulated` leaves it at the base leak. |
| `arm_epoch` | 0 | `per_neuron`: change the number to re-arm. |

### Choosing the values

Size every value from the burst rate and the behavior, never keep the defaults. All of them
are counted in bursts, so rescale them whenever the burst rate changes.

1. **Set-point.** `target_firing_per_burst = desired rate (Hz) / burst rate (Hz)`. A sparse
   population code is about 0.02 to 0.1; above about 0.3 the area is near its refractory
   ceiling and the homeostat has little room. For population codes, where a few neurons are
   active and the rest silent, use `per_neuron`: `area` mode drives the active neurons down
   to the area average and pins the silent ones at `leak_min`.
2. **Time constant.** `rate_ema_tau_bursts` must be several times (at least 5x) the longest
   signal the area must pass unchanged, in bursts. Shorter, and the homeostat cancels the
   signal. For an area that carries task events of 2 s at 50 Hz bursts, that is at least
   500 bursts.
3. **Gain.** One update moves the leak by `gain * (rate - target)`. Crossing the full range
   takes about `(leak_max - leak_min) / (gain * |rate - target|)` updates. Choose the gain so
   that time is close to `rate_ema_tau_bursts`. Much faster, and the leak oscillates; much
   slower, and the area spends the run out of range.
4. **Range.** Set `leak_min` from the longest integration the area may have (`1/leak_min`
   bursts) and `leak_max` from the shortest. Start the area's own `leak_coefficient` inside
   the range; a leak edit becomes the homeostat's new starting point.
5. **Learning.** On an area fed by plastic mappings, a potentiated path raises the rate and
   the homeostat cancels it within about `rate_ema_tau_bursts`. Make the time constant
   longer than the reward or credit window (`eligibility_decay_bursts`) and the behavior
   episode, or the area forgets what it learns. To evaluate learned weights alone, set
   `gain` to 0 (the leaks hold) rather than disabling, which drops the homeostat state.

Record the derivation in the design notebook with the burst-rate derivation.

### Arming (`per_neuron`)

- For `arm_bursts` after enable or re-arm, the leak stays at the area's base leak and each
  neuron's rate is measured; that rate becomes its frozen target.
- Arm while the brain runs the regime to hold: experiment running, sensors live, a normal
  task in progress. A brain that is idle while arming arms every neuron to silence.
- Re-arm with `{"arm_epoch": <new number>}` alone; partial updates merge, so the other
  fields are kept. Re-sending the config with the same `arm_epoch` changes only the gain,
  clamps and time constants and keeps the targets.
- A full connectome import restarts the homeostat from the area's `leak_coefficient`, so
  `per_neuron` areas arm again from the import. Drive the brain during those bursts. After
  any restore, read `rate_target` to confirm the targets you expect.

### With modulators

A `neuro.leak` modulator scales the homeostat's leak (`leak x (1 + m)`, clamped to 0..1):
the homeostat sets the baseline, the modulator scales it while active. A long, strong
`neuro.leak` signal is seen by the homeostat as a rate change and partly undone after about
`rate_ema_tau_bursts`.

### Set it, then verify it

1. Check the area is a dense custom area and baseline its firing with `monitor_activity()`
   while the brain is driven.
2. Set it with `update_cortical_area(area, {"rate_modulated_leak": {...}})`. The whole object
   is validated first; an invalid field is rejected and nothing changes.
3. Read it back with `get_area_parameters(area)`, and again after a save or restart.
4. Read per-neuron state over HTTP:
   `GET /v1/connectome/cortical_area/<id>/neuron_state?fields=leak_coefficient,rate_ema,rate_target,homeostat_regulated`.
   `homeostat_regulated` is 1 for two-sided, 0.5 for one-sided (silent-armed), 0 for not
   regulated (arming, or `unregulated`). `list_area_neuron_states()` does not return these
   fields. For a time series, add the area and fields to the Trainer's `runData.neural.neuronState`
   (see behavior-design.md).
5. Pass checks, after at least 3x `rate_ema_tau_bursts` of driven running: the area's rate
   is within about 25% of the target (or each regulated neuron's), and under 10% of the
   regulated neurons sit at `leak_min` or `leak_max`.

| Symptom | Cause | Fix |
|---------|-------|-----|
| Most leaks at `leak_max`, rate still high | Single-burst input reaches threshold | Raise threshold, cut PSC, add inhibition |
| Most leaks at `leak_min`, rate still low | Input too weak or missing | Check wiring and upstream firing |
| Response fades during a held stimulus | `rate_ema_tau_bursts` shorter than the signal | Lengthen it, or remove the homeostat from a signal-carrying area |
| Learned behavior fades over minutes | Homeostat undoes potentiation | Longer time constant, or `gain` 0 during evaluation |
| Leak swings up and down | Gain too high for the time constant | Lower `gain` or raise `update_every_n_bursts` |
| All `rate_target` near 0, nothing regulated | Armed while the brain was idle | Re-arm with a new `arm_epoch` while driven |
| `rate_ema` is null | Area not registered (`enabled` false, invalid config, or not dense) | Read `get_area_parameters()`; fix and re-send |

## Stop new memories forming (`memory.formation`)

`memory.formation` is an area-level modulator for memory areas. With its driver active at
-100% the area forms no new memory neurons. Pattern detection still runs, so a known pattern
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
   keeps the driver on after one `stimulate_area()` (see Driver semantics under Modulators);
   it stops after that many bursts and then rests `rest_bursts`.
3. `set_area_modulators(memory_area_id, ["no_new_memory"])` on each memory area to suppress.
   The call replaces the list, so include the area's existing modulator ids.
4. Verify with `get_memory_area_runtime_config(memory_area_id)`:
   `lifecycle_totals.formation_suppressed_total` rises while `created_total` stays flat, and
   a `memory_formation_suppressed` finding appears. `modulator_usage()` lists the subscribers.

**Pairing with plastic mappings.** A memory area is not the only learner. For plastic
mappings (`stdp` / `rstdp`) subscribe the rule to a `synaptic.learning_rate` modulator at
-100% on the same driver area (a second `create_modulator()` whose driver is that area, then
`set_mapping_modulators()`). One driver then freezes both memory formation and mapping
learning.

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

A modulator is a typed signal with a `1x1x1` driver area. When the driver fires, subscribed
areas or mappings are modulated for a number of bursts.

- Types (`list_modulator_types()`): `neuro.*` types (`neuro.firing_threshold`,
  `neuro.leak`, `neuro.firing_probability`) modulate neurons in subscribed areas;
  `synaptic.*` types (`synaptic.transmission_gain`, `synaptic.reward`,
  `synaptic.learning_rate`, `synaptic.gate`) modulate subscribed mappings;
  `memory.formation` (memory areas): driver at -100% stops new memory neurons forming;
  existing memories still fire and age.
- Create: `create_modulator(modulator_id, definition)` with `type`, `magnitude_percent`
  (at least -100), `effect_duration_bursts` (at least 1), `rest_bursts`, `graded`, and
  `full_scale_potential` when graded.
- Driver semantics: the signal is on for exactly the bursts the driver neuron fires, and
  takes effect on the following burst. FEAGI makes the driver a spike train: one firing
  schedules forced firings at the same potential for up to `effect_duration_bursts`
  consecutive bursts, then the neuron rests for `rest_bursts`. So one `stimulate_area()` holds
  the signal for the effect duration and no longer, and a driver wired to a detector re-triggers
  after each rest. `graded` scales the signal by the driver's membrane potential up to
  `full_scale_potential`.
- Deliver reward or punishment by hand (tests, external teachers): `POST /v1/training/reward`
  or `/v1/training/punishment` with `{"modulator_ids": [...]}`; reward needs positive
  modulators, punishment negative ones.
- Subscribe: `set_area_modulators(cortical_id, modulator_ids)` for areas,
  `set_mapping_modulators(src_area, dst_area, modulator_ids, morphology_id)` for mappings.
  Both replace the full subscription list.
  Remove one subscription with `unsubscribe_area_modulator()` or
  `unsubscribe_mapping_modulator()`.
- Manage: `list_modulators()`, `get_modulator()`, `update_modulator()`, `rename_modulator()`,
  `modulator_usage()`, `delete_modulator()` (refused while subscribers exist unless forced;
  confirm first).
