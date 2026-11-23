"""Offline soak caps by mode (#140): lines fish up to 72 real hours in Cozy, 36 in Old Salt.

`State.catch_up` replays the real seconds since the save's stamp as game minutes, up to the
loaded save's mode cap (`comfort.offline_soak_seconds`). These checks pin each cap just under,
at and past its boundary, follow the mode through save, reload and the title's Continue, and
read a missing or unknown mode as Cozy. They also hold what the cap must not change: a shorter
absence replays exactly and alike in both modes, hooked fish get away by the 13-game-hour rule,
nothing is sold, Old Salt needs, active play and quest clocks stay put, calendar plans roll
forward without social replay, and a full boat's 72-hour soak replays the same every time.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import calendar, comfort
from .data import SPOIL_HOURS
from .game import Keys, Session
from .narrative import QUEST_IDS
from .sim import Catch, Hook, SetLine, State
from .world import World

HOUR = 3600  # real seconds; offline, each real second replays one game minute
COZY_CAP = 72 * HOUR
OLD_SALT_CAP = 36 * HOUR
START = 1_000.0  # the stamp every soak here starts from, epoch seconds
SOCIAL = ("cookout_gifts", "cookout_chats", "invitation_day", "lake_day_notes")
# Briar anchors that take a 60 m line in open water, one per line of a full boat.
SPOTS = ("deep", "flats", "lilies", "inlet", "open", "rocks", "cypress", "mail_mooring")


class OfflineSoakChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="trotline-offline-soak-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "save.json"

    def soaker(self, mode, lines=()):
        """A new Briar game in `mode` with `lines` set and no toasts, last saved at START."""
        state = State.new(self.world, seed=140)
        comfort.change_mode(state.v2, mode)
        state.lines = list(lines)
        state.toasts.clear()
        state.stamp = START
        return state

    def lines(self, count=3, tier="std", hooks=12):
        """`count` baited lines of `hooks` hooks in Briar's open water, 60 m each.

        Line ids are fixed, so twin states save alike."""
        out = []
        for k, spot in enumerate(SPOTS[:count]):
            x, z = self.world.anchors[f"briar:{spot}"].position
            out.append(SetLine(tier, ["worm", "shad", "liver"], x - 30, z, x + 30, z,
                               self.world.zone_at(x, z), [Hook(True) for _ in range(hooks)],
                               line_id=f"soak-{k}"))
        return out

    @staticmethod
    def soak(state, seconds):
        """Catch `state` up `seconds` real seconds past its stamp; the game minutes replayed."""
        before = state.game_minutes
        state.catch_up(now=state.stamp + seconds)
        return state.game_minutes - before

    def test_the_cap_is_72_real_hours_in_cozy_and_36_in_old_salt(self):
        cases = (
            ({}, COZY_CAP),
            ({"mode": "cozy"}, COZY_CAP),
            ({"mode": "old_salt"}, OLD_SALT_CAP),
            ({"settings": {"mode": "old_salt"}}, OLD_SALT_CAP),
            # Settings hold the live choice, so they win over the top-level copy.
            ({"mode": "cozy", "settings": {"mode": "old_salt"}}, OLD_SALT_CAP),
            ({"mode": "old_salt", "settings": {"mode": "cozy"}}, COZY_CAP),
            ({"mode": "old_salt", "settings": {"mode": "hardcore"}}, OLD_SALT_CAP),
            ({"mode": "hardcore"}, COZY_CAP),
            ({"mode": None, "settings": []}, COZY_CAP),
        )
        for v2, cap in cases:
            with self.subTest(v2=v2):
                self.assertEqual(comfort.offline_soak_seconds(v2), cap)

    def test_each_mode_soaks_up_to_its_cap_and_no_further(self):
        for mode, cap in (("cozy", COZY_CAP), ("old_salt", OLD_SALT_CAP)):
            for away, replayed in ((cap - 1, cap - 1), (cap, cap), (cap + 1, cap),
                                   (30 * 24 * HOUR, cap)):
                with self.subTest(mode=mode, away=away):
                    state = self.soaker(mode)
                    self.assertEqual(self.soak(state, away), replayed)
                    # The time past the cap is skipped, never owed to a later catch-up.
                    self.assertEqual(state.stamp, START + away)

    def test_a_shorter_absence_replays_exactly_and_alike_in_both_modes(self):
        away = 2 * HOUR + 13 * 60 + 7.9  # 133 game hours and 7 minutes; the fraction drops
        outcomes = []
        for mode in ("cozy", "old_salt"):
            state = self.soaker(mode, self.lines())
            self.assertEqual(self.soak(state, away), 133 * 60 + 7)
            self.assertEqual(state.stamp, START + away)
            self.assertGreater(state.hooked_total, 0)
            saved = state.to_json()
            outcomes.append((saved["seed"], saved["lines"], saved["journal"],
                             saved["v2"]["book"], saved["v2"]["calendar"], state.toasts))
        self.assertEqual(outcomes[0], outcomes[1])

    def test_hooked_fish_get_away_by_the_13_game_hour_rule_not_the_cap(self):
        # A fish on the hook at closing gets away 13 game hours later, 13 real minutes into
        # the absence, in either mode; the cap only ends the replay.
        spoil_s = int(SPOIL_HOURS * 60)
        x, z = self.world.anchors["briar:deep"].position
        for mode, cap in (("cozy", COZY_CAP), ("old_salt", OLD_SALT_CAP)):
            for away, kept in ((spoil_s - 1, True), (spoil_s, False), (cap + HOUR, False)):
                with self.subTest(mode=mode, away=away):
                    state = self.soaker(mode)
                    hook = Hook(False, Catch("bluegill", 1.0, 1.0, 0.0, "deep", "worm", 6.0,
                                             catch_game_minute=state.game_minutes))
                    state.lines = [SetLine("std", "worm", x - 6, z, x + 6, z, "deep", [hook],
                                           line_id="soak-0")]
                    self.assertEqual(self.soak(state, away), min(away, cap))
                    if kept:
                        self.assertAlmostEqual(hook.catch.age, 12 + 59 / 60)
                        self.assertLess(hook.catch.age, SPOIL_HOURS)
                        self.assertEqual(state.toasts, [])
                    else:
                        self.assertIsNone(hook.catch)
                        self.assertFalse(hook.baited)
                        self.assertEqual(state.toasts[-1][0],
                                         "While you were away: 0 hooked, 1 got away.")

    def test_a_capped_soak_keeps_needs_timers_sales_and_social_calendar(self):
        for mode, cap in (("old_salt", OLD_SALT_CAP), ("cozy", COZY_CAP)):
            with self.subTest(mode=mode):
                state = self.soaker(mode, self.lines())
                state.money, state.earned, state.spent = 321, 654, 333
                state.v2["needs"].update({"awake_h": 11.5, "since_meal_h": 20.25})
                state.well.append(Catch("bluegill", 1.2, 1.0, 0.0, "flats", "worm", 7.0,
                                        catch_game_minute=state.game_minutes))
                before = deepcopy(state.to_json())
                active = state.narrative.active_play_game_minutes

                self.assertEqual(self.soak(state, cap + 6 * HOUR), cap)

                after = state.to_json()
                for key in ("money", "earned", "spent", "well", "narrative_v1"):
                    self.assertEqual(after[key], before[key], key)
                self.assertEqual(after["v2"]["needs"], before["v2"]["needs"])
                self.assertEqual(state.narrative.active_play_game_minutes, active)
                self.assertGreater(state.hooked_total, 0)
                for line in state.lines:
                    for hook in line.hooks:
                        if hook.catch is not None:
                            self.assertLess(hook.catch.age, SPOIL_HOURS)
                # The forecast keeps two weeks per lake, rolled to the week the soak ended
                # in, and replays no cookouts, invitations or Lake Day notes.
                week = int(state.game_minutes // calendar.WEEK_MINUTES)
                windows = state.v2["calendar"]["weather_windows"]
                self.assertEqual(set(windows), {f"{lake}:{w}" for lake in calendar.LAKE_IDS
                                                for w in (week, week + 1)})
                seed = calendar.forecast_seed(state)
                for key, row in windows.items():
                    lake, row_week = key.split(":")
                    self.assertEqual(row["hours"], list(calendar.weekly_plan(seed, lake,
                                                                             int(row_week))))
                for key in SOCIAL:
                    self.assertEqual(after["v2"]["calendar"].get(key),
                                     before["v2"]["calendar"].get(key), key)

    def test_a_full_boat_soaks_72_hours_the_same_way_every_time(self):
        # Eight heavy lines, 192 hooks: the longest soak with the most hooks a boat sets.
        # Both runs use the bulk memo, so this pins the cap; test_bulk_memo holds memoized
        # replays to memo-free ones.
        at_cap = self.soaker("cozy", self.lines(8, "heavy", 24))
        past_cap = self.soaker("cozy", self.lines(8, "heavy", 24))
        self.assertEqual(self.soak(at_cap, COZY_CAP), COZY_CAP)
        self.assertEqual(self.soak(past_cap, COZY_CAP + 9 * 24 * HOUR), COZY_CAP)
        replayed = [state.to_json() for state in (at_cap, past_cap)]
        for saved in replayed:
            del saved["stamp"]
        self.assertEqual(replayed[0], replayed[1])
        self.assertEqual(at_cap.toasts, past_cap.toasts)
        self.assertGreater(at_cap.hooked_total, 100)

    def test_the_cap_follows_the_mode_saved_and_reloaded(self):
        for saved, cap in (("old_salt", OLD_SALT_CAP), ("cozy", COZY_CAP)):
            with self.subTest(saved=saved):
                state = self.soaker("cozy" if saved == "old_salt" else "old_salt")
                comfort.change_mode(state.v2, saved)  # changed in Settings, then closed
                state.save(self.path, update_stamp=False)
                loaded = State.load(self.path, self.world)
                self.assertEqual(comfort.mode(loaded.v2), saved)
                self.assertEqual(self.soak(loaded, COZY_CAP + OLD_SALT_CAP), cap)

    def test_a_save_without_a_known_mode_loads_as_cozy_and_soaks_72_hours(self):
        def v1(raw):
            raw.pop("v2")
            raw["version"] = 1

        def unset(raw):
            raw["v2"].pop("mode")
            raw["v2"]["settings"].pop("mode")

        def unknown(raw):
            raw["v2"]["mode"] = raw["v2"]["settings"]["mode"] = "hardcore"

        for damage in (v1, unset, unknown):
            with self.subTest(save=damage.__name__):
                raw = self.soaker("old_salt").to_json()
                damage(raw)
                self.path.write_text(json.dumps(raw), encoding="utf-8")
                loaded = State.load(self.path, self.world)
                self.assertEqual((loaded.v2["mode"], loaded.v2["settings"]["mode"]),
                                 ("cozy", "cozy"))
                self.assertEqual(self.soak(loaded, COZY_CAP + HOUR), COZY_CAP)

    def test_continue_soaks_by_the_loaded_save_and_keeps_quest_clocks(self):
        # Away 40 real hours: past Old Salt's cap, inside Cozy's. The title's Continue loads
        # the save, so its mode sets the cap, and no quest clock runs while away.
        state = self.soaker("old_salt", self.lines(1))
        state.time_scale = 1  # the frame after Continue adds no whole game minute
        state.anchored, state.throttle, state.throttle_setting = True, 0.0, 0.0
        state.x, state.z = self.world.anchors["briar:inlet"].position
        timed = state.narrative.quests[QUEST_IDS[6]]
        timed.status = "active"
        timed.accepted_game_minute = state.game_minutes
        timed.progress = {"continuous_game_minutes": 15.0}
        state.v2["needs"].update({"awake_h": 3.0, "since_meal_h": 5.0})
        state.save(self.path, update_stamp=False)
        with patch("fishing.game.time.time", return_value=START + 40 * HOUR):
            session = Session(self.world, self.path, State.load(self.path, self.world), True)
        session.ui.mode = "title"
        before = session.state.game_minutes

        session.tick(Keys(pressed=("return",)), 0.25)

        self.assertEqual(session.ui.mode, "play")
        self.assertEqual(session.state.game_minutes, before + OLD_SALT_CAP)
        self.assertEqual(session.state.stamp, START + 40 * HOUR)
        quest = session.state.narrative.quests[QUEST_IDS[6]]
        self.assertEqual(quest.status, "active")
        self.assertEqual(quest.progress["continuous_game_minutes"], 15.0)
        self.assertEqual(session.state.v2["needs"]["awake_h"], 3.0)
        self.assertEqual(session.state.v2["needs"]["since_meal_h"], 5.0)
        self.assertEqual(session.state.money, state.money)


if __name__ == "__main__":
    unittest.main()
