# Testing and debugging

Part 1 of 2: verifying connections, watching activity, finding silence. Live state drift, learning, FEAGI failures, silent-versus-active runs, gotchas: [debugging-runtime.md](debugging-runtime.md).

## Contents

- Verify a new connection
- Watch activity
- Record every burst and hold a stimulus
- Look inside areas and neurons
- Find a broken path
- Common causes of silence

## Verify a new connection

`probe_area_response(stimulus_area, stimulus_voxels, observe_area, settle_ms, observe_window_ms)`
force-fires voxels in one area and reports whether another area fired more afterward
(`responded`, plus before and after counters). It needs no robot. Run it after every wiring
step, hop by hop for multi-stage circuits, and report the result.

For manual tests:

- `stimulate_area()` / `stimulate_area_batch()` fire one area for one burst by default;
  `bursts=N` (or `duration_ms`) holds the stimulus for N consecutive bursts. Separate calls
  run one after another, never together.
- To present several areas together (sample + label, two inputs of a gate), or a timed
  sequence with rests, use `run_stimulus_protocol(steps, record_areas)`: one request per burst
  carries all stimuli. It also reads the fire queue every burst, so at 200 Hz it skips about a
  fifth of the bursts and returns a large payload (it records from the sampled fire queue, so
it sees one burst in five too). Stimulus and record areas may be names or ids; an unknown name or
a stimulus that matches no voxel is an error; for a long hold or per-burst data use
  `hold_stimulus()` and `record_spikes()` below. Run one protocol call at a time.
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
| Every burst of up to 64 areas, summarized (fire fraction, runs, gaps) | `record_spikes()` |
| A stimulus held on every burst, with a landing check | `hold_stimulus()` |
| Per-burst firing during a short stimulus sequence | `run_stimulus_protocol()` |

`get_fire_queue_detailed()` returns `timestep` (the burst the sample belongs to) and
`current_burst`. `monitor_activity()` polls about every 50 ms, counts each burst once and
reports `bursts_unsampled`; above 20 Hz it misses bursts (about one burst in five is seen at
200 Hz, as with `get_fire_queue_detailed()`), so use `record_spikes()` when every burst matters.

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

## Record every burst and hold a stimulus

`record_spikes(areas, bursts=200, csv_path=None)` reads FEAGI's Fire Ledger
(`/v1/burst_engine/fire_history`): one frame per burst per area, silent bursts included. It
returns a summary, never rows: per area `fire_fraction`, `fired_bursts`, `first_fire_burst` /
`last_fire_burst`, fire `runs` (the first 20 per area; `max_runs` raises the limit, `run_count` is
the full count, `runs_truncated` says if more exist), `top_voxels`, and for the window `gaps` (bursts with no frame;
`success` is false if any). Rows go to `csv_path` as `burst,area_id,area_name,x,y,z,
memory_neuron_id`. Up to 64 areas and 20000 bursts. A plain call waits `bursts` × the burst
interval, and one that would wait longer than about 50 s is refused, because MCP clients cut
long tool calls. For a longer window pass `background=True`: it returns a `recording_id` at
once, and `get_spike_recording(recording_id)` returns the same summary under `result` once
`state` is `done` (`cancel=True` ends it early with what was recorded). Drive the areas
with `hold_stimulus(background=True)`.

`hold_stimulus(area, voxels, duration_s, background=False)` posts the stimulus on a wall-clock
schedule (twice per burst; the pending queue dedupes) and reads nothing per burst. With
`verify` (default) it reads the area's ledger afterwards and reports `landed`: of the bursts in
`(first_post_burst, last_post_burst + 1]`, how many fired every held voxel, which did not, and
which have no ledger frame. A hold is only trusted with that line: `landed == checked`.
A foreground hold lasts at most 30 s (one tool call), a background hold at most 600 s.
`background=True` returns a `hold_id` and keeps holding while you trace or record; read the
outcome with `get_stimulus_hold(hold_id)`, and stop it early with
`get_stimulus_hold(hold_id, cancel=true)`. For pulses on exact bursts use
`schedule_stimulus(entries=[{burst_offset, stimuli}])` (`cancel_stimulus(schedule_id)` stops it,
`get_stimulus_schedule()` lists active ones). Summarize a recorded CSV with `analyze_run`.

Recipe, a held stimulus and its response in one window:

1. `hold_stimulus(area, voxels, duration_s=10, start_delay_s=1, background=True)`.
2. `record_spikes([stimulated_area, response_areas...], bursts=<covers 12 s>)` in the same turn.
3. Read `fire_fraction` and `first_fire_burst` of the response areas against the hold's
   `first_post_burst`; then `get_stimulus_hold(hold_id)` for the `landed` check.

Both use the same per-area ledger subscription; they release it when done (a second user in the
same server process keeps it alive). A subscription also lapses on its own after five minutes
without a read.

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
| Hidden area drifts to runaway or silence while weights learn | No rate regulation | `rate_modulated_leak` (memory-and-plasticity.md); it cannot stop single-burst threshold crossings |
| CPG does not oscillate | Leak or PSC too low | Raise leak or self-mapping PSC |
| CPG oscillates too fast | Leak too high | Lower leak |
| Servo barely moves | Drive mapped to high Z on a positional servo | Map to the bins `convert_io_value` shows as the high command (see [connectivity.md](connectivity.md)) |
| Memory area stays empty | No `episodic_memory` upstream, or area is CUSTOM (`c` ID) | `get_memory_area_runtime_config()` |
| Learning does nothing | Plasticity off, window too short, or no co-activation | `diagnose_mapping_plasticity()` |
| Classifier does not stamp output | Scan blockers | `inspect_classifier()` |
