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
    ACTION_ALIASES, ACTION_SYMBOLS, BUTTON_A, BUTTON_B, BUTTON_BACK,
    BUTTON_DPAD_DOWN, BUTTON_DPAD_LEFT, BUTTON_DPAD_RIGHT, BUTTON_DPAD_UP,
    BUTTON_LEFTSHOULDER, BUTTON_RIGHTSHOULDER, BUTTON_START, BUTTON_X, BUTTON_Y,
    default_key_bindings, normalize_key_bindings,
)
from .boat import (
    BOATS, FUEL_PRICE, ROWBOAT_MOTOR_PRICE, ROWBOAT_BATTERY_KWH,
    BATTERY_CHARGE_KWH, ELECTRICITY_PRICE,
)
from .lakes import LAKES, LAKE_ZONE_NAMES, travel_lock_reason
from .data import weight_string
from .weather import wind_at
from . import comfort, detail, fieldguide, pointer, skipperlook

INK = (238, 233, 216)
DIM = (169, 183, 175)
GOLD = (218, 187, 124)
WARN = (220, 126, 96)
# Shallow to deep; the last colour also covers anything deeper.
SONAR_BAND_COLORS = ((120, 204, 214), (92, 172, 196), (70, 136, 176), (52, 104, 150))
GOOD = (150, 196, 140)
# The backing behind text that sits on the lake itself (haul, credits, encounter): at this
# strength every text colour above reads at 4.5:1 or better over the brightest sky (V1-43).
TEXT_BACKING = (9, 17, 19)
TEXT_BACKING_ALPHA = 0.80
# HUD panels: dark enough that DIM text keeps 4.5:1 over a white noon sky.
HUD_PANEL_ALPHA = 0.74
GAME_TITLE = "Trotline Purridise"
BOOK_STAGE_UP_COUNTS = frozenset(
    threshold for threshold, _stage in BOOK_STAGES if threshold >= 3
)

SHOP_TABS = ("Sell", "Bait", "Gear", "Paint", "Boats", "Lakes", "Kitchen", "Bot")
_TABS = SHOP_TABS
TEXT_SIZE_SCALES = (0.9, 1.0, 1.15)
MODES = comfort.MODES
SETTINGS_ROW_COUNT = 13
SETTINGS_KEYBOARD_CONTROLS_ROW = SETTINGS_ROW_COUNT - 1
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
    "active": "Accepted",
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


def _active_hud_quest(state, content):
    """Choose the first accepted quest for this lake and its next useful status."""
    for quest_id in journal_quest_ids(state, content):
        quest = content.quests.get(quest_id)
        progress = state.narrative.quests.get(quest_id)
        if (quest is None or progress is None or progress.status not in ("active", "ready")
                or quest.get("lake_id") != state.lake_id):
            continue
        details = quest_journal_details(state, content, quest_id)
        summary = details["progress"]
        objective = quest.get("objective")
        if progress.status == "active" and "kind" in quest:
            summary = details["objective"].removeprefix("Story — ")
        elif (progress.status == "active" and isinstance(objective, dict)
              and objective.get("type") == "line_scout"):
            if summary == "No qualifying line set yet.":
                summary = (f"Set the {objective['hook_count']}-hook line; "
                           "send Bot (B) to scout.")
            elif "Bot report pending" in summary:
                summary = "Line set · send Bot (B) to report."
        return details["title"], summary
    return None


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
    """Native menu focus and the last draw's semantic pointer geometry.

    ``pointer`` rectangles use frame pixels and are valid only for its published
    context/viewport. Selection fields remain shared by keyboard, pad and hover.
    """

    mode: str = "title"
    input_device: str = "keyboard"
    pointer: pointer.Registry = field(default_factory=pointer.Registry)
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
    # The Field Guide (fieldguide, #139): the open spread. Each draw records the spread
    # count (0 until the guide is first drawn) and the topics on the open pages.
    help_spread: int = 0
    help_spreads: int = 0
    help_shown: tuple = ()
    help_from: str = "play"
    title_i: int = 0
    confirm_new: bool = False
    new_mode_i: int = 0
    comfort_i: int = 0
    needs_kind: str = ""
    nap_timer: float = 0.0
    nap_forced: bool = False
    kitchen_from: str = "play"
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
    # Seconds the conversation has been open, and the current line on screen; the session
    # advances both and the portrait animates from them (portraitmotion).
    dialogue_s: float = 0.0
    dialogue_line_s: float = 0.0
    # V1-34 Settle In: whether the Skipper is settling, and the HUD's prompt for it.
    settling: bool = False
    settle_prompt: str = ""
    credits_s: float = 0.0  # real seconds the credits have shown
    # V1-35 staging: the fade and letterbox over a story scene, and how far the credits have risen.
    stage_fx: dict | None = None
    stage_skip: bool = False  # a replayed scene's staging can be skipped with Esc (B)
    vignette: dict | None = None  # the story moment's card: {"kind", "detail", "t"} (V1-35)
    credits_rise: float = math.inf
    # The Skipper creator (skipperlook): the draft look and its row, whether the name is being
    # typed, the creator's own clock (advanced by frame dt, never by wall time), and the card.
    skipper_i: int = 0
    skipper_origin: str = "pause"  # "new": Done starts the morning; "pause": Done returns to the pause menu
    skipper_look: dict | None = None
    skipper_typing: bool = False
    skipper_fresh: bool = False  # the name is selected on entry: the first typed key replaces it
    skipper_clock: float = 0.0  # UI seconds the creator has been open
    skipper_changed_at: float = -99.0  # the clock at the last change; far past, so no wave on open
    skipper_turn: float = 0.0  # the player's turn of the card, radians


