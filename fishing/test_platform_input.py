"""Keyboard event regressions through the real SDL event queue.

SDL_PushEvent does not change SDL_GetKeyboardState. A controlled final snapshot
models physical keys while the native queue exercises the ctypes event layout.
"""

import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .platform import (
    Platform, SCAN, SDL_Event, SDL_KeyboardEvent, SDL_Keysym, SDL_WindowEvent,
    SDL_KEYDOWN, SDL_KEYUP, SDL_QUIT, SDL_WINDOWEVENT,
    SDL_WINDOWEVENT_FOCUS_GAINED, SDL_WINDOWEVENT_FOCUS_LOST,
    SDL_MOUSEBUTTONDOWN, SDL_MOUSEWHEEL,
)


class PlatformInputChecks(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.platform = Platform(32, 32, graphics=False)
        self.addCleanup(self.platform.close)
        self.platform.sdl.SDL_PushEvent.argtypes = [ctypes.POINTER(SDL_Event)]
        self.platform.sdl.SDL_PushEvent.restype = ctypes.c_int
        self.state = (ctypes.c_uint8 * 512)()

        def keyboard_snapshot(count):
            ctypes.cast(count, ctypes.POINTER(ctypes.c_int))[0] = len(self.state)
            return self.state

        self.snapshot = patch.object(self.platform.sdl, 'SDL_GetKeyboardState',
                                     side_effect=keyboard_snapshot)
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)
        self.platform.poll()  # Drain initial window events.

    def hold(self, *names):
        for code in range(len(self.state)):
            self.state[code] = 0
        for name in names:
            self.state[SCAN[name]] = 1

    def key(self, name, *, down=True, repeat=False, sym=0):
        event = SDL_Event()
        event.key.type = SDL_KEYDOWN if down else SDL_KEYUP
        event.key.state = int(down)
        event.key.repeat = int(repeat)
        event.key.keysym.scancode = SCAN[name] if isinstance(name, str) else name
        event.key.keysym.sym = sym
        self.push(event)

    def push(self, event):
        self.assertEqual(self.platform.sdl.SDL_PushEvent(ctypes.byref(event)), 1)

    def focus(self, gained):
        event = SDL_Event()
        event.window.type = SDL_WINDOWEVENT
        event.window.event = SDL_WINDOWEVENT_FOCUS_GAINED if gained else SDL_WINDOWEVENT_FOCUS_LOST
        self.push(event)

    def test_sdl2_event_layout(self):
        self.assertEqual(ctypes.sizeof(SDL_Keysym), 16)
        self.assertEqual(ctypes.sizeof(SDL_KeyboardEvent), 32)
        self.assertEqual(ctypes.sizeof(SDL_WindowEvent), 24)
        self.assertEqual(ctypes.sizeof(SDL_Event), 56)
        self.assertEqual(SDL_KeyboardEvent.keysym.offset, 16)
        self.assertEqual(SDL_KeyboardEvent.repeat.offset, 13)
        self.assertEqual(SDL_WindowEvent.event.offset, 12)

    def test_pointer_edges_wheel_direction_and_focus_are_preserved(self):
        event = SDL_Event()
        event.button.type = SDL_MOUSEBUTTONDOWN
        event.button.button = 1
        event.button.x, event.button.y = 12, 17
        self.push(event)
        event = SDL_Event()
        event.wheel.type = SDL_MOUSEWHEEL
        event.wheel.y, event.wheel.direction = 2, 1
        self.push(event)
        inp = self.platform.poll()
        self.assertEqual(inp.mouse_click, (12, 17))
        self.assertEqual(inp.mouse_wheel, -2)
        self.assertEqual(inp.viewport, (32, 32))
        self.assertEqual(inp.device, "mouse")
        self.assertIsNone(self.platform.poll().mouse_click)
        self.assertEqual(inp.mouse_wheel, 0)
        self.focus(False)
        self.push(event)
        self.assertEqual(self.platform.poll().mouse_wheel, 0)

    def test_complete_taps_between_frames_survive_once(self):
        for name in SCAN:
            self.key(name)
            self.key(name, down=False)
        inp = self.platform.poll()
        self.assertEqual(inp.pressed, set(SCAN))
        self.assertEqual(inp.held, set())
        self.assertTrue(inp.tap('w', .1))
        self.assertIs(self.platform.poll(), inp)
        self.assertEqual(inp.pressed, set())
        self.assertFalse(inp.tap('w', .5))

    def test_held_snapshot_and_os_repeat_do_not_retrigger_one_shots(self):
        self.hold('space', 'w', 'rshift')
        for name in ('space', 'w', 'rshift'):
            self.key(name)
        inp = self.platform.poll()
        self.assertEqual(inp.pressed, {'space', 'w', 'rshift'})
        self.assertTrue(inp.tap('w', .01))
        self.key('space', repeat=True)
        self.key('w', repeat=True)
        inp = self.platform.poll()
        self.assertEqual(inp.pressed, set())
        self.assertEqual(inp.held, {'space', 'w', 'rshift'})
        self.assertFalse(inp.tap('w', .2))
        self.assertTrue(inp.tap('w', .2))  # Game repeat, independent of OS repeat.
        self.assertFalse(inp.tap('w', .01))
        self.hold()
        self.key('w', down=False)
        inp = self.platform.poll()
        self.assertEqual(inp.held, set())
        self.assertFalse(inp.tap('w', 1))

    def test_release_and_repress_between_frames_is_a_new_edge(self):
        self.hold('e')
        self.key('e')
        self.assertEqual(self.platform.poll().pressed, {'e'})
        self.key('e', down=False)
        self.key('e')
        self.assertEqual(self.platform.poll().pressed, {'e'})
        self.assertEqual(self.platform.poll().pressed, set())

    def test_scancode_selects_action_and_unknown_keys_are_ignored(self):
        self.key('h', sym=ord('j'))
        self.key(-1)
        self.key(9999)
        self.assertEqual(self.platform.poll().pressed, {'h'})

    def test_focus_loss_clears_queued_actions_held_keys_and_repeat(self):
        self.hold('w')
        self.key('w')
        inp = self.platform.poll()
        self.assertTrue(inp.tap('w', .1))
        inp = self.platform.poll()
        self.assertFalse(inp.tap('w', .3))
        self.key('space')
        self.focus(False)
        self.key('e')
        inp = self.platform.poll()
        self.assertFalse(inp.focused)
        self.assertEqual(inp.pressed, set())
        self.assertEqual(inp.held, set())
        self.assertEqual(inp._rep, {})
        self.assertEqual(self.platform.poll().held, set())
        self.focus(True)
        self.key('w', repeat=True)
        inp = self.platform.poll()
        self.assertTrue(inp.focused)
        self.assertEqual(inp.pressed, set())
        self.assertEqual(inp.held, {'w'})
        self.assertFalse(inp.tap('w', .1))  # No stale repeat from before focus loss.
        self.key('w', down=False)
        self.key('w')
        self.assertEqual(self.platform.poll().pressed, {'w'})

    def test_quit_is_reported_for_the_poll_that_received_it(self):
        event = SDL_Event()
        event.type = SDL_QUIT
        self.push(event)
        self.assertTrue(self.platform.poll().quit)
        self.assertFalse(self.platform.poll().quit)

    def test_menu_direction_requires_release_before_driving(self):
        from .game import Session
        from .sim import State
        from .world import World

        world = World()
        with tempfile.TemporaryDirectory(prefix='briar-input-') as temp:
            state = State.new(world, seed=17)
            session = Session(world, Path(temp) / 'save.json', state, True)
            session.ui.mode = 'help'
            session.ui.help_from = 'play'
            self.hold('w')
            self.key('w')
            session.tick(self.platform.poll(), .1)
            self.key('esc')
            self.key('esc', down=False)
            session.tick(self.platform.poll(), .1)
            self.assertEqual(session.ui.mode, 'play')
            self.assertEqual(state.throttle_setting, 0)
            self.key('w', repeat=True)
            session.tick(self.platform.poll(), .1)
            self.assertEqual(state.throttle_setting, 0)
            self.hold()
            self.key('w', down=False)
            session.tick(self.platform.poll(), .1)
            self.hold('w')
            self.key('w')
            session.tick(self.platform.poll(), .1)
            self.assertGreater(state.throttle_setting, 0)
            throttle = state.throttle_setting
            self.hold()
            self.key('w', down=False)
            session.tick(self.platform.poll(), .1)
            self.assertEqual(state.throttle_setting, throttle)

    def test_short_movement_taps_drive_and_steer_for_one_tick(self):
        from .game import Session
        from .sim import State
        from .world import World

        world = World()
        with tempfile.TemporaryDirectory(prefix='briar-short-movement-') as temp:
            state = State.new(world, seed=17)
            state.anchored = False
            session = Session(world, Path(temp) / 'save.json', state, True)
            session.ui.mode = 'play'

            self.key('w')
            self.key('w', down=False)
            inp = self.platform.poll()
            self.assertEqual(inp.pressed, {'w'})
            self.assertEqual(inp.held, set())
            session.tick(inp, .1)
            throttle = state.throttle_setting
            self.assertGreater(throttle, 0)
            session.tick(self.platform.poll(), .1)
            self.assertEqual(state.throttle_setting, throttle)

            self.key('a')
            self.key('a', down=False)
            inp = self.platform.poll()
            self.assertEqual(inp.pressed, {'a'})
            self.assertEqual(inp.held, set())
            session.tick(inp, .1)
            self.assertLess(state.steer, 0)
            steer = state.steer
            session.tick(self.platform.poll(), .1)
            self.assertGreater(state.steer, steer)

    def test_menu_movement_tap_does_not_drive_when_closing_menu(self):
        from .game import Session
        from .sim import State
        from .world import World

        world = World()
        with tempfile.TemporaryDirectory(prefix='briar-menu-tap-') as temp:
            state = State.new(world, seed=17)
            state.anchored = False
            session = Session(world, Path(temp) / 'save.json', state, True)
            session.ui.mode = 'help'
            session.ui.help_from = 'play'
            self.key('w')
            self.key('w', down=False)
            self.key('esc')
            self.key('esc', down=False)
            session.tick(self.platform.poll(), .1)
            self.assertEqual(session.ui.mode, 'play')
            self.assertEqual(state.throttle_setting, 0)

    def test_short_shift_taps_idle_the_lever_after_release(self):
        from .game import Session
        from .sim import State
        from .world import World

        world = World()
        with tempfile.TemporaryDirectory(prefix='briar-shift-input-') as temp:
            for name in ('shift', 'rshift'):
                with self.subTest(key=name):
                    state = State.new(world, seed=17)
                    state.anchored = False
                    state.throttle_setting = state.throttle = .75
                    session = Session(world, Path(temp) / 'save.json', state, True)
                    session.ui.mode = 'play'
                    self.key(name)
                    self.key(name, down=False)
                    inp = self.platform.poll()
                    self.assertEqual(inp.held, set())
                    self.assertEqual(inp.pressed, {name})
                    session.tick(inp, .1)
                    self.assertEqual(state.throttle_setting, 0)
                    session.tick(self.platform.poll(), .1)
                    self.assertEqual(state.throttle_setting, 0)


if __name__ == '__main__':
    unittest.main()
