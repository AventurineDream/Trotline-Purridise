# NPC presence and game-time rotation

Ticket #5 implements §3 of the [approved contract](V3-QUEST-IMPLEMENTATION-CONTRACT.md).
The authoritative Drive contract remains unchanged.

A session exposes two immutable `state.npcs` actors for the active world: its
permanent host and one rotating NPC. Their positions come from the chart-checked
anchor table. The large chart labels them in blue; the minimap marks their sites.
The landing shop identifies the permanent supplier and remains available all day.
Grandmother's anchor is Briar Landing; Doc's narrative anchor stays at his marina,
separate from the existing Cedar landing shop and travel menu.

The saved `schedule_seed` defaults to integer 0. For each loaded lake, the ledger
stores `selection_day = max(0, floor(game_minutes / 1440))` and the daytime ID at
`pool[(schedule_seed + selection_day) % len(pool)]`:

- Briar: Elder Moss, Pip & Pebble, Willow, Silas.
- Cedar: Captain Maeve, Sparky, Quill, Dr. Alder, Patch.

Game minute 0 is 06:00. Selection rolls at 1440, 2880, etc., rather than at
midnight. Briar replaces the selected daytime actor with Master Cinder during
[20:00, 04:00); the same daytime actor returns at 04:00 until the next 06:00.
Cedar keeps its selected actor through the night.

The session refreshes after real game-clock advancement, on save, and when its
state or loaded lake changes. This covers Continue's offline catch-up, new games,
1x/12x ticks, menus that advance time, and lake travel. An unloaded lake retains
only its saved selection metadata. Returning computes the current interval
directly, without constructing its world while offscreen, replaying skipped
schedules, evaluating quests, or granting rewards. Fishing RNG is never used.
Runtime actors are not serialized; saved seed/day/ID reconstruct them.

`python -m unittest fishing.test_npcs fishing.test_narrative -v` exercises exact
night/dawn/day boundaries, both ordered pools, nondefault seeds, save/reload,
legacy saves, offline time, real session ticks, permanent landing shops and lake
travel. `npc_checks()` is called from the full software self-test, so the required
`gameplay-tests` CI job executes these regressions as well.

Hailing, branching dialogue, quest evaluation and rewards remain assigned to
subsequent roadmap tickets.
