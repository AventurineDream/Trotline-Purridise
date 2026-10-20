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
| Lakes and world | `lakes.py`, `world.py`, `forest.py`, `shoreline.py`, `marina.py`, `anchors.py` | Three new procedural lakes, new zone archetypes, per-lake labels, thermocline, currents, reeds |
| Weather and ambience | `weather.py`, `ambient.py`, `life.py`, `audio.py` | New weather states, weather-window scheduler, per-lake ambience, shell chimes |
| Boats | `boat.py`, `boatmesh.py`, `boatchecks.py` | 24 boats from 8 parametric families, traits |
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
  boats.json         # 24 boats + traits (03 §6)
  bot.json           # prefixes, shells, tools (03 §7)
  lakes.json         # 5 lakes: labels, zones, Lake Days, weather sets, palettes
  npcs.json          # 52 cats: appearance params, boat, slot, anchor, quests
  quests.json        # 96 new quests (15 story + 3 host + 34 quest A + 44 quest B);
                     # 108 in total with the 12 in narrative_v1.json
  dialogue/*.json    # one file per lake + story.json + bot.json + system.json
  book.json          # rumors, legendary stories, folk names
  ripples.json       # 44
  keepsakes.json     # 44
```

`fishing/assets/narrative_v1.json` stays as-is and is loaded **in addition**. The
v2 loader rejects any id that collides with a v1 id unless the row is marked
`"extends": "<v1 id>"` (used for quest-B links and recopied V3 lines).

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
  Override with `--save PATH` for tests.
- On first launch, if `saves/briar.json` (v1) exists and no v2 save does: copy it
  to `<prefpath>/backup/briar.v1.<timestamp>.json`, migrate, write v2, and leave
  the original untouched.
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
              "last_prompt_real_s": 0},
    "buff": null,
    "pantry": {"herbs": 0},
    "recipes": [], "dishes_known": [],
    "boat_extras": {"<boat id>": {"paint": {}}},
    "book": {"species": {"bluegill": {"found": [], "shiny": 0, "since_shiny": 3}},
             "tracked": null, "title": "fishypedia", "dream_clue": null},
    "legendaries": {"spillway_monster": {"records": [], "clues": ["teller"]}},
    "story": {"chapter": 0, "steps": {}, "scenes_seen": [], "pending_rewards": []},
    "npcs": {"letters": [], "talk_days": {}},
    "keepsakes": [], "ripples_v2": [],
    "calendar": {"weather_windows": {}},
    "settings": {"text_size": 1, "haul_speed": "normal", "reduced_motion": false}
  }
}
```

### 3.3 Rules

- **Migration of v1 → v2:** the migrated save, written to the new path (§3.1)
  while the v1 file stays untouched, is the v1 JSON with `version: 2` and a
  default `v2` object. The book stage is derived from the existing journal
  `count` (`02 §6.1`); `found` is seeded from the saved zone, bait and band. Boat
  fields are untouched (ids `jon`, `rowboat`, `sail`, `pontoon`). The Bot name comes from the schedule seed.
  Mode is `cozy`. Story chapter is 0, but the **prologue is marked seen** for any
  save with catches, so a veteran isn't asked to set a first line. Unlocks: Cedar
  is open. Guardian sightings carry over.
- **Exactly once:** each reward (quest, story, legendary record, book stage-up) has
  a claim key in the ledger. Credit and reward are written in the same save
  transaction. Re-entering a scene never re-grants.
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
  star reflections on water.
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

### 6.4 Boats (24) — `boatmesh.py`

The existing four handcrafted boats stay. Eight family generators produce the
remaining 20 from parameters (length, beam, sheer, transom, deck layout,
accessories). Every boat needs a collision footprint and draft (existing rule).
Cat NPC boats reuse the same generators.

### 6.5 UI as a book

- Paper and ink palette, stitched tabs (Fish · Book · Ripples & Keepsakes · Story ·
  Watch), stamps for stages, a watercolor fish grid, and a title-page ceremony
  for each rename.
- Dialogue: portrait left, name ribbon, text with a type-on effect (instant with
  reduced motion), and choices as tabs.
- Every screen works at 1280×720 and up, with three text sizes, and keyboard,
  gamepad and mouse navigation.

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
- **Review and merge:** follow `docs/PR-REVIEW-POLICY.md` (the required reviewer and
  the 30-minute wait are owner policy, not ticket choices).
- **Definition of Done:** acceptance criteria met; CI green; docs updated; no new
  warnings in `--selftest`; benchmark under budget when relevant; saves migrate.
