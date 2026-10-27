"""Bot, the tin deckhand. He rides the bow until you send him out.

He does not change bite rates, prices, or the boat. B launches him toward
the nearest line, or a short way ahead, and B calls him back.
"""

from __future__ import annotations

import math

import numpy as np

from .world import Face
from . import comfort
from . import calendar
from .data import BOT_SHELLS
from .botmesh import WOOL as _COLLAR_WOOL

_PHASES = ("home", "go", "out", "back")
# Feet position in the level boat frame: starboard, up, forward of the eye.
_PERCH = {
    "jon": (0.34, -0.49, 2.24),
    "sail": (0.28, -0.45, 2.02),
    "pontoon": (0.58, -0.84, 1.48),
    "rowboat": (0.0, -0.36, 1.05),
}
_SPEED = 7.5  # metres per real second


def reset(state) -> None:
    state.bot_phase = "home"
    state.bot_x = state.bot_z = 0.0
    state.bot_yaw = 0.0
    state.bot_tx = state.bot_tz = 0.0
    state.bot_target_line_id = None


def status(state) -> str:
    return {
        "home": "BOT  aboard",
        "go": "BOT  running",
        "out": "BOT  on the line" if state.lines else "BOT  scouting",
        "back": "BOT  returning",
    }.get(state.bot_phase, "BOT  aboard")


def summon(state, world) -> str | None:
    """Launch or recall. Returns a sound name, or None."""
    if state.bot_phase in ("go", "out"):
        state.bot_phase = "back"
        state.bot_target_line_id = None
        state.toast("Bot, come on home.")
        return "bot"
    if state.bot_phase == "back":
        state.toast("Bot is already on his way.")
        return None
    target = _target(state, world)
    if target is None:
        state.toast("Bot won't run up on the bank.")
        return "error"
    fx, fz = math.sin(state.yaw), math.cos(state.yaw)
    state.bot_x = state.x + fx * 2.4
    state.bot_z = state.z + fz * 2.4
    if not _afloat(world, state.bot_x, state.bot_z):
        state.bot_x, state.bot_z = state.x, state.z
    state.bot_tx, state.bot_tz, state.bot_target_line_id = target
    state.bot_phase = "go"
    state.bot_yaw = math.atan2(target[0] - state.bot_x, target[1] - state.bot_z)
    if state.bot_hooks < 0:
        state.bot_hooks = state.hooked_total
    where = "the nearest line" if state.lines else "open water"
    state.toast(f"Bot shoves off toward {where}.")
    return "bot"


def tick(state, world, dt: float) -> str | None:
    """Move Bot. Returns a sound when he arrives or spots a bite."""
    if dt <= 0.0 or state.bot_phase == "home":
        if state.bot_hooks < 0:
            state.bot_hooks = state.hooked_total
        return None
    sound = None
    if state.hooked_total > state.bot_hooks and state.bot_phase == "out":
        state.toast("Bot: Fish on. I'm staying with it.")
        sound = "bot"
    state.bot_hooks = state.hooked_total
    if state.bot_phase == "back":
        fx, fz = math.sin(state.yaw), math.cos(state.yaw)
        state.bot_tx = state.x + fx * 2.3
        state.bot_tz = state.z + fz * 2.3
    if state.bot_phase == "out":
        ang = state.anim * 0.55
        ox = state.bot_tx + math.cos(ang) * 1.3
        oz = state.bot_tz + math.sin(ang) * 1.3
        if _afloat(world, ox, oz):
            state.bot_x, state.bot_z = ox, oz
            state.bot_yaw = ang + math.pi * 0.5
        return sound
    dist = _step(state, world, min(_SPEED * dt, 2.5))
    leash = math.hypot(state.bot_x - state.x, state.bot_z - state.z)
    if state.bot_phase == "go" and leash > 170.0 * comfort.scout_range_factor(state, calendar.weather_at(state)):
        state.bot_phase = "back"
        state.bot_target_line_id = None
        state.toast("Bot is turning around. That's far enough.")
    if dist < 0.45:
        if state.bot_phase == "back":
            reset(state)
            state.toast("Bot climbs aboard, wet and pleased.")
            return "bot"
        if state.bot_phase == "go":
            state.bot_phase = "out"
            state.bot_x, state.bot_z = state.bot_tx, state.bot_tz
            report = _report(state, world)
            state.toast(report)
            if world.zone_at(state.bot_x, state.bot_z) != "landing":
                state.narrative.record_bot_note(report)
            depth = float(world.depth(state.bot_x, state.bot_z))
            depth_class = "skinny" if depth < 2.2 else "deep" if depth > 8.0 else "middling"
            event = {
                "type": "bot.scout_complete",
                "lake_id": world.id,
                "target_line_id": state.bot_target_line_id,
                "zone_id": f"{world.id}:{world.zone_at(state.bot_x, state.bot_z)}",
                "depth_class": depth_class,
                "report_delivered": True,
                "game_minute": state.game_minutes,
            }
            if state.finder:
                event["exact_depth_m"] = depth
            state.emit_quest_event(event)
            return "bot"
    return sound


