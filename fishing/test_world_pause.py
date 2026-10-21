"""Long-frame clock, NPC, fishing, quest, and focus pause regressions."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from .game import Keys, Session
from .narrative import QUEST_IDS
from .sim import Hook, SetLine, State
from .world import World


class WorldPauseChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="briar-world-pause-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "save.json"
        self.state = State.new(self.world, seed=87)
        self.state.game_minutes = 800
        self.state.minute_acc = 0.0
        self.state.time_scale = 12
        self.state.anchored = True
        self.state.throttle = 0.0
        self.state.throttle_setting = 0.0
        self.state.lines = [SetLine(
            "std", "worm", 0, 10, 0, 30, "open", [Hook(True) for _ in range(12)]
        )]
        self.state.narrative.active_play_game_minutes = 7.0
        timed_quest = self.state.narrative.quests[QUEST_IDS[6]]
        timed_quest.status = "active"
        timed_quest.accepted_game_minute = 100.0
        timed_quest.progress = {"continuous_game_minutes": 15.0}
        inlet = self.world.anchors["briar:inlet"]
        self.state.x, self.state.z = inlet.position
        self.session = Session(self.world, self.path, self.state, False)

    def snapshot(self):
        return {
            "save": deepcopy(self.state.to_json()),
            "anim": self.state.anim,
            "minute_acc": self.state.minute_acc,
            "npcs": tuple((npc.id, npc.anchor.id) for npc in self.state.npcs),
        }

    def tick_for_five_minutes(self, keys_factory=Keys):
        # The game's real loop caps each frame at 0.25 seconds.
        for _ in range(1200):
            self.session.tick(keys_factory(), 0.25)

    def test_every_world_menu_freezes_300_seconds_of_simulation(self):
        self.state.x, self.state.z = self.state.npcs[1].anchor.position
        self.session._hail()
        self.assertEqual(self.session.ui.mode, "dialogue")
        modes = (
            "dialogue", "shop", "journal", "book", "map", "pause", "help",
            "settings", "kitchen", "scene", "well", "setbait", "check", "title",
        )

        for mode in modes:
            with self.subTest(mode=mode):
                self.session.ui.mode = mode
                if mode == "journal":
                    self.session.ui.journal_page = 1
                before = self.snapshot()
                self.tick_for_five_minutes()
                self.assertFalse(self.session.world_running())
                self.assertEqual(self.snapshot(), before)

    def test_window_focus_loss_freezes_300_seconds_and_resumes_on_focus(self):
        self.session.ui.mode = "play"
        before = self.snapshot()
        self.tick_for_five_minutes(lambda: Keys(focused=False))
        self.assertFalse(self.session.world_running())
        self.assertEqual(self.snapshot(), before)

        self.session.tick(Keys(focused=True), 0.25)
        self.assertTrue(self.session.world_running())
        self.assertEqual(self.state.game_minutes, before["save"]["game_minutes"] + 3)

    def test_bulk_advance_hook_counts_time_and_updates_quest_timers(self):
        self.session.ui.mode = "play"
        quest = self.state.narrative.quests[QUEST_IDS[6]]
        quest.progress["continuous_game_minutes"] = 0.0
        before = self.state.game_minutes
        active_before = self.state.narrative.active_play_game_minutes

        hooked, spoiled = self.session.advance_bulk(120)

        self.assertGreaterEqual(hooked, 0)
        self.assertGreaterEqual(spoiled, 0)
        self.assertEqual(self.state.game_minutes, before + 120)
        self.assertEqual(self.state.narrative.active_play_game_minutes, active_before + 120)
        self.assertEqual(quest.progress["continuous_game_minutes"], 120)
        self.assertEqual(quest.status, "ready")

    def test_bulk_advance_hook_does_not_run_from_a_menu(self):
        self.session.ui.mode = "journal"
        before = self.snapshot()
        self.assertEqual(self.session.advance_bulk(120), (0, 0))
        self.assertEqual(self.snapshot(), before)

    def test_chart_menu_cannot_trigger_the_tow_time_jump(self):
        self.session.ui.mode = "map"
        before = self.snapshot()
        self.session.tick(Keys(pressed=("r",)), 0.25)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
