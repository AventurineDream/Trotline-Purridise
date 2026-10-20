"""Validation and behavior contracts for the v2 gameplay data pipeline."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .boat import BOATS
from .content import (ContentError, _load_all_content, load_content_v2,
                      validate_content_v2)
from .data import (BAITS, BAIT_BY_ID, BAIT_MATCH, CEDAR_FISH, LINE_TIERS,
                   CONTENT_V2_RAW, LAKE_RATE_MULTIPLIERS, SPECIES, SPECIES_BY_ID, ZONE_MATCH, ZONE_ORDER,
                   _species_values, _validate_content_v2_files, bait_mult, zone_mult)
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
            "species.json:species[36](new_fish).lakes: species must belong to at least one lake",
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

    def test_runtime_validation_reports_structural_errors_before_building_objects(self):
        broken = deepcopy(CONTENT_V2_RAW)
        del broken["baits.json"]["baits"][0]["matches"]

        with self.assertRaises(ContentError) as caught:
            _validate_content_v2_files(broken)

        self.assertIn("baits.json:baits[0](worm): missing required field 'matches'", str(caught.exception))

    def test_cli_reports_v1_and_v2_errors_together(self):
        with patch("fishing.content.load_content", side_effect=ContentError("narrative.json:root: bad v1")), \
                patch("fishing.content.load_content_v2", side_effect=ContentError("species.json:root: bad v2")):
            with self.assertRaises(ContentError) as caught:
                _load_all_content()

        self.assertEqual(str(caught.exception), "narrative.json:root: bad v1\nspecies.json:root: bad v2")

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
