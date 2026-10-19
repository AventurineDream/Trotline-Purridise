# Validated narrative content (Ticket 3)

`fishing/assets/narrative_v1.json` contains the two permanent hosts, ten rotating
quest givers, twelve independently available quests, cash and Ripple rewards,
and the complete dialogue graph. `fishing.content.load_content()` validates the
whole bundle before returning `NarrativeContent` indexes named `npcs`, `quests`,
`rewards`, and `dialogue`. It resolves its default path relative to the module,
not the process working directory. Each call returns a fresh bundle.

Run `python -m fishing.content` to validate the shipped data, or pass a candidate
path to `load_content(path)` from an authoring tool. Invalid content raises
`ContentError` with the file path and offending ID/field (or row index if the ID
itself is missing). Errors are collected so an author can fix several broken
links in one pass. Duplicate JSON keys, IDs and choices, unsupported objective
fields/types, unknown game IDs, wrong lakes, invalid clock windows, orphaned
rewards, invalid Ripple mappings, missing dialogue targets, wrong speakers,
unreachable nodes and dialogue cycles are rejected. Malformed optional content
is never silently loaded as partial valid content.

## Authority and authored text

The merged [V3 Quest Implementation Contract](V3-QUEST-IMPLEMENTATION-CONTRACT.md)
is normative. The private Drive sources read for this ticket were:

- [Contract v1](https://drive.google.com/file/d/1Ahwiz4FDU4BktsPS2KvH9p7dpkh4pSEA/view),
  modified 16 October 2026. Its text agrees with the merged repository mirror.
- [Script-v3](https://drive.google.com/file/d/19XoBsm0SbYQ2Bj6_hc3_qHt7xfs6iu0T/view),
  modified 15 October 2026.
- [RelationshipAndQuestFlowmap-v3](https://drive.google.com/file/d/10Pfo5MRg0eR88GDghT3R-ZVSWliyrWi0/view).
- CanonSheet-v3, ImplementationGuide-v3 and GameplayNarrativeUpdateSpec-v3,
  read to confirm the roster, optionality and integration boundary.

Source URLs and normalized-text SHA-256 values for the contract and script are
stored in the bundle. Greetings, ready responses, hand-in responses and decline
branches retain the script's authored text. Accept, active-progress, ready-wait
and completed-return branches add connective text for the new graph. Offer
wording is aligned to the later contract where the earlier script is stale:

- Willow qualifies the time of **livewell entry**, after acceptance, during
  05:00–08:00. Hook time does not determine eligibility. The source line may
  predate acceptance, and the fish is not consumed.
- All four soak quests require 60 **active-play game minutes** for the same
  deployment, excluding time while the game is closed.
- Bot's nearest eligible line must be **strictly less than 140 metres** away.
  His existing ordinary depth class is sufficient. q11 needs the report before
  its qualifying line check; q01 needs no line check.
- Patch requires fresh player-controlled boat entries into landing, lilies,
  landing, in order. Tow, load and lake-travel placement do not count.

The Drive sources are retained as read; this ticket does not rewrite them or the
normative contract. The bundle records these adaptations explicitly. The older
specification's schedule formula is not implemented here; Ticket 5 must use the
contract's `floor(game_minutes / 1440)` rule, with clock zero at 06:00.

## Stable IDs and future consumers

Existing `QUEST_IDS`, `RIPPLE_BY_QUEST` and `DAY_NPCS` in `fishing.narrative` remain
the save authority. Content IDs match those constants. NPC IDs map back to one
quest and the same lake; Doc uses `cedar:docs_marina_dock`, independent of the
Cedar landing menu. Anchors are namespaced references, not newly placed actors.
Ticket 4 owns chart anchors and navigability validation.

Each quest contains a stable `<quest-id>:objective`, a reward reference, and
entry nodes for `available`, `active`, `ready` and `completed`. There are nine
nodes per quest: greeting, offer, accept, decline, progress, ready, ready-wait,
completion and return. Node IDs are `<quest-id>:dialogue:<stage>`; choice IDs are
`<quest-id>:choice:<action>`, with `later` for the ready-wait branch. A node has
either `next` (null closes) or a nonempty list of choices with explicit target
and action. Only the available entry can reach accept/decline actions, and only
the ready entry can reach turn-in/close actions. The data loader executes none
of these actions. Dialogue applies them to live state, checks readiness and
giver presence again, and uses the existing idempotent reward-claim ledger
before paying the supported cash and Ripple. Turn-in leaves catches in the
livewell; the current contract defines no fish consumption or physical quest
reward.

All objectives begin observation after acceptance. Supported type semantics are:

| Type | Required event interpretation for Ticket 7 |
| --- | --- |
| `line_scout` | Record a qualifying new `line.set`, then a delivered `bot.scout_complete` for that immutable line ID; launch uses nearest-line strict range; ordinary depth class is enough. |
| `line_check` | Record the new deployment's tier, hooks, bait, set zone and active clock; check the same ID after the active soak. Optional set window uses set-time game clock. No fish is required. |
| `line_scout_check` | Same as line check, with a qualifying ordinary report for the same deployment before the check. |
| `anchor_idle` | Advance only foreground anchor samples in the target zone with anchor set and engine idle; any interruption resets the continuous timer. |
| `scout_report` | Delivered Bot report with scout point in the target zone; no line, exact depth or new instrument required. |
| `fish_livewell` | Qualifying species transferred after acceptance from a line set with the named bait/zone; evaluate the entry-time window. The source line may predate acceptance. |
| `travel_distance` | Actual accepted player movement path portions in the named zone, by motor or sail, counted once. Exclude outside portions, tow, load and travel placement. |
| `visit_zones` | Record each listed `zone.enter` after acceptance in any order, following the contract's q10 event rules. |
| `visit_sequence` | Record each listed entry in order, including the repeated landing. Require boat movement provenance and player control; excluded placement never advances or resets a leg. |

Zones in objectives are existing fishing zones, never story waypoints. Clock
windows store minute-of-day endpoints in [0, 1440), start included/end excluded;
start greater than end wraps midnight. They are local clock values, not elapsed
`State.game_minutes`: the latter starts at 06:00. Durations are game minutes,
distance is game metres, and cash is whole game dollars. Reward definitions
contain only cash plus an optional unique Ripple. Host quests award no Ripple.
There are no quest prerequisites, consumption costs, physical items or unlocks.

This document originally described Ticket 3's definitions and validation.
Tickets 4–8 have since added actors, schedules, hailing, event adapters, progress
evaluation and contract-supported turn-in rewards. Guardian behavior remains
with its roadmap ticket. Existing fishing data and assets are unchanged. The full
software self-test includes `fishing.test_content`, so the existing required
`gameplay-tests` workflow validates the content through its normal path.
