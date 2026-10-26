# Trotline Purridise — V1.0 Gameplay Specification

*Final V1.0 beta · supersedes `V1_0_GameplayNarrativeUpdateSpec.md` (Gemini).*
*Every number here is a starting value for playtesting. Change numbers in the
data tables (`03`), not in code constants scattered across modules.*

"Existing" means already in the build on `main` (two lakes, 36 fish, 4 boats, V3
quests, Guardian, Trinidad Cove). "New" means V1.0 work. Every new rule has an
owner ticket in `07-TICKETS.md`.

---

## 1. Core loop and session shape

**The loop (existing, deepened):** choose water → bait and set trotlines → explore,
scout with Bot, visit cats → come back and **run the line** → keep, release or
cook the catch → sell, upgrade, travel.

**What V1.0 adds to each beat:**

| Beat | Existing | New in V1.0 |
| --- | --- | --- |
| Choose water | 2 lakes, 8 zones each | 5 lakes, up to 10 habitat zones, a weekly lake calendar, Bot's weather invitations |
| Bait & set | 5 baits, 3 line tiers, one bait per line | 9 baits, **split baiting** (up to 3 bait sections per line), bait recipes for legendaries |
| Wait | Soak while exploring; time scale | Cats to visit, catnaps, cooking, Bot tools, legendary watch cards |
| Run the line | Check menu lists the hooks | **Hand-over-hand haul**: the line rises hook by hook, with a fish card for each catch (§5.4) |
| Resolve | Livewell or spoil | Book credit first, then Keep / Release / Cook; Treasured fish are protected |
| Progress | Money → gear, boats | Book stages, 24 boats as sidegrades, Bot shells and tools, friendships, story |

**Session targets (real time at 1×):**

- First catch in the first **3 minutes** of a new game.
- A satisfying "sit-down" session is **20–40 minutes**: about one to two game days,
  one cat's quest, and one book stage-up.
- Story: chapter 1 ≈ 60–90 min, 2 ≈ 2 h, 3 ≈ 2.5 h, 4 ≈ 2.5 h, 5 ≈ 1.5 h.
  The main story totals **10–12 h**.
- The Pescapedia (all 144 verified) takes about **50 h**. All shinies, all
  keepsakes and all 24 boats are a long tail of **100 h+**, always optional.

---

## 2. Modes

Mode is chosen on **New Game** (default **Cozy**), saved, and changeable at any
time from Pause → Settings. Both modes have identical story, collection, shops and
travel.

### 2.1 Cozy (default)

No penalties of any kind. Naps and meals exist as **positive choices** (§4). Bot
never warns, only invites. The tow (R) is free.

### 2.2 Old Salt (opt-in)

For players who want light routine. It is still never stranding, never losing.

