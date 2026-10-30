"""V1-35 story staging: the camera, fades and light of the story's scenes (05 §1–3).

A staged scene plays its keyframes on a clock that starts with its first bubble. Each key
sets a view, a fade to black, a letterbox and, where the script asks, the light: the fog
lifting off Crater's marker, or the dawn the credits roll over. Between keys every value
eases; a view of None is the Skipper's own. When the clock passes the last key the staging
is over and the Skipper's view returns, except for the credits, which hold their last key.

The staging only changes what is drawn. The scene's bubbles, choices and effects are the
story's (`story.py`), and no frame of it is needed to finish a scene.

- Reduced motion keeps the fades and the letterbox, but never moves the camera: each scene
  holds its last framing throughout, and the credits stand still.
- A scene replayed after a reload can be skipped: Esc (B) jumps to its last frame.
- A scene read before its staging is done lets the rest play out four times faster, so the
  view and the light return without a cut.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .lakes import place


@dataclass(frozen=True)
class Key:
    t: float                          # seconds into the staging
    view: tuple | None = None         # (back, up, side, yaw, pitch) about the anchor; None is the Skipper's
    fade: float = 0.0                 # black over the frame, 0..1
    bars: float = 0.0                 # letterbox, 0..1
    mist: float | None = None         # the visual mist, overriding the weather's
    hour: float | None = None         # the light's hour of day, overriding the clock's
    whale: float | None = None        # how far the Star-Whale has risen (`finale.py`), 0..1
    sketch: float | None = None       # how much of the Skipper's drawing is on the page, 0..1


@dataclass(frozen=True)
class Stage:
    anchor: str                       # "boat", or "toward:<lake:waypoint>" (the boat, facing it)
    keys: tuple
    hold: bool = False                # keep the last key once the clock passes it (the credits)

    @property
    def duration(self) -> float:
        return self.keys[-1].t


EYE = 1.22  # the Skipper's eye over the water, as the boat camera stands

STAGES = {
    # 05 §1: fade in on still water at dawn, the Skipper's paws on a tiller; the jon boat bumps
    # the dock. The view starts on the water at the bow, lifts, and the bump dips it once.
    "pro_01": Stage("boat", (
        Key(0.0, (0.0, EYE, 0.0, 0.0, -0.42), fade=1.0, bars=1.0),
        Key(2.4, (0.0, EYE, 0.0, 0.0, -0.30), fade=0.0, bars=1.0),
        Key(3.2, (0.0, EYE, 0.0, 0.0, -0.10), bars=1.0),
        Key(3.45, (0.0, EYE - 0.06, 0.0, 0.02, -0.16), bars=0.8),   # the bump
        Key(4.4, None, bars=0.0),
    )),
    # 05 §2.4: the fog lifts off the survey marker. The view turns to it while the mist thins.
    "story_c4_clear": Stage("toward:crater:survey_marker", (
        Key(0.0, (0.0, EYE, 0.0, 0.0, 0.0), bars=1.0, mist=1.0),
        Key(1.5, (0.0, EYE, 0.0, 0.0, 0.03), bars=1.0, mist=0.85),
        Key(5.5, (0.0, EYE, 0.0, 0.0, 0.06), bars=1.0, mist=0.0),
        Key(7.0, None, bars=0.0, mist=0.0),
    )),
    # 05 §3: the ending at the landing, framed wide while the radio carries the hosts.
    "end_01": Stage("boat", (
        Key(0.0, None, bars=0.0),
        Key(2.0, (2.5, 1.9, 0.8, -0.18, -0.10), bars=1.0),
        Key(12.0, (1.6, 1.7, 0.5, -0.12, -0.08), bars=1.0),
    ), hold=True),
    # 05 §2.5: the Star-Whale rises out of the deep glow ahead, and the view lifts with it. It
    # holds, risen, until the Skipper draws it.
    "story_c5_whale": Stage("boat", (
        Key(0.0, (0.0, EYE, 0.0, 0.0, -0.06), bars=1.0, whale=0.0),
        Key(2.0, (0.0, EYE, 0.0, 0.0, -0.04), bars=1.0, whale=0.12),
        Key(6.5, (0.0, EYE - 0.1, 0.0, 0.0, 0.10), bars=1.0, whale=0.85),
        Key(9.0, (0.0, EYE - 0.1, 0.0, 0.0, 0.07), bars=1.0, whale=1.0),
    ), hold=True),
    # "Draw it": the drawing appears stroke by stroke while the whale floats; then it sinks
    # unhurried, after the Skipper is free to sail again.
    "story_c5_drawn": Stage("boat", (
        Key(0.0, None, bars=1.0, whale=1.0, sketch=0.0),
        Key(3.0, None, bars=1.0, whale=1.0, sketch=1.0),
        Key(24.0, None, bars=0.0, whale=1.0, sketch=1.0),
        Key(30.0, None, bars=0.0, whale=0.0, sketch=1.0),
    )),
    # The credits roll over the boat at dawn (05 §3): a slow pull back and up.
    "credits": Stage("boat", (
        Key(0.0, (5.0, 2.6, 0.0, 0.0, -0.18), fade=1.0, bars=1.0, hour=6.4),
        Key(1.6, (5.6, 2.9, 0.4, -0.04, -0.20), fade=0.0, bars=1.0, hour=6.4),
        Key(24.0, (12.0, 6.0, 3.0, -0.26, -0.30), bars=1.0, hour=6.6),
    ), hold=True),
}
# The ending's later scenes keep its framing; their stage is the one they continue.
CONTINUES = {"end_01b": "end_01", "end_02": "end_01", "end_03": "end_01"}
CREDITS_SPEED = 26.0  # pixels a second the credits rise at 720 lines, before Reduced Motion
RELEASE = 4.0  # how much faster a staging plays out once its scene has been read


@dataclass
class Clock:
    """A staging under way: which stage, how far in, and whether it replays a saved scene."""
    stage_id: str
    t: float = 0.0
    repeat: bool = False

    @property
    def stage(self) -> Stage:
        return STAGES[self.stage_id]

    @property
    def over(self) -> bool:
        return not self.stage.hold and self.t >= self.stage.duration


def stage_of(scene_id: str | None) -> str | None:
    """The stage a scene plays under, if it is staged."""
    if scene_id is None:
        return None
    scene_id = CONTINUES.get(scene_id, scene_id)
    return scene_id if scene_id in STAGES else None


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _span(stage: Stage, t: float) -> tuple[Key, Key, float]:
    keys = stage.keys
    if t <= keys[0].t:
        return keys[0], keys[0], 0.0
    for a, b in zip(keys, keys[1:]):
        if t <= b.t:
            return a, b, _smooth((t - a.t) / (b.t - a.t))
    return keys[-1], keys[-1], 0.0


def _mix(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def sample(clock: Clock | None, *, reduced: bool = False) -> dict | None:
    """The fade, letterbox and light overrides at this moment, or None when nothing is staged."""
    if clock is None or clock.over:
        return None
    a, b, k = _span(clock.stage, clock.t)
    out = {"fade": _mix(a.fade, b.fade, k), "bars": _mix(a.bars, b.bars, k)}
    for name in ("mist", "hour", "whale", "sketch"):
        va, vb = getattr(a, name), getattr(b, name)
        if va is not None or vb is not None:
            out[name] = _mix(va if va is not None else vb, vb if vb is not None else va, k)
    if reduced:
        last = clock.stage.keys[-1]
        for name in ("mist", "hour"):  # the light settles at once; nothing drifts
            if getattr(last, name) is not None:
                out[name] = getattr(last, name)
        for name in ("whale", "sketch"):  # the whale is simply there, and the drawing complete
            values = [getattr(key, name) for key in clock.stage.keys if getattr(key, name) is not None]
            if values:
                out[name] = max(values)
    return out


def light_overrides(clock: Clock | None, *, reduced: bool = False) -> dict | None:
    """What the renderers draw differently: `weather.lighting_at`'s mist and hour, and the
    Star-Whale (`finale.faces`)."""
    values = sample(clock, reduced=reduced)
    if not values:
        return None
    light = {name: values[name] for name in ("mist", "hour", "whale") if name in values}
    return light or None


def _anchor(stage: Stage, state) -> tuple[float, float, float]:
    """(x, z, yaw) the stage's views are measured from."""
    if stage.anchor.startswith("toward:"):
        found = place(stage.anchor.split(":", 1)[1])
        if found is not None:
            row = found[1]
            return state.x, state.z, math.atan2(row["x"] - state.x, row["z"] - state.z)
    return state.x, state.z, state.yaw