def comfort_controls(viewport):
    """Return the two comfort-choice rectangles for a (width, height) pixel viewport."""
    width, height = viewport
    margin = max(12, min(28, width // 35))
    button_h = max(34, min(52, height // 7))
    button_w = (width - margin * 2 - 48) // 2
    y = height - margin - 16 - button_h
    return ((margin + 16, y, button_w, button_h),
            (width - margin - 16 - button_w, y, button_w, button_h))


def shop_rows(state, tab: int) -> list[Row]:
    """Build the selectable rows for one zero-based landing-shop tab.

    Returns rows in display order without mutating the game state.
    """
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
            rows.append(Row(nxt["name"], dollars(nxt["price"]), "Upgrades every tiller boat; sail, oar and console boats keep their own power.", True, "motor"))
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
        if state.boat_id != "rowboat" and state.boat.tank > 0:
            missing = state.boat.tank - state.fuel
            amount = min(5.0, missing, max(0.0, state.money) / FUEL_PRICE)
            rows.append(Row(
                f"Fuel  {state.fuel:.1f}/{state.boat.tank:.0f} L",
                f"{dollars(amount * FUEL_PRICE)} / {amount:.1f} L",
                "Refuel here; if stranded, call a tow back to this landing.",
                missing > 0.001, "fuel",
            ))
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


def pause_options(state) -> list[str]:
    """The pause menu. It also reaches every action that has no pad button of its own, so
    a player on a gamepad can do everything a keyboard player can (V1-43)."""
    items = ["Resume", "Book", "Livewell", "Your Skipper"]
    boat = getattr(state, "boat", None)
    if getattr(boat, "sail_speed", 0):
        items.append("Lower the sail" if getattr(state, "sail_raised", False) else "Raise the sail")
    scale = getattr(state, "time_scale", 1)
    items += ["Call a tow", f"Time {scale}x", "Settings", "Help", "Main menu", "Quit"]
    return items


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
        self._map_image_cache: dict[tuple[int, int, int], np.ndarray] = {}
        self._map_image_cache_bytes = 0
        # The tier's UI layer cap is shared: a third for chart images, the rest for title washes.
        layer_bytes = detail.current().ui_layer_cache_bytes
        self._map_image_cache_limit = layer_bytes // 3
        # Per-size title wash terms: keep-weight (h,w,1) and tint-add (h,w,3), uint16.
        self._title_alpha_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        self._title_alpha_cache_bytes = 0
        self._title_alpha_cache_limit = layer_bytes - self._map_image_cache_limit
        self._text_scale = 1.0
        self._dyslexia_font = False
        self._guide_layouts: OrderedDict = OrderedDict()  # the Field Guide's, newest last
        self.fish_card_renderer = None

    def close(self) -> None:
        """Release presentation caches when this UI is retired with its world."""
        self._map_image_cache.clear()
        self._map_image_cache_bytes = 0
        self._title_alpha_cache.clear()
        self._title_alpha_cache_bytes = 0
        self._cw.clear()
        self._ch.clear()
        self._guide_layouts.clear()

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
        """Paint an RGB frame and replace its context-bound menu hit targets.

        ``frame`` dimensions and published rectangles are UI pixels; ``state``
        supplies content/settings, ``ui`` receives visible geometry and native
        selection normalization, and optional ``camera`` positions lake sightings.
        Returns None; drawing never activates a menu or changes gameplay.
        """
        v2 = getattr(state, "v2", {})
        settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
        text_size = settings.get("text_size", 1)
        if type(text_size) is not int or text_size not in range(len(TEXT_SIZE_SCALES)):
            text_size = 1
        self._text_scale = TEXT_SIZE_SCALES[text_size]
        self._dyslexia_font = bool(settings.get("dyslexia_font", False))
        self._hud_rects = []  # the HUD's top panels this frame; toasts keep clear of them
        mode = ui.mode
        h, w = frame.shape[:2]
        scroll = {"title": "title", "pause": "pause", "settings": "settings",
                  "skipper": "skipper", "dialogue": "dialogue", "shop": "shop",
                  "kitchen": "kitchen", "setbait": "bait", "check": "check",
                  "well": "well", "help": "help", "journal": "book"}.get(mode, "")
        if mode == "settings" and ui.settings_page == "keys":
            scroll = "keys"
        elif mode == "cook_confirm" and ui.cook_kind in {"dish", "cookout"}:
            scroll = "cook_fish"
        ui.pointer.begin(pointer.context(state, ui), (w, h), scroll)
        self._caption_floor = None
        if mode == "play":
            draw_sighting(frame, state, camera)
        if mode == "title":
            self._title(frame, state, ui)
            self._caption(frame, state, ui)
            self._toasts(frame, state, ui.input_device)
            self._pointer_outline(frame, state, ui)
            return
        if mode == "play" and ui.whale_return:
            # The Star-Whale comes back (V1-37): the HUD steps aside under a letterbox.
            from .staging import overlay
            overlay(frame, ui.stage_fx)
            h, w = frame.shape[:2]
            size = self._size(frame, "small")
            label = self._controls(ui, "Esc · Skip", "B · Skip")
            button_w = self._measure(label, size, "sans") + 24
            button_h = self.cell(size)[1] + 8
            self._pointer_button(frame, ui, label,
                                 ((w - button_w) // 2, h - button_h - 10, button_w, button_h), "skip_whale")
            self._caption(frame, state, ui)
            self._toasts(frame, state, ui.input_device)
            self._pointer_outline(frame, state, ui)
            return
        if mode == "play":
            if comfort.drowsy(state.v2):
                self._drowsy_edges(frame)
            # Only in play is the control-hint bar the bottom-most thing on screen;
            # the map and dialogue panels cover it, so captions stay at the edge there.
            self._caption_floor = self._hud(frame, state, ui)
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
            self._pointer_outline(frame, state, ui)
            return
        if mode == "map":
            # The chart is a full-screen information surface; drawing the play HUD
            # underneath it makes its footer and map labels collide at compact sizes.
            self._map(frame, state, ui, big=True)
            # Toasts float across the lake view, but collide with the chart title
            # and footer on compact screens; the chart is a deliberate focus mode.
            self._pointer_outline(frame, state, ui)

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
            self._pause(frame, state, ui)
        elif mode == "settings":
            if ui.settings_page == "keys":
                self._keybindings(frame, state, ui)
            else:
                self._settings(frame, state, ui)
        elif mode == "skipper":
            self._skipper(frame, state, ui)
        elif mode == "help":
            self._help(frame, ui, state)
        elif mode == "credits":
            self._credits(frame, state, ui)
        self._caption(frame, state, ui)
        self._pointer_outline(frame, state, ui)

    def _pointer_button(self, frame, ui, label, rect, action="back", field="", value=None,
                        *, selected=False, size=None):
        """Draw and publish one measured button; later controls win overlapping hits."""
        x, y, width, height = (int(part) for part in rect)
        self._round_fill(frame, x, y, width, height, GOLD if selected else (46, 66, 62), 1)
        size = self._size(frame, "small") if size is None else size
        color = (22, 39, 39) if selected else INK
        while size > 1 and (self._measure(label, size, "sans") > width - 10
                           or self._render(label, size, color, "sans").shape[0] > height - 4):
            size -= 1
        glyph_h = self._render(label, size, color, "sans").shape[0]
        self._center(frame, label, x + width / 2, y + (height - glyph_h) // 2,
                     size, color, "sans")
        ui.pointer.add((x, y, width, height), action, field, value)

    def _pointer_outline(self, frame, state, ui):
        """Publish normalized display identity and outline pointer-owned semantic focus."""
        ui.pointer.identity = pointer.context(state, ui)
        target = ui.pointer.hovered
        if ui.pointer.owner != "pointer" or target is None or target not in ui.pointer.targets:
            return
        x, y, width, height = (int(part) for part in target.rect)
        for inset, color in ((0, (22, 39, 39)), (1, GOLD)):
            self._fill(frame, x + inset, y + inset, width - inset * 2, 1, color, 1)
            self._fill(frame, x + inset, y + height - 1 - inset, width - inset * 2, 1, color, 1)
            self._fill(frame, x + inset, y + inset, 1, height - inset * 2, color, 1)
            self._fill(frame, x + width - 1 - inset, y + inset, 1, height - inset * 2, color, 1)

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
        # A dark column behind the names, so they keep AA contrast over a bright dawn (V1-43).
        column = max(self._measure(text, size, "sans") for text, size, _color in rows if text) + 48
        self._fill(frame, int(w / 2 - column / 2), 0, int(column), h, TEXT_BACKING, 0.72)
        for text, size, color in rows:
            if -40 < y < h:
                self._center(frame, text, w / 2, y, size, color)
            y += self.cell(size)[1] + 8
        if ui.credits_s >= CREDITS_HOLD_S:  # keys do nothing while the credits hold
            hint = self._controls(ui, "Press any key to keep fishing.", "Press A to keep fishing.")
            self._backed(frame, hint, w / 2, int(h * 0.82), small, DIM, "sans", center=True)
            ui.pointer.add((0, 0, w, h), "activate")

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
        # The speaker's portrait sits at the left when the frame has room (V1-29), and breathes,
        # blinks and bobs as it speaks (portraitmotion). Bot's card wears his current shell and collar.
        from .catart import portrait_rig
        from .botidentity import format_text
        from .botportrait import BOT, look
        from .portraitmotion import portrait_motion
        text = format_text(node['text'], state)
        side = min(176, max(96, h // 4))
        rig = None
        if w >= 640:
            rig = (portrait_rig(BOT, side, look(state)) if chat.npc_id == BOT
                   else portrait_rig(chat.npc_id, side))
        portrait = None
        if rig is not None:
            v2 = getattr(state, "v2", {})
            reduced = bool(isinstance(v2, dict) and v2.get("settings", {}).get("reduced_motion", False))
            portrait = rig.frame(portrait_motion(chat.npc_id, text, ui.dialogue_s, ui.dialogue_line_s,
                                                 reduced_motion=reduced))
        inset = side + margin if portrait is not None else 0
        cols = max(8, (width - margin*2 - inset) // cw)
        lines = textwrap.wrap(text, cols)
        choices = node.get('choices', [])
        foot = self._controls(
            ui, "W/S or arrows choose · Enter selects · Esc leave · H Help",
            "D-pad choose · A select · B leave · RB continue",
        )
        if not choices:
            foot = self._controls(ui, "C / Enter / Space continue · Esc leave · H Help",
                                  "A continue · B leave · RB continue")
        scene = bool(node.get('scene'))
        if scene:
            foot = (self._controls(ui, "W/S or arrows choose · Enter selects · H Help",
                                  "D-pad choose · A select · RB continue") if choices else
                    self._controls(ui, "C / Enter / Space continue · H Help", "A continue · RB continue"))
            if ui.stage_skip:
                foot += self._controls(ui, " · Esc skips staging", " · B skips staging")
        wrapped_choices = []
        for index, choice in enumerate(choices):
            prefix = f"{index + 1}. "
            content = textwrap.wrap(format_text(choice['text'], state), max(1, cols - len(prefix) - 2)) or [""]
            marker = ">" if index == chat.selected else " "
            wrapped_choices.append([f"{marker} {prefix}{content[0]}",
                                    *[" " * (len(prefix) + 2) + line for line in content[1:]]])
        footer = textwrap.wrap(foot, cols)
        button_h = max(24, ch + 8)
        capacity = len(choices)
        if choices:
            available = ((h - 24 - margin * 2 - button_h - 10) // (ch + 3)
                         - len(lines) - len(footer) - 4)
            capacity = max(1, available // max(len(choice) for choice in wrapped_choices))
        start, end = ui.pointer.window("dialogue", chat.selected, len(choices), max(1, capacity))
        rows = lines + ['']
        colors = [INK] * len(lines) + [DIM]
        choice_rows = []
        for index in range(start, end):
            wrapped = wrapped_choices[index]
            choice_rows.append((index, len(rows), len(wrapped)))
            rows.extend(wrapped)
            colors.extend([GOLD if index == chat.selected else DIM] * len(wrapped))
        if end - start < len(choices):
            footer = [f"Choices {start + 1}–{end} of {len(choices)} · Scroll to browse", *footer]
        height = (len(rows) + len(footer) + 2) * (ch + 3) + margin * 2 + button_h + 10
        if portrait is not None:
            height = max(height, side + margin * 2)
        x, y = (w - width) // 2, h - height - 12
        self._panel(frame, x, y, width, height, 0.96)
        if portrait is not None:
            self._blit_rgb(frame, portrait, x + margin, y + margin)
        text_x = x + margin + inset
        text_w = width - margin * 2 - inset
        self._text(frame, name, text_x, y + margin, size, GOLD, False)
        top = y + margin + (ch + 3) * 2
        for index, (line, color) in enumerate(zip(rows + footer, colors + [DIM] * len(footer))):
            self._text(frame, line, text_x, top + index * (ch + 3), size, color, False)
        for index, first_row, row_count in choice_rows:
            ui.pointer.add((text_x - 4, top + first_row * (ch + 3) - 1,
                            text_w + 8, row_count * (ch + 3)),
                           "activate", "dialogue_selected", index)
        buttons = ([] if choices else [("Continue", "activate")]) + [("Help", "help")]
        if not scene:
            buttons.append(("Leave", "back"))
        elif ui.stage_skip:
            buttons.append(("Skip staging", "skip_scene"))
        button_w = (text_w - (len(buttons) - 1) * 8) // len(buttons)
        button_y = y + height - margin - button_h
        for index, (label, action) in enumerate(buttons):
            self._pointer_button(frame, ui, label,
                                 (text_x + index * (button_w + 8), button_y, button_w, button_h), action)
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
                skip = self._controls(ui, "Click / Esc skip · Hold E hurries", "B skip · Hold A hurries")
                sy = int(h * 0.95)
                self._backed(frame, skip, w / 2, sy, small, DIM, "sans", center=True)
                sw = min(w, self._measure(skip, small, "sans"))
                ui.pointer.add(((w - sw) // 2, sy, sw, min(h - sy, self.cell(small)[1])), "activate")
            return
        title = f"HAULING  {index + 1:02d} / {len(line.hooks):02d}"
        self._backed(frame, title, int(w * 0.055), int(h * 0.06), head, INK)
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
        self._backed(frame, result, w / 2, int(h * 0.73), body, result_color, "sans", center=True)
        speed_label = {"normal": "Normal", "quick": "Quick", "instant": "Instant"}.get(speed, "Normal")
        self._backed(frame, f"{speed_label} speed", int(w * 0.055), int(h * 0.13), small, GOLD)
        foot = self._controls(ui, "Click continues · Hold E 3× · Esc summary",
                              "Hold A 3× · A skips a card · B summary")
        fy = int(h * 0.95)
        self._backed(frame, foot, w / 2, fy, small, INK, "sans", center=True)
        fw = min(w, self._measure(foot, small, "sans"))
        ui.pointer.add(((w - fw) // 2, fy, fw, min(h - fy, self.cell(small)[1])), "activate")
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
        heading = "A LEGENDARY SURFACES" if catch.legendary else "A FISH SURFACES"
        self._center(frame, heading, w / 2, y + 18,
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
        foot = self._controls(ui, "Click / any key except E continues · Hold E hurries",
                              "A continues · Hold A speeds the haul")
        fy = y + ph - self.cell(small)[1] - 10
        self._center(frame, foot, w / 2, fy, small, DIM)
        fw = min(w, self._measure(foot, small, "sans"))
        ui.pointer.add(((w - fw) // 2, fy, fw, self.cell(small)[1]), "activate")

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
        alpha = patch[:, :, 3:4].astype(np.uint16)
        region = dst[y0:y1, x0:x1]
        region[:] = (
            region.astype(np.uint16) * (255 - alpha)
            + patch[:, :, :3].astype(np.uint16) * alpha
        ) // 255

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
            # One row of the colour, copied down: numpy copies whole rows many times faster
            # than it spreads a 3-tuple over every pixel, which matters for the page-sized
            # fills of the Field Guide's paper.
            region = dst[y0:y1, x0:x1]
            region[0] = rgb
            region[1:] = region[0]
            return
        # Weights out of 256 so the divide is a shift; rounding stays within one level.
        weight = min(256, max(0, int(alpha * 256 + 0.5)))
        region = dst[y0:y1, x0:x1]
        work = region.astype(np.uint16)
        work *= 256 - weight
        work += np.asarray(rgb, np.uint16) * weight + 128
        work >>= 8
        region[:] = work

    def _panel(self, dst, x, y, w, h, alpha=0.82):
        self._round_fill(dst, x+2, y+4, w, h, (5, 10, 10), 0.20)
        self._round_fill(dst, x, y, w, h, (17, 31, 32), alpha)
        self._fill(dst, x+10, y, w-20, 1, GOLD, 0.34)

    def _backed(self, frame, s, x, y, size, color, family="mono", center=False) -> int:
        """Text drawn straight over the lake, on its own soft dark backing (V1-43).

        A drop shadow alone falls below WCAG AA contrast over a bright sky. Behind the
        backing, every UI text colour reads at 4.5:1 or better, even over white sky."""
        if not s:
            return 0
        width = self._measure(s, size, family)
        height = self._render(s, size, color, family).shape[0]
        left = x - width / 2 if center else x
        pad = max(4, size // 3)
        self._round_fill(frame, left - pad, y - pad // 2, width + pad * 2, height + pad,
                         TEXT_BACKING, TEXT_BACKING_ALPHA)
        return self._text(frame, s, left, y, size, color, False, family)

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
            a = (np.clip(r+0.5-np.hypot(dx,dy),0,1)*alpha*255+0.5).astype(np.uint16)[...,None]
            region = dst[ay:by,ax:bx]
            region[:] = (
                region.astype(np.uint16) * (255-a)
                + np.asarray(rgb,np.uint16) * a
            ) // 255

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

    def _trim(self, s: str, size: int, width: int, family: str = "mono") -> str:
        """Shorten `s` with ".." to fit `width` pixels in the font it will be drawn in."""
        if family != "mono":
            # Proportional text is narrower than the mono cell estimate, which
            # used to cut captions that had room to spare.
            if self._measure(s, size, family) <= width:
                return s
            low, high = 1, len(s)
            while low < high:
                mid = (low + high + 1) // 2
                if self._measure(s[:mid] + "..", size, family) <= width:
                    low = mid
                else:
                    high = mid - 1
            return s[:low] + ".."
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
        clock_size = max(22,int(30*unit))
        meta = weather
        if self.world.id == "nebula":
            # The Lagoon names its bands Rising, Bright, Fading and Deep (03 §1.6).
            from .data import hour_of_day
            from .nebula import band_label
            meta = band_label(hour_of_day(state.game_minutes)).upper() + "  /  " + weather
        if state.time_scale!=1:
            meta += f"  /  {state.time_scale}x" + ("" if state.fast_ok() else " held")
        # As wide as its clock at the largest text (V1-43).
        lw = max(int(205*unit)+34, self._measure(clock,clock_size,"serif")+34,
                 self._measure(self.world.name.upper(),small,"sans")+34, self._measure(meta,small,"sans")+34)
        lh = int(92*unit)+10
        meta_y = m+int(71*unit)
        hud_quest = _active_hud_quest(state, self.narrative_content)
        if hud_quest is not None:
            # The tracker may widen the panel, but never past 42% of the screen.
            quest_title = "QUEST · " + hud_quest[0]
            quest_progress = hud_quest[1]
            content_width = max(self._measure(quest_title, small, "sans"),
                                self._measure(quest_progress, small, "sans"))
            lw = max(lw, min(int(w*.42), content_width+32))
            quest_title = self._trim(quest_title, small, lw-32, "sans")
            quest_progress = self._trim(quest_progress, small, lw-32, "sans")
            quest_y = meta_y+self.cell(small)[1]+max(2,int(3*unit))
            progress_y = quest_y+self.cell(small)[1]+max(1,int(2*unit))
            lh = max(lh, progress_y+self.cell(small)[1]+10-m)
        lw = min(w-2*m, lw)
        self._panel(frame,m,m,lw,lh,HUD_PANEL_ALPHA)
        if getattr(self, "_hud_rects", None) is None:
            self._hud_rects = []
        self._hud_rects.append((m, m, lw, lh))
        self._text(frame,self.world.name.upper(),m+16,m+int(11*unit),small,GOLD,False,"sans")
        self._text(frame,clock,m+16,m+int(31*unit),clock_size,INK,False,"serif")
        self._text(frame,meta,m+16,meta_y,small,DIM,False,"sans")
        if hud_quest is not None:
            self._text(frame,quest_title,m+16,quest_y,small,GOLD,False,"sans")
            self._text(frame,quest_progress,m+16,progress_y,small,INK,False,"sans")
        zone = self.world.zone_name(self.world.zone_at(state.x, state.z))
        zone_width = self._measure(zone,size+4,"serif")
        rx = w-m-max(int(194*unit),zone_width+32)
        rw = w-m-rx
        self._panel(frame,rx,m,rw,int(140*unit)+10,HUD_PANEL_ALPHA)
        self._hud_rects.append((rx, m, rw, int(140*unit)+10))
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
        if state.boat.fuelled and state.boat.tank > 0 and state.fuel < state.boat.tank * 0.15:
            level = "EMPTY" if state.fuel <= 0.001 else "LOW FUEL"
            recovery = self._controls(ui, "R tow · Boats", "Call tow · Boats")
            label = self._trim(f"{level} · {recovery}", small, rw - 32)
            self._text(frame, label, rx + 16, m + int(131 * unit), small, WARN, False, "sans")
        elif state.boat.power == "sail":
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
        return hint_y

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
            kind = self._line_kind(line)
            self._seg(frame, line.x0, line.z0, line.x1, line.z1, x, y, mw, mh, self._line_color(line),
                      dashed=kind == "soak")
            if kind == "tired":
                u, v = self.world.map_pixel((line.x0 + line.x1) / 2, (line.z0 + line.z1) / 2, mw, mh)
                self._marker(frame, "tired", x + u, y + v)
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

    def _line_kind(self, line) -> str:
        if any(h.catch is not None and h.catch.age >= 9.0 for h in line.hooks):
            return "tired"
        return "fish" if line.fish_on() else "soak"

    def _line_color(self, line):
        return {"tired": WARN, "fish": (232, 176, 72)}.get(self._line_kind(line), (126, 168, 146))

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
        chart = self.world.map_rgb
        margin = max(12, min(28, w // 40))
        gap = max(10, w // 80)
        size = self._size(frame, "small")
        button_h = max(24, self.cell(size)[1] + 8)
        actions = [("Hail", "map_hail"),
                   ("Weigh anchor" if state.anchored else "Anchor", "map_anchor")]
        if getattr(state.boat, "sail_speed", 0):
            actions.append(("Lower sail" if state.sail_raised else "Raise sail", "map_sail"))
        actions += [("Call tow", "map_tow"),
                    ("Send Bot" if state.bot_phase == "home" else "Recall Bot", "map_bot")]
        columns = 3 if len(actions) > 4 else 2
        rows = (len(actions) + columns - 1) // columns
        x, y = margin, int(h * 0.10)
        available_width = w - 2 * margin - gap
        mw = int(available_width * 0.62)
        mh = int(mw * chart.shape[0] / chart.shape[1])
        max_map_h = h - y - margin - rows * (button_h + 6) - 12
        if mh > max_map_h:
            mh = max_map_h
            mw = int(mh * chart.shape[1] / chart.shape[0])
        # A shallow window can drive max_map_h negative; _fit needs positive samples.
        mh, mw = max(1, mh), max(1, mw)
        # Reserve the chart's lower edge for the same actions its native keys expose.
        key_x = x + mw + gap
        key_w = w - margin - key_x
        key_h = h - y - margin
        map_key = (id(chart), mw, mh)
        scaled = self._map_image_cache.get(map_key)
        if scaled is None:
            scaled = _fit(chart, mw, mh)
            if scaled.nbytes <= self._map_image_cache_limit:
                self._map_image_cache.clear()
                self._map_image_cache[map_key] = scaled
                self._map_image_cache_bytes = scaled.nbytes
        # The opaque chart overwrites nearly half the frame, so the wash and the
        # panel are blended only in the four strips around it.
        for view, ox, oy in ((frame[:y], 0, 0), (frame[y + mh:], 0, y + mh),
                             (frame[y:y + mh, :x], 0, y), (frame[y:y + mh, x + mw:], x + mw, y)):
            self._fill(view, -ox, -oy, w, h, (8, 10, 8), 0.45)
            self._panel(view, x - 8 - ox, y - 8 - oy, mw + 16, mh + 16, 0.88)
        frame[y:y + mh, x:x + mw] = scaled
        for line in state.lines:
            color = self._line_color(line)
            self._seg(frame, line.x0, line.z0, line.x1, line.z1, x, y, mw, mh, color,
                      dashed=self._line_kind(line) == "soak")
            if comfort.has_buff(state, "glow_buoys"):
                for bx, bz in line.buoys():
                    bu, bv = self.world.map_pixel(bx, bz, mw, mh)
                    self._dot(frame, x + bu, y + bv, 4, GOLD)
            n = max(1, len(line.hooks))
            markers = []
            for i, hook in enumerate(line.hooks):
                t = (i + 0.5) / n
                hx = line.x0 + (line.x1 - line.x0) * t
                hz = line.z0 + (line.z1 - line.z0) * t
                if hook.catch is not None and hook.catch.age >= 9.0:
                    kind = "tired"
                elif hook.catch is not None:
                    kind = "fish"
                elif hook.baited:
                    kind = "bait"
                else:
                    kind = "empty"
                markers.append((kind in ("fish", "tired"), kind, *self.world.map_pixel(hx, hz, mw, mh)))
            # Fish and tired fish last, so a neighbouring hook never covers their shape.
            for _on_top, kind, u, v in sorted(markers, key=lambda m: m[0]):
                self._marker(frame, kind, x + u, y + v)
        sonar_cells = sonar.overlay(state, self.world)
        self._plot_sonar(frame, sonar_cells, x, y, mw, mh)
        marker_size = max(8, min(12, h // 60))
        places = self._plot_habitats(frame, x, y, mw, mh, marker_size)
        badge_radius = max(14, marker_size + 6) // 2
        protected_markers = [
            (px, py, badge_radius) for _number, _name, px, py in places
        ]
        if self.world.id == "cedar":
            anchor = self.world.anchors.get("cedar:trinidad_cove")
            if anchor is not None:
                number = len(places) + 1
                u, v = self.world.map_pixel(anchor.x, anchor.z, mw, mh)
                self._draw_map_badge(frame, x + u, y + v, number, marker_size)
                places.append((number, anchor.name, x + u, y + v))
                protected_markers.append((x + u, y + v, badge_radius))
        tip_marker = self._plot_invitation(frame, state, x, y, mw, mh)
        if tip_marker is not None:
            protected_markers.append(tip_marker)
        residents = self._plot_npcs(frame, state, x, y, mw, mh, large=True,
                                    protected=protected_markers)
        self._plot_boat(frame, state, x, y, mw, mh, radius=4)
        self._plot_bot(frame, state, x, y, mw, mh)
        top = max(4, y - self.cell(size)[1] - 10)
        close_w = min(mw // 2, self._measure("Tab · Close", size, "sans") + 16)
        close_hint = self._controls(ui, "Tab · Close", "B · Close")
        self._backed(frame, self._trim(self.world.name, size, mw - close_w - 8),
                     x, top, size, INK)
        self._pointer_button(frame, ui, close_hint,
                             (x + mw - close_w, top - 2, close_w, self.cell(size)[1] + 6))
        self._map_key(frame, state, key_x, y, key_w, key_h, places, residents,
                      bool(sonar_cells))
        action_w = (mw - (columns - 1) * 8) // columns
        for index, (label, action) in enumerate(actions):
            bx = x + index % columns * (action_w + 8)
            by = y + mh + 12 + index // columns * (button_h + 6)
            self._pointer_button(frame, ui, label, (bx, by, action_w, button_h), action)

    def legend_items(self, state, sonar_bands=False) -> list[tuple[str, str]]:
        """(marker kind, words) for the chart key. Every kind differs in shape, not only
        colour, so the key reads with any colour vision (V1-43)."""
        from .botidentity import name as bot_name
        items = [("fish", "fish on"), ("tired", "tired fish"), ("soak", "soaking line"),
                 ("cat", "cat"), ("bot", bot_name(state)), ("tip", bot_name(state) + "'s weather tip"),
                 ("boat", "you")]
        if sonar_bands:
            items.append(("sonar", "sonar depth"))
        return items

    def _map_key(self, frame, state, x, y, width, height, places, residents, sonar_visible):
        """Explain the chart's numbered places, resident pins and marker shapes in a side panel.

        `places` holds (number, name, ...) tuples from `_plot_habitats`; `residents` holds
        (name, coat rgb) pairs from `_plot_npcs`. Residents are omitted when the full list
        would push the marker legend off the panel.
        """
        self._panel(frame, x, y, width, height, 0.88)
        size = max(8, min(13, frame.shape[0] // 60))
        row_h = max(12, self.cell(size)[1] + 2)
        pad = max(8, min(14, width // 14))
        left = x + pad
        text_w = max(1, width - 2 * pad - 22)
        title_size = min(16, size + 2)
        cursor = y + 8
        self._text(frame, "CHART KEY", left, cursor, title_size, GOLD, False, "sans")
        cursor += self.cell(title_size)[1] + 3
        legend = self.legend_items(state, sonar_visible)
        available_rows = max(0, (y + height - 8 - cursor) // row_h)
        fixed_rows = 1 + len(places) + 1 + len(legend)
        show_residents = bool(residents) and fixed_rows + 1 + len(residents) <= available_rows
        marker_size = max(8, min(10, size))
        self._text(frame, "PLACES", left, cursor, size, GOLD, False, "sans")
        cursor += row_h
        for number, name, *_ in places:
            self._draw_map_badge(frame, left + marker_size // 2 + 2,
                                 cursor + row_h // 2, number, marker_size)
            self._text(frame, self._trim(name, size, text_w, "sans"),
                       left + 22, cursor, size, INK, False, "sans")
            cursor += row_h
        if show_residents:
            self._text(frame, "RESIDENTS", left, cursor, size, GOLD, False, "sans")
            cursor += row_h
            for name, pin in residents:
                self._shape(frame, "disc", left + 7, cursor + row_h // 2, 3, pin)
                self._text(frame, self._trim(name, size, text_w, "sans"),
                           left + 22, cursor, size, INK, False, "sans")
                cursor += row_h
        self._text(frame, "MARKERS", left, cursor, size, GOLD, False, "sans")
        cursor += row_h
        for kind, words in legend:
            if cursor + row_h > y + height - 4:
                break
            self._marker(frame, kind, left + 7, cursor + row_h // 2, legend=True)
            self._text(frame, self._trim(words, size, text_w, "sans"),
                       left + 22, cursor, size, DIM, False, "sans")
            cursor += row_h

    def _draw_map_badge(self, frame, x, y, number, size):
        """Draw a numbered habitat icon whose matching name appears in the chart key."""
        diameter = max(14, size + 6)
        radius = diameter // 2
        self._round_fill(frame, x - radius, y - radius, diameter, diameter, GOLD, 1.0)
        inner = diameter - 4
        inner_radius = inner // 2
        self._round_fill(frame, x - inner_radius, y - inner_radius, inner, inner,
                         (17, 31, 32), 1.0)
        number_size = max(8, min(size, inner - 2))
        self._center(frame, str(number), x, y - self.cell(number_size)[1] // 2,
                     number_size, GOLD, "sans")

    def _draw_tip_halo(self, frame, cx, cy, radius):
        """Outline Bot's weather-tip mark without obscuring the chart beneath."""
        radius = max(3, int(radius))
        thickness = max(1, radius // 6)
        side = radius * 2 + 1
        inner = side - thickness * 2
        self._fill(frame, cx - radius, cy - radius, side, thickness, GOLD, 1.0)
        self._fill(frame, cx - radius, cy + radius - thickness + 1,
                   side, thickness, GOLD, 1.0)
        self._fill(frame, cx - radius, cy - radius + thickness,
                   thickness, inner, GOLD, 1.0)
        self._fill(frame, cx + radius - thickness + 1, cy - radius + thickness,
                   thickness, inner, GOLD, 1.0)

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
        radius = max(11, min(16, mw // 40)) if mw >= 400 else 8
        self._draw_tip_halo(frame, x + u, y + v, radius)
        return (x + u, y + v, radius)
    def _plot_habitats(self, frame, x, y, mw, mh, marker_size=None):
        """Badge every habitat with its number; the names live in the chart key.

        `marker_size` is the badge text size in pixels (defaults from frame height).
        Returns (number, name, badge x, badge y) per habitat, in zone order.
        """
        chains = {}
        for zone, cx, cz, _radius in self.world.zones:
            chains.setdefault(zone, []).append((cx, cz))
        marker_size = max(8, min(12, frame.shape[0] // 60)) if marker_size is None else marker_size
        places = []
        for number, (zone, points) in enumerate(chains.items(), 1):
            cx, cz = points[len(points) // 2]
            u, v = self.world.map_pixel(cx, cz, mw, mh)
            self._draw_map_badge(frame, x + u, y + v, number, marker_size)
            places.append((number, self.world.zone_name(zone), x + u, y + v))
        return places

    def _plot_trinidad_cove(self, frame, x, y, mw, mh):
        if self.world.id != "cedar":
            return
        anchor = self.world.anchors.get("cedar:trinidad_cove")
        if anchor is None:
            return
        u, v = self.world.map_pixel(anchor.x, anchor.z, mw, mh)
        self._shape(frame, "diamond ring", x + u, y + v, 4, (240, 198, 112))

    def _plot_npcs(self, frame, state, x, y, mw, mh, large=False, protected=()):
        """Pin each resident cat on the chart in its coat colour.

        `large` draws the full-chart pin size; `protected` lists (x, y, radius) frame-pixel
        markers that a pin must not cover, so it steps aside from them. Returns
        (name, coat rgb) pairs for the chart key.
        """
        from .actors import roster
        fallback = (128, 206, 240)
        cats = roster()
        residents = []
        radius = 3 if large else 2
        obstacles = [
            (cx, cy, marker_radius + radius + 3)
            for cx, cy, marker_radius in protected
        ]
        directions = ((0, -1), (1, 0), (0, 1), (-1, 0),
                      (1, -1), (1, 1), (-1, 1), (-1, -1))
        for npc in state.npcs:
            if npc.anchor.lake_id != self.world.id:
                continue
            u, v = self.world.map_pixel(npc.anchor.x, npc.anchor.z, mw, mh)
            pin_x, pin_y = x + u, y + v
            collisions = [
                clearance for cx, cy, clearance in obstacles
                if (pin_x - cx) ** 2 + (pin_y - cy) ** 2 < clearance ** 2
            ]
            if collisions:
                min_x, max_x = x + radius + 1, x + mw - radius - 2
                min_y, max_y = y + radius + 1, y + mh - radius - 2
                moved = False
                for distance in (max(18, max(collisions) + 2),
                                 max(26, max(collisions) + 10),
                                 max(34, max(collisions) + 18)):
                    for dx, dy in directions:
                        candidate_x = max(min_x, min(max_x, pin_x + dx * distance))
                        candidate_y = max(min_y, min(max_y, pin_y + dy * distance))
                        if all((candidate_x - cx) ** 2 + (candidate_y - cy) ** 2
                               >= clearance ** 2
                               for cx, cy, clearance in obstacles):
                            pin_x, pin_y = candidate_x, candidate_y
                            moved = True
                            break
                    if moved:
                        break
            # Each pin wears its cat's coat, ringed so pale coats read on the chart (V1-29),
            # and is round so no colour vision mistakes it for a fish or the Bot (V1-43).
            row = cats.get(npc.id)
            pin = (tuple(int(c * 255 + 0.5) for c in row["appearance"]["colors"]["base"])
                   if row is not None else fallback)
            self._shape(frame, "disc", pin_x, pin_y, radius, pin)
            residents.append((npc.name, pin))
        return residents

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
        self._marker(frame, "bot", x + u, y + v)

    def _seg(self, frame, x0, z0, x1, z1, ox, oy, mw, mh, rgb, dashed=False):
        u0, v0 = self.world.map_pixel(x0, z0, mw, mh)
        u1, v1 = self.world.map_pixel(x1, z1, mw, mh)
        steps = max(abs(u1 - u0), abs(v1 - v0), 1)
        samples = np.arange(steps + 1, dtype=np.float64) / steps
        if dashed:
            samples = samples[np.arange(steps + 1) % 6 < 3]
        xs = (ox + u0 + (u1 - u0) * samples).astype(np.intp)
        ys = (oy + v0 + (v1 - v0) * samples).astype(np.intp)
        height, width = frame.shape[:2]
        for dy in (-1, 0, 1):
            py = ys + dy
            valid_y = (py >= 0) & (py < height)
            if not valid_y.any():
                continue
            for dx in (-1, 0, 1):
                px = xs + dx
                valid = valid_y & (px >= 0) & (px < width)
                frame[py[valid], px[valid]] = rgb

    def _marker(self, frame, kind, x, y, legend=False):
        """One chart marker. Shape carries the meaning and colour only repeats it (V1-43)."""
        if kind == "fish":
            self._shape(frame, "fish", x, y, 5 if legend else 3, (255, 214, 120))
        elif kind == "tired":
            self._shape(frame, "cross", x, y, 5 if legend else 3, WARN)
        elif kind == "bait":
            self._dot(frame, x, y, 1, (186, 214, 196))
        elif kind == "empty":
            self._dot(frame, x, y, 1, (90, 104, 98))
        elif kind == "soak":
            # A soaking line on the chart is a row of baited hooks along a dashed line.
            for k in (-6, -2, 2, 6):
                self._dot(frame, x + k, y, 1, (186, 214, 196))
        elif kind == "cat":
            self._shape(frame, "disc", x, y, 4 if legend else 3, (200, 162, 118))
        elif kind == "bot":
            self._shape(frame, "triangle", x, y, 5 if legend else 4, (255, 148, 48))
        elif kind == "tip":
            # Hollow, so the numbered place badge under a tip stays readable.
            self._draw_tip_halo(frame, x, y, 6 if legend else 11)
        elif kind == "boat":
            self._dot(frame, x - 2, y, 3, (236, 224, 180))
            self._dot(frame, x + 5, y, 1, (232, 196, 110))
        elif kind == "sonar":
            for k, color in enumerate(SONAR_BAND_COLORS):
                self._dot(frame, x - 5 + k * 3, y, 1, color)

    def _shape(self, frame, shape, x, y, r, rgb):
        """A small shape (square, cross, disc, diamond, diamond ring, triangle or fish)
        with a dark edge, so it reads on pale and dark chart paper alike."""
        h, w = frame.shape[:2]
        cx, cy = int(x), int(y)
        rr = r + 1
        yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]

        def mask_for(size):
            if shape == "square":
                return (np.abs(xx) <= size) & (np.abs(yy) <= size)
            if shape == "cross":
                return ((np.abs(xx - yy) <= 1) | (np.abs(xx + yy) <= 1)) & (np.abs(xx) <= size) & (np.abs(yy) <= size)
            if shape == "disc":
                return xx * xx + yy * yy <= size * size + size
            if shape in ("diamond", "diamond ring"):
                return np.abs(xx) + np.abs(yy) <= size
            if shape == "fish":
                # A body twice as long as it is deep, with a forked tail to the right.
                body = ((xx + size * 0.25) / (size * 0.75)) ** 2 + (yy / max(1.0, size * 0.55)) ** 2 <= 1.0
                tail = (xx >= size * 0.5) & (xx <= size) & (np.abs(yy) <= (xx - size * 0.5) * 1.4 + 0.5)
                fork = (xx > size * 0.8) & (np.abs(yy) < (xx - size * 0.8) * 1.5)
                return body | (tail & ~fork)
            if shape == "triangle":
                return (yy <= size) & (yy >= -size) & (np.abs(xx) * 2 <= yy + size)
            raise ValueError(shape)

        edge, body = mask_for(r + 1), mask_for(r)
        if shape == "diamond ring":
            body = body & (np.abs(xx) + np.abs(yy) >= r - 1)
        for mask, color in ((edge, (28, 34, 38)), (body, rgb)):
            ys, xs = np.nonzero(mask)
            px, py = xs - rr + cx, ys - rr + cy
            keep = (px >= 0) & (px < w) & (py >= 0) & (py < h)
            frame[py[keep], px[keep]] = np.array(color, np.uint8)

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
        h, w = frame.shape[:2]
        unit = h / 720
        margin = max(12, int(26 * unit))
        # Leave the tallest right-hand HUD panel unobscured (sail/wind, Bot,
        # or scanner status can extend it beyond the location label).
        y = margin + int(140 * unit) + 18
        for raw_text, _ttl in state.toasts[-3:]:
            text = _toast_for_device(raw_text, input_device)
            if raw_text == "Shall we add that?":
                text += " Hold Y to read." if input_device == "gamepad" else " J reads the page."
            text = self._trim(text, size, w - 48)
            tw = self._measure(text, size, "mono") + 16
            x = (w - tw) // 2
            # A toast never covers the HUD's clock or boat panels: it drops below them (V1-43).
            for rx, ry, rw, rh in getattr(self, "_hud_rects", ()):
                if x < rx + rw and rx < x + tw and y < ry + rh and ry < y + ch + 8:
                    y = ry + rh + 8
            self._panel(frame, x, y, tw, ch + 8, 0.72)
            self._text(frame, text, x + 8, y + 3, size, INK, False, "sans")
            y += ch + 12

    # --- menus -----------------------------------------------------------

    def _title(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        # A translucent gradient preserves the lake while giving the title air.
        terms = self._title_alpha_cache.get((w, h))
        if terms is None:
            yy = np.arange(h,dtype=np.float32)[:,None,None]/h
            xx = np.arange(w,dtype=np.float32)[None,:,None]/w
            # Keep the original AA backing: both the left title column and horizon must meet contrast.
            alpha = np.minimum(np.clip((yy-0.22)*1.0,0,0.50)
                               + np.clip((0.62-xx)*1.4,0,0.62),0.84)
            weight = (alpha*256+0.5).astype(np.uint16)
            terms = (256-weight, weight*np.array([10,25,27],np.uint16)+128)
            size = terms[0].nbytes+terms[1].nbytes
            if size <= self._title_alpha_cache_limit:
                self._title_alpha_cache.clear()
                self._title_alpha_cache[(w, h)] = terms
                self._title_alpha_cache_bytes = size
        keep, tint = terms
        work = frame.astype(np.uint16)
        work *= keep
        work += tint
        work >>= 8
        frame[:] = work
        title = max(38,min(96,int(h*0.117)))
        body = max(15,int(h/38))
        small = max(11,int(h/60))
        title_h, body_h, small_h = (self._actual_size(value)
                                    for value in (title, body, small))
        gap_scale = getattr(self, "_text_scale", 1.0)
        x,y = int(w*0.075),int(h*(0.12 if h<480 else 0.43))
        self._text(frame,"A   T R O T L I N E   L A K E",x,y,small,GOLD,False,"sans")
        self._text(frame,GAME_TITLE,x,y+small_h+10*gap_scale,title,INK,True,"serif")
        self._text(frame,"Set your lines. Stay a while.",x,y+title_h+small_h+20*gap_scale,body,DIM,False,"sans")
        options = title_options(ui.has_save)
        ui.title_i %= len(options)
        y2 = y+title_h+small_h+body_h+(20 if h<480 else 48)*gap_scale
        if ui.confirm_new:
            msg = "New morning? The save on disk stays until you overwrite it."
            self._backed(frame, self._trim(msg, small, w - x * 2), x, y2, small, WARN)
            button_y = y2 + small_h + 12 * gap_scale
            button_h = body_h + 18 * gap_scale
            button_w = min(240, (w - x * 2 - 12) // 2)
            self._pointer_button(frame, ui, "Yes · Choose a mode", (x, button_y, button_w, button_h),
                                 "activate", selected=True, size=body)
            self._pointer_button(frame, ui, "Cancel", (x + button_w + 12, button_y, button_w, button_h),
                                 "back", size=body)
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
            ui.pointer.add((int(x), int(oy - 4 * gap_scale), int(button_w),
                            int(body_h + 24 * gap_scale)), "activate", "title_i", i)
        guide_w = self._measure("Field guide", small, "sans") + 24
        guide_y = h - small_h - 28 * gap_scale
        self._pointer_button(frame, ui, "Field guide", (x, guide_y, guide_w, small_h + 12), "help")
        controls = self._controls(ui, "H Help · W / S Choose · Enter selects",
                                  "D-pad / stick choose · A select")
        self._text(frame, self._trim(controls, small, w - 2 * x - guide_w - 16, "sans"),
                   x + guide_w + 16, guide_y + 4, small, DIM, False, "sans")
        if w >= 960:
            mark = "ONE LAKE. NO HURRY."
            self._backed(frame,mark,w-x-self._measure(mark,small,"sans"),guide_y-20,small,DIM,"sans")

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
            body = ("Cozy: half fuel burn, half gust drift with sail down, free tow, no needs penalties. Naps optional.\n"
                    "Old Salt: 2/3 base fuel burn; Drowsy at 16h, safe nap at 20h, Peckish at 24h. Tow: $25 + 2% boat price, cash-capped.\n"
                    "Change mode in Settings.")
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
        head, size = self._size(frame, "head"), self._size(frame, "body")
        while head > 10 and self._measure(title, head) > width - 32:
            head -= 1
        title_h = self._render(title, head, INK, "sans").shape[0]
        hint = self._controls(ui, "Arrows choose · Enter selects · Esc back",
                               "D-pad chooses · A selects · B back") if labels else "Any key or click finishes the fade."
        if labels and ui.mode == "needs":
            hint = self._controls(ui, "Arrows choose · Enter selects · F / Esc later",
                                   "D-pad chooses · A selects · X / B later")
        values = body + "\n" + hint
        available = buttons[0][1] - 12 - (y + 30 + title_h)
        while size > 10:
            lines, line_height = self._comfort_lines(values, size, width - 32)
            if len(lines) * line_height <= available:
                break
            size -= 1
        lines, line_height = self._comfort_lines(values, size, width - 32)
        if labels:
            # A sheet just tall enough for its words, resting on the fixed
            # buttons, so the lake stays in view above a question.
            spare = available - len(lines) * line_height
            if spare > 0:
                y, height = y + spare, height - spare
            self._fill(frame, 0, 0, w, h, (6, 14, 16), 0.30)
            self._panel(frame, x, y, width, height, 0.95)
        else:
            self._fill(frame, x + 10, y, width - 20, 1, GOLD, .34)
        self._text(frame, title, x + 16, y + 16, head, INK, False, "sans")
        top = y + 30 + title_h
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
                field = "new_mode_i" if ui.mode == "new_mode" else "comfort_i"
                ui.pointer.add(rect, "activate", field, index)
            if ui.mode == "new_mode":
                # Pace select is the only comfort sheet with no way back but Esc; give the
                # pointer the same exit the keys have.
                font = self._size(frame, "small")
                bw = self._measure("Back", font) + 16
                bh = min(30, max(22, font + 8))
                bx, by = x + width - bw - 12, y + 10
                self._round_fill(frame, bx, by, bw, bh, (46, 66, 62), 1)
                glyph = self._render("Back", font, INK, "sans").shape[0]
                self._center(frame, "Back", bx + bw / 2, by + (bh - glyph) / 2, font, INK)
                ui.pointer.add((bx, by, bw, bh), "back")
        else:
            ui.pointer.add((0, 0, w, h), "activate")

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
        width = self._measure(label, size) + 24
        # Sit below the HUD panels in this column: the quest tracker makes the clock
        # panel taller than its old fixed int(92*unit)+10, and a fixed offset covered it.
        y = margin
        for rx, ry, rw, rh in getattr(self, "_hud_rects", ()):
            if rx < margin + width and margin < rx + rw:
                y = max(y, ry + rh + 8)
        self._panel(frame, margin, y, width, self._render(label, size, GOLD, "sans").shape[0] + 16, .8)
        self._text(frame, label, margin + 12, y + 6, size, GOLD, False, "sans")

    def _shop_tabs(self, frame, ui, x, y, width, size):
        """Draw the same measured tab strip for stock, Kitchen and Bot shops."""
        font = size
        indexes = list(range(len(_TABS)))
        while font > 10 and sum(self._measure(f"[{name}]", font, "mono") + 8
                                for name in _TABS) > width:
            font -= 1
        if sum(self._measure(f"[{name}]", font, "mono") + 8 for name in _TABS) > width:
            indexes = [(ui.shop_tab + delta) % len(_TABS) for delta in (-1, 0, 1)]
        tx = x
        for index in indexes:
            name = _TABS[index]
            label = f"[{name}]" if index == ui.shop_tab else f" {name} "
            color = GOLD if index == ui.shop_tab else DIM
            tw = self._text(frame, label, tx, y, font, color, False)
            ui.pointer.add((tx - 2, y - 2, tw + 4, self.cell(font)[1] + 4), "tab", value=index)
            tx += tw + 8
        return y + self.cell(font)[1] + 10

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
        list_top = self._shop_tabs(frame, ui, x + m, tab_y, pw - m * 2, body)
        list_h = ph - (list_top - y) - ch * 3
        visible = max(1, list_h // (ch + 2))
        start, end = ui.pointer.window("shop", ui.shop_i, len(rows), visible)
        for i in range(start, end):
            n = i - start
            row = rows[i]
            ry = list_top + n * (ch + 2)
            if i == ui.shop_i:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            color = INK if row.enabled else DIM
            if i == ui.shop_i:
                color = GOLD
            # A label may run up to its own right-hand column, not a fixed share of the panel.
            rw = len(row.right) * self.cell(body)[0]
            label = self._trim(row.label, body, pw - m * 2 - rw - self.cell(body)[0])
            self._text(frame, label, x + m, ry, body, color, shadow=False)
            self._text(frame, row.right, x + pw - m - rw, ry, body, color, shadow=False)
            ui.pointer.add((x + 8, ry - 1, pw - 16, ch + 2), "activate", "shop_i", i)
        blurb = rows[ui.shop_i].blurb if rows else ""
        if ui.note:
            blurb = ui.note
        # Blurbs and notes are sentences: proportional type fits far more of them.
        self._text(frame, self._trim(blurb, small, pw - m * 2, "sans"), x + m, y + ph - ch - 28,
                   small, WARN if ui.note else DIM, False, "sans")
        foot = self._controls(ui, "W/S choose  A/D tabs  Arrows too  Enter buys  Esc",
                              "D-pad / stick choose  D-pad tabs  A buys  B back")
        foot_y = y + ph - self.cell(small)[1] - 12
        self._text(frame, self._trim(foot, small, pw - m * 2 - 90, "sans"), x + m,
                   foot_y, small, DIM, False, "sans")
        self._pointer_button(frame, ui, "Back", (x + pw - m - 76, foot_y - 3, 76,
                                                self.cell(small)[1] + 8))

    def _setbait(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        head, body, small = (self._size(frame, key) for key in ("head", "body", "small"))
        head_h, ch, small_h = self.cell(head)[1], self.cell(body)[1], self.cell(small)[1]
        m = 16
        pw = min(w - 24, max(int(w * 0.64), 560))
        control_h = max(22, small_h + 8)
        foot_h = max(26, control_h)
        minimum = 32 + head_h + control_h * 2 + ch + 4 + small_h + 10 + foot_h
        ph = min(h - 24, max(int(h * 0.72), minimum))
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        self._text(frame, "SET A LINE", x + m, y + 12, head, INK)
        footer_y = y + ph - foot_h - 10
        if not state.held:
            self._text(frame, "No line aboard.", x + m, y + 20 + head_h, body, WARN)
            self._pointer_button(frame, ui, "Back", (x + pw - m - 76, footer_y, 76, foot_h))
            return
        ui.set_line %= len(state.held)
        ui.set_bait %= len(BAITS)
        ui.set_sections = max(1, min(3, int(ui.set_sections)))
        ui.set_section %= ui.set_sections
        section_baits = [index % len(BAITS) for index in ui.set_section_baits]
        if ui.set_section_baits == (0, 0, 0) and ui.set_bait:
            section_baits = [ui.set_bait] * 3
        ui.set_bait = section_baits[ui.set_section]
        spec = LINE_TIERS[state.held[ui.set_line].tier]
        control_y = y + 20 + head_h
        line_w = (pw - m * 2) // 2
        self._pointer_button(frame, ui, "‹", (x + m, control_y, control_h, control_h),
                             "set_line", value=(ui.set_line - 1) % len(state.held))
        self._pointer_button(frame, ui, "›", (x + m + line_w - control_h, control_y, control_h, control_h),
                             "set_line", value=(ui.set_line + 1) % len(state.held))
        which = f"Line {ui.set_line + 1}/{len(state.held)} · {spec['hooks']} hooks"
        self._text(frame, self._trim(which, small, line_w - 2 * control_h - 12, "sans"),
                   x + m + control_h + 6, control_y + 3, small, GOLD, False, "sans")
        count_x = x + m + line_w + 10
        count_right = x + pw - m
        label_w = max(0, count_right - count_x - control_h * 3 - 8)
        self._text(frame, self._trim("Sections", small, label_w, "sans"),
                   count_x, control_y + 3, small, DIM, False, "sans")
        for count in range(1, 4):
            bx = count_right - (4 - count) * control_h
            self._pointer_button(frame, ui, str(count), (bx, control_y, control_h - 2, control_h),
                                 "set_sections", value=count, selected=count == ui.set_sections)
        section_y = control_y + control_h + 6
        section_w = (pw - m * 2 - (ui.set_sections - 1) * 6) // ui.set_sections
        for index in range(ui.set_sections):
            label = f"S{index + 1} · {BAITS[section_baits[index]].name}"
            self._pointer_button(frame, ui, label,
                                 (x + m + index * (section_w + 6), section_y, section_w, control_h),
                                 "set_section", value=index, selected=index == ui.set_section)
        top = section_y + control_h + 8
        note_y = footer_y - small_h - 6
        visible = max(1, (note_y - top - 4) // (ch + 4))
        start, end = ui.pointer.window("bait", ui.set_bait, len(BAITS), visible)
        need = sum(1 for hook_index in range(spec["hooks"])
                   if hook_index * ui.set_sections // spec["hooks"] == ui.set_section)
        for index in range(start, end):
            bait = BAITS[index]
            have = state.bait.get(bait.id, 0)
            label, right = f"{index + 1}  {bait.name}", f"{have} aboard"
            selected = index == section_baits[ui.set_section]
            color = WARN if selected and have < need else GOLD if selected else INK
            ry = top + (index - start) * (ch + 4)
            if selected:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            rw = self._measure(right, body, "mono")
            self._text(frame, self._trim(label, body, pw - m * 2 - rw - 16),
                       x + m, ry, body, color, shadow=False)
            self._text(frame, right, x + pw - m - rw, ry, body, color, shadow=False)
            ui.pointer.add((x + 8, ry - 1, pw - 16, ch + 3), "focus", "set_bait", index)
        bait = BAITS[section_baits[ui.set_section]]
        note = ui.note or f"Section {ui.set_section + 1} needs {need}. {bait.blurb}"
        self._text(frame, self._trim(note, small, pw - m * 2, "sans"), x + m, note_y,
                   small, WARN if ui.note else DIM, False, "sans")
        foot = self._controls(ui, "W/S bait · A/D line · Q sections · Tab section · Enter sets",
                              "D-pad bait · LB sections · Back section · A sets · B back")
        self._text(frame, self._trim(foot, small, pw - m * 2 - 164, "sans"),
                   x + m, footer_y + 4, small, DIM, False, "sans")
        self._pointer_button(frame, ui, "Set", (x + pw - m - 156, footer_y, 74, foot_h), "set")
        self._pointer_button(frame, ui, "Back", (x + pw - m - 74, footer_y, 74, foot_h))

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
            self._pointer_button(frame, ui, "Back", (x + pw - m - 76, y + ph - 38, 76, 28))
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
        visible = max(1, (ph - (list_top - y) - 44) // (ch + 1))
        start, end = ui.pointer.window("check", ui.check_i, len(rows), visible)
        for i in range(start, end):
            n = i - start
            row = rows[i]
            ry = list_top + n * (ch + 1)
            if i == ui.check_i:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            color = GOLD if i == ui.check_i else (INK if row.enabled or row.kind != "hook" else DIM)
            if row.kind == "hook" and not row.enabled and i != ui.check_i:
                color = DIM
            rw = len(row.right) * self.cell(body)[0]
            label = self._trim(row.label, body, pw - m * 2 - rw - self.cell(body)[0])
            self._text(frame, label, x + m, ry, body, color, shadow=False)
            if row.right:
                self._text(frame, row.right, x + pw - m - rw, ry, body, color, shadow=False)
            ui.pointer.add((x + 8, ry - 1, pw - 16, ch + 1), "activate", "check_i", i)
        foot = ui.note or self._controls(
            ui, "W/S choose  Enter toggles  Resolve applies  Esc back",
            "D-pad choose  A toggles / applies  B back",
        )
        foot_y = y + ph - self.cell(small)[1] - 12
        self._text(frame, self._trim(foot, small, pw - m * 2 - 90, "sans"), x + m,
                   foot_y, small, WARN if ui.note else DIM, False, "sans")
        self._pointer_button(frame, ui, "Back", (x + pw - m - 76, foot_y - 3, 76,
                                                self.cell(small)[1] + 8))

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
        visible = max(1, (ph - (top - y) - 44) // (ch + 2))
        if not rows:
            self._text(frame, "Empty. The lines keep what they catch.", x + m, top, body, DIM)
        else:
            start, end = ui.pointer.window("well", ui.well_i, len(rows), visible)
            for i in range(start, end):
                n = i - start
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
                if i == ui.well_i:
                    # Focus shows as a band as well as colour, like every other list (V1-43).
                    self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
                self._text(frame, self._trim(label, body, int(pw * 0.68)), x + m, ry, body, color, shadow=False)
                right = dollars(catch.value())
                self._text(frame, right, x + pw - m - len(right) * self.cell(body)[0], ry, body, color, shadow=False)
                ui.pointer.add((x + 8, ry - 1, pw - 16, ch + 2), "treasure", "well_i", i)
        foot = self._controls(ui, "W/S choose    T / Enter marks Treasured    I closes",
                              "D-pad choose    A marks Treasured    B closes")
        foot_y = y + ph - self.cell(small)[1] - 12
        controls_w = 194 if rows else 76
        self._text(frame, self._trim(foot, small, pw - m * 2 - controls_w - 12, "sans"),
                   x + m, foot_y, small, DIM, False, "sans")
        if rows:
            label = "Unmark" if rows[ui.well_i].treasured else "Treasure"
            self._pointer_button(frame, ui, label,
                                 (x + pw - m - 194, foot_y - 3, 110, self.cell(small)[1] + 8), "treasure")
        self._pointer_button(frame, ui, "Close", (x + pw - m - 76, foot_y - 3, 76,
                                                 self.cell(small)[1] + 8))

    def _pause(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        self._fill(frame, 0, 0, w, h, (6, 8, 8), 0.35)
        labels = pause_options(state)
        body, head, small = (self._size(frame, key) for key in ("body", "head", "small"))
        head_h, body_h, small_h = self.cell(head)[1], self.cell(body)[1], self.cell(small)[1]
        foot = ui.note or self._controls(ui, "Arrows · Enter · Z nap · K pantry",
                                         "D-pad · A · X nap · Y pantry")
        widest = max([self._measure("> " + label, body, "mono") for label in labels]
                     + [self._measure(foot, small, "mono")])
        pw = min(w - 24, max(420, int(w * 0.34), widest + 36))
        row_h, button_h = body_h + 8, max(26, small_h + 10)
        fixed = 36 + head_h + button_h + small_h + 24
        visible = max(1, min(len(labels), (h - 24 - fixed) // row_h))
        ph = fixed + visible * row_h
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.92)
        self._text(frame, "PAUSED", x + 18, y + 14, head, INK)
        ui.pause_i %= len(labels)
        start, end = ui.pointer.window("pause", ui.pause_i, len(labels), visible)
        list_top = y + 24 + head_h
        for index in range(start, end):
            ry = list_top + (index - start) * row_h
            color = GOLD if index == ui.pause_i else INK
            prefix = "> " if index == ui.pause_i else "  "
            self._text(frame, prefix + labels[index], x + 18, ry, body, color)
            ui.pointer.add((x + 10, ry - 2, pw - 20, row_h), "activate", "pause_i", index)
        shortcut_y = list_top + visible * row_h + 4
        button_w = (pw - 44) // 2
        self._pointer_button(frame, ui, "Kitchen", (x + 18, shortcut_y, button_w, button_h), "kitchen")
        self._pointer_button(frame, ui, "Catnap", (x + 26 + button_w, shortcut_y, button_w, button_h), "catnap")
        self._text(frame, self._trim(foot, small, pw - 36, "sans"), x + 18,
                   y + ph - small_h - 12, small, WARN if ui.note else DIM, False, "sans")

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
            ("Camera view", "Third person" if settings.get("third_person") is True
             else "First person"),
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
        button_h = max(24, small_h + 8)
        foot_h = len(foot_lines) * (small_h + 2) + button_h + 8
        row_h = body_h + max(4, int(h * 0.008))
        rows_top_offset = m + head_h + 14
        available = h - 24 - (2 * m + rows_top_offset + foot_h + 12)
        visible = max(1, min(len(rows), available // max(1, row_h)))
        start, end = ui.pointer.window("settings", ui.settings_i, len(rows), visible)
        ph = 2 * m + head_h + 14 + visible * row_h + foot_h + 12
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        self._text(frame, "SETTINGS & ACCESSIBILITY", x + m, y + m, head, INK)
        list_top = y + rows_top_offset
        control_w = max(18, row_h - 2)
        controls_x = x + pw - m - control_w * 2 - 6
        left_width = int((pw - 2 * m - control_w * 2 - 18) * 0.60)
        for offset, (label, value) in enumerate(rows[start:end]):
            index = start + offset
            ry = list_top + offset * row_h
            if index == ui.settings_i:
                self._fill(frame, x + m - 4, ry - 1, pw - 2 * m + 8, row_h, (46, 42, 28), 0.86)
            color = GOLD if index == ui.settings_i else INK
            prefix = "> " if index == ui.settings_i else "  "
            self._text(frame, prefix + self._trim(label, body, left_width - 10), x + m, ry, body, color, shadow=False)
            value_right = x + pw - m if index == SETTINGS_KEYBOARD_CONTROLS_ROW else controls_x - 8
            value = self._trim(value, body, value_right - (x + m + left_width) - 4)
            self._text(frame, value, value_right - self._measure(value, body, "mono"), ry, body, color, shadow=False)
            ui.pointer.add((x + m - 4, ry - 1, pw - 2 * m + 8, row_h), "activate", "settings_i", index)
            if index != SETTINGS_KEYBOARD_CONTROLS_ROW:
                self._pointer_button(frame, ui, "-", (controls_x, ry, control_w, row_h - 2),
                                     "adjust_minus", "settings_i", index)
                self._pointer_button(frame, ui, "+", (controls_x + control_w + 6, ry, control_w, row_h - 2),
                                     "adjust_plus", "settings_i", index)
        foot_y = y + ph - m - foot_h
        for line in foot_lines:
            self._text(frame, line, x + m, foot_y, small, DIM, shadow=False)
            foot_y += small_h + 2
        self._pointer_button(frame, ui, "Back", (x + pw - m - 86, y + ph - m - button_h, 86, button_h))

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
        button_h = max(24, small_h + 8)
        foot_h = len(foot_lines) * (small_h + 2) + button_h + 8
        row_h = body_h + max(4, int(h * 0.008))
        rows_top_offset = m + head_h + 14
        available = h - 24 - (2 * m + rows_top_offset + foot_h + 12)
        visible = max(1, min(len(rows), available // max(1, row_h)))
        start, end = ui.pointer.window("keys", ui.key_binding_i, len(rows), visible)
        ph = 2 * m + head_h + 14 + visible * row_h + foot_h + 12
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        self._text(frame, "KEYBOARD CONTROLS", x + m, y + m, head, INK)
        list_top = y + rows_top_offset
        value_width = int((pw - 2 * m) * 0.24)
        for offset, (action, label) in enumerate(rows[start:end]):
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
            self._text(frame, value, x + pw - m - self._measure(value, body, "mono"), ry, body, color, shadow=False)
            if not ui.capturing_key:
                ui.pointer.add((x + m - 4, ry - 1, pw - 2 * m + 8, row_h),
                               "activate", "key_binding_i", index)
        foot_y = y + ph - m - foot_h
        for line in foot_lines:
            self._text(frame, line, x + m, foot_y, small, DIM, shadow=False)
            foot_y += small_h + 2
        self._pointer_button(frame, ui, "Cancel key" if ui.capturing_key else "Back",
                             (x + pw - m - 96, y + ph - m - button_h, 96, button_h))

    def _skipper(self, frame, state, ui: UIState):
        """The Skipper creator (skipperlook): settings-style rows on the left, the card on the right.

        A full-screen mode, so the play HUD stays off and the world is frozen behind it. The card is
        skipperview.preview, a pure function of the UI clock, the turn and reduced motion, so the same
        state always draws the same frame. Publishes native row focus and draft controls; activation lives in Session.
        """
        from . import skipperview
        h, w = frame.shape[:2]
        self._fill(frame, 0, 0, w, h, (6, 8, 8), 0.35)
        look = ui.skipper_look or skipperlook.normalize({})
        rows = skipperlook.ROWS
        ui.skipper_i = _clamp(ui.skipper_i, len(rows))
        head, body, small = (self._size(frame, key) for key in ("head", "body", "small"))
        head_h, body_h, small_h = self.cell(head)[1], self.cell(body)[1], self.cell(small)[1]
        m = max(14, min(24, int(w * 0.025)))
        pw = min(w - 20, max(int(w * 0.74), 760))
        foot_lines = _phrase_lines(self._skipper_foot(ui), max(12, (pw - 2 * m) // self.cell(small)[0]))
        button_h = max(24, small_h + 8)
        foot_h = len(foot_lines) * (small_h + 2) + button_h + 8
        row_h = body_h + max(4, int(h * 0.008))
        rows_top_offset = m + head_h + 14
        available = h - 24 - (2 * m + rows_top_offset + foot_h + 12)
        visible = max(1, min(len(rows), available // max(1, row_h)))
        start, end = ui.pointer.window("skipper", ui.skipper_i, len(rows), visible)
        ph = 2 * m + head_h + 14 + visible * row_h + foot_h + 12
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        self._text(frame, "YOUR SKIPPER", x + m, y + m, head, INK)
        list_top = y + rows_top_offset
        # The rows keep the left 60% of the panel; the card takes the rest, beside them.
        left = int((pw - 2 * m) * 0.6)
        control_w = max(18, row_h - 2)
        content_w = max(40, left - control_w * 2 - 14)
        value_w = int(content_w * 0.45)
        for offset, (key, label) in enumerate(rows[start:end]):
            index = start + offset
            ry = list_top + offset * row_h
            selected = index == ui.skipper_i
            if selected:
                self._fill(frame, x + m - 4, ry - 1, left + 8, row_h, (46, 42, 28), 0.86)
            # A dimmed row changes nothing the cat wears right now (skipperlook.row_enabled).
            color = GOLD if selected else (INK if skipperlook.row_enabled(look, key) else DIM)
            value = skipperlook.value_label(look, key)
            if key == "name" and ui.skipper_typing:
                value, color = look["name"] + "_", GOLD
            prefix = "> " if selected else "  "
            self._text(frame, prefix + self._trim(label, body, content_w - value_w - 12), x + m, ry, body, color,
                       shadow=False)
            if value:
                value = self._trim(value, body, value_w)
                width = self._measure(value, body, "mono")
                value_x = x + m + content_w - width
                if key == "name" and ui.skipper_typing and ui.skipper_fresh:
                    # Selected on entry: the first key typed replaces the name (game._skipper_type). A box in
                    # the row-highlight colour would vanish on the selected row, so the box is gold with the
                    # dark row tone as ink. It stays inside the row's right edge.
                    self._fill(frame, value_x - 4, ry - 1, width + 8, body_h + 2, GOLD, 1.0)
                    color = (46, 42, 28)
                self._text(frame, value, value_x, ry, body, color, shadow=False)
            action = "creator_done" if key == "done" else "activate"
            if not skipperlook.row_enabled(look, key) or (key == "name" and ui.skipper_typing):
                action = "focus"
            ui.pointer.add((x + m - 4, ry - 1, left + 8, row_h), action, "skipper_i", index)
            if key != "done" and skipperlook.row_enabled(look, key) and not ui.skipper_typing:
                controls_x = x + m + left - control_w * 2 - 6
                self._pointer_button(frame, ui, "-", (controls_x, ry, control_w, row_h - 2),
                                     "adjust_minus", "skipper_i", index)
                self._pointer_button(frame, ui, "+", (controls_x + control_w + 6, ry, control_w, row_h - 2),
                                     "adjust_plus", "skipper_i", index)
        col_x = x + m + left + m
        col_w = x + pw - m - col_x
        block = visible * row_h
        # A square card as tall as the rows, never wider than its column (240-360 px at normal sizes).
        side = max(8, min(360, col_w, block))
        settings = state.v2.get("settings", {}) if isinstance(getattr(state, "v2", None), dict) else {}
        card = skipperview.preview(look, ui.skipper_clock, ui.skipper_turn, side,
                                   bool(settings.get("reduced_motion", False)),
                                   ui.skipper_clock - ui.skipper_changed_at)
        self._blit_rgb(frame, card, col_x + (col_w - side) // 2, list_top + (block - side) // 2)
        foot_y = y + ph - m - foot_h
        for line in foot_lines:
            self._text(frame, line, x + m, foot_y, small, DIM, shadow=False)
            foot_y += small_h + 2
        controls_y = y + ph - m - button_h
        self._pointer_button(frame, ui, "Done", (x + pw - m - 182, controls_y, 86, button_h), "creator_done")
        self._pointer_button(frame, ui, "Cancel", (x + pw - m - 86, controls_y, 86, button_h), "creator_cancel")

    def _skipper_foot(self, ui: UIState) -> str:
        """The creator's control hints for the device, the typing state and where Done returns."""
        if ui.skipper_typing:
            return self._controls(ui, "Type a name  ·  Backspace deletes  ·  Enter or Esc sets it",
                                  "D-pad changes the name  ·  A or B sets it")
        back = ("Esc back", "B back") if ui.skipper_origin == "new" else ("Esc cancels", "B cancels")
        return self._controls(
            ui, f"W/S choose  ·  A/D change  ·  Enter picks  ·  Q/E turn  ·  Done saves  ·  {back[0]}",
            f"D-pad choose  ·  D-pad change  ·  A picks  ·  LB/RB turn  ·  Done saves  ·  {back[1]}")

    @staticmethod
    def _shown_caption(state, ui: UIState) -> str:
        """The sound caption to show this frame: `ui.caption`, or "" while none is timed to
        show or the player has turned captions off in `state`'s settings (state may be None)."""
        v2 = getattr(state, "v2", {})
        settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
        if not settings.get("captions", True) or ui.caption_timer <= 0:
            return ""
        return ui.caption

    def _caption(self, frame, state, ui: UIState):
        # The Field Guide covers the window, so `_help` draws the caption on its cover instead.
        if ui.mode == "help" or not self._shown_caption(state, ui):
            return
        h, w = frame.shape[:2]
        if ui.mode in {"kitchen", "cook_confirm", "cooking"} or (ui.mode == "shop" and ui.shop_tab in (6, 7)):
            size = self._size(frame, "small")
            while size > 9 and self._render(ui.caption, size, INK, "sans").shape[0] > 18:
                size -= 1
            label = self._trim(ui.caption, size, w - 48, "sans")
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
        # Over the HUD the caption sits above the control-hint bar, not on it.
        floor = getattr(self, "_caption_floor", None)
        x = (w - pw) // 2
        y = max(4, h - ph - 18) if floor is None else max(4, floor - ph - 8)
        self._panel(frame, x, y, pw, ph, 0.94)
        self._center(frame, self._trim(ui.caption, size, pw - 24, "sans"), w / 2,
                     y + 8, size, INK, family="sans")

    def _help(self, frame, ui: UIState, state=None):
        """Draw the Field Guide, the help notebook, open at the reader's spread (#139).

        `state` supplies the saved key bindings for the keyboard tables and the captions
        setting. `fieldguide` lays out the pages and draws them, a sound's caption in the
        controls hint's place below them, and records the spread count in `ui`."""
        hint = self._controls(ui, "Esc closes · WASD / arrows or wheel turn · Click page corners",
                              "B closes · D-pad / stick turn pages")
        fieldguide.draw(self, frame, ui, help_topics(state, ui.input_device),
                        FIELD_GUIDE_TITLE, hint, self._shown_caption(state, ui))


_HELP = (
    ("ON THE WATER", (
        "W/S row, or run the motor when one is installed",
        "Power stays set       Shift returns it to idle",
        "A D or arrows steer   arrows look up and down",
        "Space drops or raises the anchor",
        "W / S also pull the anchor when you mean to go",
        "",
        "F sets a trotline     E checks a line or the landing",
        "Tab chart    J journal    I livewell",
        "C hails a paw-wave NPC: within 20 m, below 3 knots",
        "T changes time: 1x 3x 6x 12x, while you are still",
        "B sends Bot ahead, or out to a line.  B calls him back.",
        "H help    M mute    Esc pause",
        "",
        "One real second is one minute on the lake at 1x.",
        "A day on the water is 24 minutes.",
    )),
    ("TROT LINES", (
        "There is no rod and reel. The lines do the fishing.",
        "Idle the boat, point at open water, and set.",
        "Each hook takes one bait. A line can mix up to three.",
        "Corks mark the hooks. A flag means a fish is on.",
        "Tired fish go red on the chart, about four hours left.",
        "The landing and water around it are a no-line zone.",
        "",
        "Anchor and let time run. Come back and check.",
        "Take fish into the livewell, rebait, or pull the line.",
        "A fish left on the hook gets away after 13 hours.",
        "Run a line over and you may knock one off.",
        "",
        "While the game is closed the lines keep soaking,",
        "for up to 72 real hours in Cozy or 36 in Old Salt.",
        "Hooked fish still get away after 13 game hours.",
    )),
    ("THE LANDING", (
        "Nose into the slip and press E.",
        "Sell the well. Buy bait by the dozen.",
        "Motors, a deeper well, a bait box,",
        "a depth finder and a bow light are at that counter.",
        "Rowboats use oars; the electric motor is optional.",
        "",
        "Hull, deck, buoy, and tiller colors are yours once you",
        "buy them. Wearing one you own is free.",
        "",
        "Your active boat sets the deployed-line limit.",
        "Lines out stay out if you switch to a smaller boat.",
        "Bait comes from buying, recipes, or quest gifts.",
        "Liver, cut shad, and the deep hole are where the",
        "heavy fish live, and they fill a small livewell fast.",
    )),
    ("BOATS AND OTHER WATERS", (
        "At the landing: A/D tabs, W/S rows, Enter selects.",
        "Boats tab: 24 boats in 8 tiers.",
        "Jon, rowboat, daysailer and pontoon start unlocked.",
        "New boats: tiers 1–2 at start, tiers 3–4 after chapter 2,",
        "tiers 5–6 after chapter 3, tier 7 after chapter 4,",
        "and tier 8 after chapter 5.",
        "Tier 8 boats sell only at Cosmic Drift Station",
        "in the Nebula. Buy and switch only at a landing.",
        "Owned boats switch freely at any landing.",
        "The pontoon adds 40 lb of livewell space.",
        "",
        "Q raises or lowers the daysailer's sail.",
        "A/D steers. Sail across the wind; tack to go upwind.",
        "W/S controls its small auxiliary. Shift idles it.",
        "Wind power burns no fuel. Lower the sail to stop.",
        "Space anchors and lowers the sail.",
        "",
        "Buy fuel in the Boats tab. Each boat keeps its tank.",
        "Idle, then R calls a tow if you get stranded.",
        "Lakes: pick up your lines, then travel from a landing.",
        "Money, catches, gear, boats, and journal come with you.",
    )),
    ("BAIT SECTIONS", (
        "A line has one to three bait sections.",
        "Hooks are shared out evenly, in order, across them.",
        "Each hook takes the bait of its own section.",
        "",
        "Q or G sets how many sections, 1 to 3.",
        "Tab picks which section you edit.",
        "Up and down pick the bait for that section.",
    )),
    ("FIRST HOUR", (
        "A day starts at 6 AM and lasts 24 minutes.",
        "W and S throttle up and down. A and D steer.",
        "Idle with Shift. Press F to set a trotline.",
        "The 1 to 5 keys pick bait. Enter sets the line.",
        "Anchor with Space and press T to let time run.",
        "E checks a line once its cork flag is up.",
        "Keep the fish, rebait, or pull the line.",
        "Head for the landing and press E to open the shop.",
        "Sell the well in the Sell tab. Bait is in the Bait tab.",
        "Bot rides the bow. B sends him out to a line and back.",
        "The journal's Story tab shows your next step.",
        "H opens these pages on the water. Pause has Help too.",
    )),
    ("LAKES AND TRAVEL", (
        "Five waters. Briar and Cedar Creek are open now.",
        "Flathead opens after chapter 2, Crater after 3,",
        "and the Starlight Nebula Lagoon after chapter 4.",
        "",
        "At a landing, press E and pick the Lakes tab.",
        "A/D changes tabs, W/S picks a lake, Enter travels.",
        "Pick up your lines first. Money, catches, gear,",
        "boats and the journal all come with you.",
        "",
        "Flathead has snow mist, Crater caldera fog",
        "and Nebula aurora. Reeds need the Reed Anchor.",
        "Nebula currents drift lines unless you own",
        "the Zero-G Winch.",
    )),
    ("THE BOOK", (
        "J opens the book. A/D changes tabs, W/S chooses.",
        "Enter opens a fish or turns a page. J closes it.",
        "Tabs: Fish, Book, Ripples & Keepsakes, Story,",
        "Watch and Week.",
        "Stages: Rumor, Identified (1 catch), Bait known (3),",
        "Verified (5), Mastered (10). Each one toasts.",
        "What we heard stays put. What we found grows.",
        "The title changes: Fishypedia, The Book of Five Waters,",
        "then Pescapedia when all 144 are verified.",
        "Mouse: click tabs, species, controls and week rows.",
        "The wheel scrolls the book. Kitchen lists take clicks.",
        "Hover shares menu focus with keys and controllers.",
    )),
    ("THE CHART", (
        "On the chart: C hails, Space anchors, Q sails,",
        "R tows, B sends Bot. Tab or Esc closes the chart.",
        "",
        "Chart keys work only while the chart is open.",
        "Click the chart's action buttons, or Close.",
    )),
    ("SHINIES AND TROPHIES", (
        "About 1 in 64 standard catches is a shiny. It is",
        "rolled once, when caught. Shinies sell for 3x,",
        "and start Treasured, so bulk sale keeps them.",
        "Verified species can be tracked, one at a time.",
        "Track from the species entry: click it, or press F.",
        "Tracking guarantees a shiny by the 50th catch.",
        "The counter survives switching targets and reloads.",
        "In the livewell, Enter or T marks Treasured.",
        "Trophy shelf: F hangs a replica on a rail boat.",
        "Fish cards and the book show each weight;",
        "the book keeps your best.",
    )),
    ("CATS AND HAILING", (
        "Cats you can see sit on their own boats. The chart",
        "marks the cats who are here now.",
        "Hail with C within 20 m, under 3 knots.",
        "In a chat, W/S or the arrows pick a reply.",
        "Numbers 1 to 5 pick one too. Enter or C goes on.",
        "Esc closes a chat, unless a story scene is playing.",
        "Each cat starts as a Stranger, becomes",
        "an Acquaintance after their first quest, and a Friend",
        "after the second. Greetings change at each step.",
        "Friends write once their quests are all done.",
        "Postmaster Pounce: one letter a day, 8 AM to 4 PM.",
        "Tinker Thistle moors at your lake on Saturdays.",
    )),
    ("QUESTS AND STORY", (
        "Cats offer quests in dialogue. Declined offers stay.",
        "Accepted quests show in the book's Story tab.",
        "Turn a quest in to its giver, or the lake's host.",
        "Turn-ins never take your fish, gear or boats.",
        "The first quest of a cat gives a Ripple, a line",
        "they remember. The second gives a Keepsake.",
        "Ripples and Keepsakes are the book's third tab.",
        "The story is five chapters of three steps each.",
        "Finish a chapter to open the next lake's route.",
    )),
    ("THE WEEK AND COOKOUT", (
        "Weeks run Sun–Sat. Each day begins at 6 AM.",
        "The book's Week tab lists all seven days.",
        "Each lake has two Lake Days, with a bonus for",
        "certain fish, hours or weather.",
        "Forecasts survive reloads and lake travel.",
        "Bot points out nearby good water once a day.",
        "You can ask him from the Kitchen menu too.",
        "Sunday, 5 to 8 PM, the lake's cats gather.",
        "Share one ordinary fish at the Kitchen menu",
        "for a pantry gift, once per lake each Sunday.",
        "Missing a cookout costs nothing.",
    )),
    ("KITCHEN AND GALLEY", (
        "K opens the pantry from the water. Cooking needs",
        "a landing, or a galley boat at anchor.",
        "The Kitchen tab at a landing has the same menu.",
        "Each host sells one specialty; pantries hold 20.",
        "Kibble Tins are $3 everywhere: a snack, not a buff.",
        "Each dish needs one fish from a food group",
        "and one pantry item. The smallest fish is used.",
        "Shiny, Treasured, protected and legendary fish",
        "are never used. Each cooked dish gives its buff.",
        "Hosts teach dishes in their chapter. Cards cost $40",
        "after that chapter.",
        "Recipe bait takes two parent baits and an item.",
        "It makes twelve.",
    )),
    ("COZY AND OLD SALT", (
        "New Game asks for your pace. Settings change it.",
        "Cozy, the default, has no penalties at all.",
        "Old Salt has a light routine. Nothing is ever lost.",
        "Energy: 16 awake hours is Drowsy, and hauls",
        "are 25% slower. After 20 hours a safe catnap runs.",
        "Hunger: 24 hours without a meal is Peckish.",
        "Boats run 20% slower until you eat.",
        "Any dish or Kibble Tin counts as a meal.",
        "Prompts come at most once per 10 real minutes.",
        "Later snoozes a prompt for 30 minutes. F or Esc.",
        "Tow: free in Cozy. In Old Salt it is $25 plus 2%",
        "of the boat's price, or all your cash if less.",
        "Menus and pauses stop every need clock.",
    )),
    ("CATNAPS AND RESTED", (
        "Z takes a two-hour catnap. Hold Y on a pad.",
        "Anchor or dock first. Hammock boats also nap",
        "while idling with the sail down.",
        "Lines keep soaking, and naps count as game time.",
        "Any key or click ends the fade early.",
        "Pause, then Z or F, also naps.",
        "The first nap in a while grants Rested for six",
        "game hours. Rested can bring a dream: a habitat lead.",
        "Read it in the book, under What we heard.",
        "Only one ordinary dream waits at a time.",
        "Extra naps just pass time. Nothing is lost by it.",
    )),
    ("BOT AND HIS TOOLS", (
        "Bot is the tin deckhand. His name, Word-###,",
        "shows on the title screen and in the book.",
        "B sends him to a line, or ahead. B recalls him.",
        "Shells swap free at the landing's Bot tab.",
        "Shells: Tin, Frog (chapter 1), Duck (2), Sub (3),",
        "and Astral (5). Tools need their shell earned.",
        "Reed Anchor, $120: sets lines in reeds.",
        "Wave Chime, $180: G near a line, while slow.",
        "Thermocline Scanner, $260: the cold layer",
        "on Flathead and Crater, shown in the HUD.",
        "Zero-G Winch, $400: holds lines in Nebula currents.",
        "Sonar Grid, $150: chart overlay. Needs a depth finder.",
    )),
    ("LEGENDARIES", (
        "Twelve legendary fish: ten to catch, two witnessed.",
        "Each gated one has a watch card in the Watch tab.",
        "The card lists the clue, the requirements, and the",
        "next window when they line up, weather included.",
        "A line that meets every requirement hooks it on",
        "the first haul of an eligible window. Then a photo",
        "and a trophy replica for the rail.",
        "Star-Whale: Settle In by the Nebula reflection.",
        "Press C there and keep still for 45 seconds.",
        "Whiskered Guardian: no Settle In. Be in Cedar Creek's",
        "deep water, 6 to 8 PM, with 8 Ripples.",
        "Repeats add a weight record, once per game week.",
    )),
    ("SETTINGS AND CAPTIONS", (
        "Pause (Esc, or Start), then Settings.",
        "Text size: Small, Standard or Large.",
        "Dyslexia-friendly font: on or off.",
        "Reduced motion: no camera sway, simpler fades.",
        "Haul speed: Normal, Quick or Instant. Hold E to hurry.",
        "Captions: every chime, Bot sound and horn gets one.",
        "Volumes: master, music, ambience and effects.",
        "Collar visibility hides the collar. Story still counts.",
        "Keyboard controls: Enter rebinds. Backspace or Esc",
        "cancels. Keys in use swap with the one you replace.",
        "Reset keyboard controls brings back the defaults.",
        "",
        "Menus: hover focuses, click selects; the wheel browses rows.",
        "A menu click never steers or acts on the water.",
        "Bait rows only choose; click Set to deploy the line.",
        "Field Guide spreads turn on the wheel or page corners.",
    )),
    ("WHERE SAVES LIVE", (
        "The save is save.json in the game's user-data",
        "folder, the per-user app-data place for this game.",
        "The title screen offers Continue when one exists.",
        "It autosaves about every 45 seconds, and it saves",
        "when you quit, pause to title, or change lakes.",
        "An old v1 save, saves/briar.json, is migrated.",
        "The original is kept in a backup folder beside it.",
        "Start with --save PATH to use another file.",
        "Your money, fish, gear, boats and journal are kept.",
    )),
)

_GAMEPAD_HELP_CONTROLS = {
    "W/S row, or run the motor when one is installed":
        "Left stick / LT / RT row or run the motor",
    "Power stays set       Shift returns it to idle":
        "Power stays set       Shift idles (keyboard)",
    "A D or arrows steer   arrows look up and down":
        "Left stick steers. The pad has no look control.",
    "Space drops or raises the anchor":
        "Space anchors (keyboard)",
    "W / S also pull the anchor when you mean to go":
        "Use the left stick or triggers to set the throttle",
    "F sets a trotline     E checks a line or the landing":
        "X sets a trotline     A checks a line or the landing",
    "Tab chart    J journal    I livewell":
        "Back chart    J journal / I livewell (keyboard)",
    "C hails a paw-wave NPC: within 20 m, below 3 knots":
        "RB hails a paw-wave NPC: within 20 m, below 3 knots",
    "T changes time: 1x 3x 6x 12x, while you are still":
        "T changes time (keyboard): 1x 3x 6x 12x while still",
    "B sends Bot ahead, or out to a line.  B calls him back.":
        "Tap Y sends Bot ahead or to a line.  Tap Y again to recall.",
    "H help    M mute    Esc pause":
        "H help / M mute (keyboard)    Start pauses",
    "Nose into the slip and press E.":
        "Nose into the slip and press A.",
    "At the landing: A/D tabs, W/S rows, Enter selects.":
        "At landing: D-pad tabs / rows, A selects, B returns.",
    "Q raises or lowers the daysailer's sail.":
        "Q raises or lowers the daysailer's sail (keyboard).",
    "A/D steers. Sail across the wind; tack to go upwind.":
        "Left stick steers. Sail across the wind; tack upwind.",
    "W/S controls its small auxiliary. Shift idles it.":
        "Stick or triggers run it; Shift idles (keyboard).",
    "Space anchors and lowers the sail.":
        "Space anchors and lowers the sail (keyboard).",
    "Idle, then R calls a tow if you get stranded.":
        "Press R (keyboard) to call a tow if you get stranded.",
    "W and S throttle up and down. A and D steer.":
        "Left stick or triggers throttle. The stick steers.",
    "Idle with Shift. Press F to set a trotline.":
        "Ease off the triggers. X sets a trotline.",
    "The 1 to 5 keys pick bait. Enter sets the line.":
        "D-pad or stick picks bait. A sets the line.",
    "Anchor with Space and press T to let time run.":
        "Anchor with Space; T lets time run (keyboard).",
    "E checks a line once its cork flag is up.":
        "A checks a line once its cork flag is up.",
    "Head for the landing and press E to open the shop.":
        "Head for the landing and press A to open the shop.",
    "Bot rides the bow. B sends him out to a line and back.":
        "Bot rides the bow. Y tap sends him out and back.",
    "H opens these pages on the water. Pause has Help too.":
        "Pause (Start), then Help, opens these pages.",
    "At a landing, press E and pick the Lakes tab.":
        "At a landing, press A and pick the Lakes tab.",
    "A/D changes tabs, W/S picks a lake, Enter travels.":
        "D-pad changes tabs and lakes; A travels.",
    "J opens the book. A/D changes tabs, W/S chooses.":
        "J opens the book (keyboard). D-pad changes tabs.",
    "Enter opens a fish or turns a page. J closes it.":
        "A opens a fish or turns a page. B closes it.",
    "Track from the species entry: click it, or press F.":
        "Track from the entry: click it, or press X.",
    "In the livewell, Enter or T marks Treasured.":
        "In the livewell, Enter or T marks Treasured (keyboard).",
    "Trophy shelf: F hangs a replica on a rail boat.":
        "Trophy shelf: X hangs a replica on a rail boat.",
    "Hail with C within 20 m, under 3 knots.":
        "Hail with RB within 20 m, under 3 knots.",
    "In a chat, W/S or the arrows pick a reply.":
        "The D-pad picks a reply in a chat.",
    "Numbers 1 to 5 pick one too. Enter or C goes on.":
        "A goes on. Number keys pick a reply (keyboard).",
    "Esc closes a chat, unless a story scene is playing.":
        "B closes a chat, unless a story scene is playing.",
    "K opens the pantry from the water. Cooking needs":
        "Pause, then Y, opens the pantry. Cooking needs",
    "Later snoozes a prompt for 30 minutes. F or Esc.":
        "Later snoozes a prompt for 30 minutes. X or B.",
    "Z takes a two-hour catnap. Hold Y on a pad.":
        "Hold Y for a two-hour catnap.",
    "Pause, then Z or F, also naps.":
        "Pause, then X, also naps.",
    "B sends him to a line, or ahead. B recalls him.":
        "Y tap sends him to a line; tap again to recall.",
    "Wave Chime, $180: G near a line, while slow.":
        "Wave Chime, $180: LB near a line, while slow.",
    "Press C there and keep still for 45 seconds.":
        "Press RB there and keep still for 45 seconds.",
    "Pause (Esc, or Start), then Settings.":
        "Pause (Start), then Settings.",
    "Haul speed: Normal, Quick or Instant. Hold E to hurry.":
        "Haul speed: Normal, Quick or Instant. Hold A to hurry.",
    "Q or G sets how many sections, 1 to 3.":
        "LB sets how many sections, 1 to 3.",
    "Tab picks which section you edit.":
        "Back picks which section you edit.",
    "On the chart: C hails, Space anchors, Q sails,":
        "On the chart: RB hails; the rest are keyboard.",
    "R tows, B sends Bot. Tab or Esc closes the chart.":
        "Back or B closes the chart. R tows (keyboard).",
    "Keyboard controls: Enter rebinds. Backspace or Esc":
        "Keyboard controls: Enter rebinds (keyboard). Backspace or Esc",
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
    "Dress your Skipper: Esc, then Your Skipper.":
        "Dress your Skipper: Start, then Your Skipper.",
    "Anchor and press T to let time run. E checks a line.":
        "After setting a line, wait for a bite; A checks it.",
    "Nose into the landing and press E to sell.":
        "Nose into the landing and press A to sell.",
}


# --- glyph tables (V1-41) -------------------------------------------------
#
# The keyboard tables name each player action with the key bound to it, so a
# rebound key shows here. Each row holds up to two actions. Every page's line
# count is fixed, so HELP_N does not depend on the bindings.

_KEY_GLYPHS = {
    "shift": "Shift", "rshift": "R Shift", "return": "Enter", "esc": "Esc",
    "space": "Space", "tab": "Tab", "up": "Up", "down": "Down",
    "left": "Left", "right": "Right",
}
_KEYBOARD_ROWS = (
    ("KEYBOARD: ON THE WATER", (
        (("Throttle up", ("throttle_up",)), ("Throttle dn", ("throttle_down",))),
        (("Steer left", ("steer_left",)), ("Steer right", ("steer_right",))),
        (("Idle", ("idle",)), ("Idle, too", ("idle_right",))),
        (("Anchor", ("anchor",)), ("Set trotline", ("set_line",))),
        (("Check/land", ("check_or_land",)), ("Raise sail", ("sail",))),
        (("Call a tow", ("tow",)), ("Bot out/back", ("bot",))),
        (("Bot's chime", ("bot_tool",)), ("Hail, talk", ("hail",))),
    )),
    ("KEYBOARD: THE REST", (
        (("Time scale", ("time_scale",)), ("Catnap", ("catnap",))),
        (("Pantry", ("galley",)), ("Chart", ("chart",))),
        (("Journal", ("journal",)), ("Livewell", ("livewell",))),
        (("Help", ("help",)), ("Mute", ("mute",))),
        (("Pause", ("pause",)), ("New (title)", ("new_game",))),
        (("Menu up/dn", ("menu_up", "menu_down")),
         ("Menu L/R", ("menu_left", "menu_right"))),
        (("Select", ("select",)), None),
    )),
)

# (buttons, name, what it does). The page is built from these rows; the test
# checks that every button in BUTTON_ACTIONS has a row.
_PAD_BUTTON_ROWS = (
    ((BUTTON_A,), "A", "Check a line or landing; select"),
    ((BUTTON_B,), "B", "Pause; back out of menus and pages"),
    ((BUTTON_X,), "X", "Set a trotline; track a shiny"),
    ((BUTTON_Y,), "Y tap", "Send or recall Bot"),
    ((BUTTON_Y,), "Y hold", "Catnap at anchor or a landing"),
    ((BUTTON_LEFTSHOULDER,), "LB", "Use the Bot tool (the Wave Chime)"),
    ((BUTTON_RIGHTSHOULDER,), "RB", "Hail a cat; go on talking"),
    ((BUTTON_START,), "Start", "Pause"),
    ((BUTTON_BACK,), "Back", "Chart"),
    ((BUTTON_DPAD_UP, BUTTON_DPAD_DOWN, BUTTON_DPAD_LEFT, BUTTON_DPAD_RIGHT),
     "D-pad", "Move through menus, tabs and pages"),
)
_PAD_STICK_ROWS = (
    ("Left stick", "Steer. Up and down set the throttle."),
    ("RT / LT", "Throttle up; down to idle and reverse."),
    ("In pause, Y", "Opens the pantry; cook at a landing."),
    ("Start, then", "Book, livewell, sail, tow and time."),
    ("Settings", "Volumes; Master at 0% is quiet."),
    ("Title", "D-pad to New morning, then A."),
)


def _glyph(key: str) -> str:
    return _KEY_GLYPHS.get(key) or UI._key_name(key)


def _keyboard_cell(bindings, item) -> tuple:
    """(key, label) for one keyboard table cell; ("", "") when the row has none."""
    if item is None:
        return ("", "")
    label, actions = item
    return ("/".join(_glyph(bindings[action]) for action in actions), label)


def _keyboard_pages(bindings) -> tuple:
    pages = []
    for title, rows in _KEYBOARD_ROWS:
        lines = ["Each key is the one you have bound.", ""]
        for left, right in rows:
            lines.append((*_keyboard_cell(bindings, left), *_keyboard_cell(bindings, right)))
        pages.append((title, tuple(lines)))
    return tuple(pages)


def _gamepad_pages() -> tuple:
    buttons = tuple((name, what) for _buttons, name, what in _PAD_BUTTON_ROWS)
    sticks = tuple((name, what) if what else name for name, what in _PAD_STICK_ROWS)
    return (
        ("GAMEPAD: BUTTONS", buttons),
        ("GAMEPAD: STICKS, PAUSE", sticks),
    )


_GAMEPAD_PAGES = _gamepad_pages()


def help_pages(saved_bindings=None) -> tuple:
    """Every help page: the authored pages, then the keyboard and gamepad tables.

    `saved_bindings` is the `key_bindings` setting. The keyboard tables follow it,
    but the page count never changes with the bindings.
    """
    bindings = normalize_key_bindings(saved_bindings)
    return (*_HELP, *_keyboard_pages(bindings), *_GAMEPAD_PAGES)


def _saved_bindings(state):
    v2 = getattr(state, "v2", None)
    settings = v2.get("settings") if isinstance(v2, dict) else None
    return settings.get("key_bindings") if isinstance(settings, dict) else None


def help_topics(state, input_device: str) -> tuple:
    """The help pages as the Field Guide shows them to this player.

    Args:
        state: the game state whose saved key bindings fill the keyboard tables, or None.
        input_device: "gamepad" uses pad wording; keyboard and pointer retain keyboard hints.

    Returns:
        (title, lines) per help page, in `help_pages` order.
    """
    pages = help_pages(_saved_bindings(state))
    if input_device != "gamepad":
        return pages
    return tuple((title, tuple(_GAMEPAD_HELP_CONTROLS.get(line, line) for line in lines))
                 for title, lines in pages)


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


HELP_N = len(help_pages())
# Spreads in the Field Guide when every topic fits one page. The guide counts its real
# spreads when it is drawn (UIState.help_spreads); page turns fall back on this before then.
HELP_SPREADS = (HELP_N + 1) // 2
FIELD_GUIDE_TITLE = f"{GAME_TITLE}  ·  Field Guide"


def _clamp(index: int, count: int) -> int:
    if count <= 0:
        return 0
    if index < 0:
        return 0
    if index >= count:
        return count - 1
    return index


def _phrase_lines(text: str, cells: int) -> list[str]:
    """Lay a hint out in lines of at most `cells` characters, breaking only between phrases.

    The phrases of a hint are joined by "  ·  ". A phrase stays whole on one line, so "Done" is
    never left at the end of a line with "saves" on the next. A phrase longer than a line on its
    own is word-wrapped, since nothing else can fit it.

    Args:
        text: the hint, phrases separated by "  ·  ".
        cells: the line width in character cells (panel width over the small font's cell width).

    Returns:
        The lines top to bottom; an empty list for empty text.
    """
    separator = "  ·  "
    lines: list[str] = []
    line = ""
    for phrase in text.split(separator):
        if len(phrase) > cells:
            if line:
                lines.append(line)
                line = ""
            lines.extend(textwrap.wrap(phrase, cells))
            continue
        trial = phrase if not line else line + separator + phrase
        if len(trial) <= cells:
            line = trial
        else:
            lines.append(line)
            line = phrase
    if line:
        lines.append(line)
    return lines


def _fit(img: np.ndarray, tw: int, th: int) -> np.ndarray:
    sh, sw = img.shape[:2]
    ys = np.linspace(0, sh - 1, th).astype(np.int32)
    xs = np.linspace(0, sw - 1, tw).astype(np.int32)
    return img[ys][:, xs]


# Haul sprite pixels per fish-mesh unit; the legendary idle bob converts with it.
_HAUL_SPRITE_SCALE = 136.0


@lru_cache(maxsize=48)
def _haul_mesh_sprite(species_id: str, lake_id: str, shiny: bool) -> np.ndarray:
    """Rasterize a cached side-on fish mesh for the haul's surface beat."""
    from .fishmesh import haul_mesh

    width, height = 384, 192
    color = np.zeros((height, width, 3), dtype=np.float32)
    depth = np.full((height, width), 1e6, dtype=np.float32)
    mesh = haul_mesh(species_id, lake_id, shiny)
    projected = mesh.vertices[:, :2].copy()
    projected[:, 0] = width * 0.5 + projected[:, 0] * _HAUL_SPRITE_SCALE
    projected[:, 1] = height * 0.5 - projected[:, 1] * _HAUL_SPRITE_SCALE
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
                  "peak_rss_mib": round(__import__("fishing.verify", fromlist=["rss_bytes"]).rss_bytes() / 1024**2, 1),
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
