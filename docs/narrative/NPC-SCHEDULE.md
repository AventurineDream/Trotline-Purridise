# NPC presence and game-time rotation

Presence is derived from the save by `fishing/npcs.py` (02 §11.3, V1-30). Nothing is
stored per lake beyond the saved `schedule_seed` and the legacy V3 pair described in
SAVE-LEDGER.md. This file describes the shipped build. The V3 contract's §3 model (one
rotating NPC per lake, `V3-QUEST-IMPLEMENTATION-CONTRACT.md`) is not what ships.

Each lake's host (Grandmother Whiskers, Doc Barnaby, Captain Huckleberry, Sora and
Professor Astra-9) stays at its landing anchor all day (`cast().hosts`).

A game day runs 06:00 to 06:00 on the game clock: game minute 0 is 06:00.

- **Day, 06:00–20:00:** three encounters per lake. They come from a seeded
  permutation of the lake's day pool, walked round-robin, so every encounter appears
  at least once in any three consecutive days (`day_encounters`).
- **Night, 20:00–04:00:** one encounter per lake, from the seeded night pool, which
  rotates by day (`night_encounter`).

Each lake has seven day encounters. Night pools: Briar has Master Cinder alone;
Cedar alternates Hank Mudpaw and Señora Luz; Crater, Flathead and Nebula each alternate
two cats (Nyx and Fumi; Torvald and Elk-Ears Eli; Orion-Cat and Twinkle).

Pinned cats: `pinned()` keeps present the `talk_to` cat of an active quest's current
step, and the giver of a quest that is ready for turn-in, whatever the pool says.

Travelers: Postmaster Pounce visits one unlocked lake a day, 08:00–16:00
(`pounce_lake`). Tinker Thistle moors at the player's lake on Saturdays, 10:00–18:00.
The Sunday cookout gathers a lake's cast on its landing piers (`_cookout_anchor`).

Presence depends only on the saved seed, the lake, the game day and the pins. It never
uses fishing RNG, evaluates quests or reads the computer clock, so offline catch-up and
lake travel give the same result.

`npc_checks()` (`fishing/test_npcs.py`) runs from `python -m fishing --selftest --software`.
`python -m unittest fishing.test_npcs fishing.test_narrative -v` runs the same
regressions directly.

Hailing and branching dialogue (DIALOGUE.md) and quest evaluation (`quests.py`) use
this presence list.
