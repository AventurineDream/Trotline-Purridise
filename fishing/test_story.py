"""V1-34: the story spine. Chapters are three `story`-kind steps each, started and finished by
play (01 §5, 02 §13). These checks drive a new save through real hails and events, reload it
mid-chapter, and check that rewards are paid once and the chapters finish in order."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .botidentity import profile
from .content import load_content
from .dialogue import nearby_npc, open_conversation, story_heard
from .fleet import chapter_finished
from .game import Keys, Session
from .npcs import day_encounters, night_encounter
from .quests import QuestManager, autostart_story, story_part
from .sim import State
from .world import World
from .test_quests_v2 import centre

STEPS = [f"story_c{c}_s{s}" for c in (1, 2, 3, 4, 5) for s in (1, 2, 3)]


class StoryPlay(unittest.TestCase):
    """Drives a save through the story with real hails, events, scenes and travel. It has
    no checks of its own: the chapters' checks are Story's, and test_playthrough plays it all."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("briar")
        self.state = State.new(self.world, seed=34)
        # These checks start where the prologue ends (test_prologue plays it): chapter one open.
        self.state.set_scene_status("prologue", "done")
        self.open_session()

    # --- a session on whatever lake the state is on -------------------------------------
    def open_session(self):
        self.world = World(self.state.lake_id)
        with patch("fishing.game.load_content", return_value=self.content):
            self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = "play"

    def status(self, qid):
        progress = self.state.narrative.quests.get(qid)
        return progress.status if progress else "available"

    def present(self, npc_id):
        self.session._refresh_npcs()
        return next((n for n in self.state.npcs if n.id == npc_id), None)

    def meet(self, npc_id):
        """Move the clock to a time the cat is out on this lake (the schedule decides)."""
        seed, lake = self.state.narrative.schedule_seed, self.world.id
        for day in range(0, 30):
            for minute in (120, 900):
                self.state.game_minutes = day * 1440 + minute
                self.session._refresh_npcs()
                if self.present(npc_id) is not None:
                    return
        self.fail(f"{npc_id} is never out on {lake}")

    def dock_beside(self, npc):
        slip, s = self.world.slip, self.state
        s._park(self.world)
        spots = [slip.world(a / 4, side / 4) for a in range(9, int(slip.land_ext * 4) + 1)
                 for side in range(-int(slip.half_w * 4), int(slip.half_w * 4) + 1)]
        spots = [p for p in spots if self.world.hull_clear(p[0], p[1], s.yaw, s.boat_id)]
        s.x, s.z = min(spots, key=lambda p: math.hypot(p[0] - npc.anchor.x, p[1] - npc.anchor.z))
        self.assertEqual(nearby_npc(s).id, npc.id)

    def talk(self, npc_id, *choices):
        """Hail the cat, read to each choice and take the next listed action there.
        Returns the node ids seen."""
        npc = self.present(npc_id)
        self.assertIsNotNone(npc, npc_id)
        self.state.x, self.state.z = npc.anchor.position  # as the other suites hail: at the cat
        self.assertEqual(nearby_npc(self.state).id, npc_id)
        self.state.speed = 0
        self.session.ui.mode, self.session.conversation = "play", None
        self.session._hail()
        chat = self.session.conversation
        self.assertIsNotNone(chat, f"{npc_id} only waved")
        seen, pending = [], list(choices)
        while True:
            seen.append(chat.node_id)
            node = chat.node(self.content)
            if "choices" in node:
                if not pending:
                    break
                action = pending.pop(0)
                chat.selected = next(i for i, ch in enumerate(node["choices"]) if ch["action"] == action)
            if not chat.advance(self.state, self.content):
                break
        self.session._close_dialogue()
        self.assertEqual(pending, [], f"{npc_id}: choices not offered")
        return seen

    def press(self, key):
        self.session.tick(Keys(pressed={key}), 0.05)

    def scene(self, *choices):
        """The story scene whose moment has come plays at once; read it through. Returns its nodes.
        A scene that comes due as this one ends (the ending, after the trip home) is left open."""
        self.press("x")
        self.assertEqual(self.session.ui.mode, "dialogue", "no scene played")
        seen, pending, chat = [], list(choices), self.session.conversation
        while self.session.conversation is chat:
            seen.append(chat.node_id)
            node = chat.node(self.content)
            if "choices" in node:
                index = next(i for i, c in enumerate(node["choices"]) if c["text"] == pending[0])
                pending.pop(0)
                self.press(str(index + 1))
            else:
                self.press("c")
        self.assertEqual(pending, [])
        return seen

    def reload(self):
        """Quit (which saves) and continue the save in a new session."""
        self.session.tick(Keys(quit=True), 0.05)
        self.state = State.load(self.path, World(self.state.lake_id))
        self.open_session()

    def emit(self, **event):
        event.setdefault("lake_id", self.world.id)
        event.setdefault("game_minute", self.state.game_minutes)
        self.state.emit_quest_event(event)

    def at(self, ref, **extra):
        x, z = centre(ref)
        return {"x": x, "z": z, **extra}

    def play_chapter_one_meet(self):
        self.meet("pip_pebble")
        self.talk("pip_pebble")  # the hail completes step one
        self.talk("pip_pebble", "turn_in")

    def play_chapter_one(self):
        # Meet: Pip & Pebble, the first hail (talk_to) completes the step.
        self.meet("pip_pebble")
        self.assertEqual(self.status("story_c1_s1"), "active")  # auto-started, no offer or decline
        self.assertEqual(self.talk("pip_pebble")[0], "story_c1_s1:dialogue:ready")
        self.assertEqual(self.status("story_c1_s1"), "ready")
        self.talk("pip_pebble", "turn_in")
        self.assertEqual(self.status("story_c1_s1"), "completed")
        self.assertEqual(self.status("story_c1_s2"), "active")
        # Notice: Bot scouts the three reed-edge points, in any order.
        for ref in ("briar:reed_edge_3", "briar:reed_edge_1", "briar:reed_edge_2"):
            self.emit(type="bot.scout_complete", zone_id="briar:reeds", depth_class="middling",
                      report_delivered=True, **self.at(ref))
        self.assertEqual(self.status("story_c1_s2"), "ready")
        self.talk("pip_pebble", "turn_in")
        self.assertIn("reed_anchor", profile(self.state)["tools"])  # the step's reward, free
        # Share: a catch in the reeds, then turn in to Grandmother.
        self.assertEqual(self.status("story_c1_s3"), "active")
        self.emit(type="catch.resolved", species_id="bluegill", legendary=False, kept=True,
                  zone_id="briar:reeds", lake_id="briar", x=0.0, z=0.0, bait_id="worm",
                  weight_lb=1.0, catch_hour=9.0, in_cold_band=False)
        self.assertEqual(self.status("story_c1_s3"), "ready")
        self.talk("grandmother_whiskers", "turn_in")

    def travel(self, lake):
        """Tow to another lake as the game does: docked at the landing, then change_lake."""
        self.state._park(self.world)
        self.assertIsNone(self.session.change_lake(lake))
        self.world = self.session.world

    def play_chapter_two(self):
        self.travel("cedar")
        # Meet: Doc Barnaby, who is always at Cedar Creek's landing. His first meeting greets
        # the Skipper before the step (05 §4.2, greetings precede the step's own node).
        self.assertEqual(self.status("story_c2_s1"), "active")
        seen = self.talk("doc_barnaby")
        self.assertEqual(seen[0], "doc_barnaby:greeting")
        self.assertIn("story_c2_s1:dialogue:ready", seen)
        self.talk("doc_barnaby", "turn_in")
        # Notice: the three drift buoys, in order.
        self.assertEqual(self.status("story_c2_s2"), "active")
        for ref in ("cedar:drift_buoy_1", "cedar:drift_buoy_2", "cedar:drift_buoy_3"):
            self.emit(type="waypoint.enter", lake_id="cedar", waypoint_id=ref, movement_cause="boat",
                      player_controlled=True)
        self.assertEqual(self.status("story_c2_s2"), "ready")
        self.talk("doc_barnaby", "turn_in")
        # Share: a premium line in the Marked Pool, checked after its soak.
        self.assertEqual(self.status("story_c2_s3"), "active")
        set_line = {"line_id": "00000000-0000-0000-0000-000000000034", "tier_id": "prem", "hook_count": 18,
                    "bait_id": "liver", "bait_sections": ["liver"], "in_cold_band": False,
                    "zone_id": "cedar:rocks", "x": centre("cedar:marked_pool")[0],
                    "z": centre("cedar:marked_pool")[1]}
        self.emit(type="line.set", active_game_minute=10, **set_line)
        self.emit(type="line.check", lake_id="cedar", zone_id="cedar:rocks", line_id=set_line["line_id"],
                  active_game_minute=70)
        self.assertEqual(self.status("story_c2_s3"), "ready")
        self.talk("doc_barnaby", "turn_in")

    def at_clock(self, hour):
        """Move the clock forward to the next given hour of the day (game minute 0 is 06:00)."""
        minute = (hour - 6) % 24 * 60
        day = self.state.game_minutes // 1440 + 1
        self.state.game_minutes = day * 1440 + minute

    def cold_catch(self, **extra):
        event = dict(type="catch.resolved", species_id="lake_trout", legendary=False, kept=True,
                     zone_id="flathead:deep", lake_id="flathead", x=0.0, z=0.0, bait_id="minnow", weight_lb=6.0,
                     catch_hour=9.0, in_cold_band=True)
        event.update(extra)
        self.emit(**event)

    def play_chapter_three(self):
        self.travel("flathead")
        # Meet: Huckleberry's first hail is the step itself; his Whopper waits (05 §2.3, §4.3).
        self.assertEqual(self.status("story_c3_s1"), "active")
        seen = self.talk("captain_huckleberry", "turn_in")
        self.assertEqual(seen[0], "story_c3_s1:dialogue:ready")
        self.assertNotIn("captain_huckleberry:story", seen)
        self.assertIn("thermo_scanner", profile(self.state)["tools"])  # lent for the readings
        # Notice: one report in the Glacial trench each morning and afternoon window.
        self.assertEqual(self.status("story_c3_s2"), "active")
        self.at_clock(8)
        report = dict(type="bot.scout_complete", zone_id="flathead:deep", depth_class="deep", report_delivered=True,
                      x=0.0, z=0.0)
        self.emit(**report)
        self.emit(**report)  # a second morning report counts once
        self.assertEqual(self.status("story_c3_s2"), "active")
        self.at_clock(15)
        self.emit(**report)
        self.assertEqual(self.status("story_c3_s2"), "ready")
        self.assertEqual(self.scene(), ["scene:story_c3_cold"])  # Bot says it on the spot
        self.assertEqual(self.status("story_c3_s2"), "completed")
        # Share: a cold-water fish from a line in the cold layer, turned in to Huckleberry.
        self.cold_catch(in_cold_band=False)
        self.cold_catch(species_id="smallmouth_bass")
        self.assertEqual(self.status("story_c3_s3"), "active")
        self.cold_catch()
        self.assertEqual(self.status("story_c3_s3"), "ready")
        self.talk("captain_huckleberry", "turn_in")

    def play_chapter_four(self, knot="Bow"):
        self.travel("crater")
        self.talk("sora", "turn_in")
        self.assertEqual(self.status("story_c4_s2"), "active")
        cove = self.at("crater:safe_cove_2")
        sample = dict(type="anchor.sample", lake_id="crater", zone_id="crater:flats", **cove)
        self.emit(**sample, anchored=True, weather="fog", elapsed_game_minutes=12)
        self.emit(**sample, anchored=False, weather="fog", elapsed_game_minutes=5)  # drifting pauses, keeps 12
        self.emit(**sample, anchored=True, weather="fog", elapsed_game_minutes=10)
        self.assertEqual(self.status("story_c4_s2"), "active")
        self.emit(**sample, anchored=True, weather_spans=[["fog", 1], ["clear", 15]], elapsed_game_minutes=16)
        self.assertEqual(self.status("story_c4_s2"), "ready")
        self.assertEqual(self.scene(), ["scene:story_c4_clear"])
        self.assertEqual(self.status("story_c4_s3"), "active")
        self.emit(type="bot.scout_complete", zone_id="crater:open", depth_class="deep", report_delivered=True,
                  **self.at("crater:survey_marker"))
        self.assertEqual(self.status("story_c4_s3"), "ready")
        # At the marker, before the reading: Bot chooses his knot with the Skipper.
        self.assertEqual(self.scene(knot), ["scene:story_c4_knot", "scene:story_c4_tied"])
        self.talk("sora", "turn_in")

    def settle_by_the_reflection(self):
        """Anchor in Nebula open at the calm reflection, where "Settle in" is offered."""
        self.state.x, self.state.z = centre("nebula:calm_reflection")
        self.state.speed, self.state.throttle, self.state.throttle_setting = 0.0, 0.0, 0.0
        self.state.anchored = True
        self.assertIsNone(nearby_npc(self.state))
        self.press("x")
        self.assertIn("Settle in", self.session.ui.settle_prompt)

    def wait(self, seconds, step=5.0):
        for _ in range(int(seconds / step)):
            self.session.tick(Keys(), step)

    def play_chapter_five(self, together=True):
        self.travel("nebula")
        self.assertEqual(self.scene(), ["scene:story_c5_arrive"])  # the first trip onto the sky
        self.talk("astra_9", "turn_in")
        self.assertEqual(self.status("story_c5_s2"), "active")
        self.settle_by_the_reflection()
        self.press("c")
        self.assertTrue(self.session.ui.settling)
        self.wait(15)  # the first cue, then Astra-9 drifts alongside
        self.assertEqual(self.state.v2["story"]["settle"]["cues"], 1)
        self.assertEqual(self.session.conversation.node_id, "scene:story_c5_together")
        choice = "Watch together" if together else "We'll keep still"
        index = 1 if together else 2
        self.press(str(index))
        self.assertEqual(self.session.ui.mode, "play")
        self.assertEqual(self.state.v2["story"]["settle"]["together"], together, choice)
        self.wait(30)
        self.assertEqual(self.status("story_c5_s2"), "ready")
        self.assertEqual(self.scene("Draw it", "Go home to Briar Landing"),
                         ["scene:story_c5_whale", "scene:story_c5_whale:2", "scene:story_c5_drawn"])
        self.world = self.session.world
        self.assertEqual(self.world.id, "briar")  # the free trip, from the reflection

    def play_the_ending(self):
        self.assertEqual(self.scene(), ["scene:end_01", "scene:end_01:2", "scene:end_01:3", "scene:end_01b",
                                        "scene:end_01b:2", "scene:end_02", "scene:end_02:2", "scene:end_03",
                                        "scene:end_03:2"])
        self.press("x")
        self.assertEqual(self.session.ui.mode, "credits")
        self.press("return")  # too soon: the credits hold
        self.assertEqual(self.session.ui.mode, "credits")
        self.session.tick(Keys(), 3.0)
        self.press("return")
        self.assertEqual(self.session.ui.mode, "play")


