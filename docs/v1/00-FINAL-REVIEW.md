# Trotline Purridise V1.0 — Third and Final Review

*Design & narrative lead review · 19 October 2026*
*Inputs: the five Gemini V1.0 drafts (Canon, Gameplay/Narrative Spec, Characters,
Script, Implementation Guide), the second review (`Trotline-Purridise-V1-Second-Review-2026-10-19.md`),
the V3 package and Gemini review in Drive, and the current `main` build.*

## Verdict

The Gemini drafts had a charming premise (water-cats, a robot deckhand, five very
different waters) and enough named content to seed a world. As specs they were
not buildable. Core rules contradicted the cozy no-fail pillar. Counts didn't add
up. The drafts ignored what was already built. Numbers broke under the game's own
clock. The script had about 30 lines for a 52-character cast.

This review replaces them with a complete, internally consistent V1.0 packet:

| File | What it now provides |
| --- | --- |
| `01-CANON.md` | Title, identity, pillars, truth rules, five lakes, the *Book of Five Waters* story spine, Bot, 12 legendaries |
| `02-GAMEPLAY-SPEC.md` | All systems with numbers: modes, clock, comfort, fishing, haul view, book, legendaries, shinies, boats, Bot tools, NPCs, quests, economy, controls, accessibility |
| `03-CONTENT-TABLES.md` | All 144 species with stats, 12 legendaries with gates, 9 baits + 8 recipes, 10 dishes, 24 boats, Bot shells, zones, Lake Days |
| `04-CHARACTERS.md` | All 52 cats; 44 water-cat encounters have A/B quests, 5 hosts have one errand each, and 2 travelers have no quests |
| `05-SCRIPT.md` | The full story script, host lines, Bot barks with true/uncertain pairs, lines for every water-cat, 144 rumors, 34 Ripples, letters, system copy |
| `06-IMPLEMENTATION-GUIDE.md` | Module map against the real code, content-v2 data, save v2 + migration, formulas, the procedural art plan, a 3 GB memory budget, testing |
| `07-TICKETS.md` | 44 ordered tickets, model-tagged, mirrored as GitHub issues |

The owner asked for no further decisions, so every open question is decided here
and recorded in the decision log below.

---

## 1. Decision log (made on the owner's behalf)

| # | Decision | Why |
| --- | --- | --- |
| D1 | **Cozy is the default and is truly no-fail.** Needs are positive choices (catnap clues, meal buffs). **Old Salt** is opt-in light routine with no blackout, no sickness, no stranding | The Gemini survival rules (12 h blackout, 80% spoilage, starvation tow priced at 15% of boat value) broke the cozy pillar and could strand a broke player. This keeps the second review's two-mode direction |
| D2 | **Start in the existing jon boat** ("Grandmother's old boat"), not the Cedar Log Raft. Tier-1 pioneer craft become cheap specialty boats | Existing saves and tuning start in the jon boat. A paddle-only raft made the first hour slower and duller |
| D3 | **Boats are sidegrades with traits** in 8 parametric families (24 boats) | A strict 24-step ladder is content debt with little play value. Traits (shallow, silent, galley, hammock…) create real choices |
| D4 | **144 = existing 36 + 6 Cedar + 34 × 3 new lakes.** Real species keep real names; protected species are always released | Gemini's per-lake counts (28/30/29/29/28) summed to 144 but conflated the 36 existing game species with species shared by both lakes; six Briar specialties are intentionally absent from Cedar |
| D5 | **12 legendaries, distributed 2/3/3/2/2**, with two *witnessed* (Guardian, Star-Whale) | Gemini's table listed only 9. Witnessed legendaries put wu wei into the mechanics |
| D6 | **The Whiskered Guardian stays at Cedar deep** (as implemented) | Gemini moved it to Briar. That would have broken shipped V3 behavior |
| D7 | **Story spine: *The Book of Five Waters*.** The second review's inherited-book spine, finished with five concrete chapters, a collar arc and an ending | The drafts had no connected journey |
| D8 | **Book stages 0/1/3/5/10** with *What we heard / What we found*; titles Fishypedia → Book of Five Waters → Pescapedia | Gemini's "Bot auto-corrects folklore after 10 catches" made neighbors wrong and gave no help while learning |
| D9 | **Shinies:** 1/64, standard species only, saved at catch, tracker pity at 50, 3× price, Treasured by default | It is a measurable rule. Unique legendaries can't have fair shiny odds |
| D10 | **The Nebula is the night sky's reflection, reached from Crater**, not "a far-off galaxy" | It gives a diegetic, gentle way to get there and ties the finale to the chapter 4 discovery |
| D11 | **Crater Caldera is a lake**; "Reservoir" is dropped. Flathead and Crater are fictionalized and procedural (no park or survey data) | It fixes a factual error and avoids data and licensing work |
| D12 | **Visible NPCs** (a procedural cat rig) and **illustrated fish cards** are core scope | NPCs were invisible anchor points at review time; the cat rig (`catmesh.py`) now draws them. A 52-cat game needs to show its cats |
| D13 | **The haul view** (running the line hook by hook) is the signature interaction | The existing check menu is the least expressive moment of the loop |
| D14 | **Hail stays at 20 m below 3 knots** (implemented), not Gemini's 15 m | It keeps shipped behavior |
| D15 | **Offline soak stays** (existing). Needs and NPC timers don't run offline | The second review proposed no offline time at all, which would remove a shipped cozy feature |
| D16 | **Bot is "he"** (existing canon) with a plate *Deckhand Unit 04* + `Word-###`; prefix "Pebble" → "Rivet" | It reconciles V3's "Deckhand Unit 04" with Gemini's procedural names, and avoids the clash with the cat Pebble |
| D17 | **Gamepad support is in scope** | Gemini promised a Right Bumper hail; the build had no pad support at review time (now `fishing/gamepad.py`) |
| D18 | **Player-facing title: *Trotline Purridise***; Little Briar is the first lake | It resolves the title ambiguity both earlier reviews flagged |
| D19 | **Memory target ≤ 2.6 GB peak**, with the hard cap at 3 GB as today | The owner wants depth that "approaches" 3 GB; headroom protects against driver variance |

