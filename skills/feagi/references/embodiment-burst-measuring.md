# Burst rate, measuring behavior, and falls

Part 2 of 2. Agents, joints, simulator ground truth, scene settings, asset packs: [embodiment.md](embodiment.md).

## Contents

- Choosing the burst rate
- Measuring behavior
- Death and falls

## Choosing the burst rate

The burst rate is a design choice tied to the body, never a default. Studio defaults to
10 Hz (`burst_engine_timestep` 0.1) and the genome's value overrides it; neither knows the
robot.

- **Find the fastest dynamic the brain must react to.** Unstable tasks (standing,
  balancing): the pendulum time constant `tau = sqrt(h/g)`, h = centre-of-mass height (a
  0.11 m biped: tau about 0.1 s). Confirm it from a trace with the motors quiet as the
  median 5-to-15 degree fall time. Tracking or reaching: the joint or target settling time.
  Slow tasks (wheeled driving at low speed, slow reaching) may land at a low rate, but derive it and record the derivation; never keep 10 Hz as an unexamined default.
- **No body (dataset tasks: classification, segmentation, tables, recorded signals).** Nothing
  physical sets a deadline. The Trainer counts time in ticks (bursts), so the rate only sets
  the wall time per sample. Run at the highest rate the brain sustains: raise the setpoint,
  then read `get_runtime_metrics(measure_s=5)`, and keep the highest setpoint whose measured
  rate holds within about 10% of it (design guidance; derive your own margin). Recheck after
  the brain grows. Burst-counted settings keep their meaning, because every timing is in
  bursts. A low default is never a reason to run slowly, and neither is a body rule carried
  over from robot work.
- **Count loop latency in bursts.** Synaptic hops from sensor IPU to motor OPU
  (`trace_signal_path()`), plus about one burst each way for transport. Latency in seconds
  is bursts / burst_hz, or bursts x sim time per burst in lock-step.
- **Rule of thumb: loop latency at most tau/4 for stabilizing feedback.** So
  `burst_hz >= 4*(hops + 2)/tau`, or sim time per burst `<= tau/(4*(hops + 2))`. Example
  (one small biped, a worked example to derive your own from): 3 hops + 2 transport, tau about 0.1 s needs at least 200 Hz in real
  time, or at most 5 ms of sim time per burst in lock-step. The same biped at 10 Hz: latency
  0.30 s equaled the median fall time, so no circuit could balance it.
- **Ceilings.** The burst must finish inside its period (`get_runtime_metrics(measure_s=5)`: `burst_timing.measured` gives the achieved rate and shortfall; burst duration and missed bursts are not reported by FEAGI, `burst_timing.gap` names the endpoints); the
  controller and sensors must keep up (no gain above the sensor sample rate); servo slew
  limits. When the required rate exceeds the ceiling, shorten the sensor-to-motor path (a
  direct reflex path) or run the simulator in lock-step (sim time advances a fixed step per
  burst). Never slow the robot's physics as a stand-in.
- **Also check the sensor frame rate (frames per burst) and the motor step size** against the chosen rate: a burst faster than the frame rate repeats stale frames, and the per-burst motor step must stay inside servo slew.
- **Burst-counted settings change meaning in seconds when the rate changes:** R-STDP
  windows, modulator holds, memory `temporal_depth`, refractory and leak timing, Trainer
  `holdBursts`, `attemptBurstCap`, `settleBursts`. Rescale them in the same change as the rate, and record the derivation in the design notebook.
- **Change the rate with one call:** `set_burst_engine_frequency(frequency_hz)`. The
  returned `burst_frequency_hz` is the confirmation. Do not search the source tree, call
  physiology or `simulation_timestep`, or sample `get_burst_counter` unless the user asks
  whether the engine is keeping the period. A later genome reload can restore the stored
  physiology timestep; say so in one sentence. It is not a second call.

## Measuring behavior

Take a baseline with these before building toward a behavioral goal, and re-run them after
each stage. Both read the controller's physics endpoint directly, so they need a running
experiment (`_experiment.state` is `running`).

- `measure_balance(duration_s, controller_id, upright_deg, fall_deg)`: samples the
  simulator at 20 Hz for up to 25 s and returns numbers only: `reset_count` (clock drops),
  `episode_length_s` (ended episodes with mean, median, max, plus the ongoing one),
  `upright_fraction`, a 10-degree tilt histogram, `recoveries`, `falls`, and
  `fall_confirmation_latency_s` (fall threshold to reset). Each call carries a
  `window_id`; for a longer measurement make repeated calls and keep the ids. Tilt comes
  from the trunk free joint's quaternion; pass `free_joint` if the robot's root is not
  auto-detected. Compare windows by their numbers, not by impression.
