# Memory design: associative tuning, worked examples, mistakes

Part 2 of [memory-design.md](memory-design.md) (read that first). Labels: (code: path:line),
(measured once), (derived rule).

## Associative connections

Legal pairs: memory->memory, memory->plain, plain->memory. (code: npu.rs)

- Created when both endpoints fired by encoding (a pattern match, not a recall) within
  `plasticity_window` bursts. (code: npu.rs:6559-6567, 6288-6311)
- Every source x destination pair in the window is linked. Keep windows small. (code: npu.rs:6678-6740)
- Initial weight = clamp(`plasticity_constant` * `ltp_multiplier`, 0..255). (code: npu.rs:242-247)
- Each later co-firing: w += eta * R * e, capped at `max_weight`. (code: npu.rs:6593-6610)
- `stdp`: R is the learning factor, 1.0 without modulators. `rstdp` needs a `synaptic.reward`
  modulator, else R=0 and nothing is learned. (code: npu.rs:6484-6498)
- A `stdp` mapping subscribed to any `synaptic.reward` modulator is reward-gated too: off-reward
  R=0, so it neither creates nor grows. For an unrewarded seed phase leave it unsubscribed, then
  subscribe at the switch to `rstdp`. (code: npu.rs:6484-6490)
- `e` is a trace, not 1: it gains `delta_plus` on every co-firing burst and decays over
  `eligibility_decay_bursts` (code: npu.rs:6559-6575). A held state co-firing for many bursts
  gives e >> 1, so one presentation can move the weight several steps (window 5 gave weight 5).
  Size eta from one read: `watch_mapping_weights()` through one presentation or reward pulse.
- No LTD on associative mappings. Weights only rise. They fall by expiry, eviction, reset or
  punishment (R<0). `max_weight` is the only brake besides punishment. (code: npu.rs:6570, 6597-6610)
- A target fires from memory alone when weight * PSP >= the target's firing threshold. Memory
  areas are leak-free accumulators. (code: lif.rs:87; sparse_memory_lif.rs:99-103)
- Memory areas default to uniform PSP, and the tool created them with PSP 500 (measured). At 500
  one co-firing fires anything. Set PSP deliberately.

### Pairings to recall

Formula (derived rule, matches the runs): pairings to recall = 1 + ceil((threshold - w0) / (eta * e)),
with w0 the initial weight and e the per-pairing term in `w += eta*R*e` (1 in these runs).

| Goal | Settings | Result (measured) |
|---|---|---|
| One-shot | constant 1, ltp 1, threshold 1 | recall after 1 pairing |
| Gradual | constant 1, ltp 1, eta 0.25, threshold 2, window 1 | weights 1, 1.25, 1.5, 1.75, 2.0; recall after the 5th pairing |
| One-shot, capped | constant 2, ltp 2, max_weight 3, threshold 1 | recall after 1 pairing, weight capped at 3 |

Choosing the speed (derived rule): one-shot only when every pairing is correct (a reliable
teacher, a clean cue pair). When pairings are noisy or the teacher is sometimes wrong, size it
for 5-20 pairings so one bad pairing cannot recall alone, and cap with `max_weight` just above
the threshold. When the right pairing is known only by its outcome, use `rstdp` with reward
and seed creation first (a short `stdp` phase), because reward-gated creation needs R > 0 on
the co-firing burst. Too fast shows as wrong recalls after one stray pairing; too slow shows as
neurons expiring before the weight reaches the threshold (compare pairings needed x the gap
between pairings with the lifespan).

A window above 1 raised the weight within one presentation (window 5: one teach gave 5),
consistent with the trace `e` summing every co-firing burst in the window (see above). Use
window 1 and single-burst presentations when you need a countable pairing.

Other rules:
- Reward consolidation: a reward-gated weight rise or creation marks both memory endpoints; the
  next compute promotes still-active STM to LTM. (code: npu.rs:6617-6619, 6769-6774; service.rs:608-636)
- Recall is one-directional: one A+B pairing makes A fire MB; B alone does not fire MA.
  Recalled neurons drive their own outgoing synapses (chains). Recall-fired neurons do not create
  new associative synapses. (measured; code: npu.rs:6654)
- A structural mapping change (delay, morphology, `mapping_psc`) rebuilt the synapse and reset
  the weight to 1 (measured). Plasticity-only changes keep weights. Never sweep delay,
  morphology or `mapping_psc` on a learned mapping.

## Worked examples

1. **State classifier to action.** Sensor area (coarse, a few dozen patterns) -> memory area
   `S` (depth 1, lifespan above the longest revisit gap, long-term threshold sized in bursts).
   `S` -> output via `associative_memory`, `rstdp`, a reward modulator, `plasticity_constant` 1,
   small eta, window 1-2. A teacher or reflex fires the output at first; reward raises the right
   weights. Verify with `diagnose_mapping_plasticity()` and `watch_mapping_weights()`.
2. **Two-cue assembly.** Memory `MA` and `MB` fed by cues A and B. Mappings `MA->MB` and `MB->MA`
   (`stdp`, constant 1, ltp 1, threshold 1: one pairing). Present A+B once. Then A alone fires
   `MB` one hop later (+1 burst at delay 1). Cost: two mappings for two directions.
3. **Three-step chain.** `MA -> MB -> MC`, each link learned by presenting the pair in order.
   Recall from A's input alone: A at +2, B at +3, C at +4 from the input spike (measured).
   Check the +4 against the loop budget.
4. **Two-level hierarchy over a sequence.** Lower memory `L` (depth 1) over the sensor; upper
   memory `U` (depth 2) fed episodically from `L`. A1 then A2 gives 3 `U` neurons; A2 then A1
   gives different ones, so `U` tells order. Latency is +4 from input. `L` must stay bounded.

## Costly mistakes

- `rstdp` without a reward modulator: R=0, nothing learns, and nothing errors.
- Leaving the default PSP 500: one co-firing fires every target; learning looks instant and wrong.
- `temporal_depth` > 1 on a held input: 3 start-up neurons that never recur, wasting pool.
- Unbounded pattern count: the area never levels and fills the shared pool.
- Lifespan shorter than the recurrence gap: neurons expire and their learned links are deleted.
- Growth below 1: reactivation adds 0, so neurons only age.
- Changing delay, morphology or `mapping_psc` on a learned mapping: the weight resets to 1.
- Expecting STM to survive save or restart: only LTM does, and synapses need both ends LTM.
- Expecting recalled neurons to learn: recall-fired neurons form no new associative synapses.
- Wide `plasticity_window` or many fired sources: every pair links (cross-product synapses).
- Expecting memory to sequence unaided: use a chain or hierarchy, or keep an innate clock.

## Consolidation, worked example

Worked example, derive your own (see "Tuning consolidation" in [memory-design.md](memory-design.md)):
P = 42 bursts per presentation, r about 20, f_min = 1/50, so G = 2100; init = 4200; growth = 210
(net +2100 per recurrence); K = 3 gives threshold = 10500. The rarest kept pattern goes long-term
after about 150 presentations; a pattern seen every 4th presentation after about 2 sightings.
(design intent, unmeasured)
