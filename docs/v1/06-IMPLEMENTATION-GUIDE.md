# Trotline Purridise — V1.0 Implementation Guide

*Supersedes `V1_0_ImplementationGuide.md` (Gemini). The game is Python 3.12 +
NumPy + ModernGL (OpenGL 3.3) with SDL2/SDL2_ttf and a CPU fallback renderer.
**Extend the existing modules. Do not create the parallel `survival.py`,
`pescapedia.py`, `npc.py` or `save_data.json` that the Gemini draft proposed.***

## 0. Ground rules for every ticket

1. **Existing behavior is a contract.** README features, `docs/narrative/*`, the V3
   quests and saves must keep working. Every PR runs
   `python -m unittest discover -v` and `python -m fishing --selftest --software`
   (the CI job `gameplay-tests`).
2. **Data, not code.** Species, baits, boats, NPCs, quests, dialogue and dishes
   live in validated JSON under `fishing/assets/content_v2/`. Code reads them
   through typed loaders. Numbers in `03-CONTENT-TABLES.md` are copied into data
   files, not hard-coded.
3. **Determinism.** All gameplay randomness uses the existing `sim.RNG` with the
   save seed. NPC schedules, Bot names, shinies and weather windows must be
   reproducible from the save.
4. **One lake in memory.** Only the active lake's terrain, foliage, NPC actors and
   textures are resident. Lake travel releases the previous renderer (existing
   benchmark check).
5. **Cozy by construction.** No code path may remove money, boats, lines, gear,
   book progress or rewards as a penalty. Old Salt effects are limited to the
   `02 §2.2` table.
6. **Docs travel with code.** A PR that changes a rule or number updates the
   matching file in `docs/v1/` in the same PR.

## 1. Module map

| Area | Existing module(s) | V1.0 work |
| --- | --- | --- |
| Game loop, input, menus | `game.py`, `platform.py`, `ui.py` | Pause-world rule, new keys, gamepad, haul view, book UI, kitchen tab |
| Simulation | `sim.py` (`State`, lines, catches, journal, tow) | Split bait, line capacity, catch-resolution order, shiny roll, legendary hook, buffs, Old Salt counters |
| Species and gear data | `data.py` | Loads species, baits, boats and dishes from `content_v2`; keeps the `SPECIES` / `SPECIES_BY_ID` / `BAIT_MATCH` / `ZONE_MATCH` API |
| Lakes and world | `lakes.py`, `world.py`, `lakegen.py`, `caldera.py`, `nebula.py`, `starlight.py`, `forest.py`, `shoreline.py`, `marina.py`, `anchors.py` | Three new procedural lakes, new zone archetypes, per-lake labels, thermocline, currents, reeds |
| Weather and ambience | `weather.py`, `ambient.py`, `life.py`, `audio.py` | New weather states, weather-window scheduler, per-lake ambience, shell chimes |
| Boats | `boat.py`, `boatmesh.py`, `boatfamilies.py`, `fleet.py`, `boatchecks.py`, `boatshots.py` | 24 boats from 8 parametric families, traits |
| Bot | `bot.py` | Name generator, shells, tools, factual/fallback barks |
| Narrative | `narrative.py`, `content.py`, `quests.py`, `dialogue.py`, `npcs.py`, `guardian.py` | Content v2 loader and validator, new objective types, 52-cat schedule, friendships, story chapters, letters, legendaries |
| Rendering | `glrender.py`, `render.py`, `software.py`, `shaders/*`, `sprites.py`, `raster.py` | Cat actors, fish models and cards, new lake palettes and skies, book UI art |
| Verification | `verify.py`, `expansionchecks.py`, `updatechecks.py`, `__main__.py` (`--selftest`, `--benchmark`, `--shots`) | Coverage for 5 lakes, 24 boats, 156 fish, 52 cats, memory budget |

New modules may be added where a concern is new: `book.py` (stages, shiny
tracker), `comfort.py` (naps, meals, buffs, Old Salt), `legendary.py`,
`calendar.py` (weekdays, Lake Days, weather windows), `lakegen.py` (procedural
lakes), `catmesh.py`, `fishmesh.py`, `gamepad.py`, `savepaths.py`. Keep the
existing flat package style.

## 2. Content v2 data files

```
fishing/assets/content_v2/
  species.json       # 144 rows (03 §1) + tier defaults
  legendaries.json   # 12 rows (03 §3)
  baits.json         # 9 baits + 8 recipe baits (03 §2)
  pantry.json        # 6 items (02 §4.2)
  dishes.json        # 10 dishes (03 §5)
  calendar.json      # validated Lake Days, weather reservations, cookout lines (V1-16)
  boats.json         # 24 boats + traits (03 §6)
  bot.json           # prefixes, shells, tools (03 §7)
  lakes.json         # 5 lakes: labels, zones, Lake Days, weather sets, palettes
  npcs.json          # 52 cats in 51 rows: role, lake, boat, appearance (V1-29),
                     # schedule slot, anchor and quest ids (V1-30)
  quests.json        # 96 new quests (15 story + 3 host + 34 quest A + 44 quest B);
                     # 108 in total with the 12 in narrative_v1.json. V1-31 ships
                     # the schema and engine; V1-32 authors Briar and Cedar's 24,
                     # V1-33 the other lakes and V1-34 the story
  dialogue/*.json    # one file per lake + story.json + bot.json + system.json
  book.json          # rumors, legendary stories, folk names
  ripples.json       # Ripples 11–44 (V1-32 ships 11–17)
  keepsakes.json     # 44, one per water-cat (V1-32 ships Briar and Cedar's 17)
```

V1-01 seeds the existing 36 species only. In its initial Briar/Cedar dataset,
the manifest records 36 Briar species and 30 Cedar species; the six Cedar
additions in `03 §1.3` and species for the later lakes arrive with their content
tickets. Each lake's declared `species_count` is checked against its species IDs
and the reciprocal lake memberships in `species.json`.

`fishing/assets/narrative_v1.json` stays as-is and is loaded **in addition**. The
current v2 gameplay loader handles the separate species, bait, boat, and lake
tables above; it does not load v2 narrative rows. When those narrative rows are
introduced, their loader must reject ids that collide with a v1 id unless the
row is marked `"extends": "<v1 id>"` (used for quest-B links and recopied V3
lines).

**Validation** (extend `content.py`, keep its collect-all-errors style): unique
ids; every reference resolves; numbers finite and in range; every lake has ≥ 2
legendaries; every legendary window ≥ 120 game min; every NPC's quests point to
its lake (cross-lake objectives allowed and listed explicitly); every dialogue
graph reachable and acyclic; every `[F]` line has a condition key and exactly
one declared fallback (`[U]` sibling, `silent` or `report`, `05 §0`); every
objective uses only the fields in `02 §12.3`; the 12 V3 quest ids appear only as
`extends` targets, never as new rows; v1 + v2 total 108 quests; species counts per lake match `03 §1` (36/36/34/34/34, total 144). Run
with `python -m fishing.content`.

## 3. Save v2

### 3.1 Location and migration

- New path: the platform user-data directory, via SDL `SDL_GetPrefPath("TrotLineSim",
  "TrotlinePurridise")`, file `save.json`. Keep `TrotLineSim` as the stable SDL
  organization identifier; the GitHub repository is `AventurineDream/Trotline-Purridise`.
  If SDL cannot provide that folder, use the install-local `saves/save.json` and
  show a toast. Override with `--save PATH` for tests.
- On first launch, if `saves/briar.json` (v1) exists and no v2 save does: copy it
  to `<prefpath>/backup/briar.v1.<timestamp>.json`, migrate, write v2, and leave
  the original untouched. Do not make another backup on later launches after a
  v2 save has been written. `--save PATH` selects an explicit save file for
  tests and portable runs; its backup folder is next to that file.
- If the active save is corrupt, try timestamped backups newest first. Before
  restoring the first valid backup, preserve the rejected bytes beside the save
  as `save.rejected.<timestamp>.json`; this file is not a load candidate. Show a
  toast after recovery. If no backup can be loaded, keep a rejected copy before
  starting a fresh game, since its later autosave can replace the active file.
  Treat invalid UTF-8 contents as corrupt data, and skip unreadable or malformed
  backup candidates while checking older backups.
  Refuse to load a save written by a newer game version and do not fall back to
  an older backup. Invalid known v2 values use their defaults; unknown fields
  remain available for a later compatible build.
- Writes stay atomic (temp file + rename) and keep the existing autosave cadence.

### 3.2 Schema

**One authority per domain.** Save v2 is the existing flat `State` JSON
(`sim.State.to_json`) with `"version": 2` and **one new key, `v2`**, that holds
only domains that didn't exist before. Existing fields stay where they are and
remain the single source of truth: money, lines, well, `journal` (catch count,
best, zone, bait, band), `narrative_v1` (quests, Ripples, reward claims,
schedule seed, Bot notes), `boat_id`, `owned_boats`, and the fuel and battery
fields. Nothing in `v2` duplicates them. Derived values (a book stage from a
journal count, a friendship state from quest status) are computed on load, never
stored. New V1.0 quests extend `narrative_v1`'s quest map and claim ledger with
their new ids, rather than starting a second ledger.

```json
{
  "version": 2,
  "...": "every existing v1 State field, unchanged names and meaning",
  "narrative_v1": { "...": "existing ledger; V1.0 quest ids and claims are added here" },
  "v2": {
    "mode": "cozy",
    "profile": {"bot_name": "Copper-316", "shell": "tin", "shells": ["tin"],
                "tools": [], "collar": {"stage": "none", "knot": null, "visible": true}},
    "needs": {"awake_h": 0.0, "since_meal_h": 0.0, "rested_until": null,
              "meal_hours": 24.0,
              "last_prompt_real_s": 0, "active_real_s": 0,
              "prompt_shown": false,
              "prompted": {"energy": false, "hunger": false},
              "snooze_until": {"energy": 0, "hunger": 0}},
    "buff": null,
    "pantry": {"herbs": 0, "pecan": 0, "huckleberries": 0,
               "salt": 0, "moonmilk": 0, "kibble": 0},
    "recipes": [], "dishes_known": [],
    "boat_extras": {"<boat id>": {"paint": {}}},
    "book": {"species": {"bluegill": {"found": [], "shiny": 0, "since_shiny": 3}},
             "tracked": null, "title": "fishypedia", "dream_clue": null},
    "legendaries": {"spillway_monster": {"records": [], "clues": ["teller"]}},
    "story": {"chapter": 0, "steps": {}, "scenes_seen": [], "pending_rewards": [],
              "scene_states": {}},
    "npcs": {"letters": [], "talk_days": {}},
    "keepsakes": [], "ripples_v2": [], "unlocks": [],
    "calendar": {"weather_windows": {}},
    "settings": {"text_size": 1, "haul_speed": "normal", "reduced_motion": false,
                  "key_bindings": {"throttle_up": "w", "throttle_down": "s",
                                   "steer_left": "a", "steer_right": "d",
                                   "idle": "shift", "idle_right": "rshift",
                                   "anchor": "space", "set_line": "f",
                                   "check_or_land": "e", "help": "h", "pause": "esc",
                                   "mute": "m", "hail": "c", "chart": "tab",
                                   "journal": "j", "livewell": "i", "bot": "b",
                                   "time_scale": "t", "sail": "q", "tow": "r",
                                   "new_game": "n", "dialogue_continue": "c",
                                   "catnap": "z", "bot_tool": "g", "galley": "k",
                                   "menu_up": "up", "menu_down": "down",
                                   "menu_left": "left", "menu_right": "right",
                                   "select": "return", "alternate_select": "space",
                                   "cancel": "esc"}},
    "reward_claims": {"story": [], "legendary_record": [], "book_stage_up": []}
  }
}
```

Book pages snapshot their attributed rumor in `book.species[id].heard`
(`text`, `teller`) on first access or catch. Authored rumors, folk names and
legendary stories are loaded from validated `content_v2/book.json`. Later content
edits cannot replace an existing snapshot. Each catch appends its zone, bait,
time band, lake, weight and game minute to `found`; new catches also carry an
optional `depth_m`, copied into that observation. Migrated observations retain
only the conditions actually present in the old journal. Legendary pages keep
an analogous `heard` story snapshot and append their first-hand `records`.