def _pose(view: tuple, anchor: tuple, eye: float) -> tuple[float, float, float, float, float]:
    back, up, side, yaw, pitch = view
    x, z, heading = anchor
    fx, fz = math.sin(heading), math.cos(heading)   # yaw 0 looks north (+z), as the camera does
    rx, rz = math.cos(heading), -math.sin(heading)
    # Heights are given for the jon boat's eye; another boat's eye moves the view with it.
    return (x - fx * back + rx * side, eye + up - EYE, z - fz * back + rz * side, heading + yaw, pitch)


def _lerp_angle(a: float, b: float, k: float) -> float:
    d = (b - a + math.pi) % math.tau - math.pi
    return a + d * k


def camera_pose(clock: Clock | None, state, own: tuple, *, reduced: bool = False):
    """The staged (x, eye, z, yaw, pitch), given the Skipper's own pose; None when unstaged."""
    if clock is None or clock.over:
        return None
    stage = clock.stage
    anchor = _anchor(stage, state)

    def pose(key: Key):
        return own if key.view is None else _pose(key.view, anchor, own[1])

    if reduced:
        last = stage.keys[-1]
        return None if last.view is None else pose(last)
    a, b, k = _span(stage, clock.t)
    pa, pb = pose(a), pose(b)
    if pa is own and pb is own:
        return None
    return (_mix(pa[0], pb[0], k), _mix(pa[1], pb[1], k), _mix(pa[2], pb[2], k),
            _lerp_angle(pa[3], pb[3], k), _mix(pa[4], pb[4], k))


