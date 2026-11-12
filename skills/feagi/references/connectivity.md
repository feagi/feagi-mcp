# Connectivity: mappings and morphologies

## Contents

- How wiring works
- Reading existing wiring
- Reuse-first workflow
- Core rules
- Mapping rule fields
- Custom rules and the pattern language
- Positional servo outputs
- Changing and removing wiring

## How wiring works

A **cortical mapping** connects a source area to a destination area. It holds one or more
**mapping rules**. Each rule names a **morphology** (a connectivity pattern) and adds gain,
delay, and plasticity settings. FEAGI grows synapses from the rules; changing a rule rebuilds
them. One src to dst edge can carry several rules (for example `episodic_memory` plus
`associative_memory`).

## Reading existing wiring

| Question | Tool |
|---|---|
| All edges, scan by source or destination | `get_connectivity_summary(src_filter=..., dst_filter=...)` |
| Rules stored on one edge | `get_cortical_mapping(src_area, dst_area)` |
| Full detail on one edge, with synapse counts | `get_connectivity(src_area, dst_area)` |
| Outgoing map for every area | `get_cortical_map_detailed()` |
| One region's edges | `get_region_circuit(region_id)` |
| Paths between two areas | `trace_signal_path(from_area, to_area, max_hops)` |
| Synapses that actually exist | `get_cortical_synapse_counts()`, `list_area_synapses(direction="incoming")` |

Rules are what the genome asks for; synapses are what FEAGI grew. When they disagree, trust
synapse counts and look at dimensions and rule filters.

## Reuse-first workflow

1. `describe_connectivity_rules(include_classes=["core"])` or `list_morphologies_summary()`
   to see what exists. The default `detail="names"` returns name + one-line description;
   use `detail="full"` (or `include_pattern_language=True`) only when authoring a custom rule.
2. `recommend_connectivity_rules(src_area, dst_area, intent="...")` ranks existing rules for
   the intent and also returns a `construction` plan if nothing fits.
3. `apply_connectivity_rule(src_area, dst_area, intent="...", postsynaptic_current_multiplier=...)`
   selects and applies the best existing rule. By default it appends to the edge;
   `replace_existing=True` overwrites.
4. Only when no rule expresses the intent, or the user asks for a new rule, author one (see
   below).

Do not jump to `build_reflex_mapping()` or `create_morphology()` for ordinary wiring.

## Core rules

Confirm availability with `describe_connectivity_rules()`; these are the usual core rules.

| Rule | Use for | Same dimensions? |
|---|---|---|
| `block_to_block` | One-to-one, topology-preserving copy | Yes |
| `projector` | Scale each axis by the ratio of the sizes: a larger source folds onto fewer voxels, a smaller one spreads over more | No |
| `centered_projector` | Align the centre voxels (even sizes use the lower middle voxel), keep each voxel's offset, drop what lands outside | No |
| `all_to_all` | Dense, fully connected coupling | No |
| `0-0-0_to_all` | Broadcast one starter voxel to every destination voxel | No |
| `all_to_0-0-0` | Funnel everything into the destination origin voxel | No |
| `lateral_+x`, `lateral_-x`, `lateral_+y`, `lateral_-y`, `lateral_+z`, `lateral_-z` | Shift activity one step along an axis; the last voxel has no target, nothing wraps (chains, CPG steps) | Yes |
| `transpose_xy`, `transpose_xz`, `transpose_yz` | A projector that reads the source with two axes exchanged. Not a plain swap and not for same-size areas only: the destination keeps its own shape, so each axis is also scaled to fit it, and one source voxel can reach several destination voxels | No |
| `rotator_z` | Each source XY voxel reaches every destination Z layer, rotated about the XY centre from -90 degrees (first layer) to +90 (last). Needs a destination with depth above 1 (depth 1 is the identity); a rotation outside the grid is dropped for that layer | Source depth is ignored; destination depth sets the angles |
| `tile` | Source larger than the destination (by voxel count): fold it onto the destination tile by tile. Otherwise copy it across the destination. The genome's `src_seed` and `src_pattern` are ignored | No |
| `sweeper` | Each source voxel to the next destination voxel: along x, then the next row, then the next layer; the last voxel has none | No |
| `first_to_last`, `last_to_first` | Source voxel 0,0,0 to the highest destination voxel, or the highest source voxel to destination 0,0,0 | No |

For downsizing a large input with `projector` (threshold and size choice), see [memory-design.md](memory-design.md) "Memory areas are the learning mechanism for recognition".
| `bitmask_encoder_x/y/z`, `bitmask_decoder_x/y/z` | Encoder: source voxel i along the axis is bit i (most significant first) and reaches every destination position with that bit set, so 3 source bits need 8 destination voxels. Decoder: the reverse | No |
| `randomizer`, `lateral_pairs_x` | Named in genomes but not implemented in feagi-core: a rule using them silently creates 0 synapses. Do not use | n/a |
| `episodic_memory` | Feed a memory area so it forms memory neurons. FEAGI also writes it, non-plastic, as the generated memory-to-twin recall edge | No |
| `associative_memory` | STDP association from a memory area to any ordinary area other than its own twin | No |
| `memory_replay` | Legacy. FEAGI replaces it with `episodic_memory` on the memory-to-twin pair; do not wire it | No |

## Mapping rule fields

Used by `update_cortical_mapping(src_area, dst_area, mapping_rules)`:

```json
{
  "morphology_id": "block_to_block",
  "morphology_scalar": [1, 1, 1],
  "postSynapticCurrent_multiplier": 1,
  "plasticity_flag": false,
  "plasticity_constant": 1,
  "ltp_multiplier": 1,
  "ltd_multiplier": 1,
  "plasticity_window": 0,
  "synaptic_delay_bursts": 1
}
```

