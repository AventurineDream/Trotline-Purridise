# Trotline Purridise — V1.0 Canon & World Bible

*Final V1.0 beta source of truth · third and final review · 19 October 2026*
*Supersedes `V1_0_CanonSheet.md` (Gemini). Extends the implemented V3 baseline in
`docs/narrative/`; it never contradicts what is already shipped unless a migration
rule in `06-IMPLEMENTATION-GUIDE.md` says how.*

## 0. How to use this packet

| File | Authority over |
| --- | --- |
| `00-FINAL-REVIEW.md` | Why each decision was made; findings against the Gemini drafts and the second review |
| `01-CANON.md` (this file) | Names, identity, tone, places, story spine, truth rules |
| `02-GAMEPLAY-SPEC.md` | Every system rule and number |
| `03-CONTENT-TABLES.md` | Species, legendaries, baits, pantry, dishes, boats, Bot chassis, zones |
| `04-CHARACTERS.md` | All 52 cats, Bot, relationships, schedules |
| `05-SCRIPT.md` | Every authored line players read |
| `06-IMPLEMENTATION-GUIDE.md` | Architecture, save v2, data formats, memory budget, testing |
| `07-TICKETS.md` | The build plan; mirrored as GitHub issues |

If two files disagree, the order of precedence is: **02 > 03 > 01 > 04 > 05 > 06**
for rules and numbers, and **01 > 04 > 05** for names and voice. Any disagreement is a
bug: fix the lower-precedence file in the same PR.

Words in this packet:

- **game minute / game hour** — the simulation clock. At 1× one real second is one
  game minute; a game day is 1,440 game minutes = 24 real minutes.
- **real minute** — wall-clock time the player experiences.
- **m** — game metres. Depth is stored in metres and *displayed in feet* (existing
  behavior); tables give both.

## 1. Identity

- **Player-facing title:** *Trotline Purridise*. The GitHub repository is
  **`AventurineDream/Trotline-Purridise`**; the Drive project retains the
  **TrotLineSim** name. "Little Briar" is now the name of the first lake only.
- **Story title:** *The Book of Five Waters*.
- **Genre:** a cozy, first-person trotline-fishing and boating game with a gentle,
  optional story. There is no rod and reel. You set lines, let them soak, and run
  them by hand.
- **Audience:** all ages, readable for a confident eight-year-old. No fail states in
  the default mode, no timers that punish, no violence, no peril played for tension.
- **Player:** the **Skipper**, an unnamed bipedal water-cat. Never named, never
  gendered; dialogue says "Skipper", "you", "dear" (Grandmother), "friend". The
  Skipper is seen only as paws on the tiller and line, a reflection in still
  water, and a silhouette on the Pescapedia title page.
- **World:** populated entirely by bipedal, talking water-cats. There are no humans.
  Fish are fish; birds, frogs, dragonflies and ducks are ordinary animals.
- **Bot:** a small tin-and-brass deckhand robot who rides the bow. Pronoun **he**
  (existing canon). Model plate reads *Deckhand Unit 04*; his own name is stamped
  under it in the form `Word-###` (e.g. *Copper-316*), unique per save. Cats call
  him by that name or simply "Bot".

## 2. The five pillars

1. **The lake is the main character.** Light, weather, water and fish behavior are
   the spectacle. Every system should give the player a reason to *look* at water.
2. **Cozy means no-fail, not no-choice.** Nothing the player does by default can be
   lost, ruined or stranded. Interest comes from choosing where, when and how to
   fish, not from avoiding punishment.
3. **Watch, then act (wu wei).** The best results come from noticing, waiting and
   working with conditions. Patience is rewarded visibly, and never by an invisible
   idle timer.
4. **Neighbors are worth returning to.** Every cat wants something small and
   specific, and greets you differently after you help.
5. **Tools extend curiosity.** Bot and his gadgets help the Skipper notice more.
   They never replace the Skipper's judgment and never prove a neighbor "wrong".

## 3. Truth rules

These keep the writing consistent and trustworthy.

1. **Factual lines must be true.** Any line that states a current fishing fact
   ("the trout are deep today", "thermocline at 14 ft") must be backed by the live
   simulation. Otherwise the line uses its written *uncertain* fallback.
2. **Folklore is attributed, never "corrected".** Book entries keep *What we heard*
   (a cat's story, with their name) beside *What we found* (the Skipper's verified
   observations). Both stay forever.
3. **"In these waters."** Named real places are fictionalized inspirations. The book
   records how fish behave *in this game's waters*, not real-world science. Real
   species keep their real names and look; their in-game habits are simplified.
