"""Named-save storage, session isolation and displayed menu regressions for #144.

All persistence uses temporary directories. Headless key and native-font pointer
checks exercise the same UI state as play without opening an SDL window.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import pointer, saveslots, skipperlook
from .game import Keys, Session
from .platform import Text
from .sim import State
from .test_skipper_creator import tap
from .ui import UI, UIState, title_options
from .world import World


class SlotStorageChecks(unittest.TestCase):
    """Check portable paths and metadata without loading an authored world."""

    def setUp(self):
        """Give every storage check an isolated main-save path."""
        temporary = tempfile.TemporaryDirectory(prefix="trotline-slots-")
        self.addCleanup(temporary.cleanup)
        self.default = Path(temporary.name) / "save.json"
        self.root = saveslots.slot_root(self.default)

    def write_save(self, path, raw):
        """Write raw JSON to path, creating only this fixture's parent directories."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw), encoding="utf-8")

    def test_slugs_are_portable_bounded_and_cannot_escape_the_slot_root(self):
        """Sanitize traversal, separators, device names, empty and Unicode names."""
        for name, expected in (("../evil", "evil"), ("a/b\\c", "a-b-c"), ("", "slot"),
                               ("...", "slot"), ("猫🐟", "slot"), ("CON", "slot-con"),
                               ("LPT1", "slot-lpt1"), (" My -- Cat ", "my-cat")):
            with self.subTest(name=name):
                slug = saveslots.slot_slug(name)
                self.assertEqual(slug, expected)
                self.assertRegex(slug, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertEqual((self.root / slug).parent, self.root)
        long_slug = saveslots.slot_slug("a" * 39 + " / " + "b" * 80)
        self.assertLessEqual(len(long_slug), 40)
        self.assertFalse(long_slug.endswith("-"))

    def test_allocation_is_lazy_and_collides_case_insensitively(self):
        """Only an actual save reserves a path; existing empty directories count too."""
        first, display = saveslots.allocate_slot(self.default, "Mochi")
        self.assertEqual(first, self.root / "mochi" / "save.json")
        self.assertEqual(display, "Mochi")
        self.assertFalse(self.root.exists())
        self.write_save(first, {"slot_name": display})
        second, second_display = saveslots.allocate_slot(self.default, "Mochi")
        self.assertEqual(second.parent.name, "mochi-2")
        # The shown name carries the same index so browser rows stay distinct.
        self.assertEqual(second_display, "Mochi 2")
        second.parent.mkdir()
        (self.root / "MOCHI-3").mkdir()
        fourth, fourth_display = saveslots.allocate_slot(self.default, "MOCHI")
        self.assertEqual(fourth.parent.name, "mochi-4")
        self.assertEqual(fourth_display, "MOCHI 4")
        self.assertFalse(fourth.exists())

    def test_slot_root_follows_an_explicit_save_override_uniformly(self):
        """A portable filename changes the root, not the slot file's .json suffix."""
        override = self.default.parent / "portable" / "chosen.json"
        path, _ = saveslots.allocate_slot(override, "Boat Cat")
        self.assertEqual(path, override.parent / "slots" / "boat-cat" / "save.json")
        self.assertFalse(path.parent.exists())

    def test_listing_keeps_main_first_sorts_names_and_ignores_empty_directories(self):
        """Display metadata wins over the Skipper name; corrupt files remain visible."""
        self.write_save(self.default, {"v2": {"skipper": {"name": "Original"}}})
        self.write_save(self.root / "zed" / "save.json",
                        {"slot_name": "Alpha", "v2": {"skipper": {"name": "Ignored"}}})
        self.write_save(self.root / "bee" / "save.json", {"v2": {"skipper": {"name": "Beta"}}})
        corrupt = self.root / "corrupt" / "save.json"
        corrupt.parent.mkdir()
        corrupt.write_bytes(b"\xffbroken JSON")
        (self.root / "empty").mkdir()
        slots = saveslots.list_slots(self.default)
        self.assertEqual([slot.name for slot in slots], ["Original", "Alpha", "Beta", "corrupt"])
        self.assertEqual([slot.slug for slot in slots], ["", "zed", "bee", "corrupt"])
        self.assertTrue(slots[0].is_default)
        self.assertTrue(all(not slot.is_default for slot in slots[1:]))
        self.assertEqual(slots[0].path, self.default)

    def test_absent_and_malformed_metadata_falls_back_without_writes(self):
        """Missing main saves are listed and nested malformed JSON never breaks listing."""
        self.assertEqual(saveslots.list_slots(self.default),
                         [saveslots.Slot("", "save", self.default, True)])
        self.assertFalse(self.root.exists())
        path = self.root / "fallback" / "save.json"
        for raw in ([], {"slot_name": 8, "v2": []}, {"v2": {"skipper": []}},
                    {"slot_name": " ", "v2": {"skipper": {"name": ""}}}):
            with self.subTest(raw=raw):
                self.write_save(path, raw)
                self.assertEqual(saveslots.slot_display_name(path), "fallback")
        path.write_text("{not JSON", encoding="utf-8")
        self.assertEqual(saveslots.slot_display_name(path), "fallback")

    def test_named_rename_moves_backups_and_preserves_every_other_json_field(self):
        """The directory key and display name change together without losing future keys."""
        source = self.root / "old" / "save.json"
        raw = {"version": 2, "money": 43.5, "slot_name": "Old", "future": {"keep": [1, 2]},
               "v2": {"skipper": {"name": "Skipper stays"}}}
        self.write_save(source, raw)
        backup = source.parent / "backup" / "briar.v1.test.json"
        self.write_save(backup, {"original": True})
        renamed = saveslots.rename_slot(self.default, "old", "New Cat")
        target = self.root / "new-cat" / "save.json"
        self.assertEqual(renamed, ("new-cat", target))
        self.assertFalse(source.parent.exists())
        self.assertEqual(json.loads(target.read_text()), {**raw, "slot_name": "New Cat"})
        self.assertEqual((target.parent / "backup" / backup.name).read_bytes(), b'{"original": true}')
        self.assertFalse(target.with_suffix(".tmp").exists())

    def test_rename_excludes_its_own_slug_but_avoids_other_case_insensitive_keys(self):
        """Display-only edits retain a directory while real collisions get numbered."""
        source = self.root / "mochi" / "save.json"
        self.write_save(source, {"slot_name": "Mochi"})
        self.assertEqual(saveslots.rename_slot(self.default, "mochi", "MOCHI"), ("mochi", source))
        (self.root / "OTHER").mkdir()
        slug, path = saveslots.rename_slot(self.default, "mochi", "Other")
        self.assertEqual(slug, "other-2")
        self.assertEqual(path.parent, self.root / slug)

    def test_default_rename_moves_the_save_and_its_backup_not_unrelated_files(self):
        """The legacy main file becomes a named slot without moving the slot root itself."""
        raw = {"version": 2, "money": 100, "unknown": ["keep"]}
        self.write_save(self.default, raw)
        backup = self.default.parent / "backup" / "briar.v1.test.json"
        self.write_save(backup, {"old": True})
        unrelated = self.default.parent / "keep.txt"
        unrelated.write_text("untouched", encoding="utf-8")
        slug, path = saveslots.rename_slot(self.default, "", "Main Cat")
        self.assertEqual((slug, path), ("main-cat", self.root / "main-cat" / "save.json"))
        self.assertFalse(self.default.exists())
        self.assertFalse(backup.parent.exists())
        self.assertTrue((path.parent / "backup" / backup.name).is_file())
        self.assertEqual(json.loads(path.read_text()), {**raw, "slot_name": "Main Cat"})
        self.assertEqual(unrelated.read_text(), "untouched")
        self.assertTrue(saveslots.list_slots(self.default)[0].is_default)

    def test_default_rename_retires_the_legacy_v1_into_the_slots_backups(self):
        """Moving the main save also moves the install-era v1 so it cannot re-import."""
        raw = {"version": 2, "money": 7}
        self.write_save(self.default, raw)
        legacy = self.default.parent / "install" / "saves" / "briar.json"
        self.write_save(legacy, {"version": 1, "money": 1})
        slug, path = saveslots.rename_slot(self.default, "", "Main Cat",
                                           legacy_path=legacy)
        self.assertEqual(slug, "main-cat")
        self.assertFalse(legacy.exists())
        moved = list((path.parent / "backup").glob("briar.v1.*.json"))
        self.assertEqual(len(moved), 1)
        self.assertEqual(json.loads(moved[0].read_text()), {"version": 1, "money": 1})
        # Without a legacy path (a --save override) nothing outside moves.
        self.write_save(self.default, raw)
        self.write_save(legacy, {"version": 1})
        slug, _ = saveslots.rename_slot(self.default, "", "Other Cat")
        self.assertTrue(legacy.is_file())

    def test_missing_or_escaping_rename_does_not_create_paths(self):
        """Reject absent slots and path traversal before writing anything."""
        for slug in ("", "missing", "../outside", "..", "a\\b"):
            with self.subTest(slug=slug):
                self.assertIsNone(saveslots.rename_slot(self.default, slug, "New"))
        self.assertFalse(self.root.exists())

    def test_corrupt_rename_preserves_the_original_file_and_directory(self):
        """Do not move a save before its metadata can be decoded safely."""
        source = self.root / "broken" / "save.json"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"broken")
        with self.assertRaises(ValueError):
            saveslots.rename_slot(self.default, "broken", "New")
        self.assertEqual(source.read_bytes(), b"broken")
        self.assertFalse((self.root / "new").exists())


