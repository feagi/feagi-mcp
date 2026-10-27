# Robots, simulators, and embodiment

## Contents

- Agents and device registrations
- Driving joints
- Matching the genome to the robot
- Simulator ground truth
- Choosing the burst rate
- Measuring behavior
- Death and falls
- MuJoCo scene settings
- Simulator asset packs

## Agents and device registrations

A robot or simulator connects to FEAGI as an **agent** and registers its devices: sensors
become IPU areas and actuators become OPU areas, grouped by `group_id` (unit index).

| Need | Tool |
|---|---|
| Which agents are connected | `get_registered_agents()`, `get_agent_liveness()` |
| Controllers running on this machine (MuJoCo, xArm, ROS 2) | `list_controller_bridges()`, `get_embodiment_status()` |
| One agent's details | `get_agent_properties(agent_id)` |
| Motor groups at a glance | `get_motor_group_summary()` |
| Joint or actuator to OPU mapping, with ranges | `get_agent_joint_map(agent_id)` |
| Full sensor and motor structure | `get_agent_device_registrations(agent_id)` (large; prefer the two above) |
| How agents connect (ZMQ/WebSocket endpoints) | `get_agent_connection_endpoints()` |

## Driving joints

`send_motor_command(agent_id, joint_name, target_value)` moves one joint to a target in its
native units (degrees for servos). It looks up the OPU, maps the value to a voxel, and fires
it. Prerequisites: the controller bridge is running, the agent is registered, and the burst
engine is running. Get joint names and ranges from `get_agent_joint_map()` first.

To learn which OPU column moves a sensor in which direction before wiring a reflex, use
`auto_polarity_probe(opu_id, sensor_id)`; add `include_mujoco_physics=True` to compare with
simulator ground truth.

## Matching the genome to the robot

When a robot does not respond, check that the genome's OPUs are the ones the agent reads:

1. `get_registered_agents()` for the agent id.
2. `get_motor_group_summary()` or `get_agent_joint_map()` for group ids and control modes.
3. `list_io_areas_compact()` for the OPUs the genome has, with `dev_count` and mismatches.
4. `explain_cortical_area_naming()` for any OPU whose title is unclear.
5. Missing OPU: `create_io_area_for_unit()` with the right subtype and `unit_index`, then
   wire it.
6. Verify with `get_motor_snapshot_last(cortical_id=...)` and watch the robot.

## Simulator ground truth

- Check the experiment first: `get_experiment_status()`, or `_experiment` on the physics,
  motor and bridge tools. When `state` is `stopped`, the controller keeps serving the last
  frame, so a constant `time` means the experiment is stopped, not that the simulator froze.
  Ask the user to run the experiment before testing behavior on the robot.
- `embodiment_discover_introspection_endpoint()` finds a controller's introspection URL.
- `embodiment_get_physics_state()` reads actuator controls and joint positions from the
  simulator.
- `embodiment_set_joint_state(joint_qpos=..., joint_qvel=...)` places joints directly (for
  example to tilt a pendulum before a test).
- `embodiment_reset_simulation_time_stats()` resets the simulation-speed benchmark.

## Choosing the burst rate

The burst rate is a design choice tied to the body, never a default. Studio defaults to
10 Hz (`burst_engine_timestep` 0.1) and the genome's value overrides it; neither knows the
robot.

- **Find the fastest dynamic the brain must react to.** Unstable tasks (standing,
  balancing): the pendulum time constant `tau = sqrt(h/g)`, h = centre-of-mass height (a
  0.11 m biped: tau about 0.1 s). Confirm it from a trace with the motors quiet as the
  median 5-to-15 degree fall time. Tracking or reaching: the joint or target settling time.
  Slow tasks (classification, wheeled driving at low speed, slow reaching) tolerate 10 Hz.
- **Count loop latency in bursts.** Synaptic hops from sensor IPU to motor OPU
  (`trace_signal_path()`), plus about one burst each way for transport. Latency in seconds
  is bursts / burst_hz, or bursts x sim time per burst in lock-step.
- **Rule of thumb: loop latency at most tau/4 for stabilizing feedback.** So
  `burst_hz >= 4*(hops + 2)/tau`, or sim time per burst `<= tau/(4*(hops + 2))`. Example
  (Howard, microduck): 3 hops + 2 transport, tau about 0.1 s needs at least 200 Hz in real
  time, or at most 5 ms of sim time per burst in lock-step. Howard ran at 10 Hz: latency
  0.30 s equaled the median fall time, so no circuit could balance it.
