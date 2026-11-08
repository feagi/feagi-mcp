# Genome design: plan the modules before building

Part 1 of 2: checklist, intake, modules, mechanisms, modulators. Efficiency budget, schematic, build order: [genome-design-budget.md](genome-design-budget.md).

## Contents

- Design checklist
- What a design produces
- Intake: goal, safety, facts
- Hub first
- Decompose into modules
- Choose the mechanism per module
- Orchestrate with modulators
- Standing: blocks and innate first

## Design checklist

Run all eleven for a multi-module genome, a new region or a new mechanism. One pattern goes
straight to "Build a circuit" (act with defaults).

1. **Goal:** one measurable outcome, the tool that reads it, a baseline taken. If no tool
   reads it, that is the first report.
2. **Safety:** list what must never happen (a fall wired to Death, servo range, runaway or
   silent population, reward wireheading, memory pool full) and the hard-wired veto for each.
3. **Facts:** embodiment, burst rate derived from the body, neuron and synapse budget.
4. **Hub first:** search_brain_hub_genomes, show only a match worth acting on, prefer augment_genome_from_hub, record ancestry.
5. **Blocks:** behaviors are Lego blocks for Brain Hub ("Decompose into modules"); one region per function, each with its own acceptance number and tool; a
   port contract row (shape, code, sign, latency, driver) per port.
6. **Mechanism:** innate wiring first; memory only for few patterns; plasticity only with a
   credit path; a learn/freeze gate.
7. **Modulators:** an influence table (output, modules affected, intended or not, lag in
   bursts); reward only from hard-wired detectors.
8. **Budget:** a row per mapping rule, events per burst, hops x burst period against the
   body's time constant; the smallest dimensions that work.
9. **Layout:** one Y per layer, one map step apart (about 120 voxels). A circuit that would sit inside that step of another title, a core area, or I/O goes on the next Y, not far away on X. Do not scale the step by the title length. See building-circuits "Placement".
10. **Document:** [genome-design-template.md](genome-design-template.md): fixed tables, an
    `<rule>, <sign>` schematic, a note per module, one exclusive question at most.
11. **Build:** one stage per module, snapshot first, black-box test after, stop after two
    failed checks; end with Bugs and Gaps and the cost line.

Detail: the sections below. Template: genome-design-template. Blocks: genome-design-patterns.
Worked designs and the adaptive patterns ship with Neurorobotics Studio (`behavior-playbooks` skill).

## What a design produces

Write one document before the first create call, in the order and with the exact table
headers of [genome-design-template.md](genome-design-template.md): intake, module table, port
contract table, per-rule budget table, influence table, layout table, schematic, stages table,
cost line. Length: about 6-9k characters per design when condensed, 12-18k in full.

Run the method for any new genome, any new region and any change of mechanism. It sits above
[behavior-design.md](behavior-design.md), which covers robot behaviors; a perception or dataset
genome needs the same steps.

## Intake: goal, safety, facts

- **Goal as a number.** "Walk" is not a goal; "forward displacement of at least X m in 20 s
  without a fall" is. Take the baseline now (Measure before you build in
  [lessons.md](lessons.md)). Task analysis for a body: [behavior-design.md](behavior-design.md).
- **Safety envelope.** Ask what the user must never see, and turn each answer into a hard-wired
  veto or limit in the design (pattern "Safety veto"). Check at least: falls never wired to
  Death (the Trainer ends attempts, see [embodiment.md](embodiment.md)); servo ranges and slew;
  runaway or silent populations (homeostasis, see [memory-plasticity-homeostatic.md](memory-plasticity-homeostatic.md));
  reward wired only from hard-wired detectors; memory pools that can fill (`memory_neuron_cap`).
