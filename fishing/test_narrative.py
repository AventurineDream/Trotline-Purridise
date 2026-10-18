"""Regression checks for the optional ledger through real saves and sessions."""

import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from . import bot
from .game import Keys, Session
from .narrative import NarrativeState, QUEST_IDS
from .sim import Catch, Hook, SetLine, State
from .world import World


class NarrativeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="briar-narrative-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "save.json"
        self.state = State.new(self.world, seed=87)

    def load(self, raw=None):
        if raw is None:
            self.state.save(self.path)
        else:
            self.path.write_text(json.dumps(raw))
        return State.load(self.path, self.world)

    def line(self, z=10):
        return SetLine("std", "worm", 0, z, 0, z + 20, "open", [Hook(True) for _ in range(12)])

    def populated(self):
        n = self.state.narrative
        n.quests[QUEST_IDS[0]].status = "active"
        n.quests[QUEST_IDS[0]].accepted_game_minute = 32
        n.quests[QUEST_IDS[0]].progress = {
            "line_id": self.state.lines[0].line_id,
            "set": {"zone_id": "briar:lilies", "bait_id": "worm", "active_game_minute": 40},
            "distance_m": 17.25, "visited": ["cedar:rocks", "cedar:open"],
        }
        n.quests[QUEST_IDS[1]].declined = True
        n.quests[QUEST_IDS[2]].status = "completed"
        n.quests[QUEST_IDS[3]].status = "ready"
        n.ripples = ["ripple_01"]
        n.reward_claims = [QUEST_IDS[2]]
        n.schedule_seed = -17
        n.day_npc_by_lake = {"briar": "willow", "cedar": "quill"}
        n.schedule_day_by_lake = {"briar": 2, "cedar": 2}
        n.bot_notes = ["Bot: Middling water."]
        n.guardian_seen = True
        n.active_play_game_minutes = 140
        return n.to_json()

    def test_new_and_legacy_defaults_preserve_fishing(self):
        s = self.state
        s.money, s.earned, s.spent = 234.56, 300, 65.44
        s.lines = [self.line()]
        s.well = [Catch("bluegill", .5, .8, 2, "flats", "worm", 7)]
        s.journal["bluegill"]["count"] = 4
        s.finder = s.light = True
        s.motor, s.well_tier, s.box_tier = 1, 1, 1
        raw = s.to_json()
        del raw["narrative_v1"]
        del raw["lines"][0]["line_id"]
        del raw["bot"]["target_line_id"]
        loaded = self.load(raw)
        result = loaded.to_json()
        for key in ("money", "earned", "spent", "bait", "held", "well", "journal", "owned",
                    "look", "motor", "well_tier", "box_tier", "finder", "light", "game_minutes",
                    "seed", "lake_id", "boat_id", "owned_boats", "fuel_tanks"):
            self.assertEqual(result[key], raw[key], key)
        for key, value in raw["lines"][0].items():
            self.assertEqual(result["lines"][0][key], value)
        self.assertEqual(loaded.narrative.to_json(), NarrativeState().to_json())
        self.assertEqual(len(loaded.narrative.quests), 12)
        self.assertTrue(all(q.status == "available" for q in loaded.narrative.quests.values()))
        self.assertEqual(result["version"], 1)
        migrated_id = loaded.lines[0].line_id
        UUID(migrated_id)
        loaded.save(self.path)
        self.assertEqual(State.load(self.path, self.world).lines[0].line_id, migrated_id)

    def test_complete_ledger_roundtrips_repeatedly_without_payouts(self):
        self.state.lines = [self.line()]
        expected = self.populated()
        money = self.state.money
        loaded = self.load()
        for _ in range(3):
            self.assertEqual(loaded.narrative.to_json(), expected)
            self.assertEqual(loaded.money, money)
            self.assertFalse(loaded.narrative.record_reward_claim(QUEST_IDS[2]))
            loaded.save(self.path)
            loaded = State.load(self.path, self.world)

    def test_reward_claim_latches_once_and_survives_reload(self):
        qid = QUEST_IDS[3]
        n = self.state.narrative
        self.assertFalse(n.record_reward_claim(qid))
        n.quests[qid].status = "ready"
        self.assertTrue(n.record_reward_claim(qid))
        self.assertFalse(n.record_reward_claim(qid))
        loaded = self.load()
        self.assertFalse(loaded.narrative.record_reward_claim(qid))
        self.assertEqual(loaded.narrative.quests[qid].status, "completed")
        self.assertEqual(loaded.money, self.state.money)

    def test_completed_legacy_ledger_cannot_claim_again(self):
        qid = QUEST_IDS[2]
        n = NarrativeState.from_json({"quests": {qid: {"status": "completed"}}})
        self.assertIn(qid, n.reward_claims)
        self.assertFalse(n.record_reward_claim(qid))
        n = NarrativeState.from_json({"reward_claims": [qid, qid]})
        self.assertEqual(n.quests[qid].status, "completed")
        self.assertEqual(n.reward_claims, [qid])

    def test_malformed_optional_fields_do_not_discard_fishing_or_valid_siblings(self):
        raw = self.state.to_json()
        for invalid in (None, False, "broken", [], 42):
            with self.subTest(invalid=invalid):
                raw["narrative_v1"] = invalid
                loaded = self.load(raw)
                self.assertEqual(loaded.money, self.state.money)
                self.assertEqual(loaded.narrative.to_json(), NarrativeState().to_json())
        qid = QUEST_IDS[0]
        raw["narrative_v1"] = {
            "quests": {qid: {"status": "active", "accepted_game_minute": "yesterday",
                              "progress": {"good": 32, "bad": float("nan"), "nested": [1, float("inf")] }},
                       QUEST_IDS[1]: [], "unknown": {"status": "completed"}},
            "schedule_seed": True, "active_play_game_minutes": -12,
            "day_npc_by_lake": {"briar": [], "cedar": "quill"},
            "schedule_day_by_lake": {"briar": True, "cedar": 3},
            "ripples": ["ripple_01", [], "ripple_01", "ripple_99"],
            "bot_notes": ["Kept note", None], "guardian_seen": "false",
            "reward_claims": [QUEST_IDS[2], {}, QUEST_IDS[2]],
        }
        loaded = self.load(raw)
        n = loaded.narrative
        self.assertEqual(n.quests[qid].progress, {"good": 32, "nested": [1]})
        self.assertIsNone(n.quests[qid].accepted_game_minute)
        self.assertEqual(n.quests[qid].status, "active")
        self.assertEqual(n.ripples, ["ripple_01"])
        self.assertEqual(n.bot_notes, ["Kept note"])
        self.assertEqual(n.schedule_seed, 0)
        self.assertEqual(n.schedule_day_by_lake, {"briar": None, "cedar": 3})
        self.assertFalse(n.guardian_seen)
        self.assertEqual(n.active_play_game_minutes, 0)
        self.assertEqual(loaded.money, self.state.money)
        json.dumps(loaded.to_json(), allow_nan=False)

    def test_schedule_seed_default_and_existing_integer(self):
        for raw, expected in (({}, 0), ({"schedule_seed": 19}, 19),
                              ({"schedule_seed": -8}, -8), ({"schedule_seed": 2.5}, 0)):
            self.assertEqual(NarrativeState.from_json(raw).schedule_seed, expected)

    def test_active_clock_uses_actual_effective_rate_and_excludes_offline(self):
        s = self.state
        s.time_scale = 12
        s.advance(1, False)
        self.assertEqual(s.narrative.active_play_game_minutes, 12)
        s.anchored = False
        s.speed = 2
        s.advance(1, False)
        self.assertEqual(s.narrative.active_play_game_minutes, 13)
        s.advance(30, True)
        self.assertEqual(s.narrative.active_play_game_minutes, 13)
        s.catch_up(s.stamp + 125)
        self.assertEqual(s.game_minutes, 138)
        self.assertEqual(s.narrative.active_play_game_minutes, 13)
        loaded = self.load()
        loaded.advance(1, False)
        self.assertEqual(loaded.narrative.active_play_game_minutes, 25)

    def test_bulk_online_clock_and_tow_count_actual_delta(self):
        s = self.state
        s.advance(181, False)
        self.assertEqual(s.narrative.active_play_game_minutes, 181)
        self.assertIsNone(s.tow_to_landing(self.world))
        self.assertEqual(s.narrative.active_play_game_minutes, 241)

    def test_session_menus_count_only_when_clock_advances(self):
        session = Session(self.world, self.path, self.state, False)
        for mode, expected in (("pause", 0), ("help", 0), ("journal", 1), ("shop", 2)):
            session.ui.mode = mode
            session.tick(Keys(), 1)
            self.assertEqual(self.state.narrative.active_play_game_minutes, expected)

    def test_lake_travel_and_offline_keep_shared_ledger_and_saved_selection(self):
        self.state.lines = [self.line()]
        expected = self.populated()
        self.state.pull_line(0)
        session = Session(self.world, self.path, self.state, False)
        self.assertIsNone(session.change_lake("cedar"))
        loaded = State.load(self.path, session.world)
        loaded.catch_up(loaded.stamp + 2 * 1440)
        # Session scheduling now updates only each loaded lake's selection.
        # The rest of the shared ledger remains untouched by travel/offline time.
        expected["day_npc_by_lake"] = {"briar": "silas", "cedar": "dr_alder"}
        expected["schedule_day_by_lake"] = {"briar": 0, "cedar": 0}
        self.assertEqual(loaded.narrative.to_json(), expected)
        loaded.save(self.path)
        self.assertEqual(State.load(self.path, session.world).narrative.to_json(), expected)
        self.assertIsNone(session.change_lake("briar"))
        self.assertEqual(self.state.narrative.to_json(), expected)

    def test_line_identity_survives_reordering_rebait_and_redeployment(self):
        s = self.state
        s.lines = [self.line(10), self.line(40)]
        target = s.lines[1].line_id
        s.narrative.quests[QUEST_IDS[0]].progress = {"line_id": target}
        s.lines[1].hooks[0].baited = False
        self.assertIsNone(s.rebait(1))
        s.pull_line(0)
        loaded = self.load()
        self.assertEqual(loaded.lines[0].line_id, target)
        self.assertEqual(loaded.narrative.quests[QUEST_IDS[0]].progress["line_id"], target)
        s.pull_line(0)
        s.x = s.z = s.yaw = 0
        self.assertIsNone(s.try_set(self.world, 0, "worm"))
        self.assertNotEqual(s.lines[0].line_id, target)

    def test_bot_keeps_launch_identity_after_reload_and_nearest_line_changes(self):
        s = self.state
        s.x = s.z = s.yaw = 0
        s.lines = [self.line(10), self.line(40)]
        bot.summon(s, self.world)
        target = s.bot_target_line_id
        self.assertEqual(target, s.lines[0].line_id)
        s.z = 60
        s.lines.reverse()
        loaded = self.load()
        self.assertEqual(loaded.bot_target_line_id, target)
        self.assertEqual((loaded.bot_tx, loaded.bot_tz), (0, 20))
        loaded.pull_line(0)
        self.assertEqual(loaded.bot_target_line_id, target)
        loaded.pull_line(0)
        self.assertIsNone(loaded.bot_target_line_id)

    def test_bot_clears_identity_on_recall_reset_and_legacy_load(self):
        s = self.state
        s.x = s.z = s.yaw = 0
        s.lines = [self.line()]
        bot.summon(s, self.world)
        raw = s.to_json()
        del raw["bot"]["target_line_id"]
        loaded = self.load(raw)
        self.assertEqual(loaded.bot_phase, "go")
        self.assertIsNone(loaded.bot_target_line_id)
        bot.summon(s, self.world)
        self.assertIsNone(s.bot_target_line_id)
        bot.reset(s)
        bot.summon(s, self.world)
        self.assertIsNotNone(s.bot_target_line_id)
        bot.reset(s)
        self.assertIsNone(s.bot_target_line_id)

    def test_duplicate_or_invalid_saved_line_ids_cannot_bind_bot_to_wrong_line(self):
        s = self.state
        s.lines = [self.line(), self.line(40)]
        raw = s.to_json()
        old_id = s.lines[0].line_id
        raw["lines"][1]["line_id"] = old_id
        raw["bot"].update(phase="go", target_line_id=old_id)
        loaded = self.load(raw)
        self.assertEqual(len({line.line_id for line in loaded.lines}), 2)
        self.assertNotIn(old_id, [line.line_id for line in loaded.lines])
        self.assertIsNone(loaded.bot_target_line_id)
        raw["lines"][0]["line_id"] = []
        UUID(self.load(raw).lines[0].line_id)

    def test_narrative_does_not_change_fishing_rng_or_results(self):
        other = State.new(self.world, seed=87)
        self.state.lines = [self.line()]
        other.lines = [SetLine.from_json(self.state.lines[0].to_json())]
        self.populated()
        self.state.advance(125, False)
        other.advance(125, False)
        self.assertEqual(self.state.rng.s, other.rng.s)
        self.assertEqual(self.state.lines[0].to_json(), other.lines[0].to_json())
        self.assertEqual(self.state.money, other.money)
        self.assertEqual(self.state.journal, other.journal)


def narrative_checks():
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NarrativeChecks))
    if not result.wasSuccessful():
        raise AssertionError("narrative persistence regressions")


if __name__ == "__main__":
    unittest.main()
