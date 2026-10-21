"""SDL GameController input and the saved keyboard-to-action table."""

from __future__ import annotations

import ctypes
from ctypes import c_int, c_int16, c_uint8, c_uint16, c_uint32, c_void_p


SDL_INIT_JOYSTICK = 0x00000200
SDL_INIT_GAMECONTROLLER = 0x00002000
SDL_ENABLE = 1

SDL_CONTROLLERAXISMOTION = 0x650
SDL_CONTROLLERBUTTONDOWN = 0x651
SDL_CONTROLLERBUTTONUP = 0x652
SDL_CONTROLLERDEVICEADDED = 0x653
SDL_CONTROLLERDEVICEREMOVED = 0x654
SDL_CONTROLLERDEVICEREMAPPED = 0x655

AXIS_LEFTX = 0
AXIS_LEFTY = 1
AXIS_TRIGGERLEFT = 4
AXIS_TRIGGERRIGHT = 5

BUTTON_A = 0
BUTTON_B = 1
BUTTON_X = 2
BUTTON_Y = 3
BUTTON_BACK = 4
BUTTON_START = 6
BUTTON_LEFTSHOULDER = 9
BUTTON_RIGHTSHOULDER = 10
BUTTON_DPAD_UP = 11
BUTTON_DPAD_DOWN = 12
BUTTON_DPAD_LEFT = 13
BUTTON_DPAD_RIGHT = 14

Y_TAP_LIMIT_MS = 300
STICK_DEADZONE = 0.22
STICK_RELEASE_ZONE = 0.15
TRIGGER_DEADZONE = 0.20
TRIGGER_RELEASE_ZONE = 0.12


class SDL_ControllerAxisEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int),
        ("axis", c_uint8), ("padding1", c_uint8), ("padding2", c_uint8),
        ("padding3", c_uint8), ("value", c_int16), ("padding4", c_uint16),
    ]


class SDL_ControllerButtonEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int),
        ("button", c_uint8), ("state", c_uint8), ("padding1", c_uint8),
        ("padding2", c_uint8),
    ]


class SDL_ControllerDeviceEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int),
    ]


# The values name the physical keyboard key for each action. A settings screen
# can change the key values later without changing gameplay code.
ACTION_SYMBOLS = {
    "throttle_up": "w", "throttle_down": "s",
    "steer_left": "a", "steer_right": "d",
    "idle": "shift", "idle_right": "rshift", "anchor": "space",
    "set_line": "f", "check_or_land": "e", "help": "h", "pause": "esc",
    "mute": "m", "hail": "c", "chart": "tab", "journal": "j",
    "livewell": "i", "bot": "b", "time_scale": "t", "sail": "q",
    "tow": "r", "new_game": "n", "dialogue_continue": "c",
    "catnap": "z", "bot_tool": "g", "galley": "k",
    "menu_up": "up", "menu_down": "down", "menu_left": "left",
    "menu_right": "right",
    "select": "return", "alternate_select": "space", "cancel": "esc",
}

DEFAULT_KEY_BINDINGS = {
    "throttle_up": "w", "throttle_down": "s",
    "steer_left": "a", "steer_right": "d",
    "idle": "shift", "idle_right": "rshift", "anchor": "space",
    "set_line": "f", "check_or_land": "e", "help": "h", "pause": "esc",
    "mute": "m", "hail": "c", "chart": "tab", "journal": "j",
    "livewell": "i", "bot": "b", "time_scale": "t", "sail": "q",
    "tow": "r", "new_game": "n", "dialogue_continue": "c",
    "catnap": "z", "bot_tool": "g", "galley": "k",
    "menu_up": "up", "menu_down": "down", "menu_left": "left",
    "menu_right": "right",
    "select": "return", "alternate_select": "space", "cancel": "esc",
}

