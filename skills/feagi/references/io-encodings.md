# I/O encodings: how values become voxels

How FEAGI's coders turn a sensor reading into IPU firing and OPU firing into a command. This
is the one home for encoding rules; other files link here. Evidence tags: *code-read* (read in
the `feagi-sensorimotor` coders and `feagi-structures` templates), *measured once*,
*unverified*. Get the live coding of a channel instead of assuming it:
`convert_io_value(area, channel, bin=...)` returns the variant, depth and decoded fraction,
using FEAGI's own coder and the agent's registration.

## Contents

- Shape of an I/O area
- Percentage codings along Z
- Reading rules shared by every percentage decoder
- Absolute and incremental
- Positional servo (absolute, incremental, speed)
- IMU areas
- Other templates

## Shape of an I/O area

- The template fixes the shape and which axes can be edited (an axis whose template minimum
  equals its maximum is locked). Device count repeats the per-device width along X; height and
  depth stay one device's size. Channel `c` of a `w`-wide device starts at `x = c * w`.
- The coding (data type, absolute or incremental, linear or fractional) is part of the
  cortical ID, so changing it changes the ID. Bind areas with `compute_io_cortical_id()` /
  `create_io_area_for_unit()` ([concepts.md](concepts.md#cortical-area-ids)).
- The controller must use the same map. A signed command does not match an unsigned area.
- Read template shapes and defaults with `get_cortical_template()` and the live area's
  dimensions, not from this file.

## Percentage codings along Z

`Z` is the channel depth, `z` the active index. *code-read*.

| Variant | Used when | Decode | Encode |
|---|---|---|---|
| Unsigned linear | unsigned, linear | `p = 1 - z/(Z-1)`: z 0 = 1.0, last z = 0.0 | one z = `min(floor((1-v)·Z), Z-1)` |
| Unsigned fractional | unsigned, fractional | `p = Σ 0.5^(z+1)`: z 0 = 1/2, z 1 = 1/4 ... | greedy bits; 0 fires the last z only (reads `0.5^Z`, not 0) |
| Signed along Z | signed, one value per channel (1D), linear | `v = 1 - 2·z/(Z-1)`: z 0 = +1, middle = 0, last z = -1 | one z = `floor((1-v)/2·(Z-1))` |
| Signed two-lobe | signed 2D/3D/4D, linear | two X columns per axis, `+` then `-`; each lobe `1 - z/Z`; `v = pos - neg` | the lobe of the sign; 0 fires the last z of both |
| Signed fractional | signed, fractional | two lobes, each `Σ 0.5^(z+1)`; `v = pos - neg` | greedy bits on the lobe of the sign |

- Linear: one obvious "value is here" neuron; a deeper area gives finer steps. Fractional
  (called exponential in some tools): a value is a small bit pattern of Z planes.
- Encoder and decoder differ by up to one bin: the linear encoder scales by `Z`, the unsigned
  decoder by `Z-1`. To pick the bin that decodes to a wanted value, use `convert_io_value`
  with `fraction` (it inverts the decoder), never `(1-v)·Z` by hand. *code-read*
- Two-lobe linear lobes divide by `Z`, not `Z-1`, so one lobe's last z reads `1/Z`, not 0.
  *code-read*

## Reading rules shared by every percentage decoder

*code-read* in the percentage and positional-servo decoders:

- Only `y = 0` is read, voxels with potential 0 are skipped, and z beyond the depth is ignored.
- Several active z on one channel: linear takes the **mean index** (so z 0 plus last z reads
  0.5), fractional **sums** the planes (a repeated z counts twice).
- Firing strength (potential) does not change a percentage value; position does.
- A silent channel is not decoded: the cached value **holds** and the channel is not marked
  changed. Whether the controller then holds or zeroes the actuator is controller-defined
  (*unverified* per controller; check with `get_motor_snapshot_last()`).

## Absolute and incremental

- **Absolute**: the value is the reading or command now.
- **Incremental**: a change. Where a template allows it, each axis gets an increase column
  (even X) and a decrease column (odd X). Each column decodes as an unsigned percentage
  magnitude, so low z = big step; net = increase - decrease.
- What happens to the net depends on the decoder: the positional servo integrates it into a
  held target (below); spatial and angular pointers emit it as a signed velocity per burst,
  with silent axes at 0. *code-read*

## Positional servo (absolute, incremental, speed)

A positional servo unit has three areas per device group: 0 absolute (`1 x 1 x Z` per
channel), 1 incremental (`2 x 1 x Z` per channel), and 2 speed (`1 x 1 x Z`). *code-read*
(`positional_servo_decoder.rs`, motor templates).

**Absolute area**: target `p = 1 - z/(Z-1)` (mean of active z). The controller maps `p` onto
the joint's range, `ctrl = lo + (hi - lo)·p`. Read `lo`/`hi` from `get_agent_joint_map()` or
the registration's `physical_range`; never assume them.

**Incremental area** (per channel `c`: `x = 2c` increase, `x = 2c+1` decrease):

1. Each column decodes `p = 1 - z/(Z-1)` (linear) or `Σ 0.5^(z+1)` (fractional). **Low z is a
   big step**, z = Z-1 a zero step.
2. `net = p_increase - p_decrease` (-1..1).
3. `target = clamp(cached_target + net · step_size, 0, 1)`.
4. The target is held between fires: a silent burst leaves it where it is. Each burst a column
   fires adds another step, so a column held on integrates until the stop.
5. When the absolute and incremental areas both fire on a channel in one burst, absolute wins.

`step_size` (*code-read*): the target-and-speed decoder uses the registration's
`incremental_step_size_0_1` (0 < s <= 1), read with `get_agent_device_registrations()`; the
older two-area decoder uses a fixed 0.002 per burst that the registration does not carry.
Per-fire joint motion is `net · step_size · (hi - lo)`. `convert_io_value()` on an incremental
servo area returns, per column, the signed `step_fraction` and `step_value` of one fire at that bin;
it reports the step as not registered for the two-area decoder.

**Speed area**: unsigned `1 - z/(Z-1)`, a per-channel speed limit. Before the first speed
command a silent speed area means full speed (1.0); after one, silence keeps the last speed,
including 0. A speed-only fire republishes the cached target with the new speed. *code-read*

Design consequences (general):

- An incremental servo is an integrator in the body: a joint keeps whatever target the last
  fires left. A circuit that only fires on error needs no hold loop, but it has no "home"
  unless something drives it there.
- Size the step from the body: pick the z (or step size) so one fire moves the joint less
  than the error the sensors can resolve, then check with a trace.

> **Worked example (measured once on one biped, derive your own):** joint range ±π/2, step
> size 1.0. One fire at z 508 moved the joint target about 0.012 rad; a fire at z 0 swung the
> joint from stop to stop in one burst.

## IMU areas

Both are signed two-lobe, linear by default: per value a `+` column then a `-` column, each
lobe `z = min(floor((1-|v|)·Z), Z-1)`, potential 1, so a reading of `v` fires one voxel on the
lobe of its sign. *code-read* (`percentage_encoder.rs`, `raw_imu.rs`, the templates).

| Area | Columns per channel (x from `c·w`) | Value |
|---|---|---|
| Raw IMU (`w` = 6), one area each for accelerometer, gyroscope, magnetometer | 0 `+X`, 1 `-X`, 2 `+Y`, 3 `-Y`, 4 `+Z`, 5 `-Z`, in the sensor's frame | `reading / cutoff`, clamped to -1..1 |
| Smart IMU (`w` = 8) | 0 `+w`, 1 `-w`, 2 `+x`, 3 `-x`, 4 `+y`, 5 `-y`, 6 `+z`, 7 `-z` | unit quaternion; `w` raw, `x, y, z` divided by the cutoff, clamped |

The controller sets the scale (*code-read* in the MuJoCo controller; other controllers
*unverified*): the cutoff comes from the mapping JSON's `sensor_cutoffs[<sensor name>]`, else
the model's sensor `cutoff`. With neither, Raw IMU divides by an adaptive running maximum
(`max(floor, 1.1 x decaying max |reading|)`), so the same reading lands on different z over
time; Smart IMU uses the raw components. Read the cutoffs before mapping z to an angle.

- A rotation by `θ` about one axis gives that vector component `sin(θ/2)`, `w = cos(θ/2)`. With
  cutoff `c` the component saturates at `θ = 2·asin(c)`: past that the lobe sits at z 0 and
  only `w` still changes. `w` is never scaled, so near upright it moves slowly.
- An accelerometer at rest reads the support force, about 1 g pointing up in its own frame
  (MuJoCo convention, general knowledge), so tilt shows on the X and Y columns.
- A burst with no new sample: the Raw IMU encoder clears that channel and emits nothing; the
  Smart IMU (percentage) encoder re-emits its last voxels. *code-read*, not measured. For gaps
  and `sensory_hold_last_frame` see [embodiment.md](embodiment.md).

> **Worked example (measured once on one biped, derive your own):** a still body pitched about
> 69°, quaternion (0.821, 0.037, 0.568, -0.054), cutoff 0.14, Z 10. Predicted and fired: x 0 z 1
> (`w`), x 2 z 7 (`x/c` = 0.26), x 4 z 0 (`y/c` saturated), x 7 z 6 (`z/c` = -0.39). The pitch
> lobe was pinned at z 0: this cutoff resolves only about ±16° of tilt.

## Other templates

*code-read* unless tagged. Depth and grid defaults are template defaults; read the live area.

| Template | Direction | Layout and value |
|---|---|---|
| Rotary motor | OPU | signed along Z, 1 column: z 0 full forward, middle stopped, last z full reverse |
| Count, Infrared, Proximity, Battery, Shock, Servo encoder | IPU/OPU | one unsigned percentage per channel, `1 x 1 x Z`; count is absolute only |
| Analog GPIO | IPU | X, Y pick the pin; each pin's percentage along Z (depth 1 cannot resolve a range) |
| Digital GPIO | IPU | boolean, `1 x 1 x 1`: firing = on |
| Raw IMU, Smart IMU | IPU | signed two-lobe, 6 and 8 X columns per channel: [IMU areas](#imu-areas) |
| Cartesian position | IPU | x, y, z unsigned on 3 X columns, absolute only; pairs with an absolute spatial pointer |
| Spatial pointer | OPU | absolute: 3 columns unsigned, all three must fire in one burst; incremental: 6 columns, signed velocity |
| Angular pointer | OPU | yaw, pitch, roll, -1..1. Absolute: 3 columns, low z = +1, high z = -1, all three must fire together; incremental: 6 columns |
| Gaze control | OPU | two areas: XY eccentricity (a 2D plane; mean position of firing neurons, `index/(span-1)`) and a modulation size percentage. A silent area keeps its value |
| Image enhancements | OPU | sliders diff, brightness, contrast; z 0 = top. Absolute 3 columns, incremental 6 (increase, decrease) |
| Simple vision (in and out), segmented vision | IPU/OPU | picture: X, Y pixel (origin top left), Z channel, potential = brightness. Segmented: nine pictures, high-resolution centre plus eight lower-resolution surrounds |
| Depth map | IPU | one layer, X, Y = canvas, potential = normalized depth (0 = no return) |
| Object segmentation | IPU/OPU | one layer, potential = (class + 1)/classes, 0 = unlabeled. Value planes: [value-planes-and-classifiers.md](value-planes-and-classifiers.md) |
| Pose estimation | OPU | Z = joint id; per Z layer the potential-weighted centroid of firing on X, Y is the joint (0..1), mean potential is confidence; an incoherent cluster = not detected |
| Audio in and out | IPU/OPU | X frequency column, Y phase step, potential = loudness on the registered dB floor and ceiling; potential 0 = silence. Output: the strongest phase row per column wins, and every decode is one tick (silence is written) |
| Text in and out | IPU/OPU | bits along Z at x 0, y 0, z 0 = highest bit, any potential > 0 sets a bit; integer = token id + 1, so a quiet frame is "no token" |
| Miscellaneous | IPU/OPU | no meaning assigned; the dimensions are the contract between brain and controller |

Before wiring a channel, read what drives it (`explain_motor_channel()`) and lint the OPU
(`lint_motor_channels()`). Joint and agent checks: [embodiment.md](embodiment.md).
