# Homeostatic plasticity

Part 3 of 3 of [memory-and-plasticity.md](memory-and-plasticity.md) (memory areas, modulators). STDP and R-STDP: [memory-plasticity-stdp.md](memory-plasticity-stdp.md).

## Contents

- Homeostatic plasticity (`rate_modulated_leak`)

## Homeostatic plasticity (`rate_modulated_leak`)

FEAGI's homeostasis is **intrinsic**: each neuron's leak follows its own firing rate. Firing
above the set-point raises the leak (less charge carries over, the neuron fires less); firing
below it lowers the leak. It never changes synapse weights. FEAGI has no synaptic scaling or
weight normalization, so it does not fix STDP weights that saturate or collapse.

### What it can and cannot do

- Charge per burst is `V = V_prev * (1 - g) + I`, where `g` is the leak (fraction lost per
  burst). An area integrates over about `1/g` bursts: `g = 0.02` sums about 50 bursts of
  input, `g = 0.5` about 2.
- So the homeostat only changes how much **sub-threshold** input adds up across bursts. A
  neuron whose input in a single burst reaches threshold fires at any leak. Input-driven
  saturation needs a higher threshold, a smaller PSC, or inhibition, not homeostasis. The
  sign: a leak pinned at `leak_max` with the rate still above target means the input is too
  strong for the homeostat.
- A silent neuron with no input stays silent at any leak. A leak pinned at `leak_min` with
  the rate still below target means the input is too weak or missing; fix the wiring.
- It works only on dense custom (LIF) areas. Memory neurons are skipped.
- Use it on hidden populations that must stay in a working range while weights or inputs
  drift: reservoirs, feature layers, recurrent loops at risk of runaway or silence, and
  areas receiving plastic mappings.
- Do not use it on areas that carry a graded value (value planes, magnitude passthrough),
  on motor output areas, on modulator drivers, or on detectors whose firing **is** the
  signal. The homeostat would treat the signal as an error: a sustained stimulus makes the
  area adapt to it, and the output fades over about `rate_ema_tau_bursts`.

### Parameters

| Field | Default | Meaning |
|-------|---------|---------|
| `enabled` | false | Off unless true. `{"enabled": false}` disables and keeps the tuning. |
| `target_mode` | `area` | `area`: one set-point for all neurons. `per_neuron`: each neuron keeps the rate it had while arming. |
| `target_firing_per_burst` | 0.1 | `area` mode set-point, as fires per burst (0 to 1). Ignored in `per_neuron`. |
| `rate_ema_tau_bursts` | 50 | Time constant of the rate estimate, in bursts. |
| `gain` | 0.2 | Leak change per unit of rate error per update. |
| `leak_min`, `leak_max` | 0.02, 0.5 | Range the homeostat may move the leak in. |
| `update_every_n_bursts` | 1 | Leak update cadence. The rate is sampled every burst. |
| `arm_bursts` | 500 | `per_neuron`: bursts spent measuring each neuron's target. |
| `arm_tau_bursts` | `arm_bursts / 4` | `per_neuron`: averaging time constant while arming. |
| `min_target_firing_per_burst` | 0.001 | `per_neuron`: neurons armed below this count as silent. |
| `silent_neurons` | `one_sided` | `per_neuron`: `one_sided` lets a silent-armed neuron's leak only rise (back down to the base leak at rest), which stops a disturbance from recruiting it; `unregulated` leaves it at the base leak. |
| `arm_epoch` | 0 | `per_neuron`: change the number to re-arm. |

### Choosing the values

Size every value from the burst rate and the behavior, never keep the defaults. All of them
are counted in bursts, so rescale them whenever the burst rate changes.

1. **Set-point.** `target_firing_per_burst = desired rate (Hz) / burst rate (Hz)`. A sparse
   population code is about 0.02 to 0.1; above about 0.3 the area is near its refractory
   ceiling and the homeostat has little room. For population codes, where a few neurons are
   active and the rest silent, use `per_neuron`: `area` mode drives the active neurons down
   to the area average and pins the silent ones at `leak_min`.
2. **Time constant.** `rate_ema_tau_bursts` must be several times (at least 5x) the longest
   signal the area must pass unchanged, in bursts. Shorter, and the homeostat cancels the
   signal. For an area that carries task events of 2 s at 50 Hz bursts, that is at least
   500 bursts.
