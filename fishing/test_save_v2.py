"""Save envelope, v1 migration, backup recovery, and forward-compatibility tests."""

from __future__ import annotations

import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import savepaths
from .gamepad import default_key_bindings
from .narrative import QUEST_IDS
from .savepaths import (UnsupportedSaveVersionError, book_stage,
                        load_game_save)
from .sim import State
from .ui import UI, UIState
from .world import World


FIXTURES = Path(__file__).with_name("fixtures") / "save_v2"
V1_FIXTURES = ("fresh.json", "mid_game.json", "v3_complete.json", "guardian_seen.json")


class SaveV2Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trotline-save-v2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.save_path = self.root / "platform" / "save.json"
        self.legacy_path = self.root / "install" / "saves" / "briar.json"

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def expected_migrated_value(key, value):
        if key != "lines" or not isinstance(value, list):
            return value
        lines = []
        for old_line in value:
            line = dict(old_line)
            sections = line.pop("bait_sections", None)
            if (not isinstance(sections, list) or not 1 <= len(sections) <= 3
                    or any(not isinstance(bait, str) for bait in sections)):
                legacy_bait = line.pop("bait", "worm")
                sections = [legacy_bait if isinstance(legacy_bait, str) else "worm"]
            line["bait"] = sections[0]
            line["bait_sections"] = sections
            lines.append(line)
        return lines

    def migrate_fixture(self, name):
        self.save_path = self.root / name / "platform" / "save.json"
        self.legacy_path = self.root / name / "install" / "saves" / "briar.json"
        fixture = FIXTURES / name
        old_bytes = fixture.read_bytes()
        original = json.loads(old_bytes)
        self.legacy_path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy_path.write_bytes(old_bytes)
        world, state, has_save = load_game_save(
            self.save_path, State, World, legacy_path=self.legacy_path)
        self.assertTrue(has_save)
        self.assertEqual(world.id, original.get("lake_id", "briar"))
        self.assertEqual(self.legacy_path.read_bytes(), old_bytes)
        migrated = self.read(self.save_path)
        self.assertEqual(migrated["version"], 2)
        for key, value in original.items():
            if key != "version":
                self.assertIn(key, migrated, f"{name}: missing v1 key {key}")
                self.assertEqual(migrated.get(key), self.expected_migrated_value(key, value),
                                 f"{name}: {key}")
        backups = savepaths.backup_candidates(self.save_path)
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0].name, r"^briar\.v1\.\d{8}T\d{12}Z\.json$")
        self.assertEqual(backups[0].read_bytes(), old_bytes)
        return original, migrated, state

    def test_all_committed_v1_fixtures_migrate_and_roundtrip_without_losing_v1_fields(self):
        for name in V1_FIXTURES:
            with self.subTest(fixture=name):
                self.save_path = self.root / name / "platform" / "save.json"
                self.legacy_path = self.root / name / "install" / "saves" / "briar.json"
                original, migrated, state = self.migrate_fixture(name)
                self.assertEqual(len(savepaths.backup_candidates(self.save_path)), 1)
                self.assertIn("v2", migrated)
                # A second startup reads v2 directly and neither makes a backup
                # nor changes any v1 field.
                world, second, has_save = load_game_save(
                    self.save_path, State, World, legacy_path=self.legacy_path)
                self.assertTrue(has_save)
                self.assertEqual(world.id, original.get("lake_id", "briar"))
                self.assertEqual(len(savepaths.backup_candidates(self.save_path)), 1)
                result = second.to_json()
                for key, value in original.items():
                    if key != "version":
                        self.assertEqual(result.get(key), self.expected_migrated_value(key, value),
                                         f"{name}: {key}")

    def test_v2_defaults_and_migration_derived_book_stages(self):
        _, fresh, _ = self.migrate_fixture("fresh.json")
        defaults = fresh["v2"]
        self.assertEqual(defaults["mode"], "cozy")
        self.assertEqual(defaults["profile"]["bot_name"], "Copper-000")
        self.assertEqual(defaults["profile"]["shell"], "tin")
        self.assertEqual(defaults["profile"]["shells"], ["tin"])
        self.assertEqual(defaults["profile"]["tools"], [])
        self.assertEqual(defaults["profile"]["collar"],
                         {"stage": "none", "knot": None, "visible": True})
        self.assertEqual(defaults["needs"], {
            "awake_h": 0.0, "since_meal_h": 0.0, "rested_until": None,
            "last_prompt_real_s": 0,
        })
        self.assertIsNone(defaults["buff"])
        self.assertEqual(defaults["pantry"], {"herbs": 0})
        self.assertEqual(defaults["recipes"], [])
        self.assertEqual(defaults["dishes_known"], [])
        self.assertEqual(defaults["boat_extras"], {})
        self.assertEqual(defaults["book"]["tracked"], None)
        self.assertEqual(defaults["book"]["species"], {})
        self.assertEqual(defaults["book"]["title"], "fishypedia")
        self.assertIsNone(defaults["book"]["dream_clue"])
        self.assertEqual(defaults["story"]["chapter"], 0)
        self.assertEqual(defaults["story"]["steps"], {})
        self.assertEqual(defaults["story"]["pending_rewards"], [])
        self.assertEqual(defaults["story"]["scene_states"], {})
        self.assertEqual(defaults["legendaries"], {})
        self.assertEqual(defaults["npcs"], {"letters": [], "talk_days": {}})
        self.assertEqual(defaults["keepsakes"], [])
        self.assertEqual(defaults["ripples_v2"], [])
        self.assertEqual(defaults["calendar"], {"weather_windows": {}})
        self.assertEqual(defaults["settings"], {
            "mode": "cozy", "text_size": 1, "dyslexia_font": False,
            "reduced_motion": False, "captions": True,
            "volumes": {"master": 1.0, "music": 1.0,
                        "ambience": 1.0, "sfx": 1.0},
            "collar_visible": True,
            "key_bindings": default_key_bindings(),
        })
        self.assertEqual(defaults["reward_claims"], {
            "story": [], "legendary_record": [], "book_stage_up": [],
        })

        _, mid, _ = self.migrate_fixture("mid_game.json")
        self.assertEqual(book_stage(mid["journal"]["bluegill"]["count"]), "bait_known")
        self.assertEqual(mid["v2"]["book"]["species"]["bluegill"], {
            "found": [{"zone": "flats", "bait": "worm", "band": "dawn"}],
            "shiny": 0, "since_shiny": 3,
        })
        self.assertEqual(mid["v2"]["profile"]["bot_name"], "Copper-517")
        self.assertEqual(mid["v2"]["story"]["scene_states"], {"prologue": "done"})
        self.assertIn("prologue", mid["v2"]["story"]["scenes_seen"])

        _, complete, _ = self.migrate_fixture("v3_complete.json")
        self.assertEqual(book_stage(complete["journal"]["bluegill"]["count"]), "mastered")
        self.assertEqual(complete["narrative_v1"]["reward_claims"], list(QUEST_IDS))

        _, guardian, _ = self.migrate_fixture("guardian_seen.json")
        self.assertTrue(guardian["narrative_v1"]["guardian_seen"])
        self.assertEqual(guardian["v2"]["profile"]["bot_name"], "Copper-316")
        self.assertEqual([book_stage(n) for n in (0, 1, 3, 5, 10)],
                         ["rumor", "identified", "bait_known", "verified", "mastered"])

    def test_unknown_fields_survive_at_root_narrative_line_catch_and_v2_levels(self):
        self.migrate_fixture("mid_game.json")
        raw = self.read(self.save_path)
        raw["v2"]["future_domain"] = {"version": 9}
        raw["v2"]["profile"]["future_profile_field"] = {"kept": True}
        raw["v2"]["settings"]["future_setting"] = ["large", "text"]
        raw["v2"]["needs"]["last_prompt_real_s"] = 1729.5
        raw["v2"]["story"]["scene_states"]["future_scene"] = "skipped"
        raw["v2"]["settings"]["text_size"] = "large"
        raw["boat_id"] = "future_skiff"
        raw["owned_boats"].remove("jon")
        raw["owned_boats"].append("future_skiff")
        raw["fuel_tanks"]["future_skiff"] = 6.75
        self.save_path.write_text(json.dumps(raw), encoding="utf-8")

        world, state, has_save = load_game_save(self.save_path, State, World)
        self.assertTrue(has_save)
        self.assertEqual(state.boat_id, "jon")
        state.save(self.save_path)
        roundtrip = self.read(self.save_path)
        self.assertEqual(roundtrip["future_v1_marker"], {"source": "fixture", "keep": True})
        self.assertEqual(roundtrip["narrative_v1"]["future_narrative_marker"], {"revision": 4})
        self.assertEqual(roundtrip["narrative_v1"]["quests"][QUEST_IDS[0]]["future_quest_marker"],
                         ["retain", 2])
        self.assertEqual(roundtrip["narrative_v1"]["quests"]["future_quest_v1"],
                         {"status": "ready", "progress": {"future_step": True}})
        self.assertIn("future_ripple_v1", roundtrip["narrative_v1"]["ripples"])
        self.assertIn("future_quest_v1", roundtrip["narrative_v1"]["reward_claims"])
        self.assertEqual(roundtrip["narrative_v1"]["day_npc_by_lake"]["flathead"],
                         "future_cat")
        self.assertEqual(roundtrip["narrative_v1"]["schedule_day_by_lake"]["flathead"], 4)
        self.assertEqual(roundtrip["narrative_v1"]["bot_reactions"]["quest:future_quest_v1"],
                         "Bot: Future progress retained.")
        self.assertEqual(roundtrip["lines"][0]["future_line_marker"], {"material": "legacy"})
        self.assertEqual(roundtrip["lines"][0]["hooks"][0]["future_hook_marker"], "steady")
        self.assertEqual(roundtrip["lines"][0]["hooks"][0]["catch"]["future_catch_marker"], 6)
        self.assertTrue(roundtrip["bot"]["future_bot_marker"])
        self.assertEqual(roundtrip["v2"]["future_domain"], {"version": 9})
        self.assertEqual(roundtrip["v2"]["profile"]["future_profile_field"], {"kept": True})
        self.assertEqual(roundtrip["v2"]["settings"]["future_setting"], ["large", "text"])
        self.assertEqual(roundtrip["v2"]["needs"]["last_prompt_real_s"], 1729.5)
        self.assertEqual(roundtrip["v2"]["story"]["scene_states"]["future_scene"],
                         "skipped")
        self.assertEqual(roundtrip["v2"]["settings"]["text_size"], 1)
        self.assertEqual(roundtrip["owned_boats"], ["sail", "future_skiff"])
        self.assertEqual(roundtrip["boat_id"], "future_skiff")
        self.assertEqual(roundtrip["fuel_tanks"]["future_skiff"], 6.75)

    def test_v2_reward_claims_and_pending_done_scenes_are_idempotent(self):
        world = World()
        state = State.new(world, seed=22)
        starting_money = state.money
        for kind in ("story", "legendary_record", "book_stage_up"):
            with self.subTest(kind=kind):
                self.assertTrue(state.claim_reward(kind, "reward-1"))
                state.money += 5
                self.assertFalse(state.claim_reward(kind, "reward-1"))
        self.assertFalse(state.claim_reward("unknown_kind", "reward-1"))
        self.assertFalse(state.claim_reward("story", ""))
        quest_id = QUEST_IDS[0]
        state.narrative.quests[quest_id].status = "ready"
        self.assertTrue(state.narrative.record_reward_claim(quest_id))
        self.assertFalse(state.narrative.record_reward_claim(quest_id))
        balance = starting_money + 15
        self.assertEqual(state.money, balance)
        self.assertTrue(state.set_scene_status("ending", "pending"))
        self.assertFalse(state.set_scene_status("ending", "invalid"))
        path = self.save_path
        state.save(path)

        loaded = State.load(path, world)
        self.assertEqual(loaded.money, balance)
        self.assertEqual(loaded.v2["story"]["scene_states"]["ending"], "pending")
        self.assertNotIn("ending", loaded.v2["story"]["scenes_seen"])
        for kind in ("story", "legendary_record", "book_stage_up"):
            self.assertIn("reward-1", loaded.v2["reward_claims"][kind])
            self.assertFalse(loaded.claim_reward(kind, "reward-1"))
        self.assertIn(quest_id, loaded.narrative.reward_claims)
        self.assertFalse(loaded.narrative.record_reward_claim(quest_id))
        self.assertTrue(loaded.set_scene_status("ending", "done"))
        self.assertIn("ending", loaded.v2["story"]["scenes_seen"])
        self.assertFalse(loaded.set_scene_status("ending", "pending"))

    def test_corrupt_v2_recovers_the_newest_backup_and_shows_a_toast_once(self):
        backup_dir = savepaths.backup_directory(self.save_path)
        backup_dir.mkdir(parents=True)
        older = json.loads((FIXTURES / "fresh.json").read_text(encoding="utf-8"))
        newer = json.loads((FIXTURES / "mid_game.json").read_text(encoding="utf-8"))
        older_path = backup_dir / "briar.v1.20260101T000000000000Z.json"
        newer_path = backup_dir / "briar.v1.20260102T000000000000Z.json"
        older_path.write_text(json.dumps(older), encoding="utf-8")
        newer_path.write_text(json.dumps(newer), encoding="utf-8")
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        invalid_bytes = b'{ "version": 2, "v2": [broken active save'
        self.save_path.write_bytes(invalid_bytes)

        world, restored, has_save = load_game_save(self.save_path, State, World)
        self.assertTrue(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(restored.money, newer["money"])
        self.assertTrue(any("restored from a backup" in toast[0]
                            for toast in restored.toasts))
        self.assertEqual(self.read(self.save_path)["version"], 2)
        self.assertEqual(len(savepaths.backup_candidates(self.save_path)), 2)
        rejected = list(self.save_path.parent.glob("save.rejected.*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].read_bytes(), invalid_bytes)
        self.assertNotIn(rejected[0], savepaths.backup_candidates(self.save_path))

        _, next_launch, has_save = load_game_save(self.save_path, State, World)
        self.assertTrue(has_save)
        self.assertFalse(any("restored from a backup" in toast[0]
                             for toast in next_launch.toasts))
        self.assertEqual(len(savepaths.backup_candidates(self.save_path)), 2)

    def test_unreadable_newest_backup_is_skipped_for_older_valid_backup(self):
        backup_dir = savepaths.backup_directory(self.save_path)
        backup_dir.mkdir(parents=True)
        older = json.loads((FIXTURES / "fresh.json").read_text(encoding="utf-8"))
        newer = json.loads((FIXTURES / "mid_game.json").read_text(encoding="utf-8"))
        older_path = backup_dir / "briar.v1.20260101T000000000000Z.json"
        newer_path = backup_dir / "briar.v1.20260102T000000000000Z.json"
        older_path.write_text(json.dumps(older), encoding="utf-8")
        newer_path.write_text(json.dumps(newer), encoding="utf-8")
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        active_bytes = b"invalid active save"
        self.save_path.write_bytes(active_bytes)
        read_text = Path.read_text

        def fail_newest(path, *args, **kwargs):
            if path == newer_path:
                raise PermissionError("simulated unreadable backup")
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", new=fail_newest):
            world, restored, has_save = load_game_save(self.save_path, State, World)

        self.assertTrue(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(restored.money, older["money"])
        rejected = list(self.save_path.parent.glob("save.rejected.*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].read_bytes(), active_bytes)

    def test_invalid_utf8_active_save_recovers_from_backup_and_preserves_bytes(self):
        backup_dir = savepaths.backup_directory(self.save_path)
        backup_dir.mkdir(parents=True)
        backup = json.loads((FIXTURES / "mid_game.json").read_text(encoding="utf-8"))
        backup_path = backup_dir / "briar.v1.20260102T000000000000Z.json"
        backup_path.write_text(json.dumps(backup), encoding="utf-8")
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        invalid_bytes = b'{"version": 2, \xff\xfe broken save'
        self.save_path.write_bytes(invalid_bytes)

        world, restored, has_save = load_game_save(self.save_path, State, World)

        self.assertTrue(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(restored.money, backup["money"])
        rejected = list(self.save_path.parent.glob("save.rejected.*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].read_bytes(), invalid_bytes)
        self.assertEqual(self.read(self.save_path)["version"], 2)

    def test_invalid_utf8_newest_backup_is_skipped_for_older_valid_backup(self):
        backup_dir = savepaths.backup_directory(self.save_path)
        backup_dir.mkdir(parents=True)
        older = json.loads((FIXTURES / "fresh.json").read_text(encoding="utf-8"))
        older_path = backup_dir / "briar.v1.20260101T000000000000Z.json"
        newer_path = backup_dir / "briar.v1.20260102T000000000000Z.json"
        older_path.write_text(json.dumps(older), encoding="utf-8")
        invalid_backup = b"\xff\xfe not utf-8"
        newer_path.write_bytes(invalid_backup)
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        active_bytes = b"corrupt active save"
        self.save_path.write_bytes(active_bytes)

        world, restored, has_save = load_game_save(self.save_path, State, World)

        self.assertTrue(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(restored.money, older["money"])
        self.assertEqual(newer_path.read_bytes(), invalid_backup)
        rejected = list(self.save_path.parent.glob("save.rejected.*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].read_bytes(), active_bytes)

    def test_corrupt_active_save_without_backup_does_not_overwrite_from_legacy(self):
        self.save_path.parent.mkdir(parents=True)
        active_bytes = b"corrupt active save"
        self.save_path.write_bytes(active_bytes)
        legacy_bytes = (FIXTURES / "mid_game.json").read_bytes()
        self.legacy_path.parent.mkdir(parents=True)
        self.legacy_path.write_bytes(legacy_bytes)

        world, state, has_save = load_game_save(
            self.save_path, State, World, legacy_path=self.legacy_path)

        self.assertFalse(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(self.save_path.read_bytes(), active_bytes)
        self.assertEqual(self.legacy_path.read_bytes(), legacy_bytes)
        self.assertEqual(savepaths.backup_candidates(self.save_path), [])
        rejected = list(self.save_path.parent.glob("save.rejected.*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].read_bytes(), active_bytes)
        self.assertTrue(any("could not be restored" in toast[0]
                            for toast in state.toasts))

        # A later autosave for the new game may replace the active path, but
        # it cannot destroy the only copy of the rejected bytes.
        state.save(self.save_path)
        self.assertEqual(self.read(self.save_path)["version"], 2)
        self.assertEqual(rejected[0].read_bytes(), active_bytes)

    def test_future_save_version_fails_without_downgrading_or_replacing_files(self):
        self.migrate_fixture("mid_game.json")
        active = self.read(self.save_path)
        active["money"] = 99999
        active["version"] = 3
        active_bytes = json.dumps(active).encode("utf-8")
        self.save_path.write_bytes(active_bytes)
        backups_before = {path: path.read_bytes()
                          for path in savepaths.backup_candidates(self.save_path)}
        legacy_before = self.legacy_path.read_bytes()

        with self.assertRaisesRegex(UnsupportedSaveVersionError,
                                    "update the game before loading"):
            load_game_save(self.save_path, State, World,
                           legacy_path=self.legacy_path)

        self.assertEqual(self.save_path.read_bytes(), active_bytes)
        self.assertEqual({path: path.read_bytes() for path in backups_before},
                         backups_before)
        self.assertEqual(self.legacy_path.read_bytes(), legacy_before)
        self.assertEqual(list(self.save_path.parent.glob("save.rejected.*.json")), [])

    def test_malformed_v2_envelope_defaults_without_discarding_legacy_progress(self):
        self.migrate_fixture("mid_game.json")
        raw = self.read(self.save_path)
        raw["money"] = 9876.5
        raw["v2"] = []
        self.save_path.write_text(json.dumps(raw), encoding="utf-8")

        world, state, has_save = load_game_save(self.save_path, State, World)

        self.assertTrue(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(state.money, 9876.5)
        self.assertEqual(state.v2["mode"], "cozy")
        self.assertEqual(state.v2["story"]["scene_states"], {"prologue": "done"})

    def test_recovery_toast_is_rendered_on_the_title_screen(self):
        world = World()
        state = State.new(world)
        state.toast("Your save was restored from a backup.")
        ui = UI(None, world)
        frame = np.zeros((120, 240, 3), dtype=np.uint8)
        ui_state = UIState(mode="title")
        with patch.object(ui, "_title") as draw_title, \
                patch.object(ui, "_toasts") as draw_toasts:
            ui.draw(frame, state, ui_state)
        draw_title.assert_called_once_with(frame, state, ui_state)
        draw_toasts.assert_called_once_with(frame, state, ui_state.input_device)

    def test_save_override_and_sdl_pref_path_selection(self):
        args, override = savepaths.parse_save_option(["--software", "--save", "folder/my save.json"])
        self.assertEqual(args, ["--software"])
        self.assertEqual(override, Path("folder/my save.json"))
        args, override = savepaths.parse_save_option(["--save=/tmp/save.json", "--selftest"])
        self.assertEqual(args, ["--selftest"])
        self.assertEqual(override, Path("/tmp/save.json"))
        with self.assertRaises(ValueError):
            savepaths.parse_save_option(["--save"])
        with self.assertRaises(ValueError):
            savepaths.parse_save_option(["--save", "a.json", "--save", "b.json"])

        with patch.object(savepaths, "sdl_pref_path", return_value=self.root / "platform"):
            self.assertEqual(savepaths.resolve_save_path(), self.root / "platform" / "save.json")
            self.assertEqual(savepaths.resolve_save_path("explicit.json"), Path("explicit.json"))

        from .__main__ import main
        with patch("fishing.game.run") as run:
            self.assertEqual(main(["--software", "--save", str(self.save_path)]), 0)
        run.assert_called_once_with(software=True, save_path=self.save_path)

        from .game import _save_target
        with patch("fishing.game.resolve_save_path", side_effect=RuntimeError("SDL failed")):
            self.assertEqual(_save_target(self.root, None),
                             (self.root / "saves" / "save.json", True))
            with self.assertRaisesRegex(RuntimeError, "SDL failed"):
                _save_target(self.root, self.save_path)

        output = StringIO()
        with patch("fishing.game.run", side_effect=UnsupportedSaveVersionError(3, 2)), \
                redirect_stderr(output):
            self.assertEqual(main([]), 1)
        self.assertIn("update the game before loading", output.getvalue())

    def test_explicit_v1_save_override_gets_backed_up_before_replacement(self):
        override = self.root / "override" / "save.json"
        override.parent.mkdir(parents=True)
        raw = (FIXTURES / "mid_game.json").read_bytes()
        override.write_bytes(raw)
        world, state, has_save = load_game_save(override, State, World)
        self.assertTrue(has_save)
        self.assertEqual(world.id, "briar")
        self.assertEqual(self.read(override)["version"], 2)
        backups = savepaths.backup_candidates(override)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), raw)
        self.assertEqual(state.money, json.loads(raw)["money"])


if __name__ == "__main__":
    unittest.main()
