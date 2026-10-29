# V1-28 evidence: fish looks for 144 species and 12 legendaries

All captures are from `python -m fishing --shots docs/issue-56/native --fish`, run
natively on Mesa llvmpipe. The cards pass through the GL paint pass, as players
with a GPU see them. The haul sprites, idles and the look-alike check are drawn
on the CPU, the same as in game.

| File | What it shows |
| --- | --- |
| `cards-<lake>.png`, `cards-<lake>-shiny.png` | Every species on the lake, field and shiny |
| `cards-legendaries.png` | The 12 legendaries |
| `haul-<lake>.png`, `haul-legendaries.png` | Each fish's haul mesh, as the haul's surface beat draws it |
| `legendary-idle.png` | Each legendary's idle: six poses across one loop, three-quarter underwater view, then the Reduced Motion pose |
| `lookalike.json` | The automated check: thresholds, every lake's closest pairs, failures (none) |
| `lookalike-closest.png` | The three closest same-lake pairs per lake, side by side |
| `benchmark.json` | Timings, triangle counts, idle checks, cache and memory |

## The automated look-alike check

`fishing/fishcheck.py` compares every same-lake pair at book thumbnail size,
128×64. The lake's legendaries are included: 3,370 pairs over the five lakes.

A pair fails only if both of these hold:

- **Silhouette:** IoU ≥ 0.90.
- **Palette:** soft CIE Lab histograms of the back, flank and belly thirds
  overlap by ≥ 0.60.

**Result: 0 failures.** No pair comes within 0.015 IoU and 0.03 overlap of
failing on both measures.

The closest pairs by lake:

| Lake | Fish | Closest pairs (IoU / palette overlap) |
| --- | --- | --- |
| Briar | 36 + 2 legendaries | hybrid striper / white crappie 0.881 / 0.725; black / white crappie 0.845 / 0.559 |
| Cedar | 36 + 3 legendaries | the same two pairs as Briar |
| Flathead | 34 + 3 legendaries | lake chub / mottled sculpin 0.860 / 0.637; bull trout / peamouth 0.895 / 0.567 |
| Crater | 34 + 2 legendaries | Klamath smallscale sucker / prickly sculpin 0.859 / 0.595; ash minnow / blue chub 0.855 / 0.656 |
| Nebula | 34 + 2 legendaries | moonbeam crappie / twinkle shad 0.811 / 0.750; halo whitefish / twinkle shad 0.808 / 0.553 |

In every case the second fish differs visibly: bars against stripes, a sculpin's
fan pectoral against a chub's slim fins, and stars against bars.

**What the check found.** I ran it while authoring.

1. **First draft, originals still on the old painter.** It flagged 33 lake
   pairs. Several original species had near-identical palettes:
   - bluegill and redear (overlap 0.84);
   - the four gars;
   - the bullheads;
   - channel catfish and drum.
2. **After the originals moved to the new painter.** 14 pairs still failed,
   mostly drab Flathead and Crater minnows, suckers and trout.
3. **Follow-up rounds.** Each pair was fixed with a true-to-life difference,
   never an invented colour:

- **Field marks:**
  - The sunfish ear flaps.
  - The bowfin's tail eyespot.
  - The shads' shoulder spots.
  - The pikeminnows' longer heads.
- **Breeding or regional colour:**
  - Red spawning kokanee with a kype.
  - The tiger trout's vermiculation.
  - The brassy lake chub.
  - The mountain sucker's red band.
- **Body shape:**
  - The deep black crappie, beside the slimmer white crappie.
  - The stout fathead minnow, Alvord chub and Oregon chub.
  - The slender sauger, beside the walleye.

`test_fishlooks` checks that the real data has no failing pair. It also checks
that copying the bluegill's look onto the redear is caught.

## Manual review note

I reviewed every lake sheet, the shiny sheets and the legendary, haul and idle
sheets, along with individual cards at full size wherever a sheet raised a
question.

**One style for the whole book.** The 32 original Briar and Cedar species used to
share a separate, older painter. Their palettes were also duplicated, so the
check above could not pass without repainting them. All 156 fish now share one
painter and one look format.

**Briar and Cedar.**
- **Sunfish:** each is told apart by its ear flap, as anglers do.
  - Bluegill: black flap, dusky bars.
  - Redear: red-edged flap, speckled.
  - Green sunfish: pale-edged flap, turquoise flecks, yellow fin edges.
  - Longear: long white-edged flap, orange with blue worm marks.
  - Redbreast: long black flap, red-orange breast.
  - Warmouth: red eye, mottled.
