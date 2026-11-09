# Modulators

A modulator is a driver area plus a typed signal that retunes subscribed neurons, synapses or
memory areas for a few bursts. Use it for circuit-level control (excitability, gain, gating,
learning phases, memory formation), not only for learning. Learning details:
[memory-plasticity-stdp.md](memory-plasticity-stdp.md). Code paths below are in feagi-core:
`engine` = `feagi-npu/burst-engine/src/modulator_engine.rs`, `kind` =
`feagi-structures/src/genomic/modulator.rs`; `modulators.rs` is in `feagi-evolutionary`, other
`*.rs` files are in the crate that owns them (burst-engine, services, brain-development).

## Model

- **Instance:** `type`, `magnitude_percent` m (>= -100, no upper bound), `effect_duration_bursts`
  (>= 1), `rest_bursts`, `graded` with `full_scale_potential` (> 0 when graded), one driver
  area. (kind:125-152)
- **Driver:** created as a `1x1x1` area (threshold 1, leak 0, excitability 1) running a spike
  train: `consecutive_fire_limit` = duration, snooze = rest, refractory 0
  (genome_service_impl.rs:1686-1689, modulators.rs:234-253). Or adopt an existing area
  (`driver_cortical_id`): duration must be 1, rest 0, one modulator per area
  (modulators.rs:290, genome_service_impl.rs:2202-2210).
- **Signal:** s = m/100 x strength, strength 1 (graded: min(MP / full_scale, 1)); a silent driver
  gives 0. Only the first fired neuron of the driver area counts. (kind:172-188, engine:468-488)
- **Timing:** driver fires on burst t, the factor applies from burst t+1 and is recomputed every
  burst (engine:399-405; test_conditional_gate.rs:119-160). A one-shot trigger holds for the
  spike train: forced refires at the trigger potential, then rest (engine:344-394).
- **Subscribe:** `neuro.*`, `memory.formation` and `memory.freeze` on cortical areas (area property
  `modulators`); `synaptic.*` on mapping rules (rule key `modulators`). Wrong level or unknown id
  is rejected at write time (genome_service_impl.rs:1403-1430, connectome_service_impl.rs:3130-3155).
- **Groups:** the synaptic ids of one rule form a group id stamped on that mapping's synapses;
  identical id sets share a group; group 0 means none (engine:217-240,
  connectome_manager.rs:5774-5787).

| Several modulators on one target | Combined as | Code |
|---|---|---|
| Same `neuro.*` parameter of an area | product of (1 + s) | engine:553-559 |
| `synaptic.reward` on a rule | sum of s | kind:210 |
| `synaptic.learning_rate`, `synaptic.transmission_gain` | product of (1 + s) | kind:191 |
| `synaptic.gate` | largest s (open if any gate is open) | kind:199 |
| Gate with gain in one group | gate x gain, so a closed gate zeroes it | engine:525-530 |
| `memory.formation` | product of (1 + s), clamped 0..1 | kind:205 |
| `memory.freeze` | frozen while the combined signal is > 0 | feagi-core, not re-read here |

## Types

Silent driver = rest value. Every type accepts `graded`; it scales s by driver MP.

