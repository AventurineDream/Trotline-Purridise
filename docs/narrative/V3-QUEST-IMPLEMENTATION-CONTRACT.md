# Little Briar: V3 Quest Implementation Contract

*Ticket 1 scope gate*
*Contract version 1.1 — 18 October 2026*
*Status: normative V3 design and implementation contract; NPC and quest systems are present in the current game.*

This contract is the single authority for the V3 narrative feature's quest names, IDs, locations, schedules, controls, progress rules, rewards, persistence, and optionality. CanonSheet-v3, GameplayNarrativeUpdateSpec-v3, RelationshipAndQuestFlowmap-v3, ImplementationGuide-v3, StoryOverview-v3, CharactersOverview-v3, the V3 character sheets, and Script-v3 must agree with it. Earlier V2 material remains in the existing superseded archive.

## 1. Scope and build boundary

Ticket 1 freezes a design against the current Little Briar game. It does not implement NPCs, quests, or new game systems.

| Area | Current build | V3 proposal covered by this contract |
| --- | --- | --- |
| Game and world | Python game, Little Briar and Cedar Creek Lake; lake IDs briar and cedar | Optional narrative layer across both existing lakes |
| Fishing | 36 fish, five bait IDs, four boats, trotline tiers of 12/18/24 hooks, maximum five deployed lines | Quest listeners observe existing line, catch, and boat events |
| Bot | B sends and recalls Bot; report contains zone, depth class or exact depth when a finder is owned, and bait advice | Quest objectives can request that existing report; no thermal or audio sensors |
| Controls | F sets a line; E checks a line or opens the landing; B controls Bot; H opens Help; M mutes | C is the keyboard hail/chat action; H remains Help |
| Time | One real second advances one game minute at 1x; day is 1,440 game minutes (24 real minutes at 1x). T selects 1x/3x/6x/12x while still | All quest durations and windows use the game clock |
| Landing and travel | Briar Landing and Cedar Landing menus handle shop and lake travel | Story anchors do not move those menus or change travel |
| Save | Existing JSON save is saves/briar.json and preserves fishing progress | Add an optional narrative_v1 object to the existing save; do not replace the save format |

The two lakes, their fishing, and normal progression remain available without accepting any quest. Quest content never consumes a fish, line, bait, upgrade, or boat as a turn-in requirement. No quest gates fishing, travel, a shop, or an existing item.

## 2. Identity, controls, units, and canonical locations

### 2.1 Names and IDs

Use these stable lake IDs and names everywhere:

- briar — Little Briar Lake.
- cedar — Cedar Creek Lake.

Use namespaced zone IDs in specifications and saved quest progress: lake ID, colon, zone ID. A zone ID can exist on both lakes and still refer to different places. Display labels below are the current game labels.

| Namespaced ID | Current display label | Narrative alias or note |
| --- | --- | --- |
| briar:landing | Briar Landing | Grandmother's existing landing |
| briar:inlet | Creek inlet | Little Briar |
| briar:flats | North flats | Little Briar |
| briar:lilies | Lily cove | Little Briar |
| briar:cypress | Cypress shore | Little Briar |
| briar:deep | Deep hole | Cypress Trench is prose alias only |
| briar:rocks | South rocks | Little Briar |
| briar:open | Open water | Little Briar |
| cedar:landing | Caney Creek landing | Existing Cedar travel/shop landing |
| cedar:inlet | Creek channels | Cedar |
| cedar:flats | Upper lake flats | Cedar |
| cedar:lilies | Clear Creek coves | Cedar |
| cedar:cypress | Flooded shoreline | Cedar |
| cedar:rocks | Dam riprap | Cedar |
| cedar:deep | Southern basin | Lonely Star Deep is a named story waypoint in this existing zone |
| cedar:open | Cedar open water | Cedar |

Do not write a bare zone ID where the lake could be ambiguous. In particular, the Lily cove quest target is briar:lilies and Clear Creek coves is cedar:lilies.

### 2.2 Named Cedar waypoints

