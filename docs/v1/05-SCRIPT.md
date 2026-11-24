# Trotline Purridise — V1.0 Master Script

*Supersedes `V1_0_Script.md` (Gemini). Every line a player reads. Ids in
`backticks` are content keys for `fishing/assets/content_v2/`.*

## 0. Writing rules

1. **No mechanics in dialogue.** Cats speak like neighbors. Every quest also has a
   journal objective string (`obj:`) that states the rule plainly. Only the `obj:`
   string may contain tiers, numbers of minutes, or zone ids.
2. **Length:** at most 140 characters per bubble and 3 bubbles per node. Kids read
   these.
3. **Placeholders:** `{BotName}` (e.g. Copper-316), `{Skipper}` (always "Skipper"),
   `{lake}`, `{fish}`, `{depth_ft}`, `{zone}`. Never put a placeholder at the start
   of a sentence.
4. **Truth rule (canon §3):** any line marked **[F]** is factual and needs a live
   condition. When the condition is false, the game uses the line's declared
   fallback: a **[U]** twin, `fallback: silent` (say nothing), or
   `fallback: report` (the line's data comes straight from the simulation, so it
   is true whenever it is shown, as with Bot's depth and Sonar Grid reports). Every
   [F] line declares exactly one of the three.
5. **Every quest node set** has greeting, offer, accept, decline, progress, ready,
   ready-wait, completion and return (existing 9-node pattern). This script gives
   the lines that carry character. Implementers fill accept/decline/progress/
   ready-wait from §6.0 when a cat's entry omits them.
6. Bot's pronoun is **he**. The Skipper has no pronoun; use "you".

---

## 1. Prologue — Briar Landing (new game)

`pro_01` *(fade in on still water at dawn, the Skipper's paws on a tiller; the jon
boat bumps the dock)*
**Grandmother Whiskers:** There you are, dear. Mind the third plank; it likes to
squeak. And this must be your deckhand.
**Bot:** Deckhand Unit 04. The plate says {BotName}. Hello.
**Grandmother Whiskers:** {BotName}. What a fine, shiny name.

`pro_02`
**Grandmother Whiskers:** This was my old boat. She's slow, but she's honest. Let's
get you a line in the water before the tea goes cold.
`obj:` Set a trotline (F) anywhere near the landing.

`pro_03` *(after the first line is set)*
**Grandmother Whiskers:** Good. Now we wait, which is most of fishing. Bot, would
you show {Skipper} how you scout?
**Bot:** Scouting means I go and look. Then I tell you what I saw. I like it very much.
`obj:` Send Bot to scout (B).

`pro_04` *(after the first catch is brought up)*
**Grandmother Whiskers:** Oh, look at that. Your first one. Every fish here has a
story, you know. Come inside a moment.

`pro_05` *(inside the landing; the book on the counter)*
**Grandmother Whiskers:** This is the landing's old fish book, the Fishypedia. My
grandmother started it, and anyone who tied up here wrote in it.
**Grandmother Whiskers:** It's mostly stories, and not every one happened quite the
way it's told. The last pages are empty.
**Grandmother Whiskers:** Would you carry it for a while? Bring back one useful new
note from each water. Not the biggest fish. A useful note.
*Choices:* **"I'd love to."** → `pro_06` · **"What kind of note?"** → `pro_05b`

`pro_05b`
**Grandmother Whiskers:** The kind that helps the next cat. Where the fish really
are, when the weed moves, which way the mist goes. You'll know it when you find it.
→ `pro_06`

`pro_06`
**Bot:** There is a pencil in the spine. It is very short.
**Grandmother Whiskers:** Then write small, dear. Pip and Pebble were asking for
you out on the flats. They have a map with a hole in it.
`obj:` Story — *The Book of Five Waters*. Talk to Pip & Pebble on Little Briar.

---

## 2. Chapters

### 2.1 Chapter 1 — *The Reed Passage* (Little Briar)

`story_c1_s1` *(talk_to pip_pebble)*
**Pip:** Skipper! Life jacket? You're wearing one. Good. Look at our map. There's
a way through the reeds, we *know* there is, but it isn't on here.
**Pebble:** Frogs live in the reeds. Big ones. *(quietly)* I don't go in there.
**Pip:** Could you and {BotName} find where the reeds open up? Three spots should do it.
`obj:` Send Bot to scout 3 marked points along the reed edge (any order).

`story_c1_s2` progress *(after each point)*
**Bot:** [F] Water opens to {depth_ft} ft here. Soft ground, reeds thinning to the
north. · [U] Reeds are thick here. I do not see a way through yet.
completion *(third point)*
**Bot:** The three openings line up. There is a passage. I would like to tell Pip.

`story_c1_s3` *(back at Pip & Pebble)*
**Pip:** It goes all the way?! Pebble, write it down, write it down!
**Pebble:** You write it, I'm holding the crayons.
**Pip:** Last thing. Grandmother says a passage isn't real until somebody fishes it.
Here, take our old reed anchor. It holds in the soft stuff.
`obj:` Catch any fish in the Reed Passage (a Reed Anchor is provided).

`story_c1_end` *(turn in to Grandmother after the catch)*
**Grandmother Whiskers:** The Reed Passage. My grandmother used to row through
there, you know. Then the reeds closed and everyone forgot.
**Grandmother Whiskers:** That's a useful note. Write it in, dear. And
{BotName}, come here a moment. Hold still.
*(she ties a small wool collar around Bot's neck)*
**Bot:** It is warm. I do not need to be warm. I like it.
**Grandmother Whiskers:** Pip left you something too. A frog-shaped shell, of all
things. Pebble insisted.
`reward:` Frog Bot shell · Reed Passage chart layer · Book page *Little Briar*.
`obj:` Story — Doc Barnaby at Cedar Creek has lost something.

### 2.2 Chapter 2 — *The Drifted Marker* (Cedar Creek)

`story_c2_s1` *(talk_to doc_barnaby)*
**Doc Barnaby:** Skipper! Heard you found a whole passage on Briar. Well, I've lost
a whole jug.
**Doc Barnaby:** For thirty years my blue jug marked the catfish pool. Now
it's gone and I keep sending folks to the wrong water. Embarrassing!
**Doc Barnaby:** The current took it, that's my guess. Follow the drift line, would
you? Bot's got better eyes than my old gauges.
`obj:` Follow the 3 drift buoys in order to find the blue jug.

`story_c2_s2` progress
**Bot:** [F] Current is setting toward the dam riprap. The next buoy is ahead. · [U]
The water is quiet here. I will look for the next buoy.
completion
**Bot:** Blue jug located. It is wedged on the riprap, upright and pleased with
itself.

`story_c2_s3`
**Doc Barnaby:** Ha! The old rascal. So the pool moved too. Fish follow the soft
water, not my jug.
**Doc Barnaby:** Set a good line right where it sits now. Nightfall's best. If the
cats bite there, I'll change my directions for good.
`obj:` Set a premium or heavy line in the Marked Pool and let it soak 60 active minutes, then check it.

`story_c2_end`
**Doc Barnaby:** That's it, that's the spot! I'll have a proper barrier and a sign up
by morning. Calm water, marked edges, nobody near the spillway.
**Doc Barnaby:** Sparky made you something, too. Says it squeaks on purpose.
**Bot:** I am a duck now. I would like to try the chime.
**Doc Barnaby:** And Skipper, you've earned a trip north. My trailer's hitched.
Captain Huckleberry's been hollering about his fishing for a week.
`reward:` Rubber Duck shell · Marked Pool · Flathead travel · Book page *Cedar Creek*.

### 2.3 Chapter 3 — *Two Readings* (Flathead Alpine)

`story_c3_s1` *(arrival; talk_to captain_huckleberry)*
**Captain Huckleberry:** Ho-ho! The Skipper! Doc said you'd come. Warm your paws by
the stove, I've got a story—
**Captain Huckleberry:** —it's about my note. *"Lake trout, forty feet, every day,
guaranteed."* Thirty winters it worked. This summer? Nothing!
**Captain Huckleberry:** Either the fish have moved or I've got old. Bet you a pie
it's the fish.
**Bot:** I can listen to the water's temperature with this borrowed scanner. Two
readings would tell us more than one.
`obj:` Have Bot report in the Glacial trench once in the morning (06:00–10:00) and once in the afternoon (14:00–18:00).

`story_c3_s2` reports
**Bot (morning):** [F] Cold water begins near {depth_ft} ft this morning. · [U] I
could not find the cold layer here. Try the deeper middle.
**Bot (afternoon):** [F] Now the cold water starts near {depth_ft} ft. It moved. ·
[U] The reading is unclear. The trench is deeper toward the center.
completion
**Bot:** The fish are not at forty feet. They are wherever the cold is. The cold
moves.

`story_c3_s3`
`obj:` Catch any cold-water fish from a line set inside the cold layer.

`story_c3_end`
**Captain Huckleberry:** You — it — the *cold moves*?! Ho-ho-HO! Thirty years! I was
right *and* wrong! That's the best kind of story!
**Captain Huckleberry:** Here, write it beside mine. Don't cross mine out. Let folks
see how we learned it.
*(a gust; Bot's collar slips loose and flaps)*
**Bot:** My collar. The wind is very strong here. It is holding on by one loop.
**Captain Huckleberry:** Keep the scanner, it's yours. Sora at the Caldera's been
asking about cold water too. She's quiet, but she'll like you.
`reward:` Clockwork Copper Sub shell · Thermocline Scanner · Crater travel · Book page *Flathead Alpine*.

### 2.4 Chapter 4 — *The Fog Marker* (Crater Caldera)

`story_c4_s1` *(talk_to sora)*
**Sora:** Skipper. Bot. Welcome. One question first: do you like waiting?
**Sora:** My survey marker is out there. The fog sits on it every morning. My chart
has a hole exactly where the marker is.
**Sora:** The forecast says the fog will lift. Choose a safe cove and wait for it.
Then we read the marker together.
`obj:` Wait in one of the three marked coves until the fog clears. Anchored time adds up; drifting does not reset it.

`story_c4_s2` progress
**Bot:** [F] Fog is thinning. I can see the rim now. · [U] Still foggy. That is all
right. Fog is a kind of weather that likes company.
completion
**Bot:** The marker is visible. It is a brass ring on a post. It is pointing up.

`story_c4_s3`
`obj:` Have Bot scout the survey marker.

`story_c4_knot` *(at the marker, before the reading)*
**Bot:** Skipper. My collar again. Will you help me tie it? I would like to choose
the knot.
*Choices (cosmetic, saved):* **Square knot** · **Bow** · **Sailor's hitch**
**Bot:** This one. I can loosen it myself when it is cold, and tighten it when it is
windy. It adjusts.

`story_c4_end`
**Sora:** The reading is… odd. The marker isn't measuring the water. It's measuring
the reflection.
**Sora:** On the clearest nights the caldera holds the whole sky. This says the
reflection there is deep enough to sail into. I've checked it eleven times.
**Bot:** I would like to check it a twelfth time. Then go.
**Sora:** Of course you would. Professor Astra-9 lives there. Tell her I said her
units are wrong.
`reward:` Star reading · Nebula travel · Book page *Crater Caldera*.

### 2.5 Chapter 5 — *Settle In* (Starlight Nebula Lagoon)

`story_c5_arrive` *(first travel: the reflection deepens and the boat tips gently
into starlight)*
**Bot:** We are on the sky. I do not have a word for this. I will keep looking for one.

`story_c5_s1` *(talk_to astra_9)*
**Professor Astra-9:** Salutations, Skipper and {BotName}! Welcome to Cosmic Drift
Station, three point one parsecs above sea level!
**Bot:** That is not how parsecs work.
**Professor Astra-9:** Splendid, a colleague! Listen: there's a visitor here, a
whale made of light. It rises where the reflection is calmest. But every time I
survey the spot, the water ripples and it won't come.
**Professor Astra-9:** I have measured everything. Perhaps the answer is to measure
nothing?
`obj:` Anchor near the calm reflection in Nebula open and choose "Settle in".

`story_c5_settle` cues *(auto, during settle)*
- 15 s: **Bot:** The stars have stopped wobbling.
- 30 s: **Bot:** The lilies are drifting toward us. Slowly. I think they are curious.
- 45 s: **Bot:** Something is coming up. It is not in a hurry.
*(after the first cue, Astra-9's skiff drifts alongside: "May I watch with you?"
→ "Watch together" completes the rest hands-free)*

`story_c5_whale` *(the Star-Whale rises, turns once, and the reflection fills with
it; no dialogue for 10 s)*
**Professor Astra-9:** *(whispering)* I have wanted to see that for my whole life.
I've never once kept still long enough.
**Bot:** Skipper. *(he holds out the short pencil)* You should write this one. I
will hold the book.
*Prompt:* **Draw it** *(the Skipper sketches the whale in the book; the drawing is
a pre-made line illustration revealed stroke by stroke)*
**Bot:** That is a useful note.
`reward:` Astral Starlight shell · Zero-G Winch unlocked · Book page *Starlight Nebula*.
`obj:` Story — Go home to Briar Landing. (A free trip is offered now.)

---

## 3. Ending — *The First New Page*

`end_01` *(Briar Landing at dusk; lanterns; Pounce's radio on the counter)*
**Grandmother Whiskers:** Read them to me, dear. All five. The others are listening
on Pounce's radio. Doc insisted.
*(the five notes appear one by one, each with a short host reaction)*
- **Doc Barnaby (radio):** The jug and me thank you!
- **Captain Huckleberry (radio):** Ho-ho! I've told that one six times already!
- **Sora (radio):** Gap filled. Thank you.
- **Professor Astra-9 (radio):** Still no units! Wonderful!

`end_02`
**Grandmother Whiskers:** Five useful notes. My grandmother would have liked
you, Skipper. She'd have said the book's been waiting for you.
*(she re-stitches the spine; the title lettering changes: The Book of Five Waters;
the author line gains "the Skipper & {BotName}")*
**Grandmother Whiskers:** There. Now it's yours as much as anyone's. Keep
filling it. Or don't. The lake won't mind either way.

`end_03`
**Grandmother Whiskers:** And look at you, {BotName}. A new knot.
**Bot:** Different knot. Still my favorite.
*(credits over the boat on still water at dawn; play resumes at the landing)*

---

## 4. Hosts

Greeting states: `first` (first meeting) · `day` (normal) · `weather:<state>` ·
`after_chN` (the chapter is done) · `cookout`. The game picks the most specific
true state.

### 4.1 Grandmother Whiskers
- `day`: "Welcome back, dear. The kettle's on and the coves are quiet."
- `day`: "Ah, {BotName}. Your collar's crooked. There. Better."
- `weather:rain`: "A good soaking for the lines. Come under the porch roof."
- `weather:mist`: "Mist on the lilies. That's when the shy ones come out."
- `after_ch5`: "There's my author. What did the lake tell you today?"
- **Kitchen:** "Fish in the pot, herbs on top, and patience in between."
- **Pantry:** "Herbs from the back garden. The rabbits take their share first."
- **Clue (Old Lantern):** "Under this very dock lives a fish as gold as a lamp. My
  grandmother called him Old Lantern. He comes up when there's a light on the water,
  late, and he's partial to liver dressed up nicely. I'll write the recipe down."
- **Cookout:** "Everyone's here! Sit, sit. Bring a fish if you like. Bring yourself
  regardless."
- **Old Salt nap prompt:** "You've got sleepy eyes, dear. There's a bench in the shade."

### 4.2 Doc Barnaby
- `first`: "Ahoy, Skipper! Welcome to Doc's Lonely Star Marina! What can I get your rig?"
- `day`: "Wind's off the main channel today. Read it with your whiskers, then check my gauges."
- `weather:rain`: "Rain's good for catfish and bad for my knees!"
- `after_ch2`: "Marked Pool's busy. Folks say a Skipper found it. Wonder who."
- **Clue (Spillway Monster):** "The big one? A blue cat near a hundred pounds lives
  in the calm, marked pool beyond the barrier. Heavy line, cut shad, after dark.
  That's all it takes. And luck. Mostly luck. Actually, it's mostly the heavy line."
- **Tow return (both modes):** "Back safe! That's all that matters. Coffee's free
  for towed sailors."
- **Kitchen:** "Chowder's like a good motor. Low and steady."

### 4.3 Captain Huckleberry
- `first`: see `story_c3_s1`.
- `day`: "Ho-ho! Warm your paws by the stove! I've got a story, it's short, I promise."
- `weather:snow_mist`: "Snow mist! The trout love it. My whiskers don't."
- **The Whopper story (3 different days):**
  1. "Did I tell you about the Whopper? Longest burbot in the world. It ate my boot."
  2. "The Whopper, part two: it *returned* my boot. Polished. I'm not making this up."
  3. "Last part: I saw it again on the gravel reefs, snowy night, roe on the hook.
     It winked. You'll see." *(gate complete)*
- `after_ch3`: "Used your note this morning. You saved me a very long story!"

### 4.4 Sora the Obsidian
- `first`: see `story_c4_s1`.
- `day`: "Skipper. The water is deep and calm today. What will you look for?"
- `weather:fog`: "This fog is called Marguerite. She's slow but kind."
- `weather:clear`: "Clear. You can see sixty feet down. Don't let it make you dizzy."
- `after_ch4`: "My chart has no gaps now. I keep looking at where the gap was."
- **Errand `host_crater`:** offer "Every fog here has a name. Wait in one, and tell me
  how it felt. I'll tell you what it's called." / turn-in "That one is Bartholomew.
  He's shy. He liked you."

### 4.5 Professor Astra-9
- `first`: see `story_c5_s1`.
- `day`: "Salutations! Today's currents are glowing at forty-two… purples. Is purple a unit?"
- **Bot:** "It is not."
- `weather:aurora`: "Aurora tide! Everything's biting! Including my curiosity!"
- `after_ch5`: "I've stopped surveying on Tuesdays. I've seen three new things."
- **Errand `host_nebula`:** offer "Teach me your units, Skipper. Catch five kinds of
  fish here and tell me their sizes in your 'feet'." / turn-in "Feet! Fish have no
  feet! I love it."

---

## 5. Bot barks

**[F]** needs its condition; **[U]** is the fallback. Bot speaks at most once per
20 real seconds, except for direct responses to the player.

### 5.1 Scouting (existing report, with V1.0 additions)
- [F] `fallback: report` "Depth {depth_ft} ft. {ground} ground. I would try {bait}."
  (exact depth needs the finder; otherwise use the existing depth class)
- [F] `fallback: silent` *(herbal_stew active)* "…and I think {fish1} or {fish2} live here."
- [F] *(scanner, Flathead/Crater)* "Cold water begins near {depth_ft} ft."
- [U] *(scanner, no layer)* "I cannot find a cold layer here. It may be deeper."
- [F] `fallback: report` *(Sonar Grid)* "Mapped. The bottom drops off to the {direction}."

### 5.2 Tools
- Wave Chime cast: "Chime's out. Let's see who visits!" *(always: this is the [U] form, safe)*
- Wave Chime, a surface fish later hooked on that line: [F] "A surface fish came to
  the chime. I am trying not to be smug." (`fallback: silent`)
- Reed Anchor set: "Anchor's holding in the reeds. Ribbit. I said that on purpose."
- Winch engaged: "Lines are holding steady in the current."

### 5.3 Book
- Stage-up: "Shall we add that?" *(accept)* "Added. In your handwriting. Mostly."
- First catch of a species: "New page. I have drawn a small box for it."
- Verified: "Verified. Five times the same story. That makes it true here."
- Mastered: "Mastered. {teller} will want to hear."
- Dream-clue (after a nap): "I dreamed about {folk_name}. In the dream it was near
  {zone}. I do not know if robots dream. I wrote it down anyway."

### 5.4 Catches
- Shiny: "That one is sparkling. I have marked it Treasured."
- Protected release: "This is a {fish}. They are protected here, so back it goes. The book still counts it."
- Legendary: *(silence during the scene)* then "I will remember that for the rest of my battery."
- Got away (spoilage): "A fish waited a long while and wriggled free. Good for it."
- Livewell full: "The livewell is full. I picked the smallest to swim home. You can change that."

### 5.5 Invitations and needs
- Weather invitation: [F] `fallback: silent` "The {zone} is having a good {time_band}. Shall I mark it?"
- Lake Day (morning, once): [F] `fallback: silent` "It is {day_name}. On {lake}, that means {effect_short}."
- Old Salt Drowsy: "Your blinks are getting longer, Skipper. A catnap would help."
- Old Salt Peckish: "My sensors say 'peckish'. That is a funny word. Shall we cook?"
- Cozy nap invitation (at most once per game day, only if the player hasn't
  napped): "There is a sunbeam on the deck. Just saying."

### 5.6 Shell hails (when a shell is equipped)
- Tin: "*[soft triangle chime]* Ready, Skipper."
- Frog: "*[wooden click]* Ribbit. Reed-ready."
- Duck: "*[squeak]* Squeak-boop! Surface sensors clear!"
- Sub: "*[bubbly tick]* Glub. Listening for cold water."
- Astral: "*[glass bell]* Twinkling. Is that the word?"

---

## 6. Water-cats

### 6.0 Generic fills (used when an entry omits a node)
- accept: "Wonderful. No hurry at all." / "Take your time; the lake isn't going anywhere."
- decline: "That's all right. Ask me another day."
- progress: "How's it going? Don't rush on my account."
- ready-wait: "Whenever you like. I'll be around."

### 6.1 Little Briar

**Elder Moss.** *greet:* "Peace upon your bow, Skipper. The water reflects the
clouds without holding them." · *A (existing q03).* · **B offer:** "Last time we
sat still together. This time, sleep. A nap in the cypress shade. I'll keep watch.
Badly, probably." · `obj:` Catnap in Cypress shore. · **B done:** "You slept, and the
roots grew a little. Neither of you tried." · *friend greet:* "Ah, my napping
colleague. The dragonflies asked after you."

**Pip & Pebble.** *A (existing q04).* · **B offer (Pip):** "We want our map to have
fish on it! Real ones! Can your book show ten kinds from Little Briar?" ·
`obj:` Identify 10 Little Briar species in the book. · **B done (Pebble):** "I drew a
frog in the corner. It's a friendly frog." · *friend greet:* "Skipper! Life jacket? Yes!
Good! Hi, {BotName}! Hi, frog-Bot!"

**Master Cinder.** *A (existing q05).* · **B offer:** "When I was small, I saw a fish
under the landing glowing like a lamp. Old Lantern. Nobody believes me but
Grandmother. Find him?" · `obj:` Record Old Lantern. · **B done:** "Gold. Just as
gold as I remembered. Thank you for not laughing." · *friend greet:* "The moon's
good tonight, Skipper. I'm not scared of the landing anymore. Mostly."

**Willow.** *A (existing q06).* · **Clue:** "In the misty mornings there's a pickerel
in the lilies as long as my canoe. The Lily Queen. She likes a fancy breakfast:
minnow, crawfish, herbs." · **B offer:** "Wait with me in the lily cove in the mist?
I want to paint the moment before she rises." · `obj:` Anchor in Lily cove for 30
game minutes while it's misty. · **B done:** "No queen today, and I painted the mist anyway. It's the
best one I've done." · *friend greet:* "Look, another heron. I'm going to paint it.
Don't judge me."

**Silas.** *A (existing q07).* · **B offer:** "Three birdhouses, three snags, and I've
built them all. I just can't stay awake long enough to deliver them. Would you?" ·
`obj:` Visit Cypress shore, South rocks and Creek inlet. · **B done:** "Wrens moved
in already. Fastest tenants I've ever had." · *friend greet:* "*(yawning)* Oh,
Skipper. I was just resting my eyes. For an hour."

**Marigold.** *greet:* "Hello! Don't mind me, I'm swimming. Cats can swim, you know.
Some of us adore it." · **A offer:** "Paddle alongside me across the open water?
Everyone else just stares." · `obj:` Travel 200 m in Open water. · **A done:** "See?
Perfectly normal. Here, a little thing I think about while floating." → Ripple 11 ·
**B offer:** "Confession: I hate rain on my ears. Could I shelter under your boat next
time it rains?" · `obj:` Anchor anywhere on Little Briar for 30 game minutes while it rains. · **B done:**
"Dry ears! You're a hero. Have my old swim cap. It's lucky." · *friend greet:* "Water's
lovely today! Come in! No? Fine, I'll swim by your boat."

**Old Gus.** *greet:* "Afternoon. Ferried cats across this lake forty years. Never
once lost." *(a heron croaks)* "…that's the heron agreeing." · **A offer:** "The
herons tell the hour by the rocks. Have your Bot look at the south rocks and tell me
what he sees." · `obj:` Bot scouts South rocks. · **A done:** "Herons stand there when
the shade's just so. That's three o'clock. Told you." → Ripple 12 · **B offer:** "I
heard there are loons up north. Haven't heard a loon since I was young. If you ever
go, listen for me?" · `obj:` Visit Big open water on Flathead, then tell Gus. · **B
done:** "You heard one? *(quiet)* Thank you. Take the bell; I don't ring it
anymore." · *friend greet:* "There's my loon-listener."

**Biscuit.** *greet:* "Fresh dough balls! Don't drop crumbs. Please don't drop crumbs."
· **A offer:** "New recipe. Will fish eat it? Take a dozen, put it on a line, tell me
honestly." · `obj:` Catch any fish on dough balls. · **A done:** "They ATE it?! I'm
putting it in the shop." → Ripple 13 · **B offer:** "Sunday cookout, I'm bringing
bread. Come eat some so I'm not the only one." · `obj:` Attend the Sunday cookout at
Briar Landing. · **B done:** "You came! Here, a loaf-shaped buoy. It floats better
than my real bread." · *friend greet:* "Skipper! Crumb check. …Clean. Wonderful."

### 6.2 Cedar Creek

**Captain Maeve.** *greet (recopied):* "Ahoy, Skipper! Forty years on riverboats,
and you know what I learned? Slow turns win." · **A (existing q08), recopied offer:**
"Take a long, easy run across the open water with me. Your own pace. I want to see
how you hold a line." · **B offer:** "My practice buoys are in the sheltered cove.
Follow them at your own pace, round and back." · `obj:` Pass the 4 practice buoys in
order in Clear Creek coves. · **B done:** "Lovely line! You've got whisker-sense
for open water. Have my whistle." · *friend greet:* "There's my best student. Slow
and pretty, Skipper."

**Sparky.** *A (existing q09).* · **B offer:** "Is the duck squeaking right? Ring the
chime somewhere on Cedar and tell me if the fish complain!" · `obj:` Use the Wave
Chime on Cedar Creek. · **B done:** "HA! A fish came up! HA!" *(much quieter)* "Sorry.
Have a gear." · *friend greet:* "Skipper! I built a silent winch! It's… mostly silent!"

**Quill.** *A (existing q10).* · **Clue:** "There's a verse I can't finish, about
whiskers in the deep at dusk. Some say the Guardian rises when the lake has been
kind to it." · **B offer:** "If you ever see the Guardian, tell me how it looked. Then
I'll have my last verse." · `obj:` Witness the Whiskered Guardian. · **B done:** "*Its
whiskers wrote the twilight on the water.* There. Finished. Keep this copy." ·
*friend greet:* "Skipper, I've been very quiet all morning. Three whole minutes."

**Dr. Alder.** *A (existing q11).* · **B offer:** "I'm compiling a census of Cedar. Help
me reach twenty species? I'll name the next one after you. Kidding. After my aunt
Beatrix." · `obj:` Identify 20 Cedar Creek species in the book. · **B done:** "Twenty!
Take my old notebook, every page has a fish and an aunt." · *friend greet:* "Hello,
colleague. Aunt Beatrix says hello. She's a drum."

**Patch.** *A (existing q12).* · **B offer:** "Treasure hunt! Flooded shoreline, dam
riprap, creek channels. Then come back and I'll tell you what I found." · `obj:`
Visit Flooded shoreline, Dam riprap and Creek channels, then talk to Patch. · **B
done:** "Found it! My lucky spoon! …You keep it. You were luckier for me than it ever
was." · *friend greet:* "Skipper! Found three lures and a sock today. Want the sock?"

**Hank Mudpaw.** *greet:* "Hmph. Evening." · **A offer:** "Set a good line in the creek
channels with liver and leave it an hour. Let's see if you've got the patience. I
don't, these days." · `obj:` Premium or heavy line · Chicken liver · Creek channels ·
60 active minutes, then check it. · **A done:** "Not bad. Not bad at all." *(he
sniffs)* "It's the wind." → Ripple 14 · **Clue:** "There's a gar in these channels
longer than my boat. The Leviathan. After a good rain, past ten at night. Smoke your
shad with pecan, drop in liver. Don't laugh." · **B offer:** "Catch the Leviathan. Then
nobody can tell me I dreamed it." · **B done:** "*(long pause)* I'm not crying. Take my
lantern. I won't need proof anymore." · *friend greet:* "Evening, Skipper. Look at
that sunset. *(sniff)* Wind again."

**Belle Pecan.** *greet:* "Hi, sugar! Want a pecan? I have nine hundred." · **A
offer:** "My pecan trees shade the flooded shoreline. Catch three fish under them so I
know they're useful." · `obj:` Catch 3 fish in Flooded shoreline. · **A done:** "Shade AND fish. Good trees." → Ripple 15 · **B offer:** "Sunday I'm
bringing pie to the cookout. You'll come? You won't ask for the recipe?" · `obj:`
Attend the Sunday cookout at Cedar Landing. · **B done:** "You didn't ask! You're my
favorite. Here's a charm, not the recipe." · *friend greet:* "Sugar! Pecan? Still
nine hundred."

**Señora Luz.** *greet:* "Good evening. The pool is calm and the edges are lit. Fish
here safely." · **A offer:** "Ride with me around the three lamp buoys tonight. I like
company while I check them." · `obj:` After 7 pm, pass the 3 lamp buoys around the
Marked Pool in order. · **A done:** "All three bright. The pool is happy." → Ripple
16 · **B offer:** "I sing to the big blue every night. I would love to see who I've
been singing to." · `obj:` Record the Spillway Monster. · **B done:** "*(humming)*
There you are, big one. Thank you, Skipper. Keep the old lamp glass." · *friend
greet:* "Skipper. The pool says hello. In a very deep voice."

**Kit.** *greet:* "Junior Ranger Kit! Life jacket check! …Pass!" · **A offer:** "Ranger
check: visit the flats, the coves and the landing, and say 'all clear' at each! I'm
practicing!" · `obj:` Visit Upper lake flats, Clear Creek coves and Caney Creek
landing. · **A done:** "All clear, all clear, all clear! You're a natural." → Ripple
17 · *(she tips her paddleboat in the shallows, laughing)* · **B offer:** "Last badge!
I have to teach someone a whole fishing line. Set one on the flats with worms and let
it soak an hour, then show me!" · `obj:` Standard or better line · Nightcrawlers ·
Upper lake flats · 60 active minutes, then talk to Kit. · **B done:** "I'M A RANGER!
You get my practice badge. You earned it too." · *friend greet:* "Ranger Kit
reporting! Life jacket? Good! Me? …Also good! Probably!"

### 6.3 Flathead Alpine

**Torvald.** *greet:* "Evening. I'm retired. Don't tell anyone you saw me out here."
· **A offer:** "Old Silverhead lives where the cold is. Set a line down in it in the
trench. Your little sub can find it." · `obj:` In the Glacial trench, set a line
inside the cold layer and check it. · **A done:** "Good. The cold remembers. Here's
how to make Huckleberry's mash; Silverhead likes it." → Ripple 18 · **B offer:** "Show
me Silverhead before I really retire." · **B done:** "Still there. Still silver.
Take my old depth weight; I'll fish shallower now." · *friend greet:* "Out again.
Retired again. Hello."

**Freya.** *greet:* "Shh. The light's nearly right. …No. Gone. Hello!" · **A offer:**
"Wait with me in the snowmelt inlet next time the snow mist comes. Mist makes the
best light." · `obj:` Anchor in Snowmelt inlet for 30 game minutes during snow mist. · **A done:** "Look at
that. I forgot my lens cap, and it's still the best photo I've taken." → Ripple 19
· **Clue:** "In the snow mist at dawn there's a trout so pale it looks like a ghost.
The Glacial Phantom. It likes roe and minnow with a little huckleberry." · **B
offer:** "Find the Phantom. I want one picture. Just one." · **B done:** "Got it.
And look, I got you in the frame too. Keep this one." · *friend greet:* "Hold still!
…Lens cap. Again. Hi!"

**Bramble.** *greet:* "*(shivering)* This sleeping sack is rated for very cold.
I am testing whether I am." · **A offer:** "Nap on the gravel flats and tell me if
you were cozy. Science!" · `obj:` Catnap in Gravel flats. · **A done:** "Cozy? I knew
it. It's me that's the problem." → Ripple 20 · **B offer:** "Cook something warm
and tell me about it. That's also science." · **B done:** "Data recorded: soup
works. Take a mitten. I have nine." · *friend greet:* "Hello! I'm wearing four
layers! It's going great!"

**Ingrid.** *greet:* "I carve fish. Show me fish." · **A offer:** "Bring eight
Flathead fish into your book. I carve from what you've seen, not from stories." ·
`obj:` Identify 8 Flathead species in the book. · **A done:** "Good shapes. Very
good shapes." → Ripple 21 · **B offer:** "The burbot is the hardest to carve. Show
me one." · **B done:** "Ah. It's all chin. Lovely. Here's a trout I made you." ·
*friend greet:* "Hello. That is a big talk for me."

**Elk-Ears Eli.** *greet:* "Evening, angler. Counting owls. Seven. Eight. Hello."
· **A offer:** "If you catch a bull trout, you'll see it go right back. That's the
rule here, and it's a good one. Catch one, and watch it swim off." · `obj:` Catch a
bull trout (it is always released). · **A done:** "There it goes. Letting it go is
how we keep it." → Ripple 22 · **B offer:** "Sit with me on the gravel reefs a while.
I lose count when I'm alone." · `obj:` Anchor in Gravel reefs for 2 game hours. ·
**B done:** "Fourteen owls. Best count all year. Take a feather. I found it, I didn't
take it." · *friend greet:* "*(mouth full)* Huckleberries? No. What
huckleberries."

**Bjorn.** *greet:* "My uncle's Huckleberry. Don't ask him about the Whopper.
…You asked him, didn't you." · **A offer:** "Listen to the whole Whopper story. All
three parts, on three days. I'll know if you skip." · `obj:` Talk to Captain
Huckleberry on 3 different days. · **A done:** "You heard it all. The boot part's
true, you know. I was there." → Ripple 23 · **B offer:** "Catch the Whopper. Prove
him right. Please." · **B done:** "IT'S REAL! *(composes himself)* I mean. Obviously.
Take the tin cup; he drinks from it when he tells it." · *friend greet:* "Uncle says
you're in four of his stories now."

**Willa Larch.** *greet:* "Hello-hello! The larches are going gold, it's my
favorite week, have you got a minute, I've got many." · **A offer:** "Catch three
perch for my basket supper, they're the color of larch!" · `obj:` Catch 3 yellow
perch. · **A done:** "Gold fish for a gold week!" → Ripple 24 · **B offer:** "Come to
the outpost supper on Sunday! I'll weave you something while we talk!" · **B done:**
"There! A needle basket, I made it while you ate, I'm slow but I'm chatty." ·
*friend greet:* "Hello-hello! Guess how many baskets. More."

**Dakota.** *greet:* "Howdy. Mighty fine wind. Tied my hat down twice." · **A
offer:** "Ride the big open water with me. Let the wind do the work." · `obj:`
Travel 400 m in Big open water. · **A done:** "Yeehaw. Quietly." → Ripple 25 · **B
offer:** "Four kinds of trout. That's a proper trail." · `obj:` Catch 4 different
trout species. · **B done:** "Now that's a trail. Wear this pennant on your boat." ·
*friend greet:* "Howdy, partner. Wind says hi."

**Mitzi.** *greet:* "*(three sweaters)* I study glaciers. I'm fine. I'm toasty."
· **A offer:** "Can your Bot measure the cold layer here? I want my map to match the
water." · `obj:` Use the Thermocline Scanner on Flathead. · **A done:** "There's the
floor you can't see. Perfect." → Ripple 26 · **B offer:** "Sora says the caldera has
a cold layer too. Same physics, different lake. Measure it?" · `obj:` Use the
Thermocline Scanner on Crater Caldera. · **B done:** "Two lakes, one law. Here's my
rock hammer; I have a spare in sweater two." · *friend greet:* "Fourth sweater
today. It's for science."

### 6.4 Crater Caldera

**Nyx.** *greet:* "Welcome to the bathhouse. Do not splash. I'm only half joking." ·
**A offer:** "Set a line near the warm springs with ember grubs. If the fish come,
the guests will too." · `obj:` Line with ember grubs in Thermal springs, 60 active
minutes, then check it. · **A done:** "Warm water, happy fish. I'll put the lanterns
up again." → Ripple 27 · **Clue:** "Some nights in the fog, something big and
glowing walks the spring bottom. Not a fish. Mist wrote a poem about it. Ask her
first, then bring dumplings." · **B offer:** "Find the old bather. I want to know
it's well." · **B done:** "A salamander! Of course. Take a token; it can bathe for
free." · *friend greet:* "Skipper. Come in. Carefully."

**Ignis.** *greet:* "HELLO! Have you seen the cinder isle?! The shore is GLASS!" ·
**A offer:** "Send your Bot along the obsidian cliffs! Tell me what he sees!" ·
`obj:` Bot scouts Obsidian cliffs. · **A done:** "SEE?! Glass!" → Ripple 28 ·
**Clue:** *(whispering)* "There's a gar by the isle as black as the shore. Late
afternoon, clear sky. Mineral shad. Shh." · **B offer:** *(whisper)* "Catch it. Then
tell me loudly." · **B done:** "IT'S SO SHINY!! Take a bead from the shore." ·
*friend greet:* "SKIPPER! *(whisper)* Hi."

**Ashby.** *greet:* "Cocoa? It's better on foggy mornings. I hate foggy mornings." ·
**A offer:** "Wait with me in the next fog on the pumice shelf. I'll make two cups."
· `obj:` Anchor on Pumice shelf for 30 game minutes during fog. · **A done:** "*(sip)* Perfect. Don't tell
the fog." → Ripple 29 · **B offer:** "Sora makes a mineral broth. Cook it? I want to
try a savory cup." · **B done:** "Savory cocoa. I've made a terrible mistake and I
love it. Take the mug." · *friend greet:* "Two cups ready. Fog or no fog."

**Basalt Bea.** *greet:* "Hold this rock. No, this one. Where did I put the other
one?" · **A offer:** "Pumice floats! Want to see where it washes up? Shelf, cliffs,
drowned pines!" · `obj:` Visit Pumice shelf, Obsidian cliffs and Drowned pines. · **A
done:** "Floating stone. Still amazes me." → Ripple 30 · **B offer:** "I want a rock
from every lake. Go look at the rocky spots on Briar, Cedar and Flathead for me?" ·
**B done:** "You remembered all of them! I won't. Keep this pocket stone." · *friend
greet:* "I found a rock. It was in my pocket. Was it yours?"

**Fumi.** *greet:* "Good evening. Welcome. *(sneeze)* Ha! Excuse me." · **A offer:**
"Sit with me in the moss gardens while I light the lanterns. It takes a while.
That is the point." · `obj:` Anchor in Moss gardens for 2 game hours. · **A done:**
"All lit. One for you." → Ripple 31 · **B offer:** "I make a lantern for each
friend. Catch three kinds of night fish here, so I know your colors." · **B done:**
"Your lantern. It suits you. *(sneeze)* Ha!" · *friend greet:* "Your lantern is
still lit. I checked."

**Ember.** *greet:* "I'm the lookout. Official. My dad says I'm *a* lookout, but
I'm *the* lookout." · **A offer:** "Do a lookout loop across the open caldera! Report
anything big!" · `obj:` Travel 500 m in Caldera open. · **A done:** "Report:
everything is big. Good job." → Ripple 32 · **B offer:** "Is the fog marker fixed?
Sora won't tell me. Fix it and tell me!" · `obj:` Finish chapter 4, then talk to
Ember. · **B done:** "ALL CLEAR! Take my binoculars, I have, um, a spare pair. My
eyes." · *friend greet:* "Lookout Ember! You're cleared to fish."

**Mist.** *greet:* "*(whisper)* hello… *(enormous sneeze)* …sorry." · **A offer:**
"*(whisper)* My poem is about the fog. Wait in it with me, among the drowned pines.
Then I'll read it." · `obj:` Anchor in Drowned pines for 30 game minutes during fog, then talk to Mist. · **A
done (poem):** "*Something warm walks under the cold, / carrying a lamp it was
never told about. / I hear it more than see it, / and I don't mind.*" → Ripple 33
(unlocks the Fire-Lizard gate) · **B offer:** "There's a minnow that hides in fog
too. Hide-away. Find one for me?" · **B done:** "*(whisper)* there it is. Take the
poem; I know it by heart." · *friend greet:* "*(whisper)* hello again."

**Juno.** *greet:* "*(yawning)* Is it night yet? I'm an astronomer. I keep missing
it." · **A offer:** "On a clear day the water's so still it shows the sky. Wait in it
with me?" · `obj:` Anchor in Caldera open for 30 game minutes while it's clear. · **A done:** "See? The sky
lies down on the water. I *knew* it." → Ripple 34 · **B offer (after ch. 5):** "You
went IN the reflection? Come tell me everything." · **B done:** "I told everyone. I
TOLD them. Take my chart, you'll use it more than me." · *friend greet:* "I stayed
up for the stars! …Fell asleep at eight."

**Tamsin.** *greet:* "Mind your wake near the shore, please. Clear water is
everyone's." *(her paws are muddy)* · **A offer:** "If you catch a Lahontan, it goes
right back, and you'll see why. They're rare here. Catch one and let it go." ·
`obj:` Catch a Lahontan cutthroat (it is always released). · **A done:** "Back
home it goes. Clear water is a lot of small kindnesses." → Ripple 35 · **B offer:**
"Help me count what lives here. Fifteen kinds in your book." · **B done:** "Fifteen.
The water's in good paws. Wear this pin." · *friend greet:* "Hello! Ignore the paws."

### 6.5 Starlight Nebula

**Orion-Cat.** *greet:* "Good evening, fellow engineer. Your deckhand has an
excellent chassis." · **A offer:** "Set a line in the astral current and check it
after an hour. Watch how far it drifts. Data!" · `obj:` Line in Astral current, 60
active minutes, then check it. · **A done:** "Drifted. Of course. But you tied it
well." → Ripple 36 · **B offer:** "When you've a winch, hold a line in the current.
I want to see the knot hold." · `obj:` Use the Zero-G Winch. · **B done:** "Old
knot, new winch. Perfect. Take my star-knot." · *friend greet:* "Colleague! And
colleague's Skipper!"

**Nebula-Paws.** *greet:* "Oh! An audience. *(drops a chime)* Hello." · **A offer:**
"Sit with me in the current while I practice? Two hours. I'm less nervous with a
friend." · `obj:` Anchor in Astral current for 2 game hours. · **A done:** "I played
the whole thing! Here, the Weaver's favorite bait. Moon-milk on stardust." → Ripple
37 · **Clue:** "On aurora nights the Weaver ribbons through the current. I've never
seen it dance to my chimes. Maybe it would, for you." · **B offer:** "Find the
Weaver while I play?" · **B done:** "It DANCED. Take a chime. Play it badly; it
likes that." · *friend greet:* "*(confidently)* Hello! *(drops chime)*"

**Comet.** *greet:* "ZOOM! Hi! Bye! Hi!" · **A offer:** "Race me up the comet stream!
Well, travel. Travel me!" · `obj:` Travel 400 m in Comet stream. · **A done:** "You
WIN. Or I won. Everyone wins!" → Ripple 38 · **B offer:** "Nap with me by the
stream. I nap the hardest." · **B done:** "*(waking)* …I won the nap. Take a ribbon."
· *friend greet:* "Zoom! (I'm sleepy.)"

**Lyra.** *greet:* "Harp music! Do you like harps? You're wrong, you do." · **A
offer:** "Catch a fish in the light-reeds. Where there are fish, there are good reeds
for strings." · `obj:` Catch any fish in Light-reeds. · **A done:** "Perfect reed. Hear
it hum?" → Ripple 39 · **B offer:** "Station supper on Sunday. I'll play. You'll
listen and pretend you hate it." · **B done:** "You tapped your paw. I SAW it.
Take a string." · *friend greet:* "Admit it. You hum my songs."

**Vega.** *greet:* "I chart the Lagoon. Don't look down; I get dizzy." · **A offer:**
"Help me find the edges: the open, the deep, the current and the reeds." · `obj:`
Visit Nebula open, Void well, Astral current and Light-reeds. · **A done:** "No edge.
It just goes on, gently. I like that." → Ripple 40 · **B offer:** "Ten kinds of fish
for my chart's border, please. It's a decorative border." · **B done:** "Gorgeous
border. Take my compass; it points to friends, which is you." · *friend greet:*
"Hello. Don't look down. I'm fine. I'm looking up."

**Selene.** *greet:* "My moon garden! It's… well, it's mostly moon." · **A offer:**
"Cook Astra-9's moon pudding? I'll grow something from the spoon." · `obj:` Cook
Moon-Milk Pudding. · **A done:** "A sprout! An actual sprout!" → Ripple 41 · **B
offer:** "A sun fish and a moon fish, for the garden's two halves." · `obj:` Catch a
solar sunfish and a lunar loach. · **B done:** "Day and night, both in bloom. Take a
moon-flower." · *friend greet:* "Two sprouts now! A record!"

**Andi.** *greet:* "Are you from the lakes below? Is it true there are FROGS?" · **A
offer:** "Catch a fish in a lily cove down there and tell me about it. Especially
the frogs." · `obj:` Catch any fish in Lily cove on Little Briar, then talk to Andi.
· **A done:** "They SING? Frogs SING?" → Ripple 42 · **B offer:** "Can your Bot be a
frog? Can it frog in the light-reeds? Please?" · `obj:` Wearing the Frog shell, set
the Reed Anchor in Light-reeds. · **B done:** "RIBBIT! I drew you a picture." ·
*friend greet:* "Frog report, please!"

**Twinkle.** *greet:* "These are my lanternfish. One, two, three… lots." · **A
offer:** "Help me count? Catch three and I'll count them twice." · `obj:` Catch 3
purrsec lanternfish. · **A done:** "Three! Then three more is six! Then it's lots
again." → Ripple 43 · **B offer:** "There's a goby that sits right at the edge of the
deep. I've never reached it. Could you?" · **B done:** "The Edge-Sitter! Take my
crook. I'll herd with my paws." · *friend greet:* "Lots and lots of lanternfish
today!"

**Rigel.** *greet:* "Fastest sail in the sky. Hello. I'd like to stop being that." ·
**A offer:** "Sail the astral current with me, slowly. Teach me." · `obj:` Travel 300 m
in Astral current. · **A done:** "I saw a star I've passed a thousand times. Today
it waved." → Ripple 44 · **B offer:** "One last fast thing: the Supernova salmon. It
only bites for the patient. Funny, right?" · **B done:** "Patient AND fast. Take a
sail patch." · *friend greet:* "Hello, slowly."

---

## 7. New Ripples (34)

| id | Text |
| --- | --- |
| ripple_11 | Water holds up those who stop fighting it. |
| ripple_12 | The birds know the hour without a clock. |
| ripple_13 | Small things, done warmly, feed many. |
| ripple_14 | A tired line still holds if it was tied well. |
| ripple_15 | Shade is a gift you never see being given. |
| ripple_16 | A light doesn't pull you in; it shows you the way. |
| ripple_17 | Ready is a kind of calm. |
| ripple_18 | Deep water keeps old promises. |
| ripple_19 | Fog doesn't hide things; it frames them. |
| ripple_20 | Rest is part of the trip, not a stop in it. |
| ripple_21 | Look until the shape tells you. |
| ripple_22 | Letting go is also how you keep. |
| ripple_23 | A tall tale is a true feeling in a big coat. |
| ripple_24 | Gold comes and goes; notice it while it's here. |
| ripple_25 | The wind is a horse nobody owns. |
| ripple_26 | Water has floors you cannot see. |
| ripple_27 | Warmth rises; let it. |
| ripple_28 | Hard edges were once soft fire. |
| ripple_29 | Some sweetness only arrives with grey. |
| ripple_30 | Even stone can float, if it's full of air. |
| ripple_31 | A small light makes the dark friendly. |
| ripple_32 | Big things are made of small loops. |
| ripple_33 | What you can't see, you can still listen to. |
| ripple_34 | The sky lies down on still water. |
| ripple_35 | Clear water is many small kindnesses. |
| ripple_36 | Let the current carry; you still choose the knot. |
| ripple_37 | Music is patience you can hear. |
| ripple_38 | Even comets come back around. |
| ripple_39 | A thin line can hold a whole song. |
| ripple_40 | Not every edge is an end. |
| ripple_41 | Everything grows toward a little light. |
| ripple_42 | Home is wherever someone asks about it. |
| ripple_43 | You don't have to count what you love. |
| ripple_44 | Fast is how you arrive; slow is how you see. |

---

## 8. Book rumors — *What we heard*

One per species. Each one gives an actionable lead (zone, bait or time) wrapped in
folklore. The teller is shown as "— Name".

### 8.1 Little Briar and Cedar (existing 36 + 6)

| id | Rumor | Teller |
| --- | --- | --- |
| bluegill | "Sunnies follow worms like kittens follow string. Try the flats by day." | Pip & Pebble |
| bullhead | "Mud Kittens come out at dusk in skinny water. Worms, always worms." | Silas |
| crappie | "Papermouths hide in the lilies at dawn and gossip about minnows." | Willow |
| carp | "A Golden Bucket will drag your jug clear across the warm flats." | Biscuit |
| drum | "Put your ear to the hull over deep mud. That grunting is a Grunter." | Old Gus |
| channel | "The Wage pays the rent: liver, cypress shore, after dark." | Grandmother Whiskers |
| blue | "Old Blue sleeps in the deepest hole and wakes for cut shad at night." | Master Cinder |
| flathead | "The Yellow Cat wants its supper alive. Minnows on the rocks at night." | Master Cinder |
| largemouth | "Bucketmouth could swallow a sunrise. Minnows in the lilies at dawn." | Willow |
| smallmouth | "Bronzeback lives on the south rocks and loves a crawfish." | Old Gus |
| gar | "Needle-Nose sunbathes in the cypress, then hunts cut bait after sunset." | Elder Moss |
| buffalo | "The Drifter wanders the deep, bumping into worms by accident." | Old Gus |
| white_crappie | "Silver Paper is the creek channel's papermouth. Minnows by the brush." | Dr. Alder |
| redear | "Shellcrackers crunch snails on firm ground. Worms do nicely." | Biscuit |
| green_sunfish | "The Green Grump guards the rocks like it owns them." | Pip & Pebble |
| warmouth | "Goggle-Eye peeks out of brushy coves at dusk." | Master Cinder |
| redbreast | "Copper Belly waits at creek mouths with its long ear flap out." | Silas |
| longear | "Painted Ear is the prettiest fish in the clear shallows. Worms." | Willow |
| spotted_bass | "Spot hunts where the creek channel drops off. Minnow or craw." | Sparky |
| white_bass | "Sand Bass school where the channel meets open water at dawn." | Captain Maeve |
| yellow_bass | "Stripey hangs over underwater humps. Small minnows by day." | Dr. Alder |
| hybrid_striper | "The Wiper pulls like a motor. Shad over deep humps at dawn." | Doc Barnaby |
| striped_bass | "A Rockfish was stocked here once, and it never left. Deep, open water, cut shad." | Grandmother Whiskers |
| bowfin | "Grinnel is older than the lake, they say. Warm weedy backwater, cut bait, night." | Elder Moss |
| spotted_gar | "Spotted Stick waits beside flooded timber at dusk." | Patch |
| shortnose_gar | "Stubby Snout noses around muddy creek mouths at dusk." | Patch |
| alligator_gar | "Gator is the heavyweight. Cut shad in the creek channels. Bring a big well." | Hank Mudpaw |
| black_bullhead | "Inky is a little cat of quiet mud. Liver after dark." | Señora Luz |
| brown_bullhead | "Horned Pout hides by the flooded brush on Briar. Liver at night." | Master Cinder |
| blue_sucker | "The Blue Racer visits the deep gravel on Briar, but only rarely." | Old Gus |
| bigmouth_buffalo | "Gourdhead drifts over deep mud and sometimes takes a worm." | Dr. Alder |
| black_buffalo | "The Shadow Drifter keeps to Briar's deep shelf. Worms or cut bait." | Silas |
| golden_shiner | "Gold Flash darts in the weeds and the Reed Passage. Tiny worm bites." | Pip & Pebble |
| gizzard_shad | "Hickory schools roll over open water. Rarely, one bites a worm." | Captain Maeve |
| threadfin_shad | "Thread is so small the hook laughs. Warm open water, if you must." | Quill |
| chain_pickerel | "Jack is toothy and lives in Briar's lilies. Live minnows." | Willow |
| inland_silverside | "Glass Sliver is see-through and shy of nothing. Open water, worms." | Kit |
| bluntnose_minnow | "Button-Nose crowds the creek channels. Worms or dough." | Belle Pecan |
| river_carpsucker | "The Silver Vacuum cleans the creek bottom. Dough balls work." | Hank Mudpaw |
| orangespotted_sunfish | "Ember-Dot glows in the flooded shoreline. Worms by day." | Belle Pecan |
| bigscale_logperch | "Log-Roller flips pebbles on the dam riprap. Worms." | Patch |
| bullhead_minnow | "Little Boss rules the channels at dusk. Worms." | Kit |

### 8.2 Flathead Alpine

| id | Rumor | Teller |
| --- | --- | --- |
| lake_trout | "The Deep Mackinaw follows the cold down and down. Minnows at dawn." | Torvald |
| bull_trout | "Old Bull comes up the inlets at dawn. If you meet one, let it go home." | Elk-Ears Eli |
| westslope_cutthroat | "Red-Throat loves the inlet riffles. Worms by day." | Dakota |
| rainbow_trout | "Sky-Side rises in the inlets and pondweed bay. Dough works too." | Freya |
| brook_trout | "Speckle is shy and lives in the snowmelt inlet. A quiet boat helps." | Bramble |
| brown_trout | "Butter-Belly lurks by the larch snags at dusk. Minnow or craw." | Ingrid |
| kokanee | "Silver Bullets school out deep at dawn. Roe, always roe." | Torvald |
| lake_whitefish | "Snow-Belly grazes the trench bottom. Worms or roe." | Mitzi |
| mountain_whitefish | "Pebble-Nose sniffs the inlet stones by day." | Bjorn |
| pygmy_whitefish | "Thimble lives so deep it's practically a rumor. Night, worms." | Mitzi |
| northern_pike | "The Water Wolf waits in the pondweed with its teeth out." | Dakota |
| yellow_perch | "Tiger-Stripes crowd the pondweed bay and the outpost dock." | Willa Larch |
| burbot | "The Eelpout comes up at night on the gravel reefs. It's all chin." | Captain Huckleberry |
| largescale_sucker | "Rubber-Lip vacuums the inlet. Dough balls." | Bjorn |
| longnose_sucker | "Snoot keeps to the cold reefs." | Ingrid |
| peamouth | "Pea-Pods dimple the bay at dusk." | Freya |
| northern_pikeminnow | "The Big-Mouth Minnow is no minnow at all. Gravel reefs, dusk." | Dakota |
| redside_shiner | "Sunset Flicker flashes pink over the flats." | Willa Larch |
| slimy_sculpin | "Puddle-Puss hides under reef stones on cold nights." | Elk-Ears Eli |
| mottled_sculpin | "Patchwork sits so still you'd think it was a pebble." | Bramble |
| lake_chub | "Button pops up anywhere shallow. Dough." | Bjorn |
| pumpkinseed | "Penny-Cheek suns itself by the outpost dock." | Willa Larch |
| cisco | "Lake Herring flash in the open water at dawn." | Torvald |
| arctic_grayling | "Sail-Fin only shows itself to quiet boats in the inlet." | Freya |
| golden_trout | "Sunbeam lives in the snowmelt shallows. Shy as morning." | Freya |
| tiger_trout | "Marble-Back prowls the reefs at dusk. Minnows." | Ingrid |
| splake | "Twice-Char can't decide what it is, but it likes deep reefs at dawn." | Mitzi |
| longnose_dace | "Riffle-Nose noses the inlet stones. Worms." | Bramble |
| mountain_sucker | "Cobble-Kiss kisses every stone in the inlet." | Bjorn |
| white_sturgeon | "The Old Plates is older than the outpost. Deep, at night. Let it go." | Captain Huckleberry |
| walleye | "Glass-Eye sees in the dark. Reefs at dusk, minnows." | Dakota |
| sauger | "Sand-Eye follows the cold into the trench at night." | Mitzi |
| shorthead_redhorse | "Rusty Tail flicks red in the inlet. Worms or craw." | Willa Larch |
| fathead_minnow | "Pudge is everyone's snack. Dough by the dock." | Bramble |

### 8.3 Crater Caldera

| id | Rumor | Teller |
| --- | --- | --- |
| redband_trout | "Ember-Stripe warms itself by the springs. Worms or grubs." | Nyx |
| coastal_cutthroat | "Rain-Throat hides among the drowned pines at dawn. Quiet boats." | Mist |
| lahontan_cutthroat | "The Desert King is rare and royal. Deep at dawn. Let it go." | Tamsin |
| chinook | "King's Supper roams the cobalt deep at dawn. Roe." | Juno |
| coho | "Silver-Side flashes in the open caldera at dawn." | Ember |
| tui_chub | "Button-Belly loafs on the pumice shelf." | Ashby |
| speckled_dace | "Freckle dances in the warm spring shallows." | Nyx |
| oregon_chub | "Moss Pip hides in the moss gardens. Shy, worms." | Fumi |
| klamath_smallscale_sucker | "Soft-Mouth grazes the shelf and the deep. Dough." | Basalt Bea |
| blue_chub | "Bluebell rings near the surface in the moss gardens." | Fumi |
| prickly_sculpin | "Pincushion bristles under the cliffs at night." | Ignis |
| umpqua_pikeminnow | "River Wolf hunts the drowned pines at dusk." | Mist |
| chiselmouth | "Scraper scrapes the cliff stones by day." | Basalt Bea |
| alvord_chub | "Dust Pip lives only in the warmest springs. Grubs." | Nyx |
| cobalt_cisco | "The Blue Ghost lives where the water is bluest. Deep, dawn." | Sora |
| obsidian_darter | "Glass Bead darts along the obsidian. Grubs." | Ignis |
| ember_char | "Coal-Belly glows a little at dusk near the springs." | Nyx |
| ash_minnow | "Smudge is grey as ash and everywhere on the shelf." | Ember |
| cinder_sculpin | "Hot-Rock sits on warm stones at night." | Ignis |
| pumice_skipper | "Bobber-Fish floats like pumice. Dough at the surface." | Basalt Bea |
| fumarole_perch | "Steam-Stripe loves the springs by day." | Ashby |
| sulfur_shiner | "Yellow Spark flickers in the spring water." | Fumi |
| basalt_bass | "Black Brick guards the cliffs at dawn. Crawfish." | Ignis |
| glasswing_trout | "Window-Fin is see-through on clear days in the open." | Juno |
| mistfin_dace | "Fog-Flicker only comes out when the fog does." | Mist |
| lava_belly_sunfish | "Hot Penny glows orange in the spring shallows." | Ashby |
| geyser_goby | "Hiccup hops near the springs at night." | Ember |
| moonpool_whitefish | "Night-Lamp rises in the deep after dark." | Juno |
| snagtooth_pike | "Old Crook-Jaw waits in the drowned pines at dusk." | Mist |
| fog_mudminnow | "Hide-Away hides even better in fog." | Mist |
| indigo_eelpout | "Velvet Rope lives deeper than the light goes. Night, cut shad." | Sora |
| steam_carp | "Kettle-Lips blows bubbles in the springs. Dough." | Ashby |
| rimrock_bullhead | "Pebble-Whisker pokes around the cliffs at night. Liver." | Tamsin |
| vent_catfish | "Warm-Whiskers naps by the deep springs and wakes at night for liver." | Nyx |

### 8.4 Starlight Nebula

| id | Rumor | Teller |
| --- | --- | --- |
| comet_minnow | "Tail-Lights zip up the comet stream. Star-dust." | Comet |
| meteor_bass | "Rock-Drop crashes into the meteor reefs at rising." | Vega |
| quasar_koi | "Lantern Koi glow in the lily drifts. Dough or star-dust." | Selene |
| pulsar_perch | "Blinkers blink in the deep phase. Count the blinks." | Twinkle |
| lunar_loach | "Moon-Noodle wiggles through the light-reeds at night." | Andi |
| solar_sunfish | "Little Sun warms the lily drifts in the bright phase." | Selene |
| starling_shiner | "Twinkle-Fry flock in the light-reeds at fading." | Lyra |
| galaxy_gar | "Swirl-Snout spirals in the current at fading." | Rigel |
| aurora_trout | "Ribbon-Light shimmers in the comet stream at rising. Roe." | Nebula-Paws |
| cosmic_carp | "Big Bubble blows bubbles shaped like planets." | Comet |
| void_eel | "Long Shadow lives in the void well. Liver, deep phase." | Orion-Cat |
| orbit_bluegill | "Ring-Gills circle the station dock." | Andi |
| gravity_drum | "Thumpers thump in the deep. You feel it in the hull." | Orion-Cat |
| photon_tetra | "Sparks light up the reeds at night." | Lyra |
| nova_pike | "Flare-Jaw flares in the crystal kelp at fading." | Vega |
| dwarf_star_darter | "Speck is tiny, bright and lives on the meteor reefs." | Twinkle |
| saturnfin_puffer | "Ring-Ball floats in the current with its fins like rings." | Rigel |
| celestial_catfish | "Star-Whiskers prowls the void well at night. Liver." | Professor Astra-9 |
| moonbeam_crappie | "Paper-Moon hides in the crystal kelp at rising." | Selene |
| twinkle_shad | "Glitter-Fry schools in the current. Star-dust." | Comet |
| eclipse_bowfin | "Half-Moon lurks in the reeds at night." | Andi |
| stardust_bullhead | "Sprinkle-Cat noses the shoals at night. Liver or worms." | Twinkle |
| asteroid_sucker | "Pock-Lip grazes the meteor reefs." | Vega |
| halo_whitefish | "Ring-Light rises in the open at rising. Roe." | Nebula-Paws |
| constellation_char | "Dot-to-Dot follows the current at fading. Connect its spots." | Rigel |
| milky_way_buffalo | "Cream-Back drifts over the shoals." | Selene |
| supernova_salmon | "Burst only bites for the patient, in the current at rising." | Rigel |
| event_horizon_goby | "The Edge-Sitter sits at the very bottom of the void well." | Twinkle |
| zodiac_zander | "Twelve-Stripe has a stripe for every month. Reefs at fading." | Vega |
| plasma_pickerel | "Zap-Jaw zaps in the reeds at rising. Minnows." | Lyra |
| ion_icefish | "Clear-Cat is invisible except at night, deep in the current." | Orion-Cat |
| prism_ray | "Rainbow Kite glides over the shoals on bright days." | Andi |
| comet_tail_betta | "Silk-Tail flutters at the surface of the lily drifts." | Lyra |
| purrsec_lanternfish | "Purr-Lights purr. You can hear them if you're quiet." | Twinkle |

### 8.5 Legendary pages

| id | Story |
| --- | --- |
| old_lantern | "As gold as a lamp, and older than the landing. My grandmother said he guards the dock at night." — Grandmother Whiskers |
| lily_queen | "Long as my canoe, and she rises only for misty dawns and a fancy breakfast." — Willow |
| spillway_monster | "Near a hundred pounds of blue cat in the calm, marked pool. Heavy line, cut shad, after dark." — Doc Barnaby |
| channel_leviathan | "Longer than my boat. After rain, deep night, pecan-smoked shad. I'm not making it up." — Hank Mudpaw |
| whiskered_guardian | "Its whiskers write the twilight on the water. It comes when the lake has been treated kindly." — Quill |
| glacial_phantom | "A trout so pale it looks like snow mist. Dawn in the inlet." — Freya |
| old_silverhead | "Older than my boat and my boat's boat. Lives where the cold is." — Torvald |
| huckleberrys_whopper | "It ate my boot and gave it back polished. Snowy night, gravel reefs, roe." — Captain Huckleberry |
| obsidian_gar | "As black as the cinder shore and twice as shiny." — Ignis |
| caldera_fire_lizard | "Not a fish at all. Something warm walks under the cold." — Nyx & Mist |
| nebula_weaver | "It ribbons through the current on aurora nights and leaves light behind." — Nebula-Paws |
| star_whale | "A whale made of light. It comes to whoever stops looking for it." — Professor Astra-9 |

---

## 9. Pounce's letters (samples; one per friend, sent after quest B)

- **From Elder Moss:** "Dear Skipper, the dragonflies are back. My tail says hello.
  — Moss"
- **From Hank Mudpaw:** "Skipper. Saw a good sunset. Thought of you. Wind's fine. — H."
- **From Captain Huckleberry:** "SKIPPER! New story. It's long. Come hear it. — Huck"
  *(+ hint: a Flathead Lake Day)*
- **From Andi:** "I drew 40 frogs. Are they right? (They have stars on, for fun.) — A"
- **From Señora Luz:** "The big one sang back last night. Truly. — Luz"
- Template: `"Dear Skipper, {small_news}. {hint_optional} — {signature}"`. One per
  friend, 3 variants each, at most one letter per game day.

---

## 10. System copy

- **New Game → mode:** "**Cozy** — no hunger, no tiredness, nothing to lose. Naps and
  meals are treats. *(recommended)*" / "**Old Salt** — light daily routine: rest and
  eat to keep your best pace. You can never be stranded."
- **Travel captions:** Briar→Cedar "The jon boat rides the trailer down the county
  road." · Cedar→Flathead "Doc's trailer rattles north toward the mountains." ·
  Flathead→Crater "Huckleberry knows a cat with a truck." · →Nebula "The reflection
  deepens, and the boat tips gently into starlight." · Nebula→anywhere "You sail down
  the reflection and onto ordinary water."
- **Got away:** "A fish waited a long while and wriggled free."
- **Tow (Cozy):** "Doc's tow barge brings you home. No charge for friends."
- **Tow (Old Salt):** "Tow fee: {fee}. Doc waived the rest."
- **Book titles:** *Fishypedia* → *The Book of Five Waters* → *Pescapedia*.
- **Pescapedia ceremony (Grandmother):** "Every fish, verified and still full of
  stories. That's a Pescapedia, dear. My grandmother never finished hers. You did."
