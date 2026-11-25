"""Mouse look: pointer travel turns the gameplay view, and the turn settles back to centre.

Platform.poll reports each frame's pointer travel as a fraction of the window width
(Input.mouse_delta), so a sweep across the window turns the view the same at any size. Session keeps the
turn as a yaw and pitch offset in radians. That offset is runtime state and is never saved.
These helpers hold the arithmetic, away from SDL and the renderers, so the tests can pin
gain, clamps and recentring exactly.

Constraints: the cursor stays visible and free (no relative mouse mode), so HUD and menu
clicks are unaffected. A turn never passes the keyboard look's pitch bounds or YAW_LIMIT.
"""
import math

LEVELS = ("off", "gentle", "normal", "quick")
DEFAULT_LEVEL = "normal"
LABELS = {"off": "Off", "gentle": "Gentle", "normal": "Normal", "quick": "Quick"}
# Radians of view turn for one full window width of pointer travel. A sweep across the
# window turns the view about 46, 75 or 115 degrees at Gentle, Normal and Quick.
GAIN = {"off": 0.0, "gentle": 0.8, "normal": 1.3, "quick": 2.0}
# Yaw may swing this far either side of the heading, in radians.
YAW_LIMIT = math.radians(70.0)
# The keyboard look's pitch bounds on state.look, in radians. game._simulate clamps to these
# too. Mouse look stays inside them so the two controls never add up past the limit.
KEY_LOOK_MIN, KEY_LOOK_MAX = -0.45, 0.62
# Seconds without pointer motion before the turn starts to ease back.
REST_S = 1.2
# Time constant of the ease back to centre, in seconds.
TAU_S = 0.6
# Components below this, in radians (0.06 degrees), snap to zero so the ease finishes
# rather than trailing off forever.
SNAP_RAD = 1e-3


def level(settings: dict) -> str:
    """The saved Mouse look level, or the default when the setting is missing or unknown.

    Args:
        settings: The v2 settings dict. Only its "mouse_look" entry is read.

    Returns:
        One of LEVELS.
    """
    value = settings.get("mouse_look") if isinstance(settings, dict) else None
    return value if value in LEVELS else DEFAULT_LEVEL


def gain(name: str) -> float:
    """Radians of view turn per full window width of pointer travel for a level.

    Args:
        name: A level from LEVELS.

    Returns:
        The gain in radians per window width. 0.0 means mouse look is off.
    """
    return GAIN[name]


def label(name: str) -> str:
    """The Settings row text for a level.

    Args:
        name: A level from LEVELS.

    Returns:
        The capitalised label, such as "Normal".
    """
    return LABELS[name]


def cycle(name: str, step: int) -> str:
    """The level a number of places along LEVELS from `name`, wrapping at either end.

    Args:
        name: A level from LEVELS.
        step: Places to move; -1 for the − button, +1 for the + button.

    Returns:
        The level reached. Wrapping matches the other cycling Settings rows.
    """
    return LEVELS[(LEVELS.index(name) + step) % len(LEVELS)]


def clamp(yaw: float, pitch: float, key_look: float) -> tuple[float, float]:
    """Keep a turn inside the view limits.

    Args:
        yaw: Turn to the right, in radians. Positive turns east.
        pitch: Turn upward, in radians. Positive looks up.
        key_look: The keyboard look already applied, state.look, in radians.

    Returns:
        (yaw, pitch) with |yaw| <= YAW_LIMIT, and key_look + pitch inside
        [KEY_LOOK_MIN, KEY_LOOK_MAX].
    """
    yaw = min(max(yaw, -YAW_LIMIT), YAW_LIMIT)
    pitch = min(max(pitch, KEY_LOOK_MIN - key_look), KEY_LOOK_MAX - key_look)
    return yaw, pitch


def turn(yaw: float, pitch: float, dx: float, dy: float, gain_rad: float,
         key_look: float) -> tuple[float, float]:
    """Add one frame's pointer travel to the turn, then clamp it.

    Args:
        yaw: Current turn to the right, in radians.
        pitch: Current upward turn, in radians.
        dx: Pointer travel to the right this frame, as a fraction of the window width.
        dy: Pointer travel down this frame, as a fraction of the window width. Screen
            space, so moving up gives a negative dy.
        gain_rad: Radians per window width, from gain().
        key_look: The keyboard look already applied, state.look, in radians.

    Returns:
        The new (yaw, pitch). Moving the pointer right turns right, and moving it up looks up.
    """
    return clamp(yaw + dx * gain_rad, pitch - dy * gain_rad, key_look)


def settle(yaw: float, pitch: float, dt: float, *, snap: bool = False) -> tuple[float, float]:
    """Ease the turn back toward centre for one frame.

    Args:
        yaw: Current turn to the right, in radians.
        pitch: Current upward turn, in radians.
        dt: Real seconds elapsed this frame. Negative values count as zero.
        snap: Jump straight to centre instead of easing. Reduced motion uses this.

    Returns:
        The decayed (yaw, pitch). Each decays by exp(-dt / TAU_S), and a component below
        SNAP_RAD becomes zero.
    """
    if snap:
        return 0.0, 0.0
    keep = math.exp(-max(dt, 0.0) / TAU_S)
    yaw, pitch = yaw * keep, pitch * keep
    return (0.0 if abs(yaw) < SNAP_RAD else yaw), (0.0 if abs(pitch) < SNAP_RAD else pitch)