class _SlotSessionFixture:
    """Share temporary saves and real menu-entry helpers, not inherited test cases."""

    @classmethod
    def setUpClass(cls):
        """Share the immutable authored Briar world among isolated sessions."""
        cls.world = World()

    def setUp(self):
        """Start a headless session at a fresh temporary main-save path."""
        temporary = tempfile.TemporaryDirectory(prefix="trotline-slot-session-")
        self.addCleanup(temporary.cleanup)
        self.default = Path(temporary.name) / "save.json"
        self.state = State.new(self.world, seed=144)
        self.session = Session(self.world, self.default, self.state, False)

    def seed_slot(self, name, money, *, world=None, count=0):
        """Persist a real slot with money dollars and bluegill journal count; return it."""
        world = world or self.world
        state = State.new(world, seed=144)
        state.money = money
        state.journal["bluegill"]["count"] = count
        path, display = saveslots.allocate_slot(self.default, name)
        saveslots.stamp_slot_name(state, display)
        state.save(path)
        return saveslots.Slot(path.parent.name, display, path, False)

    def enter_browser(self):
        """Reach Saves via the title's actual selection and confirm handler."""
        self.session.ui.mode = "title"
        self.session.ui.title_i = title_options(self.session.ui.has_save).index("Saves")
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.ui.mode, "saves")

    def begin_rename(self):
        """Select Rename with the keyboard action row and open its draft."""
        self.session._keys(Keys(pressed={"right"}), 0)
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertTrue(self.session.ui.slot_renaming)


