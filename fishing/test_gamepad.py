"""SDL GameController translation and controller-only play loop checks."""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from .gamepad import (
    AXIS_LEFTX, AXIS_LEFTY, AXIS_TRIGGERRIGHT, BUTTON_A, BUTTON_B, BUTTON_DPAD_DOWN,
    BUTTON_DPAD_RIGHT, BUTTON_X, BUTTON_Y, SDL_CONTROLLERAXISMOTION,
    SDL_CONTROLLERBUTTONDOWN, SDL_CONTROLLERBUTTONUP,
    SDL_CONTROLLERDEVICEADDED, SDL_CONTROLLERDEVICEREMOVED,
    default_key_bindings, remap_keyboard, session_input,
)
from .game import Session
from .platform import Input, Platform, SDL_Event
from .sim import State
from .ui import check_rows
from .world import World


class GamepadChecks(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.platform = Platform(32, 32, graphics=False)
        self.addCleanup(self.platform.close)
        self.platform.sdl.SDL_PushEvent.argtypes = [ctypes.POINTER(SDL_Event)]
        self.platform.sdl.SDL_PushEvent.restype = ctypes.c_int
        self.platform.poll()  # Drain window events before each event assertion.
        self.timestamp = 100

    def push(self, event):
        self.assertEqual(self.platform.sdl.SDL_PushEvent(ctypes.byref(event)), 1)

    def button(self, button, down, timestamp=None):
        event = SDL_Event()
        event.cbutton.type = SDL_CONTROLLERBUTTONDOWN if down else SDL_CONTROLLERBUTTONUP
        event.cbutton.timestamp = self.timestamp if timestamp is None else timestamp
        event.cbutton.which = 77
        event.cbutton.button = button
        event.cbutton.state = int(down)
        self.push(event)
        self.timestamp += 50

    def axis(self, axis, value):
        event = SDL_Event()
        event.caxis.type = SDL_CONTROLLERAXISMOTION
        event.caxis.timestamp = self.timestamp
        event.caxis.which = 77
        event.caxis.axis = axis
        event.caxis.value = value
        self.timestamp += 50
        self.push(event)

    def tap(self, button, session=None):
        self.button(button, True)
        self.button(button, False)
        keys = self.platform.poll(0.05)
        if session is not None:
            session.tick(keys, 0.05)
        return keys

    def attach_virtual_controller(self):
        sdl = self.platform.sdl
        try:
            attach = sdl.SDL_JoystickAttachVirtual
            detach = sdl.SDL_JoystickDetachVirtual
            get_joystick = sdl.SDL_GameControllerGetJoystick
            set_button = sdl.SDL_JoystickSetVirtualButton
            update = sdl.SDL_JoystickUpdate
        except AttributeError:
            self.skipTest("SDL virtual controllers are unavailable")
        attach.argtypes = [ctypes.c_int] * 4
        attach.restype = ctypes.c_int
        detach.argtypes = [ctypes.c_int]
        detach.restype = ctypes.c_int
        get_joystick.argtypes = [ctypes.c_void_p]
        get_joystick.restype = ctypes.c_void_p
        set_button.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8]
        set_button.restype = ctypes.c_int
        update.argtypes = []

        # SDL_JOYSTICK_TYPE_GAMECONTROLLER is 1. SDL assigns the standard
        # GameController button mapping to this virtual device.
        index = attach(1, 6, 16, 1)
        self.assertGreaterEqual(index, 0, "could not attach SDL virtual controller")
        self.platform.poll(0.05)  # Process DEVICEADDED and open the controller.
        self.assertIsNotNone(self.platform.gamepad.controller)
        joystick = get_joystick(self.platform.gamepad.controller)
        self.assertTrue(joystick)

        detached = False

        def detach_device():
            nonlocal detached
            if detached:
                return
            if detach(index) != 0:
                raise AssertionError("could not detach SDL virtual controller")
            detached = True
            self.platform.poll(0.05)  # Drain DEVICE REMOVED before SDL_Quit.

        def cleanup():
            detach_device()
            self.platform.gamepad.close()

        self.addCleanup(cleanup)
        return joystick, set_button, update, detach_device

    def virtual_button(self, joystick, set_button, update, button, down):
        self.assertEqual(set_button(joystick, button, int(down)), 0)
        update()
        return self.platform.poll(0.05)

    def virtual_tap(self, joystick, set_button, update, button, session):
        session.tick(self.virtual_button(joystick, set_button, update, button, True), 0.05)
        session.tick(self.virtual_button(joystick, set_button, update, button, False), 0.05)

    def test_buttons_hold_and_y_tap_vs_hold(self):
        self.button(BUTTON_A, True)
        self.button(BUTTON_A, False)
        keys = self.platform.poll(0.05)
        self.assertEqual(keys.gamepad_pressed, {"e", "return"})
        self.assertEqual(keys.gamepad_held, set())
        self.assertEqual(keys.device, "gamepad")

        self.button(BUTTON_Y, True)
        self.button(BUTTON_Y, False)
        keys = self.platform.poll(0.05)
        self.assertEqual(keys.gamepad_pressed, {"b"})
        self.assertNotIn("z", keys.gamepad_held)

        self.button(BUTTON_Y, True)
        keys = self.platform.poll(0.16)
        self.assertNotIn("b", keys.gamepad_pressed)
        self.assertNotIn("z", keys.gamepad_held)
        keys = self.platform.poll(0.16)
        self.assertIn("z", keys.gamepad_pressed)
        self.assertIn("z", keys.gamepad_held)
        self.button(BUTTON_Y, False)
        keys = self.platform.poll(0.05)
        self.assertNotIn("b", keys.gamepad_pressed)
        self.assertNotIn("z", keys.gamepad_held)

    def test_stick_deadzone_trigger_lever_and_hotplug_events(self):
        self.axis(AXIS_LEFTX, -5000)
        keys = self.platform.poll()
        self.assertNotIn("a", keys.gamepad_held)

        self.axis(AXIS_LEFTX, -20000)
        keys = self.platform.poll()
        self.assertIn("a", keys.gamepad_pressed)
        self.assertIn("a", keys.gamepad_held)
        self.axis(AXIS_LEFTX, 0)
        self.assertNotIn("a", self.platform.poll().gamepad_held)

        self.axis(AXIS_TRIGGERRIGHT, 24000)
        keys = self.platform.poll()
        self.assertIn("w", keys.gamepad_held)
        self.axis(AXIS_TRIGGERRIGHT, 0)
        self.assertNotIn("w", self.platform.poll().gamepad_held)

        added = SDL_Event()
        added.cdevice.type = SDL_CONTROLLERDEVICEADDED
        added.cdevice.which = 0
        self.push(added)
        self.platform.poll()
        self.button(BUTTON_DPAD_DOWN, True)
        self.assertIn("down", self.platform.poll().gamepad_held)
        removed = SDL_Event()
        removed.cdevice.type = SDL_CONTROLLERDEVICEREMOVED
        removed.cdevice.which = 77
        self.push(removed)
        self.assertEqual(self.platform.poll().gamepad_held, set())

    def test_virtual_controller_hotplug_opens_and_closes(self):
        joystick, set_button, update, detach_device = self.attach_virtual_controller()
        keys = self.virtual_button(joystick, set_button, update, BUTTON_A, True)
        self.assertEqual(keys.gamepad_pressed, {"e", "return"})
        self.assertEqual(keys.device, "gamepad")
        self.virtual_button(joystick, set_button, update, BUTTON_A, False)
        detach_device()
        self.assertIsNone(self.platform.gamepad.controller)
        self.assertIsNone(self.platform.gamepad.instance_id)

    def test_saved_key_binding_remaps_keyboard_without_remapping_pad(self):
        saved = default_key_bindings()
        saved["throttle_up"] = "p"
        pressed, held = remap_keyboard({"p", "w"}, {"p", "w"}, saved)
        self.assertIn("w", pressed)
        self.assertIn("w", held)

        keys = SimpleNamespace(
            keyboard_pressed={"p"}, keyboard_held={"p"},
            gamepad_pressed={"e"}, gamepad_held={"e"},
            quit=False, focused=True, device="gamepad",
        )
        mapped = session_input(keys, saved, {})
        self.assertIn("w", mapped.pressed)
        self.assertIn("e", mapped.pressed)
        self.assertEqual(mapped.device, "gamepad")

    def test_session_accepts_legacy_input_aggregate_fields(self):
        world = World()
        state = State.new(world, seed=1707)
        with tempfile.TemporaryDirectory(prefix="trotline-legacy-input-") as temp:
            session = Session(world, Path(temp) / "save.json", state, False)
            session.ui.mode = "journal"
            keys = Input()
            keys.pressed = keys.held = {"s"}
            session.tick(keys, 0.05)
            keys.pressed = set()
            for _ in range(9):
                session.tick(keys, 0.1)
            self.assertGreaterEqual(session.ui.journal_i, 3)

    def test_menu_stick_direction_requires_release_before_driving(self):
        world = World()
        state = State.new(world, seed=1706)
        state.anchored = False
        with tempfile.TemporaryDirectory(prefix="trotline-gamepad-menu-release-") as temp:
            session = Session(world, Path(temp) / "save.json", state, False)
            session.ui.mode = "help"
            session.ui.help_from = "play"

            self.axis(AXIS_LEFTY, -20000)  # Left stick up navigates and means throttle.
            session.tick(self.platform.poll(0.1), 0.1)
            self.button(BUTTON_B, True)  # B closes help while the stick is held.
            session.tick(self.platform.poll(0.1), 0.1)
            self.assertEqual(session.ui.mode, "play")
            self.assertEqual(state.throttle_setting, 0)

            self.axis(AXIS_LEFTY, 0)
            session.tick(self.platform.poll(0.1), 0.1)
            self.axis(AXIS_LEFTY, -20000)
            session.tick(self.platform.poll(0.1), 0.1)
            self.assertGreater(state.throttle_setting, 0)

    def test_controller_events_run_set_scout_check_shop_and_travel_loop(self):
        joystick, set_button, update, _detach_device = self.attach_virtual_controller()
        world = World()
        state = State.new(world, seed=1705)
        # Start far enough outside the landing's no-line area to set a line.
        fx, fz = math.sin(state.yaw), math.cos(state.yaw)
        state.x += fx * 100.0
        state.z += fz * 100.0
        with tempfile.TemporaryDirectory(prefix="trotline-gamepad-loop-") as temp:
            session = Session(world, Path(temp) / "save.json", state, False)
            session.ui.mode = "play"

            self.virtual_tap(joystick, set_button, update, BUTTON_X, session)  # Set a line.
            self.assertEqual(session.ui.mode, "setbait")
            self.virtual_tap(joystick, set_button, update, BUTTON_A, session)
            self.assertEqual(len(state.lines), 1)
            self.assertEqual(len(state.held), 0)

            self.virtual_tap(joystick, set_button, update, BUTTON_Y, session)  # Tap Y sends Bot to scout.
            self.assertNotEqual(state.bot_phase, "home")

            self.virtual_tap(joystick, set_button, update, BUTTON_A, session)  # E-equivalent opens the check list.
            self.assertEqual(session.ui.mode, "check")
            for _ in range(len(check_rows(state, 0)) - 1):
                self.virtual_tap(joystick, set_button, update, BUTTON_DPAD_DOWN, session)
            self.virtual_tap(joystick, set_button, update, BUTTON_A, session)  # Pull the empty line aboard.
            self.assertEqual(session.ui.mode, "play")
            self.assertEqual(state.lines, [])
            self.assertEqual(len(state.held), 1)

            state._park(world)  # Stable dock fixture for the shop/travel section.
            self.virtual_tap(joystick, set_button, update, BUTTON_A, session)
            self.assertEqual(session.ui.mode, "shop")
            for _ in range(5):
                self.virtual_tap(joystick, set_button, update, BUTTON_DPAD_RIGHT, session)
            self.assertEqual(session.ui.shop_tab, 5)
            self.virtual_tap(joystick, set_button, update, BUTTON_DPAD_DOWN, session)
            self.virtual_tap(joystick, set_button, update, BUTTON_A, session)
            self.assertEqual(session.world.id, "cedar")
            self.assertEqual(session.ui.mode, "play")
