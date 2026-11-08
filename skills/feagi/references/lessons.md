# Lessons from live builds

Staging, measuring, sizing, signals, layout, behavior design, tools. The measured learning and embodiment lessons ship with Neurorobotics Studio (`behavior-playbooks` skill).

Facts about FEAGI, its MCP tools and embodiments that cost real time to learn. Each entry
says what happened, how to recognize it, and what to do. Add to this file when a task's gap
report finds a generic fact; keep host- and vendor-specific advice out of it.

## Contents

- Work in stages
- Measure before you build
- Sizing facts
- Signal and encoding facts
- Diagnosing before designing
- Layout facts
- Behavior design facts
- Recording and building tools

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
- End every task with two lists. **Bugs:** the software did the wrong thing. **Gaps:** a
  missing tool, parameter, or path whose absence cost time or forced a worse circuit. One
  line each, with where and the smallest fix. Do not put a bug on the gap list. Generic
  facts from either list belong in this file.

## Measure before you build

A behavioral goal needs an outcome metric that existing tools can read, and a baseline,
before any circuit is built. For a balancing or walking robot that is
`measure_balance()`: episodes between resets, upright fraction, falls and recovery counts
as numbers, in 25 s windows that are concatenated by `window_id`. When the question is
"did the brain react to the body in time", `record_aligned_trace()` pairs the bursts on
which chosen areas fired with the physics at those bursts; read the burst numbers, not
the plots. If the metric cannot be measured with existing tools, that is the first report
of the task, not a script to write. After each stage, measure again with the same window
length and compare numbers; and after every controller restart run
`check_live_state_drift()` before trusting the next measurement, because re-registration
reverts live area widths and the burst rate silently.

## Sizing facts

Used by the design method ([genome-design-budget.md](genome-design-budget.md#efficiency-budget)). Measured on
one laptop-class machine, read once; they move with the host and the release, so
re-measure with `get_runtime_metrics(measure_s=10)` before sizing a real run.

- **Synapses per rule** (N = positions, D = depth): `block_to_block` one per voxel;
  `projector` about N_src (one per source in the block); `all_to_all` N_src x N_dst; a k x k
  local kernel k^2 x N; the `!` token (every coordinate except the source's) along depth for
  winner-take-all N x D x (D - 1); one pooled-inhibition area (class to pool and back) 2 x N x D;
  a plastic fan-in of F feature planes onto D classes F x D x N.
- **Events per burst** = active fraction x synapses. One synaptic event cost 0.37 us in the CI
  microbench (`feagi-core/perf/ci_microbench_baseline.json`). A brain of about 270k neurons and
  924k synapses at about 40% activity (about 114k fired, about 578k injections per burst) took
  278 to 333 ms per burst against a 66.67 ms budget at 15 Hz
  (`feagi-core/crates/feagi-npu/SCALABILITY_BOTTLENECK_ANALYSIS.md`). The plasticity pass also
  visits every plastic synapse each burst.
- **Capacity** is read from `feagi_configuration.toml` (`neuron_space` 10M, `synapse_space`
  25M when read once), allocated at startup. Read it; do not hard-code it.
- **Value planes are cheap, one-hot Z is not.** A 512x256 mask as `W x H x 19` one-hot needs
  about 2.49M neurons; as a value plane 131k.
- FEAGI does not report burst duration or missed bursts: a rate above what the engine sustains
  silently shortens every Trainer hold, which counts wall-clock time.

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

## Diagnosing before designing

- A simulator whose clock stops is usually a stopped experiment, not a frozen physics
  engine: check the experiment state (`get_experiment_status()`, or the Studio context tool)
  before reading controller logs.
- A fixed pose never balances a legged robot with weak position servos; it needs a sensed
  correction loop or learning. Measure which direction each joint change tips the body
  before wiring any corrective mapping.

## Layout facts

Added after one layout stacked circuit titles.

- **Do not outrun fixed-size titles.** Region titles stay the same size on
  screen, so no world pitch keeps them apart when the camera frames the whole brain.
  Spreading circuits by 40 voxels times the title length (720 and up) only empties the
  scene. Use one map step, about 120 voxels, between rows. If the next circuit on that Y
  would land within one map step of another title, a core area, or an I/O area, put it on
  the next Y. Zoom in to read a title. Full rule:
  [building-circuits-placement.md](building-circuits-placement.md) "Placement".

## Behavior design facts

Full method: [behavior-design.md](behavior-design.md).

- **Support must only help a standing stance.** A harness that keeps helping
  while a contact body is off the floor, or re-centres a lean, holds a crouch or lean and
  scores it as success. Weight support off when a contact body leaves the floor, re-centre a
  lean, and require standing time for success.
- **R-STDP rewarded for upright-while-supported collapses or saturates weights.** The reward pays for the support, not the brain. Fix the credit (reward the
  brain's own contribution), not the LTD ratio.
- **A sign-fixed one-to-one reflex cannot learn direction.** R-STDP can mute a
  wrong-sign path but never flip it. Wire the correct sign, or wire both directions as
  candidates with mutual inhibition.
- **A frozen `plasticity_flag` left from a test run silently stops learning.**
  Read it back on every plastic mapping before a training run. (`freeze_mapping_plasticity()`
  no longer clears the flag; it sets FEAGI's `plasticity_frozen`, which also survives save/load.)
- **A sign-crossed rewire with initial weights above half the threshold fires both
  directions at once.** The opposing commands destabilize the body. Start
  candidate weights quiet, so several inputs must agree to fire.
- **Work top-down.** Synapse-level tuning with no circuit-level check wasted
  runs. Test each region as a black box (sign, gain, lag) before touching weights.

## Recording and building tools

- **Per-burst data comes from the Fire Ledger, not the samplers.** `monitor_activity` and
  `get_fire_queue_detailed` see about one burst in five at 200 Hz (the fire queue holds only
  the latest burst). `record_spikes` reads `/v1/burst_engine/fire_history`: a frame per burst
  per area, silent bursts included, subscribed on first read (window = `bursts` asked for,
  max 2000 per read), released after. FEAGI keeps one subscription per area and DELETE removes
  it outright; two recorders on one area in separate processes can drop each other's.
- **A held stimulus is a post loop, not a counter-gated loop.** A post merges into the next
  burst's fire queue and the pending queue dedupes and drains every burst, so
  `hold_stimulus` posts twice per burst on a wall-clock schedule and trusts the ledger
  (`landed`) instead of counting posts. A counter poll plus post per burst loses bursts at 200 Hz.
- **FEAGI does not report burst duration or missed bursts.** `avg_burst_time_ms` is hard-coded
  0.0 and `actual_frequency_hz` echoes the target. `get_runtime_metrics(measure_s=...)` compares
  the burst counter with the wall clock; one 1 s sample on a live 200 Hz run read 183 bursts
  (shortfall 18). Repeat with a longer window before concluding the engine overruns.
- **Ring step time is not given by a simple formula yet.** The design formula
  `p = (threshold - d) / k` and the leak-aware sum `V <- V (1 - leak) + (p + d)` both disagree
  with a measured 6-burst step at `p = 0.565`. `ring_cpg` returns `predicted_step_bursts`
  flagged uncalibrated: measure the period with `record_spikes` and set `lateral_psc` from it.
- **Region exports carry every morphology of the brain.** `download_region_genome` now keeps
  only the morphologies the exported mappings name.