---

## 2. Findings against the Gemini V1.0 drafts

Severity: **Blocker** means it can't be built or breaks a pillar or shipped
behavior. **Major** means players would feel it or implementers would diverge.
**Minor** means polish or consistency.

1. **[Blocker] Survival rules contradict cozy no-fail.** Blackout, malnourishment
   that removes steering and hauling, 80% spoilage, and a value-scaled tow can
   strand a player. → D1, `02 §2`.
2. **[Blocker] Time math breaks under a 24-minute day.** "2 h nap per 4 h awake"
   means napping every 4 real minutes. "Eat 2 lb every 24 in-game minutes" and "per
   day" contradict each other. → `02 §2–4`, every number stated in game time.
3. **[Blocker] The drafts ignore the shipped game.** 12 V3 quests, Ripples, the
   Guardian at Cedar, Trinidad Cove, 4 boats with physics, 3 line tiers, 36
   species, offline soak, and the `saves/briar.json` format. The implementation
   guide proposed a replacement save and parallel modules. → `06 §0–3`.
4. **[Blocker] The implementation sample crashes.** `current_boat_index: 2` on a
   two-element list. (The second review found the same.) → `06 §3.3`.
5. **[Major] Counts don't reconcile.** 12 legendaries vs 9 listed; 52 NPCs vs 17
   named; "10–12 per lake" vs "9–10 rotating"; lake species counts vs the existing
   shared 36. → D4, D5, `04 §5`.
6. **[Major] The script covers about 5% of what's needed.** No connected story,
   two sample quests, five host greetings. → `05` is complete for the story, the
   hosts, Bot and all 45 water-cats.
7. **[Major] NPCs and fish were invisible.** At review time the build had no cat models and no fish
   art, so 52 cats and 156 fish would have been text (both now exist: `catmesh.py`, `fishart.py`). → D12, `06 §6`.
8. **[Major] The core interaction is thin.** "Set, wait, check menu" doesn't carry
   50 hours. → split baiting, the haul view, Lake Days, recipes and watch cards
   (`02 §1`).
9. **[Major] Bot tools reference mechanics that don't exist.** Line snaps (the
   winch), drifting in lily beds (the reed anchor), and temperature (the scanner).
   → each tool gets a defined mechanic: reeds zones, currents, thermocline
   (`02 §5.2`, `06 §5`).
10. **[Major] The economy is undefined.** No prices for 20 boats, meals, tools or
    recipes, and no income curve. → `02 §15`, `03`.
11. **[Major] There are no unlock or travel rules for lakes 3–5.** → `01 §4`,
    `02 §14`.
12. **[Major] Factual barks aren't backed by state.** "Thermocline at 14 ft",
    "trout biting deep today". → truth rule `01 §3` and `[F]/[U]` pairs in
    `05 §5`.
