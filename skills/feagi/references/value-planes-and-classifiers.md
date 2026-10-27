# Value planes, segmentation, depth, and classifiers

## Contents

- Value planes
- Class map and depth encoding
- Passing values through exactly
- Expanding a plane into bins
- Classifiers
- Checking and debugging

## Value planes

The Depth Map input (`idpt`), Object Segmentation input mask (`iseg`), Object Segmentation
output (`oseg`), and scanner classifier outputs are **one layer deep**: `W x H x 1`. The
payload is each firing voxel's membrane potential, not a Z index. Never size these areas with
a class count or depth bins in Z. Potential 0 always means "nothing here" (unlabeled, silent,
or no depth return).

Why: a 512x256 Cityscapes mask as a one-hot Z volume needed 512x256x19, about 2.49M neurons,
for the teacher and again for the output. As value planes both are 131k.

## Class map and depth encoding

- **Class maps** (segmentation masks, segmentation outputs, classifier twins): class `c` of
  `class_count` is potential `(c + 1) / class_count`, always in (0, 1]. Decode with
  `round(potential * class_count) - 1`. Example with 19 classes: class 0 is 1/19, class 13 is
  14/19. FEAGI accepts 1 to 9999 classes; the Trainer caps segmentation at 255 because byte
  label 255 marks an unpredicted pixel.
- **Depth**: the encoder quantizes normalized distance into `depth_levels` and writes
  `level / depth_levels` with level 1 to `depth_levels`. Levels cost no neurons, so 256 or 1024
  levels are free. Lidar fits as a range image: rings on Y, azimuth on X.

## Passing values through exactly

A value survives a hop only when:

- the source has `mp_driven_psp` on (otherwise every spike delivers a flat PSP);
- the mapping is 1:1 with weight 1 and PSC multiplier 1;
- the source uses uniform PSP if it fans out (otherwise the value is divided);
- the destination threshold is below the smallest value;
- the destination does not leak, accumulate charge, or have refractory or snooze periods.

`mp_driven_psp` and uniform PSP are area-wide, so they also affect the source's other outgoing
mappings.

Tools:

- `wire_value_passthrough(src, dst, class_count=N)` (or `value_levels=` for depth) sets all of
  the above and maps with `projector` at weight 1. Shapes must match.
- `validate_magnitude_passthrough(src_area, dst_area, class_count=N)` confirms it. With a class
  count, any scaling, fan-out, accumulation, or threshold drift is an error, because drift
  decodes to a different class. Each finding includes an `update_cortical_area()` fix.

The same validator diagnoses any graded signal that arrives saturated or distorted, such as an
audio output that plays as full-scale noise. `measure_audio_io_disparity()` measures the live
gap between an audio input and output while audio streams.

## Expanding a plane into bins

Downstream areas learn from *which* neuron fires. When a circuit must react per depth range or
per class ("obstacle nearer than X"), expand the plane:
`expand_value_to_bins(src, levels, name, brain_region_id, position)` creates a
`W x H x levels` area whose threshold rises along Z and maps the plane into it with
`projector`. Bin `z` fires when the value is at least `(z + 0.5) / levels`: a cumulative
(thermometer) code. For a class map use `levels = class_count`; class `c` fires bins 0 to c.
For one-hot bins, add an inhibitory mapping from each bin to the bin below.

Keep the plane for transport, readout, scoring, visualization, and MP replay. Expand to bins
when synapses must specialize by range or class, or when a scanner classifier reads the area
(scan patterns hash fired coordinates, so a bare plane looks identical at every depth).

## Classifiers

Classifiers are first-class genome objects, not cortical areas: list them with
`list_classifiers()`, not by searching area names for `_sample_mem` or `_class_mem`.
`create_classifier(name, brain_region_id, coordinates_3d)` makes the classifier circuit with
a sample memory, a class memory, an **error** area, a **correct** area, the associative edge
(sample memory -> class memory), and two Reward modulators that adopt the answer areas as
drivers: "*name* correct answer" (+100%) and "*name* error" (-100%).

**Inputs** are mappings, not tool arguments. Map a sample area onto the sample memory with
morphology `classifier_sample` (several inputs hash as one pattern). Map each class area onto
the class memory with `classifier_class`; FEAGI creates a class output shaped like that class
input. Class memory replays onto the outputs.

**Answer check**: the error area fires on the next burst when a class output disagrees with
its class input from the answer delay earlier, or an output has more than one neuron firing.
The correct area fires when every class input that fired was answered with no error. The
answer delay comes from the circuit: the class input -> class memory rule's
`synaptic_delay_bursts` (default 1) plus one burst for the replay onto the output.

**Reward training** (`update_classifier(id, {"reward_training": true, ...})`) makes the
associative edge standard R-STDP. `reward_modulator_ids` lists the `synaptic.reward`
modulators it learns from: positive ones strengthen the links active when they fire,
negative ones weaken them. Turning reward training on with an empty list selects the
classifier's correct-answer and error modulators. The edge's `eligibility_decay_bursts` is
set to the answer delay + 2 so a late answer still reaches the active links. Strength is
each modulator's `magnitude_percent`. `answer_feedback_area_id`, `answer_latency_bursts`,
`learn_area_id` and `confidence_area_id` are stored but have no effect.

`POST /v1/cortical_area/classifier/{id}/answer_modulators` creates missing answer areas and
modulators (classifiers made before they existed, or after one was deleted) and returns
their ids. To deliver reward or punishment by hand, `POST /v1/training/reward` or
`/v1/training/punishment` with `{"modulator_ids": [...]}`; reward needs positive modulators,
punishment negative ones.

**Routing to an output**: wire a class output with
`wire_value_passthrough(output, oseg, class_count=N)`, then confirm with
`validate_magnitude_passthrough()`.

## Checking and debugging

- `inspect_classifier()` resolves every slot and the required mappings and reports
  `missing_slots`, `missing_mappings`, `blockers`, `ready`, memory counts,
  `memory_findings`, and `value_findings`. Use it instead of walking areas and mappings by
  hand.
- `decode_class_map(area, class_count)` decodes the last burst of a mask, twin, or segmentation
  output into a class histogram, an `undecodable` count (a sign of scaling or a non-value
  area), and up to `max_pixels` pixel rows.
- Trainer scoring writes ground truth to `iseg` (ignore-label pixels are not written) and
  decodes `oseg` the same way. A pixel the brain leaves silent counts as a miss for its true
  class, never as class 0.
