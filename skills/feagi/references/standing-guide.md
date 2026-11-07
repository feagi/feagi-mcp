# Make a biped stand: guide for any body

Part 1 of 2. Testing and verifying a standing brain: [standing-testing.md](standing-testing.md).

## Contents

- What a standing brain is made of
- Start from Brain Hub
- Order of work
- Best practices
- What to ask the user
- What is not established

Use this when a user has a bipedal robot (any model) and wants it to stand, or standing suddenly
fails. Mechanics of single circuits live in the pattern references
([genome-design-patterns.md](genome-design-patterns.md), [behavior-design.md](behavior-design.md));
this file is the playbook that ties them together.

## What a standing brain is made of

Standing is a closed loop: the body's tilt is sensed, a reflex turns it into corrective joint
commands, and the servos hold the corrected pose. In FEAGI that loop is a small set of blocks, each
doing one behavior and meeting the others only at named ports
([genome-design.md](genome-design.md) for the block rules):

| Block | Does | Robot-specific? |
|---|---|---|
| Body adapter | Maps this robot's joints, stance rows and sensor channels to the generic ports | Yes, the only one |
| Tilt sensing | Turns torso tilt (and tilt rate) into graded tilt ports, forward/back and left/right | No |
| Posture hold | Holds the rest stance through the servo rest and offset rows | No (rows come from the adapter) |
| Balance reflex | Tilt ports to correcting command ports with the correct sign; innate | No |
| Safety gate | Vetoes or limits commands in unsafe states | No |
| Contact sensing | Foot load to a stance flag; needed for single-support and walking | No |
| Gait generator | Rhythm (ring) gated by contact; only for walking | No |
| Learning or healing | Reward-gated gain tuning, homeostasis; optional, added last | No |

A new body needs a new adapter only. If a block must reach into another block's internals, redesign
the port instead.

Document each block's ports in one table before wiring: port name, meaning, encoding, timing, the
burst rate it assumes, and its dependencies. Field meanings and how a stranger uses the block:
[hub-block-datasheet.md](hub-block-datasheet.md).

## Start from Brain Hub

1. `search_brain_hub_genomes` with the task's terms (stand, balance, reflex, walking) before
   building anything. Open every match before relying on it: descriptions can be empty, and a title
   does not say which body the block was built for.
2. For a block that publishes a datasheet, read it with `get_block_datasheet`, design your adapter
   from its port table, and verify each port with `check_port_contract`.
3. Merge a block with `augment_genome_from_hub`, never by hand-copying, so the ancestry is
   recorded. Prefer reusing a block to building one.
4. Say plainly whether a hub block was tested on bodies other than its own. Unless its datasheet
   says so, treat the adapter as untested.
5. If nothing fits, build the missing block to the same rules (ports, own adapter, publishable
   alone) so it can be shared.

## Order of work

1. **Check the body can be balanced.** It needs a tilt sensor (a tilt angle and ideally a rate).
   Joints need servo steps fine enough to centre the stance and fast enough to catch a fall.
   If not, fix the embodiment first, and report it as embodiment configuration.
2. **Pick the burst rate from the body** (its fall time constant and the loop depth), never a
   default: [embodiment-burst-measuring.md](embodiment-burst-measuring.md).
3. **Measure the silent stance** with the motors holding the rest pose and no help: fall time and
   fall direction. Trim and sweep the stance against the fall direction until the silent fall time
   stops improving ([behavior-design.md](behavior-design.md), "Make the stance balance").
4. **Add the reflex** with the correct sign and prove by behavior that it carries the body.
5. **Fade the scaffolding.** Use Trainer support that starts high and steps down by success rate.
   Support acts on the torso only; it must never move the legs.
6. **Add on top, one block at a time:** contact sensing, then a gait, then learning or healing.
   After each, check the earlier blocks still behave as before.

## Best practices

- **Innate first.** Observed on the bodies tried so far: a sensed, correct-sign reflex closed
  standing, and learning added no unaided gain until it worked. Treat learning as tuning around a
  working reflex.
- **Expect a fixed pose to fail on weak servos.** Measured on one weak-servo biped, where a sensed
  feedback loop was needed; check your own body's silent stance before assuming it.
- **Prefer many small corrective steps to one big command.** On weak position servos a big step
  overshoots and topples the robot the other way. Grade force by how many small steps fire.
- **Keep robot knowledge in the adapter.** Joint names, stance rows and one-robot values stay there.
  Gain lives in the adapter's offset rows, not in a synaptic multiplier on a saturated command area.
- **The Trainer ends attempts, never Death.** Do not wire a fall, tilt or floor contact into Death;
  a fallen robot must stay in the scene so it can learn to get up.
- **Rescale burst-counted settings** (refractory, loops, windows, leak per burst) whenever the burst
  rate changes, in the same change.
- **Use run plans for sweeps** (gains, thresholds, stance values), not one builder stage per value.
- **Verify live state after any restart, restore or structural edit,** from the reloaded brain, not
  from the call that set it ([standing-testing.md](standing-testing.md)).
- **Stay bio-inspired.** Corrections come from what the body itself senses (tilt, tilt rate,
  contact). No simulator ground truth, solvers or planners as brain inputs.

## What to ask the user

One question at a time: which robot and simulator are registered; whether tilt and tilt rate
sensors exist and are mapped; whether foot contact or load sensing exists; whether the goal is
two-foot standing only, or one-foot standing and walking next; and whether a Hub block should be
reused or a new one built.

## What is not established

- Whether any Hub balance block works on a body other than the one it was built on.
- Whether learning can add robustness to a standing brain that already stands (designed, not run).
- A tilt-rate (D) channel, a dead zone around upright and a hip-versus-ankle split are design ideas
  without measured results here. Offer them as options, not as findings.
