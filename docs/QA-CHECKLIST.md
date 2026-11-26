# Manual QA checklist

Use a **disposable save** for every pass: launch with `--save <scratch>` (for example, a temporary path outside the repository). Never point QA at the normal save. This checklist describes intended play, not implementation internals; leave unclear or unavailable features unmarked and note what build was used.

## Smoke pass (about 60–90 minutes; non-starter boat access may add time)

### Clean start, title, prologue
- [ ] **Precondition:** disposable save path does not exist. Launch a new game. **Expect:** title/start flow is legible; Cozy is the default, and the prologue introduces the Skipper, Bot, and starter jon boat without requiring prior knowledge.
- [ ] Choose Cozy and begin; follow the opening guidance. **Expect:** reach a fishable spot and set a line promptly; the experience is calm, with no fail state or hurry.
- [ ] If start-over is offered, inspect the confirmation and cancel with Escape. **Expect:** cancellation leaves the current scratch progress intact.

### Boat controls, set / soak / haul / sell
- [ ] Set a line with **F**, choose bait/tier if offered, and observe it on the chart/HUD. **Expect:** line shows its state; bait and hook information are understandable.
- [ ] **W/S** changes throttle, **A/D** steers, **Shift** returns to idle, **Space** anchors; try brief taps and held inputs. **Expect:** controls respond, idle/coast is clear, and anchoring is safe.
- [ ] Let a line soak with no bite, then check with **E**. **Expect:** empty/bait states are understandable; no penalty for an empty haul. Try rebaiting and pulling the line.
- [ ] Haul a line with a catch. **Expect:** hook-by-hook progress and catch details are readable; resolve catches by keeping or releasing; book credit is retained either way.
- [ ] At a landing, sell ordinary fish and inspect the result. **Expect:** money updates clearly; no unexpected loss of protected/Treasured fish.
- [ ] **Boundary:** fill the livewell, then haul another eligible catch. **Expect:** any required release is explicitly indicated; nothing is silently discarded.
- [ ] **Boundary:** leave a fish hooked beyond the 13-game-hour spoilage window. **Expect:** it is described as having gotten away; no other possession is lost.
- [ ] **Boundary:** leave lines soaking while the game is closed for a short interval, well under the offline cap (72 real hours in Cozy, 36 in Old Salt, by the save's mode). **Expect:** on return the lines fished for the whole interval; a fish hooked more than 13 game hours before your return has gotten away under the normal hook rule, not because of the cap.

### Menus, book, quests, NPCs
- [ ] Open chart (**Tab**), journal (**J**), livewell (**I**), help (**H**) and pause (**Esc**); navigate with **W/S**, tabs/pages with **A/D**, Enter/Space to select, Escape to close. **Expect:** world time pauses in menus and controls are explained.
- [ ] Browse Fish, Book, Ripples & Keepsakes, Story, Watch and Week pages. **Expect:** unknown fish retain rumor/silhouette presentation; recorded catches add found information; long notes can be turned through.
- [ ] Review an available quest and hail a nearby NPC with **C** when slow and within range. **Expect:** offers/objectives and progress are understandable; declining does not permanently remove an offer; showing a fish does not consume it.
- [ ] Return to a needed NPC or host after completing an objective. **Expect:** sensible turn-in is available and rewards are not duplicated.

### Kitchen and food
- [ ] At a landing, open shop with **E**, choose Kitchen; inspect pantry with **K**. **Expect:** ingredients, prices, quantities and available dishes are clear.
- [ ] If eligible ingredients/fish are available, begin cooking, inspect confirmation, choose another eligible fish with Up/Down, then cancel once and confirm once. **Expect:** cancel spends nothing; confirmation previews ingredients/fish; cooking is a gentle skippable scene and does not consume protected, shiny, legendary or Treasured fish.
- [ ] Eat a Kibble Tin if available. **Expect:** it is a snack, not a replacement for an active picnic buff.

### Lake travel, boats, weather, time
- [ ] At a landing, inspect Boats and Lakes tabs; if funds/availability permit, switch boats and visit Cedar. First pull deployed lines before travel. **Expect:** travel is understandable; owned gear, records and catches persist; active boat/fuel differences are clear.
- [ ] Try **T** while anchored or idling; observe the lake clock/weather, then open a menu. **Expect:** time scale cycles as described; world time pauses in menus.
- [ ] Try a short drive near shore/dock, then approach landing. **Expect:** boundaries/collisions are readable and do not trap the boat.
- [ ] If using daysailer/rowboat, verify sail or oars work as applicable; empty fuel/battery should not make travel impossible where the documented alternative propulsion applies.

### Cats, narrative, legendary stories
- [ ] Meet Bot and a host/neighbor; use **B** to send/recall Bot and **C** to hail a nearby cat. **Expect:** Bot reports useful scouting information and returns; dialogue and journal notes persist.
- [ ] Review chapter objectives, Watch cards and any legendary rumors available in this save. **Expect:** clues and current requirements are distinguishable; do not assume a gated encounter is ready merely from seeing its story.
- [ ] With a valid legendary catch on a line, check its first haul and a repeat. **Expect:** a calm 4–6-second first reveal that cannot be skipped until it completes; later reveals can be skipped or hurried. The book shows a framed photo and a cosmetic trophy; legendaries are always released, including Fire-Lizard and Zero-G Winch variants.

### Animation overhaul and custom Skipper (PR #135)
- [ ] **New game and live creator:** use the disposable save, start a new game, type a distinct name (for example, “Mochi”), and choose a visibly different coat/pattern and attire. Turn the preview and wait for its hello wave. **Expect:** the name is editable and the first key replaces the selected old name; the preview wears the chosen look, turns, and waves; Done keeps the draft and starts the prologue.
- [ ] **Pause editor and persistence:** open Pause → Your Skipper, make a temporary change, and press Escape; reopen and confirm it was discarded. Make a second change, choose Done, save and reload the scratch save. **Expect:** only the confirmed look and name persist.
- [ ] **First-person paws:** choose a tuxedo with an Ink coat and white bib/mitts, then inspect the visible paw(s) for the current hull. **Expect:** coat/pattern and mitt colours match the chosen look; attire colours are not painted onto the paws, so check attire on the preview or chase-camera figure. Use a rowboat with oars if both paws need to be visible.
- [ ] **Generated non-starter boat in chase view:** buy or use a disposable save that owns a generated non-starter hull (for example, River Runner or Mahogany Runabout); set Camera view to Third Person. Sail and steer. **Expect:** the Skipper stands at the helm with feet on the deck (not floating or below it), wears the saved look, and leans with steering.
- [ ] **Attention and greeting:** in the chase view, idle near a cat, then move away; if two cats are nearby, pass between them. **Expect:** the Skipper looks toward nearby cats, eases attention when their directions oppose, and waves when close and slow, without a visible snap.
- [ ] **Reduced motion:** enable Reduced motion and watch an NPC, Bot, and the Skipper off the eye. **Expect:** clock-driven idle holds still; distance-driven attention and greeting can still respond.
- [ ] **Old-save migration (optional):** make a copy of a pre-creator v2 save without `v2.skipper` and launch only the copy. **Expect:** the default dusk-brown tabby is added, the one-time Continue hint appears, and the original save remains untouched.
- [ ] **Controller (if available):** use a gamepad to navigate/change a row, start name entry, finish/cancel it, and turn the preview. **Expect:** A/B and d-pad keep their controls; keyboard letter bindings do not interrupt physical name typing.

### Settings, input, gamepad, accessibility
- [ ] Open Pause → Settings; inspect Cozy/Old Salt, Camera view, and available input/accessibility/audio controls. **Expect:** first person is default; third person is a steady, level chase view; authored story staging keeps priority.
- [ ] **Mouse look:** on the water in first person, move the pointer sideways, then up and down, then stop. Compare Off, Gentle, Normal and Quick in Settings. **Expect:** the view turns with the pointer while the hull and paws move together and stay on the boat, it stops about 70 degrees either side, and it eases back about 1.2 seconds after the pointer stops. A menu or Pause starts the recentre at once. Repeat with Reduced motion on (the recentre snaps) and in Third person.
- [ ] Try keyboard and, if available, controller navigation. **Expect:** mappings match on-screen hints; hints follow the last-used device; releasing a menu direction before driving does not leave steering stuck.
- [ ] Change text size, the dyslexia-friendly font, reduced motion, haul speed, captions and volumes where present. **Expect:** readable differences, reduced-motion presentation, non-color-only markers and relevant captions.
- [ ] **Boundary:** while steering/throttle is held, move focus away and back. **Expect:** pending input/menu repeat clears on focus loss; held controls follow current keyboard state as documented.

### Save, reload, resume
- [ ] Quit normally, relaunch using the same scratch save. **Expect:** money, catches, lines, bait, boats, fuel/battery, journal and quest progress persist; powered engine resumes at idle and sail lowered.
- [ ] **Boundary:** save/reload with an active buff or an incomplete story/quest step if feasible. **Expect:** documented progress persists; timed effects do not advance while offline.

### Visual, audio, presentation boundaries
- [ ] Observe dawn/day/night and any available rain/mist; move and idle. **Expect:** water, lighting, weather and wake feel coherent; no obstructive camera movement while viewing shore.
- [ ] Listen for water, engine/oars, wind, wildlife and strike cues; press **M**. **Expect:** mute works and audio mix remains calm.
- [ ] **Boundary:** resize or use a second screen size/aspect ratio if available; check text, menus, HUD and fish cards. Try low-quality/software rendering if supported. **Expect:** essential information remains usable and presentation degrades gracefully.

## Optional deeper pass (time permitting)

- [ ] Start a separate scratch save in Old Salt. Observe needs prompts and snooze; eat, navigate and nap as appropriate. **Expect:** penalties remain mild, never remove possessions or prevent steering/hauling/tow; Cozy switching clears needs.
- [ ] Check an eligible shiny, protected fish or legendary only when encountered naturally. **Expect:** special disposition/protection is explicit; shiny identification uses more than color alone; legendary release is not confused with ordinary sale.
- [ ] Visit later waters as unlocked; compare shoreline, weather, fishing areas, chart and travel. **Expect:** lake identity is apparent and chapter unlocks follow the documented sequence.
- [ ] Try optional Sunday cookout, recipes, Bot tools, catnap and additional boat traits when available. **Expect:** prompts and confirmations communicate costs/effects; skipped optional content does not block the cozy fishing loop.

## Devmode checks

- [ ] **Opt-in / inert when off:** launch a disposable save with `--dev`. Expect a persistent DEV marker, and verify opening/closing the panel and using cheats do not write to that save. With an existing scratch save, apply a cheat on the title and choose Continue; expect the in-memory effect to remain and the save bytes to stay unchanged. Grave opens the panel on title, gameplay, and menus; Esc and grave close it. Repeat without `--dev`; expect no marker or panel, and grave to leave game state unchanged.
- [ ] **Input ownership:** open the panel over the title and a gameplay/menu screen. Use Up/Down or W/S to choose and Left/Right or A/D to change a fish/lake choice; Enter/Space activates. Also click and scroll over the underlying screen. Expect keyboard, mouse and gamepad input not to reach the underlying screen or boat while the panel is open.
- [ ] **+$1,000:** record the current balance, select **+$1,000**, and activate. Expect the balance to increase by exactly $1,000.
- [ ] **Refill bait:** use a save with a partially full bait box, select **Refill bait**, and activate. Expect worms to fill only the remaining capacity; bait total never exceeds the displayed box capacity.
- [ ] **Starter kit:** record money and bait, select **Starter kit**, and activate. Expect $1,000 added and the bait box filled to capacity.
- [ ] **Advance 1 game hour:** set a line first, record the lake clock, then activate this command from play. Expect exactly 60 game minutes to pass through the normal simulation and any resulting catches to use normal rules.
- [ ] **Catch standard fish:** deploy a line with an empty hook, choose an authored standard fish with Left/Right, then activate. Expect that fish on the next open hook; no legendary species are selectable.
- [ ] **Fill first line:** deploy a line with multiple open hooks, activate this command, and inspect the catch list. Expect every available open hook on the first line filled with distinct authored standard species; existing catches remain unchanged.
- [ ] **Change lake:** at a landing with no deployed lines, select any authored lake and activate. **Expect:** that route unlocks only in memory, then uses the ordinary safe-travel transition; if underway or lines are deployed, the cheat explains why and leaves the location unchanged.
- [ ] **Set up Old Lantern encounter:** in Little Briar, bring deployed lines aboard, retain a held line, and make room for 12 bait pieces; activate the command. Expect the authored Old Lantern line at its required site/time with spotlight and the real legendary hook evaluator, not a fabricated catch. If fixture setup cannot meet an invariant, it must explain why without corrupting the save state.
- [ ] **Reset in-memory session:** activate **Reset in-memory session**. Choose Cancel and verify current money/progress remain. Open the prompt again, explicitly choose Reset. Expect the confirmation to close into a fresh Little Briar session. Close/relaunch using the same scratch save; expect no file deletion or reset from Devmode.

## Historical verification — 2026-11-13

The checklist remains reusable; unchecked boxes are not claims of a complete
manual playthrough. The real-window replay below was captured on the pass2
worktree before its rebase, based at `6ae08f3`. The final PR integrates with
`main` at `797c317`; no post-rebase live-window replay was performed.

- **Headless gameplay/input:** new-game flow, set/soak/haul, keep/release/rebait/pull,
  kitchen confirmation/cancellation/skipping, quest turn-in, boat purchase/switching,
  empty-tank sailing, empty-battery oars, line-deployed travel refusal, time-scale
  cycling, offline soak, buff reload, Cozy switching, start-over cancellation, and
  alternate window sizes. Disposable saves/in-memory state only; not the normal save.
- **Pre-rebase live replay:** title, Cozy prompt, dialogue, chart and all five lakes at
  1200×675 on HDMI-A-1. The DEV panel title and performance badge were separated;
  the chart and lagoon transition were captured. Earlier QA notes also record
  a camera-view toggle and hull framing; these were not repeated after integrating
  upstream V1-42–V1-44.
- **Current local verification:** the focused review-fix suite ran 89 tests
  successfully. Native and software `python -m fishing --selftest` both
  reported `selftest ok`. A full suite on the earlier rebased head ran 865
  tests successfully (1 skipped); the latest full-suite rerun exceeded the
  600-second command timeout while the long playthrough test was running, with
  no assertion failure reported before timeout. Local Python was 3.15.2;
  GitHub validation targets Python 3.12, and its exact-head push check remains
  the merge gate.
- **Final 1,200-frame benchmarks:** all four tiers reported complete five-lake
  coverage after restoring the HDR shader setup and copy-on-ingest audio samples.
  The primary renderer is closed before the separate play-loop measurement so
  the peak does not count two renderers at once. Combined process RSS plus
  DRM-reported GPU allocation is checked against 3,000,000,000 bytes on every
  frame:

  | Detail | 3D target at 1440×810 | Play-loop p50 / p95 at 1200×675 | Peak combined MiB |
  | --- | ---: | ---: | ---: |
  | Low | 792×445 | 17.39 / 21.23 ms | 603 |
  | Standard | 864×486 | 19.23 / 27.99 ms | 1,202 |
  | High | 1296×729 | 30.35 / 48.24 ms | 1,588 |
  | Ultra | 1440×810 | 34.77 / 40.30 ms | 2,643 |

- **Performance tradeoff:** Standard at 60% of window resolution missed the
  earlier ~17 ms p50 target by about 2.2 ms on this loaded host. I kept 60%
  rather than lowering the default scene resolution further; the cost is a
  softer image.
- **Memory details:** Ultra peaked at 2,049 MiB DRM GPU allocation and 2,643 MiB
  combined. Its audio bank used 117.87 MiB of the 150 MiB budget. That is
  19 MiB below the soft 2.6 GiB tier target and 218 MiB under the 3 GB hard
  ceiling; the 4x MSAA setting is retained for image quality.
- **CI gate:** GitHub run status is tracked on the PR. Per
  `docs/PR-REVIEW-POLICY.md`, the exact-head push `gameplay-tests` job must pass
  before merge.
- **Not established:** the final rebased window was not replayed; audio was not
  auditioned by ear, physical-controller operation was not tested, and a natural
  unlock/story playthrough was not completed.

## PR #135 review record — code head `f544b7e`, 2026-11-21

**Human play pass: pending.** The PR review asks for a human pass of the new-game flow, typed Skipper name, and a non-starter boat in chase camera. No human play session has been performed by the agent; leave all boxes in the feature section unchecked until Aven records the pass.

- **Code head validated:** `f544b7e` is a formatting-only follow-up to behavior head `0f0f67c`. On `0f0f67c`, `python -m unittest discover` passed 935 tests (1 skipped), `fishing.test_narrative` passed 37, `python -m fishing --selftest --software` passed, and native/software `--cats` shots passed. After spacing cleanup at `f544b7e`, `py_compile` and `unittest fishing.test_cats.Skipper fishing.test_skipper_creator` passed (29 tests).
- **GitHub validation:** the applicable `gameplay-tests`, `windows-tests`, package, smoke, and `second-review-pass` jobs passed on code head `f544b7e` at the time recorded. Conditional macOS/Windows package jobs were skipped.
- **Review scope:** the remaining required verification is the human play pass above. Merge remains Aven's decision.