`narrative_v1.reward_claims` remains the single authority for quest rewards.
The v2 `reward_claims` lists hold keys for the new story, legendary-record and
book-stage-up rewards. A scene state is `pending` or `done`; pending scenes
replay from their start and do not grant rewards, while done scenes also appear
in `scenes_seen`. Unknown JSON keys at the save root, inside the v1 narrative
ledger, throughout `v2`, and in the boat ownership and fuel tank maps are kept
when a save is written. An unrecognized active boat ID runs as `jon` in this
build and remains serialized until a recognized boat is selected.

### 3.3 Rules

- **Migration of v1 → v2:** the migrated save, written to the new path (§3.1)
  while the v1 file stays untouched, is the v1 JSON with `version: 2` and a
  default `v2` object. The book stage is derived from the existing journal
  `count` (`02 §6.1`); `found` is seeded from the saved zone, bait and band. Boat
  fields are untouched (ids `jon`, `rowboat`, `sail`, `pontoon`). The Bot name comes from the schedule seed.
  Mode is `cozy`. Story chapter is 0, but the **prologue is marked seen** for any
  save with catches, so a veteran isn't asked to set a first line. Existing
  counts derive the book stage at 0/1/3/5/10 catches; a saved zone, bait and band
  seed the first `found` condition. The Bot name uses a private `sim.RNG` fork of the
  schedule seed: one of the twelve `bot.json` prefixes plus suffix 011–999.
  Existing valid assigned names survive; old out-of-range placeholders such as
  `Copper-000` are repaired once. Unlocks: Cedar is
  open. Guardian sightings carry over.
- Historical book thresholds are seeded into `book_stage_up` as
  `<species id>:<stage>` claim keys during migration or normalization. Loading
  never replays their toasts or grants their rewards. New catch transitions
  claim the next threshold and emit a `book.stage_up` event together; the toast
  lasts 3 seconds. Counts stay solely in the existing journal.
- **Exactly once:** each reward (quest, story, legendary record, book stage-up) has
  a claim key in the ledger. Credit and reward are written in the same save
  transaction. Re-entering a scene never re-grants. For v2 rewards, add the key
  before applying the credit, then save both changes together.
- **Interrupted scenes:** a story scene is either *pending* (it replays from its
  start on load, with no rewards granted yet) or *done*. Never half.
- **Unknown fields** are preserved on save (forward compatibility) and ignored on
  load.
- **Gemini schema errata:** the sample's `"current_boat_index": 2` indexed a
  two-element list (Python `IndexError`). Its `"skipper_name": "Barnaby"`
  contradicted the unnamed Skipper and collided with Doc Barnaby. Its tow formula
  `150 + 0.15 × value` is replaced by `02 §2.2`. Its QA checklist was pre-ticked
  without any test existing. Do not copy any of it.

## 4. Clock and pause

- One `Session.world_running()` predicate gates every simulation step: false in any
  menu, dialogue, book, chart, kitchen, pause, settings, scene, or while unfocused.
  The haul view runs its own presentation clock; the world is paused during it.
- Catnap calls the existing bulk-advance path (as the tow does) for 120 game
  minutes, with interpolated visuals. It counts as active play for quest timers.
- Offline catch-up stays as implemented (lines only).
- `comfort.py` owns mode checks, need thresholds, prompt throttling, meals,
  nap rewards and the tow quote. Effects read the current mode at use time;
  switching clears Energy/Hunger while retaining Rested, dream notes and the
  global prompt throttle. Entering Old Salt starts fresh counters.
- `State.advance` and `advance_bulk` advance Old Salt needs by the actual game
  delta. Offline `catch_up` does not. Rested uses
  `narrative.active_play_game_minutes`, including naps and tow time.
- `Session._start_catnap` validates eligibility, calls `State.catnap`, samples
  quest/NPC time, and saves the complete 120-minute advance before presenting a
  three-second skippable fade. A due forced nap anchors before the next driving
  step. Skipping or resuming a saved game cannot repeat the advance.
- Active real seconds accumulate only behind `Session.world_running()` and
  persist in `v2.needs.active_real_s`. `last_prompt_real_s` uses that clock;
  `prompted` and `snooze_until` keep per-need offer/snooze state. Menus, focus
  loss, the fade and time offline do not consume snooze time.
- `comfort.meal(v2)` is the kitchen/snack integration hook: clears hunger and
  its offer state without replacing a buff. `kitchen.snack` uses it; cooked
  dishes call `comfort.serve_dish`, replacing the single `v2.buff` slot.
- `remember_dream_clue` retains a dream in `book.species[id].dreams` while
  `book.dream_clue` holds the one unread lead. Reading its entry clears that
  slot; drawing pages is read-only and never rolls a lead.

### Pantry and picnic integration (V1-15)

- `pantry.json` holds the six items, host/lake stock, capacity and card price;
  `dishes.json` holds all ten effects. `baits.json` holds regional stock and
  eight parent-pair recipes. `data.py` exposes typed `PANTRY`, `DISHES`, and
  `BAIT_RECIPES`. `content.py` validates references, prices, durations/charges,
  food groups and recipe parents before building runtime objects.
- `kitchen.py` owns atomic purchases, teaching, cards, safe fish selection,
  dish cooking, bait cooking and snacks. Fish are selected from the livewell
  by food group and weight, excluding every protected class even when selected
  explicitly. Only accepted input consumes ingredients. Rendering is read-only.
- `kitchenview.py` provides scrolling landing/pantry rows, fish confirmation,
  and the two-second scene. `--shots` includes its gallery and warmed UI
  benchmark. Mouse hitboxes, keyboard and controller paths share the row model.
- A buff saves `dish`, `charges`, `until_active_minutes` and `day`; the validated
  dish supplies effect parameters. Timed buffs use
  `narrative.active_play_game_minutes`. Unknown future buff fields survive.
  Haul perks snapshot at the first raised hook (or direct/instant check), save
  remaining charges, and keep the third check's speed until it finishes.
- Pudding adds bonus credit on an affected check only once per tracked ordinary
  fish, using a saved `picnic_pity_credited` catch field. It does not reroll a
  hooked fish or change base shiny odds. The next catch honors an earned pity
  guarantee through the existing `roll_shiny` path.
- Meals save a finite `needs.meal_hours` threshold between 24 hours and the
  longest configured meal. Before resetting `since_meal_h`, `comfort.meal`
  keeps `max(new_meal_duration, previous_threshold - elapsed_since_meal)`.
  Normalization and slowdown queries retain fractional carryover, including
  through save/load; a snack or new dish cannot shorten Soup's 48-hour window.
  Extra pie dreams use `book.dream_queue`; the existing unread slot stays first.
- Bot scouting, fuel burn, software fog/buoys, GL fog/buoys and chart markers
  query the current effect. No fishing-rate modifier is added. The five legacy
  bait maps and 360 sampled base-rate tables have regression fingerprints.
- `weather_spot` finds current favorable nearby water; `weather_invitation`
  enforces the saved daily quota and optional tacos charge, stays silent when
  none is favorable, and saves a two-hour chart mark. The calendar ticket can
  call the same hook for automatic invitations.
- Host teaching reads the saved story cursor; card sales follow chapter
  completion. Future chapter/lake content supplies its hosts and food species
  through the same interfaces; no story progress is fabricated by the kitchen.

## 5. Simulation formulas

- **Thermocline:** `d(h) = base + amp·sin(2π(h − 15)/24) + weather_offset`, in
  metres, clamped to [3, 0.8·max_depth]. Flathead base 12, amp 3. Crater base 18,
  amp 4. Weather offset: fog/snow mist +1.5, clear −1.0. A cold-tagged species
  multiplier is 1.0 when `d ≤ hook_depth ≤ d+6`, else 0.35.
- **Currents (Nebula):** each `current` zone has a flow vector field (smooth noise,
  ≤ 0.5 m/game min). Each soaking line's anchor point integrates the flow (capped at
  60 m from its set point). The winch sets flow to 0 for the player's lines.
- **Shiny:** at catch creation, `shiny = rng.chance(1/64)`. If tracking this
  species and `since_shiny + 1 ≥ 50`, then shiny = true. Update `since_shiny`.
  `book.roll_shiny` uses `State.rng` once for each standard catch, including a
  pity catch. New counters start at zero, advance even while untracked, and
  reset on any shiny. Existing saved counters are retained. Legendary catches
  never roll. `Catch.shiny` persists through both hooks and the livewell; loading,
  checking and resolving catches never roll again. A hooked shiny saves
  `shiny_since_before` and its `shiny_observation` index on the catch, reserving
  the reset until Keep/Release. `confirm_shiny` awards Trophy credit and marks
  that observation once. If the fish gets away, `lose_shiny` restores its saved
  counter to the next pending shiny or adds it to the current counter. A newer
  confirmed observation supersedes that reservation. This preserves later
  progress regardless of hook traversal, resolution order, or reloads.
  Both spoilage and running over a line use `State._drop_hook_catch`, which
  refunds the reservation before clearing the hook.
  `book.set_shiny_target` enforces Verified status and saves one target in
  `v2.book.tracked`. `book.shiny_tracker` is a read-only presentation query.
  Ordinary journal counts and field notes retain their existing hook-time
  credit. Pending shinies receive Trophy credit only at Keep/Release. `Catch.value()`
  supplies the 3× bonus to both individual and bulk sales; Treasured still
  protects against bulk sale until explicitly unmarked.
  `State.mount_shiny_trophy(species_id, boat_id=...)` is the fleet integration
  hook: an owned boat must have `trophy_rail`; its cosmetic species list is saved
  at `v2.boat_extras[boat_id].shiny_trophies`. Existing four boats have no rail;
  the book displays recorded shinies now. Mounting is idempotent and consumes
  neither a fish nor a book record.
- **Legendary hook:** at haul resolution, if the line satisfies every requirement
  (`03 §3`) and was soaking at any moment inside the active window, the first hook
  that would have rolled any species instead becomes the legendary. Record, then
  release.
- **Weather windows:** `calendar.py` pre-plans each lake's weather for the next 7
  game days from the seed. The planner guarantees the single 3-game-day bound in
  `02 §3.6` / `03 §3`, then blends with the existing weather system.
- **Named areas and waypoints:** `lakes.json` defines circles or polygons with ids
  (`marked_pool`, `landing_edge`, `reed_edge_1..3`, `drift_buoy_1..3`,
  `practice_buoy_1..4`, `lamp_buoy_1..3`, `survey_marker`, `calm_reflection`, the
  three chapter-4 coves). Objectives reference them with `area_id` or
  `waypoint_ids`. Areas used by fishing objectives must contain legal line water
  (checked by the validator). The journal reads the plan
  to show the "next eligible window".
- **Line capacity:** `boat.lines` from `boats.json`. Setting a line checks the
  number of deployed lines against the active boat.
- **Split bait:** a `SetLine` stores `bait_sections: list[str]` (1–3) instead of one
  bait. Hook *i* uses `sections[i * n // hooks]`. Legacy lines load as one section.

## 6. Visual systems

All art is **procedural and generated at load**, as the game already does. No
large downloaded texture packs. Bake once per lake load, then keep only what the
current lake needs.

### 6.1 Lakes

- `lakegen.py` builds a heightmap + zone map + shoreline for Flathead, Crater and
  Nebula from authored parameters in `lakes.json`: outline control points, basin
  depth profile, islands, inlet channels, reef ridges, spring locations, reed beds
  and current lanes. Same output format as Briar and Cedar, so `world.py`, the
  chart, collisions and fishing reuse it.
- Target sizes: Flathead about 2.2× Briar's area (the biggest open water, with
  gusts). Crater: round, steep-walled, with the cinder isle 30% off center.
  Nebula: an irregular field of "lily-drift islands" over a dark void bed, with a
  visible depth gradient to deep violet.
- Per-lake **palette and sky:** sky gradients, sun and moon tint, fog color, water
  absorption/scatter coefficients and foliage set. Flathead: larch (gold in Larch
  Gold week) and spruce, snow-capped ridges. Crater: hemlock and whitebark pine on
  ash-grey rim walls, with an indigo absorption that's very clear. Nebula: no
  trees; floating crystal kelp, light-reeds, a nebula skybox, aurora curtains, and
  star reflections on water (implemented in V1-27; see below).
- **Weather visuals:** snow mist (falling flakes + low fog), caldera fog (dense
  layered fog that lifts from the rim down), aurora (animated curtains + water
  glow). All three are shader parameters on the existing weather blend.
- The software renderer gets simplified versions (flat palettes, fog color, no
  reflection detail) and must still be playable.

### 6.2 Cats (52) — `catmesh.py`

