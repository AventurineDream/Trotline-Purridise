# Trotline Purridise — V1.0 Content Tables

*Data source for `fishing/data.py` and `fishing/assets/content_v2/*.json`. Ids are
stable save keys: never rename an id after it ships. Prices are game dollars;
`$/lb` uses the existing `Species.price` unit (value = price × lb × quality).*

## 1. Species — 144 standard

### 1.1 Tier defaults

Use these unless a row overrides them. `rate` and `trophy` have the same meaning as
`data.Species`.

| Tier | Code | rate | trophy | Book rumor teller |
| --- | --- | --- | --- | --- |
| Common | C | 0.030 | 0.04 | Any cat of that lake |
| Uncommon | U | 0.012 | 0.04 | A named water-cat |
| Rare | R | 0.005 | 0.05 | A named water-cat or host |
| Very rare | V | 0.0015 | 0.05 | A host |

**Columns:** *Time* ∈ dawn/day/dusk/night (existing `pref_time`). *Baits*: primary
(match 1.0) / secondary (match 0.6). Every other bait gets 0.05 (existing fallback).
*Zones*: primary 1.0, then 0.7 for each listed after it, and 0.07 elsewhere.
*Depth* in metres (displayed in ft). *Food* is the cooking group (`none` means it
can't be cooked). *Tags*: `surface` (Wave Chime), `cold` (thermocline), `shy`
(silent boats), `current` (Zero-G Winch), `protected` (always released, no price).
*Shiny* palette: albino, golden, starry, glow, ink, rose.

### 1.2 Existing 36 (stats unchanged in `data.py`; new columns only)

Lakes: **B** = Little Briar, **C** = Cedar Creek (existing `CEDAR_FISH`). The six
Briar specialties absent from Cedar are marked B only.

| id | Folk name | Lakes | Food | Tags | Shiny |
| --- | --- | --- | --- | --- | --- |
| bluegill | Sunny | B C | panfish | surface | golden |
| bullhead | Mud Kitten | B C | catfish | — | albino |
| crappie | Papermouth | B C | panfish | shy | starry |
| carp | Golden Bucket | B C | hearty | — | golden |
| drum | Grunter | B C | hearty | — | glow |
| channel | The Wage | B C | catfish | — | albino |
| blue | Old Blue | B C | catfish | — | glow |
| flathead | Yellow Cat | B C | catfish | shy | golden |
| largemouth | Bucketmouth | B C | bass | surface | golden |
| smallmouth | Bronzeback | B | bass | — | rose |
| gar | Needle-Nose | B C | hearty | surface | starry |
| buffalo | Drifter | B C | hearty | — | albino |
| white_crappie | Silver Paper | B C | panfish | shy | starry |
| redear | Shellcracker | B C | panfish | — | rose |
| green_sunfish | Green Grump | B C | panfish | — | golden |
| warmouth | Goggle-Eye | B C | panfish | shy | ink |
| redbreast | Copper Belly | B C | panfish | — | rose |
| longear | Painted Ear | B C | panfish | surface | starry |
| spotted_bass | Spot | B C | bass | — | golden |
| white_bass | Sand Bass | B C | bass | surface | starry |
| yellow_bass | Stripey | B C | bass | — | golden |
| hybrid_striper | The Wiper | B C | bass | — | starry |
| striped_bass | Rockfish | B | bass | — | glow |
| bowfin | Grinnel | B C | hearty | — | ink |
| spotted_gar | Spotted Stick | B C | hearty | surface | starry |
| shortnose_gar | Stubby Snout | B C | hearty | — | rose |
| alligator_gar | Gator | B C | hearty | — | glow |
| black_bullhead | Inky | B C | catfish | — | ink |
| brown_bullhead | Horned Pout | B | catfish | shy | golden |
| blue_sucker | Blue Racer | B | hearty | shy | glow |
| bigmouth_buffalo | Gourdhead | B C | hearty | — | albino |
| black_buffalo | Shadow Drifter | B | hearty | — | ink |
| golden_shiner | Gold Flash | B C | none | surface | golden |
| gizzard_shad | Hickory | B C | none | — | starry |
| threadfin_shad | Thread | B C | none | surface | starry |
| chain_pickerel | Jack | B | hearty | shy | golden |

**New Briar zone `reeds`** (the Reed Passage) zone matches: golden_shiner 1.0,
warmouth 0.8, chain_pickerel 0.8, bluegill 0.6, bowfin 0.6, others 0.07.

### 1.3 Cedar Creek additions (6, Cedar only)

| id | Name | Folk name | T | Time | Baits | Depth m | Zones | lb | $/lb | Food | Tags | Shiny |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| inland_silverside | Inland silverside | Glass Sliver | C | day | worm | 0.3–3 | open, flats | 0.005–0.03 | 1.20 | none | surface | starry |
| bluntnose_minnow | Bluntnose minnow | Button-Nose | C | day | worm/dough | 0.3–3 | inlet, flats | 0.005–0.02 | 1.00 | none | — | golden |
| river_carpsucker | River carpsucker | Silver Vacuum | U | day | worm/dough | 1–8 | inlet, deep | 1–8 | 1.10 | hearty | — | albino |
| orangespotted_sunfish | Orangespotted sunfish | Ember-Dot | U | day | worm | 0.3–3 | lilies, cypress | 0.05–0.3 | 2.10 | panfish | surface | rose |
| bigscale_logperch | Bigscale logperch | Log-Roller | U | day | worm/craw | 0.5–5 | rocks | 0.02–0.1 | 2.30 | none | shy | starry |
| bullhead_minnow | Bullhead minnow | Little Boss | C | dusk | worm | 0.3–3 | inlet | 0.005–0.02 | 1.00 | none | — | ink |

### 1.4 Flathead Alpine Lake (34, all real species, fictionalized habits)

Lake price note: Flathead fish run about 1.3× warm-water prices.

| id | Name | Folk name | T | Time | Baits | Depth m | Zones | lb | $/lb | Food | Tags | Shiny |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_trout | Lake trout | Deep Mackinaw | C | dawn | minnow/roe | 8–40 | deep, open | 2–30 | 4.20 | trout | cold | starry |
| bull_trout | Bull trout | Old Bull | R | dawn | minnow/roe | 6–30 | inlet, deep | 2–18 | — | trout | cold, protected | glow |
| westslope_cutthroat | Westslope cutthroat trout | Red-Throat | C | day | worm/roe | 1–10 | inlet, rocks, flats | 0.5–4 | 4.60 | trout | cold | rose |
| rainbow_trout | Rainbow trout | Sky-Side | C | day | worm/dough | 1–12 | inlet, lilies, open | 0.5–8 | 4.40 | trout | surface | golden |
| brook_trout | Brook trout | Speckle | U | dawn | worm/roe | 0.5–6 | inlet, flats | 0.3–3 | 5.20 | trout | shy | rose |
| brown_trout | Brown trout | Butter-Belly | U | dusk | minnow/craw | 2–15 | rocks, cypress | 1–14 | 4.80 | trout | shy | golden |
| kokanee | Kokanee salmon | Silver Bullet | C | dawn | roe/dough | 6–25 | open, deep | 0.5–3 | 4.10 | trout | cold | rose |
| lake_whitefish | Lake whitefish | Snow-Belly | C | day | worm/roe | 8–30 | deep, flats | 1–8 | 3.20 | fillet | cold | glow |
| mountain_whitefish | Mountain whitefish | Pebble-Nose | C | day | worm/craw | 1–8 | inlet, rocks | 0.5–3 | 2.90 | fillet | — | starry |
| pygmy_whitefish | Pygmy whitefish | Thimble | U | night | worm | 15–40 | deep | 0.05–0.3 | 2.20 | none | cold | glow |
| northern_pike | Northern pike | Water Wolf | U | day | minnow/shad | 1–6 | lilies, cypress | 2–25 | 3.60 | hearty | — | golden |
| yellow_perch | Yellow perch | Tiger-Stripe | C | day | worm/minnow | 1–8 | lilies, flats, landing | 0.2–1.8 | 3.40 | fillet | — | golden |
| burbot | Burbot | Eelpout | U | night | minnow/roe | 10–40 | deep, rocks | 1–12 | 3.80 | hearty | cold | ink |
| largescale_sucker | Largescale sucker | Rubber-Lip | C | day | worm/dough | 1–10 | inlet, flats | 1–6 | 1.20 | hearty | — | albino |
| longnose_sucker | Longnose sucker | Snoot | U | day | worm | 2–15 | rocks, deep | 0.5–4 | 1.30 | hearty | cold | rose |
| peamouth | Peamouth | Pea-Pod | C | dusk | worm/dough | 1–8 | lilies, inlet | 0.2–1.2 | 1.60 | panfish | surface | golden |
| northern_pikeminnow | Northern pikeminnow | Big-Mouth Minnow | U | dusk | minnow | 1–10 | rocks, open | 1–8 | 1.80 | hearty | — | starry |
| redside_shiner | Redside shiner | Sunset Flicker | C | day | worm | 0.3–4 | flats, lilies | 0.02–0.2 | 1.40 | none | surface | rose |
| slimy_sculpin | Slimy sculpin | Puddle-Puss | U | night | worm | 2–20 | rocks | 0.02–0.1 | 1.50 | none | cold, shy | ink |
| mottled_sculpin | Mottled sculpin | Patchwork | U | night | worm/craw | 0.5–6 | inlet, rocks | 0.02–0.12 | 1.50 | none | shy | albino |
| lake_chub | Lake chub | Button | C | day | worm/dough | 0.5–6 | flats, inlet | 0.05–0.4 | 1.30 | none | — | golden |
| pumpkinseed | Pumpkinseed | Penny-Cheek | C | day | worm | 0.3–4 | lilies, landing | 0.1–0.8 | 2.40 | panfish | surface | rose |
| cisco | Cisco | Lake Herring | U | dawn | worm/roe | 6–30 | open, deep | 0.3–2 | 2.60 | fillet | cold | glow |
| arctic_grayling | Arctic grayling | Sail-Fin | R | day | worm/roe | 0.5–4 | inlet | 0.3–2.5 | 6.50 | trout | surface, shy | starry |
| golden_trout | Golden trout | Sunbeam | R | day | worm/roe | 0.5–4 | inlet, flats | 0.2–2.5 | 7.20 | trout | shy | starry |
| tiger_trout | Tiger trout | Marble-Back | R | dusk | minnow | 2–10 | rocks, cypress | 1–8 | 6.00 | trout | — | golden |
| splake | Splake | Twice-Char | U | dawn | minnow/roe | 4–20 | deep, rocks | 1–8 | 4.90 | trout | cold | glow |
| longnose_dace | Longnose dace | Riffle-Nose | U | day | worm | 0.2–2 | inlet | 0.01–0.06 | 1.40 | none | shy | rose |
| mountain_sucker | Mountain sucker | Cobble-Kiss | U | day | worm/dough | 0.5–5 | inlet, rocks | 0.1–0.8 | 1.30 | hearty | — | albino |
| white_sturgeon | White sturgeon | The Old Plates | V | night | shad/roe | 15–40 | deep | 20–150 | — | none | cold, protected | albino |
| walleye | Walleye | Glass-Eye | U | dusk | minnow/worm | 3–15 | rocks, open | 1–10 | 4.50 | fillet | — | golden |
| sauger | Sauger | Sand-Eye | U | night | minnow | 3–15 | inlet, deep | 0.5–4 | 4.20 | fillet | cold | glow |
| shorthead_redhorse | Shorthead redhorse | Rusty Tail | U | day | worm/craw | 1–8 | inlet, rocks | 1–5 | 1.40 | hearty | — | rose |
| fathead_minnow | Fathead minnow | Pudge | C | day | worm/dough | 0.2–3 | landing, flats | 0.005–0.03 | 1.00 | none | — | golden |

### 1.5 Crater Caldera (34: 14 real, 20 caldera-fictional)

Lake price note: about 1.5×. Crater has no `inlet` zone.

| id | Name | Folk name | T | Time | Baits | Depth m | Zones | lb | $/lb | Food | Tags | Shiny |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| redband_trout | Redband trout | Ember-Stripe | C | day | worm/grub | 1–12 | springs, rocks, open | 0.5–6 | 5.00 | trout | — | rose |
| coastal_cutthroat | Coastal cutthroat trout | Rain-Throat | U | dawn | worm/roe | 1–10 | cypress, lilies | 0.5–4 | 5.40 | trout | shy | golden |
| lahontan_cutthroat | Lahontan cutthroat trout | Desert King | R | dawn | minnow/roe | 2–20 | deep, open | 2–20 | — | trout | cold, protected | starry |
| chinook | Chinook salmon | King's Supper | R | dawn | roe/shad | 10–40 | deep, open | 5–40 | 6.20 | trout | cold | golden |
| coho | Coho salmon | Silver-Side | U | dawn | roe/minnow | 6–30 | open | 3–15 | 5.80 | trout | cold | rose |
| tui_chub | Tui chub | Button-Belly | C | day | worm/dough | 1–10 | flats, lilies | 0.1–1 | 1.80 | none | — | golden |
| speckled_dace | Speckled dace | Freckle | C | day | worm | 0.3–3 | springs, flats | 0.01–0.05 | 1.60 | none | shy | starry |
| oregon_chub | Oregon chub | Moss Pip | U | day | worm/dough | 0.3–3 | lilies | 0.01–0.04 | 2.20 | none | shy | glow |
| klamath_smallscale_sucker | Klamath smallscale sucker | Soft-Mouth | U | day | worm/dough | 2–15 | flats, deep | 1–5 | 1.70 | hearty | — | albino |
| blue_chub | Blue chub | Bluebell | C | day | worm/grub | 1–8 | lilies, cypress | 0.2–1.5 | 1.90 | none | surface | glow |
| prickly_sculpin | Prickly sculpin | Pincushion | U | night | worm/grub | 2–25 | rocks | 0.02–0.15 | 1.80 | none | shy | ink |
| umpqua_pikeminnow | Umpqua pikeminnow | River Wolf | U | dusk | minnow | 2–12 | cypress, rocks | 1–6 | 2.20 | hearty | — | starry |
| chiselmouth | Chiselmouth | Scraper | C | day | worm/dough | 0.5–6 | rocks, flats | 0.2–1.5 | 1.60 | hearty | — | golden |
| alvord_chub | Alvord chub | Dust Pip | R | day | grub | 0.5–4 | springs | 0.02–0.1 | 4.00 | none | shy | glow |
| cobalt_cisco | Cobalt cisco | Blue Ghost | C | dawn | roe/dough | 15–60 | deep, open | 0.3–2 | 3.20 | fillet | cold | glow |
| obsidian_darter | Obsidian darter | Glass Bead | U | day | grub | 1–10 | rocks | 0.01–0.05 | 3.50 | none | shy | starry |
| ember_char | Ember char | Coal-Belly | R | dusk | grub/roe | 4–30 | springs, deep | 1–9 | 7.40 | trout | — | glow |
| ash_minnow | Ash minnow | Smudge | C | day | worm/grub | 0.3–4 | flats | 0.01–0.04 | 1.40 | none | — | albino |
| cinder_sculpin | Cinder sculpin | Hot-Rock | U | night | grub | 2–20 | springs, rocks | 0.05–0.25 | 2.80 | none | shy | ink |
| pumice_skipper | Pumice skipper | Bobber-Fish | C | day | dough/worm | 0–2 | flats, lilies | 0.1–0.6 | 2.40 | panfish | surface | golden |
| fumarole_perch | Fumarole perch | Steam-Stripe | C | day | worm/grub | 1–8 | springs | 0.2–1.6 | 3.80 | panfish | — | rose |
| sulfur_shiner | Sulfur shiner | Yellow Spark | C | day | worm | 0.5–5 | springs, lilies | 0.02–0.1 | 1.70 | none | surface | golden |
| basalt_bass | Basalt bass | Black Brick | U | dawn | craw/minnow | 2–12 | rocks, cypress | 1–7 | 5.20 | bass | — | starry |
| glasswing_trout | Glasswing trout | Window-Fin | R | day | roe/grub | 2–20 | open | 1–6 | 7.80 | trout | shy | glow |
| mistfin_dace | Mistfin dace | Fog-Flicker | U | dawn | worm | 0.5–4 | lilies, flats | 0.02–0.08 | 2.60 | none | — | starry |
| lava_belly_sunfish | Lava-belly sunfish | Hot Penny | C | day | worm/grub | 0.5–5 | springs, lilies | 0.2–1.4 | 2.90 | panfish | surface | rose |
| geyser_goby | Geyser goby | Hiccup | U | night | grub | 0.5–6 | springs | 0.02–0.12 | 2.70 | none | shy | glow |
| moonpool_whitefish | Moonpool whitefish | Night-Lamp | U | night | roe/worm | 10–50 | deep | 1–6 | 4.60 | fillet | cold | glow |
| snagtooth_pike | Snagtooth pike | Old Crook-Jaw | U | dusk | minnow/shad | 1–8 | cypress | 3–20 | 4.40 | hearty | — | golden |
| fog_mudminnow | Fog mudminnow | Hide-Away | U | dawn | worm | 0.3–3 | cypress, lilies | 0.01–0.04 | 2.10 | none | shy | ink |
| indigo_eelpout | Indigo eelpout | Velvet Rope | R | night | shad/grub | 20–60 | deep | 2–14 | 5.60 | hearty | cold | starry |
| steam_carp | Steam carp | Kettle-Lips | C | day | dough/worm | 1–6 | springs, flats | 2–16 | 1.40 | hearty | — | golden |
| rimrock_bullhead | Rimrock bullhead | Pebble-Whisker | C | night | liver/grub | 1–10 | rocks, cypress | 0.3–2.5 | 2.60 | catfish | — | albino |
| vent_catfish | Vent catfish | Warm-Whiskers | U | night | liver/shad | 8–40 | springs, deep | 2–25 | 4.20 | catfish | — | glow |

Weather affinities (×1.4 in that weather, else ×1.0): mistfin_dace and
fog_mudminnow in **fog**. glasswing_trout in **clear**.

### 1.6 Starlight Nebula Lagoon (34, fictional)

Lake price note: about 1.8×. The Nebula keeps the normal 24-hour clock, but its sky
is always starlit. The four time bands display as **Rising** (dawn), **Bright**
(day), **Fading** (dusk) and **Deep** (night).

| id | Name | Folk name | T | Time | Baits | Depth m | Zones | lb | $/lb | Food | Tags | Shiny |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| comet_minnow | Comet minnow | Tail-Light | C | day | stardust/worm | 0.5–4 | inlet, flats | 0.02–0.1 | 2.40 | none | surface | starry |
| meteor_bass | Meteor bass | Rock-Drop | C | dawn | stardust/minnow | 2–12 | rocks | 1–8 | 6.80 | bass | — | golden |
| quasar_koi | Quasar koi | Lantern Koi | U | day | dough/stardust | 0.5–4 | lilies | 2–18 | 7.50 | cosmic | surface | golden |
| pulsar_perch | Pulsar perch | Blinker | C | night | stardust/worm | 1–8 | lilies, open | 0.2–1.8 | 4.80 | cosmic | — | glow |
| lunar_loach | Lunar loach | Moon-Noodle | U | night | stardust | 0.3–3 | flats, reeds | 0.05–0.3 | 4.20 | none | shy | albino |
| solar_sunfish | Solar sunfish | Little Sun | C | day | stardust/worm | 0.3–4 | lilies, landing | 0.2–1.5 | 4.40 | cosmic | surface | golden |
| starling_shiner | Starling shiner | Twinkle-Fry | C | dusk | stardust | 0.3–4 | reeds, flats | 0.02–0.1 | 2.20 | none | surface | starry |
| galaxy_gar | Galaxy gar | Swirl-Snout | U | dusk | shad/stardust | 1–10 | cypress, current | 3–25 | 4.60 | hearty | current | starry |
| aurora_trout | Aurora trout | Ribbon-Light | U | dawn | roe/stardust | 2–15 | inlet, current | 1–7 | 8.20 | trout | current | rose |
| cosmic_carp | Cosmic carp | Big Bubble | C | day | dough/stardust | 1–8 | flats, lilies | 3–24 | 2.60 | hearty | — | golden |
| void_eel | Void eel | Long Shadow | R | night | liver/stardust | 20–60 | deep | 2–15 | 7.60 | hearty | — | ink |
| orbit_bluegill | Orbit bluegill | Ring-Gill | C | day | worm/stardust | 0.3–4 | lilies, landing | 0.1–1 | 3.60 | panfish | — | rose |
| gravity_drum | Gravity drum | Thumper | U | day | craw/stardust | 4–20 | deep, open | 2–16 | 3.40 | hearty | — | glow |
| photon_tetra | Photon tetra | Spark | C | night | stardust | 0.5–5 | reeds, lilies | 0.01–0.03 | 2.80 | none | — | glow |
| nova_pike | Nova pike | Flare-Jaw | R | dusk | minnow/stardust | 1–8 | cypress | 4–24 | 7.20 | hearty | — | golden |
| dwarf_star_darter | Dwarf-star darter | Speck | U | day | stardust | 0.5–6 | rocks | 0.01–0.04 | 4.00 | none | shy | starry |
| saturnfin_puffer | Saturnfin puffer | Ring-Ball | U | day | dough/stardust | 1–8 | open, current | 0.3–2 | 5.00 | none | surface, current | rose |
| celestial_catfish | Celestial catfish | Star-Whiskers | C | night | liver/stardust | 3–20 | deep, cypress | 2–30 | 5.20 | catfish | — | starry |
| moonbeam_crappie | Moonbeam crappie | Paper-Moon | C | dawn | minnow/stardust | 1–8 | cypress, lilies | 0.3–2.4 | 5.40 | panfish | — | glow |
| twinkle_shad | Twinkle shad | Glitter-Fry | C | day | stardust | 1–10 | open, current | 0.1–1.2 | 1.80 | none | current | starry |
| eclipse_bowfin | Eclipse bowfin | Half-Moon | U | night | shad/stardust | 0.5–6 | reeds, cypress | 1–10 | 3.80 | hearty | — | ink |
| stardust_bullhead | Stardust bullhead | Sprinkle-Cat | C | night | liver/worm | 0.5–6 | flats, inlet | 0.3–3 | 3.40 | catfish | — | starry |
| asteroid_sucker | Asteroid sucker | Pock-Lip | U | day | dough/stardust | 3–20 | rocks, deep | 1–8 | 2.40 | hearty | — | albino |
| halo_whitefish | Halo whitefish | Ring-Light | U | dawn | roe/stardust | 8–30 | open, deep | 1–6 | 5.80 | fillet | — | glow |
| constellation_char | Constellation char | Dot-to-Dot | R | dusk | roe/stardust | 4–25 | current, deep | 1–10 | 9.40 | trout | current | starry |
| milky_way_buffalo | Milky-way buffalo | Cream-Back | U | day | dough/stardust | 3–20 | open, flats | 4–30 | 2.20 | hearty | — | albino |
| supernova_salmon | Supernova salmon | Burst | R | dawn | roe/stardust | 6–30 | current, open | 5–28 | 9.80 | trout | current | golden |
| event_horizon_goby | Event-horizon goby | Edge-Sitter | R | night | stardust | 30–60 | deep | 0.05–0.3 | 8.00 | none | shy | ink |
| zodiac_zander | Zodiac zander | Twelve-Stripe | U | dusk | minnow/stardust | 3–15 | rocks, open | 1–12 | 6.40 | fillet | — | golden |
| plasma_pickerel | Plasma pickerel | Zap-Jaw | U | dawn | minnow/stardust | 0.5–5 | reeds, lilies | 0.5–5 | 5.60 | hearty | — | glow |
| ion_icefish | Ion icefish | Clear-Cat | R | night | stardust | 10–40 | deep, current | 0.1–0.8 | 8.60 | none | shy, current | glow |
| prism_ray | Prism ray | Rainbow Kite | R | day | craw/stardust | 2–12 | flats | 2–20 | 8.20 | cosmic | — | rose |
| comet_tail_betta | Comet-tail betta | Silk-Tail | U | day | stardust | 0–2 | lilies, reeds | 0.02–0.08 | 5.20 | none | surface | rose |
| purrsec_lanternfish | Purrsec lanternfish | Purr-Light | U | night | stardust | 10–40 | open, deep | 0.02–0.1 | 6.00 | none | — | glow |

Weather affinity: every Nebula species ×1.25 during **aurora**.

**Count check:** 36 + 6 + 34 + 34 + 34 = **144**. Per-lake catchable: Briar 36,
Cedar 36, Flathead 34, Crater 34, Nebula 34.

---

## 2. Baits (9) and recipe baits

| id | Name | $/dozen | Sold at | Note |
| --- | --- | --- | --- | --- |
| worm | Nightcrawlers | 6 | all | existing |
| liver | Chicken liver | 8 | all | existing |
| shad | Cut shad | 10 | all | existing |
| minnow | Live minnows | 14 | all | existing |
| craw | Crawfish | 16 | all | existing |
| dough | Dough balls | 5 | all | new; cheap universal secondary |
| roe | Trout roe | 15 | Flathead, Crater | new |
| grub | Ember grubs | 15 | Crater | new |
| stardust | Star-dust | 18 | Nebula | new |

**Recipe baits** (cook 2 baits + 1 pantry item → 12; recipe cards are given by the
legendary's clue teller):

| id | Name | Inputs | Key for |
| --- | --- | --- | --- |
| lantern_liver | Lantern Liver | liver + dough + Briar herbs | Old Lantern |
| queens_breakfast | Queen's Breakfast | minnow + craw + Briar herbs | The Lily Queen |
| pecan_smoked_shad | Pecan-Smoked Shad | shad + liver + pecan smoke chips | Channel Leviathan |
| phantom_roe | Phantom Roe | roe + minnow + huckleberries | Glacial Phantom |
| huckleberry_mash | Huckleberry Minnow Mash | minnow + dough + huckleberries | Old Silverhead |
| mineral_shad | Mineral Shad | shad + grub + mineral salt | Obsidian Gar |
| ember_dumpling | Ember Grub Dumpling | grub + dough + mineral salt | Caldera Fire-Lizard |
| moonmilk_stardust | Moon-Milk Stardust | stardust + roe + moon-milk | Nebula Weaver |

---

The nine ordinary baits and eight recipe definitions are loaded from
`baits.json`. A recipe consumes one piece of each parent and one ingredient;
its dozen must fit after those inputs are removed. Recipe baits are cooked,
never sold. The original five bait-match maps are unchanged. For the current
36-species collection, dough is a universal 0.25 secondary match, roe uses the
minnow matches, grubs use the worm matches, and stardust uses the existing
fallback. Later species tables may add their own matches. Every recipe uses
`max(parent_a_match, parent_b_match)` for every species, including fallback.

Briar and Cedar are the currently available lakes. Recipes needing roe, ember
grubs or stardust depend on stock at the later lakes; later specialty pantry
items likewise arrive with their hosts. Their recipes are defined here so the
matching lake/content tickets can enable them without changing cooking rules.

## 3. Legendaries (12)

All windows are game clock, at least 120 minutes long. "Line" means a qualifying
line soaking through the window. Its first haul inside the window hooks the
legendary (`02 §7.2`).

| id | Name | Lake · zone | Window | Weather | Bait | Other gate | lb | Kind | Clue teller |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| old_lantern | Old Lantern | briar · `area: landing_edge`: a line whose midpoint is 50–150 m from the Briar Landing slip (just outside the existing no-line zone, `sim.py` 46 m slip radius / 50 m landing zone) | 20:00–24:00 | any | lantern_liver | Spotlight owned and on | 38 | caught | Grandmother Whiskers |
| lily_queen | The Lily Queen | briar · lilies or reeds | 05:00–08:00 | mist or rain | queens_breakfast | Ch. 1 complete | 14 | caught | Willow |
| spillway_monster | The Spillway Monster | cedar · `area: marked_pool` (inside cedar:rocks) | 20:00–04:00 | any | shad | Heavy line only. **No other gate; day-one** | 95 | caught | Doc Barnaby |
| channel_leviathan | The Channel Leviathan | cedar · inlet | 22:00–02:00 | rain within the last 6 game h | pecan_smoked_shad | Ch. 2 complete | 120 | caught | Hank Mudpaw |
| whiskered_guardian | The Whiskered Guardian | cedar · deep | 18:00–20:00 | any | — | Existing: any 8 of the 10 V3 Ripples | — | witnessed | Quill |
| glacial_phantom | The Glacial Phantom | flathead · inlet | 05:00–09:00 | snow mist | phantom_roe | Line in the cold band | 22 | caught (protected) | Freya |
| old_silverhead | Old Silverhead | flathead · deep | 03:00–07:00 | clear | huckleberry_mash | Line in the cold band | 60 | caught | Torvald |
| huckleberrys_whopper | Huckleberry's Whopper | flathead · rocks | 22:00–02:00 | snow mist | roe | Heard Huckleberry's Whopper story on 3 different days | 18 | caught | Captain Huckleberry |
| obsidian_gar | The Obsidian Gar | crater · rocks (cinder isle) | 16:00–20:00 | clear | mineral_shad | Ch. 4 complete | 48 | caught | Ignis |
| caldera_fire_lizard | The Caldera Fire-Lizard | crater · springs | 00:00–04:00 | fog | ember_dumpling | Heard Mist's poem | 30 | caught | Nyx |
| nebula_weaver | The Nebula Weaver | nebula · current | 20:00–24:00 | aurora | moonmilk_stardust | Zero-G Winch owned | 26 | caught | Nebula-Paws |
| star_whale | The Celestial Star-Whale | nebula · open (the reflection) | Ch. 5; afterward any clear night 20:00–04:00 while settled | clear | — | Ch. 5 | — | witnessed | Professor Astra-9 |

Weather scheduling: once a legendary is eligible, the planner must produce a window
where its required weather overlaps its clock window within **3 game days**
(`02 §3.6`, tested by V1-16). Areas such as `landing_edge` and `marked_pool` are
named regions defined in `lakes.json` (`06 §5`). The validator checks that each
one contains water where a line can legally be set.

---

## 4. Pantry

See `02 §4.2` (herbs, pecan smoke chips, huckleberries, mineral salt, moon-milk,
Kibble Tin).

## 5. Dishes (10)

One buff active at a time (`02 §4.3`). "Hauls" means line checks that bring up at
least one hook.

| id | Dish | Teacher | Fish + pantry | Buff |
| --- | --- | --- | --- | --- |
| herbal_stew | Herbal Catfish Stew | Grandmother | catfish + herbs | For 6 game h, Bot's scout report also names the 2 likeliest species there |
| pan_fritters | Sunny Pan Fritters | Grandmother | panfish + herbs | Next 3 hauls rise 25% quicker |
| pecan_chowder | Doc's Pecan Chowder | Doc | catfish + pecan | Fuel use −25% for 6 game h |
| smoky_tacos | Smoky Bass Tacos | Doc | bass + pecan | Unlocks one extra weather invitation today |
| smoked_trout | Glacial Smoked Trout | Huckleberry | trout + huckleberries | 6 game h: no gust push in snow mist; elsewhere Bot's scout range +25% |
| huckle_pie | Huckleberry Fish Pie | Huckleberry | fillet + huckleberries | Next catnap grants a dream-clue even if one is unread |
| mineral_broth | Cobalt Mineral Broth | Sora | fillet + salt | 6 game h: fog thins within 150 m of the boat |
| ember_hotpot | Ember Hotpot | Sora | hearty + salt | Next 3 hauls: each empty hook keeps its bait |
| moon_pudding | Moon-Milk Pudding | Astra-9 | cosmic + moon-milk | Next 3 hauls count double toward the tracked shiny guarantee |
| starlight_soup | Starlight Soup | Astra-9 | any food fish + moon-milk | 6 game h: your buoys glow on the water and chart; in Old Salt, the meal lasts 48 game h |

Any dish (and the Kibble Tin) resets Old Salt hunger.

---

## 6. Boats (24)

*Speed* is top speed in m/s at full throttle with the base motor (existing jon:
3.15–7.15 with upgrades). *Well* is the base livewell in lb. Existing livewell
upgrades (+40/+100 lb) apply to tiers 2–7. *Lines* is the deployed-line capacity.
*Power*: P paddle/pole, O oars (+ optional electric per existing rowboat rules),
T tiller outboard (existing motor upgrades apply), C console outboard,
I inboard, S sail + auxiliary (existing sail rules), ★ starlight (no fuel).

| id | Name | Tier · family | ft | Price | Power | Speed | Well | Lines | Traits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| log_raft | Cedar Log Raft | 1 Pioneer | 10 | $300 | P | 1.2 | 30 | 3 | shallow, silent, hammock |
| birch_skiff | Birch Bark Skiff | 1 Pioneer | 12 | $420 | P | 1.6 | 40 | 3 | shallow, silent |
| reed_dugout | Reed Dugout | 1 Pioneer | 11 | $360 | P | 1.4 | 35 | 3 | shallow, silent; may set lines in `reeds` without the Reed Anchor |
| dory | Classic Wooden Dory | 2 Rowed | 14 | $480 | O | 1.7 | 60 | 4 | wind_steady |
| rowboat | Reinforced Rowboat *(existing "10 ft Plastic Rowboat")* | 2 Rowed | 10 | $325 | O | existing | existing | 5 | — |
| flat_skiff | Flat-Bottom Skiff | 2 Rowed | 14 | $560 | O | 1.6 | 80 | 5 | shallow |
| jon | Aluminum Jon Boat *(existing; starting boat)* | 3 Jon | 12 | start | T | existing | existing | 5 | — |
| river_runner | River Runner Skiff | 3 Jon | 14 | $900 | T | +0.3 vs jon | 80 | 5 | shallow |
| duck_jon | Duck Hunter Jon | 3 Jon | 14 | $1,100 | T | jon | 90 | 6 | silent |
| marsh_runner | Marsh Runner | 4 Utility | 16 | $1,200 | C | 6.5 | 120 | 6 | shallow, wind_steady |
| deepv_skiff | Deep-V Bass Skiff | 4 Utility | 17 | $1,600 | C | 7.5 | 140 | 6 | wind_steady, trophy_rail |
| coastal_craft | Coastal Craft | 4 Utility | 18 | $1,900 | C | 7.0 | 160 | 7 | wind_steady, ice_hull |
| mahogany_runabout | Classic Mahogany Runabout | 5 Runabout | 17 | $2,600 | I | 9.5 | 60 | 4 | trophy_rail, glow |
| fiberglass_cruiser | Fiberglass Cruiser | 5 Runabout | 20 | $3,000 | I | 8.5 | 120 | 5 | galley, hammock |
| lake_taxi | Lake Taxi | 5 Runabout | 19 | $2,000 | I | 7.5 | 100 | 5 | wind_steady |
| sail | Cat-Rigged Daysailer *(existing "12 ft Daysailer")* | 6 Sail & trawler | 12 | $650 | S | existing | existing | 5 | — |
| small_sloop | Small Sloop | 6 Sail & trawler | 18 | $2,200 | S | sail ×1.2 | 110 | 5 | hammock, trophy_rail |
| tug_skiff | Wooden Tug-Skiff | 6 Sail & trawler | 18 | $2,800 | I | 4.5 | 260 | 7 | galley, ice_hull |
| pontoon | Classic Pontoon *(existing "15 ft Pontoon")* | 7 Pontoon | 15 | $1,450 | T | existing | existing | 6 | hammock |
| party_barge | Triple-Hull Party Barge | 7 Pontoon | 24 | $3,400 | C | 6.0 | 220 | 8 | galley, hammock, trophy_rail |
| houseboat | Lake Houseboat | 7 Pontoon | 32 | $5,200 | I | 4.0 | 300 | 8 | galley, hammock, trophy_rail, wind_steady |
| steam_barge | Astral Steam-Barge | 8 Cosmic | 22 | $5,000 | ★ | 6.5 | 240 | 8 | galley, glow, ice_hull |
| nebula_cruiser | Nebula Cruiser | 8 Cosmic | 20 | $7,000 | ★ | 10.0 | 160 | 7 | glow, silent, trophy_rail |
| celestial_flagship | Celestial Flagship | 8 Cosmic | 30 | $11,000 | ★ | 8.0 | 320 | 8 | galley, hammock, trophy_rail, wind_steady, ice_hull, glow, silent |

Tier 8 is sold only at Cosmic Drift Station and works on every lake. Existing ids
`jon`, `rowboat`, `sail` (the daysailer's id in `fishing/boat.py`) and `pontoon`
keep their physics, collision, saved fuel and battery state. Only display names
change (and the pontoon gains +1 line and `hammock`). Tier unlocks and the pacing
rule are in `02 §9` and `02 §15.3`. Prices follow that rule: the cheapest new boat
of each tier costs 3.3–5.7 days of the income midpoint at the stage it unlocks.

---

## 7. Bot

**Name prefixes (12):** Copper, Quark, Zed, Brass, Sprocket, Clinker, Whirly,
Widget, Cobalt, Anchor, **Rivet**, Echo. *(Gemini's "Pebble" is replaced; it
collides with the Pip & Pebble cat.)* Suffix 011–999, `f"{n:03d}"`.

| Shell id | Name | Look | Chime | Earned | Tool id | Tool price |
| --- | --- | --- | --- | --- | --- | --- |
| tin | Classic Tin Deckhand | Riveted tin, brass ears, copper-ring eye | triangle | start | sonar_grid | $150 (needs Depth Finder) |
| frog | Frog Bot | Green enamel, webbed brass ears, round eyes | wooden click | Ch. 1 | reed_anchor | $120 (free during ch. 1 step 3) |
| duck | Rubber Duck Bot | Bright yellow, orange bill, visible gears | squeak | Ch. 2 | wave_chime | $180 |
| sub | Clockwork Copper Sub | Copper hull, glass dome, little propeller | bubbly tick | Ch. 3 | thermo_scanner | $260 (lent for ch. 3) |
| astral | Astral Starlight Bot | Violet-teal chrome, star freckles, faint glow | glass bell | Ch. 5 | zero_g_winch | $400 |

---

## 8. Zones and Lake Days

Internal zone ids are shared habitat archetypes (existing `landing, inlet, flats,
lilies, cypress, rocks, deep, open`, plus new `reeds, springs, current`). Each lake
supplies display labels (existing pattern: `CEDAR_ZONES`).

| id | briar | cedar | flathead | crater | nebula |
| --- | --- | --- | --- | --- | --- |
| landing | Briar Landing | Caney Creek landing | Glacial Peak Outpost | Caldera Rim Dock | Cosmic Drift Station |
| inlet | Creek inlet | Creek channels | Snowmelt inlet | — | Comet stream |
| flats | North flats | Upper lake flats | Gravel flats | Pumice shelf | Stardust shoals |
| lilies | Lily cove | Clear Creek coves | Pondweed bay | Moss gardens | Zero-G lily drifts |
| cypress | Cypress shore | Flooded shoreline | Larch snags | Drowned pines | Crystal kelp forest |
| rocks | South rocks | Dam riprap (Marked Pool) | Gravel reefs | Obsidian cliffs (cinder isle) | Meteor reefs |
| deep | Deep hole | Southern basin | Glacial trench | Cobalt deep | Void well |
| open | Open water | Cedar open water | Big open water | Caldera open | Nebula open |
| reeds | Reed Passage (new) | — | — | — | Light-reeds |
| springs | — | — | — | Thermal springs | — |
| current | — | — | — | — | Astral current |

**Lake Days** (day 0 = Monday):

| Lake | Day | Name | Effect |
| --- | --- | --- | --- |
| briar | Tue | Mayfly Morning | dawn: panfish ×1.3 |
| briar | Fri | Firefly Night | night: catfish ×1.25 (and more fireflies) |
| cedar | Thu | Shad Run | night: blue and channel ×1.3 |
| cedar | Sat | Breezy Bass | day: bass ×1.25 in open/rocks |
| flathead | Mon | Clear-Sky Trout | dawn: trout ×1.3; weather biased to clear |
| flathead | Wed | Larch Gold | day: perch and pike ×1.25 |
| crater | Tue | Warm Springs | `springs` species ×1.3 |
| crater | Fri | Fog Lift | dawn: weather biased to fog→clear; fog species ×1.4 |
| nebula | Wed | Meteor Shower | night: all species ×1.15, plus a sky show |
| nebula | Sat | Aurora Tide | weather biased to aurora; `current` species ×1.3 |
| all | Sun | Landing Cookout | 17:00–20:00 at the landing (`02 §5.6`) |

## 9. Ripples and Keepsakes

- **Ripples** (wisdom notes, existing system): 10 existing V3 ids + 34 new (one per
  new encounter's quest A) = 44. Ids and text are in `04` and `05`.
- **Keepsakes** (quest B rewards): 44 small decorations. Each is a 2D icon on the
  Keepsakes page, and a decal or prop on boats with a `trophy_rail` or on the
  houseboat shelf. Ids `ks_<npc_id>`, names in `04`.


V1-16 copies Briar/Cedar §8 Lake Days and all §3 legendary weather/clock requirements into
validated `content_v2/calendar.json`. Briar/Cedar modifiers are active now;
future legendary weather rows prepare forecasts without unlocking their worlds. Game-day
weekday boundaries are 06:00. Cookout gifts contain one host-specialty pantry
item or Kibble Tin, chosen reproducibly, with at most one claim per lake each
Sunday; no fish is spent when that item's pantry slot is full.
