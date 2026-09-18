# Changelog

All notable changes to FEAGI MCP will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`propose_connectivity_rule`**: local authoring judgment for morphologies.
  Returns a reuse-or-compact ``*`` / ``?`` / ``?+N`` plan. Sit/motor subsets
  require ``source_x_channels``. Z offsets toward a PositionalServo absolute
  OPU are rejected (``z=0`` is max command).
- **`list_io_areas_compact`**: one-fetch IPU/OPU inventory with locally decoded
  4-char subtype, dimensions, per-device dimensions, ``dev_count``, and a
  ``dimension_dev_count_mismatch`` flag. Prefer this over
  ``list_ipu_areas_with_metadata`` (which labels encoder types ``unknown`` and
  repeats long capability text per area).
- **Circuit naming policy**: `create_brain_region` rejects placeholder titles
  (Autogen Circuit, Untitled, generic container words).
  `create_cortical_area` (CUSTOM/MEMORY) and `clone_cortical_area` (when a
  parent is set) refuse those parents and require a function-based circuit
  title (Sit, Walk CPG, OR Gate).
- **Absolute pattern range ``N..M``**: source-side contiguous channels collapse
  to one ``["1..98", "*", "*"]`` row instead of one exact-X row per channel.
- **`get_morphology`**: fetch one rule via
  ``POST /v1/morphology/morphology_properties``. Parameters are omitted by
  default; local ``judgment`` includes ``compact_form`` when rows collapse to
  ``N..M``. Use this instead of ``list_morphologies``.
- **`update_morphology`**: ``PUT /v1/morphology/morphology`` with the same
  compactness gate as ``create_morphology``. Rebuilds mappings that use the
  rule.
- **`monitor_activity` / `monitor_activity_batch` ``summary_only``** (default
  True): drop ``spike_history`` and ``firing_statistics.active_neurons``. Set
  False only when a raw spike dump is required.

### Changed
- **`create_morphology` / `build_reflex_mapping`** reject enumerated exact
  voxel dumps that share one offset, and reject high dest Z on PositionalServo
  absolute areas. ``recommend_connectivity_rules`` / ``describe_connectivity_rules``
  now attach ``pattern_language`` and a ``construction`` plan.
- **`list_cortical_areas` catalog rows** now include ``cortical_subtype``,
  ``cortical_dimensions_per_device``, and ``dev_count`` when the list payload
  has them.
- **`get_agent_device_registrations`** now reads the sibling
  ``device_registrations`` field on ``/v1/agent/capabilities/all``. Live FEAGI
  does not nest that blob under ``capabilities``, so musculoskeletal agents
  previously looked unregistered to MCP.
- **`get_agent_joint_map`** lists muscle/tendon ``PositionalServo`` channels
  that have an empty ``joint_name``. Identity comes from ``actuator_name`` /
  ``source_entity``, with ``channel_kind`` and ``channel_kind_counts``.
- **`send_motor_command`** matches ``actuator_name`` and ``source_entity``
  as well as ``joint_name``, and reports ambiguity instead of silently
  driving the first duplicate.

## [0.0.14] - 2026-09-12

### Added
- **`list_cortical_areas` / `list_cortical_area_names`**: optional `name_contains`,
  `cortical_id_contains`, `cortical_type`, and `limit` filters applied locally
  after one list fetch. `list_cortical_areas` returns compact catalog rows
  instead of full neuron-parameter records.

### Changed
- **Dependencies**: require `feagi-core>=2.1.51` (Python SDK from PyPI).

## [0.0.13] - 2026-09-06

### Added
- **`download_connectome`** / **`upload_connectome`**: MCP tools and `FeagiClient` methods for
  saving and restoring running NPU state via FEAGI connectome endpoints.
- **`list_memory_neurons`** / **`inspect_memory_neuron`**: Paginated memory-neuron listing and
  per-neuron lifecycle/synapse inspection.
- **`genome_artifact`**: Explicit encoding boundary for external `.genome` files (UTF-8 JSON
  codec); snapshot manager and upload paths use the shared artifact contract.

