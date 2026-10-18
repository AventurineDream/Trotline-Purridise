"""Event-driven progress for the optional, contract-defined side quests.

The quest manager observes existing gameplay transitions. It does not alter
fishing, movement, NPC schedules, payouts, or the save format.
"""

from __future__ import annotations

import math

from .narrative import deployment_id


def _finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _window_contains(window, game_minute: float) -> bool:
    if not isinstance(window, list) or len(window) != 2 or not _finite_number(game_minute):
        return False
    minute = game_minute % 1440
    start, end = window
    return start <= minute < end if start < end else minute >= start or minute < end


class QuestManager:
    """Apply one named game event to every active, validated quest objective."""

    def __init__(self, content):
        self.content = content

    def handle_event(self, state, event: dict) -> None:
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        for quest_id, definition in self.content.quests.items():
            progress = state.narrative.quests[quest_id]
            if (progress.status != "active"
                    or not self._prerequisites_met(state, definition)
                    or not self._after_acceptance(progress, event)):
                continue
            objective = definition["objective"]
            objective_type = objective["type"]
            if kind == "line.set" and objective_type in ("line_scout", "line_check", "line_scout_check"):
                self._line_set(progress, objective, event)
            elif kind == "bot.scout_complete":
                self._scout_complete(state, definition, progress, objective, event)
            elif kind == "line.check" and objective_type in ("line_check", "line_scout_check"):
                self._line_check(state, definition, progress, objective, event)
            elif kind == "fish.enter_livewell" and objective_type == "fish_livewell":
                self._fish_entered(state, definition, progress, objective, event)
            elif kind == "anchor.sample" and objective_type == "anchor_idle":
                self._anchor_sample(state, definition, progress, objective, event)
            elif kind == "boat.move" and objective_type == "travel_distance":
                self._boat_moved(state, definition, progress, objective, event)
            elif kind == "zone.enter":
                if objective_type == "visit_zones":
                    self._visited(state, definition, progress, objective, event)
                elif objective_type == "visit_sequence":
                    self._visited_in_sequence(state, definition, progress, objective, event)

    @staticmethod
    def _after_acceptance(progress, event) -> bool:
        accepted = progress.accepted_game_minute
        event_time = (event.get("entry_game_minute") if event.get("type") == "fish.enter_livewell"
                      else event.get("game_minute"))
        return (_finite_number(accepted) and _finite_number(event_time)
                and event_time >= accepted)

    @staticmethod
    def _prerequisites_met(state, definition: dict) -> bool:
        return all(state.narrative.quests[quest_id].status == "completed"
                   for quest_id in definition.get("prerequisites", []))

    @staticmethod
    def _ready(state, definition: dict, progress) -> None:
        if progress.status != "active" or not QuestManager._prerequisites_met(state, definition):
            return
        progress.status = "ready"
        state.toast(f"{definition['title']} is ready to turn in.")

    @staticmethod
    def _attempts(progress) -> dict:
        attempts = progress.progress.get("deployments")
        if not isinstance(attempts, dict):
            attempts = {}
            progress.progress["deployments"] = attempts
        return attempts

    def _line_set(self, progress, objective: dict, event: dict) -> None:
        line_id = deployment_id(event.get("line_id"))
        if line_id is None:
            return
        if (event.get("zone_id") != objective.get("zone_id")
                or event.get("tier_id") != objective.get("tier_id")
                or event.get("hook_count") != objective.get("hook_count")
                or event.get("bait_id") != objective.get("bait_id")):
            return
        if "set_window" in objective and not _window_contains(objective["set_window"], event.get("game_minute")):
            return
        if not _finite_number(event.get("active_game_minute")):
            return
        attempts = self._attempts(progress)
        attempts.setdefault(line_id, {
            "set": {
                "lake_id": event.get("lake_id"),
                "zone_id": event["zone_id"],
                "tier_id": event["tier_id"],
                "hook_count": event["hook_count"],
                "bait_id": event["bait_id"],
                "game_minute": event["game_minute"],
                "active_game_minute": event["active_game_minute"],
            },
            "scouted": False,
            "checked": False,
        })

    def _scout_complete(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        if event.get("report_delivered") is not True:
            return
        if event.get("zone_id") != objective.get("zone_id"):
            return
        if objective["type"] == "scout_report":
            if event.get("depth_class") not in {"skinny", "middling", "deep"}:
                return
            self._ready(state, definition, progress)
            return
        distance = event.get("distance_m")
        maximum = objective.get("scout_range_lt_m")
        if (not _finite_number(distance) or not _finite_number(maximum)
                or distance >= maximum):
            return
        line_id = deployment_id(event.get("target_line_id"))
        attempt = self._attempts(progress).get(line_id)
        if line_id is None or not isinstance(attempt, dict):
            return
        set_data = attempt.get("set")
        if (not isinstance(set_data, dict)
                or set_data.get("zone_id") != objective.get("zone_id")
                or set_data.get("lake_id") != event.get("lake_id")):
            return
        attempt["scouted"] = True
        attempt["scout"] = {"zone_id": event["zone_id"], "game_minute": event["game_minute"]}
        if objective["type"] == "line_scout":
            self._ready(state, definition, progress)

    def _line_check(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        line_id = deployment_id(event.get("line_id"))
        attempts = self._attempts(progress)
        attempt = attempts.get(line_id)
        if line_id is None or not isinstance(attempt, dict):
            return
        set_data = attempt.get("set")
        if not isinstance(set_data, dict):
            return
        current = event.get("active_game_minute")
        start = set_data.get("active_game_minute")
        if not (_finite_number(current) and _finite_number(start)):
            return
        soaked = max(0.0, current - start)
        recorded = progress.progress.get("active_soak_game_minutes", 0.0)
        if not _finite_number(recorded) or recorded < 0:
            recorded = 0.0
        progress.progress["active_soak_game_minutes"] = max(recorded, soaked)
        if soaked < objective.get("active_soak_game_minutes", math.inf):
            return
        if objective.get("scout_before_check") is True and attempt.get("scouted") is not True:
            return
        attempt["checked"] = True
        self._ready(state, definition, progress)

    def _fish_entered(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        if (event.get("species_id") != objective.get("species_id")
                or event.get("source_zone_id") != objective.get("zone_id")
                or event.get("bait_id") != objective.get("bait_id")
                or not deployment_id(event.get("source_line_id"))):
            return
        entry = event.get("entry_game_minute")
        if not _window_contains(objective.get("entry_window"), entry):
            return
        progress.progress["fish_entered_livewell"] = {
            "species_id": event["species_id"],
            "source_line_id": event["source_line_id"],
            "source_zone_id": event["source_zone_id"],
            "bait_id": event["bait_id"],
            "catch_game_minute": event.get("catch_game_minute"),
            "entry_game_minute": entry,
        }
        self._ready(state, definition, progress)

    def _anchor_sample(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        valid = (event.get("zone_id") == objective.get("zone_id")
                 and event.get("anchored") is True and event.get("engine_idle") is True)
        if not valid:
            progress.progress["continuous_game_minutes"] = 0.0
            return
        elapsed = event.get("elapsed_game_minutes", 0.0)
        if not _finite_number(elapsed) or elapsed < 0:
            return
        current = progress.progress.get("continuous_game_minutes", 0.0)
        if not _finite_number(current) or current < 0:
            current = 0.0
        current += elapsed
        progress.progress["continuous_game_minutes"] = current
        if current >= objective.get("continuous_game_minutes", math.inf):
            self._ready(state, definition, progress)

    def _boat_moved(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        distance = event.get("distance_m")
        if (event.get("zone_id") != objective.get("zone_id")
                or event.get("lake_id") != objective["zone_id"].split(":", 1)[0]
                or event.get("player_controlled") is not True
                or event.get("propulsion") not in objective.get("propulsion", [])
                or not _finite_number(distance) or distance <= 0):
            return
        current = progress.progress.get("distance_m", 0.0)
        if not _finite_number(current) or current < 0:
            current = 0.0
        current += distance
        progress.progress["distance_m"] = current
        if current >= objective.get("distance_m", math.inf):
            self._ready(state, definition, progress)

    def _visited(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        zone_id = event.get("zone_id")
        if zone_id not in objective.get("zone_ids", []):
            return
        visited = progress.progress.get("visited_zones", [])
        if not isinstance(visited, list):
            visited = []
        if zone_id not in visited:
            visited.append(zone_id)
        progress.progress["visited_zones"] = visited
        if set(objective["zone_ids"]).issubset(visited):
            self._ready(state, definition, progress)

    def _visited_in_sequence(self, state, definition: dict, progress, objective: dict, event: dict) -> None:
        if (event.get("movement_cause") != objective.get("movement_cause")
                or event.get("player_controlled") is not objective.get("player_controlled")):
            return
        zones = objective["zone_ids"]
        index = progress.progress.get("sequence_index", 0)
        if type(index) is not int or not 0 <= index < len(zones):
            return
        if event.get("zone_id") == zones[index]:
            index += 1
            progress.progress["sequence_index"] = index
            progress.progress["visited_sequence"] = zones[:index]
            if index == len(zones):
                self._ready(state, definition, progress)