class SlotSessionChecks(_SlotSessionFixture, unittest.TestCase):
    """Exercise real save/load state and the native title/rename key paths."""

    def test_missing_or_corrupt_slots_never_install_an_unnamed_new_game(self):
        """An always-listed but missing main save cannot bypass fresh-slot creation."""
        active = self.seed_slot("Active", 789)
        self.session._load_slot(active)
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                if corrupt:
                    self.default.write_text("broken main save", encoding="utf-8")
                self.enter_browser()
                self.session._keys(Keys(pressed={"up"}), 0)
                self.assertTrue(self.session.ui.slots[self.session.ui.slot_i].is_default)
                before = self.session.state
                self.session._keys(Keys(pressed={"return"}), 0)
                self.assertEqual(self.session.ui.mode, "saves")
                self.assertIs(self.session.state, before)
                self.assertEqual(self.session.save_path, active.path)
                self.assertEqual(self.session.state.money, 789)
                self.assertIn("could not be loaded", self.session.ui.note)
                self.assertTrue(any("could not be loaded" in text
                                    for text, _ttl in before.toasts))
                if corrupt:
                    self.assertEqual(self.default.read_text(), "broken main save")
                else:
                    self.assertFalse(self.default.exists())

    def test_empty_browser_cannot_autosave_or_quit_save_a_bootstrap_state(self):
        """Browsing before the first morning must not create an unnamed main save."""
        self.enter_browser()
        self.session.save()
        self.session.tick(Keys(quit=True), 0)
        self.assertTrue(self.session.quit)
        self.assertFalse(self.default.exists())
        self.assertFalse(self.session.slots_dir.exists())

    def test_loading_restores_pending_scene_replays_as_boot_does(self):
        """A slot reopened mid-scene retains the same replay/skip flags as startup."""
        slot = self.seed_slot("Replay", 111)
        state = State.load(slot.path, self.world)
        state.v2["story"]["scene_states"].update({"prologue": "pending", "credits": "pending"})
        self.session._heard_hour = 5
        self.session._heard_days = {"cookout": ("briar", 1)}
        state.save(slot.path)
        self.session._load_slot(slot)
        self.assertEqual(self.session._replays, self.session._saved_pending())
        self.assertIn("prologue", self.session._replays)
        self.assertIn("credits", self.session._replays)
        self.assertIsNone(self.session._heard_hour)
        self.assertEqual(self.session._heard_days, {})
        self.assertTrue(any(text == "Dress your Skipper: Esc, then Your Skipper."
                            for text, _ttl in self.session.state.toasts))

    def test_new_mornings_always_allocate_and_leave_the_main_save_untouched(self):
        """Two identical Skipper names create distinct slots beside the original path."""
        self.session.save()
        original = self.default.read_bytes()
        look = skipperlook.normalize({"skipper": {"name": "Mochi", "created": True}})
        self.session._start_new_game("cozy", look)
        first = self.default.parent / "slots" / "mochi" / "save.json"
        self.assertEqual(self.session.save_path, first)
        self.assertTrue(first.is_file())
        self.assertEqual(json.loads(first.read_text())["slot_name"], "Mochi")
        first_bytes = first.read_bytes()
        self.session._start_new_game("old_salt", look)
        self.assertEqual(self.session.save_path, first.parent.with_name("mochi-2") / "save.json")
        self.assertTrue(self.session.save_path.is_file())
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(self.default.read_bytes(), original)
        self.assertEqual(self.session.default_save_path, self.default)
        self.assertEqual(self.session.slots_dir, self.default.parent / "slots")

    def test_invalid_new_skipper_name_uses_the_creator_fallback(self):
        """Direct new-game callers receive the same safe name as the creator."""
        look = skipperlook.normalize({})
        look["name"] = "..."
        self.session._start_new_game("cozy", look)
        self.assertEqual(self.session.save_path.parent.name,
                         saveslots.slot_slug(skipperlook.DEFAULT_NAME))
        self.assertFalse(self.default.exists())

    def test_slot_money_journal_and_save_writes_are_isolated(self):
        """Switch A to B and back without overwriting another slot or the main save."""
        self.session.save()
        main_bytes = self.default.read_bytes()
        first = self.seed_slot("A", 101, count=7)
        second = self.seed_slot("B", 202, count=3)
        second_bytes = second.path.read_bytes()
        self.session._load_slot(first)
        self.assertEqual(self.session.save_path, first.path)
        self.assertEqual(self.session.state.money, 101)
        self.assertEqual(self.session.state.journal["bluegill"]["count"], 7)
        self.session.state.money = 111
        self.session.save()
        first_bytes = first.path.read_bytes()
        self.assertEqual(second.path.read_bytes(), second_bytes)
        self.session._load_slot(second)
        self.assertEqual(self.session.save_path, second.path)
        self.assertEqual(self.session.state.money, 202)
        self.assertEqual(self.session.state.journal["bluegill"]["count"], 3)
        self.assertTrue(any(text == "Loaded B." for text, _ttl in self.session.state.toasts))
        self.session.state.money = 222
        self.session.save()
        self.assertEqual(first.path.read_bytes(), first_bytes)
        self.assertEqual(self.default.read_bytes(), main_bytes)
        self.session._load_slot(first)
        self.assertEqual(self.session.state.money, 111)

    def test_loading_uses_the_slots_own_lake_and_replaces_dialogue_and_handlers(self):
        """A Cedar slot must not be loaded against the boot-time Briar world."""
        slot = self.seed_slot("Cedar Cat", 333, world=World("cedar"))
        self.session.conversation = object()
        self.session.ui.input_device = "gamepad"
        self.session._load_slot(slot)
        self.assertEqual(self.session.world.id, "cedar")
        self.assertEqual(self.session.state.lake_id, "cedar")
        self.assertEqual(self.session.ui.mode, "play")
        self.assertEqual(self.session.ui.input_device, "gamepad")
        self.assertIs(self.session.ui.dialogue_content, self.session._npc_content)
        self.assertIsNone(self.session.conversation)
        self.assertIsNone(self.session.ui.conversation)
        self.assertEqual(self.session.state._quest_event_handler, self.session.quest_manager.handle_event)

    def test_loading_applies_offline_catchup_once_at_selection_time(self):
        """A save loaded after a long browser visit gets its own catch-up cutoff."""
        slot = self.seed_slot("Mochi", 100)
        with patch("fishing.game.time.time", return_value=12345), \
                patch.object(State, "catch_up", autospec=True) as catch_up:
            self.session._load_slot(slot)
        catch_up.assert_called_once_with(self.session.state, now=12345)
        self.assertEqual(self.session._continue_catchup_at, 12345)
        self.assertFalse(self.session._title_catchup_pending)

    def test_browser_continue_and_new_save_use_native_menu_keys(self):
        """W/S selects rows; A/D actions choose a non-overwriting new morning."""
        slot = self.seed_slot("Mochi", 321)
        self.enter_browser()
        self.assertEqual(len(self.session.ui.slots), 2)
        self.session._keys(Keys(pressed={"s"}), 0)
        self.assertEqual(self.session.ui.slot_i, 1)
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.save_path, slot.path)
        self.assertEqual(self.session.state.money, 321)
        self.enter_browser()
        self.session._keys(Keys(pressed={"d"}), 0)
        self.session._keys(Keys(pressed={"d"}), 0)
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.ui.mode, "new_mode")
        self.assertFalse(self.session.ui.confirm_new)
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.ui.mode, "skipper")

    def test_active_named_rename_key_path_updates_path_and_future_autosaves(self):
        """Renaming updates both disk metadata and the active State's unknown field."""
        active = self.seed_slot("Mochi", 321)
        self.session._load_slot(active)
        self.enter_browser()
        self.begin_rename()
        for key in ("b", "e", "l", "l"):
            self.session._keys(Keys(pressed={key}), 0)
        self.session._keys(Keys(pressed={"return"}), 0)
        path = self.default.parent / "slots" / "bell" / "save.json"
        self.assertEqual(self.session.save_path, path)
        self.assertFalse(active.path.exists())
        self.assertFalse(self.session.ui.slot_renaming)
        self.assertEqual(self.session.ui.slots[self.session.ui.slot_i].path, path)
        self.assertEqual(self.session.state.unknown_save_fields["slot_name"], "Bell")
        self.session.save()
        self.assertEqual(json.loads(path.read_text())["slot_name"], "Bell")
        self.assertEqual(json.loads(path.read_text())["money"], 321)
        self.assertFalse(self.default.exists())

    def test_active_main_rename_key_path_moves_backups_and_updates_the_active_path(self):
        """A main-save rename never recreates the old file on later autosaves."""
        self.session.save()
        backup = self.default.parent / "backup" / "briar.v1.test.json"
        backup.parent.mkdir()
        backup.write_text("backup", encoding="utf-8")
        self.enter_browser()
        self.begin_rename()
        self.session.ui.slot_name_buf = "Main Cat"
        self.session._keys(Keys(pressed={"return"}), 0)
        expected = self.default.parent / "slots" / "main-cat" / "save.json"
        self.assertEqual(self.session.save_path, expected)
        self.assertTrue((expected.parent / "backup" / backup.name).is_file())
        self.session.save()
        self.assertFalse(self.default.exists())
        self.assertEqual(json.loads(expected.read_text())["slot_name"], "Main Cat")

    def test_renaming_an_inactive_slot_does_not_redirect_the_active_save(self):
        """The renamed row stays selected but subsequent saves still belong to main."""
        self.session.save()
        active_name = self.session.state.unknown_save_fields.get("slot_name")
        slot = self.seed_slot("Other", 456)
        self.enter_browser()
        self.session._keys(Keys(pressed={"down"}), 0)
        self.begin_rename()
        self.session.ui.slot_name_buf = "Renamed"
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.save_path, self.default)
        self.assertEqual(self.session.state.unknown_save_fields.get("slot_name"), active_name)
        self.assertEqual(self.session.ui.slots[self.session.ui.slot_i].name, "Renamed")
        self.assertFalse(slot.path.exists())

    def test_rename_cancel_and_browser_back_do_not_modify_saved_bytes(self):
        """Esc first discards a draft, then returns to title without saving it."""
        self.session.save()
        original = self.default.read_bytes()
        self.enter_browser()
        self.begin_rename()
        self.session._keys(Keys(pressed={"z"}), 0)
        self.session._keys(Keys(pressed={"esc"}), 0)
        self.assertEqual(self.session.ui.mode, "saves")
        self.assertFalse(self.session.ui.slot_renaming)
        self.session._keys(Keys(pressed={"esc"}), 0)
        self.assertEqual(self.session.ui.mode, "title")
        self.assertEqual(self.default.read_bytes(), original)

    def test_rename_uses_ordered_physical_keys_not_remapped_actions_or_gamepad_letters(self):
        """Typing M must neither mute nor confirm even if its action maps to Return."""
        self.session.save()
        self.enter_browser()
        self.begin_rename()
        muted = self.session.state.muted
        self.session.state.throttle = self.session.state.throttle_setting = 0.5
        keys = Keys(pressed={"return"}, held={"shift"})
        keys.physical_keyboard_pressed = {"z", "m"}
        keys.physical_keyboard_press_order = ["m", "z"]
        self.session._keys(keys, 0)
        self.assertEqual(self.session.ui.slot_name_buf, "Mz")
        self.assertTrue(self.session.ui.slot_renaming)
        self.assertEqual(self.session.state.muted, muted)
        self.assertEqual((self.session.state.throttle, self.session.state.throttle_setting), (0.5, 0.5))
        keys = Keys(pressed={"return", "e"})
        keys.physical_keyboard_pressed = set()
        keys.gamepad_pressed = {"return", "e"}
        self.session._keys(keys, 0)
        self.assertFalse(self.session.ui.slot_renaming)
        self.assertEqual(self.session.save_path.parent.name, "mz")

    def test_gamepad_can_browse_continue_and_return_to_title(self):
        """The standard d-pad/A/B action mapping reaches saves without physical letters."""
        slot = self.seed_slot("Pad Cat", 444)
        self.enter_browser()
        tap(self.session, "down", dt=0, device="gamepad")
        tap(self.session, "return", dt=0, device="gamepad")
        self.assertEqual(self.session.save_path, slot.path)
        self.enter_browser()
        tap(self.session, "esc", dt=0, device="gamepad")
        self.assertEqual(self.session.ui.mode, "title")

    def test_devmode_new_mornings_and_slot_loading_never_create_or_rewrite_paths(self):
        """Lazy allocation and read-only loading also cover the new browser's Rename."""
        dev = Session(self.world, self.default, State.new(self.world, seed=144), False, dev=True)
        dev._start_new_game("cozy", skipperlook.normalize({"skipper": {"name": "Dev Cat"}}))
        self.assertFalse(dev.slots_dir.exists())
        self.assertFalse(self.default.exists())
        slot = self.seed_slot("Stored Cat", 555)
        before = slot.path.read_bytes()
        dev._load_slot(slot)
        dev.state.money = 1000
        dev.save()
        dev._open_saves()
        dev._keys(Keys(pressed={"right"}), 0)
        dev._keys(Keys(pressed={"return"}), 0)
        self.assertFalse(dev.ui.slot_renaming)
        self.assertIn("Devmode", dev.ui.note)
        self.assertEqual(slot.path.read_bytes(), before)
        self.assertEqual([entry.name for entry in dev.slots_dir.iterdir()], [slot.slug])


