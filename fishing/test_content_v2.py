"""Validation and behavior contracts for the v2 gameplay data pipeline."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .boat import BOATS
from .content import ContentError, load_content_v2, validate_content_v2
from .data import (BAITS, BAIT_BY_ID, BAIT_MATCH, CEDAR_FISH, LINE_TIERS,
                   CONTENT_V2_RAW, LAKE_RATE_MULTIPLIERS, SPECIES, SPECIES_BY_ID, ZONE_MATCH, ZONE_ORDER,
                   _species_values, _validate_content_v2_files, bait_mult, zone_mult)
from .sim import Hook, SetLine, State, species_rates
from .world import World


class ContentV2Checks(unittest.TestCase):
    def test_data_loaders_keep_the_existing_gameplay_apis(self):
        content = load_content_v2()
        self.assertEqual(len(content.species), 144)
        self.assertEqual(len(content.baits), 17)
        self.assertEqual(len(content.pantry), 6)
        self.assertEqual(len(content.dishes), 10)
        self.assertEqual(len(content.boats), 24)
        self.assertLessEqual({"jon", "rowboat", "sail", "pontoon"}, set(content.boats))
        self.assertEqual(set(content.lakes), {"briar", "cedar", "flathead", "crater", "nebula"})
        self.assertEqual(len(SPECIES), 144)
        self.assertEqual(SPECIES_BY_ID["bluegill"].folk_name, "Sunny")
        self.assertEqual(SPECIES_BY_ID["bluegill"].lakes, ("briar", "cedar"))
        self.assertEqual(set(BAIT_BY_ID), {bait.id for bait in BAITS})
        self.assertIn("worm", BAIT_MATCH)
        self.assertIn("open", ZONE_MATCH)
        self.assertEqual(ZONE_ORDER[:8], ("landing", "inlet", "flats", "lilies", "cypress", "rocks", "deep", "open"))
        self.assertEqual(ZONE_ORDER[8:], ("reeds", "springs", "current"))
        self.assertEqual(CEDAR_FISH["blue"], 2.4)
        self.assertEqual(CEDAR_FISH["smallmouth"], 0.0)
        self.assertEqual(LINE_TIERS["std"]["hooks"], 12)
        self.assertEqual(BOATS["pontoon"].traits, ("hammock",))
        self.assertEqual({boat_id: BOATS[boat_id].lines for boat_id in ("jon", "rowboat", "sail", "pontoon")}, {
            "jon": 5, "rowboat": 5, "sail": 5, "pontoon": 6,
        })
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
        self.assertEqual(sorted(message.splitlines()), sorted([
            "species.json:species[0](bluegill).price: expected finite number >= 0",
            "species.json:species[0](bluegill).price: must be greater than zero",
            "species.json:species[1](bullhead).lakes: expected a list",
            "species.json:species[1](bullhead).lakes: species must belong to at least one lake",
            "species.json:species[1](bullhead).lakes: must retain baseline lake membership 'briar'",
            "species.json:species[1](bullhead).lakes: must retain baseline lake membership 'cedar'",
            "baits.json:baits[0](worm).matches.missing_fish: unknown reference 'missing_fish'",
            "boats.json:boats[0](jon).bow: expected finite number >= 0",
            "boats.json:boats[0](jon).bow: must be forward of stern",
            "lakes.json:lakes[0](briar).species_count: declares 999, but lists 36 species",
            "lakes.json:lakes[1](cedar).rate_multipliers(blue): must be positive exactly when the species is listed in species_ids",
            "lakes.json:lakes[1](cedar).rate_multipliers(smallmouth): must be positive exactly when the species is listed in species_ids",
        ]))

    def test_validator_preserves_save_referenced_ids(self):
        tables = (
            ("species.json", "species", "gar", "gar_renamed"),
            ("baits.json", "baits", "worm", "worm_renamed"),
            ("boats.json", "boats", "jon", "jon_renamed"),
            ("lakes.json", "lakes", "briar", "briar_renamed"),
            ("lakes.json", "zones", "landing", "landing_renamed"),
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

    def test_rate_map_missing_entry_names_the_species(self):
        broken = deepcopy(CONTENT_V2_RAW)
        del broken["lakes.json"]["lakes"][1]["rate_multipliers"]["carp"]

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)

        self.assertIn(
            "lakes.json:lakes[1](cedar).rate_multipliers(carp): missing rate entry for species 'carp'",
            str(caught.exception),
        )

    def test_zone_order_and_label_errors_name_the_zone(self):
        broken = deepcopy(CONTENT_V2_RAW)
        broken["lakes.json"]["zone_order"].remove("rocks")
        del broken["lakes.json"]["lakes"][1]["zone_labels"]["rocks"]

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)

        message = str(caught.exception)
        self.assertIn("lakes.json:zone_order(rocks): missing fishing zone from zone_order", message)
        self.assertIn("lakes.json:lakes[1](cedar).zone_labels.rocks: missing label for zone 'rocks'", message)

    def test_species_keep_baseline_lake_memberships(self):
        broken = deepcopy(CONTENT_V2_RAW)
        bluegill = next(row for row in broken["species.json"]["species"] if row["id"] == "bluegill")
        bluegill["lakes"].remove("cedar")
        cedar = broken["lakes.json"]["lakes"][1]
        cedar["species_ids"].remove("bluegill")
        cedar["species_count"] -= 1
        cedar["rate_multipliers"]["bluegill"] = 0.0

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)

        self.assertIn(
            "species.json:species[0](bluegill).lakes: must retain baseline lake membership 'cedar'",
            str(caught.exception),
        )

    def test_species_must_belong_to_at_least_one_lake(self):
        broken = deepcopy(CONTENT_V2_RAW)
        new_species = deepcopy(broken["species.json"]["species"][0])
        new_species["id"] = "new_fish"
        new_species["name"] = "New Fish"
        new_species["lakes"] = []
        broken["species.json"]["species"].append(new_species)
        broken["lakes.json"]["lakes"][1]["rate_multipliers"]["new_fish"] = 0.0

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)

        self.assertIn(
            "species.json:species[144](new_fish).lakes: species must belong to at least one lake",
            str(caught.exception),
        )

    def test_species_rows_use_tier_defaults_with_explicit_overrides(self):
        content = deepcopy(CONTENT_V2_RAW)
        defaulted = content["species.json"]["species"][0]
        defaulted["tier"] = "C"
        defaulted.pop("rate")
        defaulted.pop("trophy")
        overridden = content["species.json"]["species"][1]
        overridden["tier"] = "R"
        overridden.pop("rate")
        overridden["trophy"] = 0.2

        validate_content_v2(content)
        defaulted_values = _species_values(defaulted)
        overridden_values = _species_values(overridden)
        self.assertEqual((defaulted_values["rate"], defaulted_values["trophy"]), (0.03, 0.04))
        self.assertEqual((overridden_values["rate"], overridden_values["trophy"]), (0.005, 0.2))

        no_default = deepcopy(CONTENT_V2_RAW)
        no_default["species.json"]["species"][0].pop("rate")
        no_default["species.json"]["species"][0].pop("trophy")
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(no_default)
        self.assertIn("species.json:species[0](bluegill).rate: missing required field 'rate'", str(caught.exception))
        self.assertIn("species.json:species[0](bluegill).trophy: missing required field 'trophy'", str(caught.exception))

    def test_boat_handling_factors_must_be_positive(self):
        broken = deepcopy(CONTENT_V2_RAW)
        jon = broken["boats.json"]["boats"][0]
        for field in ("speed_factor", "turn_factor", "acceleration"):
            jon[field] = 0

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)

        for field in ("speed_factor", "turn_factor", "acceleration"):
            self.assertIn(f"boats.json:boats[0](jon).{field}: must be greater than zero", str(caught.exception))

    def test_boat_line_capacity_must_be_an_integer_from_three_to_eight(self):
        for value in (2, 9, 4.5):
            with self.subTest(value=value):
                broken = deepcopy(CONTENT_V2_RAW)
                broken["boats.json"]["boats"][0]["lines"] = value
                with self.assertRaises(ContentError) as caught:
                    validate_content_v2(broken)
                self.assertIn("boats.json:boats[0](jon).lines: expected finite integer >= 3 and <= 8",
                              str(caught.exception))

    def test_protected_species_may_have_no_sale_price(self):
        protected = deepcopy(CONTENT_V2_RAW)
        species = protected["species.json"]["species"][0]
        species["price"] = 0
        species["tags"].append("protected")
        validate_content_v2(protected)

        unprotected = deepcopy(CONTENT_V2_RAW)
        unprotected["species.json"]["species"][0]["price"] = 0
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(unprotected)
        self.assertIn(
            "species.json:species[0](bluegill).price: must be greater than zero",
            str(caught.exception),
        )

    def test_runtime_validation_reports_structural_errors_before_building_objects(self):
        broken = deepcopy(CONTENT_V2_RAW)
        del broken["baits.json"]["baits"][0]["matches"]

        with self.assertRaises(ContentError) as caught:
            _validate_content_v2_files(broken)

        self.assertIn("baits.json:baits[0](worm): missing required field 'matches'", str(caught.exception))

    def test_cli_reports_v1_and_v2_errors_together_without_mocks(self):
        source_package = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "fishing"
            required_files = (
                "__init__.py", "content.py", "narrative.py", "data.py",
                "assets/narrative_v1.json",
                "assets/content_v2/species.json", "assets/content_v2/baits.json",
                "assets/content_v2/boats.json", "assets/content_v2/lakes.json",
            )
            for relative_path in required_files:
                source = source_package / relative_path
                target = package / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            narrative_path = package / "assets/narrative_v1.json"
            narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
            narrative["quests"][0]["objective"]["zone_id"] = "briar:shore"
            narrative_path.write_text(json.dumps(narrative), encoding="utf-8")

            species_path = package / "assets/content_v2/species.json"
            species = json.loads(species_path.read_text(encoding="utf-8"))
            species["species"][0].pop("name")
            species_path.write_text(json.dumps(species), encoding="utf-8")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(root)
            result = subprocess.run(
                [sys.executable, "-m", "fishing.content"], cwd=root, env=env,
                text=True, capture_output=True, check=False,
            )

        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("narrative_v1.json:q01_tea_leaves_deep_holes.objective.zone_id", combined)
        self.assertIn("unknown reference/value 'briar:shore'", combined)
        self.assertIn("species.json:species[0](bluegill): missing required field 'name'", combined)

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
        self.assertIn("species.json:species[144](bluegill).price", message)
        self.assertIn("species.json:species[145].price", message)
        self.assertIn("species.json:species[144](bluegill).id: duplicate ID 'bluegill'", message)
        self.assertIn("species.json:species[145].id: expected non-empty text", message)

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

    def test_an_unreadable_file_quests_name_is_reported_once(self):
        # The shipped quests (V1-32) name species, baits, zones, tools, legendaries, cats and rewards.
        for unreadable in ("species.json", "baits.json", "lakes.json", "bot.json", "legendaries.json",
                           "npcs.json", "ripples.json", "keepsakes.json", "quests.json"):
            with self.subTest(file=unreadable), tempfile.TemporaryDirectory() as directory:
                for filename, raw in CONTENT_V2_RAW.items():
                    source = json.dumps(raw, indent=2)
                    if filename == unreadable:
                        source = source.replace('"schema_version"', '"schema_version": 2, "schema_version"', 1)
                    (Path(directory) / filename).write_text(source, encoding="utf-8")
                with self.assertRaises(ContentError) as caught:
                    load_content_v2(directory)
                lines = str(caught.exception).splitlines()
                self.assertEqual(len(lines), 1, lines[:4])
                self.assertTrue(lines[0].startswith(unreadable + ":root: duplicate JSON key"), lines[0])

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
                catch.shiny,
            ))
            return record(catch, announce=announce)

        state._note_journal = collect
        state.lines.append(SetLine(
            "std", "worm", 100.0, 100.0, 100.0, 100.0, "open",
            [Hook(True) for _ in range(12)],
        ))
        # Keep the original data/RNG contract independent of calendar weather.
        # Calendar reproducibility and live rates are covered in test_calendar.
        from .data import weather_at as reference_weather
        with patch("fishing.sim.weather_at", side_effect=lambda st: reference_weather(st.game_minutes)):
            for _ in range(1000):
                state.advance(1.0, frozen=False)

        # Catch creation now consumes one shiny roll from the saved RNG.
        # Pin that sequence, including the flag, rather than the pre-shiny one.
        self.assertEqual(outcomes, [
            ("bluegill", "0x1.9a1521e7aa5aap-3", "0x1.8c00000000000p+8",
             "open", "worm", "0x1.9333333333333p+3", "briar", False),
            ("carp", "0x1.3c26136d49b5ap+1", "0x1.8b00000000000p+9",
             "open", "worm", "0x1.32aaaaaaaaaabp+4", "briar", False),
        ])
        self.assertEqual((state.game_minutes, state.hooked_total, state.rng.s),
                         (1000.0, 2, 9380871146142679977))


if __name__ == "__main__":
    unittest.main()