3. **Gain.** One update moves the leak by `gain * (rate - target)`. Crossing the full range
   takes about `(leak_max - leak_min) / (gain * |rate - target|)` updates. Choose the gain so
   that time is close to `rate_ema_tau_bursts`. Much faster, and the leak oscillates; much
   slower, and the area spends the run out of range.
4. **Range.** Set `leak_min` from the longest integration the area may have (`1/leak_min`
   bursts) and `leak_max` from the shortest. Start the area's own `leak_coefficient` inside
   the range; a leak edit becomes the homeostat's new starting point.
5. **Learning.** On an area fed by plastic mappings, a potentiated path raises the rate and
   the homeostat cancels it within about `rate_ema_tau_bursts`. Make the time constant
   longer than the reward or credit window (`eligibility_decay_bursts`) and the behavior
   episode, or the area forgets what it learns. To evaluate learned weights alone, set
   `gain` to 0 (the leaks hold) rather than disabling, which drops the homeostat state.

Record the derivation in the design notebook with the burst-rate derivation.

### Arming (`per_neuron`)

- For `arm_bursts` after enable or re-arm, the leak stays at the area's base leak and each
  neuron's rate is measured; that rate becomes its frozen target.
- Arm while the brain runs the regime to hold: experiment running, sensors live, a normal
  task in progress. A brain that is idle while arming arms every neuron to silence.
- Re-arm with `{"arm_epoch": <new number>}` alone; partial updates merge, so the other
  fields are kept. Re-sending the config with the same `arm_epoch` changes only the gain,
  clamps and time constants and keeps the targets.
- A full connectome import restarts the homeostat from the area's `leak_coefficient`, so
  `per_neuron` areas arm again from the import. Drive the brain during those bursts. After
  any restore, read `rate_target` to confirm the targets you expect.

### With modulators

A `neuro.leak` modulator scales the homeostat's leak (`leak x (1 + m)`, clamped to 0..1):
the homeostat sets the baseline, the modulator scales it while active. A long, strong
`neuro.leak` signal is seen by the homeostat as a rate change and partly undone after about
`rate_ema_tau_bursts`.

### Set it, then verify it

1. Check the area is a dense custom area and baseline its firing with `monitor_activity()`
   while the brain is driven.
2. Set it with `update_cortical_area(area, {"rate_modulated_leak": {...}})`. The whole object
   is validated first; an invalid field is rejected and nothing changes.
3. Read it back with `get_area_parameters(area)`, and again after a save or restart.
4. Read per-neuron state over HTTP:
   `GET /v1/connectome/cortical_area/<id>/neuron_state?fields=leak_coefficient,rate_ema,rate_target,homeostat_regulated`.
   `homeostat_regulated` is 1 for two-sided, 0.5 for one-sided (silent-armed), 0 for not
   regulated (arming, or `unregulated`). `list_area_neuron_states()` does not return these
   fields. For a time series, add the area and fields to the Trainer's `runData.neural.neuronState`
   (see behavior-design.md).
5. Pass checks, after at least 3x `rate_ema_tau_bursts` of driven running: the area's rate
   is within about 25% of the target (or each regulated neuron's), and under 10% of the
   regulated neurons sit at `leak_min` or `leak_max`.

| Symptom | Cause | Fix |
|---------|-------|-----|
| Most leaks at `leak_max`, rate still high | Single-burst input reaches threshold | Raise threshold, cut PSC, add inhibition |
| Most leaks at `leak_min`, rate still low | Input too weak or missing | Check wiring and upstream firing |
| Response fades during a held stimulus | `rate_ema_tau_bursts` shorter than the signal | Lengthen it, or remove the homeostat from a signal-carrying area |
| Learned behavior fades over minutes | Homeostat undoes potentiation | Longer time constant, or `gain` 0 during evaluation |
| Leak swings up and down | Gain too high for the time constant | Lower `gain` or raise `update_every_n_bursts` |
| All `rate_target` near 0, nothing regulated | Armed while the brain was idle | Re-arm with a new `arm_epoch` while driven |
| `rate_ema` is null | Area not registered (`enabled` false, invalid config, or not dense) | Read `get_area_parameters()`; fix and re-send |
