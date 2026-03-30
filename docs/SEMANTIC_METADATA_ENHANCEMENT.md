# MCP Enhancement: Semantic Cortical Area Metadata

## Overview
Enhanced the FEAGI MCP server to provide rich semantic information about cortical areas, making it much easier to understand what each area does, what devices it controls, and how it should be used.

## What Was Added

### 1. New Module: `area_metadata.py`
Created a comprehensive metadata system that maps cortical area types to their semantic information:

- **Category**: High-level classification (motor_control, vision_input, language, etc.)
- **Purpose**: Clear description of what the area does
- **Capabilities**: List of specific capabilities
- **Supported Devices**: Hardware/sensor types the area works with
- **Data Format**: Expected data format
- **Typical Use**: Common use cases and examples

### 2. Supported Area Types
The metadata system includes detailed information for:

**Output Areas (OPU):**
- `opse`: Servo motor control
- `omot`: General motor control
- `ogaz`: Gaze/camera control
- `oimg`: Image output
- `oseg`: Object segmentation output
- `onet`: Text/language output
- `ocnt`: Counter/control signals

**Input Areas (IPU):**
- `isvi`: Visual/camera input
- `iten`: Text/language input
- `icnt`: Counter/control input

### 3. New MCP Tools

#### `list_opu_areas_with_metadata()`
Returns OPU areas with full semantic metadata instead of just IDs.

**Example Response:**
```json
[
  {
    "id": "b21vdAUAAAA=",
    "area_type": "omot",
    "category": "motor_control",
    "purpose": "Controls general motor outputs and movement actuators",
    "capabilities": ["velocity_control", "direction_control"],
    "supported_devices": ["dc_motor", "stepper_motor", "velocity_controller"],
    "data_format": "velocity_commands",
    "typical_use": "Wheel motors, linear actuators, continuous rotation motors"
  }
]
```

#### `list_ipu_areas_with_metadata()`
Returns IPU areas with full semantic metadata.

#### `get_area_semantic_info(area_id: str)`
Get detailed semantic information about a specific cortical area by its ID.

### 4. Enhanced Existing Tools

#### `get_embodiment_status()`
Now includes semantic metadata for all OPU and IPU areas, enriching the response with:
- Area type and category
- Purpose description
- Capabilities list
- Supported devices
- Typical use cases

## Usage Examples

### Before Enhancement
```python
# Question: "What output areas do I have?"
areas = await list_opu_areas()
# Response: ["b21vdAUAAAA=", "b2dhegIAAAA=", ...]
# No information about what these areas control!
```

### After Enhancement
```python
# Question: "What output areas do I have and what do they control?"
areas = await list_opu_areas_with_metadata()
# Response includes full semantic information:
# - "omot" controls general motors (dc_motor, stepper_motor)
# - "ogaz" controls camera gaze (camera_gimbal, eye_actuator)
# - Clear purpose descriptions and use cases
```

### Getting Specific Area Info
```python
info = await get_area_semantic_info("b21vdAUAAAA=")
# Returns complete metadata for this specific area
```

## Benefits

1. **Improved Discoverability**: Users can immediately understand what each area does
2. **Better Documentation**: Self-documenting API responses
3. **Easier Integration**: Clear information about supported devices and data formats
4. **Reduced Confusion**: No more guessing from cryptic IDs or inferring from names
5. **Optimized for AI Assistants**: Semantic information helps AI tools answer questions accurately

## Testing

Created comprehensive test suite in `tests/test_area_metadata.py`:
- ✅ Area type extraction from encoded IDs
- ✅ Semantic info retrieval
- ✅ List enrichment
- ✅ Name and device count enrichment
- ✅ Metadata completeness validation

All tests pass successfully.

## Code Quality
- ✅ All ruff linting violations fixed
- ✅ Follows PEP8 style guidelines
- ✅ Type hints throughout
- ✅ Comprehensive docstrings

## Migration Guide

### Old Approach
```python
# Get OPU areas
opu_ids = await feagi.list_opu_areas()
# Then manually look up what each ID means
# or infer from names if available
```

### New Approach
```python
# Get OPU areas with metadata
opu_areas = await feagi.list_opu_areas_with_metadata()
# Each area includes type, purpose, capabilities, etc.
# Immediate understanding without extra lookups
```

## Future Enhancements

Potential additions:
1. Add more area types as they're introduced
2. Include parameter recommendations (optimal dimensions, neuron counts)
3. Add connection pattern suggestions (which areas typically connect)
4. Include performance characteristics (latency, throughput)

## Files Changed
- ✅ `src/feagi_mcp/area_metadata.py` (new)
- ✅ `src/feagi_mcp/feagi_client.py` (enhanced)
- ✅ `src/feagi_mcp/server.py` (new tools added)
- ✅ `tests/test_area_metadata.py` (new)