def staged_camera(renderer, state, clock: Clock | None, *, reduced: bool = False):
    """The renderer's camera for this moment of the staging: the Skipper's own when unstaged."""
    own = renderer.camera_for(state)
    pose = camera_pose(clock, state, (own.x, own.y, own.z, own.yaw, own.pitch), reduced=reduced)
    if pose is None:
        return own
    from .camera import Camera
    staged = Camera(*pose, own.roll, own.fov_x, own.w, own.h, build_rays=own.build_rays)
    staged.boat = own  # the boat and the Skipper's paws stay where they float
    return staged


def credits_rise(clock: Clock | None, *, reduced: bool = False) -> float:
    """How far the credits have risen from below the frame, in 720-line pixels. They roll up
    over the dawn and come to rest; under Reduced Motion, or with no roll, they stand at rest."""
    if clock is None or clock.stage_id != "credits" or reduced:
        return math.inf
    return clock.t * CREDITS_SPEED


def overlay(frame, values: dict | None) -> None:
    """Fade the frame toward black and draw the letterbox, in place."""
    if not values:
        return
    import numpy as np
    h = frame.shape[0]
    fade = min(1.0, max(0.0, values.get("fade", 0.0)))
    if fade > 0.0:
        frame[:] = (frame.astype(np.float32) * (1.0 - fade)).astype(frame.dtype)
    bar = int(round(h * 0.11 * min(1.0, max(0.0, values.get("bars", 0.0)))))
    if bar > 0:
        frame[:bar] = 0
        frame[h - bar:] = 0