- `postSynapticCurrent_multiplier`: synapse gain. The input a neuron receives is source PSP x multiplier, and the multiplier can be fractional. Negative values inhibit. The alias `psc_multiplier` was dropped on save before the feagi-core fix; it is now normalized, but write the full key.
  `apply_connectivity_rule()` and `build_reflex_mapping()` truncate fractions (0.5 becomes 0,
  which silences the edge), so balance excitation with destination thresholds instead.
- `morphology_scalar`: stretches the pattern per axis.
- `synaptic_delay_bursts`: axonal delay in bursts, at least 1 (FEAGI rejects 0).
- Plasticity fields are covered in [memory-and-plasticity.md](memory-and-plasticity.md).
  `ltp_multiplier` and `ltd_multiplier` are 8-bit signed (-128 to 127).

`update_cortical_mapping()` replaces the rules on that edge with the list you pass. Read the
current rules first with `get_cortical_mapping()` and include any you want to keep.

## Custom rules and the pattern language

A custom rule (morphology) has one of four types (code-read, `MorphologyType`):

- `patterns`: per-axis source filter and destination expansion, below.
- `vectors`: a list of `[dx, dy, dz]` offsets; each source voxel connects to `src + offset`
  (times the mapping's `scalar`). An offset that leaves the destination makes no synapse;
  nothing wraps. `[0, 0, 0]` is identity. Use it for uniform shifts, not as a list of pairs.
- `composite`: a source seed, a source pattern, and a second rule that maps from there.
- `functions`: a built-in algorithm chosen by name, with no editable parameters.

Pattern expansion: each axis expands on its own and the destinations are their Cartesian
product; relative tokens clamp to `[0, dimension)` (edge neurons get fewer targets); several
rows union; an inverted range (`98..1`) matches nothing.

A custom `patterns` rule is a list of `[src_x, src_y, src_z] -> [dst_x, dst_y, dst_z]` rows.
Tokens per axis:

| Token | Meaning |
|---|---|
| `*` | Every coordinate on this axis |
| `N` | Exactly coordinate N |
| `N..M` | N through M inclusive |
| `?` | Same coordinate as the source neuron |
| `!` | Every coordinate except the source's |
| `?+` / `?-` | All coordinates greater / less than the source |
| `?+=` / `?-=` | Same, inclusive |
| `?+N` / `?-N` | Exactly source plus / minus N |
| `?-A:?+B` | Source minus A through source plus B |

Constraints:

- On the source side only `*`, exact integers, and `N..M` filter which neurons the row
  applies to. `?`, `!`, and relative tokens do not filter.
- Never send an unknown token, or a plain number as a string (`"5"`; send `5`). The API
  currently accepts such a `patterns` rule but stores it without patterns, so the mapping
  silently grows zero synapses (code-read). Check the synapse count after every new rule.
  There is no modulo or even/odd filter.
- Never enumerate exact voxel pairs for a regular transform. Express it with `*`, `?`, and
  `?+N`. The server rejects enumerated dumps that share one offset.

Authoring flow:

1. `propose_connectivity_rule()` with the intent (and area IDs or dimensions). Use its
   `reuse` rule if set; otherwise take its `custom` patterns unchanged.
2. Either `create_morphology()` then `update_cortical_mapping()`, or
   `build_reflex_mapping(src_area_id, dst_area_id, morphology_name, voxel_mappings, ...)` to do
   both in one call. Example `voxel_mappings`:

   ```json
   [
     {"src": ["*", "*", "*"], "dst": ["?", "?", "?"]},
     {"src": [3, "*", "*"], "dst": ["?", "?", 0]}
   ]
   ```

3. To change a live custom rule: `get_morphology(name)`, then `update_morphology()` with the
   compact form from its `judgment.compact_form`. `rename_morphology()` renames it everywhere.

## Positional servo outputs

On an absolute positional servo OPU (`opse`, subunit 0), X is the device channel, Y is 1, and
Z is command depth. The bin rule is FEAGI's own coder for the unit the controller registered,
so read it instead of assuming a direction: `convert_io_value(area, channel, bin=...)` (or
`fraction=...`) returns the decoded `fraction`, the coding `variant` and, when the channel
registers a `physical_range`, the physical value and unit. Measured on an unsigned linear
servo coding: z=0 decodes to the maximum fraction, and when several Z voxels fire FEAGI
averages them. The mean is over **distinct** voxels: several sources
firing the same voxel count once (measured once: a stance voxel fired by three areas
plus one offset voxel at z+9 decoded 4.5 bins, two offset voxels z+9 and z+18 decoded 9.0),
so N sources on one channel scale each offset by 1/(distinct voxels). Mapping a drive to high destination Z (for example
`?+17` on a depth-20 strip) produces about 0.05 of full scale. Select specific joints with an
exact source-X filter (`source_x_channels` in `propose_connectivity_rule()`); wildcarding every
muscle is refused. `send_motor_command()` handles this mapping for direct joint commands.
To see what already writes a channel and which paths inhibit it, use
`explain_motor_channel(opu_area, channel)`; `lint_motor_channels()` warns, with evidence, about
channels with no writer or several.

## Changing and removing wiring

- Append a rule: `apply_connectivity_rule()` or `build_reflex_mapping()` (default appends).
- Replace all rules on an edge: pass `replace_existing=True`, or call
  `update_cortical_mapping()` with the full new list.
- Remove an edge entirely: `delete_cortical_mapping(src_area, dst_area)`. Confirm first.
