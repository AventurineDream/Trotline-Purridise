"""Load and validate optional narrative definitions without changing game state.

The returned indexes are fresh per call. Runtime scheduling, progress, dialogue,
and reward actions are handled by their game layers; loading never runs an action.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from .narrative import DAY_NPCS, QUEST_IDS, RIPPLE_BY_QUEST

CONTENT_PATH = Path(__file__).with_name("assets") / "narrative_v1.json"
CONTENT_V2_PATH = Path(__file__).with_name("assets") / "content_v2"
CONTENT_V2_FILES = ("species.json", "baits.json", "boats.json", "lakes.json",
                    "pantry.json", "dishes.json", "calendar.json", "bot.json", "legendaries.json",
                    "npcs.json", "quests.json", "ripples.json", "keepsakes.json")
BOOK_CONTENT_PATH = CONTENT_V2_PATH / "book.json"
BAIT_BY_ID = LAKES = LINE_TIERS = SPECIES_BY_ID = ZONE_ORDER = None
_GAMEPLAY_REFS_LOADED = False


def _load_gameplay_refs():
    global BAIT_BY_ID, LAKES, LINE_TIERS, SPECIES_BY_ID, ZONE_ORDER, _GAMEPLAY_REFS_LOADED
    if _GAMEPLAY_REFS_LOADED:
        return
    try:
        from .data import BAIT_BY_ID as bait_by_id, LINE_TIERS as line_tiers
        from .data import SPECIES_BY_ID as species_by_id, ZONE_ORDER as zone_order
        from .lakes import LAKES as lakes
    except ValueError:
        # Keep v1 diagnostics available when the independent v2 data is broken.
        # The command-line validator reports the v2 error separately.
        _set_fallback_gameplay_refs()
        return

    BAIT_BY_ID = bait_by_id
    LAKES = lakes
    LINE_TIERS = line_tiers
    SPECIES_BY_ID = species_by_id
    ZONE_ORDER = zone_order
    _GAMEPLAY_REFS_LOADED = True


def _is_finite(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
NPC_IDS = {"grandmother_whiskers", "doc_barnaby", "master_cinder"}.union(
    *(set(pool) for pool in DAY_NPCS.values()))
WAYPOINTS = {
    "cedar:docs_marina_dock": "cedar:open",
    "cedar:trinidad_cove": "cedar:deep",
    "cedar:lonely_star_deep": "cedar:deep",
}
STATUSES = {"available", "active", "ready", "completed"}
# Per-type fields are closed so misspelled conditions cannot be silently ignored.
LINE_FIELDS = {"zone_id", "tier_id", "hook_count", "bait_id", "set_after_acceptance"}
OBJECTIVE_FIELDS = {
    "line_scout": LINE_FIELDS | {"scout_range_lt_m"},
    "line_check": LINE_FIELDS | {"active_soak_game_minutes"},
    "line_scout_check": LINE_FIELDS | {
        "scout_range_lt_m", "active_soak_game_minutes", "scout_before_check"},
    "anchor_idle": {"zone_id", "continuous_game_minutes", "reset_on_interruption"},
    "scout_report": {"zone_id", "report_delivered", "exact_depth_required"},
    "fish_livewell": {"zone_id", "bait_id", "species_id", "entry_window",
                      "window_field", "set_after_acceptance", "consume_fish"},
    "travel_distance": {"zone_id", "distance_m", "player_controlled", "propulsion",
                        "count_tow", "measurement"},
    "visit_zones": {"zone_ids", "ordered"},
    "visit_sequence": {"zone_ids", "ordered", "movement_cause", "player_controlled"},
}


class ContentError(ValueError):
    """An authored file is invalid; every message includes source and ID context."""


class _DuplicateJSONKeyError(ContentError):
    def __init__(self, key):
        self.key = key
        super().__init__(f"duplicate JSON key {key!r}")


@dataclass
class NarrativeContent:
    npcs: dict[str, dict]
    quests: dict[str, dict]
    rewards: dict[str, dict]
    dialogue: dict[str, dict]
    # V1-31: every roster cat (name, lake, role, quest chain, greetings, letters). `npcs`
    # stays the V3 cast; V1.0 quests join `quests` and `dialogue` with a `kind`.
    cats: dict[str, dict] = field(default_factory=dict)
    ripples: dict[str, dict] = field(default_factory=dict)    # V1.0 Ripples by id (V1-32)
    keepsakes: dict[str, dict] = field(default_factory=dict)  # keepsakes by id (V1-32)
    scenes: dict[str, dict] = field(default_factory=dict)     # story scenes by id (V1-34)

    def name(self, npc_id: str) -> str:
        row = self.cats.get(npc_id) or self.npcs.get(npc_id) or {}
        return row.get("name", npc_id)


@dataclass
class GameplayContent:
    """Validated v2 gameplay definitions indexed by their stable IDs."""

    species: dict[str, dict]
    baits: dict[str, dict]
    boats: dict[str, dict]
    lakes: dict[str, dict]
    zones: dict[str, dict]
    pantry: dict[str, dict]
    dishes: dict[str, dict]
    legendaries: dict[str, dict]
    roster: dict[str, dict]
    places: dict[str, dict] = field(default_factory=dict)      # "<lake>:<id>" area or waypoint (V1-31)
    quests: dict[str, dict] = field(default_factory=dict)      # quests.json rows (V1-31)
    quest_cats: dict[str, dict] = field(default_factory=dict)  # greetings and letters by cat (V1-31)
    extends: dict[str, dict] = field(default_factory=dict)     # recopied V3 lines (V1-32)
    ripples: dict[str, dict] = field(default_factory=dict)     # ripples.json (V1-32)
    keepsakes: dict[str, dict] = field(default_factory=dict)   # keepsakes.json (V1-32)
    scenes: dict[str, dict] = field(default_factory=dict)      # quests.json story scenes (V1-34)


@dataclass(frozen=True)
class Rumor:
    text: str
    teller: str
    folk_name: str = ""


@dataclass(frozen=True)
class LegendaryStory:
    story: str
    teller: str


@dataclass
class BookContent:
    rumors: dict[str, Rumor]
    legendaries: dict[str, LegendaryStory]


class _Validator:
    def __init__(self, source):
        self.source = str(source)
        self.errors = []
        self.ids = set()

    def error(self, where, message):
        self.errors.append(f"{self.source}:{where}: {message}")

    def shape(self, value, where, required, optional=()):
        if not isinstance(value, dict):
            self.error(where, "expected an object")
            return False
        for key in sorted(set(required) - value.keys()):
            self.error(where, f"missing required field {key!r}")
        for key in sorted(value.keys() - set(required) - set(optional)):
            self.error(where, f"unknown field {key!r}")
        return True

    def text(self, value, where):
        if not isinstance(value, str) or not value.strip():
            self.error(where, "expected non-empty text")
            return False
        return True

    def member(self, value, allowed, where):
        if not isinstance(value, str) or value not in allowed:
            self.error(where, f"unknown reference/value {value!r}")
            return False
        return True

    def number(self, value, where, *, integer=False):
        valid = type(value) is int if integer else type(value) in (int, float)
        try:
            valid = valid and math.isfinite(value) and value > 0
        except OverflowError:
            valid = False
        if not valid:
            self.error(where, "expected a finite positive " + ("integer" if integer else "number"))

    def literal(self, value, expected, where):
        if type(value) is not type(expected) or value != expected:
            self.error(where, f"expected {expected!r}")

    def identifier(self, value, where):
        if not self.text(value, where):
            return False
        if value in self.ids:
            self.error(where, f"duplicate ID {value!r}")
            return False
        self.ids.add(value)
        return True

    def table(self, raw, name, fields):
        out = {}
        if not isinstance(raw, list):
            self.error(name, "expected a list")
            return out
        for index, row in enumerate(raw):
            where = f"{name}[{index}]"
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                where += f"({row['id']})"
            if not self.shape(row, where, fields):
                continue
            if self.identifier(row.get("id"), where + ".id"):
                out[row["id"]] = row
        return out

    def zone(self, value, lake, where, *, anchor=False):
        allowed = {f"{lid}:{zone}" for lid in LAKES for zone in ZONE_ORDER}
        if anchor:
            allowed.update(WAYPOINTS)
        if self.member(value, allowed, where) and value.split(":")[0] != lake:
            self.error(where, f"location must belong to lake {lake!r}")

    def window(self, value, where):
        if (not isinstance(value, list) or len(value) != 2
                or any(type(n) is not int or not 0 <= n < 1440 for n in value)
                or value[0] == value[1]):
            self.error(where, "expected distinct start/end clock minutes in [0, 1440)")

    def objective(self, obj, qid, lake):
        where = qid + ".objective"
        if not isinstance(obj, dict):
            self.error(where, "expected an object")
            return
        kind = obj.get("type")
        if not self.member(kind, OBJECTIVE_FIELDS, where + ".type"):
            return
        fields = OBJECTIVE_FIELDS[kind] | {"id", "type", "after_acceptance"}
        self.shape(obj, where, fields, {"set_window"} if kind == "line_check" else ())
        oid = obj.get("id")
        if self.identifier(oid, where + ".id") and oid != qid + ":objective":
            self.error(where, "objective ID must use its quest ID prefix")
        self.literal(obj.get("after_acceptance"), True, where + ".after_acceptance")
        if "zone_id" in fields:
            self.zone(obj.get("zone_id"), lake, where + ".zone_id")
        if "zone_ids" in fields:
            zones = obj.get("zone_ids")
            if not isinstance(zones, list) or not zones:
                self.error(where + ".zone_ids", "expected a non-empty zone list")
            else:
                for zone in zones:
                    self.zone(zone, lake, where + ".zone_ids")
                if kind == "visit_zones" and len(set(map(str, zones))) != len(zones):
                    self.error(where + ".zone_ids", "unordered targets must be unique")
        for key in ("bait_id", "species_id", "tier_id"):
            if key in fields:
                allowed = {"bait_id": BAIT_BY_ID, "species_id": SPECIES_BY_ID,
                           "tier_id": LINE_TIERS}[key]
                self.member(obj.get(key), allowed, where + "." + key)
        if "hook_count" in fields:
            hooks = obj.get("hook_count")
            self.number(hooks, where + ".hook_count", integer=True)
            tier = obj.get("tier_id")
            if isinstance(tier, str) and tier in LINE_TIERS and hooks != LINE_TIERS[tier]["hooks"]:
                self.error(where + ".hook_count", "does not match line tier")
        for key in ("scout_range_lt_m", "active_soak_game_minutes",
                    "continuous_game_minutes", "distance_m"):
            if key in fields:
                self.number(obj.get(key), where + "." + key)
        for key in ("set_window", "entry_window"):
            if key in obj:
                self.window(obj[key], where + "." + key)
        literals = {"reset_on_interruption": True, "report_delivered": True,
                    "exact_depth_required": False, "scout_before_check": True,
                    "consume_fish": False, "player_controlled": True,
                    "count_tow": False, "measurement": "in_zone_path",
                    "window_field": "entry_game_minute", "movement_cause": "boat"}
        for key, expected in literals.items():
            if key in fields:
                self.literal(obj.get(key), expected, where + "." + key)
        if "ordered" in fields:
            self.literal(obj.get("ordered"), kind == "visit_sequence", where + ".ordered")
        if "set_after_acceptance" in fields:
            self.literal(obj.get("set_after_acceptance"), kind != "fish_livewell",
                         where + ".set_after_acceptance")
        if "propulsion" in fields:
            self.literal(obj.get("propulsion"), ["motor", "sail", "oar"], where + ".propulsion")


def validate_content(raw, *, source="<content>") -> NarrativeContent:
    """Validate all definitions and links before returning any usable content."""
    _load_gameplay_refs()
    v = _Validator(source)
    if not v.shape(raw, "root", {"schema_version", "sources", "adaptations", "npcs",
                                 "quests", "rewards", "dialogue"}):
        raise ContentError("\n".join(v.errors))
    v.literal(raw.get("schema_version"), 1, "schema_version")
    for key in ("sources", "adaptations"):
        if not isinstance(raw.get(key), list) or not raw[key]:
            v.error(key, "expected a non-empty provenance list")
    for index, item in enumerate(raw.get("sources", []) if isinstance(raw.get("sources"), list) else []):
        where = f"sources[{index}]"
        if v.shape(item, where, {"name", "url"}, {"sha256"}):
            v.text(item.get("name"), where + ".name")
            v.text(item.get("url"), where + ".url")
    for index, item in enumerate(raw.get("adaptations", []) if isinstance(raw.get("adaptations"), list) else []):
        v.text(item, f"adaptations[{index}]")
    npcs = v.table(raw.get("npcs"), "npcs",
                   {"id", "name", "lake_id", "anchor_id", "presence", "quest_id"})
    quests = v.table(raw.get("quests"), "quests",
                     {"id", "title", "giver_id", "lake_id", "prerequisites",
                      "objective", "reward_id", "dialogue"})
    rewards = v.table(raw.get("rewards"), "rewards", {"id", "cash", "ripple_id"})
    # Dialogue shape allows either next or choices; checked separately below.
    dialogue = {}
    nodes = raw.get("dialogue")
    if not isinstance(nodes, list):
        v.error("dialogue", "expected a list")
    else:
        for index, node in enumerate(nodes):
            where = f"dialogue[{index}]"
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                where += f"({node['id']})"
            if v.shape(node, where, {"id", "quest_id", "speaker_id", "text"}, {"next", "choices"}):
                if v.identifier(node.get("id"), where + ".id"):
                    dialogue[node["id"]] = node
    for name, actual, expected in (("npcs", npcs, NPC_IDS), ("quests", quests, set(QUEST_IDS))):
        if set(actual) != expected:
            v.error(name, f"canonical IDs differ; missing={sorted(expected-set(actual))}, unknown={sorted(set(actual)-expected)}")
    for nid, npc in npcs.items():
        v.text(npc.get("name"), nid + ".name")
        lake = npc.get("lake_id")
        v.member(lake, LAKES, nid + ".lake_id")
        v.zone(npc.get("anchor_id"), lake, nid + ".anchor_id", anchor=True)
        expected = ("permanent" if nid in ("grandmother_whiskers", "doc_barnaby")
                    else "night" if nid == "master_cinder" else "day")
        v.literal(npc.get("presence"), expected, nid + ".presence")
        v.member(npc.get("quest_id"), quests, nid + ".quest_id")
    used_rewards = set()
    for qid, quest in quests.items():
        v.text(quest.get("title"), qid + ".title")
        lake = quest.get("lake_id")
        v.member(lake, LAKES, qid + ".lake_id")
        giver = quest.get("giver_id")
        if v.member(giver, npcs, qid + ".giver_id"):
            if npcs[giver].get("quest_id") != qid or npcs[giver].get("lake_id") != lake:
                v.error(qid, "giver/quest/lake references disagree")
        # All twelve are independently available; no quest unlock chain.
        v.literal(quest.get("prerequisites"), [], qid + ".prerequisites")
        v.objective(quest.get("objective"), qid, lake)
        rid = quest.get("reward_id")
        if v.member(rid, rewards, qid + ".reward_id"):
            if rid in used_rewards:
                v.error(qid, "reward is shared by more than one quest")
            used_rewards.add(rid)
            if rewards[rid].get("ripple_id") != RIPPLE_BY_QUEST.get(qid):
                v.error(qid, "reward must match the canonical Ripple (hosts award cash only)")
        entries = quest.get("dialogue")
        if v.shape(entries, qid + ".dialogue", STATUSES):
            for status, node_id in entries.items():
                if v.member(node_id, dialogue, qid + ".dialogue." + status):
                    if dialogue[node_id].get("quest_id") != qid:
                        v.error(qid + ".dialogue." + status, "entry belongs to another quest")
    if used_rewards != set(rewards):
        v.error("rewards", "unreferenced reward definitions")
    for rid, reward in rewards.items():
        v.number(reward.get("cash"), rid + ".cash", integer=True)
        if reward.get("ripple_id") is not None:
            v.member(reward["ripple_id"], set(RIPPLE_BY_QUEST.values()), rid + ".ripple_id")
    edges = {nid: [] for nid in dialogue}
    actions = {qid: [] for qid in quests}
    for nid, node in dialogue.items():
        qid = node.get("quest_id")
        v.text(node.get("text"), nid + ".text")
        v.member(qid, quests, nid + ".quest_id")
        if v.member(node.get("speaker_id"), npcs, nid + ".speaker_id") and isinstance(qid, str) and qid in quests:
            if quests[qid].get("giver_id") != node["speaker_id"]:
                v.error(nid, "speaker is not this quest's giver")
        if ("next" in node) == ("choices" in node):
            v.error(nid, "provide exactly one of next (null closes) or choices")
        targets = []
        if node.get("next") is not None:
            targets.append(node["next"])
        if "choices" in node:
            choices = node["choices"]
            if not isinstance(choices, list) or not choices:
                v.error(nid + ".choices", "expected a non-empty choice list")
            else:
                for index, choice in enumerate(choices):
                    where = f"{nid}.choices[{index}]"
                    if not v.shape(choice, where, {"id", "text", "target", "action"}):
                        continue
                    v.identifier(choice.get("id"), where + ".id")
                    v.text(choice.get("text"), where + ".text")
                    action = choice.get("action")
                    if v.member(action, {"accept", "decline", "turn_in", "close"}, where + ".action"):
                        if isinstance(qid, str) and qid in actions:
                            actions[qid].append(action)
                    targets.append(choice.get("target"))
        for target in targets:
            if v.member(target, dialogue, nid + ".target"):
                if dialogue[target].get("quest_id") != qid:
                    v.error(nid, "dialogue target belongs to another quest")
                else:
                    edges[nid].append(target)
    for qid, quest in quests.items():
        if sorted(actions[qid]) != ["accept", "close", "decline", "turn_in"]:
            v.error(qid, "dialogue must supply one accept, decline, turn_in and close choice")
        roots = quest.get("dialogue")
        if not isinstance(roots, dict):
            continue
        reached = set()
        pending = [n for n in roots.values() if isinstance(n, str) and n in dialogue]
        while pending:
            nid = pending.pop()
            if nid not in reached:
                reached.add(nid)
                pending.extend(edges[nid])
        owned = {nid for nid, node in dialogue.items() if node.get("quest_id") == qid}
        if owned - reached:
            v.error(qid, f"unreachable dialogue nodes {sorted(owned-reached)}")
        # A later dialogue runner must always be able to reach a closing node.
        # Check for cycles iteratively so malformed content cannot exhaust Python's stack.
        done = set()
        for root in owned:
            visiting = set()
            stack = [(root, False)]
            while stack:
                nid, leaving = stack.pop()
                if leaving:
                    visiting.discard(nid)
                    done.add(nid)
                elif nid in visiting:
                    v.error(nid, "dialogue cycle cannot be executed safely")
                    break
                elif nid not in done:
                    visiting.add(nid)
                    stack.append((nid, True))
                    stack.extend((target, False) for target in edges[nid])
        for status, root in roots.items():
            if not isinstance(root, str) or root not in dialogue:
                continue
            pending, seen = [root], set()
            allowed = {"available": {"accept", "decline"}, "ready": {"turn_in", "close"}}.get(status, set())
            while pending:
                nid = pending.pop()
                if nid in seen:
                    continue
                seen.add(nid)
                choices = dialogue[nid].get("choices")
                if isinstance(choices, list):
                    for choice in choices:
                        if isinstance(choice, dict):
                            action = choice.get("action")
                            if not isinstance(action, str) or action not in allowed:
                                v.error(nid, f"action is not valid for {status!r} dialogue")
                pending.extend(edges[nid])
    if v.errors:
        raise ContentError("\n".join(v.errors))
    return NarrativeContent(npcs, quests, rewards, dialogue)


_SPECIES_FOODS = {"none", "panfish", "catfish", "hearty", "bass", "trout", "fillet", "cosmic"}
_SPECIES_TAGS = {"surface", "cold", "shy", "current", "protected"}
_SHINY_PALETTES = {"albino", "golden", "starry", "glow", "ink", "rose"}
# Fish looks name their own colours and anatomy; fishart.py paints and meshes them.
_FISH_FAMILIES = {"catfish", "bass", "sunfish", "trout", "gar", "sucker", "minnow", "pike",
                  "sculpin", "eel", "cosmic", "sturgeon", "salamander", "ray", "whale"}
_FISH_HEAD_SHAPES = {"rounded", "pointed", "flat"}
_FISH_MOUTHS = {"terminal", "inferior", "upturned"}
_FISH_TAILS = {"forked", "rounded", "truncate", "heterocercal", "pointed", "fluke", "flowing"}
_FISH_PATTERNS = {"plain", "spots", "bars", "stripes", "mottled", "vermiculate",
                  "speckled", "haloed", "saddles", "chain", "blotched", "stars"}
_FISH_STYLE_COLORS = {"marks", "fins", "fin_edge", "band", "throat", "parr", "eye", "ear", "ear_edge"}
_FISH_DORSAL_STYLES = {"normal", "sail", "long", "spiny"}
_FISH_PECTORALS = {"normal", "fan"}
_FISH_FEATURES = {"kype", "hump", "scutes", "gills", "legs", "rings", "lure", "halo",
                  "comet", "ribbon", "whiskers", "long_ear", "ocellus", "shoulder_spot"}
# The cat roster's appearance (V1-29): catmesh.py builds and paints these.
_CAT_COATS = {"short", "long", "rex", "hairless"}
_CAT_EARS = {"pointed", "folded", "tufted", "rounded"}
_CAT_TAILS = {"long", "bob", "none", "plume"}
_CAT_PATTERNS = {"solid", "tabby", "mackerel", "calico", "tortoiseshell", "tuxedo", "point", "spotted", "bicolor"}
_CAT_ATTIRE = {"shawl", "spectacles", "oilskin", "cap", "parka", "vest", "goggles", "life_jacket",
               "bandana", "sweater", "lantern", "scarf"}
_CAT_POSE_PROPS = {"sit_fish": {"rod"}, "nap_curl": {"none"}, "wave": {"none"}, "helm": {"none"},
                   "craft": {"book", "brush", "whittle", "mug", "tablet"}}
_HANDCRAFTED_BOATS = {"jon", "rowboat", "sail", "pontoon"}
_ROUND_ROBIN_DAYS = 3  # every encounter appears at least once in any three game days
# V1-31: named story and fishing places in lakes.json (06 §5), by lake and kind.
NAMED_PLACES = {
    "briar": {"landing_edge": "area", "reed_edge_1": "waypoint", "reed_edge_2": "waypoint",
              "reed_edge_3": "waypoint"},
    "cedar": {"marked_pool": "area", **{f"lamp_buoy_{i}": "waypoint" for i in (1, 2, 3)},
              **{f"drift_buoy_{i}": "waypoint" for i in (1, 2, 3)},
              **{f"practice_buoy_{i}": "waypoint" for i in (1, 2, 3, 4)}},
    "flathead": {},
    "crater": {**{f"safe_cove_{i}": "area" for i in (1, 2, 3)}, "survey_marker": "waypoint"},
    "nebula": {"calm_reflection": "area"},
}
# V1-31 quests (02 §12.3). Fields are closed per type, so a misspelt condition is an error.
QUEST_KINDS = {"host", "a", "b", "story"}
# V1-34 scene ids follow the script (05 §1–3): pro_01–pro_06 (and a branch, pro_05b), the
# chapter scenes story_c<n>_<name>, and the ending end_01–end_03.
SCENE_ID = r"pro_\d\d[a-z]?|story_c[1-5]_[a-z]+|end_\d\d"
SCENE_KNOTS = {"square", "bow", "sailors_hitch"}  # bot.json's canonical knots; a choice may tie one
LINE_STEP_FIELDS = {"zone_id", "area_id", "tier_id", "min_tier", "hook_count", "bait_id", "set_window",
                    "in_cold_band"}
STEP_FIELDS = {
    # Bot's 140 m launch range and line_scout_check's report-before-check are the types' own rules.
    "line_set": LINE_STEP_FIELDS,
    "line_scout": LINE_STEP_FIELDS,
    "line_check": LINE_STEP_FIELDS | {"active_soak_game_minutes"},
    "line_scout_check": LINE_STEP_FIELDS | {"active_soak_game_minutes"},
    "anchor_idle": {"zone_id", "continuous_game_minutes"},
    "scout_report": {"zone_id", "waypoint_ids", "lake_id", "windows"},
    "fish_livewell": {"zone_id", "bait_id", "species_id", "entry_window"},
    "travel_distance": {"zone_id", "distance_m", "propulsion"},
    "visit_zones": {"zone_ids", "waypoint_ids", "windows"},
    "visit_sequence": {"zone_ids", "waypoint_ids", "windows"},
    "catch_species": {"species_id", "species_ids", "group", "tag", "any", "count", "distinct", "min_lb",
                      "zone_id", "area_id", "lake_id", "time_band", "bait_id", "in_cold_band"},
    "book_stage": {"species_ids", "lake_id", "stage", "count"},
    "cook_dish": {"dish_id", "any"},
    "catnap": {"zone_id"},
    "tool_use": {"tool_id", "zone_id", "lake_id", "shell_id"},
    "wait_weather": {"weather", "then_weather", "zone_id", "zone_ids", "lake_id", "area_ids", "minutes"},
    "settle": {"zone_id", "cues"},
    "talk_to": {"npc_id", "distinct_days"},
    "attend_event": {"lake_id", "event"},
}
MAX_QUEST_STEPS = 4
MAX_STORY_PARTS = 5
LINE_TIER_ORDER = ("std", "prem", "heavy")
_TIER_HOOKS = {"std": 12, "prem": 18, "heavy": 24}  # mirrors data.LINE_TIERS
TIME_BANDS = {"dawn", "day", "dusk", "night"}  # data.band_of
# Mirror weather._WEATHER and book.BOOK_STAGES, which import this module; tests check both.
WEATHER_STATES = {"clear", "fair", "overcast", "drizzle", "mist", "snow_mist", "fog", "aurora"}
BOOK_STAGE_ORDER = ("rumor", "identified", "bait_known", "verified", "mastered")
QUEST_EVENTS = {"cookout"}
QUEST_LINE_STAGES = ("offer", "accept", "decline", "progress", "ready", "ready_wait", "done", "return")
# A V3 quest's nine nodes (docs/narrative/CONTENT.md), which an `extends` row may recopy (V1-32).
V3_LINE_STAGES = ("greeting", "offer", "accept", "decline", "progress", "ready", "ready_wait", "completion",
                  "return")
QUEST_CHOICE_LABELS = ("accept_choice", "decline_choice", "turn_in_choice", "later_choice")
LINE_PLACEHOLDERS = {"BotName", "Skipper", "lake", "fish", "depth_ft", "zone"}
GREETING_STATES = ({"stranger", "acquaintance", "friend", "first", "day", "cookout"}
                   | {f"after_ch{n}" for n in range(1, 6)} | {f"weather:{w}" for w in WEATHER_STATES})
UNLOCK_KINDS = {"travel", "chart", "area", "shop"}
REWARD_FIELDS = {"cash", "ripple_id", "keepsake_id", "recipes", "dish_cards", "items", "shells", "unlocks", "tools"}
_V2_RIPPLES = {f"ripple_{n}" for n in range(11, 45)}
_QUEST_REFERENCE_FILES = {"species.json", "baits.json", "lakes.json", "pantry.json", "dishes.json", "bot.json",
                          "legendaries.json", "npcs.json", "ripples.json", "keepsakes.json"}
_BUBBLE_CHARS = 140
# Mirrors data.PAINT, which cannot be imported while data.py is still validating.
_BOAT_PAINT_IDS = {"hull": {"aluminum", "green", "olive", "carolina", "red", "black", "sand", "white"},
                   "deck": {"aluminum", "wood", "carpet"}, "motor": {"black", "red", "white", "green"}}
_BOAT_TRAITS = {
    "shallow", "silent", "hammock", "wind_steady", "trophy_rail", "glow",
    "galley", "ice_hull",
}
_BOAT_FAMILIES = {"pioneer", "rowed", "jon", "utility", "runabout", "sail_trawler", "pontoon", "cosmic"}
_BOAT_POWERS = {"paddle", "oars", "tiller", "console", "inboard", "sail", "starlight"}
# Powers whose speed is the table's top speed rather than motor upgrades or sail.
_FIXED_SPEED_POWERS = {"paddle", "oars", "console", "inboard", "starlight"}
_SHALLOW_DRAFT = 0.32  # draft + 0.08 clearance reaches 0.4 m water (02 §9)

# These IDs are persisted in saves and must remain loadable when content grows.
# New IDs may be added; existing IDs cannot be renamed or removed.
_SAVE_REFERENCED_IDS = {
    "species": frozenset({
        "bluegill", "bullhead", "crappie", "carp", "drum", "channel", "blue",
        "flathead", "largemouth", "smallmouth", "gar", "buffalo", "white_crappie",
        "redear", "green_sunfish", "warmouth", "redbreast", "longear", "spotted_bass",
        "white_bass", "yellow_bass", "hybrid_striper", "striped_bass", "bowfin",
        "spotted_gar", "shortnose_gar", "alligator_gar", "black_bullhead",
        "brown_bullhead", "blue_sucker", "bigmouth_buffalo", "black_buffalo",
        "golden_shiner", "gizzard_shad", "threadfin_shad", "chain_pickerel",
    }),
    "baits": frozenset({"worm", "liver", "shad", "minnow", "craw"}),
    "boats": frozenset({"jon", "rowboat", "sail", "pontoon"}),
    "lakes": frozenset({"briar", "cedar", "flathead", "crater", "nebula"}),
    "zones": frozenset({
        "landing", "inlet", "flats", "lilies", "cypress", "rocks", "deep", "open", "shore",
        "reeds", "springs", "current",
    }),
}
_BASELINE_CEDAR_EXCLUSIONS = frozenset({
    "smallmouth", "striped_bass", "brown_bullhead", "blue_sucker", "black_buffalo",
    "chain_pickerel",
})
_FALLBACK_FISHING_ZONE_ORDER = (
    "landing", "inlet", "flats", "lilies", "cypress", "rocks", "deep", "open",
    "reeds", "springs", "current",
)
_BASELINE_LAKE_MEMBERSHIPS = {
    species_id: frozenset({"briar"} | (set() if species_id in _BASELINE_CEDAR_EXCLUSIONS else {"cedar"}))
    for species_id in _SAVE_REFERENCED_IDS["species"]
}


def _set_fallback_gameplay_refs():
    """Use stable baseline IDs so v1 can still report its errors when v2 is invalid."""
    global BAIT_BY_ID, LAKES, LINE_TIERS, SPECIES_BY_ID, ZONE_ORDER, _GAMEPLAY_REFS_LOADED
    BAIT_BY_ID = {item_id: None for item_id in _SAVE_REFERENCED_IDS["baits"]}
    LAKES = {item_id: None for item_id in _SAVE_REFERENCED_IDS["lakes"]}
    LINE_TIERS = {
        "std": {"hooks": 12},
        "prem": {"hooks": 18},
        "heavy": {"hooks": 24},
    }
    SPECIES_BY_ID = {item_id: None for item_id in _SAVE_REFERENCED_IDS["species"]}
    ZONE_ORDER = _FALLBACK_FISHING_ZONE_ORDER
    _GAMEPLAY_REFS_LOADED = True


@dataclass
class _QuestRefs:
    """The validated ids a quest row may reference."""
    lakes: dict        # lake -> its zone ids
    places: dict       # "<lake>:<id>" -> ("area" | "waypoint", row)
    species: dict
    legendaries: dict
    baits: dict
    dishes: dict
    pantry: dict
    shells: dict
    tools: dict
    roster: dict
    ripples: dict = field(default_factory=dict)
    keepsakes: dict = field(default_factory=dict)


class _ContentV2Validator:
    """Collect schema, value, reference, and roster errors across all v2 files."""

    def __init__(self, unavailable_files=()):
        self.errors: list[str] = []
        self.unavailable_files = set(unavailable_files)
        self.table_rows = {}

    def error(self, filename, where, message):
        self.errors.append(f"{filename}:{where}: {message}")

    def root(self, docs, filename, required, optional=()):
        if filename in self.unavailable_files:
            return {}
        raw = docs.get(filename)
        if not isinstance(raw, dict):
            self.error(filename, "root", "expected a JSON object")
            return {}
        for key in sorted(set(required) - raw.keys()):
            self.error(filename, "root", f"missing required field {key!r}")
        for key in sorted(raw.keys() - set(required) - set(optional)):
            self.error(filename, "root", f"unknown field {key!r}")
        if type(raw.get("schema_version")) is not int or raw.get("schema_version") != 2:
            self.error(filename, "schema_version", "expected 2")
        return raw

    def text(self, filename, where, value):
        if not isinstance(value, str) or not value.strip():
            self.error(filename, where, "expected non-empty text")

    def number(self, filename, where, value, *, minimum=None, maximum=None, integer=False):
        valid = type(value) is int if integer else type(value) in (int, float)
        try:
            valid = valid and math.isfinite(value)
        except OverflowError:
            valid = False
        if valid and minimum is not None:
            valid = value >= minimum
        if valid and maximum is not None:
            valid = value <= maximum
        if not valid:
            bounds = []
            if minimum is not None:
                bounds.append(f">= {minimum}")
            if maximum is not None:
                bounds.append(f"<= {maximum}")
            description = "finite " + ("integer" if integer else "number")
            if bounds:
                description += " " + " and ".join(bounds)
            self.error(filename, where, f"expected {description}")
        return valid

    def enum(self, filename, where, value, allowed):
        if not isinstance(value, str) or value not in allowed:
            self.error(filename, where, f"unknown value/reference {value!r}")
            return False
        return True

    def table(self, docs, filename, group, required, optional=(), *, id_field="id"):
        validation_rows = []
        self.table_rows[(filename, group)] = validation_rows
        if filename in self.unavailable_files:
            return {}
        raw = docs.get(filename)
        raw_rows = raw.get(group) if isinstance(raw, dict) else None
        if not isinstance(raw_rows, list):
            self.error(filename, group, "expected a list")
            return {}
        indexed = {}
        for index, row in enumerate(raw_rows):
            where = f"{group}[{index}]"
            if isinstance(row, dict) and isinstance(row.get(id_field), str):
                where += f"({row[id_field]})"
            if not isinstance(row, dict):
                self.error(filename, where, "expected an object")
                continue
            validation_rows.append((row.get(id_field), row, where))
            for key in sorted(set(required) - row.keys()):
                self.error(filename, where, f"missing required field {key!r}")
            for key in sorted(row.keys() - set(required) - set(optional)):
                self.error(filename, where, f"unknown field {key!r}")
            item_id = row.get(id_field)
            if not isinstance(item_id, str) or not item_id.strip():
                self.error(filename, where + "." + id_field, "expected non-empty text")
            elif item_id in indexed:
                self.error(filename, where + "." + id_field, f"duplicate ID {item_id!r}")
            else:
                indexed[item_id] = row
        return indexed

    def rows(self, filename, group):
        if filename in self.unavailable_files:
            return ()
        return self.table_rows.get((filename, group), ())

    def require_saved_ids(self, filename, group, indexed):
        if filename in self.unavailable_files:
            return
        for item_id in sorted(_SAVE_REFERENCED_IDS.get(group, ()) - indexed.keys()):
            self.error(filename, f"{group}({item_id})", "missing save-referenced ID")

    def id_list(self, filename, where, value, allowed):
        if not isinstance(value, list):
            self.error(filename, where, "expected a list")
            return []
        seen = set()
        valid = []
        for index, item in enumerate(value):
            item_where = f"{where}[{index}]"
            if not isinstance(item, str):
                self.error(filename, item_where, f"expected a string ID, got {item!r}")
                continue
            if item in seen:
                self.error(filename, item_where, f"duplicate ID {item!r}")
                continue
            seen.add(item)
            if allowed is not None and item not in allowed:
                self.error(filename, item_where, f"unknown reference {item!r}")
            elif allowed is None or item in allowed:
                valid.append(item)
        return valid

    def multiplier_map(self, filename, where, value, allowed, *, maximum=None):
        if not isinstance(value, dict):
            self.error(filename, where, "expected an object of IDs to multipliers")
            return {}
        for item_id, multiplier in value.items():
            item_where = where + "." + str(item_id)
            if allowed is not None and item_id not in allowed:
                self.error(filename, item_where, f"unknown reference {item_id!r}")
            self.number(filename, item_where, multiplier, minimum=0, maximum=maximum)
        return value

    def environment(self, filename, where, value, lake):
        """Bound allocations and reject malformed procedural map parameters."""
        keys = {"kind", "seed", "bounds", "grid", "outline", "slip_angle", "snow_line",
                "tree_count", "sky_zenith", "sky_horizon", "water_shallow", "water_deep",
                "zones", "depths", "peaks", "ambience"}
        if not isinstance(value, dict):
            self.error(filename, where, "expected an environment object")
            return
        for key in sorted(keys - value.keys()):
            self.error(filename, where, f"missing required field {key!r}")
        nebula_keys = {"water_mid", "lanes", "drifts", "bands"}
        for key in sorted(value.keys() - keys - {"rim", "islands", "thermal"} - nebula_keys):
            self.error(filename, where, f"unknown field {key!r}")
        self.enum(filename, where + ".kind", value.get("kind"), {"alpine", "caldera", "nebula"})
        if lake.get("placeholder") is not False:
            self.error(filename, where, "a generated environment cannot be a placeholder")
        self.number(filename, where + ".seed", value.get("seed"), integer=True, minimum=0, maximum=2**32-1)
        self.number(filename, where + ".tree_count", value.get("tree_count"), integer=True, minimum=1, maximum=800)
        self.number(filename, where + ".slip_angle", value.get("slip_angle"), minimum=0, maximum=math.tau)
        self.number(filename, where + ".snow_line", value.get("snow_line"), minimum=20, maximum=500)

        def vector(key, count, lo, hi, integer=False):
            row = value.get(key)
            if not isinstance(row, list) or len(row) != count:
                self.error(filename, where + "." + key, f"expected {count} numbers")
                return False
            return all([self.number(filename, f"{where}.{key}[{i}]", n,
                                    minimum=lo, maximum=hi, integer=integer) for i, n in enumerate(row)])

        if vector("bounds", 4, -2400, 2400):
            x0, z0, x1, z1 = value["bounds"]
            if x1-x0 < 500 or z1-z0 < 500:
                self.error(filename, where + ".bounds", "expected increasing bounds spanning at least 500 metres")
        vector("grid", 2, 64, 1024, True)
        for key in ("sky_zenith", "sky_horizon", "water_shallow", "water_deep"):
            vector(key, 3, 0, 1)
        outline = value.get("outline")
        valid_outline = isinstance(outline, list) and 5 <= len(outline) <= 65
        if valid_outline:
            valid_outline = all(isinstance(row, list) and len(row) == 2
                                and all(type(n) in (int, float) and _is_finite(n) for n in row)
                                and 0 <= row[0] <= 360 and 100 <= row[1] <= 1500 for row in outline)
        if (not valid_outline or outline[0][0] != 0 or outline[-1][0] != 360
                or outline[0][1] != outline[-1][1]
                or any(a[0] >= b[0] for a, b in zip(outline, outline[1:]))):
            self.error(filename, where + ".outline", "expected ordered closed polar points from 0 to 360 degrees")
        elif isinstance(value.get("bounds"), list) and len(value["bounds"]) == 4:
            bounds = value["bounds"]
            if all(type(n) in (int, float) and _is_finite(n) for n in bounds):
                radius = max(row[1] for row in outline)
                if not (bounds[0] < -radius and bounds[1] < -radius and bounds[2] > radius and bounds[3] > radius):
                    self.error(filename, where + ".bounds", "must contain the complete polar shoreline")
        zones = value.get("zones")
        zone_ids = []
        if not isinstance(zones, list) or not 1 <= len(zones) <= 9:
            self.error(filename, where + ".zones", "expected 1 to 9 habitat circles")
        else:
            for i, row in enumerate(zones):
                at = f"{where}.zones[{i}]"
                if not isinstance(row, list) or len(row) != 4:
                    self.error(filename, at, "expected zone ID, x, z, radius")
                    continue
                if self.enum(filename, at, row[0], lake.get("zone_ids") if isinstance(lake.get("zone_ids"), list) else []):
                    if row[0] in zone_ids:
                        self.error(filename, at, "duplicate habitat circle")
                    zone_ids.append(row[0])
                for j, n in enumerate(row[1:]):
                    self.number(filename, at, n, minimum=1 if j == 2 else -1500, maximum=1500)
        depths = value.get("depths")
        if not isinstance(depths, dict) or set(depths) != set(zone_ids):
            self.error(filename, where + ".depths", "expected a depth profile for every habitat circle")
        if isinstance(depths, dict):
            for zone, row in depths.items():
                if (not isinstance(row, list) or len(row) != 2
                        or not all(type(n) in (int, float) and _is_finite(n) for n in row)
                        or not .9 <= row[0] < row[1] <= 100):
                    self.error(filename, where + ".depths." + str(zone), "expected 0.9 <= minimum < maximum <= 100 metres")
        peaks = value.get("peaks")
        if not isinstance(peaks, list) or not 1 <= len(peaks) <= 12:
            self.error(filename, where + ".peaks", "expected 1 to 12 bounded ridges")
        else:
            for i, row in enumerate(peaks):
                if (not isinstance(row, list) or len(row) != 4
                        or not all(type(n) in (int, float) and _is_finite(n) for n in row)
                        or not all(-2400 <= n <= 2400 for n in row[:2])
                        or not 20 <= row[2] <= 400 or not 50 <= row[3] <= 500):
                    self.error(filename, f"{where}.peaks[{i}]", "expected x, z, height 20..400, width 50..500")
        hooks = {"caldera": {"caldera_wind"}, "nebula": {"star_twinkle", "nebula_hum"}}.get(
            value.get("kind"), {"loon", "larch_wind"})
        ambience = self.id_list(filename, where + ".ambience", value.get("ambience"), hooks)
        if set(ambience) != hooks:
            self.error(filename, where + ".ambience", "environment requires its declared ambience hooks")
        if value.get("kind") == "caldera":
            for key in ("rim", "islands", "thermal"):
                if key not in value:
                    self.error(filename, where + "." + key, "required for a caldera environment")
        if value.get("kind") == "nebula":
            for key in sorted(nebula_keys - value.keys()):
                self.error(filename, where + "." + key, "required for a nebula environment")
        elif value.keys() & nebula_keys:
            self.error(filename, where, "lanes, drifts, bands and water_mid belong to a nebula environment")
        if "water_mid" in value:
            vector("water_mid", 3, 0, 1)
        if "lanes" in value:
            self.nebula_lanes(filename, where + ".lanes", value["lanes"], value.get("bounds"))
        if "drifts" in value:
            drifts = value["drifts"]
            if not isinstance(drifts, list) or not 1 <= len(drifts) <= 12:
                self.error(filename, where + ".drifts", "expected 1 to 12 floating lily drifts")
            else:
                for i, row in enumerate(drifts):
                    if (not isinstance(row, list) or len(row) != 4
                            or not all(type(n) in (int, float) and _is_finite(n) for n in row)
                            or not all(-1200 <= n <= 1200 for n in row[:2])
                            or not all(8 <= n <= 40 for n in row[2:])):
                        self.error(filename, f"{where}.drifts[{i}]", "expected x, z and radii 8..40 metres")
        if "bands" in value:
            bands = value["bands"]
            names = {"rising", "bright", "fading", "deep"}
            if not isinstance(bands, dict) or set(bands) != names:
                self.error(filename, where + ".bands", "expected rising, bright, fading and deep palettes")
            else:
                for name in sorted(names):
                    band, at = bands[name], f"{where}.bands.{name}"
                    if not isinstance(band, dict) or set(band) != {"zenith", "horizon", "stars"}:
                        self.error(filename, at, "expected zenith, horizon and stars")
                        continue
                    for key in ("zenith", "horizon"):
                        row = band[key]
                        if not isinstance(row, list) or len(row) != 3:
                            self.error(filename, f"{at}.{key}", "expected 3 numbers")
                            continue
                        for i, n in enumerate(row):
                            self.number(filename, f"{at}.{key}[{i}]", n, minimum=0, maximum=1)
                    self.number(filename, at + ".stars", band["stars"], minimum=0, maximum=1)
        if "rim" in value:
            vector("rim", 2, 20, 200)
        if "islands" in value:
            islands = value["islands"]
            if not isinstance(islands, list) or not 1 <= len(islands) <= 4:
                self.error(filename, where + ".islands", "expected 1 to 4 bounded cinder islands")
            else:
                for i, row in enumerate(islands):
                    if (not isinstance(row, list) or len(row) != 5
                            or not all(type(n) in (int, float) and _is_finite(n) for n in row)
                            or not all(-1200 <= n <= 1200 for n in row[:2])
                            or not all(20 <= n <= 200 for n in row[2:])):
                        self.error(filename, f"{where}.islands[{i}]", "expected x, z, radii and height 20..200")
                    elif valid_outline and math.hypot(*row[:2])+max(row[2:4])+20 >= min(p[1] for p in outline):
                        self.error(filename, f"{where}.islands[{i}]", "island must leave a navigable outer channel")
        if "thermal" in value:
            thermal = value["thermal"]
            if not isinstance(thermal, list) or not 1 <= len(thermal) <= 4:
                self.error(filename, where + ".thermal", "expected 1 to 4 thermal vents")
            else:
                for i, row in enumerate(thermal):
                    if (not isinstance(row, list) or len(row) != 2
                            or not all(type(n) in (int, float) and _is_finite(n) and -1200 <= n <= 1200 for n in row)):
                        self.error(filename, f"{where}.thermal[{i}]", "expected finite x, z coordinates")

    def fish_look(self, filename, where, look):
        """The look schema shared by species and legendaries.

        Every look names its own back, flank and belly `colors` and may add
        markings, fin styles and signature features.
        """
        if not isinstance(look, dict):
            self.error(filename, where, "expected an object")
            return
        required = {"family", "length_depth_ratio", "body_depth", "head_shape", "snout",
                    "mouth", "dorsal_count", "adipose", "tail_shape", "barbels",
                    "scale_pattern", "colors"}
        optional = _FISH_STYLE_COLORS | {"mark_scale", "dorsal_style", "pectoral", "features", "glow"}
        for key in sorted(required - look.keys()):
            self.error(filename, where, f"missing required field {key!r}")
        for key in sorted(look.keys() - required - optional):
            self.error(filename, where, f"unknown field {key!r}")
        at = where + "."
        self.enum(filename, at + "family", look.get("family"), _FISH_FAMILIES)
        self.number(filename, at + "length_depth_ratio", look.get("length_depth_ratio"), minimum=1.5, maximum=8.0)
        self.number(filename, at + "body_depth", look.get("body_depth"), minimum=0.5, maximum=1.5)
        self.enum(filename, at + "head_shape", look.get("head_shape"), _FISH_HEAD_SHAPES)
        self.number(filename, at + "snout", look.get("snout"), minimum=0.0, maximum=0.75)
        self.enum(filename, at + "mouth", look.get("mouth"), _FISH_MOUTHS)
        self.number(filename, at + "dorsal_count", look.get("dorsal_count"), integer=True, minimum=0, maximum=2)
        if type(look.get("adipose")) is not bool:
            self.error(filename, at + "adipose", "expected a boolean")
        self.enum(filename, at + "tail_shape", look.get("tail_shape"), _FISH_TAILS)
        self.number(filename, at + "barbels", look.get("barbels"), integer=True, minimum=0, maximum=6)
        self.enum(filename, at + "scale_pattern", look.get("scale_pattern"), _FISH_PATTERNS)

        def colour(key, value):
            if not isinstance(value, list) or len(value) != 3:
                self.error(filename, at + key, "expected an RGB triple")
                return
            for i, n in enumerate(value):
                self.number(filename, f"{at}{key}[{i}]", n, minimum=0, maximum=1)

        colors = look.get("colors")
        if not isinstance(colors, dict) or set(colors) != {"top", "side", "belly"}:
            self.error(filename, at + "colors", "expected top, side and belly colours")
        else:
            for key in ("top", "side", "belly"):
                colour("colors." + key, colors[key])
        for key in sorted(_FISH_STYLE_COLORS & look.keys()):
            colour(key, look[key])
        if "mark_scale" in look:
            self.number(filename, at + "mark_scale", look["mark_scale"], minimum=0.4, maximum=3.0)
        if "glow" in look:
            self.number(filename, at + "glow", look["glow"], minimum=0, maximum=1)
        if "dorsal_style" in look:
            self.enum(filename, at + "dorsal_style", look["dorsal_style"], _FISH_DORSAL_STYLES)
        if "pectoral" in look:
            self.enum(filename, at + "pectoral", look["pectoral"], _FISH_PECTORALS)
        if "features" in look:
            features = look["features"]
            if (not isinstance(features, list) or not all(isinstance(name, str) for name in features)
                    or len(set(features)) != len(features) or not set(features) <= _FISH_FEATURES):
                self.error(filename, at + "features", "expected unique known features")

    def nebula_lanes(self, filename, where, lanes, bounds):
        """Current lanes are continuous chains of circles inside the lake bounds."""
        if not isinstance(lanes, list) or not 1 <= len(lanes) <= 4:
            self.error(filename, where, "expected 1 to 4 current lanes")
            return
        circles = 0
        for i, lane in enumerate(lanes):
            at = f"{where}[{i}]"
            if not isinstance(lane, dict) or set(lane) != {"width", "depths", "points"}:
                self.error(filename, at, "expected width, depths and points")
                continue
            width_ok = self.number(filename, at + ".width", lane["width"], minimum=20, maximum=80)
            depths = lane["depths"]
            if (not isinstance(depths, list) or len(depths) != 2
                    or not all(type(n) in (int, float) and _is_finite(n) for n in depths)
                    or not .9 <= depths[0] < depths[1] <= 100):
                self.error(filename, at + ".depths", "expected 0.9 <= minimum < maximum <= 100 metres")
            points = lane["points"]
            if not isinstance(points, list) or not 2 <= len(points) <= 40:
                self.error(filename, at + ".points", "expected 2 to 40 lane points")
                continue
            circles += len(points)
            inside = isinstance(bounds, list) and len(bounds) == 4 and all(
                type(n) in (int, float) and _is_finite(n) for n in bounds)
            for j, point in enumerate(points):
                if (not isinstance(point, list) or len(point) != 2
                        or not all(type(n) in (int, float) and _is_finite(n) for n in point)):
                    self.error(filename, f"{at}.points[{j}]", "expected finite x, z")
                    break
                if inside and not (bounds[0] < point[0] < bounds[2] and bounds[1] < point[1] < bounds[3]):
                    self.error(filename, f"{at}.points[{j}]", "lane point is outside the lake bounds")
                if j and width_ok and math.dist(point, points[j-1]) > lane["width"]:
                    self.error(filename, f"{at}.points[{j}]", "lane points must overlap into one continuous lane")
        if circles > 48:
            self.error(filename, where, "at most 48 lane points fit the water shader")

    def validate(self, docs):
        species_file, baits_file = "species.json", "baits.json"
        boats_file, lakes_file = "boats.json", "lakes.json"
        species_root = self.root(docs, species_file, {"schema_version", "tier_defaults", "species"})
        baits_root = self.root(docs, baits_file, {"schema_version", "fallback_multiplier", "baits"})
        boats_root = self.root(docs, boats_file, {"schema_version", "boats"})
        lakes_root = self.root(docs, lakes_file, {
            "schema_version", "zone_order", "zone_fallback_multiplier", "zones", "lakes"})

        tiers = self.table(docs, species_file, "tier_defaults", {"tier", "rate", "trophy"}, id_field="tier")
        if species_file not in self.unavailable_files and set(tiers) != {"C", "U", "R", "V"}:
            self.error(species_file, "tier_defaults", "must define exactly C, U, R, and V")
        for tier_id, row, where in self.rows(species_file, "tier_defaults"):
            self.number(species_file, where + ".rate", row.get("rate"), minimum=0)
            self.number(species_file, where + ".trophy", row.get("trophy"), minimum=0, maximum=1)

        species = self.table(docs, species_file, "species", {
            "id", "name", "price", "min_lb", "max_lb", "pref_time", "depth", "blurb",
            "folk_name", "lakes", "food", "tags", "shiny", "look"},
            {"rate", "trophy", "tier", "baits", "zones", "weather_affinities"})
        if species_file not in self.unavailable_files and len(species) != 144:
            self.error(species_file, "species", "expected exactly 144 standard species")
        baits = self.table(docs, baits_file, "baits", {"id", "name", "price", "blurb", "matches"},
                           {"sold_at", "recipe"})
        boats = self.table(docs, boats_file, "boats", {
            "id", "name", "bow", "stern", "half_beam", "draft", "eye_height", "price",
            "lines", "tank", "fuel_burn", "speed_factor", "turn_factor", "acceleration",
            "well_bonus", "sail_speed", "traits", "tier", "family", "power", "blurb"},
            {"top_speed", "sold_at"})

        self.require_saved_ids(species_file, "species", species)
        self.require_saved_ids(baits_file, "baits", baits)
        self.require_saved_ids(boats_file, "boats", boats)

        if lakes_file in self.unavailable_files:
            zone_order = []
        else:
            zone_order = lakes_root.get("zone_order")
            if not isinstance(zone_order, list):
                self.error(lakes_file, "zone_order", "expected a list")
                zone_order = []
            elif any(not isinstance(item, str) for item in zone_order):
                self.error(lakes_file, "zone_order", "expected string zone IDs")
                zone_order = [item for item in zone_order if isinstance(item, str)]
            seen_zone_ids = set()
            for index, zone_id in enumerate(zone_order):
                if zone_id in seen_zone_ids:
                    self.error(lakes_file, f"zone_order[{index}]({zone_id})", f"duplicate zone ID {zone_id!r}")
                seen_zone_ids.add(zone_id)
            self.number(lakes_file, "zone_fallback_multiplier", lakes_root.get("zone_fallback_multiplier"),
                        minimum=0, maximum=1)
        zones = self.table(docs, lakes_file, "zones", {"id", "name", "cedar_name", "fishing", "matches"})
        lakes = self.table(docs, lakes_file, "lakes", {
            "id", "name", "landing", "region", "blurb", "species_count", "species_ids",
            "zone_ids", "zone_labels", "palette", "placeholder", "unlock_chapter",
            "travel_caption", "lake_days"}, {"rate_multipliers", "placeholder_depths", "environment",
                                             "areas", "waypoints"})
        self.require_saved_ids(lakes_file, "zones", zones)
        self.require_saved_ids(lakes_file, "lakes", lakes)
        if lakes_file not in self.unavailable_files and not {"briar", "cedar"}.issubset(lakes):
            self.error(lakes_file, "lakes", "must include the existing briar and cedar lakes")

        species_ids = set(species)
        lake_ids = set(lakes)
        zone_ids = set(zones)
        lake_refs = lake_ids if lakes_file not in self.unavailable_files else None
        species_refs = species_ids if species_file not in self.unavailable_files else None
        for sid, row, where in self.rows(species_file, "species"):
            tags = row.get("tags")
            protected = isinstance(tags, list) and "protected" in tags
            self.text(species_file, where + ".name", row.get("name"))
            self.text(species_file, where + ".blurb", row.get("blurb"))
            self.text(species_file, where + ".folk_name", row.get("folk_name"))
            for key in ("price", "min_lb", "max_lb"):
                self.number(species_file, where + "." + key, row.get(key), minimum=0)
            if (type(row.get("price")) in (int, float) and row.get("price", 0) <= 0
                    and not protected):
                self.error(species_file, where + ".price", "must be greater than zero")
            if (type(row.get("max_lb")) in (int, float) and type(row.get("min_lb")) in (int, float)
                    and row["max_lb"] <= row["min_lb"]):
                self.error(species_file, where + ".max_lb", "must be greater than min_lb")
            tier_defaults = None
            if "tier" in row and self.enum(species_file, where + ".tier", row.get("tier"), tiers):
                tier_defaults = tiers[row["tier"]]
            for key in ("rate", "trophy"):
                if key in row:
                    value = row[key]
                elif tier_defaults is not None and key in tier_defaults:
                    value = tier_defaults[key]
                else:
                    self.error(species_file, where + "." + key,
                               f"missing required field {key!r}; provide it or a valid tier default")
                    continue
                self.number(species_file, where + "." + key, value,
                            minimum=0, maximum=1 if key == "trophy" else None)
                if key == "rate" and type(value) in (int, float) and value <= 0:
                    self.error(species_file, where + ".rate", "must be greater than zero")
            self.enum(species_file, where + ".pref_time", row.get("pref_time"),
                      {"dawn", "day", "dusk", "night", "any"})
            depth = row.get("depth")
            if (not isinstance(depth, list) or len(depth) != 2
                    or any(type(n) not in (int, float) or not _is_finite(n) for n in depth)):
                self.error(species_file, where + ".depth", "expected two finite depth values")
            elif depth[0] < 0 or depth[1] <= depth[0]:
                self.error(species_file, where + ".depth", "expected 0 <= min depth < max depth")
            declared_lakes = self.id_list(species_file, where + ".lakes", row.get("lakes"), lake_refs)
            if not declared_lakes:
                self.error(species_file, where + ".lakes", "species must belong to at least one lake")
            required_lakes = (_BASELINE_LAKE_MEMBERSHIPS.get(sid, frozenset())
                              if isinstance(sid, str) else frozenset())
            for lake_id in sorted(required_lakes - set(declared_lakes)):
                self.error(species_file, where + ".lakes",
                           f"must retain baseline lake membership {lake_id!r}")
            self.enum(species_file, where + ".food", row.get("food"), _SPECIES_FOODS)
            if not isinstance(tags, list):
                self.error(species_file, where + ".tags", "expected a list")
            else:
                if all(isinstance(tag, str) for tag in tags) and len(tags) != len(set(tags)):
                    self.error(species_file, where + ".tags", "tags must be unique")
                for index, tag in enumerate(tags):
                    self.enum(species_file, f"{where}.tags[{index}]", tag, _SPECIES_TAGS)
            self.enum(species_file, where + ".shiny", row.get("shiny"), _SHINY_PALETTES)
            for key, refs in (("baits", baits if baits_file not in self.unavailable_files else None),
                              ("zones", zone_ids if lakes_file not in self.unavailable_files else None)):
                if key not in row:
                    continue
                ids = self.id_list(species_file, where + "." + key, row[key], refs)
                if not ids:
                    self.error(species_file, where + "." + key, "expected at least one preference")
                for index, item_id in enumerate(ids):
                    source = baits.get(item_id) if key == "baits" else zones.get(item_id)
                    if source is not None:
                        match = source.get("matches", {})
                        fallback = baits_root.get("fallback_multiplier") if key == "baits" else lakes_root.get("zone_fallback_multiplier")
                        value = match.get(sid, fallback) if isinstance(match, dict) and isinstance(sid, str) else None
                        expected = 1.0 if index == 0 else .6 if key == "baits" else .7
                        if value != expected:
                            self.error(species_file, where + "." + key,
                                       f"{item_id!r} must have match {expected} for {sid!r}")
                    if key == "zones" and lake_refs is not None:
                        for lid in declared_lakes:
                            available = lakes.get(lid, {}).get("zone_ids", [])
                            if isinstance(available, list) and item_id not in available:
                                self.error(species_file, where + ".zones", f"{item_id!r} has no habitat on {lid!r}")
            if "weather_affinities" in row:
                weather = row["weather_affinities"]
                if not isinstance(weather, dict):
                    self.error(species_file, where + ".weather_affinities", "expected an object")
                else:
                    for condition, value in weather.items():
                        self.enum(species_file, where + ".weather_affinities", condition,
                                  {"clear", "fair", "overcast", "drizzle", "mist", "snow_mist", "fog", "aurora"})
                        self.number(species_file, where + ".weather_affinities." + str(condition),
                                    value, minimum=1, maximum=2)
            self.fish_look(species_file, where + ".look", row.get("look"))

        if baits_file not in self.unavailable_files:
            self.number(baits_file, "fallback_multiplier", baits_root.get("fallback_multiplier"), minimum=0, maximum=1)
        for bid, row, where in self.rows(baits_file, "baits"):
            self.text(baits_file, where + ".name", row.get("name"))
            self.text(baits_file, where + ".blurb", row.get("blurb"))
            self.number(baits_file, where + ".price", row.get("price"), minimum=0)
            if ("recipe" not in row and type(row.get("price")) in (int, float)
                    and row.get("price", 0) <= 0):
                self.error(baits_file, where + ".price", "must be greater than zero")
            self.multiplier_map(baits_file, where + ".matches", row.get("matches"), species_refs, maximum=1)
            if "sold_at" in row:
                self.id_list(baits_file, where + ".sold_at", row["sold_at"],
                             {"all", "briar", "cedar", "flathead", "crater", "nebula"})

        for bid, row, where in self.rows(boats_file, "boats"):
            self.text(boats_file, where + ".name", row.get("name"))
            self.number(boats_file, where + ".lines", row.get("lines"),
                        minimum=3, maximum=8, integer=True)
            for key in ("bow", "stern", "half_beam", "draft", "eye_height", "price", "tank",
                        "fuel_burn", "speed_factor", "turn_factor", "acceleration", "well_bonus", "sail_speed"):
                # A tier-1 well may sit below the 40 lb base; the bonus is then negative.
                minimum = None if key == "stern" else -40 if key == "well_bonus" else 0
                self.number(boats_file, where + "." + key, row.get(key), minimum=minimum)
            self.text(boats_file, where + ".blurb", row.get("blurb"))
            self.number(boats_file, where + ".tier", row.get("tier"), minimum=1, maximum=8, integer=True)
            self.enum(boats_file, where + ".family", row.get("family"), _BOAT_FAMILIES)
            self.enum(boats_file, where + ".power", row.get("power"), _BOAT_POWERS)
            if row.get("power") in _FIXED_SPEED_POWERS or "top_speed" in row:
                self.number(boats_file, where + ".top_speed", row.get("top_speed"), minimum=0.1)
            if "sold_at" in row:
                self.id_list(boats_file, where + ".sold_at", row["sold_at"],
                             {"briar", "cedar", "flathead", "crater", "nebula"})
            if (isinstance(row.get("traits"), list) and "shallow" in row["traits"]
                    and type(row.get("draft")) in (int, float) and row["draft"] > _SHALLOW_DRAFT):
                self.error(boats_file, where + ".draft", f"a shallow boat draws at most {_SHALLOW_DRAFT} m")
            for key in ("speed_factor", "turn_factor", "acceleration"):
                value = row.get(key)
                if type(value) in (int, float) and value <= 0:
                    self.error(boats_file, where + "." + key, "must be greater than zero")
            if (type(row.get("bow")) in (int, float) and type(row.get("stern")) in (int, float)
                    and row["bow"] <= row["stern"]):
                self.error(boats_file, where + ".bow", "must be forward of stern")
            traits = row.get("traits")
            if not isinstance(traits, list):
                self.error(boats_file, where + ".traits", "expected a list")
            else:
                seen_traits = set()
                for index, trait in enumerate(traits):
                    trait_where = f"{where}.traits[{index}]"
                    if isinstance(trait, str) and trait in seen_traits:
                        self.error(boats_file, trait_where, f"duplicate trait {trait!r}")
                    if isinstance(trait, str):
                        seen_traits.add(trait)
                    self.enum(boats_file, trait_where, trait, _BOAT_TRAITS)

        for zid, row, where in self.rows(lakes_file, "zones"):
            self.text(lakes_file, where + ".name", row.get("name"))
            self.text(lakes_file, where + ".cedar_name", row.get("cedar_name"))
            if type(row.get("fishing")) is not bool:
                self.error(lakes_file, where + ".fishing", "expected a boolean")
            self.multiplier_map(lakes_file, where + ".matches", row.get("matches"), species_refs, maximum=1)
        fishing_zones = {zid for zid, row in zones.items() if row.get("fishing") is True}
        if lakes_file not in self.unavailable_files:
            for zone_id in sorted(fishing_zones - set(zone_order)):
                self.error(lakes_file, f"zone_order({zone_id})", "missing fishing zone from zone_order")
            for zone_id in sorted(set(zone_order) - fishing_zones):
                self.error(lakes_file, f"zone_order({zone_id})", "zone order includes an unknown or non-fishing zone")
        places = {}  # "<lake>:<id>" -> ("area" | "waypoint", row), for quest references
        for lid, row, where in self.rows(lakes_file, "lakes"):
            for key in ("name", "landing", "region", "blurb"):
                self.text(lakes_file, where + "." + key, row.get(key))
            listed_ids = self.id_list(lakes_file, where + ".species_ids", row.get("species_ids"), species_refs)
            count = row.get("species_count")
            placeholder = row.get("placeholder")
            if type(placeholder) is not bool:
                self.error(lakes_file, where + ".placeholder", "expected a boolean")
            self.number(lakes_file, where + ".species_count", count, integer=True,
                        minimum=0 if placeholder is True else 1)
            if type(count) is int and count != len(listed_ids):
                self.error(lakes_file, where + ".species_count", f"declares {count}, but lists {len(listed_ids)} species")
            if "environment" in row:
                self.environment(lakes_file, where + ".environment", row["environment"], row)
            if "placeholder_depths" in row:
                depths = row["placeholder_depths"]
                if not isinstance(depths, dict):
                    self.error(lakes_file, where + ".placeholder_depths", "expected an object")
                else:
                    for zone, values in depths.items():
                        zone_ids_for_lake = row.get("zone_ids")
                        self.enum(lakes_file, where + ".placeholder_depths", zone,
                                  zone_ids_for_lake if isinstance(zone_ids_for_lake, list) else [])
                        if (not isinstance(values, list) or len(values) != 2
                                or not all(type(value) in (int, float) and _is_finite(value) for value in values)
                                or not .9 <= values[0] < values[1] <= 100):
                            self.error(lakes_file, where + ".placeholder_depths." + str(zone),
                                       "expected 0.9 <= minimum < maximum <= 100 metres")
            if "rate_multipliers" in row:
                rates = self.multiplier_map(lakes_file, where + ".rate_multipliers",
                                            row.get("rate_multipliers"), species_refs)
                if species_file not in self.unavailable_files:
                    for sid in sorted(species_ids - set(rates)):
                        self.error(lakes_file, f"{where}.rate_multipliers({sid})",
                                   f"missing rate entry for species {sid!r}")
                listed = row.get("species_ids")
                listed_ids = {sid for sid in listed if isinstance(sid, str)} if isinstance(listed, list) else set()
                for sid in species_ids.intersection(rates):
                    rate = rates[sid]
                    if type(rate) in (int, float) and _is_finite(rate) and rate >= 0:
                        if (sid in listed_ids) != (rate > 0):
                            self.error(
                                lakes_file,
                                f"{where}.rate_multipliers({sid})",
                                "must be positive exactly when the species is listed in species_ids",
                            )
            available = self.id_list(lakes_file, where + ".zone_ids", row.get("zone_ids"), fishing_zones)
            if not {"landing", "open"}.issubset(available):
                self.error(lakes_file, where + ".zone_ids", "must include landing and open")
            self.number(lakes_file, where + ".unlock_chapter", row.get("unlock_chapter"),
                        integer=True, minimum=0, maximum=5)
            self.text(lakes_file, where + ".travel_caption", row.get("travel_caption"))
            self.named_places(lakes_file, where, lid, row, places)
            palette = row.get("palette")
            if not isinstance(palette, dict) or set(palette) != {"water", "land"}:
                self.error(lakes_file, where + ".palette", "expected water and land RGB colors")
            else:
                for key, color in palette.items():
                    if not isinstance(color, list) or len(color) != 3:
                        self.error(lakes_file, where + ".palette." + key, "expected three color components")
                    else:
                        for index, value in enumerate(color):
                            self.number(lakes_file, f"{where}.palette.{key}[{index}]", value,
                                        minimum=0, maximum=1)
            days = self.id_list(lakes_file, where + ".lake_days", row.get("lake_days"), None)
            if "calendar.json" not in self.unavailable_files:
                calendar_doc = docs.get("calendar.json")
                authored_days = calendar_doc.get("lake_days", []) if isinstance(calendar_doc, dict) else []
                if not isinstance(authored_days, list):
                    authored_days = []
                expected_days = {d.get("id") for d in authored_days
                                 if isinstance(d, dict) and d.get("lake") == lid
                                 and isinstance(d.get("id"), str)}
                if set(days) != expected_days or len(days) != 2:
                    self.error(lakes_file, where + ".lake_days", "must reference this lake's two calendar specials")
            if "zone_labels" in row:
                labels = row.get("zone_labels")
                if not isinstance(labels, dict):
                    self.error(lakes_file, where + ".zone_labels", "expected an object")
                else:
                    for zone_id, label in labels.items():
                        if zone_id not in zone_ids and lakes_file not in self.unavailable_files:
                            self.error(lakes_file, where + ".zone_labels." + str(zone_id), f"unknown zone {zone_id!r}")
                        self.text(lakes_file, where + ".zone_labels." + str(zone_id), label)
                    expected_labels = set(available) | {"shore"}
                    if lakes_file not in self.unavailable_files:
                        for zone_id in sorted(expected_labels - set(labels)):
                            self.error(lakes_file, f"{where}.zone_labels.{zone_id}",
                                       f"missing label for zone {zone_id!r}")
                        for zone_id in sorted(set(labels) - expected_labels):
                            self.error(lakes_file, f"{where}.zone_labels.{zone_id}",
                                       "label has no habitat on this lake")

        for sid, row, _where in self.rows(species_file, "species"):
            if not isinstance(sid, str):
                continue
            declared = row.get("lakes")
            if not isinstance(declared, list):
                continue
            for lid in declared:
                if isinstance(lid, str) and lid in lakes:
                    listed = lakes[lid].get("species_ids")
                    if isinstance(listed, list) and sid not in listed:
                        self.error(lakes_file, f"lakes({lid}).species_ids", f"missing species {sid!r} declared for this lake")
        for lid, row, _where in self.rows(lakes_file, "lakes"):
            if not isinstance(lid, str):
                continue
            listed = row.get("species_ids")
            if not isinstance(listed, list):
                continue
            for sid in listed:
                if isinstance(sid, str) and sid in species:
                    species_lakes = species[sid].get("lakes")
                    if isinstance(species_lakes, list) and lid not in species_lakes:
                        self.error(species_file, f"species({sid}).lakes",
                                   f"missing lake {lid!r} listed by lakes.json")

        cedar = lakes.get("cedar")
        if isinstance(cedar, dict):
            if "rate_multipliers" not in cedar:
                self.error(lakes_file, "lakes(cedar).rate_multipliers", "required for the CEDAR_FISH API")
            if "zone_labels" not in cedar:
                self.error(lakes_file, "lakes(cedar).zone_labels", "required for the existing Cedar zone labels")

        pantry_file, dishes_file = "pantry.json", "dishes.json"
        pantry_root = self.root(docs, pantry_file, {"schema_version", "capacity", "card_price", "items"})
        self.root(docs, dishes_file, {"schema_version", "dishes"})
        pantry = self.table(docs, pantry_file, "items", {"id", "name", "host", "lake", "price"})
        dishes = self.table(docs, dishes_file, "dishes", {
            "id", "name", "host", "chapter", "food", "ingredient", "effect",
            "minutes", "charges", "value", "blurb"})
        if pantry_file not in self.unavailable_files:
            self.number(pantry_file, "capacity", pantry_root.get("capacity"), integer=True, minimum=1, maximum=20)
            self.number(pantry_file, "card_price", pantry_root.get("card_price"), minimum=0)
        for item_id, row, where in self.rows(pantry_file, "items"):
            for key in ("name", "host"):
                self.text(pantry_file, where + "." + key, row.get(key))
            self.enum(pantry_file, where + ".lake", row.get("lake"),
                      {"all", "briar", "cedar", "flathead", "crater", "nebula"})
            self.number(pantry_file, where + ".price", row.get("price"), minimum=.01)
        for dish_id, row, where in self.rows(dishes_file, "dishes"):
            for key in ("name", "host", "blurb"):
                self.text(dishes_file, where + "." + key, row.get(key))
            if row.get("host") not in [item.get("host") for item in pantry.values()]:
                self.error(dishes_file, where + ".host", "must reference a pantry host")
            self.number(dishes_file, where + ".chapter", row.get("chapter"), integer=True, minimum=1, maximum=5)
            self.enum(dishes_file, where + ".food", row.get("food"), (_SPECIES_FOODS - {"none"}) | {"any"})
            self.enum(dishes_file, where + ".ingredient", row.get("ingredient"), pantry)
            self.enum(dishes_file, where + ".effect", row.get("effect"), {
                "scout_species", "quick_haul", "fuel_saver", "weather_invitation", "steady_scout",
                "extra_dream", "clear_fog", "keep_bait", "shiny_credit", "glow_buoys"})
            self.number(dishes_file, where + ".minutes", row.get("minutes"), integer=True, minimum=0)
            self.number(dishes_file, where + ".charges", row.get("charges"), integer=True, minimum=0)
            self.number(dishes_file, where + ".value", row.get("value"), minimum=.01)
            if not row.get("minutes") and not row.get("charges"):
                self.error(dishes_file, where, "a buff needs a duration or charges")
            timed = row.get("effect") in {"scout_species", "fuel_saver", "steady_scout", "clear_fog", "glow_buoys"}
            if timed and (not row.get("minutes") or row.get("charges") != 0):
                self.error(dishes_file, where, "timed effects need a duration and no charges")
            if not timed and (row.get("minutes") != 0 or not row.get("charges")):
                self.error(dishes_file, where, "charged effects need charges and no duration")
            if row.get("effect") in {"quick_haul", "fuel_saver"}:
                self.number(dishes_file, where + ".value", row.get("value"), minimum=.01, maximum=1)
        for bait_id, row, where in self.rows(baits_file, "baits"):
            if "recipe" not in row:
                continue
            recipe = row["recipe"]
            if not isinstance(recipe, dict):
                self.error(baits_file, where + ".recipe", "expected an object")
                continue
            if set(recipe) != {"parents", "ingredient", "teller"}:
                self.error(baits_file, where + ".recipe", "expected parents, ingredient and teller")
            parents = self.id_list(baits_file, where + ".recipe.parents", recipe.get("parents"), baits)
            if len(parents) != 2 or any("recipe" in baits[p] for p in parents):
                self.error(baits_file, where + ".recipe.parents", "expected two distinct ordinary baits")
            self.enum(baits_file, where + ".recipe.ingredient", recipe.get("ingredient"), pantry)
            self.text(baits_file, where + ".recipe.teller", recipe.get("teller"))
            if row.get("price") != 0 or row.get("sold_at"):
                self.error(baits_file, where + ".recipe", "recipe bait is cooked, never sold")

        windows = self.calendar(docs, species)
        shells, tools = self.bot(docs)
        legendaries = self.legendaries(docs, species, windows)
        roster = self.roster(docs, lake_ids if lakes_file not in self.unavailable_files else None,
                             boats if boats_file not in self.unavailable_files else None)
        if lakes_file not in self.unavailable_files:
            for lake_id, expected in NAMED_PLACES.items():
                for place_id, kind in sorted(expected.items()):
                    if lake_id in lakes and places.get(f"{lake_id}:{place_id}", ("",))[0] != kind:
                        self.error(lakes_file, f"lakes({lake_id})", f"missing {kind} {place_id!r} (06 §5)")
        refs = _QuestRefs(
            lakes={lid: set(row.get("zone_ids") or ()) for lid, row in lakes.items()
                   if isinstance(row.get("zone_ids"), list)},
            places=places, species=species, legendaries=legendaries, baits=baits, dishes=dishes,
            pantry=pantry, shells=shells, tools=tools, roster=roster)
        refs.ripples, refs.keepsakes = self.keepsakes_and_ripples(docs, roster)
        quests, quest_cats, extends, scenes = self.quests(docs, refs)
        if self.errors:
            raise ContentError("\n".join(self.errors))
        return GameplayContent(species, baits, boats, lakes, zones, pantry, dishes, legendaries, roster,
                               places, quests, quest_cats, extends, refs.ripples, refs.keepsakes, scenes)

    def roster(self, docs, lakes, boats):
        """The 52 cats (51 rows; Pip & Pebble share one): role, lake, boat and appearance."""
        filename = "npcs.json"
        self.root(docs, filename, {"schema_version", "npcs"})
        rows = self.table(docs, filename, "npcs", {"id", "name", "lake", "role", "boat", "slot", "anchor",
                                                   "quests", "appearance"}, {"boat_paint"})
        if filename in self.unavailable_files:
            return rows
        counts = {"host": 0, "traveler": 0, "water": 0}
        cats = 0
        anchors, quest_ids, pools = {}, {}, {}
        for cid, row, where in self.rows(filename, "npcs"):
            self.text(filename, where + ".name", row.get("name"))
            role, lake, boat = row.get("role"), row.get("lake"), row.get("boat")
            if self.enum(filename, where + ".role", role, set(counts)):
                counts[role] += 1
            self.schedule_row(filename, where, cid, row, anchors, quest_ids, pools)
            if role == "traveler":
                if lake is not None:
                    self.error(filename, where + ".lake", "travelers visit every lake; expected null")
            elif lakes is not None:
                self.enum(filename, where + ".lake", lake, lakes)
            if role == "host":
                if boat is not None:
                    self.error(filename, where + ".boat", "hosts stand on their landing; expected null")
            elif boats is not None and (not self.enum(filename, where + ".boat", boat, boats)
                                        or boat in _HANDCRAFTED_BOATS):
                self.error(filename, where + ".boat", "expected a generated family boat")
            paint = row.get("boat_paint", {})
            if not isinstance(paint, dict) or not set(paint) <= set(_BOAT_PAINT_IDS):
                self.error(filename, where + ".boat_paint", "expected hull, deck or motor paint")
            else:
                for slot, value in paint.items():
                    self.enum(filename, f"{where}.boat_paint.{slot}", value, _BOAT_PAINT_IDS[slot])
            look = row.get("appearance")
            self.cat_look(filename, where + ".appearance", look, twin_allowed=True)
            cats += 1 + int(isinstance(look, dict) and "twin" in look)
        if counts != {"host": 5, "traveler": 2, "water": 44} or cats != 52:
            self.error(filename, "npcs", "expected 5 hosts, 2 travelers and 44 water-cat rows: 52 cats")
        hosts = [row.get("lake") for row in rows.values() if row.get("role") == "host"]
        if lakes is not None and sorted(map(str, hosts)) != sorted(lakes):
            self.error(filename, "npcs", "expected one host per lake")
        for lake, pool in DAY_NPCS.items():
            for npc_id in pool:
                if npc_id not in rows or rows[npc_id].get("lake") != lake or rows[npc_id].get("slot") != "day":
                    self.error(filename, "npcs", f"expected the V3 cat {npc_id!r} on {lake} by day")
        if "master_cinder" in rows and rows["master_cinder"].get("slot") != "night":
            self.error(filename, "npcs", "Master Cinder keeps the Briar night slot")
        for lake in sorted(lakes or ()):
            day, night = pools.get((lake, "day"), 0), pools.get((lake, "night"), 0)
            # Three day encounters a day must cover the pool every three days (02 §11.3).
            if not 3 <= day <= 3 * _ROUND_ROBIN_DAYS:
                self.error(filename, "npcs", f"{lake} needs 3–9 day encounters, found {day}")
            if not 1 <= night <= _ROUND_ROBIN_DAYS:
                self.error(filename, "npcs", f"{lake} needs 1–3 night encounters, found {night}")
        return rows

    def schedule_row(self, filename, where, cid, row, anchors, quest_ids, pools):
        """V1-30: each cat's schedule slot, its own anchor on its lake, and its quest ids."""
        role, lake, slot, anchor = row.get("role"), row.get("lake"), row.get("slot"), row.get("anchor")
        slots = {"host": {"landing"}, "traveler": {"traveler"}, "water": {"day", "night"}}
        expected = slots.get(role, set()) if isinstance(role, str) else set()
        if self.enum(filename, where + ".slot", slot, expected) and role == "water" and isinstance(lake, str):
            pools[(lake, slot)] = pools.get((lake, slot), 0) + 1
        if role == "traveler":
            if anchor is not None:
                self.error(filename, where + ".anchor", "travelers moor at each lake's mail or tinker mooring; expected null")
        elif not isinstance(anchor, str) or not isinstance(lake, str) or not anchor.startswith(lake + ":"):
            self.error(filename, where + ".anchor", "expected an anchor id on the cat's own lake")
        elif anchor in anchors:
            self.error(filename, where + ".anchor", f"already the anchor of {anchors[anchor]!r}")
        else:
            anchors[anchor] = cid
        quests = row.get("quests")
        if role == "host":
            allowed = [set(QUEST_IDS) | {f"host_{lake}"}]
        elif role == "water":
            allowed = [set(QUEST_IDS) | {f"wc_{cid}_a"}, {f"wc_{cid}_b"}]
        else:
            allowed = []
        if not isinstance(quests, list) or len(quests) != len(allowed):
            self.error(filename, where + ".quests", f"expected {len(allowed)} quest id(s)")
            return
        for i, (qid, ids) in enumerate(zip(quests, allowed)):
            if not isinstance(qid, str) or qid not in ids:
                self.error(filename, f"{where}.quests[{i}]", "expected a V3 quest id or the cat's own quest id")
            elif qid in quest_ids:
                self.error(filename, f"{where}.quests[{i}]", f"already given by {quest_ids[qid]!r}")
            else:
                quest_ids[qid] = cid

    def named_places(self, filename, where, lake, row, places):
        """V1-31: a lake's named areas (circles, rings or polygons) and story waypoints (06 §5)."""
        for group, kind in (("areas", "area"), ("waypoints", "waypoint")):
            if group not in row:
                continue
            items = row[group]
            if not isinstance(items, list):
                self.error(filename, f"{where}.{group}", "expected a list")
                continue
            for index, item in enumerate(items):
                item_where = f"{where}.{group}[{index}]"
                if not isinstance(item, dict):
                    self.error(filename, item_where, "expected an object")
                    continue
                pid = item.get("id")
                if isinstance(pid, str):
                    item_where += f"({pid})"
                shape = item.get("shape") if kind == "area" else "circle"
                required = {"id", "name", "x", "z", "r"} if shape == "circle" else {"id", "name", "points"}
                if kind == "area":
                    required |= {"shape"}
                optional = {"inner_r"} if kind == "area" and shape == "circle" else set()
                for key in sorted(required - item.keys()):
                    self.error(filename, item_where, f"missing required field {key!r}")
                for key in sorted(item.keys() - required - optional):
                    self.error(filename, item_where, f"unknown field {key!r}")
                self.text(filename, item_where + ".name", item.get("name"))
                if kind == "area" and not self.enum(filename, item_where + ".shape", shape, {"circle", "polygon"}):
                    continue
                if shape == "circle":
                    for key in ("x", "z"):
                        self.number(filename, f"{item_where}.{key}", item.get(key), minimum=-5000, maximum=5000)
                    radius_ok = self.number(filename, item_where + ".r", item.get("r"), minimum=1, maximum=400)
                    if "inner_r" in item and self.number(filename, item_where + ".inner_r", item["inner_r"],
                                                         minimum=0) and radius_ok and item["inner_r"] >= item["r"]:
                        self.error(filename, item_where + ".inner_r", "must be smaller than r")
                else:
                    points = item.get("points")
                    if not isinstance(points, list) or len(points) < 3:
                        self.error(filename, item_where + ".points", "expected at least three [x, z] points")
                    else:
                        for i, point in enumerate(points):
                            if not isinstance(point, list) or len(point) != 2:
                                self.error(filename, f"{item_where}.points[{i}]", "expected [x, z]")
                                continue
                            for value in point:
                                self.number(filename, f"{item_where}.points[{i}]", value,
                                            minimum=-5000, maximum=5000)
                if not isinstance(pid, str) or not pid.strip() or ":" in pid:
                    self.error(filename, item_where + ".id", "expected a bare place id")
                elif f"{lake}:{pid}" in places:
                    self.error(filename, item_where + ".id", f"duplicate place {pid!r} on {lake}")
                else:
                    places[f"{lake}:{pid}"] = (kind, item)

    def quests(self, docs, refs):
        """V1-31: quests.json rows (steps, requires, rewards, lines) and each cat's greetings and letters."""
        filename = "quests.json"
        self.root(docs, filename, {"schema_version", "quests", "cats", "extends"}, {"scenes"})
        rows = self.table(docs, filename, "quests", {"id", "kind", "giver_id", "lake_id", "title", "objective",
                                                     "journal", "reward"},
                          {"requires", "cross_lake", "on_accept", "lines"})
        cats = self.table(docs, filename, "cats", {"id", "greetings"}, {"letters", "story"})
        extends = self.table(docs, filename, "extends", {"id", "extends", "lines"})
        raw = docs.get(filename)
        scenes = (self.table(docs, filename, "scenes", {"id", "speaker_id", "lake_id", "lines"}, {"next", "choices"})
                  if isinstance(raw, dict) and "scenes" in raw else {})
        if filename in self.unavailable_files or self.unavailable_files & _QUEST_REFERENCE_FILES:
            # An unreadable file is reported once; checking rows against its ids would cascade.
            return rows, cats, extends, scenes
        given = {"ripples": {}, "keepsakes": {}}
        quest_ids = set(QUEST_IDS) | set(rows)
        for qid, row, where in self.rows(filename, "quests"):
            self.quest_row(filename, where, qid, row, refs, quest_ids, given)
        for cid, row, where in self.rows(filename, "cats"):
            self.quest_cat(filename, where, cid, row, refs)
        for qid, row, where in self.rows(filename, "extends"):
            # A recopied V3 line replaces one node's text; the quest itself never changes (06 §2).
            if not isinstance(qid, str) or qid not in QUEST_IDS or row.get("extends") != qid:
                self.error(filename, where, "an extends row names a V3 quest in both id and extends")
            lines = row.get("lines")
            if not isinstance(lines, dict) or not lines:
                self.error(filename, where + ".lines", "expected V3 stages to recopy")
                continue
            for stage, text in lines.items():
                if self.enum(filename, where + ".lines", stage, V3_LINE_STAGES):
                    self.bubbles(filename, f"{where}.lines.{stage}", text, most=1)
                    if isinstance(text, list):
                        self.error(filename, f"{where}.lines.{stage}", "a recopied V3 node holds one text")
        self.scenes(filename, scenes, refs)
        return rows, cats, extends, scenes

    def scenes(self, filename, scenes, refs):
        """V1-34: story scenes. A scene is one speaker's bubbles, then the next scene or a choice of them;
        a scene's state is pending or done (06 §3.3), so it must end and never loop."""
        for sid, row, where in self.rows(filename, "scenes"):
            if isinstance(sid, str) and not re.fullmatch(SCENE_ID, sid):
                self.error(filename, where + ".id", "expected pro_NN[b], story_c<n>_<name> or end_NN")
            speaker = row.get("speaker_id")
            if speaker != "bot" and speaker not in refs.roster:
                self.error(filename, where + ".speaker_id", f"unknown value/reference {speaker!r}")
            self.enum(filename, where + ".lake_id", row.get("lake_id"), refs.lakes)
            self.bubbles(filename, where + ".lines", row.get("lines"))
            if "next" in row and "choices" in row:
                self.error(filename, where, "expected next or choices, not both")
            if "next" in row and row["next"] is not None and (not isinstance(row["next"], str)
                                                               or row["next"] not in scenes):
                self.error(filename, where + ".next", f"unknown scene {row['next']!r}")
            if "choices" in row:
                choices = row["choices"]
                if not isinstance(choices, list) or not 1 <= len(choices) <= 3:
                    self.error(filename, where + ".choices", "expected one to three choices")
                    continue
                for i, choice in enumerate(choices):
                    choice_where = f"{where}.choices[{i}]"
                    if not isinstance(choice, dict) or not {"text", "next"} <= set(choice) <= {"text", "next", "knot"}:
                        self.error(filename, choice_where, "expected text and next, and optionally knot")
                        continue
                    if "knot" in choice:
                        self.enum(filename, choice_where + ".knot", choice["knot"], SCENE_KNOTS)
                    self.bubbles(filename, choice_where + ".text", choice["text"], limit=60, most=1)
                    if choice["next"] is not None and (not isinstance(choice["next"], str)
                                                       or choice["next"] not in scenes):
                        self.error(filename, choice_where + ".next", f"unknown scene {choice['next']!r}")
        for sid in scenes:
            # Follow every branch; a scene reached again on its own path would never finish.
            stack = [(sid, (sid,))]
            while stack:
                current, path = stack.pop()
                row = scenes.get(current, {})
                choices = row.get("choices") if isinstance(row.get("choices"), list) else []
                targets = ([row.get("next")] if "choices" not in row
                           else [c.get("next") for c in choices if isinstance(c, dict)])
                for target in targets:
                    if not isinstance(target, str) or target not in scenes:
                        continue  # reported above; a malformed scene is not followed
                    if target in path:
                        self.error(filename, f"scenes({sid})", f"loops back to {target!r}")
                        stack = []
                        break
                    stack.append((target, path + (target,)))

    def keepsakes_and_ripples(self, docs, roster):
        """V1-32: ripples.json (Ripples 11-44) and keepsakes.json (ks_<cat>), which rewards name."""
        ripples_file, keepsakes_file = "ripples.json", "keepsakes.json"
        self.root(docs, ripples_file, {"schema_version", "ripples"})
        self.root(docs, keepsakes_file, {"schema_version", "keepsakes"})
        ripples = self.table(docs, ripples_file, "ripples", {"id", "text"})
        keepsakes = self.table(docs, keepsakes_file, "keepsakes", {"id", "name", "npc_id"})
        for rid, row, where in self.rows(ripples_file, "ripples"):
            if isinstance(rid, str) and rid not in _V2_RIPPLES:
                self.error(ripples_file, where + ".id", "expected ripple_11 to ripple_44")
            self.bubbles(ripples_file, where + ".text", row.get("text"), most=1)
        for kid, row, where in self.rows(keepsakes_file, "keepsakes"):
            self.text(keepsakes_file, where + ".name", row.get("name"))
            npc = row.get("npc_id")
            if "npcs.json" in self.unavailable_files:
                continue
            if self.enum(keepsakes_file, where + ".npc_id", npc, roster) and kid != f"ks_{npc}":
                self.error(keepsakes_file, where + ".id", f"expected 'ks_{npc}'")
        return ripples, keepsakes

    def quest_row(self, filename, where, qid, row, refs, quest_ids, given):
        kind, giver, lake = row.get("kind"), row.get("giver_id"), row.get("lake_id")
        self.text(filename, where + ".title", row.get("title"))
        self.text(filename, where + ".journal", row.get("journal"))
        kind_ok = self.enum(filename, where + ".kind", kind, QUEST_KINDS)
        lake_ok = self.enum(filename, where + ".lake_id", lake, refs.lakes)
        if isinstance(qid, str) and qid in QUEST_IDS:
            # V1-32 adds `extends` rows for recopied V3 lines; the V3 definitions never change.
            self.error(filename, where + ".id", "collides with a V3 quest, which stays unchanged")
        cat = refs.roster.get(giver) if isinstance(giver, str) else None
        if cat is None:
            self.error(filename, where + ".giver_id", f"unknown value/reference {giver!r}")
        elif kind_ok and kind != "story":
            role = {"host": "host", "a": "water", "b": "water"}[kind]
            if cat.get("role") != role:
                self.error(filename, where + ".giver_id", f"a {kind!r} quest is given by a {role} cat")
            if lake_ok and cat.get("lake") != lake:
                self.error(filename, where + ".lake_id", "a cat's quests belong to its own lake")
            expected = {"host": f"host_{lake}", "a": f"wc_{giver}_a", "b": f"wc_{giver}_b"}[kind]
            if qid != expected:
                self.error(filename, where + ".id", f"expected {expected!r} for this kind and giver")
            listed = cat.get("quests")
            if not isinstance(listed, list) or qid not in listed:
                self.error(filename, where + ".id", f"not one of {giver}'s roster quests")
        if kind == "story" and isinstance(qid, str) and not re.fullmatch(r"story_c[0-5]_s[1-9]", qid):
            # Chapter 0 is the prologue (V1-34).
            self.error(filename, where + ".id", "expected story_c<chapter>_s<step>")
        objective = row.get("objective")
        steps = objective if isinstance(objective, list) else [objective]
        if isinstance(objective, list) and not 1 <= len(objective) <= MAX_QUEST_STEPS:
            self.error(filename, where + ".objective", f"expected 1–{MAX_QUEST_STEPS} steps")
        referenced = set()
        for index, step in enumerate(steps):
            self.quest_step(filename, where + (f".objective[{index}]" if isinstance(objective, list)
                                               else ".objective"), step, refs, referenced)
        listed = self.id_list(filename, where + ".cross_lake", row["cross_lake"], refs.lakes) \
            if "cross_lake" in row else []
        if lake_ok:
            # Cross-lake objectives are allowed, but only when the row lists them (06 §2).
            for other in sorted(referenced - {lake} - set(listed)):
                self.error(filename, where + ".objective", f"references {other!r}; list it in cross_lake")
            for other in listed:
                if other == lake or other not in referenced:
                    self.error(filename, where + ".cross_lake", f"{other!r} is not another lake a step uses")
        if "requires" in row:
            self.quest_requires(filename, where + ".requires", row["requires"], refs, quest_ids - {qid})
        self.quest_reward(filename, where + ".reward", row.get("reward"), kind if kind_ok else None, giver,
                          refs, given, qid)
        if "on_accept" in row:
            on_accept = row["on_accept"]
            if not isinstance(on_accept, dict) or set(on_accept) != {"items"}:
                self.error(filename, where + ".on_accept", "expected only items")
            else:
                self.reward_items(filename, where + ".on_accept.items", on_accept["items"], refs)
        if "lines" in row:
            self.quest_lines(filename, where + ".lines", row["lines"])
        elif kind in ("host", "a", "b"):
            self.error(filename, where, "missing required field 'lines'")

    def quest_requires(self, filename, where, value, refs, quest_ids):
        if not isinstance(value, dict) or not value:
            self.error(filename, where, "expected chapter_complete, quest or travel_unlocked")
            return
        for key in sorted(value.keys() - {"chapter_complete", "quest", "travel_unlocked"}):
            self.error(filename, where, f"unknown field {key!r}")
        if "chapter_complete" in value:
            self.number(filename, where + ".chapter_complete", value["chapter_complete"], integer=True,
                        minimum=1, maximum=5)
        if "quest" in value:
            self.enum(filename, where + ".quest", value["quest"], quest_ids)
        if "travel_unlocked" in value:
            self.enum(filename, where + ".travel_unlocked", value["travel_unlocked"], refs.lakes)

    def quest_zone(self, filename, where, value, refs, referenced):
        lake, _, zone = value.partition(":") if isinstance(value, str) else ("", "", "")
        if lake not in refs.lakes or zone not in refs.lakes[lake]:
            self.error(filename, where, f"unknown zone {value!r}")
            return
        referenced.add(lake)

    def quest_place(self, filename, where, value, kind, refs, referenced):
        if not isinstance(value, str) or refs.places.get(value, ("",))[0] != kind:
            self.error(filename, where, f"unknown {kind} {value!r}")
            return
        referenced.add(value.partition(":")[0])

    def clock_window(self, filename, where, value):
        if (not isinstance(value, list) or len(value) != 2
                or any(type(n) is not int or not 0 <= n < 1440 for n in value) or value[0] == value[1]):
            self.error(filename, where, "expected distinct start/end clock minutes in [0, 1440)")

    def quest_step(self, filename, where, step, refs, referenced):
        if not isinstance(step, dict):
            self.error(filename, where, "expected an object")
            return
        kind = step.get("type")
        if not self.enum(filename, where + ".type", kind, STEP_FIELDS):
            return
        for key in sorted(step.keys() - STEP_FIELDS[kind] - {"type"}):
            self.error(filename, where, f"unknown field {key!r} for {kind}")

        def one_of(*keys, required=True):
            present = [key for key in keys if key in step]
            if len(present) > 1 or (required and not present):
                self.error(filename, where, "expected exactly one of " + ", ".join(keys))

        def needs(*keys):
            for key in keys:
                if key not in step:
                    self.error(filename, where, f"missing required field {key!r}")

        def literal_true(key):
            if key in step and step[key] is not True:
                self.error(filename, where + "." + key, "expected true")

        def ids(key, *, unique=True, minimum=1):
            value = step[key]
            if not isinstance(value, list) or len(value) < minimum:
                self.error(filename, where + "." + key, f"expected a list of at least {minimum}")
                return []
            if unique and len({str(item) for item in value}) != len(value):
                self.error(filename, where + "." + key, "expected unique entries")
            return value

        def positive(key, *, integer=False, maximum=None):
            if key in step:
                self.number(filename, where + "." + key, step[key], integer=integer, minimum=1 if integer else 0.001,
                            maximum=maximum)

        for key in ("zone_id",):
            if key in step:
                self.quest_zone(filename, where + "." + key, step[key], refs, referenced)
        if "zone_ids" in step:
            for i, zone in enumerate(ids("zone_ids", unique=kind != "visit_sequence")):
                self.quest_zone(filename, f"{where}.zone_ids[{i}]", zone, refs, referenced)
        if "area_id" in step:
            self.quest_place(filename, where + ".area_id", step["area_id"], "area", refs, referenced)
        if "area_ids" in step:
            for i, area in enumerate(ids("area_ids")):
                self.quest_place(filename, f"{where}.area_ids[{i}]", area, "area", refs, referenced)
        if "waypoint_ids" in step:
            for i, point in enumerate(ids("waypoint_ids", unique=kind != "visit_sequence")):
                self.quest_place(filename, f"{where}.waypoint_ids[{i}]", point, "waypoint", refs, referenced)
        if "lake_id" in step and self.enum(filename, where + ".lake_id", step["lake_id"], refs.lakes):
            referenced.add(step["lake_id"])
        for key in ("set_window", "entry_window"):
            if key in step:
                self.clock_window(filename, where + "." + key, step[key])
        if "windows" in step:
            for i, window in enumerate(ids("windows", unique=False)):
                self.clock_window(filename, f"{where}.windows[{i}]", window)
        if "bait_id" in step:
            self.enum(filename, where + ".bait_id", step["bait_id"], refs.baits)
        for key in ("in_cold_band", "any", "distinct"):
            literal_true(key)

        if kind in ("line_set", "line_scout", "line_check", "line_scout_check"):
            if not {"zone_id", "area_id"} & step.keys():
                self.error(filename, where, "expected zone_id or area_id")
            one_of("tier_id", "min_tier", required=False)
            for key in ("tier_id", "min_tier"):
                if key in step:
                    self.enum(filename, where + "." + key, step[key], LINE_TIER_ORDER)
            if "hook_count" in step:
                if step.get("tier_id") not in _TIER_HOOKS:
                    self.error(filename, where + ".hook_count", "an exact hook count needs tier_id")
                elif step["hook_count"] != _TIER_HOOKS[step["tier_id"]]:
                    self.error(filename, where + ".hook_count", "does not match line tier")
            # Without a soak time, any check of the line after the set counts (V1-33).
            positive("active_soak_game_minutes", maximum=1440)
        elif kind == "anchor_idle":
            needs("zone_id", "continuous_game_minutes")
            positive("continuous_game_minutes", maximum=1440)
        elif kind == "scout_report":
            one_of("zone_id", "waypoint_ids", "lake_id")
        elif kind == "fish_livewell":
            needs("zone_id", "species_id")
            if "species_id" in step:
                self.enum(filename, where + ".species_id", step["species_id"], refs.species)
        elif kind == "travel_distance":
            needs("zone_id", "distance_m")
            positive("distance_m", maximum=20000)
            if "propulsion" in step:
                for i, item in enumerate(ids("propulsion")):
                    self.enum(filename, f"{where}.propulsion[{i}]", item, {"motor", "sail", "oar"})
        elif kind in ("visit_zones", "visit_sequence"):
            one_of("zone_ids", "waypoint_ids")
        elif kind == "catch_species":
            one_of("species_id", "species_ids", "group", "tag", "any")
            fish = set(refs.species) | set(refs.legendaries)
            if "species_id" in step:
                self.enum(filename, where + ".species_id", step["species_id"], fish)
            if "species_ids" in step:
                for i, sid in enumerate(ids("species_ids", minimum=2)):
                    self.enum(filename, f"{where}.species_ids[{i}]", sid, fish)
            if "group" in step:
                self.enum(filename, where + ".group", step["group"], _SPECIES_FOODS - {"none"})
            if "tag" in step:
                self.enum(filename, where + ".tag", step["tag"], _SPECIES_TAGS)
            positive("count", integer=True, maximum=50)
            positive("min_lb", maximum=500)
            if "time_band" in step:
                self.enum(filename, where + ".time_band", step["time_band"], TIME_BANDS)
            if (isinstance(step.get("species_ids"), list) and type(step.get("count")) is int
                    and step.get("distinct") is True and step["count"] > len(step["species_ids"])):
                self.error(filename, where + ".count", "more distinct fish than species_ids")
        elif kind == "book_stage":
            one_of("species_ids", "lake_id")
            needs("stage", "count")
            self.enum(filename, where + ".stage", step.get("stage"), BOOK_STAGE_ORDER[1:])
            positive("count", integer=True, maximum=144)
            scope = None
            if "species_ids" in step:
                scope = len([self.enum(filename, f"{where}.species_ids[{i}]", sid, refs.species)
                             for i, sid in enumerate(ids("species_ids"))])
            elif isinstance(step.get("lake_id"), str):
                scope = sum(1 for row in refs.species.values()
                            if isinstance(row.get("lakes"), list) and step["lake_id"] in row["lakes"])
            if scope is not None and type(step.get("count")) is int and step["count"] > scope:
                self.error(filename, where + ".count", f"more entries than the {scope} species in scope")
        elif kind == "cook_dish":
            one_of("dish_id", "any")
            if "dish_id" in step:
                self.enum(filename, where + ".dish_id", step["dish_id"], refs.dishes)
        elif kind == "tool_use":
            needs("tool_id")
            self.enum(filename, where + ".tool_id", step.get("tool_id"), refs.tools)
            if "shell_id" in step:
                self.enum(filename, where + ".shell_id", step["shell_id"], refs.shells)
        elif kind == "wait_weather":
            needs("weather")
            self.enum(filename, where + ".weather", step.get("weather"), WEATHER_STATES)
            one_of("zone_id", "zone_ids", "lake_id", "area_ids")
            if "then_weather" in step and self.enum(filename, where + ".then_weather", step["then_weather"],
                                                    WEATHER_STATES) and step["then_weather"] == step.get("weather"):
                self.error(filename, where + ".then_weather", "must differ from weather")
            positive("minutes", integer=True, maximum=1440)
        elif kind == "settle":
            needs("zone_id", "cues")
            positive("cues", integer=True, maximum=3)
        elif kind == "talk_to":
            needs("npc_id")
            self.enum(filename, where + ".npc_id", step.get("npc_id"), refs.roster)
            if "distinct_days" in step:
                self.number(filename, where + ".distinct_days", step["distinct_days"], integer=True,
                            minimum=2, maximum=7)
        elif kind == "attend_event":
            needs("lake_id", "event")
            self.enum(filename, where + ".event", step.get("event"), QUEST_EVENTS)

    def quest_reward(self, filename, where, reward, kind, giver, refs, given, qid):
        if not isinstance(reward, dict):
            self.error(filename, where, "expected an object")
            return
        for key in sorted(reward.keys() - REWARD_FIELDS):
            self.error(filename, where, f"unknown reward kind {key!r}")
        if "cash" in reward:
            self.number(filename, where + ".cash", reward["cash"], integer=True, minimum=0, maximum=100000)
        for key, pool, allowed in (("ripple_id", "ripples", _V2_RIPPLES), ("keepsake_id", "keepsakes", None)):
            if key not in reward:
                continue
            value = reward[key]
            if allowed is not None:
                if not self.enum(filename, where + "." + key, value, allowed):
                    continue
            elif not isinstance(value, str) or not re.fullmatch(r"ks_[a-z0-9_]+", value):
                self.error(filename, where + "." + key, "expected a ks_<cat id> keepsake id")
                continue
            elif kind == "b" and value != f"ks_{giver}":
                self.error(filename, where + "." + key, f"expected 'ks_{giver}'")
            registry = refs.ripples if pool == "ripples" else refs.keepsakes
            if value not in registry:
                self.error(filename, where + "." + key, f"{value!r} is not in {pool}.json")
            if value in given[pool]:
                self.error(filename, where + "." + key, f"already given by {given[pool][value]!r}")
            else:
                given[pool][value] = qid
        if "recipes" in reward:
            self.id_list(filename, where + ".recipes", reward["recipes"],
                         {bid for bid, row in refs.baits.items() if "recipe" in row})
        if "dish_cards" in reward:
            self.id_list(filename, where + ".dish_cards", reward["dish_cards"], refs.dishes)
        if "items" in reward:
            self.reward_items(filename, where + ".items", reward["items"], refs)
        if "shells" in reward:
            self.id_list(filename, where + ".shells", reward["shells"], set(refs.shells) - {"tin"})
        if "tools" in reward:
            self.id_list(filename, where + ".tools", reward["tools"], set(refs.tools))
        if "unlocks" in reward:
            for i, unlock in enumerate(self.id_list(filename, where + ".unlocks", reward["unlocks"], None)):
                kind_of, _, target = unlock.partition(":")
                if kind_of not in UNLOCK_KINDS or not re.fullmatch(r"[a-z0-9_:]+", target):
                    self.error(filename, f"{where}.unlocks[{i}]", "expected travel:, chart:, area: or shop:<id>")
                elif kind_of == "travel" and target not in refs.lakes:
                    self.error(filename, f"{where}.unlocks[{i}]", f"unknown lake {target!r}")
        required = {"host": {"cash"}, "a": {"cash", "ripple_id"}, "b": {"cash", "keepsake_id"}}.get(kind, set())
        for key in sorted(required - reward.keys()):
            self.error(filename, where, f"a {kind!r} quest rewards {key!r} (02 §12.1)")
        if required and type(reward.get("cash")) is int and reward["cash"] <= 0:
            self.error(filename, where + ".cash", "side quests pay cash")
        if kind == "host":
            for key in sorted(reward.keys() - {"cash"}):
                self.error(filename, where + "." + key, "host errands pay cash only (02 §12.1)")

    def reward_items(self, filename, where, items, refs):
        if not isinstance(items, dict) or not items:
            self.error(filename, where, "expected an object of item ids to counts")
            return
        for item_id, count in items.items():
            if item_id not in refs.baits and item_id not in refs.pantry:
                self.error(filename, f"{where}.{item_id}", f"unknown bait or pantry item {item_id!r}")
            self.number(filename, f"{where}.{item_id}", count, integer=True, minimum=1, maximum=99)

    def bubbles(self, filename, where, value, *, limit=_BUBBLE_CHARS, most=3):
        """Authored text: one to three bubbles of at most 140 characters, known placeholders only (05 §0)."""
        texts = value if isinstance(value, list) else [value]
        if isinstance(value, list) and not 1 <= len(value) <= most:
            self.error(filename, where, f"expected one to {most} bubbles (05 §0)")
        for i, text in enumerate(texts):
            text_where = f"{where}[{i}]" if isinstance(value, list) else where
            if not isinstance(text, str) or not text.strip():
                self.error(filename, text_where, "expected non-empty text")
                continue
            if len(text) > limit:
                self.error(filename, text_where, f"longer than {limit} characters (05 §0)")
            for name in re.findall(r"\{([^{}]*)\}", text):
                if name not in LINE_PLACEHOLDERS:
                    self.error(filename, text_where, f"unknown placeholder {{{name}}}")

    def quest_lines(self, filename, where, lines):
        if not isinstance(lines, dict):
            self.error(filename, where, "expected an object")
            return
        for key in sorted(lines.keys() - set(QUEST_LINE_STAGES) - set(QUEST_CHOICE_LABELS)):
            self.error(filename, where, f"unknown field {key!r}")
        for key in ("offer", "done"):
            if key not in lines:
                self.error(filename, where, f"missing required field {key!r}")
        for key, value in lines.items():
            if key in QUEST_CHOICE_LABELS:
                self.bubbles(filename, f"{where}.{key}", value, limit=60, most=1)
            elif key in QUEST_LINE_STAGES:
                self.bubbles(filename, f"{where}.{key}", value)

    def quest_cat(self, filename, where, cid, row, refs):
        cat = refs.roster.get(cid) if isinstance(cid, str) else None
        if cat is None:
            self.error(filename, where + ".id", f"unknown cat {cid!r}")
            return
        greetings = row.get("greetings")
        if not isinstance(greetings, dict) or not greetings:
            self.error(filename, where + ".greetings", "expected an object of greeting states")
        else:
            for state, value in greetings.items():
                if not self.enum(filename, f"{where}.greetings", state, GREETING_STATES):
                    continue
                # A greeting is one line or a list of alternatives; an alternative may be bubbles.
                options = value if isinstance(value, list) else [value]
                if not options:
                    self.error(filename, f"{where}.greetings.{state}", "expected at least one greeting")
                for i, option in enumerate(options):
                    self.bubbles(filename, f"{where}.greetings.{state}" + (f"[{i}]" if isinstance(value, list)
                                                                            else ""), option)
        if "letters" in row:
            letters = row["letters"]
            if cat.get("role") == "traveler":
                self.error(filename, where + ".letters", "travelers carry letters; they don't write them")
            elif not isinstance(letters, list) or not 1 <= len(letters) <= 3:
                self.error(filename, where + ".letters", "expected one to three letter variants (05 §9)")
            else:
                for i, letter in enumerate(letters):
                    self.bubbles(filename, f"{where}.letters[{i}]", letter, limit=280, most=1)
        if "story" in row:
            # A story told one part a game day (05 §4.3); each part is a line of bubbles.
            story = row["story"]
            if cat.get("role") == "traveler":
                self.error(filename, where + ".story", "travelers don't tell stories")
            elif not isinstance(story, list) or not 2 <= len(story) <= MAX_STORY_PARTS:
                self.error(filename, where + ".story", f"expected 2–{MAX_STORY_PARTS} parts")
            else:
                for i, part in enumerate(story):
                    self.bubbles(filename, f"{where}.story[{i}]", part)

    def cat_look(self, filename, where, look, *, twin_allowed):
        if not isinstance(look, dict):
            self.error(filename, where, "expected an object")
            return
        required = {"breed", "size", "build", "legs", "coat", "ears", "tail", "pattern", "colors", "eyes",
                    "whiskers", "attire", "pose", "prop"}
        optional = {"glow", "one_ear"} | ({"twin"} if twin_allowed else set())
        for key in sorted(required - look.keys()):
            self.error(filename, where, f"missing required field {key!r}")
        for key in sorted(look.keys() - required - optional):
            self.error(filename, where, f"unknown field {key!r}")
        at = where + "."
        self.text(filename, at + "breed", look.get("breed"))
        for key, low, high in (("size", 0.5, 1.4), ("build", 0.7, 1.4), ("legs", 0.5, 1.3),
                               ("whiskers", 0.3, 1.6)):
            self.number(filename, at + key, look.get(key), minimum=low, maximum=high)
        for key, allowed in (("coat", _CAT_COATS), ("ears", _CAT_EARS), ("tail", _CAT_TAILS),
                             ("pattern", _CAT_PATTERNS)):
            self.enum(filename, at + key, look.get(key), allowed)

        def colour(key, value):
            if not isinstance(value, list) or len(value) != 3:
                self.error(filename, at + key, "expected an RGB triple")
                return
            for i, n in enumerate(value):
                self.number(filename, f"{at}{key}[{i}]", n, minimum=0, maximum=1)

        colors = look.get("colors")
        if not isinstance(colors, dict) or set(colors) != {"base", "secondary", "accent"}:
            self.error(filename, at + "colors", "expected base, secondary and accent colours")
        else:
            for key in ("base", "secondary", "accent"):
                colour("colors." + key, colors[key])
        colour("eyes", look.get("eyes"))
        attire = look.get("attire")
        if not isinstance(attire, list) or len(attire) > 4:
            self.error(filename, at + "attire", "expected at most four attire items")
        else:
            kinds = []
            for i, item in enumerate(attire):
                if not isinstance(item, dict) or set(item) != {"kind", "color"}:
                    self.error(filename, f"{at}attire[{i}]", "expected kind and color")
                    continue
                if self.enum(filename, f"{at}attire[{i}].kind", item["kind"], _CAT_ATTIRE):
                    kinds.append(item["kind"])
                colour(f"attire[{i}].color", item["color"])
            if len(set(kinds)) != len(kinds):
                self.error(filename, at + "attire", "expected each attire kind once")
        pose = look.get("pose")
        if self.enum(filename, at + "pose", pose, set(_CAT_POSE_PROPS)):
            self.enum(filename, at + "prop", look.get("prop"), _CAT_POSE_PROPS[pose])
        if "glow" in look:
            self.number(filename, at + "glow", look["glow"], minimum=0, maximum=1)
        if "one_ear" in look and type(look["one_ear"]) is not bool:
            self.error(filename, at + "one_ear", "expected a boolean")
        if "twin" in look:
            self.cat_look(filename, at + "twin", look["twin"], twin_allowed=False)

    def legendaries(self, docs, species, windows):
        """The twelve legendaries' bespoke looks and underwater idles (V1-28)."""
        filename = "legendaries.json"
        self.root(docs, filename, {"schema_version", "legendaries"})
        rows = self.table(docs, filename, "legendaries", {"id", "name", "lake", "look", "idle"})
        if filename in self.unavailable_files:
            return rows
        if len(rows) != 12:
            self.error(filename, "legendaries", "expected all twelve legendaries")
        if windows is not None and set(rows) != set(windows):
            self.error(filename, "legendaries", "expected the same IDs as calendar.json legendary_windows")
        for lid, row, where in self.rows(filename, "legendaries"):
            self.text(filename, where + ".name", row.get("name"))
            if lid in species:
                self.error(filename, where, "a legendary must not reuse a standard species ID")
            lake = (windows or {}).get(lid, {}).get("lake")
            if windows and lid in windows and row.get("lake") != lake:
                self.error(filename, where + ".lake", f"expected {lake!r} from its legendary window")
            self.fish_look(filename, where + ".look", row.get("look"))
            idle = row.get("idle")
            if not isinstance(idle, dict) or set(idle) != {"sway", "rate", "bob"}:
                self.error(filename, where + ".idle", "expected sway, rate and bob")
                continue
            self.number(filename, where + ".idle.sway", idle["sway"], minimum=0, maximum=0.3)
            self.number(filename, where + ".idle.rate", idle["rate"], minimum=0.05, maximum=1.0)
            self.number(filename, where + ".idle.bob", idle["bob"], minimum=0, maximum=0.08)
        return rows

    def bot(self, docs):
        filename = "bot.json"
        raw = self.root(docs, filename, {"schema_version", "name_prefixes", "suffix_min", "suffix_max",
                                       "shells", "tools", "collar_stages", "knots"})
        if filename in self.unavailable_files:
            return {}, {}
        prefixes = raw.get("name_prefixes")
        expected = {"Copper", "Quark", "Zed", "Brass", "Sprocket", "Clinker", "Whirly",
                    "Widget", "Cobalt", "Anchor", "Rivet", "Echo"}
        if (not isinstance(prefixes, list) or len(prefixes) != 12
                or any(not isinstance(p, str) for p in prefixes)
                or set(prefixes) != expected):
            self.error(filename, "name_prefixes", "expected the twelve canonical prefixes, including Rivet and excluding Pebble")
        self.number(filename, "suffix_min", raw.get("suffix_min"), integer=True, minimum=11, maximum=11)
        self.number(filename, "suffix_max", raw.get("suffix_max"), integer=True, minimum=999, maximum=999)
        shells = self.table(docs, filename, "shells", {"id", "name", "chapter", "tool_id", "body", "trim", "secondary", "chime", "caption"})
        tools = self.table(docs, filename, "tools", {"id", "name", "price", "requires_finder"})
        stages = self.table(docs, filename, "collar_stages", {"id", "name"})
        knots = self.table(docs, filename, "knots", {"id", "name"})
        for group, rows, ids in (("shells", shells, {"tin", "frog", "duck", "sub", "astral"}),
                ("tools", tools, {"sonar_grid", "reed_anchor", "wave_chime", "thermo_scanner", "zero_g_winch"}),
                ("collar_stages", stages, {"none", "received", "loose", "retied", "favorite"}),
                ("knots", knots, {"square", "bow", "sailors_hitch"})):
            if set(rows) != ids:
                self.error(filename, group, "canonical IDs differ")
            for _id, row, where in self.rows(filename, group):
                self.text(filename, where + ".name", row.get("name"))
        for _id, row, where in self.rows(filename, "shells"):
            self.number(filename, where + ".chapter", row.get("chapter"), integer=True, minimum=0, maximum=5)
            self.enum(filename, where + ".tool_id", row.get("tool_id"), tools)
            self.enum(filename, where + ".chime", row.get("chime"), {"bot_tin", "bot_frog", "bot_duck", "bot_sub", "bot_astral"})
            self.text(filename, where + ".caption", row.get("caption"))
            if isinstance(_id, str) and row.get("chime") != "bot_" + _id:
                self.error(filename, where + ".chime", "each shell must have its own chime")
            for color in ("body", "trim", "secondary"):
                value = row.get(color)
                if not isinstance(value, list) or len(value) != 3:
                    self.error(filename, where + "." + color, "expected an RGB triple")
                else:
                    for i, channel in enumerate(value):
                        self.number(filename, where + f".{color}[{i}]", channel, minimum=0, maximum=1)
        refs = [row.get("tool_id") for row in shells.values()]
        if len(refs) != len(tools) or any(refs.count(tool) != 1 for tool in tools):
            self.error(filename, "shells", "each tool must belong to exactly one shell")
        for _id, row, where in self.rows(filename, "tools"):
            self.number(filename, where + ".price", row.get("price"), integer=True, minimum=1)
            if type(row.get("requires_finder")) is not bool:
                self.error(filename, where + ".requires_finder", "expected a boolean")
        return shells, tools

    def calendar(self, docs, species):
        filename = "calendar.json"
        raw = self.root(docs, filename, {"schema_version", "lake_days", "legendary_windows",
                                       "reservations", "cookout", "cookout_lines"})
        if filename in self.unavailable_files:
            return None
        lakes = {"briar", "cedar", "flathead", "crater", "nebula"}
        weather = {"clear", "fair", "overcast", "drizzle", "mist", "snow_mist", "fog", "aurora"}
        days = self.table(docs, filename, "lake_days", {"id", "lake", "weekday", "name", "band",
                          "multiplier", "foods", "species", "zones", "weather_bias", "fireflies"})
        windows = self.table(docs, filename, "legendary_windows", {"id", "lake", "start_hour", "end_hour",
                             "weathers", "recent_rain", "minimum_minutes"})
        if len(days) != 10:
            self.error(filename, "lake_days", "expected two Lake Days per playable lake")
        if len(windows) != 12:
            self.error(filename, "legendary_windows", "expected all twelve legendary windows")
        seen = set()
        for _id, row, where in self.rows(filename, "lake_days"):
            self.enum(filename, where + ".lake", row.get("lake"), lakes)
            self.number(filename, where + ".weekday", row.get("weekday"), integer=True, minimum=0, maximum=5)
            self.text(filename, where + ".name", row.get("name"))
            self.enum(filename, where + ".band", row.get("band"), {"dawn", "day", "dusk", "night", "any"})
            self.number(filename, where + ".multiplier", row.get("multiplier"), minimum=1, maximum=2)
            self.id_list(filename, where + ".foods", row.get("foods"), _SPECIES_FOODS)
            # All five authored fish rosters are now available.
            for key in ("species", "zones"):
                values = row.get(key)
                if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                    self.error(filename, where + "." + key, "expected a list of stable IDs")
            self.enum(filename, where + ".weather_bias", row.get("weather_bias"), weather | {"", "fog_clear"})
            if type(row.get("fireflies")) is not bool:
                self.error(filename, where + ".fireflies", "expected a boolean")
            if "species.json" not in self.unavailable_files:
                for sid in row.get("species", []) if isinstance(row.get("species"), list) else []:
                    self.enum(filename, where + ".species", sid, species)
                for zone in row.get("zones", []) if isinstance(row.get("zones"), list) else []:
                    self.enum(filename, where + ".zones", zone, set(_FALLBACK_FISHING_ZONE_ORDER))
            pair = (str(row.get("lake")), str(row.get("weekday")))
            if pair in seen:
                self.error(filename, where, "duplicate lake/weekday")
            seen.add(pair)
        for lake in lakes:
            if sum(row.get("lake") == lake for row in days.values()) != 2:
                self.error(filename, "lake_days", f"expected two specials for {lake}")
        for lake in lakes:
            if sum(row.get("lake") == lake for row in windows.values()) < 2:
                self.error(filename, "legendary_windows", f"expected at least two windows for {lake}")
        reservations = raw.get("reservations")
        if not isinstance(reservations, list):
            self.error(filename, "reservations", "expected a list")
            reservations = []
        rows = [(row, where) for _id, row, where in self.rows(filename, "legendary_windows")]
        for index, row in enumerate(reservations):
            where = f"reservations[{index}]"
            if not isinstance(row, dict) or set(row) != {"lake", "start_hour", "end_hour", "weathers"}:
                self.error(filename, where, "expected lake, start_hour, end_hour and weathers")
                continue
            rows.append((row, where))
        for row, where in rows:
            self.enum(filename, where + ".lake", row.get("lake"), lakes)
            self.number(filename, where + ".start_hour", row.get("start_hour"), integer=True, minimum=0, maximum=23)
            self.number(filename, where + ".end_hour", row.get("end_hour"), integer=True, minimum=0, maximum=24)
            conditions = self.id_list(filename, where + ".weathers", row.get("weathers"), weather)
            if where.startswith("reservations") and not conditions:
                self.error(filename, where + ".weathers", "reservation must choose at least one weather")
            if "recent_rain" in row and type(row["recent_rain"]) is not bool:
                self.error(filename, where + ".recent_rain", "expected a boolean")
            if "minimum_minutes" in row:
                self.number(filename, where + ".minimum_minutes", row["minimum_minutes"], integer=True, minimum=120, maximum=240)
            if row.get("start_hour") == row.get("end_hour"):
                self.error(filename, where, "weather window must have positive duration")
        cookout = raw.get("cookout")
        if cookout != {"weekday": 6, "start_hour": 17, "end_hour": 20, "gift_count": 1}:
            self.error(filename, "cookout", "expected Sunday 17–20 and one pantry gift")
        lines = raw.get("cookout_lines")
        if not isinstance(lines, dict) or set(lines) != NPC_IDS:
            self.error(filename, "cookout_lines", "expected one line per current lake cat")
        elif any(not isinstance(line, str) or not line.strip() for line in lines.values()):
            self.error(filename, "cookout_lines", "expected non-empty chat lines")
        return windows


