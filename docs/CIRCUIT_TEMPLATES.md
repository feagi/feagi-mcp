# Circuit Templates for FEAGI

Pre-built neural circuit patterns that can be used as building blocks for complex behaviors.

## CPG (Central Pattern Generator)

### 5-Phase Ring Oscillator

```python
{
    "name": "CPG_Oscillator",
    "cortical_id": "cCPG_",
    "dimensions": [1, 1, 5],
    "neuron_properties": {
        "excitability": 80.0,
        "fire_threshold": 0.05,
        "leak_coefficient": 18.0,
        "post_synaptic_current": 12.0,
        "post_synaptic_current_max": 60.0,
        "refractory_period": 1
    },
    "self_connection": {
        "morphology": "cpg_ring",
        "weight": 12.0
    },
    "behavior": "Oscillates at ~5Hz, generates rhythmic output"
}
```

**Use for:**
- Walking/running gaits
- Flapping wings
- Swimming motions
- Breathing patterns

**Tuning:**
- Increase `leak_coefficient` (18→24) for faster oscillation
- Decrease `leak_coefficient` (18→12) for slower oscillation
- Adjust `weight` (12.0) for oscillation stability

---

## Phase-Locked CPG Pair

Two CPGs with mutual inhibition for coordinated movement.

```python
{
    "cpg_a": {
        "name": "CPG_Phase_A",
        "oscillation": "5Hz ring",
        "connections": {
            "to_cpg_b": {"morphology": "block_to_block", "weight": -4.0}
        }
    },
    "cpg_b": {
        "name": "CPG_Phase_B", 
        "oscillation": "5Hz ring",
        "connections": {
            "to_cpg_a": {"morphology": "block_to_block", "weight": -4.0}
        }
    },
    "behavior": "180° phase offset, ideal for diagonal gait pairs"
}
```

**Use for:**
- Quadruped trot gait (diagonal pairs)
- Bipedal walking (left/right alternation)
- Wing flapping (up/down coordination)

**Tuning:**
- Inhibition weight (-4.0): Control phase locking strength
- Too weak (<-2.0): CPGs may drift out of phase
- Too strong (>-6.0): CPGs may fail to oscillate

---

## Pattern-to-Motor Mapping

Translate CPG phases into joint commands.

```python
{
    "name": "Hip_Controller",
    "dimensions": [3, 1, 10],  # 3 joints (hip-x, hip-y, knee)
    "input": "CPG output (5-phase)",
    "morphologies": [
        {
            "name": "cpg_to_hip_x",
            "weight": 18.0,
            "effect": "Forward/backward swing"
        },
        {
            "name": "cpg_to_hip_y", 
            "weight": 20.0,
            "effect": "Lateral swing"
        },
        {
            "name": "cpg_to_knee",
            "weight": 22.0,
            "effect": "Knee flexion/extension"
        }
    ]
}
```

**Use for:**
- Limb control from CPG
- Multi-DOF joint coordination
- Trajectory generation

**Tuning:**
- Weight ratios control joint coordination
- Higher weight = larger range of motion
- Equal weights = uniform joint contribution

---

## Sensorimotor Feedback Loop

Integrate sensory feedback with motor control.

```python
{
    "sensor": {
        "name": "Joint_Position_IPU",
        "type": "IPU",
        "device_count": 12,
        "measures": "Current joint angles"
    },
    "error_computer": {
        "name": "Position_Error",
        "type": "CUSTOM",
        "dimensions": [12, 1, 10],
        "computes": "Target - Actual position"
    },
    "controller": {
        "name": "PID_Controller",
        "type": "CUSTOM",
        "applies": "Proportional correction"
    },
    "motor": {
        "name": "Joint_Control_OPU",
        "type": "OPU",
        "device_count": 12,
        "outputs": "Corrected joint commands"
    }
}
```

**Use for:**
- Closed-loop control
- Balance correction
- Precise positioning
- Adaptive movement

---

## Trigger/Gate Pattern

Start/stop behavior on command.

```python
{
    "trigger": {
        "name": "BehaviorTrigger",
        "dimensions": [1, 1, 1],
        "activation": "External stimulation or sensor event"
    },
    "gate": {
        "name": "MotorGate",
        "dimensions": [12, 1, 10],
        "function": "Multiply CPG output by trigger state",
        "behavior": "Enables/disables motor output"
    }
}
```

**Use for:**
- Manual behavior activation
- Conditional actions
- Safety interlocks
- Mode switching

---

## Morphology Patterns

### Ring (CPG)
```python
"cpg_ring": {
    "patterns": [
        [0, 0, 1],  # Phase N → Phase N+1
        [0, 0, 1],  # Wraps: Phase 4 → Phase 0
        ...
    ],
    "use": "Self-excitatory ring for oscillation"
}
```

### Block-to-Block (Inhibition)
```python
"block_to_block": {
    "patterns": [
        [0, 0, 0]  # All neurons in src → all in dst
    ],
    "weight": -4.0,  # Negative for inhibition
    "use": "Phase-locking between CPGs"
}
```

### Spatial Mapping
```python
"cpg_to_hip_x": {
    "patterns": [
        [0, 0, 0],  # Phase 0 → Joint 0 (hip-x)
        [0, 0, 0],  # Phase 1 → Joint 0
        ...         # All phases feed same joint
    ],
    "use": "Map CPG phases to specific joint"
}
```

## Parameter Ranges

### Neuron Properties
- `excitability`: 50.0 - 100.0 (typical: 80.0)
- `fire_threshold`: 0.01 - 0.1 (typical: 0.05)
- `leak_coefficient`: 10.0 - 30.0 (typical: 18.0)
- `post_synaptic_current`: 5.0 - 20.0 (typical: 12.0)
- `post_synaptic_current_max`: 30.0 - 100.0 (typical: 60.0)
- `refractory_period`: 1 - 5 (typical: 1)

### Connection Weights
- Excitatory: 5.0 - 30.0
- Inhibitory: -10.0 to -1.0
- CPG self-excitation: 10.0 - 15.0
- Motor commands: 15.0 - 25.0

## Common Patterns

### Walking (Quadruped)
```
CPG_A (FL+RR) ⇄ CPG_B (FR+RL)  [mutual inhibition]
    ↓               ↓
  Hip_FL/RR      Hip_FR/RL       [pattern mapping]
    ↓               ↓
     Motor_OPU                   [12 channels]
```

### Reaching (Arm)
```
Target_IPU → Trajectory_Planner → Joint_Commands → Arm_OPU
              ↑                        ↑
         Current_Position          Position_Error
```

### Balance Control
```
IMU_IPU → Balance_Error → Corrective_Commands → Leg_OPU
            ↑                    
       Desired_Pose
```

## Troubleshooting Circuit Design

| Problem | Possible Cause | Solution |
|---------|---------------|----------|
| CPG doesn't oscillate | Leak too low or PSC too low | Increase leak_coefficient or PSC |
| Oscillation too fast | Leak too high | Reduce leak_coefficient (18→12) |
| Phase drift | Inhibition too weak | Increase mutual inhibition weight |
| No motor output | Missing OPU connection | Check `get_connectivity(hip, opu)` |
| Weak movement | PSC multiplier too low | Increase connection weights |
| Erratic behavior | Too much excitability | Reduce excitability or add damping |

## Resources

- FEAGI Genome Structure: See `essential_genome.json`
- Neuron Morphologies: See `neuron_morphologies` in genome
- FEAGI Docs: https://feagi.org
- Research Papers: https://neuraville.com/research