- **Ceilings.** The burst must finish inside its period (`get_runtime_metrics()`); the
  controller and sensors must keep up (no gain above the sensor sample rate); servo slew
  limits. When the required rate exceeds the ceiling, shorten the sensor-to-motor path (a
  direct reflex path) or run the simulator in lock-step (sim time advances a fixed step per
  burst). Never slow the robot's physics as a stand-in.
- **Burst-counted settings change meaning in seconds when the rate changes:** R-STDP
  windows, modulator holds, memory `temporal_depth`, refractory and leak timing, Trainer
  `holdBursts`, `attemptBurstCap`, `settleBursts`. Rescale them only when the user asks.
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
  burst with the physics at that moment, for up to 20 s and 16 areas. The full trace is in
  `<feagi-mcp>/var/traces/<trace_id>.jsonl` (absolute `trace_path` in the result; `FEAGI_MCP_TRACES_DIR` overrides); the result is per area a run-length list of the bursts on
  which it fired with pitch, roll, tilt, trunk height and the chosen actuator targets at
  the start of each run. Use it to answer "did the tilt bin fire before the nudge voxel,
  and did pitch change after?" with burst numbers. `bursts_missed_by_sampler` says how
  many engine bursts FEAGI's sampler skipped.
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

## Death and falls

- Death resets the scene and ends a Trainer attempt as death.
- Never drive Death from tilt, a fall detector, floor contact, a learning or affect signal,
  or a timer. A fallen robot must stay in the scene so it can learn to recover.
- Attempt endings for balance or locomotion belong to the Trainer: max tilt, Pain,
  truncation.
- An existing fall > Death path is a bug to remove. Howard: an accumulating zero-leak
  detector fired Death every ~0.7 s, 42 times in 31 s, and gave 0/40 Trainer successes.
- Check before any Trainer run: nothing maps into Death from sensory or vestibular areas,
  and Death fires 0 times in 20 s. Count `[DEATH]` lines in the MuJoCo controller log, or
  use `monitor_activity` on Death.

## MuJoCo scene settings

These change the **running** MuJoCo simulation, the same settings as the desktop MuJoCo
Settings dialog. They are not cortical areas and not asset-pack XML.

- Read first: `get_mujoco_scene_config()`.
- **Safety box**: `set_mujoco_safety_boundary(enabled, workspace_min_mm, workspace_max_mm)`.
  Corners are millimeters `[x, y, z]`. If the user gives no numbers, choose a box around the
  robot and say what you chose.
- **Add an object**: `add_mujoco_scene_object(object_id, shape, size_mm, position_mm, dynamic, mass_g, friction)`.
  Positions and sizes are millimeters; `size_mm` is `[radius]` for a sphere,
  `[radius, half_length]` for a capsule, or three half-extents for a box. A weight means `dynamic=True` with `mass_g` in grams. `friction` is
  `[sliding, torsional, rolling]`; omit it for MuJoCo defaults. Other objects stay.
- **Cameras, IMU/motors, environment feedback, body attachments**: read the config, then
  `configure_mujoco_scene(action, body)` with a full replacement document (`apply_*` actions
  replace the whole list). Body-mounted cameras use `offset_mm` in the body frame so the
  camera sits outside the mesh. Attaching MJCF (for example a hand) through `xml_mounts`
  needs a choice from the user first: `io_mode=full` (motors and sensors, needs a restart so
  FEAGI creates areas, a stable `device_id`, and a `feagi_group` above the host's limb count)
  or `io_mode=geometry` (mesh only).
- `configure_mujoco_scene(action="save_mujoco_general", ...)` with `controllerLoopRateHz`
  sets how often the embodiment reads sensors and applies commands on the **next** launch. It
  does not change the physics timestep or the FEAGI burst rate.
- If a tool reports a missing control URL, ask the user to restart the MuJoCo controller.
  Never invent MJCF as a substitute.

## Simulator asset packs

The Composer catalog lists shared simulator asset packs (props, scenes). Listing needs
`FEAGI_COMPOSER_BASE_URL` set for the MCP server.

- "What assets can I add?": `composer_list_simulator_packs(engine="mujoco")` first. Present
  each pack by title with one plain sentence from its description; skip raw IDs and versions
  unless the user needs them. Never invent packs.
- Details: `composer_get_simulator_pack_versions(pack_id)`,
  `composer_get_simulator_pack_resolved(pack_id, semver)`.
- Install: `composer_download_simulator_pack_bundle(output_directory, pack_id, semver)` next
  to the scene XML, add an MJCF `<include file="..."/>`, and restart the MuJoCo controller.
  Packs are not hot-spawned into a running viewer; primitives from
  `add_mujoco_scene_object()` are.
