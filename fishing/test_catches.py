"""Keep, release, Treasure and protected-catch regressions."""

from types import SimpleNamespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .sim import Catch, Hook, SetLine, State
from .ui import check_rows
from .world import World


class CatchResolutionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def state_with_catch(self, *, full=False, shiny=False, legendary=False):
        state = State.new(self.world, seed=49)
        catch = Catch(
            "bluegill", 1.25, 1.0, 0.0, "flats", "worm", 8.0,
            shiny=shiny, legendary=legendary,
        )
        state._note_journal(catch)
        state.lines = [SetLine(
            "std", "worm", 0, 0, 12, 0, "flats", [Hook(False, catch)],
        )]
        if full:
            state.well = [Catch(
                "channel", state.well_cap(), 1.0, 0.0, "deep", "shad", 8.0,
            )]
        return state, catch

    def test_standard_shiny_protected_and_legendary_resolution_with_full_or_empty_well(self):
        kinds = ("standard", "shiny", "protected", "legendary")
        for kind in kinds:
            for full in (False, True):
                with self.subTest(kind=kind, full=full):
                    patch_values = ({"bluegill": SimpleNamespace(
                        name="Bull trout", tags=("protected",),
                    )} if kind == "protected" else {})
                    with patch.dict("fishing.sim.SPECIES_BY_ID", patch_values):
                        state, catch = self.state_with_catch(
                            full=full, shiny=kind == "shiny",
                            legendary=kind == "legendary",
                        )
                        events = []
                        state._quest_event_handler = lambda _state, event: events.append(event)

                        if kind == "shiny" and full:
                            state.prepare_catch_dispositions(0)
                            self.assertTrue(catch.treasured)
                            self.assertEqual(catch.disposition, "keep")
                            self.assertIn("full", state.take_all(0).lower())
                            self.assertIsNotNone(state.lines[0].hooks[0].catch)
                            self.assertIsNone(state.toggle_catch_disposition(0, 0))

                        result = state.take_all(0)

                        self.assertTrue(result.startswith("Resolved"), result)
                        forced = kind in ("protected", "legendary")
                        expected_kept = kind in ("standard", "shiny") and not full
                        self.assertEqual(catch.disposition, "kept" if expected_kept else "released")
                        self.assertIsNone(state.lines[0].hooks[0].catch)
                        self.assertEqual(state.journal["bluegill"]["count"], 1)
                        livewell = [e for e in events if e["type"] == "fish.enter_livewell"]
                        self.assertEqual(len(livewell), 1 if expected_kept else 0)
                        # Every resolved fish, kept or released, is one catch.resolved (V1-31).
                        resolved = [e for e in events if e["type"] == "catch.resolved"]
                        self.assertEqual([e["kept"] for e in resolved], [expected_kept])
                        if full:
                            self.assertEqual(len(state.well), 1)
                        else:
                            self.assertEqual(len(state.well), 1 if expected_kept else 0)
                        if forced:
                            self.assertTrue(any("book still counts it" in toast[0]
                                                or "remember that" in toast[0]
                                                for toast in state.toasts))

    def test_full_well_preselects_smallest_non_treasured_catch(self):
        state = State.new(self.world, seed=50)
        state.well = [Catch("channel", state.well_cap(), 1, 0, "deep", "shad", 8)]
        small = Catch("bluegill", 0.5, 1, 0, "flats", "worm", 8)
        large = Catch("bluegill", 2.0, 1, 0, "flats", "worm", 8)
        state.lines = [SetLine(
            "std", "worm", 0, 0, 12, 0, "flats",
            [Hook(False, small), Hook(False, large)],
        )]

        selected = state.prepare_catch_dispositions(0)

        self.assertTrue(selected)
        self.assertEqual(small.disposition, "release")
        self.assertEqual(large.disposition, "keep")
        self.assertEqual(next(row.right for row in check_rows(state, 0)
                             if row.kind == "hook" and row.arg == "0"), "RELEASE")
        self.assertIn("smallest", state.toasts[-1][0])
        self.assertIn("full", state.toasts[-1][0])
        self.assertIn("full", state.take_all(0).lower())
        self.assertIsNotNone(state.lines[0].hooks[0].catch)
        self.assertIsNotNone(state.lines[0].hooks[1].catch)

    def test_release_and_keep_record_identical_book_credit_but_only_keep_emits_livewell_event(self):
        snapshots = []
        for disposition in ("keep", "release"):
            state, catch = self.state_with_catch()
            events = []
            state._quest_event_handler = lambda _state, event: events.append(event)

            self.assertIsNone(state.take_hook(0, 0, disposition))
            snapshots.append((state.journal["bluegill"].copy(), events, catch.disposition))

        self.assertEqual(snapshots[0][0], snapshots[1][0])
        self.assertEqual(snapshots[0][0]["count"], 1)
        self.assertEqual(snapshots[0][2], "kept")
        self.assertEqual(snapshots[1][2], "released")
        self.assertEqual([event["type"] for event in snapshots[0][1]], ["fish.enter_livewell", "catch.resolved"])
        self.assertEqual([event["type"] for event in snapshots[1][1]], ["catch.resolved"])
        self.assertEqual([events[-1]["kept"] for _record, events, _d in snapshots], [True, False])

    def test_explicit_keep_choice_overrides_a_preselected_release(self):
        state, catch = self.state_with_catch()
        catch.disposition = "release"

        self.assertIsNone(state.take_hook(0, 0, "keep"))
        self.assertEqual(catch.disposition, "kept")
        self.assertEqual(state.well, [catch])

    def test_treasured_is_default_for_shinies_and_bulk_sale_keeps_treasures(self):
        state, shiny = self.state_with_catch(shiny=True)
        self.assertTrue(shiny.treasured)
        normal = Catch("bluegill", 1.0, 1.0, 0.0, "flats", "worm", 8.0)
        treasured = Catch("channel", 2.0, 1.0, 0.0, "deep", "shad", 8.0,
                          treasured=True)
        state.well = [normal, treasured]
        expected = normal.value()
        starting_money = state.money

        result = state.sell_all()

        self.assertTrue(result.startswith("Sold 1"))
        self.assertEqual(state.money, starting_money + expected)
        self.assertEqual(state.well, [treasured])

    def test_treasured_and_pending_release_choice_round_trip(self):
        state, catch = self.state_with_catch(shiny=True)
        catch.disposition = "release"
        raw = state.to_json()
        with tempfile.TemporaryDirectory(prefix="trotline-catch-save-") as directory:
            save_path = Path(directory) / "save.json"
            save_path.write_text(json.dumps(raw), encoding="utf-8")
            restored = State.load(save_path, self.world)
        saved_catch = restored.lines[0].hooks[0].catch

        self.assertTrue(saved_catch.shiny)
        self.assertTrue(saved_catch.treasured)
        self.assertEqual(saved_catch.disposition, "release")
        state.well = [Catch("channel", 1.0, 1.0, 0.0, "deep", "shad", 8.0,
                            treasured=True)]
        with tempfile.TemporaryDirectory(prefix="trotline-well-save-") as directory:
            save_path = Path(directory) / "save.json"
            save_path.write_text(json.dumps(state.to_json()), encoding="utf-8")
            restored_well = State.load(save_path, self.world)
        self.assertTrue(restored_well.well[0].treasured)
        self.assertEqual(restored_well.well[0].disposition, "kept")

    def test_spoilage_copy_uses_got_away_language(self):
        for count in (1, 2):
            with self.subTest(count=count):
                copy = State._spoilage_copy(count)
                self.assertIn("wriggled free", copy)
                self.assertNotIn("spoiled", copy.lower())

    def test_invalid_saved_disposition_falls_back_to_pending(self):
        raw = Catch("bluegill", 1.0, 1.0, 0.0, "flats", "worm", 8.0).to_json()
        raw["disposition"] = ["release"]

        self.assertEqual(Catch.from_json(raw).disposition, "pending")


if __name__ == "__main__":
    unittest.main()
