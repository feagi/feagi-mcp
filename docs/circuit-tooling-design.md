# Circuit tooling: design note

Status: submitted to `senior-systems-architect` 2026-10-31. Scope: feagi-mcp only (Python). No
feagi-core or Studio edits. All tools are generic: no robot, joint or experiment names; defaults
are dimensionless or taken from the spec/model.

Problem: eight build stages exposed gaps that cost 5-15 min each and hundreds of single calls:
no burst-exact spike read, no held stimulus that lands every burst, circuits built call by call,
oversized exports and payloads, no burst-timing read.

## Facts read (not assumed)

- feagi-core exposes `GET /v1/burst_engine/fire_history?areas=<id,..>&bursts=<n>` (16 areas, 1..2000
  bursts; `burst_engine.rs:1354`; route `transports/http/server.rs:1067`) and
  `DELETE` of the same. One frame per burst per area, oldest first, **explicit empty frames for
  silent bursts**, voxels as `[x,y,z]`, dynamic memory neurons as ids. The first read subscribes the
  areas to the Fire Ledger (window = `bursts`), so it returns only bursts recorded since; a
  subscription idles out after `subscription_ttl_s` (300 s). The route answers on the live build
  (404 for an unknown area, checked with a read-only GET).
  `fire_queue/detailed` holds only the latest burst, the cause of the 1-in-5 sampling today.
- `manual_stimulation` fires one burst per post (`feagi_client._post_stimulation`). Today's hold
  (`_run_burst_gated`) polls the counter and, in `run_stimulus_protocol`, also GETs the fire queue
  (~100 KB) inside the per-burst gate: that is why ~20% of bursts at 200 Hz get no post.
- Burst timing: not exposed. `/v1/monitoring/metrics` has `burst_count`, `burst_frequency_hz`,
  counts only; `/v1/monitoring/performance` returns constants 0.0; `frequency_status.
  actual_frequency_hz` echoes the target (`burst_engine.rs` `get_frequency_status`);
  `avg_burst_time_ms` is hard-coded 0.0 ("Not yet tracked by BurstLoopRunner",
  `runtime_service_impl.rs:367-379`, `system_service_impl.rs:231`).
- `record_embodiment_trace` is a Studio (feagi-desktop) tool, not served by feagi-mcp, so a
  `stimulus=` option there is out of scope; `hold_stimulus` below is its feagi-mcp counterpart and
  runs in the background next to any trace.
- Genome export: `neuron_morphologies` holds all ~106 morphologies of the brain; mappings sit in
  `blueprint["<prefix>-cx-dstmap-d"] = {dst_id: [rule{morphology_id,...}]}`.
- Mapping rules per edge are readable from `cortical_map_detailed`; realized synapse edges from
  `/v1/connectome/{id}/synapses[/incoming]` carry neuron ids only (no target area), so a per-mapping
  count is `|{e in out(src): e.target in targets(in(dst))}|` (neuron ids are global).

## 1. `record_spikes(areas, bursts=200, csv_path=None)` (read-only hint)

Reuses: `_resolve_area_refs` (names or ids), `get_burst_counter`, `get_burst_engine_config`.
New client method `record_spikes`, pure helpers in `spike_record.py`.

Flow: resolve areas (<=16) -> read #1 (`bursts=window`) subscribes and gives `current_burst` c0 ->
wait until counter >= c0+N (sleep paced by the burst interval; timeout 2x expected + 5 s) -> read
frames; for N > window, re-read every 0.8 window and merge by burst number -> trim to (c0, c0+N] ->
DELETE the subscription in `finally` (in-process refcount per area so a concurrent `hold_stimulus`
verify or second recorder never drops the other's subscription; cross-process users are not
coordinated, stated in the doc). Caps: N <= 20000, window 1000.

