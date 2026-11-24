"""Issue #155: Bot gameplay toasts hold longer, and menus pause the timer.

Bot-authored notices (the ``Bot:`` prefix) stay up a few seconds past the
normal reading time, still bounded by the reading cap. A toast hidden by a
menu does not count down, so closing the menu leaves its full time.
"""
import unittest
from pathlib import Path

from .game import Keys, Session
from .reading import READ_MAX_SECONDS, reading_seconds
from .sim import BOT_TOAST_BONUS, State
from .world import World


class BotToastTiming(unittest.TestCase):
    def test_bot_toasts_hold_longer_but_stay_bounded(self):
        state = State.new(World(), seed=155)
        state.toast("Bot: The flats were quiet this morning.")
        state.toast("Saved.")
        bot, saved = state.toasts[-2][1], state.toasts[-1][1]
        self.assertEqual(saved, 4.8)
        expected = min(READ_MAX_SECONDS,
                       reading_seconds("Bot: The flats were quiet this morning.", 4.8)
                       + BOT_TOAST_BONUS)
        self.assertAlmostEqual(bot, expected)
        self.assertGreater(bot, saved)
        self.assertLessEqual(bot, READ_MAX_SECONDS)

    def test_a_long_bot_toast_still_respects_the_cap(self):
        state = State.new(World(), seed=155)
        state.toast("Bot: " + "word " * 40)
        self.assertEqual(state.toasts[-1][1], READ_MAX_SECONDS)

    def test_a_menu_pauses_the_toast_timer(self):
        world = World()
        state = State.new(world, seed=155)
        session = Session(world, Path("/tmp/trotline-toast.json"), state, False)
        session.ui.mode = "play"
        session.focused = True
        state.toast("Bot: Fish on. I'm staying with it.")
        before = state.toasts[-1][1]

        session.ui.mode = "pause"
        for _ in range(20):
            session.tick(Keys(), 0.25)
        self.assertEqual(state.toasts[-1][1], before, "a hidden toast lost time")

        session.ui.mode = "play"
        session.tick(Keys(), 0.25)
        self.assertLess(state.toasts[-1][1], before)




if __name__ == "__main__":
    unittest.main()
