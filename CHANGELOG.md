# Changelog

All notable changes to FEAGI MCP will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
