# Testing and debugging

## Contents

- Verify a new connection
- Watch activity
- Look inside areas and neurons
- Find a broken path
- Common causes of silence
- Live state drift
- Watch learning
- FEAGI itself is failing
- Known gotchas

## Verify a new connection

`probe_area_response(stimulus_area, stimulus_voxels, observe_area, settle_ms, observe_window_ms)`
force-fires voxels in one area and reports whether another area fired more afterward
(`responded`, plus before and after counters). It needs no robot. Run it after every wiring
step, hop by hop for multi-stage circuits, and report the result.

For manual tests:

- `stimulate_area(area_id, coordinates, potential, duration_ms)` fires one voxel;
  `stimulate_area_batch()` fires many in one area.
- `monitor_activity(area_id, duration_ms)` or `monitor_activity_batch(area_ids, ...)` then
  shows counts and rates.

The burst engine must be running for anything to propagate: check
`get_burst_engine_status()`.

## Watch activity

| Need | Tool |
|---|---|
| Firing counts and rates over a window | `monitor_activity()`, `monitor_activity_batch()` (summaries by default) |
| Which neurons fired last burst, per area | `get_fire_queue_detailed()` |
| What sensors delivered last burst | `get_sensor_snapshot_last(cortical_id=..., threshold=...)` |
| What motors received last burst | `get_motor_snapshot_last(cortical_id=...)` |
| Burst rate, counter, run state | `get_burst_engine_config()`, `get_burst_counter()`, `get_burst_engine_status()` |
| System-wide counters | `get_runtime_metrics()`, `health_check()` |

`monitor_activity()` rates are sampled over the window, not counted per burst. A rate near
half the burst frequency on a one-neuron loop does not mean the neuron fires every other
burst; a `block_to_block` self-mapping with delay 1 fires every burst. For per-burst cadence,
read `get_fire_queue_detailed()` on consecutive bursts or use `probe_area_response()`.

Burst control: `control_burst_engine(action)` with `start`, `resume`, `pause`, or `stop`;
`pause_burst_engine()` and `resume_burst_engine()` hold and release;
`set_burst_engine_frequency(frequency_hz)` is the whole rate change. The return confirms
the setpoint. Do not open the source tree or sample the burst counter unless the user asks
whether the engine is keeping that period. Pausing affects every connected robot, so say
so before you do it.

## Look inside areas and neurons

- Area parameters: `get_area_parameters()`, `inspect_cortical_areas_minimal()`, or the full
  record with `inspect_cortical_area()`.
- Neuron states across an area: `list_area_neuron_states(area_id)` (position, membrane
  potential, fire count).
- One voxel: `inspect_neuron_state_at(cortical_id, x, y, z)`, or
  `get_voxel_neurons(cortical_id, x, y, z)` for neurons with summarized synapses
  (`view="edges"` and `synapse_page` for raw pages).
- One neuron by stable id: `get_neuron_state_by_id()`.
- Realized synapses: `list_area_synapses(cortical_area_id, direction="incoming" | "outgoing" | "both")`
  and `get_cortical_synapse_counts()`.

## Find a broken path

1. `trace_signal_path(from_area, to_area, max_hops)`: is there any path?
2. `get_connectivity_summary(src_filter=...)`: which rules sit on each hop?
3. `get_cortical_synapse_counts()` per hop: did the rules produce synapses?
4. `inspect_cortical_areas_minimal()` along the path: threshold, leak, refractory, burst
   engine flag.
5. `probe_area_response()` hop by hop until one stays silent. Fix that hop, then re-probe the
   whole path.
6. For a robot output, `get_motor_snapshot_last(cortical_id=<OPU>)`: if FEAGI emits commands
   but the robot does not move, the problem is on the embodiment side (see
   [embodiment.md](embodiment.md)).

## Common causes of silence

