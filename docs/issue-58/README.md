# V1-30 evidence: roster v2 and the daily schedule

Captured on commit 8800814 with Mesa llvmpipe. There is no hardware GPU here. The design is in `docs/v1/06-IMPLEMENTATION-GUIDE.md`, "Implemented roster and schedule (V1-30)".

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| A property test over 10,000 seeds: every encounter appears in every 3-day span | `fishing.test_npcs.ScheduleProperties.test_every_encounter_appears_in_every_three_day_span_over_10000_seeds`. For every seed and all five lakes, it checks three 3-day spans that start anywhere in the calendar. Every span holds the lake's whole day pool and night pool, with three distinct day cats each day. |
| Pins are honored | `test_quests_pin_their_cats_with_an_extra_slot`: an active quest's `talk_to` cat and a ready quest's giver are present on a day the round-robin skips them, a night cat only at night, and the pin ends once the quest is completed. `test_quest_progress_refreshes_the_cast` shows the running session picking up a new pin. |
| Deterministic across reloads and lake switches | `test_save_reload_and_offline_refresh_are_deterministic_and_grant_nothing`, `test_lake_switches_do_not_change_either_lakes_schedule` and `test_the_schedule_is_a_pure_function_of_seed_lake_and_day`, plus `test_narrative`'s ledger checks across travel and offline time. `test_schedule_does_not_consume_rng_or_change_fishing` shows presence draws no RNG. |
| V3 schedule tests updated, migration documented | The V3 tests in `test_npcs`, `test_calendar`, `test_dialogue`, `test_lakes` and `test_narrative` now assert the new rule. `test_v3_day_selection_migrates_for_its_own_day` loads a V3 save's day cat. The migration is in the guide section above. |

## A sample week

`python -c` over `fishing.npcs` for seed 20261029 (days 0–3). Hosts are always present and are not listed.

| Lake | Day 0 | Day 1 | Day 2 | Day 3 | Nights 0–3 |
| --- | --- | --- | --- | --- | --- |
| Briar | Silas, Pip & Pebble, Marigold | Biscuit, Old Gus, Willow | Elder Moss, Silas, Pip & Pebble | Marigold, Biscuit, Old Gus | Master Cinder every night |
| Cedar | Captain Maeve, Dr. Alder, Kit | Belle Pecan, Sparky, Patch | Quill, Captain Maeve, Dr. Alder | Kit, Belle Pecan, Sparky | Señora Luz, Hank Mudpaw, alternating |
| Flathead | Mitzi, Dakota, Ingrid | Willa Larch, Freya, Bramble | Bjorn, Mitzi, Dakota | Ingrid, Willa Larch, Freya | Elk-Ears Eli, Torvald |
| Crater | Juno, Ashby, Ember | Basalt Bea, Mist, Ignis | Tamsin, Juno, Ashby | Ember, Basalt Bea, Mist | Nyx, Fumi |
| Nebula | Comet, Nebula-Paws, Rigel | Selene, Andi, Lyra | Vega, Comet, Nebula-Paws | Rigel, Selene, Andi | Twinkle, Orion-Cat |

Each lake's seven day cats are walked three at a time, so days 0–2 and 1–3 each cover all seven.

## New encounters in the world

`python -m fishing --shots <dir> --cats` now captures the day's cast, so it shows encounters that V3 never scheduled:

- **`world-briar-marigold-close-native.png`, `world-briar-marigold-hail-software.png`:** Marigold on a log raft at `briar:open`.
- **`world-cedar-kit-close-native.png`, `world-cedar-kit-hail-software.png`:** Kit in a reed dugout at `cedar:ranger_flats`.

Every approach and hail frame in that capture has the cat's hail available.

## Numbers

- **Full-frame benchmark** (`--benchmark 1200`; both report `coverage_complete: true`). The files are `benchmark-software.json` and `benchmark-native.json`.

| Path | Render median | Full frame median (p95) | Peak RSS |
| --- | --- | --- | --- |
| Software | 229.02 ms | 329.09 (503.04) ms | 272.3 MiB |
| llvmpipe | 79.51 ms | 198.74 (364.06) ms | 515.0 MiB |

  V1-29's numbers on the same machine were 241.44 / 348.75 ms (software) and 82.83 / 204.56 ms (llvmpipe), so the schedule costs nothing measurable.
- **Cat capture.** 52 cats. Peak RSS was 404 MiB (native) and 269 MiB (software).

## Limitations

- **Mesa llvmpipe only, and no interactive play.**
- **The 39 cats without a V3 dialogue graph answer a hail with a wave toast.** Their quests are V1-31's.