The existing chart zone set remains intact. Add the following named narrative waypoints in the Cedar chart coordinate system. Coordinates are game metres on the horizontal plane (X east, Z north); they are anchors, not street addresses.

| Waypoint ID | Display name | Parent zone | Anchor and provenance |
| --- | --- | --- | --- |
| cedar:docs_marina_dock | Doc's Lonely Star Marina | cedar:open | X -186.451, Z -400.499; nearest modeled water point to the owner-provided public marina pin. This is separate from cedar:landing. |
| cedar:trinidad_cove | Trinidad Cove | cedar:deep | X 186.862, Z -855.722; transformed from the owner-provided water point 32.220216, -96.114709 using the Cedar survey origin and scale in the game asset. Record no residential address. |
| cedar:lonely_star_deep | Lonely Star Deep | cedar:deep | Story alias at the existing Southern basin deep-water marker; not a new fishing zone. |

Doc's NPC anchor is at cedar:docs_marina_dock. Cedar shop, fuel, and lake-travel menus remain at cedar:landing for this ticket. The water point is named Trinidad Cove. The Cedar asset uses the Texas Water Development Board survey origin and horizontal game scale; future chart work must retain these named anchors when rebuilding the asset. The source survey identifies its coordinate system as NAD83 State Plane Texas North Central Zone (feet) ([TWDB 2017 survey report](https://www.twdb.texas.gov/hydro_survey/cedarcreek/2017-10/CedarCreek2017_FinalReport2.pdf)); the supplied latitude/longitude point was converted into that system with the [NOAA NGS Coordinate Conversion and Transformation Tool](https://www.ngs.noaa.gov/NCAT/).

### 2.3 Hailing

- Keyboard action: C opens or advances hail/dialogue for the nearest eligible NPC.
- Eligibility: horizontal boat-to-NPC distance at most 20.0 game metres and absolute boat speed below 3.0 knots.
- H does not change; it remains Help. Do not remap it to F1.
- Right Bumper is not a binding in the current gamepad layer and is not part of V3 acceptance.
- The existing game clock and line simulation continue during dialogue. Player boat input is ignored while the dialogue choice panel is open; closing it restores input. Hailing never changes quest progress by itself.

### 2.4 Bot reactions

Ticket 10 adds optional, non-authoritative reactions to the existing NPC and quest state:

- On the first foreground play frame when an active NPC is within the same 20.0-metre and below-3.0-knot eligibility boundary in §2.3, Bot shows a short, non-blocking text toast and records a matching narrative-journal note. Record at most one proximity reaction for each stable NPC ID per save. Use only the current lake's active NPCs; do not create offscreen or retroactive reactions.
- After a successful quest turn-in has latched its existing reward and applied the existing cash and Ripple, Bot shows one short text toast and records one journal note keyed by quest ID. Do not react to accepting or declining an offer, an objective merely becoming ready, or a failed turn-in.
- Describe Bot's small brass-ear or approving-click gesture in text. Add no audio cue, animation, NPC response, dialogue, choice, reward, or quest progress. These notes do not interpret the player's achievement or alter any fishing, movement, control, or narrative outcome.

## 3. NPC presence and daily schedule

There are twelve quest givers: two permanent lake hosts and ten rotating NPCs. At most one rotating NPC is active on a lake at a time, in addition to that lake's permanent host.

