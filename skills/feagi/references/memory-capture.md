# Recording episodes: memory.capture and sequential_memory

A memory area normally learns fixed windows: each memory neuron is `temporal_depth` bursts of
its upstream. To learn a whole event of any length while something salient is happening, add
these three pieces to the memory area:

| Piece | Kind | What it does |
|---|---|---|
| `memory.capture` | area modulator on a memory area, magnitude 1..100 | While its driver's combined signal is > 0, the area is recording |
| `sequential_memory` | mapping from a memory area to itself, one per area | Holds the area's episode links; gate and gain modulators on it control episode replay |
| `capture_max_bursts` | memory-area property, in bursts | Longest piece of one episode; unset = 5 s at the FEAGI refresh rate. A set value is a burst count: rescale it when the refresh rate changes |

## What recording does

- **Episode:** the states the area encodes from live input during the recording, in order.
  - A held input counts as one state.
  - A silent burst does not end the episode.
  - Recalled or replayed states never join it.
- **Links:** each state links to the next one inside the `sequential_memory` loop. At the cap,
  the piece closes and the next piece starts at once, linked to the last.
- **Boost:** each recorded state's lifespan is boosted once per recording. The magnitude is
  the share of the gap to long-term that it closes; 100 makes the state long-term at once.
- **Episode neuron:** each piece gets one, in the same area, even a one-state piece.
  - Its identity is the ordered list of its states, so recording the same chain again
    reactivates it instead of creating a new one.
  - It fires when recording ends, so an `associative_memory` mapping can link the whole
    episode to another area.
  - It dies when any of its states dies; its states outlive it.
  - It becomes long-term only once all its states have.
- **Precedence:** `memory.freeze` beats capture (nothing is recorded). `memory.formation` at
  -100 beats capture (only states the area already knows join).
- **No loop mapping:** the boost and episode neurons still happen, but there are no links and
  no replay. `validate_genome` warns.
- **Lifetime:** links live and die with their memory neurons, under the normal short-term to
  long-term rules. There is no other limit.

## Replay

- **From a state:** a state recalled from outside starts a chain.
  - Each step follows the strongest next state: long-term beats short-term, then more lifespan
    left, then more reactivations, then the one that fired most recently.
  - Each state plays at most once per replay, and a replay lasts at most `capture_max_bursts`.
  - Each state writes its own frames to the twin, as usual.
  - A chain that completes an episode fires that episode's neuron.
- **From the episode neuron:** recalling it, for example through an `associative_memory`
  mapping from another area, replays its chain exactly.
- **One replay at a time per area:** while one runs, no other replay starts in that area,
  including ordinary twin echoes. Cues that arrive meanwhile are dropped. Live encoding and
  learning continue.
- **While the area records:** no new replay of any kind starts, so the twin is silent. A
  replay already running finishes.
- **Gate:** a closed `synaptic.gate`, or a `synaptic.transmission_gain` of -100, on the loop
  stops chains and stops episode neurons firing from replay.

## Recipe

1. Build the memory area with its episodic sources as usual ([memory-design.md](memory-design.md)).
2. Create the modulator: `create_modulator("<name>", {"type": "memory.capture",
   "magnitude_percent": <1..100>, ...})`, with the salience area as its driver (driver keys:
   [modulators.md](modulators.md)). Then `set_area_modulators(memory_area_id, [...])`. The
   call replaces the list, so keep the area's existing modulator ids in it.
3. Add a `sequential_memory` mapping from the memory area to itself.
4. Optionally set `capture_max_bursts` on the memory area.
5. Verify:
   - `list_memory_neurons()`: `kind` (state or episode) and `episode_members`;
   - `get_memory_area_runtime_config()`: `recording`, episode count and blocked replays;
   - `record_spikes()`: the `chain_recall` fire kind.

## Design notes

- The genome decides what is salient by wiring the driver from detectors it already has. The
  modulator is a generic gate, like `synaptic.reward`.
- The twin gets no replay while the area records, so a circuit that reads the twin sees
  nothing during the salient stretch.
- **Limits:**
  - There is no live recognition of an episode: the episode neuron does not fire when live
    input runs through its chain.
  - A replay cued from a state that revisits a state (A-B-A-C) stops at the repeat and never
    fires that episode's neuron.

Evidence: tested in feagi-core deterministic tests; not yet measured on a live brain.