- **One shared parametric rig:** head, ears, muzzle, torso, arms, legs and tail
  built from deformed ellipsoids and swept tubes in NumPy, about 2.5k triangles at
  LOD0, 600 at LOD1, and an impostor sprite beyond 120 m.
- **Parameters per cat in `npcs.json`:** size, build, ear shape (pointed, folded,
  tufted, rounded), tail (long, bob, none: Manx, plume), coat pattern (solid,
  tabby, mackerel, calico, tortoiseshell, tuxedo, point, spotted, bicolor),
  colors, eye color, whisker length, and attire props from a shared kit (shawl,
  spectacles, oilskin, cap, parka, vest, goggles, life jacket, bandana, sweaters
  ×1–4, lantern, scarf).
- **Coat patterns** are evaluated in a fragment shader from object-space noise and
  masks (no per-cat textures). The software renderer uses per-vertex colors.
- **Animation:** vertex-shader procedural motion (breathing, tail sway, ear
  flicks, head turn toward the player within 40 m), plus 5 authored poses blended
  by weight: sit-fish, nap-curl, wave, paint/read/whittle (prop-driven), and stand
  at the helm.
- **Portraits:** each cat's portrait is rendered offscreen once per lake load from
  its model (3/4 view, warm rim light, paper-tone background) at 256×256 and
  shown in dialogue. The cache holds only the current lake's cats + hosts +
  travelers.
- **Skipper:** first-person paws (two hands with fur pattern from a fixed Skipper
  palette) on the tiller, oars and the line during the haul. A reflection of the
  Skipper's head silhouette in calm water at idle (reflection pass only).

### 6.3 Fish (156) — `fishmesh.py`

- **Parametric fish:** a body profile (length:depth ratio, back and belly curves),
  head shape, mouth, fins (dorsal count and shape, adipose, tail fork), barbels,
  scale pattern (plain, spots, bars, stripes, mottled, vermiculate), and palette.
  Defined per species in `species.json` (`look`), with family presets (catfish,
  bass, sunfish, trout, gar, sucker, minnow, pike, sculpin, eel, cosmic).
- **Haul mesh:** about 1.5k triangles, generated on demand and cached per lake
  (LRU, 64 entries).
- **Fish card illustration:** a 512×256 "field-guide watercolor" render: the fish
  mesh with a toon-ish paint shader, paper texture, soft edge bleed and a hand-ink
  outline, plus a shiny variant. Cards render on demand into an LRU cache of 48
  entries (≈ 25 MB). The book uses cached thumbnails at 128×64 for the grid view.
- **Legendaries** get bespoke parameter sets and a slow underwater idle animation
  for their scene.

The painter and mesh are in `fishart.py`; see "Implemented fish looks (V1-28)".

### 6.4 Boats (24) — `boatmesh.py`

The existing four handcrafted boats stay. Eight family generators produce the
remaining 20 from parameters (length, beam, sheer, transom, deck layout,
accessories). Every boat needs a collision footprint and draft (existing rule).
Cat NPC boats reuse the same generators. The generators are in
`boatfamilies.py`; see "Implemented parametric boat families (V1-22)".

### 6.5 UI as a book

- Paper and ink palette, stitched tabs (Fish · Book · Ripples & Keepsakes · Story ·
  Watch · Week), stamps for stages, a watercolor fish grid, and a title-page ceremony
  for each rename.
- Dialogue: portrait left, name ribbon, text with a type-on effect (instant with
  reduced motion), and choices as tabs.
- Every screen works at 1280×720 and up, with three text sizes, and keyboard,
  gamepad and mouse navigation.

`bookview.py` shares tab, grid and page-control geometry between presentation
and pointer hit testing. J opens the book; A/D or gamepad left/right changes
tabs, W/S or gamepad up/down chooses entries, and Enter/A turns a page. Mouse
clicks select tabs or fish, and the wheel browses entries. The Story tab retains
the existing Lake Whispers & Ripples quest details and Guardian progress.
Story details wrap to measured glyph widths and paginate at every window size;
Enter/A or the Turn button reaches the full objective, status, prerequisites,
Bot note and Guardian text. The page counter wraps when the last page is turned.
The compact opening overview keeps progress and Guardian status together;
subsequent pages include those fields in full alongside all quest details.
Rumors are remembered when the session opens an entry; drawing previews uses
read-only page data. Idle menu ticks do not record rumors. Page-control labels
are centered inside their hit regions.
Species rumors and observations, Watch clues, legendary records and shelf
descriptions use measured line pagination too. The renderer publishes the
current page count in transient UI state. Enter/A finishes a Watch card before
opening its entry, and finishes a shelf item's text before cycling shelves.
Changing selection or tabs resets the page cursor and count. A zero-room
paragraph marks the last visible line with an ellipsis.
The collection tab cycles Ripples, Keepsakes and Trophies. `--shots` includes
every tab at text sizes 0 and 2, extra shelf and ceremony views, a contact sheet,
and `book-benchmark.json` for the warmed 1280×720 book presentation.
`book-story-compact.png` shows every page of The Deep-Water Drift at 480×270 with
large text. The full-frame verifier includes all six book tabs in its coverage.
`book-*-compact-text{0,1,2}.png` captures every page of each tab, all shelf types,
recorded and unrecorded legendary examples, and the title ceremony at 480×270
for every text size. The compact quest selection falls back to the first quest
if the long line/scout objective is no longer in the content.
The `-accessible.png` variants also capture Large text with the accessibility
font; shortcut hints fit their reserved footer row using that font's metrics.

Stage events are consumed by the session into one three-second invitation;
J (hold Y on gamepad) reads its exact species page. Title ceremonies wait for
Briar Landing and add the acknowledged milestone to `book.titles_seen`, so a
reload cannot replay an acknowledged title page. Unknown save fields continue
to preserve that acknowledgement for older builds.

## 7. Memory budget (3 GB hard cap)

Peak RSS target **≤ 2.6 GB** on the GPU path. The benchmark hard-fails at
3,000,000,000 bytes (existing).

| Subsystem | Budget |
| --- | --- |
| Python + NumPy + ModernGL + SDL baseline | 250 MB |
| Active lake terrain, zones, depth grids, shoreline | 350 MB |
| Foliage atlas + instances (active lake) | 250 MB |
| Water, reflection and post render targets (1440×810, 4× MSAA) | 300 MB |
| Cat actors (≤ 14 resident) + portraits | 150 MB |
| Fish meshes + card cache | 120 MB |
| Boats (player + ≤ 14 NPC) | 80 MB |
| Audio synthesis buffers + music | 150 MB |
| UI, text cache (existing 8 MiB), book assets | 150 MB |
| Content data, save, simulation state | 100 MB |
| **Steady-state subtotal** | **≤ 1.9 GB** |
| Transient bake headroom during lake load | 400 MB |
| **Modeled lake-load peak** | **≤ 2.3 GB** |

The allocations above leave a further 300 MB between the modeled peak and the
2.6 GB peak RSS target for driver and process variance.

Rules: free bake scratch arrays after upload; no frame histories; cap every cache
with an LRU; the `--benchmark` run logs per-subsystem estimates
(`sys.getsizeof` + NumPy `nbytes` + GL buffer sizes).

## 8. Performance targets

- GPU path: 60 fps at 1440×810 on mid-range integrated graphics (existing class
  of target). The benchmark reports p50 and p95 frame time. It fails if p50 is
  over 16.7 ms (60 fps) or p95 is over 20 ms. That 3.3 ms of tolerance covers GC
  and driver hitches, not a lower target.
- Lake load: ≤ 6 s on GPU, ≤ 15 s on software.
- Software renderer: ≥ 20 fps at 640×360 with cats as impostors.

## 9. Testing

- **Unit tests** per new module (`test_book.py`, `test_comfort.py`,
  `test_legendary.py`, `test_calendar.py`, `test_lakegen.py`, `test_catmesh.py`,
  `test_fishmesh.py`, `test_save_v2.py`, `test_gamepad.py`).
- **Determinism:** the same seed gives the same schedule, Bot name, shiny sequence
  and weather plan across reloads and lake switches.
- **Save fixtures:** commit anonymized v1 saves (fresh, mid-game, V3 complete,
  Guardian seen). Migrations must preserve every v1 field.
- **Cozy invariant test:** fuzz 10,000 random actions in Cozy and assert that
  money never decreases except by player purchases, and no boat, line, book stage,
  Ripple or keepsake is ever removed.
- **Content validation** runs inside `--selftest`.
- **Benchmark coverage** (`--benchmark 1200`): all 5 lakes, 24 boats, 156 fish
  cards, 52 cat models, every shop tab, every book tab, each weather state, and a
  legendary scene.
- **Screenshots:** `--shots` produces one beauty frame per lake × {dawn, noon, dusk,
  night, signature weather}, plus book, dialogue, haul and kitchen. Visual tickets
  attach these to their PR.

## 10. Agent workflow

- **Labels:** `model:opus-sol` (visual, design or narrative-intensive) and
  `model:luna-haiku` (systems, data, tests, plumbing), plus an area label.
- **Branch:** `feat/v1-<ticket-number>-<slug>`. One ticket per PR unless the ticket
  says otherwise.
- **PR body:** link the ticket, list acceptance criteria with ✓, attach
  `--shots` output for visual work, and paste the benchmark summary for anything
  that renders or allocates.
- **Review and merge:** follow `docs/PR-REVIEW-POLICY.md`; Codex and Claude must
  each give a clear review of the current pull request head before merging.
- **Definition of Done:** acceptance criteria met; CI green; docs updated; no new
  warnings in `--selftest`; benchmark under budget when relevant; saves migrate.


### V1-16 calendar implementation

`calendar.json` supplies typed Lake Days, all twelve legendary clock/weather
requirements, daily weather reservations and cookout dialogue. Briar/Cedar have full landscapes; V1-23 adds flat maps for the other waters.
Forecast data itself does not load terrain or unlock content. Their future visual spectacles and full NPC/species rosters
arrive with those lake tickets.

`calendar.py` forks `sim.RNG` with a stable SHA-256 digest of the saved calendar
seed, lake, absolute week and plan version. New saves capture the initial fishing
seed; old saves without a calendar seed capture their saved RNG state on bind.
Fishing never consumes a forecast draw. Current and next 168-hour plans for all
five lake IDs live under `v2.calendar.weather_windows`, bounded to ten records;
unknown future calendar fields/keys survive. Plans are reconstructed from the
same seed during reads, so drawing and menus cannot mutate saved state.
Clock changes refresh saved plans only when crossing a week; lake binding repairs
or initializes them. Lake travel therefore cannot reroll weather.

Daily hard reservations guarantee every legendary at least 120 continuous game
minutes of matching weather and clock, within three days of any eligibility
instant. Flathead's conflicting clear/snow windows and Nebula's clear/aurora
windows get separate intervals. Cedar's rain condition checks only the preceding
six hours. The planner exposes `next_legendary_window`; the future encounter
system still owns non-weather gates and catch replacement. Unreserved weather
uses seeded two-hour blocks, while visuals crossfade over one hour. Fishing,
Bot, HUD, audio, sail wind and both renderers use the same state-aware forecast;
the old no-state weather/rate APIs remain available to reference regressions.

Cookout claims and per-friend chats are saved as bounded last-day ledgers. All
current lake cats use landing anchors from 17:00 until 20:00 Sunday, with normal
schedule restoration at the end. Fish/gift validation happens before any
transaction; the confirmation saves exactly once before the two-second scene.
Only an explicit share consumes a fish. Offline soak advances forecasts without
replaying invitations, chats, morning notes or gifts. Automatic invitations
share the kitchen quota but never consume the tacos' optional extra request.

`test_calendar.py` exercises 1,000 seeded weeks × twelve legendaries × two
fractional eligibility instants, checking complete two-hour windows and the
three-day bound. It also covers reload, lake binding, week rollover, Lake Day
rate isolation, event boundaries, atomic gifts, protected choices, pause/focus,
read-only drawing and keyboard/pointer forecast pagination. `--shots` adds the
calendar gallery and a warmed UI benchmark (week, Sunday, cookout and fish
confirmation), including large text, accessibility font and 480×270 layouts.

### V1-23 five-water framework

`lakes.json` now defines all five destinations, each with `zone_ids`, display
labels, water/land palette stubs, the required completed story chapter and its
two `lake_days` IDs. The actual Lake Day rules remain in `calendar.json` so
there is one source of truth. The old eight habitat indices stay in place;
`reeds`, `springs` and `current` are appended. Briar gains the Reed Passage
matches from `03 §1.2`; Cedar's survey, zones and geometry stay unchanged.

