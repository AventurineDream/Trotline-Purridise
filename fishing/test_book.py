"""Book stage, folklore, page history, and migration regressions."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .book import (BOOK_SPECIES_IDS, LEGENDARY_IDS, LEGENDARY_STORIES,
                   SPECIES_RUMORS, LegendaryStory, Rumor, all_species_verified,
                   book_stage, claim_stage_up, legendary_page, promote_title,
                   record_legendary, record_observation, refresh_collection_title,
                   remember_rumor, set_dream_clue, species_page, stage_transitions,
                   stage_up_events,
                   take_dream_clue)
from .content import (BOOK_CONTENT_PATH, ContentError, load_book_content,
                      validate_book_content)
from .data import SPECIES_BY_ID
from .sim import Catch, State
from .world import World


class BookChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def test_every_threshold_selects_its_highest_stage(self):
        self.assertEqual([book_stage(count) for count in (0, 1, 2, 3, 4, 5, 9, 10, 99)],
                         ["rumor", "identified", "identified", "bait_known",
                          "bait_known", "verified", "verified", "mastered", "mastered"])
        self.assertEqual(stage_transitions(0, 10), (
            (1, "identified"), (3, "bait_known"), (5, "verified"), (10, "mastered"),
        ))
        self.assertEqual(stage_transitions(5, 4), ())

    def test_authored_rumors_and_legendary_stories_are_complete_and_attributed(self):
        self.assertEqual(len(BOOK_SPECIES_IDS), 144)
        self.assertEqual(len(LEGENDARY_IDS), 12)
        self.assertEqual(SPECIES_RUMORS["bluegill"].teller, "Pip & Pebble")
        self.assertEqual(LEGENDARY_STORIES["old_lantern"].teller, "Grandmother Whiskers")

    def test_rumor_is_written_once_and_never_replaced(self):
        saved_book = {"species": {}}
        first = remember_rumor(saved_book, "bluegill")
        with patch.dict(SPECIES_RUMORS, {"bluegill": Rumor("A changed rumor.", "Someone else")}):
            second = remember_rumor(saved_book, "bluegill")
        self.assertEqual(first, second)
        self.assertEqual(second, {
            "text": "Sunnies follow worms like kittens follow string. Try the flats by day.",
            "teller": "Pip & Pebble",
        })
        second["text"] = "A caller tried to edit the returned copy."
        self.assertEqual(remember_rumor(saved_book, "bluegill"), first)

        state = State.new(self.world, seed=70)
        state.v2["book"] = saved_book
        with tempfile.TemporaryDirectory(prefix="trotline-book-") as directory:
            path = Path(directory) / "save.json"
            state.save(path, update_stamp=False)
            with patch.dict(SPECIES_RUMORS, {"bluegill": Rumor("New edition", "New teller")}):
                loaded = State.load(path, self.world)
                self.assertEqual(remember_rumor(loaded.v2["book"], "bluegill"), first)

    def test_observations_only_grow_and_species_page_reveals_best_bait_at_three(self):
        saved_book = {"species": {}}
        catches = (
            Catch("bluegill", 0.5, 1, 0, "flats", "worm", 8, lake_id="briar", depth_m=2.5),
            Catch("bluegill", 0.6, 1, 0, "reed", "minnow", 13, lake_id="cedar"),
            Catch("bluegill", 0.7, 1, 0, "flats", "worm", 9, lake_id="briar"),
        )
        first = record_observation(saved_book, catches[0])
        for catch in catches[1:]:
            record_observation(saved_book, catch)
        self.assertEqual(len(saved_book["species"]["bluegill"]["found"]), 3)
        self.assertEqual(saved_book["species"]["bluegill"]["found"][0], first)
        self.assertEqual(first["depth_m"], 2.5)
        page = species_page(saved_book, "bluegill", 3, {"best": 0.7})
        self.assertEqual(page["stage"], "bait_known")
        self.assertEqual(page["best_bait"], "worm")
        self.assertEqual(page["best_weight"], 0.7)
        page["found"].clear()
        self.assertEqual(len(saved_book["species"]["bluegill"]["found"]), 3)

    def test_page_reveals_names_and_bait_at_the_earned_stage(self):
        saved_book = {}
        self.assertIsNone(species_page(saved_book, "bluegill", 0)["name"])
        self.assertEqual(species_page(saved_book, "bluegill", 0)["folk_name"], "Sunny")
        self.assertEqual(species_page(saved_book, "bluegill", 1)["name"], "Bluegill")
        self.assertIsNone(species_page(saved_book, "bluegill", 2)["best_bait"])
        # Observed bait frequency must not replace the authored bait preference.
        for _ in range(3):
            record_observation(saved_book, Catch("bluegill", 1, 1, 0, "flats", "minnow", 12))
        self.assertEqual(species_page(saved_book, "bluegill", 3)["best_bait"], "worm")
        self.assertFalse(species_page(saved_book, "bluegill", 4)["tracker_unlocked"])
        self.assertTrue(species_page(saved_book, "bluegill", 5)["tracker_unlocked"])
        self.assertFalse(species_page(saved_book, "bluegill", 9)["mastered"])
        self.assertTrue(species_page(saved_book, "bluegill", 10)["mastered"])

    def test_stage_claim_is_exactly_once_even_after_save_reload(self):
        state = State.new(self.world, seed=71)
        catch = Catch("bluegill", 0.5, 1, 0, "flats", "worm", 8)
        stages = []
        with tempfile.TemporaryDirectory(prefix="trotline-book-") as directory:
            path = Path(directory) / "save.json"
            for count in range(1, 11):
                state._note_journal(catch)
                events = state.take_book_events()
                stages.extend(event["stage"] for event in events)
                self.assertFalse(state.take_book_events())
                if events:
                    self.assertEqual(state.toasts[-1], ["Shall we add that?", 3.0])
                state.save(path, update_stamp=False)
                state = State.load(path, self.world)
                self.assertFalse(state.take_book_events())
                self.assertEqual(stage_up_events(state.v2, "bluegill", 0, count), ())
        self.assertEqual(stages, ["identified", "bait_known", "verified", "mastered"])
        self.assertEqual(len(state.v2["reward_claims"]["book_stage_up"]), 4)
        self.assertFalse(claim_stage_up(state.v2, "bluegill", "mastered"))

    def test_v1_counts_seed_book_stage_and_the_first_observation(self):
        raw = State.new(self.world, seed=73).to_json()
        raw["version"] = 1
        raw.pop("v2")
        counts = dict(zip(("bluegill", "bullhead", "crappie", "carp", "drum"),
                          (0, 1, 3, 5, 10)))
        for species_id, count in counts.items():
            raw["journal"][species_id].update({
                "count": count, "zone": "flats", "bait": "worm", "band": "dawn",
            })
        with tempfile.TemporaryDirectory(prefix="trotline-book-") as directory:
            path = Path(directory) / "v1.json"
            path.write_text(json.dumps(raw))
            migrated = State.load(path, self.world)
        self.assertEqual(migrated.journal, raw["journal"])
        for species_id, count in counts.items():
            self.assertEqual(species_page(migrated.v2["book"], species_id, count)["stage"],
                             book_stage(count))
            entry = migrated.v2["book"]["species"][species_id]
            self.assertEqual(entry["found"],
                             [{"zone": "flats", "bait": "worm", "band": "dawn"}] if count else [])
            self.assertEqual(stage_up_events(migrated.v2, species_id, 0, count), ())
        self.assertFalse(migrated.take_book_events())

    def test_title_states_require_all_144_pages_for_pescapedia(self):
        saved_book = {"title": "fishypedia"}
        journal = {species_id: {"count": 5} for species_id in BOOK_SPECIES_IDS}
        self.assertFalse(promote_title(saved_book, "pescapedia", journal))
        journal["bluegill"]["count"] = 4
        self.assertFalse(all_species_verified(journal))
        self.assertFalse(promote_title(saved_book, "pescapedia", journal))
        self.assertTrue(promote_title(saved_book, "book_of_five_waters", journal))
        journal["bluegill"]["count"] = 5
        self.assertTrue(all_species_verified(journal))
        self.assertTrue(refresh_collection_title(saved_book, journal))
        self.assertEqual(saved_book["title"], "pescapedia")
        self.assertFalse(promote_title(saved_book, "fishypedia", journal))
        self.assertFalse(refresh_collection_title(saved_book, journal))

    def test_legendary_page_keeps_its_authored_story_and_appends_records(self):
        v2 = {"legendaries": {}}
        before = legendary_page("old_lantern", v2)
        self.assertEqual(before["teller"], "Grandmother Whiskers")
        record = {"weight": 12.5, "zone": "landing", "hour": 21.0}
        self.assertTrue(record_legendary(v2, "old_lantern", record))
        self.assertTrue(record_legendary(v2, "old_lantern", {"weight": 13.0}))
        after = legendary_page("old_lantern", v2)
        self.assertTrue(after["verified"])
        self.assertEqual(after["records"], [record, {"weight": 13.0}])
        with patch.dict(LEGENDARY_STORIES, {
            "old_lantern": LegendaryStory("A changed story", "A different teller"),
        }):
            self.assertEqual(legendary_page("old_lantern", v2)["story"], before["story"])

        state = State.new(self.world, seed=89)
        state._note_journal(Catch("old_lantern", 24.0, 1, 0, "landing", "shad", 21,
                                  legendary=True))
        self.assertTrue(legendary_page("old_lantern", state.v2)["verified"])
        self.assertNotIn("old_lantern", state.journal)

    def test_only_one_unread_dream_clue_waits(self):
        saved_book = {"dream_clue": None}
        self.assertTrue(set_dream_clue(saved_book, {"species": "bluegill"}))
        self.assertFalse(set_dream_clue(saved_book, {"species": "crappie"}))
        self.assertEqual(take_dream_clue(saved_book), {"species": "bluegill"})
        self.assertIsNone(take_dream_clue(saved_book))
        self.assertEqual(saved_book["dream_clue"], None)

    def test_book_content_validation_reports_multiple_errors_and_duplicate_keys(self):
        raw = json.loads(BOOK_CONTENT_PATH.read_text(encoding="utf-8"))
        broken = deepcopy(raw)
        broken["species_rumors"]["bluegill"]["text"] = ""
        broken["legendary_stories"]["old_lantern"]["teller"] = None
        with self.assertRaises(ContentError) as caught:
            validate_book_content(broken, source="book.json", species_ids=SPECIES_BY_ID)
        self.assertIn("book.json:species_rumors(bluegill).text", str(caught.exception))
        self.assertIn("book.json:legendary_stories(old_lantern).teller", str(caught.exception))
        with tempfile.TemporaryDirectory(prefix="trotline-book-") as directory:
            path = Path(directory) / "book.json"
            path.write_text('{"schema_version": 1, "schema_version": 1}')
            with self.assertRaisesRegex(ContentError, "duplicate JSON key"):
                load_book_content(path)

    def test_depth_and_book_history_survive_save_reload(self):
        state = State.new(self.world, seed=91)
        catch = Catch("bluegill", 0.5, 1, 0, "flats", "worm", 8, depth_m=1.75)
        self.assertEqual(Catch.from_json(catch.to_json()).depth_m, 1.75)
        state._note_journal(catch)
        state.v2["book"]["species"]["bluegill"]["future_field"] = {"kept": True}
        self.assertTrue(set_dream_clue(state.v2["book"], {"species": "carp"}))
        state.set_book_title("book_of_five_waters")
        state._note_journal(Catch("old_lantern", 24, 1, 0, "landing", "shad", 21,
                                  legendary=True))
        with tempfile.TemporaryDirectory(prefix="trotline-book-") as directory:
            path = Path(directory) / "save.json"
            state.save(path, update_stamp=False)
            loaded = State.load(path, self.world)
        self.assertEqual(loaded.v2["book"], state.v2["book"])
        self.assertEqual(loaded.v2["legendaries"], state.v2["legendaries"])
        loaded._note_journal(catch)
        self.assertEqual(len(loaded.v2["book"]["species"]["bluegill"]["found"]), 2)


if __name__ == "__main__":
    unittest.main()
