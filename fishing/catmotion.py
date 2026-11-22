"""Idle life for the cat rig: breathing, blinks, ear twitches, glances, tail, weight shifts and work cycles.

actors.pose_state composes these into the parameters that drive both shaders/cat.vert
and its CPU twin actors.animate. Every function is a pure function of a clock
(seconds) and an integer per-actor seed, so a frame never depends on the frames
before it: tests, `--shots` and both renderers see the same cat at the same time.

Events (blinks, ear twitches, glances, casts, page turns) are scheduled in fixed
slots: slot k's event time comes from a hash of (seed, k, salt), so any instant
is evaluated without history and two cats with different seeds drift apart. Pip &
Pebble share one actor and so one seed: the twins breathe and blink together, by
design and because the shader's motion uniforms are one set per actor.
Angles are radians; positive head pitch is nose down, positive arm angle lowers
the paws (the shader's convention, see cat.vert).
"""

from __future__ import annotations

import math

TAU = math.tau


def hash01(seed: int, k: int, salt: int) -> float:
    """A well-mixed 0-1 float from three integers (stable across runs and platforms)."""
    h = (seed * 0x9E3779B1 ^ k * 0x85EBCA77 ^ salt * 0xC2B2AE3D) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & 0xFFFFFFFF
    h ^= h >> 12
    h = (h * 0x297A2D39) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 4294967296.0


def smooth(x: float) -> float:
    """Clamped smoothstep 0→1."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def smoother(x: float) -> float:
    """Clamped quintic smootherstep 0→1: zero velocity and acceleration at both ends."""
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (6.0 * x - 15.0) + 10.0)


def _pulse(x: float, attack: float) -> float:
    """0 at x=0, 1 at x=attack, 0 again at x=1: a quick rise and a slower ease back."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return smooth(x / attack) if x < attack else 1.0 - smooth((x - attack) / (1.0 - attack))


def _event(t: float, seed: int, salt: int, slot: float, length: float, attack: float) -> float:
    """The pulse of the one event in each `slot` seconds, `length` long, at a hashed time."""
    k = math.floor(t / slot)
    for kk in (k - 1, k):
        start = kk * slot + hash01(seed, kk, salt) * (slot - length)
        x = (t - start) / length
        if 0.0 < x < 1.0:
            return _pulse(x, attack)
    return 0.0


def blink(t: float, seed: int) -> float:
    """0 open → 1 shut. Every 3-6 s, a quarter of them doubled."""
    slot = 3.4 + 2.4 * hash01(seed, 0, 11)
    value = _event(t, seed, 12, slot, 0.17, 0.35)
    k = math.floor(t / slot)
    for kk in (k - 1, k):
        if hash01(seed, kk, 13) < 0.25:
            start = kk * slot + hash01(seed, kk, 12) * (slot - 0.17) + 0.30
            x = (t - start) / 0.17
            if 0.0 < x < 1.0:
                value = max(value, _pulse(x, 0.35))
    return value


def ear(t: float, seed: int, side: int) -> float:
    """0-1 swivel of one ear (side ±1): a flick back every 5-11 s, the two ears out of step."""
    slot = 5.0 + 6.0 * hash01(seed, side, 21)
    return _event(t, seed, 22 + side, slot, 0.42, 0.22)


# Where each pose's attention rests between glances: (yaw, pitch nose-down, roll).
INTEREST = {"sit_fish": (0.0, 0.10, 0.0), "craft": (0.0, 0.28, 0.0), "wave": (0.0, -0.04, 0.0),
            "helm": (0.0, -0.02, 0.0), "nap_curl": (0.0, 0.0, 0.0)}


def _glance_target(seed: int, k: int, pose: str) -> tuple[float, float, float]:
    home = INTEREST.get(pose, (0.0, 0.0, 0.0))
    if hash01(seed, k, 31) < 0.4:
        return home
    yaw = (hash01(seed, k, 32) - 0.5) * 1.2
    pitch = home[1] * 0.5 + (hash01(seed, k, 33) - 0.45) * 0.32
    roll = (0.16 if hash01(seed, k, 35) < 0.5 else -0.16) if hash01(seed, k, 34) < 0.2 else 0.0
    return yaw, pitch, roll