Returns (compact, never rows): `{success, first_burst, last_burst, bursts_requested,
bursts_observed, gaps:[burst..](capped 50), timed_out, areas:{id:{name, fired_bursts, fire_fraction,
total_spikes, first_fire_burst, last_fire_burst, runs:[[start,end]..](capped 20), top_voxels:
[{voxel,count,fraction}..](8)}}, csv_path}`. CSV (optional): header
`burst,area_id,area_name,x,y,z,memory_neuron_id`, one row per spike, written by a stream.

## 2. `hold_stimulus(area, voxels, duration_s, start_delay_s=0, background=False, verify=True)` and `get_stimulus_hold(hold_id, cancel=False)`

Reuses: `_post_stimulation`, `get_burst_counter`, `get_burst_engine_config`, the fire-history
subscription of tool 1 (for verification), `STIMULATION_HOLD_MAX_MS` cap (30 s).

Loop does only two light requests per burst (counter GET, post) and never reads the fire queue:
`c = counter; if c != last: post; record c`. A jump of the counter by more than 1 between two posts
is recorded as skipped bursts. `background=True` starts an `asyncio` task in the server loop and
returns `{hold_id, ...}` at once, so it runs beside `record_embodiment_trace`/`record_spikes`;
`start_delay_s` replaces a trace-relative `from_s`. `get_stimulus_hold` returns the same summary
(state running/done/cancelled/failed) or cancels.

Landing check (the requested confirmation): with `verify=True` the target area is subscribed
for the hold and, at the end, every burst between the first and last post is checked for the
stimulated voxels (`force_fire` guarantees a spike when the post is consumed). Returns `{hold_id,
state, area, voxels, first_burst, last_burst, burst_interval_s, bursts_posted, bursts_skipped:
[..], post_failures, landed:{checked, landed, missed:[..]}}` in under 2 KB. If the loop cannot
sustain the rate the numbers say so; the hold is not claimed to work without them.

## 3. `build_circuit_from_spec(spec_json, dry_run=True)`

New pure module `circuit_spec.py` (expansion, sizing, validation; no I/O) plus one client method
that executes the plan with existing code: `create_brain_region`, `create_cortical_area` (neuron
parameters go through its existing post-create update path), `create_morphology` (patterns;
`_morphology_rule_rejection` still applies), `update_cortical_mapping`, and
`stance_mapping.compile_stance_offset_rows` (with `coactive_z`).

Spec: `{"region": {title, coordinates_2d, coordinates_3d, parent_region_id?} | {"region_id"},
"areas":[{name, dimensions, position?, neurons_per_voxel?, properties{neuron_*}}], "morphologies":
[{name, type, parameters}], "mappings":[{src, dst, rules[], replace?}], "templates":[{"template",
"name", ...}]}`. Names refer to spec areas or to existing live areas (resolved at run time, listed
as `external` in the dry run). Positions default to a deterministic grid from the region's
`coordinates_3d` (step 40, so >= 32 apart); live placement checks still run.

Templates (each expands to areas + morphologies + mappings; the numbers it computes are returned
under `sizing`, nothing is hidden):

