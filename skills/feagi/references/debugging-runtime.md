# Debugging: drift, learning, runtime failure

Part 2 of 2. Verifying connections, watching activity, finding silence: [debugging.md](debugging.md).

## Contents

- Live state drift
- Watch learning
- FEAGI itself is failing
- Silent versus active run
- Known gotchas

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
  check reward modulators and `plasticity_flag` with `diagnose_mapping_plasticity()`, and a left-over freeze switch (it is not in that report; `freeze_mapping_plasticity(frozen=False)` resumes and reads back).
- For memory-to-memory mappings `diagnose_mapping_plasticity()` splits
  `memory_neuron_synapse_count` (learned links) from `placeholder_synapse_count`.
- `freeze_mapping_plasticity(src_area, dst_area, frozen=True)` stops learning on one
  mapping through FEAGI's `PUT /v1/cortical_mapping/plasticity_frozen` (`frozen=False`
  resumes) and reads the state back. The switch belongs to the running brain (kept in brain
  snapshots, cleared on genome reload, not in the genome); the rule, `plasticity_flag`, synapses
  and weights are untouched. `set_memory_area_learning_frozen(area)` does the same for a memory
  area. It needs a plastic rule
  (`freeze_failed` otherwise). `frozen` is the read-back state; `weights_preserved` is false
  if the weight statistics changed.
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
- Tools dropped mid-call: confirm FEAGI is down before blaming it. FEAGI logs events, not
  bursts, so a quiet log while bursts run is normal, not a hang. Call `get_burst_counter()`
  twice a few seconds apart: a rising counter means FEAGI is running. A controller that still
  receives motor frames at the burst rate says the same. When FEAGI is running, the failure is
  in the process between the assistant and FEAGI (the MCP host or server): read that host's log
  for the last call it started.
- Logs: `get_log_tail(message_contains=..., level=..., limit=...)`. Always filter.
- An experiment stopped unexpectedly: `get_experiment_stop_cause()` and
  `get_controller_lifecycle_events()`.
- Version questions: `get_version_info()`.

## Silent versus active run

To show how much of a result comes from the brain rather than the harness, run the same
Trainer attempt twice: once as built, once with the brain's drive switched off by a scheduled
event. In the task setup add `scheduledEvents` (applied each train attempt, restored after the
phase) that set the PSC multiplier of the mapping that carries the command to 0:

```json
"scheduledEvents": [
  {"atS": 0, "label": "silence reflex",
   "action": {"type": "set_mapping_psc", "src": "<sense port>", "dst": "<command port>", "pscMultiplier": 0}}
]
```

`atS` is seconds after the settle window ends; `set_area_parameter` (`{area, key, value}`) can
silence an area by its threshold instead. Use a mapping per command path you want silent, label
each event, and keep every other setting equal (support level, seeds, attempt count). Compare the
two runs' outcome numbers (time upright, tilt RMS): the gap is the brain's contribution. A silent
run that does as well as the active one means the harness, not the circuit, produced the result.

## Known gotchas

- `health_check()` may report 0 connected agents while a simulation works. It counts a
  stricter transport state. If `get_registered_agents()` lists the agent and motor snapshots
  update, the link is live.
- `list_area_synapses()` defaults to outgoing synapses. OPUs are driven by incoming ones:
  pass `direction="incoming"`.
- Deleted vision (`isvi`) areas that keep coming back are recreated from the descriptor
  registration store. Compare stores with `compare_device_registration_store()`.
- `get_cortical_mapping()` reads stored rules safely; prefer it to raw mapping endpoints.
