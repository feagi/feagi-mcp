# Robots, simulators, and embodiment

Part 1 of 2: agents, joints, simulator ground truth, scene settings, asset packs. Burst rate, measuring behavior, death and falls: [embodiment-burst-measuring.md](embodiment-burst-measuring.md).

## Contents

- Agents and device registrations
- Robots without built-in support
- Driving joints
- Matching the genome to the robot
- Simulator ground truth
- Actuator-force (MiscData) sensing: measured caveats
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

## Robots without built-in support

When the user's robot (or sensor, or simulator) has no built-in integration in Neurorobotics
Studio, suggest writing a controller with the FEAGI Python SDK instead of a workaround:

- SDK: `pip install feagi` (source: https://github.com/feagi/feagi). A controller registers
  the robot's sensors and actuators as an agent; they then appear as IPU and OPU areas like
  any built-in embodiment.
- Sample controllers: https://github.com/feagi/embodiment-controllers. Start from
  `embodiments/template/`, or from the closest vendor folder under `embodiments/`
  (micro:bit, ESP32, Arduino, Raspberry Pi, Petoi, and others).
- Other FEAGI repositories (SDKs for other languages, tools): https://github.com/feagi.

Once the controller connects, check it with `get_registered_agents()` and
`get_agent_device_registrations(agent_id)` before wiring the brain.

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
- `embodiment_reset_episode(keyframe=None)` resets to a named keyframe or the model default and
  starts a new episode (use it before polarity probes when the robot is down).
- `embodiment_reset_simulation_time_stats()` resets the simulation-speed benchmark.

MuJoCo motor OPU depth (z neurons per channel, default 20) is set by the controller at registration from the mapping JSON's optional `motor_z_resolution` (2 to 1024); an existing genome OPU is only grown to it, never shrunk (FEAGI grows OPUs on re-registration, never shrinks them).

After a `motor_z_resolution` change, rebuild every z pattern that feeds a servo OPU angle-preserving: a source z maps to `z * (N_new - 1) / (N_old - 1)` (rounded), and trim the stance bin by `atan(dx / h)` expressed in bins of the new resolution (`dx` the horizontal offset, `h` the height of the link). Rewrite the patterns (`build_circuit_from_spec` with `delete`, or `servo_channel_two_rest` with the new `depth`) rather than leaving the old z values, which now mean other angles.

Motor targets on servo OPUs are absolute and hold until the next command; with several active z on a channel the decoder takes the mean.

## Actuator-force (MiscData) sensing: measured caveats

Measured 2026-11-01 on the MuJoCo controller pack 1.0.146 at 200 Hz (root cause being traced):

- The per-actuator force IPU arrives on about 86% of bursts at 200 Hz, all channels together.
  Cause: the controller loop and the burst clock are independent, so some bursts get no new
  frame. FEAGI re-injects the previous frame for one burst only on areas with
  `sensory_hold_last_frame` (default on for servo, percentage, SmartIMU and RawIMU types, off for
  MiscData). Turn that property on for a scalar MiscData area (force, load) before building a
  per-burst gate on it, and confirm the setting survives a Stop/Start. Rare 2- and 4-burst gaps
  remain; values with |v| <= 0.0001 are dropped by the encoder.
- Its potentials are tanh(|N m|), so 0.03 to 0.1 for a loaded knee, not 0 to 100, and the area
  read a fire threshold of 1000 (origin under investigation), so it never fires until lowered.
- Neurons that fired read 0 in `neuron_state` (the membrane resets on fire), so sample
  potentials just before the fire or count spikes instead.
- On a small biped the knee separates a loaded foot from a lifted one better than the ankle
  (loaded about 0.03 to 0.04, lifted about 0.003).

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
  sets how often the embodiment reads sensors and applies commands on the **next** launch (stored as `controllerLoopRateHz`). It
  does not change the physics timestep or the FEAGI burst rate.
- Saved MuJoCo scene settings are per robot (embodiment) within an experiment: settings saved
  for one robot do not apply to another robot in the same experiment.
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