def glance(t: float, seed: int, pose: str) -> tuple[float, float, float]:
    """Head (yaw, pitch, roll) looking about: a new point of interest every 3-6 s, eased in.

    Two in five glances return to the pose's own interest (the float, the work, the
    way ahead); the rest look about the lake, one in five with a curious tilt.
    """
    slot = 3.2 + 2.8 * hash01(seed, 0, 30)
    k = math.floor(t / slot)
    turn = smoother((t - k * slot) / 0.6)
    a, b = _glance_target(seed, k - 1, pose), _glance_target(seed, k, pose)
    return tuple(x + (y - x) * turn for x, y in zip(a, b))


def breath(t: float, seed: int, pose: str) -> tuple[float, float]:
    """(torso widening fraction, chest rise m at size 1): slower and deeper when asleep."""
    sleeping = pose == "nap_curl"
    rate = (0.18 + 0.10 * hash01(seed, 0, 41)) * (0.62 if sleeping else 1.0)
    wave = math.sin(TAU * rate * t + TAU * hash01(seed, 0, 42))
    return (0.020 if sleeping else 0.013) * wave, (0.002 if sleeping else 0.004) * wave


def tail(t: float, seed: int, pose: str) -> tuple[float, float, float]:
    """(sway amplitude m at size 1, sway phase, tip curl m at size 1).

    A slow travelling sway, a second slower sway layered in, and every 6-10 s a
    flick of the tip.
    """
    amp = {"nap_curl": 0.022, "helm": 0.045, "wave": 0.07}.get(pose, 0.055)
    rate = 0.26 + 0.16 * hash01(seed, 0, 51)
    phase = TAU * rate * t + TAU * hash01(seed, 0, 52)
    amp *= 0.8 + 0.2 * math.sin(TAU * 0.07 * t + TAU * hash01(seed, 0, 53))
    flick = _event(t, seed, 54, 6.0 + 4.0 * hash01(seed, 0, 55), 0.7, 0.3)
    # Which way the tip flicks drifts slowly, so a flick never jumps sides mid-way.
    side = math.sin(TAU * t / 17.0 + TAU * hash01(seed, 0, 56))
    return amp, phase, 0.05 * flick * side


def weight(t: float, seed: int, pose: str) -> tuple[float, float]:
    """Whole-body (roll, pitch): a slow settling from haunch to haunch; still when asleep."""
    if pose == "nap_curl":
        return 0.0, 0.0
    roll = 0.020 * math.sin(TAU * t / (9.0 + 5.0 * hash01(seed, 0, 61)) + TAU * hash01(seed, 0, 62))
    pitch = 0.012 * math.sin(TAU * t / (12.0 + 5.0 * hash01(seed, 0, 63)) + TAU * hash01(seed, 0, 64))
    return roll, pitch


def _cast(t: float, seed: int) -> tuple[float, float, float]:
    """sit_fish: a cast every 14-22 s (wind up, whip, settle), a reel, then a still float with a jig."""
    period = 14.0 + 8.0 * hash01(seed, 0, 71)
    tau = (t + period * hash01(seed, 0, 72)) % period
    arm = 0.015 * math.sin(TAU * 0.3 * t)          # the rod's slow bob, under every phase
    forearm = 0.0
    head = 0.0
    if tau < 0.8:                                   # wind up: rod back over the shoulder
        arm += -0.55 * smooth(tau / 0.8)
        head = -0.12 * smooth(tau / 0.8)
    elif tau < 1.05:                                # whip forward past the rest angle
        x = smooth((tau - 0.8) / 0.25)
        arm += -0.55 + 0.77 * x
        head = -0.12 + 0.2 * x
    elif tau < 1.75:                                # settle back to rest
        x = smoother((tau - 1.05) / 0.7)
        arm += 0.22 * (1.0 - x)
        head = 0.08 * (1.0 - x)
    elif tau < 6.0:                                 # reel in: the right paw cranks
        envelope = smooth((tau - 1.75) / 0.4) * (1.0 - smooth((tau - 5.4) / 0.6))
        forearm = 0.12 * math.sin(TAU * 2.2 * (tau - 1.75)) * envelope
        arm += 0.02 * math.sin(TAU * 2.2 * (tau - 1.75)) * envelope
        head = 0.10 * envelope
    jig = period * 0.7
    if jig < tau < jig + 0.5:                       # a twitch of the rod tip
        arm -= 0.07 * _pulse((tau - jig) / 0.5, 0.3)
    return arm, forearm, head


