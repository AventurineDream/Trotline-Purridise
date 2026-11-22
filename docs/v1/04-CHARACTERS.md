# Trotline Purridise — V1.0 Characters

*Supersedes `V1_0_CharactersOverview.md` (Gemini). 52 cats + Bot. Every water-cat
has a **want** (small, specific, achievable with the player's help) and a
**contradiction** (the endearing thing that makes them a person). Changed greeting
and return lines live in `05-SCRIPT.md`.*

**Quest id scheme:** the 12 existing V3 quests keep their full shipped ids
(`fishing/narrative.py` `QUEST_IDS`): `q01_tea_leaves_deep_holes`,
`q02_lonely_star_current`, `q03_unstrung_line`, `q04_great_contour_chart`,
`q05_moonlight_trotlines`, `q06_unrepeatable_sunrise`, `q07_art_of_the_nap`,
`q08_channel_run`, `q09_quiet_channel`, `q10_ballad_lonely_star`,
`q11_deep_water_drift`, `q12_first_voyage`. Short forms like "q03" in this packet
are reading aids only. Data files, prerequisites and migrations must use the full
ids. New: story steps
`story_c<chapter>_s<step>`, host errands `host_<lake>`, and water-cat quests
`wc_<npc_id>_a` / `wc_<npc_id>_b`. Keepsake id: `ks_<npc_id>`. Cash: quest A pays
Briar $45 · Cedar $55 · Flathead $80 · Crater $110 · Nebula $140. Quest B pays
1.5× that. Existing V3 rewards are unchanged.

**Objective shorthand** uses the types and fields in `02 §12.3`. Notation:
`prem+` means `min_tier: prem`. "Then `talk_to`" means a second step. "(after
ch. N)" or "(needs Flathead travel)" means `requires`. "Any Briar zone" means
`lake_id: briar`.

---

## 0. The Skipper — you

- **Ids:** `v2.skipper` in the save; `{Skipper}` in any line is the chosen name
  (default "Skipper").
- **Look:** chosen in the Skipper creator at a new game, and changed any time from
  the pause menu: pattern (the nine coat patterns), coat, markings and bib colours,
  eyes, ears, tail, fur, a hat or spectacles, neckwear and a jacket from the cats'
  shared attire kit. A save from before the creator wears the default dusk-brown
  tabby. Size, build and leg length stay at the rig's 1.0 so the view from the eye,
  the paws on the tiller and the Skipper's place in every cockpit stay true.
- **On the water:** seen in first person as paws in the chosen coat and a head in
  calm-water reflections; from the chase camera, standing at the helm, glancing at
  nearby cats and waving back to one in hailing range.

## 1. Bot — the tin deckhand

- **Ids:** `bot`. Plate: *Deckhand Unit 04*; name `Word-###` (`03 §7`).
- **Look:** the shell changes (`03 §7`); the copper-ring eye, brass ears and the wool
  collar (from ch. 1) are on every shell.
- **Wants:** to be useful, and to understand why the Skipper looks at the water so
  long. By the end he does it too.
- **Contradiction:** precise about numbers and hopeless about feelings. He reports
  "joy detected" in a deadpan voice.
- **Arc:** reports facts → asks "Shall we add that?" → by ch. 5 offers the pencil to
  the Skipper instead of writing himself.
- **Relationships:** Grandmother knits his collar. Pebble (the kitten, scared of
  frogs) loves Frog Bot. Orion-Cat treats him as a fellow engineer. Astra-9 calls
  him "colleague".

## 2. Hosts (permanent, at their landing)

Each host: sells their pantry item, teaches two dishes, gives one host errand and the
chapter's first and last beats, and tells one legendary clue. Sentence shapes are
for writers.

