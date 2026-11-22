# Trotline Purridise — V1.0 Build Tickets

Each ticket below is mirrored as a GitHub issue titled `[V1-xx] …` (V1-01 = #29 …
V1-44 = #72). The tracking issue is #73.
**Model tags:** `model:opus-sol` for visual, design or narrative-intensive work;
`model:luna-haiku` for systems, data, tests and plumbing. Every ticket also carries
the `v1.0` label and one area label. The last three tickets (V1-42 to V1-44) are
second-pass refinements and must run after everything else is merged.

Common to every ticket (don't repeat in PRs): follow `06 §0` and `06 §10`. CI
`gameplay-tests` must pass. Update `docs/v1/` when a rule changes. Saves must
migrate.

## Phase map

| Phase | Tickets | Parallelism |
| --- | --- | --- |
| 0 Foundations | 01–06 | 01 and 02 first; 03–06 in parallel after 01 |
| 1 Core loop | 07–16 | After 01–03 |
| 2 Bot | 17–20 | After 01, 02 |
| 3 Boats | 21–22 | After 01 |
| 4 Lakes & species | 23–28 | 23 first; then 24–28 in parallel |
| 5 Cats & narrative | 29–37 | 30, 31 first; 29 any time after 22 |
| 6 Audio, verification, release | 38–41 | Late |
| 7 Second pass | 42–44 | Last, after all others are merged |

---

### V1-01 (#29) · Content v2 data pipeline and validator · `model:luna-haiku` · data
**Goal:** move gameplay data into validated JSON without changing behavior.
**Source:** `06 §2`, `03`.
**Scope:** create `fishing/assets/content_v2/` with `species.json` (existing 36
only, new columns from `03 §1.2`), `baits.json` (existing 5), `boats.json` (existing
4 + traits), `lakes.json` (briar, cedar). Make `data.py` load them while keeping
the `SPECIES`, `SPECIES_BY_ID`, `BAIT_MATCH`, `ZONE_MATCH`, `CEDAR_FISH` and
`LINE_TIERS` API. Extend `content.py` validation (collect-all-errors) for the v2
files, including the count checks, which turn on when lake data exists.
**Acceptance:** every existing test passes unchanged. `python -m fishing.content`
validates v1 + v2. A deliberately broken fixture reports all errors with file
and id. Fishing outcomes are bit-identical for a seeded 1,000-step simulation
before and after the change (add this test).
**Depends on:** none.

### V1-02 (#30) · Save v2, platform save path, migration and backup · `model:luna-haiku` · persistence
**Goal:** introduce the v2 save envelope without losing any v1 data.
**Source:** `06 §3`, `02 §20`.
**Scope:** `savepaths.py` (SDL pref path, `--save` override); v1 → v2 migration
with a timestamped backup; the `v2` object with defaults; preserve unknown fields;
exactly-once claim keys for all new reward kinds; the pending/done scene flag.
Commit fixtures (fresh, mid-game, V3 complete, Guardian seen).
**Acceptance:** each fixture loads, migrates and round-trips with every v1 field
equal. The backup is written once. A second launch doesn't re-migrate. A corrupt
v2 file falls back to the newest backup with a toast. Tests live in
`test_save_v2.py`.
**Depends on:** none.

### V1-03 (#31) · World pauses in menus; clock audit · `model:luna-haiku` · core
**Goal:** reading never costs game time.
**Source:** `02 §3`, `06 §4`.
**Scope:** add a `Session.world_running()` predicate. Pause in dialogue, shops,
journal/book, chart, pause, help, settings, kitchen, scenes and focus loss. Keep T
time-scale and offline catch-up as they are. Add catnap's bulk-advance hook (no
UI yet).
**Acceptance:** a test opens each menu for 300 real seconds of simulated frames and
asserts the game clock, NPC schedule, line soak and quest timers didn't change.
Offline-soak tests still pass.
**Depends on:** V1-01.

### V1-04 (#32) · Rename to *Trotline Purridise* · `model:luna-haiku` · core
**Goal:** a consistent player-facing title.
**Source:** `01 §1`.
**Scope:** window title, title screen text, help pages and the README heading.
"Little Briar" stays as the lake name. The GitHub repository is
`AventurineDream/Trotline-Purridise`; the Python import package remains `fishing`.
Keep the SDL organization identifier `TrotLineSim` for the user-data namespace and
use the `TrotlinePurridise` app name specified in `06 §3`.
**Acceptance:** no player-facing "Little Briar" refers to the game, verified by a
grep test over UI strings. Screenshots of the title screen are attached.
**Depends on:** none.

### V1-05 (#33) · Gamepad support and new key bindings · `model:luna-haiku` · input
**Goal:** play fully on a controller; add Z, G and K.
**Source:** `02 §16`.
**Scope:** `gamepad.py` (SDL GameController: hot-plug, deadzones, the throttle
lever on the stick and triggers). Menu navigation, the device-aware prompt
glyphs, a remapping table saved in settings, and the new actions (catnap, tool,
galley) wired as no-ops until their tickets land.
**Acceptance:** a scripted input test drives a full loop (set line, scout, check,
shop, travel) using only virtual pad events. Keyboard behavior is unchanged
(existing input tests pass). Held-direction release rules still hold.
**Depends on:** V1-03.

### V1-06 (#34) · Settings and accessibility · `model:luna-haiku` · ui
**Goal:** the options in `02 §17`.
**Source:** `02 §2`, `02 §17`.
**Scope:** a settings screen from Pause: mode (Cozy/Old Salt, applied by V1-14),
text size (3), dyslexia-friendly font option (bundle an OFL font), reduced motion,
haul speed, captions, the volume split, collar visibility, and key remapping
(uses V1-05). Saved in `v2.settings`.
**Acceptance:** each option persists and has a visible effect, with a test per
option where measurable. The text-size max fits every existing screen at
1280×720 (layout test, like `test_ui_layout.py`).
**Depends on:** V1-02, V1-05.

### V1-07 (#35) · Line capacity per boat and split baiting · `model:luna-haiku` · fishing
**Source:** `02 §5.1`, `06 §5`, `03 §6`.
**Scope:** replace the global `MAX_LINES` with `boat.lines` (it limits new
deployments only). Add `bait_sections` (1–3) to `SetLine`, plus the set-line UI to
split hooks, the hook-to-section mapping, and the check list showing each section.
Load legacy lines as one section.
**Acceptance:** seeded tests for section mapping and capacity edge cases (a boat
switch with over-capacity lines keeps them). V3 quest bait checks treat a line as
matching if **every** section uses the required bait (documented in the
contract mirror).
**Depends on:** V1-01, V1-21 (data only; stub capacities until it lands).

### V1-08 (#36) · Catch resolution, Keep/Release, Treasured, Protected · `model:luna-haiku` · fishing
**Source:** `02 §5.3`, `02 §5.5`.
**Scope:** book credit before disposition, and the per-catch disposition state. A
Treasured flag protects fish from cooking and bulk sale. Protected species are
auto-released with a line. Livewell-full pre-selects the smallest non-Treasured
fish for release. All "spoiled" copy becomes "got away".
**Acceptance:** a test matrix of standard, shiny, protected and legendary
(stubbed) fish with a full and an empty livewell. Release gives identical book
credit. The V3 `fish_livewell` objective still counts only kept fish.
**Depends on:** V1-01, V1-11 (credit hook may be stubbed first).

### V1-09 (#37) · Haul view: running the line · `model:opus-sol` · ui
**Goal:** make checking a line the tactile heart of the game.
**Source:** `02 §5.4`, `06 §6.3`.
**Scope:** a first-person haul presentation. Paws pull the line, hooks rise from
the water in sequence with drips, ripples and line tension, and each result
animates (empty, bait kept, bait taken, fish). Fish surface with their mesh, then
the card pops (*NEW!*, *Stage up!*, shiny sparkle). Speeds: Normal, Quick,
Instant, with hold-E to speed up 3×. The summary screen carries Keep/Release
toggles. Works in the software renderer with simplified visuals.
**Acceptance:** `--shots` frames for mid-haul, a fish card, a shiny and the
summary, on GPU and software renderers. A 24-hook haul at Normal takes ≤ 8 s.
Reduced motion removes sway and splash particles. No world time passes (V1-03).
**Depends on:** V1-08, V1-10.

### V1-10 (#38) · Parametric fish meshes and watercolor fish cards (existing 36) · `model:opus-sol` · art
**Source:** `06 §6.3`, `03 §1`.
**Scope:** `fishmesh.py` with family presets, per-species `look` parameters for
all 36 existing species, the haul mesh, the 512×256 card render with the paint
shader and paper, the 128×64 thumbnail, shiny palette variants, and LRU caches.
Software-renderer fallback cards (flat watercolor approximation).
**Acceptance:** a contact sheet of all 36 cards + shinies via `--shots`, each
species recognizable (catfish barbels, gar snouts, sunfish profiles, and so on).
Cache stays ≤ 25 MB at 48 entries. Card generation ≤ 30 ms each on GPU.
**Depends on:** V1-01.

### V1-11 (#39) · Book system: stages, What we heard / What we found · `model:luna-haiku` · book
**Source:** `02 §6`, `05 §8`.
**Scope:** `book.py` stage thresholds (0/1/3/5/10); attributed rumor storage;
appended observations; stage-up events and toasts ("Shall we add that?");
journal → book migration; title states; legendary pages; dream-clue slot.
**Acceptance:** tests for every threshold, for migration from v1 counts, for
rumor immutability, and that a stage-up claim is exactly once.
**Depends on:** V1-01, V1-02.

### V1-12 (#40) · Book UI · `model:opus-sol` · ui
**Goal:** the journal becomes the inherited book.
**Source:** `02 §6`, `06 §6.5`.
**Scope:** a paper-and-ink book with tabs Fish · Book · Ripples & Keepsakes ·
Story · Watch. The species grid with thumbnails and silhouettes; an entry page
with the two columns, stamps and card art; watch cards; the Trophy page; the
Keepsake shelf; title-page ceremonies. Keyboard, gamepad and mouse navigation; all
three text sizes.
**Acceptance:** `--shots` of each tab at both text-size extremes; navigation tests;
the existing Lake Whispers & Ripples content is reachable in the new layout.
**Depends on:** V1-10, V1-11.

### V1-13 (#41) · Shinies and the Shiny Tracker · `model:luna-haiku` · book
**Source:** `02 §8`, `06 §5`.
**Scope:** a roll at catch creation (1/64), saved on the `Catch`; the tracker
(Verified species only, one at a time); the pity counter at 50 with a per-species
counter that survives target switches; the 3× sale price; Treasured default; a
trophy-rail hook.
**Acceptance:** seeded test that 10,000 tracked catches never exceed 50 without a
shiny; untracked frequency within ±10% of 1/64; save round-trip of counters.
**Depends on:** V1-08, V1-11.

### V1-14 (#42) · Modes, catnap and Old Salt needs · `model:luna-haiku` · comfort
**Source:** `02 §2`, `02 §4.1`.
**Scope:** `comfort.py` (Cozy/Old Salt state and the switch rules), Z catnap (2
game h bulk advance with a skippable fade), Rested and the dream-clue, Drowsy and
Peckish effects, prompt throttling (10 real min) and snooze, the tow fee rule
(free in Cozy). A mode-select step on New Game.
**Acceptance:** a Cozy invariant test (no needs effects ever). Old Salt timeline
tests at 16 h, 20 h and 24 h. Switching modes clears or starts counters correctly.
The tow never fails with $0. A fuzz test shows no stranding.
**Depends on:** V1-03, V1-11.

### V1-15 (#43) · Pantry, kitchen, dishes, buffs and recipe baits · `model:luna-haiku` · comfort
**Source:** `02 §4.2–4.4`, `03 §2`, `03 §5`.
**Scope:** pantry inventory and host sales; a Kitchen tab at landings and K on
galley boats; food-group fish selection that excludes Treasured, protected and
legendary fish; 10 dishes and their buffs (single active, persistent haul
counts); recipe-bait cooking; dish cards ($40) after a chapter.
**Acceptance:** a test per buff effect, a test that buffs don't stack, a test that
a shiny is never auto-selected, and save round-trip. Base fishing rates are
unchanged with no buff.
**Depends on:** V1-08, V1-14.

### V1-16 (#44) · Calendar, Lake Days, weather-window planner, cookout · `model:luna-haiku` · world
**Source:** `02 §5.6`, `03 §3`, `03 §8`, `06 §5`.
**Scope:** `calendar.py` (weekday from game day), Lake Day modifiers, the 7-day
seeded weather plan with the legendary coverage guarantee, the Sunday cookout
event (cats gather; bring a fish to get a pantry gift), Bot's weather invitation
(once per day, only when true), and the journal week view.
**Acceptance:** over 1,000 seeded weeks, every legendary's weather window occurs
within 3 game days of eligibility (the single bound in `02 §3`, rule 6). Lake Day multipliers apply only on their day.
The plan is reproducible after reload and lake switches.
**Depends on:** V1-01, V1-23 (lake list; stub with briar/cedar first).

### V1-17 (#45) · Bot identity, shells and collar state · `model:luna-haiku` · bot
**Source:** `01 §6`, `02 §10`, `03 §7`.
**Scope:** a deterministic `Word-###` name from the schedule seed (migration
included), shell unlock and swap at landings, tool purchase gating by the shells
earned, collar stages and knot choice, and the `{BotName}` placeholder in
dialogue.
**Acceptance:** name stable across reloads; 12 prefixes (with Rivet, not Pebble);
the swap preserves notes and progress; the existing Bot scouting tests pass.
**Depends on:** V1-02.

### V1-18 (#46) · Bot shell models, collar and chimes · `model:opus-sol` · art
**Source:** `03 §7`, `02 §18`, `06 §6`.
**Scope:** procedural models for the five shells, sitting on the bow and
animating during scouting; the wool collar on every shell, reflecting the knot
choice; per-shell chime synthesis plus captions; the Astral glow at night; a
software-renderer version.
**Acceptance:** a `--shots` turntable of every shell, with and without the collar,
day and night. Each chime is distinct and captioned. RAM delta ≤ 10 MB.
**Depends on:** V1-17.

### V1-19 (#47) · Bot tools I: Sonar Grid and Reed Anchor (+ reeds zones) · `model:luna-haiku` · bot
**Source:** `02 §5.2`, `02 §10.2`.
**Scope:** the Sonar Grid chart overlay (ground and contours of scouted zones,
needs the finder); the `reeds` zone archetype (crawl speed, no line setting without
the anchor or the `reed_dugout`); the Reed Anchor. The Briar Reed Passage region
is added to Briar's zone data and chart.
**Acceptance:** tests for the reeds speed cap, the set-line gate and the overlay
data; the chart `--shots` frame shows the Reed Passage.
**Depends on:** V1-17, V1-23.

### V1-20 (#48) · Bot tools II: Wave Chime, Thermocline Scanner, Zero-G Winch · `model:luna-haiku` · bot
**Source:** `02 §5.2`, `02 §10.2`, `06 §5`.
**Scope:** chime (G, radius, duration, cooldown, `surface` multiplier);
thermocline `d(h)` per lake with the scanner HUD and report line; the `cold` tag
multiplier; Nebula current flow fields and line drift; the winch hold and
`current` multiplier.
**Acceptance:** unit tests of `d(h)` bounds, the chime window, drift capped at
60 m, and that winch lines never move. Without tools, every species remains
catchable (a rate floor test).
**Depends on:** V1-17, V1-23.

### V1-21 (#49) · Boats: data, traits, shop tiers and unlocks · `model:luna-haiku` · boats
**Source:** `02 §9`, `03 §6`.
**Scope:** load 24 boats from `boats.json`; trait effects (shallow, silent,
galley, hammock, trophy_rail, wind_steady, ice_hull, glow); tier unlock gates by
story chapter; the T8 shop exclusivity; display renames for the existing 4; the
pontoon gets +1 line and hammock.
**Acceptance:** existing boat physics and collision tests pass unchanged; each
trait has a test (hammock: nap at idle without anchoring; other boats need
anchor or dock); a shop listing test per chapter state; a test that the price of
each tier's cheapest new boat ÷ its unlock-stage income midpoint is between 3 and
6.
**Depends on:** V1-01.

### V1-22 (#50) · Parametric boat families (20 new hulls) · `model:opus-sol` · art
**Source:** `06 §6.4`, `03 §6`.
**Scope:** eight family generators; meshes, collision footprints and drafts for
the 20 new boats; handling archetypes (pole/paddle, console, inboard, starlight
glide); first-person cockpit views; paint support; the same generators for NPC
boats.
**Acceptance:** a `--shots` lineup of all 24 boats plus a cockpit view of each
family; `boatchecks.py` collision coverage for every boat; the benchmark cycles
all 24.
**Depends on:** V1-21.

### V1-23 (#51) · Five-lake framework and Briar Reed Passage · `model:luna-haiku` · world
**Source:** `01 §4`, `03 §8`, `02 §14`.
**Scope:** `lakes.json` for 5 lakes (labels, zones, palettes stubs, Lake Days);
the zone archetypes `reeds`, `springs`, `current`; per-lake zone labels; travel
unlocks by story state; travel captions; placeholder flat lakes for flathead,
crater and nebula, so systems can build before the art tickets land.
**Acceptance:** travel works between all 5 (placeholders); lines must be pulled
first (existing); existing Cedar and Briar charts are unchanged apart from the
Reed Passage.
**Depends on:** V1-01.

### V1-24 (#52) · Species data for 108 new fish · `model:luna-haiku` · data
**Source:** `03 §1.3–1.6`, `05 §8`.
**Scope:** add all rows exactly as tabled (tier defaults, baits, zones, depth,
weather affinity, tags, folk names, rumors, food group, shiny palette); new baits
(dough, roe, grub, stardust) in shops per lake; the Cedar-only rule.
**Acceptance:** the content validator's count check (144); for every species, at
least one reachable zone, bait and time with rate ≥ 0.5 × tier default (an
automated catchability test); the existing 36 species are unchanged.
**Depends on:** V1-01, V1-23.

### V1-25 (#53) · Flathead Alpine Lake environment · `model:opus-sol` · art/world
**Source:** `01 §4`, `06 §6.1`, `03 §8`.
**Scope:** `lakegen.py` parameters for Flathead (outline, glacial trench, gravel
reefs, snowmelt inlet, larch snags, pondweed bay); terrain and depth; snow-capped
ridges; larch and spruce foliage (the Larch Gold variant); palette and sky; snow
mist weather; Glacial Peak Outpost marina with a stove-smoke chimney; ambience
hooks (loons, wind in larch).
**Acceptance:** `--shots` at dawn, noon, dusk, night and in snow mist; collision
and zone checks pass; lake load ≤ 6 s on GPU; RAM within the `06 §7` lake budget.
**Depends on:** V1-23.

### V1-26 (#54) · Crater Caldera environment · `model:opus-sol` · art/world
**Source:** `01 §4`, `06 §6.1`.
**Scope:** a round, steep caldera with sheer rim walls; the cinder isle with an
obsidian shore; drowned pines; moss gardens; pumice shelf; thermal springs with
steam and bubbles; very clear indigo water with deep absorption; layered caldera
fog that lifts; Caldera Rim Dock; the survey marker (for chapter 4); the clear-night
sky reflection effect needed for the chapter 4 → 5 transition.
**Acceptance:** `--shots` at dawn fog, clearing, noon, dusk and a clear night with
the full sky reflection; checks and budget as V1-25.
**Depends on:** V1-23.

### V1-27 (#55) · Starlight Nebula Lagoon environment · `model:opus-sol` · art/world
**Source:** `01 §4`, `06 §6.1`, `03 §1.6`.
**Scope:** a void bed with a violet depth gradient; floating lily-drift islands;
crystal kelp; light-reeds; meteor reefs; visible astral current lanes; a nebula
skybox with the Rising/Bright/Fading/Deep palette; aurora weather; star
reflections; Cosmic Drift Station; the travel transition (the boat tips into
starlight) shared with Crater.
**Acceptance:** `--shots` for each time band and the aurora; currents are visible
and match the flow field; checks and budget as V1-25.
**Depends on:** V1-23, V1-20 (flow field data).

### V1-28 (#56) · Fish looks for 108 new species and 12 legendaries · `model:opus-sol` · art
**Source:** `06 §6.3`, `03 §1`, `03 §3`.
**Scope:** `look` parameters for every new species (the real species must read
true to life; the fictional caldera and cosmic species must be striking but
consistent with the family style); bespoke legendary sets with an underwater idle;
new family presets as needed (sculpin, sturgeon, eel, salamander, ray, cosmic).
**Acceptance:** contact sheets per lake + legendaries via `--shots`; no two
species within a lake share a silhouette and palette pair (automated perceptual
check on thumbnails, plus a manual review note in the PR).
**Depends on:** V1-10, V1-24.

### V1-29 (#57) · Cats: parametric rig, coat shader, attire, LOD, portraits · `model:opus-sol` · art
**Source:** `02 §11.2`, `06 §6.2`, `04`.
**Scope:** `catmesh.py` rig and parameters; the coat-pattern shader (9 patterns);
the attire kit; 5 poses + procedural idle; LOD0/LOD1/impostor; portrait renders;
**visible NPCs on their boats at anchors** with chart pins; wave on approach; the
first-person Skipper paws and calm-water reflection; software-renderer versions.
**Acceptance:** a `--shots` lineup of all 52 cats with portraits; NPCs visible in
the world on both existing lakes; ≤ 14 resident actors within 150 MB; hailing
range and behavior are unchanged.
**Depends on:** V1-22 (NPC boats), V1-30 (roster data, can stub).

### V1-30 (#58) · Roster v2 and the 52-cat schedule · `model:luna-haiku` · npc
**Source:** `02 §11.3`, `04 §5`.
**Scope:** `npcs.json` for all 52 cats (appearance params as provided by V1-29's
schema, boat, slot, anchor, quest ids); the schedule (3 day + 1 night per lake,
round-robin coverage every 3 days, pins for active needs, travelers); migrate the
V3 `day_npc_by_lake`; new anchors per lake.
**Acceptance:** every encounter appears within any 3-day span (property test
over 10,000 seeds); pins honored; deterministic across reload and lake switch;
existing V3 schedule tests are updated to the new rule with a documented
migration.
**Depends on:** V1-01, V1-02, V1-23.

### V1-31 (#59) · Quests v2: objective types, friendship, rewards · `model:luna-haiku` · quest
**Source:** `02 §12`, `04`.
**Scope:** objective types `catch_species`, `book_stage`, `cook_dish`, `catnap`,
`tool_use`, `wait_weather`, `settle`, `talk_to`, `attend_event`, every extended
field in `02 §12.3` (`min_tier`, `area_id`, `waypoint_ids`, `windows`,
`bait_id`, `shell_id`, `then_weather`, cross-lake `visit_zones`), multi-step
objectives and `requires`; named areas and waypoints from `lakes.json`; quest B unlock the day after A; turn-in at the giver or host;
Stranger/Acquaintance/Friend states; reward kinds (cash, Ripple, keepsake,
recipe, dish card, item, shell, unlock) via the claim ledger; letters via Pounce.
**Acceptance:** a test per objective type (event-driven, after-acceptance only,
exactly-once); the 12 V3 quests are unchanged; turn-in at the host is
acknowledged by the giver's return line.
**Depends on:** V1-02, V1-30.

### V1-32 (#60) · Author Briar + Cedar content v2 (new cats, quest B, recopied lines) · `model:luna-haiku` · content
**Source:** `04 §4.1–4.2`, `05 §4.1–4.2`, `05 §6.1–6.2`, `05 §7–9`.
**Scope:** transcribe exactly into `content_v2` JSON: the new cats (Marigold, Old
Gus, Biscuit, Hank Mudpaw, Belle Pecan, Señora Luz, Kit); quests A and B; quest B
for the 10 V3 cats; the recopied Maeve lines; host states; rumors; Ripples 11–17;
keepsakes; letters. Journal `obj:` strings as written.
**Acceptance:** the validator passes; every dialogue node is reachable; a playthrough
test completes every Briar and Cedar quest via scripted events.
**Depends on:** V1-31.

### V1-33 (#61) · Author Flathead + Crater + Nebula content v2 · `model:luna-haiku` · content
**Source:** `04 §2–4.5`, `05 §4.3–4.5`, `05 §6.3–6.5`, `05 §7–9`.
**Scope:** the same as V1-32 for the remaining three lakes, the three new hosts'
errands, and the travelers.
**Acceptance:** as V1-32, for all three lakes.
**Depends on:** V1-31, V1-23.

### V1-34 (#62) · Story system: prologue, five chapters, ending · `model:luna-haiku` · story
**Source:** `01 §5`, `02 §13`, `05 §1–3`.
**Scope:** story state and steps; the prologue for new games (with a skip for
migrated saves); chapter steps with pinned NPCs; borrowed tools for ch. 1 and 3;
rewards and unlocks; the collar beats; the settle-in logic (accumulate, pause,
"Watch together"); the ending and book retitle; scenes as pending/done; story
journal entries.
**Acceptance:** a scripted playthrough from a new save to the credits in the test
harness; interrupting at every scene and reloading replays without duplicate
rewards; the story is never time-limited.
**Depends on:** V1-31, V1-17, V1-19, V1-20, V1-23.

### V1-35 (#63) · Story scene staging · `model:opus-sol` · narrative/art
**Source:** `05 §1–3`, `02 §13.5`.
**Scope:** staging, cameras and presentation for the prologue arrival, the book on
the counter, collar knitting, the collar slipping in the wind, the knot choice,
the fog lifting, the reflection-deepening travel, the three Settle-In cues, the
Star-Whale rise, the stroke-by-stroke "Draw it" reveal, and the ending ceremony
and credits roll. Every scene is skippable on repeat and follows the reduced
motion setting.
**Acceptance:** a capture of each scene as a `--shots` sequence (keyframes); a
playtest note in the PR on timing; the Settle-In cues are readable without
audio.
**Depends on:** V1-34, V1-27, V1-29.

### V1-36 (#64) · Legendary system · `model:luna-haiku` · legendary
**Source:** `02 §7`, `03 §3`, `06 §5`.
**Scope:** `legendary.py` with requirement evaluation and watch cards (clue source,
revealed requirements, live ✓/✗, next window from the planner); guaranteed hook;
records; forced release; weekly repeat; the Spillway day-one exception;
integration with the existing Guardian (witnessed).
**Acceptance:** a test per legendary that meeting all requirements in-window hooks
on the first haul and missing any one doesn't; the watch card states match;
Spillway is catchable on a fresh save with a heavy line.
**Depends on:** V1-16, V1-24, V1-15 (recipes).

### V1-37 (#65) · Legendary encounter presentation · `model:opus-sol` · art
**Source:** `02 §7.2`, `06 §6.3`.
**Scope:** the calm encounter scene (the water stills, the line hums, the fish
surfaces beside the boat with its idle animation), the book photo frame, the
trophy replica model, the winch variant, and a bespoke beat for the Fire-Lizard
("not a fish!") and the Star-Whale (shared with V1-35).
**Acceptance:** `--shots` for each of the 10 caught legendaries; scene length 4–6 s;
skippable after the first time.
**Depends on:** V1-36, V1-28.

### V1-38 (#66) · Audio: lake ambiences, music motifs, horn, chimes · `model:opus-sol` · audio
**Source:** `02 §18`.
**Scope:** procedural ambience for Flathead, Crater and Nebula; sparse music motifs
per lake for dawn, dusk and story moments; the hail horn; Lake Day and cookout
cues; legendary and finale cues; captions for everything; mixer categories from
V1-06.
**Acceptance:** an audio-coverage check in the benchmark; caption coverage test;
RAM within the audio budget; mute (M) still silences everything.
**Depends on:** V1-06, V1-23.

### V1-39 (#67) · Verification: benchmark, budgets, invariants · `model:luna-haiku` · verify
**Source:** `06 §7–9`.
**Scope:** extend `--benchmark` and `--selftest` coverage (5 lakes, 24 boats, 156
cards, 52 cats, all tabs, every weather, a legendary scene); per-subsystem memory
accounting; p95 frame time; the Cozy invariant fuzz; determinism suite; a
catchability report.
**Acceptance:** the benchmark JSON includes every coverage item and per-subsystem
MB; CI runs the software selftest within the 15-minute job limit (split jobs if
needed, without removing the required `gameplay-tests` check).
**Depends on:** V1-25 to V1-37 (incrementally; land early and extend).

### V1-40 (#68) · Release packaging and save promise · `model:luna-haiku` · release
**Source:** `02 §20`.
**Scope:** a one-command offline package build (PyInstaller or equivalent) for
Linux, Windows and macOS with bundled SDL2/SDL2_ttf and fonts; a clone setup
script tested on a fresh machine; saves in the platform user-data directory; a
release checklist doc.
**Acceptance:** the CI artifact launches the game in `--selftest --software` from
the package without Python installed (Linux at minimum); a fresh install plus an
existing v1 save migrates.
**Depends on:** V1-02.

### V1-41 (#69) · In-game help and player docs · `model:luna-haiku` · docs
**Source:** all of `02`.
**Scope:** update the help pages (H) for every new system and the README player
section; key and pad glyph tables; a first-hour tips page.
**Acceptance:** each new key and system has a help entry; help pages fit at every
text size (layout test).
**Depends on:** V1-05 to V1-36.

### V1-42 (#70) · Second pass: graphics · `model:opus-sol` · polish
**Goal:** make every lake look like a key-art screenshot.
**Scope:** review `--shots` for all lakes, times and weathers and fix composition,
lighting, water color, fog layering, foliage density, shoreline clutter, cat and
boat silhouettes, fish card consistency, and night readability. Fix any
software-renderer regressions. Re-verify the memory budget.
**Acceptance:** a before/after contact sheet in the PR; benchmark p95 and RAM within
budget; no new visual test failures.
**Depends on:** all of V1-01 to V1-41 merged.

### V1-43 (#71) · Second pass: UI and UX · `model:opus-sol` · polish
**Goal:** every screen is calm, legible and kid-friendly.
**Scope:** a full pass on book, dialogue, haul, shop, kitchen, settings, chart,
help and HUD: typography hierarchy, spacing, iconography, focus states, gamepad
flow, the 1280×720 minimum and text sizes, contrast (WCAG AA for text),
colorblind-safe markers, caption timing, and copy consistency with `05 §0`.
**Acceptance:** a screenshot matrix (screen × text size × input device); an
accessibility checklist in the PR; no layout test failures.
**Depends on:** V1-42 can run in parallel; all of V1-01 to V1-41 merged.

### V1-44 (#72) · Second pass: pacing and economy · `model:opus-sol` · polish
**Goal:** the first hour delights, and the 10–12 h story and 50 h book feel right.
**Scope:** build a headless pacing simulator (a scripted "attentive player" bot)
that reports time-to-first-catch, chapter durations, income per game day per stage,
book stage curve and legendary time-to-eligible; tune `03` numbers (rates, prices,
boat costs, quest cash, dish effects) to the `02 §1` and `02 §15` targets; review
prompt frequency and Bot bark density; adjust the onboarding.
**Acceptance:** the simulator report in the PR shows every target band met;
updated `03` tables in the same PR; no cozy invariant violations.
**Depends on:** all of V1-01 to V1-41 merged.
