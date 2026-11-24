"""Issue #156: Bot explains time scaling after Grandmother's first conversation.

The explanation fires once, when her conversation closes, in Bot's voice and
with the remapped key. It persists across a reload, and the older generic
notice stays silent once Bot has spoken.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

from .game import Session
from .sim import SetLine, State
from .world import World


def _session(world, state):
    session = Session(world, Path("/tmp/trotline-time-tip.json"), state, False)
    session.ui.mode = "play"
    session.ui.dialogue_from = "play"
    return session


class BotTimeTip(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.state = State.new(self.world, seed=156)

    def _close_as(self, session, npc_id):
        session.conversation = SimpleNamespace(npc_id=npc_id)
        session._close_dialogue()

    def test_grandmothers_close_explains_time_once(self):
        session = _session(self.world, self.state)
        self._close_as(session, "grandmother_whiskers")
        tips = [t for t in self.state.toasts if t[0].startswith("Bot: Anchor")]
        self.assertEqual(len(tips), 1)
        self.assertIn("press T", tips[0][0])
        self.assertTrue(self.state.time_tip_given())

        self._close_as(session, "grandmother_whiskers")
        tips = [t for t in self.state.toasts if t[0].startswith("Bot: Anchor")]
        self.assertEqual(len(tips), 1, "the tip fired twice")

    def test_other_cats_do_not_trigger_it(self):
        session = _session(self.world, self.state)
        self._close_as(session, "elder_moss")
        self.assertFalse(self.state.time_tip_given())

    def test_the_tip_uses_the_remapped_key(self):
        self.state.v2["settings"]["key_bindings"]["time_scale"] = "y"
        session = _session(self.world, self.state)
        self._close_as(session, "grandmother_whiskers")
        tip = next(t[0] for t in self.state.toasts if t[0].startswith("Bot: Anchor"))
        self.assertIn("press Y", tip)
        self.assertNotIn("press T", tip)

    def test_the_tip_survives_reload_and_does_not_refire(self):
        session = _session(self.world, self.state)
        self._close_as(session, "grandmother_whiskers")
        session.save()
        loaded = State.load(session.save_path, self.world)
        self.assertTrue(loaded.time_tip_given())
        again = _session(self.world, loaded)
        self._close_as(again, "grandmother_whiskers")
        self.assertFalse(any(t[0].startswith("Bot: Anchor") for t in loaded.toasts))

    def test_generic_notice_stays_silent_once_bot_explained(self):
        self.state.mark_time_tip()
        self.state.tutorial = 1
        self.state.lines = [SetLine("std", "worm", 0, 0, 1, 0, "open", [])]
        before = len(self.state.toasts)
        self.state._tutorial()
        self.assertEqual(self.state.tutorial, 2)
        self.assertEqual(len(self.state.toasts), before)


if __name__ == "__main__":
    unittest.main()