def validate_content_v2(raw_files, *, unavailable_files=()) -> GameplayContent:
    """Validate the v2 source files and every cross-file reference."""
    if not isinstance(raw_files, dict):
        raise ContentError("content_v2:root: expected a mapping of filenames to documents")
    validator = _ContentV2Validator(unavailable_files)
    return validator.validate(raw_files)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKeyError(key)
        result[key] = value
    return result


def _duplicate_key_location(source, duplicate_key):
    """Locate the repeated key token so parse errors can name a source line."""
    decoder = json.JSONDecoder()
    frames = []

    def consume_value():
        if not frames:
            return True
        frame = frames[-1]
        if frame["kind"] == "object" and frame["state"] == "value":
            frame["state"] = "comma"
            return True
        if frame["kind"] == "array" and frame["state"] in {"value", "value_or_end"}:
            frame["state"] = "comma"
            return True
        return False

    index = 0
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        char = source[index]
        if char == "{":
            if not consume_value():
                return None
            frames.append({"kind": "object", "state": "key_or_end", "keys": set()})
            index += 1
        elif char == "[":
            if not consume_value():
                return None
            frames.append({"kind": "array", "state": "value_or_end"})
            index += 1
        elif char in "}]":
            if not frames:
                return None
            frame = frames[-1]
            expected_kind = "object" if char == "}" else "array"
            allowed = {"key_or_end", "comma"} if char == "}" else {"value_or_end", "comma"}
            if frame["kind"] != expected_kind or frame["state"] not in allowed:
                return None
            frames.pop()
            index += 1
        elif char == ":":
            if not frames or frames[-1]["kind"] != "object" or frames[-1]["state"] != "colon":
                return None
            frames[-1]["state"] = "value"
            index += 1
        elif char == ",":
            if not frames or frames[-1]["state"] != "comma":
                return None
            frames[-1]["state"] = "key" if frames[-1]["kind"] == "object" else "value"
            index += 1
        elif char == '"':
            try:
                value, end = decoder.raw_decode(source, index)
            except ValueError:
                return None
            if frames and frames[-1]["kind"] == "object" and frames[-1]["state"] in {"key", "key_or_end"}:
                frame = frames[-1]
                if value == duplicate_key and value in frame["keys"]:
                    line = source.count("\n", 0, index) + 1
                    column = index - source.rfind("\n", 0, index)
                    return line, column
                frame["keys"].add(value)
                frame["state"] = "colon"
            elif not consume_value():
                return None
            index = end
        else:
            try:
                _value, end = decoder.raw_decode(source, index)
            except ValueError:
                return None
            if not consume_value():
                return None
            index = end
    return None


