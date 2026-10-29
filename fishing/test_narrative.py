"""Regression checks for the optional ledger through real saves and sessions."""

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from uuid import UUID

import numpy as np

from . import bot
from .camera import Camera
from .content import load_content
from .game import Keys, Session
from .guardian import draw_sighting, maybe_start_sighting
from .narrative import NarrativeState, QUEST_IDS, RIPPLE_BY_QUEST
from .quests import QuestManager
from .sim import Catch, Hook, SetLine, State
from .software import BASE_PITCH, FOV
from .ui import UI, UIState, quest_journal_details
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
        n.record_bot_note("Bot: Middling water.")
        n.record_bot_reaction("npc:grandmother_whiskers",
                              "Bot: His brass ears turn toward Grandmother Whiskers.")
        n.record_bot_reaction(f"quest:{QUEST_IDS[2]}",
                              "Bot: He gives a small approving brass click.")
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
        self.assertEqual(result["version"], 2)
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

    def test_quest_journal_details_follow_saved_state_and_contract(self):
        content = load_content()
        qid = QUEST_IDS[1]
        details = quest_journal_details(self.state, content, qid)
        self.assertEqual(details["status"], "Available")
        self.assertEqual(details["giver"], "Doc Barnaby · Doc's Lonely Star Marina")
        self.assertEqual(details["prerequisites"], "none")
        self.assertIn("Dam riprap", details["objective"])
        self.assertIn("Not started", details["progress"])

        quest_progress = self.state.narrative.quests[qid]
        quest_progress.declined = True
        details = quest_journal_details(self.state, content, qid)
        self.assertIn("Declined earlier", details["progress"])

        quest_progress.status = "active"
        quest_progress.progress = {
            "deployments": {
                "line-a": {"set": {"active_game_minute": 40}, "checked": False}
            }
        }
        self.state.narrative.active_play_game_minutes = 75
        details = quest_journal_details(self.state, content, qid)
        self.assertIn("soak 35/60 active-play min", details["progress"])

        quest_progress = self.state.narrative.quests[QUEST_IDS[10]]
        quest_progress.status = "active"
        quest_progress.progress = {
            "deployments": {
                "line-old": {"set": {"active_game_minute": 0},
                             "active_soak_game_minutes": 60},
                "line-new": {"set": {"active_game_minute": 75},
                             "active_soak_game_minutes": 2},
            },
            "active_soak_game_minutes": 60,
        }
        self.state.narrative.active_play_game_minutes = 80
        details = quest_journal_details(self.state, content, QUEST_IDS[10])
        self.assertIn("soak 5/60 active-play min", details["progress"])

        sunrise = quest_journal_details(self.state, content, QUEST_IDS[5])
        self.assertIn("into the livewell during 05:00–08:00", sunrise["objective"])
        self.assertIn("line set in Lily cove", sunrise["objective"])

        self.state.narrative.bot_notes = ["Bot: Minnows along the shaded bank."]
        details = quest_journal_details(self.state, content, qid)
        self.assertEqual(details["bot_notes"], ["Bot: Minnows along the shaded bank."])
        self.state.narrative.record_bot_reaction(
            "npc:elder_moss", "Bot: His brass ears turn toward Elder Moss.")
        details = quest_journal_details(self.state, content, qid)
        self.assertEqual(details["latest_bot_note"],
                         "Bot: His brass ears turn toward Elder Moss.")
        self.assertIn("Guardian locked (<8 Ripples)", details["guardian_status"])
        self.state.narrative.ripples = list(RIPPLE_BY_QUEST.values())[:8]
        details = quest_journal_details(self.state, content, qid)
        self.assertIn("Guardian available", details["guardian_status"])
        self.state.narrative.guardian_seen = True
        details = quest_journal_details(self.state, content, qid)
        self.assertIn("Whiskered Blessing", details["guardian_status"])
        self.assertIn("broad ripple", details["guardian_status"])

    def test_guardian_sighting_requires_eight_ripples_deep_water_and_sunset(self):
        cedar = World("cedar")
        state = State.new(cedar, seed=91)
        state.x, state.z = cedar.anchors["cedar:deep"].position
        state.game_minutes = 720  # 18:00, with game time anchored at 06:00.
        state.narrative.ripples = list(RIPPLE_BY_QUEST.values())[:7]

        self.assertFalse(maybe_start_sighting(state, cedar, "play"))
        state.narrative.ripples.append("ripple_08")
        self.assertFalse(maybe_start_sighting(state, cedar, "map"))
        state.game_minutes = 719.9
        self.assertFalse(maybe_start_sighting(state, cedar, "play"))
        state.game_minutes = 840  # 20:00 is outside the half-open window.
        self.assertFalse(maybe_start_sighting(state, cedar, "play"))
        state.game_minutes = 720
        state.x, state.z = cedar.anchors["cedar:open"].position
        self.assertFalse(maybe_start_sighting(state, cedar, "play"))
        state.x, state.z = cedar.anchors["cedar:deep"].position

        fishing_before = {key: state.to_json()[key]
                          for key in ("money", "lines", "well", "bait", "journal", "game_minutes")}
        state.anim = 12.5
        self.assertTrue(maybe_start_sighting(state, cedar, "play"))
        self.assertTrue(state.narrative.guardian_seen)
        self.assertTrue(state.guardian_sighting_pending)
        self.assertIsNone(state.guardian_sighting_started_at)
        self.assertFalse(maybe_start_sighting(state, cedar, "play"))
        self.assertEqual(fishing_before, {key: state.to_json()[key]
                                          for key in fishing_before})

        state.save(self.path)
        loaded = State.load(self.path, cedar)
        self.assertTrue(loaded.narrative.guardian_seen)
        self.assertFalse(loaded.guardian_sighting_pending)
        self.assertIsNone(loaded.guardian_sighting_started_at)
        details = quest_journal_details(loaded, load_content(), QUEST_IDS[0])
        self.assertIn("Whiskered Blessing", details["guardian_status"])

    def test_guardian_sighting_overlay_is_brief_and_nonblocking(self):
        state = self.state
        frame = np.full((180, 320, 3), 96, dtype=np.uint8)
        state.guardian_sighting_started_at = 2.0
        state.guardian_sighting_last_anim = 2.0
        state.anim = 3.0
        draw_sighting(frame, state)
        self.assertFalse(np.all(frame == 96))

        state.anim = 10.0
        expired = np.full((180, 320, 3), 96, dtype=np.uint8)
        draw_sighting(expired, state)
        self.assertTrue(np.all(expired == 96))

    def test_guardian_sighting_tracks_waterline_and_waits_until_visible(self):
        state = self.state
        frame = np.full((270, 360, 3), 96, dtype=np.uint8)
        state.anim = 2.0
        state.guardian_sighting_pending = True
        state.guardian_sighting_last_anim = 2.0

        def camera_for_state():
            return Camera(state.x, state.boat.eye_height, state.z, state.yaw,
                          BASE_PITCH + state.look, 0.0, FOV,
                          frame.shape[1], frame.shape[0], build_rays=False)

        state.look = 0.0
        self.assertTrue(draw_sighting(frame, state, camera_for_state()))
        self.assertFalse(state.guardian_sighting_pending)
        self.assertEqual(state.guardian_sighting_started_at, 2.0)
        self.assertFalse(np.all(frame == 96))

        state.anim = 3.0
        state.look = 0.62
        sky_view = np.full_like(frame, 96)
        self.assertFalse(draw_sighting(sky_view, state, camera_for_state()))
        self.assertTrue(np.all(sky_view == 96))
        self.assertEqual(state.guardian_sighting_started_at, 3.0)

        state.anim = 4.0
        state.look = 0.0
        resumed = np.full_like(frame, 96)
        self.assertTrue(draw_sighting(resumed, state, camera_for_state()))
        self.assertFalse(np.all(resumed == 96))
        self.assertEqual(state.guardian_sighting_started_at, 3.0)

    def test_guardian_sighting_clock_pauses_while_ui_hides_it(self):
        state = self.state
        state.narrative.guardian_seen = True
        state.anim = 3.0
        state.guardian_sighting_started_at = 2.0
        state.guardian_sighting_last_anim = 3.0
        session = Session(self.world, self.path, state, False)
        session.ui.mode = "journal"

        session.tick(Keys(), 2.0)

        self.assertEqual(state.anim, 3.0)
        self.assertEqual(state.guardian_sighting_started_at, 2.0)
        self.assertEqual(state.guardian_sighting_last_anim, 3.0)

        session.ui.mode = "play"
        session.tick(Keys(), 1.0)
        self.assertEqual(state.anim - state.guardian_sighting_started_at, 2.0)

    def test_session_starts_guardian_sighting_during_visible_play(self):
        cedar = World("cedar")
        state = State.new(cedar, seed=92)
        state.x, state.z = cedar.anchors["cedar:deep"].position
        state.game_minutes = 720
        state.narrative.ripples = list(RIPPLE_BY_QUEST.values())[:8]
        session = Session(cedar, self.path, state, False)
        session.ui.mode = "play"

        session.tick(Keys(), 0.1)

        self.assertTrue(state.narrative.guardian_seen)
        self.assertTrue(state.guardian_sighting_pending)
        self.assertAlmostEqual(state.guardian_sighting_last_anim, state.anim)

    def test_small_narrative_journal_reserves_progress_line(self):
        qid = QUEST_IDS[10]
        progress = self.state.narrative.quests[qid]
        progress.status = "active"
        progress.progress = {
            "deployments": {
                "line-new": {"set": {"active_game_minute": 5}, "checked": False}
            }
        }
        self.state.narrative.active_play_game_minutes = 10

        class FakeText:
            def render(self, value, size, color, family="mono"):
                return SimpleNamespace(shape=(size + 4, size // 2 + 1))

        renderer = UI(FakeText(), self.world)
        drawn = []
        renderer._text = lambda _frame, value, *_args, **_kwargs: drawn.append(str(value))
        renderer._panel = lambda *_args, **_kwargs: None
        renderer._fill = lambda *_args, **_kwargs: None
        renderer._narrative_journal(SimpleNamespace(shape=(270, 480)), self.state,
                                     UIState(journal_quest_i=10))
        self.assertTrue(any(line.startswith("Progress:") for line in drawn), drawn)
        self.assertTrue(any(line.startswith("Guardian locked") for line in drawn), drawn)

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

    def test_bot_reactions_are_keyed_once_and_journal_notes_roundtrip(self):
        n = self.state.narrative
        npc_note = "Bot: His brass ears turn toward Elder Moss."
        quest_note = "Bot: He gives a small approving brass click."
        self.assertTrue(n.record_bot_reaction("npc:elder_moss", npc_note))
        self.assertFalse(n.record_bot_reaction("npc:elder_moss", "Repeated cue."))
        self.assertTrue(n.record_bot_reaction(f"quest:{QUEST_IDS[2]}", quest_note))
        self.assertFalse(n.record_bot_reaction("npc:unknown", "Unsupported NPC."))
        self.assertFalse(n.record_bot_reaction([], "Invalid key."))
        self.assertEqual(n.bot_journal, [npc_note, quest_note])

        loaded = self.load()
        self.assertEqual(loaded.narrative.bot_reactions, n.bot_reactions)
        self.assertEqual(loaded.narrative.bot_journal, [npc_note, quest_note])
        self.assertFalse(loaded.narrative.record_bot_reaction(
            "npc:elder_moss", "A cue must not repeat after loading."))

    def test_scout_reports_keep_their_two_note_history_and_journal_order(self):
        n = self.state.narrative
        reports = [f"Bot: Report {index}." for index in range(3)]
        for report in reports:
            self.assertTrue(n.record_bot_note(report))
        reaction = "Bot: His brass ears turn toward Doc Barnaby."
        n.record_bot_reaction("npc:doc_barnaby", reaction)
        self.assertEqual(n.bot_notes, reports[-2:])
        self.assertEqual(n.bot_journal, reports + [reaction])
        self.assertEqual(self.load().narrative.bot_notes, reports[-2:])
        self.assertEqual(self.load().narrative.bot_journal, reports + [reaction])

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
            "bot_reactions": {"npc:elder_moss": "One cue", "npc:unknown": "Drop",
                              f"quest:{QUEST_IDS[0]}": None},
            "bot_journal": ["Journal entry", None, 42, "  "],
            "reward_claims": [QUEST_IDS[2], {}, QUEST_IDS[2]],
        }
        loaded = self.load(raw)
        n = loaded.narrative
        self.assertEqual(n.quests[qid].progress, {"good": 32, "nested": [1]})
        self.assertIsNone(n.quests[qid].accepted_game_minute)
        self.assertEqual(n.quests[qid].status, "active")
        self.assertEqual(n.ripples, ["ripple_01"])
        self.assertEqual(n.bot_notes, ["Kept note"])
        self.assertEqual(n.bot_reactions, {"npc:elder_moss": "One cue"})
        self.assertEqual(n.bot_journal, ["Journal entry"])
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

    def test_session_menus_keep_the_active_clock_frozen(self):
        session = Session(self.world, self.path, self.state, False)
        self.state.x, self.state.z = self.state.npcs[1].anchor.position
        session._hail()
        self.assertEqual(session.ui.mode, "dialogue")
        session.tick(Keys(), 1)
        self.assertEqual(self.state.narrative.active_play_game_minutes, 0, "dialogue")
        session._close_dialogue()
        self.state.lines = [self.line()]
        for mode in ("shop", "journal", "map", "pause", "help", "well", "setbait",
                     "check", "settings", "kitchen", "scene"):
            session.ui.mode = mode
            session.tick(Keys(), 1)
            self.assertEqual(self.state.narrative.active_play_game_minutes, 0, mode)

    def test_lake_travel_and_offline_keep_shared_ledger_and_saved_selection(self):
        self.state.lines = [self.line()]
        expected = self.populated()
        self.state.pull_line(0)
        session = Session(self.world, self.path, self.state, False)
        self.assertIsNone(session.change_lake("cedar"))
        loaded = State.load(self.path, session.world)
        loaded.catch_up(loaded.stamp + 2 * 1440)
        # The V1-30 schedule is a pure function of the seed and day: it never writes the
        # shared ledger. A V3 day selection stays in the save exactly as it was.
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

    def test_line_scout_uses_the_matching_line_captured_at_launch(self):
        manager = QuestManager(load_content())
        qid = QUEST_IDS[0]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 100
        money = self.state.money
        line_id = self.state.lines[0].line_id if self.state.lines else self.line().line_id
        manager.handle_event(self.state, {
            "type": "line.set", "lake_id": "briar", "line_id": line_id,
            "zone_id": "briar:lilies", "tier_id": "std", "hook_count": 12,
            "bait_id": "worm", "game_minute": 100, "active_game_minute": 20,
        })
        manager.handle_event(self.state, {
            "type": "bot.scout_complete", "lake_id": "briar",
            "target_line_id": str(UUID(int=1)), "zone_id": "briar:lilies",
            "depth_class": "middling", "report_delivered": True,
            "game_minute": 101,
        })
        self.assertEqual(quest.status, "active")
        manager.handle_event(self.state, {
            "type": "bot.scout_complete", "lake_id": "briar",
            "target_line_id": line_id, "zone_id": "briar:lilies",
            "depth_class": "middling", "report_delivered": True,
            "game_minute": 101,
        })
        self.assertEqual(quest.status, "ready")
        self.assertEqual(self.state.money, money)

    def test_bot_launch_uses_strict_nearest_line_range(self):
        world = SimpleNamespace(
            slip=SimpleNamespace(contains=lambda _x, _z: False),
            shore_sd=lambda _x, _z: -1.0,
        )
        self.state.x = self.state.z = 0.0
        line = SetLine("std", "worm", 138.99, 0.0, 140.99, 0.0, "lilies", [])
        self.state.lines = [line]
        self.assertEqual(bot._target(self.state, world)[2], line.line_id)

        line.x0, line.x1 = 139.0, 141.0
        self.assertIsNone(bot._target(self.state, world)[2])

    def test_successful_line_set_and_opened_check_emit_progress_events(self):
        qid = QUEST_IDS[4]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 0
        self.state.game_minutes = 1230
        self.state.bait["shad"] = max(12, self.state.bait.get("shad", 0))
        session = Session(self.world, self.path, self.state, False)
        fake_world = SimpleNamespace(
            slip=SimpleNamespace(ox=1000.0, oz=1000.0,
                                 contains=lambda _x, _z: False),
            navigable=lambda _x, _z: True,
            depth=lambda _x, _z: 10.0,
            zone_at=lambda _x, _z: "deep",
        )
        self.assertIsNone(self.state.try_set(fake_world, 0, "shad"))
        line = self.state.lines[0]
        line.hooks[0].catch = Catch("golden_shiner", 0.3, 1.0, 0, "deep", "shad",
                                    20.5, "briar", catch_game_minute=1230)
        self.state.x = (line.x0 + line.x1) * 0.5
        self.state.z = (line.z0 + line.z1) * 0.5
        deployment = quest.progress["deployments"][line.line_id]
        self.assertEqual(deployment["set"]["zone_id"], "briar:deep")
        self.state.narrative.active_play_game_minutes += 60
        self.state.slip_status = lambda _world: None
        events = []
        handler = self.state._quest_event_handler

        def capture(state, event):
            events.append(event)
            return handler(state, event)

        self.state._quest_event_handler = capture
        session._open_e()
        self.assertEqual(session.ui.mode, "haul")
        self.assertEqual(quest.status, "ready")
        event = next(event for event in events if event["type"] == "line.check")
        self.assertEqual(event["zone_id"], "briar:deep")
        self.assertEqual(event["eligible_catch_records"], [{
            "species_id": "golden_shiner",
            "source_line_id": line.line_id,
            "lake_id": "briar",
            "source_zone_id": "briar:deep",
            "bait_id": "shad",
            "bait_sections": ["shad"],
            "catch_game_minute": 1230,
        }])

    def test_delivered_bot_report_emits_authored_zone_event(self):
        qid = QUEST_IDS[3]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 0
        Session(self.world, self.path, self.state, False)
        target = self.world.anchors["briar:flats"]
        self.state.finder = 1
        self.state.x, self.state.z = target.x, target.z
        self.state.bot_phase = "go"
        self.state.bot_x = self.state.bot_tx = target.x
        self.state.bot_z = self.state.bot_tz = target.z
        self.state.bot_target_line_id = None
        events = []
        handler = self.state._quest_event_handler

        def capture(state, event):
            events.append(event)
            return handler(state, event)

        self.state._quest_event_handler = capture
        bot.tick(self.state, self.world, 0.1)
        self.assertEqual(self.state.bot_phase, "out")
        self.assertEqual(quest.status, "ready")
        self.assertEqual(events[0]["zone_id"], "briar:flats")
        self.assertEqual(len(self.state.narrative.bot_notes), 1)
        self.assertIn("Bot:", self.state.narrative.bot_notes[0])
        self.state.save(self.path)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.narrative.bot_notes, self.state.narrative.bot_notes)
        self.assertIn("exact_depth_m", events[0])
        self.assertNotIn("exact_depth", events[0])
        self.assertNotIn("distance_m", events[0])

    def test_scout_check_requires_same_line_and_scout_before_soaked_check(self):
        manager = QuestManager(load_content())
        qid = QUEST_IDS[10]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 50
        line_id = str(UUID(int=2))
        manager.handle_event(self.state, {
            "type": "line.set", "lake_id": "cedar", "line_id": line_id,
            "zone_id": "cedar:deep", "tier_id": "prem", "hook_count": 18,
            "bait_id": "shad", "game_minute": 50, "active_game_minute": 10,
        })
        check = {"type": "line.check", "lake_id": "cedar", "zone_id": "cedar:deep",
                 "line_id": line_id, "game_minute": 111, "active_game_minute": 71,
                 "eligible_catch_records": []}
        manager.handle_event(self.state, check)
        self.assertEqual(quest.status, "active")
        self.state.save(self.path)
        resumed = State.load(self.path, self.world)
        manager = QuestManager(load_content())
        manager.handle_event(resumed, {
            "type": "bot.scout_complete", "lake_id": "cedar",
            "target_line_id": line_id, "zone_id": "cedar:deep",
            "depth_class": "deep", "report_delivered": True, "game_minute": 112,
        })
        check["game_minute"] = 113
        manager.handle_event(resumed, {**check, "lake_id": "briar", "zone_id": "briar:deep"})
        self.assertEqual(resumed.narrative.quests[qid].status, "active")
        manager.handle_event(resumed, {**check, "zone_id": "cedar:rocks"})
        self.assertEqual(resumed.narrative.quests[qid].status, "active")
        manager.handle_event(resumed, check)
        resumed_quest = resumed.narrative.quests[qid]
        self.assertEqual(resumed_quest.status, "ready")
        self.assertTrue(resumed_quest.progress["deployments"][line_id]["scouted"])

    def test_all_three_soaked_line_objectives_and_moonlight_set_window(self):
        manager = QuestManager(load_content())
        cases = (
            (QUEST_IDS[1], "cedar", "cedar:rocks", "std", 12, "minnow", 300),
            (QUEST_IDS[4], "briar", "briar:deep", "std", 12, "shad", 1230),
            (QUEST_IDS[8], "cedar", "cedar:inlet", "std", 12, "liver", 300),
        )
        for index, (qid, lake, zone, tier, hooks, bait, set_minute) in enumerate(cases, 10):
            with self.subTest(qid=qid):
                quest = self.state.narrative.quests[qid]
                quest.status = "active"
                quest.accepted_game_minute = 100
                line_id = str(UUID(int=index))
                manager.handle_event(self.state, {
                    "type": "line.set", "lake_id": lake, "line_id": line_id,
                    "zone_id": zone, "tier_id": tier, "hook_count": hooks,
                    "bait_id": bait, "game_minute": set_minute,
                    "active_game_minute": 10,
                })
                manager.handle_event(self.state, {
                    "type": "line.check", "lake_id": lake, "line_id": line_id,
                    "zone_id": zone, "game_minute": 160, "active_game_minute": 69,
                    "eligible_catch_records": [],
                })
                self.assertEqual(quest.status, "active")
                manager.handle_event(self.state, {
                    "type": "line.check", "lake_id": lake, "line_id": line_id,
                    "zone_id": zone, "game_minute": 161, "active_game_minute": 70,
                    "eligible_catch_records": [],
                })
                self.assertEqual(quest.status, "ready")

    def test_bot_report_and_second_anchor_zone_complete_without_payout(self):
        manager = QuestManager(load_content())
        money = self.state.money
        qid = QUEST_IDS[3]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 20
        event = {"type": "bot.scout_complete", "lake_id": "briar",
                 "target_line_id": None, "zone_id": "briar:flats",
                 "depth_class": "skinny", "report_delivered": True, "game_minute": 21}
        event["report_delivered"] = False
        manager.handle_event(self.state, event)
        self.assertEqual(quest.status, "active")
        event["report_delivered"] = True
        manager.handle_event(self.state, event)
        self.assertEqual(quest.status, "ready")

        nap = self.state.narrative.quests[QUEST_IDS[6]]
        nap.status = "active"
        nap.accepted_game_minute = 0
        manager.handle_event(self.state, {
            "type": "anchor.sample", "zone_id": "briar:inlet", "game_minute": 120,
            "elapsed_game_minutes": 120, "anchored": True, "engine_idle": True,
        })
        self.assertEqual(nap.status, "ready")
        self.assertEqual(self.state.money, money)

    def test_objective_readiness_waits_for_authored_prerequisites(self):
        content = load_content()
        qid, prerequisite = QUEST_IDS[3], QUEST_IDS[0]
        content.quests[qid]["prerequisites"] = [prerequisite]
        manager = QuestManager(content)
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 0
        event = {"type": "bot.scout_complete", "zone_id": "briar:flats",
                 "depth_class": "middling", "report_delivered": True,
                 "game_minute": 1}
        manager.handle_event(self.state, event)
        self.assertEqual(quest.status, "active")
        self.state.narrative.quests[prerequisite].status = "completed"
        manager.handle_event(self.state, event)
        self.assertEqual(quest.status, "ready")

    def test_livewell_entry_uses_entry_time_and_survives_save_reload(self):
        qid = QUEST_IDS[5]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 100
        line = SetLine("std", "worm", 0, 10, 0, 30, "lilies", [
            Hook(False, Catch("golden_shiner", 0.3, 1.0, 0, "lilies", "worm", 6,
                              "briar", catch_game_minute=90))
        ])
        self.state.lines = [line]
        self.state.game_minutes = 335
        session = Session(self.world, self.path, self.state, False)
        events = []
        handler = self.state._quest_event_handler

        def capture(state, event):
            events.append(event)
            return handler(state, event)

        self.state._quest_event_handler = capture
        self.assertIsNone(self.state.take_hook(0, 0))
        self.assertEqual(quest.status, "ready")
        self.assertEqual(events[0]["lake_id"], "briar")
        self.assertEqual(quest.progress["fish_entered_livewell"]["entry_game_minute"], 335)
        session.save()
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.narrative.quests[qid].status, "ready")
        self.assertEqual(loaded.narrative.quests[qid].progress,
                         quest.progress)
        self.assertEqual(loaded.money, self.state.money)

    def test_anchor_interruptions_travel_and_zone_visit_provenance(self):
        manager = QuestManager(load_content())
        qid = QUEST_IDS[2]
        quest = self.state.narrative.quests[qid]
        quest.status = "active"
        quest.accepted_game_minute = 0
        sample = {"type": "anchor.sample", "zone_id": "briar:cypress",
                  "game_minute": 60, "elapsed_game_minutes": 60,
                  "anchored": True, "engine_idle": True}
        manager.handle_event(self.state, sample)
        self.assertEqual(quest.progress["continuous_game_minutes"], 60)
        sample.update(game_minute=61, elapsed_game_minutes=1, engine_idle=False)
        manager.handle_event(self.state, sample)
        self.assertEqual(quest.progress["continuous_game_minutes"], 0)

        travel_id = QUEST_IDS[7]
        travel = self.state.narrative.quests[travel_id]
        travel.status = "active"
        travel.accepted_game_minute = 0
        movement = {"type": "boat.move", "lake_id": "cedar",
                    "zone_id": "cedar:open", "distance_m": 300,
                    "player_controlled": True, "propulsion": "motor", "game_minute": 5}
        movement["player_controlled"] = False
        manager.handle_event(self.state, movement)
        self.assertEqual(travel.status, "active")
        movement["player_controlled"] = True
        manager.handle_event(self.state, movement)
        self.assertEqual(travel.status, "ready")

        visits = self.state.narrative.quests[QUEST_IDS[9]]
        visits.status = "active"
        visits.accepted_game_minute = 0
        for index, zone in enumerate(("cedar:open", "cedar:rocks", "cedar:lilies")):
            manager.handle_event(self.state, {
                "type": "zone.enter", "zone_id": zone, "game_minute": index + 1,
                "movement_cause": "boat", "player_controlled": True,
            })
        self.assertEqual(visits.status, "ready")

    def test_sequence_requires_player_control_and_ready_is_not_completion(self):
        manager = QuestManager(load_content())
        quest = self.state.narrative.quests[QUEST_IDS[11]]
        quest.status = "active"
        quest.accepted_game_minute = 0
        money = self.state.money
        zones = ("cedar:landing", "cedar:lilies", "cedar:landing")
        for index, zone in enumerate(zones):
            manager.handle_event(self.state, {
                "type": "zone.enter", "zone_id": zone, "game_minute": index + 1,
                "movement_cause": "tow", "player_controlled": False,
            })
        self.assertEqual(quest.progress.get("sequence_index", 0), 0)
        for index, zone in enumerate(zones):
            manager.handle_event(self.state, {
                "type": "zone.enter", "zone_id": zone, "game_minute": index + 4,
                "movement_cause": "boat", "player_controlled": True,
            })
        self.assertEqual(quest.status, "ready")
        self.assertNotIn(QUEST_IDS[11], self.state.narrative.reward_claims)
        self.assertEqual(self.state.money, money)

    def test_collision_slide_movement_events_follow_accepted_path(self):
        world = SimpleNamespace(
            id="cedar",
            zone_at=lambda x, z: "north" if z >= 0.4 else "south",
        )
        self.state.x = self.state.z = 0.0
        self.state._hull_ok = lambda x, z, _world, yaw=None: not (x > 0.5 and z > 0.5)

        moved, path = self.state._move(1.0, 1.0, world)

        self.assertFalse(moved)
        self.assertEqual(len(path), 2)
        self.assertEqual(path[0], (0.0, 0.0, 0.5, 0.5))
        self.assertEqual(path[1], (0.5, 0.5, 1.0, 0.5))

        events = []
        self.state._quest_event_handler = lambda _state, event: events.append(event)
        for x0, z0, x1, z1 in path:
            self.state._emit_movement_events(
                world, x0, z0, x1, z1, player_controlled=True, propulsion="motor")

        distance_by_zone = {}
        for event in events:
            if event["type"] == "boat.move":
                distance_by_zone[event["zone_id"]] = (
                    distance_by_zone.get(event["zone_id"], 0.0) + event["distance_m"])
        self.assertAlmostEqual(distance_by_zone["cedar:south"], 2 ** 0.5 * 0.4, places=2)
        self.assertAlmostEqual(distance_by_zone["cedar:north"], 0.5 + 2 ** 0.5 * 0.1, places=2)


def narrative_checks():
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NarrativeChecks))
    if not result.wasSuccessful():
        raise AssertionError("narrative persistence regressions")


if __name__ == "__main__":
    unittest.main()
