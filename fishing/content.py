"""Load and validate optional narrative definitions without changing game state.

The returned indexes are fresh per call. Scheduling, event evaluation, dialogue
execution and rewards belong to later tickets; loading never runs an action.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from .data import BAIT_BY_ID, LINE_TIERS, SPECIES_BY_ID, ZONE_ORDER
from .lakes import LAKES
from .narrative import DAY_NPCS, QUEST_IDS, RIPPLE_BY_QUEST

CONTENT_PATH = Path(__file__).with_name("assets") / "narrative_v1.json"
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


@dataclass
class NarrativeContent:
    npcs: dict[str, dict]
    quests: dict[str, dict]
    rewards: dict[str, dict]
    dialogue: dict[str, dict]


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
            self.literal(obj.get("propulsion"), ["motor", "sail"], where + ".propulsion")


def validate_content(raw, *, source="<content>") -> NarrativeContent:
    """Validate all definitions and links before returning any usable content."""
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


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContentError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_content(path: str | Path = CONTENT_PATH) -> NarrativeContent:
    """Fail with actionable path/ID context instead of returning partial data."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (OSError, ValueError) as exc:
        raise ContentError(f"{path}: {exc}") from exc
    return validate_content(raw, source=path)


if __name__ == "__main__":
    content = load_content()
    print(f"Narrative content valid: {len(content.npcs)} NPCs, "
          f"{len(content.quests)} quests, {len(content.dialogue)} dialogue nodes")