4. **Protected fish are always released.** Species flagged *protected* (bull trout,
   white sturgeon, Lahontan cutthroat) are recorded and released automatically, with
   a kind line about why. They are never sold or eaten.
5. **No unsafe staging.** Nobody tells the Skipper to fish in spillway foam, race near
   a dam, or go out in lightning. Big water is "the calm marked pool beyond the
   barrier". Weather is mood, not danger.

## 4. The Five Waters

All five lakes are fully driveable, separately loaded maps. Only one is in memory
at a time. Travel happens from a landing menu (existing behavior), and prose may
describe the journey.

| # | Lake (id) | Inspired by | Mood & palette | Hub · Host | Unlock |
| --- | --- | --- | --- | --- | --- |
| 1 | **Little Briar Lake** (`briar`) | Fictional woodland lake | Still water, cypress, lilies, reeds, warm mist · greens and amber | **Briar Landing** · Grandmother Whiskers | Start |
| 2 | **Cedar Creek Lake** (`cedar`) | Cedar Creek Reservoir, Texas (TWDB survey) | Open channels, wind, riprap, creek arms · sky blue and sandstone | **Cedar Landing**, with **Doc's Lonely Star Marina** on the dock beside it · Doc Barnaby | Start (existing saves), chapter 2 for the story |
| 3 | **Flathead Alpine Lake** (`flathead`) | Flathead Lake and the Glacier country, Montana (fictionalized, procedural) | Glacial clarity, snow peaks, larch, gusts · teal, white, gold larch | **Glacial Peak Outpost** · Captain Huckleberry | After the Briar and Cedar notes |
| 4 | **Crater Caldera** (`crater`) | Crater Lake, Oregon (fictionalized, procedural; no park data used) | Cobalt water, sheer rim, cinder isle, morning fog, warm springs · indigo, ash, ember | **Caldera Rim Dock** · Sora the Obsidian | After the Flathead note |
| 5 | **Starlight Nebula Lagoon** (`nebula`) | Fictional | The night sky's reflection made into water. Bioluminescent currents, floating lilies, aurora · violet, teal, starlight | **Cosmic Drift Station** · Professor Astra-9 | After the Crater note; first arrival is the story's finale |

Crater Caldera is a lake, not a reservoir. The Gemini name "Crater Caldera
Reservoir" is retired.

**How do you reach a lake in the sky?** On the clearest nights at Crater Caldera,
the water is so still that it holds the whole sky. Sora's recovered star reading
shows where the reflection is "deep enough to sail into." After that the Skipper can
travel to the Lagoon from any landing, at any time, because "once you have seen the
way, you can always find it again." Nobody explains it further. The Lagoon is
gentle, glowing and a little funny (Astra-9 keeps getting the units wrong). It is
not scary or lonely.

## 5. The Book of Five Waters — story spine

The story is optional, short, and ends in a place where free play continues. Total
target: **10–12 hours** for a player who follows it, while fishing normally.

**Prologue — The inherited book.** At Briar Landing, Grandmother Whiskers gives the
Skipper the landing's old fish book, the **Fishypedia**. It is a scrapbook of cat
stories about fish, started by her own grandmother and added to by "anyone who ever
tied up here". The last pages are blank. Her request: *"Bring back one useful new
note from each water. Not the biggest fish. A useful note."* Bot finds a pencil stub
in the spine and keeps it.

Each lake chapter is three small steps: **meet → notice → share**. Each one ends
with a visible change in the world and a page in the book.

| Ch. | Water | Small problem | What the Skipper does | Visible payoff | Unlocks |
| --- | --- | --- | --- | --- | --- |
| 1 | Little Briar | Pip & Pebble's map is missing the passage through the reeds | Scout three points along the reed edge with Bot. Fish the reed pocket once | Their map (and the chart) gains the **Reed Passage**. Grandmother knits Bot a wool collar | **Frog Bot** chassis, Reed Anchor |
| 2 | Cedar Creek | The current has carried Doc's old blue-jug marker away from the catfish pool | Follow the drift line, find the jug, and set a line where it really is now | Doc's directions change. The **Marked Pool** gets a proper barrier and sign | **Rubber Duck Bot**, Wave Chime; Doc tows your boat north |
| 3 | Flathead Alpine | Huckleberry's trusty depth note no longer explains the quiet fishing | Take two readings, morning and afternoon. See that the fish follow the cold layer. Set lines at the new depth | Huckleberry writes your note beside his old one and admits it happily. Bot's collar comes loose in the mountain wind | **Clockwork Copper Sub**, Thermocline Scanner; Crater travel |
| 4 | Crater Caldera | Fog hides Sora's survey marker, leaving a gap in her chart | Pick a safe spot to wait for the forecast clearing. Read the marker when it shows | The gap is filled, and the reading points "into the sky". Bot picks a new adjustable knot for his collar, with your help | Star reading, so Nebula travel |
| 5 | Starlight Nebula | Astra-9's survey keeps rippling the reflection where a visitor is said to appear | "Settle in." Stop, watch three changes in the water, and let Astra-9 join you | The **Celestial Star-Whale** rises. Bot hands the Skipper the pencil, and the Skipper draws it | **Astral Starlight Bot**, Zero-G Winch; the ending |

