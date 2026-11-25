"""SDL input and presentation regressions without a visible window.

SDL_PushEvent does not change SDL_GetKeyboardState. Controlled snapshots and
size queries keep keyboard, pointer, high-DPI resize, and minimize cases
deterministic while the native queue exercises the ctypes event layout.
"""

import ctypes
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from .platform import (
    Platform, RGB24, SCAN, SDL_Event, SDL_KeyboardEvent, SDL_Keysym, SDL_WindowEvent,
    SDL_MouseButtonEvent, SDL_MouseMotionEvent, SDL_MouseWheelEvent, SDL_Rect, SDL_Surface,
    SDL_KEYDOWN, SDL_KEYUP, SDL_QUIT, SDL_WINDOWEVENT, SDL_WINDOW_RESIZABLE,
    SDL_WINDOWEVENT_FOCUS_GAINED, SDL_WINDOWEVENT_FOCUS_LOST,
    SDL_WINDOWEVENT_SIZE_CHANGED, SDL_WINDOWEVENT_MINIMIZED, SDL_WINDOWEVENT_RESTORED,
    SDL_WINDOWEVENT_LEAVE, SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN, SDL_MOUSEWHEEL,
)


class PlatformInputChecks(unittest.TestCase):
    """Exercise native SDL event transport and mocked presentation-size boundaries."""

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

    def _motion(self, x, y, *, dx=0, dy=0):
        """Queue logical-window pointer coordinates and relative pixel deltas."""
        event = SDL_Event()
        event.motion.type = SDL_MOUSEMOTION
        event.motion.x, event.motion.y = x, y
        event.motion.xrel, event.motion.yrel = dx, dy
        self.push(event)

    def _click(self, x, y, *, button=1):
        """Queue a mouse-button edge without injecting keyboard actions."""
        event = SDL_Event()
        event.button.type = SDL_MOUSEBUTTONDOWN
        event.button.button = button
        event.button.x, event.button.y = x, y
        self.push(event)

    def _window_event(self, kind, width=0, height=0):
        """Queue a window lifecycle event with logical-pixel size payloads."""
        event = SDL_Event()
        event.window.type = SDL_WINDOWEVENT
        event.window.event = kind
        event.window.data1, event.window.data2 = width, height
        self.push(event)

    @staticmethod
    def _size_query(width, height):
        """Return an SDL-style size callback writing deterministic pixel dimensions."""
        def query(_window, output_width, output_height):
            ctypes.cast(output_width, ctypes.POINTER(ctypes.c_int))[0] = width
            ctypes.cast(output_height, ctypes.POINTER(ctypes.c_int))[0] = height
        return query

    def test_sdl2_event_layout(self):
        """Keep pointer structures ABI-compatible with SDL2's 56-byte event union."""
        self.assertEqual(ctypes.sizeof(SDL_Keysym), 16)
        self.assertEqual(ctypes.sizeof(SDL_KeyboardEvent), 32)
        self.assertEqual(ctypes.sizeof(SDL_WindowEvent), 24)
        self.assertEqual(ctypes.sizeof(SDL_MouseMotionEvent), 36)
        self.assertEqual(ctypes.sizeof(SDL_MouseButtonEvent), 28)
        self.assertEqual(ctypes.sizeof(SDL_MouseWheelEvent), 44)
        self.assertEqual(SDL_MouseMotionEvent.x.offset, 20)
        self.assertEqual(SDL_MouseMotionEvent.xrel.offset, 28)
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

    def test_window_requests_native_resize_support(self):
        """Allow the window manager to resize the software window."""
        flags = self.platform.sdl.SDL_GetWindowFlags
        flags.argtypes = [ctypes.c_void_p]
        flags.restype = ctypes.c_uint32
        self.assertTrue(flags(self.platform.window) & SDL_WINDOW_RESIZABLE)

    def test_motion_position_persists_but_movement_is_a_frame_edge(self):
        """Only real motion claims the pointer; stale coordinates do not steal focus."""
        self.key("e")
        self.assertEqual(self.platform.poll().device, "keyboard")
        self._motion(4, 6, dx=4, dy=6)
        inp = self.platform.poll()
        self.assertEqual(inp.mouse_pos, (4, 6))
        self.assertTrue(inp.mouse_moved)
        self.assertEqual(inp.device, "mouse")
        self.assertIsNone(inp.mouse_click)
        self.assertEqual(inp.pressed, set())

        inp = self.platform.poll()
        self.assertEqual(inp.mouse_pos, (4, 6))
        self.assertFalse(inp.mouse_moved)
        self.key("e")
        self._motion(4, 6)
        self.assertEqual(self.platform.poll().device, "keyboard")
        self.assertFalse(inp.mouse_moved)

        self._motion(4, 6, dx=1)
        self.assertTrue(self.platform.poll().mouse_moved)
        self.assertEqual(inp.device, "mouse")

    def _poll_with_window(self, width, height):
        """Poll once while SDL reports a width x height logical window."""
        with patch.object(self.platform.sdl, 'SDL_GetWindowSize',
                          side_effect=self._size_query(width, height)):
            return self.platform.poll()

    def test_mouse_delta_sums_each_motion_in_one_poll_and_resets_next_poll(self):
        """Look input is the frame's total travel; it never carries into the next poll."""
        self._motion(10, 10, dx=8, dy=0)
        self._motion(12, 10, dx=8, dy=-4)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (16 / 200, -4 / 200))
        self.assertEqual(self.platform.poll().mouse_delta, (0.0, 0.0))

    def test_mouse_delta_is_a_fraction_of_window_width_on_both_axes(self):
        """A full-width sweep turns the view the same at any size; height never scales it."""
        self._motion(0, 0, dx=200, dy=50)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (1.0, 0.25))
        self._motion(0, 0, dx=400, dy=50)
        self.assertEqual(self._poll_with_window(400, 200).mouse_delta, (1.0, 0.125))

    def test_an_unknown_window_size_gives_no_turn_instead_of_dividing_by_zero(self):
        """Before SDL reports a size, pointer travel is dropped rather than divided."""
        self._motion(10, 10, dx=8)
        self.assertEqual(self._poll_with_window(0, 0).mouse_delta, (0.0, 0.0))

    def test_focus_loss_drops_pending_motion_and_unfocused_motion_never_pans(self):
        """Alt-tabbing away mid-drag must not leave the view turning when focus returns."""
        self._motion(10, 10, dx=8)
        self.focus(False)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (0.0, 0.0))
        self._motion(12, 10, dx=8)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (0.0, 0.0))
        self.focus(True)
        self._motion(14, 10, dx=8)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (8 / 200, 0.0))

    def test_minimize_and_pointer_leave_drop_pending_motion(self):
        """Travel queued before the window hides or the pointer leaves never turns the view."""
        self._motion(10, 10, dx=8)
        self._window_event(SDL_WINDOWEVENT_MINIMIZED)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (0.0, 0.0))
        self._window_event(SDL_WINDOWEVENT_RESTORED)
        self._motion(10, 10, dx=8)
        self._window_event(SDL_WINDOWEVENT_LEAVE)
        self.assertEqual(self._poll_with_window(200, 100).mouse_delta, (0.0, 0.0))

    def test_an_empty_presentation_surface_drops_pending_motion(self):
        """A zero-width frame (a hidden or resizing window) drops pending travel."""
        class EmptySurface(ctypes.Structure):
            _fields_ = [('w', ctypes.c_int), ('h', ctypes.c_int)]

        self._motion(10, 10, dx=8)
        empty = ctypes.pointer(EmptySurface(0, 32))
        with patch.object(self.platform.sdl, 'SDL_GetWindowSurface', return_value=empty):
            self.assertEqual(self.platform.poll().mouse_delta, (0.0, 0.0))

    def test_button_position_does_not_synthesize_motion_or_keyboard_actions(self):
        """Clicks carry their own position; only left presses activate menus."""
        self._click(12, 17)
        inp = self.platform.poll()
        self.assertEqual(inp.mouse_pos, (12, 17))
        self.assertEqual(inp.mouse_click, (12, 17))
        self.assertFalse(inp.mouse_moved)
        self.assertEqual(inp.pressed, set())
        self.assertEqual(inp.held, set())
        self._click(19, 21, button=3)
        inp = self.platform.poll()
        self.assertEqual(inp.mouse_pos, (19, 21))
        self.assertIsNone(inp.mouse_click)
        self.assertFalse(inp.mouse_moved)

    def test_wheel_position_uses_only_supported_sdl_fields(self):
        """Old wheel unions cannot replace a known pointer with undefined coordinates."""
        self._motion(2, 3)
        self.platform.poll()
        event = SDL_Event()
        event.wheel.type = SDL_MOUSEWHEEL
        event.wheel.y = 1
        event.wheel.mouseX, event.wheel.mouseY = 9, 10
        self.platform._sdl_version = (2, 25, 0)
        self.push(event)
        inp = self.platform.poll()
        self.assertEqual(inp.mouse_pos, (2, 3))
        self.assertEqual(inp.mouse_wheel, 1)
        self.assertFalse(inp.mouse_moved)

        self.platform._sdl_version = (2, 26, 0)
        self.push(event)
        inp = self.platform.poll()
        self.assertEqual(inp.mouse_pos, (9, 10))
        self.assertEqual(inp.mouse_wheel, 1)
        self.assertFalse(inp.mouse_moved)

    def test_focus_loss_discards_pointer_edges_and_fractional_wheel_input(self):
        """A background window cannot replay queued pointer activity on returning."""
        self._motion(8, 11)
        self._click(8, 11)
        event = SDL_Event()
        event.wheel.type = SDL_MOUSEWHEEL
        event.wheel.preciseY = 0.5
        self.push(event)
        self.focus(False)
        self._motion(18, 21)
        self._click(18, 21)
        self.push(event)
        inp = self.platform.poll()
        self.assertFalse(inp.focused)
        self.assertIsNone(inp.mouse_pos)
        self.assertIsNone(inp.mouse_click)
        self.assertFalse(inp.mouse_moved)
        self.assertEqual(inp.mouse_wheel, 0)
        self.assertEqual(inp.mouse_wheel_remainder, 0.0)
        self.focus(True)
        inp = self.platform.poll()
        self.assertTrue(inp.focused)
        self.assertIsNone(inp.mouse_pos)
        self.assertIsNone(inp.mouse_click)
        self.assertFalse(inp.mouse_moved)
        self._motion(5, 9)
        self.assertEqual(self.platform.poll().mouse_pos, (5, 9))

    def test_leaving_window_invalidates_hover_without_blurring_keyboard(self):
        """An absent pointer cannot leave a menu row hovered outside the window."""
        self._motion(8, 11)
        self.platform.poll()
        self._window_event(SDL_WINDOWEVENT_LEAVE)
        inp = self.platform.poll()
        self.assertIsNone(inp.mouse_pos)
        self.assertFalse(inp.mouse_moved)
        self.assertTrue(inp.focused)

    def test_software_coordinates_follow_surface_pixels_after_logical_resize(self):
        """Logical resizes invalidate geometry without pretending the pointer moved."""
        self._motion(5, 3)
        self.platform.poll()
        with patch.object(self.platform.sdl, "SDL_GetWindowSize",
                          side_effect=self._size_query(16, 8)):
            self._window_event(SDL_WINDOWEVENT_SIZE_CHANGED, 16, 8)
            inp = self.platform.poll()
            self.assertEqual(inp.viewport, (32, 32))
            self.assertEqual(self.platform.viewport, (32, 32))
            self.assertEqual(inp.mouse_pos, (10, 12))
            self.assertTrue(inp.resized)
            self.assertFalse(inp.mouse_moved)

            self._click(7, 5)
            inp = self.platform.poll()
            self.assertEqual(inp.mouse_pos, (14, 20))
            self.assertEqual(inp.mouse_click, (14, 20))
            self.assertFalse(inp.resized)
            self.assertFalse(inp.mouse_moved)
            self._motion(-1, -1)
            inp = self.platform.poll()
            self.assertEqual(inp.mouse_pos, (-2, -4))

    def test_gl_coordinates_use_drawable_size_not_window_event_dimensions(self):
        """High-DPI pointer input shares the renderer's actual presentation pixels."""
        with (patch.object(self.platform, "context", object()),
              patch.object(self.platform.sdl, "SDL_GetWindowSize",
                           side_effect=self._size_query(1920, 1080)),
              patch.object(self.platform.sdl, "SDL_GL_GetDrawableSize",
                           side_effect=self._size_query(3840, 2160)),
              patch.object(self.platform.sdl, "SDL_GetWindowSurface") as surface):
            self._window_event(SDL_WINDOWEVENT_SIZE_CHANGED, 1920, 1080)
            self._motion(959, 539)
            self._click(1200, 720)
            inp = self.platform.poll()
            self.assertEqual(inp.viewport, (3840, 2160))
            self.assertEqual((self.platform.w, self.platform.h), inp.viewport)
            self.assertEqual(inp.mouse_pos, (2400, 1440))
            self.assertEqual(inp.mouse_click, (2400, 1440))
            self.assertTrue(inp.mouse_moved)
            self.assertTrue(inp.resized)
            surface.assert_not_called()
            inp = self.platform.poll()
            self.assertFalse(inp.resized)
            self.assertFalse(inp.mouse_moved)

    def test_minimize_clears_actions_and_restore_publishes_a_resize_edge(self):
        """Minimized windows expose zero viewport and never blit or replay a click."""
        self.hold("w")
        self.key("w")
        self._motion(5, 9)
        self._click(5, 9)
        self._window_event(SDL_WINDOWEVENT_MINIMIZED)
        self._motion(12, 20)
        self._click(12, 20)
        inp = self.platform.poll()
        self.assertEqual(inp.viewport, (0, 0))
        self.assertTrue(inp.resized)
        self.assertFalse(inp.focused)
        self.assertFalse(inp.mouse_moved)
        self.assertIsNone(inp.mouse_pos)
        self.assertIsNone(inp.mouse_click)
        self.assertEqual(inp.pressed, set())
        self.assertEqual(inp.held, set())
        with (patch.object(np, "ascontiguousarray") as upload,
              patch.object(self.platform.sdl, "SDL_GetWindowSurface") as surface,
              patch.object(self.platform.sdl, "SDL_UpdateWindowSurface") as update):
            self.platform.present(np.empty((0, 0, 3), np.uint8))
            upload.assert_not_called()
            surface.assert_not_called()
            update.assert_not_called()
        self.assertFalse(self.platform.poll().resized)
        self._window_event(SDL_WINDOWEVENT_RESTORED)
        inp = self.platform.poll()
        self.assertEqual(inp.viewport, (32, 32))
        self.assertTrue(inp.resized)
        self.assertTrue(inp.focused)
        self.assertIsNone(inp.mouse_click)
        self.assertIsNone(inp.mouse_pos)
        self.assertEqual(inp.pressed, set())
        self.assertEqual(inp.held, {"w"})

    def test_zero_window_or_drawable_sizes_never_upload_or_divide(self):
        """Zero dimensions are unavailable viewports even without a minimize event."""
        for logical, drawable in (((0, 32), (32, 32)), ((32, 32), (32, 0))):
            with (self.subTest(logical=logical, drawable=drawable),
                  patch.object(self.platform, "context", object()),
                  patch.object(self.platform.sdl, "SDL_GetWindowSize",
                               side_effect=self._size_query(*logical)),
                  patch.object(self.platform.sdl, "SDL_GL_GetDrawableSize",
                               side_effect=self._size_query(*drawable)),
                  patch.object(np, "ascontiguousarray") as upload,
                  patch.object(self.platform.sdl, "SDL_GL_SwapWindow") as swap):
                self._motion(5, 9)
                self._click(5, 9)
                self.key("e")
                inp = self.platform.poll()
                self.assertEqual(inp.viewport, (0, 0))
                self.assertIsNone(inp.mouse_pos)
                self.assertIsNone(inp.mouse_click)
                self.assertFalse(inp.mouse_moved)
                self.assertFalse(inp.focused)
                self.assertEqual(inp.pressed, set())
                self.platform.present(np.empty((0, 0, 3), np.uint8))
                upload.assert_not_called()
                swap.assert_not_called()

    def test_software_present_scales_old_frames_and_retains_resize_for_next_poll(self):
        """A resize after input polling scales rather than clipping the old UI frame."""
        destination = SDL_Surface()
        destination.w, destination.h = 64, 48
        source = SDL_Surface()
        with (patch.object(self.platform.sdl, "SDL_GetWindowSize",
                           side_effect=self._size_query(64, 48)),
              patch.object(self.platform.sdl, "SDL_GetWindowSurface",
                           return_value=ctypes.pointer(destination)),
              patch.object(self.platform.sdl, "SDL_CreateRGBSurfaceWithFormatFrom",
                           return_value=ctypes.pointer(source)) as create,
              patch.object(self.platform.sdl, "SDL_FreeSurface"),
              patch.object(self.platform.sdl, "SDL_UpperBlit", return_value=0) as direct,
              patch.object(self.platform.sdl, "SDL_UpperBlitScaled", return_value=0) as scaled,
              patch.object(self.platform.sdl, "SDL_UpdateWindowSurface", return_value=0)):
            self.platform.present(np.zeros((16, 20, 3), np.uint8))
            self.assertEqual(create.call_args.args[1:], (20, 16, 24, 60, RGB24))
            self.assertEqual(self.platform.viewport, (64, 48))
            source_rect = ctypes.cast(scaled.call_args.args[1],
                                      ctypes.POINTER(SDL_Rect)).contents
            destination_rect = ctypes.cast(scaled.call_args.args[3],
                                           ctypes.POINTER(SDL_Rect)).contents
            self.assertEqual((source_rect.x, source_rect.y, source_rect.w, source_rect.h),
                             (0, 0, 20, 16))
            self.assertEqual((destination_rect.x, destination_rect.y,
                              destination_rect.w, destination_rect.h), (0, 0, 64, 48))
            direct.assert_not_called()
            self.assertTrue(self.platform.poll().resized)
            self.assertFalse(self.platform.poll().resized)
            self.platform.present(np.zeros((48, 64, 3), np.uint8))
            direct.assert_called_once()
            scaled.assert_called_once()

    def test_gl_present_resizes_upload_texture_and_drawable_viewport_independently(self):
        """Framebuffer resizes need a new viewport, not needless texture allocations."""
        old_texture = Mock(size=(32, 32))
        texture = Mock(size=(20, 16))
        context = SimpleNamespace(
            texture=Mock(return_value=texture), screen=SimpleNamespace(use=Mock()),
            disable=Mock(), error="GL_NO_ERROR",
        )
        vao = SimpleNamespace(render=Mock())
        moderngl = SimpleNamespace(NEAREST=0, DEPTH_TEST=1, BLEND=2, CULL_FACE=4)
        with (patch.dict(sys.modules, {"moderngl": moderngl}),
              patch.object(self.platform, "context", context),
              patch.object(self.platform, "_gl_objects", [old_texture]),
              patch.object(self.platform, "_present_texture", old_texture, create=True),
              patch.object(self.platform, "_present_vao", vao, create=True),
              patch.object(self.platform, "make_current"),
              patch.object(self.platform.sdl, "SDL_GetWindowSize",
                           side_effect=self._size_query(32, 24)),
              patch.object(self.platform.sdl, "SDL_GL_GetDrawableSize",
                           side_effect=self._size_query(64, 48)) as drawable,
              patch.object(self.platform.sdl, "SDL_GL_SwapWindow") as swap):
            frame = np.zeros((16, 20, 3), np.uint8)
            self.platform.present(frame)
            context.texture.assert_called_once_with((20, 16), 3, alignment=1)
            old_texture.release.assert_called_once()
            self.assertEqual(self.platform._gl_objects, [texture])
            self.assertEqual(context.viewport, (0, 0, 64, 48))
            texture.write.assert_called_once_with(frame.tobytes(), alignment=1)
            self.assertTrue(self.platform.poll().resized)

            drawable.side_effect = self._size_query(96, 72)
            self.platform.present(frame)
            context.texture.assert_called_once()
            self.assertEqual(context.viewport, (0, 0, 96, 72))
            self.assertEqual(swap.call_count, 2)
            self.assertTrue(self.platform.poll().resized)
            self.assertFalse(self.platform.poll().resized)

    def test_cursor_visibility_is_explicit_and_avoids_redundant_sdl_calls(self):
        """UI ownership can show/hide the cursor without affecting input state."""
        with patch.object(self.platform.sdl, "SDL_ShowCursor", return_value=1) as cursor:
            self.platform.set_pointer_visible(True)
            self.platform.set_pointer_visible(True)
            self.platform.set_pointer_visible(False)
            self.assertEqual([call.args for call in cursor.call_args_list], [(1,), (0,)])
        self.assertEqual(self.platform._input.pressed, set())

    def test_failed_cursor_visibility_is_not_cached_as_success(self):
        """A failed native visibility change remains retryable by its caller."""
        with patch.object(self.platform.sdl, "SDL_ShowCursor",
                          side_effect=[-1, 1]) as cursor:
            with self.assertRaises(RuntimeError):
                self.platform.set_pointer_visible(False)
            self.platform.set_pointer_visible(False)
            self.assertEqual(cursor.call_count, 2)

    def test_old_sdl_uses_integer_wheel_delta_when_precise_y_is_garbage(self):
        self.platform._sdl_version = (2, 0, 17)
        event = SDL_Event()
        event.wheel.y = 1
        event.wheel.preciseY = 1234.0
        self.assertEqual(self.platform._wheel_delta(event.wheel), 1.0)

    def test_sdl_2018_uses_nonzero_fractional_precise_wheel_delta(self):
        self.platform._sdl_version = (2, 0, 18)
        event = SDL_Event()
        event.wheel.y = 3
        event.wheel.preciseY = 0.5
        self.assertEqual(self.platform._wheel_delta(event.wheel), 0.5)

    def test_fractional_wheel_deltas_accumulate_into_menu_steps(self):
        """Retain fractional trackpad deltas until a whole menu step is reached."""
        self.assertEqual(self.platform._wheel_steps(0.5, 0), 0)
        self.assertEqual(self.platform._wheel_steps(0.5, 0), 1)
        self.assertEqual(self.platform._wheel_steps(0.5, 1), 0)
        self.assertEqual(self.platform._wheel_steps(0.5, 1), -1)

        self.assertEqual(self.platform._wheel_steps(0.5, 0), 0)
        self.focus(False)
        self.platform.poll()
        self.focus(True)
        self.platform.poll()
        self.assertEqual(self.platform._wheel_steps(0.5, 0), 0)

    def test_dev_panel_discards_partial_wheel_input_before_returning_to_menu(self):
        """A half-wheel delta swallowed by Devmode cannot scroll the menu after closing it."""
        from .game import Session
        from .sim import State
        from .world import World

        world = World("briar")
        with tempfile.TemporaryDirectory(prefix="dev-wheel-") as temp:
            session = Session(world, Path(temp) / "save.json", State.new(world, seed=17),
                              has_save=False, dev=True)
            session.ui.mode = "journal"
            session.dev_mode.open = True
            session.ui.book_entry_i = 0
            self.assertEqual(self.platform._wheel_steps(0.5, 0), 0)
            session.tick(self.platform.poll(), 0.0)
            self.assertEqual(self.platform._input.mouse_wheel_remainder, 0.0)

            session.dev_mode.open = False
            self.assertEqual(self.platform._wheel_steps(0.5, 0), 0)
            session.tick(self.platform.poll(), 0.0)
            self.assertEqual(session.ui.book_entry_i, 0)

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