| Template | Parameters (defaults) | Expansion |
|---|---|---|
| `port` | name, bins N, threshold T (2.5), psp (3), leak (0.04), refractory (0), input (1.0), self_hold (true), hold_psc? | `[1,1,N]` area, accumulation on. Self-hold = `block_to_block` self-mapping with s = psp x psc obeying `T - input <= s < T`; default s = T - input/2, psc = s/psp (4 dp); an explicit `hold_psc` outside the interval is an error. |
| `onset_pulse` | name, gate, threshold (1), exc_psc (1), inh_psc? | `<name>_Onset`, `<name>_Delay` `[1,1,1]`, accumulation off. gate->Onset +exc, gate->Delay +exc, Delay->Onset -inh (default inh = exc, so the second burst nets 0), all delay 1: Onset fires once, one burst after gate onset. |
| `ring_cpg` | name, bins N, step_bursts k, threshold T (6), psp (1), leak (0.02), drive?, drive_d (0.05), lateral_psc?, inhibit_psc?, seed?{area,bin,psc}, readouts?[{name, shift}] | `[1,1,N]` ring: self-hold `block_to_block` with s in `[T-d, T)`; excitation `lateral_+z` + `last_to_first`, p = (T - d)/k by the S3 design formula n = ceil((T-d)/p); inhibition `lateral_-z` + `first_to_last` (default -p); optional drive `0-0-0_to_all`; seed = custom pattern `*,*,* -> 0,0,bin`; readout shift m = `block_to_block`-style custom patterns `0..N-m-1 -> ?+m`, `N-m..N-1 -> ?-(N-m)` (m=0: `block_to_block`). |
| `servo_channel_two_rest` | name, opu, depth, channels[{channel, reference, range}], tonic, tonic_psc, sources[{area, role reflex/pattern, channel, src_axis, src_bins, gain, max_offset, deadband}], opu_psc, inhibit_psc? | Areas `<name>_RestReflex`, `<name>_RestPattern` `[C,1,depth]`. tonic -> RestReflex voxel `[ch,0,z+1]`, tonic -> RestPattern `[ch,0,z-1]` per channel (z = stance bin from the OPU's registered coding via `feagi_rust_py_libs`; see `percentage_coding.py`); Rest* -> opu `block_to_block`. Each source: offset rows from `compile_stance_offset_rows` with `coactive_z` = the other role's rest z (reflex z-1, pattern z+1), mapped source -> opu; source -> own Rest area with inhibit rows (bins that have an offset, as `N..M` ranges) and psc -max(1, ceil(tonic_psc)) (integer, >= the drive). A clamp warning from the compiler on a leg channel is an error unless `allow_clamp`. |

Dry run (`dry_run=True`, the default): validates, expands, returns `{valid, errors, warnings,
summary{areas,morphologies,mappings}, sizing, external, calls:[{n, call, args}]}`; makes no
request except an optional read of live names to flag conflicts. Real run: preflight read of live
names (abort before any create on a name conflict), then sequential create region -> areas ->
morphologies (an "already exists" answer on a morphology is reported `reused`) -> mappings; stops at
the first failure and returns what exists (no rollback; the docs say to snapshot first).
Returns `{created{region_id, areas{name:id}, morphologies, mappings}, failed, verification{areas:
{expected, found}, mappings:[{src,dst,rules_expected,rules_found,synapses}], zero_synapse:[..]}}`.
Synapse counts per mapping use the exact pair count from the Facts section (shared helper
`synapse_counts.py`, also used by item 6).

## 4. Region export and validation

- `download_region_genome(region_id, prune_morphologies=True)`: after the existing GET, keep only
  morphologies referenced by a `morphology_id` in any `dstmap-d` rule of the exported blueprint
  (pure `prune_unreferenced_morphologies`). Result shape is unchanged (the genome); the count
  removed is logged. `prune_morphologies=False` returns the raw export.
- `validate_genome(genome_json="", file_path=None)`: exactly one of the two; `file_path` is read
  with `decode_genome_artifact` (any extension; `~` expanded); errors for missing/unreadable files
  are returned in `issues`.

## 5. `get_runtime_metrics(measure_s=0)`

Adds `burst_timing`: `{available: false, gap: "<exact endpoints above>", fix: "BurstLoopRunner
records per-burst duration (mean, max) and overruns; expose in /v1/monitoring/metrics"}`. With
`measure_s > 0` (cap 10): `measured` = counter delta against wall clock over the window:
`bursts_elapsed, expected_bursts, achieved_frequency_hz, mean_period_ms, shortfall_bursts`,
labelled `source: counter_vs_wallclock`. This is a period/shortfall measurement, not a duration:
mean and max burst duration stay unavailable and are not faked.

## 6. Compact views

- `get_region_circuit(region_id, include_child_regions=True, compact=False, synapse_counts=True)`:
  `compact=True` returns `{region, title, members:[{name, dimensions}], edges:[{src, dst, rules:
  [{rule, psc, delay, plastic}], synapses}]}` with names instead of ids; drops roles, boundary,
  designated, isolated lists. Dimensions from `get_cortical_area_geometry`.
- `get_cortical_map_detailed(compact=False, synapse_counts=True)`: same edge shape for the whole
  brain. Synapse counts skipped (flag in result) when the listed edges exceed 200 000.

## Alternatives weighed

1. `record_spikes` by sampling `fire_queue/detailed` faster: still one burst per read, races the
   engine at 200 Hz. Rejected; the ledger route is burst-aligned by construction.
2. Hold as a blocking tool only, parallel to a trace: needs the caller to issue concurrent calls;
   kept as the default (`background=False`), background added for traces in Studio.
3. Spec builder as a one-off script per circuit: that is the status quo (hundreds of calls).
4. Verify landing by re-reading the fire queue: same sampling gap. Rejected for the ledger.
5. Burst duration estimated from counter jitter: only gives the period; reported as such, not as
   duration.

## Files touched

New: `src/feagi_mcp/spike_record.py`, `circuit_spec.py`, `synapse_counts.py`, `tests/
test_spike_record.py`, `test_circuit_spec.py`, `test_circuit_tooling.py`. Edited:
`feagi_client.py`, `server.py`, `skills/feagi/SKILL.md`, `references/tool-index.md` (generated),
`building-circuits.md`, `behavior-design.md`, `embodiment.md` (spike/hold recipes), `lessons.md`.

## Acceptance

Unit tests with mocked FEAGI responses per tool; one dry-run test expanding every template;
`ruff check`/`ruff format` clean on touched files; `test_tool_names.py` green (index regenerated).
No live run is made (live experiment in progress); the first live use is the next build stage.

## Open points for review

- `ring_cpg` sizing: the design formula gives p = (T-d)/k = 0.99 for T=6, d=0.05, k=6; the S3
  measurement that produced a 6-burst step used p = 0.565. The formula is unverified against that
  measurement (uniform PSP distribution and leak are not in it). Proposal: ship the formula as the
  default, make `lateral_psc` an explicit override, return the computed value in `sizing`, and
  state the discrepancy in the skill recipe (verify the period with `record_spikes`).
- `record_spikes` marked read-only (the subscription is a transient observer, dropped in `finally`)
  so it passes the Studio hand-off guard; `hold_stimulus` and `build_circuit_from_spec` are not.

## Architect verdict (2026-10-31): APPROVED WITH CHANGES; applied

1. `record_spikes` re-read pacing is `min(0.8 * window * interval, ttl/2)` (`ttl` from the
   response's `subscription_ttl_s`; the service expires idle subscriptions inside the read itself),
   and the window is capped at 500 bursts per read (a read resolves coordinates under the NPU
   lock). The in-process refcount stays (the server keeps one entry per area; DELETE removes it).
2. `hold_stimulus` is a wall-clock-paced, post-only loop at `interval/2` (the pending queue dedupes
   and drains every burst, so duplicates are harmless); no per-burst counter poll. Posted and
   skipped bursts come from the ledger, not from the loop.
3. Landing window is `(first_post_burst, last_post_burst + 1]` (a post merges into the next burst).
4. `mode` is dropped from `hold_stimulus` (the server always force-fires).
5. `ring_cpg`: `lateral_psc` is required (no default); `psp_uniform_distribution=true` and
   `neurons_per_voxel=1` are set explicitly; `sizing.predicted_step` uses the leak-aware model
   `sum_{i<n} (p+d)(1-g)^i >= T` and is flagged `uncalibrated` (the S3 measurement is not explained
   by it); the recipe requires a `record_spikes` period check.
6. `servo_channel_two_rest`: Rest areas get explicit neuron properties (threshold <= tonic
   contribution, accumulation off); inhibition is sized in membrane-potential units,
   `|psc| >= ceil(tonic_psp * tonic_psc / source_psp)` (PSPs read from the spec, default 1);
   per-source `src_fixed` is accepted.

Gaps recorded for the report (feagi-core, deferred while a run is live): burst duration/missed
bursts are not tracked; there is no multi-burst stimulation endpoint (a per-burst post loop is the
only way to hold a stimulus).