| Type | Target | What m does | Silent driver / edge cases |
|---|---|---|---|
| `neuro.firing_threshold` | area | threshold x (1+s), floor 0: +50 = 1.5x harder, -100 = 0 | baseline; a baseline of 0 never moves |
| `neuro.leak` | area | leak x (1+s), clamp 0..1; leak is the fraction of V lost per burst (dynamics.rs:26): +50 = 1.5x faster loss, -100 = no leak | baseline; baseline 0 stays 0 |
| `neuro.firing_probability` | area | excitability x (1+s), clamp 0..1: -70 = about 30% of threshold crossings fire | baseline; positive m on baseline 1 does nothing |
| `synaptic.transmission_gain` | mapping | each synapse's final contribution x (1+s): +100 = 2x, -100 = 0 | factor 1 |
| `synaptic.reward` | mapping | adds s to R: +100 reward, -100 punishment; R = summed reward x learning factor (npu.rs:6484-6498) | R = 0; mapping is reward-gated |
| `synaptic.learning_rate` | mapping | multiplies the commit (eta): +50 = 1.5x; a combined factor <= 0 (-100) stops all learning on the subscribed plastic rule | factor 1 |
| `synaptic.gate` | mapping | closed (0) unless the driver fires; then the factor is s: +100 passes all, +50 half, m <= 0 never opens, m > 100 amplifies | closed, also before the first burst (engine:111-128; test_conditional_gate.rs:104-117) |
| `memory.formation` | memory area | factor clamp(1+s, 0, 1); new memory neurons are blocked only at factor 0, so m = -100 at full drive; -50 and any positive m do nothing (engine:174-190) | forms normally; recall and existing memories keep running (plasticity/src/service.rs:4916-4950) |
| `memory.freeze` | memory area | m > 0 only; area is frozen while the driver's combined signal > 0 (see recipe 2) | not frozen; non-memory areas reject it |

## Recipes

Verify each with `record_spikes()` (burst-exact `fire_fraction`) unless the line says otherwise.

1. **R-STDP reward and punishment.** Two `synaptic.reward` modulators (+100, -100), each driver
   fed only by hard-wired detectors: plastic input into a reward driver is rejected in either
   build order (npu.rs:6046-6089). `set_mapping_modulators()` with a reward id also switches the
   rule to `rstdp` (server.py:1437-1450); set `eligibility_decay_bursts` for late reward. Read:
   weight stats in `diagnose_mapping_plasticity()`, `watch_mapping_weights()`.
2. **Freeze learning for a test phase.** Three levels, all stop weight commits and synapse
   synthesis and pause (not clear) eligibility traces; pick by scope (feagi-core behavior, not
   re-measured by this skill):
   - *Circuit-driven, plastic mappings:* one `synaptic.learning_rate` at -100 on a `LearnOff`
     driver, subscribed on every plastic rule (`modulator_usage()` lists them). A combined
     factor <= 0 freezes `stdp`, `rstdp` and `associative_memory` rules; graded factors > 0
     only scale eta.
   - *Circuit-driven, memory areas:* `memory.freeze` (m > 0) subscribed on the memory area: it
     becomes a full snapshot (no new memory neurons, no ageing or expiry, no lifespan growth, no
     long-term conversion or consolidation, never evicted by other areas) and learns nothing on
     mappings into or out of it. Existing memory neurons still fire.
   - *Manual switch:* `freeze_mapping_plasticity()` (one mapping) and
     `set_memory_area_learning_frozen()` (one memory area). These are brain-instance state, not
     genome: kept in brain snapshots, cleared on genome reload. The Brain Visualizer "Learning"
     toggle sets the same switches.
   Read: `watch_mapping_weights()` flat under co-firing; `get_memory_area_runtime_config()`
   `created_total` flat.
3. **Salience-gated memory formation.** `memory.formation` at -100, `set_area_modulators()` on the
   memory area. Driver active means blocked, so make the driver tonic (steady drive) and let the
   salient event inhibit it through an inhibitory mapping: formation opens only then. (Design
   inference, not run end to end.) To stop all learning in the area, not only creation, use `memory.freeze` (recipe 2). Read: `get_memory_area_runtime_config()`
   `formation_suppressed_total` rises while `created_total` stays flat.
4. **Attention or arbitration.** Subscribe each candidate path's mapping to its own
   `synaptic.gate` (m = +100) whose driver the path's selector feeds: only the selected path
   conducts. Or subscribe the loser's mapping to `synaptic.transmission_gain` at -100 driven by
   the winner. The effect starts one burst late and lasts `effect_duration_bursts`; keep both
   short. Read: `probe_area_response()` with the selector on and off (gate shut: 0 spikes).
5. **Context excitability (mode switch, e.g. stance vs swing).** `neuro.firing_threshold` or
   `neuro.leak` on the area, driver fed by the mode signal, `set_area_modulators()`. Size m from
   the numbers: new threshold = T x (1 + m/100) must fall between the area's input drive and
   its old threshold. Read: `hold_stimulus()` on the mode driver, area `fire_fraction` held on
   versus off.