- **Facts and budget.** Derive the burst rate from the body before sizing any burst-counted
  setting ([embodiment-burst-measuring.md](embodiment-burst-measuring.md#choosing-the-burst-rate)), and record the derivation
  in a notebook note. Mark each fact `read` or `assumed` in the template's facts table.
- **Read budget:** about six calls, plus one named read per fact the design depends on:
  `get_brain_regions()`, `list_io_areas_compact()`, `list_modulators()`,
  `get_agent_joint_map()` (when a body is registered), search_brain_hub_genomes,
  `get_runtime_metrics(measure_s=10)` (caps and engine speed, see "Efficiency budget" in genome-design-budget.md). Inspect
  an existing area only when the design changes it; never inspect another experiment's robot.

## Hub first

Reuse beats building. In Studio: search_brain_hub_genomes with the task's key terms, then show
only a match worth acting on. Same rules as [building-circuits.md](building-circuits.md) step 0.

| Judge a hit by | Meaning |
|---|---|
| Region inputs and outputs | does it fit an interface you need |
| Neuron and synapse counts | equal counts across unrelated genomes mean a seed with I/O areas, not a circuit (three Hub genomes shared 13,845 neurons and 400 synapses) |
| Tags and ancestry | what it was derived from |

Use augment_genome_from_hub into a scratch experiment, keep what matches a module row, cut the
rest, and note the ancestry in the design. Say "nothing fits" in one line when no hit matches a
module, and design that module from patterns. Region exports drop outgoing mappings and no tool
declares a region's ports, so re-create the glue mappings at assembly; the contract table below
is the workaround.

## Decompose into modules

Design behaviors as Lego blocks that others can pull from Brain Hub and combine. A block does one
behavior and connects only through documented ports; no mapping enters another block's internal
area, and a block that must quiet another uses a port that block offers. Robot rows and poses stay
in an adapter block, split per behavior when another behavior does not need them. A block is done
when it exports cleanly, loads without blocks it does not depend on, passes its check there, and
passes again combined.

One brain region per function, with declared inputs and outputs, so each can be tested as a
black box (sign, gain, lag; see [behavior-design.md](behavior-design.md)) and exported alone.
Layer the genome: sense, feature, decide, act, adapt. Name regions and areas per
[building-circuits.md](building-circuits.md#naming-policy).

Write one port-table row per port (headers in the template). Codes: **binary** (fires or not), **thermometer** (bins up to the value fire), **one-hot** (one
bin fires), **value plane** (`W x H x 1`, the potential is the value), **rate** (fires per
burst). Name the sign by effect on the body, not by joint angle. A module talks only to its
own ports; one adapter region knows the robot's areas.

## Choose the mechanism per module

| Mechanism | Use when | Never when | Cost | Verify with |
|---|---|---|---|---|
| Innate wiring (reflex, gate, CPG, feature detector) | the sign and gain can be measured | the direction must be discovered | synapses per rule | `probe_area_response()`, `record_spikes()` |
| Episodic memory area | pattern identity from a source with a few dozen patterns, `temporal_depth` 1 | the source is multi-column bins (1,475 patterns in 60 s never levelled); you need a sequence from one area (use a chain or hierarchy: [memory-design.md](memory-design.md)) | shared memory pool, `memory_neuron_cap` | `get_memory_area_runtime_config()` twice, 45 s apart |
| Plastic mapping (`stdp`, `rstdp`) | a credit path exists: something makes the destination fire in the window (teacher clamp, reflex, babble) and reward comes from a hard-wired detector | the reward pays for external support; a sign-fixed one-to-one path is expected to flip; the destination never fires in the window | every plastic synapse is visited each burst | `diagnose_mapping_plasticity()`, `watch_mapping_weights()` |
| Classifier | whole-pattern identity (one pattern per input area) | per-pixel or per-location output | memory neurons, one link per pattern-class pair | `inspect_classifier()` |
| Homeostasis (`rate_modulated_leak`) | hidden populations or areas with plastic inputs | value planes, motor outputs, modulator drivers, detectors | none in synapses | `get_area_parameters()` |

Credit paths and reward timing: [memory-plasticity-stdp.md](memory-plasticity-stdp.md#credit-assignment-read-before-training-with-reward).
Order: innate path first, measured; then learning against it ([behavior-design.md](behavior-design.md#innate-vs-learned)).
**Learn/freeze gating is part of the design:** decide which modulator driver freezes
which plastic rules for validate, test and live use (see "Orchestrate").

## Orchestrate with modulators

Types, magnitude semantics, driver timing and recipes: [modulators.md](modulators.md).

| Type | Orchestrates |
|---|---|
| `synaptic.learning_rate` | phases: -100% on a driver stops weight commits of the subscribed plastic rules |
| `synaptic.reward` | credit, from hard-wired detector areas only |
| `memory.formation` | salience: -100% stops new memory neurons forming |
| `synaptic.gate`, `synaptic.transmission_gain` | arbitration between modules: a gate conducts only while its driver fires |
| `neuro.firing_threshold`, `neuro.leak`, `neuro.firing_probability` | an area-wide state: excitability, integration time |

Write the template's influence table for every module output that feeds a modulator driver
or a shared command, naming the subscribed mapping.

A driver firing on burst t modulates burst t+1, for `effect_duration_bursts`, then rests
`rest_bursts`. Reward modulators on one rule sum (correct +100 with error -100 gives 0).
**Wireheading rule:** reward and punishment detectors take only hard-wired, non-plastic input;
FEAGI rejects genomes where learning can feed its own reward. Check subscribers with `modulator_usage()`.

## Standing: blocks and innate first

Standing is a closed loop from sensed tilt to corrective joint commands. Build it as blocks that
meet only at named ports:

| Block | Does | Body-specific |
|---|---|---|
| Body adapter | Maps this body's joints, stance rows and sensor channels to the generic ports | Yes, the only one |
| Tilt sensing | Torso tilt (and its rate) to graded tilt ports per axis | No |
| Posture hold | Holds the rest stance through the servo rest and offset rows | No, rows come from the adapter |
| Balance reflex | Tilt ports to correcting command ports, correct sign, innate | No |
| Safety gate | Vetoes or limits commands in unsafe states | No |
| Contact sensing | Foot load to a stance flag, for single support and walking | No |
| Gait generator | Rhythm gated by contact, walking only | No |
| Learning or healing | Reward-gated gain tuning, homeostasis, optional | No |

A new body needs a new adapter only. Document each block's ports (name, meaning, encoding, timing,
assumed burst rate, dependencies) as in [hub-block-datasheet.md](hub-block-datasheet.md).

**Innate first.** Get a sensed, correct-sign reflex holding the body, proven by behavior, before any
learning on top; treat learning as tuning around a working reflex (design rule, held on the bodies
tried so far). Add one block at a time and re-check the earlier ones. A fall is never wired to
Death. The full order of work and the standing test method ship with Neurorobotics Studio
(`behavior-playbooks` skill).