- `record_aligned_trace(duration_s, areas, signals)`: one timeline pairing each sampled
  burst with the physics at that moment, for up to 20 s and 64 areas. The full trace is in
  `<feagi-mcp>/var/traces/<trace_id>.jsonl` (absolute `trace_path` in the result; `FEAGI_MCP_TRACES_DIR` overrides); the result is per area a run-length list of the bursts on
  which it fired with pitch, roll, tilt, trunk height and the chosen actuator targets at
  the start of each run. Use it to answer "did the tilt bin fire before the nudge voxel,
  and did pitch change after?" with burst numbers. `bursts_missed_by_sampler` says how
  many engine bursts FEAGI's sampler skipped.
- `analyze_run(csv_path, ring=..., port_in_window=..., window_counts=..., duty=...)`: acceptance
  numbers from a spikes CSV (a Trainer run's `neural/spikes.csv` from `list_run_data`, or a
  `record_spikes` `csv_path`): ring period mean/sd/cycles and bins visited, the share of a
  port's spikes inside a phase window at a lag, an area's spikes in and out of a window (resets
  in/out of window), and duty with off-episodes per half-cycle. Quote its numbers.
- `check_live_state_drift()` after any controller restart: re-registration re-applies the
  controller's IPU/OPU dimensions and can revert hand-widened areas. The result names each
  drifted value and the `update_cortical_area()` or `set_burst_engine_frequency()` call
  that restores it.
- `embodiment_measure_bodies(bodies, contacts)`: one read-only snapshot of named bodies from
  the controller's `measure` primitive: tilt, `com` (height), per contact set `touching`,
  `bodies` in contact and `normal_force_n`, and the spring report. A contact set takes `a`
  or `a_except` (every body except those listed, their descendants and the world), and `b`
  `"world"` or a list.
- For joint trajectories over time without brain alignment, the Studio tools
  `record_embodiment_trace` and `run_embodiment_trial` remain the right choice.

## Stimulus presentation and reading at high burst rates

At high burst rates `run_stimulus_protocol` posts land about every other burst and its reads miss bursts (measured once at 200 Hz). For burst-exact presentation use `schedule_stimulus`; for burst-exact reading use `record_spikes`.

## Death and falls

- Death resets the scene and ends a Trainer attempt as death.
- Never drive Death from tilt, a fall detector, floor contact, a learning or affect signal,
  or a timer. A fallen robot must stay in the scene so it can learn to recover.
- Attempt endings for balance or locomotion belong to the Trainer: max tilt, Pain,
  truncation.
- An existing fall > Death path is a bug to remove. Worked example: an accumulating zero-leak
  detector fired Death every ~0.7 s, 42 times in 31 s, and gave 0/40 Trainer successes.
- Check before any Trainer run: nothing maps into Death from sensory or vestibular areas,
  and Death fires 0 times in 20 s. Count `[DEATH]` lines in the MuJoCo controller log, or
  use `monitor_activity` on Death.

## Exact argument shapes (acceptance and pulse tools)

Every area argument of every area tool (`area_id`, `src_area`, `cortical_id`, `areas`, `stimuli[].area_id`, ...) accepts a base64 id or the area's exact display name. A valid id passes through; a name must match one area exactly; an unknown or ambiguous name is an error that lists close matches.

- `analyze_run` (one entry per metric, all optional; `bins` is a list or `"3..7"`):
  - `ring={"area": "Phase", "anchor_bin": 0}`
  - `port_in_window=[{"port": "Gate", "phase_area": "Phase", "bins": "3..7", "lag": 0}]`
  - `window_counts=[{"area": "Reset", "phase_area": "Phase", "bins": "3..7"}]` (`phase_area` and `bins` are required)
  - `duty={"area": "Port", "phase_area": "Phase", "bins": 12}`
- `schedule_stimulus(entries=[{"burst_offset": 0, "stimuli": [{"area_id": "Gate", "coordinates": [[0, 0, 0]]}]}])`: offset 0 is the next burst; all areas of one entry fire on the same burst. Optional `repeat_period_bursts` (> the largest offset) replays the entries at offset + k*period until cancelled. The result has `schedule_id`, `start_burst`, `end_burst` (null when repeating). Hold an area on: one entry at offset 0 with `repeat_period_bursts=1`, stop it with `cancel_stimulus`.
- `cancel_stimulus(schedule_id=3)` drops entries not yet fired, and ends a repeating schedule (404 once finished).
- `get_stimulus_schedule()` lists active schedules: ids, burst range, remaining entries, `next_burst`, and `repeat: {period_bursts}` for repeating ones.
- `get_cortical_map_detailed(cortical_id="Gate", compact=true)` keeps only the mappings where that area is source or destination (no argument: the whole map).
