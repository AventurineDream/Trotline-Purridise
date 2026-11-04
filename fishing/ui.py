"""Quiet lake journal, readable menus, and a compact navigation HUD."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
import math
import textwrap

import numpy as np

from .data import (
    BAITS,
    BAIT_BY_ID,
    BOXES,
    BOX_PRICE,
    FINDER_PRICE,
    LIGHT_PRICE,
    LINE_TIERS,
    MOTORS,
    PAINT,
    PAINT_LABEL,
    SPECIES,
    SPECIES_BY_ID,
    WELL_PRICE,
    WELLS,
    dollars,
    paint_name,
    quality_name,
    weather_at,
    clock_string,
    CEDAR_FISH,
)
from .content import load_content
from .guardian import draw_sighting
from . import bottools, fleet, sonar
from .haul import haul_cadence
from .book import BOOK_STAGES
from .bookview import BookView
from .narrative import QUEST_IDS
from .platform import Text
from .dialogue import nearby_npc
from .imageops import resize_rgb
from .raster import raster_tri
from .world import ZONE_NAME, World
from .gamepad import (
    ACTION_ALIASES, ACTION_SYMBOLS, default_key_bindings,
    normalize_key_bindings,
)
from .boat import (
    BOATS, FUEL_PRICE, ROWBOAT_MOTOR_PRICE, ROWBOAT_BATTERY_KWH,
    BATTERY_CHARGE_KWH, ELECTRICITY_PRICE,
)
from .lakes import LAKES, LAKE_ZONE_NAMES, travel_lock_reason
from .data import weight_string
from .weather import wind_at
from . import comfort

INK = (238, 233, 216)
DIM = (169, 183, 175)
GOLD = (218, 187, 124)
WARN = (220, 126, 96)
# Shallow to deep; the last colour also covers anything deeper.
SONAR_BAND_COLORS = ((120, 204, 214), (92, 172, 196), (70, 136, 176), (52, 104, 150))
GOOD = (150, 196, 140)
GAME_TITLE = "Trotline Purridise"
BOOK_STAGE_UP_COUNTS = frozenset(
    threshold for threshold, _stage in BOOK_STAGES if threshold >= 3
)

SHOP_TABS = ("Sell", "Bait", "Gear", "Paint", "Boats", "Lakes", "Kitchen", "Bot")
_TABS = SHOP_TABS
TEXT_SIZE_SCALES = (0.9, 1.0, 1.15)
MODES = comfort.MODES
VOLUME_NAMES = ("master", "music", "ambience", "sfx")
VOLUME_LABELS = {
    "master": "Master volume", "music": "Music volume",
    "ambience": "Ambience volume", "sfx": "SFX volume",
}
KEY_ACTION_LABELS = {
    "throttle_up": "Throttle up / row forward",
    "throttle_down": "Throttle down / row reverse",
    "steer_left": "Steer left", "steer_right": "Steer right",
    "idle": "Return to idle", "idle_right": "Return to idle (right Shift)",
    "anchor": "Anchor / alternate select", "set_line": "Set a trotline",
    "check_or_land": "Check a line / landing", "help": "Help",
    "pause": "Pause / cancel", "mute": "Mute audio", "hail": "Hail / continue",
    "chart": "Chart", "journal": "Journal", "livewell": "Livewell",
    "bot": "Send / recall Bot", "time_scale": "Time scale",
    "sail": "Raise / lower sail", "tow": "Call a tow",
    "new_game": "New morning", "catnap": "Catnap",
    "bot_tool": "Bot tool", "galley": "Galley",
    "menu_up": "Menu up", "menu_down": "Menu down",
    "menu_left": "Menu left", "menu_right": "Menu right",
    "select": "Select",
}

_ZONE_LABELS = {
    "briar:landing": "Briar Landing",
    "briar:inlet": "Creek inlet",
    "briar:flats": "North flats",
    "briar:lilies": "Lily cove",
    "briar:cypress": "Cypress shore",
    "briar:deep": "Deep hole",
    "briar:rocks": "South rocks",
    "briar:open": "Open water",
    "cedar:landing": "Caney Creek landing",
    "cedar:inlet": "Creek channels",
    "cedar:flats": "Upper lake flats",
    "cedar:lilies": "Clear Creek coves",
    "cedar:cypress": "Flooded shoreline",
    "cedar:rocks": "Dam riprap",
    "cedar:deep": "Southern basin",
    "cedar:open": "Cedar open water",
    "cedar:docs_marina_dock": "Doc's Lonely Star Marina",
}
_LAKE_LABELS = {"briar": "Little Briar Lake", "cedar": "Cedar Creek Lake"}
_STATUS_LABELS = {
    "available": "Available",
    "active": "Active",
    "ready": "Ready",
    "completed": "Completed",
}
_STATUS_BADGES = {
    "available": "AVL",
    "active": "ACT",
    "ready": "RDY",
    "completed": "DONE",
}
_STATUS_COLORS = {
    "available": DIM,
    "active": GOLD,
    "ready": GOOD,
    "completed": INK,
}
_SHORT_QUEST_TITLES = {
    "q01_tea_leaves_deep_holes": "Tea",
    "q02_lonely_star_current": "Star",
    "q03_unstrung_line": "Line",
    "q04_great_contour_chart": "Chart",
    "q05_moonlight_trotlines": "Moon",
    "q06_unrepeatable_sunrise": "Sunrise",
    "q07_art_of_the_nap": "Nap",
    "q08_channel_run": "Channel",
    "q09_quiet_channel": "Quiet",
    "q10_ballad_lonely_star": "Song",
    "q11_deep_water_drift": "Drift",
    "q12_first_voyage": "Voyage",
}


def _zone_label(zone_id: str) -> str:
    if not isinstance(zone_id, str):
        return "Unknown water"
    if zone_id in _ZONE_LABELS:
        return _ZONE_LABELS[zone_id]
    lake, separator, zone = zone_id.partition(":")
    if not separator:
        return zone_id
    if zone in LAKE_ZONE_NAMES.get(lake, {}):
        return LAKE_ZONE_NAMES[lake][zone]
    return f"{_LAKE_LABELS.get(lake, lake.title())} · {zone.replace('_', ' ')}"


def _finite_progress(value) -> float:
    if type(value) not in (int, float):
        return 0.0
    try:
        return float(value) if math.isfinite(value) and value >= 0 else 0.0
    except OverflowError:
        return 0.0


def _clock_window(window) -> str:
    if not isinstance(window, (list, tuple)) or len(window) != 2:
        return ""
    if any(type(value) is not int or not 0 <= value < 1440 for value in window):
        return ""
    start, end = window
    return f"{start // 60:02d}:{start % 60:02d}–{end // 60:02d}:{end % 60:02d}"


def _quest_objective_text(quest: dict) -> str:
    objective = quest.get("objective", {})
    kind = objective.get("type")
    zone = _zone_label(objective.get("zone_id", ""))
    bait_row = BAIT_BY_ID.get(objective.get("bait_id"))
    bait = bait_row.name.lower() if bait_row else "specified bait"
    hooks = objective.get("hook_count")
    duration = objective.get("active_soak_game_minutes")

    if kind == "line_scout":
        return (f"Set a {hooks}-hook {bait} line in {zone}; make it Bot's nearest line "
                f"under {objective.get('scout_range_lt_m', 140)} m and request a report.")
    if kind == "line_check":
        window = _clock_window(objective.get("set_window"))
        window_text = f" during {window}" if window else ""
        return (f"Set a {hooks}-hook {bait} line in {zone}{window_text}; check that same line "
                f"after {duration} active-play game minutes.")
    if kind == "line_scout_check":
        return (f"Set an {hooks}-hook {bait} line in {zone}; have Bot report on it under "
                f"{objective.get('scout_range_lt_m', 140)} m, then check it after "
                f"{duration} active-play game minutes.")
    if kind == "anchor_idle":
        return (f"Anchor with the engine idle in {zone} for "
                f"{objective.get('continuous_game_minutes', 0)} continuous game minutes; "
                "interruptions reset the timer.")
    if kind == "scout_report":
        return f"Ask Bot for his ordinary depth report in {zone}."
    if kind == "fish_livewell":
        species_id = objective.get("species_id", "fish")
        species = SPECIES_BY_ID.get(species_id)
        species_name = species.name.lower() if species else species_id.replace("_", " ")
        window = _clock_window(objective.get("entry_window"))
        return (f"Bring a {species_name} into the livewell during {window} from a {bait} "
                f"line set in {zone}; the fish stays yours.")
    if kind == "travel_distance":
        propulsion = objective.get("propulsion", [])
        methods = " or ".join(str(item) for item in propulsion) or "your own power"
        return (f"Travel {objective.get('distance_m', 0)} m under your control in {zone} "
                f"({methods}; towing does not count).")
    if kind in ("visit_zones", "visit_sequence"):
        locations = [_zone_label(item) for item in objective.get("zone_ids", [])]
        joiner = " → " if kind == "visit_sequence" else ", "
        order = " in order" if kind == "visit_sequence" else " in any order"
        return f"Visit {joiner.join(locations)}{order}."
    return "Follow the current quest objective."


def _quest_progress_text(quest: dict, quest_progress, narrative) -> str:
    status = quest_progress.status
    if status == "available":
        return ("Declined earlier; still available." if quest_progress.declined
                else "Not started; accept whenever you like.")
    if status == "ready":
        return "Ready to turn in; hail the same giver again."
    if status == "completed":
        return "Completed; the reward has been claimed once."

    objective = quest.get("objective", {})
    progress = quest_progress.progress if isinstance(quest_progress.progress, dict) else {}
    kind = objective.get("type")
    if kind == "anchor_idle":
        current = _finite_progress(progress.get("continuous_game_minutes"))
        target = _finite_progress(objective.get("continuous_game_minutes"))
        return f"Anchor timer: {current:g}/{target:g} game min."
    if kind == "travel_distance":
        current = _finite_progress(progress.get("distance_m"))
        target = _finite_progress(objective.get("distance_m"))
        return f"Travel: {current:.0f}/{target:.0f} m."
    if kind == "visit_zones":
        expected = objective.get("zone_ids", [])
        visited = progress.get("visited_zones", [])
        visited = visited if isinstance(visited, list) else []
        count = sum(1 for zone in expected if zone in visited)
        return f"Places visited: {count}/{len(expected)}."
    if kind == "visit_sequence":
        expected = objective.get("zone_ids", [])
        index = progress.get("sequence_index", 0)
        if type(index) is not int or index < 0:
            index = 0
        index = min(index, len(expected))
        if index < len(expected):
            return f"Route: step {index + 1}/{len(expected)} — {_zone_label(expected[index])}."
        return f"Route: {len(expected)}/{len(expected)} steps."
    if kind == "scout_report":
        return "Waiting for Bot's report."
    if kind == "fish_livewell":
        return "Waiting for a qualifying fish to enter the livewell."
    if kind in ("line_scout", "line_check", "line_scout_check"):
        deployments = progress.get("deployments", {})
        if not isinstance(deployments, dict):
            deployments = {}
        attempts = [value for value in deployments.values()
                    if isinstance(value, dict) and isinstance(value.get("set"), dict)]
        if not attempts:
            return "No qualifying line set yet."
        attempt = attempts[-1]
        parts = ["Line set"]
        if kind in ("line_scout", "line_scout_check"):
            parts.append("Bot report received" if attempt.get("scouted") is True
                         else "Bot report pending")
        if kind in ("line_check", "line_scout_check"):
            target = _finite_progress(objective.get("active_soak_game_minutes"))
            set_minute = _finite_progress(attempt["set"].get("active_game_minute"))
            active_now = _finite_progress(narrative.active_play_game_minutes)
            elapsed = max(0.0, active_now - set_minute)
            recorded = _finite_progress(attempt.get("active_soak_game_minutes"))
            elapsed = max(elapsed, recorded)
            parts.append(f"soak {elapsed:g}/{target:g} active-play min")
        return "; ".join(parts) + "."
    return "Objective in progress."


def journal_quest_ids(state, content) -> tuple:
    """The twelve V3 quests, then each V1.0 side quest and story step once it has been accepted."""
    accepted = tuple(qid for qid, quest in content.quests.items()
                     if quest.get("kind") in ("host", "a", "b", "story") and qid in state.narrative.quests
                     and state.narrative.quests[qid].status != "available")
    return QUEST_IDS + accepted


def _v2_journal_details(state, content, quest_id: str) -> dict:
    """A V1.0 quest's row: its authored objective, its step, and when a needed cat is next out."""
    from .npcs import next_appearance
    from .quests import current_step, steps_of
    quest = content.quests[quest_id]
    progress = state.narrative.quests[quest_id]
    steps = steps_of(quest)
    needed = None
    if progress.status == "active":
        step, _data = current_step(quest, progress)
        text = f"Step {progress.progress.get('step', 0) + 1} of {len(steps)}." if len(steps) > 1 else "Under way."
        if step is not None and step["type"] == "talk_to":
            needed = step["npc_id"]
    elif progress.status == "ready":
        text = "Ready to turn in, to the giver or at the landing."
        needed = quest["giver_id"]
    else:
        text = "Completed; the reward has been claimed once."
    if needed is not None:
        text += " " + next_appearance(state, content, needed)
    giver = content.cats.get(quest["giver_id"], {})
    return {
        "title": quest["title"],
        "status": _STATUS_LABELS.get(progress.status, "Available"),
        "giver": f"{content.name(quest['giver_id'])} · {LAKES.get(giver.get('lake_id'), {}).get('name', '')}",
        "objective": quest["journal"],
        "progress": text,
        "prerequisites": "none",
        "bot_notes": [], "latest_bot_note": None,
        "guardian_status": "",
    }


def quest_journal_details(state, content, quest_id: str) -> dict:
    """Build safe, contract-grounded text for the selected narrative journal row."""
    quest = content.quests[quest_id]
    if "kind" in quest:
        return _v2_journal_details(state, content, quest_id)
    giver = content.npcs[quest["giver_id"]]
    quest_progress = state.narrative.quests[quest_id]
    prerequisites = quest.get("prerequisites", [])
    titles = {row["id"]: row["title"] for row in content.quests.values()}
    prerequisite_text = (", ".join(titles[item] for item in prerequisites if item in titles)
                         if prerequisites else "none")
    notes = [note for note in state.narrative.bot_notes
             if isinstance(note, str) and note.strip()]
    bot_journal = [note for note in state.narrative.bot_journal
                   if isinstance(note, str) and note.strip()]
    ripple_count = min(10, len(set(state.narrative.ripples)))
    if state.narrative.guardian_seen:
        guardian_status = ("Guardian seen — Whiskered Blessing: A broad ripple passed "
                           "under the hull. The lake was quiet again.")
    elif ripple_count >= 8:
        guardian_status = ("Guardian available. Cedar deep water at sunset "
                           "(18:00–20:00).")
    else:
        guardian_status = ("Guardian locked (<8 Ripples). Cedar deep water at sunset "
                           "(18:00–20:00).")
    return {
        "title": quest["title"],
        "status": _STATUS_LABELS.get(quest_progress.status, "Available"),
        "giver": f"{giver['name']} · {_zone_label(giver.get('anchor_id', ''))}",
        "objective": _quest_objective_text(quest),
        "progress": _quest_progress_text(quest, quest_progress, state.narrative),
        "prerequisites": prerequisite_text,
        "bot_notes": notes[-2:],
        "latest_bot_note": bot_journal[-1] if bot_journal else (notes[-1] if notes else None),
        "guardian_status": guardian_status,
    }


@dataclass
class Row:
    label: str
    right: str
    blurb: str
    enabled: bool
    kind: str
    arg: str = ""


CREDITS_TITLE = "The Book of Five Waters"
CREDITS_HOLD_S = 3.0  # the credits can't be dismissed by a key still being pressed from the ending
CREDITS_LINES = ("Grandmother Whiskers · Pip & Pebble · Doc Barnaby",
                 "Captain Huckleberry · Sora · Professor Astra-9",
                 "and everyone who ever tied up at Briar Landing.",
                 "Thank you for fishing with us.")


