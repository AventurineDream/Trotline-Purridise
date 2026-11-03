"""Legendary system: requirement evaluation, watch cards, guaranteed hooks and records (V1-36)."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Any

from . import bottools, calendar, lakes
from .book import LEGENDARY_IDS, LEGENDARY_STORIES, legendary_page
from .data import band_of, hour_of_day
from .fleet import chapter_finished
from .quests import quest_status

if TYPE_CHECKING:
    from .sim import Catch, SetLine, State

LAKE_NAMES = {
    "briar": "Little Briar",
    "cedar": "Cedar Creek",
    "flathead": "Flathead Alpine Lake",
    "crater": "Crater Caldera",
    "nebula": "Starlight Nebula Lagoon",
}

LEGENDARY_DATA: dict[str, dict[str, Any]] = {
    "old_lantern": {
        "id": "old_lantern",
        "name": "Old Lantern",
        "lake": "briar",
        "kind": "caught",
        "weight_lb": 38.0,
        "teller": "Grandmother Whiskers",
        "teller_location": "Briar Landing",
        "area_id": "briar:landing_edge",
        "start_hour": 20,
        "end_hour": 24,
        "weathers": (),
        "bait": "lantern_liver",
        "gate_type": "spotlight",
        "gate_desc": "Bow spotlight owned and on",
    },
    "lily_queen": {
        "id": "lily_queen",
        "name": "The Lily Queen",
        "lake": "briar",
        "kind": "caught",
        "weight_lb": 14.0,
        "teller": "Willow",
        "teller_location": "Little Briar",
        "zones": ("lilies", "reeds"),
        "start_hour": 5,
        "end_hour": 8,
        "weathers": ("mist", "drizzle"),
        "bait": "queens_breakfast",
        "gate_type": "chapter",
        "gate_value": 1,
        "gate_desc": "Chapter 1 complete",
    },
    "spillway_monster": {
        "id": "spillway_monster",
        "name": "The Spillway Monster",
        "lake": "cedar",
        "kind": "caught",
        "weight_lb": 95.0,
        "teller": "Doc Barnaby",
        "teller_location": "Cedar Creek",
        "area_id": "cedar:marked_pool",
        "start_hour": 20,
        "end_hour": 4,
        "weathers": (),
        "bait": "shad",
        "gate_type": "heavy_line",
        "gate_desc": "Heavy line only (day-one exception)",
    },
    "channel_leviathan": {
        "id": "channel_leviathan",
        "name": "The Channel Leviathan",
        "lake": "cedar",
        "kind": "caught",
        "weight_lb": 120.0,
        "teller": "Hank Mudpaw",
        "teller_location": "Cedar Creek",
        "zones": ("inlet",),
        "start_hour": 22,
        "end_hour": 2,
        "weathers": (),
        "recent_rain": True,
        "bait": "pecan_smoked_shad",
        "gate_type": "chapter",
        "gate_value": 2,
        "gate_desc": "Chapter 2 complete",
    },
    "whiskered_guardian": {
        "id": "whiskered_guardian",
        "name": "The Whiskered Guardian",
        "lake": "cedar",
        "kind": "witnessed",
        "weight_lb": None,
        "teller": "Quill",
        "teller_location": "Cedar Creek",
        "zones": ("deep",),
        "start_hour": 18,
        "end_hour": 20,
        "weathers": (),
        "bait": None,
        "gate_type": "ripples",
        "gate_value": 8,
        "gate_desc": "Any 8 of 10 V3 Ripples",
    },
    "glacial_phantom": {
        "id": "glacial_phantom",
        "name": "The Glacial Phantom",
        "lake": "flathead",
        "kind": "caught",
        "weight_lb": 22.0,
        "teller": "Freya",
        "teller_location": "Flathead Alpine Lake",
        "zones": ("inlet",),
        "start_hour": 5,
        "end_hour": 9,
        "weathers": ("snow_mist",),
        "bait": "phantom_roe",
        "gate_type": "cold_band",
        "gate_desc": "Line in the cold band",
    },
    "old_silverhead": {
        "id": "old_silverhead",
        "name": "Old Silverhead",
        "lake": "flathead",
        "kind": "caught",
        "weight_lb": 60.0,
        "teller": "Torvald",
        "teller_location": "Flathead Alpine Lake",
        "zones": ("deep",),
        "start_hour": 3,
        "end_hour": 7,
        "weathers": ("clear",),
        "bait": "huckleberry_mash",
        "gate_type": "cold_band",
        "gate_desc": "Line in the cold band",
    },
    "huckleberrys_whopper": {
        "id": "huckleberrys_whopper",
        "name": "Huckleberry's Whopper",
        "lake": "flathead",
        "kind": "caught",
        "weight_lb": 18.0,
        "teller": "Captain Huckleberry",
        "teller_location": "Flathead Alpine Lake",
        "zones": ("rocks",),
        "start_hour": 22,
        "end_hour": 2,
        "weathers": ("snow_mist",),
        "bait": "roe",
        "gate_type": "whopper_story",
        "gate_desc": "Heard Whopper story on 3 different days",
    },
    "obsidian_gar": {
        "id": "obsidian_gar",
        "name": "The Obsidian Gar",
        "lake": "crater",
        "kind": "caught",
        "weight_lb": 48.0,
        "teller": "Ignis",
        "teller_location": "Crater Caldera",
        "zones": ("rocks",),
        "start_hour": 16,
        "end_hour": 20,
        "weathers": ("clear",),
        "bait": "mineral_shad",
        "gate_type": "chapter",
        "gate_value": 4,
        "gate_desc": "Chapter 4 complete",
    },
    "caldera_fire_lizard": {
        "id": "caldera_fire_lizard",
        "name": "The Caldera Fire-Lizard",
        "lake": "crater",
        "kind": "caught",
        "weight_lb": 30.0,
        "teller": "Nyx",
        "teller_location": "Crater Caldera",
        "zones": ("springs",),
        "start_hour": 0,
        "end_hour": 4,
        "weathers": ("fog",),
        "bait": "ember_dumpling",
        "gate_type": "mist_poem",
        "gate_desc": "Heard Mist's poem",
    },
    "nebula_weaver": {
        "id": "nebula_weaver",
        "name": "The Nebula Weaver",
        "lake": "nebula",
        "kind": "caught",
        "weight_lb": 26.0,
        "teller": "Nebula-Paws",
        "teller_location": "Starlight Nebula Lagoon",
        "zones": ("current",),
        "start_hour": 20,
        "end_hour": 24,
        "weathers": ("aurora",),
        "bait": "moonmilk_stardust",
        "gate_type": "zero_g_winch",
        "gate_desc": "Zero-G Winch owned",
    },
    "star_whale": {
        "id": "star_whale",
        "name": "The Celestial Star-Whale",
        "lake": "nebula",
        "kind": "witnessed",
        "weight_lb": None,
        "teller": "Professor Astra-9",
        "teller_location": "Starlight Nebula Lagoon",
        "zones": ("open",),
        "start_hour": 20,
        "end_hour": 4,
        "weathers": ("clear",),
        "bait": None,
        "gate_type": "star_whale",
        "gate_desc": "Chapter 5 complete & settled by the calm reflection",
    },
}


@dataclass
class RequirementStatus:
    name: str
    met: bool
    description: str
    revealed: bool = True
    category: str = ""

    @property
    def status_text(self) -> str:
        return "✓" if self.met else "✗"


@dataclass
class WatchCard:
    id: str
    name: str
    lake: str
    kind: str
    clue_source: str
    story: str
    verified: bool
    requirements: list[RequirementStatus]
    next_window: tuple[float, float] | None
    next_window_text: str
    ready_now: bool
    states: dict[str, bool] = field(default_factory=dict)

    def lines(self) -> list[str]:
        rows: list[str] = []
        if self.verified:
            rows.append(f"Recorded in the Pescapedia · {self.name}")
        else:
            rows.append(f"A lead from {self.clue_source}")
        if self.story:
            rows.append(self.story)
        for req in self.requirements:
            if req.revealed:
                mark = "✓" if req.met else "✗"
                rows.append(f"[{mark}] {req.description}")
            else:
                cat = req.name or req.category.capitalize()
                rows.append(f"[?] {cat}: Clue not yet revealed")
        if self.next_window_text:
            rows.append(f"Next eligible window: {self.next_window_text}")
        return rows


def roll_legendary_weight(legendary_id: str, rng: Any = None) -> float:
    """Return a deterministic weight centered around the nominal weight from 03 §3."""
    data = LEGENDARY_DATA.get(legendary_id)
    if not data or data["weight_lb"] is None:
        return 0.0
    nominal = float(data["weight_lb"])
    if rng is None:
        return round(nominal, 2)
    u = rng.u01() if hasattr(rng, "u01") else 0.5
    return round(nominal * (0.95 + 0.10 * u), 2)


def caught_this_week(state: Any, legendary_id: str) -> bool:
    """Check if this legendary was caught in the current game week."""
    v2 = getattr(state, "v2", None)
    if not isinstance(v2, dict):
        return False
    pages = v2.get("legendaries", {})
    if not isinstance(pages, dict):
        return False
    page = pages.get(legendary_id, {})
    if not isinstance(page, dict):
        return False
    records = page.get("records", [])
    if not isinstance(records, list) or not records:
        return False
    current_week = int(state.game_minutes // calendar.WEEK_MINUTES)
    for rec in reversed(records):
        if isinstance(rec, dict):
            minute = rec.get("game_minute")
            if minute is not None and isinstance(minute, (int, float)):
                if int(minute // calendar.WEEK_MINUTES) == current_week:
                    return True
    return False


def _check_location(data: dict, state: Any, line: Any = None, world: Any = None) -> tuple[bool, str]:
    lake_id = data["lake"]
    if "area_id" in data:
        area_ref = data["area_id"]
        area_tag = area_ref.partition(":")[2]
        area_name = area_tag.replace("_", " ").title()
        desc = f"Area: {area_name}"
        if line is not None:
            if line.extra_fields.get("area_id") == area_ref or getattr(line, "zone", "") == area_tag:
                return True, desc
            mx, mz = (line.x0 + line.x1) * 0.5, (line.z0 + line.z1) * 0.5
            return lakes.in_place(area_ref, lake_id, mx, mz), desc
        boat_in = lakes.in_place(area_ref, lake_id, state.x, state.z)
        line_in = any(
            ln.extra_fields.get("area_id") == area_ref
            or getattr(ln, "zone", "") == area_tag
            or lakes.in_place(area_ref, lake_id, (ln.x0 + ln.x1) * 0.5, (ln.z0 + ln.z1) * 0.5)
            for ln in getattr(state, "lines", [])
        )
        return boat_in or line_in, desc

    zones = data.get("zones", ())
    zone_label = " or ".join(z.replace("_", " ").title() for z in zones)
    desc = f"Zone: {zone_label}"
    if line is not None:
        return line.zone in zones, desc
    current_zone = getattr(state, "zone", "")
    if world and hasattr(world, "zone_at"):
        current_zone = world.zone_at(state.x, state.z)
    boat_match = current_zone in zones
    line_match = any(ln.zone in zones for ln in getattr(state, "lines", []))
    return boat_match or line_match, desc


def _check_window(data: dict, state: Any) -> tuple[bool, str]:
    start = data["start_hour"]
    end = data["end_hour"]
    desc = f"Window: {start:02d}:00–{end:02d}:00"
    minute_acc = getattr(state, "minute_acc", 0.0)
    hour = hour_of_day(state.game_minutes + minute_acc)
    return calendar.in_hours(hour, start, end), desc


def _check_weather(lid: str, data: dict, state: Any) -> tuple[bool, str]:
    if data.get("recent_rain"):
        desc = "Weather: Rain within last 6 game hours"
        explicit = getattr(state, "recent_rain", None)
        if explicit is not None:
            return bool(explicit), desc
        seed = calendar.forecast_seed(state)
        window = calendar.LEGENDARY_WINDOWS.get(lid)
        met = bool(window and calendar.window_favorable(seed, window, state.game_minutes))
        return met, desc

    weathers = data.get("weathers", ())
    if not weathers:
        return True, "Weather: Any"

    w_label = " or ".join(w.replace("_", " ").title() for w in weathers)
    desc = f"Weather: {w_label}"
    state_w = getattr(state, "weather", None)
    if state_w is not None:
        return state_w in weathers, desc
    planned_w = calendar.weather_at(state, state.game_minutes)
    return planned_w in weathers, desc


def _check_bait(data: dict, state: Any, line: Any = None) -> tuple[bool, str] | None:
    bait = data.get("bait")
    if bait is None:
        return None
    desc = f"Bait: {bait.replace('_', ' ').title()}"
    if line is not None:
        match = (
            bait in getattr(line, "bait_sections", ())
            or getattr(line, "bait", "") == bait
            or any(line.bait_for_hook(i) == bait for i in range(len(line.hooks)))
        )
        return match, desc
    inventory_has = getattr(state, "bait", {}).get(bait, 0) > 0
    deployed_has = any(bait in ln.bait_sections for ln in getattr(state, "lines", []))
    return inventory_has or deployed_has, desc


def _check_gate(data: dict, state: Any, line: Any = None, world: Any = None) -> tuple[bool, str] | None:
    gate_type = data.get("gate_type")
    if not gate_type:
        return None

    desc = data.get("gate_desc", "")
    if gate_type == "spotlight":
        met = bool(getattr(state, "light", False))
        return met, desc
    if gate_type == "heavy_line":
        if line is not None:
            return getattr(line, "tier", "") == "heavy", desc
        held_has = any(ln.tier == "heavy" for ln in getattr(state, "held", []))
        line_has = any(ln.tier == "heavy" for ln in getattr(state, "lines", []))
        return held_has or line_has or getattr(state, "tier", None) == "heavy", desc
    if gate_type == "chapter":
        req = data.get("gate_value", 0)
        return chapter_finished(state, req), desc
    if gate_type == "cold_band":
        if line is not None:
            if "in_cold_band" in getattr(line, "extra_fields", {}):
                return bool(line.extra_fields["in_cold_band"]), desc
            wrld = world or getattr(state, "_world", None)
            if wrld and hasattr(wrld, "depth"):
                hour = hour_of_day(state.game_minutes + getattr(state, "minute_acc", 0.0))
                weather = calendar.weather_at(state, state.game_minutes)
                cold = bottools.cold_layer_m(state.lake_id, hour, weather)
                mx, mz = (line.x0 + line.x1) * 0.5, (line.z0 + line.z1) * 0.5
                depth = float(wrld.depth(mx, mz))
                met = cold is not None and cold <= depth <= cold + bottools.COLD_BAND_M
                return met, desc
            return False, desc
        return any(bool(ln.extra_fields.get("in_cold_band")) for ln in getattr(state, "lines", [])), desc
    if gate_type == "whopper_story":
        if getattr(state, "whopper_story_heard", False):
            return True, desc
        from .dialogue import story_heard
        return story_heard(state, "captain_huckleberry") >= 3, desc
    if gate_type == "star_whale":
        desc = "Chapter 5 complete & settled by the calm reflection"
        if not chapter_finished(state, 5):
            return False, desc
        if getattr(state, "settled", False):
            return True, desc
        from .story import settle_near
        wrld = world or getattr(state, "_world", None)
        if wrld is not None:
            is_settled = bool(state.anchored and abs(state.speed) < 0.1 and settle_near(state, wrld))
            return is_settled, desc
        return bool(state.anchored and abs(state.speed) < 0.1), desc
    if gate_type == "mist_poem":
        if getattr(state, "mist_poem_heard", False):
            return True, desc
        v2 = getattr(state, "v2", None) or {}
        ripples = getattr(state.narrative, "ripples", []) if hasattr(state, "narrative") else []
        v2_ripples = v2.get("ripples_v2", []) if isinstance(v2, dict) else []
        met = (
            quest_status(state, "wc_mist_a") == "completed"
            or 33 in ripples
            or "ripple_33" in v2_ripples
        )
        return met, desc
    if gate_type == "zero_g_winch":
        return state.owns_tool("zero_g_winch"), desc
    if gate_type == "ripples":
        needed = data.get("gate_value", 8)
        ripples = getattr(state.narrative, "ripples", []) if hasattr(state, "narrative") else []
        return len(set(ripples)) >= needed, desc

    return True, desc


def evaluate_requirements(state: Any, legendary_id: str, line: Any = None,
                          world: Any = None) -> dict[str, Any]:
    """Evaluate all requirements for one legendary against the current state and optional line."""
    data = LEGENDARY_DATA.get(legendary_id)
    if not data:
        raise ValueError(f"Unknown legendary ID: {legendary_id}")

    requirements: list[RequirementStatus] = []

    # 1. Lake
    lake_met = state.lake_id == data["lake"]
    lake_name = LAKE_NAMES.get(data["lake"], data["lake"].title())
    requirements.append(RequirementStatus(
        name="Lake",
        met=lake_met,
        description=f"Lake: {lake_name}",
        category="lake",
    ))

    # 2. Location (Area or Zone)
    loc_met, loc_desc = _check_location(data, state, line, world)
    requirements.append(RequirementStatus(
        name="Location",
        met=loc_met,
        description=loc_desc,
        category="location",
    ))

    # 3. Time Window
    win_met, win_desc = _check_window(data, state)
    requirements.append(RequirementStatus(
        name="Window",
        met=win_met,
        description=win_desc,
        category="window",
    ))

    # 4. Weather
    w_met, w_desc = _check_weather(legendary_id, data, state)
    requirements.append(RequirementStatus(
        name="Weather",
        met=w_met,
        description=w_desc,
        category="weather",
    ))

    # 5. Bait
    bait_res = _check_bait(data, state, line)
    if bait_res is not None:
        b_met, b_desc = bait_res
        requirements.append(RequirementStatus(
            name="Bait",
            met=b_met,
            description=b_desc,
            category="bait",
        ))

    # 6. Gate (if applicable)
    gate_res = _check_gate(data, state, line, world)
    if gate_res is not None:
        g_met, g_desc = gate_res
        requirements.append(RequirementStatus(
            name="Gate",
            met=g_met,
            description=g_desc,
            category="gate",
        ))

    all_met = all(r.met for r in requirements)
    missing = [r.name for r in requirements if not r.met]

    states = {r.category: r.met for r in requirements}
    states.update({r.name.lower(): r.met for r in requirements})

    return {
        "met": all_met,
        "requirements": requirements,
        "missing": missing,
        "states": states,
    }


def watch_card(state: Any, legendary_id: str, line: Any = None,
               world: Any = None) -> WatchCard:
    """Build a complete WatchCard with revealed clues, live ✓/✗ statuses and next window."""
    data = LEGENDARY_DATA.get(legendary_id)
    if not data:
        raise ValueError(f"Unknown legendary ID: {legendary_id}")

    page = legendary_page(legendary_id, getattr(state, "v2", {}), remember=False)
    verified = bool(page and page.get("verified"))
    if legendary_id == "whiskered_guardian" and getattr(state.narrative, "guardian_seen", False):
        verified = True
    if legendary_id == "star_whale":
        from .story import scene_state
        if scene_state(state, "story_c5_whale") == "done":
            verified = True

    eval_result = evaluate_requirements(state, legendary_id, line=line, world=world)
    reqs: list[RequirementStatus] = eval_result["requirements"]

    clues = page.get("clues", []) if page else []
    revealed_categories: set[str] = set()
    all_revealed = verified

    if isinstance(clues, (list, tuple)):
        for clue in clues:
            if isinstance(clue, str):
                if clue in ("all", "revealed"):
                    all_revealed = True
                elif clue in ("teller",):
                    revealed_categories.add("teller")
                elif clue in ("location", "area", "zone"):
                    revealed_categories.add("location")
                elif clue in ("window", "time", "band", "hour"):
                    revealed_categories.add("window")
                elif clue in ("weather",):
                    revealed_categories.add("weather")
                elif clue in ("bait",):
                    revealed_categories.add("bait")
                elif clue in ("gate",):
                    revealed_categories.add("gate")
            elif isinstance(clue, dict):
                if any(k in clue for k in ("zone", "area", "lake")):
                    revealed_categories.add("location")
                if any(k in clue for k in ("band", "window", "time", "hour")):
                    revealed_categories.add("window")
                if "weather" in clue:
                    revealed_categories.add("weather")
                if "bait" in clue:
                    revealed_categories.add("bait")
                if "gate" in clue:
                    revealed_categories.add("gate")

    for req in reqs:
        if all_revealed or req.category in revealed_categories or (req.category == "lake" and "location" in revealed_categories):
            req.revealed = True
        else:
            req.revealed = False
    # Next eligible window from weather planner
    seed = calendar.forecast_seed(state)
    try:
        start, end = calendar.next_legendary_window(seed, legendary_id, state.game_minutes)
        window_text = f"{calendar.day_name(start)} {calendar.clock_string(start)}–{calendar.clock_string(end)}"
        next_win = (start, end)
    except Exception:
        next_win = None
        window_text = "Schedule unavailable"

    teller_src = f"{data['teller']} ({data['teller_location']})"
    story_text = page.get("story", "") if page else LEGENDARY_STORIES.get(legendary_id, None)
    if hasattr(story_text, "story"):
        story_text = story_text.story
    if not isinstance(story_text, str):
        story_text = ""

    return WatchCard(
        id=legendary_id,
        name=data["name"],
        lake=data["lake"],
        kind=data["kind"],
        clue_source=teller_src,
        story=story_text,
        verified=verified,
        requirements=reqs,
        next_window=next_win,
        next_window_text=window_text,
        ready_now=eval_result["met"],
        states=eval_result["states"],
    )


def check_legendary_hook(state: Any, line: Any, world: Any = None) -> Any | None:
    """Evaluate and hook a legendary fish on the line if every requirement is met."""
    from .sim import Catch

    if any(getattr(h.catch, "legendary", False) for h in line.hooks if h.catch is not None):
        return next(h.catch for h in line.hooks if h.catch and h.catch.legendary)

    lake_id = getattr(state, "lake_id", None)
    if not lake_id:
        return None

    for lid, data in LEGENDARY_DATA.items():
        if data["lake"] != lake_id or data["kind"] == "witnessed":
            continue
        if caught_this_week(state, lid):
            continue

        eval_res = evaluate_requirements(state, lid, line=line, world=world)
        if not eval_res["met"]:
            continue

        weight = roll_legendary_weight(lid, getattr(state, "rng", None))
        minute_acc = getattr(state, "minute_acc", 0.0)
        hour = hour_of_day(state.game_minutes + minute_acc)
        catch = Catch(
            species=lid,
            weight=weight,
            quality=1.0,
            age=0.0,
            zone=line.zone,
            bait=data["bait"],
            hour=hour,
            lake_id=lake_id,
            catch_game_minute=state.game_minutes,
            legendary=True,
            disposition="release",
        )

        # Prefer an unoccupied hook with matching bait, then any unoccupied hook.
        # Only if all hooks are already occupied does it replace an existing catch.
        target_hook = None
        req_bait = data["bait"]
        empty_hooks = [h for h in line.hooks if h.catch is None]
        if empty_hooks:
            for idx, h in enumerate(line.hooks):
                if h.catch is None and line.bait_for_hook(idx) == req_bait:
                    target_hook = h
                    break
            if target_hook is None:
                for idx, h in enumerate(line.hooks):
                    if h.catch is None and h.baited:
                        target_hook = h
                        break
            if target_hook is None:
                target_hook = empty_hooks[0]
        elif line.hooks:
            for idx, h in enumerate(line.hooks):
                if line.bait_for_hook(idx) == req_bait:
                    target_hook = h
                    break
            if target_hook is None:
                target_hook = line.hooks[0]
        if target_hook is not None:
            target_hook.catch = catch
            target_hook.baited = False
            state._note_journal(catch)
            state.claim_reward("legendary_record", lid)
            return catch

    return None


def record_witnessed(state: Any, legendary_id: str, world: Any = None) -> bool:
    """Record a witnessed legendary in the book and ledger."""
    from .book import record_legendary
    data = LEGENDARY_DATA.get(legendary_id)
    if not data or data["kind"] != "witnessed":
        return False

    lake_id = world.id if world else data["lake"]
    minute_acc = getattr(state, "minute_acc", 0.0)
    hour = hour_of_day(state.game_minutes + minute_acc)
    zone = data["zones"][0] if data.get("zones") else "deep"
    record_legendary(state.v2, legendary_id, {
        "witnessed": True,
        "lake_id": lake_id,
        "zone": zone,
        "hour": hour,
        "game_minute": state.game_minutes,
    })
    state.claim_reward("legendary_record", legendary_id)
    state.emit_quest_event({
        "type": "legendary.witnessed",
        "species_id": legendary_id,
        "lake_id": lake_id,
        "zone_id": f"{lake_id}:{zone}",
        "game_minute": state.game_minutes,
    })
    return True