- Grandmother Whiskers is always present at briar:landing while Little Briar is loaded.
- Doc Barnaby is the permanent Cedar host at cedar:docs_marina_dock while Cedar is loaded. His narrative NPC anchor does not relocate the existing Cedar landing menu.
- Initialize `schedule_seed` to the integer `0` for every new save and for any legacy save missing that field, including saves without `narrative_v1`. Persist it before selecting NPCs, preserve an existing saved integer value, and never randomize or reroll it on load or lake travel. This is the normative default, including for the suggested save shape in §6.
- At 06:00 game time on each lake day, choose and save one daytime NPC for that lake. `game_minutes == 0` is 06:00, so define `selection_day = max(0, floor(game_minutes / 1440))`; select `pool[(schedule_seed + selection_day) mod pool_length]`. Pool order is the order listed above. Save the selected ID and `selection_day`. On a new save, initialize the current interval on first load. If time advances while a lake is offscreen, compute its current scheduled NPC on return without granting offscreen quest progress. The selection day advances at `game_minutes` 1440, 2880, and so on, each corresponding to 06:00.
- Little Briar daytime pool: Elder Moss, Pip & Pebble, Willow, Silas. The selected daytime NPC is active from 06:00 to 20:00 and again from 04:00 to 06:00 the following morning.
- Master Cinder occupies the Little Briar rotating slot from 20:00 to 04:00. His quest requires the night window, not a spotlight upgrade.
- Cedar daytime pool: Captain Maeve, Sparky, Quill, Dr. Alder, Patch. The selected Cedar NPC remains active until the next 06:00 selection.
- NPC schedules are based on the game's local lake clock. Switching lakes does not reroll the selection. Only the loaded lake displays actors; off-lake state is not simulated. On return, show the NPC selected for the current schedule interval.
- Quest progress is recorded only from events generated while the player is actively playing. Do not grant retroactive narrative progress for offscreen time.
- If the giver becomes inactive or the player changes lakes, accepted progress remains saved. A ready quest can be turned in the next time its giver is present.

### 3.1 Fixed NPC anchors

These are fixed narrative NPC positions in the current game coordinate system. Coordinates are X/Z game metres. All listed points resolve to navigable water in their assigned current zone; retain them across chart rebuilds.

| NPC | Namespaced anchor | X | Z | Presence |
| --- | --- | ---: | ---: | --- |
| Grandmother Whiskers | briar:landing | -435.789 | 107.381 | Permanent Little Briar host; current landing slip center |
| Doc Barnaby | cedar:docs_marina_dock | -186.451 | -400.499 | Permanent Cedar host |
| Elder Moss | briar:cypress | 330.000 | 20.000 | Little Briar day pool |
| Pip & Pebble | briar:flats | 10.000 | 205.000 | Little Briar day pool |
| Master Cinder | briar:deep | 75.000 | -25.000 | Little Briar night slot |
| Willow | briar:lilies | -175.000 | -115.000 | Little Briar day pool |
| Silas | briar:inlet | -210.000 | 155.000 | Little Briar day pool |
| Captain Maeve | cedar:open | 0.000 | 0.000 | Cedar day pool |
| Sparky | cedar:inlet | -423.772 | 948.817 | Cedar day pool |
| Quill | cedar:flats | -234.448 | 509.948 | Cedar day pool |
| Dr. Alder | cedar:deep | 330.854 | -754.864 | Cedar day pool |
| Patch | cedar:lilies | 632.171 | -964.758 | Cedar day pool |

The Little Briar positions use the current zone centers in fishing/world.py. Cedar positions use the named zone centers in fishing/assets/cedar.json, except the marina waypoint and open-water NPC anchor. Zone lookup and navigability were checked against the current map.

## 4. Quest rules

### 4.1 Shared state and offer behavior

Every quest has one of four saved states: available, active, ready, completed.

- New quests begin available. Hailing a present giver displays the offer. Accept changes available to active; decline leaves it available and the offer returns on the next hail.
- Progress survives schedule changes, lake switches, save/load, and missed time windows. There is no quest failure, expiry, or penalty.
- An objective becoming satisfied changes active to ready. Hail the same giver while present to turn in; then award the fixed reward and set completed.
- A completed quest cannot be replayed and cannot pay a second reward. The ten Ripple quests each add their unique Ripple once. The two host quests award cash only.
- Progress is evaluated from the event and source data defined in §5. Events that occurred before accepting a quest do not count.
- Fish are not removed from the livewell. A catch objective records a qualifying fish after it enters the livewell.
- Time windows use the current game minute, not real time. Intervals are half-open: start included, end excluded. A window spanning midnight wraps over the day boundary. The four line-soak objectives measure their 60-minute duration with the active-play counter defined below; offline catch-up does not count.

