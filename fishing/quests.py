"""Event-driven progress for the optional side quests.

The quest manager observes existing gameplay transitions. It does not alter
fishing, movement or NPC schedules. The twelve V3 quests keep their contract
evaluation unchanged; the V1.0 quests (rows with a `kind`, V1-31) are evaluated
step by step from `02 §12.3`.
"""

from __future__ import annotations

import math

from . import lakes
from .content import BOOK_STAGE_ORDER, LINE_TIER_ORDER
from .data import LAKE_SPECIES_IDS, SPECIES_BY_ID, band_of
from .narrative import deployment_id


def _finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


CLOCK_START = 360  # game minute 0 is 06:00 on the clock


def _window_contains(window, game_minute: float) -> bool:
    """Windows are local clock minutes, not elapsed game minutes (docs/narrative/CONTENT.md)."""
    if not isinstance(window, list) or len(window) != 2 or not _finite_number(game_minute):
        return False
    minute = (game_minute + CLOCK_START) % 1440
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
            if "kind" in definition:
                continue  # a V1.0 quest; see _handle_v2
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
        self._handle_v2(state, event)

    @staticmethod
    def _after_acceptance(progress, event) -> bool:
        accepted = progress.accepted_game_minute
        event_time = (event.get("entry_game_minute") if event.get("type") == "fish.enter_livewell"
                      else event.get("game_minute"))
        return (_finite_number(accepted) and _finite_number(event_time)
                and event_time >= accepted)

    @staticmethod
    def _bait_sections_match(event: dict, required_bait: str) -> bool:
        if "bait_sections" in event:
            sections = event.get("bait_sections")
            if not isinstance(sections, list) or not 1 <= len(sections) <= 3:
                return False
        else:
            # Legacy line events carried only one bait_id.
            sections = [event.get("bait_id")]
        return all(isinstance(bait, str) and bait == required_bait
                   for bait in sections)

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
                or not self._bait_sections_match(event, objective.get("bait_id"))):
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
                "bait_id": objective["bait_id"],
                "bait_sections": list(event.get("bait_sections", [event.get("bait_id")])),
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
        # Bot captures the nearest eligible line (strictly inside the authored
        # range) at launch. The report can arrive after the boat has moved, so
        # its arrival-time distance must not be used to re-evaluate that rule.
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
        if (event.get("lake_id") != set_data.get("lake_id")
                or event.get("zone_id") != set_data.get("zone_id")
                or event.get("zone_id") != objective.get("zone_id")):
            return
        current = event.get("active_game_minute")
        start = set_data.get("active_game_minute")
        if not (_finite_number(current) and _finite_number(start)):
            return
        soaked = max(0.0, current - start)
        attempt_recorded = attempt.get("active_soak_game_minutes", 0.0)
        if not _finite_number(attempt_recorded) or attempt_recorded < 0:
            attempt_recorded = 0.0
        attempt["active_soak_game_minutes"] = max(attempt_recorded, soaked)
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
        expected_lake = objective.get("zone_id", "").split(":", 1)[0]
        if (event.get("lake_id") != expected_lake
                or event.get("species_id") != objective.get("species_id")
                or event.get("source_zone_id") != objective.get("zone_id")
                or event.get("bait_id") != objective.get("bait_id")
                or not self._bait_sections_match(event, objective.get("bait_id"))
                or not deployment_id(event.get("source_line_id"))):
            return
        entry = event.get("entry_game_minute")
        if not _window_contains(objective.get("entry_window"), entry):
            return
        progress.progress["fish_entered_livewell"] = {
            "species_id": event["species_id"],
            "source_line_id": event["source_line_id"],
            "lake_id": event["lake_id"],
            "source_zone_id": event["source_zone_id"],
            "bait_id": event["bait_id"],
            "bait_sections": list(event.get("bait_sections", [event.get("bait_id")])),
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

    # --- V1.0 quests (V1-31) ---------------------------------------------------

    def _handle_v2(self, state, event: dict) -> None:
        types = _STEP_EVENTS.get(event.get("type"))
        if not types:
            return
        for quest_id, definition in self.content.quests.items():
            if "kind" not in definition:
                continue
            progress = state.narrative.quests.get(quest_id)
            if (progress is None or progress.status != "active"
                    or not self._after_acceptance(progress, event)):
                continue
            step, data = current_step(definition, progress)
            if step is None or step["type"] not in types:
                continue
            if getattr(self, "_v2_" + step["type"])(state, step, data, event):
                self._advance(state, definition, progress)

    def begin_step(self, state, quest_id: str) -> None:
        """Start the current step. A book goal already met completes at once."""
        definition = self.content.quests.get(quest_id)
        progress = state.narrative.quests.get(quest_id)
        if definition is None or progress is None or progress.status != "active":
            return
        step, _data = current_step(definition, progress)
        if step is not None and step["type"] == "book_stage" and book_goal_met(state, step):
            self._advance(state, definition, progress)

    def _advance(self, state, definition: dict, progress) -> None:
        index = progress.progress.get("step", 0) + 1
        if index >= len(steps_of(definition)):
            progress.status = "ready"
            state.toast(f"{definition['title']} is ready to turn in.")
            return
        progress.progress = {"step": index, "data": {}}
        self.begin_step(state, definition["id"])

    def _line_set_matches(self, step: dict, event: dict) -> bool:
        if deployment_id(event.get("line_id")) is None or not _finite_number(event.get("active_game_minute")):
            return False
        tier = event.get("tier_id")
        return ((("zone_id" not in step) or event.get("zone_id") == step["zone_id"])
                and (("area_id" not in step)
                     or lakes.in_place(step["area_id"], event.get("lake_id"), event.get("x"), event.get("z")))
                and (("tier_id" not in step) or tier == step["tier_id"])
                and (("min_tier" not in step) or _tier_rank(tier) >= _tier_rank(step["min_tier"]))
                and (("hook_count" not in step) or event.get("hook_count") == step["hook_count"])
                and (("bait_id" not in step) or self._bait_sections_match(event, step["bait_id"]))
                and (("set_window" not in step) or _window_contains(step["set_window"], event.get("game_minute")))
                and (not step.get("in_cold_band") or event.get("in_cold_band") is True))

    def _v2_line(self, state, step: dict, data: dict, event: dict) -> bool:
        kind = event["type"]
        attempts = data.get("deployments")
        if not isinstance(attempts, dict):
            attempts = data["deployments"] = {}
        if kind == "line.set":
            if self._line_set_matches(step, event):
                attempts.setdefault(event["line_id"], {
                    "set": {"lake_id": event.get("lake_id"), "zone_id": event.get("zone_id"),
                            "game_minute": event.get("game_minute"),
                            "active_game_minute": event["active_game_minute"]},
                    "scouted": False})
            return False
        line_id = deployment_id(event.get("target_line_id" if kind == "bot.scout_complete" else "line_id"))
        attempt = attempts.get(line_id) if line_id is not None else None
        if not isinstance(attempt, dict) or not isinstance(attempt.get("set"), dict):
            return False
        set_data = attempt["set"]
        if event.get("lake_id") != set_data.get("lake_id"):
            return False
        if kind == "bot.scout_complete":
            if event.get("report_delivered") is not True:
                return False
            attempt["scouted"] = True
            return step["type"] == "line_scout"
        if step["type"] == "line_scout" or event.get("zone_id") != set_data.get("zone_id"):
            return False
        current, start = event.get("active_game_minute"), set_data.get("active_game_minute")
        if not (_finite_number(current) and _finite_number(start)):
            return False
        soaked = max(0.0, current - start)
        attempt["active_soak_game_minutes"] = max(_amount(attempt.get("active_soak_game_minutes")), soaked)
        data["active_soak_game_minutes"] = max(_amount(data.get("active_soak_game_minutes")), soaked)
        if soaked < step["active_soak_game_minutes"]:
            return False
        return step["type"] == "line_check" or attempt.get("scouted") is True

    _v2_line_scout = _v2_line_check = _v2_line_scout_check = _v2_line

    @staticmethod
    def _hit_pairs(step: dict, data: dict, targets, at, minute) -> bool:
        """Each target, in each listed clock window, needs its own event (`windows`, 02 §12.3)."""
        windows = step.get("windows") or [None]
        hits = data.get("hits")
        if not isinstance(hits, list):
            hits = data["hits"] = []
        for t, target in enumerate(targets):
            if not at(target):
                continue
            for w, window in enumerate(windows):
                key = f"{t}:{w}"
                if key not in hits and (window is None or _window_contains(window, minute)):
                    hits.append(key)
                    return len(hits) >= len(targets) * len(windows)
        return False

    def _v2_scout_report(self, state, step: dict, data: dict, event: dict) -> bool:
        if (event.get("type") != "bot.scout_complete" or event.get("report_delivered") is not True
                or event.get("depth_class") not in {"skinny", "middling", "deep"}):
            return False
        if "waypoint_ids" in step:
            # Waypoints are story points; Bot's scouting spot must fall within one.
            return self._hit_pairs(step, data, step["waypoint_ids"], lambda ref: lakes.in_place(
                ref, event.get("lake_id"), event.get("x"), event.get("z")), event.get("game_minute"))
        return self._hit_pairs(step, data, [step["zone_id"]], lambda zone: event.get("zone_id") == zone,
                               event.get("game_minute"))

    def _v2_visit_zones(self, state, step: dict, data: dict, event: dict) -> bool:
        key, targets = (("waypoint_id", step["waypoint_ids"]) if "waypoint_ids" in step
                        else ("zone_id", step["zone_ids"]))
        if event.get("type") != _VISIT_EVENT[key]:
            return False
        return self._hit_pairs(step, data, targets, lambda target: event.get(key) == target,
                               event.get("game_minute"))

    def _v2_visit_sequence(self, state, step: dict, data: dict, event: dict) -> bool:
        key, targets = (("waypoint_id", step["waypoint_ids"]) if "waypoint_ids" in step
                        else ("zone_id", step["zone_ids"]))
        if (event.get("type") != _VISIT_EVENT[key] or event.get("movement_cause") != "boat"
                or event.get("player_controlled") is not True):
            return False
        # With windows, each window needs its own ordered pass (02 §12.3); a leg counts once.
        windows = step.get("windows") or [None]
        indexes = data.get("sequence_by_window")
        if (not isinstance(indexes, list) or len(indexes) != len(windows)
                or any(type(index) is not int or not 0 <= index <= len(targets) for index in indexes)):
            indexes = [0] * len(windows)
        for w, window in enumerate(windows):
            if (indexes[w] < len(targets) and event.get(key) == targets[indexes[w]]
                    and (window is None or _window_contains(window, event.get("game_minute")))):
                indexes[w] += 1
                break
        data["sequence_by_window"] = indexes
        return all(index == len(targets) for index in indexes)

    def _v2_travel_distance(self, state, step: dict, data: dict, event: dict) -> bool:
        distance = event.get("distance_m")
        if (event.get("zone_id") != step["zone_id"] or event.get("player_controlled") is not True
                or event.get("propulsion") not in step.get("propulsion", ("motor", "sail", "oar"))
                or not _finite_number(distance) or distance <= 0):
            return False
        data["distance_m"] = _amount(data.get("distance_m")) + distance
        return data["distance_m"] >= step["distance_m"]

    def _v2_anchor_idle(self, state, step: dict, data: dict, event: dict) -> bool:
        if not (event.get("zone_id") == step["zone_id"] and event.get("anchored") is True
                and event.get("engine_idle") is True):
            data["continuous_game_minutes"] = 0.0
            return False
        data["continuous_game_minutes"] = _amount(data.get("continuous_game_minutes")) + _amount(
            event.get("elapsed_game_minutes"))
        return data["continuous_game_minutes"] >= step["continuous_game_minutes"]

    def _v2_wait_weather(self, state, step: dict, data: dict, event: dict) -> bool:
        lake = event.get("lake_id")
        if "zone_id" in step:
            here = event.get("zone_id") == step["zone_id"]
        elif "zone_ids" in step:
            here = event.get("zone_id") in step["zone_ids"]
        elif "lake_id" in step:
            here = lake == step["lake_id"]
        else:
            here = any(lakes.in_place(area, lake, event.get("x"), event.get("z")) for area in step["area_ids"])
        if not (here and event.get("anchored") is True):
            # Drifting pauses the total without resetting it, and ends a wait for the change.
            data["waiting"] = False
            return False
        spans = event.get("weather_spans")
        if not isinstance(spans, list) or not spans:
            spans = [[event.get("weather"), event.get("elapsed_game_minutes")]]
        # A long sample (a catnap) can cross forecast changes; take its spans in order.
        for span in spans:
            if not isinstance(span, list) or len(span) != 2:
                continue
            weather, minutes = span
            if weather == step["weather"]:
                data["minutes"] = _amount(data.get("minutes")) + _amount(minutes)
                if "then_weather" not in step:
                    if data["minutes"] >= step.get("minutes", 30):
                        return True
                    continue
                data["waiting"] = True
            elif "then_weather" in step and weather == step["then_weather"] and data.get("waiting") is True:
                if _amount(data.get("minutes")) >= step.get("minutes", 0):
                    return True
                data["waiting"] = False
            else:
                data["waiting"] = False
        return False

    def _v2_fish_livewell(self, state, step: dict, data: dict, event: dict) -> bool:
        return (event.get("species_id") == step["species_id"]
                and event.get("source_zone_id") == step["zone_id"]
                and deployment_id(event.get("source_line_id")) is not None
                and (("bait_id" not in step) or (event.get("bait_id") == step["bait_id"]
                                                 and self._bait_sections_match(event, step["bait_id"])))
                and (("entry_window" not in step)
                     or _window_contains(step["entry_window"], event.get("entry_game_minute"))))

    def _v2_catch_species(self, state, step: dict, data: dict, event: dict) -> bool:
        species_id = event.get("species_id")
        if event.get("type") == "legendary.witnessed":
            # A legendary's record counts, caught or witnessed; a sighting has no catch details.
            if step.keys() & {"min_lb", "area_id", "time_band", "bait_id", "in_cold_band"}:
                return False
        else:
            hour = event.get("catch_hour")
            weight = event.get("weight_lb")
            if (("min_lb" in step and not (_finite_number(weight) and weight >= step["min_lb"]))
                    or ("area_id" in step and not lakes.in_place(step["area_id"], event.get("lake_id"),
                                                                 event.get("x"), event.get("z")))
                    or ("time_band" in step and not (_finite_number(hour) and band_of(hour) == step["time_band"]))
                    or ("bait_id" in step and event.get("bait_id") != step["bait_id"])
                    or (step.get("in_cold_band") and event.get("in_cold_band") is not True)):
                return False
        if (("zone_id" in step and event.get("zone_id") != step["zone_id"])
                or ("lake_id" in step and event.get("lake_id") != step["lake_id"])
                or not _fish_matches(step, species_id, event.get("legendary") is True)):
            return False
        if step.get("distinct"):
            caught = data.get("species")
            caught = [sid for sid in caught if isinstance(sid, str)] if isinstance(caught, list) else []
            if species_id not in caught:
                caught.append(species_id)
            data["species"] = caught
            return len(caught) >= step.get("count", 1)
        data["count"] = int(_amount(data.get("count"))) + 1
        return data["count"] >= step.get("count", 1)

    def _v2_book_stage(self, state, step: dict, data: dict, event: dict) -> bool:
        return book_goal_met(state, step)

    def _v2_cook_dish(self, state, step: dict, data: dict, event: dict) -> bool:
        return step.get("any") is True or event.get("dish_id") == step["dish_id"]

    def _v2_catnap(self, state, step: dict, data: dict, event: dict) -> bool:
        return "zone_id" not in step or event.get("zone_id") == step["zone_id"]

    def _v2_tool_use(self, state, step: dict, data: dict, event: dict) -> bool:
        return (event.get("tool_id") == step["tool_id"]
                and (("zone_id" not in step) or event.get("zone_id") == step["zone_id"])
                and (("lake_id" not in step) or event.get("lake_id") == step["lake_id"])
                and (("shell_id" not in step) or event.get("shell_id") == step["shell_id"]))

    def _v2_settle(self, state, step: dict, data: dict, event: dict) -> bool:
        cues = event.get("cues")
        return event.get("zone_id") == step["zone_id"] and type(cues) is int and cues >= step["cues"]

    def _v2_talk_to(self, state, step: dict, data: dict, event: dict) -> bool:
        if event.get("npc_id") != step["npc_id"] or not _finite_number(event.get("game_minute")):
            return False
        days = data.get("days")
        days = [day for day in days if type(day) is int] if isinstance(days, list) else []
        day = game_day(event["game_minute"])
        if day not in days:
            days.append(day)
        data["days"] = days
        return len(days) >= step.get("distinct_days", 1)

    def _v2_attend_event(self, state, step: dict, data: dict, event: dict) -> bool:
        # Be at that lake's landing during the event and hail its host.
        return (event.get("host_of") == step["lake_id"] == event.get("lake_id")
                and event.get("event") == step["event"] and event.get("at_landing") is True)


_STEP_EVENTS = {
    "line.set": ("line_scout", "line_check", "line_scout_check"),
    "bot.scout_complete": ("line_scout", "line_scout_check", "scout_report"),
    "line.check": ("line_check", "line_scout_check"),
    "fish.enter_livewell": ("fish_livewell",),
    "anchor.sample": ("anchor_idle", "wait_weather"),
    "boat.move": ("travel_distance",),
    "zone.enter": ("visit_zones", "visit_sequence"),
    "waypoint.enter": ("visit_zones", "visit_sequence"),
    "catch.resolved": ("catch_species",),
    "legendary.witnessed": ("catch_species",),
    "book.stage_up": ("book_stage",),
    "cook_dish": ("cook_dish",),
    "catnap.complete": ("catnap",),
    "tool.use": ("tool_use",),
    "settle.complete": ("settle",),
    "npc.hail": ("talk_to", "attend_event"),
}
_VISIT_EVENT = {"zone_id": "zone.enter", "waypoint_id": "waypoint.enter"}


def _amount(value) -> float:
    return value if _finite_number(value) and value >= 0 else 0.0


def _tier_rank(tier) -> int:
    return LINE_TIER_ORDER.index(tier) if tier in LINE_TIER_ORDER else -1


def _fish_matches(step: dict, species_id, legendary: bool) -> bool:
    if "species_id" in step:
        return species_id == step["species_id"]
    if "species_ids" in step:
        return species_id in step["species_ids"]
    if step.get("any") is True:
        return isinstance(species_id, str)
    species = SPECIES_BY_ID.get(species_id)
    if species is None or legendary:
        return False
    return species.food == step["group"] if "group" in step else step.get("tag") in species.tags


def game_day(minutes) -> int:
    """Game day d runs from 06:00 to 06:00 (minute 0 is 06:00 on day 0)."""
    return max(0, int(minutes // 1440)) if _finite_number(minutes) else 0


def steps_of(definition: dict) -> list:
    objective = definition["objective"]
    return objective if isinstance(objective, list) else [objective]


def current_step(definition: dict, progress) -> tuple[dict | None, dict]:
    """The active step and its own progress, which restarts for each step."""
    steps = steps_of(definition)
    index = progress.progress.get("step", 0)
    if type(index) is not int or not 0 <= index < len(steps):
        return None, {}
    data = progress.progress.get("data")
    if not isinstance(data, dict):
        data = progress.progress["data"] = {}
    progress.progress["step"] = index
    return steps[index], data


def book_goal_met(state, step: dict) -> bool:
    """N book entries at or above a stage: a goal on the book, checked as it grows."""
    from .book import book_stage
    wanted = BOOK_STAGE_ORDER.index(step["stage"])
    scope = step.get("species_ids") or LAKE_SPECIES_IDS.get(step.get("lake_id"), ())
    reached = 0
    for species_id in scope:
        record = state.journal.get(species_id)
        count = record.get("count", 0) if isinstance(record, dict) else 0
        if BOOK_STAGE_ORDER.index(book_stage(count)) >= wanted:
            reached += 1
    return reached >= step["count"]


def quest_status(state, quest_id: str) -> str:
    progress = state.narrative.quests.get(quest_id)
    return progress.status if progress is not None else "available"


def requirements_met(state, definition: dict) -> bool:
    """`requires`: a finished chapter, a completed quest and an open route, all that are listed."""
    from .fleet import chapter_finished
    requires = definition.get("requires") or {}
    return (("chapter_complete" not in requires or chapter_finished(state, requires["chapter_complete"]))
            and ("quest" not in requires or quest_status(state, requires["quest"]) == "completed")
            and ("travel_unlocked" not in requires or lakes.travel_unlocked(state, requires["travel_unlocked"])))


def chain(content, npc_id: str) -> list[str]:
    """A cat's quests with dialogue, in order: a host's errand, or a water-cat's A then B."""
    cat = content.cats.get(npc_id)
    if cat is not None:
        ids = cat["quests"]
    else:
        row = content.npcs.get(npc_id)
        ids = [row["quest_id"]] if row else []
    return [qid for qid in ids if "dialogue" in content.quests.get(qid, {})]


def quest_available(state, content, quest_id: str) -> bool:
    """On offer now. The V3 quests always are; quest B opens the game day after A is turned in."""
    definition = content.quests.get(quest_id)
    if definition is None or quest_status(state, quest_id) != "available":
        return False
    if "kind" not in definition:
        return True
    if not requirements_met(state, definition):
        return False
    if definition["kind"] == "b":
        cat = content.cats.get(definition["giver_id"], {})
        quests = cat.get("quests", [])
        before = quests[quests.index(quest_id) - 1] if quest_id in quests[1:] else None
        progress = state.narrative.quests.get(before) if before else None
        if progress is None or progress.status != "completed":
            return False
        if (progress.completed_game_minute is not None
                and game_day(progress.completed_game_minute) >= game_day(state.game_minutes)):
            return False
    return True


def current_quest(state, content, npc_id: str) -> str | None:
    """The quest a hail opens: the first not yet done, or the last done while the next isn't open."""
    done = None
    for quest_id in chain(content, npc_id):
        status = quest_status(state, quest_id)
        if status == "completed":
            done = quest_id
        elif status in ("active", "ready") or quest_available(state, content, quest_id):
            return quest_id
        else:
            return done
    return done


def friendship(state, content, npc_id: str) -> str | None:
    """Stranger, Acquaintance (quest A done) or Friend (quest B done), derived, never stored (02 §11.5)."""
    cat = content.cats.get(npc_id)
    if cat is None or cat["role"] != "water" or not cat["quests"]:
        return None
    statuses = [quest_status(state, qid) for qid in cat["quests"]]
    if len(statuses) > 1 and statuses[1] == "completed":
        return "friend"
    return "acquaintance" if statuses[0] == "completed" else "stranger"


def accept_quest(state, content, quest_id: str) -> bool:
    """Accept an offered quest. Objectives count only from here on."""
    definition = content.quests.get(quest_id)
    if definition is None or ("kind" in definition and not quest_available(state, content, quest_id)):
        return False
    progress = state.narrative.quest(quest_id)
    if progress is None or progress.status != "available":
        return False
    progress.status = "active"
    progress.accepted_game_minute = state.game_minutes
    progress.declined = False
    if "kind" in definition:
        progress.progress = {"step": 0, "data": {}}
        gift = definition.get("on_accept")
        if gift and state.narrative.record_accept_claim(quest_id):
            apply_reward(state, gift)
        QuestManager(content).begin_step(state, quest_id)
    return True


def apply_reward(state, reward: dict) -> None:
    """Credit every V1.0 reward kind (02 §12.1). The caller has already latched the claim."""
    from .botidentity import grant_shell
    from .data import BAIT_BY_ID
    v2 = state.v2
    cash = reward.get("cash", 0)
    if cash:
        state.money = round(state.money + cash, 2)
    for key, target in (("ripple_id", "ripples_v2"), ("keepsake_id", "keepsakes")):
        if reward.get(key):
            owned = v2.setdefault(target, [])
            if reward[key] not in owned:
                owned.append(reward[key])
    for key, target in (("recipes", "recipes"), ("dish_cards", "dishes_known"), ("unlocks", "unlocks")):
        owned = v2.setdefault(target, [])
        owned.extend(item for item in reward.get(key, ()) if item not in owned)
    for item_id, count in reward.get("items", {}).items():
        if item_id in BAIT_BY_ID:
            state.bait[item_id] = state.bait.get(item_id, 0) + count
        else:
            pantry = v2.setdefault("pantry", {})
            pantry[item_id] = pantry.get(item_id, 0) + count
    for shell_id in reward.get("shells", ()):
        grant_shell(state, shell_id)
