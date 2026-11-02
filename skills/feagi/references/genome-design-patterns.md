# Genome design patterns: sensing, features, decisions, safety, output

Block catalog for [genome-design.md](genome-design.md). Memory, learning and orchestration
patterns: [genome-design-patterns-adaptive.md](genome-design-patterns-adaptive.md). Read one entry with
`genome-design-patterns#<heading>`.

Tags: **live** = built and verified in a live brain (stage named). **design** = unverified
live, from a design document (named); re-verify before relying on it. Synapse formulas use
N = positions (W x H), D = depth; cost model in [genome-design-budget.md](genome-design-budget.md#efficiency-budget).

## Contents

- Sensing: Value plane; Thermometer bins; Two-area one-hot; Pooling
- Features: Center-surround; Oriented pairs; Opponent channels
- Decisions: AND/OR gate; Onset pulse; Port; Ring CPG; Winner-take-all race; Pooled inhibition
- Safety: Safety veto
- Output: Servo rest and offset; Value passthrough to an OPU

## Sensing

### Value plane
- **Tag:** live (value-planes-and-classifiers.md).
- **When:** a graded value per position (class map, depth). **Shape:** `W x H x 1`; class c of K is potential (c+1)/K.
- **Synapses:** N per hop (`projector`, weight 1, PSC 1). **Pitfall:** never size Z by class count; flat PSP, leak, accumulation or fan-out division change the decoded class.
- **Verify:** `validate_magnitude_passthrough()`, `decode_class_map()`. Detail: [value-planes-and-classifiers.md](value-planes-and-classifiers.md).

### Thermometer bins
- **Tag:** live tool; design use (Cityscapes plan, `docs/cityscapes-segmentation-genome-plan.md`).
- **When:** synapses must specialize by range or class. **Shape:** `W x H x levels`; bin z fires when value >= (z+0.5)/levels; class c fires bins 0 to c. `expand_value_to_bins()`.
- **Synapses:** about N x levels (read the real count with `get_cortical_synapse_counts()`).
- **Pitfall:** keep the plane for transport and scoring; bins only where needed. **Verify:** `record_spikes()` on a known value.

### Two-area one-hot
- **Tag:** design (Cityscapes plan, block 4, unbuilt).
- **When:** a thermometer must become one bin per position on every burst. **Rules:** Thermo to OneHot, `[*,*,*]->[?,?,?]` +1 and `[*,*,*]->[?,?,?-1]` -1 at the same delay, so OneHot[z] = Thermo[z] - Thermo[z+1].
- **Synapses:** 2 x N x D. **Pitfall:** the in-area inhibit-the-bin-below chain alternates by parity under a re-driven thermometer.
- **Verify:** exactly one bin per position on every burst of a held sample (`record_spikes()`).

### Pooling
- **Tag:** design (Cityscapes plan, blocks 1 and 3).
- **When:** shrink a plane or take a neighborhood sum. **Rules:** `projector` with PSC = 1/block, or a k x k kernel (`?-2:?+2` on both axes) into a non-leaky integrator.
- **Synapses:** about N_src (projector); k^2 x N (kernel, 25 N for 5x5). **Pitfall:** class potentials cannot be averaged (two classes average to a third); pool in bin space with OR.
- **Verify:** `probe_area_response()` on one source voxel.

## Features

### Center-surround
- **Tag:** design (Cityscapes plan, block 2). **When:** contrast from a luminance plane.
- **Rules:** centre `[*,*,0]->[?,?,0]` excitatory, surround `?-1:?+1` on x and y inhibitory.
- **Synapses:** about (1 + k^2) x N, k = 3. **Pitfall:** weights floor at 0, so ship the complement plane (a tonic driver inhibited by the contrast plane marks flat regions).
- **Verify:** a bar on a flat field fires the contrast plane on its edge only (`record_spikes()`).

### Oriented pairs
- **Tag:** design (Cityscapes plan, block 2). **When:** edges by orientation.
- **Rules:** paired +/- one-pixel offsets across the edge (`?+1` and `?-1` on one axis, or diagonal pairs); both polarities sum into one plane per orientation.
- **Synapses:** 2 x N per orientation. **Pitfall:** one polarity only misses half the edges.
- **Verify:** a bar at each orientation fires its own plane at least 3x the others.

### Opponent channels
- **Tag:** design (Cityscapes plan, block 1). **When:** colour contrast from channel planes.
- **Rules:** `[*,*,0]->[?,?,0]` +1 and `[*,*,1]->[?,?,0]` -1 (and the reverse for the complement), rectified by the 0 floor, thresholded to binary.
- **Synapses:** 2 x N per opponent plane. **Pitfall:** build both signs; a negative result cannot be learned later.
- **Verify:** colour patches fire the expected plane (`record_spikes()`).

## Decisions

### AND/OR gate
- **Tag:** live (building-circuits.md worked examples). **When:** combine two binary signals.
- **Shape:** three `[1, 1, 1]` areas. OR: each input alone passes threshold. AND: threshold 1.5 x PSP, `neuron_mp_charge_accumulation` false. PSC is an integer; balance with thresholds.
- **Synapses:** 2. **Pitfall:** an AND of two sparse signals rarely fires; drive from one source and inhibit with the other.
- **Verify:** `probe_area_response()` per input, `run_stimulus_protocol()` for both together.

### Onset pulse
- **Tag:** live (walking S3b, S4). **When:** fire once when a held signal starts (seed a ring, detect load onset).
- **Rules:** gate to `Onset`; a one-burst `Delay` copy of the gate inhibits `Onset` from the next burst, inhibition >= gate input. Template `onset_pulse`.
- **Synapses:** 3. **Pitfall:** a self-holding gate cannot seed once; it refires the seed every burst.
- **Verify:** `record_spikes()`: one fire per onset, none while the gate holds.

### Port
- **Tag:** live (walking S2). **When:** a condition must drive a command for as long as it lasts.
- **Shape:** `[1,1,N]` leaky integrator, `block_to_block` self-mapping with s = PSP x PSC and threshold - input <= s < threshold (PSP 3, threshold 2.5, input 1: PSC 0.7). Template `port`.
- **Synapses:** N (self-hold) plus inputs. **Pitfall:** the membrane resets on every fire, so without self-hold it fires one burst in three; an input gap of one burst silences it (add a delay line).
- **Verify:** `record_spikes()` duty near 100% while the input bin holds, releasing one burst after.

### Ring CPG
- **Tag:** live (walking S3). **When:** a rhythm with a controllable period and a shifted second phase.
- **Rules:** `[1,1,N]` ring: self-hold, `lateral_+z` plus `last_to_first` excitation, `lateral_-z` plus `first_to_last` inhibition, drive by `0-0-0_to_all`, seed by an onset pulse; shifted readouts for anti-phase. Template `ring_cpg`.
- **Synapses:** about 4 x N (self, forward, backward, drive), plus N per readout. **Pitfall:** step time has no reliable formula; tonic drive must stay below leak x threshold per burst.
- **Verify:** `record_spikes()` period over 10 cycles; set `lateral_psc` from it.

### Winner-take-all race
- **Tag:** design, **unverified live** (Cityscapes plan, stage 3b; from code reading).
- **When:** exactly one bin of D must win per position. **Rules:** integrate-to-threshold race (charge accumulation on, first bin to cross fires, its inhibition resets the others, refractory holds the winner). The `!` pairwise form costs N x D x (D - 1).
- **Pitfall:** symmetric delayed lateral inhibition shifts every class equally, picks no maximum and can oscillate; the mask decoder sums ties into a third class.
- **Verify before any learning stage:** one bin fires on the last burst of a 12-burst hold in at least 95% of positions, and it is the larger input.

### Pooled inhibition
- **Tag:** design (Cityscapes plan, variant 5v, unbuilt). **When:** winner selection across D separate class areas.
- **Rules:** each `Class_k` to one pool area (+1), pool back to every `Class_k` (-1), one burst delayed.
- **Synapses:** 2 x N x D, against N x D x (D - 1) pairwise. **Pitfall:** the same winner check as the race applies.
- **Verify:** `run_stimulus_protocol()` with two inputs one PSC apart.

## Safety

### Safety veto
- **Tag:** design (walking genome design, stage 3, `Lift_Permit`, unbuilt).
- **When:** a learned or rhythmic command must be blocked on a sensed condition (a lift while tilted).
- **Rules:** a `[1,1,1]` permit area: the safe condition excites it (the other foot's stance), any tilt port above a bin inhibits it, a self-hold gives a release delay so it does not chatter at 200 Hz; rate ports may join as predicted tilt. It gates the command mappings and also inhibits the reset pulses so a cancelled step does not ping-pong the ring. The rhythm keeps running.
- **Synapses:** 1 per safe-condition source, 1 per veto source, 1 per gated command mapping; all non-plastic.
- **Pitfall:** place the veto on the output side so it also blocks learned commands; never subscribe it to a learning modulator.
- **Verify:** raise the veto input and confirm the gated command stays silent (`probe_area_response()`), then a held trial with `run_embodiment_trial`.

## Output

### Servo rest and offset
- **Tag:** design (walking S1b probe pending); template `servo_channel_two_rest` exists.
- **When:** two modules drive one positional servo channel. **Why:** the channel decodes the mean of distinct active voxels, so one shared voxel counts once.
- **Rules:** two rest voxels per channel (stance z+1 and z-1); each source's offset voxel is relative to its own rest voxel and inhibits only its own rest neuron. `build_stance_relative_mapping` builds offsets.
- **Synapses:** 2 rest neurons per channel, 1 inhibitory edge per source. **Pitfall:** a clamp warning on a leg channel fails the build; the Rest to OPU path is one hop longer, giving a one-burst blip.
- **Verify:** idle, each source alone and both decode within 0.5 bin of z, z+a, z+b, z+a+b.

### Value passthrough to an OPU
- **Tag:** live tools; the decoder shape is design (Cityscapes plan, block 6).
- **When:** a class or depth plane must reach `oseg` or another OPU unchanged.
- **Rules:** `wire_value_passthrough()`; for class bins, one rule per z, `[*,*,z]->[?,?,0]`, PSC (z+1)/K, destination threshold 0.01, no leak, no accumulation.
- **Synapses:** D x N for the bin decoder. **Pitfall:** two fired bins sum into a third class, so the winner stage gates this one.
- **Verify:** `validate_magnitude_passthrough()` with the class count, then `decode_class_map()`.
