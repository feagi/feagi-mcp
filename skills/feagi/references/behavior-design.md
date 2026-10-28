# Teach a robot a behavior (top-down)

## Contents

- Levels of analysis
- Task analysis before building
- Circuit capability check
- Innate vs learned
- Training method fit
- When to step back
- Run data
- Start-of-goal checklist

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
  [embodiment.md](embodiment.md#choosing-the-burst-rate).
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

## Motor targets are absolute and hold

- A positional-servo absolute channel decodes the mean of its active z voxels into one
  target, and the controller holds it until the next command (silence = keep last target).
- A stance command and a reflex on the same channel therefore average, not add: a reflex
  voxel at z moves the target only half as far as intended if one stance voxel is also active.
- Build reflexes as small corrections around a stance that is commanded every burst, and
  probe each direction before closing the loop. Use stance-relative offsets:
  `build_stance_relative_mapping` (dry run first) converts joint-unit offsets to z bins,
  with deadband, max offset and mean compensation (`n_stance_voxels`).
- Verify the sign with `probe_area_response` before wiring more.

## Training method fit

- The reward must credit the brain's own action, not an outcome produced by external
  support. A body held up by support scores well whatever the brain does.
- Check how reward and eligibility interact before a run; see
  [memory-and-plasticity.md](memory-and-plasticity.md#credit-assignment-read-before-training-with-reward).
- Trainer settings (`get_trainer_experiment`, `configure_trainer_run`):
  - use the `balance_feet` task for standing on contact bodies;
  - choose a support ladder (fixed steps) or adaptive support (follows deviation);
  - use a contribution reward, which pays for the brain's share of the correction;
  - support only helps a standing stance: feet loaded and the body upright. It must be off
    when a contact body is off the floor.
- Read the Support check panel and the deviation-vs-assistance chart in
  `get_trainer_balance_results`. Assistance should rise with deviation (r > 0), and both
  should fall over the run. Flat or rising assistance means the brain is not taking over.
- Metrics observe, they do not steer. Do not feed a result metric back into the reward or
  the circuit.

## When to step back

- After 2 failed stages on one goal, return to task analysis and the capability check.
  Reassess the circuit and the training method before the next change.
- Never spend two runs tuning the same mechanism.
- State the level each stage works at in its brief; a stage must not drift below it.

## Run data

Every Trainer run, any task, writes `<run_id>.rundata/` in the Trainer artifacts folder:

- `tables/*.csv` (per-step or per-sample values), `events.csv`, `neural/*` (only when areas are
  recorded), `dictionary.json` and `dictionary.csv` (every column with unit and meaning), and
  `manifest.json` (task, phases, label, operator, seeds, genome and connectome ids, versions,
  burst rate, errors, and the size and sha256 of every file).
- `runData` in the setup of any task: `label`, and `neural` with `areas` (cortical areas to
  record: spikes, firing counts, burst clock), `neuronState` (a list of `{area, fields}`) and
  `neuronStateSampleS` (seconds between samples; 0 = off). Nothing neural is recorded unless
  areas are listed. A setup key set to `null` is deleted, so the default applies again.
- `list_run_data` (filters: `task`, `label`, `limit`) lists the folders newest first from their
  manifests. `export_run_data(run_id, destination?)` re-hashes every file against the manifest,
  fails with the mismatches if one differs, then writes `<run_id>.rundata.zip` and returns its
  path, file count, bytes and sha256. Run results report `run_data_dir`.
- Per-neuron state of an area: `GET /v1/connectome/cortical_area/{id}/neuron_state?fields=a,b`
  (columnar; an unknown field gets a 400 that lists the valid ones). The same fields feed
  `runData.neural.neuronState`.
- Scheduled actions (`scheduledEvents`: a list of `{at_s, label, action}`, where the action sets
  a mapping's post-synaptic current multiplier or one area parameter) are applied during a run
  and restored after it. Fixed support (`supportMode: fixed` with `supportLevel`) holds one
  support level for every training attempt.

## Start-of-goal checklist

1. `get_brain_regions()`: list regions and their inputs and outputs.
2. Name the outcome metric; take a baseline with `measure_balance()` or `run_embodiment_trial`.
3. Derive the burst rate from the body's fastest dynamic and loop depth.
4. Check the start pose: is it statically stable?
5. List the axes that need correction and the direction each needs.
6. Run full, region-muted and pose-only trials (3 repeats); fill the table.
7. Push each direction; confirm the response opposes it.
8. Write the region-level hypothesis and the test that would refute it.
9. Wire correct-sign reflexes first; add plasticity only after the reflex helps.
10. Check that the reward credits the brain's action, then brief one stage.
