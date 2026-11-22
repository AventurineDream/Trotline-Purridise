# Trotline Purridise

*A cozy, first-person trotline-fishing game.* You are the Skipper, a water-cat,
with Bot, a tin deckhand riding the bow. Set lines, let them soak, run them by
hand, and fill an old fish book with notes from five very different waters. No rod
and reel, no fail states, no hurry.

## Status

The **V1.0 beta** is in production. The design is final, and implementation is
tracked as GitHub issues labeled `v1.0`.

The landing's **Lakes** tab lists all five waters. Briar and Cedar remain open
from the start. Completing chapter 2 opens Flathead, chapter 3 opens Crater,
and chapter 4 opens Nebula; pull every line and return to the landing before
travelling. Flathead now has a procedural alpine landscape, snow mist, larch
and spruce, and Glacial Peak Outpost. Crater now has a steep caldera, obsidian
cinder isle, thermal springs and a clear-night sky mirror. Nebula now has its own
generated lagoon: stardust dunes, lily drifts, reed and current lanes, and aurora
nights. All 144 standard fish are now authored
and catchable: 36 each on Briar and Cedar, and 34 on each new water. Briar's chart now includes the
Reed Passage. [Lake framework](docs/issue-51/README.md) · [Fish data and captures](docs/issue-52/README.md) · [Flathead captures and load evidence](docs/issue-53/README.md) · [Crater captures and budgets](docs/issue-54/README.md).

