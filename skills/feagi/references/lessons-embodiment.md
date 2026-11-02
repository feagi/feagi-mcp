# Lessons: embodiment facts

Part 3 of 3 of [lessons.md](lessons.md). Learning facts: [lessons-learning.md](lessons-learning.md).

## Contents

- Embodiment facts

## Embodiment facts

- **IMU areas can register narrower than they stream.** A controller may register an
  orientation IPU 4 wide and stream 8 columns (plus and minus per axis); the dropped columns
  carry the pitch sign. Check `list_io_areas_compact()` against
  `get_sensor_snapshot_last()` column indices, widen with `update_cortical_area()`, and
  expect to redo it after every controller restart until the registration is fixed.
  `check_live_state_drift()` lists such reverts with the restoring call.
- **Gyro auto-scaling hides small rates.** Without a declared cutoff, a controller may scale
  the gyro to the largest rate seen; one fall makes balance-sized rates read as zero.
  Declare a cutoff in the controller's mapping file. That is embodiment configuration, not a
  brain shortcut.
- **Servo speed sub-channels may be ignored.** Some controllers consume only the absolute
  position sub-channel and slew at a fixed rate; firing the speed or incremental areas has
  no effect. Confirm with `get_motor_snapshot_last()` and the controller log before relying
  on them.
- **Changing the burst rate is one call.** `set_burst_engine_frequency(frequency_hz)` sets
  the running engine, and the returned `burst_frequency_hz` is the confirmation. Searching
  for a physiology or `simulation_timestep` write, or sampling `get_burst_counter`, is how
  that change turns into a source hunt. A later genome reload can restore the stored
  timestep; that is one sentence in the report, not another call. Sample the counter only
  when the user asks whether the loop is keeping the period.
- **The default burst rate can make balance impossible.** Howard ran at 10 Hz: a 3-hop path
  plus transport was 0.30 s of loop latency, equal to the median fall time (tau about
  0.1 s). Derive the rate from tau and hops (`embodiment-burst-measuring.md`, "Choosing the burst rate")
  before wiring anything.
- **Wiring falls into Death kills learning.** The robot never gets to recover or learn to
  get up. Let the Trainer end attempts; see `embodiment-burst-measuring.md`, "Death and falls".

- **A tonic self-loop can die on a structural edit (2026-10-31).** A `[1,1,1]` driver kept alive by
  its own self-mapping stopped after a morphology/mapping rebuild, and a Brain_Power seed below
  its threshold did not restart it. Give the seed a PSP at or above the threshold, and after any
  mapping or morphology edit re-read the driver and the OPU firing before trusting the servo
  `ctrl` values: the controller holds the last decoded target while the OPU is silent.
- **Servo bins are joint-specific (2026-10-31).** Degrees per z bin come from each channel's
  `ctrl_min`/`ctrl_max` (read them from a trace), not from one joint's range. Microduck at depth
  91 measured 2026-11-01: about 2.8 deg per bin on ankle, hip pitch and knee, 0.49 deg on hip
  roll, so equal bin offsets give very unequal angles.

- **A leaky-integrator port fires one burst in three under a steady input (2026-10-31).** FEAGI
  resets the membrane on every fire, so a port that needs 3 input bursts to fire keeps that
  period while the input persists; a servo command driven from it runs at 1/3 duty and the
  slew-limited controller averages it back to idle (a 1 s hold moved pitch 0.04 deg). Add a
  `block_to_block` self-mapping whose effective PSP s = port PSP x PSC multiplier obeys
  threshold - input <= s < threshold (PSP 3, threshold 2.5, input 1: PSC 0.7): the port then
  fires every burst while its input bin persists and releases one burst after it stops.
- **Brain_Power synapses degenerate to zero (2026-10-31).** The default genome's Brain_Power
  area degenerates its synapse PSP by 0.01 per fire; a driver seeded only by it dies after a few
  thousand bursts (seen after every Trainer start). Set its degeneracy to 0 when it must seed a
  tonic driver, and give the seed a PSP at or above the driver's threshold.
- **A self-holding area cannot seed once (2026-10-31).** A tonic gate (`Walk_Go` held by its
  self-mapping) that also drives a ring's start bin refires that bin every burst, and the
  whole ring lights up. Seed through a one-burst onset pulse (gate -> `Onset`; a one-burst
  `Delay` copy of the gate inhibits `Onset` from the next burst on). The same pulse pattern
  detects a load onset. Tonic drive into a leaky ring must stay below leak x threshold per
  burst, or every bin settles above threshold (V = V(1-leak) + I, reset to 0 on fire).
- **A freshly started experiment has no support (2026-11-01).** Right after `start_experiment`
  a legged robot with only a stance falls within a second, so any "servo ctrl within 1 deg of
  the stance" check taken then reads the fallen pose (reflex saturation). Take that check from
  a Trainer run with fixed support or from `run_embodiment_trial`, never from a bare trace
  after a start.
- **Learned motor sequences: what memory areas can and cannot do (2026-11-01, architect
  review).** A memory neuron fires only when its upstream pattern matches live fires, so a
  lone memory area classifies states; it does not sequence on its own. Chains and hierarchies of memory areas do replay and sequence (measured 2026-11-01, [memory-design.md](memory-design.md)). Keep
  an innate clock and learn state -> command with `associative_memory` rstdp (CUSTOM targets are
  legal), plasticity_window >= the clock step + 2 bursts of injection lag. Reward consolidation
  to long-term links only two memory neurons, so state neurons must go long-term by
  reactivation (`neuron_longterm_mem_threshold`) or expiry deletes the learned synapses.
  `neuro.firing_probability` is per-neuron excitability that blocks fires already past
  threshold, not exploration noise; explore with a tonic-driven Babble area of static
  excitability < 1 into both-sign command candidates.
- **Trainer contribution reward is punish-only at support 0 (2026-11-01).** balance_feet's
  contribution reward pays the brain's share of a correction relative to support; with support
  0 only Pain at falls reached the synapses, so R-STDP could only lower the reflex gain
  (median hold 7.2 s before training, 4.8 s after). Check that a positive signal can fire at the
  support level you train at before running reward training. The Trainer's test phase freezes
  plasticity, so "test with learning on" is a train-only run.
- **Read back every probe restore (2026-11-01).** A neuron silenced for a probe (threshold 1e12)
  and reported restored stayed silenced across restarts and cost a day of misleading numbers
  (one leg's stance one bin off). Read the value back from the live brain after the restore.
- **A full connectome restore dropped per-area NPU flags (feagi-core, fixed 2026-11-01).**
  Before the fix, every experiment start that restored a connectome lost uniform PSP,
  MP-driven PSP, baseline PSC and degeneration flags until a single-area update re-set them;
  uniform-PSP areas then divided their output by fan-out (a ring stopped stepping, reflex
  self-holds weakened). If behaviour changes after a restart with no genome change, read the
  effective input of one uniform-PSP area (fire at threshold just below the expected input)
  before tuning anything.
