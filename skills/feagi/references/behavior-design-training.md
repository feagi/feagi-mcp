# Teach a robot a behavior: training and run data

Part 2 of 2. Analysis, capability checks, tuning, start-of-goal checklist: [behavior-design.md](behavior-design.md).

## Contents

- Training method fit
- When to step back
- Run data

## Training method fit

- The reward must credit the brain's own action, not an outcome produced by external
  support. A body held up by support scores well whatever the brain does.
- Check how reward and eligibility interact before a run; see
  [memory-plasticity-stdp.md](memory-plasticity-stdp.md#credit-assignment-read-before-training-with-reward).
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