KEY_NAMES = frozenset({
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "m",
    "n", "p", "q", "r", "s", "t", "w", "z", "1", "2", "3", "4",
    "5", "return", "esc", "tab", "space", "right", "left", "down", "up",
    "shift", "rshift",
})

BUTTON_ACTIONS = {
    BUTTON_A: ("e", "return"),
    BUTTON_B: ("esc",),
    BUTTON_X: ("f",),
    BUTTON_BACK: ("tab",),
    BUTTON_START: ("esc",),
    BUTTON_LEFTSHOULDER: ("g",),
    BUTTON_RIGHTSHOULDER: ("c",),
    BUTTON_DPAD_UP: ("up",),
    BUTTON_DPAD_DOWN: ("down",),
    BUTTON_DPAD_LEFT: ("left",),
    BUTTON_DPAD_RIGHT: ("right",),
}


def default_key_bindings() -> dict[str, str]:
    return dict(DEFAULT_KEY_BINDINGS)


def _bindings(saved) -> dict[str, str]:
    bindings = default_key_bindings()
    if isinstance(saved, dict):
        for action in bindings:
            key = saved.get(action)
            if isinstance(key, str) and key in KEY_NAMES:
                bindings[action] = key
    return bindings


def remap_keyboard(pressed, held, saved=None) -> tuple[set[str], set[str]]:
    """Translate physical keyboard keys to canonical game actions."""
    pressed, held = set(pressed), set(held)
    bindings = _bindings(saved)
    translated_pressed: set[str] = set()
    translated_held: set[str] = set()
    for action, symbol in ACTION_SYMBOLS.items():
        key = bindings[action]
        if key in pressed:
            translated_pressed.add(symbol)
        if key in held:
            translated_held.add(symbol)
    # Bait selection and dialogue choice numbers are not remapped.
    for key in "12345":
        if key in pressed:
            translated_pressed.add(key)
        if key in held:
            translated_held.add(key)
    return translated_pressed, translated_held


def session_input(keys, saved_bindings, repeat_state: dict[str, float]):
    """Build one action input from a Platform Input without losing its source."""
    keyboard_pressed_source = getattr(keys, "keyboard_pressed", None)
    keyboard_held_source = getattr(keys, "keyboard_held", None)
    if keyboard_pressed_source is None or keyboard_held_source is None:
        return keys
    gamepad_pressed_source = set(getattr(keys, "gamepad_pressed", ()))
    gamepad_held_source = set(getattr(keys, "gamepad_held", ()))
    # Keep supporting callers that construct Platform.Input directly and set
    # its legacy aggregate fields, as the built-in self-test does.
    if not (keyboard_pressed_source or keyboard_held_source
            or gamepad_pressed_source or gamepad_held_source):
        if keys.pressed or keys.held:
            keyboard_pressed_source = keys.pressed
            keyboard_held_source = keys.held
    keyboard_pressed, keyboard_held = remap_keyboard(
        keyboard_pressed_source, keyboard_held_source, saved_bindings,
    )
    pressed = keyboard_pressed | gamepad_pressed_source
    held = keyboard_held | gamepad_held_source

    class ActionInput:
        def __init__(self):
            self.pressed = pressed
            self.held = held
            self.quit = keys.quit
            self.focused = keys.focused
            self.device = keys.device
            self.keyboard_pressed = keyboard_pressed
            self.keyboard_held = keyboard_held
            self.gamepad_pressed = gamepad_pressed_source
            self.gamepad_held = gamepad_held_source
            self._rep = repeat_state

        def tap(self, name: str, dt: float) -> bool:
            if name in self.pressed:
                self._rep[name] = 0.0
                return True
            if name in self.held:
                self._rep[name] = self._rep.get(name, 0.0) + dt
                if self._rep[name] > 0.38:
                    self._rep[name] = 0.26
                    return True
                return False
            self._rep.pop(name, None)
            return False

    return ActionInput()