6. **Exploration.** `neuro.firing_probability` is excitability, not noise: it only blocks a
   neuron that already crossed threshold, and the blocked neuron keeps its charge and retries
   (neural_dynamics.rs:701-720). Drive a tonic area whose excitability is below 1 into the
   candidate paths; a modulator at m < 0 lowers it further in a phase. The draw is a
   deterministic hash of neuron id and burst, so runs repeat. Read: `fire_fraction` is about
   (1 + m/100) of the crossings (test_balance_circuit_regressions.rs:156-194).
7. **Graded modulation from a magnitude area.** Adopt the area as driver (`driver_cortical_id`,
   duration 1, rest 0), `graded` true, `full_scale_potential` = the MP that means full strength.
   Use a one-neuron area. Read: drive three MP levels with `stimulate_area()` and compare the
   target quantity against m/100 x min(MP / full_scale, 1).
8. **Neuromodulated gain control.** `synaptic.transmission_gain` on the path to scale, graded
   driver from the level signal. Read: `probe_area_response()` destination response ratio
   versus 1 + s.

## Pitfalls

- A reward subscription makes plain `stdp` reward-gated: no potentiation or new synapses while the
  driver is silent (npu.rs:6484-6490; test_balance_circuit_regressions.rs:111-153). Rewards on one
  rule sum, so +100 with -100 firing together gives 0.
- `set_area_modulators()` and `set_mapping_modulators()` replace the whole list: pass existing ids.
- Persistence: areas and rules name modulators by id; the registry (`genome.modulators`) is
  separate and no check at genome load compares one against the other. If the registry is lost
  while subscriptions remain, the build only logs per-mapping errors (connectome_manager.rs:8186).
  A plastic rule then fails with "lists modulators that are not synaptic instances" (5421) and
  connectome reload returns that error (6860, 7282). A non-plastic gate or gain rule gets group 0
  with no error and conducts ungated (5783-5786; synaptic_propagation.rs:268-275). After any
  save, restore or restart compare `list_modulators()` with `modulator_usage()` per id.
- `delete_modulator()` is refused while subscribers exist (genome_service_impl.rs:1876-1883);
  `force=True` strips them. A type change is refused while subscribers exist (1763-1767).
  Deleting an adopted driver area drops its modulator.
- Any group factor other than 1, including a closed gate, turns off the propagation fast path
  (synaptic_propagation.rs:462); the cost was not measured.
- While an area is subscribed to `neuro.*`, its parameter is rewritten from a stored baseline;
  unsubscribing restores it (engine:431-465).

## Tools

| Need | Tool |
|---|---|
| Types, instances, subscribers | `list_modulator_types()`, `list_modulators()`, `get_modulator()`, `modulator_usage()` |
| Create (or adopt a driver), edit, rename, delete | `create_modulator()`, `update_modulator()`, `rename_modulator()`, `delete_modulator()` |
| Subscribe an area | `set_area_modulators()`, `unsubscribe_area_modulator()` |
| Subscribe a mapping | `set_mapping_modulators()`, `unsubscribe_mapping_modulator()` |
| Fire a reward driver by hand | `POST /v1/training/reward` or `/punishment`, body `{"modulator_ids": [...]}`; reward needs m > 0, punishment m < 0 (training.rs:316-370) |
| Fire any other driver | `stimulate_area()` or `hold_stimulus()` on the driver area |
| Build from a spec | `build_circuit_from_spec()`: `areas[].modulators` and `mappings[].modulators` take existing ids only; a spec cannot create modulators, so create them first (circuit_spec.py:14-16) |

## Unverified

- Hold length of one trigger is unit-tested (engine:823) but not driven through a brain.
- Threshold 0 (`neuro.firing_threshold` at -100): whether an idle neuron then fires.
- Graded signal at brain level, and which neuron is first in a multi-voxel driver.
- Whether `inspect_neuron_state_at()` shows the modulated or the baseline threshold.
- Recipe 3 wiring and recipe 5 sizing are inferences from the signal rules.
