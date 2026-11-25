"""Bot comes home by himself when the line he is watching is pulled, and only then.

Covers pulls while running out and while watching, unrelated pulls, a line with fish
on it, a livewell too full to take them, recall before the pull, a replacement
line, open-water scouting, and the save round trip.
"""
import tempfile
import unittest
from pathlib import Path

from . import bot
from .sim import Catch, Hook, SetLine, State
from .world import World

COMING = "Bot: Line's in. Coming aboard."


class BotReboardsOnWatchedPull(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        self.state = State.new(self.world, seed=87)
        self.state.x = self.state.z = self.state.yaw = 0
        self.state.lines = [self.line(10), self.line(40)]

    @staticmethod
    def line(z):
        return SetLine("std", "worm", 0, z, 0, z + 20, "open", [Hook(True) for _ in range(12)])

    def toasts(self, text=COMING):
        return [t for t, _ in self.state.toasts].count(text)

    def send_out(self, settle=True):
        """Launch Bot to the nearest line; with `settle`, tick until he is watching it."""
        self.assertEqual(bot.summon(self.state, self.world), "bot")
        target = self.state.bot_target_line_id
        self.assertEqual(target, self.state.lines[0].line_id)
        for _ in range(400 if settle else 0):
            if self.state.bot_phase == "out":
                break
            bot.tick(self.state, self.world, 0.05)
        if settle:
            self.assertEqual(self.state.bot_phase, "out")
        return target

    def ride_home(self):
        for _ in range(800):
            if self.state.bot_phase == "home":
                return
            bot.tick(self.state, self.world, 0.05)
        self.fail("Bot never climbed aboard")

    def index_of(self, line_id):
        return next(i for i, line in enumerate(self.state.lines) if line.line_id == line_id)

    def test_pulling_the_watched_line_brings_him_aboard_without_a_recall(self):
        target = self.send_out()
        self.assertIsNone(self.state.pull_line(self.index_of(target)))
        self.assertEqual(self.state.bot_phase, "back")
        self.assertIsNone(self.state.bot_target_line_id)
        self.assertEqual(self.toasts(), 1)
        self.ride_home()
        self.assertEqual(self.state.bot_phase, "home")

    def test_pulling_while_he_is_still_running_out_turns_him_round(self):
        target = self.send_out(settle=False)
        self.assertEqual(self.state.bot_phase, "go")
        self.state.pull_line(self.index_of(target))
        self.assertEqual(self.state.bot_phase, "back")

    def test_pulling_a_different_line_leaves_him_watching(self):
        target = self.send_out()
        other = next(line.line_id for line in self.state.lines if line.line_id != target)
        self.state.pull_line(self.index_of(other))
        self.assertEqual(self.state.bot_phase, "out")
        self.assertEqual(self.state.bot_target_line_id, target)
        self.assertEqual(self.toasts(), 0)

    def test_a_line_with_fish_on_is_emptied_then_brings_him_home(self):
        target = self.send_out()
        line = self.state.lines[self.index_of(target)]
        line.hooks[0] = Hook(False, Catch("bluegill", 0.4, 0.9, 1.0, "open", "worm", 3, "briar"))
        self.assertIsNone(self.state.pull_line(self.index_of(target)))
        self.assertEqual(self.state.bot_phase, "back")

    def test_a_pull_refused_by_a_full_livewell_keeps_him_out(self):
        target = self.send_out()
        line = self.state.lines[self.index_of(target)]
        fish = Catch("bluegill", 0.4, 0.9, 1.0, "open", "worm", 3, "briar")
        fish.disposition = "keep"  # the player chose Keep, so the full livewell refuses it
        line.hooks[0] = Hook(False, fish)
        self.state.well = [Catch("bluegill", self.state.well_cap(), 0.9, 1.0, "open", "worm", 3, "briar")]
        self.assertIsNotNone(self.state.pull_line(self.index_of(target)))
        self.assertEqual(self.state.bot_phase, "out")
        self.assertEqual(self.state.bot_target_line_id, target)

    def test_recall_before_the_pull_is_one_trip_home_not_two(self):
        target = self.send_out()
        bot.summon(self.state, self.world)
        self.assertEqual(self.state.bot_phase, "back")
        self.state.pull_line(self.index_of(target))
        self.assertEqual(self.state.bot_phase, "back")
        self.assertEqual(self.toasts(), 0)
        self.ride_home()
        # Aboard again, a later pull of the other line moves nobody.
        self.state.pull_line(0)
        self.assertEqual(self.state.bot_phase, "home")

    def test_a_replacement_line_in_the_same_water_is_not_his_line(self):
        target = self.send_out()
        self.state.pull_line(self.index_of(target))
        self.ride_home()
        self.state.lines.insert(0, self.line(10))
        self.assertNotEqual(self.state.lines[0].line_id, target)
        self.state.pull_line(0)
        self.assertEqual(self.state.bot_phase, "home")
        self.assertEqual(self.toasts(), 1)

    def test_scouting_open_water_ignores_line_pulls(self):
        self.state.lines = []
        bot.summon(self.state, self.world)
        self.assertIsNone(self.state.bot_target_line_id)
        self.state.lines = [self.line(10)]
        self.state.pull_line(0)
        self.assertEqual(self.state.bot_phase, "go")

    def test_the_trip_home_survives_save_and_load(self):
        target = self.send_out()
        self.state.pull_line(self.index_of(target))
        with tempfile.TemporaryDirectory(prefix="bot-reboard-") as temp:
            path = Path(temp) / "save.json"
            self.state.save(path)
            loaded = State.load(path, self.world)
        self.assertEqual(loaded.bot_phase, "back")
        self.assertIsNone(loaded.bot_target_line_id)
        self.assertEqual(len(loaded.lines), 1)


if __name__ == "__main__":
    unittest.main()
