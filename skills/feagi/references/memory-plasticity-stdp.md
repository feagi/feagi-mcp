# Plasticity: STDP and R-STDP

Part 2 of 3 of [memory-and-plasticity.md](memory-and-plasticity.md) (memory areas, modulators). Homeostatic plasticity: [memory-plasticity-homeostatic.md](memory-plasticity-homeostatic.md).

## Contents

- Plasticity: STDP and R-STDP

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
| `modulators` | Ids of `synaptic.*` instances the rule subscribes to (`synaptic.reward`, `synaptic.learning_rate`, `synaptic.transmission_gain`, `synaptic.gate`); see [modulators.md](modulators.md) |

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
  `eligibility_decay_bursts` later still moves it (`w += eta * R * e * step`).
- Only synapses whose own endpoint neurons fired get credit. For memory areas the exception
  is the placeholder seed edge between the memory voxels, which counts any activity in its
  areas.
- Punishment never potentiates; it lowers weights to a floor of 0.
- Several reward modulators on one rule sum into one R per burst (correct +100% and error
  -100% firing together give 0).

### Recipe: make one mapping plastic (R-STDP)

1. `create_modulator()` for reward and punishment; wire the detector (or Trainer-driven) driver
   areas as above.
2. One `update_cortical_mapping(src, dst, rules)` call carries the whole rule, read back first with
   `get_cortical_mapping()` so the edge's other rules are kept:
   `plasticity_mode: "rstdp"`, `plasticity_flag: true`, `modulators: [reward_id, punish_id]`,
   `ltp_multiplier`, `ltd_multiplier` (0 also turns punishment off and stops one-sided depression, so
   it is not a way to keep weights from wearing), `one_sided_firing` (see Credit assignment),
   `plasticity_constant`,
   `plasticity_eta`, `max_weight`, `plasticity_window`, `eligibility_decay_bursts`,
   `synaptic_delay_bursts` (at least 1).
   Send `eligibility_decay_bursts` only together with `plasticity_mode: "rstdp"`. On a rule that is
   not rstdp the call returns HTTP 500 although the other fields in it are saved (seen in live
   use), so a failed call can still have changed the rule: read it back before retrying.
3. Read it back with `get_cortical_mapping()` and `diagnose_mapping_plasticity(src, dst)`; watch
   weights with `watch_mapping_weights()`.
4. Size the step before the first reward. In live use `plasticity_constant: 1` drove a weight to
   its maximum on one reward event (2 to 4, measured in the walking build). The constant is an
   integer, so lower it to 1 and scale the commit with `plasticity_eta` (the commit is
   `w += eta * R * e`, eta in (0, 1]), and cap growth with `max_weight`. Confirm on a single
   reward event with `watch_mapping_weights()` before training.

Reward and punishment detector areas must be driven only by hard-wired, non-plastic input.
FEAGI's wireheading check rejects genomes where learning can feed its own reward.

**Measured (associative STDP).** One co-firing inside `plasticity_window` forms a synapse. A
memory -> plain-area association arrives at the memory spike + `synaptic_delay_bursts` (delay 1
gives +1, delay 4 gives +4); the memory spike shows 2 bursts after the input spike. Full timing
table and learning-speed formula: [memory-design.md](memory-design.md).

**Structural versus in-place changes.** By contract a structural mapping change (rules, PSC
multiplier = initial weight) rebuilds the synapses, so learned weights restart; plasticity-only
changes apply in place. Never sweep `mapping_psc` on a learned mapping: sweep the area
parameter (`area_parameter`) instead.

FEAGI keeps **fire ledgers** so STDP can see which sources and destinations co-fired. Check
whether a mapping is actually learning with `diagnose_mapping_plasticity(src_area, dst_area)`,
and see per-area ledger windows with `get_fire_ledger_areas_window_config()`.

### Credit assignment (read before training with reward)

- Plain STDP here is not spike-order sensitive. LTP needs both ends to fire anywhere inside
  `plasticity_window`, in either order. LTD (only when LTD > 0, and not on associative-memory
  mappings) comes from one-sided firing, never from post-before-pre. The exponential timing
  curves (`stdp_core.rs`, `compute_timing_factors`) exist in the plasticity crate but the burst
  engine does not run them (`apply_stdp_updates_for_burst`, npu.rs, uses window sets and the
  event count `e` only).

- The weight commit is `w += eta * R * e * step`, applied only when R is not 0 and e is not 0.
  The trace `e` counts events: +1 per co-firing burst, -1 per one-sided burst (source or
  destination fired alone in the window), decayed each burst. `step` is LTP or LTD:
  R > 0 on e > 0 uses LTP; R < 0 on e > 0 (punished co-firing) and R > 0 on e < 0 use LTD;
  R < 0 on e < 0 commits nothing. Punishment never potentiates.
- LTD 0 disables punishment (and one-sided depression); LTP 0 disables reward only.
- With LTD > 0, `e` goes negative on one-sided firing, so a positive reward then lowers the
  weight. Reward that arrives while the postsynaptic area is quiet wears weights down.
- With LTD 0, `e` never goes negative, so every reward potentiates co-firing until
  `max_weight`. The weights saturate, and punishment cannot lower them.
- `one_sided_firing` (plastic rule field, set with `update_cortical_mapping`;
  `build_reflex_mapping` cannot set it): `"decrement"` (default) is the -1 rule above. `"ignore"`
  leaves `e` unchanged on one-sided bursts; co-firing still adds 1, commit rules are unchanged, so
  reward only potentiates co-fired links and punishment with `e` > 0 applies LTD. Associative-memory
  mappings never decrement either way. Unknown values are rejected. Choose `"ignore"` for a tonically
  active source (e.g. a sensor port firing every burst) paired with a sparse destination (e.g.
  exploration), where `"decrement"` drives `e` negative before reward arrives. Evidence: implemented,
  unit-tested; not yet measured on a body.
- On associative mappings the commit needs a co-firing burst. Delayed punishment (pain
  arriving after the co-firing) does not commit; pain must precede or coincide with a
  co-firing burst.
- A one-to-one mapping per direction means R-STDP only gates a fixed direction. It can mute
  a wrong one; it cannot flip it.
- A reward that pays for an outcome produced by external support teaches dependence on the
  support.
- Before training, read `plasticity_flag` back on the plastic mappings, and resume a mapping
  a test run froze with `freeze_mapping_plasticity(frozen=False)`, and resume frozen memory areas with
  `set_memory_area_learning_frozen(area, False)`. A leftover freeze and a flag left off both stop
  all learning. Freeze overview: [memory-and-plasticity.md](memory-and-plasticity.md).
- `eligibility_decay_bursts` sets the credit window. Match it to the reward latency in
  bursts.

Do not quote internal parameter names, kernel details, or module paths that tools or this
skill do not show; they change between releases.
