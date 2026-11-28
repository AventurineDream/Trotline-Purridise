"""The Skipper on the shared cat rig: in the boat for views off the eye, and the creator's live preview.

In first person the Skipper is a pair of paws and a reflection (skipper.py). When
the camera leaves the eye (the third-person chase camera, or a staged view such as
a whale or the prologue) the boat would be empty, so `SkipperFigure` stands the
Skipper's own rig at the helm instead: the saved look (skipperlook) in the "helm"
pose, steering with the player's input, turning its head to the cats nearby and
waving back when the boat idles within hailing range of one. Both renderers draw it
through the same actors.pose_state / cat.vert path as the 52 cats.

`preview` renders the creator's turning card on the CPU raster the portraits use
(catart), animated by the same pose_state, so what the player picks is what the
rig wears on the water.
"""

from __future__ import annotations

import json
import math

import numpy as np

from . import actors, catart, catmesh, catmotion, skipperlook
from .dialogue import HAIL_RANGE_M, HAIL_SPEED_MPS

# Measured eye-local cockpit floors for the four hand-built meshes; generated hulls
# use their authored deck height from boatfamilies.SPECS instead.
FLOOR = {"jon": -0.96, "rowboat": -0.88, "sail": -1.0, "pontoon": -0.92}


def _floor_offset(state) -> float:
    """Feet height in the eye frame, metres: measured for hand-built hulls, authored deck for generated."""
    boat_id = getattr(state, "boat_id", "")
    if boat_id in FLOOR:
        return FLOOR[boat_id]
    model = getattr(state, "boat", None)
    if model is not None:
        from .boatfamilies import SPECS
        if boat_id == "log_raft":
            # Its deck is the top face of six logs, not SPECS["log_raft"].deck.
            return float(model.half_beam / 6.0 + 0.04 - model.eye_height + 0.02)
        spec = SPECS.get(boat_id)
        if spec is not None:
            return float(spec.deck - model.eye_height + 0.02)
    return -0.95
SEED = 0.4242          # the Skipper's idle rhythm (actors seed range 0-1)
WAVE_BACK_M = HAIL_RANGE_M  # close enough to talk is close enough to wave
SHARE_M = 3.0          # cats within a few metres of the nearest share the Skipper's attention
# The jon's helm figure stands this far to port of the centreline, metres in the eye frame. The tiller's
# rod sweeps across the centreline as the motor yaws: on the centreline the figure fails the tiller bound
# at steer +1 (test_jon_outboard pins this). test_jon_outboard asserts WALL_MARGIN to the hull's walls and
# TILLER_CLEARANCE from the tiller for the helm, waving and mid-blend poses at every steer, for the default
# look only (other looks change the silhouette and are not swept). The other hulls keep the centreline.
JON_HELM_X = -0.35


class SkipperFigure:
    """The Skipper's rig in the player's boat, re-placed every frame from the boat camera.

    Holds one Actor (with its meshes) per look; a changed look in the save builds a
    new one, the old meshes going with it.
    """

    def __init__(self):
        self.actor: actors.Actor | None = None
        self._key = None

    def place(self, state, boat_cam) -> actors.Actor:
        """The Skipper's actor at the helm of `state`'s boat as `boat_cam` (the eye camera) sees it.

        The jon's figure stands JON_HELM_X to port of the centreline; other boats' figures stay on it.

        Args:
            state: The live sim state (look, boat, steer).
            boat_cam: The ordinary boat camera (`cam.boat` of a chase or staged camera).

        Returns:
            The figure's Actor, its x, y, z and yaw set for this frame.
        """
        look = skipperlook.saved(state)
        appearance = skipperlook.appearance(look, "helm")
        key = json.dumps(appearance, sort_keys=True)
        if key != self._key:
            self.actor = actors.Actor("skipper", look["name"], 0.0, 0.0, 0.0, 0.0, None, {}, [], SEED,
                                      appearance=appearance)
            self._key = key
        floor = _floor_offset(state)
        # Only the jon's figure moves off the centreline, to clear its tiller (JON_HELM_X).
        x = JON_HELM_X if getattr(state, "boat_id", "") == "jon" else 0.0
        foot = boat_cam.eye_to_world(np.array([x, floor, 0.0], np.float32))
        forward = np.asarray(boat_cam.forward, np.float32)
        actor = self.actor
        actor.x, actor.y, actor.z = (float(v) for v in foot)
        actor.yaw = math.atan2(float(forward[0]), float(forward[2]))
        return actor

    def params(self, state, reduced_motion: bool) -> dict:
        """This frame's pose_state for the placed figure: steering, a look at the cats, a wave back.

        The look target is a softmin over the cats' directions rather than the nearest cat,
        so the head turns smoothly when two cats trade places instead of snapping between them.

        Args:
            state: The live sim state (npcs, lake, speed, steer, anim).
            reduced_motion: Passed to pose_state: clock-driven motion holds still.

        Returns:
            The pose_state dict for `self.actor` (call `place` first).
        """
        actor = self.actor
        lake = getattr(state, "lake_id", None)
        near = []
        for npc in getattr(state, "npcs", ()) or ():
            anchor = npc.anchor
            if getattr(anchor, "lake_id", lake) != lake:
                continue
            dx, dz = anchor.x - actor.x, anchor.z - actor.z
            near.append((dx, dz, math.hypot(dx, dz)))
        target, distance = None, math.inf
        attention = 0.0
        if near:
            distance = min(d for _, _, d in near)
            vx = vz = 0.0
            weight_sum = 0.0
            for dx, dz, d in near:
                if d > 1e-6:
                    w = math.exp(-(d - distance) / SHARE_M)
                    vx, vz = vx + w * dx / d, vz + w * dz / d
                    weight_sum += w
            norm = math.hypot(vx, vz)
            attention = min(norm / weight_sum, 1.0) if weight_sum else 0.0
            if norm > 1e-6:
                dx, dz = vx / norm, vz / norm
            else:
                # Opposing cats cancel to the forward direction; attention fades to zero.
                dx, dz = math.sin(actor.yaw), math.cos(actor.yaw)
            reach = max(distance, 1.0)
            target = (actor.x + dx * reach, actor.z + dz * reach)
        slow = 1.0 - catmotion.smoother((abs(float(getattr(state, "speed", 0.0))) - 0.5 * HAIL_SPEED_MPS)
                                        / (0.5 * HAIL_SPEED_MPS))
        wave = (1.0 - catmotion.smoother((distance - (WAVE_BACK_M - 6.0)) / 6.0)) * slow if target else 0.0
        # The rig's arm channel also carries both upper arms, so the full steer swing would move the waving
        # shoulder toward the port wall. The swing therefore fades with the wave, squared: at blend b it is
        # steer * (1 - b)**2, pinned by test_jon_outboard with no cat, a cat 5 m ahead, and each cat distance in
        # MID_BLEND_M. At full wave the arm channel is steer-independent (idle motion still moves it), so the steer
        # swing never reaches the non-waving forearm and paw at full wave. That is intended: the wave runs only
        # while the boat is slow. The same fade damps the body roll's wheel term (0.12 * wheel), so the jon's lean
        # damps with the wave too. The rig has no wheel mesh, so the wheel itself does not freeze; at partial blend
        # the left arm and paw's steer swing is damped, not held. The first-person grip (skipper._tiller_pivot)
        # follows the raw steer and is unaffected. Third person, the left paw does not reach the grip at any steer
        # or blend, so only the first-person paw holds it. The tests cover the default look only.
        # Other boats keep the full swing.
        steer = float(getattr(state, "steer", 0.0))
        if getattr(state, "boat_id", "") == "jon":
            steer *= (1.0 - wave) ** 2
        return actors.pose_state(actor, *(target or (None, None)), float(getattr(state, "anim", 0.0)), reduced_motion,
                                 gesture=wave, steer=steer, attention=attention)


