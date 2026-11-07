# Test and verify a standing brain

Part 2 of 2. Building it: [standing-guide.md](standing-guide.md).

## Contents

- Gates before any test
- Measure by behavior
- Design the comparison
- Adding a disturbance or a new block
- After a restart or restore
- When standing suddenly fails

## Gates before any test

Run these first. Each one has produced invalid data in real work.

1. **One controller.** Count simulator controller processes at the expected burst rate. Two
   controllers invalidate all behavior data from that period.
2. **Know which brain is loaded.** Record the checkpoint the experiment start actually loads and
   use that as the host. A newer lineage can regress while an older one stands.
3. **No-fault stance check:** a few full-length trials with everything installed and no disturbance
   (3 is a floor). Most must hold past the time the test will start.
4. **Live-state check** against the expected state (burst rate, controller loop, plasticity and
   homeostat settings, mapping strengths at rest): `check_live_state_drift` or a written list.
5. **Mute control:** mute the reflex and confirm the body falls. That shows the reflex, not the
   pose, carries the body.

## Measure by behavior

- Judge standing by behavior: hold time, fall direction, which feet touch, how it recovers.
  Use engineering quantities only when no behavioral measure answers the question.
- Use a fixed clock per trial, auto-reset after a fall, one attempt per trial, and record the window
  of the first fall (before, during, after any disturbance).
- Score the window under test, on trials that were still standing at its start. Baseline falls are
  not zero and vary, so total falls hide effects.
- Pair a behavior measure with a mechanism measure (for example firing of the affected area per
  burst). With few trials the mechanism often separates while falls do not.
- Burst-level checks use Trainer run data; samplers see only a fraction of bursts at high rates.

## Design the comparison

- Seeded trials, the same seeds in every arm, arms **interleaved** in one plan, analysis unpaired.
  A batch run later drifts; interleave, or report the drift.
- Include a **sham** arm that is identical but inert, and confirm from the stored settings that it
  really is inert and differs from the other arms. A stale setting can make two arms identical.
- Set control margins in advance (pre-onset falls, tilt spread, sham versus off) and report a breach
  as a confound.
- Size n before the run. If the control arm has no failures there is nothing to protect against, and
  the behavior endpoint cannot be assessed: report the mechanism and say so.
- A data-dependent extension is declared in writing first, reported as a follow-up, never pooled with
  a different host or an earlier pilot.

## Adding a disturbance or a new block

- Choose the disturbance size by calibration and check it is harmful; do not assume a graded
  dose response.
- A neural disturbance (an extra input into the sensing area) is repeatable but is not a body push.
  Say which one was tested; a mechanical push is the obvious reviewer question.
- Add one block at a time and re-run the no-fault check: adding or removing a block must leave the
  measured behavior of the others unchanged.
- **Works alone and combined.** Each block exports, loads without the blocks it does not depend on,
  and passes its acceptance check there; then the same check passes with all blocks combined. A block
  that only works with the others is not publishable ([hub-block-datasheet.md](hub-block-datasheet.md)).
- If a Hub block assumes a different burst rate, rescale its burst-counted settings in the same change
  or reject the block; do not run it unchanged.
- A homeostat's per-neuron state can survive disabling it. Read the starting state of every trial.

## After a restart or restore

Check from the live brain, not the call that set it: one controller and the burst rate; motor depth,
input-area count and sensor widths match the genome; stored settings of every area the plan touches;
modulator list, mappings and synapse counts; commanded stance read back as joint angles; Death fires
0 times; a no-fault stance run holds.

## When standing suddenly fails

1. Count controllers, check the burst rate and the experiment state (a stopped experiment looks like
   a frozen simulator).
2. Compare the loaded brain's lineage with the last one that stood; load the old genome on the same
   platform before suspecting the platform.
3. Check the embodiment settings (motor depth, sensor widths, cutoffs) against the genome; a shared
   embodiment setting changed by another experiment silently invalidates a stance.
4. Read the commanded stance in joint angles and the stored area settings.
5. Report what was found at each step; do not re-apply reverted state without saying why.
