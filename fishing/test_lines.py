"""Per-boat line limits and split-bait regression checks."""

from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from .content import load_content
from .game import Keys, Session
from .narrative import QUEST_IDS
from .quests import QuestManager
from .sim import Hook, SetLine, State
from .world import World


class LineCapacityAndBaitChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def test_hook_mapping_divides_each_supported_tier_into_equal_sections(self):
        for tier, hooks, section_size in (
            ("std", 12, 4), ("prem", 18, 6), ("heavy", 24, 8),
        ):
            with self.subTest(tier=tier):
                line = SetLine(
                    tier, ["worm", "shad", "minnow"], 0, 0, 1, 0, "open",
                    [Hook(True) for _ in range(hooks)],
                )
                self.assertEqual(
                    [line.section_for_hook(i) for i in range(hooks)],
                    [section for section in range(3)
                     for _ in range(section_size)],
                )
                self.assertEqual(
                    [line.bait_for_hook(i) for i in range(hooks)],
                    [bait for bait in ("worm", "shad", "minnow")
                     for _ in range(section_size)],
                )

    def test_legacy_scalar_bait_migrates_to_one_section(self):
        old = SetLine(
            "std", "shad", 1, 2, 3, 4, "open", [Hook(True)],
            line_id=str(uuid4()), extra_fields={"future_line_marker": 7},
        ).to_json()
        old["bait"] = old.pop("bait_sections")[0]

        migrated = SetLine.from_json(old)

        self.assertEqual(migrated.bait_sections, ["shad"])
        saved = migrated.to_json()
        self.assertEqual(saved["bait_sections"], ["shad"])
        self.assertNotIn("bait", saved)
        self.assertEqual(saved["future_line_marker"], 7)

    def test_each_hook_catches_with_its_section_bait_and_emits_the_line_sections(self):
        state = State.new(self.world, seed=73)
        line = SetLine(
            "std", ["worm", "shad", "minnow"], 0, 0, 12, 0, "open",
            [Hook(True) for _ in range(12)],
        )
        state.lines = [line]
        state._world = SimpleNamespace(
            zone_at=lambda _x, _z: "open", depth=lambda _x, _z: 10.0,
        )
        observed_baits = []

        def rates(_zone, bait, _hour, _weather, _depth, _lake):
            observed_baits.append(bait)
            return {"bluegill": 1.0}

        with patch("fishing.sim.species_rates", side_effect=rates), \
                patch.object(state.rng, "chance", return_value=True), \
                patch.object(state.rng, "pick", return_value="bluegill"), \
                patch.object(state, "_roll_weight", return_value=0.5):
            state._one_span(1 / 60)

        expected = [bait for bait in ("worm", "shad", "minnow") for _ in range(4)]
        self.assertEqual(observed_baits, expected)
        self.assertEqual([hook.catch.bait for hook in line.hooks], expected)

        events = []
        state._quest_event_handler = lambda _state, event: events.append(event)
        state._emit_livewell_entry(line.hooks[6].catch, line)
        self.assertEqual(events[0]["bait_id"], "shad")
        self.assertEqual(events[0]["bait_sections"], ["worm", "shad", "minnow"])

    def test_set_consumes_each_section_bait_and_emits_split_configuration(self):
        state = State.new(self.world, seed=19)
        state.bait.update({"shad": 4, "minnow": 4})
        fake_world = SimpleNamespace(
            slip=SimpleNamespace(
                contains=lambda _x, _z: False, ox=1000.0, oz=1000.0,
            ),
            navigable=lambda _x, _z: True,
            depth=lambda _x, _z: 10.0,
            shore_sd=lambda _x, _z: -1.0,
            zone_at=lambda _x, _z: "open",
        )
        events = []
        state._quest_event_handler = lambda _state, event: events.append(event)

        error = state.try_set(fake_world, 0, ["worm", "shad", "minnow"])

        self.assertIsNone(error)
        self.assertEqual(state.bait["worm"], 20)
        self.assertEqual(state.bait["shad"], 0)
        self.assertEqual(state.bait["minnow"], 0)
        self.assertEqual(state.lines[0].bait_sections, ["worm", "shad", "minnow"])
        self.assertEqual(events[0]["bait_id"], None)
        self.assertEqual(events[0]["bait_sections"], ["worm", "shad", "minnow"])

    def test_set_line_controls_cycle_sections_and_edit_each_bait(self):
        state = State.new(self.world, seed=22)
        session = Session(self.world, Path("/tmp/trotline-set-controls.json"), state, False)
        session.ui.mode = "setbait"

        session._keys(Keys(pressed={"q"}), 0.05)
        session._keys(Keys(pressed={"tab"}), 0.05)
        session._keys(Keys(pressed={"2"}), 0.05)

        self.assertEqual(session.ui.set_sections, 2)
        self.assertEqual(session.ui.set_section, 1)
        self.assertEqual(session.ui.set_section_baits, (0, 1, 0))

    def test_smaller_boat_capacity_blocks_new_sets_and_keeps_existing_lines(self):
        state = State.new(self.world, seed=27)
        state.boat_id = "pontoon"
        state.owned_boats.append("pontoon")
        state._park(self.world)
        state.lines = [
            SetLine("std", "worm", i * 20, 0, i * 20 + 10, 0, "open", [])
            for i in range(6)
        ]
        state.money = 1000
        self.assertIsNone(state.buy_boat("rowboat", self.world))
        self.assertEqual(len(state.lines), 6)
        self.assertIsNone(state.buy_line("std"))
        held_before = len(state.held)

        error = state.try_set(self.world, 0, "worm")

        self.assertIn("up to 5 deployed lines", error)
        self.assertEqual(len(state.lines), 6)
        self.assertEqual(len(state.held), held_before)

    def test_bait_specific_quests_reject_any_mixed_bait_line(self):
        state = State.new(self.world, seed=51)
        manager = QuestManager(load_content())

        line_quest = QUEST_IDS[0]
        line_progress = state.narrative.quests[line_quest]
        line_progress.status = "active"
        line_progress.accepted_game_minute = 0
        line_event = {
            "type": "line.set", "lake_id": "briar", "line_id": str(uuid4()),
            "zone_id": "briar:lilies", "tier_id": "std", "hook_count": 12,
            "bait_id": None, "bait_sections": ["worm", "shad"],
            "game_minute": 10, "active_game_minute": 10,
        }
        manager.handle_event(state, line_event)
        self.assertEqual(line_progress.progress.get("deployments", {}), {})
        manager.handle_event(state, {
            **line_event, "line_id": str(uuid4()), "bait_id": "worm",
            "bait_sections": ["worm", "worm"],
        })
        self.assertEqual(len(line_progress.progress["deployments"]), 1)

        fish_quest = QUEST_IDS[5]
        fish_progress = state.narrative.quests[fish_quest]
        fish_progress.status = "active"
        fish_progress.accepted_game_minute = 0
        fish_event = {
            "type": "fish.enter_livewell", "species_id": "golden_shiner",
            "source_line_id": str(uuid4()), "lake_id": "briar",
            "source_zone_id": "briar:lilies", "bait_id": "worm",
            "bait_sections": ["worm", "shad"], "catch_game_minute": 340,
            "entry_game_minute": 350,
        }
        manager.handle_event(state, fish_event)
        self.assertEqual(fish_progress.status, "active")
        self.assertNotIn("fish_entered_livewell", fish_progress.progress)
        manager.handle_event(state, {
            **fish_event, "bait_sections": ["worm", "worm"],
        })
        self.assertEqual(fish_progress.status, "ready")


if __name__ == "__main__":
    unittest.main()