### 4.2 The twelve canonical quests

Quest IDs and Ripple IDs are permanent save identifiers. Reward amounts are game dollars, paid once on hand-in.

| # / Quest ID | Canonical title and giver | Start/turn-in anchor | Testable objective | Reward |
| --- | --- | --- | --- | --- |
| q01_tea_leaves_deep_holes | Tea Leaves & Deep Holes — Grandmother Whiskers | briar:landing | After acceptance, set a 12-hook std line with worm bait in briar:lilies. Make it the nearest eligible deployed line with its midpoint strictly less than 140 game metres from the boat, send Bot with B, and receive his ordinary report for that line. An exact depth is not required. | $60; no Ripple |
| q02_lonely_star_current | The Lonely Star Current — Doc Barnaby | cedar:docs_marina_dock | After acceptance, set a 12-hook std line with minnow bait in cedar:rocks; wait at least 60 game minutes from set time; check that same line. | $90; no Ripple |
| q03_unstrung_line | The Unstrung Line — Elder Moss | briar:cypress | Anchor in briar:cypress with engine idle for 120 continuous game minutes. Any interruption resets this objective's timer. | $45 and ripple_01 |
| q04_great_contour_chart | The Great Contour Chart — Pip & Pebble | briar:flats | Complete a Bot scout report whose scout point is in briar:flats. Accept the standard depth class, or the exact depth if the player owns a finder; neither requires a new tool. | $45 and ripple_02 |
| q05_moonlight_trotlines | Moonlight Trotlines — Master Cinder | briar:deep | Set a 12-hook std line with shad bait in briar:deep during 20:00–04:00; wait at least 60 game minutes and check that line. The boat spotlight is optional. | $50 and ripple_03 |
| q06_unrepeatable_sunrise | The Unrepeatable Sunrise — Willow | briar:lilies | After acceptance, a fish whose `species_id` is `golden_shiner` must enter the livewell during 05:00–08:00 from a worm-bait line set in briar:lilies. The line may be set earlier. The fish stays in the livewell. | $55 and ripple_04 |
| q07_art_of_the_nap | The Art of the Nap — Silas | briar:inlet | Anchor in briar:inlet with engine idle for 120 continuous game minutes. Fishing continues normally. | $40 and ripple_05 |
| q08_channel_run | The Channel Run — Captain Maeve | cedar:open | Travel at least 300 game metres within cedar:open under player control by motor, oars or sail. Accumulate actual path distance; tow movement does not count. | $65 and ripple_06 |
| q09_quiet_channel | The Quiet Channel — Sparky | cedar:inlet | Set a 12-hook std line with liver bait in cedar:inlet; wait at least 60 game minutes; check that same line. | $50 and ripple_07 |
| q10_ballad_lonely_star | Ballad of the Lonely Star — Quill | Quill at cedar:flats | After acceptance, enter cedar:rocks, cedar:lilies, and cedar:open in any order. Then hail Quill to turn in. No sound recording is required. | $45 and ripple_08 |
| q11_deep_water_drift | The Deep-Water Drift — Dr. Alder | cedar:deep | Set an 18-hook prem line with shad bait in cedar:deep; make it the nearest deployed line within Bot's current scout range, receive his ordinary report for it, wait at least 60 game minutes from set time, and check that same line. | $60 and ripple_09 |
| q12_first_voyage | The First Voyage — Patch | Patch at cedar:lilies | After acceptance, enter cedar:landing, then cedar:lilies, then return to cedar:landing, in that order, through player-controlled boat movement. Any player boat and available propulsion work; tow and other repositioning transitions do not count. | $50 and ripple_10 |

Record each line's set zone and bait. The Willow catch event must occur after acceptance and within 05:00–08:00, and its source line must be a worm-bait line set in briar:lilies. The line may have been set before accepting. If the dawn window is missed, try the next sunrise.

