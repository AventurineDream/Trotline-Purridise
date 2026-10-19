# Narrative save ledger (Ticket 2)

The existing save filename and top-level version `1` remain in use. The optional
`narrative_v1` object follows section 6 of the V3 implementation contract. A save
without it loads twelve available quests, no Ripples, seed `0`, no NPC selections,
no notes or claims, no Guardian sighting, and zero active-play minutes.

`State.narrative` is a `NarrativeState`. Each canonical quest ID maps to a
`QuestProgress` with `status`, `progress`, `accepted_game_minute` and `declined`.
Declining can be recorded while leaving status `available`. Progress stores finite
JSON values, including counters, namespaced zones, source line UUIDs and set-time
properties. The ledger also stores unique Ripple IDs, `schedule_seed`, paired
`day_npc_by_lake`/`schedule_day_by_lake` entries, `bot_notes`, `reward_claims`,
`guardian_seen`, and `active_play_game_minutes`.

Saved daytime NPC IDs are `elder_moss`, `pip_pebble`, `willow`, `silas` on Briar
and `captain_maeve`, `sparky`, `quill`, `dr_alder`, `patch` on Cedar. A selection
requires a valid ID for that lake and a non-negative integer day. This ticket
stores choices; Ticket 5 will compute them from game time using the saved seed.

Malformed optional fields fall back independently; valid fishing data and valid
ledger siblings survive. Unknown quest/Ripple IDs are ignored. A completed quest
counts as already claimed even in a ledger missing `reward_claims`; a saved claim
also restores completed status. `record_reward_claim` latches a ready quest once
and returns whether it changed. Ticket 8 uses that latch before paying the
validated cash reward and adding its unique Ripple. Quest cash does not alter
fish-sale totals, and hand-in leaves the livewell unchanged. Loading this ledger
never grants rewards.

Each deployment saves a UUID `line_id`. Legacy or invalid IDs receive a new UUID;
ambiguous duplicate IDs are all replaced without altering fishing state or
rebinding historical quest references. Migration emits no quest events. A new
deployment receives a new UUID; checks and rebaiting retain the original.

Bot saves the selected deployment UUID at launch. Loading an in-flight scout
restores that UUID only if the deployment still exists. Recall, reset, leash
return and pulling the target clear it. Legacy scouts keep their normal movement
and reports without a line association. Free-water scouts have no target UUID.

The active-play clock measures the actual positive game-clock delta in online
simulation and tow actions, including effective-rate limits and bulk advances.
Frozen updates and `catch_up` add no active-play minutes. Lake travel keeps the
same shared ledger; offscreen NPC selection and quest evaluation are later work.

Run the persistence regressions with `python -m unittest fishing.test_narrative -v`.
They also run through the existing `python -m fishing --selftest` entry point.
