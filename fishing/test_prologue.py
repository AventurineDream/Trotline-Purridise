"""V1-34: the prologue (05 §1) and the story scenes it is built from.

A new game is driven through the title screen's real "New morning" path. The first
line is set with the game's own line-setting rules at the landing, and every scene is
read with the dialogue keys. Each scene is interrupted at its first bubble and reloaded.
The scene must replay from its start, and no step may be paid twice.
"""
from copy import deepcopy
import math
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .content import ContentError, load_content, validate_content_v2
from .data import CONTENT_V2_RAW
from .dialogue import nearby_npc
from .game import Keys, Session
from .lakes import in_place
from .quests import scene_state
from .savepaths import load_game_save
from .sim import State
from .story import due_scene, hail_scene, resume, scene_conversation
from .test_skipper_creator import finish_creator
from .world import World

SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "v1" / "05-SCRIPT.md"
PROLOGUE = ("pro_01", "pro_02", "pro_03", "pro_04", "pro_05", "pro_05b", "pro_06")
STEPS = ("story_c0_s1", "story_c0_s2", "story_c0_s3")
GRAN = "grandmother_whiskers"


class Prologue(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        # The title screen of a game with no save, on another lake: a new game opens at Briar.
        self.world = World("cedar")
        self.state = State.new(self.world, seed=34)
        with patch("fishing.game.load_content", return_value=self.content):
            self.session = Session(self.world, self.path, self.state, False)

    # --- driving the game ---------------------------------------------------------------
    def press(self, key):
        self.session.tick(Keys(pressed={key}), 0.05)

    def new_morning(self):
        self.session.ui.mode, self.session.ui.new_mode_i = "new_mode", 0
        self.press("return")
        finish_creator(self.session)
        self.state, self.world = self.session.state, self.session.world

    def reload(self):
        """Quit (which saves) and continue the save in a new session."""
        self.session.tick(Keys(quit=True), 0.05)
        world, state, has_save = load_game_save(self.path, State, World)
        self.assertTrue(has_save)
        with patch("fishing.game.load_content", return_value=self.content):
            self.session = Session(world, self.path, state, True)
        self.session.ui.mode = "play"
        self.state, self.world = state, world

    def node(self):
        chat = self.session.conversation
        return chat.node_id if chat is not None else None

    def read(self, *choices):
        """Read the conversation on screen to its end, taking the listed choices. Returns its nodes."""
        self.assertEqual(self.session.ui.mode, "dialogue")
        seen, pending = [], list(choices)
        while self.session.conversation is not None:
            chat = self.session.conversation
            seen.append(chat.node_id)
            node = chat.node(self.content)
            if "choices" in node:
                index = next(i for i, c in enumerate(node["choices"]) if c["text"] == pending[0])
                pending.pop(0)
                self.press(str(index + 1))
            else:
                self.press("c")
        self.assertEqual(pending, [])
        self.assertEqual(self.session.ui.mode, "play")
        return seen

    def status(self, qid):
        progress = self.state.narrative.quests.get(qid)
        return progress.status if progress else "available"

    def set_first_line(self):
        """Set a real line, under the game's own rules, somewhere near the landing."""
        state, world = self.state, self.world
        slip = world.slip
        for radius in (70, 80, 90, 100, 60, 110):
            for k in range(24):
                angle = k * math.tau / 24
                state.x = slip.ox + radius * math.sin(angle)
                state.z = slip.oz + radius * math.cos(angle)
                state.yaw, state.speed = angle, 0.0
                if not world.navigable(state.x, state.z):
                    continue
                if state.try_set(world, 0, "worm") is None:
                    line = state.lines[-1]
                    mid = ((line.x0 + line.x1) / 2, (line.z0 + line.z1) / 2)
                    self.assertTrue(in_place("briar:landing_edge", "briar", *mid))
                    return
        self.fail("no legal line near the Briar landing")

    def emit(self, **event):
        event.setdefault("lake_id", self.world.id)
        event.setdefault("game_minute", self.state.game_minutes)
        self.state.emit_quest_event(event)

    def scout_and_catch(self):
        self.emit(type="bot.scout_complete", zone_id="briar:open", depth_class="middling",
                  report_delivered=True, x=self.state.x, z=self.state.z)
        self.emit(type="catch.resolved", species_id="bluegill", legendary=False, kept=True,
                  zone_id="briar:open", x=self.state.x, z=self.state.z, bait_id="worm", weight_lb=0.6,
                  catch_hour=7.0, in_cold_band=False)

    def hail_grandmother(self):
        self.session._refresh_npcs()
        gran = next(n for n in self.state.npcs if n.id == GRAN)
        self.state.x, self.state.z = gran.anchor.position
        self.state.speed = 0
        self.assertEqual(nearby_npc(self.state).id, GRAN)
        self.press("c")

    def play_prologue(self, note_choice="I'd love to."):
        self.new_morning()
        self.assertEqual(self.node(), "scene:pro_01")
        self.read()
        self.assertEqual(self.status("story_c0_s1"), "active")
        self.set_first_line()
        self.press("c")  # back in play, the scene whose moment came opens (a no-op key here)
        self.assertEqual(self.node(), "scene:pro_03")
        self.read()
        self.assertEqual(self.status("story_c0_s2"), "active")
        self.scout_and_catch()
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_04")
        self.read()
        self.hail_grandmother()
        self.assertEqual(self.node(), "scene:pro_05")
        return self.read(note_choice)

    # --- the prologue -------------------------------------------------------------------
    def test_a_new_game_opens_at_briar_with_the_arrival_scene(self):
        self.new_morning()
        self.assertEqual(self.world.id, "briar")
        self.assertEqual(self.state.lake_id, "briar")
        self.assertEqual(scene_state(self.state, "prologue"), "pending")
        self.assertEqual(self.node(), "scene:pro_01")
        self.assertEqual(scene_state(self.state, "pro_01"), "pending")
        seen = self.read()
        self.assertEqual(seen, ["scene:pro_01", "scene:pro_01:2", "scene:pro_01:3", "scene:pro_02"])
        self.assertEqual([scene_state(self.state, s) for s in ("pro_01", "pro_02")], ["done", "done"])
        # The first step starts with the arrival, never offered and never time-limited.
        self.assertEqual(self.status("story_c0_s1"), "active")
        self.assertEqual(self.status("story_c1_s1"), "available")

    def test_the_prologue_runs_from_a_new_game_to_chapter_one(self):
        seen = self.play_prologue("What kind of note?")
        self.assertEqual(seen[:3], ["scene:pro_05", "scene:pro_05:2", "scene:pro_05:3"])
        self.assertEqual(seen[3:], ["scene:pro_05b", "scene:pro_06", "scene:pro_06:2"])
        self.assertEqual([self.status(q) for q in STEPS], ["completed"] * 3)
        story = self.state.v2["story"]
        self.assertEqual(scene_state(self.state, "prologue"), "done")
        self.assertIn("prologue", story["scenes_seen"])
        self.assertEqual(story["chapter"], 1)
        self.assertNotIn(0, story.get("completed_chapters", []))
        self.assertEqual(self.status("story_c1_s1"), "active")  # "Talk to Pip & Pebble"
        for scene in PROLOGUE:
            self.assertEqual(scene_state(self.state, scene), "done", scene)
        self.assertEqual(sorted(q for q in self.state.narrative.reward_claims if q.startswith("story_c0")),
                         list(STEPS))
        self.assertIsNone(due_scene(self.state, self.content))

    def test_the_short_answer_skips_the_question(self):
        seen = self.play_prologue("I'd love to.")
        self.assertNotIn("scene:pro_05b", seen)
        self.assertIsNone(scene_state(self.state, "pro_05b"))
        self.assertEqual(scene_state(self.state, "prologue"), "done")

    def drawn_text(self):
        from .platform import Text
        from .ui import UI
        text = Text()
        self.addCleanup(text.close)
        renderer, drawn = UI(text, self.world), []
        original = renderer._text
        renderer._text = lambda frame, s, *args, **kw: (drawn.append(s), original(frame, s, *args, **kw))[1]
        renderer._dialogue(np.zeros((720, 1280, 3), np.uint8), self.state, self.session.ui)
        return drawn

    def test_a_scene_is_read_through_and_esc_does_not_leave_it(self):
        self.new_morning()
        self.press("esc")
        self.assertEqual(self.session.ui.mode, "dialogue")
        self.assertEqual(self.node(), "scene:pro_01")
        self.assertFalse(any("Esc" in line for line in self.drawn_text()))  # nor is it offered
        self.read()
        # An ordinary conversation still closes with Esc.
        self.hail_grandmother()
        self.assertEqual(self.node(), "story_c0_s1:dialogue:progress")
        self.assertTrue(any("Esc leave" in line for line in self.drawn_text()))
        self.press("esc")
        self.assertEqual(self.session.ui.mode, "play")

    def test_interrupting_every_scene_replays_it_and_pays_nothing_twice(self):
        self.new_morning()
        # pro_01: quit at its first bubble.
        self.reload()
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_01")
        self.assertEqual(scene_state(self.state, "pro_01"), "pending")
        self.press("c")
        self.press("c")
        self.press("c")
        self.assertEqual(self.node(), "scene:pro_02")  # pro_01 done; quit inside pro_02
        self.reload()
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_02")
        self.read()
        self.assertEqual(self.status("story_c0_s1"), "active")
        # pro_03 and pro_04 replay from their start; the steps they turn in wait for them.
        self.set_first_line()
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_03")
        self.reload()
        self.assertEqual(self.status("story_c0_s1"), "ready")
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_03")
        self.read()
        self.scout_and_catch()
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_04")
        self.reload()
        self.press("x")
        self.assertEqual(self.node(), "scene:pro_04")
        self.read()
        # pro_05 opens on a hail; quit there, then inside the branch, then inside pro_06.
        self.hail_grandmother()
        self.assertEqual(self.node(), "scene:pro_05")
        self.reload()
        self.press("x")
        self.assertIsNone(self.session.conversation)  # a hail scene waits for the hail
        self.hail_grandmother()
        self.assertEqual(self.node(), "scene:pro_05")
        for _ in range(2):
            self.press("c")
        self.press("2")  # "What kind of note?"
        self.assertEqual(self.node(), "scene:pro_05b")
        self.reload()
        self.hail_grandmother()
        self.assertEqual(self.node(), "scene:pro_05b")
        self.press("c")
        self.assertEqual(self.node(), "scene:pro_06")
        self.reload()
        self.assertEqual(self.status("story_c0_s3"), "ready")
        self.assertEqual(self.state.v2["story"]["chapter"], 0)
        self.hail_grandmother()
        self.assertEqual(self.read(), ["scene:pro_06", "scene:pro_06:2"])
        self.assertEqual(self.state.v2["story"]["chapter"], 1)
        claims = self.state.narrative.reward_claims
        self.assertEqual(sorted(q for q in claims if q.startswith("story_c0")), list(STEPS))
        self.assertEqual(len(claims), len(set(claims)))
        self.reload()
        self.assertEqual(self.state.v2["story"]["chapter"], 1)
        self.assertEqual(self.status("story_c1_s1"), "active")
        self.press("x")
        self.assertIsNone(self.session.conversation)

    def test_a_catch_before_bot_scouts_waits_for_the_next(self):
        self.new_morning()
        self.read()
        self.set_first_line()
        self.press("x")
        self.read()
        self.emit(type="catch.resolved", species_id="bluegill", legendary=False, kept=True, zone_id="briar:open",
                  x=self.state.x, z=self.state.z, bait_id="worm", weight_lb=0.6, catch_hour=7.0,
                  in_cold_band=False)
        self.assertEqual(self.status("story_c0_s2"), "active")  # Bot scouts first, as the journal says
        self.scout_and_catch()
        self.assertEqual(self.status("story_c0_s2"), "ready")

    def test_a_line_far_from_the_landing_does_not_count(self):
        self.new_morning()
        self.read()
        self.emit(type="line.set", line_id="00000000-0000-0000-0000-000000000034", tier_id="std",
                  hook_count=12, bait_id="worm", bait_sections=["worm"], zone_id="briar:deep",
                  x=self.world.slip.ox + 400, z=self.world.slip.oz, active_game_minute=1)
        self.assertEqual(self.status("story_c0_s1"), "active")

    def test_a_scene_waits_on_another_lake(self):
        self.new_morning()
        self.read()
        self.state.narrative.quests["story_c0_s1"].status = "ready"
        self.state.lake_id = "cedar"
        self.assertIsNone(due_scene(self.state, self.content))
        self.assertIsNone(hail_scene(self.state, self.content, GRAN))
        self.state.lake_id = "briar"
        self.assertEqual(due_scene(self.state, self.content), "pro_03")

    # --- the scene engine (Codex review of PR 108) ---------------------------------------------
    def authored(self, *scenes):
        content = deepcopy(self.content)
        content.scenes = {row["id"]: {"speaker_id": GRAN, "lake_id": "briar", **row} for row in scenes}
        return content

    def test_a_chained_scene_speaks_in_its_own_voice(self):
        content = self.authored({"id": "pro_07", "lines": ["Pip will tell you."], "next": "pro_08"},
                                {"id": "pro_08", "speaker_id": "pip_pebble", "lines": ["Hi!"], "next": None})
        state = State.new(World("briar"), seed=8)
        chat = scene_conversation(state, content, "pro_07")
        self.assertEqual(chat.npc_id, GRAN)
        self.assertTrue(chat.advance(state, content))
        self.assertEqual((chat.node_id, chat.npc_id), ("scene:pro_08", "pip_pebble"))  # name and portrait

    def test_a_choice_that_ends_the_scene_is_not_resumed_into_the_other(self):
        content = self.authored({"id": "pro_07", "lines": ["Shall I go on?"],
                                 "choices": [{"text": "Not now.", "next": None},
                                             {"text": "Go on.", "next": "pro_08"}]},
                                {"id": "pro_08", "lines": ["Well then."], "next": None})
        for index, expected in ((0, None), (1, "pro_08")):
            state = State.new(World("briar"), seed=9)
            chat = scene_conversation(state, content, "pro_07")
            chat.selected = index
            chat.advance(state, content)
            self.assertEqual(scene_state(state, "pro_07"), "done")
            self.assertEqual(resume(state, content, "pro_07"), expected, index)

    # --- saves --------------------------------------------------------------------------
    def test_saves_without_a_new_game_never_start_the_prologue(self):
        # Older saves and test states have no prologue state; nothing plays or starts.
        state = State.new(World("briar"), seed=3)
        self.assertIsNone(due_scene(state, self.content))
        self.assertIsNone(hail_scene(state, self.content, GRAN))

    def test_a_save_whose_prologue_is_done_opens_chapter_one(self):
        state = State.new(World("briar"), seed=4)
        state.set_scene_status("prologue", "done")  # a migrated save with catches (06 §3.3)
        with patch("fishing.game.load_content", return_value=self.content):
            Session(World("briar"), self.path, state, True)
        self.assertEqual(state.v2["story"]["chapter"], 1)
        self.assertEqual(state.narrative.quests["story_c1_s1"].status, "active")
        self.assertIsNone(state.narrative.quests.get("story_c0_s1"))  # the prologue's steps never start
        self.assertIsNone(due_scene(state, self.content))

    # --- the script ---------------------------------------------------------------------
    def test_the_scenes_are_the_script(self):
        """Every bubble of 05 §1, in order, speaker by speaker; a second voice is prefixed."""
        text = SCRIPT.read_text(encoding="utf-8")
        section = text[text.index("## 1. Prologue"):text.index("## 2. Chapters")]
        blocks = re.split(r"^`(pro_\w+)`", section, flags=re.M)[1:]
        script = {}
        for sid, body in zip(blocks[::2], blocks[1::2]):
            bubbles = []
            for match in re.finditer(r"\*\*([^*]+):\*\* (.+?)(?=\n\*\*|\n`|\n\*Choices|\n→|\n\n|\Z)", body, re.S):
                speaker, line = match.group(1), " ".join(match.group(2).split())
                line = line.replace("*", "")
                bubbles.append(line if speaker != "Bot" else "Bot: " + line)
            script[sid] = bubbles
        self.assertEqual(sorted(script), sorted(PROLOGUE))
        for sid in PROLOGUE:
            lines = self.content.scenes[sid]["lines"]
            self.assertEqual(lines if isinstance(lines, list) else [lines], script[sid], sid)
        choices = [c["text"] for c in self.content.scenes["pro_05"]["choices"]]
        self.assertEqual(choices, ["I'd love to.", "What kind of note?"])


class SceneValidation(unittest.TestCase):
    """Every scene must end, and say only what the script allows (05 §0)."""

    def errors(self, scenes):
        raw = {name: (dict(doc) if isinstance(doc, dict) else doc) for name, doc in CONTENT_V2_RAW.items()}
        raw["quests.json"] = {**CONTENT_V2_RAW["quests.json"], "scenes": scenes}
        try:
            validate_content_v2(raw)
        except ContentError as exc:
            return [line for line in str(exc).splitlines() if "scenes" in line]
        return []

    def scene(self, sid, **extra):
        return {"id": sid, "speaker_id": GRAN, "lake_id": "briar", "lines": ["Hello, dear."], **extra}

    def test_the_shipped_scenes_validate(self):
        self.assertEqual(self.errors(CONTENT_V2_RAW["quests.json"]["scenes"]), [])

    def test_bad_scenes_are_rejected(self):
        cases = {
            "loops back": [self.scene("pro_01", next="pro_02"), self.scene("pro_02", next="pro_01")],
            "unknown scene": [self.scene("pro_01", next="pro_09")],
            "not both": [self.scene("pro_01", next=None, choices=[{"text": "Yes.", "next": None}])],
            "unknown value/reference": [{**self.scene("pro_01"), "speaker_id": "nobody"}],
            "expected pro_NN": [self.scene("prologue_one")],
            "longer than 140": [{**self.scene("pro_01"), "lines": ["a" * 141]}],
            "one to 3 bubbles": [{**self.scene("pro_01"), "lines": ["a", "b", "c", "d"]}],
            "longer than 60": [self.scene("pro_01", choices=[{"text": "a" * 61, "next": None}])],
            "unknown placeholder": [{**self.scene("pro_01"), "lines": ["Hi, {Name}."]}],
            # Malformed values are reported, never raised while following the scene graph.
            "one to three choices": [self.scene("pro_01", choices=None)],
            "unknown scene ['pro_02']": [self.scene("pro_01", next=["pro_02"]), self.scene("pro_02")],
            "unknown scene {'a': 1}": [self.scene("pro_01", choices=[{"text": "Yes.", "next": {"a": 1}}])],
            "unknown value/reference 'granny'": [self.scene("story_c4_knot", choices=[{"text": "Granny", "next": None, "knot": "granny"}])],
            "optionally one of knot, together or trip": [self.scene("story_c4_knot", choices=[{"text": "Bow", "next": None, "colour": "red"}])],
            "one of knot, together or trip": [self.scene("story_c5_drawn", choices=[
                {"text": "Home", "next": None, "trip": "briar", "together": True}])],
            "expected true": [self.scene("story_c5_together", choices=[{"text": "Watch", "next": None, "together": False}])],
            "unknown value/reference 'mars'": [self.scene("story_c5_drawn", choices=[{"text": "Go", "next": None, "trip": "mars"}])],
        }
        for expected, scenes in cases.items():
            with self.subTest(expected):
                found = self.errors(scenes)
                self.assertTrue(any(expected in line for line in found), found)

    def test_a_branch_that_rejoins_is_not_a_loop(self):
        scenes = [self.scene("pro_05", choices=[{"text": "Yes.", "next": "pro_06"}, {"text": "Why?", "next": "pro_05b"}]),
                  self.scene("pro_05b", next="pro_06"), self.scene("pro_06")]
        self.assertEqual(self.errors(scenes), [])


if __name__ == "__main__":
    unittest.main()