### Changed
- **Dependencies**: declare `feagi-core>=2.1.44` (Python SDK from PyPI).
- **Introspection discovery**: when `FEAGI_RUNTIME_ROOT` is set, search only that root
  (do not merge descriptors from `~/.feagi-staging` / `~/.feagi`).
- **Snapshots**: store standard genome artifacts in `<label>.genome` with snapshot metadata in
  `<label>.snapshot.json`.
- Release preparation: aligned package metadata and runtime version declarations to `0.0.13`
  across `pyproject.toml`, `src/feagi_mcp/__init__.py`, and `mcp-manifest.json`.

## [0.0.12] - 2026-09-02

### Changed
- Release preparation: aligned package metadata and runtime version declarations to `0.0.12`
  across `pyproject.toml`, `src/feagi_mcp/__init__.py`, and `mcp-manifest.json`.

## [0.0.11] - 2026-08-20

### Changed
- Release preparation: aligned package metadata and runtime version declarations to `0.0.11`
  across `pyproject.toml`, `src/feagi_mcp/__init__.py`, and `mcp-manifest.json`.

## [0.0.8] - 2026-08-05

### Added
- **`rename_morphology`**: MCP tool and `FeagiClient.rename_morphology` — rename custom
  connectivity rules via `PUT /v1/morphology/rename` with cortical mapping updates on the
  FEAGI server.

### Changed
- **Composer simulator packs**: HTTP clients follow redirects (308 from trailing-slash or
  host aliases) for list and bundle download requests.
- **Dependencies**: cap `mcp` at `<2.0.0` — MCP 2.x removes `mcp.server.fastmcp`, which
  this server still uses (CI/PyPI publish was resolving 2.0 and failing mypy/runtime).

## [0.0.7] - 2026-07-23

## [0.0.5] - 2026-06-17

### Added
- **`stimulate_area_batch`**: MCP tool and `FeagiClient.stimulate_area_batch` — fire many
  ``[x,y,z]`` voxels in one cortical area in a single ``manual_stimulation`` HTTP call
  (wraps existing `stimulate_areas`). Use for mirroring encoder patterns onto an OPU
  without one round trip per voxel.
- **`interpret_cortical_id`**: client-side decode of 8-byte cortical IDs (hex, byte 6/7 indices,
  mapping hints for BV unit_id, ROS deviceGroupId, Python motor XYZP). **`inspect_cortical_area`**
  now attaches ``cortical_id_interpretation`` on every response.
- **Composer shared simulator packs** (optional ``FEAGI_COMPOSER_BASE_URL``): tools
  ``composer_list_simulator_packs``, ``composer_get_simulator_pack_versions``,
  ``composer_get_simulator_pack_resolved``, ``composer_download_simulator_pack_bundle``;
  client module ``composer_simulator_packs.py`` and tests ``test_composer_simulator_packs.py``.

### Changed
- **`inspect_cortical_areas_minimal`**: includes optional `rate_modulated_leak` (homeostatic LIF leak) from the area record or `properties`; **`update_cortical_area`** / **FeagiClient** docstrings and **`docs/NEW_TOOLS.md`** document the same object shape and flat key `cx-hmlk-d`.
- **Documentation**: MCP tool and catalog text for **`GET /v1/cortical_area/voxel_neurons`** (`get_cortical_area_voxel_neurons`): when to use voxel/neuron inspection, incoming/outgoing synapses, and debugging; `list_brain_visualizer_operations`, `brain_visualizer_api`, `feagi_client.brain_visualizer_operation`, `README.md`, `docs/API_REFERENCE.md`, and `bv_operations` description.
- **Documentation**: Cortical area naming policy for MCP (no `Mcp` prefix; role/circuit-first names) in `docs/NEW_TOOLS.md` and tool/client docstrings.
- **`create_cortical_area`**: Added `brain_region_id` for CUSTOM/MEMORY areas (required by FEAGI `custom_cortical_area` API). The client returns a clear error if it is missing; may be supplied via `properties["brain_region_id"]` instead.
- **`create_cortical_area`**: For CUSTOM/MEMORY, MCP validates placement — anchors must be outside a **20-voxel** origin exclusion sphere (BV axis visibility) and **32 voxels** from existing area anchors (label overlap). Optional `skip_placement_validation=True` to bypass.