@dataclass
class UIState:
    mode: str = "title"
    input_device: str = "keyboard"
    shop_tab: int = 0
    shop_i: int = 0
    set_line: int = 0
    set_bait: int = 0
    set_sections: int = 1
    set_section: int = 0
    set_section_baits: tuple[int, int, int] = (0, 0, 0)
    check_line: int = 0
    check_i: int = 0
    haul_index: int = 0
    haul_timer: float = 0.0
    haul_picnic_factor: float = 1.0
    haul_picnic_started: bool = False
    haul_phase: str = "rise"
    haul_phase_timer: float = 0.0
    haul_badge_enabled: bool = True
    haul_counts_before: dict = field(default_factory=dict)
    whale_return: bool = False          # the Star-Whale is coming back in play (V1-37)
    haul_legendary: str = ""            # the legendary whose scene the haul is presenting (V1-37)
    haul_encounter_only: bool = False   # an instant haul stopped for a legendary's first scene
    journal_i: int = 0
    book_week_i: int = 0
    journal_page: int = 0
    journal_quest_i: int = 0
    book_entry_i: int = 0
    book_detail_page: int = 0
    book_detail_pages: int = 1
    book_shelf: int = 0
    book_collection_i: int = 0
    book_watch_i: int = 0
    book_ceremony: str = ""
    book_prompt_species: str = ""
    book_prompt_timer: float = 0.0
    well_i: int = 0
    pause_i: int = 0
    settings_page: str = "main"
    settings_i: int = 0
    key_binding_i: int = 0
    capturing_key: bool = False
    caption: str = ""
    caption_timer: float = 0.0
    help_page: int = 0
    help_from: str = "play"
    title_i: int = 0
    confirm_new: bool = False
    new_mode_i: int = 0
    comfort_i: int = 0
    needs_kind: str = ""
    nap_timer: float = 0.0
    nap_forced: bool = False
    kitchen_from: str = "play"
    kitchen_hitboxes: list = field(default_factory=list)
    cook_kind: str = ""
    cook_arg: str = ""
    cook_fish: int = 0
    cook_label: str = ""
    cook_text: str = ""
    cook_timer: float = 0.0
    cook_from: str = "shop"
    note: str = ""
    has_save: bool = False
    conversation: object = None
    dialogue_content: object = None
    dialogue_from: str = "play"
    # V1-34 Settle In: whether the Skipper is settling, and the HUD's prompt for it.
    settling: bool = False
    settle_prompt: str = ""
    credits_s: float = 0.0  # real seconds the credits have shown
    # V1-35 staging: the fade and letterbox over a story scene, and how far the credits have risen.
    stage_fx: dict | None = None
    stage_skip: bool = False  # a replayed scene's staging can be skipped with Esc (B)
    vignette: dict | None = None  # the story moment's card: {"kind", "detail", "t"} (V1-35)
    credits_rise: float = math.inf


