# V3 chart locations

Ticket #4 implements the fixed locations in sections 2.2 and 3.1 of the
[V3 contract](V3-QUEST-IMPLEMENTATION-CONTRACT.md). Each `World` exposes an
immutable `anchors` mapping for its own lake. Resolve a content NPC with
`world.anchors[npc['anchor_id']]`; a missing or off-lake ID raises `KeyError`.
Each frozen `Anchor` supplies its namespaced ID, parent `zone_id`, display
name, X/Z `position`, `kind`, and a checked `player_position` (X, Z, yaw).

All twelve NPC references resolve. The canonical X/Z coordinates remain fixed
across world construction and lake travel. The locations are independent of
random placement, fishing RNG, clock, saves and future schedule selections.
The two named Cedar water waypoints, Trinidad Cove and Lonely Star Deep, are
also exposed. Lonely Star Deep is an alias within the existing Southern basin;
it does not create a fishing zone. East Cove is not an approved new zone.

| NPC | Anchor | Parent zone | X | Z | Placement |
| --- | --- | --- | ---: | ---: | --- |
| Grandmother Whiskers | briar:landing | briar:landing | -435.789 | 107.381 | Dock host |
| Doc Barnaby | cedar:docs_marina_dock | cedar:open | -186.451 | -400.499 | Dock host |
| Elder Moss | briar:cypress | briar:cypress | 330.000 | 20.000 | Water |
| Pip & Pebble | briar:flats | briar:flats | 10.000 | 205.000 | Water |
| Master Cinder | briar:deep | briar:deep | 75.000 | -25.000 | Water |
| Willow | briar:lilies | briar:lilies | -175.000 | -115.000 | Water |
| Silas | briar:inlet | briar:inlet | -210.000 | 155.000 | Water |
| Captain Maeve | cedar:open | cedar:open | 0.000 | 0.000 | Water |
| Sparky | cedar:inlet | cedar:inlet | -423.772 | 948.817 | Water |
| Quill | cedar:flats | cedar:flats | -234.448 | 509.948 | Water |
| Dr. Alder | cedar:deep | cedar:deep | 330.854 | -754.864 | Water |
| Patch | cedar:lilies | cedar:lilies | 632.171 | -964.758 | Water |

## Doc's marina mapping

The public marina site in issue #4 is the owner-confirmed former Docs site,
currently identified there as Lone Star Marina at Cedar Creek. The fictional
name stays **Doc's Lonely Star Marina**. Its game position comes from the
merged contract, not Cedar's existing Caney Creek landing or a place centroid.
The contract records the nearest modeled water point to the supplied marina
pin, `(-186.451, -400.499)`, in `cedar:open`.

The chart uses the [TWDB 2017 Cedar Creek survey](https://www.twdb.texas.gov/hydro_survey/cedarcreek/2017-10/CedarCreek2017_FinalReport2.pdf),
NAD83 State Plane Texas North Central (US survey feet). The contract's
latitude/longitude conversion provenance is [NOAA NGS NCAT](https://www.ngs.noaa.gov/NCAT/).
The current asset records the survey origin and scale in `cedar.json`:

```text
origin easting  = 2700043.5562172392 feet
origin northing = 6799489.036218292 feet
feet to game metres = 0.03048006096  (horizontal scale 0.1)
X = (survey_easting  - origin_easting)  * feet_to_game_metres
Z = (survey_northing - origin_northing) * feet_to_game_metres
```

X points east and Z north. The frozen marina water point and the water-only
Trinidad Cove point `(186.862, -855.722)` are retained exactly from the contract;
this implementation does not geocode them again, move the shoreline, or modify
the survey asset. A future asset rebuild must preserve these fixed points or
fail the anchor regressions for explicit review.

## Dock references and safe approaches

A dock host's reference point is not an NPC boat spawn. Grandmother's reference
is the existing slip centre. Placing another boat there would obstruct the
player's launch lane. Her checked player approach is `(-424.138, 104.510)` with
yaw `1.81238898038469`, twelve metres out from the slip origin. Doc's reference
is point-navigable, but is too close to shore for an entire player hull. His
checked approach is `(-182.208, -396.256)` at yaw zero, six metres from the
reference and inside the contract's 20-metre hail range. Rotating NPC water
anchors are outside the 50-metre landing exclusion. Their default checked
player position is the anchor with yaw zero.

Trinidad Cove keeps this fixed water anchor and adds a short bank-side timber
launch, cypress shade, reeds and stone detail on the west side. These are
rendered scene details only: they do not move the surveyed shoreline, create a
new fishing zone, or obstruct the existing route to the anchor. Shop, fuel,
travel menus and player start/docking positions keep using the existing landing.

## Validation

`validate_anchors(world)` rejects wrong-zone or non-navigable points, blocked
full-hull approaches for any boat model in `boat.BOATS` (24 in the shipped data), approaches beyond the
hail radius, and water NPCs inside the landing exclusion. It never relocates a
site. It is invoked by regressions rather than on every frame or startup.

`python -m unittest fishing.test_anchors -v` covers content resolution, chart
coordinates and labels, all boats' draft/shore/prop/dock clearance, launch-lane
passage, immutable lookups, damaged-chart rejection, actual lake travel,
reconstruction and state preservation. A conservative four-metre connectivity
grid checks that each interaction site can be reached within hail range from
the landing exit, using the deepest boat draft and clearance for the largest
hull, dock barriers and solid props. This is a sampled chart regression, not a
runtime navigation system. The full software self-test runs these checks too.
