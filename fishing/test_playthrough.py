"""V1-34 (#62) acceptance: a scripted playthrough from a new save reaches the credits, and
interrupting at every scene and reloading replays the scene without duplicating rewards.

One new game is played through the title's "New morning", the prologue, all five chapters,
the ending and the credits, by real keys, hails, events and travel. At the first bubble of
every scene (and at the credits), the game is quit and the save continued in a new session.
The scene must be pending, with no reward paid, and it must replay from its start.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .botidentity import book_credit, profile
from .content import load_content
from .dialogue import nearby_npc
from .game import Keys, Session
from .quests import scene_state
from .sim import State
from . import test_prologue
from .test_story import StoryPlay
from .world import World

SCENES = {"pro_01", "pro_02", "pro_03", "pro_04", "pro_05", "pro_05b", "pro_06",
          "story_c3_cold", "story_c4_clear", "story_c4_knot", "story_c4_tied",
          "story_c5_arrive", "story_c5_together", "story_c5_whale", "story_c5_drawn",
          "end_01", "end_01b", "end_02", "end_03"}


class Playthrough(StoryPlay):
    """The chapter helpers of test_story, from a new save, with an interruption at every scene."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("cedar")
        self.state = State.new(self.world, seed=62)
        with patch("fishing.game.load_content", return_value=self.content):
            self.session = Session(self.world, self.path, self.state, False)
        self.interrupted = []
        self.opened_by = None

    # --- reading, with an interruption at each scene's first bubble --------------------------
    def reload(self):
        super().reload()
        self.world = self.session.world

    def interrupt(self, sid):
        """Quit at this scene's first bubble and continue: it is pending and has paid nothing."""
        node = self.session.conversation.node_id
        claims = list(self.state.narrative.reward_claims)
        money, tools = self.state.money, list(profile(self.state)["tools"])
        self.reload()
        self.assertEqual(scene_state(self.state, sid), "pending", sid)
        self.assertEqual(self.state.narrative.reward_claims, claims, sid)
        self.assertEqual((self.state.money, profile(self.state)["tools"]), (money, tools), sid)
        self.interrupted.append(sid)
        if self.opened_by == "auto":
            self.press("x")
        else:
            self.hail(self.opened_by)
        self.assertIsNotNone(self.session.conversation, f"{sid} did not replay")
        self.assertEqual(self.session.conversation.node_id, node, f"{sid} did not replay from its start")

    def read_keys(self, *actions):
        """Read the open conversation with the dialogue keys; a choice is picked by its action or
        text. Without one left, an ordinary conversation is left with Esc. Returns the nodes."""
        seen, pending, chat = [], list(actions), self.session.conversation
        while self.session.conversation is chat:  # a scene due as this one ends is left open
            node = chat.node(self.content)
            sid = node.get("scene_start")
            if sid and sid not in self.interrupted:
                self.interrupt(sid)
                chat = self.session.conversation
                node = chat.node(self.content)
            seen.append(chat.node_id)
            if "choices" in node:
                if not pending:
                    self.press("esc")
                    break
                wanted = pending.pop(0)
                index = next(i for i, c in enumerate(node["choices"]) if wanted in (c["action"], c["text"]))
                self.press(str(index + 1))
            else:
                self.press("c")
        self.assertEqual(pending, [])
        return seen

    def hail(self, npc_id):
        npc = self.present(npc_id)
        self.assertIsNotNone(npc, npc_id)
        self.state.x, self.state.z = npc.anchor.position
        self.assertEqual(nearby_npc(self.state).id, npc_id)
        self.state.speed = 0
        self.session.ui.mode = "play"
        self.press("c")

    def talk(self, npc_id, *choices):
        self.hail(npc_id)
        self.assertIsNotNone(self.session.conversation, f"{npc_id} only waved")
        self.opened_by = npc_id
        return self.read_keys(*choices)

    def scene(self, *choices):
        self.press("x")
        self.assertEqual(self.session.ui.mode, "dialogue", "no scene played")
        self.opened_by = "auto"
        return self.read_keys(*choices)

    def wait(self, seconds, step=5.0):
        for _ in range(int(seconds / step)):
            self.session.tick(Keys(), step)
            if self.session.conversation is not None:
                return  # a scene's moment came (Astra-9 drifts alongside)

    # --- the prologue, as test_prologue plays it ---------------------------------------------
    set_first_line = test_prologue.Prologue.set_first_line
    scout_and_catch = test_prologue.Prologue.scout_and_catch

    def play_prologue(self):
        self.session.ui.mode, self.session.ui.new_mode_i = "new_mode", 0
        self.press("return")
        self.state, self.world = self.session.state, self.session.world
        self.assertEqual(self.session.conversation.node_id, "scene:pro_01")
        self.opened_by = "auto"
        self.read_keys()
        self.set_first_line()
        self.scene()
        self.scout_and_catch()
        self.scene()
        self.assertIsNone(self.state.pull_line(0))  # the first line comes aboard before any trip
        self.talk("grandmother_whiskers", "What kind of note?")
        self.assertEqual(self.state.v2["story"]["chapter"], 1)

    def play_chapter_five(self, together=True):
        self.travel("nebula")
        self.scene()
        self.talk("astra_9", "turn_in")
        self.settle_by_the_reflection()
        self.press("c")
        self.wait(15)
        self.opened_by = "auto"
        self.read_keys("Watch together")
        if not self.session.ui.settling:
            self.press("c")  # a reload ended the settling; going on from the progress kept
        self.wait(30)
        self.assertEqual(self.status("story_c5_s2"), "ready")
        self.scene("Draw it", "Go home to Briar Landing")
        self.world = self.session.world
        self.assertEqual(self.world.id, "briar")

    def test_a_new_save_reaches_the_credits_and_every_scene_survives_a_reload(self):
        self.play_prologue()
        self.play_chapter_one()
        self.play_chapter_two()
        self.play_chapter_three()
        self.play_chapter_four()
        self.play_chapter_five()
        self.scene()  # the ending, end_01 to end_03
        # The credits roll once; a game quit during them rolls them again.
        self.press("x")
        self.assertEqual(self.session.ui.mode, "credits")
        self.reload()
        self.press("x")
        self.assertEqual(self.session.ui.mode, "credits")
        self.press("return")  # too soon: the credits hold
        self.assertEqual(self.session.ui.mode, "credits")
        self.session.tick(Keys(), 3.0)
        self.press("return")
        self.assertEqual(self.session.ui.mode, "play")
        self.press("x")  # then the book shows its new title, once
        self.assertEqual((self.session.ui.mode, self.session.ui.book_ceremony), ("journal", "book_of_five_waters"))
        self.press("esc")
        self.reload()
        self.press("x")
        self.assertEqual(self.session.ui.mode, "play")
        self.assertIsNone(self.session.conversation)

        self.assertEqual(set(self.interrupted), SCENES)
        self.assertEqual(len(self.interrupted), len(SCENES))  # each interrupted once, none replayed twice
        story = self.state.v2["story"]
        self.assertEqual(story["completed_chapters"], [1, 2, 3, 4, 5])
        self.assertEqual(story["chapter"], 6)
        for sid in SCENES | {"prologue", "ending", "credits"}:
            self.assertEqual(scene_state(self.state, sid), "done", sid)
        steps = [f"story_c{c}_s{s}" for c in range(6) for s in (1, 2, 3)]
        claims = self.state.narrative.reward_claims
        self.assertEqual(len(claims), len(set(claims)))
        self.assertEqual(sorted(q for q in claims if q.startswith("story_")), sorted(steps))
        me = profile(self.state)
        self.assertEqual(sorted(me["shells"]), sorted(["tin", "frog", "duck", "sub", "astral"]))
        self.assertEqual(sorted(me["tools"]), sorted(["reed_anchor", "thermo_scanner"]))  # the story's gifts
        self.assertEqual(me["collar"]["stage"], "favorite")
        self.assertEqual(self.state.v2["book"]["title"], "book_of_five_waters")
        self.assertEqual(book_credit(self.state), "the Skipper & " + me["bot_name"])
        self.assertTrue({"travel:flathead", "travel:crater", "travel:nebula", "chart:reeds"}
                        <= set(self.state.v2["unlocks"]))
        self.assertEqual(self.state.v2["npcs"]["letters"], [])  # story givers queue no letters


if __name__ == "__main__":
    unittest.main()
