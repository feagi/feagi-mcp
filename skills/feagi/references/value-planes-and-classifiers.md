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
`list_classifiers()`, not by searching area names for `_kernel_mem` or `_class_mem`. A
classifier owns a sample memory, a class memory, an error area, and an associative edge.

**Kernel mode**: `create_classifier()` with a kernel area and a `1 x 1 x n` class area.
`attach_classifier_field()` requires the field to match the kernel area and creates
`{classifier name} class output` as `1 x 1 x n`; on recall the winning class fires at depth z.
`mp_driven_psp` stays off.

**Scanner mode**: `create_classifier()` with a `W x H x 1` mask area, a `kernel_size` whose Z
equals the image field depth, and `class_count`. Then `attach_classifier_field()` for each
image field; FEAGI creates a `W x H x 1` class output (twin) per field. Training reads the class
from the mask potential. On recall each detected pixel is written once with the winning class
(highest vote, ties to the lower id) as an exact potential. Changing class count, kernel size,
or mode drops learned patterns. Modify with `update_classifier()`.

**Routing to an output**: the Trainer only reads the segmentation OPU. Wire the twin with
`wire_value_passthrough(twin, oseg, class_count=N)`, then confirm with
`validate_magnitude_passthrough()`.

## Checking and debugging

- `inspect_classifier()` resolves every slot and the four required mappings and reports
  `missing_slots`, `missing_mappings`, `scan_blockers`, `scan_ready`, memory counts,
  `memory_findings`, and `value_findings` (`class_count_missing`, `mask_not_single_layer`,
  `twin_not_single_layer`, `twin_not_forwarding_value` with a fix). Use it instead of walking
  areas and mappings by hand.
- Common `scan_blockers`: `kernel_memory_no_ltm`, `field_burst_engine_off`,
  `twin_burst_engine_off`, missing scan mapping or slots, and `memory_no_episodic_upstream`.
- `decode_class_map(area, class_count)` decodes the last burst of a mask, twin, or segmentation
  output into a class histogram, an `undecodable` count (a sign of scaling or a non-value
  area), and up to `max_pixels` pixel rows.
- Trainer scoring writes ground truth to `iseg` (ignore-label pixels are not written) and
  decodes `oseg` the same way. A pixel the brain leaves silent counts as a miss for its true
  class, never as class 0.