class Story(StoryPlay):
    def test_chapter_one_waits_for_the_prologue(self):
        state = State.new(World("briar"), seed=5)  # a save the prologue has not opened
        autostart_story(state, self.content)
        self.assertEqual(state.narrative.quest("story_c1_s1").status, "available")
        state.v2["story"]["chapter"] = 1
        autostart_story(state, self.content)
        self.assertEqual(state.narrative.quest("story_c1_s1").status, "active")

    def test_a_chapter_starts_without_an_offer_and_steps_only_on_play(self):
        autostart_story(self.state, self.content)
        self.assertEqual(self.status("story_c1_s1"), "active")
        self.assertEqual(self.status("story_c1_s2"), "available")  # waits for step one's turn-in
        self.assertEqual(self.status("story_c2_s1"), "available")  # waits for chapter one
        self.assertTrue(all(self.status(qid) != "declined" for qid in STEPS))

    def test_chapter_one_runs_from_a_new_save_to_its_finish(self):
        self.play_chapter_one()
        self.assertTrue(chapter_finished(self.state, 1))
        self.assertEqual(self.state.v2["story"]["completed_chapters"], [1])
        self.assertEqual(self.state.v2["story"]["chapter"], 2)
        self.assertIn("frog", profile(self.state)["shells"])
        self.assertIn("chart:reeds", self.state.v2["unlocks"])
        self.assertEqual(self.status("story_c2_s1"), "active")  # chapter two starts at once

    def test_a_reload_mid_chapter_keeps_progress_and_pays_no_reward_twice(self):
        self.play_chapter_one()
        tools = list(profile(self.state)["tools"])
        money = self.state.money
        self.state.save(self.path)
        self.state = State.load(self.path, self.world)
        self.open_session()
        self.assertEqual(self.status("story_c2_s1"), "active")
        self.assertEqual(profile(self.state)["tools"], tools)
        self.assertEqual(self.state.money, money)
        self.assertEqual(self.state.v2["story"]["completed_chapters"], [1])
        # Hailing the cat again after the finish opens the cat's own conversation, not the step.
        self.talk("grandmother_whiskers")
        self.assertEqual(self.state.v2["story"]["completed_chapters"], [1])
        self.assertEqual(len(set(self.state.narrative.reward_claims)), len(self.state.narrative.reward_claims))

    def test_a_step_is_never_time_limited(self):
        story = [qid for qid, row in self.content.quests.items() if row.get("kind") == "story"]
        self.assertEqual(len(story), 18)  # the prologue's three and chapters 1–5
        for qid in story:
            row = self.content.quests[qid]
            steps = row["objective"] if isinstance(row["objective"], list) else [row["objective"]]
            for step in steps:
                self.assertFalse({"deadline", "until", "by_minute", "expires"} & set(step), qid)
            self.assertNotIn("time_limit", row)

    def test_chapters_three_and_four_run_to_the_nebula_route(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.assertEqual(profile(self.state)["collar"]["stage"], "received")
        self.play_chapter_three()
        story = self.state.v2["story"]
        self.assertEqual(story["completed_chapters"], [1, 2, 3])
        self.assertIn("sub", profile(self.state)["shells"])
        self.assertIn("travel:crater", self.state.v2["unlocks"])
        self.assertEqual(profile(self.state)["collar"]["stage"], "loose")  # the mountain wind (05 §2.3)
        self.play_chapter_four("Sailor's hitch")
        self.assertEqual(story["completed_chapters"], [1, 2, 3, 4])
        self.assertEqual(story["chapter"], 5)
        self.assertIn("travel:nebula", self.state.v2["unlocks"])
        collar = profile(self.state)["collar"]
        self.assertEqual((collar["stage"], collar["knot"]), ("retied", "sailors_hitch"))
        self.assertEqual(self.state.v2["npcs"]["letters"], [])
        for scene in ("story_c3_cold", "story_c4_clear", "story_c4_knot", "story_c4_tied"):
            self.assertEqual(self.state.v2["story"]["scene_states"][scene], "done")

    def test_the_new_scenes_replay_after_a_reload_and_pay_once(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.travel("flathead")
        self.talk("captain_huckleberry", "turn_in")
        report = dict(type="bot.scout_complete", zone_id="flathead:deep", depth_class="deep", report_delivered=True,
                      x=0.0, z=0.0)
        self.at_clock(8)
        self.emit(**report)
        self.at_clock(15)
        self.emit(**report)
        self.press("x")
        self.assertEqual(self.session.conversation.node_id, "scene:story_c3_cold")
        self.reload()
        self.assertEqual(self.status("story_c3_s2"), "ready")
        self.assertEqual(self.scene(), ["scene:story_c3_cold"])
        self.cold_catch()
        self.talk("captain_huckleberry", "turn_in")
        self.travel("crater")
        self.talk("sora", "turn_in")
        cove = self.at("crater:safe_cove_1")
        self.emit(type="anchor.sample", lake_id="crater", zone_id="crater:lilies", anchored=True,
                  weather_spans=[["fog", 30], ["clear", 5]], elapsed_game_minutes=35, **cove)
        self.press("x")
        self.assertEqual(self.session.conversation.node_id, "scene:story_c4_clear")
        self.reload()
        self.assertEqual(self.scene(), ["scene:story_c4_clear"])
        self.emit(type="bot.scout_complete", zone_id="crater:open", depth_class="deep", report_delivered=True,
                  **self.at("crater:survey_marker"))
        self.press("x")
        self.assertEqual(self.session.conversation.node_id, "scene:story_c4_knot")
        self.press("esc")  # the choice must be made
        self.assertEqual(self.session.conversation.node_id, "scene:story_c4_knot")
        self.reload()
        self.assertIsNone(profile(self.state)["collar"]["knot"])
        self.assertEqual(self.scene("Square knot"), ["scene:story_c4_knot", "scene:story_c4_tied"])
        self.talk("sora", "turn_in")
        self.reload()
        self.press("x")
        self.assertIsNone(self.session.conversation)  # every scene is done; nothing replays
        claims = self.state.narrative.reward_claims
        self.assertEqual(len(claims), len(set(claims)))
        self.assertEqual(sorted(q for q in claims if q.startswith(("story_c3", "story_c4"))),
                         [f"story_c{c}_s{s}" for c in (3, 4) for s in (1, 2, 3)])
        self.assertEqual(profile(self.state)["collar"]["knot"], "square")
        self.assertEqual(self.state.v2["story"]["completed_chapters"], [1, 2, 3, 4])

    def test_a_scene_is_not_restarted_while_it_is_read(self):
        # Bot is never on a lake's roster; his scenes must not close and replay each frame.
        self.play_chapter_one()
        self.play_chapter_two()
        self.play_chapter_three()
        self.travel("crater")
        self.state.narrative.quest("story_c4_s1")  # under way since chapter four opened
        progress = self.state.narrative.quests["story_c4_s3"]
        progress.status = "ready"
        self.press("x")
        chat = self.session.conversation
        self.assertEqual(chat.node_id, "scene:story_c4_knot")
        # He speaks it in his own name, with no cat's portrait.
        from .botidentity import name
        from .platform import Text
        from .ui import UI
        text = Text()
        self.addCleanup(text.close)
        renderer, drawn = UI(text, self.world), []
        renderer._text = lambda frame, s, *args, **kw: drawn.append(s)
        renderer._blit_rgb = lambda *args: self.fail("a portrait for Bot")
        renderer._dialogue(np.zeros((720, 1280, 3), np.uint8), self.state, self.session.ui)
        self.assertEqual(drawn[0], name(self.state))
        self.session.tick(Keys(), 0.05)
        self.assertIs(self.session.conversation, chat)  # not closed and reopened from its start
        self.press("2")  # "Bow"
        self.assertEqual(chat.node_id, "scene:story_c4_tied")
        self.session.tick(Keys(), 0.05)
        self.assertIs(self.session.conversation, chat)
        self.assertEqual(self.state.v2["story"]["scene_states"]["story_c4_knot"], "done")
        self.press("c")
        self.assertIsNone(self.session.conversation)
        self.assertEqual(self.state.v2["story"]["scene_states"]["story_c4_tied"], "done")

    def test_chapter_five_and_the_ending_reach_the_credits(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.play_chapter_three()
        self.play_chapter_four()
        self.play_chapter_five()
        self.assertEqual(self.status("story_c5_s3"), "active")
        self.assertIn("astral", profile(self.state)["shells"])
        # The winch is unlocked for sale by the shell, as the Duck shell unlocks the chime (05 §2.5).
        self.assertNotIn("zero_g_winch", profile(self.state)["tools"])
        self.play_the_ending()
        story = self.state.v2["story"]
        self.assertEqual(story["completed_chapters"], [1, 2, 3, 4, 5])
        self.assertEqual(story["chapter"], 6)
        self.assertEqual(self.state.v2["book"]["title"], "book_of_five_waters")
        from .botidentity import book_credit
        self.assertEqual(book_credit(self.state), "the Skipper & " + profile(self.state)["bot_name"])
        self.assertEqual(profile(self.state)["collar"]["stage"], "favorite")
        for scene in ("ending", "end_03", "credits"):
            self.assertEqual(story["scene_states"][scene], "done", scene)
        self.assertEqual(self.status("story_c5_s3"), "completed")
        # Play continues at the landing, where the book shows its new title (V1-17's ceremony). Then
        # free play: no scene left to play, and the cats greet the author.
        self.press("x")
        self.assertEqual((self.session.ui.mode, self.session.ui.book_ceremony), ("journal", "book_of_five_waters"))
        self.press("esc")
        self.press("x")
        self.assertEqual(self.session.ui.mode, "play")
        self.assertIsNone(self.session.conversation)
        from .dialogue import greeting
        self.assertEqual(greeting(self.state, self.content, "grandmother_whiskers"),
                         "There's my author. What did the lake tell you today?")  # after_ch5 (05 §4)
        self.assertTrue(self.talk("grandmother_whiskers")[0].endswith(":greeting"))

    def test_watching_together_counts_only_by_the_reflection(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.play_chapter_three()
        self.play_chapter_four()
        self.travel("nebula")
        self.scene()
        self.talk("astra_9", "turn_in")
        self.settle_by_the_reflection()
        self.press("c")
        self.wait(15)
        self.press("1")  # watch together
        settle = self.state.v2["story"]["settle"]
        seconds = settle["seconds"]
        # Sailing off across Nebula open, out of the reflection's 200 m: paused.
        cx, cz = centre("nebula:calm_reflection")
        far = next((cx + r * math.cos(a / 8 * math.tau), cz + r * math.sin(a / 8 * math.tau))
                   for r in (260, 320, 400) for a in range(8)
                   if self.world.navigable(cx + r * math.cos(a / 8 * math.tau), cz + r * math.sin(a / 8 * math.tau))
                   and self.world.zone_at(cx + r * math.cos(a / 8 * math.tau), cz + r * math.sin(a / 8 * math.tau)) == "open")
        self.state.anchored, (self.state.x, self.state.z) = False, far
        self.wait(40)
        self.assertEqual(settle["seconds"], seconds)
        self.assertIn("paused", self.session.ui.settle_prompt)
        from . import comfort  # a settle paused out here holds no nap off
        comfort.change_mode(self.state.v2, "old_salt")
        self.state.v2["needs"]["awake_h"] = 99.0
        self.session.tick(Keys(), 1.0)
        self.assertEqual(self.session.ui.mode, "catnap")
        comfort.change_mode(self.state.v2, "cozy")
        self.state.v2["needs"]["awake_h"] = 0.0
        self.session.ui.mode = "play"
        # Home to Briar: the step can't finish there either.
        self.travel("briar")
        self.assertFalse(self.session.ui.settling)
        self.wait(40)
        self.assertEqual((settle["seconds"], self.status("story_c5_s2")), (seconds, "active"))
        # Back by the reflection, hands-free again from where it paused.
        self.travel("nebula")
        self.settle_by_the_reflection()
        self.press("c")
        self.state.anchored, self.state.speed = False, 2.0
        self.wait(30)
        self.assertEqual(self.status("story_c5_s2"), "ready")

    def test_moving_pauses_settling_and_never_resets_it(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.play_chapter_three()
        self.play_chapter_four()
        self.travel("nebula")
        self.scene()
        self.talk("astra_9", "turn_in")
        self.settle_by_the_reflection()
        self.press("c")
        self.wait(10)
        seconds = self.state.v2["story"]["settle"]["seconds"]
        self.assertAlmostEqual(seconds, 10.0, delta=0.1)  # with the frame "Settle in" was chosen on
        self.state.anchored = False  # drifting off: paused, not reset
        self.wait(20)
        self.assertEqual(self.state.v2["story"]["settle"]["seconds"], seconds)
        self.assertIn("paused", self.session.ui.settle_prompt)
        # A reload keeps the progress; settling in again goes on from there.
        self.reload()
        self.settle_by_the_reflection()
        self.assertEqual(self.state.v2["story"]["settle"]["seconds"], seconds)
        self.press("c")
        self.wait(5)
        self.assertEqual(self.state.v2["story"]["settle"]["cues"], 1)
        self.assertEqual(self.session.conversation.node_id, "scene:story_c5_together")
        self.press("2")  # keep still alone
        # Needs never interrupt Settle In, even in Old Salt mode.
        from . import comfort
        comfort.change_mode(self.state.v2, "old_salt")
        self.state.v2["needs"]["awake_h"] = 99.0
        self.wait(30)
        self.assertEqual(self.session.ui.mode, "dialogue")  # the whale, not a nap
        self.assertEqual(self.session.conversation.node_id, "scene:story_c5_whale")

    def test_the_credits_offer_a_key_only_once_their_hold_is_over(self):
        from .platform import Text
        from .ui import CREDITS_HOLD_S, UI, UIState
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        for shown, offered in ((0.0, False), (CREDITS_HOLD_S, True)):
            drawn = []
            # Every helper (_center, _backed) draws through _text.
            renderer._text = lambda frame, s, *args, **kw: drawn.append(s) or 0
            renderer.draw(np.zeros((720, 1280, 3), np.uint8), self.state, UIState(mode="credits", credits_s=shown))
            self.assertIn("The Book of Five Waters", drawn)
            self.assertEqual(any("keep fishing" in line for line in drawn), offered, shown)

    def test_the_free_trip_needs_the_lines_aboard(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.play_chapter_three()
        self.play_chapter_four()
        self.travel("nebula")
        self.scene()
        self.talk("astra_9", "turn_in")
        self.settle_by_the_reflection()
        self.press("c")
        self.wait(15)
        self.press("1")  # watch together
        self.wait(30)
        from .sim import SetLine
        self.state.lines.append(SetLine("std", ["worm"], 0, 0, 10, 0, "open", []))
        self.scene("Draw it", "Go home to Briar Landing")
        self.assertEqual(self.session.world.id, "nebula")  # no trip with a line out
        self.assertEqual(self.status("story_c5_s3"), "active")
        self.state.lines.clear()
        self.state._park(self.world)
        self.assertIsNone(self.session.change_lake("briar"))  # home any other way
        self.world = self.session.world
        self.play_the_ending()
        self.assertEqual(self.state.v2["story"]["chapter"], 6)

    def test_a_reading_outside_its_window_does_not_count(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.travel("flathead")
        self.talk("captain_huckleberry", "turn_in")
        report = dict(type="bot.scout_complete", zone_id="flathead:deep", depth_class="deep", report_delivered=True,
                      x=0.0, z=0.0)
        for hour in (12, 20, 3):  # midday, evening and night readings
            self.at_clock(hour)
            self.emit(**report)
        self.at_clock(9)
        self.emit(**{**report, "zone_id": "flathead:open"})  # a morning reading, but not in the trench
        self.assertEqual(self.status("story_c3_s2"), "active")

    def test_chapter_two_runs_on_cedar_and_opens_the_flathead_route(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.assertEqual(self.state.v2["story"]["completed_chapters"], [1, 2])
        self.assertEqual(self.state.v2["story"]["chapter"], 3)
        self.assertIn("duck", profile(self.state)["shells"])
        self.assertIn("travel:flathead", self.state.v2["unlocks"])
        self.assertTrue(chapter_finished(self.state, 2))

    def test_no_letter_is_queued_for_a_story_giver(self):
        self.play_chapter_one()
        self.play_chapter_two()
        self.assertEqual(self.state.v2["npcs"]["letters"], [])

    def test_a_step_under_way_shows_its_progress_when_its_giver_is_hailed(self):
        # Codex, PR 107: a scouting step (not a talk step) must still speak through its giver.
        self.play_chapter_one_meet()
        self.assertEqual(self.status("story_c1_s2"), "active")
        self.meet("pip_pebble")  # not pinned now: the schedule alone decides when she is out
        seen = self.talk("pip_pebble")
        self.assertIn("story_c1_s2:dialogue:progress", seen)

    def test_story_steps_are_journal_entries(self):
        from .ui import journal_quest_ids
        self.play_chapter_one()
        self.assertIn("story_c2_s1", journal_quest_ids(self.state, self.content))
        self.assertIn("story_c1_s3", journal_quest_ids(self.state, self.content))

    def test_story_parts_parse_and_the_ledger_knows_them(self):
        from .narrative import is_quest_id
        self.assertEqual(story_part("story_c2_s3"), (2, 3))
        self.assertEqual(story_part("story_c0_s1"), (0, 1))  # the prologue
        self.assertIsNone(story_part("wc_marigold_a"))
        self.assertTrue(all(is_quest_id(qid) for qid in STEPS + ["story_c0_s3"]))

    def test_the_collar_is_tied_when_chapter_one_ends(self):
        self.assertEqual(profile(self.state)["collar"]["stage"], "none")
        self.play_chapter_one()
        self.assertEqual(profile(self.state)["collar"]["stage"], "received")  # live, not on the next load

    def test_a_cats_finished_errand_is_handed_in_before_the_story_reminder(self):
        # Review of PR 107: Grandmother's ready errand waited for her story step to finish.
        self.meet("pip_pebble")
        self.talk("pip_pebble")
        self.talk("pip_pebble", "turn_in")
        for ref in ("briar:reed_edge_1", "briar:reed_edge_2", "briar:reed_edge_3"):
            self.emit(type="bot.scout_complete", zone_id="briar:reeds", depth_class="middling",
                      report_delivered=True, **self.at(ref))
        self.talk("pip_pebble", "turn_in")
        self.assertEqual(self.status("story_c1_s3"), "active")
        errand = "q01_tea_leaves_deep_holes"
        progress = self.state.narrative.quest(errand)
        progress.status, progress.accepted_game_minute = "ready", 0
        seen = self.talk("grandmother_whiskers", "turn_in")
        self.assertIn(f"{errand}:dialogue:ready", seen)
        self.assertEqual(self.status(errand), "completed")
        self.assertEqual(self.status("story_c1_s3"), "active")
        # With the errand handed in, her next hail is the story's reminder again.
        self.assertIn("story_c1_s3:dialogue:progress", self.talk("grandmother_whiskers"))
