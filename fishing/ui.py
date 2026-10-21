"""Quiet lake journal, readable menus, and a compact navigation HUD."""

from __future__ import annotations

from dataclasses import dataclass
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
from .narrative import QUEST_IDS
from .platform import Text
from .dialogue import nearby_npc
from .world import ZONE_NAME, World
from .boat import (
    BOATS, FUEL_PRICE, ROWBOAT_MOTOR_PRICE, ROWBOAT_BATTERY_KWH,
    BATTERY_CHARGE_KWH, ELECTRICITY_PRICE,
)
from .lakes import LAKES
from .weather import wind_at

INK = (238, 233, 216)
DIM = (169, 183, 175)
GOLD = (218, 187, 124)
WARN = (220, 126, 96)
GOOD = (150, 196, 140)
GAME_TITLE = "Trotline Purridise"

SHOP_TABS = ("Sell", "Bait", "Gear", "Paint", "Boats", "Lakes")
_TABS = SHOP_TABS

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


def quest_journal_details(state, content, quest_id: str) -> dict:
    """Build safe, contract-grounded text for the selected narrative journal row."""
    quest = content.quests[quest_id]
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


@dataclass
class UIState:
    mode: str = "title"
    input_device: str = "keyboard"
    shop_tab: int = 0
    shop_i: int = 0
    set_line: int = 0
    set_bait: int = 0
    check_line: int = 0
    check_i: int = 0
    journal_i: int = 0
    journal_page: int = 0
    journal_quest_i: int = 0
    well_i: int = 0
    pause_i: int = 0
    help_page: int = 0
    help_from: str = "play"
    title_i: int = 0
    confirm_new: bool = False
    note: str = ""
    has_save: bool = False
    conversation: object = None
    dialogue_content: object = None
    dialogue_from: str = "play"


def shop_rows(state, tab: int) -> list[Row]:
    rows: list[Row] = []
    if tab == 0:
        total = round(sum(c.value() for c in state.well), 2)
        rows.append(Row(
            "Sell everything", dollars(total), "The buyer is at the end of the dock.",
            bool(state.well), "sell_all",
        ))
        for i, catch in enumerate(state.well):
            name = SPECIES_BY_ID[catch.species].name
            q = quality_name(catch.quality)
            rows.append(Row(
                f"{catch.weight:.1f} lb {name}, {q}", dollars(catch.value()),
                f"Caught on {BAIT_BY_ID[catch.bait].name.lower()}.",
                True, "sell_one", str(i),
            ))
    elif tab == 1:
        for bait in BAITS:
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
                state.owned_lines() < 5, "line", tier,
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
        descriptions = {
            "jon":"Light and nimble. A 12 L tank and your familiar 12-foot hull.",
            "sail":"Wind power uses no fuel. Small auxiliary, 6 L tank. Q raises or lowers the sail.",
            "pontoon":"Wide deck, sheltered helm, 36 L tank, and 40 lb of extra livewell capacity.",
            "rowboat":"Blue 10-foot plastic hull, cream interior, two-place front bench, backless center stool, and two aft seats. Row with W/S; steer with A/D.",
        }
        for model in BOATS.values():
            owned = model.id in state.owned_boats
            right = "aboard" if model.id==state.boat_id else ("owned" if owned else dollars(model.price))
            rows.append(Row(model.name,right,descriptions[model.id],model.id!=state.boat_id,"boat",model.id))
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
            detail = lake["blurb"] if not state.lines else "Pick up your deployed lines before towing to another lake."
            rows.append(Row(lake["name"],"here" if here else "travel",detail,not here,"lake",lake_id))
    return rows