| | |
| --- | --- |
| **Repository** | [`AventurineDream/Trotline-Purridise`](https://github.com/AventurineDream/Trotline-Purridise) |
| **Design packet** (source of truth) | [`docs/v1/`](docs/v1/): [Final review](docs/v1/00-FINAL-REVIEW.md) · [Canon](docs/v1/01-CANON.md) · [Gameplay spec](docs/v1/02-GAMEPLAY-SPEC.md) · [Content tables](docs/v1/03-CONTENT-TABLES.md) · [Characters](docs/v1/04-CHARACTERS.md) · [Script](docs/v1/05-SCRIPT.md) · [Implementation guide](docs/v1/06-IMPLEMENTATION-GUIDE.md) · [Tickets](docs/v1/07-TICKETS.md) |
| **Implemented baseline** | V3 narrative layer: [`docs/narrative/`](docs/narrative/) (12 quests, Ripples, Whiskered Guardian) |
| **Review policy** | [`docs/PR-REVIEW-POLICY.md`](docs/PR-REVIEW-POLICY.md) |

### V1.0 at a glance

- **Five waters:** Little Briar, Cedar Creek, Flathead Alpine, Crater Caldera and
  the Starlight Nebula Lagoon.
- **144 species + 12 legendaries**, in an inherited book that grows from cat
  folklore (*What we heard*) to verified notes (*What we found*).
- **52 visible cat neighbors**: 5 hosts with errands, 2 travelers, and 45
  water-cats (44 encounters, each with a want, a quirk and two quests).
- **The Book of Five Waters:** a short, optional story (10–12 h). Free play
  continues afterward.
- **24 boats** in eight families, with traits instead of a strict ladder.
- **Bot's five shells and tools:** sonar grid, reed anchor, wave chime,
  thermocline scanner, zero-G winch.
- **Cozy by default** (nothing can be lost), plus an opt-in **Old Salt** routine
  mode.
- **Built to a 3 GB RAM cap** with fully procedural art.

## Playing

Press **H** in the game for help. Each page covers one topic, and the last pages
are the **keyboard** and **gamepad** tables. The keyboard table shows the keys you
have actually bound, so a rebound key shows correctly. Change keys in Pause →
Settings → Keyboard controls. The **First hour** page is the place to start.

### The five waters

- **Little Briar**: where you start. Reeds, flats and the landing, and the Reed Passage on the chart.
- **Cedar Creek Lake**: a reservoir with a branching shore. Open from the start.
- **Flathead Alpine Lake**: opens after chapter 2. Snow mist, and a cold layer you can scan for.
- **Crater Caldera**: opens after chapter 3. A steep caldera, warm springs and fog.
- **Starlight Nebula Lagoon**: opens after chapter 4. Currents, reeds and aurora nights.

Travel from a landing: press **E** and choose the Lakes tab. Pull your lines first.
Money, catches, gear, boats and the journal come with you.

### The main systems

- **The book (J)**: 144 fish and 12 legendaries. Entries grow from rumor to verified notes. Track one species for a shiny (about 1 in 64).
- **Cats and quests**: hail a cat with **C**. Quests give cash, Ripples and keepsakes. Turn-ins never take your fish. Friends write letters.
- **The week**: the book's Week tab shows each lake's Lake Days. On Sunday from 5 to 8 PM the lake's cats gather at the landing for a cookout.
- **Kitchen (K)**: cook a dish from one fish and one pantry item, at a landing or on a galley boat at anchor.
- **Comfort**: Cozy (the default) has no penalties. Old Salt adds energy and hunger routines, and still never strands you. A catnap (**Z**) passes two hours, and a nap can bring Bot's dream, a habitat lead.
- **Bot (B)**: five shells and five tools, including the Wave Chime (**G**) and the Zero-G Winch.
- **Legendaries**: twelve in all. Ten can be caught and two are witnessed, the Whiskered Guardian and the Star-Whale. Trophy replicas hang on boats with a trophy rail.

### Your Skipper

**New morning** asks for a pace, then opens the Skipper creator. Choose a row with **W/S** and change it with **A/D**. The rows are name, pattern, coat, markings, bib and mitts, eyes, ears, tail, fur, hat and specs, hat colour, neckwear, neckwear colour, jacket and jacket colour. On the name row, typing edits the name. **Q** and **E** turn the Skipper (gamepad **LB** and **RB**). **Done** starts the morning, and **Esc** goes back to the pace choice.

In play, **Pause → Your Skipper** reopens the creator. Done saves and returns to the game; Esc cancels without saving.

### Where your save lives

The game saves to `save.json` in your per-user app-data folder, not the install
folder. (Only if that folder cannot be found does it use `saves/save.json` beside
the game.) It autosaves about every 45 seconds and when you quit. An older
`saves/briar.json` is migrated, and a backup of the original is kept in a
`backup` folder beside the new save. Start the game with `--save PATH` to use a
different file.

## The current build

Everything below describes what is playable on `main` today. The game was
previously titled *Little Briar*; that is now the first lake's name.

A first-person trotline game with five lakes, 144 catchable species and 12 legendaries, and 24 boats in eight families. You start in a 12-foot jon boat, set lines, let them soak, and sell the catch at the landing. The cat cast is 52 cats (51 roster rows; Pip & Pebble share one boat), and the story runs five chapters to *The Book of Five Waters*. There is no rod and reel.

The lake now uses a 16:9 OpenGL renderer: fixed terrain, a dense procedural forest, reflected trees and sky, gentle water ripples, warm dawn and sunset light, night lighting, and mist in rain. The boat and landing have individual boards and hardware, and the HUD uses a quiet lake-journal style.

The shore stays fixed. Terrain is baked once, the water boundary follows the same lake and landing-slip functions used by the simulation, and the camera no longer bobs or rolls while you look at the bank.

Both main landings have full marina wings around the original service slip:
planked promenades, finger piers, moored boats, lanterns, life rings, shore
buildings, and picnic details. Cedar has covered berths. The central approach
stays open, and the piers and moored hulls have matching collision footprints.
Trinidad Cove keeps its smaller, quiet launch.

The banks have cattails, grasses, wildflowers, shrubs, driftwood, shore stones,
herons, and ducks. Gulls circle above the lake, swallows dart, and broad-winged
herons fly more slowly. Dragonflies work the sunny margins; fireflies pulse
after dusk, while heavy rain quiets the wildlife. These are decorative, bounded
details, shared by the OpenGL and CPU renderers. They add no saved entities or
retained particle histories and do not change fishing or quest outcomes.

A moving boat leaves a wake, and fish rise on the open water. When a hook takes a fish, a ring spreads on that spot and a flagged cork stands up on the line. The chart and the corner list show which lines are soaking, which have fish, and which are getting tired. With the depth finder, idling tells you what you would bait there. The lake has a voice: lapping water, the motor or the rowboat's oar strokes, wind when you sail or it rains, birds at the edge of the day, frogs after dark, and a splash with the strike. M mutes it.

The full chart uses numbered habitat icons and a side key. Residents, your boat,
Bot's weather tip, and line states use keyed symbols instead of names over the water.

Weather blends over an hour on the lake, including changes at midnight. Cloud
cover, rain, mist, water chop, and lighting fade together; the sun and moon
follow continuous orbits across midnight and fade at the horizon. The sky uses
the fractional lake clock so lighting moves smoothly between game minutes.

Graphics are designed for a **3 GB RAM budget**. The 3D scene target is capped at 1440×810 and scales with its detail tier (low 55%, standard 60%, high 90%, ultra 100% of the window); UI remains native-size. The GPU upscales the scene before final readback. Low/standard use 1× sampling, while high/ultra use up to 4× antialiasing. Reflections use half the internal render resolution. Mesa software graphics uses at most 640×360. Text and UI layer caches are bounded by the tier (text 8–64 MiB, UI layers 32–256 MiB). There are no large downloaded texture packs or retained frame histories.

## Run

Pull requests follow the [review and CI policy](docs/PR-REVIEW-POLICY.md).

SDL2 and SDL2_ttf have to be on the system. The launcher installs NumPy and ModernGL in the local virtual environment. OpenGL 3.3 is required for the full scenery; a CPU renderer is available when graphics initialization fails.

```sh
./play.sh
```

That makes a `.venv` if you don't have one, installs the dependencies, and starts the game. A save is written to your platform's user-data folder (autosave about every 45 seconds, and on quit). An older `saves/briar.json` is migrated there on first launch, with a backup.

To set up a fresh clone and check it first, run `sh scripts/setup.sh` (on Windows, `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`). For an offline package that runs without Python, see the [release checklist](docs/RELEASE-CHECKLIST.md): `python3 scripts/build_package.py` builds it.

**Python versions.** Running from source needs Python 3.10 or newer. CI (`validation.yml`) and the release packages use Python 3.12, and that is the version whose green run gates a merge. Use 3.12 to match CI exactly. The local gate also passes on 3.14 (`uv venv .venv --python 3.14`). Lint with `ruff check .`; the rules are in `ruff.toml`.

```sh
./play.sh --selftest          # gameplay and graphics regressions. No window.
./play.sh --shots shots       # PNG frames of the lakes and menus
./play.sh --shots shots/legendary --legendary  # legendary scenes and book portraits
./play.sh --chart shots/chart.png
./play.sh --benchmark 1200    # five lakes, boats, menus, weather, and full coverage
./play.sh --software          # use the simpler CPU fallback
./play.sh --detail auto       # choose the highest tier that fits free memory
./play.sh --detail low        # lower-memory systems and the lightest GPU effects
./play.sh --detail high       # larger baked textures, shadows and scene targets
./play.sh --detail ultra      # upper tier; peak target 2,600 MiB RSS + GPU
./play.sh --detail standard   # pin the balanced tier
./play.sh --selftest --software
./play.sh --smoke             # real window, sailing, purchases, weather, and lake changes
```

Detail tiers keep the same shader path on GPU systems and size their baked
textures to available memory. `--detail auto` is the default; it selects a tier
from currently available RAM, and the low tier is forced for the CPU fallback
and Mesa software OpenGL. `TROTLINE_DETAIL=<tier>` can pin a tier for a
repeatable capture or benchmark.

For an opt-in playtest overlay, launch interactive play with `./play.sh --dev`.
It adds a persistent **DEV** marker; press **grave** from any screen to open or
close the panel. **Up/Down** (or W/S) selects a command, **Left/Right** (or A/D)
chooses a fish or any authored lake, **Enter/Space** runs it, and **Esc/grave**
closes it. While open, panel input is intercepted instead of reaching game
screens or controls. A `--dev` run never writes the loaded save; cheats and
ordinary play remain in memory only; title cheats carry through **Continue**.
Reset requires an explicit confirmation and never deletes the save file.
The panel offers **+$1,000**, **Refill bait**, **Starter kit** ($1,000 and a
bait-box refill), **Advance 1 game hour**, **Catch standard fish**, **Fill first
line** with distinct standard species, **Change lake** (unlocks the selected
authored route in memory; requires a docked boat and no deployed lines), **Set
up Old Lantern encounter**, and **Reset in-memory session**. The legendary
fixture requires Little Briar, no deployed lines, a held line, and enough
bait-box capacity; it uses the authored Old Lantern requirements and real hook.

The benchmark writes `shots/benchmark.json`, records peak process RAM and DRM-reported GPU memory, and fails if their combined bytes reach 3,000,000,000. Its 1,200-frame run checks all five lakes and boats, eight shop tabs, all 24 help pages, every fish and cat model, 12 quest journal entries, and all twelve dialogue givers across four quest states. It exercises weather, fuel and battery, paint, buoys, audio, a legendary scene and catchability, while checking per-subsystem memory and fixed geometry. Results depend on the graphics driver and other applications running on the computer.

During play the window and lake share one OpenGL context. The window check reads the pixels submitted to the actual window and verifies that presenting a frame does not corrupt subsequent lake frames. Headless screenshots use a separate standalone context.

The `backups/` folder, which holds the original-source archives, is git-ignored and not part of this repository. Older saves keep their money, fish, lines, gear, and records. They start with the owned jon boat and a full starter fuel tank; the new boats must be purchased. The active lake, owned boats, fuel tanks, rowboat battery, and its charge allowance for the current landing visit are saved. Engines resume at idle and sails resume lowered.

## Modes and catnap

New morning asks you to choose a pace, **Cozy** (default) or **Old Salt**, then opens the Skipper creator. You can switch
any time in Pause → Settings. Cozy applies no needs penalties. Entering either
mode clears the routine counters; entering Old Salt starts them at zero.

Press **Z** or hold gamepad **Y** to take a two-game-hour catnap at anchor or a
landing. A boat with a **hammock** can nap while idling with the sail down.
Pause also offers the shortcut **Z** / gamepad **X**. Lines soak normally. Any
key or click finishes the fade; each nap advances the full two hours once.

The first nap in a six-hour window grants **Rested** for six active game hours
and, when a lead is available, a **Bot's dream** habitat note for a fish uncaught
on this lake. One ordinary unread dream waits at a time; Huckleberry Fish Pie can queue an extra. Opening the book goes to that
lead; its heard note stays after reading it. Extra naps pass time and reset Old
Salt Energy without extending an existing Rested window.

In **Old Salt**, 16 awake game hours brings **Drowsy** (hauling 25% slower and
soft screen edges). After 20 hours, the boat anchors safely for a catnap.
More than 24 hours without a meal brings **Peckish** (boat speed reduced by 20%).
Needs invitations appear at most once per ten real minutes of active play;
**Later** snoozes that need for thirty active real minutes. Menus, lost focus,
and time offline freeze the needs and Rested clocks.

## Pantry and kitchen

Open the landing shop with **E** and choose **Kitchen**, or press **K** to open
your pantry. Gamepad users can open the pantry with **Y** from Pause. A galley
boat can cook while anchored; every boat can carry and eat Kibble Tins.

Each host sells a specialty ingredient and **$3 Kibble Tins**. The pantry holds
**20 of each item**. A snack resets Old Salt hunger without replacing a picnic
buff. Hosts teach two dishes during their chapter; missed dish cards cost
**$40 after that chapter**. Legendary clue tellers provide recipe-bait cards.

A dish uses one food-group fish and one pantry ingredient. The confirmation
screen selects the smallest eligible fish; **Up / Down** chooses another.
Shiny, Treasured, protected and legendary fish are never used. A cooked dish
replaces the previous picnic buff. Six-hour buffs pause in menus and offline;
haul buffs keep their remaining checks across saves and travel. A charge is
spent when a hook rises or the check is shown instantly. Skipping the two-second
steam-and-bowl scene never cooks twice.

The ten dishes improve scouting, haul speed, fuel use, favorable-water
invitations, dream leads, fog visibility, bait retention, shiny progress or buoy
visibility. Huckleberry Fish Pie queues an extra dream without discarding an
unread one. Moon-Milk Pudding gives an extra guarantee credit per tracked fish
on the next three checks; the next newly hooked fish uses an earned guarantee.
Starlight Soup lights your buoys for six game hours and makes its Old Salt meal
last 48 game hours. Later snacks or dishes retain any longer remaining meal
window while granting at least 24 hours from when they are eaten.

Recipe bait uses **one piece of each parent bait plus one pantry item** and
makes **twelve pieces**, subject to bait-box capacity. It takes the better
species match of its two parents and is selected normally when setting a line.
The bait picker scrolls through all seventeen baits. A weather invitation marks
currently favorable nearby water on the chart for two game hours; Bot stays
quiet when no such water is nearby.

## Five waters

**Little Briar** retains its familiar shoreline, landing, and fishing grounds. Its 36-species collection can be found here.

**Cedar Creek Lake** recreates the Texas reservoir's branching shoreline, islands, and depth contours from the [Texas Water Development Board's 2017 survey](https://www.twdb.texas.gov/surfacewater/surveys/completed/index.asp). Horizontal distances are compressed tenfold for play; depth stays in metres and is capped at about 53 feet. The landing is placed near the County Public Ramp on Caney Creek. The shoreline and depth grids are shared by graphics, the chart, fishing, and collisions.

Cedar Creek's stronger blue catfish, white bass, hybrid striped bass, and crappie fishing is informed by [TPWD's Cedar Creek profile](https://tpwd.texas.gov/fishboat/fish/recreational/lakes/cedar_creek/) and [2023 fisheries survey](https://tpwd.texas.gov/publications/pwdpubs/media/lake_survey/pwd_rp_t3200_1267_2023.pdf). The broader fish community, catch rates, prices, scenery, and boat handling are game design. Six Little Briar specialties are absent from Cedar Creek, giving the lakes different fishing profiles.

At a landing, press **E**, choose the **Lakes** tab with **A/D**, choose a destination with **W/S**, then press **Enter**. Pick up your deployed lines before towing to another lake. Money, livewell catches, held lines, bait, upgrades, owned boats, fuel, and journal records travel with you.

The game loads only the bundled `fishing/assets/cedar.npz` and `cedar.json`, about 4 MB. It needs no map downloads during play. The asset records its source and checksum. `scripts/build_cedar.py` rebuilds it from the public TWDB survey using build-only GIS libraries; those libraries are not game dependencies.

## Boats and fuel

At either landing, the Boats tab's **first row** refuels the active powered boat. New powered boats include a full tank, and switching to a boat you already own is free. Each powered boat keeps its own fuel; switching cannot refill a tank. The rowboat has no fuel tank.

| Boat | Purchase | Tank | Character |
| --- | ---: | ---: | --- |
| Aluminum Jon Boat (12 ft) | Starting boat | 12 L | Light and nimble tiller boat with the original handling |
| Cat-Rigged Daysailer (12 ft) | $650 | 6 L | Wind power uses no fuel; a small auxiliary motor |
| Classic Pontoon (15 ft) | $1,450 | 36 L | Wide deck, sheltered helm, hammock, slower turns, and 40 lb extra livewell space |
| Reinforced Rowboat (10 ft) | $325 | — | Blue plastic hull; oars by default, with an optional electric trolling motor |

This table lists the four original boats. The other twenty are sold in the same Boats tab, in eight families; each boat's price, tank and burn rate are in `fishing/assets/content_v2/boats.json`.

All four models have their own complete hull collision footprint and draft. A wider boat needs more clearance. Motor and livewell upgrades stay with your equipment; motor upgrades improve every tiller boat (the jon boat, pontoon, River Runner Skiff and Duck Hunter Jon), while the daysailer's auxiliary remains small. Sell enough fish before changing to a boat with a smaller livewell.

**Q** raises or lowers the daysailer's sail. Raising it lifts the anchor. **A/D** steers, while the sail trims to the wind. A reach across the wind is fastest; the boat cannot sail straight into the wind, so tack or use the auxiliary. The HUD shows wind direction, wind speed, and sail status. **Space** anchors and lowers the sail. **Shift** idles the auxiliary; a raised sail keeps providing wind power.

**Sailing burns no fuel.** Powered travel uses fuel according to the engine, boat, throttle, and lake clock. Burn is **half the boat's table rate in Cozy** and **two-thirds in Old Salt**; an active fuel-saving dish further reduces it. A lowered throttle uses less fuel, and idling or anchoring does not consume it. Fuel costs **$1.40 per litre**, sold in up-to-five-litre fills, limited by tank space and available cash. Empty tanks stop motor thrust, but the daysailer can keep sailing and the rowboat can keep rowing.

The rowboat runs on oars without fuel. You can fit an optional **$350 9.9 hp electric trolling motor** with an **18 kWh battery**. Charging costs **$0.35 per kWh**, up to **5 kWh per landing visit**. Leave and return to charge again; the oars still work when the battery is empty.

If you run out away from a landing, idle the boat (lower the sail if raised)
and press **R** to tow back to the current landing. A tow takes one game hour.
It is **free in Cozy**; in **Old Salt** it costs the smaller of your cash and
**$25 + 2% of the active boat's price**. Any shortfall is waived, including at
$0. Deployed lines keep soaking in place.

## On the water

One real second is one minute on the lake. A day is 24 minutes. `T` cycles 1×, 3×, 6×, and 12× while the boat is idling or anchored. At 12× a whole day takes two real minutes. Lines keep fishing for up to six real hours while the game is closed. A hook holds one fish, and a fish spoils after 13 game hours, so a long absence is one soak.

**Bot** is the tin deckhand on the bow. `B` sends him to the nearest trotline, or a short way ahead if nothing is set. He calls back the depth (a range, unless you own the finder), the ground, and what he would bait. `B` again brings him home. He does not change what bites or what fish are worth. A tow or a change of lake puts him back on deck.

Every key and button is on the help screen (**H**), in its own pages for the keyboard and the gamepad. The keys shown there are your current bindings.

Menus accept **W/S** to move through items and **A/D** to change tabs, lines, or
pages. Arrow keys also work, including held-key repeat. Enter or Space selects;
Esc closes. On a controller, the D-pad or left stick moves through menus, the
D-pad changes tabs or pages, A selects, and B returns. The on-screen hints switch
to controller glyphs after the last controller input, and back to keyboard hints
after the last keyboard input. Release a direction used in a menu before using it
to drive the boat again.

**Pause → Settings → Camera view** switches between **First person** (the
default) and **Third person**. The preference is saved. Third person keeps a
fixed position behind and above the boat, without bob or smoothing. Authored
story shots take priority; the selected view returns when staging ends.

Short taps are retained even when pressed and released between rendered frames.
Losing window focus clears pending input and menu repeat, while held steering
and throttle still follow the current keyboard state.

**J** opens the inherited book, with **Fish**, **Book**, **Ripples & Keepsakes**,
**Story**, **Watch** and **Week** tabs. Use **A/D** (or gamepad left/right) for tabs,
**W/S** (or gamepad up/down) to choose, and **Enter/A** to open a fish page or
turn its notes. You can also click tabs, fish, the page controls and Close;
the mouse wheel browses entries. Unknown fish keep their folk names and
silhouettes until caught. The Book page keeps *What we heard* beside *What we
found*, with stamps for each stage. The collection shelf cycles through Ripples,
Keepsakes and Trophies. **Story** retains **Lake Whispers & Ripples**, including
quest status, objectives, progress, locations and Bot's saved notes. Declined
offers remain available, and missed time windows return later. Book renames
receive a title-page ceremony when you return to Briar Landing.
Story details wrap across numbered pages in small windows; **Enter/A** or
**Turn** advances through the complete objective and prerequisites.
Rumors, Watch clues, legendary records and keepsake descriptions also wrap onto
as many pages as needed. Finish the Watch card's pages to open its entry;
finish a shelf item's pages to switch to the next shelf.
Each caught legendary gets a calm five-second reveal on its first haul; later
reveals can be skipped or hurried. The camera stays anchored and the catch is
still released. Its illustrated Book entry keeps the record and the Trophies
shelf shows a gold replica. The Fire-Lizard's page says “NOT A FISH!”; the
Zero-G Winch gives every legendary haul a floating-line variant.

Standard catches now have a **1 in 64** shiny chance, rolled once and saved on
the catch. After five catches of a species (**Verified**), its Book entry offers
**Track shiny**: click it, press **F** (the rebindable Set line action), or use
gamepad **X**. One species can be tracked at a time, with a shiny guaranteed by
its 50th catch since the last shiny. Counters survive switching targets and
reloads; untracked catches also advance their own species' counters. The entry
shows how many catches remain while tracking.

Shinies use their variant palette and **✦** labels, sell for **3×** normal value,
and start **Treasured**, so bulk sale keeps them until you remove that mark.
Shiny Trophy credit is awarded when you Keep or Release the fish. A hooked
shiny that gets away leaves no Trophy and returns its reserved pity progress.
Released or sold shinies remain recorded on the book's Trophy shelf. On that shelf, **F** hangs the selected replica on the current boat's rail, or takes it down. Only boats with a trophy rail take replicas: Deep-V Bass Skiff, Classic Mahogany Runabout, Small Sloop, Triple-Hull Party Barge, Lake Houseboat, Nebula Cruiser and Celestial Flagship.

Release W or S and the throttle stays where you set it. The HUD shows forward,
reverse, or idle and the lever percentage. Dropping the anchor resets the lever
to idle, and existing saves resume at idle.

The full 12-foot hull has collision barriers against the bank, dock piers,
the dock crossbeam, and solid rocks and stumps. Turns and movement are checked
in short steps, so the bow and corners stay out of obstacles. The hull sides
and rails continue back past the camera and fill the bottom of the view.

Nine ordinary baits: nightcrawlers, chicken liver, cut shad, live minnows, crawfish, dough balls, trout roe, ember grubs and star-dust. The 144 fish each have their own size range, value, bait preferences, habitat, activity period, and journal record. The journal scrolls through the full collection and shows fishing notes before the first catch. Sell fish at the landing and spend it on bait, lines, boats, fuel, motors, livewells, a bait box, a depth finder, a spotlight, and paint. A color you own can be worn again for free.

The collection includes bluegill; yellow, black, and brown bullhead; black and white crappie; common carp; freshwater drum; channel, blue, and flathead catfish; largemouth, smallmouth, and spotted bass; white and yellow bass; hybrid striped and striped bass; longnose, spotted, shortnose, and alligator gar; smallmouth, bigmouth, and black buffalo; redear, green, redbreast, and longear sunfish; warmouth; bowfin; blue sucker; golden shiner; gizzard and threadfin shad; and chain pickerel.


The **Week** tab shows the active lake's seven-day weather plan, Lake Days and
Sunday cookout. Days begin at 6 AM, with Monday as day zero. Tuesday dawn
panfish and Friday night catfish have Briar bonuses; Cedar has Thursday night
blue/channel catfish and Saturday daytime bass in open water or rocks. Forecasts
survive reloading and lake travel, and Watch cards show the next rare-weather
opportunity (story and gear requirements still apply).

On Sunday from 5–8 PM, meet the lake friends at the landing: six on Briar and Cedar, none yet on the other lakes. Open
**Kitchen**, choose **Share a fish at the Sunday cookout**, then confirm a fish
for one pantry gift per lake that Sunday. Chat with each friend from the same
menu. Shiny, Treasured, protected and legendary fish stay safe. Bot automatically
marks nearby favorable water at most once per day; the kitchen's manual weather
request shares that allowance, with the existing tacos exception.


Open **Bot** at a landing to see his stamped name, earned shells, tool ownership
and collar memory. Shell changes are free and preserve his notes and scouting
progress. Tools require the earned shell (Sonar Grid also requires the Depth
Finder) and remain owned with any shell. Story rewards advance the wool collar;
the chapter-four marker enables his saved knot choice. Settings can hide the
collar without changing the story. Bot's name also appears on Continue and in
the book. All five shells now have procedural models, with the wool collar and saved
knot, moving scout parts and distinct captioned chimes. Astral glows at night.
Reduced motion freezes decorative joints.
