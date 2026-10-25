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
   to see what exists.
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
| `projector` | Resample or project source space into destination space | No |
| `centered_projector` | Projection centered in the destination | No |
| `all_to_all` | Dense, fully connected coupling | No |
| `0-0-0_to_all` | Broadcast one starter voxel to every destination voxel | No |
| `all_to_0-0-0` | Funnel everything into the destination origin voxel | No |
| `lateral_+x`, `lateral_-x`, `lateral_+y`, `lateral_-y`, `lateral_+z`, `lateral_-z` | Shift activity one step along an axis (chains, rings, CPG steps) | Yes |
| `lateral_pairs_x` | Pairwise neighbors across X | Yes |
| `transpose_xy`, `transpose_xz`, `transpose_yz` | Swap axes | Yes |
| `rotator_z` | Rotate around Z | Yes |
| `tile` | Repeat a source pattern across destination tiles | No |
| `sweeper` | Sequential sweep through the destination | No |
| `first_to_last`, `last_to_first` | Route the first unit to the end, or the last to the start | No |
| `randomizer` | Random connectivity for decorrelation or exploration | No |
| `bitmask_encoder_x/y/z`, `bitmask_decoder_x/y/z` | Pack or unpack bitmask values along an axis | No |
| `episodic_memory` | Feed a memory area so it forms memory neurons | No |
| `associative_memory` | STDP association from a memory area | No |
| `memory_replay` | Only onto that memory area's own twin. Any other memory-to-ordinary link is `associative_memory` | No |

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

- `postSynapticCurrent_multiplier`: synapse gain, an integer. Negative values inhibit.
  `apply_connectivity_rule()` and `build_reflex_mapping()` truncate fractions (0.5 becomes 0,
  which silences the edge), so balance excitation with destination thresholds instead.
- `morphology_scalar`: stretches the pattern per axis.
- `synaptic_delay_bursts`: axonal delay in bursts, at least 1 (FEAGI rejects 0).
- Plasticity fields are covered in [memory-and-plasticity.md](memory-and-plasticity.md).
  `ltp_multiplier` and `ltd_multiplier` are 8-bit signed (-128 to 127).

`update_cortical_mapping()` replaces the rules on that edge with the list you pass. Read the
current rules first with `get_cortical_mapping()` and include any you want to keep.

## Custom rules and the pattern language

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
- Never send an unknown token: FEAGI treats unrecognized strings as `*` and silently
  over-connects. There is no modulo or even/odd filter.
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
Z is command depth. **`z=0` decodes to the maximum command** and `z=depth-1` to near zero.
When several Z voxels fire, FEAGI averages them and flips the result:
`value = 1 - mean(z) / (depth - 1)`. Mapping a drive to high destination Z (for example
`?+17` on a depth-20 strip) produces about 0.05 of full scale. Select specific joints with an
exact source-X filter (`source_x_channels` in `propose_connectivity_rule()`); wildcarding every
muscle is refused. `send_motor_command()` handles this mapping for direct joint commands.

## Changing and removing wiring

- Append a rule: `apply_connectivity_rule()` or `build_reflex_mapping()` (default appends).
- Replace all rules on an edge: pass `replace_existing=True`, or call
  `update_cortical_mapping()` with the full new list.
- Remove an edge entirely: `delete_cortical_mapping(src_area, dst_area)`. Confirm first.
