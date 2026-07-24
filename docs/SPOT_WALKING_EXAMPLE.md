# Using FEAGI MCP with the Spot Walking Example

This guide demonstrates how to use FEAGI MCP to iteratively design, debug, and tune the Spot quadruped walking controller.

## Prerequisites

- FEAGI MCP installed and configured in Cursor
- FEAGI running at localhost:8000
- MuJoCo Spot controller running
- Spot walking genome loaded (see `/tmp/spot_walking_genome_v2.json`)

## Workflow: Debug Non-Moving Robot

### Problem Statement

You loaded the Spot walking genome, see lots of neuron activity in Brain Visualizer, but the robot isn't moving.

### Investigation with MCP

**Step 1: Verify System Health**

Ask Cursor:
> "Check FEAGI health and embodiment status"

The AI will call:
```python
health_check()
get_embodiment_status()
```

Expected output:
```
FEAGI is running with genome "Spot CPG Walking Controller v1.0"
Motor outputs: Spot_Joint_Control (opose0) with 12 devices
Controller should be connected
```

**Step 2: Check CPG Activity**

Ask:
> "Are the CPGs oscillating? Monitor CPG_Diagonal_A and CPG_Diagonal_B for 3 seconds"

AI calls:
```python
monitor_activity("cCPGa_", 3000)
monitor_activity("cCPGb_", 3000)
```

Possible findings:
- ✓ Both firing at ~5Hz with 180° phase offset → CPGs working
- ✗ No activity → CPGs not triggered
- ✗ Random firing → Not oscillating properly

**Step 3: Verify Signal Propagation**

Ask:
> "Trace the signal path from CPG_Diagonal_A to the motor output"

AI calls:
```python
trace_signal_path("cCPGa_", "opose0")
```

Expected path:
```
cCPGa_ → cHipFL → opose0
cCPGa_ → cHipRR → opose0
```

If no path found → Missing connections!

**Step 4: Inspect Hip Control Activity**

Ask:
> "Monitor Hip_FL activity and check its connectivity to CPG and OPU"

AI calls:
```python
monitor_activity("cHipFL", 2000)
get_connectivity("cCPGa_", "cHipFL")
get_connectivity("cHipFL", "opose0")
```

Findings:
- CPG → Hip connected ✓ → Hip should be active
- Hip → OPU connected ✓ → Motor commands should be generated
- Hip → OPU not connected ✗ → **This is the problem!**

**Step 5: Verify Motor Output**

Ask:
> "Is the motor output area (opose0) showing any activity?"

AI calls:
```python
monitor_activity("opose0", 2000)
```

If no activity:
- Signals aren't reaching the OPU
- Missing connection or wrong cortical ID

### Root Cause Analysis

Common issues and MCP tools to diagnose them:

| Problem | MCP Tool | What to Look For |
|---------|----------|------------------|
| CPGs not firing | `monitor_activity(cpg_id)` | Firing rate = 0 |
| CPGs not triggered | `get_area_parameters("cStart")` | Check if WalkStart exists |
| Phase not locked | `monitor_activity` both CPGs | Phase offset ≠ 180° |
| Signal not propagating | `trace_signal_path` | Path doesn't exist |
| Missing connections | `get_connectivity` | `connected: false` |
| Wrong OPU ID | `get_embodiment_status` | Mismatch between genome and controller |
| Motor values too small | `get_connectivity` → check weights | PSC multiplier too low |

### Fix and Verify

Once you identify the issue, fix the genome and verify:

```python
# 1. Download current genome
genome = download_genome()

# 2. Fix the issue (add connection, adjust parameter, etc.)
# [Modify genome JSON]

# 3. Validate before upload
validation = validate_genome(modified_genome)
# Check validation.issues == []

# 4. Upload
upload_genome(modified_genome)

# 5. Re-test
monitor_activity("cCPGa_", 2000)
trace_signal_path("cCPGa_", "opose0")
```

---

## Workflow: Design From Scratch

### Step 1: Analyze Requirements

Ask:
> "I need a walking controller for Spot. What cortical areas do I need?"

AI will outline:
- 2 CPGs for diagonal pairs
- 4 Hip control areas (one per leg)
- 1 Motor OPU (12 channels)
- 1 Trigger area

### Step 2: Download Baseline

AI calls:
```python
download_genome()
```

Uses existing genome as template for structure.

### Step 3: Design Circuit

AI designs genome with:
- Proper cortical IDs
- Correct dimensions
- Connection morphologies
- Initial parameter values

### Step 4: Validate

AI calls:
```python
validate_genome(new_design)
```

Catches:
- Missing required fields
- Invalid cortical IDs
- Undefined connections
- Structural issues

### Step 5: Upload and Test

AI calls:
```python
upload_genome(new_design)
list_cortical_areas()  # Verify upload
monitor_activity("cCPGa_", 2000)  # Check CPG
```

### Step 6: Iterate

If not working:
```python
get_connectivity("cCPGa_", "cHipFL")  # Verify connections
get_area_parameters("cCPGa_")  # Inspect parameters
trace_signal_path("cCPGa_", "opose0")  # Check full path
```

Adjust and re-upload until working.

---

