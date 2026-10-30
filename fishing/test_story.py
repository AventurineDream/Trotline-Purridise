"""V1-34: the story spine. Chapters are three `story`-kind steps each, started and finished by
play (01 §5, 02 §13). These checks drive a new save through real hails and events, reload it
mid-chapter, and check that rewards are paid once and the chapters finish in order."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

STEPS = [f"story_c{c}_s{s}" for c in (1, 2) for s in (1, 2, 3)]


class Story(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("briar")
        self.state = State.new(self.world, seed=34)
        # The prologue (not built yet) opens chapter one; these checks start from that point.
        self.state.v2["story"]["chapter"] = 1
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
        for qid in STEPS:
            row = self.content.quests[qid]
            steps = row["objective"] if isinstance(row["objective"], list) else [row["objective"]]
            for step in steps:
                self.assertFalse({"deadline", "until", "by_minute", "expires"} & set(step), qid)
            self.assertNotIn("time_limit", row)

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
        self.assertIsNone(story_part("wc_marigold_a"))
        self.assertTrue(all(is_quest_id(qid) for qid in STEPS))