Nebula uses a bounded, driveable flat map with its own
habitat labels and safe landing slips. Crater has springs and no inlet;
Nebula has reeds and current. V1-24 populates their ordinary fish rosters and temporary soundings. Their NPC
casts remain empty until the character-content tickets land. They allocate only the active
world, and the native renderer supports an empty foliage buffer. The play loop
also releases its startup reference when changing lakes.

Travel reads `v2.story.chapter` (earlier chapters completed) or explicit integer
`completed_chapters`: completing 2/3/4 opens Flathead/Crater/Nebula. Briar and
Cedar remain open for existing saves. Querying the menu never grants rewards or
changes story state. Captions come from `05 §10`, including the return from the
reflection. New saves and migrated v1 saves keep the same schema version; new
lake IDs round-trip through the existing save loader.

All ten Lake Days are authored. The new species selectors are canonical future
IDs and take effect when those fish arrive. Monday's Flathead clear bias leaves
the 05:00–07:00 snow reservation intact; clear weather follows at 07:00, retaining
two-hour legendary opportunities. Friday's Crater dawn changes from fog at
06:00 to clear at 07:00. Rare-weather reservations still take precedence;
future meteor and aurora artwork belongs to the lake art tickets.

`python -m fishing --shots shots/lakes --lake-framework` captures all five maps,
day/night water, route locks and warmed full-frame benchmarks. Add `--software`
for the CPU path. `--lakes=briar,flathead,crater,nebula` explicitly selects a
subset on checkouts missing Cedar's binary; full CI still exercises the actual
five-water travel paths. See `docs/issue-51/README.md` for evidence and limits.

### V1-24 species data

`species.json` now contains all 144 standard fish, with counts 36/36/34/34/34
across the five waters. All 108 new rows transcribe `03 §1.3–1.6`: tier defaults,
weights/prices, depths, time bands, bait and habitat priorities, tags, food and
shiny palettes. Their folk names and attributed rumors match the existing Book
manifest. Each row carries a bounded anatomical look using the shared family
meshes, so its catch and Book page render immediately.

New rows declare ordered `baits` and `zones`; validation checks their 1.0/0.6 and
1.0/0.7 matches against the global tables and lake habitats. Optional
`weather_affinities` supply the exact fog/clear ×1.4 and Nebula aurora ×1.25
modifiers. The validator checks 144 unique species and reciprocal lake rosters.
Cedar's six additions are Cedar-only. Existing 36 species rows and the original
five bait/habitat profiles retain regression hashes and seeded-catch coverage.
Roe gains a 0.6 secondary match for the two legacy shad, whose previous best bait
was 0.3; buying specialty bait elsewhere and returning with it is supported.

The flat maps have provisional data-driven `placeholder_depths`, derived from
the authored habitat depth ranges. Their dry terrain stays flat. This lets real
lines reach deep-water fish before the dedicated lake environments arrive;
Briar and Cedar depths are unchanged. `specieschecks.py` floods a conservative
four-metre boating grid from the landing, checks hull/obstacle/draft clearance,
and records real coordinates, depths, bait stock sources and live rate queries.
Every species must have at least one witness at ≥0.5× its authored default rate.
Legacy rows keep their explicit rate overrides. A species present in two lakes
can meet the threshold in either one. Both unit tests and the full gameplay
self-test run this check; no fishing RNG is consumed.

Migration adds empty journal entries for newly supported species while retaining
all prior records and future fields. Tiny weights use up to three decimals so a
0.005 lb minnow never reads as zero. Book hints now name the actual home water.
The 1,200-frame benchmark gives the journal two blocks per cycle to retain full
coverage of 144 fish, twelve quests and every Book tab.

`python -m fishing --shots shots/species --species` produces all 288 normal/shiny
cards, new Book entries, roe stock, a placeholder sounding chart and a warmed
full-frame benchmark. Add `--software` for the CPU path. See
`docs/issue-52/README.md` for captures and measurements.


## Implemented Flathead environment (V1-25)

Flathead now uses `lakegen.LakeFields` with a closed polar outline, six habitat
depth profiles and six authored ridges from `lakes.json.environment`. The shore,
depth and terrain grids share the same bounds for physics, chart and GLSL
textures. The active lake owns its grids; travel can release them. The older
Briar/Cedar fields and Cedar's survey asset are unchanged.

The generator bakes 673×545 float32 fields and a bounded larch/spruce forest.
Larch Gold switches atlas layers in the existing instance buffer. Alpine sky,
teal depth tint, snow caps, pondweed, flooded trunks and a stove-smoke chimney
have native and simplified CPU paths. Snow flakes and smoke have fixed bounds
and freeze under Reduced Motion. The audio lake hook selects loons and a gentle
larch-wind bed; no new downloaded assets are required.

`python -m fishing --shots PATH --alpine [--software]` captures the five required
time/weather views, Larch Gold, the Outpost and a labelled habitat chart. It also
records first-frame load, 60 warmed full frames, memory, fixed GPU resources,
floating-point native probes and all 34 real-map catchability witnesses.
See [issue 53](../issue-53/README.md) for evidence and the explicit Mesa versus
hardware-GPU measurement distinction.


## Implemented Crater environment (V1-26)

Crater uses `LakeFields` with a near-round polar shore, a steep authored rim,
an elliptical obsidian cinder isle, six habitat depth profiles and thermal vent
coordinates. Its 601×601 float32 fields feed collision, terrain, chart and water.
Briar, Cedar and Flathead geometry remain unchanged. The active lake owns its
fields and can be released after travel.

Hemlock, whitebark and drowned-pine atlas layers load for Crater. The dock uses
the existing conservative marina footprints, with a physical brass survey marker
for the later chapter-four ticket. Bounded steam/bubble faces freeze in Reduced
Motion. Height-dependent fog reveals the rim as the forecast clears. A calm
clear-night reflection hook strengthens the sky mirror without changing story
or travel state. The native reflection depth protects terrain silhouettes; the
CPU fallback supplies a simpler moon/star mirror.

`python -m fishing --shots PATH --caldera [--software]` records fog, clearing,
noon, sunset, clear night, springs, isle, survey dock and chart. It checks capture
hulls and records full first-frame load, 60 warmed frames, RSS, resource counts,
finite native colors and all34 real-map catchability witnesses.
[Issue54 evidence](../issue-54/README.md) documents measured Mesa/CPU limits and
the remaining hardware-GPU load measurement.


Crater save loading also relocates deployed ropes buried by the new cinder isle
into a hull-checked launch approach. It preserves deployment IDs, hook/catch and
future fields and updates any matching Bot target. Wet ropes are unchanged; a
save/reload cannot repeatedly relocate a recovered deployment. This keeps the
existing pull-all-lines travel rule from trapping an older save.


## Implemented Nebula environment (V1-27)

The Lagoon is no longer a placeholder. It uses `LakeFields` with kind `nebula`.

**Fields.**
- The polar shore is irregular, with the Comet stream inlet notched into the
  west bank.
- Seven floating lily drifts are islands in the shore field, so hulls collide
  with them.
- Seven habitat circles and two current lanes sit over a void bed. The bed's
  depth is 0.9 + 36 × (1 − e^(−d/90)) m at d metres from a bank, and it falls
  to 62 m in the Void well.
- The 567×567 float32 grids feed collision, depth, the chart and both renderers.

**Current lanes.** Each lane is a polyline traced from `bottools.flow_at`, so it
follows the field that drifts lines. Every lane point becomes a 46 m `current`
circle. Zone lookup, depth profiles, the chart and the drift rule all reuse the
ordinary zone table. The validator checks that:
- lanes are continuous, stay inside the bounds and fit the water shader's
  48-point array;
- each drift's radii are 8–40 m;
- all four band palettes and `water_mid` are present;
- no other lake carries Nebula keys.

**Scenery.** No trees or shore grass grow here.

| Prop | Count | Where | Collision |
| --- | --- | --- | --- |
| Crystal spires | 110 | stardust dunes | none (on land) |
| Star-lilies | on every drift | drift islands | none (on land) |
| Crystal kelp | 36, in six clusters | kelp forest | solid, radius 0.12 × height |
| Meteor boulders | 18, in three reefs | meteor reefs | solid, radius 0.45 × height |
| Light-reeds | 70 | reed bed | none; Briar's reed rules apply |

These props light themselves: `Prop.shade` holds 2 plus the emission, which
both `foliage.frag` and the CPU sprites read.

**Cosmic Drift Station.** The station restyles the shared landing geometry and
keeps every footprint. Timber becomes silver-lilac panels, and lamps become
emissive star-lanterns. It adds an observatory dome with a telescope and a
beacon mast on the dry pad.

**Sky.** `weather.lighting_at` eases between the band palettes Rising, Bright,
Fading and Deep, and `starlight` never drops to zero. The HUD shows the band
name beside the weather. Overcast turns to a lilac stardust haze. The GL sky
adds:
- drifting gas;
- a galaxy band;
- twinkling stars;
- aurora curtains, because aurora is now a visual weather property that
  crossfades like the others;
- Meteor Shower streaks from one radiant on Wednesday nights.

`nebula.py` holds the matching CPU versions.

**Water.**
- Teal shallows deepen to violet water and a starry void bed.
- The surface is glassy, and open-sky reflections sample the full-resolution
  sky. This uses the reflection depth texture, as at Crater.
- Banks and drifts have bioluminescent rims, and the zero-G pads glow.
- Stardust shoals glint, and aurora nights tint the surface.
- Current lanes glow teal and carry one dash per 6 m cell. Each dash points
  and moves along `flow_at`: `nebula.dashes` draws it on the CPU and
  `current_dashes` in GLSL.

**Life and sound.** Star motes replace birds, dragonflies and fireflies. Star
twinkles and a low hum replace loons, gulls, frogs and crickets.

**Starlight travel.** `starlight.py` serves any route to or from the Lagoon:
- The run loop plays the tip into the reflection from the last frame shown.
- The new lake loads under the full starfield.
- The boat then rights itself on the new water.
- The session does not tick meanwhile, and closing the window still quits.
- Reduced Motion plays a still crossfade instead.

Crater's chapter-four reading can reuse `starlight.frame`. Loading a save from
the flat placeholder map moves any rope buried by a new drift, using Crater's
recovery.

`python -m fishing --shots PATH --nebula [--software]` records:
- the four bands, the aurora and the Meteor Shower;
- every habitat, the station and the chart;
- a flow-field figure and the transition strip from Crater;
- first-frame load, 60 warmed frames, RSS, fixed GPU resources and float probes;
- all 34 catchability witnesses;
- the measured angle between the rendered streaks and `flow_at`.

See [issue 55](../issue-55/README.md).

Briar, Cedar, Flathead and Crater are unchanged. Their fields, props, faces and
charts are byte-identical, and their native and CPU frames pixel-identical, to
the previous release. No lake ships as a placeholder now. `World` keeps the flat
placeholder path for a future lake, and a patched test still covers it.


### V1-17 Bot identity and progression

`bot.json` is validated with the other v2 content files and supplies twelve name
prefixes, five shells, tool prices/Depth Finder prerequisites, collar stages and
three knots. `data.py` exposes typed `BotShell` / `BotTool` views. The name fork
is domain-separated with SHA-256 from the schedule seed and never advances the
fishing RNG. The save slot and book header show the saved name, and dialogue
expands only literal `{BotName}` and `{Skipper}` tokens; other braces stay literal.

`botidentity.py` owns profile normalization and explicit story reward hooks:
`grant_shell`, `grant_tool` (including the chapter-one free Reed Anchor),
`advance_collar`, `choose_knot`, and `sync_story_rewards`. Shell awards never
auto-equip. Completed chapters reconcile earned shells and the received/loose
collar on load without replaying toasts, purchases or choices. The chapter-four
marker scene enables knot choice with `story.scene_states.story_c4_knot` set to
`ready`/`active`; finishing or skipping `end_02` adds the joint book credit, and
`end_03` preserves the favorite knot. The future story system calls the same
hooks when its authored scenes run.

Landing → Bot swaps earned shells free, records tool purchases and offers the
saved cosmetic knot choice when the marker scene is ready. Purchases validate
landing/speed, earned shell, Depth Finder (Sonar Grid), money and duplicate
ownership before spending. Owning the shell is sufficient; wearing it is not
required. Free story tools can be granted before the corresponding shell award.
A swap changes only `profile.shell`: name, notes, quest rewards, collar, tools,
scouting phase/target and RNG remain untouched. Future profile fields and IDs
survive normalization. The collar renders only after receipt; hiding it in
Settings changes visibility without changing story state.