## Workflow: Tune CPG Frequency

### Problem: Robot walking too fast/slow

**Step 1: Measure Current Frequency**

> "What's the current CPG oscillation frequency?"

```python
activity = monitor_activity("cCPGa_", 3000)
# Returns: firing_rate = 8.0 Hz (too fast!)
```

**Step 2: Identify Parameter to Tune**

> "Show me the leak coefficient for CPG_Diagonal_A"

```python
params = get_area_parameters("cCPGa_")
# Returns: leak_c-f = 24.0 (high value → fast oscillation)
```

**Step 3: Calculate Adjustment**

AI determines:
- Target: 5 Hz
- Current: 8 Hz  
- Leak is too high
- Reduce to ~18.0 for 5Hz

**Step 4: Apply and Verify**

```python
genome = download_genome()
# [Modify leak_c-f: 24.0 → 18.0]
upload_genome(modified)
monitor_activity("cCPGa_", 3000)
# Verify: firing_rate = 5.2 Hz ✓
```

---

## Workflow: Strengthen Weak Movement

### Problem: Robot moves but steps are too small

**Step 1: Check Motor Output Strength**

> "What PSC multipliers are used from Hip to OPU?"

```python
conn = get_connectivity("cHipFL", "opose0")
# Returns: postSynapticCurrent_multiplier = 15.0 (weak)
```

**Step 2: Increase Connection Strength**

AI modifies genome:
```python
# Change PSC multiplier: 15.0 → 25.0
upload_genome(modified)
```

**Step 3: Verify**

```python
get_connectivity("cHipFL", "opose0")
# Confirm: weight now 25.0
monitor_activity("opose0", 2000)
# Check: increased firing intensity
```

---

## Workflow: Add Sensorimotor Feedback

### Extension: Add balance control

**Step 1: Check Existing Sensors**

> "What sensory inputs are available?"

```python
status = get_embodiment_status()
# Shows: Joint_Pos_Sensor (iipro0) with 24 channels
```

**Step 2: Design Feedback Loop**

AI designs:
1. Balance error computer
2. Corrective commands
3. Integration with CPG output

**Step 3: Validate Topology**

```python
# After adding areas
get_connectivity("iipro0", "cBalCt")  # Sensor → Balance
get_connectivity("cBalCt", "opose0")  # Balance → Motor
trace_signal_path("iipro0", "opose0")  # Full loop
```

**Step 4: Upload and Test**

```python
upload_genome(with_feedback)
stimulate_area("cStart", [0, 0, 0], 1.0)
monitor_activity("cBalCt", 2000)
```

---

## Common Debugging Patterns

### Pattern 1: No Activity Anywhere

```python
health_check()  # FEAGI running?
list_cortical_areas()  # Genome loaded?
get_area_parameters("cStart")  # Trigger exists?
stimulate_area("cStart", [0, 0, 0], 1.0)  # Manual trigger
monitor_activity("cCPGa_", 1000)  # Did it start?
```

### Pattern 2: CPG Active, No Motor Output

```python
monitor_activity("cCPGa_", 1000)  # CPG working ✓
monitor_activity("cHipFL", 1000)  # Hip working?
monitor_activity("opose0", 1000)  # Motor output?
trace_signal_path("cCPGa_", "opose0")  # Path exists?
get_connectivity("cHipFL", "opose0")  # Connection exists?
```

### Pattern 3: Motor Output, No Robot Movement

This is embodiment-side issue, not genome:
```python
get_embodiment_status()  # Controller connected?
# Then check:
# - MuJoCo controller logs for [MOTOR-SNAPSHOT]
# - Cortical ID matches between genome OPU and controller registration
# - Device count matches (12 for Spot)
```

---

## Tips for Effective MCP Usage

### 1. Always Start with Health Check
Every session:
```
"Check FEAGI health and show current genome"
```

### 2. Work Top-Down
```
System level:   health_check, list_cortical_areas
Circuit level:  get_connectivity, trace_signal_path
Neuron level:   monitor_activity, get_area_parameters
```

### 3. Verify After Every Change
```
upload_genome(modified)
→ list_cortical_areas()  # Confirm upload
→ monitor_activity(...)   # Verify behavior
```

### 4. Use Path Tracing for Complex Circuits
```
trace_signal_path(input, output)  # Full path in one call
# Instead of checking each hop manually
```

### 5. Validate Before Upload
```
validate_genome(new_design)
# Catches errors before upload fails
```

---

## What MCP Can't Do (Yet)

- **Real-time continuous monitoring** - Only snapshots
- **Live parameter tuning** - Must reload genome
- **Controller log inspection** - Can only check FEAGI side
- **Visual rendering** - Returns data, not images

For these, use:
- Brain Visualizer for continuous visualization
- Controller logs for embodiment debugging
- Spike Train Generator for complex stimulation patterns

---

## Next Steps

- See [TOOL_CATALOG.md](TOOL_CATALOG.md) for complete tool reference
- See [CIRCUIT_TEMPLATES.md](CIRCUIT_TEMPLATES.md) for design patterns
- See [FAQ.md](FAQ.md) for troubleshooting

## Questions?

Join Discord: https://discord.gg/feagi
