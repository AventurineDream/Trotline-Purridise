"""SDL controllers and keyboard actions; pointer/viewport metadata stays in UI pixels."""

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
    "tow": "r", "engine": "v", "new_game": "n", "dialogue_continue": "c",
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
    "tow": "r", "engine": "v", "new_game": "n", "dialogue_continue": "c",
    "catnap": "z", "bot_tool": "g", "galley": "k",
    "menu_up": "up", "menu_down": "down", "menu_left": "left",
    "menu_right": "right",
    "select": "return", "alternate_select": "space", "cancel": "esc",
}

# These actions share the same canonical game key in different contexts. Keep
# their physical bindings aligned so rebinding one context cannot leave its
# old key active through another alias.
ACTION_ALIASES = (
    ("hail", "dialogue_continue"),
    ("pause", "cancel"),
    ("anchor", "alternate_select"),
)

KEY_NAMES = frozenset({
    *"abcdefghijklmnopqrstuvwxyz", *"0123456789",
    "return", "esc", "tab", "space", "right", "left", "down", "up",
    "shift", "rshift",
    "minus", "equals", "left_bracket", "right_bracket", "backslash",
    "semicolon", "apostrophe", "grave", "comma", "period", "slash",
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
        # Prefer an alias whose saved value differs from its default. This
        # handles existing full settings maps where a user changed only one
        # member of a context-shared action pair. If conflicting non-default
        # values are present, the stable alias order above wins.
        for aliases in ACTION_ALIASES:
            changed = [action for action in aliases
                       if bindings[action] != DEFAULT_KEY_BINDINGS[action]]
            key = bindings[changed[0] if changed else aliases[0]]
            for action in aliases:
                bindings[action] = key
    return bindings


def normalize_key_bindings(saved=None) -> dict[str, str]:
    """Return validated bindings with context-shared actions reconciled."""
    return _bindings(saved)


def _action_groups():
    grouped = {action for aliases in ACTION_ALIASES for action in aliases}
    return (*ACTION_ALIASES,
            *((action,) for action in ACTION_SYMBOLS if action not in grouped))


def set_key_binding(saved, action: str, key: str) -> dict[str, str]:
    """Return normalized bindings, swapping any existing use of the new key."""
    if action not in ACTION_SYMBOLS:
        raise KeyError(action)
    if key not in KEY_NAMES:
        raise ValueError(f"Unsupported key: {key}")
    bindings = _bindings(saved)
    aliases = next((group for group in ACTION_ALIASES if action in group), (action,))
    old_key = bindings[action]
    if key != old_key:
        for group in _action_groups():
            if group == aliases or bindings[group[0]] != key:
                continue
            for member in group:
                bindings[member] = old_key
            break
    for alias in aliases:
        bindings[alias] = key
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
    # Number keys remain the bait shortcuts unless the player deliberately
    # assigns one to an action.
    bound = set(bindings.values())
    for key in "123456789":
        if key in pressed and key not in bound:
            translated_pressed.add(key)
        if key in held and key not in bound:
            translated_held.add(key)
    return translated_pressed, translated_held


def session_input(keys, saved_bindings, repeat_state: dict[str, float]):
    """Translate keyboard actions while preserving physical and pointer metadata.

    Args:
        keys: Physical input; pointer coordinates and viewport are UI pixels.
        saved_bindings: Saved physical-key bindings keyed by canonical action.
        repeat_state: Mutable action-repeat timers in seconds, shared across ticks.
    Returns:
        Action input retaining the source's pointer position/motion, click/wheel,
        focus, resize edge, and viewport. Inputs without physical key sets pass
        through unchanged.
    Side effects:
        Expires repeat timers for released actions; does not consume input edges.
    """
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
    physical_keyboard_pressed = set(keyboard_pressed_source)
    physical_keyboard_held = set(keyboard_held_source)
    physical_keyboard_press_order = list(getattr(keys, "keyboard_press_order", ()))
    pressed = keyboard_pressed | gamepad_pressed_source
    held = keyboard_held | gamepad_held_source
    # A menu may stop asking about a direction while another screen is open.
    # Expire its repeat timer from the complete current held set every tick,
    # rather than waiting for a later tap() call to notice the release.
    for name in repeat_state.keys() - held:
        repeat_state.pop(name, None)

    class ActionInput:
        """One translated frame with unchanged pointer, focus, and geometry units."""

        def __init__(self):
            """Capture this frame's translated keys and physical input metadata."""
            self.pressed = pressed
            self.held = held
            self.quit = keys.quit
            self.focused = keys.focused
            self.device = keys.device
            self.mouse_pos = getattr(keys, "mouse_pos", None)
            self.mouse_moved = getattr(keys, "mouse_moved", False)
            self.mouse_delta = getattr(keys, "mouse_delta", (0.0, 0.0))
            self.mouse_click = getattr(keys, "mouse_click", None)
            self.mouse_wheel = getattr(keys, "mouse_wheel", 0)
            self.viewport = getattr(keys, "viewport", (1280, 720))
            self.resized = getattr(keys, "resized", False)
            self.keyboard_pressed = keyboard_pressed
            self.keyboard_held = keyboard_held
            self.physical_keyboard_pressed = physical_keyboard_pressed
            self.physical_keyboard_held = physical_keyboard_held
            self.physical_keyboard_press_order = physical_keyboard_press_order
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
        self._axis_actions: dict[int, set[str]] = {}
        self._pressed: set[str] = set()
        self._y_down = False
        self._y_elapsed = 0.0
        self._y_started_ms = 0
        self._y_long = False
        self._y_release_pulse = False
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
        self._axis_actions.clear()
        self._pressed.clear()
        self._y_down = False
        self._y_elapsed = 0.0
        self._y_started_ms = 0
        self._y_long = False
        self._y_release_pulse = False

    def handle_event(self, event) -> bool:
        """Apply one SDL event and report whether it was controller activity."""
        event_type = int(event.type)
        if event_type == SDL_CONTROLLERDEVICEADDED:
            self._open(int(event.cdevice.which))
            return False
        if event_type == SDL_CONTROLLERDEVICEREMOVED:
            removed = int(event.cdevice.which)
            if self.instance_id is None or removed == self.instance_id:
                self._close()
                self._open_existing()
            return False
        if event_type == SDL_CONTROLLERDEVICEREMAPPED:
            return False
        if event_type == SDL_CONTROLLERAXISMOTION:
            if self.instance_id is not None and int(event.caxis.which) != self.instance_id:
                return False
            axis = int(event.caxis.axis)
            if axis not in (AXIS_LEFTX, AXIS_LEFTY, AXIS_TRIGGERLEFT, AXIS_TRIGGERRIGHT):
                return False
            value = int(event.caxis.value)
            before = (
                set().union(*self._axis_actions.values())
                if self._axis_actions else set()
            )
            actions = self._actions_for_axis(
                axis, value, self._axis_actions.get(axis, set()),
            )
            if actions:
                self._axis_actions[axis] = actions
            else:
                self._axis_actions.pop(axis, None)
            after = (
                set().union(*self._axis_actions.values())
                if self._axis_actions else set()
            )
            # Capture an action edge even if another axis event returns to
            # neutral before the next poll samples the controller.
            self._pressed.update(after - before)
            active = bool(actions) or self._axis_value_active(axis, value)
            return active
        if event_type not in (SDL_CONTROLLERBUTTONDOWN, SDL_CONTROLLERBUTTONUP):
            return False
        if self.instance_id is not None and int(event.cbutton.which) != self.instance_id:
            return False
        button = int(event.cbutton.button)
        down = event_type == SDL_CONTROLLERBUTTONDOWN
        already_down = button in self.buttons
        if down == already_down:
            return False
        if down:
            self.buttons.add(button)
            if button == BUTTON_Y:
                self._y_down = True
                self._y_elapsed = 0.0
                self._y_started_ms = int(event.cbutton.timestamp)
                self._y_long = False
                return True
            self._pressed.update(BUTTON_ACTIONS.get(button, ()))
            return True
        else:
            self.buttons.discard(button)
            if button == BUTTON_Y:
                duration = max(self._y_elapsed,
                               self._timestamp_delta(int(event.cbutton.timestamp)))
                action_generated = False
                if duration >= Y_TAP_LIMIT_MS:
                    if not self._y_long:
                        self._y_long = True
                        self._pressed.add("z")
                        self._y_release_pulse = True
                        action_generated = True
                elif self._y_down:
                    self._pressed.add("b")
                    action_generated = True
                self._y_down = False
                return action_generated
            return False

    def _timestamp_delta(self, now: int) -> float:
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

    def _actions_for_axis(self, axis: int, value: int, prior: set[str]) -> set[str]:
        if axis == AXIS_LEFTX:
            return self._signed_axis(
                value, "a", "d", prior, STICK_DEADZONE, STICK_RELEASE_ZONE,
            )
        if axis == AXIS_LEFTY:
            return self._signed_axis(
                value, "w", "s", prior, STICK_DEADZONE, STICK_RELEASE_ZONE,
            )
        if axis == AXIS_TRIGGERLEFT:
            return self._trigger_axis(value, "s", prior)
        if axis == AXIS_TRIGGERRIGHT:
            return self._trigger_axis(value, "w", prior)
        return set()

    def sample(self, dt: float, now_ms: int | None = None) -> tuple[set[str], set[str], bool]:
        # Keep dt for API compatibility; the Y hold uses SDL's event clock.
        activity = False
        if self._y_down:
            if now_ms is None:
                now_ms = int(self.sdl.SDL_GetTicks64())
            self._y_elapsed = max(
                self._y_elapsed,
                self._timestamp_delta(int(now_ms) & 0xFFFFFFFF),
            )
            if not self._y_long and self._y_elapsed >= Y_TAP_LIMIT_MS:
                self._y_long = True
                self._pressed.add("z")
                activity = True

        next_axes = (set().union(*self._axis_actions.values())
                     if self._axis_actions else set())

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
        # Only report activity synthesized during sampling. Physical events
        # are handled in poll order so they cannot override a later keyboard
        # event from the same queue drain.
        return pressed, held, activity