def faces(state) -> list[Face]:
    v2 = getattr(state, "v2", {})
    settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
    profile = v2.get("profile", {}) if isinstance(v2, dict) else {}
    collar = profile.get("collar", {}) if isinstance(profile, dict) else {}
    collar_visible = settings.get("collar_visible", collar.get("visible", True))
    collar_visible = collar_visible and collar.get("stage", "none") != "none"
    shell = profile.get("shell", "tin")
    shell = shell if isinstance(shell, str) and shell in BOT_SHELLS else "tin"
    pose = dict(shell=shell, stage=collar.get("stage", "none"), knot=collar.get("knot"),
                anim=float(state.anim), reduced_motion=bool(settings.get("reduced_motion", False)))
    if state.bot_phase == "home":
        eye, right, up, forward = _boat_basis(state)
        lx, ly, lz = _PERCH.get(state.boat_id, _PERCH["jon"])
        origin = eye + right * lx + up * ly + forward * lz
        # Look back at the skipper so the lamp is in view.
        return _mesh(origin, -right, up, -forward, bob=0.0,
                     collar_visible=collar_visible, **pose)
    y = 0.05 + (0.0 if pose["reduced_motion"] else math.sin(state.anim * 5.0) * 0.018)
    origin = np.array([state.bot_x, y, state.bot_z], np.float32)
    facing = np.array([math.sin(state.bot_yaw), 0.0, math.cos(state.bot_yaw)], np.float32)
    right = np.array([math.cos(state.bot_yaw), 0.0, -math.sin(state.bot_yaw)], np.float32)
    up = np.array([0.0, 1.0, 0.0], np.float32)
    mesh = _mesh(origin, right, up, facing, bob=0.0, scale=1.7,
                 collar_visible=collar_visible, scouting=True, **pose)
    try:
        from .life import extra_faces
        mesh.extend(extra_faces(state))
    except Exception:
        pass
    return mesh


def checks(world) -> None:
    """Headless: he launches, reports, returns, and the deck pose does not breathe."""
    from .sim import State

    state = State.new(world, seed=3)
    state.anim = 0.0
    home = _points(faces(state))
    state.anim = 37.0
    if not np.array_equal(home, _points(faces(state))):
        raise AssertionError("Bot moved on the deck while the boat was still")
    eye = np.array([state.x, state.boat.eye_height, state.z], np.float32)
    amber = [f for f in faces(state) if float(f.color[0]) > 0.9 and float(f.color[2]) < 0.3]
    if not amber:
        raise AssertionError("Bot has no lamp")
    center = amber[0].pts.mean(axis=0)
    if float(np.dot(amber[0].normal, eye - center)) <= 0.2:
        raise AssertionError("Bot's lamp faces away from the skipper")
    rowboat = State.new(world, seed=4)
    rowboat.boat_id = "rowboat"
    rowboat.owned_boats.append("rowboat")
    eye, _right, _up, forward = _boat_basis(rowboat)
    rowboat_points = _points(faces(rowboat)).reshape(-1, 3)
    along = (rowboat_points - eye) @ forward
    if float(along.max()) >= rowboat.boat.bow or float(along.min()) <= rowboat.boat.stern:
        raise AssertionError("Bot's rowboat perch extends beyond the hull")
    money = state.money
    sound = summon(state, world)
    if sound != "bot" or state.bot_phase != "go" or state.money != money:
        raise AssertionError("Bot did not launch cleanly")
    arrived = False
    for _ in range(40):
        state.anim += 0.5
        tick(state, world, 0.5)
        if state.bot_phase == "out":
            arrived = True
            break
    if not arrived:
        raise AssertionError("Bot never reached his scout point")
    if not any(t[0].startswith("Bot:") for t in state.toasts):
        raise AssertionError("Bot arrived without a report")
    if summon(state, world) != "bot" or state.bot_phase != "back":
        raise AssertionError("Bot ignored the recall")
    home_again = False
    for _ in range(80):
        tick(state, world, 0.5)
        if state.bot_phase == "home":
            home_again = True
            break
    if not home_again:
        raise AssertionError("Bot did not climb back aboard")
    if state.money != money:
        raise AssertionError("Bot changed the player's money")
    from pathlib import Path
    from .game import Keys, Session
    session = Session(world, Path("/tmp/briar-bot-key.json"), state, False)
    session.ui.mode = "play"
    session.tick(Keys(pressed={"b"}), 0.1)
    if state.bot_phase != "go":
        raise AssertionError("B did not send Bot")


def _points(mesh: list[Face]) -> np.ndarray:
    return np.concatenate([face.pts.reshape(-1) for face in mesh])


def _boat_basis(state):
    yaw = float(state.yaw)
    forward = np.array([math.sin(yaw), 0.0, math.cos(yaw)], np.float32)
    right = np.array([math.cos(yaw), 0.0, -math.sin(yaw)], np.float32)
    up = np.array([0.0, 1.0, 0.0], np.float32)
    eye = np.array([state.x, state.boat.eye_height, state.z], np.float32)
    return eye, right, up, forward