V1-18 supplies the shell geometry, chosen-knot models and chimes; V1-19/V1-20
supply tool effects. This ticket provides their state and purchase contracts.
`--shots` includes the identity gallery and a warmed menu benchmark, using one
shared active world for all snapshot states. Compact books keep the name in
the title row so the inherited three-line quest overview remains intact.


### V1-18 Bot shell art, collar rig and chimes

`botmesh.py` builds Classic Tin, green Frog, yellow Duck, copper Sub and violet/
teal Astral shells from boxes, ellipsoids, swept rods and rings. The shared wool
collar has raised stitches, a loose loop and the three saved knots. Home poses
stay fixed on each existing boat's bow. Scouting drives shell-specific propeller,
webbed-foot, wing or crystal joints; reduced motion freezes decorative motion
without changing scout travel. Unknown future shell IDs fall back visually to
Tin without rewriting the saved identity.

Twelve immutable local meshes bound the cache; transformed faces are temporary.
The largest variant is 802 quads, below the existing 500 KB dynamic-buffer budget
alongside the player boat. No texture atlas, extra framebuffer, actor history or
per-lake resource is added. `Face.emissive=None` preserves legacy material
inference; new actor faces use explicit zero or a 0–1 night-emission strength.
This keeps yellow Duck enamel from being classified as a lamp, and makes Astral
chrome/freckles glow in both OpenGL and software. The existing vertex stride and
buffer sizes stay intact.

Shell palette, chime ID and caption are validated `bot.json` fields. The legacy
scouting API still emits `bot`; playback resolves that cue to the current shell,
and captions use its matching authored sound description. `botchimes.py` caches
five quiet, deterministic mono PCM voices: triangle, wooden ribbit-click, rubber
squeak, bubbly tick and glass bell. They use the existing SFX volume/mute path.

`--shots` adds four-view turntables for every shell × collar on/off × day/night,
a knot comparison, scout-motion strip, the native GL comparison when available,
five WAV samples and an incremental memory/rig report. The memory probe excludes
renderer/context and exported image buffers, warms all shell/collar variants and
all voices, and records RSS growth plus traced Python/NumPy peak. The same active
world/context serves native snapshots; software studio frames need no lake.

## Implemented Reed Passage tools (V1-19)