class SlotPointerChecks(_SlotSessionFixture, unittest.TestCase):
    """Check the browser's actually displayed geometry and stale-context protection."""

    def setUp(self):
        """Add a native-font renderer to the ordinary isolated session fixture."""
        super().setUp()
        text = Text()
        self.addCleanup(text.close)
        self.renderer = UI(text, self.world)
        self.addCleanup(self.renderer.close)
        self.viewport = (480, 270)

    def draw(self):
        """Publish a compact browser frame without a window or any input side effects."""
        self.renderer.draw(np.zeros((self.viewport[1], self.viewport[0], 3), np.uint8),
                           self.session.state, self.session.ui)

    def click_target(self, field, value):
        """Click the center of the displayed field/value target in UI pixels."""
        target = next(target for target in self.session.ui.pointer.targets
                      if target.field == field and target.value == value)
        x, y, width, height = target.rect
        self.session._keys(Keys(mouse_click=(x + width // 2, y + height // 2),
                                viewport=self.viewport), 0)

    def test_displayed_slot_rows_continue_and_action_buttons_rename(self):
        """Use rendered controls, not synthetic key activation, to load and rename."""
        slot = self.seed_slot("Pointer Cat", 612)
        self.enter_browser()
        self.draw()
        self.click_target("slot_i", 1)
        self.assertEqual(self.session.save_path, slot.path)
        self.assertEqual(self.session.state.money, 612)
        self.enter_browser()
        self.draw()
        self.click_target("slot_action_i", 1)
        self.assertTrue(self.session.ui.slot_renaming)
        self.session.ui.slot_name_buf = "Clicked"
        self.draw()
        target = next(target for target in self.session.ui.pointer.targets
                      if target.action == "slot_rename_done")
        x, y, width, height = target.rect
        self.session._keys(Keys(mouse_click=(x + width // 2, y + height // 2),
                                viewport=self.viewport), 0)
        self.assertEqual(self.session.save_path.parent.name, "clicked")
        self.assertFalse(self.session.ui.slot_renaming)

    def test_slot_fields_invalidate_previously_displayed_pointer_targets(self):
        """Every browser field that affects content or selection participates in identity."""
        self.enter_browser()
        ui = self.session.ui
        identity = pointer.context(self.session.state, ui)
        variants = {"slots": ui.slots + [saveslots.Slot("x", "X", Path("slots/x/save.json"), False)],
                    "slot_i": 1, "slot_action_i": 1, "slot_renaming": True,
                    "slot_name_buf": "Changed", "slot_name_fresh": True}
        for field, value in variants.items():
            with self.subTest(field=field):
                self.assertNotEqual(pointer.context(self.session.state, replace(ui, **{field: value})), identity)
        self.draw()
        ui.slot_renaming = True
        self.click_target("slot_action_i", 2)
        self.assertEqual(ui.mode, "saves")
        self.assertTrue(ui.slot_renaming)

    def test_hover_keeps_save_rows_stationary_until_the_displayed_slot_is_clicked(self):
        """Selection-only invalidation must not move a different row under the cursor."""
        for index in range(15):
            self.seed_slot(f"Cat {index:02}", index)
        self.enter_browser()
        self.draw()
        rows = [target for target in self.session.ui.pointer.targets if target.field == "slot_i"]
        target = rows[-1]
        expected_path = self.session.ui.slots[target.value].path
        x, y, width, height = target.rect
        position = (x + width // 2, y + height // 2)
        self.session._keys(Keys(mouse_pos=position, mouse_moved=True, viewport=self.viewport), 0)
        self.draw()
        current = [target for target in self.session.ui.pointer.targets if target.field == "slot_i"]
        self.assertEqual(current, rows)
        self.session._keys(Keys(mouse_click=position, viewport=self.viewport), 0)
        self.assertEqual(self.session.save_path, expected_path)

    def test_title_options_stay_above_the_footer_at_every_supported_window_size(self):
        """The new Saves row must not overlap Help at medium sizes or large text."""
        for viewport in ((480, 270), (640, 360), (960, 540), (1280, 720), (1920, 1080)):
            for size in range(3):
                for dyslexia in (False, True):
                    for has_save in (False, True):
                        with self.subTest(viewport=viewport, size=size, dyslexia=dyslexia,
                                          has_save=has_save):
                            self.session.state.v2["settings"].update(
                                {"text_size": size, "dyslexia_font": dyslexia})
                            ui = UIState(mode="title", has_save=has_save)
                            self.renderer.draw(np.zeros((viewport[1], viewport[0], 3), np.uint8),
                                               self.session.state, ui)
                            footer = next(target for target in ui.pointer.targets if target.action == "help")
                            rows = [target for target in ui.pointer.targets if target.field == "title_i"]
                            self.assertEqual(len(rows), len(title_options(has_save)))
                            for row in rows:
                                self.assertLessEqual(row.rect[1] + row.rect[3], footer.rect[1])

    def test_long_lists_scroll_and_publish_only_bounded_visible_rows(self):
        """Wheel navigation reveals late saves while hitboxes stay inside the compact panel."""
        for index in range(15):
            self.seed_slot(f"Cat {index:02}", index)
        self.enter_browser()
        self.draw()
        self.session._keys(Keys(mouse_wheel=-12, viewport=self.viewport), 0)
        self.assertEqual(self.session.ui.slot_i, 12)
        self.draw()
        registry = self.session.ui.pointer
        row_values = [target.value for target in registry.targets if target.field == "slot_i"]
        self.assertIn(12, row_values)
        self.assertLess(len(row_values), len(self.session.ui.slots))
        for target in registry.targets:
            x, y, width, height = target.rect
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)
            self.assertLessEqual(x + width, self.viewport[0])
            self.assertLessEqual(y + height, self.viewport[1])


if __name__ == "__main__":
    unittest.main()