| Symptom | Likely cause | Check or fix |
|---|---|---|
| Destination never fires | Rule exists but no synapses (dimension mismatch, source filter matches nothing) | `get_cortical_synapse_counts()`; rules that need same dimensions (`block_to_block`, `lateral_*`, `transpose_*`) |
| Destination never fires | PSC too low for the threshold, or threshold too high | Raise `postsynaptic_current_multiplier` or lower the threshold |
| Area never fires at all | Burst engine flag off for the area | `inspect_cortical_areas_minimal()` |
| Output saturates or loses magnitude | `mp_driven_psp` off, fan-out, threshold, or accumulation | `validate_magnitude_passthrough()` |
| Activity dies after one hop | Refractory or leak too strong, or single-burst stimulus | Lengthen `duration_ms`, adjust leak |
| Runaway firing | Excitatory loop without inhibition, excitability too high | Add inhibition (negative PSC), raise threshold, add leak |
| CPG does not oscillate | Leak or PSC too low | Raise leak or self-mapping PSC |
| CPG oscillates too fast | Leak too high | Lower leak |
| Servo barely moves | Drive mapped to high Z on a positional servo | Map to `z=0` side (see [connectivity.md](connectivity.md)) |
| Memory area stays empty | No `episodic_memory` upstream, or area is CUSTOM (`c` ID) | `get_memory_area_runtime_config()` |
| Learning does nothing | Plasticity off, window too short, or no co-activation | `diagnose_mapping_plasticity()` |
| Classifier does not stamp output | Scan blockers | `inspect_classifier()` |

## Live state drift

Live state reverts without any error: an agent re-registration re-applies the controller's
IPU/OPU dimensions, a genome reload resets the burst rate, a controller restart registers
a new agent id. `check_live_state_drift()` compares the live brain with the genome
blueprint and the controller descriptor and lists every mismatch with both values and the
restoring call (`update_cortical_area(cortical_id=..., updates=...)` or
`set_burst_engine_frequency(frequency_hz=...)`; an unregistered agent needs a controller
restart). Run it after `health_check()` at the start of a session, after every controller
restart, and before blaming a circuit for going silent. Checks: cortical area dimensions,
burst frequency vs `simulation_timestep`, descriptor `agent_id` vs registered agents, and
IPU width vs the columns present in the last sensor snapshot.

## Watch learning

- `watch_mapping_weights(src_area, dst_area, duration_s, interval_s)` samples one
  mapping's weight statistics over time (min, max, avg, count at 0, count at the
  destination's PSP cap, the five largest and five smallest synapses) and reports
  `avg_delta` and `max_delta`. A flat series while the pair co-fires means no learning:
  check reward modulators and `plasticity_flag` with `diagnose_mapping_plasticity()`.
- `freeze_mapping_plasticity(src_area, dst_area, frozen=True)` stops learning on one
  mapping by rewriting its rules with `plasticity_flag` off (FEAGI has no per-mapping
  freeze route). It reports weights before and after; `weights_preserved` false means the
  rewrite regrew the synapses.
- `reset_mapping_weights(src_area, dst_area)` resets weights in place via FEAGI's native route
  (`method: native`, `synapses_reset`, `weight`). On older FEAGI it deletes and recreates the
  mapping (`method: recreate_fallback`); FEAGI keeps the weight of a neuron pair that already
  existed there, so read `weights_reset`; take `snapshot_genome()` first. For every incoming
  mapping of an area use `reset_area_incoming_weights(cortical_ids)`.
- `inspect_cortical_areas_minimal()` now falls back to the incoming synapse listing when
  the properties record reports `incoming_synapse_count` 0 (`incoming_synapse_count_source`
  says so); the counter in the properties record stays 0 after a restart.

## FEAGI itself is failing

- Calls fail intermittently: `get_feagi_link_health()` checks FEAGI, the agent registries,
  the burst endpoint, and controller registration in one call.
- FEAGI does not answer HTTP: `diagnose_feagi_runtime()` reads local logs and returns a
  `likely_cause` (`feagi_unreachable`, `health_check_timeout`, `npu_watchdog_stall`,
  `npu_lock_during_structural_rebuild`, `npu_missing_cortical_registration`,
  `outstanding_control_reply_then_client_stop`) with evidence.
- Health is fine but an upload, genome change, or experiment launch failed:
  `get_last_failed_mutation()`.
- Logs: `get_log_tail(message_contains=..., level=..., limit=...)`. Always filter.
- An experiment stopped unexpectedly: `get_experiment_stop_cause()` and
  `get_controller_lifecycle_events()`.
- Version questions: `get_version_info()`.

## Known gotchas

- `health_check()` may report 0 connected agents while a simulation works. It counts a
  stricter transport state. If `get_registered_agents()` lists the agent and motor snapshots
  update, the link is live.
- `list_area_synapses()` defaults to outgoing synapses. OPUs are driven by incoming ones:
  pass `direction="incoming"`.
- Deleted vision (`isvi`) areas that keep coming back are recreated from the descriptor
  registration store. Compare stores with `compare_device_registration_store()`.
- `get_cortical_mapping()` reads stored rules safely; prefer it to raw mapping endpoints.
