"""Validation and behavior contracts for the v2 gameplay data pipeline."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .boat import BOATS
from .content import ContentError, load_content_v2, validate_content_v2
from .data import (BAITS, BAIT_BY_ID, BAIT_MATCH, CEDAR_FISH, LINE_TIERS,
                   CONTENT_V2_RAW, LAKE_RATE_MULTIPLIERS, SPECIES, SPECIES_BY_ID, ZONE_MATCH, ZONE_ORDER,
                   bait_mult, zone_mult)
from .sim import Hook, SetLine, State, species_rates
from .world import World


class ContentV2Checks(unittest.TestCase):
    def test_data_loaders_keep_the_existing_gameplay_apis(self):
        content = load_content_v2()
        self.assertEqual(len(content.species), 36)
        self.assertEqual(len(content.baits), 5)
        self.assertEqual(set(content.boats), {"jon", "rowboat", "sail", "pontoon"})
        self.assertEqual(set(content.lakes), {"briar", "cedar"})
        self.assertEqual(len(SPECIES), 36)
        self.assertEqual(SPECIES_BY_ID["bluegill"].folk_name, "Sunny")
        self.assertEqual(SPECIES_BY_ID["bluegill"].lakes, ("briar", "cedar"))
        self.assertEqual(set(BAIT_BY_ID), {bait.id for bait in BAITS})
        self.assertIn("worm", BAIT_MATCH)
        self.assertIn("open", ZONE_MATCH)
        self.assertEqual(ZONE_ORDER[-1], "open")
        self.assertEqual(CEDAR_FISH["blue"], 2.4)
        self.assertEqual(CEDAR_FISH["smallmouth"], 0.0)
        self.assertEqual(LINE_TIERS["std"]["hooks"], 12)
        self.assertEqual(BOATS["pontoon"].traits, ("hammock",))
        self.assertEqual(bait_mult("unlisted", "bluegill"), 0.05)
        self.assertEqual(zone_mult("unlisted", "bluegill"), 0.07)

    def test_validator_collects_cross_file_errors_with_file_and_id(self):
        broken = deepcopy(CONTENT_V2_RAW)
        broken["species.json"]["species"][0]["price"] = -1
        broken["species.json"]["species"][1]["lakes"] = None
        broken["baits.json"]["baits"][0]["matches"]["missing_fish"] = 0.5
        broken["boats.json"]["boats"][0]["bow"] = -2
        broken["lakes.json"]["lakes"][0]["species_count"] = 999
        broken["lakes.json"]["lakes"][1]["rate_multipliers"]["smallmouth"] = 1.0
        broken["lakes.json"]["lakes"][1]["rate_multipliers"]["blue"] = 0.0

        with tempfile.TemporaryDirectory() as directory:
            for filename, raw in broken.items():
                (Path(directory) / filename).write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ContentError) as caught:
                load_content_v2(directory)
        message = str(caught.exception)
        for location in (
            "species.json:species[0](bluegill).price",
            "species.json:species[1](bullhead).lakes",
            "baits.json:baits[0](worm).matches.missing_fish",
            "boats.json:boats[0](jon).bow",
            "lakes.json:lakes[0](briar).species_count",
            "lakes.json:lakes[1](cedar).rate_multipliers(smallmouth)",
            "lakes.json:lakes[1](cedar).rate_multipliers(blue)",
        ):
            with self.subTest(location=location):
                self.assertIn(location, message)
        self.assertGreaterEqual(len(message.splitlines()), 4)

    def test_validator_preserves_save_referenced_ids(self):
        tables = (
            ("species.json", "species", "gar", "gar_renamed"),
            ("baits.json", "baits", "worm", "worm_renamed"),
            ("boats.json", "boats", "jon", "jon_renamed"),
            ("lakes.json", "lakes", "briar", "briar_renamed"),
        )
        for filename, group, old_id, new_id in tables:
            with self.subTest(group=group, id=old_id):
                broken = deepcopy(CONTENT_V2_RAW)
                row = next(row for row in broken[filename][group] if row["id"] == old_id)
                row["id"] = new_id
                with self.assertRaises(ContentError) as caught:
                    validate_content_v2(broken)
                self.assertIn(f"{filename}:{group}({old_id}): missing save-referenced ID",
                              str(caught.exception))

    def test_duplicate_and_non_string_ids_do_not_skip_row_value_checks(self):
        broken = deepcopy(CONTENT_V2_RAW)
        duplicate = deepcopy(broken["species.json"]["species"][1])
        duplicate["id"] = "bluegill"
        duplicate["price"] = -2
        invalid = deepcopy(broken["species.json"]["species"][2])
        invalid["id"] = 17
        invalid["price"] = -3
        broken["species.json"]["species"].extend((duplicate, invalid))

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)
        message = str(caught.exception)
        self.assertIn("species.json:species[36](bluegill).price", message)
        self.assertIn("species.json:species[37].price", message)
        self.assertIn("species.json:species[36](bluegill).id: duplicate ID 'bluegill'", message)
        self.assertIn("species.json:species[37].id: expected non-empty text", message)

    def test_unparseable_file_does_not_cascade_unknown_reference_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for filename, raw in CONTENT_V2_RAW.items():
                source = json.dumps(raw, indent=2)
                if filename == "species.json":
                    source = source.replace('"id": "bluegill"', '"id": "bluegill", "id": "bluegill"', 1)
                (Path(directory) / filename).write_text(source, encoding="utf-8")
            with self.assertRaises(ContentError) as caught:
                load_content_v2(directory)

        message = str(caught.exception)
        self.assertRegex(message, r"species\.json:root: duplicate JSON key 'id' at line \d+, column \d+")
        self.assertNotIn("unknown reference", message)
        self.assertEqual(len(message.splitlines()), 1)

    def test_lake_rate_map_limits_availability_to_the_declared_roster(self):
        with patch.dict(LAKE_RATE_MULTIPLIERS, {"partial": {"bluegill": 1.0}}):
            rates = species_rates("open", "worm", 12.0, "clear", 5.0, lake_id="partial")

        self.assertGreater(rates["bluegill"], 0.0)
        self.assertEqual(rates["gar"], 0.0)
        self.assertEqual(rates["smallmouth"], 0.0)

    def test_seeded_thousand_step_fishing_outcomes_are_bit_identical(self):
        world = World("briar")
        state = State.new(world, seed=73021)
        outcomes = []
        record = state._note_journal

        def collect(catch, announce=False):
            outcomes.append((
                catch.species,
                catch.weight.hex(),
                catch.catch_game_minute.hex(),
                catch.zone,
                catch.bait,
                catch.hour.hex(),
                catch.lake_id,
            ))
            return record(catch, announce=announce)

        state._note_journal = collect
        state.lines.append(SetLine(
            "std", "worm", 100.0, 100.0, 100.0, 100.0, "open",
            [Hook(True) for _ in range(12)],
        ))
        for _ in range(1000):
            state.advance(1.0, frozen=False)

        self.assertEqual(outcomes, [
            ("bluegill", "0x1.9a1521e7aa5aap-3", "0x1.8c00000000000p+8",
             "open", "worm", "0x1.9333333333333p+3", "briar"),
            ("carp", "0x1.3c26136d49b5ap+1", "0x1.8b80000000000p+9",
             "open", "worm", "0x1.32eeeeeeeeeefp+4", "briar"),
        ])
        self.assertEqual((state.game_minutes, state.hooked_total, state.rng.s),
                         (1000.0, 2, 16426900400529033108))


if __name__ == "__main__":
    unittest.main()