13. **[Major] Unsafe staging for kids.** Spillway foam, high-speed turns by the dam.
    → the Marked Pool, the practice-buoy cove (`05 §4.2`, `§6.2`).
14. **[Major] The pre-ticked QA checklist** claimed verification that never
    happened. → removed; tests are specified in `06 §9`.
15. **[Minor] "Corat"** → Korat. **"Skipper name: Barnaby"** contradicted canon.
    **"it"** for Bot contradicted canon. **"Pebble"** prefix collided with a cat
    name. **"Squawfish"** is an outdated name for the pikeminnow; it isn't used.
16. **[Minor] "Reservoir" for Crater Lake is factually wrong.** "Flathead Alpine
    Lake" needed a fictionalization note. → D11, `01 §3`.
17. **[Minor] Mechanics leak into V3 dialogue** ("less than 140 game metres from
    the boat"). → `05 §0` rule 1; the V3 lines stay as shipped, and new content
    follows the rule. V1-43 recopies the V3 lines.

## 3. Disposition of the second review's findings

| # | Topic | Disposition |
| --- | --- | --- |
| 1 | Separate story ending from book completion | **Adopted** (`01 §5`, `02 §6`) |
| 2 | Five-lake spine with small problems | **Adopted and finished**: five chapters with steps, rewards and unlocks (`02 §13`, `05 §2`) |
| 3 | Knowledge arrives too late | **Adopted**: 0/1/3/5/10 stages |
| 4 | Don't auto-replace folklore | **Adopted**: two persistent columns |
| 5 | Bounded finale wait | **Adopted**: 45 s, three cues, pause-not-reset, "Watch together" |
| 6 | Collar as an arc | **Adopted**: four beats, cosmetic knot choice, hide option |
| 7 | Mode-switch safety | **Adopted** (`02 §2.2`) |
| 8 | Cozy positive nudges | **Adopted with changes**: catnap dream-clues, dish buffs, weather invitations; prompts throttled |
| 9 | Rescue always completes | **Adopted**: fee capped at cash, shortfall waived; free in Cozy |
| 10 | Clock behavior | **Adopted for menus. Modified for offline**: the existing offline soak stays (D15) |
| 11 | Promise persistence and NPC availability | **Adopted**: round-robin within 3 days, pins, turn-in at host |
| 12 | Legendary eligibility cards | **Adopted**: watch cards, guaranteed hook, weather planner |
| 13 | Shiny rule and bad luck | **Adopted with changes**: 1/64 + pity at 50; standard species only (D9) |
| 14 | Chassis independent of tools | **Adopted** |
| 15 | Cherished fish | **Adopted**: Treasured, protected and legendary dispositions |
| 16 | Want, contradiction, return line per cat | **Adopted for all 45 water-cats and hosts** |
| 17 | Factual barks need state | **Adopted** as the truth rule |
| 18 | Kid-facing staging | **Adopted** (Marked Pool, practice buoys, "Warm your paws") |
| 19 | Persistence contract | **Adopted**: save v2 with exactly-once claims and pending scenes |
| 20 | Index bug | **Adopted** |
| 21 | Real vs fictional waters | **Adopted**: "In these waters" |
| 22 | Clone/package parity | **Adopted**: V1-40 |

## 4. What I deliberately cut or deferred

- **Ice fishing** (implied by Huckleberry's role): Flathead is open water in snow
  mist. Ice would need a whole new interaction.
- **Seasons:** a 7-day calendar with Lake Days gives rhythm without a seasonal
  content multiplier.
- **Physical inter-lake channels:** travel stays menu-based (existing).
- **Rod-and-reel and any fish-fighting fail state:** never. The haul can't fail.
- **Real survey data for Flathead and Crater:** procedural "inspired by" lakes
  keep the build offline and license-clean.

## 5. Risks to watch during production

1. **Art volume** (52 cats, 156 fish, 24 boats, 3 lakes) is the long pole. It is
   all parametric by design; protect that, and resist hand-authored one-offs.
2. **Memory** with 5 lake palettes, portraits and card caches: enforce the LRUs
   and the per-subsystem benchmark accounting from the first art ticket.
3. **Content transcription drift** across 111 quests: the validator and a scripted
   playthrough test per lake are mandatory (V1-32, V1-33).
4. **Software-renderer parity:** every visual ticket must keep `--selftest
   --software` green, because CI runs it.