For q06, qualify the event by `entry_game_minute`, the game time when the fish is transferred into the livewell. `catch_game_minute` records when the fish took the hook and does not determine the sunrise window. This distinction allows a fish hooked before 05:00 to qualify if it enters the livewell during the window after acceptance.

For both anchoring quests, the 120-minute counter advances only while the boat is anchored, the engine is idle, and the player's boat remains in the target zone. Any unanchor, non-idle engine, or zone exit resets the current continuous timer. At 1x, 120 game minutes take two real minutes; at 12x they take ten real seconds.

For q02, q05, q09, and q11, the line must accumulate at least 60 active-play game minutes between its `line.set` and later `line.check` events. Compare the events' `active_game_minute` values; do not use the wall-clock game-minute difference. Increment the persistent counter by the actual positive change to `State.game_minutes` from foreground simulation and player-triggered online actions that advance the clock. Do not infer elapsed game minutes from the selected `time_scale`: when 12x is selected but the simulation is limited to 1x, count the actual 1x clock change. Menus and dialogue count only while the game clock advances. Frozen time and offline time added by `State.catch_up` when the game is reopened do not count. At 1x this takes one real minute; at an effective 12x it takes five real seconds. Do not require a catch or consume the line. The line's night-window condition for q05 still uses `game_minute` at set time.

### 4.3 Ripples and Guardian

- The player-facing singular is Ripple of Wisdom and the plural is Ripples of Wisdom. Only q03 through q12 award Ripples, one unique Ripple each, in the order shown above.
- At eight or more unique Ripples, the optional Whiskered Guardian sighting can occur when the player's boat is in cedar:deep during 18:00–20:00 game time.
- The sighting is peaceful and non-blocking. If the player misses the window, it can occur on a later eligible sunset. It never locks fishing, travel, a quest, or an ending.
- Record guardian_seen and a Whiskered Blessing journal note once. Do not create a pennant, lure, sound recorder, or other inventory reward in this scope.

## 5. Event adapter contract

These are quest-observation events over existing game state. They are not new fishing, sonar, audio, boat, inventory, or NPC mechanics.

| Event | Required fields | Used by |
| --- | --- | --- |
| line.set | line_id, lake_id, midpoint zone_id, tier_id, hook_count, bait_id, game_minute, active_game_minute | q01, q02, q05, q06 line source, q09, q11 |
| line.check | line_id, lake_id, zone_id, game_minute, active_game_minute, eligible catch records | q02, q05, q09, q11 |
| bot.scout_complete | lake_id, target line_id when applicable, scout-point zone_id, depth_class, exact_depth_m only when available, report-delivered flag | q01, q04, q11 |
| fish.enter_livewell | species_id, source_line_id, lake_id, source zone_id, bait_id, catch_game_minute, entry_game_minute | q06 |
| zone.enter | lake_id, zone_id, game_minute, movement_cause, player_controlled | q10, q12 |
| boat.move | lake_id, segment zone_id, in-zone distance_m, player_controlled, propulsion type | q08 |
| anchor.sample | lake_id, zone_id, anchored, engine_idle, elapsed game minutes | q03, q07 |

Use IDs from the live game state: bait IDs worm, liver, shad, minnow, craw; line tiers std (12 hooks), prem (18 hooks), heavy (24 hooks); species ID `golden_shiner`. The current `Catch` model exposes a species identifier and has no per-catch instance identifier, so do not add or require a separate `fish_id`. A new adapter may observe or persist existing state transitions, but it must not alter bite rates, fish values, line limits, movement, or gear.

### 5.1 Persistent deployed-line identity

The current `SetLine` has no identifier. The later implementation must assign an immutable `line_id` (a UUID string) to each deployment before emitting `line.set`, and persist it as an optional field on that deployed line's serialized record. Restore the same ID on load and retain it through checks, rebaiting, and list reordering. Lake travel still requires pulling every deployed line first; no deployment or live line ID crosses a lake switch. Saved quest references to ended deployments remain historical references across travel and must never bind to a new deployment. Never derive identity from the mutable `State.lines` index, coordinates, bait, or tier. Pulling a line ends that deployment; deploying the coiled gear again receives a new ID, even in the same place. IDs must be unique across both lakes and must not be reused for saved quest references.