`reeds` zones slow every boat to 0.6 m/s while it is inside one. Lines whose
midpoint lands in a reed bed are refused unless the save owns the Reed Anchor
(Frog Bot's chapter-one grant, `profile.tools`). Owned tools work with any shell
worn, as §10.2 requires. The `reed_dugout` alternative waits for the boat work in
V1-22, when that hull exists.

`sonar.py` builds the Sonar Grid overlay as pure data: a 24 m grid inside each
habitat circle, with a 2 m depth band per cell. It needs the depth finder and the
purchased grid. "Scouted" means a zone with a line in the water or the boat
inside it; a saved scouting record would need a save change and is not added
here. Open water outside habitat circles gets no overlay yet. The chart draws the
bands and adds a legend. `--shots` writes `reed-passage-sonar.png`.

## Implemented bot tools II (V1-20)

`bottools.py` holds the rules as pure functions. The cold layer is
`d(h) = base + amp·sin(2π(h − 15)/24) + weather`, clamped to [3 m, 0.8 × the
lake's deepest authored depth]. Flathead uses base 12 and amp 3; Crater uses 18
and 4. Fog and snow mist add 1.5 m and clear subtracts 1.0. A `cold` species
keeps ×1.0 inside `[d, d+6]` and drops to ×0.35 outside, with or without the
scanner. Briar and Cedar have no thermocline and are unchanged.

The Thermocline Scanner adds `Cold layer N m` to the HUD line under the boat and
to the Bot status line while Bot is out. The book's per-species band display is
not built yet.

**Wave Chime (G on the water):** needs the boat slower than 0.5 m/s and a line
within 30 m. The nearest such line gets `chime_until = now + 60` game minutes.
`surface` species on that line bite ×1.6 while it rings. The cooldown is 120 game
minutes, stored in `v2.bot_tools.chime_ready_at`. `SetLine.chime_until` is saved
only when a chime has rung, so older saves keep their shape.

**Zero-G Winch:** while owned, lines hold still and `current` species on every
line bite ×1.2.

**Nebula currents:** without the winch, each line in a `current` zone drifts at
0.5 m per game minute in a deterministic flow field. Its midpoint stays within
60 m of the set point (`drift_origin`, saved only once the line drifts). A step
that would leave the water or bring the line within 16 m of another is skipped.

## Implemented fleet data and shop tiers (V1-21)

`boats.json` holds all 24 boats from `03 §6`. Each row now carries `tier`,
`family`, `power`, `blurb`, and optionally `top_speed` and `sold_at`. The
validator checks the new fields, allows a well bonus down to −40 lb for tier-1
wells under the 40 lb base, and holds every `shallow` boat to a draft of at most
0.32 m. The four older boats keep every physics and geometry number. Only their
display names change: Aluminum Jon Boat, Reinforced Rowboat, Cat-Rigged
Daysailer and Classic Pontoon. The pontoon already had six lines and `hammock`.

**Power.** `tiller` keeps the motor-upgrade speed and fuel factor. `console`,
`inboard`, `paddle`, `oars` and `starlight` use the table's top speed, with no
motor upgrades. Paddles, oars and starlight burn no fuel, and the HUD shows
`NO FUEL NEEDED`. `sail` boats use the daysailer's auxiliary and sail rules; the
Small Sloop's sail is 1.2× the daysailer's. The rowboat's oars and electric motor
are unchanged.

**Hulls.** V1-21 shipped the new boats on borrowed hulls. V1-22 replaced them
with their own footprints and generated meshes (below).

**Traits.** `shallow` boats reach water down to 0.4 m. `silent` hulls give `shy`
species ×1.15. `galley`, `hammock`, `trophy_rail` and `wind_steady` keep their
existing rules. `ice_hull` boats skip the Flathead snow-mist chop, which slows
every other hull to 0.8× top speed. `glow` hulls get a 0.55 night-emission
strength in both renderers. The Reed Dugout may set lines in reeds without the
Reed Anchor.

**Shop.** `fleet.py` gates new boats by chapter: tiers 1–2 from the start, 3–4
after chapter 2, 5–6 after chapter 3, 7 after chapter 4 and 8 after chapter 5.
"After" uses the dish-card reading: past the chapter, or listed as completed.
Tier 8 is sold only at Cosmic Drift Station and sails on every lake. The older
four stay buyable from the start, and owned boats always switch. The Boats tab
lists the older four first, then new boats by tier and price, with the lock
reason. Livewell upgrades apply to tiers 2–7 only. The benchmark visits all 48
lake/boat pairs within 1200 frames.

## Implemented parametric boat families (V1-22)

**Footprints.** Each of the 20 new boats has its own collision footprint, draft
and eye height. Its length is the table's feet × 0.3048 (within 2 cm), and its
beam, draft and eye height follow its family. No draft is deeper than the
daysailer's 0.72 m, so the catchability witnesses do not change. Every hull
passes landing parking, the Cedar landing barriers and every anchor approach.
Trinidad Cove needed its own approach, 5 m off with the bow toward the cove: an
approach on the anchor point itself blocked the five longest hulls.

**Meshes.** `boatfamilies.py` builds the new boats from one `HullSpec` per boat
and one generator per family:

- Pioneer: the log raft, birch skiff and reed dugout.
- Rowed
- Jon
- Utility
- Runabout
- Sail & Trawler
- Pontoon
- Cosmic

A `HullSpec` sets sheer, bow rise, bow and stern width, and colours. Monohulls
share one shell, with a chine, keel, gunwale and foredeck. Pontoons share one
deck on two tubes.

Benches, oars, paddles, motors, consoles, windshields, canopies, cabins, masts,
lamps, a trophy rail and starlight panels are placed for the cockpit view. Helms
and cabins sit fore or aft of the eye, so the bow and Bot stay in view.

`boatmesh` hands every generated boat to `family_faces`. The four older boats
keep their hand-built meshes unchanged.

Paint reaches hull, deck and motor. Unpainted aluminium keeps each boat's own
material. Cosmic fittings emit at full strength, and glow hulls keep the 0.55
night emission from V1-21. Each mesh has 69–237 faces, which fits the GL boat
buffer alongside the largest Bot. Bot perches on each generated foredeck
(`perch`). `npc_faces(boat_id, x, z, yaw)` places the same meshes in the world
for cat NPC boats.

**Handling.** Acceleration stays per boat. Easing off now sheds speed at a rate
set by the boat's power (`COAST_RATE`, per second):

| Power | Coast rate | Feel |
| --- | --- | --- |
| Paddle | 1.1 | stops short |
| Console | 0.75 | |
| Tiller, oars, sail | 0.65 | as before |
| Inboard | 0.5 | carries way |
| Starlight | 0.22 | glides |

The older four boats handle exactly as before.

**Checks and shots.** `boat_checks` runs the bank, thin-post, pier-rotation and
crossbeam checks for all 24 footprints. `--shots` writes:

- `boat-lineup.png`: a 6×4 studio grid of all 24 boats.
- `boat-lineup.json`
- `cockpit-<family>.png`: one first-person view per family. The Cosmic view is at night.

## Implemented fish looks (V1-28)

**One look format.** All 144 species and the 12 legendaries name their own
`colors` (back, flank, belly) in their `look`. The legacy `palette` looks and
their painter are gone, so the whole field guide shares one style. A look may
also set:

- `marks` and `mark_scale` for its pattern. The patterns are plain, spots,
  speckled, haloed, stars, bars, saddles, stripes, chain, mottled, vermiculate
  and blotched.
- `band` (lateral stripe), `throat`, `parr`, `eye`, `fins` and `fin_edge`.
- `ear` and `ear_edge`: the sunfish ear flap.
- `dorsal_style` (normal, spiny, long, sail) and `pectoral` (normal, fan).
- The tails forked, rounded, truncate, heterocercal, pointed, fluke and flowing.
- `glow` (0–1), a halo in the band colour around cosmic and caldera fish.
- `features`:
  - Anatomy: kype, hump, scutes, gills, legs, whiskers.
  - Field marks: long_ear, ocellus (tail eyespot), shoulder_spot.
  - Cosmic: rings, lure, halo, comet, ribbon.

There are 15 families. The ticket's sculpin, eel and cosmic presets join
sturgeon, salamander, ray and whale. `FAMILY_PRESETS` keeps only eye size and fin
height per family. Everything else is per fish.

**Legendaries.** `legendaries.json` holds the 12 rows of `03 §3`, each with an
`id`, `name`, `lake`, bespoke `look` and `idle`. The validator requires the same
IDs and lakes as `calendar.json`'s legendary windows, and no ID may reuse a
species ID. V1-36 adds the requirement fields to these rows.

**Cards.** `fishart.paint_card` paints the 512×256 card:

- The body comes from an asymmetric profile, `_Body`.
- Fins, tails and legs are shared polygons, `fin_shapes`.
- The pectoral lies translucently over the flank, and fins carry rays.
- The paper, ink outline and frame match the earlier cards.

The GL paint pass and the 48-entry card LRU are unchanged.

**Haul mesh.** `fishart.haul_geometry` builds the haul mesh from the card's own
outline rings, fin polygons, eye, barbels and features, at one scale. Every
triangle takes its colour from the painted card where the side view sees it, so
the haul sprite matches the card. The silhouette IoU is at least 0.92 for every
fish.

- A ray is a shallow dome facing the camera.
- A puffer's ring passes behind the body and in front of it.
- Meshes have 1,312–1,662 triangles, and the 64-entry LRU is unchanged.

**Idle.** `idle_mesh(legendary_id, t, reduced_motion=False)` is the scene's
underwater idle. A body wave runs from head to tail and grows toward the tail,
with amplitude `sway` and frequency `rate`. The fish also bobs by `bob` at half
the wave's rate, so the loop lasts 2 / `rate` seconds. Under Reduced Motion the
fish holds its resting pose. V1-37 places it in the encounter scene.

**Look-alike check.** `fishcheck.lookalike_report` compares every same-lake pair
(legendaries included) at book thumbnail size, 128×64. A pair fails only when
both of these hold:

- **Silhouette:** IoU ≥ 0.90.
- **Palette:** the overlap of soft CIE Lab histograms is ≥ 0.60. The histograms
  are taken over the back, flank and belly thirds, banded column by column.

Histograms keep fin colours, bands and markings that a mean colour would wash
out. Shinies share six palettes by design and are not compared. The check found
the duplicates that the earlier cards shared, such as bluegill and redear, the
gars, the bullheads and channel and drum. Each pair was fixed with a
true-to-life difference:

- **Field marks:** ear flaps, the bowfin eyespot and shad shoulder spots.
- **Breeding or regional colours:** red spawning kokanee, and the tiger trout's
  vermiculation.
- **Body depth:** for example, the stouter black crappie and chubs.

No same-lake pair now comes within 0.015 IoU and 0.03 palette overlap of failing.
`test_fishlooks` also shows that the check catches a duplicated look.

**Shots.** `python -m fishing --shots PATH --fish [--software]` writes:

- `cards-<lake>.png` and `cards-<lake>-shiny.png`
- `cards-legendaries.png`
- `haul-<lake>.png` and `haul-legendaries.png`
- `legendary-idle.png`: six poses per loop in a three-quarter underwater view,
  plus the Reduced Motion pose.
- `lookalike.json`, and `lookalike-closest.png` with the three closest pairs
  per lake.
- `benchmark.json`

The capture fails on any look-alike pair or if it passes 3 GB.


## Implemented cats (V1-29)

**Roster.** `npcs.json` holds 51 rows for the 52 cats: Pip & Pebble share one
row and one actor, Pebble as its `twin`. Each row has an `id`, `name`, `lake`
(null for the two travelers), `role` (host, traveler or water), `boat` (a
generated family boat; null for hosts), optional `boat_paint`, and an
`appearance`:

- **Shape:** `breed`, `size` (0.5–1.4), `build` (0.7–1.4), `legs` (0.5–1.3),
  `coat` (short, long, rex, hairless), `ears` (pointed, folded, tufted,
  rounded) and `tail` (long, bob, none, plume).
- **Coat:** `pattern`, one of the nine below, and `colors` (base, secondary,
  accent).
- **Face:** `eyes` and `whiskers` (0.3–1.6).
- **Attire:** up to four items from the kit: oilskin, parka, sweater, vest,
  life jacket, shawl, scarf, bandana, cap, spectacles, goggles and lantern.
- **Pose and prop:** sit_fish holds a rod; craft holds a book, brush and easel,
  whittling, a mug or a tablet; nap_curl, wave and helm hold nothing.
- Optional `glow` (0–1, glowing markings), `one_ear` and `twin`.

The validator requires 5 hosts (one per lake, on no boat), 2 travelers, 44
water cats and 52 cats in all, with every V3 day cat on its lake. It also
checks ranges, enums, attire count and uniqueness, the prop for each pose, and
that boat paint uses the shop's paint IDs. Each error names its row; an
unhashable value is reported, never raised. V1-30 added slots, anchors and
quest ids to these rows; see "Implemented roster and schedule (V1-30)".

**Rig.** `catmesh.cat_mesh(npc_id, lod)` builds one actor in NumPy:

- Deformed ellipsoids and swept tubes for the head, muzzle, ears, torso, arms,
  legs and a Bézier tail, plus eyes with pupils and whiskers.
- The attire kit and props are built on the same frame.
- Every pose shares one triangle list. The mesh carries the idle pose and the
  wave pose, the neutral coat frame for the pattern, and per-vertex part, rig
  channel, attire tag and distance along the part.

LOD0 has 2,052–2,672 triangles (median 2,320) and LOD1 642–874 (median 750);
Pip & Pebble have 4,464 and 1,404. LOD1 is a little over the guide's 600
because attire keeps its silhouette. The mesh LRU holds 32 entries (both LODs of
14 actors and a few spare), and cached arrays are read-only.

**Coat patterns.** `shaders/cat.frag` evaluates solid, tabby, mackerel, calico,
tortoiseshell, tuxedo, point, spotted and bicolor per fragment. It uses
object-space value noise and masks over the neutral pose, scaled by the cat's
size, with no per-cat textures. `catmesh.coat_weights` is the NumPy reference.
`test_cats` renders both over every pattern's fur and requires agreement on at
least 97% of samples. The software renderer paints per vertex from the same
function.

**Motion.** `shaders/cat.vert` and `actors.animate` are twins, and `test_cats`
checks them against each other by transform feedback. Each frame:

- The torso breathes and the tail sways.
- The ears flick about every seven seconds.
- Within 40 m the head turns toward the player, clamped to ±1.1 rad.
- Between 40 m and 30 m the idle pose blends into a wave, and the waving forearm
  swings about the elbow.

Under Reduced Motion the cats hold still. `actors.pose_state` computes the
parameters, and `actors.shader_uniforms` hands them to the shader.

**Actors.** `actors.place` puts each present NPC in the world:

- A host stands on the nearest camp or marina pier within 12 m of its anchor.
  Without one, it stands on a small plank float at the anchor.
- A water cat sits at its family boat's seat, from `boatfamilies.seat`. The boat
  comes from `npc_faces`, and its heading is a hash of the anchor ID, so boats
  lie the same way each day.

`ActorCache` keeps at most 14 actors, least recently seen out first.

Hailing still measures from the anchor: within 20 m and below 3 knots,
unchanged.

**GL renderer.** `glrender` gives the 14 actor slots fixed GPU reserves: both
LODs in one indexed buffer, the boat, and an impostor layer in the foliage
atlas. LOD0 draws within 40 m and LOD1 within 120 m. Beyond that a cylindrical
billboard is cropped to the cat's silhouette, feet on its base. No GPU object
is created after build. Boats draw at every range, and cats also draw into the
reflection pass.

**Software renderer.** Cats are Gouraud-lit meshes, LOD0 within 12 m and LOD1
to 120 m. They are rasterised with `raster.cover`, a vectorised many-triangle
rasteriser that also draws portraits, impostors and the Skipper's paws. Boats
are faces within the existing 170 m cull. A near cat adds about 2–17 ms to a
software frame, mostly for its boat's faces.

**Portraits.** `catart.portrait(npc_id)` renders a 256×256 three-quarter view
with a warm rim light, ink outline, paper ground and frame. It is rendered on
first need and kept in a 24-entry LRU, which is more than a lake's cats, hosts
and travelers. Twins share the frame. The dialogue panel shows the portrait at
the left, 96–176 px, whenever the frame is at least 640 px wide, and wraps the
text beside it. Chart pins wear each cat's base coat colour, ringed in ink.

**The Skipper.** `skipper.py` draws two dusk-brown tabby paws with cream mitts
in the cockpit frame:

- **Tiller boats:** on the tiller. Where a boat's tiller sits behind the eye,
  the paw holds a tiller extension instead.
- **Rowed boats:** on the oar looms.
- **Paddle craft:** on the paddle shaft.
- **The haul:** both paws work the line hand over hand. The session sets the
  transient `state.hauling` while the haul screen is up; it is never saved.
- **Wheel boats:** no paws outside the haul.

On calm water (no rain, little mist), at idle and not hauling, the GL reflection
pass alone draws a dark silhouette of the Skipper's head. It is placed so its
mirror image, ears pointing down, lies on the water past the bow. The software
renderer stamps the same mirrored shape onto its water pixels.

**Memory.** `actors.memory_report` adds up the resident meshes and boats, the
mesh-cache bound, the portrait caches, the GPU slot reserves and software paint
caches, against the 150 MiB budget. The worst case measured with 14 resident
actors was about 17 MB on the CPU and 11 MB of GPU reserves. The `--benchmark`
run now places each lake's cats, and fails if more than 14 are resident or the
bound passes 150 MiB. It reports the result as `cat_actor_memory`.

**Shots.** `python -m fishing --shots PATH --cats [--software]` writes:

- `cats-lineup.png`: all 52 cats, each figure above its portrait.
- `cats-portraits.png`, `cats-poses.png` (with the wave blend),
  `cats-patterns.png` and `cats-lod.png` (LOD0, LOD1 and impostor).
- `world-<lake>-<npc>-{approach,hail,close}-<backend>.png` and `cats-world.png`
  for the resident cats on Briar and Cedar.
- `skipper.png` and `reflection-{idle,moving}-<backend>.png`.
- `dialogue-portrait-<lake>.png` and `chart-pins-<lake>.png`.
- `benchmark.json`: triangle counts, mesh and portrait timings, the world
  placements, a 20-cat cache run that must stay within 14 actors and 150 MiB,
  the hailing cases, and the wave and Reduced Motion checks.

The capture fails if the lineup is not 52 cats, if Reduced Motion moves a cat,
if hailing changes, or if it passes 3 GB.

## Implemented roster and schedule (V1-30)

**Roster fields.** Every `npcs.json` row now also has:

- **`slot`.** Hosts are `landing`, travelers `traveler`, and water-cats `day` or `night`, as in `04 §4`. The night cats are Master Cinder, Hank Mudpaw, Señora Luz, Torvald, Elk-Ears Eli, Nyx, Fumi, Orion-Cat and Twinkle.
- **`anchor`.** Each cat has its own anchor on its own lake. A host's is its landing dock anchor. Travelers have `null`, because they moor at each lake's `mail_mooring` or `tinker_mooring`.
- **`quests`.** A host gives one quest: its V3 errand or `host_<lake>`. A water-cat gives two: A, which is its V3 quest or `wc_<id>_a`, and B, `wc_<id>_b`. Travelers give none. V1-31 authors the new quests.

The validator checks the slot for each role and that no two cats share an anchor or a quest. Every V3 day cat keeps a day slot on its lake, and Master Cinder keeps the night. Each lake needs 3–9 day encounters and 1–3 night encounters, so the round-robin covers every encounter in three days. Each lake has 7 day encounters, and 1 night (Briar) or 2 night encounters (the others).

**Anchors.** `anchors.py` adds 47 anchors:

- the Flathead, Crater and Nebula landings;
- an anchor for every new encounter, in its `04` zone;
- a mail and a tinker mooring on every lake.

They are at least 45 m apart, so hail circles never overlap, and outside the 50 m landing exclusion. Every boat can approach each one, and each cat's own boat fits at its anchor and heading. The positions were searched once against each lake's chart and are fixed in code, like the V3 ones. A flat placeholder map has no anchors and therefore no cast.

**Schedule (`npcs.py`).** Presence is a pure function of `(schedule_seed, lake_id, day)` and of the quests that pin a cat:

- **Hosts** are always at their landing.
- **Day encounters (06:00–20:00).** Each lake's day pool is put in a seeded order (SHA-256 of the seed, lake and cat), and day *d* takes the next three: positions `3d`, `3d+1` and `3d+2`, wrapping. With at most nine day cats, any three days cover them all.
- **Night encounter (20:00–04:00).** The night belongs to the game day it starts on, and day *d* takes position *d* of the night pool's seeded order. Briar's pool is Master Cinder alone.
- **04:00–06:00.** Only hosts.
- **Pins.** A cat needed by an accepted quest is present every day in its own slot, taking an extra place if the round-robin hasn't brought it:
  - a `talk_to` cat of an active quest's objective or steps;
  - the giver of a quest waiting to be turned in.

  The story's chapter steps arrive in a later ticket and add their `talk_to` cats through `npcs.pinned`.
- **Travelers.** Postmaster Pounce moors at one unlocked lake a day, 08:00–16:00. The lake is a seeded pick, in lake order, among the lakes `travel_unlocked` opens. Tinker Thistle moors at the player's lake every Saturday, 10:00–18:00.
- **Sunday cookout (17:00–20:00).** A lake's host and all its encounters stand on the landing's two piers, alternating sides, host first. On Cedar this is the public landing, not Doc's marina, so the cookout can be joined where `at_landing` applies. Cookout chat lines are still those of `calendar.json`.
  - Every place is beside the docked stretch of the slip, from 2.6 m in, spaced to fit the slip. A boat docked alongside a cat hails that cat, which cookout chats and `attend_event` need.
  - In the jon, every cat can be hailed while docked. A long hull can't reach the deepest places: the 9.75 m houseboat gets 7 m into most slips and 5 m into Cedar's. It still reaches the host, who stands first.
  - Until V1-32 the first places were at the slip mouth, 0.5 m in. No docked boat was nearer to the host or the first guest than to someone else, so neither could be hailed while docked.

The session rebuilds the cast whenever `schedule_key` changes: the day, the band, the cookout, the pins, a migrated V3 cat, or a traveler's window.

**Hailing.** Hailing is unchanged: 20 m and below 3 knots. A cat with nothing to say answers a hail with a wave toast. Since V1-33 that is only Tinker Thistle, and Postmaster Pounce when he carries no letter.

**Migrating V3 saves.** V3 saves stored one chosen day cat per lake (`day_npc_by_lake`) and the day it was chosen (`schedule_day_by_lake`).

- On load, that cat stays present for the rest of its saved day, taking an extra slot if the new rule didn't pick it. From the next day the new rule alone decides.
- An unknown or stale pick is ignored.
- The schedule no longer writes these fields. They stay in the save as they were, so an older build can still read them.

**Tests.**

- `test_npcs` checks every lake over 10,000 seeds: every encounter appears in every three-day span, three distinct cats a day.
- It also checks:
  - the day, night and dawn boundaries;
  - Cedar's alternating nights;
  - quest pins, travelers and the V3 migration;
  - determinism across save, reload, offline time and lake switches.
- `test_anchors` validates all five lakes' anchors and seats every cat's boat.
- The earlier V3 schedule tests in `test_npcs`, `test_calendar`, `test_dialogue`, `test_lakes` and `test_narrative` now assert the new rule.

## Implemented quests v2 (V1-31)

V1-31 is the quest system. It shipped `quests.json` with no rows: V1-32 and V1-33 (below) author the side quests, and V1-34 the story steps. Its tests author their own rows against the real roster, lakes and places.

**Content (`content_v2/quests.json`).**

- **Quest rows:** `id`, `kind` (`host`, `a`, `b` or `story`), `giver_id`, `lake_id`, `title`, `objective` (one step or a list of 1–4 steps), `journal` (the `obj:` text) and `reward`. Optional fields are `requires`, `cross_lake`, `on_accept` (items given once on acceptance) and `lines`.
- **Ids follow the kind:** `host_<lake>`, `wc_<cat>_a`, `wc_<cat>_b` or `story_c<n>_s<m>`. A side quest's id must be one of its giver's roster quests. An id that collides with a V3 quest is rejected. Recopied V3 lines are `extends` rows instead (V1-32, below).
- **Cats rows:** each cat's `greetings`, keyed by state, and one to three letter variants.
- **Lines** hold `offer` and `done`, plus optional `accept`, `decline`, `progress`, `ready`, `ready_wait` and `return`, and four choice labels. Each is up to three bubbles of at most 140 characters, using only `05 §0`'s placeholders. `load_content()` turns them into the V3 nine-stage graph; missing stages take `05 §6.0`'s generic fills.

**Validator.**

- Fields are closed per step type (`content.STEP_FIELDS`), so an unlisted field, a V3-only literal or another type's field is an error naming the row.
- It checks:
  - references: zones, areas, waypoints, species and legendaries, baits, dishes, tools, shells and cats;
  - exactly one of each alternative (`species_id` / `species_ids` / `group` / `tag` / `any`, and so on);
  - clock windows, tier and hook counts, a book count no larger than its scope, and `then_weather` ≠ `weather`.
- A step on another lake must be listed in `cross_lake`.
- **Rewards follow `02 §12.1`:**
  - a host errand pays cash only;
  - quest A pays cash and a Ripple from 11–44;
  - quest B pays cash and `ks_<giver>`;
  - Ripples and keepsakes are unique across quests.

**Named places (`lakes.json`, 06 §5).** Areas are circles, rings (`inner_r`) or polygons; waypoints are circles. They were searched once against each chart:

| Lake | Areas | Waypoints |
| --- | --- | --- |
| Briar | `landing_edge` (the 50–150 m ring around the slip) | `reed_edge_1`–`3` |
| Cedar | `marked_pool` (in the rocks) | `lamp_buoy_1`–`3` around the pool; `drift_buoy_1`–`3`, the last one the jug; `practice_buoy_1`–`4` in the lilies |
| Crater | `safe_cove_1`–`3` (lilies, cypress, flats) | `survey_marker` in open water |
| Nebula | `calm_reflection` (200 m, open water) | — |

The validator requires this set, and `test_quests_v2` checks every area holds legal line water and every waypoint is navigable. `lakes.in_place(ref, lake, x, z)` tests a point.

**Events.** Each step counts only events after acceptance, and only while it is the current step.

| Event | Emitted when | Steps it advances |
| --- | --- | --- |
| `catch.resolved` | A catch is kept or released, including a forced release at the hook. It carries the hook's position, bait, weight, hour and cold band. | `catch_species` |
| `legendary.witnessed` | A legendary is witnessed. The Whiskered Guardian's sighting emits it (V1-32); the other watches arrive with V1-36. | `catch_species` |
| `book.stage_up` | A book entry reaches a new stage. | `book_stage` |
| `cook_dish` | A dish is cooked. | `cook_dish` |
| `catnap.complete` | A nap ends; it carries the zone. | `catnap` |
| `tool.use` | The chime rings; a line is set in the reeds with the Reed Anchor; Bot reports with the scanner on a thermocline lake or with the Sonar Grid; a current line is checked with the winch. It carries the shell worn. | `tool_use` |
| `waypoint.enter` | The boat crosses into a waypoint. | `visit_zones`, `visit_sequence` |
| `npc.hail` | A cat is hailed. It carries whether that cat is the lake's host, the event under way and whether the boat is docked at the landing. | `talk_to`, `attend_event` |
| `settle.complete` | The settle-in interaction finishes (emitted by V1-34). | `settle` |

Existing events gain fields: `line.set` its midpoint and cold band, `bot.scout_complete` its position, and `anchor.sample` the weather, each forecast span it covered and the boat position.

**Step rules (`quests.py`).**

- **Lines** match `zone_id` or `area_id` (the midpoint at set time), `tier_id` or `min_tier`, `hook_count`, `bait_id` on every section, `set_window` and `in_cold_band`. `line_scout_check` needs the report before the check. Since V1-33 `active_soak_game_minutes` is optional: without it, any check of the set line counts.
- **`windows`** ask for one event in each window, for each target: two windows on one zone need two reports. A `visit_sequence` needs one ordered pass inside each window, and a leg counts for one window only.
- **`wait_weather`** accumulates anchored minutes in the place while the weather holds; drifting pauses it without resetting. With `then_weather`, it completes when the weather turns while the player is still anchored there. A long advance such as a catnap reports each forecast span (`calendar.weather_spans`), so only the minutes actually spent in that weather count.
- **`book_stage`** counts the book as it stands and completes on acceptance if already met. So does a `catch_species` step that names only a legendary, when that legendary is already recorded (the Guardian once sighted).
- **`talk_to`** with `distinct_days` needs hails on that many game days (06:00 to 06:00).
- **`attend_event`** needs the host hailed during the cookout, docked at that lake's landing.
- **Clock windows** are local clock minutes. Game minute 0 is 06:00, which `_window_contains` adds. Until V1-31 it compared elapsed minutes, so the V3 windows were checked six hours late: Willow's 05:00–08:00 window was read as 11:00–14:00.

**Availability and chains.**

- A cat's chain is its roster quests that have dialogue. A hail opens the first not yet done.
- `requires` (a finished chapter, a completed quest, an open route) keeps a quest off offer until met.
- Quest B opens the game day after A is turned in: `completed_game_minute` is saved with the claim. A V3 quest A completed before V1.0, with no saved minute, opens B at once.
- A pin covers only the current step's `talk_to` cat and a ready quest's giver.

**Turn-ins and friendship.**

- **At the giver or the host.** A ready side quest can be turned in to its giver, or at its lake's host. The host's hail opens a hand-in menu before her own conversation.
- **The giver's acknowledgement.** After a host turn-in, the giver's next meeting opens on that quest's return line, even when quest B is now on offer. This uses the ledger's `turned_in_by` and `acknowledged` fields.
- **Friendship** (Stranger, Acquaintance, Friend) is derived from quests A and B and never stored.
- **Greetings** use the most specific state the cat has a line for, in this order: `first`, cookout, `after_chN`, `weather:<state>`, friendship, `day`. A list of greetings is a set of alternatives, one picked per game day. V1-32 moved `first` to the top and set when a greeting is shown; see below.

**Rewards.**

- **One ledger.** Every reward goes through `narrative_v1.reward_claims`. It recognizes V1.0 ids by their grammar (`narrative.is_quest_id`), so a later build's ids and claims load as progress. An on-accept gift claims `<quest>:accept`.
- **Where each kind goes:**
  - cash to the purse;
  - Ripples to `v2.ripples_v2` (the V3 Ripples keep their list);
  - keepsakes to `v2.keepsakes`;
  - recipes to `v2.recipes`, and dish cards to `v2.dishes_known`;
  - bait to the bait locker, and pantry items to the pantry;
  - shells through `grant_shell`;
  - unlocks to `v2.unlocks`, where `travel:<lake>` also opens that route.

**Letters.** Once a cat's quests are all done, they write one letter: a variant chosen from the seed, kept in `v2.npcs.letters`. Postmaster Pounce delivers the oldest letter sent before today, at most one a game day, when hailed. A cat with nothing to say yet still waves.

**Journal.** The quest pages list the twelve V3 quests, then each accepted V1.0 side quest. A V1.0 page shows its `journal` text and its step. For a step that needs a cat, and for a ready quest's giver, it says when the schedule next guarantees that cat is out (`npcs.next_appearance`, `02 §12.2` rule 4). Travelers follow their own rules: Pounce's next visit to your lake, and Thistle's next Saturday.

**Tests (`test_quests_v2`).**

- **Each objective type** is completed by its own events. Events before acceptance don't count, and the reward pays exactly once, including after a reload.
- **Each field** is tested with an event that differs only in that field, which must not count.
- **The validator** accepts every type and field, and rejects unlisted fields and bad rows without raising.
- **The twelve V3 quests:** `narrative_v1.json`'s digest is fixed, and merging leaves its quests, dialogue and NPCs as they were.
- **Turn-ins:** a host turn-in is acknowledged by the giver's return line at the next meeting, for a V3 quest and for a V1.0 quest.

## Implemented Briar and Cedar content (V1-32)

V1-32 transcribes `04 §4.1–4.2` and `05 §4.1–4.2, §6.1–6.2, §7, §9` into `content_v2`.

**What ships.**

- **`quests.json`: 24 quests, 11 on Briar and 13 on Cedar.**
  - Quests A and B for the seven new cats: Marigold, Old Gus, Biscuit, Hank Mudpaw, Belle Pecan, Señora Luz and Kit.
  - Quest B for the ten V3 cats, whose quest A is their V3 quest.
  - Titles and objectives come from `04`; the lines and the `obj:` journal text from `05`.
- **Cash.** Quest A pays $45 on Briar and $55 on Cedar. Quest B pays 1.5× that, rounded half up: $68 and $83.
- **Other rewards.** Ripples 11–17 go to the seven new cats' quest A, in roster order. Each quest B pays `ks_<giver>`. Hank's quest A also gives the `pecan_smoked_shad` recipe (`04`: "gives `pecan_smoked_shad` after A"). Biscuit's quest A gives a dozen dough balls on accept. Old Gus's quest B needs the Flathead route.
- **Greetings.**
  - Each water-cat's `greet` is its `day` line, and `friend greet` its `friend` line.
  - Grandmother Whiskers has `day` (two alternatives), `weather:drizzle`, `weather:mist`, `after_ch5` and `cookout`.
  - Doc Barnaby has `first`, `day`, `weather:drizzle` and `after_ch2`.
- **`ripples.json`** holds Ripples 11–17. **`keepsakes.json`** holds the 17 Briar and Cedar keepsakes, with `04`'s names.
- **Letters.** `05 §9` has samples for three of these cats (Elder Moss, Hank Mudpaw and Señora Luz), one variant each. The other friends write no letter until their variants are authored.
- **`extends`.** `q08_channel_run` recopies Maeve's greeting and quest A offer (`05 §6.2`).
- **Rumors.** `05 §8.1` already matched `book.json`, so nothing changed there.

**Transcription rules.**

- Each quoted speech is a bubble.
- A stage direction becomes text in parentheses. It joins the speech it introduces, or ends the node as its own bubble, as in Kit's quest A completion.
- Markdown emphasis is dropped, as in Quill's quest B completion.
- `weather:rain` is the game's `drizzle`, for Marigold's quest B and both hosts.
- `05` gives Hank's quest B no `obj:` line. Its journal reads "Record the Channel Leviathan.", worded like Señora Luz's.
- Some lines belong to other systems and are not greetings: the Clue lines (Willow, Quill and Hank), and the hosts' kitchen, pantry, clue, tow and nap lines.
- Elder Moss's `greet` is his `day` line. While his V3 quest A is open, its own nodes speak, so the line first greets you before his quest B offer.

**Schema.**

- **`extends` rows** are `{id, extends, lines}`. Both ids name the same V3 quest. Each key in `lines` is one of the nine V3 stages and holds one text. Merging replaces only that node's text; the V3 quest and its graph are unchanged.
- **Registries.** A reward's `ripple_id` must be in `ripples.json` (`ripple_11`–`ripple_44`, one bubble each). A reward's `keepsake_id` must be in `keepsakes.json` (`{id, name, npc_id}`, where the id is `ks_<npc_id>`).
- **Greeting values** are a text, or a list of alternatives. Each alternative is a text or a list of bubbles.
- **Letters** take one to three variants.
- **Unreadable files.** Quest rows reference species, baits, lakes, pantry, dishes, Bot tools, legendaries, cats, Ripples and keepsakes. When one of those files can't be read, it is reported once, and the rows are not checked against it.

**Greetings, as shown.**

- **Precedence:** `first`, then cookout, `after_chN`, weather, friendship and `day`.
- **A first meeting.** A `first` line opens it before anything else, V3 quests included. Doc's welcome comes before his `q02` greeting.
- **Before an offer.** A greeting comes before a V1.0 offer. A cat with no line for its state goes straight to the offer; the V3 cats other than Elder Moss have no `day` line.
- **After the last quest.** Once a cat's quests are all done, the last quest's return line answers that turn-in for the rest of the game day. From the next day, the greeting replaces it. So a host's greetings start the day after her V3 errand is turned in.
- **Bubbles.** A greeting of several bubbles is laid out as chained nodes: `<cat>:greeting`, then `<cat>:greeting:2`, and so on.

**Other changes.**

- **Book.** The Ripple shelf shows a V1.0 Ripple as its quest's title and the Ripple's text, remembered with its giver. The keepsake shelf shows the keepsake's name and its giver.
- **Guardian.** The Whiskered Guardian's sighting emits `legendary.witnessed`, which completes Quill's quest B. Accepting that quest after the sighting completes its step at once.
- **Cookout places.** The layout fix is described in the V1-30 section above; without it, Biscuit's and Belle's quest B could not be completed.

**Tests (`test_quests_briar_cedar`, now `test_quests_content`).**

- **The script.** The test reads `05 §6.1–6.2`, `§4.1–4.2`, `§7` and `§9`, and `04`'s keepsake names, and applies the transcription rules above. It then compares every line, journal, greeting, Ripple, letter and keepsake name with the shipped content.
- **Rewards.** Cash by lake, Ripples 11–17 in roster order, one keepsake per water-cat, Hank's recipe, Biscuit's gift and Gus's requirement.
- **Graphs.** Every quest's dialogue graph, V3 included, is reachable from its entries and acyclic.
- **Greeting states.** Each one can be true on its cat's lake; for example, the weather it names occurs there.
- **The playthrough,** one per lake, in a real session with the shipped content:
  - Each V1.0 quest is offered and declined, accepted, and hailed while under way.
  - Its events complete it. It is put off at the ready node, turned in by hail, and acknowledged by its return line the same day.
  - A friend's greeting follows on a later day.
  - The V3 quests A are readied directly, because `test_narrative` covers their objectives, and turned in by hail.
  - Every authored V1.0 node is shown. Rewards and letters are checked, and a reload pays nothing.
- **Systems.** The Guardian sighting readies Quill's quest B. A first line and a greeting of several bubbles lead into the quest. The book shows V1.0 Ripples and keepsakes.
- **`test_npcs`** checks that every cookout guest on every lake can be hailed from a docked boat.
- **`test_content_v2`** checks that an unreadable file the quests reference is reported once.

## Implemented Flathead, Crater and Nebula content (V1-33)

V1-33 does for the three later lakes what V1-32 did for Briar and Cedar. It transcribes `04 §2–4.5` and `05 §4.3–4.5, §6.3–6.5, §7, §9` into `content_v2`. Every lake's side quests now ship: 81 V1.0 quests in all, with the 15 story steps to come in V1-34.

**What ships.**

- **Quests A and B for the 27 water-cats.** Titles and objectives come from `04`; lines and `obj:` journals from `05`.
- **The three host errands.**
  - `host_flathead` *The Long Story*: talk to Captain Huckleberry on 3 different days.
  - `host_crater` *Fog Names*: anchor anywhere on Crater during fog for 30 minutes, then talk to Sora.
  - `host_nebula` *Units, Please*: 5 Nebula species at Identified.
- **Cash.** Quest A pays $80 on Flathead, $110 on Crater and $140 on Nebula. Quest B pays 1.5× that: $120, $165 and $210. The new host errands pay as quest B. `04` sets no amount for them, and `q01` and `q02` pay about 1.33× and 1.64× their lake's quest A.
- **Greetings.** Each water-cat has `day` and `friend` lines, and the hosts have their `day`, weather and `after_chN` states. The hosts' `first` lines belong to the story (V1-34). Bot's reply to Astra-9's `day` line is its second bubble, "Bot: It is not.", in the form his barks take.
- **Ripples 18–44 and 27 keepsakes.** Each lake's quests A give its Ripples in roster order.
- **Letters.** `05 §9`'s samples for Captain Huckleberry and Andi.
- **Rumors.** `05 §8.2–8.5`, all 144 rumors and the 12 legendary pages, already matched `book.json`.
- **Dishes and clues.** These were already in place: `kitchen.teach` gives a host's dishes in their chapter, and a clue teller's recipe on a hail (V1-15).
- **Travelers.** Pounce's letters (V1-31) and both schedules (V1-30) are their only authored parts. `03` gives Tinker Thistle no paint catalog and `05` gives no jokes, so Thistle still waves.

**Calls made where the source is silent.**

- **Written journals.** Twenty quests B have no `obj:` line in `05`. Their journals are written like their neighbours: "Record …" for a legendary, "Catch …", "Cook …", "Identify N … species in the book.", and "Attend the Sunday cookout at …". `test_quests_content` pins them.
- **Huckleberry's errand lines.** `05` gives his errand no offer or turn-in line, so these two are written in his shape (`04 §2`). His Whopper story itself is told as written.
- **Torvald's quest A** ("set a line inside the cold layer and check it") has no soak time, so any check counts.
- **Dakota's "4 different trout species"** is the `trout` food group with `distinct`, on any lake.

**Stories.** A cats row may have a `story`: 2–5 parts, each a line of bubbles.

- **Telling.** The first hail of a game day tells the next part, after the greeting and before the quest's own node.
- **Saving.** A part counts as heard only once its node is shown, so closing the conversation on the greeting keeps the part for the next hail. Progress is saved as `v2.npcs.stories.<cat> = {heard, day}`, and the story ends after its last part.
- **Use.** Captain Huckleberry tells the Whopper in three parts (`05 §4.3`). `dialogue.story_heard` is what Huckleberry's Whopper's gate, heard on 3 different days, will read in V1-36.
- **Quests are counted separately.** His errand and Bjorn's quest A count their own hails (`talk_to`, `distinct_days: 3`). The story is told once, whichever comes first.
- **The acceptance day counts.** A quest taken from the very cat its `distinct_days` step needs counts that day's hail (`quests.count_todays_hail`). The hail came before the acceptance, so the step would otherwise miss it. Huckleberry's errand is therefore ready on the day his story ends. Bjorn's quest, taken from Bjorn, counts only hails to Huckleberry.

**Still waiting on other tickets.**

- **Legendaries.** Six quests B record a legendary, which can only be hooked from V1-36 on: Old Silverhead, the Glacial Phantom, Huckleberry's Whopper, the Obsidian Gar, the Caldera Fire-Lizard and the Nebula Weaver.
- **Chapters.** Ember's and Juno's quests B need chapters 4 and 5 finished (V1-34).
- **Silent progress lines.** Those two quests are ready at the next hail after acceptance, so their generic progress line is never shown.

**Tests (`test_quests_content`, which replaces `test_quests_briar_cedar`).**

- **The script.** The V1-32 checks now run for all five lakes. They also cover the hosts' states and errand lines, the Whopper story, five letters, Ripples 11–44 and 44 keepsakes.
- **Playthroughs.** There is one per lake: `test_flathead_alpine`, `test_crater_caldera` and `test_starlight_nebula`, after the two from V1-32.
  - Each plays the host errand first, then every cat's quests A and B through their own events and real hails.
  - Cookouts are hailed docked, and the Whopper is heard across days.
  - Ember's and Juno's quests B wait for their chapters, and the Frog-shell and night-catch filters must hold until their last event.
  - Every authored V1.0 node is shown, except those two silent progress lines. A reload pays nothing.
- **Systems.** A story is told one part a game day, after the greeting, survives a reload and ends. A line check with no soak time counts a check a moment after the set. The validator rejects a one-part story and a traveler's story.

## Implemented story spine, chapters 1–2 (V1-34, part 1)

V1-34 (#62) is the story: a prologue, five chapters, the Settle In finale and the ending. This part builds the story engine and chapters 1–2. The rest is listed at the end of this section.

**Shape.** Each chapter is three steps, *meet → notice → share* (`01 §5`). A step is a `story`-kind quest row with id `story_c<chapter>_s<step>`, and its `journal` reads "Story — …".

- **Starting.** A step starts by itself. It is never offered or declined, once its chapter is the current one (`story.chapter`) and its `requires` are met. The prologue will open chapter one. Until then, no step starts, so existing saves and older suites are unchanged.
- **Finishing a chapter.** Turning in step three completes the chapter: `story.completed_chapters` gains its number, and `story.chapter` moves to the next. Turn-ins of story steps never queue a friend's letter.
- **Conversation.** A cat's story takes precedence over their own side quest, with one exception: a host's turn-in menu still comes first. Their own errand comes back on the next hail, once the story step is done.
- **Rewards.** Quest rewards gain `tools`, applied through `botidentity.grant_tool`. The Reed Anchor, for example, is granted at chapter one's second step.

**Chapters 1–2 as authored (`content_v2/quests.json`).**

| Step | Cat | Objective | Reward |
| --- | --- | --- | --- |
| `story_c1_s1` Map With a Hole in It | Pip & Pebble | talk to Pip | none |
| `story_c1_s2` Reed Scouts | Pip & Pebble | Bot scouts 3 reed-edge points, any order | Reed Anchor (tool) |
| `story_c1_s3` A Useful Note | Grandmother | catch any fish in `briar:reeds` | Frog shell, Reed Passage chart |
| `story_c2_s1` The Missing Jug | Doc Barnaby | talk to Doc | none |
| `story_c2_s2` Following the Drift | Doc Barnaby | visit the 3 drift buoys in order | none |
| `story_c2_s3` The Marked Pool | Doc Barnaby | premium-or-heavy line in the Marked Pool, 60 active minutes | Duck shell, Flathead travel |

**Calls made where the script is silent or doesn't fit one node:**
- **Speakers.** A node has one speaker, the step's giver. Where a node carries a second voice, the line is prefixed with the speaker, as in "Pebble: Frogs live in the reeds." or "Bot: It is warm." The portrait stays the giver's.
- **Trimmed lines.** Chapter 2's `05 §2.2` has four bubbles at the end, and a node holds at most three. Bot's "I am a duck now" line is dropped.
- **Turn-in labels.** Each step's `turn_in_choice` is a line of the step, for example "Let's find the reeds.", rather than the generic label.

**Not built yet.** Each of these is a later part of V1-34.
- The prologue (`pro_01`–`pro_06`), which opens chapter one and gives the Skipper the book.
- Chapters 3–5, which need the Settle In interaction (`settle` steps and their cues) and the Flathead and Crater authoring.
- The collar beats, the knot choice scene and the ending, including the book retitle and credits.
- Tools lent for chapter three, and a chapter's visible world changes (the Marked Pool barrier and sign, for instance), which belong to V1-35.

**Tests (`test_story`).** A new save's first step starts only once its chapter is open. Chapter one runs from Pip's hail through turn-ins to Grandmother's, and chapter two on Cedar through Doc's, all by real hails and events. A reload mid-chapter keeps the progress and pays nothing twice. A story step has no time limit, story steps appear in the journal, and no friend's letter is queued for a story giver.
