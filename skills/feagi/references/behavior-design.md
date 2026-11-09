# Teach a robot a behavior (top-down)

Analysis, capability checks, tuning, checklist. The training method (method fit, when to step back, run data) ships with Neurorobotics Studio (`behavior-playbooks` skill).

## Contents

- Stay bio-inspired
- Levels of analysis
- Task analysis before building
- Circuit capability check
- Make the stance balance before wiring a reflex
- Tune with a run plan, never one value per stage
- Innate vs learned
- Absolute motor targets average and hold
- Start-of-goal checklist

## Stay bio-inspired

Ask first how an animal solves this with what it can sense: vestibular-like tilt, joint state, foot
pressure, reflexes, learning.

- **Inputs** are the body's own sensors. Simulator ground truth such as centre of mass or exact
  pose never reaches the brain.
- **Solutions** are circuits and learning, not solvers, planners, inverse kinematics or
  hand-computed targets standing in for feedback.
- **Metrics** are behavior first: stays up, which feet touch, hold time, recovery. If the Trainer
  lacks an engineering number such as centre of mass, try a behavioral measure before adding it.
- **Physics** may inform reasoning (fall time sets the burst rate), but a model's output is not the
  design.
- **Exception:** only when the project requires it or a very strong reason exists. Say which
  principle it departs from and give the bio-inspired alternative; the user decides.

## Levels of analysis

Work from the behavior down, never from the synapses up.

| Level | Question | Evidence |
|---|---|---|
| Behavior in the world | Does the body do the task? | `measure_balance()`, `run_embodiment_trial` |
| Region (black box) | What are its inputs, outputs, sign, gain and latency? | muting tests, pushes, `record_aligned_trace()` |
| Mapping | Which edge carries the wrong sign, gain or timing? | `get_connectivity_summary()`, `probe_area_response()` |
| Synapse | Which weights moved, and why? | `list_area_synapses()`, `diagnose_mapping_plasticity()` |

