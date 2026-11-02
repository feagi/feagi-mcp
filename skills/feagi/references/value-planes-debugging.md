# Value planes and classifiers: checking and debugging

Part 2 of 2 of [value-planes-and-classifiers.md](value-planes-and-classifiers.md).

## Contents

- Checking and debugging

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
