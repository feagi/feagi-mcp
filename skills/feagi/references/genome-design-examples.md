# Genome design: two worked examples

Two designs written with [genome-design.md](genome-design.md), condensed from
`docs/walking-genome-design.md` and `docs/cityscapes-segmentation-genome-plan.md`. Patterns:
[genome-design-patterns.md](genome-design-patterns.md),
[genome-design-patterns-adaptive.md](genome-design-patterns-adaptive.md).

## Contents

- Walking genome (partly built)
- Cityscapes segmentation genome (unbuilt)

## Walking genome (partly built)

Modular biped gait on a MuJoCo body. Stages S0 to S4 were built in the source; the pattern former, learned
gait layer, veto and Trainer walk stages were still design.

**Intake.** Goal: forward displacement of at least 0.5 m in 20 s at support 0.2 without a fall;
baseline: `measure_balance()` 25 s window at support 0 (median upright episode 1.3 s). Safety:
falls are never wired to Death; a lift is vetoed while tilted (design); reward comes from detectors
only; servo slew must exceed the fall speed (34 deg/s lost to a 0.12 s fall, 85 deg/s won).
Burst rate: tau = 0.12 s, loop = 3 hops + 2 transport = 5 bursts, so burst_hz >= 5 / (tau/4) =
167 Hz; chosen 200 Hz (loop 25 ms against tau/4 = 30 ms).

**Modules** (one region each; modules talk only to their own ports, a body adapter knows the robot):

| Region | Mechanism | Plastic? |
|---|---|---|
| Posture | tonic driver | no |
| Balance reflex | ports (self-hold) to command ports, gated by stance | gain only (R-STDP) |
| Gait CPG | one 16-bin ring, shifted second readout, reset pulses | no |
| Contact phase gate | onset detector per foot, stance flag | no |
| Pattern former | phase bins to joint offsets, swing inhibited while that foot is loaded | amplitude |
| Locomotion command | go, speed, turn ports | no |
| Learning harness | reward and punishment drivers + `synaptic.reward` modulators | n/a |
| Body adapter | sensors to ports, command ports to servo channels (two-rest-voxel rule) | no |

**Mechanism choices.** Innate first (reflex, ring, contact gate), measured. Plasticity only on
port-to-command gains, reward paid by the harness. A learned gait layer (memory states to
commands) comes after, with the innate pattern kept as a permanent teacher and fallback.

**Modulators and influence.**

| Output | Affects | Intended? | Lag |
|---|---|---|---|
| Reward and punishment drivers | plastic port-to-command rules | yes; sum if both fire | 1 burst |
| Stance flag | swing commands, ring reset | yes: no swing on a loaded foot | 1 hop |
| Lift permit (design) | swing commands, resets | yes: veto while tilted | self-hold release |

**Budget.** Ring step 6 bursts, 16 bins = 96 bursts = 0.48 s per stride; R-STDP eligibility 40
bursts (0.2 s). The source states no synapse total (a gap): size it with the formulas first.

**Stages and numbers.**

| Stage | Level | Acceptance |
|---|---|---|
| S0 baseline | behavior | median upright episode recorded (1.3 s), snapshot taken |
| S1 adapter + posture | region | 14 channels within 0.32 deg of stance; held 30 s at support 0.4 |
| S2 balance reflex | region | support 0 active holds 6.70, 2.20, 2.04 s against silent 1.14, 1.08, 1.07 s |
| S3 gait CPG | region | period 96 bursts (sd 0) over 10 cycles; off = silent |
| S4 contact gate | region | stance on 100% loaded, 0% lifted; re-phase 3 bursts after load onset |
| S5b learned gait | region + behavior | at most 48 state neurons; learned mapping alone gives at least 0.5x teacher displacement |
| S7 walking | behavior | at least 0.5 m in 20 s at support 0.2, no fall |

## Cityscapes segmentation genome (unbuilt)

Design only (2026-11-01): nothing here was built or run. The WTA race and the `plasticity_eta`
sizing come from code reading, not a live run.

**Intake.** Goal: mean IoU on 500 validation images, T-b = mIoU_7 > max(0.30, baseline_7 + 0.10)
and pixel accuracy > 0.60; baseline_7 is the per-location majority-class value measured first.
Safety: learning frozen for validate, test and live use; a score-only run must score about 0
(the Trainer writes the teacher plane in test until fixed). Hub: the one segmentation genome has 13,845 neurons and 400 synapses (a seed, not
a circuit). Facts: no body, so the burst rate is whatever the engine sustains, measured with
`get_runtime_metrics(measure_s=10)`.

**Mechanism choice.** Classifier rejected (one pattern per image, no per-pixel output). Chosen: a
per-location plastic readout with a teacher clamp, because per-pixel credit is exact when only
synapses whose endpoints fired are credited.

**Modules** (W x H = 128x64, 19 classes, 8,192 positions):

| Block | In to out | Mechanism | Learned |
|---|---|---|---|
| Retina | image to luminance, 4 opponent planes, 4 luminance bins | opponent rules, thermometer | no |
| Edge Detector | luminance to contrast, 4 orientations, flat | center-surround, oriented pairs | no |
| Texture | contrast to 3 edge-density bins | 5x5 pooling | no |
| Mask Teacher | label plane to thermometer to one-hot (`W x H x 19`) | two-area one-hot | no |
| Pixel Classifier | 17 feature planes + teacher to class bins | plastic readout + clamp + WTA | yes |
| Mask Decoder | class bins to output plane | value passthrough, PSC (z+1)/19 | no |
| Temporal Context (live) | class bins to leaky persist area and back | block copy | no |

**Modulators.** One `synaptic.learning_rate` modulator at -100% on a `LearnOff` driver stops the
weight commits of the 17 plastic rules (plain `stdp` associative rules can still create synapses). Influence: LearnOff to all plastic rules, intended, 1 burst.

**Budget line (128x64, estimate).** Feature neurons 139k, class bins 156k; plastic synapses
17 x 19 x 8,192 = 2.65M; pairwise WTA 19 x 18 x 8,192 = 2.8M (pooled inhibition: 2 x 8,192 x 19
= 311k); 2 to 3M events per burst, about 1 burst per second on the Apple M4 Pro host; depth 4 to 5
hops, so teacher delay = feature depth - teacher depth and ticks per sample >= feature depth + 6.

**Schematic** (`show_in_studio` kind `circuit`; slug ids, schema in read_skill hey-feagi-chat Diagrams):

```json
{"v": 1, "title": "Segmentation (design)", "layout": "horizontal",
 "nodes": [{"id": "retina", "label": "Retina > Lum", "layer": 0},
           {"id": "edges", "label": "Edge Detector > Contrast", "layer": 1},
           {"id": "teacher", "label": "Mask Teacher > TeacherOneHot", "layer": 1},
           {"id": "readout", "label": "Pixel Classifier > ClassBins", "layer": 2},
           {"id": "decoder", "label": "Mask Decoder > Output", "layer": 3}],
 "edges": [{"from": "retina", "to": "edges", "label": "excitatory"},
           {"from": "edges", "to": "readout", "label": "plastic stdp"},
           {"from": "teacher", "to": "readout", "label": "clamp + inhibitory"},
           {"from": "readout", "to": "decoder", "label": "passthrough"}]}
```

**Stages** (each with a number): measure per-location baselines; verify planes, one-hot teacher
(exactly one bin per position every burst) and the WTA (one winner in at least 95% of positions)
before any learning; teacher-only run (at least 95% agreement on 10 held samples); learning pilot
at 7 classes; then 19 classes; live last.
