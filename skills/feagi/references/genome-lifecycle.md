# Saving, loading, and merging genomes

## Contents

- What is saved where
- Snapshots (rollback points)
- Saving and exporting
- Loading and replacing
- Merging a genome into the running brain (amalgamation)

## What is saved where

| Artifact | Holds | Tools |
|---|---|---|
| Genome | Blueprint: regions, areas, parameters, mapping rules, morphologies, modulators | `save_genome_to_filesystem()`, `download_genome()`, `snapshot_genome()` |
| Region genome | One region subtree as a standalone genome | `download_region_genome(region_id)` |
| Connectome | The grown network, including learned weights | `download_connectome()`, `upload_connectome(file_path)` |

Tool edits change the running brain immediately. Nothing reaches disk until you save. A
genome save or snapshot does **not** keep learned weights or membrane potentials; save the
connectome when learning matters.

## Snapshots (rollback points)

Take a snapshot before any change that is hard to undo: replacing the genome, deleting areas
or mappings, or replacing mapping rules.

- `snapshot_genome(label, description)` saves the blueprint under a filename-safe label
  (letters, digits, `_`, `.`, `-`). It refuses to overwrite an existing label unless
  `overwrite=True`.
- `list_genome_snapshots()` lists them; `delete_genome_snapshot(label)` removes one.
- `restore_genome_snapshot(label)` replaces the running genome with the snapshot. FEAGI
  rebuilds runtime state from scratch, so learned weights are lost. Confirm first.

Snapshots live on the MCP server's machine (`FEAGI_MCP_SNAPSHOTS_DIR`, or the server's
`var/snapshots`), so they survive server restarts.

## Saving and exporting

- `save_genome_to_filesystem(file_path, genome_title)` saves the running genome the same way
  Brain Visualizer does. Without `file_path`, FEAGI uses its genome directory.
- `download_genome()` returns the full genome JSON. It is large; only fetch it when you need
  to read or transform the whole document.
- `download_region_genome(region_id)` exports one circuit as a self-contained genome
  (mappings leaving the region are dropped), ready to share or merge elsewhere.
- `download_connectome()` saves the connectome to disk and returns its `file_path`.

## Loading and replacing

All of these replace the running brain. Snapshot and confirm first.

- `load_genome_from_file(path)` loads a `.genome` file read by the MCP server. Prefer it to
  `upload_genome()` for files on disk: only the path crosses into the conversation.
- `upload_genome(genome_json)` uploads a genome document you have in hand. Check it first
  with `validate_genome(genome_json)`.
- `load_barebones_genome()` resets to a minimal genome with only core areas, as a clean start.
- `upload_connectome(file_path)` restores a saved connectome, including learned weights.

## Merging a genome into the running brain (amalgamation)

Amalgamation adds another genome (for example a circuit from Brain Hub or a region export)
into the running brain without replacing it.

Brain Hub genomes: merge them with Studio's `augment_genome_from_hub` (or
`replace_genome_from_hub` to replace the brain). These register the download and the
ancestry, including the exact release. `queue_amalgamation_by_payload` is for local files and
region exports only. It records no Hub download and no lineage.

1. `queue_amalgamation_by_payload(genome_json)` with the full genome document as a JSON
   string. It returns an `amalgamation_id`.
2. `health_check()` shows `amalgamation_pending` and `brain_regions_root`.
3. `confirm_amalgamation_destination(amalgamation_id, circuit_origin_x, circuit_origin_y,
   circuit_origin_z, brain_region_id)` places it, usually under the root region. The result
   lists `skipped_existing_areas`: areas that already existed (such as shared standard I/O),
   which is expected.
4. Inspect the new region with `get_region_circuit()` and wire it into the rest of the brain.

In Neurorobotics Studio, users can also merge Brain Hub genomes from the desktop app (same registration).
