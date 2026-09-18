# Connectivity rule judgment

`connectivity_rules.py` is the local (no HTTP) authoring policy for FEAGI
morphologies. MCP tools must consult it before `create_morphology`.

## Why this exists

Agents previously expanded regular transforms into hundreds of exact voxel
pairs (for example `babble_sit` as 220 x 3 coordinates). That ignores the
pattern language and, on PositionalServo OPUs, maps command to the wrong Z
(`z=0` is max; high Z plus averaging decodes to ~0.05).

## Required agent flow

1. `propose_connectivity_rule` (local judgment).
2. Reuse a core morphology when `reuse` is set.
3. Otherwise `create_morphology` with the returned `custom` payload unchanged.
4. `update_cortical_mapping` / `build_reflex_mapping`.
5. To rewrite a live rule: `get_morphology` (no parameters) then
   `update_morphology` with `judgment.compact_form`. Do not call
   `list_morphologies` for a single name.

`create_morphology`, `update_morphology`, and `build_reflex_mapping` reject
enumerated exact dumps that share one offset or a contiguous source-X filter,
and reject high dest Z on PositionalServo absolute areas.

## Pattern language

See `PATTERN_LANGUAGE` in the module and
`feagi-core/crates/feagi-brain-development/src/connectivity/pattern-connectivity-rules.md`.

Source-side `?` / `!` / relative offsets do not filter. `*`, exact integers,
and absolute ranges (`N..M`) do.

## Tests

- Unit: `feagi-mcp/tests/test_connectivity_rules.py`
- Client integration (mocked HTTP): `feagi-mcp/tests/test_circuit_design_tools.py`
