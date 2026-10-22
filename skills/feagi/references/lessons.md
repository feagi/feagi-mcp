# Lessons from live builds

Facts about FEAGI, its MCP tools and embodiments that cost real time to learn. Each entry
says what happened, how to recognize it, and what to do. Add to this file when a task's gap
report finds a generic fact; keep host- and vendor-specific advice out of it.

## Contents

- Work in stages
- Signal and encoding facts
- Embodiment facts
- Diagnosing before designing

## Work in stages

A circuit build is a sequence of stages. One stage is: create the areas, wire them, verify
with a cheap read, report numbers. Finish and verify a stage before widening scope. A stage
that fails its check twice after adjustment is a design problem, not a tuning problem: stop
and report instead of iterating.

- Issue independent tool calls together in one turn; every turn re-sends the conversation.
- Verify with `monitor_activity()`, `inspect_cortical_areas_minimal()`,
  `probe_area_response()` or `get_sensor_snapshot_last()`, not raw dumps.
- Never poll physics or logs in a loop. Record a trace once and read its statistics.
- `snapshot_genome()` before any stage that deletes or replaces.
- When the host can route work to other models or subagents, run build-and-verify stages
  there and keep design and review on the strongest model. The stage brief names the exact
  areas, states the acceptance check as a number, and says "report, don't redesign".
- End every task with a gap report: which tool, skill, controller or core behavior cost
  time or forced a worse circuit, whether it is verified or suspected, and the smallest fix.
  Generic facts from that report belong in this file.

## Signal and encoding facts

- **PSP is divided across fan-out.** A source neuron with `neuron_psp_uniform_distribution`
  off splits its PSP over all its outgoing synapses. A `1x1x1` driver with PSP 30 wired
  `all_to_all` to 40 targets delivers 0.75 each, below a threshold of 1, and the targets
  stay silent with no error. Recognize it with `list_area_neuron_states()`: membrane
  potentials sit just under threshold. Fix with `update_cortical_area()` setting
  `neuron_psp_uniform_distribution` true on the source, or raise the PSC multiplier.
- **Positional servo depth is pinned by the agent.** The agent registers each servo OPU with
  its own depth (commonly 20). Resizing the OPU deeper in the genome drops it from the motor
  feed: the area fires but no packets reach the robot. Finer joint resolution comes from
  which voxel you add to a base set, not from a deeper area: with a base of `n` fired
  voxels, adding one voxel `d` steps from the mean shifts the command by `d / (n + 1)` steps.
- **Sensor magnitude bins are already one-hot.** IMU, encoder and joint-velocity IPUs fire
  one depth per column (depth 9 is about zero, depth 0 full scale). Select bins with exact or
  ranged source depths; no thermometer-to-one-hot stage is needed.
- **Hold a one-burst command with a self-mapping.** An action that must persist between
  decisions needs a `block_to_block` self-mapping on its area; clear it with an inhibitory
  pulse one burst before the next command arrives (`synaptic_delay_bursts`).
- **An AND of two sparse signals rarely fires.** A gate that requires two sources in the
  same burst almost never opens when one of them is intermittent. Drive from one source and
  use the other as inhibition.

## Learning facts

- **Exact-pattern memory needs a tiny source.** A memory area fed by multi-column bins minted
  1,475 state patterns in 60 s and never levelled. Feed memory from a source with at most a
  few dozen possible patterns (for example pitch direction x magnitude), `temporal_depth` 1,
  and confirm with two reads of `get_memory_area_runtime_config()` 45 s apart that
  `neuron_count` has stopped growing.
- **Memory cannot drive a normal area directly.** A memory-to-non-memory mapping is accepted
  only with `associative_memory`, and that mapping realized no synapses in a live build.
  Put learned behavior on synapses between ordinary areas (a one-hot state area to a
  pre-motor area) and keep memory areas as the experience record.
- **Reward-modulated plasticity commits through modulators.** An `rstdp` rule with
  `reward_source_area` / `punishment_source_area` was accepted but never changed a weight,
  while the same mapping subscribed to `synaptic.reward` modulators (one at +100 driven by
  the reward detector, one at -100 driven by the fall detector) changed weights within 20 s.
  Check with `diagnose_mapping_plasticity()` and the `synaptic_plasticity_generation`
  counter in `health_check()`.
- **Base plasticity potentiates without reward.** Co-active pairs on a plastic rule drift
  upward even when no reward fires. Make the reward detector reachable (it must fire in
  normal operation) and keep the Hebbian step small, or the actor self-reinforces.
- **Prove plasticity is alive with a probe.** Two rules on one pair, a strong non-plastic
  `block_to_block` and a weak plastic one, guarantee co-activity; if the plastic weights and
  the generation counter do not move in 45 s, nothing will.

## Embodiment facts

- **IMU areas can register narrower than they stream.** A controller may register an
  orientation IPU 4 wide and stream 8 columns (plus and minus per axis); the dropped columns
  carry the pitch sign. Check `list_io_areas_compact()` against
  `get_sensor_snapshot_last()` column indices, widen with `update_cortical_area()`, and
  expect to redo it after every controller restart until the registration is fixed.
- **Gyro auto-scaling hides small rates.** Without a declared cutoff, a controller may scale
  the gyro to the largest rate seen; one fall makes balance-sized rates read as zero.
  Declare a cutoff in the controller's mapping file. That is embodiment configuration, not a
  brain shortcut.
- **Servo speed sub-channels may be ignored.** Some controllers consume only the absolute
  position sub-channel and slew at a fixed rate; firing the speed or incremental areas has
  no effect. Confirm with `get_motor_snapshot_last()` and the controller log before relying
  on them.
- **Brain death resets the scene.** Wiring a fall detector into the `Death` core area makes
  the simulator reset on every fall, which turns time-between-resets into a survival metric.

## Diagnosing before designing

- A simulator whose clock stops is usually a stopped experiment, not a frozen physics
  engine: check the experiment state (`get_experiment_status()`, or the Studio context tool)
  before reading controller logs.
- A fixed pose never balances a legged robot with weak position servos; it needs a sensed
  correction loop or learning. Measure which direction each joint change tips the body
  before wiring any corrective mapping.