def _craft(t: float, seed: int, prop: str) -> tuple[float, float, float]:
    """craft: each prop's own work loop. (arm, forearm, head pitch)."""
    if prop == "book":                              # read along the line, turn a page every 7-11 s
        page = _event(t, seed, 81, 7.0 + 4.0 * hash01(seed, 0, 82), 0.9, 0.4)
        return -0.04 * page, 0.5 * page, 0.04 * math.sin(TAU * 0.25 * t) - 0.08 * page
    if prop == "brush":                             # bursts of strokes at the easel
        active = smooth(math.sin(TAU * t / 6.0 + TAU * hash01(seed, 0, 83)) * 3.0)
        return 0.10 * math.sin(TAU * 0.9 * t) * active, 0.15 * math.sin(TAU * 0.9 * t + 1.0) * active, -0.08
    if prop == "whittle":                           # short strokes of the knife
        active = smooth(math.sin(TAU * t / 5.0 + TAU * hash01(seed, 0, 84)) * 3.0)
        return 0.0, 0.22 * max(0.0, math.sin(TAU * 1.4 * t)) * active, 0.06
    if prop == "mug":                               # a sip every 9-14 s
        sip = _event(t, seed, 85, 9.0 + 5.0 * hash01(seed, 0, 86), 2.6, 0.3)
        return -0.45 * min(1.0, sip * 1.6), 0.0, -0.22 * min(1.0, sip * 1.6)
    if prop == "tablet":                            # taps
        tap = _event(t, seed, 87, 1.6 + hash01(seed, 0, 88), 0.25, 0.4)
        return 0.0, 0.08 * tap, 0.02 * math.sin(TAU * 0.2 * t)
    return 0.0, 0.0, 0.0


def _helm(t: float, seed: int) -> tuple[float, float, float]:
    """helm: small corrections of the wheel, a long slow turn under them."""
    phase = TAU * hash01(seed, 0, 91)
    return 0.30 * math.sin(TAU * t / 11.0 + phase) + 0.08 * math.sin(TAU * t / 4.3 + 2 * phase), 0.0, 0.0


def work(t: float, seed: int, pose: str, prop: str) -> tuple[float, float, float]:
    """The pose's own work loop: (arm angle, right forearm angle, head pitch).

    sit_fish casts and reels, craft works its prop, helm steers, wave and
    nap_curl have none (the wave pose waves through `wave_bursts`).
    """
    if pose == "sit_fish":
        return _cast(t, seed)
    if pose == "craft":
        return _craft(t, seed, prop)
    if pose == "helm":
        return _helm(t, seed)
    return 0.0, 0.0, 0.0


def wave(t: float) -> float:
    """The waving forearm's angle about the elbow: 1.5 waves a second."""
    return 0.45 * math.sin(TAU * 1.5 * t)


def wave_bursts(t: float, seed: int) -> float:
    """0-1 waving weight for a cat whose idle pose is the wave: bursts of hellos, a lazy sway between."""
    period = 6.0 + 3.0 * hash01(seed, 0, 101)
    tau = (t + period * hash01(seed, 0, 102)) % period
    return 0.18 + 0.82 * smooth(tau / 0.4) * (1.0 - smooth((tau - 2.6) / 0.5))
