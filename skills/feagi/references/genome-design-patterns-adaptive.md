# Genome design patterns: memory, learning, orchestration

Block catalog, part 2, for [genome-design.md](genome-design.md). Sensing, features, decisions,
safety and output: [genome-design-patterns.md](genome-design-patterns.md). Read one entry with
`genome-design-patterns-adaptive#<heading>`.

Tags: **live** = built and verified in a live brain. **design** = unverified live, from a
design document (named); re-verify before relying on it. N = positions (W x H), D = depth, F =
feature planes. Credit rules: [memory-plasticity-stdp.md](memory-plasticity-stdp.md#credit-assignment-read-before-training-with-reward).

## Contents

- Memory: Time-series cascade; Classifier
- Learning: Plastic readout with a teacher clamp; Reward-gated reflex with candidate signs; Learned state to command
- Orchestration: Phase gating; Salience gating; Arbitration

## Memory

### Time-series cascade
- **Tag:** live (ECG cascade, memory-and-plasticity.md). **When:** one scalar sampled once per burst whose shapes matter.
- **Shape:** four `[1,1,1]` memory areas: slope (depth 2, `mp_differential`), motif (8, `mp_differential`), contour (32, `mp_ratio`), motif sequence (8, `none`). Wiring table in memory-and-plasticity.md.
- **Synapses:** a handful of `episodic_memory` and `associative_memory` edges between `[1,1,1]` areas; memory neurons grow per new pattern, bounded by `memory_neuron_cap`.
- **Pitfall:** the input must fire, or samples drop out of the hash; window seconds = `temporal_depth` / burst Hz; retune `delta_quantization`.
- **Verify:** `get_memory_area_runtime_config()` twice, 45 s apart: `neuron_count` stops growing.

### Classifier
- **Tag:** live (0/10 to 10/10 per class after 20 presentations).
- **When:** the output is one class per whole input pattern. **Rules:** `create_classifier()`; sample area via `classifier_sample`, class area via `classifier_class`; `update_classifier()` with `reward_training` true.
- **Synapses:** memory neurons only: one link per (pattern, class) pair; default answer delay 3 bursts.
- **Pitfall:** one pattern per input area, so never for per-pixel output; separate stimulate calls corrupt training.
- **Verify:** `inspect_classifier()`, then `run_stimulus_protocol()` train and test; links via `diagnose_mapping_plasticity()`.

## Learning

### Plastic readout with a teacher clamp
- **Tag:** design, **unverified live** (Cityscapes plan, block 5; sizing from code reading).
- **When:** per-position labels learned from a teacher. **Shape:** D class neurons per position fed by F feature planes through one `stdp` rule per plane (`plasticity_window` 1, `max_weight` 1); start weight = the rule's PSC multiplier.
- **Teacher:** an excitatory clamp (PSC >= threshold) plus an inhibitory one-hot-to-wrong-classes edge on the same burst; the winner stage acts a burst late, so wrong classes would co-fire and collect LTP.
- **`plasticity_eta` sizing:** the step is `plasticity_constant` x `ltp_multiplier` (integer >= 1). With 1 and 4 (LTD 1), eta 0.005 makes one co-fire add 0.02 and one one-sided burst remove 0.005 (1 to 2% of `max_weight`). At eta 1 one event saturates or zeroes a weight.
- **Synapses:** F x D x N plastic, plus 2 x N x D teacher edges (17 x 19 x 8,192 = 2.65M at 128x64).
- **Pitfalls:** weights floor at 0 (ship complement planes); a rare class collects LTP rarely and decays to silence (per-class areas give each its own rates); the teacher must reach the layer on the same burst as the features (clamp delay = feature depth - teacher depth).
- **Verify:** `watch_mapping_weights()` on two rules, `diagnose_mapping_plasticity()` after one pass, `list_area_synapses()` for the start weight.

### Reward-gated reflex with candidate signs
- **Tag:** design (walking genome design, stage 1: acceptance median hold >= 2x the reflex-only median).
- **When:** tune the gain and timing of a reflex whose sign was measured. **Rules:** wire the measured-sign reflex first; `rstdp` port-to-command mappings subscribed to `synaptic.reward` modulators fed by hard-wired detectors; set LTD 0 if weights drift down while the body stands.
- **To learn the direction itself:** both signs as candidates, quiet start weights (several inputs must agree to fire), exploration, mutual inhibition between the opposite commands. A sign-fixed path can be muted, never flipped.
- **Synapses:** 2 x sources x commands for candidates, plus inhibition between opposite commands.
- **Pitfalls:** reward must pay for the brain's own action, not support; read `plasticity_flag` back before each run; eligibility = reward latency in bursts (40 at 200 Hz in the walking design).
- **Verify:** `diagnose_mapping_plasticity()`, `health_check()` counter `synaptic_plasticity_generation` moving, then the behavior number against the reflex alone.

### Learned state to command
- **Tag:** design (walking genome design, learned gait layer; architect-approved 2026-11-01, unbuilt).
- **When:** learn state -> command while an innate clock keeps time. **Why:** a memory neuron fires only when its upstream pattern matches live fires; a lone memory area classifies states. Sequences come from a chain or hierarchy of memory areas ([memory-design.md](memory-design.md)); this design keeps the innate clock by choice.
- **Rules:** a `[1,1,1]` memory area (`temporal_depth` 1, `mp_encoding` none, `memory_neuron_cap`, `ltm_eviction` lru) fed from the clock and contact areas; one `associative_memory` `rstdp` mapping per command, window >= clock step + 2 bursts; the innate pattern is the teacher and stays as the fallback.
- **Synapses:** one per (state neuron, command neuron) pair that co-fired; none at the start.
- **Pitfalls:** reward consolidation only links two memory neurons, so state neurons go long-term by reactivation (`neuron_longterm_mem_threshold`) or expiry deletes the synapses; `neuro.firing_probability` is not exploration noise.
- **Verify:** `inspect_memory_neuron()`, `diagnose_mapping_plasticity()`, a muted-teacher trial.

## Orchestration

### Phase gating
- **Tag:** design use; the modulator is documented (memory-and-plasticity.md).
- **When:** learn during training, freeze for validate, test and live use. **Rules:** a `synaptic.learning_rate` modulator at -100% on a small driver area (`LearnOff`), subscribed by each plastic rule with `set_mapping_modulators()`; the same driver can carry `memory.formation`.
- **Synapses:** one driver plus one subscription per rule; no synapses are added.
- **Pitfall:** a modulator replaces the full subscription list; include the existing ids. It stops weight commits only; a plain `stdp` associative rule can still create synapses ([modulators.md](modulators.md), recipe 2).
- **Verify:** `modulator_usage()`, then weights unchanged over a test pass (`watch_mapping_weights()`).

### Salience gating
- **Tag:** design use; documented. **When:** memory should form only on moments worth remembering.
- **Rules:** `create_modulator()` type `memory.formation`, magnitude -100; wire the suppress signal into its driver; `set_area_modulators()` on each memory area.
- **Synapses:** one driver edge. **Pitfall:** do not freeze a brain this way unless the task says so.
- **Verify:** `get_memory_area_runtime_config()`: `formation_suppressed_total` rises while `created_total` stays flat.

### Arbitration
- **Tag:** design, **unverified live**; gate and gain semantics are read from code: [modulators.md](modulators.md) (Types, recipe 4).
- **When:** two modules can drive one command. **Cheapest:** a negative-PSC mapping from the winner's driver to the loser's output. **Alternative:** subscribe the loser's output mapping to a `synaptic.gate` or `synaptic.transmission_gain` modulator whose driver is fed by the winner.
- **Synapses:** 1 per arbitrated mapping, plus the driver.
- **Pitfall:** the modulator takes effect one burst later and holds `effect_duration_bursts`; the loser fires in between.
- **Verify:** `probe_area_response()` with and without the winner active.
