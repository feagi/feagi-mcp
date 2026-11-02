# Genome design: efficiency budget and build order

Part 2 of 2. Checklist, intake, modules, mechanisms, modulators: [genome-design.md](genome-design.md).

## Contents

- Efficiency budget
- Schematic and documentation
- Build order and verification

## Efficiency budget

Synapses, not neurons, set the cost: every active synapse is one event per burst.

| Rule | Synapses (N = positions, D = depth) |
|---|---|
| `block_to_block` | one per voxel |
| `projector` (pooling) | about N_src, one per source in the block |
| `all_to_all` | N_src x N_dst |
| k x k local kernel (`?-A:?+B` on two axes) | k^2 x N |
| `!` winner-take-all along depth | N x D x (D - 1) |
| pooled inhibition (class to pool and back) | 2 x N x D |
| plastic fan-in, F feature planes to D classes | F x D x N |

- **Events per burst** = active fraction x synapses. Measured: 0.37 us per synaptic event (CI
  microbench). A brain of about 270k neurons and 924k synapses at 40% activity took 278 to 333
  ms per burst against a 66.67 ms budget at 15 Hz. Host Apple M4 Pro, 14 cores, read 2026-11-01
  from `feagi-core/crates/feagi-npu/SCALABILITY_BOTTLENECK_ANALYSIS.md` and
  `feagi-core/perf/ci_microbench_baseline.json`. Re-measure with `get_runtime_metrics(measure_s=10)`.
- Caps read from `feagi_configuration.toml`: 10M neurons, 25M synapses (check, do not assume).
- **Rules:** smallest dimensions that work (`[1, 1, 1]` for logic); value planes over one-hot Z
  (512x256x19 one-hot is about 2.49M neurons, as planes 131k); bins only where synapses must
  specialize; pooled inhibition over pairwise; no `all_to_all` on sheets.
- **Latency:** hops x burst period against the body's time constant; stabilizing loops need
  `burst_hz >= 4*(hops + 2)/tau`. A rate the engine cannot sustain silently shortens Trainer holds.
- Write the **budget** as the template's per-rule table plus its totals line. Aggregate counts
  alone hide the one rule that explodes.

## Schematic and documentation

- **Schematic and tables:** the template's schematic section sets the node and edge-label
  grammar; show it with `show_in_studio` kind `circuit`. Without Studio, give the same as the
  template's tables (module, in, out, rule, sign, synapses) and keep a design doc in the repo.
- **Notebook:** append_design_note kinds `goal`, `constraint`, `baseline`, then one `hypothesis`
  per module with its acceptance number, later `verdict` and `dead_end`.
- **Present before building:** modules, mechanism choices, budget line, risks, and at most one
  exclusive question. This is a report, not a blocking approval, unless the host has an
  architect gate; then wait for its verdict. End with one line, `Design cost: N tool calls, N
  reference reads`, so the user sees the price of each design.

## Build order and verification

- One stage per module: `snapshot_genome()`, build (`build_circuit_from_spec()` with
  `dry_run=True` first), black-box test against the module's number, then
  `download_region_genome()` to prove the module exports alone.
- Order: sense to act with innate wiring; safety vetoes; then learning, measured against the
  innate path.
- Stages and stops: [lessons.md](lessons.md#work-in-stages). End the task with Bugs and Gaps.