def _afloat(world, x: float, z: float) -> bool:
    if bool(world.slip.contains(x, z)):
        return True
    return float(world.shore_sd(x, z)) < -0.6


def _target(state, world):
    reach = comfort.scout_range_factor(state, calendar.weather_at(state))
    best = None
    best_d = 1.0e9
    for line in state.lines:
        mx = (line.x0 + line.x1) * 0.5
        mz = (line.z0 + line.z1) * 0.5
        dist = math.hypot(mx - state.x, mz - state.z)
        if dist < best_d and dist < 140.0 * reach and _afloat(world, mx, mz):
            best = (mx, mz, line.line_id)
            best_d = dist
    if best is not None:
        return best
    fx, fz = math.sin(state.yaw), math.cos(state.yaw)
    for dist in (18.0 * reach, 12.0 * reach, 8.0 * reach, 5.0):
        x = state.x + fx * dist
        z = state.z + fz * dist
        if _afloat(world, x, z):
            return (x, z, None)
    return None


def _step(state, world, step: float) -> float:
    dx = state.bot_tx - state.bot_x
    dz = state.bot_tz - state.bot_z
    dist = math.hypot(dx, dz)
    if dist < 1.0e-4:
        return 0.0
    ux, uz = dx / dist, dz / dist
    move = min(step, dist)
    if _try(state, world, ux * move, uz * move):
        state.bot_yaw = math.atan2(ux, uz)
        return dist - move
    # The straight line crosses the bank. Sidestep and keep looking for water.
    for sign in (1.0, -1.0):
        if _try(state, world, -uz * sign * move, ux * sign * move):
            state.bot_yaw = math.atan2(-uz * sign, ux * sign)
            return dist
    return dist


def _try(state, world, dx: float, dz: float) -> bool:
    x = state.bot_x + dx
    z = state.bot_z + dz
    if not _afloat(world, x, z):
        return False
    state.bot_x, state.bot_z = x, z
    return True


def _report(state, world) -> str:
    from .data import BAIT_BY_ID, SPECIES_BY_ID, hour_of_day
    from .sim import species_rates
    from .world import zone_label

    x, z = float(state.bot_x), float(state.bot_z)
    zone = world.zone_at(x, z)
    if zone == "landing":
        return "Bot: The landing. Too close to set a line."
    depth = float(world.depth(x, z))
    if state.finder:
        where = f"{depth * 3.28084:.0f} ft"
    elif depth < 2.2:
        where = "skinny water"
    elif depth > 8.0:
        where = "deep water"
    else:
        where = "middling water"
    hour = hour_of_day(state.game_minutes)
    weather = calendar.weather_at(state)
    best_bait, best_sp, best = "worm", "bluegill", -1.0
    likelihood = {}
    for bait in BAIT_BY_ID:
        rates = species_rates(zone, bait, hour, weather, depth, state.lake_id, game_minutes=state.game_minutes)
        for sid, rate in rates.items():
            likelihood[sid] = max(likelihood.get(sid, 0), rate)
        sp = max(rates, key=rates.get)
        if rates[sp] > best:
            best, best_bait, best_sp = rates[sp], bait, sp
    place = zone_label(zone).lower()
    if best < 0.004:
        return f"Bot: {where}, the {place}. Quiet for a trotline."
    bait = BAIT_BY_ID[best_bait].name.lower()
    fish = SPECIES_BY_ID[best_sp].name.lower()
    report = f"Bot: {where}, the {place}. {bait.capitalize()} for {fish}."
    if comfort.has_buff(state, "scout_species"):
        best_two = sorted((sid for sid in likelihood if likelihood[sid] > 0),
                          key=lambda sid: (-likelihood[sid], sid))[:2]
        names = ' and '.join(SPECIES_BY_ID[sid].name.lower() for sid in best_two)
        report += f" Likeliest here: {names}."
    return report


def _mesh(origin, right, up, facing, bob: float, scale: float = 1.0,
          collar_visible: bool = True, **pose) -> list[Face]:
    from .botmesh import faces as shell_faces
    origin = np.asarray(origin, np.float32) + np.array((0., bob, 0.), np.float32)
    return shell_faces(origin, right, up, facing, scale=scale,
                       collar_visible=collar_visible, **pose)


def sound_kind(state, kind):
    """Keep the scouting API's legacy 'bot' cue; resolve its shell at playback."""
    if kind != "bot":
        return kind
    profile = getattr(state, "v2", {}).get("profile", {})
    shell = profile.get("shell", "tin") if isinstance(profile, dict) else "tin"
    return BOT_SHELLS.get(shell, BOT_SHELLS["tin"]).chime if isinstance(shell, str) else BOT_SHELLS["tin"].chime


def chime_caption(state):
    profile = getattr(state, "v2", {}).get("profile")
    if not isinstance(profile, dict):
        return "Bot's chime sounds."
    shell = profile.get("shell", "tin")
    return BOT_SHELLS.get(shell, BOT_SHELLS["tin"]).caption if isinstance(shell, str) else BOT_SHELLS["tin"].caption