- **Catfish:**
  - Channel: spotted, forked tail.
  - Blue: humped, plain blue-grey.
  - Flathead: mottled, with a jutting lower jaw and square tail.
  - The bullheads: yellow, black and mottled brown, with rounded or square tails.
- **Gars, by snout:**
  - Longnose: long and thin.
  - Spotted: medium and heavily spotted.
  - Shortnose: short and plain.
  - Alligator: short and broad, with a flat head, blotches and scutes.
- **Others:**
  - The bowfin carries its eyespot.
  - The carp shows its large scales as a net.
  - The threadfin shad has its yellow fins.

**Flathead.** These are true-to-life Montana fish:
- The salmonids:
  - The lake and bull trout carry pale spots; the brook trout's red spots are
    haloed.
  - The cutthroat carries its red throat slash.
  - The golden trout has its parr marks.
  - The grayling has its sail fin.
- The white sturgeon has scutes, barbels and a heterocercal tail.
- The burbot has its chin barbel.
- The walleye and sauger are separated by saddles and blotches.
- The suckers and minnows are separated by mouth, band, depth and tone.

**Crater.**
- The Oregon and Great Basin fish are true to life: redband, coastal and
  Lahontan cutthroat, Chinook and coho, and the chubs, dace and suckers.
- The caldera fish keep their family shapes and use the caldera's indigo, ash,
  ember and obsidian:
  - The ember char and lava-belly sunfish carry a warm glow.
  - The glasswing trout and mistfin dace have glassy pale fins, the dace a
    flowing veil.

**Nebula.** The cosmic fish read as their family first, then as cosmic:
- Comet minnow: a streaked trail.
- Saturnfin puffer: a ring that passes behind and in front of the body.
- Prism ray: a spectral disc.
- Purrsec lanternfish: a lit lure.
- Halo whitefish: a halo.
- Comet-tail betta: a veil tail.
- Star patterns sparkle on the shad, gar and char.

**Legendaries.** Each has a bespoke look and an idle:
- Old Lantern: a gold catfish with glowing spots.
- The Lily Queen: a chain-patterned pike with cream fin edges.
- The Spillway Monster: a slate catfish, mottled.
- The Channel Leviathan: a scuted gar with a broad head.
- The Whiskered Guardian: a violet-to-amber glowing catfish with gold worm marks.
- The Glacial Phantom: ice-white with a pale glow.
- Old Silverhead: a humped, kyped steel trout with a blue sheen.
- Huckleberry's Whopper: a purple-blotched burbot.
- The Obsidian Gar: near-black with silver speckle.
- The Caldera Fire-Lizard: an ember salamander with gills and legs.
- The Nebula Weaver: a ribbon-finned cosmic fish with a flowing veil.
- The Celestial Star-Whale: starry, with a fluke.

**Idles.** Each idle is slow, from 0.18 Hz for the Star-Whale to 0.65 Hz for the
Weaver, and loops exactly. The head stays nearly still while the tail sways.
Under Reduced Motion the fish holds its resting pose.

**Haul meshes.** Each haul sprite matches its card in outline and paint. For
every fish, the silhouette IoU against the card is at least 0.92.

## Budgets (`benchmark.json`)

| Measurement | Result |
| --- | --- |
| Card requests | 348 (174 lake entries, field and shiny), median 40.9 ms through the GL paint pass; Cedar's 30 shared species are cache hits |
| Haul mesh build | median 49.8 ms, including its card, once per fish per session |
| First haul sprite in game (CPU) | median 187 ms, up from 95 ms on main, because the mesh paints the card first. The "A fish surfaces" panel then reuses that card, so a catch costs 182 ms against 139 ms on main. |
| Haul triangles | 1,312–1,662 (median 1,602) |
| Idle frame (192×96, CPU) | median 81.9 ms |
| Idle loops | 3.1–11.1 s; every loop closes and every Reduced Motion pose is still |
| CPU card cache | 18.9 MB at its 48-entry limit, under the 25 MB budget |
| Peak RSS | 272 MiB against the 3 GB cap |

## Other changes

- **`legendaries.json`** joins the validated content files.
- **`test_species` pin.** It still pins the original 36 species rows, now
  without their `look`. `docs/issue-56/baseline.json` records those digests.
  At base commit `1ee9607` the full rows still matched
  `docs/issue-52/baseline.json`, and only `look` changed afterwards.
- **Updated tests.** `test_fishmesh` locates whiskers and snouts from the
  shared geometry instead of fixed pixel boxes. The long-snout check moved to
  the longnose gar, whose snout is the longest; the alligator gar's is short
  and broad.