- Go down a level only when the level above has pinned the fault to one place.
- Before reading synapses, write the region-level hypothesis ("this region's output has the
  wrong sign on the pitch axis") and the behavior test that rules it in or out. Run the test
  first.
- A synapse-level change with no region-level check behind it is a guess.

## Task analysis before building

Answer these on paper before the first edit.

- **Fastest dynamic of the body.** A balancing body falls with `tau = sqrt(h/g)`, h = centre
  of mass height. A reaching arm has its joint settling time. This sets the burst rate.
- **Is the start pose statically stable?** If it is, a do-nothing brain survives and
  survival time says nothing. If it is not, the brain must act within one fall time.
- **Loop delay in bursts.** Hops from sensor to motor plus transport. Convert to seconds and
  compare to the fastest dynamic; see
  [embodiment-burst-measuring.md](embodiment-burst-measuring.md#choosing-the-burst-rate).
- **Corrections per axis.** List which axes need a correction (a pitch axis, a roll axis)
  and in which direction the actuator must move to oppose each error. Measure the direction
  with a small joint move; do not assume it.
- **Outcome metric and baseline.** Pick one number the tools can read (episode length,
  upright fraction, distance to target). Take the baseline before building. If no tool
  reads it, that gap is the first report.

## Circuit capability check

Run black-box experiments from the same reset pose, with at least 3 repeats each, before
changing the circuit. Compare means, not single runs.

| Condition | How |
|---|---|
| Full brain | Run as is. |
| Region muted | Set `postsynaptic_current_multiplier` 0 on the region's outgoing mappings with `update_cortical_mapping()`. Note the old values, run, then restore and read back. One region at a time. |
| Pose only | Mute every region that drives the actuators; the pose command alone holds the body. |

Record, per condition:

| Condition | Time to failure (s) | Failure direction | Output sign (opposes error?) | Gain (command per unit error) | Lag (bursts) |
|---|---|---|---|---|---|
| Full brain | | | | | |
| Region A muted | | | | | |
| Pose only | | | | | |

- Sign: does the corrective output move against the error? A wrong-sign output is worse
  than silence.
- Gain: command change per unit of error (degrees of tilt, metres of offset).
- Lag: bursts from error change to command change, from an aligned trace.
- Push test: apply a small push in each direction and check the response opposes it. Do both
  directions; a circuit that corrects one side often fails the other.
- If full brain does not beat pose only, the circuit adds nothing yet. Fix that before any
  training.

## Make the stance balance before wiring a reflex

A stance that falls in about a second makes every reflex fight a constant bias, and the
reflex then over-corrects. Before the first reflex:

- Measure the silent stance by behavior, with support 0 and the motors holding it: fall time and
  fall direction.
- Move the stance (ankle and hip pitch, knee bend, in the body adapter's stance rows) against the
  fall direction and sweep the stance values with a run plan (below), not by hand, until the silent
  fall time stops improving.
- The reflex then corrects disturbances around a balanced pose, not a built-in lean.

## Tune with a run plan, never one value per stage

Once a reflex has the right sign, its gains (sense -> command PSC, rate -> command PSC, offset
per level, stance values) are tuned with one Trainer run plan (`create_run_plan`, trainer skill
"Run plan (matrix)"): one condition per gain combination, 3 to 5 trials each, at the support
level the acceptance uses, compared on the key metric (median hold). A 3 x 3 sweep of two gains
runs unattended in one stage; picking values by hand costs one stage per value and hides
over-correction and oscillation. Start coarse (x0.5, x1, x2), then refine around the best cell.
Use the same tool for silent-versus-active comparisons and regression checks.

Keep sweeps cheap: put a condition's trials inside ONE cell as several attempts (protocol
`train_only`, `trainAttempts` N, condition `trials` 1) instead of one cell per trial. Each cell
pays a fixed overhead (Trainer start, brain change and read-back, reset, restore) of about 30 s,
which dominates short attempts; one cell of 5 attempts costs about a quarter of 5 cells. Read the
per-attempt holds from the cell's run data.

Sweep a parameter that actually sets the gain. A mapping's PSC scales gain only when the
target's threshold sits between the input values; into a target that fires on any input
(threshold 1, PSP 100) the PSC is a no-op (measured once: a 3 x 3 PSC sweep gave the same
hold in every cell). For a reflex that drives positional servos the gain lives in the offset per
command bin (adapter morphology rows). Do not use `neuron_excitability` on the command ports as a
gain proxy: measured once, any excitability below 1 behaved exactly like a silent reflex
(1.07 s at 0.5, 0.33, 0.2 and 0.1 against 2.0 s at 1). Sweep the offset rows, or a lever upstream
of the command threshold (a sense port's self-hold, which sets how many bursts it fires).

## Innate vs learned

- Build correct-sign reflexes in. A reflex whose sign you can measure should be wired, not
  learned.
- Plasticity tunes gain and timing around a reflex that already helps.
- To learn the direction itself, all of these are needed:
  - both directions wired as candidates (sign-crossed);
  - exploration, so both candidates get tried;
  - quiet initial weights, so several inputs must agree to fire a neuron;
  - mutual inhibition between the opposite directions, so one wins.

  Without them the weights saturate or collapse.
- Order: get a correct-sign reflex that helps (measured), then add learning, then measure
  again against the reflex alone.

## Absolute motor targets average and hold

This section is about the absolute servo area. An incremental area instead integrates steps into a held target; both layouts and their decode: [io-encodings.md](io-encodings.md#positional-servo-absolute-incremental-speed).

- A positional-servo absolute channel decodes the mean of its active z voxels into one
  target (bin rule: `convert_io_value`), and the controller holds it until the next command (silence = keep last target).
- A stance command and a reflex on the same channel therefore average, not add: a reflex
  voxel at z moves the target only half as far as intended if one stance voxel is also active.
- Build reflexes as small corrections around a stance that is commanded every burst, and
  probe each direction before closing the loop. Use stance-relative offsets:
  `build_stance_relative_mapping` (dry run first) converts joint-unit offsets to z bins,
  with deadband, max offset and mean compensation (`n_stance_voxels`).
- Verify the sign with `probe_area_response` before wiring more.
- The average counts distinct voxels, not sources: two modules that share a rest voxel do not
  add a third contributor. Two sources on one channel need two distinct rest voxels (z+1, z-1)
  with offsets relative to each, or one owner per joint at a time.

## Start-of-goal checklist

1. `get_brain_regions()`: list regions and their inputs and outputs.
2. Name the outcome metric; take a baseline with `measure_balance()` or `run_embodiment_trial`.
3. Derive the burst rate from the body's fastest dynamic and loop depth.
3b. Check actuator authority against that dynamic: the controller's servo slew
   (`incremental_step_ratios` x joint range per second for absolute targets) and the model's
   servo gains must let a correction travel farther than the fall does in tau/2. If not, raise
   the slew in the mapping file (embodiment config) before wiring any reflex; no reflex gain
   can beat a slew limit (one biped's measurement: 34 deg/s lost to a 0.12 s fall, 85 deg/s won).
4. Check the start pose: does it stand with the brain silent? If not, sweep the stance by its fall
   time and direction first ("Make the stance balance before wiring a reflex").
5. List the axes that need correction and the direction each needs.
6. Run full, region-muted and pose-only trials (3 repeats); fill the table.
7. Push each direction; confirm the response opposes it.
8. Write the region-level hypothesis and the test that would refute it.
9. Wire correct-sign reflexes first; add plasticity only after the reflex helps.
10. Check that the reward credits the brain's action, then brief one stage.