When loading a legacy deployed-line record without an ID, assign one once and persist it on the next save without changing its fishing state. This migration does not emit a `line.set` event, invent a set time, or grant retroactive quest progress. Keep existing quest references and qualifying set properties tied to the deployment ID; removing another line must not redirect them. Capture `source_line_id` from the source deployment before transferring fish or removing that line, including a pull that transfers fish into the livewell.

For line-directed Bot scouts, capture the chosen deployment's `line_id` as `target_line_id` at launch, alongside the existing target coordinates. Persist that optional field in the existing saved `bot` object with its phase and target coordinates, restore it unchanged for an in-flight scout, and use it for the eventual `bot.scout_complete` event. Do not recompute it from the boat's new position, line-list order, or coordinates after launch or load. Free-water scouts have a null target ID. Clear the association when the scout is recalled, reset, or its target deployment is pulled; an ended deployment cannot produce a qualifying line-specific report. For legacy in-flight scouts without a saved target ID, preserve ordinary Bot movement and reports but emit no line-specific quest credit; a fresh launch can capture an identity. This migration grants no retroactive progress.

### 5.2 Distance within a zone

Each `boat.move` event describes only the traversed portion in its named zone: `zone_id` is the segment's zone, and `distance_m` is the non-negative path length in that zone. Split the actual accepted movement path at zone boundaries using the live world's zone classification, including its boundary precedence. Use the movement substeps that actually occurred; do not substitute the update's start-to-end displacement, count rejected movement, or classify the whole update by its final position. Emit separate portions when a move crosses a boundary, and count each portion once.

For q08, accumulate only portions with lake `cedar`, zone `open`, player control, and motor, oar or sail propulsion after acceptance. For example, an update traveling 8 metres outside Cedar open water followed by 2 metres inside contributes 2 metres, regardless of its event cadence. Reversing across that boundary does not make the outside portion eligible. Tow movement and repositioning on load or lake travel contribute zero.

### 5.3 Zone-entry provenance

Set `zone.enter.movement_cause` to `boat`, `tow`, `load`, or `lake_travel` according to the transition's source. Set `player_controlled` true only for ordinary movement of the player's boat under the existing controls; calling a tow action is not player-controlled boat movement. For q12, advance the ordered sequence only on events with `movement_cause == boat` and `player_controlled == true` after acceptance. Tow, save/load repositioning, and lake-travel placement cannot advance any leg; they do not reset already recorded legs. Merely loading or being placed in a target zone is not an eligible entry; a subsequent qualifying boat entry is required. These fields do not change q10's existing any-order entry objective.

## 6. Persistence and journal

Add an optional narrative_v1 object inside the existing saves/briar.json state, the optional deployed-line `line_id` field, and the optional `bot.target_line_id` field defined in §5.1. Do not rename the save, discard current fields, or change fishing progress. A missing narrative_v1 object in an existing save means all twelve quests are available, zero Ripples are collected, and no Guardian sighting is recorded. Initialize and persist `schedule_seed` as specified in §3. Maintain a persistent, monotonic `active_play_game_minutes` counter for actual game-clock minutes advanced by foreground simulation and player-triggered online actions. Increase it by the actual positive `State.game_minutes` delta rather than the selected `time_scale`; this preserves the effective rate when faster ticking is unavailable. Menus and dialogue count only while the clock advances; frozen updates and offline time added by `State.catch_up` do not count. Record its value on qualifying line-set and line-check progress so active soak survives save/load without counting time the game was closed.

Suggested stable shape:

~~~json
{
  "narrative_v1": {
    "quests": {
      "q01_tea_leaves_deep_holes": {"status": "available", "progress": {}}
    },
    "ripples": [],
    "schedule_seed": 0,
    "day_npc_by_lake": {"briar": null, "cedar": null},
    "schedule_day_by_lake": {"briar": null, "cedar": null},
    "guardian_seen": false,
    "active_play_game_minutes": 0,
    "bot_reactions": {},
    "bot_journal": []
  }
}
~~~

Persist quest status and counters, accepted game minute, qualifying line IDs and their set properties including their `active_game_minute` at set time, the day-NPC choice and selection day for each lake, collected Ripple IDs, `active_play_game_minutes`, and `guardian_seen`. Persist `bot_reactions` as a map from stable `npc:<npc_id>` or `quest:<quest_id>` keys to the one-time note text, so save/load cannot repeat a cue. Preserve the existing `bot_notes` scout-report history. Keep `bot_journal` as the chronological report/reaction history, retaining its latest 40 entries, and display its latest entry on the narrative journal page; when loading an older save without this field, initialize it from the existing `bot_notes`. Derive display labels from IDs; do not save drifting prose as identifiers.

The V3 Journal page is titled Lake Whispers & Ripples. It shows quest state and explicit counters, qualifying conditions and remaining game minutes, the 0/10 unique Ripple count, and the Guardian availability state. Keep the existing fish journal and livewell pages. Preserve Bot's existing depth/ground/bait report unchanged; the optional reactions in §2.4 add non-authoritative journal notes only. No temperature or ambient-sound log is added.

## 7. Dialogue and reward boundaries

Script-v3 supplies dialogue for the same twelve IDs and titles. Lines may describe existing Bot scouting, current zones, the game clock, lines, catches, anchoring, and travel. Dialogue may use poetic references to wind, water, silence, memory, and song.

Do not promise or require thermal readings, ambient audio recordings, a buoy course, a winch or electric reel, an escort NPC boat, a sounding pole comparison, new bait or fish items, new physical quest rewards, or an upgrade unlock. Replace those objectives with the event checks in §4.2. A character may speak about these ideas as metaphor only, without claiming the game implements the system.

## 8. Acceptance checklist for implementation tickets

A later implementation is contract-compatible when it can demonstrate all of the following:

- Hail range and speed use metres and knots as defined; C does not conflict with H Help.
- New and legacy saves missing `schedule_seed` initialize and persist integer 0; existing saved seeds are retained. Daily selections persist across switching and reload; Cinder occupies only 20:00–04:00; the named anchors resolve to their canonical lakes, zones, and chart positions.
- Each of the twelve quest IDs can reach active, ready, and completed using only its specified events; all progress survives save/load.
- Legacy saves without narrative_v1 still load with their fishing progress intact.
- Deployed-line IDs survive save/load; pulling another line cannot change a quest's target, and redeployment cannot inherit the old deployment's progress. Lake travel requires pulling all lines and preserves only historical quest references to those ended deployments. Legacy ID migration emits no retroactive set event.
- q01 uses Bot's strict midpoint distance cutoff: a line exactly 140 game metres away is ineligible. An in-flight line scout retains its launch-time target ID across save/load even if the boat moves closer to another line; legacy scouts without that ID cannot receive line-specific quest credit.
- q08 counts only actual path portions within cedar:open, including updates that cross its boundary; outside portions, tow movement, and repositioning contribute zero.
- q12 advances landing → lilies → landing only through qualifying player-controlled boat entries; tow calls and load/travel placement cannot satisfy any leg.
- Exactly ten unique Ripple IDs can be earned; the optional Guardian can be seen after eight and is retryable on later windows.
- Dialogue, journal counters, event fields, reward values, units, and zones match this contract.
- Each active NPC can trigger at most one proximity reaction per save, and each successful quest turn-in can trigger at most one completion reaction. Notes survive save/load and appear in the narrative journal; toasts do not block control. Neither reaction changes fishing, movement, quest progress, or rewards, and ordinary scouting report content remains unchanged.
- Fishing and lake travel remain playable without opening the quest journal or accepting any quest.
