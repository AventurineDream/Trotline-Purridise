"""Accessibility settings, persistence, and input integration checks."""

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from .audio import Audio
from .bot import _COLLAR_WOOL, faces as bot_faces
from .game import Keys, Session, _camera
from .gamepad import KEY_NAMES, normalize_key_bindings
from .platform import Input, SCAN, find_font
from .savepaths import merge_v2_defaults
from .sim import Hook, SetLine, State
from .test_skipper_creator import finish_creator
from .ui import UI, UIState, TEXT_SIZE_SCALES
from .world import World


class SettingsChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def make_session(self):
        temp = tempfile.TemporaryDirectory(prefix="trotline-settings-")
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "save.json"
        return Session(self.world, path, State.new(self.world, seed=31), False)

    def test_settings_menu_updates_and_roundtrips_visible_options(self):
        """Settings changes on the menu survive the normal save/reload path."""
        session = self.make_session()
        session.ui.mode = "settings"

        # Values that cycle forward once reach a visibly different option.
        for index in (0, 1, 2, 3, 5, 6, 11, 12):
            session.ui.settings_i = index
            session.tick(Keys(pressed={"right"}), 0.05)
        for index in (7, 8, 9, 10):
            session.ui.settings_i = index
            session.tick(Keys(pressed={"left"}), 0.05)

        loaded = State.load(session.save_path, self.world)
        settings = loaded.v2["settings"]
        self.assertEqual(loaded.v2["mode"], "old_salt")
        self.assertEqual(settings["mode"], "old_salt")
        self.assertEqual(settings["text_size"], 2)
        self.assertTrue(settings["dyslexia_font"])
        self.assertTrue(settings["reduced_motion"])
        self.assertEqual(settings["haul_speed"], "quick")
        self.assertFalse(settings["captions"])
        self.assertEqual(settings["volumes"], {
            "master": 0.9, "music": 0.9, "ambience": 0.9, "sfx": 0.9,
        })
        self.assertFalse(settings["collar_visible"])
        self.assertTrue(settings["auto_anchor"])
        self.assertFalse(loaded.v2["profile"]["collar"]["visible"])

    def test_camera_view_toggle_is_saved_and_reloaded(self):
        """Both menu toggles persist the opt-in camera choice across a reload."""
        session = self.make_session()
        session.ui.mode = "settings"
        session.ui.settings_i = 4
        self.assertFalse(session.state.v2["settings"]["third_person"])
        rows = UI.__new__(UI)._settings_rows(session.state)
        self.assertEqual(rows[4], ("Camera view", "First person"))
        session.tick(Keys(pressed={"left"}), 0.05)
        self.assertTrue(session.state.v2["settings"]["third_person"])
        session.tick(Keys(pressed={"right"}), 0.05)
        self.assertFalse(session.state.v2["settings"]["third_person"])
        session.tick(Keys(pressed={"return"}), 0.05)
        self.assertTrue(session.state.v2["settings"]["third_person"])

        loaded = State.load(session.save_path, self.world)
        rows = UI.__new__(UI)._settings_rows(loaded)
        self.assertTrue(loaded.v2["settings"]["third_person"])
        self.assertEqual(rows[4], ("Camera view", "Third person"))
        self.assertEqual(rows[-1], ("Keyboard controls", "Open  >"))

    def test_pause_menu_opens_settings_and_escape_returns_to_pause(self):
        from .ui import pause_options
        session = self.make_session()
        session.ui.mode = "pause"
        for _ in range(pause_options(session.state).index("Settings")):
            session.tick(Keys(pressed={"down"}), 0.05)
        session.tick(Keys(pressed={"return"}), 0.05)
        self.assertEqual(session.ui.mode, "settings")
        session.tick(Keys(pressed={"esc"}), 0.05)
        self.assertEqual(session.ui.mode, "pause")

    def test_keybinding_page_captures_a_physical_key_and_drives_with_it(self):
        session = self.make_session()
        session.ui.mode = "settings"
        session.ui.settings_page = "keys"
        session.ui.key_binding_i = 0  # throttle up
        session.tick(Keys(pressed={"return"}), 0.05)
        self.assertTrue(session.ui.capturing_key)

        captured = Input()
        captured.keyboard_pressed = {"p"}
        captured.keyboard_held = {"p"}
        captured.pressed = {"p"}
        captured.held = {"p"}
        session.tick(captured, 0.05)
        self.assertFalse(session.ui.capturing_key)
        self.assertEqual(session.state.v2["settings"]["key_bindings"]["throttle_up"], "p")

        session.ui.mode = "play"
        session.state.anchored = False
        session.tick(captured, 0.05)
        self.assertGreater(session.state.throttle_setting, 0)

    def test_backspace_cancels_key_capture_without_changing_bindings(self):
        session = self.make_session()
        session.ui.mode = "settings"
        session.ui.settings_page = "keys"
        session.ui.key_binding_i = 0
        before = dict(session.state.v2["settings"]["key_bindings"])
        session.tick(Keys(pressed={"return"}), 0.05)
        keys = Input()
        keys.keyboard_pressed = {"backspace"}
        keys.pressed = {"backspace"}
        session.tick(keys, 0.05)
        self.assertFalse(session.ui.capturing_key)
        self.assertEqual(session.state.v2["settings"]["key_bindings"], before)

    def test_escape_cancels_key_capture_without_binding_escape(self):
        session = self.make_session()
        session.ui.mode = "settings"
        session.ui.settings_page = "keys"
        session.ui.key_binding_i = 0
        before = dict(session.state.v2["settings"]["key_bindings"])
        session.tick(Keys(pressed={"return"}), 0.05)
        keys = Input()
        keys.keyboard_pressed = {"esc"}
        keys.pressed = {"esc"}
        session.tick(keys, 0.05)
        self.assertFalse(session.ui.capturing_key)
        self.assertEqual(session.state.v2["settings"]["key_bindings"], before)

    def test_rebinding_to_a_used_key_swaps_the_other_action(self):
        session = self.make_session()
        session.ui.mode = "settings"
        session.ui.settings_page = "keys"
        session.ui.key_binding_i = 0  # throttle up
        session.tick(Keys(pressed={"return"}), 0.05)
        captured = Input()
        captured.keyboard_pressed = {"s"}
        captured.keyboard_held = {"s"}
        captured.pressed = {"s"}
        captured.held = {"s"}
        session.tick(captured, 0.05)
        bindings = session.state.v2["settings"]["key_bindings"]
        self.assertEqual(bindings["throttle_up"], "s")
        self.assertEqual(bindings["throttle_down"], "w")

        session.ui.mode = "play"
        session.state.anchored = False
        session.tick(captured, 0.05)
        self.assertGreater(session.state.throttle_setting, 0)

    def test_capture_uses_the_first_physical_key_pressed(self):
        session = self.make_session()
        session.ui.mode = "settings"
        session.ui.settings_page = "keys"
        session.ui.key_binding_i = 0
        session.tick(Keys(pressed={"return"}), 0.05)
        captured = Input()
        captured.keyboard_pressed = {"w", "rshift"}
        captured.keyboard_press_order = ["w", "rshift"]
        captured.pressed = {"w", "rshift"}
        session.tick(captured, 0.05)
        self.assertEqual(session.state.v2["settings"]["key_bindings"]["throttle_up"], "w")

    def test_common_letters_and_digits_are_exposed_and_bindable(self):
        for key in ("x", "l", "u", "0"):
            with self.subTest(key=key):
                self.assertIn(key, KEY_NAMES)
                self.assertIn(key, SCAN)
                self.assertEqual(normalize_key_bindings(
                    {"throttle_up": key})["throttle_up"], key)

    def test_normalized_alias_bindings_are_available_for_display(self):
        bindings = normalize_key_bindings({
            "cancel": "x", "alternate_select": "u",
            "dialogue_continue": "0",
        })
        self.assertEqual(bindings["pause"], "x")
        self.assertEqual(bindings["anchor"], "u")
        self.assertEqual(bindings["hail"], "0")
        self.assertEqual(UI._key_name(bindings["pause"]), "X")

    def test_keybinding_screen_displays_normalized_pause_alias(self):
        class TextRecorder:
            def __init__(self):
                self.calls = []

            def render(self, text, size, color, family):
                self.calls.append(text)
                return np.zeros((size, max(1, len(text) * size // 2), 4), np.uint8)

        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = TextRecorder(), {}, {}
        ui._text_scale = 1.0
        ui._dyslexia_font = False
        state = SimpleNamespace(v2={"settings": {"key_bindings": {"cancel": "x"}}})
        ui_state = UIState(key_binding_i=10)
        ui._keybindings(np.zeros((720, 1280, 3), np.uint8), state, ui_state)
        self.assertIn("X", ui.text.calls)

    def test_haul_speed_is_available_in_settings(self):
        state = SimpleNamespace(v2={
            "settings": {"haul_speed": "instant"},
            "profile": {"collar": {"visible": True}},
        })
        rows = UI.__new__(UI)._settings_rows(state)
        self.assertIn(("Haul speed", "Instant"), rows)

    def test_haul_speed_setting_changes_how_long_a_24_hook_haul_takes(self):
        def haul_seconds(speed):
            temp = tempfile.TemporaryDirectory(prefix="trotline-haul-speed-")
            self.addCleanup(temp.cleanup)
            state = State.new(self.world, seed=121)
            state.x, state.z = self.world.anchors["briar:inlet"].position
            state.speed = 0.0
            state.throttle = state.throttle_setting = 0.0
            state.anchored = True
            state.v2["settings"]["haul_speed"] = speed
            hooks = [Hook(True) for _ in range(24)]
            state.lines = [SetLine("std", "worm", state.x - 10, state.z, state.x + 10, state.z,
                                   "open", hooks)]
            session = Session(self.world, Path(temp.name) / "save.json", state, False)
            session.ui.mode = "play"
            state.slip_status = lambda _world: None
            session.tick(Keys(pressed={"e"}), 0.0)  # Instant hauls are already at the summary
            elapsed = 0.0
            while session.ui.mode == "haul" and elapsed < 12.0:
                session.tick(Keys(), 0.05)
                elapsed += 0.05
            self.assertEqual(session.ui.mode, "check")
            return elapsed

        instant, quick, normal = (haul_seconds(speed) for speed in ("instant", "quick", "normal"))
        self.assertLess(instant, 0.2)
        self.assertAlmostEqual(quick, 24 * 0.10, delta=0.35)
        self.assertAlmostEqual(normal, 24 * 0.25, delta=0.35)
        self.assertLess(quick, normal)

    def test_collar_visibility_controls_bot_rendering(self):
        state = State.new(self.world, seed=17)
        state.v2["profile"]["collar"]["stage"] = "received"
        state.v2["settings"]["collar_visible"] = True
        visible = bot_faces(state)
        self.assertTrue(any(np.allclose(face.color, _COLLAR_WOOL) for face in visible))
        state.v2["settings"]["collar_visible"] = False
        hidden = bot_faces(state)
        self.assertFalse(any(np.allclose(face.color, _COLLAR_WOOL) for face in hidden))

    def test_new_morning_preserves_accessibility_and_control_preferences(self):
        session = self.make_session()
        settings = session.state.v2["settings"]
        settings.update({
            "mode": "old_salt", "text_size": 2, "dyslexia_font": True,
            "reduced_motion": True, "captions": False, "collar_visible": False,
            "key_bindings": {**settings["key_bindings"], "throttle_up": "x"},
        })
        session.state.v2["mode"] = "old_salt"
        session.ui.mode = "title"
        session.ui.confirm_new = True
        session.tick(Keys(pressed={"return"}), 0.05)
        self.assertEqual(session.ui.mode, "new_mode")
        # The new mode choice defaults to Cozy; select Old Salt explicitly.
        session.tick(Keys(pressed={"right"}), 0)
        session.tick(Keys(pressed={"return"}), 0)
        finish_creator(session)  # Done starts the morning, carrying these preferences
        self.assertEqual(session.state.v2["settings"], settings)
        self.assertEqual(session.state.v2["mode"], "old_salt")
        self.assertFalse(session.state.v2["profile"]["collar"]["visible"])
        session.save()
        loaded = State.load(session.save_path, self.world)
        self.assertEqual(loaded.v2["settings"], settings)

class MixerVolumeChecks(unittest.TestCase):
    @staticmethod
    def silent_mixer():
        """A device-free mixer on a still briar noon: the ambience bus carries the lake
        beds, sfx carries only the shots each test plants, and music carries the layer's
        blocks, which a test stubs (music is not a shot)."""
        audio = Audio(device=False, tier="low")
        audio.prime(hour=12.0, lake_id="briar", motorized=False)
        return audio

    def test_master_ambience_sfx_and_music_have_separate_gains(self):
        audio = self.silent_mixer()
        audible = audio._mix(32, 0.0, 0.0)
        self.assertGreater(np.max(np.abs(audible)), 0)
        audio.set_volumes(ambience=0.0)
        self.assertEqual(np.max(np.abs(audio._mix(32, 0.0, 0.0))), 0)

        audio = self.silent_mixer()
        audio.shots = [(np.full(32, 12000, np.int16), 0, "sfx")]
        audio.set_volumes(ambience=0.0, sfx=0.0)
        self.assertEqual(np.max(np.abs(audio._mix(32, 0.0, 0.0))), 0)
        audio = self.silent_mixer()
        audio.shots = [(np.full(32, 12000, np.int16), 0, "sfx")]
        audio.set_volumes(ambience=0.0, sfx=1.0)
        self.assertGreater(np.max(np.abs(audio._mix(32, 0.0, 0.0))), 0)

        def layer_block(frames, lake, wait):  # the music layer's block: music is not a shot (#168)
            return np.full((2, frames), 0.5, np.float32), []

        audio = self.silent_mixer()
        audio._music.advance = layer_block
        audio.set_volumes(ambience=0.0, sfx=0.0, music=1.0)
        self.assertGreater(np.max(np.abs(audio._mix(32, 0.0, 0.0))), 0)
        audio = self.silent_mixer()
        audio._music.advance = layer_block
        audio.set_volumes(ambience=0.0, sfx=0.0, music=1.0, master=0.0)
        self.assertEqual(np.max(np.abs(audio._mix(32, 0.0, 0.0))), 0)


class SettingsPresentationChecks(unittest.TestCase):
    def test_older_mode_and_collar_fields_seed_the_new_settings(self):
        migrated = merge_v2_defaults(None, {
            "mode": "old_salt",
            "profile": {"collar": {"visible": False}},
            "settings": {"text_size": 8,
                         "volumes": {"master": 3.0, "music": -1.0}},
        })
        self.assertEqual(migrated["settings"]["mode"], "old_salt")
        self.assertFalse(migrated["settings"]["collar_visible"])
        self.assertFalse(migrated["profile"]["collar"]["visible"])
        self.assertEqual(migrated["settings"]["text_size"], 1)
        self.assertEqual(migrated["settings"]["volumes"], {
            "master": 1.0, "music": 1.0, "ambience": 1.0, "sfx": 1.0,
        })

    def test_old_saves_default_to_first_person_and_reject_malformed_camera_view(self):
        """Older saves and malformed values keep the opt-in first-person default."""
        migrated = merge_v2_defaults(None, {})
        self.assertFalse(migrated["settings"]["third_person"])
        malformed = merge_v2_defaults(None, {"settings": {"third_person": "yes"}})
        self.assertFalse(malformed["settings"]["third_person"])

    def test_caption_setting_controls_accessible_sound_copy(self):
        session = Session.__new__(Session)
        session.state = SimpleNamespace(v2={"settings": {"captions": True}})
        session.ui = UIState()
        session.sound = "bot"
        session._tick_caption(0.0)
        self.assertEqual(session.ui.caption, "Bot's chime sounds.")
        self.assertGreater(session.ui.caption_timer, 0)

        session.state.v2["settings"]["captions"] = False
        session._tick_caption(0.1)
        self.assertEqual(session.ui.caption, "")
        self.assertEqual(session.ui.caption_timer, 0.0)

    def test_reduced_motion_removes_title_camera_sway(self):
        state = SimpleNamespace(yaw=0.3, anim=4.0, v2={"settings": {}})
        session = SimpleNamespace(state=state, ui=UIState(mode="title"))

        class CameraRecorder:
            def camera_for(self, _state, **kwargs):
                return kwargs

        full_motion = _camera(CameraRecorder(), session)
        state.v2["settings"]["reduced_motion"] = True
        reduced = _camera(CameraRecorder(), session)
        self.assertNotEqual(full_motion["yaw"], state.yaw)
        self.assertEqual(reduced["yaw"], state.yaw)
        self.assertEqual(reduced["pitch"], -0.05)

    def test_rows_show_each_saved_preference(self):
        state = SimpleNamespace(v2={
            "mode": "old_salt",
            "settings": {
                "mode": "old_salt", "text_size": 2,
                "dyslexia_font": True, "reduced_motion": True,
                "third_person": True, "haul_speed": "quick", "captions": False,
                "volumes": {"master": 0.8, "music": 0.7,
                            "ambience": 0.6, "sfx": 0.5},
                "collar_visible": False,
                "mouse_look": "quick",
            },
            "profile": {"collar": {"visible": False}},
        })
        rows = UI.__new__(UI)._settings_rows(state)
        self.assertEqual(rows, [
            ("Mode", "Old Salt"),
            ("Text size", "Large"),
            ("Dyslexia-friendly font", "Atkinson Hyperlegible"),
            ("Reduced motion", "On"),
            ("Camera view", "Third person"),
            ("Haul speed", "Quick"),
            ("Captions", "Off"),
            ("Master volume", "80%"),
            ("Music volume", "70%"),
            ("Ambience volume", "60%"),
            ("SFX volume", "50%"),
            ("Collar visibility", "Hidden"),
            ("Auto anchor", "Off"),
            ("Mouse look", "Quick"),
            ("Keyboard controls", "Open  >"),
        ])

    def test_font_bundle_and_text_scaling_need_no_native_window(self):
        self.assertTrue(Path(find_font("dyslexia")).is_file())

        class TextRecorder:
            def __init__(self):
                self.calls = []

            def render(self, text, size, color, family):
                self.calls.append((text, size, family))
                return np.zeros((size, max(1, size // 2), 4), np.uint8)

        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = TextRecorder(), {}, {}
        ui._text_scale = TEXT_SIZE_SCALES[0]
        standard = ui._render("Readable", 20, (255, 255, 255)).shape
        ui._text_scale = TEXT_SIZE_SCALES[2]
        large = ui._render("Readable", 20, (255, 255, 255)).shape
        self.assertGreater(large[0], standard[0])
        ui._dyslexia_font = True
        ui._render("Readable", 20, (255, 255, 255), "serif")
        self.assertEqual(ui._font_family("mono"), "dyslexia")
        self.assertEqual(ui._font_family("serif"), "dyslexia")
        self.assertEqual(ui.text.calls[-1][2], "dyslexia")


if __name__ == "__main__":
    unittest.main()