### Grandmother Whiskers — Briar Landing
Elderly calico · knitted shawl, wire spectacles, tea mug. **Shape:** a gentle
observation, then a small invitation ("The lilies are holding the morning very
gently. Shall we see who's awake?"). **Want:** for the old book to have new
pages in a new paw. **Contradiction:** endlessly patient with everyone, and
impatient with her teapot. **Errand:** q01 *Tea Leaves & Deep Holes* (existing).
**Dishes:** herbal_stew, pan_fritters. **Pantry:** Briar herbs. **Clue:** Old
Lantern.

### Doc Barnaby — Doc's Lonely Star Marina (beside Cedar Landing)
Weathered orange tabby · yellow oilskin, salt-stained cap. **Shape:** a quick
exclamation, a practical tip, a joke at his own expense. **Want:** to see the old
blue-jug marker back where it belongs, and his directions to be right again.
**Contradiction:** tells everyone to "read the wind with your whiskers", then checks
three gauges himself. **Errand:** q02 *The Lonely Star Current* (existing).
**Dishes:** pecan_chowder, smoky_tacos. **Pantry:** pecan smoke chips. **Clue:**
Spillway Monster.

### Captain Huckleberry — Glacial Peak Outpost
Fluffy white Norwegian Forest Cat · wool parka, brass compass, thermal boots.
**Shape:** "Ho-ho!", a story that's too long, and one useful sentence at the end.
**Want:** a fishing note he can rely on again. **Contradiction:** tells enormous
tall tales and admits at once, delighted, when he's wrong. **Errand:**
`host_flathead` *The Long Story* (`talk_to` him on 3 different days; this also
counts toward Huckleberry's Whopper). **Dishes:** smoked_trout, huckle_pie.
**Pantry:** huckleberries. **Clue:** Huckleberry's Whopper.

### Sora the Obsidian — Caldera Rim Dock
Sleek black Bombay · indigo silk vest, obsidian pendant. **Shape:** short and
precise. Asks a question, then waits. **Want:** a complete chart of the caldera,
with no gaps. **Contradiction:** coolly analytical, and secretly names every fog
bank. **Errand:** `host_crater` *Fog Names* (`wait_weather fog` in any crater zone,
then `talk_to sora`; she tells you the fog's name). **Dishes:** mineral_broth,
ember_hotpot. **Pantry:** mineral salt. **Clue:** (none; Ignis and Nyx tell Crater's).

### Professor Astra-9 — Cosmic Drift Station
Sphynx with glowing violet markings · starlight brass goggles, floating chart
tablet. **Shape:** enthusiastic, slightly wrong units, a correction from Bot.
**Want:** to watch the Star-Whale without frightening it, which means learning to
stop surveying. **Contradiction:** a genius cartographer who gets lost on her own
station. **Errand:** `host_nebula` *Units, Please* (`book_stage`: 5 Nebula species
Identified; she finally adopts "feet"). **Dishes:** moon_pudding, starlight_soup.
**Pantry:** moon-milk. **Clue:** Star-Whale.

## 3. Travelers

| id | Name | Look & boat | Schedule | Role |
| --- | --- | --- | --- | --- |
| `pounce` | Postmaster Pounce | Ragamuffin in a blue cap; mail skiff with a red flag | One unlocked lake per day (seeded), 08:00–16:00 | Delivers friends' letters (`02 §11.5`) and carries the radio for the ending |
| `thistle` | Tinker Thistle | Tortoiseshell; tinker barge with jangling pots | Every Saturday at the player's lake, 10:00–18:00 | Sells shell paints and boat trims; buys nothing; tells jokes |

---

## 4. Water-cats (45)

Format per cat: **Name** (id) — breed · boat · slot · anchor zone.
*Want* / *Contradiction*. **A** quest → Ripple. **B** quest → Keepsake.

### 4.1 Little Briar (9 cats, 8 encounters; night slot: Master Cinder)

**Elder Moss** (`elder_moss`) — Maine Coon · wooden raft · day · cypress.
*Wants* to watch the cypress roots without making one ripple. *Contradiction:*
preaches stillness, and his tail chases every dragonfly.
**A** q03 *The Unstrung Line* (existing) → `ripple_01`.
**B** `wc_elder_moss_b` *The Second Stillness*: `catnap` in briar:cypress →
`ks_elder_moss` Floating candle.

**Pip & Pebble** (`pip_pebble`) — tuxedo kitten siblings · rowboat · day · flats.
*Want* the best map on the lake. *Contradiction:* Pip makes everyone wear life
jackets and always forgets her pencil. Pebble is scared of frogs, and adores Frog
Bot. Chapter 1 givers.
**A** q04 *The Great Contour Chart* (existing) → `ripple_02`.
**B** `wc_pip_pebble_b` *Map Party*: `book_stage` 10 Briar species ≥ Identified →
`ks_pip_pebble` Crayon map.

**Master Cinder** (`master_cinder`) — black cat · dark skiff · **night**
(20:00–04:00, existing) · deep. *Wants* to see Old Lantern again; he saw it once as
a kitten. *Contradiction:* the lake's most dramatic night angler, and nervous of
the dark water under the landing.
**A** q05 *Moonlight Trotlines* (existing) → `ripple_03`.
**B** `wc_master_cinder_b` *Lantern Watch*: `catch_species old_lantern` →
`ks_master_cinder` Moon lantern.

**Willow** (`willow`) — Siamese · birch canoe · day · lilies. *Wants* to paint a
sunrise nobody has painted. *Contradiction:* chases unrepeatable moments, and
paints the same heron every day. **Clue teller:** the Lily Queen (gives
`queens_breakfast`).
**A** q06 *The Unrepeatable Sunrise* (existing) → `ripple_04`.
**B** `wc_willow_b` *Paint the Queen*: `wait_weather` mist in briar:lilies →
`ks_willow` Misty watercolor.

**Silas** (`silas`) — grey tabby · flat-bottom skiff · day · inlet. *Wants* a
birdhouse on every snag. *Contradiction:* a master carpenter who naps through his
own hammering.
**A** q07 *The Art of the Nap* (existing) → `ripple_05`.
**B** `wc_silas_b` *Birdhouse Row*: `visit_zones` briar:cypress, briar:rocks,
briar:inlet → `ks_silas` Tiny birdhouse.

**Marigold** (`marigold`) — Turkish Van · inner-tube raft (she swims beside it) ·
day · open. *Wants* someone to agree that swimming cats are perfectly normal.
*Contradiction:* swims everywhere, and hates rain on her ears.
**A** `wc_marigold_a` *Swim Buddy*: `travel_distance` 200 m in briar:open →
`ripple_11`. **B** `wc_marigold_b` *Rainy-Day Ears*: `wait_weather` rain in any
Briar zone → `ks_marigold` Swim cap.

**Old Gus** (`old_gus`) — Manx · punt · day · rocks. Retired ferryman.
*Wants* to hear a loon again. *Contradiction:* insists he has never been lost, and
asks the herons for directions.
**A** `wc_old_gus_a` *Heron Clock*: `scout_report` in briar:rocks → `ripple_12`.
**B** `wc_old_gus_b` *A Loon for Gus* (needs Flathead travel): `visit_zones`
flathead:open, then `talk_to old_gus` → `ks_old_gus` Ferry bell.

**Biscuit** (`biscuit`) — British Shorthair · bread barge · day · flats.
*Wants* a dough-ball recipe the fish actually like. *Contradiction:* bakes all
day, and can't stand a crumb on her deck.
**A** `wc_biscuit_a` *Taste Test* (gives a free dozen dough on accept): `catch_species`
any fish on dough → `ripple_13`. **B** `wc_biscuit_b` *Cookout Bread*:
`attend_event` briar cookout → `ks_biscuit` Bread-loaf buoy.

### 4.2 Cedar Creek (9 cats; night slot alternates Hank Mudpaw / Señora Luz)

**Captain Maeve** (`captain_maeve`) — calico · red runabout · day · open. Retired
riverboat captain. *Wants* to teach someone her buoy course, at their own pace.
*Contradiction:* loves speed, and makes everyone else go slow.
**A** q08 *The Channel Run* (existing; dialogue recopied in `05`) → `ripple_06`.
**B** `wc_captain_maeve_b` *Practice Buoys*: `visit_sequence` of 4 practice buoys
in the sheltered cove (cedar:lilies), any speed → `ks_captain_maeve` Brass
whistle.

**Sparky** (`sparky`) — orange tabby · modified bass boat · day · inlet.
Tinkerer, and builder of the Rubber Duck shell. *Wants* to invent a truly quiet
winch. *Contradiction:* builds quiet machines, and laughs like a foghorn.
**A** q09 *The Quiet Channel* (existing) → `ripple_07`.
**B** `wc_sparky_b` *Squeak Test*: `tool_use wave_chime` in any Cedar zone →
`ks_sparky` Spare gear.

**Quill** (`quill`) — Persian · classic wooden sloop · day · flats. Poet.
*Wants* the last verse of the *Ballad of the Lonely Star*. *Contradiction:* writes
about silence, and never stops talking. **Clue teller:** the Whiskered Guardian.
**A** q10 *Ballad of the Lonely Star* (existing) → `ripple_08`.
**B** `wc_quill_b` *The Last Verse*: witness the Whiskered Guardian (book entry
present) → `ks_quill` Ballad sheet.

**Dr. Alder** (`dr_alder`) — Chartreux · hydro-survey skiff · day · deep.
Biologist. *Wants* a complete species list for Cedar. *Contradiction:* precise to
the decimal, and names every fish after one of her aunts. *(Truth rule: at Cedar
she has no thermometer; she counts and draws.)*
**A** q11 *The Deep-Water Drift* (existing) → `ripple_09`.
**B** `wc_dr_alder_b` *Cedar Census*: `book_stage` 20 Cedar species ≥ Identified →
`ks_dr_alder` Field notebook.

**Patch** (`patch`) — one-eared alley cat · rubber dinghy · day · lilies. Finder
of lost lures. *Wants* the lucky spoon he lost as a kitten. *Contradiction:*
mischief in every whisker, and he returns everything he finds.
**A** q12 *The First Voyage* (existing) → `ripple_10`.
**B** `wc_patch_b` *Treasure Tour*: `visit_zones` cedar:cypress, cedar:rocks,
cedar:inlet, then `talk_to patch` → `ks_patch` Lucky spoon (he gives it to *you*).

**Hank Mudpaw** (`hank_mudpaw`) — American Shorthair · old dented jon · **night**
· inlet. Retired lineworker. *Wants* someone to believe his Leviathan story.
*Contradiction:* gruff as gravel, and tears up at every sunset. **Clue teller:**
Channel Leviathan (gives `pecan_smoked_shad` after A).
**A** `wc_hank_mudpaw_a` *Night Line*: `line_check` prem+ · liver · cedar:inlet ·
60 active min → `ripple_14`. **B** `wc_hank_mudpaw_b` *Believe Me*:
`catch_species channel_leviathan` → `ks_hank_mudpaw` Lineman's lantern.

**Belle Pecan** (`belle_pecan`) — Selkirk Rex · pecan-shell canoe (very small) ·
day · cypress. *Wants* everyone at the cookout to have pie. *Contradiction:*
generous with everything except the recipe.
**A** `wc_belle_pecan_a` *Under the Pecans*: `catch_species` any 3 fish in
cedar:cypress → `ripple_15`. **B** `wc_belle_pecan_b` *Pie for Everyone*:
`attend_event` cedar cookout → `ks_belle_pecan` Pecan-shell charm.

**Señora Luz** (`senora_luz`) — Egyptian Mau · lamp skiff · **night** · rocks.
Keeper of the Marked Pool lights. *Wants* everyone to fish the pool safely.
*Contradiction:* stern at the barrier, and sings lullabies to the Spillway Monster.
**A** `wc_senora_luz_a` *Lamps on the Pool*: `visit_sequence` of 3 lamp buoys
around the Marked Pool after 19:00 → `ripple_16`. **B** `wc_senora_luz_b`
*Lullaby*: `catch_species spillway_monster` → `ks_senora_luz` Lamp glass.

**Kit** (`kit`) — Abyssinian kitten, junior ranger · paddleboat, life jacket
always · day · flats. *Wants* her last ranger badge, earned by teaching someone.
*Contradiction:* teaches water safety, and keeps (giggling) tipping her paddleboat
in the shallows.
**A** `wc_kit_a` *Ranger Check*: `visit_zones` cedar:flats, cedar:lilies,
cedar:landing → `ripple_17`. **B** `wc_kit_b` *Badge Day*: `line_check` std+ ·
worm · cedar:flats · 60 min, then `talk_to kit` → `ks_kit` Ranger badge.

### 4.3 Flathead Alpine (9 cats; night alternates Torvald / Elk-Ears Eli)

**Torvald** (`torvald`) — Russian Blue · heavy cabin cruiser · **night** · deep.
*Wants* to see Old Silverhead before he "really" retires. *Contradiction:* says
he's retired, and is out every single night. **Clue teller:** Old Silverhead
(gives `huckleberry_mash`).
**A** `wc_torvald_a` *The Deep Lantern*: `line_check` in flathead:deep with
`in_cold_band` → `ripple_18`. **B** `wc_torvald_b` *Silverhead*:
`catch_species old_silverhead` → `ks_torvald` Brass depth weight.

**Freya** (`freya`) — Birman · trimaran · day · inlet. Glacier photographer.
*Wants* a photograph of the Glacial Phantom. *Contradiction:* waits hours for
perfect light, and forgets her lens cap. **Clue teller:** Glacial Phantom (gives
`phantom_roe`).
**A** `wc_freya_a` *Snow Light*: `wait_weather` snow mist in flathead:inlet →
`ripple_19`. **B** `wc_freya_b` *The Phantom*: `catch_species glacial_phantom` →
`ks_freya` Freya's photo of you (shows the Skipper's silhouette and Bot).

**Bramble** (`bramble`) — Scottish Fold · wooden kayak · day · flats. Tests
cold-weather camping gear. *Wants* one perfect nap outdoors in the cold.
*Contradiction:* tests winter gear, and is always slightly too cold.
**A** `wc_bramble_a` *Field Test*: `catnap` in flathead:flats → `ripple_20`.
**B** `wc_bramble_b` *Cocoa Science*: `cook_dish` any → `ks_bramble` Wool mitten.

**Ingrid** (`ingrid`) — Siberian · larch-plank pontoon · day · cypress.
Whittler. *Wants* to carve every Flathead fish from life. *Contradiction:*
carves the tiniest scales, and can't stand small talk (she gives big talk).
**A** `wc_ingrid_a` *Models from Life*: `book_stage` 8 Flathead species ≥
Identified → `ripple_21`. **B** `wc_ingrid_b` *The Burbot Figure*: `catch_species
burbot` → `ks_ingrid` Wooden trout.

**Elk-Ears Eli** (`elk_ears_eli`) — lynx-point · canvas canoe · **night** · rocks.
Ranger and owl-counter; teaches why protected fish go back. *Wants* every angler to
understand release. *Contradiction:* strict about rules, and sneaks huckleberries
from the outpost jar.
**A** `wc_elk_ears_eli_a` *Back They Go*: `catch_species bull_trout` (auto-release)
→ `ripple_22`. **B** `wc_elk_ears_eli_b` *Owl Count*: `anchor_idle`
flathead:rocks 120 → `ks_elk_ears_eli` Owl feather.

**Bjorn** (`bjorn`) — Pixie-bob, Huckleberry's nephew · rowboat · day · open.
*Wants* his uncle's stories to be true. *Contradiction:* says he's too old for
them, and knows every word by heart.
**A** `wc_bjorn_a` *Uncle's Stories*: `talk_to captain_huckleberry` on 3 different
days → `ripple_23`. **B** `wc_bjorn_b` *The Whopper*: `catch_species
huckleberrys_whopper` → `ks_bjorn` Tall-tale tin cup.

**Willa Larch** (`willa_larch`) — Somali · larch raft · day · cypress.
Basket-weaver. *Wants* a basket of autumn gold before the snow. *Contradiction:*
weaves slowly, and talks very fast.
**A** `wc_willa_larch_a` *Larch Gold*: `catch_species yellow_perch` ×3 →
`ripple_24`. **B** `wc_willa_larch_b` *Outpost Supper*: `attend_event` flathead
cookout → `ks_willa_larch` Needle basket.

**Dakota** (`dakota`) — Ocicat · canvas canoe · day · open. Drawling cowpoke type.
*Wants* to cross the whole lake on one wind. *Contradiction:* loves wild wind, and
ties everything down twice.
**A** `wc_dakota_a` *Big Open*: `travel_distance` 400 m in flathead:open →
`ripple_25`. **B** `wc_dakota_b` *Trout Trail*: `catch_species` 4 different trout
species → `ks_dakota` Bandana pennant.

**Mitzi** (`mitzi`) — Devon Rex · survey skiff · day · deep. Glacier geologist.
*Wants* to map the trench's cold layer. *Contradiction:* studies cold for a
living, and wears three sweaters.
**A** `wc_mitzi_a` *Cold Layer*: `tool_use thermo_scanner` on Flathead →
`ripple_26`. **B** `wc_mitzi_b` *Two Lakes, One Layer*: `tool_use thermo_scanner`
on Crater → `ks_mitzi` Rock hammer.

### 4.4 Crater Caldera (9 cats; night alternates Nyx / Fumi)

**Nyx** (`nyx`) — Korat *(Gemini typo "Corat" fixed)* · steam launch · **night** ·
springs. Bathhouse keeper. *Wants* guests in her bathhouse again.
*Contradiction:* runs a bathhouse, and hates getting wet. **Clue teller:** Caldera
Fire-Lizard (gives `ember_dumpling`).
**A** `wc_nyx_a` *Warm Water*: `line_check` · grub · crater:springs · 60 min →
`ripple_27`. **B** `wc_nyx_b` *The Old Bather*: `catch_species
caldera_fire_lizard` → `ks_nyx` Bathhouse token.

**Ignis** (`ignis`) — Bengal · reinforced skiff · day · rocks. Free-diver (only
in the shallows, always with a buddy). *Wants* to show off the cinder isle's glassy
shore. *Contradiction:* the loudest cat on the caldera, who whispers when the gar
is near. **Clue teller:** Obsidian Gar (gives `mineral_shad`).
**A** `wc_ignis_a` *Glass Shore*: `scout_report` in crater:rocks → `ripple_28`.
**B** `wc_ignis_b` *Black Glass*: `catch_species obsidian_gar` → `ks_ignis`
Obsidian bead.

**Ashby** (`ashby`) — Havana Brown · cocoa barge · day · flats. *Wants* the perfect
cup on the foggiest morning. *Contradiction:* dislikes fog, and adores
foggy-morning cocoa.
**A** `wc_ashby_a` *Fog Cocoa*: `wait_weather` fog in crater:flats → `ripple_29`.
**B** `wc_ashby_b` *Mineral Cup*: `cook_dish mineral_broth` → `ks_ashby` Cocoa mug.

**Basalt Bea** (`basalt_bea`) — LaPerm · rowboat with a rock-heavy bow · day ·
rocks. *Wants* a stone from every lake. *Contradiction:* collects rocks, and can't
remember where she put any of them.
**A** `wc_basalt_bea_a` *Pumice Float*: `visit_zones` crater:flats, crater:rocks,
crater:cypress → `ripple_30`. **B** `wc_basalt_bea_b` *Stone Tour*: `visit_zones`
briar:rocks, cedar:rocks, flathead:rocks → `ks_basalt_bea` Pocket stone.

**Fumi** (`fumi`) — Japanese Bobtail · lantern sampan · **night** · lilies.
*Wants* to light one lantern for each friend. *Contradiction:* very formal, and
laughs at her own sneezes.
**A** `wc_fumi_a` *Moss Lanterns*: `anchor_idle` crater:lilies 120 → `ripple_31`.
**B** `wc_fumi_b` *Night Friends*: `catch_species` 3 different species at night on
Crater → `ks_fumi` Paper lantern.

**Ember** (`ember`) — Somali kitten, the fire-lookout's kid · paddle skiff · day ·
open. *Wants* to see the whole caldera from the water. *Contradiction:* tiny, and
absolutely certain she is the lookout.
**A** `wc_ember_a` *Lookout Loop*: `travel_distance` 500 m in crater:open →
`ripple_32`. **B** `wc_ember_b` *All Clear*: chapter 4 complete, then `talk_to
ember` → `ks_ember` Lookout binoculars.

**Mist** (`mist`) — Turkish Angora · reed boat · day · cypress. Fog poet.
*Wants* someone to hear her poem to the end. *Contradiction:* speaks in whispers,
and sneezes enormously. Her poem is the Fire-Lizard's gate.
**A** `wc_mist_a` *The Poem*: `wait_weather` fog in crater:cypress, then `talk_to
mist` → `ripple_33`. **B** `wc_mist_b` *Hide-Away*: `catch_species fog_mudminnow`
→ `ks_mist` Poem scroll.

**Juno** (`juno`) — Burmese · telescope barge · day · open. Astronomer.
*Wants* someone to see the star reflection she's sure exists. *Contradiction:* an
astronomer who keeps falling asleep before the stars come out.
**A** `wc_juno_a` *Clear Water*: `wait_weather` clear in crater:open → `ripple_34`.
**B** `wc_juno_b` *I Told You So* (after ch. 5): `talk_to juno` → `ks_juno` Star
chart.

**Tamsin** (`tamsin`) — Snowshoe · canoe · day · deep. Clear-water ranger.
*Wants* the clearest water to stay clear. *Contradiction:* devoted to clean
water, and always has muddy paws.
**A** `wc_tamsin_a` *Clear Keepers*: `catch_species lahontan_cutthroat`
(auto-release) → `ripple_35`. **B** `wc_tamsin_b` *Clear Count*: `book_stage` 15
Crater species ≥ Identified → `ks_tamsin` Clean-water pin.

### 4.5 Starlight Nebula (9 cats; night alternates Orion-Cat / Twinkle)

**Orion-Cat** (`orion_cat`) — Persian with brass star-goggles and a clockwork tail
brace · hover-barge · **night** · open. *Wants* an anti-gravity trotline that won't
drift. *Contradiction:* the most high-tech angler in the sky, who loves old knots.
**A** `wc_orion_cat_a` *Drift Lines*: `line_check` · nebula:current · 60 min →
`ripple_36`. **B** `wc_orion_cat_b` *Hold Fast*: `tool_use zero_g_winch` →
`ks_orion_cat` Star-knot.

**Nebula-Paws** (`nebula_paws`) — bioluminescent Ragdoll · starlight skiff · day ·
current. Musician. *Wants* the Weaver to dance to her star-chimes.
*Contradiction:* a star performer with stage fright. **Clue teller:** Nebula
Weaver (gives `moonmilk_stardust`).
**A** `wc_nebula_paws_a` *Star-Chimes*: `anchor_idle` nebula:current 120 →
`ripple_37`. **B** `wc_nebula_paws_b` *The Dance*: `catch_species nebula_weaver`
→ `ks_nebula_paws` Glass chime.

**Comet** (`comet`) — Bengal kitten · comet skiff · day · inlet. *Wants* to race a
real comet. *Contradiction:* zooms everywhere, and takes the longest naps on the
Lagoon.
**A** `wc_comet_a` *Comet Stream*: `travel_distance` 400 m in nebula:inlet →
`ripple_38`. **B** `wc_comet_b` *Comet Nap*: `catnap` in nebula:inlet →
`ks_comet` Tail ribbon.

**Lyra** (`lyra`) — Cymric · harp boat · day · lilies. *Wants* a new harp string
spun from light-reed. *Contradiction:* plays the gentlest music, and argues
cheerfully about everything.
**A** `wc_lyra_a` *Light-Reed String*: `catch_species` any fish in nebula:reeds →
`ripple_39`. **B** `wc_lyra_b` *Station Song*: `attend_event` nebula cookout →
`ks_lyra` Light-reed string.

**Vega** (`vega`) — Toyger · solar skiff · day · open. Navigator. *Wants* to chart
where the Lagoon ends. *Contradiction:* a master navigator who gets dizzy looking
down.
**A** `wc_vega_a` *Edge of the Map*: `visit_zones` nebula:open, nebula:deep,
nebula:current, nebula:reeds → `ripple_40`. **B** `wc_vega_b` *Star Census*:
`book_stage` 10 Nebula species ≥ Identified → `ks_vega` Friend-compass.

**Selene** (`selene`) — Nebelung · moon-garden raft · day · flats. *Wants* a
garden that grows on water. *Contradiction:* a gardener who has never kept a
cactus alive.
**A** `wc_selene_a` *Moon Garden*: `cook_dish moon_pudding` → `ripple_41`.
**B** `wc_selene_b` *Sun and Moon*: `catch_species` solar_sunfish and lunar_loach →
`ks_selene` Moon-flower.

**Andi** (`andi`) — Oriental Longhair kitten (Andromeda) · bubble skiff · day ·
lilies. Born on the station. *Wants* to hear about "the lakes below".
*Contradiction:* grew up among stars, and thinks frogs are the most amazing thing
in the universe.
**A** `wc_andi_a` *Tell Me About Frogs*: `catch_species` any fish in briar:lilies,
then `talk_to andi` → `ripple_42`. **B** `wc_andi_b` *Frog Day*: `tool_use
reed_anchor` in nebula:reeds while wearing the Frog shell → `ks_andi` Frog drawing.

**Twinkle** (`twinkle`) — Munchkin · tiny shepherd skiff · **night** · deep.
Lanternfish shepherd. *Wants* to count all her lanternfish. *Contradiction:*
shepherd of a thousand fish who can only count to twelve.
**A** `wc_twinkle_a` *Count the Lights*: `catch_species purrsec_lanternfish` ×3 →
`ripple_43`. **B** `wc_twinkle_b` *The Edge-Sitter*: `catch_species
event_horizon_goby` → `ks_twinkle` Shepherd's crook.

**Rigel** (`rigel`) — Savannah · solar-sail racer · day · current. *Wants* to
learn to sail slowly. *Contradiction:* the fastest sailor in the sky, who wants
nothing more than to dawdle.
**A** `wc_rigel_a` *Slow Sail*: `travel_distance` 300 m in nebula:current →
`ripple_44`. **B** `wc_rigel_b` *Burst*: `catch_species supernova_salmon` →
`ks_rigel` Sail patch.

---

## 5. Counts and schedule summary

| Lake | Cats | Encounters | Day pool | Night pool | Ripples | Keepsakes |
| --- | --- | --- | --- | --- | --- | --- |
| briar | 9 | 8 | moss, pip_pebble, willow, silas, marigold, old_gus, biscuit | master_cinder | 01–05, 11–13 | 8 |
| cedar | 9 | 9 | maeve, sparky, quill, alder, patch, belle, kit | hank, luz | 06–10, 14–17 | 9 |
| flathead | 9 | 9 | freya, bramble, ingrid, bjorn, willa, dakota, mitzi | torvald, eli | 18–26 | 9 |
| crater | 9 | 9 | ignis, ashby, bea, ember, mist, juno, tamsin | nyx, fumi | 27–35 | 9 |
| nebula | 9 | 9 | nebula_paws, comet, lyra, vega, selene, andi, rigel | orion_cat, twinkle | 36–44 | 9 |
| **Total** | **45** + 5 hosts + 2 travelers = **52** | 44 | | | **44** | **44** |

The objective fields used here are defined in the `02 §12.3` type table. V1-31
implements and validates these shapes before the authored quest data is loaded.
