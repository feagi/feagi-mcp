# Lessons: learning facts

Part 2 of 3 of [lessons.md](lessons.md). Embodiment facts: [lessons-embodiment.md](lessons-embodiment.md).

## Contents

- Learning facts

## Learning facts

- **Plastic synapses start at the rule's multiplier, not random.** A synapse created from a
  mapping rule (plastic or not) gets weight `abs(postSynapticCurrent_multiplier)` as f32 (default
  1.0 when absent; a negative multiplier makes it inhibitory), in `resolve_synapse_params_for_rule`
  (`feagi-core/crates/feagi-brain-development/src/connectome_manager.rs`). The effective PSP is
  that weight times the source area's `postsynaptic_current`. `max_weight` does not clamp the
  initial value: it is only applied to positive plasticity commits,
  `(old + delta_w).min(max_weight)` (`feagi-core/crates/feagi-npu/burst-engine/src/npu.rs`), so a
  start weight above `max_weight` stays until the first potentiating commit snaps it down.
  `diagnose_mapping_plasticity` reports this as `expected_initial_weight`.
- **Exact-pattern memory needs a tiny source.** A memory area fed by multi-column bins minted
  1,475 state patterns in 60 s and never levelled. Feed memory from a source with at most a
  few dozen possible patterns (for example pitch direction x magnitude), `temporal_depth` 1,
  and confirm with two reads of `get_memory_area_runtime_config()` 45 s apart that
  `neuron_count` has stopped growing.
- **An associative link starts with no synapses.** A mapping from a memory area onto an
  ordinary area is accepted only as `associative_memory`. A live build recorded zero
  synapses on that link and treated it as a dead mechanism. The observation did not check
  whether a neuron in each area fired inside the rule's `plasticity_window`, so it is not
  evidence that the link cannot drive an action. Zero synapses right after wiring is the
  starting state. A synapse is created only when a neuron in the memory area and a neuron
  in the destination area both fire inside that window. If the rule subscribes to a
  `synaptic.reward` modulator, the reward must also be positive in the window. The memory
  neuron firing alone does not create the synapse; the destination neuron has to fire in
  the same window, driven by babble, a reflex, or a teacher. Confirm that co-firing, then
  read `diagnose_mapping_plasticity()` and `inspect_memory_neuron()`. An empty synapse
  list before the co-firing is not a reason to replace the link with a hand-wired ordinary
  mapping. Detail: [memory-and-plasticity.md](memory-and-plasticity.md).
- **Reward-modulated plasticity commits through modulators.** An `rstdp` rule with
  `reward_source_area` / `punishment_source_area` was accepted but never changed a weight,
  while the same mapping subscribed to `synaptic.reward` modulators (one at +100 driven by
  the reward detector, one at -100 driven by the fall detector) changed weights within 20 s.
  Check with `diagnose_mapping_plasticity()` and the `synaptic_plasticity_generation`
  counter in `health_check()`.
  Modulator semantics: [modulators.md](modulators.md).
- **Base plasticity potentiates without reward.** Co-active pairs on a plastic rule drift
  upward even when no reward fires. Make the reward detector reachable (it must fire in
  normal operation) and keep the Hebbian step small, or the actor self-reinforces.
- **Learned classifier links died with short-term memories.** Interleaved training formed
  links but every pattern's memory neuron expired (9-burst lifespan) before the pattern
  returned, deleting its links, so tests read 0 links and no output. Reward consolidation now
  promotes rewarded memory neurons to long-term. If links still vanish, check that reward
  reached them. Detail: [value-planes-and-classifiers.md](value-planes-and-classifiers.md).
- **Present sample and label in one protocol step.** Separate stimulate calls run one after
  another, and two protocol calls in parallel share bursts and double-post. Both corrupted
  classifier training runs.
- **`diagnose_mapping_plasticity` once read 0 on memory-to-memory mappings** while links
  existed. It now counts them; if numbers disagree with `list_area_synapses()` on the
  destination (incoming), trust the realized synapses and report it.
- **Prove plasticity is alive with a probe.** Two rules on one pair, a strong non-plastic
  `block_to_block` and a weak plastic one, guarantee co-activity; if the plastic weights and
  the generation counter do not move in 45 s, nothing will.

- **`monitor_activity` samples about 1 burst in 10.** Take rates and frame counts from Run data spikes.
- **The leak is applied every burst** (lazy catch-up at input), including bursts with no input.
- **`rate_modulated_leak` `target_mode: "area"` applies one target to every neuron.** Use `per_neuron` for population codes, where silent neurons would otherwise pin at leak_min. Arm while the brain is driven.
- **A snapshot proves state only if its decoded genome shows it.** Decode and check the field before saying it was saved.