def check_rows(state, line_index: int) -> list[Row]:
    if line_index < 0 or line_index >= len(state.lines):
        return []
    line = state.lines[line_index]
    rows: list[Row] = []
    for i, hook in enumerate(line.hooks):
        if hook.catch is None:
            label = "baited" if hook.baited else "bare"
            rows.append(Row(f"{i + 1:2d}   {label}", "", "", False, "hook", str(i)))
        else:
            catch = hook.catch
            name = SPECIES_BY_ID[catch.species].name
            q = quality_name(catch.quality)
            rows.append(Row(
                f"{i + 1:2d}   {catch.weight:.1f} lb {name}, {q}", dollars(catch.value()),
                "", True, "hook", str(i),
            ))
    rows.append(Row("Take all", "", "Moves what the livewell can hold.", True, "take_all"))
    rows.append(Row("Rebait bare hooks", "", f"Uses {BAIT_BY_ID[line.bait].name.lower()} from the box.", True, "rebait"))
    rows.append(Row("Pull the line", "", "Coils it aboard. The well must hold every fish.", True, "pull"))
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
        self._cw: dict[int, int] = {}
        self._ch: dict[int, int] = {}

    def cell(self, size: int) -> tuple[int, int]:
        if size not in self._cw:
            img = self.text.render("M", size, INK)
            self._cw[size] = max(1, img.shape[1])
            self._ch[size] = max(1, img.shape[0])
        return self._cw[size], self._ch[size]

    def draw(self, frame: np.ndarray, state, ui: UIState, camera=None) -> None:
        mode = ui.mode
        if mode == "play":
            draw_sighting(frame, state, camera)
        if mode == "title":
            self._title(frame, state, ui)
            self._toasts(frame, state)
            return
        if mode == "play":
            self._hud(frame, state, ui)
            self._toasts(frame, state)
            return
        if mode == "map":
            self._hud(frame, state, ui)
            self._map(frame, state, ui, big=True)
            self._toasts(frame, state)
            return
        if mode == "dialogue":
            self._hud(frame, state, ui, interactions=False)
            self._dialogue(frame, state, ui)
            self._toasts(frame, state)
        elif mode == "shop":
            self._shop(frame, state, ui)
        elif mode == "setbait":
            self._setbait(frame, state, ui)
        elif mode == "check":
            self._check(frame, state, ui)
        elif mode == "journal":
            if ui.journal_page == 1:
                self._narrative_journal(frame, state, ui)
            else:
                self._journal(frame, state, ui)
        elif mode == "well":
            self._well(frame, state, ui)
        elif mode == "pause":
            self._pause(frame, ui)
        elif mode == "help":
            self._help(frame, ui)

    def _dialogue(self, frame, state, ui):
        chat = ui.conversation
        if chat is None:
            return
        node = ui.dialogue_content.dialogue[chat.node_id]
        name = ui.dialogue_content.npcs[chat.npc_id]['name']
        h, w = frame.shape[:2]
        size = self._size(frame, "small")
        cw, ch = self.cell(size)
        margin = 16
        width = min(w - 24, 1000)
        cols = max(8, (width - margin*2) // cw)
        lines = textwrap.wrap(node['text'], cols)
        choices = node.get('choices', [])
        rows = lines + ['']
        colors = [INK] * len(lines) + [DIM]
        for i, choice in enumerate(choices):
            label = f"{'>' if i == chat.selected else ' '} {i+1}. {choice['text']}"
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
        footer = textwrap.wrap(foot, cols)
        height = (len(rows) + len(footer) + 2) * (ch + 3) + margin*2
        x, y = (w-width)//2, h-height-12
        self._panel(frame, x, y, width, height, 0.96)
        self._text(frame, name, x+margin, y+margin, size, GOLD, False)
        top = y+margin+(ch+3)*2
        for i, (line, color) in enumerate(zip(rows+footer, colors+[DIM]*len(footer))):
            self._text(frame, line, x+margin, top+i*(ch+3), size, color, False)

    # --- primitives -----------------------------------------------------

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
            shade = self.text.render(s, size, (8, 12, 10), family)
            self._blit(frame, shade, x + 1, y + 1)
        img = self.text.render(s, size, color, family)
        self._blit(frame, img, x, y)
        return img.shape[1]

    def _measure(self, s, size, family="sans"):
        return self.text.render(s,size,INK,family).shape[1]

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
        unit = h / 720
        size,small = max(16,int(22*unit)),max(11,int(12*unit))
        m = max(12,int(26*unit))
        weather = weather_at(state.game_minutes).upper()
        clock = clock_string(state.game_minutes)
        self._panel(frame,m,m,int(205*unit)+34,int(92*unit)+10,0.66)
        self._text(frame,self.world.name.upper(),m+16,m+int(11*unit),small,GOLD,False,"sans")
        self._text(frame,clock,m+16,m+int(31*unit),max(22,int(30*unit)),INK,False,"serif")
        meta = weather
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
        else:
            fuel = f"FUEL  {state.fuel:.1f} / {state.boat.tank:.0f} L"
            self._text(frame,fuel,rx+16,m+int(111*unit),small,
                       WARN if state.fuel<state.boat.tank*0.15 else DIM,False,"sans")
        if state.boat_id=="sail":
            wind,wind_speed = wind_at(state.game_minutes+state.minute_acc)
            coming_from = (wind+np.pi)%(2*np.pi)
            direction = ("N","NE","E","SE","S","SW","W","NW")[int(coming_from/(np.pi/4)+0.5)%8]
            sail = "SAIL UP" if state.sail_raised else "SAIL DOWN"
            self._text(frame,f"{sail} / {direction} {wind_speed*1.94384:.0f} KT",rx+16,m+int(131*unit),small,GOLD,False,"sans")
        elif state.bot_phase != "home":
            from .bot import status as bot_status
            self._text(frame, bot_status(state), rx+16, m+int(131*unit), small, GOLD, False, "sans")
        else:
            from .sim import fishing_hint
            hint = fishing_hint(state, self.world)
            label = self._trim(hint, small, rw - 32) if hint else state.boat.name
            self._text(frame, label, rx+16, m+int(131*unit), small, GOLD if hint else DIM, False, "sans")
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
        prompt = state.prompt(self.world)
        if prompt and ui.input_device == "gamepad":
            prompt = prompt.replace("E  ", "A  ", 1)
        if prompt:
            pw = self._measure(prompt,small+2)+32
            px,py = (w-pw)//2,h-m-max(map_h,stat_h+lines_h)-int(35*unit)-8
            if npc is not None:
                py -= 42
            self._panel(frame,px,py,pw,int(30*unit)+8,0.72)
            self._text(frame,prompt,px+16,py+5,small+2,INK,False,"sans")
        if ui.input_device == "gamepad":
            hint = "LS drive  LT/RT lever  Y Bot  X Set  A Check  RB Hail  Back Chart  Start Pause"
        else:
            hint = "B Bot  Shift Idle  Q Sail  F Set  E Landing  C Hail  H Help" if state.boat_id=="sail" else "B Bot  Shift Idle  F Set  E Check  R Tow  C Hail  H Help"
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
        height = 12 + row_h * (len(state.lines[:5]) + 1)
        y = above - height
        self._panel(frame, right, y, width, height, 0.80)
        self._text(frame, "LINES", right + 16, y + 8, size, GOLD, False, "sans")
        for i, line in enumerate(state.lines[:5]):
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
        self._plot_trinidad_cove(frame, x, y, mw, mh, labels=True)
        self._plot_npcs(frame, state, x, y, mw, mh, labels=True)
        self._plot_boat(frame, state, x, y, mw, mh, radius=4)
        self._plot_bot(frame, state, x, y, mw, mh)
        size = self._size(frame, "small")
        self._text(frame, self.world.name, x, y - self.cell(size)[1] - 14, size, INK)
        self._text(frame, "Fish gold   soak green   tired red   NPC blue", x, y + mh + 12, size, DIM, shadow=False)
        close_hint = self._controls(ui, "Tab closes the chart", "B closes the chart")
        self._text(frame, close_hint, x + mw - 20 * self.cell(size)[0], y + mh + 14 + self.cell(size)[1], size, DIM, shadow=False)

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
        color = (128, 206, 240)
        for npc in state.npcs:
            if npc.anchor.lake_id != self.world.id:
                continue
            u, v = self.world.map_pixel(npc.anchor.x, npc.anchor.z, mw, mh)
            self._dot(frame, x + u, y + v, 3 if labels else 2, color)
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

    def _toasts(self, frame, state):
        if not state.toasts:
            return
        size = self._size(frame, "small")
        _cw, ch = self.cell(size)
        w = frame.shape[1]
        y = max(8, frame.shape[0] // 7)
        for text, _ttl in state.toasts[-3:]:
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
        x,y = int(w*0.075),int(h*(0.20 if h<480 else 0.43))
        self._text(frame,"A   T R O T L I N E   L A K E",x,y,small,GOLD,False,"sans")
        self._text(frame,GAME_TITLE,x,y+small+10,title,INK,True,"serif")
        self._text(frame,"Set your lines. Stay a while.",x,y+title+small+20,body,DIM,False,"sans")
        options = title_options(ui.has_save)
        ui.title_i %= len(options)
        y2 = y+title+small+body+(30 if h<480 else 48)
        if ui.confirm_new:
            msg = "New morning? The save on disk stays until you overwrite it."
            self._text(frame,self._trim(msg,small,w-x*2),x,y2,small,WARN,False)
            hint = self._controls(ui, "Enter starts over     Esc cancels",
                                  "A starts over     B cancels")
            self._text(frame,hint,x,y2+small+12,small,DIM,False,"sans")
            return
        for i, label in enumerate(options):
            oy = y2+i*(body+27)
            if i==ui.title_i:
                self._round_fill(frame,x,oy-4,max(210,int(w*0.21)),body+24,GOLD,0.95)
                self._text(frame,label,x+15,oy+4,body,(22,39,39),False,"sans")
                select = "A" if ui.input_device == "gamepad" else "ENTER"
                self._text(frame,select,x+max(210,int(w*0.21))-55,oy+9,small,(42,56,50),False,"sans")
            else:
                self._text(frame,label,x+15,oy+4,body,INK,False,"sans")
        controls = self._controls(ui, "H  Field guide     W / S  Choose",
                                  "D-pad / stick choose     A select")
        self._text(frame,controls,x,h-small-24,small,DIM,False,"sans")
        mark = "ONE LAKE. NO HURRY."
        self._text(frame,mark,w-x-self._measure(mark,small),h-small-24,small,DIM,False,"sans")

    def _shop(self, frame, state, ui: UIState):
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
        for i, name in enumerate(_TABS):
            color = GOLD if i == ui.shop_tab else DIM
            label = f"[{name}]" if i == ui.shop_tab else f" {name} "
            tw = self._text(frame, label, tx, tab_y, body, color)
            tx += tw + 18
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
        held = state.held[ui.set_line]
        spec = LINE_TIERS[held.tier]
        which = f"Line {ui.set_line + 1} of {len(state.held)}    {spec['hooks']} hooks"
        self._text(frame, which, x + m, y + 16 + self.cell(head)[1], small, GOLD, shadow=False)
        top = y + 28 + self.cell(head)[1] + self.cell(small)[1]
        for i, bait in enumerate(BAITS):
            have = state.bait.get(bait.id, 0)
            need = spec["hooks"]
            label = f"{i + 1}  {bait.name}"
            right = f"{have} aboard"
            color = GOLD if i == ui.set_bait else INK
            if have < need and i == ui.set_bait:
                color = WARN
            elif have < need:
                color = DIM
            ry = top + i * (ch + 4)
            if i == ui.set_bait:
                self._fill(frame, x + 8, ry - 1, pw - 16, ch + 2, (46, 42, 28), 0.85)
            self._text(frame, label, x + m, ry, body, color, shadow=False)
            rw = len(right) * self.cell(body)[0]
            self._text(frame, right, x + pw - m - rw, ry, body, color, shadow=False)
        bait = BAITS[ui.set_bait]
        note = ui.note or f"Needs {spec['hooks']}. {bait.blurb}"
        self._text(frame, self._trim(note, small, pw - m * 2), x + m, y + ph - ch - 28, small, WARN if ui.note else DIM, shadow=False)
        foot = self._controls(ui, "W/S bait  A/D line  Arrows too  1-5 bait  Enter sets  Esc",
                              "D-pad / stick choose bait or line  A sets  B back")
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
        sub = f"{BAIT_BY_ID[line.bait].name}    {line.fish_on()} fish    {line.bare_hooks()} bare"
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
            ui, "W/S or arrows choose  Enter takes  Esc leaves it fishing",
            "D-pad / stick choose  A takes  B leaves it fishing",
        )
        self._text(frame, self._trim(foot, small, pw - m * 2), x + m, y + ph - self.cell(small)[1] - 10, small, WARN if ui.note else DIM, shadow=False)

    def _journal(self, frame, state, ui: UIState):
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.72), int(h * 0.76)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.96)
        head = self._size(frame, "head")
        body = self._size(frame, "body")
        small = self._size(frame, "small")
        m = 16
        ui.journal_i = _clamp(ui.journal_i, len(SPECIES))
        seen = sum(1 for sp in SPECIES if state.journal.get(sp.id, {}).get("count", 0) > 0)
        self._text(frame, "JOURNAL", x + m, y + 12, head, INK)
        self._text(frame, f"{seen} of {len(SPECIES)} species", x + m + len("JOURNAL") * self.cell(head)[0] + 16, y + 18, small, GOLD, shadow=False)
        page_hint = "1/2 · D-pad pages" if ui.input_device == "gamepad" else "1/2 · A/D pages"
        self._text(frame, page_hint, x + pw - m - 18 * self.cell(small)[0], y + 18, small, DIM, shadow=False)
        sp = SPECIES[ui.journal_i]
        rec = state.journal.get(sp.id, {})
        count = int(rec.get("count", 0))
        top = y + 20 + self.cell(head)[1]
        ch = self.cell(body)[1]
        col_w = int(pw * 0.46)
        visible = max(4,(ph-(top-y)-self.cell(small)[1]*2)//(self.cell(small)[1]+2))
        start = _window(ui.journal_i,len(SPECIES),visible)
        for row_i,item in enumerate(SPECIES[start:start+visible]):
            i = start+row_i
            rec_i = state.journal.get(item.id, {})
            n = int(rec_i.get("count", 0))
            label = item.name
            color = GOLD if i == ui.journal_i else (INK if n else DIM)
            prefix = "> " if i == ui.journal_i else "  "
            extra = f"{n}" if n else ""
            self._text(frame, self._trim(prefix + label, small, col_w - 40), x + m, top + row_i * (self.cell(small)[1] + 2), small, color, shadow=False)
            if extra:
                self._text(frame, extra, x + col_w - 24, top + row_i * (self.cell(small)[1] + 2), small, color, shadow=False)
        dx = x + col_w + 8
        if count <= 0:
            self._text(frame,sp.name,dx,top,body,INK)
            note = "Find this one on Little Briar." if self.world.id=="cedar" and not CEDAR_FISH[sp.id] else "Not on a hook yet."
            self._text(frame,note,dx,top+ch+4,small,DIM)
            self._wrap(frame,sp.blurb,dx,top+ch+self.cell(small)[1]+14,small,DIM,pw-(dx-x)-m)
        else:
            best = float(rec.get("best", 0))
            from .lakes import CEDAR_ZONES
            names = CEDAR_ZONES if rec.get("lake_id","briar")=="cedar" else ZONE_NAME
            zone = names.get(rec.get("zone", ""), rec.get("zone", ""))
            bait = BAIT_BY_ID[rec["bait"]].name if rec.get("bait") in BAIT_BY_ID else ""
            band = rec.get("band", "")
            self._text(frame, sp.name, dx, top, body, INK)
            self._text(frame, f"{count} caught    best {best:.1f} lb", dx, top + ch + 4, small, GOLD, shadow=False)
            where = "  ".join(p for p in (zone, bait, band) if p)
            self._text(frame, where, dx, top + ch + self.cell(small)[1] + 12, small, INK, shadow=False)
            self._wrap(frame, sp.blurb, dx, top + ch + self.cell(small)[1] * 2 + 24, small, DIM, pw - (dx - x) - m)
        foot = self._controls(ui, "W/S or arrows choose    A/D pages    J or Esc closes",
                              "D-pad / stick choose    D-pad pages    B closes")
        self._text(frame, foot, x + m, y + ph - self.cell(small)[1] - 10, small, DIM, shadow=False)

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
        h, w = frame.shape[:2]
        pw, ph = int(w * 0.94), int(h * 0.96)
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.97)
        head = self._size(frame, "head")
        body = self._size(frame, "body")
        small = self._size(frame, "small")
        m = 16
        quests = self.narrative_content.quests
        ui.journal_quest_i = _clamp(ui.journal_quest_i, len(QUEST_IDS))
        ripple_count = min(10, len(set(state.narrative.ripples)))
        self._text(frame, "LAKE WHISPERS & RIPPLES", x + m, y + 9, head, INK)
        counter = f"{ripple_count}/10 Ripples"
        counter_w = len(counter) * self.cell(small)[0]
        self._text(frame, counter, x + pw - m - counter_w, y + 16, small, GOLD, shadow=False)
        page_line = self._controls(ui, "2/2 · W/S · A/D pages · J closes",
                                   "2/2 · D-pad / stick · D-pad pages · B closes")
        page_w = len(page_line) * self.cell(small)[0]
        self._text(frame, page_line, x + pw - m - page_w, y + 16 + self.cell(small)[1], small, DIM, shadow=False)

        small_ch = self.cell(small)[1]
        row_height = small_ch + 2
        content_top = y + 12 + self.cell(head)[1] + 5
        footer_height = row_height * 4 + 10
        footer_top = y + ph - footer_height
        left_w = int(pw * 0.34)
        detail_x = x + left_w + 12
        detail_w = pw - (detail_x - x) - m
        self._text(frame, "OPTIONAL QUESTS", x + m, content_top, small, GOLD, shadow=False)

        rows_top = content_top + row_height + 3
        visible = max(1, (footer_top - rows_top) // row_height)
        start = _window(ui.journal_quest_i, len(QUEST_IDS), visible)
        badge_w = max(map(len, _STATUS_BADGES.values())) * self.cell(small)[0]
        for row_offset, quest_id in enumerate(QUEST_IDS[start:start + visible]):
            index = start + row_offset
            quest = quests[quest_id]
            status = state.narrative.quests[quest_id].status
            ry = rows_top + row_offset * row_height
            if index == ui.journal_quest_i:
                self._fill(frame, x + m - 4, ry - 1, left_w - m, row_height, (46, 42, 28), 0.86)
            color = _STATUS_COLORS.get(status, DIM)
            prefix = "> " if index == ui.journal_quest_i else "  "
            label_width = left_w - 2 * m - badge_w - 8 - len(prefix) * self.cell(small)[0]
            short_title = _SHORT_QUEST_TITLES.get(quest_id, quest["title"])
            label = self._trim(short_title, small, label_width)
            self._text(frame, prefix + label, x + m, ry, small, color, shadow=False)
            badge = _STATUS_BADGES.get(status, "AVAIL")
            badge_width = len(badge) * self.cell(small)[0]
            self._text(frame, badge, x + left_w - m - badge_width, ry, small, color, shadow=False)

        detail = quest_journal_details(state, self.narrative_content,
                                       QUEST_IDS[ui.journal_quest_i])
        detail_y = content_top
        detail_bottom = footer_top - 3
        progress_line_height = small_ch + 2
        detail_body_bottom = max(content_top, detail_bottom - progress_line_height)
        detail_y = self._draw_journal_text(
            frame, detail["title"], detail_x, detail_y, detail_w, body, INK,
            max_lines=1, bottom=detail_body_bottom)
        detail_y = min(detail_y + 1, detail_body_bottom)
        detail_y = self._draw_journal_text(
            frame, f"{detail['status']} · Prerequisites: {detail['prerequisites']}",
            detail_x, detail_y, detail_w, small, GOLD, max_lines=2, bottom=detail_body_bottom)
        detail_y = self._draw_journal_text(
            frame, f"Giver: {detail['giver']}", detail_x, detail_y, detail_w,
            small, INK, max_lines=2, bottom=detail_body_bottom)
        detail_y = self._draw_journal_text(
            frame, f"Objective: {detail['objective']}", detail_x, detail_y, detail_w,
            small, DIM, max_lines=4, bottom=detail_body_bottom)
        self._draw_journal_text(
            frame, f"Progress: {detail['progress']}", detail_x, detail_y, detail_w,
            small, GOOD if detail["status"] == "Ready" else INK,
            max_lines=2, bottom=detail_bottom)

        note_y = footer_top
        latest_bot_note = detail["latest_bot_note"]
        note_bottom = y + ph - 5
        if latest_bot_note:
            note = latest_bot_note.strip()
            if note.lower().startswith("bot:"):
                note = note.split(":", 1)[1].strip()
            note_y = self._draw_journal_text(
                frame, "Bot: " + note, x + m, note_y, pw - m * 2,
                small, GOLD, max_lines=1, bottom=note_bottom)
        else:
            note_y = self._draw_journal_text(
                frame, "No narrative notes yet.", x + m, note_y, pw - m * 2,
                small, DIM, max_lines=1, bottom=note_bottom)
        note_y = self._draw_journal_text(
            frame, detail["guardian_status"], x + m, note_y, pw - m * 2,
            small, GOLD, max_lines=2, bottom=note_bottom)
        revisit = "Declined? Re-hail. Missed windows repeat; no expiry."
        self._draw_journal_text(
            frame, revisit, x + m, note_y, pw - m * 2, small, DIM,
            max_lines=1, bottom=note_bottom)

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
                name = SPECIES_BY_ID[catch.species].name
                q = quality_name(catch.quality)
                label = f"{catch.weight:.1f} lb {name}, {q}"
                color = GOLD if i == ui.well_i else INK
                ry = top + n * (ch + 2)
                self._text(frame, self._trim(label, body, int(pw * 0.68)), x + m, ry, body, color, shadow=False)
                right = dollars(catch.value())
                self._text(frame, right, x + pw - m - len(right) * self.cell(body)[0], ry, body, color, shadow=False)
        foot = self._controls(ui, "W/S or arrows choose    I closes",
                              "D-pad / stick choose    B closes")
        self._text(frame, foot, x + m, y + ph - self.cell(small)[1] - 10, small, DIM, shadow=False)

    def _pause(self, frame, ui: UIState):
        h, w = frame.shape[:2]
        self._fill(frame, 0, 0, w, h, (6, 8, 8), 0.35)
        labels = ["Resume", "Help", "Main menu", "Quit"]
        body = self._size(frame, "body")
        head = self._size(frame, "head")
        small = self._size(frame, "small")
        pw = int(w * 0.34)
        ph = 40 + self.cell(head)[1] + len(labels) * (self.cell(body)[1] + 8) + 30
        x, y = (w - pw) // 2, (h - ph) // 2
        self._panel(frame, x, y, pw, ph, 0.92)
        self._text(frame, "PAUSED", x + 18, y + 14, head, INK)
        ui.pause_i %= len(labels)
        for i, label in enumerate(labels):
            color = GOLD if i == ui.pause_i else INK
            prefix = "> " if i == ui.pause_i else "  "
            self._text(frame, prefix + label, x + 18, y + 24 + self.cell(head)[1] + i * (self.cell(body)[1] + 8), body, color)
        foot = self._controls(ui, "W/S or arrows   Enter selects",
                              "D-pad / stick choose   A selects   B resumes")
        self._text(frame, foot, x + 18, y + ph - self.cell(small)[1] - 12, small, DIM, shadow=False)

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
        ch = max(self.text.render(line, body, INK).shape[0] for line in (*lines, foot) if line)
        hh = self.text.render(title, head, INK).shape[0]
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
        "A fish left on the hook spoils after 13 hours.",
        "Run a line over and you may knock one off.",
        "",
        "While the game is closed the lines keep soaking,",
        "for up to six hours of real time, then the fish spoil.",
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
        "Five deployed lines is the limit on either lake.",
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