### Added (2026-03-30)
- **Semantic Metadata System**:
  - `area_metadata.py` - Comprehensive metadata for all cortical area types
  - `get_area_semantic_info` - Get detailed semantic info for any cortical area
  - `list_opu_areas_with_metadata` - List OPU areas with type, purpose, capabilities, devices
  - `list_ipu_areas_with_metadata` - List IPU areas with type, purpose, capabilities, devices
  - Enhanced `get_embodiment_status` to include semantic metadata in responses
- **Documentation**:
  - `docs/SEMANTIC_METADATA_ENHANCEMENT.md` - Complete enhancement guide
- **Test Coverage**:
  - `tests/test_area_metadata.py` - 6 new tests for metadata system
  - All metadata tests pass (6/6)

### Added (2026-03-29)
- **Agent Introspection Tools** (11 new tools total):
  - `get_agent_properties` - Get agent type, capabilities, version, connection info
  - `get_agent_device_registrations` - Inspect motor/sensor structure, group_ids, control modes
  - `list_opu_areas` - Filter only motor output areas
  - `list_ipu_areas` - Filter only sensory input areas
  - `get_registered_agents` - List all connected agents
- **Genome Editing Tools**:
  - `create_cortical_area` - Add OPU/IPU/CUSTOM/MEMORY areas programmatically
  - `update_cortical_area` - Modify cortical area properties
  - `delete_cortical_area` - Remove cortical areas
- **Connection Management Tools**:
  - `get_cortical_mapping` - Get connection configuration between two areas
  - `update_cortical_mapping` - Create/update connections with morphology rules
  - `delete_cortical_mapping` - Remove connections between areas
- **Documentation**:
  - `docs/NEW_TOOLS.md` - Comprehensive guide to new capabilities
  - `examples/fix_spot_walking_example.py` - Real-world usage example
- **Test Coverage**:
  - `tests/test_new_tools.py` - 11 new unit tests for all new tools
  - All tests pass (16/16)

### Changed
- Fixed unused argument warnings in `stimulate_area` (ruff ARG002)
- Formatted code with ruff for consistency

## [0.0.1] - 2026-03-31

### Added
- PyPI publication via GitHub Actions (`.github/workflows/publish_pypi_feagi_mcp.yml`), triggered when a **GitHub Release** is published (same pattern as `feagi-python-sdk`).
- Initial **0.0.1** release on PyPI.

### Changed
- **License**: Apache License 2.0 full text in `LICENSE`, aligned with `feagi-python-sdk`; `license-files` includes `LICENSE` in distributions.

## [Unreleased] (Previous)

### Added
- Initial MCP server implementation with FastMCP
- Core monitoring tools:
  - `monitor_activity` - Real-time neural activity observation
  - `get_connectivity` - Synaptic connection inspection
  - `trace_signal_path` - Multi-hop path tracing
  - `get_area_parameters` - Cortical area parameter retrieval
- Genome management tools:
  - `upload_genome` - Load neural architectures
  - `download_genome` - Retrieve current configuration
  - `validate_genome` - Pre-upload validation
  - `get_genome_info` - Metadata retrieval
- Embodiment tools:
  - `get_embodiment_status` - Controller connection status
  - `stimulate_area` - Direct neural stimulation
- Utility tools:
  - `health_check` - FEAGI connectivity verification
  - `list_cortical_areas` - Brain region enumeration
- Configuration management via environment variables
- Comprehensive documentation:
  - README with usage examples
  - API reference for all tools
  - Cursor integration guide
  - Circuit design templates
  - Development guide
  - Contributing guidelines
- Test suite with pytest
- Example scripts for circuit design workflows
- Type hints throughout for IDE support

### Known Limitations
- `monitor_activity` awaits FEAGI API implementation (returns placeholder)
- `stimulate_area` awaits FEAGI API implementation  
- `/v1/cortical_area/list` sometimes returns malformed JSON (fallback implemented)
- `/v1/embodiment/status` not yet available (fallback to genome analysis)

## [0.1.0] - 2026-03-29

### Added
- Initial release
- Core MCP server architecture
- FEAGI REST API client
- Basic tool set for observation and control
- Documentation and examples
