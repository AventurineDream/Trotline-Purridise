# Nearby conversations (Ticket 6)

C hails the nearest currently present NPC from the boat or chart, at horizontal
range at most 20 game metres and absolute speed strictly below 3 knots. Boat
speed is metres per second; the cutoff is `3 * 1852 / 3600` m/s, including in
reverse. A procedural paw-wave prompt names the eligible NPC. H remains Help;
E still checks a line or opens the landing, including Cedar's original shop.

The bottom panel traverses the validated content graph. C, Enter or Space
advances a line or selects the highlighted numbered choice. W/S and arrows
change the selection; number keys select directly. Esc leaves without making a
choice and restores the boat/chart view. H opens Help and returns to the panel.
The clock, deployed lines and Bot continue during dialogue. Boat controls are
ignored, the engine idles and the sail lowers as with other running menus.
Navigation keys held on leaving must be released before driving again.

Opening dialogue grants no progress. An explicit acceptance changes available
to active and records the game minute; declining leaves the offer available
and persists the declined flag. Both survive the existing save format. Active,
ready and completed quests use their authored state-specific entry nodes.
A departing scheduled giver closes the conversation; quest state is retained.

Ticket 7 owns objective evaluation and Ticket 8 owns atomic turn-ins/rewards.
Until then, the ready turn-in action closes with a truthful availability notice,
keeps readiness and money unchanged, and never displays the payout response.
No event evaluator, rewards or new fishing mechanics are introduced here.
The contract was read from the authoritative private Drive file (modified
2026-10-16T22:39:29.832Z); its hailing and offer rules agree with the merged
repository mirror. No design-source change was needed.

`python -m unittest fishing.test_dialogue -v` exercises eligibility, native SDL
bindings, branching, persistence, menu return, held-key release, simulation and
safe handling of schedule changes and deferred rewards. The required gameplay
self-test invokes this suite through `dialogue_checks()`.