**Ending — The first new page.** Back at Briar Landing (the game offers a free
trip), Grandmother reads the five notes aloud while the hosts listen over Pounce's
radio. The book's spine is re-stitched with the title *The Book of Five Waters*, and
the author line adds "the Skipper & {BotName}". Bot: *"Different knot. Still my
favorite."* Credits roll over the Skipper's boat on still water at dawn. Then play
continues.

**After the story:** all lakes stay open. Every unfinished side quest, legendary and
Pescapedia goal remains. **Verifying every species** renames the book once more, to
the **Pescapedia** (optional, about 50 hours). Shinies, boats and Old Salt mode never
gate the story.

The V3 legend **The River of Whys & The Whiskered Guardian** stays canon as one of
Cedar Creek's local stories. It is no longer the overall story title.

## 6. Bot

- **Personality:** curious, earnest, literal, quietly funny. He loves the wool collar
  more than any gadget. He asks before he adds anything to the book ("Shall we add
  that?"). He calls the Skipper "Skipper".
- **Voice:** short text in the HUD, with soft brass clicks and chimes as audio cues.
  Every chime has a text caption. He never speaks over an NPC.
- **What he does:** scouts (existing B behavior), reports depth, ground and bait
  advice, operates the unlocked tools, and suggests things. He never catches fish,
  never changes bite rates by himself, and never scolds.
- **Chassis:** five shells (Classic Tin, Frog, Rubber Duck, Clockwork Copper Sub,
  Astral Starlight). A shell **permanently unlocks a tool**. Tools then work with
  *any* shell. Changing shells keeps his name, memories, collar and progress.
- **The collar arc:** received (ch. 1) → comes loose in the wind (ch. 3) → Bot picks
  an adjustable knot with your help (ch. 4) → "Different knot. Still my favorite."
  (ending). The collar renders on every shell. A setting can hide it without changing
  any story line.

## 7. Legendaries

Twelve legendary fish, at least two per lake. Ten are **caught** and then always
released after the book records them. Two are **witnessed**: wu wei, some things you
only watch. Full rules are in `02 §7`, data in `03 §3`.

| Lake | Legendary | Kind |
| --- | --- | --- |
| Little Briar | **Old Lantern** — a golden channel catfish that lives under the landing | Caught |
| Little Briar | **The Lily Queen** — an enormous chain pickerel | Caught |
| Cedar Creek | **The Spillway Monster** — a 95 lb blue catfish in the Marked Pool. Available from day one with a heavy line | Caught |
| Cedar Creek | **The Channel Leviathan** — a 120 lb alligator gar | Caught |
| Cedar Creek | **The Whiskered Guardian** — the V3 twilight sighting (already implemented) | Witnessed |
| Flathead | **The Glacial Phantom** — a ghost-pale bull trout (protected) | Caught |
| Flathead | **Old Silverhead** — an ancient lake trout | Caught |
| Flathead | **Huckleberry's Whopper** — the burbot from his tall tales, real after all | Caught |
| Crater | **The Obsidian Gar** — a glassy black gar of the cinder isle | Caught |
| Crater | **The Caldera Fire-Lizard** — not a fish at all; a glowing giant salamander. The book is delighted | Caught |
| Nebula | **The Nebula Weaver** — a ribbon-finned fish that leaves light trails | Caught |
| Nebula | **The Celestial Star-Whale** — the finale visitor | Witnessed |

## 8. Tone and voice

- Warm, specific and small. *"The lilies are holding the morning very gently"* beats
  *"Nature is peaceful."*
- Cat humor: naps, boxes, sunbeams, knocking things off tables, the dignity of a
  missed jump. No puns in more than one line out of five.
- Each host has a recognizable sentence shape (see `04`). Lessons are shown, not
  preached. No character says "wu wei", "balance" or "patience is a virtue".
- Dialogue never contains mechanics. A cat says "set a line in the lily cove with
  worms". The journal objective says "Std or better line · Nightcrawlers · Lily cove".
- Weather is never a threat. Rain is "a good soaking for the lines".