def comfort_controls(viewport):
    width, height = viewport
    margin = max(12, min(28, width // 35))
    button_h = max(34, min(52, height // 7))
    button_w = (width - margin * 2 - 48) // 2
    y = height - margin - 16 - button_h
    return ((margin + 16, y, button_w, button_h),
            (width - margin - 16 - button_w, y, button_w, button_h))


def shop_rows(state, tab: int) -> list[Row]:
    if tab == 7:
        from .botidentity import rows
        return rows(state, state._world)
    if tab == 6:
        from .kitchen import rows
        return rows(state, state._world)
    rows: list[Row] = []
    if tab == 0:
        saleable = [catch for catch in state.well if not catch.treasured]
        total = round(sum(c.value() for c in saleable), 2)
        rows.append(Row(
            "Sell untreasured fish", dollars(total),
            "Treasured fish stay in the livewell during bulk sale.",
            bool(saleable), "sell_all",
        ))
        for i, catch in enumerate(state.well):
            sp = SPECIES_BY_ID.get(catch.species)
            name = sp.name if sp is not None else catch.species.replace("_", " ").title()
            if catch.shiny:
                name = "✦ " + name
            q = quality_name(catch.quality)
            mark = " · Treasured" if catch.treasured else ""
            rows.append(Row(
                f"{weight_string(catch.weight)} {name}, {q}{mark}", dollars(catch.value()),
                f"Caught on {BAIT_BY_ID[catch.bait].name.lower()}.",
                True, "sell_one", str(i),
            ))
    elif tab == 1:
        for bait in BAITS:
            if not ({"all", state.lake_id} & set(bait.sold_at)):
                continue
            have = state.bait.get(bait.id, 0)
            rows.append(Row(
                f"{bait.name}    {have} aboard", f"{dollars(bait.price)} / doz",
                bait.blurb, True, "bait", bait.id,
            ))
    elif tab == 2:
        if state.motor < len(MOTORS) - 1:
            nxt = MOTORS[state.motor + 1]
            rows.append(Row(nxt["name"], dollars(nxt["price"]), "Upgrades the jon boat and pontoon; the daysailer keeps its small auxiliary.", True, "motor"))
        else:
            rows.append(Row(MOTORS[-1]["name"], "aboard", "Nothing bigger fits this hull.", False, "motor"))
        if state.well_tier < len(WELLS) - 1:
            nxt = state.well_tier + 1
            rows.append(Row(
                f"Livewell {WELLS[nxt]:.0f} lb", dollars(WELL_PRICE[nxt]),
                f"Yours holds {WELLS[state.well_tier]:.0f} lb.", True, "well",
            ))
        else:
            rows.append(Row(f"Livewell {WELLS[-1]:.0f} lb", "aboard", "The hull won't take a bigger well.", False, "well"))
        if state.box_tier < len(BOXES) - 1:
            nxt = state.box_tier + 1
            rows.append(Row(
                f"Bait box {BOXES[nxt]}", dollars(BOX_PRICE[nxt]),
                f"Yours holds {BOXES[state.box_tier]}.", True, "box",
            ))
        else:
            rows.append(Row(f"Bait box {BOXES[-1]}", "aboard", "No more room under the seat.", False, "box"))
        if state.finder:
            rows.append(Row("Depth finder", "aboard", "Feet of water, on the dash.", False, "finder"))
        else:
            rows.append(Row("Depth finder", dollars(FINDER_PRICE), "Shows depth in feet.", True, "finder"))
        if state.light:
            rows.append(Row("Bow spotlight", "aboard", "Throws a cone ahead after dark.", False, "light"))
        else:
            rows.append(Row("Bow spotlight", dollars(LIGHT_PRICE), "For night runs back to the dock.", True, "light"))
        for tier, spec in LINE_TIERS.items():
            rows.append(Row(
                spec["name"], dollars(spec["price"]), spec["blurb"],
                True, "line", tier,
            ))
    elif tab==3:
        for slot, items in PAINT.items():
            for pid, label, _rgb, price in items:
                wearing = state.look_paint.get(slot) == pid
                owned = pid in state.owned.get(slot, [])
                if wearing:
                    right = "wearing"
                elif owned:
                    right = "owned"
                else:
                    right = dollars(price)
                rows.append(Row(
                    f"{PAINT_LABEL[slot]}   {label}", right,
                    "Owned colors can be worn again for free.",
                    True, "paint", f"{slot}:{pid}",
                ))
    if tab==4:
        for model in fleet.shop_boats():
            owned = model.id in state.owned_boats
            locked = fleet.shop_error(state, state.lake_id, model.id)
            if model.id==state.boat_id:
                right = "aboard"
            elif owned:
                right = "owned"
            elif locked:
                right = (f"After ch. {fleet.unlock_chapter(model.id)}"
                         if not fleet.chapter_finished(state, fleet.unlock_chapter(model.id)) else "Other landing")
            else:
                right = dollars(model.price)
            description = f"{locked} {model.blurb}" if locked else model.blurb
            rows.append(Row(model.name,right,description,model.id!=state.boat_id and not locked,"boat",model.id))
        if "rowboat" in state.owned_boats:
            if state.rowboat_trolling_motor:
                rows.append(Row("9.9 hp electric trolling motor", "installed",
                                "Runs on its own battery; W/S row the boat if the battery runs out.",
                                False, "trolling_motor"))
            else:
                rows.append(Row("9.9 hp electric trolling motor", dollars(ROWBOAT_MOTOR_PRICE),
                                "Fits the rowboat transom. Includes an 18 kWh battery; oars stay aboard.",
                                True, "trolling_motor"))
        if state.boat_id=="rowboat":
            if state.rowboat_trolling_motor:
                missing = ROWBOAT_BATTERY_KWH-state.rowboat_battery_kwh
                visit_remaining = state.battery_charge_available_this_visit()
                amount = min(visit_remaining,missing,
                             max(0.0,state.money)/ELECTRICITY_PRICE)
                if missing <= 0.001:
                    charge_description = "Battery full. Oars still work if it runs down."
                elif visit_remaining < 0.1:
                    charge_description = "Five kWh used this visit. Leave and return to charge again."
                else:
                    charge_description = "Buy up to five kWh per landing visit. Oars work at zero charge."
                rows.append(Row(f"Battery  {state.rowboat_battery_kwh:.1f}/{ROWBOAT_BATTERY_KWH:.0f} kWh",
                                f"{dollars(amount*ELECTRICITY_PRICE)} / {amount:.1f} kWh",
                                charge_description,
                                missing>0.001 and visit_remaining>=0.1,"battery"))
            else:
                rows.append(Row("Oars", "ready", "W/S row forward or reverse; A/D steer. No fuel needed.",
                                False, "oars"))
        elif state.boat.tank>0:
            missing = state.boat.tank-state.fuel
            amount = min(5.0,missing,max(0.0,state.money)/FUEL_PRICE)
            rows.append(Row(f"Fuel  {state.fuel:.1f}/{state.boat.tank:.0f} L",
                            f"{dollars(amount*FUEL_PRICE)} / {amount:.1f} L",
                            "Buy up to five litres. Tanks stay with each owned boat.",missing>0.001,"fuel"))
    elif tab==5:
        for lake_id,lake in LAKES.items():
            here = lake_id==state.lake_id
            locked = travel_lock_reason(state, lake_id)
            lines = bool(state.lines)
            detail = (locked or "Pick up your deployed lines before towing to another lake."
                      if lines or locked else lake["blurb"])
            rows.append(Row(lake["name"], "here" if here else "locked" if locked else "travel",
                            detail, not (here or locked or lines), "lake", lake_id))
    return rows


def check_rows(state, line_index: int) -> list[Row]:
    if line_index < 0 or line_index >= len(state.lines):
        return []
    line = state.lines[line_index]
    rows: list[Row] = []
    for i, hook in enumerate(line.hooks):
        section = line.section_for_hook(i)
        bait_name = BAIT_BY_ID.get(line.bait_for_hook(i), BAIT_BY_ID["worm"]).name
        section_label = f"S{section + 1} {bait_name}"
        if hook.catch is None:
            label = "baited" if hook.baited else "bare"
            rows.append(Row(f"{i + 1:2d}  {section_label}  {label}", "", "", False, "hook", str(i)))
        else:
            catch = hook.catch
            sp = SPECIES_BY_ID.get(catch.species)
            name = sp.name if sp is not None else catch.species.replace("_", " ").title()
            if catch.shiny:
                name = "✦ " + name
            q = quality_name(catch.quality)
            forced_release = state._forced_release_reason(catch) is not None
            choice = "RELEASE" if forced_release or catch.disposition == "release" else "KEEP"
            if catch.treasured:
                choice += " · TREASURED"
            rows.append(Row(
                f"{i + 1:2d}  {section_label}  {weight_string(catch.weight)} {name}, {q}", choice,
                "", not forced_release, "hook", str(i),
            ))
    rows.append(Row("Resolve catches", "", "Applies the Keep / Release choices.", True, "take_all"))
    rows.append(Row("Rebait bare hooks", "", "Uses each section's bait from the box.", True, "rebait"))
    rows.append(Row("Pull the line", "", "Resolves catches, then coils the line.", True, "pull"))
    return rows


def title_options(has_save: bool) -> list[str]:
    if has_save:
        return ["Continue", "New morning"]
    return ["Start the morning"]


class UI:
    def __init__(self, text: Text, world: World):
        self.text = text
        self.world = world
        self.narrative_content = load_content()
        self._cw: dict[tuple[int, str], int] = {}
        self._ch: dict[tuple[int, str], int] = {}
        self._text_scale = 1.0
        self._dyslexia_font = False
        self.fish_card_renderer = None

    def cell(self, size: int) -> tuple[int, int]:
        actual = self._actual_size(size)
        family = self._font_family("mono")
        key = (actual, family)
        if key not in self._cw:
            img = self.text.render("M", actual, INK, family)
            self._cw[key] = max(1, img.shape[1])
            self._ch[key] = max(1, img.shape[0])
        return self._cw[key], self._ch[key]

    def draw(self, frame: np.ndarray, state, ui: UIState, camera=None) -> None:
        v2 = getattr(state, "v2", {})
        settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
        text_size = settings.get("text_size", 1)
        if type(text_size) is not int or text_size not in range(len(TEXT_SIZE_SCALES)):
            text_size = 1
        self._text_scale = TEXT_SIZE_SCALES[text_size]
        self._dyslexia_font = bool(settings.get("dyslexia_font", False))
        mode = ui.mode
        if mode == "play":
            draw_sighting(frame, state, camera)
        if mode == "title":
            self._title(frame, state, ui)
            self._caption(frame, state, ui)
            self._toasts(frame, state, ui.input_device)
            return
        if mode == "play" and ui.whale_return:
            # The Star-Whale comes back (V1-37): the HUD steps aside under a letterbox.
            from .staging import overlay
            overlay(frame, ui.stage_fx)
            h, w = frame.shape[:2]
            self._center(frame, self._controls(ui, "Esc skip", "B skip"), w / 2, int(h * 0.95),
                         self._size(frame, "small"), DIM)
            self._caption(frame, state, ui)
            self._toasts(frame, state, ui.input_device)
            return
        if mode == "play":
            if comfort.drowsy(state.v2):
                self._drowsy_edges(frame)
            self._hud(frame, state, ui)
            if ui.stage_fx and "sketch" in ui.stage_fx:
                # A "Draw it" scene read early: the drawing finishes while the staging plays out.
                self._sketch(frame, ui.stage_fx["sketch"])
            self._comfort_status(frame, state)
            self._caption(frame, state, ui)
            self._toasts(frame, state, ui.input_device)
            return
        if mode in {"new_mode", "needs", "catnap"}:
            self._comfort(frame, state, ui)
            self._caption(frame, state, ui)
            return
        if mode == "map":
            self._hud(frame, state, ui)
            self._map(frame, state, ui, big=True)
            self._caption(frame, state, ui)
            self._toasts(frame, state, ui.input_device)
            return
        if mode == "dialogue":
            if ui.stage_fx:  # a staged story scene: letterbox and fade, without the HUD (V1-35)
                from .staging import overlay
                overlay(frame, ui.stage_fx)
                if "sketch" in ui.stage_fx:
                    self._sketch(frame, ui.stage_fx["sketch"])
            else:
                self._hud(frame, state, ui, interactions=False)
            panel_top = self._dialogue(frame, state, ui)
            if ui.vignette and panel_top is not None:
                self._vignette(frame, state, ui.vignette, panel_top)
            self._toasts(frame, state, ui.input_device)
        elif mode == "shop":
            self._shop(frame, state, ui)
        elif mode in {"kitchen", "cook_confirm", "cooking"}:
            from .kitchenview import draw
            draw(self, frame, state, ui)
        elif mode == "setbait":
            self._setbait(frame, state, ui)
        elif mode == "haul":
            self._haul(frame, state, ui)
        elif mode == "check":
            self._check(frame, state, ui)
        elif mode == "journal":
            self._journal(frame, state, ui)
        elif mode == "well":
            self._well(frame, state, ui)
        elif mode == "pause":
            self._pause(frame, ui)
        elif mode == "settings":
            if ui.settings_page == "keys":
                self._keybindings(frame, state, ui)
            else:
                self._settings(frame, state, ui)
        elif mode == "help":
            self._help(frame, ui)
        elif mode == "credits":
            self._credits(frame, state, ui)
        self._caption(frame, state, ui)

    def _credits(self, frame, state, ui):
        """The story's end (05 §3): the credits rise over the boat at dawn (V1-35), then rest."""
        from .botidentity import book_credit
        from .staging import overlay
        h, w = frame.shape[:2]
        frame[:] = (frame.astype(np.float32) * 0.62).astype(frame.dtype)
        overlay(frame, ui.stage_fx)
        big, small = self._size(frame, "title"), self._size(frame, "small")
        rows = [(CREDITS_TITLE, big, GOLD), (book_credit(state), small, INK), ("", small, INK)]
        rows += [(line, small, INK) for line in CREDITS_LINES]
        block = sum(self.cell(size)[1] + 8 for _text, size, _color in rows)
        rest = h // 2 - block // 2
        y = max(rest, h - int(min(ui.credits_rise, 4.0 * h) * h / 720))  # rising from below, then at rest
        for text, size, color in rows:
            if -40 < y < h:
                self._center(frame, text, w / 2, y, size, color)
            y += self.cell(size)[1] + 8
        if ui.credits_s >= CREDITS_HOLD_S:  # keys do nothing while the credits hold
            hint = self._controls(ui, "Press any key to keep fishing.", "Press A to keep fishing.")
            self._center(frame, hint, w / 2, int(h * 0.82), small, DIM)

    def _vignette(self, frame, state, vignette: dict, panel_top: int):
        """A story moment's card beside the dialogue: the book, or Bot's collar (V1-35). It fits
        between the HUD's panels and the dialogue panel, and is left out where there is no room:
        the bubbles carry the moment."""
        from .vignettes import bot_image, draw_book
        h, w = frame.shape[:2]
        y = int(h * 0.27 * getattr(self, "_text_scale", 1.0))  # below the HUD's top panels
        side = min(int(min(h * 0.32, w * 0.30)), panel_top - 20 - y)
        if side < 64:
            return None
        x = w - side - int(w * 0.04)
        self._panel(frame, x - 8, y - 8, side + 16, side + 16, 0.9)
        if vignette["kind"] == "book":
            draw_book(self, frame, x, y, side, side)
            return x, y, side
        reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
        size = max(64, side // 8 * 8)
        image = bot_image(vignette["kind"], vignette.get("detail"), vignette["t"], state, size, reduced=reduced)
        if image.shape[0] != side:
            from .imageops import resize_rgb
            image = resize_rgb(image, side, side)
        frame[y:y + side, x:x + side] = image
        return x, y, side

    def _sketch(self, frame, progress: float):
        """The Skipper's drawing of the Star-Whale on a page of the book, stroke by stroke (V1-35)."""
        from .finale import sketch_strokes
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.30), int(h * 0.27)
        x, y = w - pw - int(w * 0.04), int(h * 0.15)
        page = np.array([236, 226, 200], np.float32)
        frame[y:y + ph, x:x + pw] = (frame[y:y + ph, x:x + pw] * 0.12 + page * 0.88).astype(frame.dtype)
        pad = int(pw * 0.07)
        bw, bh = pw - pad * 2, ph - pad * 2
        width = max(2, int(h / 240))
        for stroke in sketch_strokes(progress):
            for (ax, ay), (bx, by) in zip(stroke, stroke[1:]):
                self._haul_segment(frame, x + pad + ax * bw, y + pad + ay * bh, x + pad + bx * bw,
                                   y + pad + by * bh, (58, 56, 64), width)

    def _dialogue(self, frame, state, ui):
        chat = ui.conversation
        if chat is None:
            return
        # A conversation may carry runtime nodes (greetings, host turn-ins, letters).
        node = (chat.node(ui.dialogue_content) if hasattr(chat, "node")
                else ui.dialogue_content.dialogue[chat.node_id])
        name = ui.dialogue_content.name(chat.npc_id)
        if chat.npc_id == "bot":
            from .botidentity import name as bot_name
            name = bot_name(state)  # Bot speaks a story scene in his own name (V1-34)
        h, w = frame.shape[:2]
        size = self._size(frame, "small")
        cw, ch = self.cell(size)
        margin = 16
        width = min(w - 24, 1000)
        # The speaker's portrait sits at the left when the frame has room (V1-29).
        from .catart import portrait_at
        side = min(176, max(96, h // 4))
        portrait = portrait_at(chat.npc_id, side) if w >= 640 else None
        inset = side + margin if portrait is not None else 0
        cols = max(8, (width - margin*2 - inset) // cw)
        from .botidentity import format_text
        lines = textwrap.wrap(format_text(node['text'], state), cols)
        choices = node.get('choices', [])
        rows = lines + ['']
        colors = [INK] * len(lines) + [DIM]
        for i, choice in enumerate(choices):
            label = f"{'>' if i == chat.selected else ' '} {i+1}. {format_text(choice['text'], state)}"
            wrapped = textwrap.wrap(label, cols)
            rows.extend(wrapped)
            colors.extend([GOLD if i == chat.selected else DIM] * len(wrapped))
        foot = self._controls(
            ui,
            "W/S or arrows choose / Enter Space C select / Esc leave / H Help",
            "D-pad choose / A select / B leave / RB continue",
        )
        if not choices:
            foot = self._controls(ui, "C / Enter / Space continue    Esc leave    H Help",
                                  "A continue    B leave    RB continue")
        if node.get('scene'):  # a story scene is read through; Esc does not leave it (V1-34)
            foot = (self._controls(ui, "W/S or arrows choose / Enter Space C select / H Help",
                                   "D-pad choose / A select / RB continue") if choices
                    else self._controls(ui, "C / Enter / Space continue    H Help", "A continue    RB continue"))
            if ui.stage_skip:  # a replay's staging can be skipped (V1-35)
                foot += self._controls(ui, "    Esc skip", "    B skip")
        footer = textwrap.wrap(foot, cols)
        height = (len(rows) + len(footer) + 2) * (ch + 3) + margin*2
        if portrait is not None:
            height = max(height, side + margin*2)
        x, y = (w-width)//2, h-height-12
        self._panel(frame, x, y, width, height, 0.96)
        if portrait is not None:
            self._blit_rgb(frame, portrait, x+margin, y+margin)
        self._text(frame, name, x+margin+inset, y+margin, size, GOLD, False)
        top = y+margin+(ch+3)*2
        for i, (line, color) in enumerate(zip(rows+footer, colors+[DIM]*len(footer))):
            self._text(frame, line, x+margin+inset, top+i*(ch+3), size, color, False)
        return y

    @staticmethod
    def _haul_sway(ui: UIState, reduced_motion: bool) -> float:
        if reduced_motion:
            return 0.0
        return math.sin((ui.haul_index + ui.haul_timer * 3.0) * 1.7) * 0.012

    def _haul_segment(self, frame, x0, y0, x1, y1, color, width=3, alpha=1.0):
        h, w = frame.shape[:2]
        pad = max(2, int(width) + 1)
        left = max(0, int(min(x0, x1)) - pad)
        right = min(w, int(max(x0, x1)) + pad + 1)
        top = max(0, int(min(y0, y1)) - pad)
        bottom = min(h, int(max(y0, y1)) + pad + 1)
        if left >= right or top >= bottom:
            return
        yy, xx = np.mgrid[top:bottom, left:right]
        dx, dy = float(x1 - x0), float(y1 - y0)
        denominator = dx * dx + dy * dy
        if denominator <= 1e-6:
            distance = np.hypot(xx - x0, yy - y0)
        else:
            t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / denominator, 0.0, 1.0)
            distance = np.hypot(xx - (x0 + t * dx), yy - (y0 + t * dy))
        mask = distance <= max(0.75, width * 0.5)
        region = frame[top:bottom, left:right]
        region[mask] = (region[mask].astype(np.float32) * (1.0 - alpha)
                        + np.asarray(color, np.float32) * alpha).astype(np.uint8)

    def _haul_oval(self, frame, cx, cy, rx, ry, color, alpha=1.0):
        h, w = frame.shape[:2]
        left, right = max(0, int(cx - rx)), min(w, int(cx + rx + 1))
        top, bottom = max(0, int(cy - ry)), min(h, int(cy + ry + 1))
        if left >= right or top >= bottom:
            return
        yy, xx = np.mgrid[top:bottom, left:right]
        mask = ((xx - cx) / max(1.0, rx)) ** 2 + ((yy - cy) / max(1.0, ry)) ** 2 <= 1.0
        region = frame[top:bottom, left:right]
        region[mask] = (region[mask].astype(np.float32) * (1.0 - alpha)
                        + np.asarray(color, np.float32) * alpha).astype(np.uint8)

    def _haul_ring(self, frame, cx, cy, rx, ry, color, alpha=0.75, thickness=2.0):
        h, w = frame.shape[:2]
        left, right = max(0, int(cx - rx - thickness)), min(w, int(cx + rx + thickness + 1))
        top, bottom = max(0, int(cy - ry - thickness)), min(h, int(cy + ry + thickness + 1))
        if left >= right or top >= bottom:
            return
        yy, xx = np.mgrid[top:bottom, left:right]
        distance = np.sqrt(((xx - cx) / max(1.0, rx)) ** 2
                           + ((yy - cy) / max(1.0, ry)) ** 2)
        mask = np.abs(distance - 1.0) <= thickness / max(1.0, min(rx, ry))
        region = frame[top:bottom, left:right]
        region[mask] = (region[mask].astype(np.float32) * (1.0 - alpha)
                        + np.asarray(color, np.float32) * alpha).astype(np.uint8)

    def _haul_splashes(self, frame, cx, cy, phase):
        for index in range(5):
            angle = (index * 2.399 + phase) % math.tau
            length = 14 + (index % 3) * 7
            x1 = cx + math.cos(angle) * length
            y1 = cy + math.sin(angle) * length - 8
            self._haul_segment(frame, cx + math.cos(angle) * 4,
                               cy + math.sin(angle) * 4, x1, y1,
                               (203, 226, 214), 2, 0.86)

    def _haul(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        if ui.check_line < 0 or ui.check_line >= len(state.lines):
            self._fill(frame, 0, 0, w, h, (7, 14, 15), 0.58)
            self._center(frame, "The line is gone.", w / 2, h * 0.46,
                         self._size(frame, "head"), INK)
            return
        line = state.lines[ui.check_line]
        if not line.hooks:
            return
        index = max(0, min(len(line.hooks) - 1, int(ui.haul_index)))
        hook = line.hooks[index]
        settings = state.v2.get("settings", {}) if isinstance(state.v2, dict) else {}
        reduced = bool(settings.get("reduced_motion", False))
        speed = settings.get("haul_speed", "normal")
        cadence = haul_cadence(state) * ui.haul_picnic_factor
        # A legendary's hook slows into its calm scene, then its book page (V1-37).
        from . import encounter, encounterview
        legend = encounter.is_legendary(hook.catch)
        scene = legend and ui.haul_phase == "encounter"
        beats = (encounter.look(ui.haul_phase_timer, reduced=reduced) if scene else
                 encounter.look(encounter.SCENE_S, reduced=True) if legend and ui.haul_phase == "card" else None)
        winched = legend and encounter.variant(state) == "winch"
        progress = (1.0 if ui.haul_phase == "surface" or beats is not None else
                    min(1.0, max(0.0, ui.haul_timer / cadence)))
        water_y = int(h * 0.61)
        cx = w * 0.5
        # The Zero-G Winch draws a legendary in without a sway (02 §9).
        sway = 0.0 if winched else self._haul_sway(ui, reduced) * w
        still = beats["still"] if beats else 0.0

        self._fill(frame, 0, 0, w, h, (6, 14, 16), 0.30)
        self._fill(frame, 0, water_y, w, h - water_y, (34, 84, 85), 0.26)
        if still > 0.0:
            # Looking over the side at the stilled lake: its water fills the view below the line.
            encounterview.still_water(self, frame, state, water_y, still)
        self._fill(frame, 0, water_y, w, max(1, int(h * 0.008)), (171, 190, 165), 0.24)
        ripple_phase = 0.0 if reduced else (ui.haul_timer * 3.7) % math.tau
        ripple_size = 28 if reduced else int(28 + 12 * (0.5 + 0.5 * math.sin(ripple_phase)))
        if still < 1.0:  # the ripples settle as the water stills
            self._haul_ring(frame, cx + sway, water_y + 8, ripple_size * 1.8,
                            max(7, ripple_size * 0.34), (204, 220, 194), 0.52 * (1.0 - still), 2.0)
            self._haul_ring(frame, cx + sway, water_y + 9, ripple_size,
                            max(5, ripple_size * 0.23), (221, 232, 201), 0.43 * (1.0 - still), 1.5)
        if still > 0.0:  # glassy water: long, flat highlights
            for k, (y_frac, span) in enumerate(((0.03, 0.70), (0.09, 0.52), (0.17, 0.36))):
                yy = water_y + int(h * y_frac)
                self._haul_segment(frame, w * (0.5 - span / 2), yy, w * (0.5 + span / 2), yy,
                                   (214, 228, 214), 1 + (k == 0), 0.20 * still)

        hook_y = water_y - int(progress * h * 0.18) - 8
        hand_y = int(h * 0.85)
        left_hand, right_hand = w * 0.20, w * 0.80
        tremble = beats["tremble"] if scene else 0.0
        if winched:
            # The winch at the gunwale takes the line straight up; the Skipper's paws rest.
            drum_x, drum_y = encounterview.winch(self, frame, cx, h)
            encounterview.hum_line(self, frame, drum_x, drum_y, cx + sway, hook_y,
                                   (229, 211, 169), 2, 0.95, tremble * 0.35, ui.haul_phase_timer)
            if scene:
                encounterview.hum_marks(self, frame, drum_x, drum_y, cx + sway, hook_y, beats["hum"])
        else:
            for hand_x, side in ((left_hand, -5), (right_hand, 5)):
                encounterview.hum_line(self, frame, hand_x, hand_y, cx + side + sway, hook_y,
                                       (62, 52, 42), 6, 0.9, tremble, ui.haul_phase_timer)
                encounterview.hum_line(self, frame, hand_x, hand_y - 1, cx + side + sway, hook_y,
                                       (229, 211, 169), 2, 0.95, tremble, ui.haul_phase_timer)
            if scene:
                encounterview.hum_marks(self, frame, right_hand, hand_y, cx + 5 + sway, hook_y, beats["hum"])

        # Paws stay planted while the line and hook move above them.
        paw_y = int(h * 0.87)
        for hand_x in (left_hand, right_hand):
            self._haul_oval(frame, hand_x, paw_y, w * 0.064, h * 0.047,
                            (183, 145, 112), 0.98)
            self._haul_oval(frame, hand_x - w * 0.022, paw_y - h * 0.046,
                            w * 0.018, h * 0.026, (198, 162, 128), 0.98)
            self._haul_oval(frame, hand_x, paw_y - h * 0.057,
                            w * 0.018, h * 0.026, (198, 162, 128), 0.98)
            self._haul_oval(frame, hand_x + w * 0.022, paw_y - h * 0.046,
                            w * 0.018, h * 0.026, (198, 162, 128), 0.98)

        self._haul_segment(frame, cx + sway, hook_y - 5, cx + sway,
                           hook_y + h * 0.045, (70, 58, 44), 4, 0.98)
        self._haul_segment(frame, cx + sway, hook_y + h * 0.045,
                           cx + 10 + sway, hook_y + h * 0.06,
                           (232, 217, 179), 3, 0.98)
        self._haul_segment(frame, cx + 10 + sway, hook_y + h * 0.06,
                           cx + 15 + sway, hook_y + h * 0.05,
                           (232, 217, 179), 3, 0.98)

        if beats is not None:
            # It surfaces beside the boat, not on the hook (02 §7.2).
            encounterview.fish(self, frame, state, hook.catch.species, beats,
                               ui.haul_phase_timer if scene else encounter.SCENE_S,
                               reduced=reduced, winched=winched, water_y=water_y)
        elif hook.catch is not None and not legend and (ui.haul_phase == "surface" or progress >= 0.70):
            sprite = _haul_mesh_sprite(hook.catch.species, state.lake_id, hook.catch.shiny)
            lift = int(h * (0.015 + 0.075 * progress))
            self._blit(frame, sprite, int(cx - sprite.shape[1] / 2),
                       water_y - lift - sprite.shape[0] // 2)
        if not reduced and not legend and (ui.haul_phase == "surface" or progress >= 0.82):
            self._haul_splashes(frame, cx + sway, water_y + 2,
                                (ui.haul_index * 0.77 + ui.haul_timer) % math.tau)

        head, body, small = (self._size(frame, key) for key in ("head", "body", "small"))
        if scene:
            # The scene is calm: no count, no speed and no prompts, only the letterbox and its name.
            from .staging import overlay
            overlay(frame, {"bars": beats["bars"]})
            encounterview.name(self, frame, hook.catch.species, beats)
            if encounter.presented(state.v2, hook.catch.species):
                skip = self._controls(ui, "Esc skip   Hold E hurries", "B skip   Hold A hurries")
                self._center(frame, skip, w / 2, int(h * 0.95), small, DIM)
            return
        title = f"HAULING  {index + 1:02d} / {len(line.hooks):02d}"
        self._text(frame, title, int(w * 0.055), int(h * 0.06), head, INK)
        if legend:
            result, result_color = "The line goes heavy.", GOLD  # its name waits for the scene
        elif hook.catch is not None:
            sp = SPECIES_BY_ID.get(hook.catch.species)
            hook_sp_name = sp.name if sp is not None else hook.catch.species.replace("_", " ").title()
            result = f"{hook_sp_name} on the line"
            result_color = GOLD
        elif hook.baited:
            result, result_color = "Bait still on", GOOD
        else:
            result, result_color = "Empty hook · bait taken", DIM
        self._center(frame, result, w / 2, int(h * 0.73), body, result_color)
        speed_label = {"normal": "Normal", "quick": "Quick", "instant": "Instant"}.get(speed, "Normal")
        self._text(frame, f"{speed_label} speed", int(w * 0.055), int(h * 0.13), small,
                   GOLD, shadow=False)
        foot = self._controls(ui, "Hold E 3×   Any key except E skips a card   Esc summary",
                              "Hold A 3×   A skips a card   B summary")
        self._center(frame, foot, w / 2, int(h * 0.95), small, INK)
        if ui.haul_phase == "card" and hook.catch is not None:
            if legend:
                encounterview.card(self, frame, state, ui, hook.catch)
            else:
                self._haul_card(frame, state, ui, hook.catch, body, small)

    def _haul_card(self, frame, state, ui: UIState, catch, body, small):
        h, w = frame.shape[:2]
        pw, ph = min(w - 24, 650), min(h - 24, 460)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._fill(frame, 0, 0, w, h, (4, 10, 12), 0.58)
        self._panel(frame, x, y, pw, ph, 0.98)
        self._center(frame, "A FISH SURFACES", w / 2, y + 18,
                     self._size(frame, "head"), GOLD)
        try:
            card = (self.fish_card_renderer(catch.species, catch.shiny)
                    if self.fish_card_renderer else None)
        except TypeError:
            card = self.fish_card_renderer(catch.species)
        if card is None:
            from .fishmesh import fish_card
            card = fish_card(catch.species, catch.shiny)
        max_w = max(120, min(512, pw - 40))
        max_h = max(64, min(256, ph - 170))
        image_w = min(max_w, max_h * 2)
        image_h = max(1, image_w // 2)
        image = card if card.shape[1] == image_w and card.shape[0] == image_h else \
            resize_rgb(card, image_w, image_h)
        image_x, image_y = (w - image_w) // 2, y + max(58, (ph - image_h) // 2 - 18)
        self._blit_rgb(frame, image, image_x, image_y)
        self._round_fill(frame, image_x + image_w - 144, image_y + 8, 132, 30,
                         (45, 49, 38), 0.94)
        if catch.shiny:
            ribbon = "SHINY  *"
            ribbon_color = GOLD
        elif not ui.haul_badge_enabled:
            ribbon, ribbon_color = "CATCH", INK
        else:
            count_before = int(ui.haul_counts_before.get(catch.species, 0))
            line = state.lines[ui.check_line] if 0 <= ui.check_line < len(state.lines) else None
            hauled = (sum(1 for hook in line.hooks[:ui.haul_index + 1]
                          if hook.catch is not None and hook.catch.species == catch.species)
                      if line else 1)
            count = count_before + hauled
            if count == 1:
                ribbon, ribbon_color = "NEW!", GOLD
            elif count in BOOK_STAGE_UP_COUNTS:
                ribbon, ribbon_color = "STAGE UP!", GOOD
            else:
                ribbon, ribbon_color = "CATCH", INK
        self._center(frame, ribbon, image_x + image_w - 78, image_y + 13,
                     small, ribbon_color)
        sp = SPECIES_BY_ID.get(catch.species)
        sp_name = sp.name if sp is not None else catch.species.replace("_", " ").title()
        quality = quality_name(catch.quality)
        detail = f"{weight_string(catch.weight)}  ·  {sp_name}  ·  {quality}"
        self._center(frame, detail, w / 2, image_y + image_h + 12, body, INK)
        if catch.shiny:
            self._center(frame, "SHINY CATCH", w / 2, image_y + image_h + 12 + self.cell(body)[1],
                         small, GOLD)
        foot = self._controls(ui, "Any key except E continues   Hold E speeds the haul",
                              "A continues   Hold A speeds the haul")
        self._center(frame, foot, w / 2, y + ph - self.cell(small)[1] - 10, small, DIM)

    # --- primitives -----------------------------------------------------

    def _actual_size(self, size: int) -> int:
        return max(8, int(round(size * getattr(self, "_text_scale", 1.0))))

    def _font_family(self, family: str) -> str:
        if getattr(self, "_dyslexia_font", False):
            return "dyslexia"
        return family

    def _render(self, text: str, size: int, color, family="mono"):
        return self.text.render(text, self._actual_size(size), color,
                                self._font_family(family))

    def _size(self, frame, kind: str) -> int:
        h = frame.shape[0]
        body = max(14, min(28, h // 34))
        if kind == "title":
            return max(28, min(64, h // 12))
        if kind == "small":
            return max(12, body - 2)
        if kind == "head":
            return body + 4
        return body

    def _blit(self, dst, src, x, y):
        h, w = src.shape[:2]
        dh, dw = dst.shape[:2]
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(dw, int(x) + w), min(dh, int(y) + h)
        if x0 >= x1 or y0 >= y1:
            return
        patch = src[y0 - int(y): y0 - int(y) + (y1 - y0), x0 - int(x): x0 - int(x) + (x1 - x0)]
        alpha = patch[:, :, 3:4].astype(np.float32) * (1.0 / 255.0)
        if float(alpha.max()) <= 0:
            return
        rgb = patch[:, :, :3].astype(np.float32)
        region = dst[y0:y1, x0:x1].astype(np.float32)
        dst[y0:y1, x0:x1] = np.clip(region * (1.0 - alpha) + rgb * alpha, 0, 255).astype(np.uint8)

    @staticmethod
    def _blit_rgb(dst, src, x, y):
        h, w = src.shape[:2]
        dh, dw = dst.shape[:2]
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(dw, int(x) + w), min(dh, int(y) + h)
        if x0 < x1 and y0 < y1:
            dst[y0:y1, x0:x1] = src[y0 - int(y):y1 - int(y), x0 - int(x):x1 - int(x)]

    def _fill(self, dst, x, y, w, h, rgb, alpha: float):
        dh, dw = dst.shape[:2]
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(dw, int(x) + int(w)), min(dh, int(y) + int(h))
        if x0 >= x1 or y0 >= y1:
            return
        if alpha >= 1.0:
            dst[y0:y1,x0:x1] = rgb
            return
        region = dst[y0:y1, x0:x1].astype(np.float32)
        region *= 1.0-alpha
        region += np.array(rgb,np.float32)*alpha
        dst[y0:y1,x0:x1] = region.astype(np.uint8)

    def _panel(self, dst, x, y, w, h, alpha=0.82):
        self._round_fill(dst, x+2, y+4, w, h, (5, 10, 10), 0.20)
        self._round_fill(dst, x, y, w, h, (17, 31, 32), alpha)
        self._fill(dst, x+10, y, w-20, 1, GOLD, 0.34)

    def _round_fill(self, dst, x, y, w, h, rgb, alpha):
        dh,dw = dst.shape[:2]
        x,y,w,h = int(x),int(y),int(w),int(h)
        x0,y0,x1,y1 = max(0,x),max(0,y),min(dw,x+w),min(dh,y+h)
        if x0>=x1 or y0>=y1:
            return
        r = min(8,w/2,h/2)
        r = int(r)
        # Only the tiny corner patches need distance fields. The large
        # interior can use one cheap blend, keeping menus quick on the CPU.
        self._fill(dst,x+r,y,w-r*2,h,rgb,alpha)
        self._fill(dst,x,y+r,r,h-r*2,rgb,alpha)
        self._fill(dst,x+w-r,y+r,r,h-r*2,rgb,alpha)
        for cx,cy in ((x,y),(x+w-r,y),(x,y+h-r),(x+w-r,y+h-r)):
            ax,ay,bx,by = max(0,cx),max(0,cy),min(dw,cx+r),min(dh,cy+r)
            if ax>=bx or ay>=by:
                continue
            yy = np.arange(ay,by,dtype=np.float32)[:,None]
            xx = np.arange(ax,bx,dtype=np.float32)[None,:]
            dx = np.maximum(np.maximum(x+r-xx,xx-(x+w-r-1)),0)
            dy = np.maximum(np.maximum(y+r-yy,yy-(y+h-r-1)),0)
            a = np.clip(r+0.5-np.hypot(dx,dy),0,1)[...,None]*alpha
            region = dst[ay:by,ax:bx]
            region[:] = (region*(1-a)+np.asarray(rgb,np.float32)*a).astype(np.uint8)

    def _text(self, frame, s: str, x, y, size, color, shadow=True, family="mono") -> int:
        if not s:
            return 0
        if shadow:
            shade = self._render(s, size, (8, 12, 10), family)
            self._blit(frame, shade, x + 1, y + 1)
        img = self._render(s, size, color, family)
        self._blit(frame, img, x, y)
        return img.shape[1]

    def _measure(self, s, size, family="sans"):
        return self._render(s, size, INK, family).shape[1]

    def _center(self, frame, s, x, y, size, color, family="sans"):
        return self._text(frame,s,x-self._measure(s,size,family)/2,y,size,color,family=family)

    def _trim(self, s: str, size: int, width: int) -> str:
        cw, _ch = self.cell(size)
        n = max(1, int(width) // cw)
        if len(s) <= n:
            return s
        return s[: max(1, n - 2)] + ".."

    @staticmethod
    def _controls(ui: UIState, keyboard: str, gamepad: str) -> str:
        return gamepad if ui.input_device == "gamepad" else keyboard

    # --- play ------------------------------------------------------------

    def _hud(self, frame, state, ui: UIState, *, interactions=True):
        h, w = frame.shape[:2]
        scale = getattr(self, "_text_scale", 1.0)
        unit = h / 720 * scale
        size,small = max(16,int(22*unit/scale)),max(11,int(12*unit/scale))
        m = max(12,int(26*unit))
        from . import calendar
        weather = calendar.weather_at(state).replace("_", " ").upper()
        clock = calendar.day_name(state.game_minutes)[:3] + " " + clock_string(state.game_minutes)
        self._panel(frame,m,m,int(205*unit)+34,int(92*unit)+10,0.66)
        self._text(frame,self.world.name.upper(),m+16,m+int(11*unit),small,GOLD,False,"sans")
        self._text(frame,clock,m+16,m+int(31*unit),max(22,int(30*unit)),INK,False,"serif")
        meta = weather
        if self.world.id == "nebula":
            # The Lagoon names its bands Rising, Bright, Fading and Deep (03 §1.6).
            from .data import hour_of_day
            from .nebula import band_label
            meta = band_label(hour_of_day(state.game_minutes)).upper() + "  /  " + weather
        if state.time_scale!=1:
            meta += f"  /  {state.time_scale}x" + ("" if state.fast_ok() else " held")
        self._text(frame,meta,m+16,m+int(71*unit),small,DIM,False,"sans")
        zone = self.world.zone_name(self.world.zone_at(state.x, state.z))
        zone_width = self._measure(zone,size+4,"serif")
        rx = w-m-max(int(194*unit),zone_width+32)
        rw = w-m-rx
        self._panel(frame,rx,m,rw,int(140*unit)+10,0.66)
        self._text(frame,"ON THE WATER",rx+16,m+int(11*unit),small,GOLD,False,"sans")
        self._text(frame,zone,rx+16,m+int(31*unit),size+4,INK,False,"serif")
        bearing = ("N","NE","E","SE","S","SW","W","NW")[int((state.yaw%(2*np.pi))/(np.pi/4)+0.5)%8]
        move = "ANCHORED" if state.anchored else f"{abs(state.speed)*2.23694:.1f} MPH"
        navigation = f"{bearing}  /  {move}"
        if state.finder:
            navigation += f"  /  {float(self.world.depth(state.x,state.z))*3.28084:.0f} FT"
        self._text(frame,navigation,rx+16,m+int(71*unit),small,DIM,False,"sans")
        lever = state.throttle_setting
        gear = "IDLE" if abs(lever)<0.005 else ("FWD" if lever>0 else "REV")
        percent = round(abs(lever)/(1.0 if lever>=0 else 0.45)*100)
        if state.boat_id=="rowboat":
            power = ("E-MOTOR" if state.rowboat_trolling_motor
                     and state.rowboat_battery_kwh>0 else "OARS")
            throttle = f"{power}  IDLE" if gear=="IDLE" else f"{power}  {gear} {percent}%"
        elif not state.boat.fuelled:
            power = {"paddle":"PADDLE","oars":"OARS","starlight":"GLIDE"}[state.boat.power]
            throttle = f"{power}  IDLE" if gear=="IDLE" else f"{power}  {gear} {percent}%"
        else:
            throttle = "THROTTLE  IDLE" if gear=="IDLE" else f"THROTTLE  {gear} {percent}%"
        self._text(frame,throttle,rx+16,m+int(91*unit),small,
                   DIM if gear=="IDLE" else GOLD,False,"sans")
        if state.boat_id=="rowboat":
            power = (f"BATTERY  {state.rowboat_battery_kwh:.1f} / {ROWBOAT_BATTERY_KWH:.0f} kWh"
                     if state.rowboat_trolling_motor else "ROW POWER  OARS READY")
            low_power = (state.rowboat_trolling_motor
                         and state.rowboat_battery_kwh<ROWBOAT_BATTERY_KWH*0.15)
            self._text(frame,power,rx+16,m+int(111*unit),small,WARN if low_power else DIM,False,"sans")
        elif not state.boat.fuelled:
            self._text(frame,"NO FUEL NEEDED",rx+16,m+int(111*unit),small,DIM,False,"sans")
        else:
            fuel = f"FUEL  {state.fuel:.1f} / {state.boat.tank:.0f} L"
            self._text(frame,fuel,rx+16,m+int(111*unit),small,
                       WARN if state.fuel<state.boat.tank*0.15 else DIM,False,"sans")
        if state.boat.power=="sail":
            wind,wind_speed = wind_at(state.game_minutes+state.minute_acc, state)
            coming_from = (wind+np.pi)%(2*np.pi)
            direction = ("N","NE","E","SE","S","SW","W","NW")[int(coming_from/(np.pi/4)+0.5)%8]
            sail = "SAIL UP" if state.sail_raised else "SAIL DOWN"
            self._text(frame,f"{sail} / {direction} {wind_speed*1.94384:.0f} KT",rx+16,m+int(131*unit),small,GOLD,False,"sans")
        elif state.bot_phase != "home":
            from .bot import status as bot_status
            from .sim import hour_of_day
            from .calendar import weather_at
            cold = bottools.scanner_text(state.owns_tool("thermo_scanner"), self.world.id,
                                         hour_of_day(state.game_minutes), weather_at(state))
            report = " · ".join(part for part in (bot_status(state), cold) if part)
            self._text(frame, self._trim(report, small, rw - 32), rx+16, m+int(131*unit), small, GOLD, False, "sans")
        else:
            from .sim import fishing_hint, hour_of_day
            from .calendar import weather_at
            cold = bottools.scanner_text(state.owns_tool("thermo_scanner"), self.world.id,
                                         hour_of_day(state.game_minutes), weather_at(state))
            parts = [part for part in (cold, fishing_hint(state, self.world)) if part]
            label = self._trim(" · ".join(parts), small, rw - 32) if parts else state.boat.name
            self._text(frame, label, rx+16, m+int(131*unit), small, GOLD if parts else DIM, False, "sans")
        sw,stat_h = int(208*unit)+32,int(106*unit)+12
        sx,sy = w-m-sw,h-m-stat_h
        self._panel(frame,sx,sy,sw,stat_h,0.80)
        self._text(frame,"ABOARD",sx+16,sy+12,small,GOLD,False,"sans")
        self._text(frame,dollars(state.money),sx+sw-self._measure(dollars(state.money),size,"serif")-16,
                   sy+7,size,GOLD,False,"serif")
        well = f"Livewell   {state.well_load():.0f} / {state.well_cap():.0f} lb"
        self._text(frame,well,sx+16,sy+int(38*unit),small+1,INK,False,"sans")
        self._fill(frame,sx+16,sy+int(64*unit),sw-32,3,(78,94,84),0.8)
        fill = min(1,state.well_load()/max(1,state.well_cap()))
        self._fill(frame,sx+16,sy+int(64*unit),int((sw-32)*fill),3,GOLD,1)
        bait = BAIT_BY_ID[state.preferred_bait].name
        detail = f"{len(state.lines)} lines out  /  {len(state.held)} aboard"
        self._text(frame,detail,sx+16,sy+int(76*unit),small,DIM,False,"sans")
        self._text(frame,f"{bait}  {state.bait.get(state.preferred_bait,0)}",
                   sx+16,sy+int(95*unit),small,DIM,False,"sans")
        lines_h = self._lines_panel(frame, state, sx, sy - 8, sw, small)
        map_h = self._minimap(frame, state, m, h - m, ui.input_device)
        if not interactions:
            return
        npc = nearby_npc(state)
        if npc is None and ui.settle_prompt:
            # Settle In (V1-34) uses the hail key while no cat is in range.
            hail = "RB" if ui.input_device == "gamepad" else "C"
            label = ui.settle_prompt.replace("{key}", hail)
            px, py = m, h - m - max(map_h, stat_h + lines_h) - 34 - 8
            self._panel(frame, px, py, self._measure(label, small) + 32, 34)
            self._text(frame, label, px+16, py+7, small, INK, False, "sans")
        if npc is not None:
            hail = "RB" if ui.input_device == "gamepad" else "C"
            label = f"{hail}  Hail {npc.name}"
            px, py = m, h - m - max(map_h, stat_h + lines_h) - 34 - 8
            self._panel(frame, px, py, self._measure(label, small) + 56, 34)
            # A small procedural paw wave avoids a font-dependent emoji.
            self._round_fill(frame, px+9, py+16, 14, 10, GOLD, 1.0)
            for dx, dy in ((7, 9), (13, 5), (20, 6), (26, 11)):
                self._round_fill(frame, px+dx, py+dy, 5, 6, GOLD, 1.0)
            self._text(frame, label, px+38, py+7, small, INK, False, "sans")
        prompt = _prompt_for_device(state.prompt(self.world), ui.input_device)
        if prompt:
            pw = self._measure(prompt,small+2)+32
            px,py = (w-pw)//2,h-m-max(map_h,stat_h+lines_h)-int(35*unit)-8
            if npc is not None:
                py -= 42
            self._panel(frame,px,py,pw,int(30*unit)+8,0.72)
            self._text(frame,prompt,px+16,py+5,small+2,INK,False,"sans")
        if ui.input_device == "gamepad":
            hint = "LS drive  LT/RT lever  Y Bot / hold Nap  X Set  A Check  RB Hail  Back Chart  Start Pause"
        else:
            hint = "B Bot  Shift Idle Q Sail  F Set  E Landing  Z Nap  C Hail  H Help" if state.boat.power=="sail" else "B Bot  Shift Idle  F Set  E Check  R Tow  Z Nap  C Hail  H Help"
        hint_w = self._measure(hint,small)
        hint_h = small + 16
        hint_x, hint_y = (w-hint_w-24)//2, h-m-hint_h
        self._panel(frame,hint_x,hint_y,hint_w+24,hint_h,0.88)
        self._center(frame,hint,w/2,hint_y+6,small,INK)

    def _minimap(self, frame, state, margin, bottom, input_device="keyboard") -> int:
        chart = self.world.map_small
        w = frame.shape[1]
        mw = max(96, int(w * 0.14))
        mh = max(64, int(mw * chart.shape[0] / chart.shape[1]))
        x = margin
        y = bottom - mh - 7
        scaled = _fit(chart, mw, mh)
        self._panel(frame, x, y-28, mw+16, mh+35, 0.80)
        self._text(frame,"LAKE CHART",x+8,y-21,max(10,frame.shape[0]//65),GOLD,False,"sans")
        size = max(10,frame.shape[0]//65)
        shortcut = "BACK" if input_device == "gamepad" else "TAB"
        self._text(frame,shortcut,x+mw-22,y-21,size,DIM,False,"sans")
        x += 8
        frame[y:y + mh, x:x + mw] = scaled
        for line in state.lines:
            self._seg(frame, line.x0, line.z0, line.x1, line.z1, x, y, mw, mh, self._line_color(line))
            if comfort.has_buff(state, "glow_buoys"):
                for bx, bz in line.buoys():
                    bu, bv = self.world.map_pixel(bx, bz, mw, mh)
                    self._dot(frame, x + bu, y + bv, 3, GOLD)
        self._plot_invitation(frame, state, x, y, mw, mh)
        self._plot_trinidad_cove(frame, x, y, mw, mh)
        self._plot_npcs(frame, state, x, y, mw, mh)
        self._plot_boat(frame, state, x, y, mw, mh, radius=3)
        self._plot_bot(frame, state, x, y, mw, mh)
        return mh + 35

    def _line_color(self, line):
        if any(h.catch is not None and h.catch.age >= 9.0 for h in line.hooks):
            return WARN
        if line.fish_on():
            return (232, 176, 72)
        return (126, 168, 146)

    def _lines_panel(self, frame, state, right, above, width, size) -> int:
        """Height added above the aboard card, including the gap."""
        if not state.lines:
            return 0
        row_h = size + 6
        height = 12 + row_h * (len(state.lines) + 1)
        y = above - height
        self._panel(frame, right, y, width, height, 0.80)
        self._text(frame, "LINES", right + 16, y + 8, size, GOLD, False, "sans")
        for i, line in enumerate(state.lines):
            fish = line.fish_on()
            tired = any(h.catch is not None and h.catch.age >= 9.0 for h in line.hooks)
            if tired:
                status, color = "TIRED", WARN
            elif fish:
                status, color = f"{fish} up", GOLD
            else:
                status, color = "soak", DIM
            place = self._trim(self.world.zone_name(line.zone), size, width * 0.62)
            ry = y + 8 + row_h * (i + 1)
            self._text(frame, f"{i + 1}  {place}", right + 16, ry, size, color, False, "sans")
            self._text(frame, status, right + width - 16 - len(status) * self.cell(size)[0], ry, size, color, False, "sans")
        return height + 8

    def _map(self, frame, state, ui: UIState, big=True):
        h, w = frame.shape[:2]
        self._fill(frame, 0, 0, w, h, (8, 10, 8), 0.45)
        chart = self.world.map_rgb
        mw = int(w * 0.62)
        mh = int(mw * chart.shape[0] / chart.shape[1])
        if mh > int(h * 0.78):
            mh = int(h * 0.78)
            mw = int(mh * chart.shape[1] / chart.shape[0])
        x = (w - mw) // 2
        y = int(h * 0.10)
        scaled = _fit(chart, mw, mh)
        self._panel(frame, x - 8, y - 8, mw + 16, mh + 16, 0.88)
        frame[y:y + mh, x:x + mw] = scaled
        for line in state.lines:
            color = self._line_color(line)
            self._seg(frame, line.x0, line.z0, line.x1, line.z1, x, y, mw, mh, color)
            if comfort.has_buff(state, "glow_buoys"):
                for bx, bz in line.buoys():
                    bu, bv = self.world.map_pixel(bx, bz, mw, mh)
                    self._dot(frame, x + bu, y + bv, 4, GOLD)
            n = max(1, len(line.hooks))
            for i, hook in enumerate(line.hooks):
                t = (i + 0.5) / n
                hx = line.x0 + (line.x1 - line.x0) * t
                hz = line.z0 + (line.z1 - line.z0) * t
                if hook.catch is not None and hook.catch.age >= 9.0:
                    dot = WARN
                elif hook.catch is not None:
                    dot = (255, 214, 120)
                elif hook.baited:
                    dot = (186, 214, 196)
                else:
                    dot = (90, 104, 98)
                u, v = self.world.map_pixel(hx, hz, mw, mh)
                self._dot(frame, x + u, y + v, 2 if hook.catch is not None else 1, dot)
        self._plot_habitats(frame, x, y, mw, mh)
        sonar_cells = sonar.overlay(state, self.world)
        self._plot_sonar(frame, sonar_cells, x, y, mw, mh)
        self._plot_trinidad_cove(frame, x, y, mw, mh, labels=True)
        self._plot_invitation(frame, state, x, y, mw, mh)
        self._plot_npcs(frame, state, x, y, mw, mh, labels=True)
        self._plot_boat(frame, state, x, y, mw, mh, radius=4)
        self._plot_bot(frame, state, x, y, mw, mh)
        size = self._size(frame, "small")
        self._text(frame, self.world.name, x, y - self.cell(size)[1] - 14, size, INK)
        legend = "Fish gold   soak green   tired red   NPC blue"
        if sonar_cells:
            legend += "   sonar depth bands"
        self._text(frame, legend, x, y + mh + 12, size, DIM, shadow=False)
        close_hint = self._controls(ui, "Tab closes the chart", "B closes the chart")
        self._text(frame, close_hint, x + mw - 20 * self.cell(size)[0], y + mh + 14 + self.cell(size)[1], size, DIM, shadow=False)

    def _plot_sonar(self, frame, cells, x, y, mw, mh):
        for cell in cells:
            u, v = self.world.map_pixel(cell.x, cell.z, mw, mh)
            self._dot(frame, x + u, y + v, 1, SONAR_BAND_COLORS[min(cell.band, len(SONAR_BAND_COLORS) - 1)])

    def _plot_invitation(self, frame, state, x, y, mw, mh):
        mark = getattr(state, "v2", {}).get("calendar", {}).get("invitation_mark")
        if (not isinstance(mark, dict) or mark.get("lake_id") != self.world.id
                or comfort.number(mark.get("until_game_minutes")) <= state.game_minutes):
            return
        if any(type(mark.get(key)) not in (int, float) or not math.isfinite(mark[key]) for key in ("x", "z")):
            return
        u, v = self.world.map_pixel(mark["x"], mark["z"], mw, mh)
        self._dot(frame, x + u, y + v, 5, GOLD)
        self._dot(frame, x + u, y + v, 2, INK)

    def _plot_habitats(self, frame, x, y, mw, mh):
        size = self._size(frame, "small")
        occupied = []
        # A Nebula current lane is a chain of circles; name it once, mid-lane.
        chains = {}
        for zone, cx, cz, _radius in self.world.zones:
            chains.setdefault(zone, []).append((cx, cz))
        labels = [(zone, *points[len(points)//2], None) for zone, points in chains.items()]
        for zone, cx, cz, _radius in labels:
            # Preserve the established charts apart from Briar's new passage.
            if not self.world.placeholder and not self.world.generated and zone != "reeds":
                continue
            u, v = self.world.map_pixel(cx, cz, mw, mh)
            label = self._trim(self.world.zone_name(zone), size, mw * 0.42)
            width = len(label) * self.cell(size)[0]
            tx = max(x, min(x + u + 6, x + mw - width))
            ty = max(y, min(y + v + 6, y + mh - self.cell(size)[1]))
            if self.world.generated:
                width = self._measure(label, size, "mono")
                height = self.cell(size)[1]
                # Search near the habitat first. A bounded chart-row fallback
                # keeps long canonical names inside the map and off each other.
                offsets = (6, -height-6, height+8, -2*height-10, 2*height+12,
                           -3*height-14, 3*height+16)
                candidates = [(x+u+dx, y+v+dy) for dy in offsets
                              for dx in (6, -width-6, -width/2)]
                candidates.extend((px, py) for py in range(int(y), int(y+mh-height)+1, height+4)
                                  for px in (x, x+mw-width, x+(mw-width)/2))
                for px, py in candidates:
                    tx = max(x, min(x+mw-width, px))
                    ty = max(y, min(y+mh-height, py))
                    box = (tx, ty, tx+width, ty+height)
                    if all(box[2]+4 < old[0] or old[2]+4 < box[0]
                           or box[3]+3 < old[1] or old[3]+3 < box[1] for old in occupied):
                        break
                occupied.append(box)
            self._text(frame, label, tx, ty, size, INK)

    def _plot_trinidad_cove(self, frame, x, y, mw, mh, labels=False):
        if self.world.id != "cedar":
            return
        anchor = self.world.anchors.get("cedar:trinidad_cove")
        if anchor is None:
            return
        u, v = self.world.map_pixel(anchor.x, anchor.z, mw, mh)
        color = (240, 198, 112)
        self._dot(frame, x + u, y + v, 3 if labels else 2, color)
        if labels:
            size = self._size(frame, "small")
            label = anchor.name
            width = len(label) * self.cell(size)[0]
            tx = max(x, min(x + u + 7, x + mw - width))
            ty = max(y, min(y + v + 6, y + mh - self.cell(size)[1]))
            self._text(frame, label, tx, ty, size, color)

    def _plot_npcs(self, frame, state, x, y, mw, mh, labels=False):
        from .actors import roster
        color = (128, 206, 240)
        cats = roster()
        for npc in state.npcs:
            if npc.anchor.lake_id != self.world.id:
                continue
            u, v = self.world.map_pixel(npc.anchor.x, npc.anchor.z, mw, mh)
            # Each pin wears its cat's coat, ringed so pale coats read on the chart (V1-29).
            radius = 3 if labels else 2
            row = cats.get(npc.id)
            pin = (tuple(int(c * 255 + 0.5) for c in row["appearance"]["colors"]["base"])
                   if row is not None else color)
            self._dot(frame, x + u, y + v, radius + 1, (28, 34, 38))
            self._dot(frame, x + u, y + v, radius, pin)
            if labels:
                size = self._size(frame, "small")
                label = self._trim(npc.name, size, mw)
                width = len(label) * self.cell(size)[0]
                tx = max(x, min(x + u + 6, x + mw - width))
                ty = max(y, min(y + v + 6, y + mh - self.cell(size)[1]))
                self._text(frame, label, tx, ty, size, color)

    def _plot_boat(self, frame, state, x, y, mw, mh, radius):
        u, v = self.world.map_pixel(state.x, state.z, mw, mh)
        px, py = x + u, y + v
        self._dot(frame, px, py, radius, (236, 224, 180))
        fx, fz = np.sin(state.yaw), np.cos(state.yaw)
        # North is up, +z maps toward smaller v.
        span = radius + 5
        self._dot(frame, int(px + fx * span), int(py - fz * span), 2, (232, 196, 110))

    def _plot_bot(self, frame, state, x, y, mw, mh):
        if state.bot_phase == "home":
            return
        u, v = self.world.map_pixel(state.bot_x, state.bot_z, mw, mh)
        self._dot(frame, x + u, y + v, 2, (255, 148, 48))

    def _seg(self, frame, x0, z0, x1, z1, ox, oy, mw, mh, rgb):
        u0, v0 = self.world.map_pixel(x0, z0, mw, mh)
        u1, v1 = self.world.map_pixel(x1, z1, mw, mh)
        steps = max(abs(u1 - u0), abs(v1 - v0), 1)
        for i in range(steps + 1):
            t = i / steps
            self._dot(frame, int(ox + u0 + (u1 - u0) * t), int(oy + v0 + (v1 - v0) * t), 1, rgb)

    def _dot(self, frame, x, y, r, rgb):
        h, w = frame.shape[:2]
        x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
        x1, y1 = min(w, int(x) + r + 1), min(h, int(y) + r + 1)
        if x0 >= x1 or y0 >= y1:
            return
        frame[y0:y1, x0:x1] = np.array(rgb, np.uint8)

    def _toasts(self, frame, state, input_device="keyboard"):
        if not state.toasts:
            return
        size = self._size(frame, "small")
        _cw, ch = self.cell(size)
        w = frame.shape[1]
        y = max(8, frame.shape[0] // 7)
        for raw_text, _ttl in state.toasts[-3:]:
            text = _toast_for_device(raw_text, input_device)
            if raw_text == "Shall we add that?":
                text += " Hold Y to read." if input_device == "gamepad" else " J reads the page."
                text = self._trim(text, size, w - 32)
            tw = len(text) * _cw + 16
            x = (w - tw) // 2
            self._panel(frame, x, y, tw, ch + 8, 0.72)
            self._text(frame, text, x + 8, y + 3, size, INK)
            y += ch + 12

    # --- menus -----------------------------------------------------------

    def _title(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        # A translucent gradient preserves the lake while giving the title air.
        yy = np.arange(h,dtype=np.float32)[:,None,None]/h
        xx = np.arange(w,dtype=np.float32)[None,:,None]/w
        alpha = np.clip((yy-0.30)*0.78,0,0.58)+np.clip(0.48-xx,0,0.32)
        frame[:] = (frame*(1-alpha)+np.array([10,25,27],np.float32)*alpha).astype(np.uint8)
        title = max(38,min(96,int(h*0.117)))
        body = max(15,int(h/38))
        small = max(11,int(h/60))
        title_h, body_h, small_h = (self._actual_size(value)
                                    for value in (title, body, small))
        gap_scale = getattr(self, "_text_scale", 1.0)
        x,y = int(w*0.075),int(h*(0.20 if h<480 else 0.43))
        self._text(frame,"A   T R O T L I N E   L A K E",x,y,small,GOLD,False,"sans")
        self._text(frame,GAME_TITLE,x,y+small_h+10*gap_scale,title,INK,True,"serif")
        self._text(frame,"Set your lines. Stay a while.",x,y+title_h+small_h+20*gap_scale,body,DIM,False,"sans")
        options = title_options(ui.has_save)
        ui.title_i %= len(options)
        y2 = y+title_h+small_h+body_h+(30 if h<480 else 48)*gap_scale
        if ui.confirm_new:
            msg = "New morning? The save on disk stays until you overwrite it."
            self._text(frame,self._trim(msg,small,w-x*2),x,y2,small,WARN,False)
            hint = self._controls(ui, "Enter chooses a mode     Esc cancels",
                                  "A chooses a mode     B cancels")
            self._text(frame,hint,x,y2+small_h+12*gap_scale,small,DIM,False,"sans")
            return
        for i, label in enumerate(options):
            oy = y2+i*(body_h+27*gap_scale)
            from .botidentity import name as bot_name
            display = label + ' · ' + bot_name(state) if label == 'Continue' else label
            button_w = min(w - x * 2, max(210, int(w * .21), self._measure(display, body, 'sans') + 90 * gap_scale))
            option_size = body
            while option_size > 9 and self._measure(display, option_size, 'sans') > button_w - 80 * gap_scale:
                option_size -= 1
            if i==ui.title_i:
                self._round_fill(frame,x,oy-4*gap_scale,button_w,body_h+24*gap_scale,GOLD,0.95)
                self._text(frame,display,x+15,oy+4,option_size,(22,39,39),False,"sans")
                select = "A" if ui.input_device == "gamepad" else "ENTER"
                self._text(frame,select,x+button_w-55*gap_scale,oy+9*gap_scale,small,(42,56,50),False,"sans")
            else:
                self._text(frame,display,x+15,oy+4,option_size,INK,False,"sans")
        controls = self._controls(ui, "H  Field guide     W / S  Choose",
                                  "D-pad / stick choose     A select")
        self._text(frame,controls,x,h-small_h-24*gap_scale,small,DIM,False,"sans")
        mark = "ONE LAKE. NO HURRY."
        self._text(frame,mark,w-x-self._measure(mark,small),h-small_h-24*gap_scale,small,DIM,False,"sans")

    def _comfort_lines(self, value, size, width):
        cache = getattr(self, "_comfort_line_cache", None)
        if cache is None:
            cache = self._comfort_line_cache = OrderedDict()
        key = (value, self._actual_size(size), self._font_family("sans"), width)
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        lines = []
        for paragraph in value.splitlines():
            line = ""
            for word in paragraph.split():
                trial = word if not line else line + " " + word
                if line and self._measure(trial, size) > width:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
        line_height = max(self._render(line, size, DIM, "sans").shape[0] for line in lines) + 4
        if len(cache) >= 64:
            cache.popitem(last=False)
        cache[key] = tuple(lines), line_height
        return cache[key]

    def _comfort(self, frame, state, ui):
        if ui.mode == "needs" and comfort.mode(state.v2) != "old_salt":
            return
        h, w = frame.shape[:2]
        margin = max(12, min(28, w // 35))
        x, y, width, height = margin, margin, w - 2 * margin, h - 2 * margin
        buttons = comfort_controls((w, h))
        if ui.mode == "new_mode":
            title, labels, selected = "Choose your pace", ("Cozy", "Old Salt"), ui.new_mode_i
            body = ("Cozy: free tow and no needs penalties. Naps are always optional.\n"
                    "Old Salt: Drowsy at 16 hours awake; a safe catnap after 20. Peckish after 24 hours slows boats. Tow: $25 + 2% of boat price, capped by cash.\n"
                    "Change mode any time in Settings.")
        elif ui.mode == "needs":
            energy = ui.needs_kind == "energy"
            title = "A little rest?" if energy else "A bite to eat?"
            body = ("Bot: Your eyes are getting heavy. Hauling is 25% slower while Drowsy. Shall we anchor safely for a two-hour catnap?"
                    if energy else "Bot: A meal would be nice. While Peckish, the boat runs 20% slower. You can still steer, haul and call the tow boat.")
            eat = state.v2["pantry"].get("kibble", 0) > 0
            labels = ("Anchor & nap" if energy else "Eat Kibble Tin" if eat else "Keep going", "Later (30 min)")
            selected = ui.comfort_i
        else:
            progress = 1 - max(0., min(1., ui.nap_timer / 3))
            reduced = state.v2["settings"].get("reduced_motion", False)
            warm = 0. if reduced else abs(1 - 2 * progress)
            tint = (int(15 + 50 * warm), int(26 + 20 * warm), int(35 - 10 * warm))
            self._fill(frame, 0, 0, w, h, tint, .82 if reduced else .65 + .2 * np.sin(np.pi * progress))
            title = "A safe anchor. A little sleep." if ui.nap_forced else "Catnap"
            body = "Two quiet hours. Your lines keep soaking."
            if comfort.rested(state.v2, state.narrative.active_play_game_minutes):
                remaining = (state.v2["needs"]["rested_until"] - state.narrative.active_play_game_minutes) / 60
                body += f"\nRested: {remaining:.1f} game hours left."
            if state.v2["book"].get("dream_clue"):
                body += "\nBot's dream left a habitat lead in your book."
            labels = None
            selected = 0
        if labels:
            self._round_fill(frame, x, y, width, height, (17, 31, 32), 1)
        self._fill(frame, x + 10, y, width - 20, 1, GOLD, .34)
        head, size = self._size(frame, "head"), self._size(frame, "body")
        while head > 10 and self._measure(title, head) > width - 32:
            head -= 1
        self._text(frame, title, x + 16, y + 16, head, INK, False, "sans")
        top = y + 30 + self._render(title, head, INK, "sans").shape[0]
        hint = self._controls(ui, "Arrows choose · Enter selects · Esc back",
                               "D-pad chooses · A selects · B back") if labels else "Any key or click finishes the fade."
        if labels and ui.mode == "needs":
            hint = self._controls(ui, "Arrows choose · Enter selects · F / Esc later",
                                   "D-pad chooses · A selects · X / B later")
        values = body + "\n" + hint
        available = buttons[0][1] - 12 - top
        while size > 10:
            lines, line_height = self._comfort_lines(values, size, width - 32)
            if len(lines) * line_height <= available:
                break
            size -= 1
        lines, line_height = self._comfort_lines(values, size, width - 32)
        for index, line in enumerate(lines):
            self._text(frame, line, x + 16, top + index * line_height,
                       size, DIM, False, "sans")
        if labels:
            for index, (label, rect) in enumerate(zip(labels, buttons)):
                bx, by, bw, bh = rect
                chosen = index == selected
                self._round_fill(frame, bx, by, bw, bh, GOLD if chosen else (46, 66, 62), 1)
                label = ("> " if chosen else "") + label
                font = self._size(frame, "body")
                while font > 10 and (self._measure(label, font) > bw - 16
                                    or self._render(label, font, INK, "sans").shape[0] > bh - 10):
                    font -= 1
                glyph_height = self._render(label, font, INK, "sans").shape[0]
                self._center(frame, label, bx + bw / 2, by + (bh - glyph_height) / 2,
                             font, (22, 39, 39) if chosen else INK)

    def _drowsy_edges(self, frame):
        h, w = frame.shape[:2]
        edge = max(5, min(24, h // 22))
        for x, y, width, height, reverse, horizontal in (
            (0, 0, edge, h, False, True), (w-edge, 0, edge, h, True, True),
            (0, 0, w, edge, False, False), (0, h-edge, w, edge, True, False),
        ):
            region = frame[y:y+height, x:x+width].copy()
            soft = resize_rgb(resize_rgb(region, max(1, width // 3), max(1, height // 3)), width, height)
            ramp = np.linspace(.65, 0, edge, dtype=np.float32)
            if reverse:
                ramp = ramp[::-1]
            alpha = ramp[None, :, None] if horizontal else ramp[:, None, None]
            frame[y:y+height, x:x+width] = (region * (1-alpha) + soft * alpha).astype(np.uint8)

    def _comfort_status(self, frame, state):
        labels = []
        if comfort.drowsy(state.v2):
            labels.append("Drowsy")
        if comfort.speed_factor(state.v2) < 1:
            labels.append("Peckish")
        if comfort.rested(state.v2, state.narrative.active_play_game_minutes):
            labels.append("Rested")
        if comfort.active_buff(state):
            labels.append("Picnic")
        if not labels:
            return
        h, w = frame.shape[:2]
        scale = getattr(self, "_text_scale", 1.)
        unit = h / 720 * scale
        margin = max(12, int(26 * unit))
        size = max(11, int(h / 60))
        label = " · ".join(labels)
        y = margin + int(92 * unit) + 18
        width = self._measure(label, size) + 24
        self._panel(frame, margin, y, width, self._render(label, size, GOLD, "sans").shape[0] + 16, .8)
        self._text(frame, label, margin + 12, y + 6, size, GOLD, False, "sans")

    def _shop(self, frame, state, ui: UIState):
        if ui.shop_tab == 7:
            from .botview import draw
            draw(self, frame, state, ui)
            return
        if ui.shop_tab == 6:
            from .kitchenview import draw
            draw(self, frame, state, ui)
            return
        rows = shop_rows(state, ui.shop_tab)
        ui.shop_i = _clamp(ui.shop_i, len(rows))
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.70), int(h * 0.80)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        head = self._size(frame, "head")
        body = self._size(frame, "body")
        small = self._size(frame, "small")
        ch = self.cell(body)[1]
        m = 16
        self._text(frame, self.world.landing.upper(), x + m, y + 12, head, INK)
        host = next((npc.name for npc in state.npcs if npc.permanent), "")
        meta = f"{host}    {dollars(state.money)}    well {state.well_load():.0f}/{state.well_cap():.0f} lb    bait {state.bait_count()}/{state.box_cap()}"
        self._text(frame, meta, x + m, y + 12 + self.cell(head)[1], small, GOLD, shadow=False)
        tab_y = y + 18 + self.cell(head)[1] + self.cell(small)[1]
        tx = x + m
        tab_font = body
        while tab_font > 10 and sum(self._measure(name, tab_font, "mono") + 24 for name in _TABS) > pw - m * 2:
            tab_font -= 1
        indexes = list(range(len(_TABS)))
        if sum(self._measure(name, tab_font, "mono") + 24 for name in _TABS) > pw - m * 2:
            indexes = [(ui.shop_tab + delta) % len(_TABS) for delta in (-1, 0, 1)]
        for i in indexes:
            name = _TABS[i]
            color = GOLD if i == ui.shop_tab else DIM
            label = f"[{name}]" if i == ui.shop_tab else f" {name} "
            tw = self._text(frame, label, tx, tab_y, tab_font, color)
            tx += tw + 8
        list_top = tab_y + ch + 10
        list_h = ph - (list_top - y) - ch * 3
        visible = max(4, list_h // (ch + 2))
        start = _window(ui.shop_i, len(rows), visible)
        for n in range(visible):
            i = start + n
            if i >= len(rows):
                break
            row = rows[i]
            ry = list_top + n * (ch + 2)
            if i == ui.shop_i:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            color = INK if row.enabled else DIM
            if i == ui.shop_i:
                color = GOLD
            label = self._trim(row.label, body, pw * 0.68)
            self._text(frame, label, x + m, ry, body, color, shadow=False)
            rw = len(row.right) * self.cell(body)[0]
            self._text(frame, row.right, x + pw - m - rw, ry, body, color, shadow=False)
        blurb = rows[ui.shop_i].blurb if rows else ""
        if ui.note:
            blurb = ui.note
        self._text(frame, self._trim(blurb, small, pw - m * 2), x + m, y + ph - ch - 28, small, WARN if ui.note else DIM, shadow=False)
        foot = self._controls(ui, "W/S choose  A/D tabs  Arrows too  Enter buys  Esc",
                              "D-pad / stick choose  D-pad tabs  A buys  B back")
        self._text(frame, foot, x + m, y + ph - self.cell(small)[1] - 8, small, DIM, shadow=False)

    def _setbait(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.56), int(h * 0.62)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        head = self._size(frame, "head")
        body = self._size(frame, "body")
        small = self._size(frame, "small")
        ch = self.cell(body)[1]
        m = 16
        self._text(frame, "SET A LINE", x + m, y + 12, head, INK)
        if not state.held:
            self._text(frame, "No line aboard.", x + m, y + 60, body, WARN)
            return
        ui.set_line %= len(state.held)
        ui.set_bait %= len(BAITS)
        ui.set_sections = max(1, min(3, int(ui.set_sections)))
        ui.set_section %= ui.set_sections
        section_baits = [index % len(BAITS) for index in ui.set_section_baits]
        if ui.set_section_baits == (0, 0, 0) and ui.set_bait:
            section_baits = [ui.set_bait] * 3
        ui.set_bait = section_baits[ui.set_section]
        held = state.held[ui.set_line]
        spec = LINE_TIERS[held.tier]
        which = (f"Line {ui.set_line + 1} of {len(state.held)}    {spec['hooks']} hooks"
                 f"    {len(state.lines)}/{state.boat.lines} deployed")
        self._text(frame, which, x + m, y + 16 + self.cell(head)[1], small, GOLD, shadow=False)
        section_summary = " / ".join(
            f"S{i + 1} {BAITS[section_baits[i]].name}"
            for i in range(ui.set_sections)
        )
        self._text(frame, self._trim(section_summary, small, pw - m * 2),
                   x + m, y + 17 + self.cell(head)[1] + self.cell(small)[1],
                   small, DIM, shadow=False)
        top = y + 30 + self.cell(head)[1] + self.cell(small)[1] * 2
        visible = max(1, (y + ph - ch * 2 - 42 - top) // (ch + 4))
        start = _window(ui.set_bait, len(BAITS), visible)
        need = sum(1 for hook_index in range(spec["hooks"])
                   if hook_index * ui.set_sections // spec["hooks"] == ui.set_section)
        for offset, bait in enumerate(BAITS[start:start + visible]):
            i = start + offset
            have = state.bait.get(bait.id, 0)
            label = f"{i + 1}  {bait.name}"
            right = f"{have} aboard"
            selected = i == section_baits[ui.set_section]
            color = GOLD if selected else INK
            if have < need and selected:
                color = WARN
            ry = top + offset * (ch + 4)
            if selected:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            rw = len(right) * self.cell(body)[0]
            self._text(frame, self._trim(label, body, pw - m * 2 - rw - 16), x + m, ry, body, color, shadow=False)
            self._text(frame, right, x + pw - m - rw, ry, body, color, shadow=False)
        bait = BAITS[section_baits[ui.set_section]]
        note = ui.note or f"Editing section {ui.set_section + 1}: needs {need}. {bait.blurb}"
        self._text(frame, self._trim(note, small, pw - m * 2), x + m, y + ph - ch - 28, small, WARN if ui.note else DIM, shadow=False)
        foot = self._controls(ui, "W/S bait  A/D line  Q sections  Tab section  1-5 bait  Enter sets",
                              "D-pad / stick choose  LB sections  Back section  A sets  B back")
        self._text(frame, foot, x + m, y + ph - self.cell(small)[1] - 8, small, DIM, shadow=False)

    def _check(self, frame, state, ui: UIState):
        rows = check_rows(state, ui.check_line)
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.66), int(h * 0.78)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        head = self._size(frame, "head")
        body = self._size(frame, "body")
        small = self._size(frame, "small")
        ch = self.cell(body)[1]
        m = 16
        if not rows:
            self._text(frame, "The line is gone.", x + m, y + 20, body, WARN)
            return
        line = state.lines[ui.check_line]
        title = state.line_label(ui.check_line).upper()
        self._text(frame, title, x + m, y + 12, head, INK)
        section_names = " / ".join(
            BAIT_BY_ID.get(bait, BAIT_BY_ID["worm"]).name for bait in line.bait_sections
        )
        sub = f"{section_names}    {line.fish_on()} fish    {line.bare_hooks()} bare"
        self._text(frame, sub, x + m, y + 14 + self.cell(head)[1], small, GOLD, shadow=False)
        ui.check_i = _clamp(ui.check_i, len(rows))
        list_top = y + 24 + self.cell(head)[1] + self.cell(small)[1]
        visible = max(5, (ph - (list_top - y) - 36) // (ch + 1))
        start = _window(ui.check_i, len(rows), visible)
        for n in range(visible):
            i = start + n
            if i >= len(rows):
                break
            row = rows[i]
            ry = list_top + n * (ch + 1)
            if i == ui.check_i:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            color = GOLD if i == ui.check_i else (INK if row.enabled or row.kind != "hook" else DIM)
            if row.kind == "hook" and not row.enabled and i != ui.check_i:
                color = DIM
            label = self._trim(row.label, body, int(pw * 0.72))
            self._text(frame, label, x + m, ry, body, color, shadow=False)
            if row.right:
                rw = len(row.right) * self.cell(body)[0]
                self._text(frame, row.right, x + pw - m - rw, ry, body, color, shadow=False)
        foot = ui.note or self._controls(
            ui, "W/S choose  Enter toggles  Resolve applies  Esc back",
            "D-pad choose  A toggles / applies  B back",
        )
        self._text(frame, self._trim(foot, small, pw - m * 2), x + m, y + ph - self.cell(small)[1] - 10, small, WARN if ui.note else DIM, shadow=False)

    def _journal(self, frame, state, ui: UIState):
        from .bookview import BOOK_TABS
        ui.journal_page %= len(BOOK_TABS)
        BookView(self, frame, state, ui).draw()

    def _draw_journal_text(self, frame, value, x, y, width, size, color,
                           max_lines=4, bottom=None):
        cw, ch = self.cell(size)
        columns = max(1, int(width) // cw)
        lines = textwrap.wrap(str(value), width=columns, break_long_words=True,
                              break_on_hyphens=False) or [""]
        line_height = ch + 2
        if bottom is not None:
            max_lines = min(max_lines, max(0, (bottom - y) // line_height))
        if max_lines <= 0:
            return y
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self._trim(lines[-1], size, width)
        for i, line in enumerate(lines):
            self._text(frame, line, x, y + i * line_height, size, color, shadow=False)
        return y + len(lines) * line_height

    def _narrative_journal(self, frame, state, ui: UIState):
        BookView(self, frame, state, ui).story()

    def _wrap(self, frame, text, x, y, size, color, width):
        cw, ch = self.cell(size)
        n = max(8, int(width) // cw)
        words = text.split()
        line = ""
        row = 0
        for word in words:
            trial = word if not line else line + " " + word
            if len(trial) > n:
                self._text(frame, line, x, y + row * (ch + 1), size, color, shadow=False)
                line = word
                row += 1
            else:
                line = trial
        if line:
            self._text(frame, line, x, y + row * (ch + 1), size, color, shadow=False)

    def _well(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.56), int(h * 0.70)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        head = self._size(frame, "head")
        body = self._size(frame, "body")
        small = self._size(frame, "small")
        m = 16
        self._text(frame, "LIVEWELL", x + m, y + 12, head, INK)
        cap = f"{state.well_load():.1f} / {state.well_cap():.0f} lb"
        self._text(frame, cap, x + pw - m - len(cap) * self.cell(body)[0], y + 18, body, GOLD, shadow=False)
        rows = state.well
        ui.well_i = _clamp(ui.well_i, max(1, len(rows)))
        ch = self.cell(body)[1]
        top = y + 24 + self.cell(head)[1]
        visible = max(4, (ph - (top - y) - 36) // (ch + 2))
        if not rows:
            self._text(frame, "Empty. The lines keep what they catch.", x + m, top, body, DIM)
        else:
            start = _window(ui.well_i, len(rows), visible)
            for n in range(visible):
                i = start + n
                if i >= len(rows):
                    break
                catch = rows[i]
                sp = SPECIES_BY_ID.get(catch.species)
                name = sp.name if sp is not None else catch.species.replace("_", " ").title()
                if catch.shiny:
                    name = "✦ " + name
                q = quality_name(catch.quality)
                mark = " · TREASURED" if catch.treasured else ""
                label = f"{weight_string(catch.weight)} {name}, {q}{mark}"
                color = GOLD if i == ui.well_i else INK
                ry = top + n * (ch + 2)
                self._text(frame, self._trim(label, body, int(pw * 0.68)), x + m, ry, body, color, shadow=False)
                right = dollars(catch.value())
                self._text(frame, right, x + pw - m - len(right) * self.cell(body)[0], ry, body, color, shadow=False)
        foot = self._controls(ui, "W/S choose    T / Enter marks Treasured    I closes",
                              "D-pad choose    A marks Treasured    B closes")
        self._text(frame, foot, x + m, y + ph - self.cell(small)[1] - 10, small, DIM, shadow=False)

    def _pause(self, frame, ui: UIState):
        h, w = frame.shape[:2]
        self._fill(frame, 0, 0, w, h, (6, 8, 8), 0.35)
        labels = ["Resume", "Settings", "Help", "Main menu", "Quit"]
        body = self._size(frame, "body")
        head = self._size(frame, "head")
        small = self._size(frame, "small")
        pw = min(w - 24, max(420, int(w * 0.34)))
        ph = 40 + self.cell(head)[1] + len(labels) * (self.cell(body)[1] + 8) + 30
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.92)
        self._text(frame, "PAUSED", x + 18, y + 14, head, INK)
        ui.pause_i %= len(labels)
        for i, label in enumerate(labels):
            color = GOLD if i == ui.pause_i else INK
            prefix = "> " if i == ui.pause_i else "  "
            self._text(frame, prefix + label, x + 18, y + 24 + self.cell(head)[1] + i * (self.cell(body)[1] + 8), body, color)
        foot = ui.note or self._controls(ui, "Arrows · Enter · Z nap · K pantry",
                                        "D-pad · A · X nap · Y pantry")
        self._text(frame, foot, x + 18, y + ph - self.cell(small)[1] - 12, small,
                   WARN if ui.note else DIM, shadow=False)

    def _settings_rows(self, state):
        v2 = getattr(state, "v2", {})
        settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
        profile = v2.get("profile", {}) if isinstance(v2, dict) else {}
        collar = profile.get("collar", {}) if isinstance(profile, dict) else {}
        text_size = settings.get("text_size", 1)
        if type(text_size) is not int or text_size not in range(3):
            text_size = 1
        volumes = settings.get("volumes", {})
        if not isinstance(volumes, dict):
            volumes = {}
        haul_speed = settings.get("haul_speed", "normal")
        if haul_speed not in {"normal", "quick", "instant"}:
            haul_speed = "normal"
        mode = settings.get("mode", v2.get("mode", "cozy"))
        if mode not in MODES:
            mode = "cozy"
        collar_visible = settings.get("collar_visible", collar.get("visible", True))
        rows = [
            ("Mode", "Cozy" if mode == "cozy" else "Old Salt"),
            ("Text size", ("Small", "Standard", "Large")[text_size]),
            ("Dyslexia-friendly font", "Atkinson Hyperlegible" if settings.get("dyslexia_font") else "Off"),
            ("Reduced motion", "On" if settings.get("reduced_motion") else "Off"),
            ("Haul speed", {"normal": "Normal", "quick": "Quick", "instant": "Instant"}[haul_speed]),
            ("Captions", "On" if settings.get("captions", True) else "Off"),
        ]
        for name in VOLUME_NAMES:
            value = volumes.get(name, 1.0)
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                value = 1.0
            if not math.isfinite(value):
                value = 1.0
            rows.append((VOLUME_LABELS[name], f"{round(max(0.0, min(1.0, value)) * 100):.0f}%"))
        rows.extend([
            ("Collar visibility", "Visible" if collar_visible else "Hidden"),
            ("Keyboard controls", "Open  >"),
        ])
        return rows

    def _settings(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        rows = self._settings_rows(state)
        ui.settings_i = _clamp(ui.settings_i, len(rows))
        head, body, small = (self._size(frame, key) for key in ("head", "body", "small"))
        head_h, body_h, small_h = self.cell(head)[1], self.cell(body)[1], self.cell(small)[1]
        m = max(14, min(24, int(w * 0.025)))
        pw = min(w - 20, max(int(w * 0.74), 760))
        foot = self._controls(
            ui, "W/S choose  ·  A/D change  ·  Enter changes  ·  Esc returns",
            "D-pad choose  ·  D-pad change  ·  A changes  ·  B returns",
        )
        foot_lines = textwrap.wrap(foot, max(12, (pw - 2 * m) // self.cell(small)[0]))
        foot_h = len(foot_lines) * (small_h + 2)
        row_h = body_h + max(4, int(h * 0.008))
        rows_top_offset = m + head_h + 14
        available = h - 24 - (2 * m + rows_top_offset + foot_h + 12)
        visible = max(1, min(len(rows), available // max(1, row_h)))
        start = _window(ui.settings_i, len(rows), visible)
        ph = 2 * m + head_h + 14 + visible * row_h + foot_h + 12
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        self._text(frame, "SETTINGS & ACCESSIBILITY", x + m, y + m, head, INK)
        list_top = y + rows_top_offset
        left_width = int((pw - 2 * m) * 0.63)
        value_width = pw - 2 * m - left_width
        for offset, (label, value) in enumerate(rows[start:start + visible]):
            index = start + offset
            ry = list_top + offset * row_h
            if index == ui.settings_i:
                self._fill(frame, x + m - 4, ry - 1, pw - 2 * m + 8, row_h, (46, 42, 28), 0.86)
            color = GOLD if index == ui.settings_i else INK
            prefix = "> " if index == ui.settings_i else "  "
            self._text(frame, prefix + self._trim(label, body, left_width - 10), x + m, ry, body, color, shadow=False)
            value = self._trim(value, body, value_width - 4)
            self._text(frame, value, x + pw - m - self._measure(value, body), ry, body, color, shadow=False)
        foot_y = y + ph - m - foot_h
        for line in foot_lines:
            self._text(frame, line, x + m, foot_y, small, DIM, shadow=False)
            foot_y += small_h + 2

    @staticmethod
    def _key_name(key: str) -> str:
        return {
            "esc": "Escape", "return": "Enter", "space": "Space",
            "tab": "Tab", "shift": "Left Shift", "rshift": "Right Shift",
            "up": "Up", "down": "Down", "left": "Left", "right": "Right",
            "minus": "-", "equals": "=", "left_bracket": "[",
            "right_bracket": "]", "backslash": "Backslash", "semicolon": ";",
            "apostrophe": "Apostrophe", "grave": "Grave", "comma": ",",
            "period": ".", "slash": "/",
        }.get(key, key.upper())

    def _keybinding_actions(self):
        alias_actions = {alias for group in ACTION_ALIASES for alias in group[1:]}
        return [action for action in ACTION_SYMBOLS if action not in alias_actions]

    def _keybindings(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        actions = self._keybinding_actions()
        rows = [(action, KEY_ACTION_LABELS.get(action, action.replace("_", " ").title()))
                for action in actions]
        rows.append(("__reset__", "Reset keyboard controls"))
        ui.key_binding_i = _clamp(ui.key_binding_i, len(rows))
        v2 = getattr(state, "v2", {})
        settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
        bindings = normalize_key_bindings(settings.get("key_bindings"))
        head, body, small = (self._size(frame, key) for key in ("head", "body", "small"))
        head_h, body_h, small_h = self.cell(head)[1], self.cell(body)[1], self.cell(small)[1]
        m = max(14, min(24, int(w * 0.025)))
        pw = min(w - 20, max(int(w * 0.74), 760))
        foot = ("Press a key to bind  ·  Backspace or Esc cancels" if ui.capturing_key
                else "W/S choose  ·  Enter rebinds  ·  Esc returns")
        if ui.input_device == "gamepad" and not ui.capturing_key:
            foot = "D-pad choose  ·  A rebinds a keyboard key  ·  B returns"
        foot_lines = textwrap.wrap(foot, max(12, (pw - 2 * m) // self.cell(small)[0]))
        foot_h = len(foot_lines) * (small_h + 2)
        row_h = body_h + max(4, int(h * 0.008))
        rows_top_offset = m + head_h + 14
        available = h - 24 - (2 * m + rows_top_offset + foot_h + 12)
        visible = max(1, min(len(rows), available // max(1, row_h)))
        start = _window(ui.key_binding_i, len(rows), visible)
        ph = 2 * m + head_h + 14 + visible * row_h + foot_h + 12
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        self._text(frame, "KEYBOARD CONTROLS", x + m, y + m, head, INK)
        list_top = y + rows_top_offset
        value_width = int((pw - 2 * m) * 0.24)
        for offset, (action, label) in enumerate(rows[start:start + visible]):
            index = start + offset
            ry = list_top + offset * row_h
            if index == ui.key_binding_i:
                self._fill(frame, x + m - 4, ry - 1, pw - 2 * m + 8, row_h, (46, 42, 28), 0.86)
            color = GOLD if index == ui.key_binding_i else INK
            prefix = "> " if index == ui.key_binding_i else "  "
            self._text(frame, prefix + self._trim(label, body, pw - 2 * m - value_width - 12), x + m, ry, body, color, shadow=False)
            if action == "__reset__":
                value = "Defaults"
            elif ui.capturing_key and index == ui.key_binding_i:
                value = "Press a key…"
            else:
                value = self._key_name(bindings.get(action, default_key_bindings()[action]))
            value = self._trim(value, body, value_width)
            self._text(frame, value, x + pw - m - self._measure(value, body), ry, body, color, shadow=False)
        foot_y = y + ph - m - foot_h
        for line in foot_lines:
            self._text(frame, line, x + m, foot_y, small, DIM, shadow=False)
            foot_y += small_h + 2

    def _caption(self, frame, state, ui: UIState):
        v2 = getattr(state, "v2", {})
        settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
        if not settings.get("captions", True) or ui.caption_timer <= 0 or not ui.caption:
            return
        h, w = frame.shape[:2]
        if ui.mode in {"kitchen", "cook_confirm", "cooking"} or (ui.mode == "shop" and ui.shop_tab in (6, 7)):
            size = self._size(frame, "small")
            while size > 9 and self._render(ui.caption, size, INK, "sans").shape[0] > 18:
                size -= 1
            label = self._trim(ui.caption, size, w - 48)
            glyph_h = self._render(label, size, INK, "sans").shape[0]
            width = self._measure(label, size) + 20
            x, y = (w - width) // 2, h - glyph_h - 8
            self._round_fill(frame, x, y, width, glyph_h + 6, (17, 31, 32), 1)
            self._text(frame, label, x + 10, y + 3, size, DIM, False, "sans")
            return
        size = self._size(frame, "body")
        text_w = self._measure(ui.caption, size)
        pw = min(w - 24, text_w + 32)
        ph = self.cell(size)[1] + 16
        x, y = (w - pw) // 2, max(4, h - ph - 18)
        self._panel(frame, x, y, pw, ph, 0.94)
        self._center(frame, self._trim(ui.caption, size, pw - 24), w / 2,
                     y + 8, size, INK, family="sans")

    def _help(self, frame, ui: UIState):
        pages = _HELP
        ui.help_page %= len(pages)
        title, lines = pages[ui.help_page]
        if ui.input_device == "gamepad":
            lines = tuple(_GAMEPAD_HELP_CONTROLS.get(line, line) for line in lines)
        title = _help_title(title)
        h, w = frame.shape[:2]
        head = self._size(frame, "head")
        body = self._size(frame, "small")
        if h < 300:
            head = body
        m = 12 if w < 800 else 18
        page = f"{ui.help_page + 1} / {len(pages)}"
        foot = self._controls(ui, "WASD or arrows turn pages    Esc closes",
                              "D-pad / stick turn pages    B closes")
        page_w = self._measure(page, body, "mono")
        content_w = max(self._measure(line, body, "mono") for line in (*lines, foot) if line)
        content_w = max(content_w, self._measure(title, head, "mono") + page_w + 16)
        pw = min(w - 16, max(int(w * 0.70), content_w + m * 2))
        # Fallback fonts may give descenders a taller surface than "M".
        # Space rows using the actual authored strings on this machine.
        ch = max(self._render(line, body, INK).shape[0] for line in (*lines, foot) if line)
        hh = self._render(title, head, INK).shape[0]
        header = 2 if h < 300 else 4 if h < 400 else 14
        top = header + hh + (2 if h < 300 else 4 if h < 400 else 10)
        bottom = 2 if h < 300 else 6 if h < 400 else 12
        foot_gap = 2 if h < 300 else 4 if h < 400 else 8
        vertical_margin = 4 if h < 300 else 16
        available = h - vertical_margin - top - foot_gap - ch - bottom
        # Expand the sheet before reducing spacing. Even at 480x270 the
        # authored text keeps its readable 12px font; only blank gaps collapse.
        gap = max(0, min(3, (available - len(lines) * ch) // len(lines)))
        blank_count = sum(not line for line in lines)
        blank_h = ch + gap
        if blank_count:
            blank_h = max(0, min(blank_h,
                (available - (len(lines) - blank_count) * (ch + gap)) // blank_count))
        row_heights = [ch + gap if line else blank_h for line in lines]
        ph = min(h - vertical_margin, max(int(h * 0.74), top + sum(row_heights) + foot_gap + ch + bottom))
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.92)
        self._text(frame, title, x + m, y + header, head, INK)
        self._text(frame, page, x + pw - m - page_w,
                   y + header + (hh - ch) // 2, body, GOLD, shadow=False)
        row_y = y + top
        for line, row_h in zip(lines, row_heights):
            if line:
                self._text(frame, line, x + m, row_y, body, INK, shadow=False)
            row_y += row_h
        self._text(frame, foot, x + m, y + ph - ch - bottom, body, DIM, shadow=False)


_HELP = (
    ("ON THE WATER", (
        "W/S row, or run the motor when one is installed",
        "Power stays set       Shift returns it to idle",
        "A D or arrows steer   arrows look up and down",
        "Space drops or raises the anchor",
        "W / S also pull the anchor when you mean to go",
        "",
        "F sets a trotline       E checks one, or opens the landing",
        "Tab chart    J journal    I livewell",
        "C hails a paw-wave NPC: within 20 m, below 3 knots",
        "T changes time: 1x 3x 6x 12x, while you are still",
        "B sends Bot ahead, or out to a line. B calls him back.",
        "H help    M mute    Esc pause",
        "",
        "One real second is one minute on the lake at 1x.",
        "A day on the water is 24 minutes.",
    )),
    ("TROT LINES", (
        "There is no rod and reel. The lines do the fishing.",
        "Idle the boat, point at open water, and set.",
        "Each hook takes one piece of bait and holds one fish.",
        "Corks mark the hooks. A flag means a fish is on.",
        "Tired fish turn red on the chart. About four hours left.",
        "The landing, and the water around it, is a no-line zone.",
        "",
        "Anchor and let time run. Come back and check.",
        "Take fish into the livewell, rebait, or pull the line.",
        "A fish left on the hook gets away after 13 hours.",
        "Run a line over and you may knock one off.",
        "",
        "While the game is closed the lines keep soaking,",
        "for up to six hours of real time, then the fish get away.",
    )),
    ("THE LANDING", (
        "Nose into the slip and press E.",
        "Sell the well. Buy bait by the dozen.",
        "Motors, a deeper well, a bait box,",
        "a depth finder, and a bow light are at the same counter.",
        "The rowboat runs on oars; its electric motor is optional.",
        "",
        "Hull, deck, buoy, and tiller colors are yours once you",
        "buy them. Wearing one you own is free.",
        "",
        "Your active boat sets the deployed-line limit.",
        "Lines already out stay out if you switch to a smaller boat.",
        "Worms on the flats keep the boat in bait.",
        "Liver, cut shad, and the deep hole are where the",
        "heavy fish live, and they fill a small livewell fast.",
    )),
    ("BOATS AND OTHER WATERS", (
        "At the landing: A/D tabs, W/S rows, Enter selects.",
        "Boats: buy a daysailer or a pontoon with your earnings.",
        "Owned boats can be switched freely at the landing.",
        "The pontoon adds 40 lb of livewell space.",
        "",
        "Q raises or lowers the daysailer's sail.",
        "A/D steers. Sail across the wind; tack to go upwind.",
        "W/S controls its small auxiliary. Shift idles it.",
        "Wind power burns no fuel. Lower the sail to stop.",
        "Space anchors and lowers the sail.",
        "",
        "Fuel is sold in the Boats tab. Each boat keeps its tank.",
        "Idle, then R calls a tow if you get stranded.",
        "Lakes: pick up your lines, then travel from the landing.",
        "Money, catches, gear, boats, and journal come with you.",
    )),
)

_GAMEPAD_HELP_CONTROLS = {
    "W/S row, or run the motor when one is installed":
        "Left stick / LT / RT row or run the motor",
    "Power stays set       Shift returns it to idle":
        "Power stays set       Shift idles (keyboard)",
    "A D or arrows steer   arrows look up and down":
        "Left stick steers; D-pad / stick move through menus",
    "Space drops or raises the anchor":
        "Space anchors (keyboard)",
    "W / S also pull the anchor when you mean to go":
        "Use the left stick or triggers to set the throttle",
    "F sets a trotline       E checks one, or opens the landing":
        "X sets a trotline       A checks one or opens the landing",
    "Tab chart    J journal    I livewell":
        "Back chart    J journal / I livewell (keyboard)",
    "C hails a paw-wave NPC: within 20 m, below 3 knots":
        "RB hails a paw-wave NPC: within 20 m, below 3 knots",
    "T changes time: 1x 3x 6x 12x, while you are still":
        "T changes time (keyboard): 1x 3x 6x 12x while still",
    "B sends Bot ahead, or out to a line. B calls him back.":
        "Tap Y sends Bot ahead or to a line; tap again to recall",
    "H help    M mute    Esc pause":
        "H help / M mute (keyboard)    Start pauses",
    "Nose into the slip and press E.":
        "Nose into the slip and press A.",
    "At the landing: A/D tabs, W/S rows, Enter selects.":
        "At landing: D-pad tabs / rows, A selects, B returns",
    "Q raises or lowers the daysailer's sail.":
        "Q raises or lowers the daysailer's sail (keyboard).",
    "A/D steers. Sail across the wind; tack to go upwind.":
        "Left stick steers. Sail across the wind; tack to go upwind.",
    "W/S controls its small auxiliary. Shift idles it.":
        "Stick / triggers control the auxiliary; Shift idles (keyboard).",
    "Space anchors and lowers the sail.":
        "Space anchors and lowers the sail (keyboard).",
    "Idle, then R calls a tow if you get stranded.":
        "Press R (keyboard) to call a tow if you get stranded.",
}

_GAMEPAD_TUTORIAL_PROMPTS = {
    "W/S row or power    Shift idle    A/D steer":
        "Left stick rows or steers    LT/RT set throttle",
    "Stop, then F to set a trotline":
        "Stop, then X to set a trotline",
    "T changes time while anchored    E checks a line":
        "Wait for a bite, then A checks a line",
}

_GAMEPAD_TUTORIAL_TOASTS = {
    "Stop the boat and press F to set a trotline.":
        "Stop the boat and press X to set a trotline.",
    "Anchor and press T to let time run. E checks a line.":
        "After setting a line, wait for a bite; A checks it.",
    "Nose into the landing and press E to sell.":
        "Nose into the landing and press A to sell.",
}


def _prompt_for_device(prompt: str | None, input_device: str) -> str | None:
    if prompt and input_device == "gamepad":
        if prompt.startswith("E  "):
            return prompt.replace("E  ", "A  ", 1)
        return _GAMEPAD_TUTORIAL_PROMPTS.get(prompt, prompt)
    return prompt


def _toast_for_device(text: str, input_device: str) -> str:
    if input_device == "gamepad":
        return _GAMEPAD_TUTORIAL_TOASTS.get(text, text)
    return text


def _help_title(topic: str) -> str:
    return f"{topic}  ·  {GAME_TITLE}"


HELP_N = len(_HELP)


def _clamp(index: int, count: int) -> int:
    if count <= 0:
        return 0
    if index < 0:
        return 0
    if index >= count:
        return count - 1
    return index


def _window(index: int, count: int, visible: int) -> int:
    if count <= visible:
        return 0
    start = index - visible // 2
    return max(0, min(start, count - visible))


def _fit(img: np.ndarray, tw: int, th: int) -> np.ndarray:
    sh, sw = img.shape[:2]
    ys = np.linspace(0, sh - 1, th).astype(np.int32)
    xs = np.linspace(0, sw - 1, tw).astype(np.int32)
    return img[ys][:, xs]


@lru_cache(maxsize=48)
def _haul_mesh_sprite(species_id: str, lake_id: str, shiny: bool) -> np.ndarray:
    """Rasterize a cached side-on fish mesh for the haul's surface beat."""
    from .fishmesh import haul_mesh

    width, height = 384, 192
    color = np.zeros((height, width, 3), dtype=np.float32)
    depth = np.full((height, width), 1e6, dtype=np.float32)
    mesh = haul_mesh(species_id, lake_id, shiny)
    projected = mesh.vertices[:, :2].copy()
    scale = 136.0
    projected[:, 0] = width * 0.5 + projected[:, 0] * scale
    projected[:, 1] = height * 0.5 - projected[:, 1] * scale
    for index, triangle in enumerate(mesh.triangles):
        vertices = mesh.vertices[triangle]
        xy = projected[triangle]
        zz = 3.0 - vertices[:, 2] * 0.12
        raster_tri(color, depth, xy, zz, mesh.colors[index])
    visible = depth < 1e6
    sprite = np.zeros((height, width, 4), dtype=np.uint8)
    sprite[:, :, :3] = np.clip(color * 255.0 + 0.5, 0, 255).astype(np.uint8)
    sprite[:, :, 3] = visible.astype(np.uint8) * 255
    sprite.setflags(write=False)
    return sprite


def comfort_gallery(destination, *, text=None, world=None, background=None):
    """--shots comfort fixtures and a warmed UI composition benchmark."""
    from copy import deepcopy
    import json
    from pathlib import Path
    import resource
    import time
    from .book import BOOK_SPECIES_IDS
    from .pngsave import write_png
    from .sim import State

    own_text = text is None
    text = Text() if own_text else text
    world = World() if world is None else world
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    state = State.new(world, seed=42014)
    comfort.change_mode(state.v2, "old_salt")
    state.catnap(world)
    state.toasts.clear()
    state.tutorial = 4
    clue = state.v2["book"]["dream_clue"]
    entry = BOOK_SPECIES_IDS.index(clue["species"])
    initial_needs = deepcopy(state.v2["needs"])
    panels = (
        ("mode-cozy", UIState(mode="new_mode")),
        ("mode-old-salt", UIState(mode="new_mode", new_mode_i=1)),
        ("drowsy-prompt", UIState(mode="needs", needs_kind="energy")),
        ("peckish-prompt", UIState(mode="needs", needs_kind="hunger", comfort_i=1)),
        ("catnap", UIState(mode="catnap", nap_timer=1.5)),
        ("doze", UIState(mode="catnap", nap_timer=1.5, nap_forced=True)),
        ("dream-entry", UIState(mode="journal", journal_page=1, book_entry_i=entry)),
        ("routine-hud", UIState(mode="play")),
    )
    renderer = UI(text, world)
    contact = []
    def paint(panel, width, height):
        state.v2["needs"] = deepcopy(initial_needs)
        if panel.mode in {"needs", "play"}:
            state.v2["needs"].update({"awake_h": 18., "since_meal_h": 25., "rested_until": None})
        frame = (resize_rgb(background, width, height).copy() if background is not None
                 else np.full((height, width, 3), (48, 79, 87), np.uint8))
        renderer.draw(frame, state, panel)
        return frame
    try:
        for width, height, size, accessibility, suffix in (
            (1280, 720, 1, False, "standard"),
            (1280, 720, 2, True, "accessible"),
            (480, 270, 2, True, "compact-accessible"),
        ):
            state.v2["settings"].update({"text_size": size, "dyslexia_font": accessibility})
            for name, panel in panels:
                if width < 640 and panel.mode == "play":
                    continue
                frame = paint(panel, width, height)
                if width < 640 and panel.mode == "journal":
                    pages = []
                    for page in range(panel.book_detail_pages):
                        panel.book_detail_page = page
                        pages.append(paint(panel, width, height))
                    panel.book_detail_page = 0
                    if len(pages) % 2:
                        pages.append(np.full_like(frame, (48, 79, 87)))
                    frame = np.concatenate([np.concatenate(pages[i:i+2], axis=1)
                                            for i in range(0, len(pages), 2)], axis=0)
                write_png(out / f"comfort-{name}-{suffix}.png", frame)
                if suffix == "standard":
                    contact.append(resize_rgb(frame, 640, 360))
        write_png(out / "comfort-contact-sheet.png", np.concatenate([
            np.concatenate(contact[i:i+2], axis=1) for i in range(0, len(contact), 2)
        ], axis=0))
        state.v2["settings"].update({"text_size": 2, "dyslexia_font": True})
        timings = []
        for i in range(150):
            start = time.perf_counter()
            paint(panels[i % len(panels)][1], 1280, 720)
            if i >= 10:
                timings.append((time.perf_counter() - start) * 1000)
        report = {"frames": len(timings), "resolution": [1280, 720],
                  "p50_ms": round(float(np.percentile(timings, 50)), 2),
                  "p95_ms": round(float(np.percentile(timings, 95)), 2),
                  "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                  "text_cache_mb": round(text.cache_bytes / 1e6, 2),
                  "text_size": 2, "accessibility_font": True,
                  "scope": "Warmed comfort UI composition including Drowsy edges; excludes lake rendering"}
        (out / "comfort-benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
        print("comfort shots / benchmark: " + json.dumps(report))
        return report
    finally:
        if own_text:
            text.close()


def story_gallery(destination, *, text=None, world=None, background=None):
    """--shots V1-34 story fixtures: Bot's knot scene, the Settle In prompt and the credits."""
    from pathlib import Path
    from .content import load_content
    from .pngsave import write_png
    from .sim import State
    from .story import scene_conversation

    own_text = text is None
    text = Text() if own_text else text
    world = World() if world is None else world
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    content = load_content()
    state = State.new(world, seed=34)
    state.tutorial = 4
    state.x, state.z = world.slip.world(-40.0, 0.0)  # out on the water, no cat in hail range
    knot = scene_conversation(state, content, "story_c4_knot")
    panels = (
        ("scene-bot", UIState(mode="dialogue", conversation=knot, dialogue_content=content)),
        ("settle-in", UIState(mode="play", settling=True,
                              settle_prompt="Settling in. Keep still.  (1 of 3)  {key} Stop")),
        ("credits", UIState(mode="credits", credits_s=3.0)),
    )
    renderer = UI(text, world)
    try:
        for name, panel in panels:
            frame = (resize_rgb(background, 1280, 720).copy() if background is not None
                     else np.full((720, 1280, 3), (48, 79, 87), np.uint8))
            if panel.mode == "credits":
                state.set_scene_status("ending", "done")  # the author line as the credits show it
            state.toasts.clear()
            renderer.draw(frame, state, panel)
            write_png(out / f"story-{name}.png", frame)
    finally:
        if own_text:
            text.close()