| Need | Rule | Consequence | Never |
| --- | --- | --- | --- |
| **Energy** | Counts awake game hours since the last nap or sleep | 0–16 h: fine. 16–20 h *Drowsy*: hauling 25% slower, the screen edges soften, Bot offers a nap once. Over 20 h: the Skipper dozes off. The boat anchors safely and a 2 h catnap runs where they are | No blackout. No extra spoilage beyond the normal rule. No lost lines |
| **Hunger** | Game hours since the last meal (any dish, or a Kibble Tin snack) | Over 24 h *Peckish*: boat top speed −20% until the Skipper eats | No sickness. No forced tow. No loss of steering or hauling |
| **Tow** | R, as today | Fee = min(cash, $25 + 2% of the active boat's price). Any shortfall is waived | Never blocks the tow. Never empties the livewell |

**Mode switching:** entering Cozy clears Drowsy and Peckish at once. Entering Old
Salt starts fresh counters at 0. Nothing is retroactive. Every delayed needs effect
checks the **current** mode when it fires.

**Prompts:** at most one needs prompt per 10 *real* minutes of active play, and
each can be snoozed ("Later") for 30 real minutes.

---

## 3. Clock rules (both modes)

1. **The world pauses in menus.** Dialogue, shops, kitchen, journal and book,
   chart (Tab), pause, help, settings and window-focus loss all freeze world time,
   needs, drift, NPC schedules and encounter timers.
2. **Time scale (T)** stays as today (1×/3×/6×/12× while idle or anchored).
3. **Catnap (Z)** is the only way to skip time on purpose. It advances 2 game
   hours. The simulation runs accelerated with a skippable dusk-to-dawn style
   fade, and any key ends it early.
4. **Offline soak (existing)** stays: lines keep fishing for up to 6 real hours
   while the game is closed. Needs, NPC timers and quest durations do **not**
   advance offline.
5. **Windows are generous.** No objective, legendary window or event lasts less
   than **120 game minutes**. Every recurring window shows its next occurrence in
   the journal.
6. Legendary and story windows are generated so an eligible one starts within **3
   game days** of becoming eligible. This is the single bound used by the weather
   planner (`03 §3`) and its test (V1-16).

---

## 4. Comfort: naps, pantry, cooking

### 4.1 Catnap (Z) — new

- On any boat: available when anchored or docked.
- On boats with the **hammock** trait: also available anywhere while idling at zero
  throttle, without anchoring. This is the trait's whole benefit, and V1-21 tests
  it.
- Advances 2 game hours (§3.3). Lines soak normally.
- **Rested:** the first nap in any 6 game hours grants *Rested* for 6 game hours.
  Rested gives a **Bot dream-clue**: one unknown habitat lead for a species
  uncaught on this lake, written in the book under *What we heard* as "Bot's dream".
  Only one unread dream-clue can wait at a time. In Old Salt, a nap also resets
  Energy.
- Extra naps just pass time. Nothing is lost by napping or by never napping.

### 4.2 Pantry — new

Each host sells one specialty ingredient. A pantry holds up to 20 of each item.

| Item | Sold by | Price |
| --- | --- | --- |
| Briar herbs | Grandmother Whiskers | $4 |
| Pecan smoke chips | Doc Barnaby | $6 |
| Huckleberries | Captain Huckleberry | $8 |
| Mineral salt | Sora | $10 |
| Moon-milk | Astra-9 | $12 |
| Kibble Tin (snack; counts as a meal in Old Salt, gives no buff) | All hosts | $3 |

### 4.3 Cooking — new

- Cook at any landing **Kitchen** tab, or aboard a boat with the **galley** trait
  (K while anchored).
- A dish needs **one fish from a food group** (§03 Table 1 column *Food*) plus
  one pantry item. Weight doesn't matter. The smallest eligible fish is used unless
  the player picks one.
- **Never used:** legendary, protected, shiny or player-marked *Treasured* fish.
- The scene is a gentle steam-and-bowl vignette (2 s, skippable). It is never
  graphic.
- **Picnic buff:** a cooked dish gives its buff. Only one buff is active at a
  time; a new dish replaces the old one. Haul-count buffs persist across travel,
  menus and quitting.
- **Base fishing is balanced for no buff.** Buffs are pleasant, never required.

Dishes, buffs and recipes are in `03 §5`. Each host teaches two dishes. A dish is
learned in the host's chapter, or by buying its card for $40 after that chapter.

### 4.4 Bait recipes — new

Cook two baits plus one pantry item into a **recipe bait** (makes a dozen). Recipe
baits are the "key" for gated legendaries (`03 §3`) and work as ordinary bait for
everything else (each one takes the better match of its two parent baits).

---

## 5. Fishing

### 5.1 Lines (existing, extended)

- Tiers stay: std 12 / prem 18 / heavy 24 hooks.
- **Line capacity per boat** (`03 §6`) replaces the global `MAX_LINES = 5`
  (3–8 lines). Each boat's `lines` value is the number of deployed lines it can
  carry. It limits new deployments only; lines already set stay where they are
  after switching to a boat with less capacity.
- **Split baiting (new):** when setting a line, the player may divide its hooks
  into 1–3 equal sections, each with its own bait. Hook `i` uses section
  `i * section_count // hook_count`; the check list identifies the section and
  bait for each hook. Existing saves with one `bait` value migrate to one
  section.

### 5.2 Bite model (existing, extended)

`rate = species.rate × bait_match × zone_match × time_match × weather_match × depth_match × lake_presence × modifiers`

- New lakes use the same function, fed by `03` data.
- **Thermocline (new, Flathead and Crater):** each lake has a cold-layer depth
  `d(t)` that follows hour and weather (`06 §5`). Species tagged `cold` get
  ×1.0 inside `[d, d+6 m]` and ×0.35 outside. They stay catchable without the
  scanner. The scanner just shows `d`.
- **Currents (new, Nebula `current` zones):** lines drift slowly (0.5 m per game
  minute, capped at 60 m from the set point, never lost or tangled with another
  line). The Zero-G Winch holds lines in place and gives current-tagged species
  ×1.2.
- **Reeds (new, Briar and Nebula `reeds` zones):** dense beds slow boats to a
  crawl. Lines can be set there only with the Reed Anchor (Frog Bot).

### 5.3 Spoilage (existing, recopied)

The 13-game-hour rule stays. All player-facing copy changes from "spoiled" to "got
away": *"A fish waited a long while and wriggled free."* The mechanics are
unchanged. This is Cozy-safe because it is a missed chance, not a lost
possession.

### 5.4 Running the line — new

Checking a line (E) opens the **haul view**:

1. The line rises from the water hook by hook, about 0.25 s per hook at
   *Normal*. *Quick* is 0.1 s; *Instant* (accessibility) shows the summary
   at once. Hold E to speed up 3×.
2. Each hook resolves visually: empty, bait still on, bait taken, or **fish**. A
   fish shows its illustrated **fish card** (species art, weight, a *NEW!* or
   *Stage up!* ribbon, a shiny sparkle) for 1.2 s, or until a key is pressed.
3. At the end, a summary lists catches with **Keep / Release** toggles (§5.5) and
   **Rebait / Pull line** actions, as the existing check menu does.

A haul can't fail. Drowsy (Old Salt) only slows the hook cadence.

### 5.5 Catch resolution — new

Order is fixed. **Book credit is recorded first**, then disposition:

| Fish | Default | Options |
| --- | --- | --- |
| Standard | Keep | Keep, Release (identical credit) |
| Shiny | Keep, marked *Treasured* | Keep, Release, Sell later. Never cooked or bulk-sold unless the Treasured mark is removed |
| Protected | Release (forced) | No choice. A kind line explains why |
| Legendary | Release (forced, after a 4 s presentation) | A photo for the book, plus a trophy replica (cosmetic) |

If the livewell is full, the summary pre-selects Release for the smallest
non-Treasured fish and says so. It never discards silently.

### 5.6 Weather and the lake calendar — new

- Existing weather blending stays. New lakes add **snow mist** (Flathead),
  **caldera fog** (Crater) and **aurora** (Nebula) as weather states.
- The game uses a 7-day week (day 0 = Monday). The journal shows the week.
- **Lake Days:** each lake has two weekday specials in `03 §8` (e.g. Cedar's
  Thursday *Shad Run*: blue and channel catfish ×1.3 at night).
- **Sunday Cookout (17:00–20:00, every lake):** all of that lake's cats gather at
  the landing. Bring any one fish to share for a pantry gift and a chat line from
  each friend. Missing a cookout costs nothing; there is another next week.
- **Weather invitation:** at most once per game day, Bot points out a nearby zone
  with an active favorable condition and offers to mark it. If nothing is
  favorable, he says nothing.

---

## 6. The Book: Fishypedia → Pescapedia — new

### 6.1 Entry stages (per species)

| Catches | Stage | What the entry shows |
| --- | --- | --- |
| 0 | **Rumor** | Silhouette, folk name (e.g. "the Moon-Whisker"), one *What we heard* story with an actionable habitat lead |
| 1 | **Identified** | True name, illustration, and the conditions of that catch (zone, bait, time band, depth) under *What we found* |
| 3 | **Bait known** | The best bait, revealed |
| 5 | **Verified** | Full card: depth band (ft), time band, weather preference, Lake Day. Unlocks the Shiny Tracker for this species |
| 10 | **Mastered** | Gold stamp, plus a final line from the cat who told the rumor |

- Each stage-up shows a book toast at once (*"Shall we add that?"* — Bot; one
  key to accept and view, or it auto-accepts after 3 s).
- *What we heard* never changes once written. *What we found* only grows.
- The book holds 144 species pages + 12 legendary pages + a Ripples &
  Keepsakes section + the Story pages.
- **Book titles:** *Fishypedia* (start) → *The Book of Five Waters* (story ending)
  → *Pescapedia* (all 144 verified). Each change is a small ceremony at Briar
  Landing.
- The existing 36-species journal records (`count`, `best`, `zone`, `bait`, `band`)
  migrate directly. Existing counts set the starting stage.

### 6.2 Legendary pages

Verified on first record. They show a photo, weight, the eligibility card history,
and the story of the cat who first spoke of it.

---

## 7. Legendaries — new

Twelve, defined in `03 §3`. Ten are caught; two are witnessed.

### 7.1 Eligibility card

Each gated legendary has a journal **watch card** showing:

1. **Clue source:** the cat who told the story, and where.
2. **Requirements:** revealed one at a time as clues are found. Typical: lake +
   zone, time window, weather, recipe bait, and an optional story step.
3. **Current status:** each requirement is ✓ or ✗ *right now*.
4. **Next eligible window:** the next game time all time and weather conditions
   line up (weather windows are scheduled, §3.6).

### 7.2 Encounter

- When a line meeting every requirement soaks through an eligible window, its
  **first haul in that window** hooks the legendary. This is guaranteed, not
  rolled.
- The haul view slows into a short calm scene: the water stills, the line hums,
  and the fish surfaces beside the boat (4–6 s, not skippable the first time,
  skippable after). Then: book page, photo, release.
- Legendaries are **repeatable** (once per game week each). Repeats add a weight
  record and nothing else.
- **Exception:** the Spillway Monster needs only a heavy line in the Marked Pool,
  cut shad, at night. It is possible on day one if the player has a heavy line.
  The Marked Pool (lit by Señora Luz's lamp buoys) exists from the start. Chapter
  2 only adds Doc's barrier and sign.
- **Witnessed legendaries:** the Whiskered Guardian (existing rule: any 8 of the
  10 V3 Ripples, cedar:deep, 18:00–19:59) and the Star-Whale (the finale, §13.5;
  repeatable afterward on clear Nebula nights while settled).

---

## 8. Shinies — new

- **Standard species only** (the 144). Legendaries have no shiny form.
- Rolled **once when the catch is created**, then saved on the catch. Base chance
  is 1 in 64.
- **Shiny Tracker:** available for Verified species. The player can track one
  species at a time from the book. While tracking, a shiny is **guaranteed by the
  50th eligible catch** of that species since the last shiny of it. The counter is
  saved per species and survives switching targets.
  Every standard catch advances its species' counter, including catches while
  tracking is paused or another species is selected; any shiny resets that
  species to zero. If a counter already reached 49 while untracked, selecting it
  guarantees the next catch. Opening the book or reloading never rolls again.
  A hooked shiny reserves that reset until it is kept or deliberately released.
  If it gets away, its saved pity progress carries forward, preserving later
  catches and confirmed shinies. Hook reservations survive saving and reloading.
  Use **F** (the rebindable Set line action), **X** on a controller, or the
  entry's **Track shiny / Stop tracking** button. Only Verified entries show it.
- **Look:** a per-species variant palette (`albino`, `golden`, `starry`, `glow`,
  `ink`, `rose`; see the `03` *Shiny* column) plus a sparkle. It is never
  conveyed by color alone (a
  sparkle icon and "✦" in the name).
- **Value:** sells at 3× the normal price. Default disposition is *Treasured*
  (§5.5). Shiny trophies can be mounted on boats with the *trophy rail* trait or
  shown on the book's Trophy page.
  Shiny Trophy credit and the observation's shiny flag are awarded on Keep or
  Release, so an escaped fish cannot create a Trophy or a mountable replica.
  A remembered shiny stays on that page after release or sale. The mounting
  hook places a cosmetic replica without consuming the catch or its record.
- Shiny completion never gates anything.

---

## 9. Boats — 24 vessels in 8 families

Full table: `03 §6`. Boats are **sidegrades with personalities**, not a strict
ladder. Families share a parametric mesh and handling model. Variants differ in
size, trim, numbers and traits.

| Family | Tier | Handling archetype | Existing boat mapped here |
| --- | --- | --- | --- |
| Pioneer craft | 1 | Paddled or poled; silent; shallow; tiny well | — |
| Rowed craft | 2 | Oars, optional electric (existing rowboat rules) | `rowboat` → *Reinforced Rowboat* |
| Jon boats | 3 | Tiller outboard (existing jon physics) | `jon` → *Aluminum Jon Boat* (starting boat) |
| Utility skiffs | 4 | Console outboard, stable in wind, more lines | — |
| Runabouts | 5 | Fast, small well, smooth | — |
| Sail & trawler | 6 | Sail (existing rules), or a slow tug with a big well | `sail` → *Cat-Rigged Daysailer* |
| Pontoons & houseboats | 7 | Broad, slow turning, galley and hammock | `pontoon` → *Classic Pontoon* |
| Cosmic barges | 8 | Glide on any water, quiet, star-lit | — |

**Traits** (any boat may have several): `shallow` (enters reeds and flats under
0.4 m), `silent` (×1.15 for shy-tagged species), `galley` (cook aboard),
`hammock` (nap at idle), `trophy_rail` (mount shinies and replicas),
`wind_steady` (ignores gust push), `ice_hull` (no slowdown in Flathead snow-mist
chop), `glow` (lit hull at night).

- **Start:** the existing 12 ft Aluminum Jon Boat, "Grandmother's old boat"
  in the new prologue. Existing saves keep their boats, fuel and battery state.
- **Buying:** at any landing, unless the boat is lake-exclusive in `03`. Owned
  boats can be switched for free (existing rule). Livewell-size rules are
  unchanged.
- **Unlocks (new boats):** tiers 1–2 are available from the start. Tiers 3–4
  unlock after chapter 2, 5–6 after chapter 3, 7 after chapter 4, and 8 after
  chapter 5. The four existing boats stay buyable from the start at their current
  prices, and existing owners keep every boat they own.

---

## 10. Bot — new systems

### 10.1 Name

`Word-###`, where Word comes from the 12 prefixes in `03 §7` and ### is 011–999,
zero-padded. It is generated **deterministically from the save's schedule seed**,
so existing saves get a stable name on migration. It is shown on the title screen
save slot and in the book's author line.

### 10.2 Shells and tools

| Shell | Earned | Tool unlocked for purchase | Tool rule |
| --- | --- | --- | --- |
| Classic Tin Deckhand | Start | **Sonar Grid** ($150; needs the existing Depth Finder) | Chart overlay of ground type and depth contours for scouted zones |
| Frog Bot | Ch. 1 | **Reed Anchor** ($120) | Anchor and set lines in `reeds` zones. Space anchors as usual |
| Rubber Duck Bot | Ch. 2 | **Wave Chime** ($180) | G within 30 m of your line, while slow: for 60 game min, `surface`-tagged species on that line bite ×1.6. Cooldown 120 game min |
| Clockwork Copper Sub | Ch. 3 | **Thermocline Scanner** ($260) | Shows `d(t)` in the HUD and Bot's report on Flathead and Crater. The book shows each cold species' band relative to `d` |
| Astral Starlight Bot | Ch. 5 | **Zero-G Winch** ($400) | Lines don't drift in currents; current species ×1.2; legendary hauls play the smooth "winch" variant |

- Shells swap at any landing (free once earned). Tools work with any shell.
- **Paint and trims:** Tinker Thistle (traveler) sells cosmetic shell paints, $30
  each.
- **Barks:** every factual bark is tied to a live condition, and each has an
  uncertain fallback (`05 §3`).

---

## 11. NPCs — new and extended

### 11.1 Cast

52 cats (`04`): 5 hosts, 2 travelers, and 45 water-cats (9 per lake). Pip & Pebble
are two cats sharing one boat and one encounter, so each lake has 8–9
**encounters**.

### 11.2 Visibility (new)

Every present cat is **visible**, sitting on their own boat at their anchor: a
procedural low-poly cat on a family boat mesh (`06 §6`). Idle loops: fish a line,
nap, read, paint, wave when within 40 m. A **chart pin** shows present cats. The
existing invisible-anchor behavior is replaced.

### 11.3 Daily schedule

- **Hosts:** always at their landing.
- **Per lake, per game day:** 3 *day* encounters (06:00–20:00) and 1 *night*
  encounter (20:00–04:00). Nebula uses the same clock. Its sky is always starlit,
  and its time bands display as Rising, Bright, Fading and Deep (`03 §1.6`).
- **Selection:** a seeded permutation of that lake's encounters, walked
  round-robin. Every encounter appears at least once every 3 game days.
  Deterministic from `(schedule_seed, lake_id, day)`. It doesn't depend on the
  computer clock or which lake is loaded.
- **Pinned:** a cat needed by an *active* story step, or by an accepted quest whose
  objective needs that cat present, is always present on their lake (an extra slot
  if needed).
- **Travelers:** Postmaster Pounce visits one unlocked lake per day (seeded).
  Tinker Thistle visits every Saturday at the lake the player is on.
- Existing V3 night rule: Master Cinder keeps the 20:00–04:00 Briar night slot.

### 11.4 Hailing (existing)

C within **20 m** while slower than **3 knots** (existing). It plays a short horn
"bip" and opens dialogue. The gamepad uses RB. The dialogue overlay stays
existing; portraits are new (`06 §6`).

### 11.5 Friendship

Each water-cat has three states: **Stranger → Acquaintance** (quest A done) →
**Friend** (quest B done). Each state changes their greeting (`05`). Friends write
an occasional letter via Pounce: at most 1 per game day, flavor plus a hint.

---

## 12. Quests — extended

### 12.1 Counts

| Kind | Count | Reward |
| --- | --- | --- |
| Story steps (5 chapters × 3) | 15 | Chapter rewards (§13) |
| Host errands | 5 (`q01_tea_leaves_deep_holes`, `q02_lonely_star_current` existing and unchanged + 3 new) | Cash only (dish cards come from chapters, §4.3) |
| Water-cat quest A | 44 (10 existing) | Cash + a unique **Ripple** |
| Water-cat quest B | 44 | Cash + a **Keepsake** (boat decoration, `03 §9`) |
| **Total** | **108** | |

Quest B unlocks the game day after quest A is turned in.

### 12.2 Rules

1. All side quests are optional, can be declined, and stay available after
   declining (existing).
2. Accepted objectives persist across days, lake travel and quitting.
3. **Turn-in anywhere sensible:** a completed side quest can be handed in to its
   giver **or** at that lake's host. The giver acknowledges it on the next meeting
   (their *return* line).
4. The journal shows the **next guaranteed appearance** of any cat needed.
5. **No consumption:** turn-ins never take fish, gear or boats. "Show me a fish"
   objectives check the livewell (or the haul) and leave the fish. Capacity-safe
   behavior is existing (Ticket 8).
6. Rewards are claimed exactly once (existing reward-claim ledger).

### 12.3 Objective types

Existing (keep semantics from `docs/narrative/CONTENT.md`): `line_scout`,
`line_check`, `line_scout_check`, `anchor_idle`, `scout_report`,
`fish_livewell`, `travel_distance`, `visit_zones`, `visit_sequence`.

New:

| Type | Fields | Meaning |
| --- | --- | --- |
| `catch_species` | species_id \| species_ids \| group \| tag \| `any`; count; distinct?; min_lb?; zone_id?; area_id?; lake_id?; time_band?; bait_id?; in_cold_band? | Haul-time catch after acceptance (kept or released). A legendary id is satisfied by that legendary's record, caught **or witnessed** |
| `book_stage` | species list or lake, stage, count | N entries at or above a stage |
| `cook_dish` | dish_id or any | Cook after acceptance |
| `catnap` | zone_id? | A nap completes in the zone |
| `tool_use` | tool_id, zone_id?, lake_id?, shell_id? | A successful tool use (chime cast, scanner read, reed anchor set). `shell_id` requires that shell to be equipped at the time |
| `wait_weather` | weather, then_weather?, zone_id \| zone_ids \| lake_id, minutes (default 30) | Anchored in a qualifying zone while that weather is active, for `minutes` game minutes in total (accumulated; drifting pauses progress without resetting it). With `then_weather`, it completes when the weather changes to that state while the player is waiting there |
| `settle` | zone_id, cues | The finale "settle in" interaction (§13.5) |
| `talk_to` | npc_id, distinct_days? | Hail that cat after acceptance (letters, introductions). `distinct_days: 3` means three different game days |
| `attend_event` | lake_id, event | Be at that lake's landing during the event (Sunday cookout) and hail the host |

Extended fields on existing types:

- `line_check` / `line_scout_check`: `min_tier` (`std` < `prem` < `heavy`, as an
  alternative to the exact `tier_id`), `in_cold_band` (the line was set inside
  `[d, d+6 m]` at set time), and `area_id` (a named sub-area such as the Marked
  Pool).
- `scout_report` / `visit_sequence` / `visit_zones`: `waypoint_ids` (named story
  points, `06 §5`) instead of zones, and `windows` (a list of clock windows that
  must **each** be hit by a separate report). `visit_zones` may list zones on
  several lakes.

**Quest structure:** a quest's objective may be a list of **steps** completed in
order (for example `catch_species` then `talk_to`). A quest may declare `requires`
(`chapter_complete: N`, a quest id, or `travel_unlocked: lake`), which keeps it
unavailable until met. The validator must reject any authored objective that uses
a field not in this table.

Mechanics text belongs only in the journal objective string (`05 §0`).

---

## 13. Story chapter mechanics

Each chapter's three steps use ordinary objective types. They are pinned in the
journal as **Story** and never time-limited.

- **Ch. 1 Reed Passage** (Briar): `talk_to pip_pebble` → `scout_report` at 3
  reed-edge waypoints, any order → `catch_species` any fish in `briar:reeds`
  (the Reed Anchor is granted free for this step) → turn in to Grandmother.
  Rewards: Frog Bot, collar, Reed Passage chart layer.
- **Ch. 2 The Drifted Marker** (Cedar): `talk_to doc_barnaby` →
  `visit_sequence` along 3 drift waypoints, ending at the jug → `line_check` heavy
  or prem line in the Marked Pool for 60 active game minutes. Rewards: Duck Bot,
  Marked Pool barrier and sign, Flathead travel.
- **Ch. 3 Two Readings** (Flathead): `scout_report` in `flathead:deep` between
  06:00–10:00 **and** again between 14:00–18:00 (Bot's report shows "cold water
  near X ft") → `catch_species` any cold-tagged fish within the cold band. The
  Sub's scanner is lent for this step. Rewards: Sub, Crater travel; the collar comes
  loose (scene).
- **Ch. 4 The Fog Marker** (Crater): `talk_to sora` → `wait_weather fog→clear`
  at one of three safe coves (the player chooses) → `scout_report` at the marker
  after the clearing. Rewards: star reading, Nebula travel; knot choice scene (3
  knots, cosmetic).
- **Ch. 5 Settle In** (Nebula): `talk_to astra_9` → `settle` (§13.5) → story
  objective "Go home to Briar Landing". A free trip to Briar is offered at once,
  and accepting it or travelling there any other way starts the ending scene
  (`05 §2.5`, `§3`). Nothing happens automatically.

### 13.5 Settle In (finale interaction)

- The prompt "Settle in" appears when the player is anchored in
  `nebula:open` within 200 m of the marked reflection.
- Progress accumulates over **45 real seconds** of stillness, with **three visible
  cues**: the stars stop rippling at 15 s, the lilies drift together at 30 s, and
  a deep glow rises at 45 s.
- Moving **pauses** progress without resetting it. Weather and needs can't
  interrupt.
- After the first cue, **"Watch together"** (Astra-9 joins) finishes the rest
  hands-free.
- Then the Star-Whale scene plays (30–40 s, skippable on repeats). The pencil
  moment is a single input: "Draw it".

---

## 14. Travel

- Landing menu → Lakes tab (existing). Lines must be pulled first (existing).
- Travel is free once unlocked. The prose for each trip is a one-line caption
  ("Doc's trailer rattles north…").
- A new lake loads its own map. The previous lake's renderer is released
  (existing benchmark rule).

---

## 15. Economy and pacing

### 15.1 Price levels

Species prices in `03` are already set per lake. Rough income per active game day
for an attentive player:

| Stage | Typical lake | $/game day |
| --- | --- | --- |
| Start | Briar | 60–120 |
| Ch. 2 | Cedar | 150–300 |
| Ch. 3 | Flathead | 300–500 |
| Ch. 4 | Crater | 450–750 |
| Post-story | Nebula | 700–1,100 |

### 15.2 Sinks

Boats ($300–$11,000 new; existing boats $325–$1,450), lines, bait, recipes, tools ($120–$400), pantry, fuel and
electricity (existing), paints ($15–$30), dish cards ($40).

### 15.3 Pacing guardrails (test targets)

- A chapter's required gear costs no more than **2 game days** of that stage's
  income.
- The cheapest **new** boat of each tier costs **3–6 game days** of the income-band
  midpoint at the stage it unlocks (start 90, ch. 2 225, ch. 3 400, ch. 4 600,
  ch. 5 900 dollars a day). The `03 §6` prices satisfy this; V1-44 re-checks it
  against the pacing simulator.
- No objective requires a specific boat, except a trait (e.g. `shallow`), and at
  least one cheap boat must have that trait.

---

## 16. Controls

Existing keys are unchanged. New keys:

| Key | Pad | Action |
| --- | --- | --- |
| Z | Y (hold) | Catnap |
| G | LB | Use the active Bot tool |
| K | — (via menu) | Galley (on galley boats, anchored) |
| J then A/D | D-pad | Journal pages: Fish → **Book** → Ripples & Keepsakes → Story → Watch cards |

Gamepad support is new (SDL GameController). Left stick: steer and throttle
lever. RT/LT: throttle up and down. A = E, B = back/Esc, X = F, Y (tap) = B (Bot),
RB = C (hail), LB = G, Start = pause, Back = chart, D-pad = menus. On-screen
prompts follow the last-used device.

---

## 17. Accessibility and settings (new)

Text size (3 steps), dyslexia-friendly font option, reduced motion (no camera
sway, simple fades), haul speed (Normal, Quick, Instant), colorblind-safe markers
(shape + color), captions for every chime, Bot sound and NPC horn, hold-to-confirm
off by default, remappable keys, master/music/ambience/SFX volume, and collar
visibility.

---

## 18. Audio direction

- **Keep the existing procedural lake voice.** Each new lake adds its own
  ambience: Flathead (wind in larch, loons, ice tick), Crater (deep hush, spring
  bubbling, ravens), Nebula (soft choral pads, chimes, a low "whale song" on
  finale nights).
- **Music:** a gentle procedural or sequenced score, one motif per lake, played
  sparsely: dawn, dusk, chapter moments. Silence is a valid default.
- Each Bot shell has a chime timbre (tin = triangle, duck = squeak, frog = wooden
  "ribbit" click, sub = bubbly tick, astral = glass bell).

---

## 19. Visual direction (targets; detail in `06 §6`)

- **Lakes:** each new lake gets a unique palette, sky, terrain silhouette, water
  shader parameters and shoreline set dressing at the quality of today's Briar.
- **Cats:** a soft, chunky silhouette and readable at 60 m. Breed patterns from a
  shared rig. Attire props per character.
- **Fish:** each of the 156 species gets an illustrated fish card in a consistent
  "field guide watercolor" style, generated from parameters (`06 §6.3`), plus the
  in-world fish mesh used in the haul.
- **UI:** the existing quiet lake-journal style becomes a book. Paper, ink, tabs
  and stamps, with portraits in dialogue.

---

## 20. Release and save promise

- The free clone and the paid package ship the **same game**, run offline, and
  need no developer tools to launch (the package). The clone ships tested setup
  instructions and all assets.
- Saves live **outside the install directory** (platform user-data folder; the
  existing `saves/briar.json` is migrated with a backup, `06 §3`).
- Every update migrates older saves. A save never loses money, fish, lines, gear,
  boats, journal records, quest progress or Ripples.
