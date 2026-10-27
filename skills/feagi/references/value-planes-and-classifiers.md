# Value planes, segmentation, depth, and classifiers

## Contents

- Value planes
- Class map and depth encoding
- Passing values through exactly
- Expanding a plane into bins
- Classifiers
- What learning does, link by link
- Memory lifetime and reward consolidation
- Train and test a classifier
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
`synaptic_delay_bursts` (default 1), plus one burst for the class memory neuron to fire,
plus one burst for the replay onto the output (default answer delay 3). Measured at the
default: label and sample on bursts 1-3, memories fire from burst 3, output from burst 4,
correct area from burst 5, error 0. A first answer scored as an error on every presentation
means the answer delay is stale; `inspect_classifier()` and `get_cortical_mapping()` show the
values.

**Reward training** (`update_classifier(id, {"reward_training": true})`) makes the
associative edge (sample memory -> class memory) standard R-STDP. `reward_modulator_ids` lists
the `synaptic.reward` modulators it learns from; turning reward training on with an empty
list selects the classifier's "correct answer" (+100%) and "error" (-100%) modulators. Strength
is each modulator's `magnitude_percent`. Confirm with
`get_cortical_mapping(sample_memory, class_memory)`: `plasticity_mode: rstdp`, both modulators,
and `eligibility_decay_bursts` = answer delay + 2 (default 5), so a late answer still reaches
the active links. FEAGI recomputes that value on genome load and whenever a class input ->
class memory rule changes, so do not hand-edit it. `answer_feedback_area_id`,
`answer_latency_bursts`, `learn_area_id` and `confidence_area_id` are stored but have no effect.

`POST /v1/cortical_area/classifier/{id}/answer_modulators` creates missing answer areas and
modulators (classifiers made before they existed, or after one was deleted) and returns
their ids. To deliver reward or punishment by hand, see
[memory-and-plasticity.md](memory-and-plasticity.md) (Modulators).

**Routing to an output**: wire a class output with
`wire_value_passthrough(output, oseg, class_count=N)`, then confirm with
`validate_magnitude_passthrough()`.

### What learning does, link by link

- A link is one synapse from one sample-memory neuron (a sample pattern) to one class-memory
  neuron (a class). It is created only on a burst where both neurons fire and the net reward
  is positive. Eligibility does not help creation; it only lets a later reward reach a link
  that already exists.
- Reward and punishment act only on links whose own two neurons fired in the window.
  Punishing pattern A never changes pattern B's link.
- Positive reward strengthens the active link. The correct area fires on every burst the
  answer matches, so weights keep growing while a labelled sample is held (about 180 after 20
  presentations of 8 bursts, from 1). There is no weight cap by default.
- Punishment (error area) weakens the active link. A wrong label makes the output fire both
  the recalled class and the labelled class, so the error area fires and the recalled link
  weakens (measured 180 -> 57 after 10 mislabelled presentations). A link to the wrong class
  is created only on a rewarded burst and stays at 0 under punishment.
- Retraining with the right label restores the link (57 -> 252 after 10 presentations) with
  no error bursts.
- Mislabelled samples therefore cost accuracy on that sample only; they do not spread.

### Memory lifetime and reward consolidation

Classifier memories are short-term at first: a memory neuron lives `neuron_init_lifespan`
bursts (default 9) unless its pattern returns, and each return adds
`neuron_lifespan_growth_rate`. When a neuron expires, every link touching it is deleted.
Interleaved training (A, B, A, ...) lets each pattern's neuron die before it returns, so
without help nothing is learned.

**Reward consolidation** fixes this: when a positive reward creates or strengthens a link
between two memory neurons, both become long-term at once (see
[memory-and-plasticity.md](memory-and-plasticity.md)). Correctly labelled training therefore
keeps its memories; unrewarded patterns still expire. Check with `list_memory_neurons()`
(`long_term_neuron_count`) after training. `memory_neurons_expire_unmatched` in
`inspect_classifier()` before training is normal; after training with reward on it means the
answer never earned reward (check the answer timing above).

### Train and test a classifier

Use `run_stimulus_protocol` for every step: one call presents all of a step's stimuli on the
same bursts and records per-burst firing. Never run two protocol calls at once (they share
bursts and double-post), and never present sample and label as two separate stimulate calls.

1. Build: `create_classifier()`, map the sample area(s) with `classifier_sample` and each class
   area with `classifier_class`. `inspect_classifier()`: no missing slots or mappings
   (`sample_memory_no_ltm` before any training is expected).
2. `update_classifier(id, {"reward_training": true})`; read the edge as above.
3. Baseline: each sample alone, 4 bursts on, 12 off, 5-10 per class. Expect no output.
4. Train: sample and its label together in one step, held at least answer delay + 4 bursts
   (8 at the default delay), then 12 rest bursts; interleave classes. Expect the correct
   area on every held burst after the first answer and 0 error bursts.
5. Links: `diagnose_mapping_plasticity(sample_memory, class_memory)`;
   `memory_neuron_synapse_count` is the learned links (one per pattern-class pair);
   `placeholder_synapse_count` is the fixed seed edge between the memory voxels and carries
   no class meaning.
6. Test: each sample alone, as in step 3. Score the class output only: with no label, the
   correct and error areas stay silent. Verified result: 0/10 -> 10/10 per class after 20
   presentations, kept after a 400-burst rest.
7. Reset for a clean rerun: `reset_cortical_neural_state([sample_memory, class_memory])`
   removes memory neurons and links (and the placeholder edge).

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

Classifier symptoms:

| Symptom | Cause | Check |
|---|---|---|
| 0 links after training | Reward training off, label not presented with the sample, or answer never matched | Mapping read; training trace shows correct-area bursts |
| Output silent at test after training | Memories expired (no reward reached them) | `list_memory_neurons()` long-term counts |
| Error on the first answer of every presentation | Stale answer delay / eligibility | `get_cortical_mapping()`; reload or `update_classifier()` |
| A sample answers two classes | A link to the wrong class was rewarded (labels mixed in one step, or parallel protocol calls) | `list_area_synapses(class_memory, "incoming", view="edges")` |