# --- The creator's preview card -------------------------------------------------

PREVIEW_FRAME = (np.array([0.0, 0.50], np.float32), 1.30)  # centre (m) and span (m): a helm cat, ears to toes
PREVIEW_PITCH = 0.12
SPIN = 0.35            # rad/s the card turns on its own (not with reduced motion)
HELLO_S = 2.4          # a wave after each change, this long


def hello(since_change: float) -> float:
    """0-1 wave weight `since_change` seconds after the player changed something."""
    s = float(since_change)
    return catmotion.smooth(s / 0.35) * (1.0 - catmotion.smooth((s - (HELLO_S - 0.6)) / 0.6))


_preview_cache: dict = {}


def preview(look: dict, clock: float, turn: float, side: int, reduced_motion: bool,
            since_change: float = 99.0) -> np.ndarray:
    """The creator's live card: the look on the real rig, animated and turning.

    Args:
        look: A Skipper look (skipperlook), normalized or a draft.
        clock: UI seconds since the creator opened: drives idle life and the spin.
        turn: Extra yaw (radians) the player turned the card by.
        side: The card's width and height in pixels.
        reduced_motion: Hold the cat still and stop the spin (turning by hand still works).
        since_change: Seconds since the last change, for the hello wave.

    Returns:
        (side, side, 3) uint8 RGB: paper, the inked cat and the portrait border.
        Frames are memoized at 20 per second, so a 60 Hz menu re-renders a third of them.
    """
    appearance = skipperlook.appearance(skipperlook.normalize({"skipper": look}), "helm")
    t = 0.0 if reduced_motion else float(clock)
    yaw = float(turn) + (0.0 if reduced_motion else SPIN * t) + 0.5
    wave = 0.0 if reduced_motion else hello(since_change)
    key = (json.dumps(appearance, sort_keys=True), int(side), bool(reduced_motion), round(t * 20.0), round(yaw * 40.0),
           round(wave * 20.0))
    if key in _preview_cache:
        return _preview_cache[key]
    actor = actors.Actor("skipper", appearance["breed"], 0.0, 0.0, 0.0, 0.0, None, {}, [], SEED,
                         appearance=appearance)
    mesh = actor.mesh(catmesh.LOD0)
    # The cat looks at the viewer as the card turns (the camera sits at (sin yaw, cos yaw)).
    params = actors.pose_state(actor, math.sin(yaw) * 3.0, math.cos(yaw) * 3.0, t, reduced_motion, gesture=wave)
    posed = actors.animate(mesh, params)
    image, covered = catart.rasterize(mesh, {}, side, side, yaw=yaw, pitch=PREVIEW_PITCH, frame=PREVIEW_FRAME,
                                      posed=posed)
    catart.ink_outline(image, covered)
    card = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    catart._border(card)
    _preview_cache.clear()  # one frame is all the menu ever needs back
    _preview_cache[key] = card
    return card