def load_content_v2(directory: str | Path = CONTENT_V2_PATH) -> GameplayContent:
    """Read and validate the v2 gameplay files, collecting errors across files."""
    directory = Path(directory)
    raw_files = {}
    read_errors = []
    unavailable_files = set()
    for filename in CONTENT_V2_FILES:
        path = directory / filename
        source = None
        try:
            source = path.read_text(encoding="utf-8")
            raw_files[filename] = json.loads(source, object_pairs_hook=_unique_keys)
        except _DuplicateJSONKeyError as exc:
            raw_files[filename] = None
            unavailable_files.add(filename)
            location = _duplicate_key_location(source, exc.key) if source is not None else None
            if location:
                read_errors.append(f"{filename}:root: {exc} at line {location[0]}, column {location[1]}")
            else:
                read_errors.append(f"{filename}:root: {exc}")
        except (OSError, ValueError) as exc:
            raw_files[filename] = None
            unavailable_files.add(filename)
            if isinstance(exc, json.JSONDecodeError):
                read_errors.append(f"{filename}:root: {exc.msg} at line {exc.lineno}, column {exc.colno}")
            else:
                read_errors.append(f"{filename}:root: {exc}")
    try:
        content = validate_content_v2(raw_files, unavailable_files=unavailable_files)
    except ContentError as exc:
        read_errors.extend(str(exc).splitlines())
    if read_errors:
        raise ContentError("\n".join(read_errors))
    return content