class Gamepad:
    """One active SDL GameController; other controllers are ignored safely."""

    def __init__(self, sdl):
        self.sdl = sdl
        self.controller = None
        self.instance_id: int | None = None
        self.buttons: set[int] = set()
        self.axes: dict[int, int] = {}
        self._axis_actions: set[str] = set()
        self._pressed: set[str] = set()
        self._y_down = False
        self._y_elapsed = 0.0
        self._y_started_ms = 0
        self._y_long = False
        self._y_release_pulse = False
        self.activity = False
        self._bind_sdl()
        self._open_existing()

    def _bind_sdl(self):
        s = self.sdl
        s.SDL_GameControllerEventState.argtypes = [c_int]
        s.SDL_GameControllerEventState.restype = c_int
        s.SDL_NumJoysticks.restype = c_int
        s.SDL_IsGameController.argtypes = [c_int]
        s.SDL_IsGameController.restype = c_int
        s.SDL_GameControllerOpen.argtypes = [c_int]
        s.SDL_GameControllerOpen.restype = c_void_p
        s.SDL_GameControllerGetJoystick.argtypes = [c_void_p]
        s.SDL_GameControllerGetJoystick.restype = c_void_p
        s.SDL_JoystickInstanceID.argtypes = [c_void_p]
        s.SDL_JoystickInstanceID.restype = c_int
        s.SDL_GameControllerClose.argtypes = [c_void_p]
        s.SDL_GameControllerEventState(SDL_ENABLE)

    def _open_existing(self):
        if self.controller is not None:
            return
        for index in range(max(0, int(self.sdl.SDL_NumJoysticks()))):
            if self.sdl.SDL_IsGameController(index):
                self._open(index)
                if self.controller is not None:
                    break

    def _open(self, index: int):
        if self.controller is not None or index < 0:
            return
        if not self.sdl.SDL_IsGameController(index):
            return
        controller = self.sdl.SDL_GameControllerOpen(index)
        if not controller:
            return
        joystick = self.sdl.SDL_GameControllerGetJoystick(controller)
        instance_id = self.sdl.SDL_JoystickInstanceID(joystick) if joystick else -1
        if instance_id < 0:
            self.sdl.SDL_GameControllerClose(controller)
            return
        self.controller = controller
        self.instance_id = int(instance_id)

    def _close(self):
        if self.controller:
            self.sdl.SDL_GameControllerClose(self.controller)
        self.controller = None
        self.instance_id = None
        self.clear_input()

    def close(self):
        self._close()

    def clear_input(self):
        self.buttons.clear()
        self.axes.clear()
        self._axis_actions.clear()
        self._pressed.clear()
        self._y_down = False
        self._y_elapsed = 0.0
        self._y_started_ms = 0
        self._y_long = False
        self._y_release_pulse = False
        self.activity = False

    def handle_event(self, event):
        event_type = int(event.type)
        if event_type == SDL_CONTROLLERDEVICEADDED:
            self._open(int(event.cdevice.which))
            return
        if event_type == SDL_CONTROLLERDEVICEREMOVED:
            removed = int(event.cdevice.which)
            if self.instance_id is None or removed == self.instance_id:
                self._close()
                self._open_existing()
            return
        if event_type == SDL_CONTROLLERDEVICEREMAPPED:
            return
        if event_type == SDL_CONTROLLERAXISMOTION:
            if self.instance_id is not None and int(event.caxis.which) != self.instance_id:
                return
            axis = int(event.caxis.axis)
            if axis not in (AXIS_LEFTX, AXIS_LEFTY, AXIS_TRIGGERLEFT, AXIS_TRIGGERRIGHT):
                return
            self.axes[axis] = int(event.caxis.value)
            if self._axis_value_active(axis, self.axes[axis]):
                self.activity = True
            return
        if event_type not in (SDL_CONTROLLERBUTTONDOWN, SDL_CONTROLLERBUTTONUP):
            return
        if self.instance_id is not None and int(event.cbutton.which) != self.instance_id:
            return
        button = int(event.cbutton.button)
        down = event_type == SDL_CONTROLLERBUTTONDOWN
        already_down = button in self.buttons
        if down == already_down:
            return
        if down:
            self.buttons.add(button)
            self.activity = True
            if button == BUTTON_Y:
                self._y_down = True
                self._y_elapsed = 0.0
                self._y_started_ms = int(event.cbutton.timestamp)
                self._y_long = False
                return
            self._pressed.update(BUTTON_ACTIONS.get(button, ()))
        else:
            self.buttons.discard(button)
            if button == BUTTON_Y:
                duration = max(self._y_elapsed,
                               self._timestamp_delta(int(event.cbutton.timestamp)))
                if duration >= Y_TAP_LIMIT_MS:
                    if not self._y_long:
                        self._y_long = True
                        self._pressed.add("z")
                        self._y_release_pulse = True
                elif self._y_down:
                    self._pressed.add("b")
                self._y_down = False
                return

    def _timestamp_delta(self, now: int) -> float:
        if not now or not self._y_started_ms:
            return 0.0
        return float((now - self._y_started_ms) & 0xFFFFFFFF)

    def _axis_value_active(self, axis: int, value: int) -> bool:
        if axis in (AXIS_TRIGGERLEFT, AXIS_TRIGGERRIGHT):
            return value >= int(32767 * TRIGGER_DEADZONE)
        return abs(value) >= int(32767 * STICK_DEADZONE)

    @staticmethod
    def _signed_axis(value: int, negative: str, positive: str,
                     prior: set[str], enter: float, release: float) -> set[str]:
        value = max(-1.0, min(1.0, value / 32767.0))
        threshold_negative = release if negative in prior else enter
        threshold_positive = release if positive in prior else enter
        if value <= -threshold_negative:
            return {negative}
        if value >= threshold_positive:
            return {positive}
        return set()

    @staticmethod
    def _trigger_axis(value: int, action: str, prior: set[str]) -> set[str]:
        fraction = max(0.0, min(1.0, value / 32767.0))
        threshold = TRIGGER_RELEASE_ZONE if action in prior else TRIGGER_DEADZONE
        return {action} if fraction >= threshold else set()

    def sample(self, dt: float) -> tuple[set[str], set[str], bool]:
        dt = max(0.0, min(0.5, float(dt)))
        if self._y_down:
            self._y_elapsed += dt * 1000.0
            if not self._y_long and self._y_elapsed >= Y_TAP_LIMIT_MS:
                self._y_long = True
                self._pressed.add("z")

        prior = self._axis_actions
        axes = self.axes
        next_axes: set[str] = set()
        next_axes |= self._signed_axis(
            axes.get(AXIS_LEFTX, 0), "a", "d", prior, STICK_DEADZONE, STICK_RELEASE_ZONE,
        )
        next_axes |= self._signed_axis(
            axes.get(AXIS_LEFTY, 0), "w", "s", prior, STICK_DEADZONE, STICK_RELEASE_ZONE,
        )
        next_axes |= self._trigger_axis(axes.get(AXIS_TRIGGERLEFT, 0), "s", prior)
        next_axes |= self._trigger_axis(axes.get(AXIS_TRIGGERRIGHT, 0), "w", prior)
        self._pressed.update(next_axes - prior)
        self._axis_actions = next_axes

        held = set(next_axes)
        for button in self.buttons:
            if button == BUTTON_Y:
                if self._y_long:
                    held.add("z")
            else:
                held.update(BUTTON_ACTIONS.get(button, ()))
        if self._y_release_pulse:
            held.add("z")
            self._y_release_pulse = False
        pressed = set(self._pressed)
        self._pressed.clear()
        activity = self.activity or bool(next_axes) or (self._y_down and self._y_long)
        self.activity = False
        return pressed, held, activity