def load_content(path: str | Path = CONTENT_PATH, *, gameplay: GameplayContent | None = None) -> NarrativeContent:
    """Fail with actionable path/ID context instead of returning partial data.

    The V3 bundle is validated alone, then joined by the V1.0 quests and the whole
    roster from content_v2 (or from `gameplay`, for an authoring tool or a test).
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (OSError, ValueError) as exc:
        raise ContentError(f"{path}: {exc}") from exc
    content = validate_content(raw, source=path)
    return merge_quests_v2(content, gameplay if gameplay is not None else _shipped_gameplay())


@lru_cache(maxsize=1)
def _shipped_gameplay() -> GameplayContent:
    """The shipped v2 content, validated once. The merge copies what it keeps, so the
    narrative bundle each load_content() returns stays fresh."""
    return load_content_v2()


# 05 §6.0's generic fills, used when an entry omits a node. The script has no generic
# ready or return line, so these two say nothing about the quest.
GENERIC_LINES = {
    "accept": "Wonderful. No hurry at all.",
    "decline": "That's all right. Ask me another day.",
    "progress": "How's it going? Don't rush on my account.",
    "ready": "You're back! How did it go?",
    "ready_wait": "Whenever you like. I'll be around.",
    "return": "Good to see you again, {Skipper}.",
}
GENERIC_CHOICES = {"accept_choice": "I’ll give it a try.", "decline_choice": "Maybe later.",
                   "turn_in_choice": "Here’s how it went.", "later_choice": "I’ll come back."}


def _quest_nodes(qid: str, row: dict) -> tuple[dict, dict]:
    """The V3 nine-stage graph for one V1.0 quest, one node per bubble (05 §0)."""
    lines, giver = row["lines"], row["giver_id"]
    nodes = {}

    def stage(name, last):
        value = lines.get(name, GENERIC_LINES.get(name))
        bubbles = value if isinstance(value, list) else [value]
        ids = [f"{qid}:dialogue:{name}"] + [f"{qid}:dialogue:{name}:{i}" for i in range(2, len(bubbles) + 1)]
        for i, (node_id, bubble) in enumerate(zip(ids, bubbles)):
            node = {"id": node_id, "quest_id": qid, "speaker_id": giver, "text": bubble}
            if i + 1 < len(ids):
                node["next"] = ids[i + 1]
            elif last is None:
                node["next"] = None
            else:
                node["choices"] = [
                    {"id": f"{qid}:choice:{action}", "text": lines.get(label, GENERIC_CHOICES[label]),
                     "target": f"{qid}:dialogue:{target}", "action": action}
                    for action, label, target in last]
            nodes[node_id] = node
        return ids[0]

    entries = {
        "available": stage("offer", (("accept", "accept_choice", "accept"),
                                     ("decline", "decline_choice", "decline"))),
        "active": stage("progress", None),
        "ready": stage("ready", (("turn_in", "turn_in_choice", "done"),
                                 ("close", "later_choice", "ready_wait"))),
        "completed": stage("return", None),
    }
    for name in ("accept", "decline", "ready_wait", "done"):
        stage(name, None)
    return entries, nodes


def merge_quests_v2(content: NarrativeContent, gameplay: GameplayContent) -> NarrativeContent:
    """Join the V1.0 quests, their synthesized dialogue and the whole roster to V3 content."""
    cats = {}
    for cid, row in gameplay.roster.items():
        extra = gameplay.quest_cats.get(cid, {})
        cats[cid] = {"id": cid, "name": row["name"], "lake_id": row["lake"], "role": row["role"],
                     "quests": list(row["quests"]), "greetings": deepcopy(extra.get("greetings", {})),
                     "letters": list(extra.get("letters", [])), "story": deepcopy(extra.get("story", []))}
    content.cats = cats
    content.ripples = deepcopy(gameplay.ripples)
    content.keepsakes = deepcopy(gameplay.keepsakes)
    content.scenes = deepcopy(gameplay.scenes)
    for qid, row in gameplay.quests.items():
        quest = deepcopy(row)
        if "lines" in row:
            quest["dialogue"], nodes = _quest_nodes(qid, row)
            content.dialogue.update(nodes)
        content.quests[qid] = quest
    for qid, row in gameplay.extends.items():
        for stage, text in row["lines"].items():
            node_id = f"{qid}:dialogue:{stage}"
            content.dialogue[node_id] = {**content.dialogue[node_id], "text": text}
    return content


def validate_book_content(raw, *, source=BOOK_CONTENT_PATH, species_ids=()) -> BookContent:
    """Collect book authoring errors, including missing currently playable fish."""
    validator = _Validator(source)
    rumors, legendaries = {}, {}
    if validator.shape(raw, "root", ("schema_version", "species_rumors", "legendary_stories")):
        validator.literal(raw.get("schema_version"), 1, "schema_version")
        for table, fields, count, target, row_type in (
            ("species_rumors", ("text", "teller", "folk_name"), 144, rumors, Rumor),
            ("legendary_stories", ("story", "teller"), 12, legendaries, LegendaryStory),
        ):
            rows = raw.get(table)
            if not isinstance(rows, dict):
                validator.error(table, "expected an object keyed by stable IDs")
                continue
            if len(rows) != count:
                validator.error(table, f"expected {count} entries, found {len(rows)}")
            for identifier, row in rows.items():
                where = f"{table}({identifier})"
                valid_id = validator.identifier(identifier, where + ".id")
                if not validator.shape(row, where, fields):
                    continue
                valid_fields = [validator.text(row.get(key), where + "." + key)
                                for key in fields]
                if valid_id and all(valid_fields):
                    target[identifier] = row_type(**{key: row[key] for key in fields})
        for identifier in sorted(set(species_ids) - set(rumors)):
            validator.error(f"species_rumors({identifier})", "missing rumor for playable species")
    if validator.errors:
        raise ContentError("\n".join(validator.errors))
    return BookContent(rumors, legendaries)


def load_book_content(path: str | Path = BOOK_CONTENT_PATH, *, species_ids=()) -> BookContent:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (OSError, ValueError) as exc:
        raise ContentError(f"{path}: {exc}") from exc
    return validate_book_content(raw, source=path, species_ids=species_ids)


def _load_all_content():
    """Validate narrative, gameplay and book data independently, reporting all errors."""
    errors = []
    narrative = gameplay = book = None
    try:
        narrative = load_content()
    except ContentError as exc:
        errors.extend(str(exc).splitlines())
    try:
        gameplay = load_content_v2()
    except ContentError as exc:
        errors.extend(str(exc).splitlines())
    try:
        book = load_book_content(species_ids=gameplay.species if gameplay else ())
    except ContentError as exc:
        errors.extend(str(exc).splitlines())
    if errors:
        raise ContentError("\n".join(errors))
    return narrative, gameplay, book


if __name__ == "__main__":
    content, gameplay, book = _load_all_content()
    print(f"Content valid: {len(content.npcs)} NPCs, {len(content.quests)} narrative quests, "
          f"{len(content.dialogue)} dialogue nodes, {len(gameplay.species)} species, "
          f"{len(gameplay.baits)} baits, {len(gameplay.boats)} boats, "
          f"{len(gameplay.lakes)} lakes, {len(book.rumors)} book rumors, "
          f"{len(book.legendaries)} legendary stories")
