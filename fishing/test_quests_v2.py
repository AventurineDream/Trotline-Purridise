"""V1-31 quests v2: objective types and fields, steps, requires, rewards, friendship, turn-ins, letters.

Every objective type and field is driven by the events the game emits. Each counts
only after acceptance and is rewarded exactly once. These checks author their own rows
against the real roster, lakes and places; the shipped Briar and Cedar quests (V1-32)
are test_quests_briar_cedar's.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from .content import (BOOK_STAGE_ORDER, CONTENT_PATH, NAMED_PLACES, STEP_FIELDS, TIME_BANDS, WEATHER_STATES,
                      _TIER_HOOKS, ContentError, load_content, validate_content, validate_content_v2)
from .data import BAIT_BY_ID, CONTENT_V2_RAW, LINE_TIERS, band_of
from .dialogue import greeting, next_letter, open_conversation, record_hail
from .game import Keys, Session
from .lakes import in_place, place, travel_unlocked
from .narrative import QUEST_IDS, NarrativeState
from .npcs import NPC, cast, day_encounters, pinned
from .quests import QuestManager, accept_quest, current_quest, friendship, quest_available
from .sim import Catch, HeldLine, Hook, SetLine, State
from .world import World

LINES = {"offer": "Would you help me with something?", "done": "Thank you, {Skipper}."}
LINE_ID = str(UUID(int=31))
OTHER_LINE = str(UUID(int=32))
# The V3 bundle is a contract: its quests, rewards and dialogue never change.
NARRATIVE_V1_SHA256 = "864471fc486a334b76c860e338e4104f8ce335cdf39efc046b1f6ee55187aab5"


def quest(qid, kind, giver, lake, objective, reward=None, **extra):
    reward = reward if reward is not None else {
        "a": {"cash": 45, "ripple_id": "ripple_11"}, "b": {"cash": 68, "keepsake_id": f"ks_{giver}"},
        "host": {"cash": 120}, "story": {}}[kind]
    row = {"id": qid, "kind": kind, "giver_id": giver, "lake_id": lake, "title": qid.replace("_", " ").title(),
           "objective": objective, "journal": "Do the thing.", "reward": reward}
    if kind != "story":
        row["lines"] = dict(LINES)
    row.update(extra)
    return row


def raw_with(rows, cats=(), extends=()):
    """The shipped content_v2 with these quest rows, and registry rows for what they reward."""
    raw = deepcopy(CONTENT_V2_RAW)
    raw["quests.json"] = {"schema_version": 2, "quests": list(rows), "cats": list(cats), "extends": list(extends)}
    ripples = raw["ripples.json"]["ripples"]
    keepsakes = raw["keepsakes.json"]["keepsakes"]
    for row in rows:
        reward = row.get("reward") if isinstance(row, dict) else None
        if not isinstance(reward, dict):
            continue
        rid, kid = reward.get("ripple_id"), reward.get("keepsake_id")
        if isinstance(rid, str) and rid not in {r["id"] for r in ripples}:
            ripples.append({"id": rid, "text": "A ripple."})
        if (isinstance(kid, str) and kid.startswith("ks_") and kid not in {k["id"] for k in keepsakes}
                and kid[3:] in cast().names):
            keepsakes.append({"id": kid, "name": "A keepsake", "npc_id": kid[3:]})
    return raw


def content_with(rows, cats=()):
    return load_content(gameplay=validate_content_v2(raw_with(rows, cats)))


def errors(rows, cats=()):
    try:
        validate_content_v2(raw_with(rows, cats))
    except ContentError as exc:
        return [line for line in str(exc).splitlines() if line.startswith("quests.json")]
    return []


def centre(ref):
    row = place(ref)[1]
    return row["x"], row["z"]


class Harness:
    """A Briar state wired to a quest manager over authored rows."""

    def __init__(self, test, rows, cats=(), lake="briar"):
        self.content = content_with(rows, cats)
        self.state = State.new(test.worlds[lake], seed=73)
        self.manager = QuestManager(self.content)
        self.state._quest_event_handler = self.manager.handle_event
        self.events = []

    def emit(self, **event):
        event.setdefault("game_minute", self.state.game_minutes)
        self.state.emit_quest_event(event)

    def status(self, qid):
        progress = self.state.narrative.quests.get(qid)
        return progress.status if progress else "available"

    def accept(self, qid):
        assert accept_quest(self.state, self.content, qid), qid

    def ready(self, qid):
        progress = self.state.narrative.quests[qid]
        progress.status = "ready"


class Worlds(unittest.TestCase):
    worlds = {}

    @classmethod
    def setUpClass(cls):
        if not Worlds.worlds:
            Worlds.worlds.update({lake: World(lake) for lake in ("briar", "cedar", "flathead", "crater", "nebula")})
        cls.worlds = Worlds.worlds


class QuestData(Worlds):
    def test_the_twelve_v3_quests_keep_their_ids_and_definitions(self):
        self.assertEqual(hashlib.sha256(CONTENT_PATH.read_bytes()).hexdigest(), NARRATIVE_V1_SHA256)
        import json
        alone = validate_content(json.loads(CONTENT_PATH.read_text(encoding="utf-8")))
        merged = load_content()
        self.assertEqual(tuple(alone.quests), QUEST_IDS)
        for qid in QUEST_IDS:
            self.assertEqual(merged.quests[qid], alone.quests[qid])
            self.assertNotIn("kind", merged.quests[qid])
        # Only an extends row's recopied lines differ, in text only: q08's greeting and offer
        # (05 §6.2), and the V3 offer, progress and completion lines that stated rules, rewards
        # or numbers, recopied into each cat's voice (05 §0, V1-43).
        recopied = {f"{row['id']}:dialogue:{stage}" for row in CONTENT_V2_RAW["quests.json"]["extends"]
                    for stage in row["lines"]}
        rules = {"q01_tea_leaves_deep_holes": ("offer", "progress", "completion"),
                 "q02_lonely_star_current": ("offer", "progress", "completion"),
                 "q03_unstrung_line": ("offer", "progress", "completion"),
                 "q04_great_contour_chart": ("offer", "completion"),
                 "q05_moonlight_trotlines": ("offer", "progress", "completion"),
                 "q06_unrepeatable_sunrise": ("offer", "progress", "completion"),
                 "q07_art_of_the_nap": ("offer", "progress", "completion"),
                 "q08_channel_run": ("greeting", "offer", "progress", "completion"),
                 "q09_quiet_channel": ("offer", "progress", "completion"),
                 "q10_ballad_lonely_star": ("completion",),
                 "q11_deep_water_drift": ("offer", "progress", "completion"),
                 "q12_first_voyage": ("offer", "progress", "completion")}
        self.assertEqual(recopied, {f"{qid}:dialogue:{stage}" for qid, stages in rules.items()
                                    for stage in stages})
        for node_id, node in alone.dialogue.items():
            if node_id in recopied:
                self.assertNotEqual(merged.dialogue[node_id]["text"], node["text"])
                self.assertEqual({**merged.dialogue[node_id], "text": node["text"]}, node)
            else:
                self.assertEqual(merged.dialogue[node_id], node)
        self.assertEqual({nid for nid, node in merged.dialogue.items() if node["quest_id"] in QUEST_IDS},
                         set(alone.dialogue))
        self.assertEqual(merged.npcs, alone.npcs)
        self.assertEqual(set(merged.cats), set(cast().names))
        self.assertEqual(merged.cats["willow"]["quests"], ["q06_unrepeatable_sunrise", "wc_willow_b"])

    def test_mirrored_tables_match_their_sources(self):
        from .book import BOOK_STAGES
        from .weather import _WEATHER
        self.assertEqual(WEATHER_STATES, set(_WEATHER))
        self.assertEqual(BOOK_STAGE_ORDER, tuple(stage for _n, stage in sorted(BOOK_STAGES)))
        self.assertEqual(_TIER_HOOKS, {tier: row["hooks"] for tier, row in LINE_TIERS.items()})
        self.assertEqual(TIME_BANDS, {band_of(hour / 2) for hour in range(48)})

    def test_named_places_sit_on_their_water(self):
        for lake, expected in NAMED_PLACES.items():
            world = self.worlds[lake]
            for pid, kind in expected.items():
                ref = f"{lake}:{pid}"
                found = place(ref)
                with self.subTest(place=ref):
                    self.assertEqual(found[0], kind)
                    row = found[1]
                    if kind == "waypoint":
                        self.assertTrue(world.navigable(row["x"], row["z"]))
                        continue
                    # An area holds legal line water: off the landing, 0.9 m deep, a set midpoint.
                    legal = 0
                    for r in (row.get("inner_r", 0) + 3, (row["r"] + row.get("inner_r", 0)) / 2, row["r"] - 3):
                        for k in range(16):
                            x = row["x"] + r * math.sin(k * math.tau / 16)
                            z = row["z"] + r * math.cos(k * math.tau / 16)
                            legal += (in_place(ref, lake, x, z) and world.navigable(x, z)
                                      and float(world.depth(x, z)) >= 0.9
                                      and math.hypot(x - world.slip.ox, z - world.slip.oz) >= 50
                                      and world.zone_at(x, z) not in ("landing", "shore"))
                    self.assertGreaterEqual(legal, 12)
        self.assertEqual(self.worlds["cedar"].zone_at(*centre("cedar:marked_pool")), "rocks")
        self.assertEqual(self.worlds["nebula"].zone_at(*centre("nebula:calm_reflection")), "open")
        for i, zone in enumerate(("lilies", "cypress", "flats"), 1):
            self.assertEqual(self.worlds["crater"].zone_at(*centre(f"crater:safe_cove_{i}")), zone)
        for i in (1, 2, 3, 4):
            self.assertEqual(self.worlds["cedar"].zone_at(*centre(f"cedar:practice_buoy_{i}")), "lilies")

    def test_validator_accepts_every_type_and_field(self):
        rows = [
            quest("wc_marigold_a", "a", "marigold", "briar",
                  [{"type": "line_scout", "zone_id": "briar:deep", "min_tier": "prem", "bait_id": "liver",
                    "set_window": [1200, 240], "in_cold_band": True},
                   {"type": "line_check", "area_id": "briar:landing_edge", "tier_id": "heavy", "hook_count": 24,
                    "active_soak_game_minutes": 60},
                   {"type": "line_scout_check", "zone_id": "briar:rocks", "active_soak_game_minutes": 60},
                   {"type": "anchor_idle", "zone_id": "briar:cypress", "continuous_game_minutes": 30}]),
            quest("wc_marigold_b", "b", "marigold", "briar",
                  [{"type": "scout_report", "waypoint_ids": ["briar:reed_edge_1"], "windows": [[360, 600]]},
                   {"type": "fish_livewell", "zone_id": "briar:lilies", "species_id": "golden_shiner",
                    "bait_id": "worm", "entry_window": [300, 480]},
                   {"type": "travel_distance", "zone_id": "briar:open", "distance_m": 200, "propulsion": ["oar"]},
                   {"type": "visit_zones", "zone_ids": ["briar:rocks", "cedar:rocks"], "windows": [[0, 600]]}],
                  cross_lake=["cedar"], requires={"travel_unlocked": "cedar", "chapter_complete": 1,
                                                  "quest": "q01_tea_leaves_deep_holes"}),
            quest("wc_old_gus_a", "a", "old_gus", "briar",
                  [{"type": "visit_sequence", "waypoint_ids": ["briar:reed_edge_1", "briar:reed_edge_2"],
                    "windows": [[1140, 240]]},
                   {"type": "catch_species", "group": "panfish", "count": 3, "min_lb": 0.5, "zone_id": "briar:flats",
                    "area_id": "briar:landing_edge", "lake_id": "briar", "time_band": "dawn", "bait_id": "worm",
                    "in_cold_band": True},
                   {"type": "book_stage", "lake_id": "briar", "stage": "identified", "count": 10},
                   {"type": "cook_dish", "dish_id": "herbal_stew"}],
                  reward={"cash": 45, "ripple_id": "ripple_12", "recipes": ["pecan_smoked_shad"],
                          "items": {"dough": 12, "herbs": 1}},
                  on_accept={"items": {"dough": 12}}),
            quest("wc_old_gus_b", "b", "old_gus", "briar",
                  [{"type": "catnap", "zone_id": "briar:cypress"},
                   {"type": "tool_use", "tool_id": "reed_anchor", "zone_id": "briar:reeds", "lake_id": "briar",
                    "shell_id": "frog"},
                   {"type": "wait_weather", "weather": "fog", "then_weather": "clear",
                    "area_ids": ["briar:landing_edge"], "minutes": 10},
                   {"type": "talk_to", "npc_id": "willow", "distinct_days": 3}]),
            quest("story_c5_s2", "story", "astra_9", "nebula",
                  [{"type": "settle", "zone_id": "nebula:open", "cues": 3},
                   {"type": "attend_event", "lake_id": "nebula", "event": "cookout"},
                   {"type": "catch_species", "species_ids": ["solar_sunfish", "lunar_loach"], "count": 2,
                    "distinct": True},
                   {"type": "catch_species", "species_id": "spillway_monster"}],
                  reward={"shells": ["astral"], "dish_cards": ["herbal_stew"], "unlocks": ["travel:nebula",
                                                                                         "chart:reed_passage"]},
                  cross_lake=["cedar"]),
            quest("host_flathead", "host", "captain_huckleberry", "flathead",
                  {"type": "cook_dish", "any": True}),
            quest("story_c0_s1", "story", "grandmother_whiskers", "briar",
                  [{"type": "line_set", "zone_id": "briar:open", "tier_id": "std", "hook_count": 12,
                    "bait_id": "worm", "set_window": [360, 720], "in_cold_band": True},
                   {"type": "scout_report", "lake_id": "briar"}]),
        ]
        rows[4]["objective"][3]["zone_id"] = "cedar:rocks"
        cats = [{"id": "marigold", "greetings": {"stranger": "Hello!", "friend": ["Hi again!", "Swim?"],
                                                 "weather:drizzle": "My ears!", "after_ch2": "Big news?"},
                 "letters": ["Dear Skipper, a. — M", "Dear Skipper, b. — M", "Dear Skipper, c. — M"]}]
        self.assertEqual(errors(rows, cats), [])
        covered = {step["type"] for row in rows for step in
                   (row["objective"] if isinstance(row["objective"], list) else [row["objective"]])}
        self.assertEqual(covered, set(STEP_FIELDS))
        used = {(step["type"], key) for row in rows for step in
                (row["objective"] if isinstance(row["objective"], list) else [row["objective"]])
                for key in step if key != "type"}
        # Every field of 02 §12.3 appears at least once, apart from alternatives exercised below.
        alternatives = {("catch_species", "species_id"), ("catch_species", "species_ids"), ("catch_species", "tag"),
                        ("catch_species", "any"), ("catch_species", "distinct"), ("book_stage", "species_ids"),
                        ("scout_report", "zone_id"), ("scout_report", "lake_id"), ("line_set", "area_id"),
                        ("line_set", "min_tier"), ("visit_zones", "waypoint_ids"), ("visit_sequence", "zone_ids"),
                        ("wait_weather", "zone_id"), ("wait_weather", "zone_ids"), ("wait_weather", "lake_id"),
                        ("cook_dish", "any"), ("line_scout", "area_id"), ("line_scout", "tier_id"),
                        ("line_scout", "hook_count"), ("line_check", "zone_id"), ("line_check", "min_tier"),
                        ("line_check", "bait_id"), ("line_check", "set_window"), ("line_check", "in_cold_band"),
                        ("line_scout_check", "area_id"), ("line_scout_check", "tier_id"),
                        ("line_scout_check", "min_tier"), ("line_scout_check", "hook_count"),
                        ("line_scout_check", "bait_id"), ("line_scout_check", "set_window"),
                        ("line_scout_check", "in_cold_band")}
        self.assertEqual({(kind, key) for kind, fields in STEP_FIELDS.items() for key in fields}
                         - used - alternatives, set())

    def test_validator_rejects_unlisted_fields(self):
        examples = {
            "line_set": {"area_id": "briar:landing_edge"}, "line_scout": {"zone_id": "briar:deep"}, "line_check": {"zone_id": "briar:deep",
                                                                    "active_soak_game_minutes": 60},
            "line_scout_check": {"zone_id": "briar:deep", "active_soak_game_minutes": 60},
            "anchor_idle": {"zone_id": "briar:deep", "continuous_game_minutes": 30},
            "scout_report": {"zone_id": "briar:deep"},
            "fish_livewell": {"zone_id": "briar:lilies", "species_id": "bluegill"},
            "travel_distance": {"zone_id": "briar:open", "distance_m": 100},
            "visit_zones": {"zone_ids": ["briar:rocks"]}, "visit_sequence": {"zone_ids": ["briar:rocks"]},
            "catch_species": {"any": True}, "book_stage": {"lake_id": "briar", "stage": "identified", "count": 1},
            "cook_dish": {"any": True}, "catnap": {}, "tool_use": {"tool_id": "wave_chime"},
            "wait_weather": {"weather": "fog", "lake_id": "briar"}, "settle": {"zone_id": "briar:open", "cues": 3},
            "talk_to": {"npc_id": "willow"}, "attend_event": {"lake_id": "briar", "event": "cookout"},
        }
        self.assertEqual(set(examples), set(STEP_FIELDS))
        for kind, fields in examples.items():
            step = {"type": kind, **fields}
            with self.subTest(kind=kind):
                self.assertEqual(errors([quest("wc_marigold_a", "a", "marigold", "briar", step)]), [])
                # A misspelling, a V3-only literal and another type's field are all rejected.
                for extra in ("zone", "scout_range_lt_m", "distance_m" if kind != "travel_distance" else "cues"):
                    found = errors([quest("wc_marigold_a", "a", "marigold", "briar", {**step, extra: 1})])
                    self.assertTrue(any(f"unknown field {extra!r} for {kind}" in line for line in found), found)
        for extra in ("after", "extends", "pins"):
            found = errors([quest("wc_marigold_a", "a", "marigold", "briar", examples["catnap"] | {"type": "catnap"},
                                  **{extra: 1})])
            self.assertTrue(any(f"unknown field {extra!r}" in line for line in found), found)

    def test_validator_rejects_bad_rows_without_crashing(self):
        catnap = {"type": "catnap"}
        cases = [
            ("expected 'wc_marigold_a'", [quest("wc_marigold_x", "a", "marigold", "briar", catnap)], []),
            ("collides with a V3 quest", [quest("q03_unstrung_line", "a", "elder_moss", "briar", catnap)], []),
            ("given by a water cat", [quest("wc_grandmother_whiskers_a", "a", "grandmother_whiskers", "briar",
                                            catnap)], []),
            ("roster quests", [quest("host_briar", "host", "grandmother_whiskers", "briar", catnap)], []),
            ("own lake", [quest("wc_marigold_a", "a", "marigold", "cedar", catnap)], []),
            ("list it in cross_lake", [quest("wc_marigold_a", "a", "marigold", "briar",
                                             {"type": "visit_zones", "zone_ids": ["cedar:rocks"]})], []),
            ("is not another lake a step uses", [quest("wc_marigold_a", "a", "marigold", "briar", catnap,
                                                       cross_lake=["cedar"])], []),
            ("unknown zone 'briar:springs'", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                    {"type": "catnap", "zone_id": "briar:springs"})], []),
            ("unknown area 'briar:reed_edge_1'", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                        {"type": "line_scout", "area_id": "briar:reed_edge_1"})], []),
            ("clock minutes", [quest("wc_marigold_a", "a", "marigold", "briar",
                                     {"type": "scout_report", "zone_id": "briar:deep", "windows": [[360, 1440]]})],
             []),
            ("more entries than the 36", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                {"type": "book_stage", "lake_id": "briar", "stage": "identified",
                                                 "count": 40})], []),
            ("exactly one of tier_id, min_tier", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                        {"type": "line_scout", "zone_id": "briar:deep",
                                                         "tier_id": "std", "min_tier": "std"})], []),
            ("needs tier_id", [quest("wc_marigold_a", "a", "marigold", "briar",
                                     {"type": "line_scout", "zone_id": "briar:deep", "hook_count": 12})], []),
            ("does not match line tier", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                {"type": "line_scout", "zone_id": "briar:deep", "tier_id": "std",
                                                 "hook_count": 18})], []),
            ("must differ from weather", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                {"type": "wait_weather", "weather": "fog", "then_weather": "fog",
                                                 "lake_id": "briar"})], []),
            ("unknown value/reference 'rain'", [quest("wc_marigold_a", "a", "marigold", "briar",
                                                      {"type": "wait_weather", "weather": "rain",
                                                       "lake_id": "briar"})], []),
            ("expected 1–4 steps", [quest("wc_marigold_a", "a", "marigold", "briar", [catnap] * 5)], []),
            ("missing required field 'lines'", [{k: v for k, v in quest("wc_marigold_a", "a", "marigold", "briar",
                                                                       catnap).items() if k != "lines"}], []),
            ("longer than 140", [quest("wc_marigold_a", "a", "marigold", "briar", catnap,
                                       lines={"offer": "x" * 141, "done": "Thanks."})], []),
            ("unknown placeholder {Name}", [quest("wc_marigold_a", "a", "marigold", "briar", catnap,
                                                  lines={"offer": "Hi {Name}.", "done": "Thanks."})], []),
            ("host errands pay cash only", [quest("host_flathead", "host", "captain_huckleberry", "flathead",
                                                  catnap, reward={"cash": 5, "ripple_id": "ripple_20"})], []),
            ("rewards 'ripple_id'", [quest("wc_marigold_a", "a", "marigold", "briar", catnap,
                                           reward={"cash": 45})], []),
            ("already given by 'wc_marigold_a'", [quest("wc_marigold_a", "a", "marigold", "briar", catnap),
                                                  quest("wc_old_gus_a", "a", "old_gus", "briar", catnap)], []),
            ("expected 'ks_marigold'", [quest("wc_marigold_b", "b", "marigold", "briar", catnap,
                                              reward={"cash": 68, "keepsake_id": "ks_old_gus"})], []),
            ("expected travel:, chart:, area: or shop:", [quest("story_c1_s1", "story", "pip_pebble", "briar",
                                                                 catnap, reward={"unlocks": ["boat:sub"]})], []),
            ("unknown bait or pantry item", [quest("wc_marigold_a", "a", "marigold", "briar", catnap,
                                                   on_accept={"items": {"gold": 1}})], []),
            ("unknown field 'season'", [quest("wc_marigold_a", "a", "marigold", "briar", catnap,
                                              requires={"season": "fall"})], []),
            ("unknown value/reference 'bedtime'", [], [{"id": "marigold", "greetings": {"bedtime": "Hi."}}]),
            ("one to three letter variants", [], [{"id": "marigold", "greetings": {"day": "Hi."},
                                                    "letters": ["a", "b", "c", "d"]}]),
            ("they don't write them", [], [{"id": "pounce", "greetings": {"day": "Hi."}, "letters": ["a", "b", "c"]}]),
            ("expected 2–5 parts", [], [{"id": "marigold", "greetings": {"day": "Hi."}, "story": ["Once."]}]),
            ("travelers don't tell stories", [], [{"id": "thistle", "greetings": {"day": "Hi."},
                                                   "story": ["Once.", "Twice."]}]),
            ("expected story_c<chapter>_s<step>", [quest("story_9", "story", "pip_pebble", "briar", catnap)], []),
        ]
        for message, rows, cats in cases:
            with self.subTest(message=message):
                found = errors(rows, cats)
                self.assertTrue(any(message in line for line in found), found)
        # Recopied V3 lines (V1-32) and the Ripple and keepsake registries.
        for message, extends in (
                ("names a V3 quest in both id and extends", [{"id": "wc_kit_a", "extends": "wc_kit_a",
                                                               "lines": {"offer": "Hi."}}]),
                ("names a V3 quest in both id and extends", [{"id": "q08_channel_run", "extends": "q09_quiet_channel",
                                                               "lines": {"offer": "Hi."}}]),
                ("unknown value/reference 'done'", [{"id": "q08_channel_run", "extends": "q08_channel_run",
                                                     "lines": {"done": "Hi."}}]),
                ("holds one text", [{"id": "q08_channel_run", "extends": "q08_channel_run",
                                     "lines": {"offer": ["Hi.", "There."]}}])):
            with self.subTest(message=message):
                try:
                    validate_content_v2(raw_with([], extends=extends))
                    found = []
                except ContentError as exc:
                    found = str(exc).splitlines()
                self.assertTrue(any(message in line for line in found), found)
        raw = raw_with([quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"})])
        raw["ripples.json"]["ripples"] = [r for r in raw["ripples.json"]["ripples"] if r["id"] != "ripple_11"]
        raw["keepsakes.json"]["keepsakes"].append({"id": "ks_willow", "name": "Misty watercolor", "npc_id": "kit"})
        raw["ripples.json"]["ripples"].append({"id": "ripple_10", "text": "Old."})
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(raw)
        for message in ("'ripple_11' is not in ripples.json", "expected 'ks_kit'", "expected ripple_11 to ripple_44"):
            self.assertIn(message, str(caught.exception))
        # Ill-typed values are reported, never raised.
        weird = quest("wc_marigold_a", "a", "marigold", "briar", {"type": ["catnap"]}, reward=[1])
        weird["kind"], weird["lake_id"], weird["requires"] = {"a": 1}, ["briar"], {"quest": ["x"]}
        self.assertTrue(errors([weird]))
        self.assertTrue(errors([quest("wc_marigold_a", "a", "marigold", "briar",
                                      {"type": "visit_zones", "zone_ids": [["briar:rocks"]]})]))


class ObjectiveTypes(Worlds):
    """One authored quest per type: events before acceptance don't count, and it pays once."""

    def check(self, step, events, *, giver="marigold", lake="briar", qid=None, kind="a", short=1, **row):
        qid = qid or f"wc_{giver}_{kind}"
        h = Harness(self, [quest(qid, kind, giver, lake, step, **row)])
        for event in events:
            h.emit(**event)
        self.assertEqual(h.status(qid), "available", "an event before acceptance counted")
        h.state.game_minutes += 1
        h.accept(qid)
        for event in events[:len(events) - short]:
            h.emit(**{**event, "game_minute": h.state.game_minutes})
        self.assertEqual(h.status(qid), "active")
        for event in events[len(events) - short:]:
            h.emit(**{**event, "game_minute": h.state.game_minutes})
        self.assertEqual(h.status(qid), "ready")
        # Exactly once: the giver's turn-in latches the claim, and nothing pays twice.
        from .dialogue import _claim_and_pay
        before = h.state.money
        self.assertTrue(_claim_and_pay(h.state, h.content, qid))
        paid = h.state.money - before
        self.assertFalse(_claim_and_pay(h.state, h.content, qid))
        ledger = NarrativeState.from_json(h.state.narrative.to_json())
        self.assertEqual(ledger.quests[qid].status, "completed")
        self.assertIn(qid, ledger.reward_claims)
        self.assertFalse(ledger.record_reward_claim(qid))
        self.assertEqual(h.state.money, before + paid)
        return h

    def line_events(self, lake, zone, **set_fields):
        set_event = {"type": "line.set", "lake_id": lake, "line_id": LINE_ID, "zone_id": zone, "tier_id": "prem",
                     "hook_count": 18, "bait_id": "liver", "bait_sections": ["liver"], "active_game_minute": 10,
                     "x": 0.0, "z": 0.0, "in_cold_band": False, **set_fields}
        scout = {"type": "bot.scout_complete", "lake_id": lake, "target_line_id": LINE_ID, "zone_id": zone,
                 "depth_class": "deep", "report_delivered": True, "x": 0.0, "z": 0.0}
        check = {"type": "line.check", "lake_id": lake, "zone_id": zone, "line_id": LINE_ID,
                 "active_game_minute": 70}
        return set_event, scout, check

    def test_line_scout(self):
        set_event, scout, _check = self.line_events("briar", "briar:deep")
        self.check({"type": "line_scout", "zone_id": "briar:deep"}, [set_event, scout])

    def test_line_check(self):
        set_event, _scout, check = self.line_events("briar", "briar:deep")
        self.check({"type": "line_check", "zone_id": "briar:deep", "active_soak_game_minutes": 60},
                   [set_event, {**check, "active_game_minute": 69}, check])
        # Without a soak time (V1-33), any check of the set line counts, even a moment later.
        self.check({"type": "line_check", "zone_id": "briar:deep", "in_cold_band": True},
                   [{**set_event, "in_cold_band": True}, {**check, "active_game_minute": 10.5}])

    def test_line_scout_check_needs_the_report_before_the_check(self):
        set_event, scout, check = self.line_events("briar", "briar:deep")
        h = self.check({"type": "line_scout_check", "zone_id": "briar:deep", "active_soak_game_minutes": 60},
                       [set_event, check, scout, check])
        self.assertTrue(h.state.narrative.quests["wc_marigold_a"].progress["data"]["deployments"][LINE_ID]["scouted"])

    def test_anchor_idle(self):
        sample = {"type": "anchor.sample", "lake_id": "briar", "zone_id": "briar:cypress", "anchored": True,
                  "engine_idle": True, "elapsed_game_minutes": 20.0, "weather": "clear", "x": 0.0, "z": 0.0}
        self.check({"type": "anchor_idle", "zone_id": "briar:cypress", "continuous_game_minutes": 40},
                   [sample, sample])

    def test_scout_report(self):
        report = {"type": "bot.scout_complete", "lake_id": "briar", "zone_id": "briar:rocks",
                  "depth_class": "middling", "report_delivered": True, "x": 0.0, "z": 0.0}
        self.check({"type": "scout_report", "zone_id": "briar:rocks"}, [report], short=1)

    def test_fish_livewell(self):
        entry = {"type": "fish.enter_livewell", "species_id": "bluegill", "source_line_id": LINE_ID,
                 "lake_id": "briar", "source_zone_id": "briar:flats", "bait_id": "worm", "bait_sections": ["worm"]}
        h = Harness(self, [quest("wc_marigold_a", "a", "marigold", "briar",
                                 {"type": "fish_livewell", "zone_id": "briar:flats", "species_id": "bluegill"})])
        h.emit(**entry, entry_game_minute=0)
        h.state.game_minutes = 5
        h.accept("wc_marigold_a")
        h.emit(**entry, entry_game_minute=4)
        self.assertEqual(h.status("wc_marigold_a"), "active")
        h.emit(**entry, entry_game_minute=6)
        self.assertEqual(h.status("wc_marigold_a"), "ready")

    def test_travel_distance(self):
        move = {"type": "boat.move", "lake_id": "briar", "zone_id": "briar:open", "distance_m": 120.0,
                "player_controlled": True, "propulsion": "oar"}
        self.check({"type": "travel_distance", "zone_id": "briar:open", "distance_m": 200}, [move, move])

    def test_visit_zones(self):
        enters = [{"type": "zone.enter", "lake_id": "briar", "zone_id": zone, "movement_cause": "boat",
                   "player_controlled": True} for zone in ("briar:rocks", "briar:inlet")]
        self.check({"type": "visit_zones", "zone_ids": ["briar:inlet", "briar:rocks"]}, enters)

    def test_visit_sequence(self):
        enters = [{"type": "zone.enter", "lake_id": "briar", "zone_id": zone, "movement_cause": "boat",
                   "player_controlled": True} for zone in ("briar:rocks", "briar:inlet")]
        self.check({"type": "visit_sequence", "zone_ids": ["briar:rocks", "briar:inlet"]}, enters)

    def test_catch_species(self):
        catch = {"type": "catch.resolved", "species_id": "bluegill", "legendary": False, "kept": True,
                 "lake_id": "briar", "zone_id": "briar:flats", "x": 0.0, "z": 0.0, "bait_id": "worm",
                 "weight_lb": 0.4, "catch_hour": 9.0, "in_cold_band": False}
        self.check({"type": "catch_species", "any": True, "count": 2}, [catch, {**catch, "kept": False}])

    def test_book_stage(self):
        h = Harness(self, [quest("wc_marigold_b", "b", "marigold", "briar",
                                 {"type": "book_stage", "species_ids": ["bluegill", "crappie"],
                                  "stage": "identified", "count": 2})])
        h.state.narrative.quest("wc_marigold_a").status = "completed"
        h.state.game_minutes = 1500
        h.state.journal["bluegill"]["count"] = 1
        h.emit(type="book.stage_up", species_id="bluegill", stage="identified")
        h.accept("wc_marigold_b")
        self.assertEqual(h.status("wc_marigold_b"), "active")
        h.state.journal["crappie"]["count"] = 1
        h.emit(type="book.stage_up", species_id="crappie", stage="identified")
        self.assertEqual(h.status("wc_marigold_b"), "ready")

    def test_cook_dish(self):
        self.check({"type": "cook_dish", "dish_id": "herbal_stew"},
                   [{"type": "cook_dish", "dish_id": "pan_fritters", "lake_id": "briar"},
                    {"type": "cook_dish", "dish_id": "herbal_stew", "lake_id": "briar"}][1:])

    def test_catnap(self):
        self.check({"type": "catnap", "zone_id": "briar:cypress"},
                   [{"type": "catnap.complete", "lake_id": "briar", "zone_id": "briar:cypress"}])

    def test_tool_use(self):
        self.check({"type": "tool_use", "tool_id": "wave_chime"},
                   [{"type": "tool.use", "tool_id": "wave_chime", "lake_id": "briar", "zone_id": "briar:deep",
                     "shell_id": "duck"}])

    def test_wait_weather(self):
        sample = {"type": "anchor.sample", "lake_id": "briar", "zone_id": "briar:lilies", "anchored": True,
                  "engine_idle": True, "elapsed_game_minutes": 20.0, "weather": "mist", "x": 0.0, "z": 0.0}
        self.check({"type": "wait_weather", "weather": "mist", "zone_id": "briar:lilies"}, [sample, sample])

    def test_settle(self):
        self.check({"type": "settle", "zone_id": "nebula:open", "cues": 3},
                   [{"type": "settle.complete", "lake_id": "nebula", "zone_id": "nebula:open", "cues": 3}],
                   giver="astra_9", lake="nebula", qid="story_c5_s2", kind="story")

    def test_talk_to(self):
        self.check({"type": "talk_to", "npc_id": "willow"},
                   [{"type": "npc.hail", "npc_id": "willow", "lake_id": "briar"}])

    def test_attend_event(self):
        self.check({"type": "attend_event", "lake_id": "briar", "event": "cookout"},
                   [{"type": "npc.hail", "npc_id": "grandmother_whiskers", "lake_id": "briar",
                     "host_of": "briar", "event": "cookout", "at_landing": True}])


class ObjectiveFields(Worlds):
    """Each field narrows what counts; the event that differs in only that field must not."""

    def one(self, step, good, bad, *, giver="marigold", lake="briar", qid="wc_marigold_a", **row):
        """`good` is one event or a sequence that completes the step (None: nothing can);
        `bad` is one event, or a list of events or sequences that each must not."""
        runs = [(sequence, "active") for sequence in (bad if isinstance(bad, list) else [bad])]
        if good is not None:
            runs.append((good, "ready"))
        for sequence, expected in runs:
            sequence = sequence if isinstance(sequence, list) else [sequence]
            h = Harness(self, [quest(qid, "a" if qid.endswith("_a") else "story", giver, lake, step, **row)])
            h.state.game_minutes = 10
            h.accept(qid)
            for event in sequence:
                h.emit(**event)
            with self.subTest(step=step, events=sequence, expected=expected):
                self.assertEqual(h.status(qid), expected)

    def line(self, step, good_set, bad_sets, check_overrides=None):
        def events(fields):
            set_event = {"type": "line.set", "lake_id": fields.pop("lake_id", "briar"), "line_id": LINE_ID,
                         "zone_id": "briar:deep", "tier_id": "prem", "hook_count": 18, "bait_id": "liver",
                         "bait_sections": ["liver"], "active_game_minute": 10, "x": 0.0, "z": 0.0,
                         "in_cold_band": False, "game_minute": 20}
            set_event.update(fields)
            check = {"type": "line.check", "lake_id": set_event["lake_id"], "zone_id": set_event["zone_id"],
                     "line_id": LINE_ID, "active_game_minute": 70, **(check_overrides or {})}
            return [set_event, check]
        step = {"type": "line_check", "active_soak_game_minutes": 60, **step}
        self.one(step, events(dict(good_set)), [events(dict(bad)) for bad in bad_sets])

    def test_line_zone_area_tier_hooks_bait_window_and_cold_band(self):
        self.line({"zone_id": "briar:deep"}, {}, [{"zone_id": "briar:rocks"}])
        pool = centre("cedar:marked_pool")
        row = {"lake_id": "cedar", "zone_id": "cedar:rocks", "x": pool[0], "z": pool[1]}
        self.one({"type": "line_check", "area_id": "cedar:marked_pool", "active_soak_game_minutes": 60},
                 [{"type": "line.set", "line_id": LINE_ID, "tier_id": "std", "active_game_minute": 10,
                   "bait_sections": ["shad"], **row},
                  {"type": "line.check", "lake_id": "cedar", "zone_id": "cedar:rocks", "line_id": LINE_ID,
                   "active_game_minute": 70}],
                 [[{"type": "line.set", "line_id": LINE_ID, "tier_id": "std", "active_game_minute": 10,
                    "bait_sections": ["shad"], **row, "x": pool[0] + 60},
                   {"type": "line.check", "lake_id": "cedar", "zone_id": "cedar:rocks", "line_id": LINE_ID,
                    "active_game_minute": 70}]],
                 giver="hank_mudpaw", lake="cedar", qid="wc_hank_mudpaw_a")
        self.line({"zone_id": "briar:deep", "tier_id": "prem", "hook_count": 18}, {},
                  [{"tier_id": "heavy", "hook_count": 24}, {"hook_count": 12}])
        self.line({"zone_id": "briar:deep", "min_tier": "prem"}, {"tier_id": "heavy"}, [{"tier_id": "std"}])
        self.line({"zone_id": "briar:deep", "bait_id": "liver"}, {},
                  [{"bait_sections": ["liver", "worm"], "bait_id": None}, {"bait_sections": ["worm"], "bait_id": "worm"}])
        # 20:00-04:00 on the clock is game minutes 840-1320 each day.
        self.line({"zone_id": "briar:deep", "set_window": [1200, 240]}, {"game_minute": 900},
                  [{"game_minute": 20}, {"game_minute": 1330}])
        self.line({"zone_id": "briar:deep", "in_cold_band": True}, {"in_cold_band": True}, [{"in_cold_band": False}])
        # The check must follow the full soak, on the same line, lake and zone it was set in.
        set_event = {"type": "line.set", "lake_id": "briar", "line_id": LINE_ID, "zone_id": "briar:deep",
                     "tier_id": "std", "bait_sections": ["worm"], "active_game_minute": 10, "x": 0.0, "z": 0.0}
        check = {"type": "line.check", "lake_id": "briar", "zone_id": "briar:deep", "line_id": LINE_ID,
                 "active_game_minute": 70}
        self.one({"type": "line_check", "zone_id": "briar:deep", "active_soak_game_minutes": 60},
                 [set_event, check],
                 [[set_event, {**check, "active_game_minute": 69}], [set_event, {**check, "line_id": OTHER_LINE}],
                  [set_event, {**check, "zone_id": "briar:rocks"}], [set_event, {**check, "lake_id": "cedar"}]])

    def test_scout_report_waypoints_and_windows_each_need_their_own_report(self):
        def report(ref, minute=400):
            x, z = centre(ref)
            return {"type": "bot.scout_complete", "lake_id": ref.split(":")[0], "zone_id": "briar:open",
                    "depth_class": "middling", "report_delivered": True, "x": x, "z": z, "game_minute": minute}
        refs = ["briar:reed_edge_1", "briar:reed_edge_2", "briar:reed_edge_3"]
        step = {"type": "scout_report", "waypoint_ids": refs}
        self.one(step, [report(ref) for ref in refs],
                 [[report(refs[0]), report(refs[0]), report(refs[1])],
                  [report(refs[0]), report(refs[1]), {**report(refs[2]), "x": centre(refs[2])[0] + 40}]])
        # Two windows on one zone: 06:00-10:00 and 14:00-18:00 (chapter 3's two readings).
        zone_report = {**report(refs[0]), "zone_id": "briar:deep"}
        step = {"type": "scout_report", "zone_id": "briar:deep", "windows": [[360, 600], [840, 1080]]}
        self.one(step, [{**zone_report, "game_minute": 60}, {**zone_report, "game_minute": 540}],
                 [[{**zone_report, "game_minute": 60}, {**zone_report, "game_minute": 120}],
                  [{**zone_report, "game_minute": 60}, {**zone_report, "game_minute": 300}]])

    def test_visit_zones_across_lakes_and_waypoints(self):
        def enter(zone, **extra):
            return {"type": "zone.enter", "lake_id": zone.split(":")[0], "zone_id": zone, "movement_cause": "boat",
                    "player_controlled": True, **extra}
        step = {"type": "visit_zones", "zone_ids": ["briar:rocks", "flathead:open"]}
        self.one(step, [enter("briar:rocks"), enter("flathead:open")],
                 [[enter("briar:rocks"), enter("cedar:open")]], cross_lake=["flathead"])
        points = [f"cedar:practice_buoy_{i}" for i in (1, 2)]
        waypoint = [{"type": "waypoint.enter", "lake_id": "cedar", "waypoint_id": ref, "movement_cause": "boat",
                     "player_controlled": True} for ref in points]
        self.one({"type": "visit_zones", "waypoint_ids": points}, waypoint,
                 [[waypoint[0], waypoint[0]], [enter("cedar:lilies"), waypoint[1]]],
                 giver="hank_mudpaw", lake="cedar", qid="wc_hank_mudpaw_a")
        self.one({"type": "visit_zones", "zone_ids": ["briar:rocks"], "windows": [[1200, 240]]},
                 [enter("briar:rocks", game_minute=900)], [[enter("briar:rocks", game_minute=60)]])

    def test_visit_sequence_order_provenance_and_windows(self):
        points = [f"cedar:lamp_buoy_{i}" for i in (1, 2, 3)]

        def at(ref, minute=900, **extra):
            return {"type": "waypoint.enter", "lake_id": "cedar", "waypoint_id": ref, "movement_cause": "boat",
                    "player_controlled": True, "game_minute": minute, **extra}
        step = {"type": "visit_sequence", "waypoint_ids": points, "windows": [[1140, 240]]}
        self.one(step, [at(points[0]), at(points[2]), at(points[1]), at(points[2])],
                 [[at(points[0]), at(points[2]), at(points[1])],
                  [at(points[0]), at(points[1]), at(points[2], player_controlled=False)],
                  [at(points[0]), at(points[1]), at(points[2], minute=600)]],
                 giver="senora_luz", lake="cedar", qid="wc_senora_luz_a")
        # Two windows need two ordered passes, one inside each; a leg never counts for both.
        step = {"type": "visit_sequence", "waypoint_ids": points[:2], "windows": [[360, 600], [840, 1080]]}
        self.one(step, [at(points[0], 60), at(points[1], 60), at(points[0], 540), at(points[1], 540)],
                 [[at(points[0], 60), at(points[1], 60)],
                  [at(points[0], 60), at(points[1], 60), at(points[0], 60), at(points[1], 60)],
                  [at(points[0], 60), at(points[1], 540), at(points[0], 540)]],
                 giver="senora_luz", lake="cedar", qid="wc_senora_luz_a")

    def test_travel_distance_zone_propulsion_and_control(self):
        move = {"type": "boat.move", "lake_id": "briar", "zone_id": "briar:open", "distance_m": 150.0,
                "player_controlled": True, "propulsion": "oar"}
        step = {"type": "travel_distance", "zone_id": "briar:open", "distance_m": 100, "propulsion": ["oar"]}
        self.one(step, move, [{**move, "propulsion": "motor"}, {**move, "zone_id": "briar:deep"},
                              {**move, "player_controlled": False}])

    def test_catch_species_filters(self):
        lantern_x, lantern_z = centre("briar:landing_edge")
        catch = {"type": "catch.resolved", "species_id": "bluegill", "legendary": False, "kept": False,
                 "lake_id": "briar", "zone_id": "briar:flats", "x": lantern_x + 100, "z": lantern_z,
                 "bait_id": "worm", "weight_lb": 0.6, "catch_hour": 6.0, "in_cold_band": True}
        cases = [
            ({"species_id": "bluegill"}, catch, {**catch, "species_id": "crappie"}),
            ({"group": "panfish"}, catch, {**catch, "species_id": "channel"}),
            ({"tag": "surface"}, catch, {**catch, "species_id": "channel"}),
            ({"any": True}, catch, {**catch, "species_id": 7}),
            ({"any": True, "min_lb": 0.5}, catch, {**catch, "weight_lb": 0.4}),
            ({"any": True, "zone_id": "briar:flats"}, catch, {**catch, "zone_id": "briar:deep"}),
            ({"any": True, "area_id": "briar:landing_edge"}, catch, {**catch, "x": lantern_x + 20}),
            ({"any": True, "lake_id": "briar"}, catch, {**catch, "lake_id": "cedar"}),
            ({"any": True, "time_band": "dawn"}, catch, {**catch, "catch_hour": 12.0}),
            ({"any": True, "bait_id": "worm"}, catch, {**catch, "bait_id": "dough"}),
            ({"any": True, "in_cold_band": True}, catch, {**catch, "in_cold_band": False}),
        ]
        for fields, good, bad in cases:
            self.one({"type": "catch_species", **fields}, good, bad)
        # count, distinct and species_ids: two different fish of the pair, not one twice.
        pair = {"type": "catch_species", "species_ids": ["bluegill", "crappie"], "count": 2, "distinct": True}
        self.one(pair, [catch, {**catch, "species_id": "crappie"}],
                 [[catch, catch], [catch, {**catch, "species_id": "redear"}]])
        self.one({"type": "catch_species", "any": True, "count": 2}, [catch, catch], [[catch]])
        # A legendary's record counts, caught or witnessed.
        witnessed = {"type": "legendary.witnessed", "species_id": "old_lantern", "lake_id": "briar",
                     "zone_id": "briar:landing"}
        self.one({"type": "catch_species", "species_id": "old_lantern"},
                 [{**catch, "species_id": "old_lantern", "legendary": True}],
                 [{**witnessed, "species_id": "spillway_monster"}])
        self.one({"type": "catch_species", "species_id": "old_lantern"}, witnessed, [])
        self.one({"type": "catch_species", "species_id": "old_lantern", "min_lb": 5}, None, [witnessed])

    def test_book_stage_counts_the_book_from_acceptance(self):
        h = Harness(self, [quest("wc_marigold_a", "a", "marigold", "briar",
                                 {"type": "book_stage", "lake_id": "briar", "stage": "bait_known", "count": 2})])
        for sid in ("bluegill", "crappie"):
            h.state.journal[sid]["count"] = 3
        h.accept("wc_marigold_a")
        # Already met: the goal completes on acceptance, without waiting for another catch.
        self.assertEqual(h.status("wc_marigold_a"), "ready")
        h = Harness(self, [quest("wc_marigold_a", "a", "marigold", "briar",
                                 {"type": "book_stage", "lake_id": "briar", "stage": "bait_known", "count": 2})])
        h.state.journal["bluegill"]["count"] = 3
        h.state.journal["channel"]["count"] = 2
        h.accept("wc_marigold_a")
        h.emit(type="book.stage_up", species_id="channel", stage="identified")
        self.assertEqual(h.status("wc_marigold_a"), "active")
        h.state.journal["channel"]["count"] = 3
        h.emit(type="book.stage_up", species_id="channel", stage="bait_known")
        self.assertEqual(h.status("wc_marigold_a"), "ready")

    def test_cook_dish_catnap_tool_and_shell(self):
        dish = {"type": "cook_dish", "dish_id": "herbal_stew", "lake_id": "briar"}
        self.one({"type": "cook_dish", "dish_id": "herbal_stew"}, dish, {**dish, "dish_id": "pan_fritters"})
        self.one({"type": "cook_dish", "any": True}, {**dish, "dish_id": "pan_fritters"}, [])
        nap = {"type": "catnap.complete", "lake_id": "briar", "zone_id": "briar:cypress"}
        self.one({"type": "catnap", "zone_id": "briar:cypress"}, nap, {**nap, "zone_id": "briar:deep"})
        tool = {"type": "tool.use", "tool_id": "reed_anchor", "lake_id": "nebula", "zone_id": "nebula:reeds",
                "shell_id": "frog"}
        step = {"type": "tool_use", "tool_id": "reed_anchor", "zone_id": "nebula:reeds", "shell_id": "frog"}
        self.one(step, tool, [{**tool, "shell_id": "tin"}, {**tool, "zone_id": "nebula:open"},
                              {**tool, "tool_id": "wave_chime"}], giver="andi", lake="nebula", qid="wc_andi_a")
        self.one({"type": "tool_use", "tool_id": "thermo_scanner", "lake_id": "flathead"},
                 {**tool, "tool_id": "thermo_scanner", "lake_id": "flathead"},
                 {**tool, "tool_id": "thermo_scanner", "lake_id": "crater"},
                 giver="mitzi", lake="flathead", qid="wc_mitzi_a")

    def test_wait_weather_accumulates_pauses_and_waits_for_the_change(self):
        def sample(weather, **extra):
            return {"type": "anchor.sample", "lake_id": "briar", "zone_id": "briar:lilies", "anchored": True,
                    "engine_idle": True, "elapsed_game_minutes": 10.0, "weather": weather, "x": 0.0, "z": 0.0,
                    **extra}
        step = {"type": "wait_weather", "weather": "mist", "zone_id": "briar:lilies", "minutes": 30}
        # Drifting pauses the total without resetting it.
        self.one(step, [sample("mist"), sample("mist", anchored=False), sample("mist"), sample("clear"),
                        sample("mist")],
                 [[sample("mist"), sample("mist"), sample("clear")],
                  [sample("mist"), sample("mist"), sample("mist", zone_id="briar:deep")]])
        # A catnap's single sample carries each forecast span; only the matching ones count.
        nap = sample("mist", elapsed_game_minutes=120.0, weather_spans=[["clear", 60.0], ["mist", 60.0]])
        self.one({"type": "wait_weather", "weather": "mist", "zone_id": "briar:lilies", "minutes": 90},
                 [nap, sample("mist", elapsed_game_minutes=30.0)], [nap])
        self.one({"type": "wait_weather", "weather": "fog", "then_weather": "clear", "zone_id": "briar:lilies"},
                 sample("clear", elapsed_game_minutes=120.0, weather_spans=[["fog", 60.0], ["clear", 60.0]]),
                 [sample("clear", elapsed_game_minutes=120.0, weather_spans=[["clear", 60.0], ["fog", 60.0]])])
        self.one({"type": "wait_weather", "weather": "drizzle", "lake_id": "briar"},
                 [sample("drizzle", elapsed_game_minutes=30.0)], [[sample("drizzle", lake_id="cedar",
                                                                          elapsed_game_minutes=30.0)]])
        coves = [f"crater:safe_cove_{i}" for i in (1, 2, 3)]
        x, z = centre(coves[1])
        fog = {**sample("fog"), "lake_id": "crater", "zone_id": "crater:cypress", "x": x, "z": z}
        step = {"type": "wait_weather", "weather": "fog", "then_weather": "clear", "area_ids": coves}
        self.one(step, [fog, {**fog, "weather": "clear"}],
                 [[{**fog, "weather": "clear"}], [fog, {**fog, "weather": "overcast"}, {**fog, "weather": "clear"}],
                  [fog, {**fog, "anchored": False}, {**fog, "weather": "clear"}],
                  [fog, {**fog, "weather": "clear", "x": x + 80}]],
                 giver="sora", lake="crater", qid="story_c4_s2")

    def test_settle_talk_to_days_and_attend_event(self):
        settle = {"type": "settle.complete", "lake_id": "nebula", "zone_id": "nebula:open", "cues": 3}
        self.one({"type": "settle", "zone_id": "nebula:open", "cues": 3}, settle,
                 [{**settle, "cues": 2}, {**settle, "zone_id": "nebula:deep"}],
                 giver="astra_9", lake="nebula", qid="story_c5_s2")
        hail = {"type": "npc.hail", "npc_id": "captain_huckleberry", "lake_id": "flathead"}
        step = {"type": "talk_to", "npc_id": "captain_huckleberry", "distinct_days": 3}
        self.one(step, [{**hail, "game_minute": 20}, {**hail, "game_minute": 1460},
                        {**hail, "game_minute": 2900}],
                 [[{**hail, "game_minute": 20}, {**hail, "game_minute": 30}, {**hail, "game_minute": 1460}],
                  [{**hail, "npc_id": "bjorn", "game_minute": 20}, {**hail, "game_minute": 1460},
                   {**hail, "game_minute": 2900}]],
                 giver="bjorn", lake="flathead", qid="wc_bjorn_a")
        hail = {"type": "npc.hail", "npc_id": "grandmother_whiskers", "lake_id": "briar", "host_of": "briar",
                "event": "cookout", "at_landing": True}
        self.one({"type": "attend_event", "lake_id": "briar", "event": "cookout"}, hail,
                 [{**hail, "event": None}, {**hail, "at_landing": False}, {**hail, "host_of": None},
                  {**hail, "lake_id": "cedar", "host_of": "cedar"}])


class EventSources(Worlds):
    """The game's own actions emit the events the steps read."""

    def capture(self, state):
        events = []
        state._quest_event_handler = lambda _state, event: events.append(event)
        return events

    def test_catches_kept_released_and_forced_release_are_resolved_once(self):
        state = State.new(self.worlds["briar"], seed=5)
        events = self.capture(state)
        line = SetLine("std", "worm", 0, 10, 0, 30, "flats", [
            Hook(False, Catch("bluegill", 0.3, 1.0, 0, "flats", "worm", 6.0, "briar", catch_game_minute=5)),
            Hook(False, Catch("crappie", 0.5, 1.0, 0, "flats", "worm", 7.0, "briar", catch_game_minute=6))])
        state.lines = [line]
        line.hooks[1].catch.disposition = "release"
        self.assertIsNone(state.take_hook(0, 0, "keep"))
        state.take_all(0)
        resolved = [e for e in events if e["type"] == "catch.resolved"]
        self.assertEqual([(e["species_id"], e["kept"]) for e in resolved], [("bluegill", True), ("crappie", False)])
        self.assertEqual(resolved[0]["zone_id"], "briar:flats")
        self.assertEqual((resolved[0]["x"], resolved[0]["z"]), tuple(map(float, line.point_at(0))))
        self.assertEqual(resolved[1]["catch_hour"], 7.0)

    def test_line_set_reed_anchor_chime_nap_and_stage_up(self):
        world = self.worlds["cedar"]
        state = State.new(world, seed=5)
        events = self.capture(state)
        state.bait["shad"] = 99
        state.x, state.z = centre("cedar:marked_pool")
        for yaw in [k * math.tau / 16 for k in range(16)]:
            state.yaw = yaw
            if state.try_set(world, 0, "shad") is None:
                break
        line_set = next(e for e in events if e["type"] == "line.set")
        self.assertTrue(in_place("cedar:marked_pool", "cedar", line_set["x"], line_set["z"]))
        self.assertIs(line_set["in_cold_band"], False)  # Cedar has no thermocline
        state.v2["profile"]["tools"] = ["wave_chime"]
        state.v2["profile"]["shell"] = "duck"
        self.assertIsNone(state.use_chime(world))
        self.assertEqual([e for e in events if e["type"] == "tool.use"][-1]["shell_id"], "duck")
        state.anchored = True
        self.assertIsNone(state.catnap(world))
        nap = [e for e in events if e["type"] == "catnap.complete"][-1]
        self.assertEqual(nap["zone_id"], f"cedar:{world.zone_at(state.x, state.z)}")
        state._note_journal(Catch("drum", 3.0, 1.0, 0, "rocks", "shad", 9.0, "cedar", catch_game_minute=1))
        self.assertIn({"type": "book.stage_up", "species_id": "drum", "stage": "identified",
                       "game_minute": state.game_minutes}, events)

    def test_the_reed_anchor_reports_the_lines_zone_and_shell(self):
        world = self.worlds["briar"]
        state = State.new(world, seed=5)
        events = self.capture(state)
        state.v2["profile"]["tools"] = ["reed_anchor"]
        state.v2["profile"]["shell"] = "frog"
        state.bait["worm"] = 9999
        cx, cz = next((row[1], row[2]) for row in world.zones if row[0] == "reeds")
        spots = [(cx + r * math.sin(k * math.tau / 16), cz + r * math.cos(k * math.tau / 16), j * math.tau / 8)
                 for r in (0.0, 15.0, 30.0, 45.0) for k in range(16) for j in range(8)]
        for x, z, yaw in spots:
            state.x, state.z, state.yaw = x, z, yaw
            if state.try_set(world, 0, "worm") is None:
                if state.lines[-1].zone == "reeds":
                    break
                state.held.insert(0, HeldLine(state.lines.pop().tier))  # not the reeds; take it back
        self.assertEqual(state.lines[-1].zone, "reeds")
        tool = [e for e in events if e["type"] == "tool.use"][-1]
        self.assertEqual((tool["tool_id"], tool["zone_id"], tool["shell_id"]), ("reed_anchor", "briar:reeds", "frog"))

    def test_a_long_advance_reports_each_forecast_span(self):
        from .calendar import weather_at, weather_spans
        world = self.worlds["briar"]
        state = State.new(world, seed=5)
        spans = weather_spans(state, 30, 30 + 600)
        self.assertEqual(sum(minutes for _weather, minutes in spans), 600)
        self.assertEqual([weather for weather, _m in spans],
                         [w for i, w in enumerate(weather_at(state, m) for m in range(30, 630, 30))
                          if i == 0 or w != weather_at(state, 30 + (i - 1) * 30)])
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(world, Path(tmp) / "save.json", state, False)
            session.ui.mode = "play"
            events = self.capture(state)
            before = state.game_minutes
            session.advance_bulk(120)
            sample = [e for e in events if e["type"] == "anchor.sample"][-1]
            self.assertEqual(sample["weather_spans"], weather_spans(state, before, before + 120))
            self.assertEqual(sum(m for _w, m in sample["weather_spans"]), sample["elapsed_game_minutes"])

    def test_waypoints_fire_on_entry_with_provenance(self):
        world = self.worlds["cedar"]
        state = State.new(world, seed=5)
        events = self.capture(state)
        x, z = centre("cedar:practice_buoy_2")
        state._emit_movement_events(world, x - 40, z, x, z, player_controlled=True, propulsion="motor")
        state._emit_movement_events(world, x, z, x + 1, z, player_controlled=True, propulsion="motor")
        entries = [e for e in events if e["type"] == "waypoint.enter"]
        self.assertEqual([e["waypoint_id"] for e in entries], ["cedar:practice_buoy_2"])
        self.assertTrue(entries[0]["player_controlled"])

    def test_session_samples_weather_and_hails_with_host_landing_and_cookout(self):
        world = self.worlds["briar"]
        with tempfile.TemporaryDirectory() as tmp:
            state = State.new(world, seed=5)
            session = Session(world, Path(tmp) / "save.json", state, False)
            session.ui.mode = "play"
            events = self.capture(state)
            session.tick(Keys(), 0.5)
            sample = next(e for e in events if e["type"] == "anchor.sample")
            self.assertIn(sample["weather"], WEATHER_STATES)
            self.assertEqual((sample["x"], sample["z"]), (state.x, state.z))
            host = next(n for n in state.npcs if n.id == "grandmother_whiskers")
            state.game_minutes = 6 * 1440 + 11 * 60 + 30  # Sunday 17:30, during the cookout
            state._park(world)
            self.assertTrue(record_hail(state, world, host))
            self.assertFalse(record_hail(state, world, host))
            hail = [e for e in events if e["type"] == "npc.hail"][-1]
            self.assertEqual((hail["host_of"], hail["event"], hail["at_landing"]), ("briar", "cookout", True))
            self.assertEqual(state.v2["npcs"]["talk_days"]["grandmother_whiskers"], [6])


class QuestFlow(Worlds):
    def test_steps_run_in_order_and_each_restarts_its_own_progress(self):
        h = Harness(self, [quest("wc_old_gus_b", "b", "old_gus", "briar",
                                 [{"type": "visit_zones", "zone_ids": ["flathead:open"]},
                                  {"type": "talk_to", "npc_id": "old_gus"}],
                                 requires={"travel_unlocked": "flathead"}, cross_lake=["flathead"])])
        h.state.narrative.quest("wc_old_gus_a").status = "completed"
        self.assertFalse(quest_available(h.state, h.content, "wc_old_gus_b"))  # Flathead is still closed
        h.state.v2["story"]["chapter"] = 3
        self.assertTrue(quest_available(h.state, h.content, "wc_old_gus_b"))
        h.accept("wc_old_gus_b")
        h.emit(type="npc.hail", npc_id="old_gus", lake_id="briar")
        self.assertEqual(h.state.narrative.quests["wc_old_gus_b"].progress["step"], 0)
        self.assertEqual(pinned(h.state, h.content), frozenset())
        h.emit(type="zone.enter", lake_id="flathead", zone_id="flathead:open", movement_cause="boat",
               player_controlled=True)
        self.assertEqual(h.state.narrative.quests["wc_old_gus_b"].progress, {"step": 1, "data": {}})
        self.assertEqual(pinned(h.state, h.content), frozenset({"old_gus"}))
        h.emit(type="npc.hail", npc_id="old_gus", lake_id="briar")
        self.assertEqual(h.status("wc_old_gus_b"), "ready")

    def test_requires_chapter_and_quest(self):
        h = Harness(self, [quest("wc_old_gus_a", "a", "old_gus", "briar", {"type": "catnap"},
                                 requires={"chapter_complete": 2, "quest": "q01_tea_leaves_deep_holes"})])
        self.assertFalse(quest_available(h.state, h.content, "wc_old_gus_a"))
        self.assertFalse(accept_quest(h.state, h.content, "wc_old_gus_a"))
        h.state.v2["story"]["chapter"] = 3
        self.assertFalse(quest_available(h.state, h.content, "wc_old_gus_a"))
        h.state.narrative.quests["q01_tea_leaves_deep_holes"].status = "completed"
        self.assertTrue(quest_available(h.state, h.content, "wc_old_gus_a"))

    def test_quest_b_opens_the_game_day_after_a_is_turned_in(self):
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"}),
                quest("wc_marigold_b", "b", "marigold", "briar", {"type": "catnap"}),
                quest("wc_willow_b", "b", "willow", "briar", {"type": "catnap"})]
        h = Harness(self, rows)
        self.assertEqual(current_quest(h.state, h.content, "marigold"), "wc_marigold_a")
        self.assertFalse(quest_available(h.state, h.content, "wc_marigold_b"))
        h.state.game_minutes = 1439  # 05:59, the last minute of day 0
        h.accept("wc_marigold_a")
        h.emit(type="catnap.complete", lake_id="briar", zone_id="briar:open")
        from .dialogue import _claim_and_pay
        self.assertTrue(_claim_and_pay(h.state, h.content, "wc_marigold_a"))
        self.assertEqual(h.state.narrative.quests["wc_marigold_a"].completed_game_minute, 1439)
        self.assertFalse(quest_available(h.state, h.content, "wc_marigold_b"))
        self.assertEqual(current_quest(h.state, h.content, "marigold"), "wc_marigold_a")
        h.state.game_minutes = 1440  # 06:00: the next game day
        self.assertTrue(quest_available(h.state, h.content, "wc_marigold_b"))
        self.assertEqual(current_quest(h.state, h.content, "marigold"), "wc_marigold_b")
        # A V3 quest A works the same way, including one completed before V1.0 (no minute saved).
        self.assertFalse(quest_available(h.state, h.content, "wc_willow_b"))
        h.state.narrative.quests["q06_unrepeatable_sunrise"].status = "completed"
        self.assertTrue(quest_available(h.state, h.content, "wc_willow_b"))
        self.assertEqual(current_quest(h.state, h.content, "willow"), "wc_willow_b")

    def test_friendship_is_derived_from_quest_status(self):
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"}),
                quest("wc_marigold_b", "b", "marigold", "briar", {"type": "catnap"})]
        h = Harness(self, rows)
        states = []
        for qid in (None, "wc_marigold_a", "wc_marigold_b"):
            if qid:
                h.state.narrative.quest(qid).status = "completed"
            ledger = NarrativeState.from_json(h.state.narrative.to_json())
            states.append(friendship(h.state, h.content, "marigold"))
            self.assertNotIn("friendship", str(ledger.to_json()))
        self.assertEqual(states, ["stranger", "acquaintance", "friend"])
        self.assertEqual(friendship(h.state, h.content, "willow"), "stranger")
        self.assertIsNone(friendship(h.state, h.content, "grandmother_whiskers"))
        self.assertNotIn("friendship", h.state.v2["npcs"])

    def test_greetings_pick_the_most_specific_true_state(self):
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"})]
        cats = [{"id": "marigold", "greetings": {
            "stranger": "Hello, stranger!", "acquaintance": "Hello again!", "first": "Oh! A new face!",
            "day": "Lovely day.", "after_ch1": "The book has a new page!", "cookout": "Pie!",
            **{f"weather:{w}": f"So {w}!" for w in ("fog", "drizzle")}}}]
        h = Harness(self, rows, cats)
        # A first meeting is the most specific state of all, even in weather the cat has a line for.
        with patch("fishing.calendar.weather_at", return_value="drizzle"):
            self.assertEqual(greeting(h.state, h.content, "marigold", first=True), "Oh! A new face!")
            self.assertEqual(greeting(h.state, h.content, "marigold"), "So drizzle!")
        with patch("fishing.calendar.weather_at", return_value="clear"):
            self.assertEqual(greeting(h.state, h.content, "marigold", first=True), "Oh! A new face!")
            self.assertEqual(greeting(h.state, h.content, "marigold"), "Hello, stranger!")
            h.state.narrative.quest("wc_marigold_a").status = "completed"
            self.assertEqual(greeting(h.state, h.content, "marigold"), "Hello again!")
            h.state.v2["story"]["chapter"] = 2
            self.assertEqual(greeting(h.state, h.content, "marigold"), "The book has a new page!")
            h.state.game_minutes = 6 * 1440 + 11 * 60 + 30
            self.assertEqual(greeting(h.state, h.content, "marigold"), "Pie!")
        self.assertIsNone(greeting(h.state, h.content, "old_gus"))

    def test_every_reward_kind_is_credited_once_and_survives_reload(self):
        reward = {"cash": 45, "ripple_id": "ripple_11", "recipes": ["pecan_smoked_shad"],
                  "items": {"dough": 12, "herbs": 2}}
        story = {"shells": ["frog"], "dish_cards": ["herbal_stew"], "unlocks": ["travel:flathead", "chart:reeds"],
                 "keepsake_id": "ks_pip_pebble", "cash": 10}
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"}, reward=reward,
                      on_accept={"items": {"dough": 12}}),
                quest("story_c1_s3", "story", "pip_pebble", "briar", {"type": "catnap"}, reward=story)]
        h = Harness(self, rows)
        from .dialogue import _claim_and_pay
        dough = h.state.bait.get("dough", 0)
        h.accept("wc_marigold_a")
        self.assertEqual(h.state.bait["dough"], dough + 12)
        self.assertFalse(h.state.narrative.record_accept_claim("wc_marigold_a"))
        self.assertIn("wc_marigold_a:accept", h.state.narrative.reward_claims)
        h.accept("story_c1_s3")
        for qid in ("wc_marigold_a", "story_c1_s3"):
            h.emit(type="catnap.complete", lake_id="briar", zone_id="briar:open")
        self.assertFalse(travel_unlocked(h.state, "flathead"))
        before = (h.state.money, h.state.bait["dough"], h.state.v2["pantry"]["herbs"])
        for qid in ("wc_marigold_a", "story_c1_s3", "wc_marigold_a", "story_c1_s3"):
            _claim_and_pay(h.state, h.content, qid)
        v2 = h.state.v2
        self.assertEqual(h.state.money, before[0] + 55)
        self.assertEqual((h.state.bait["dough"], v2["pantry"]["herbs"]), (before[1] + 12, before[2] + 2))
        self.assertEqual(v2["ripples_v2"], ["ripple_11"])
        self.assertEqual(v2["keepsakes"], ["ks_pip_pebble"])
        self.assertIn("pecan_smoked_shad", v2["recipes"])
        self.assertIn("herbal_stew", v2["dishes_known"])
        self.assertIn("frog", v2["profile"]["shells"])
        self.assertEqual(v2["unlocks"], ["travel:flathead", "chart:reeds"])
        self.assertTrue(travel_unlocked(h.state, "flathead"))
        self.assertEqual(h.state.narrative.ripples, [])  # V3 Ripples keep their own list
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "save.json"
            h.state.save(path)
            loaded = State.load(path, self.worlds["briar"])
        self.assertEqual(loaded.money, h.state.money)
        self.assertEqual(loaded.v2["unlocks"], v2["unlocks"])
        for qid in ("wc_marigold_a", "story_c1_s3"):
            self.assertEqual(loaded.narrative.quests[qid].status, "completed")
            self.assertFalse(_claim_and_pay(loaded, h.content, qid))
        self.assertEqual(loaded.money, h.state.money)

    def test_the_journal_lists_accepted_quests_and_when_their_cat_is_out(self):
        from .npcs import next_appearance
        from .ui import journal_quest_ids, quest_journal_details
        rows = [quest("wc_marigold_a", "a", "marigold", "briar",
                      [{"type": "catnap"}, {"type": "talk_to", "npc_id": "willow"}])]
        h = Harness(self, rows)
        self.assertEqual(journal_quest_ids(h.state, h.content), QUEST_IDS)
        h.accept("wc_marigold_a")
        self.assertEqual(journal_quest_ids(h.state, h.content), QUEST_IDS + ("wc_marigold_a",))
        detail = quest_journal_details(h.state, h.content, "wc_marigold_a")
        self.assertEqual((detail["objective"], detail["progress"]), ("Do the thing.", "Step 1 of 2."))
        h.emit(type="catnap.complete", lake_id="briar", zone_id="briar:open")
        # Willow is pinned while the step needs her, so the journal says she is out every day.
        self.assertEqual(quest_journal_details(h.state, h.content, "wc_marigold_a")["progress"],
                         "Step 2 of 2. Willow waits on Little Briar every day until then.")
        h.emit(type="npc.hail", npc_id="willow", lake_id="briar")
        self.assertTrue(quest_journal_details(h.state, h.content, "wc_marigold_a")["progress"].startswith(
            "Ready to turn in, to the giver or at the landing. Marigold waits on Little Briar"))
        # Unpinned, a day cat's next guaranteed day comes from the schedule; tonight's band from the night pool.
        seed = h.state.narrative.schedule_seed
        h.state.game_minutes = 15 * 60  # 21:00 on day 0: today's day band is over
        first = next(d for d in range(1, 9) if "silas" in day_encounters(seed, "briar", d))
        when = "tomorrow" if first == 1 else f"in {first} days"
        self.assertEqual(next_appearance(h.state, h.content, "silas"),
                         f"Silas is out on Little Briar {when}, 06:00–20:00.")
        self.assertEqual(next_appearance(h.state, h.content, "master_cinder"),
                         "Master Cinder is out on Little Briar today, 20:00–04:00.")
        self.assertEqual(next_appearance(h.state, h.content, "grandmother_whiskers"),
                         "Grandmother Whiskers is always at Briar Landing.")
        # Travelers keep their own rules, even while a quest pins them.
        from .npcs import pounce_lake
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "talk_to", "npc_id": "pounce"}),
                quest("wc_old_gus_a", "a", "old_gus", "briar", {"type": "talk_to", "npc_id": "thistle"},
                      reward={"cash": 45, "ripple_id": "ripple_12"})]
        h = Harness(self, rows)
        h.accept("wc_marigold_a")
        h.accept("wc_old_gus_a")
        visit = next(d for d in range(15) if pounce_lake(h.state, d) == "briar")
        when = "today" if visit == 0 else "tomorrow" if visit == 1 else f"in {visit} days"
        self.assertEqual(quest_journal_details(h.state, h.content, "wc_marigold_a")["progress"],
                         f"Under way. Postmaster Pounce visits Little Briar {when}, 08:00–16:00.")
        self.assertEqual(quest_journal_details(h.state, h.content, "wc_old_gus_a")["progress"],
                         "Under way. Tinker Thistle moors at your lake in 5 days, 10:00–18:00.")

    def test_ledger_keeps_v1_0_progress_claims_and_older_shapes(self):
        legacy = NarrativeState().to_json()
        self.assertEqual(NarrativeState.from_json(legacy).to_json(), legacy)
        self.assertNotIn("completed_game_minute", str(legacy))
        ledger = NarrativeState.from_json(legacy)
        progress = ledger.quest("wc_marigold_a")
        progress.status, progress.progress = "ready", {"step": 1, "data": {"count": 2}}
        self.assertTrue(ledger.record_reward_claim("wc_marigold_a", 1500))
        ledger.quest("wc_old_gus_a").status = "active"
        self.assertTrue(ledger.record_accept_claim("wc_old_gus_a"))
        ledger.quests["wc_marigold_a"].turned_in_by = "grandmother_whiskers"
        raw = ledger.to_json()
        raw["quests"]["wc_from_a_later_build_a"] = {"status": "active", "progress": {"x": 1}}
        raw["quests"]["not_a_quest"] = {"status": "weird"}
        raw["reward_claims"].append("future:claim")
        again = NarrativeState.from_json(raw)
        written = again.to_json()
        # Unrecognized entries and claims are kept verbatim; recognized ids load as progress.
        self.assertEqual(written["quests"]["not_a_quest"], {"status": "weird"})
        self.assertIn("future:claim", written["reward_claims"])
        self.assertEqual(written["quests"]["wc_from_a_later_build_a"]["progress"], {"x": 1})
        self.assertEqual({k: v for k, v in written["quests"].items() if k != "wc_from_a_later_build_a"},
                         {k: v for k, v in raw["quests"].items() if k != "wc_from_a_later_build_a"})
        self.assertEqual(NarrativeState.from_json(written).to_json(), written)
        self.assertEqual(again.quests["wc_marigold_a"].completed_game_minute, 1500)
        self.assertEqual(again.quests["wc_marigold_a"].turned_in_by, "grandmother_whiskers")
        self.assertFalse(again.quests["wc_marigold_a"].acknowledged)
        self.assertEqual(again.quests["wc_from_a_later_build_a"].status, "active")
        self.assertNotIn("not_a_quest", again.quests)
        # A claim whose progress entry was lost still marks its quest completed.
        raw = NarrativeState().to_json()
        raw["reward_claims"].append("wc_kit_b")
        self.assertEqual(NarrativeState.from_json(raw).quests["wc_kit_b"].status, "completed")


class TurnIns(Worlds):
    """Turn-ins at the giver or the lake's host, through real hails (02 §12.2 rule 3)."""

    def session(self, rows=(), cats=(), seed=11):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        content = content_with(rows, cats)
        world = self.worlds["briar"]
        state = State.new(world, seed=seed)
        with patch("fishing.game.load_content", return_value=content):
            session = Session(world, Path(tmp.name) / "save.json", state, False)
        session.ui.mode = "play"
        return session

    def hail(self, session, npc_id):
        session._refresh_npcs()
        npc = next(n for n in session.state.npcs if n.id == npc_id)
        session.state.x, session.state.z = npc.anchor.position
        session.state.speed = 0
        session.ui.mode = "play"
        session.conversation = None
        session._hail()
        return session.conversation

    def choose(self, session, text):
        chat = session.conversation
        node = chat.node(session._npc_content)
        chat.selected = next(i for i, choice in enumerate(node["choices"]) if text in choice["text"])
        return chat.advance(session.state, session._npc_content)

    def day_with(self, session, npc_id):
        seed = session.state.narrative.schedule_seed
        return next(d for d in range(7) if npc_id in day_encounters(seed, "briar", d))

    def test_a_host_turn_in_is_acknowledged_by_the_givers_return_line(self):
        session = self.session()
        state, content = session.state, session._npc_content
        state.game_minutes = 120  # 08:00
        progress = state.narrative.quests["q06_unrepeatable_sunrise"]
        progress.status, progress.accepted_game_minute = "ready", 0
        money, ripples = state.money, list(state.narrative.ripples)
        chat = self.hail(session, "grandmother_whiskers")
        self.assertEqual(chat.node_id, "grandmother_whiskers:hand_in")
        self.assertTrue(self.choose(session, "The Unrepeatable Sunrise"))
        self.assertEqual(state.narrative.quests["q06_unrepeatable_sunrise"].status, "completed")
        self.assertEqual(state.money, money + content.rewards["q06_unrepeatable_sunrise:reward"]["cash"])
        self.assertEqual(state.narrative.ripples, ripples + ["ripple_04"])
        self.assertEqual(progress.turned_in_by, "grandmother_whiskers")
        # The host then carries on with her own conversation.
        self.assertEqual(chat.node_id, "grandmother_whiskers:handed_in")
        chat.advance(state, content)
        self.assertEqual(chat.node_id, content.quests["q01_tea_leaves_deep_holes"]["dialogue"]["available"])
        # Willow is no longer pinned by a ready quest; meet her on one of her days.
        state.game_minutes = self.day_with(session, "willow") * 1440 + 120
        chat = self.hail(session, "willow")
        self.assertEqual(chat.node_id, "q06_unrepeatable_sunrise:dialogue:return")
        self.assertTrue(progress.acknowledged)
        session.save()
        loaded = State.load(session.save_path, self.worlds["briar"])
        self.assertTrue(loaded.narrative.quests["q06_unrepeatable_sunrise"].acknowledged)
        self.assertEqual(loaded.money, state.money)

    def test_a_v1_0_quest_handed_in_at_the_host_is_acknowledged_when_quest_b_is_open(self):
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"},
                      lines={**LINES, "return": "You told Grandmother! Thank you."}),
                quest("wc_marigold_b", "b", "marigold", "briar", {"type": "catnap"},
                      lines={"offer": "Shelter me from the rain?", "done": "Dry ears!"})]
        cats = [{"id": "marigold", "greetings": {"stranger": "Hello! I'm swimming.",
                                                 "acquaintance": "Hello again, swim buddy!"}}]
        session = self.session(rows, cats)
        state, content = session.state, session._npc_content
        day = self.day_with(session, "marigold")
        state.game_minutes = day * 1440 + 120
        chat = self.hail(session, "marigold")
        self.assertEqual(chat.node(content)["text"], "Hello! I'm swimming.")
        chat.advance(state, content)
        self.assertEqual(chat.node_id, "wc_marigold_a:dialogue:offer")
        self.assertTrue(self.choose(session, "give it a try"))
        self.assertEqual(state.narrative.quests["wc_marigold_a"].status, "active")
        state.anchored = True
        self.assertIsNone(state.catnap(session.world))
        self.assertEqual(state.narrative.quests["wc_marigold_a"].status, "ready")
        money = state.money
        chat = self.hail(session, "grandmother_whiskers")
        self.assertTrue(self.choose(session, "Wc Marigold A"))
        self.assertEqual(state.money, money + 45)
        self.assertEqual(state.v2["ripples_v2"], ["ripple_11"])
        # Days later, quest B is open, but Marigold first acknowledges the turn-in.
        state.game_minutes = (day + 7) * 1440 + 120
        self.assertEqual(current_quest(state, content, "marigold"), "wc_marigold_b")
        chat = self.hail(session, "marigold")
        self.assertEqual(chat.node(content)["text"], "You told Grandmother! Thank you.")
        chat = self.hail(session, "marigold")
        self.assertEqual(chat.node(content)["text"], "Hello again, swim buddy!")
        chat.advance(state, content)
        self.assertEqual(chat.node_id, "wc_marigold_b:dialogue:offer")

    def test_the_giver_takes_its_own_turn_in_and_hosts_only_their_lake(self):
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "talk_to", "npc_id": "marigold"}),
                quest("wc_hank_mudpaw_a", "a", "hank_mudpaw", "cedar", {"type": "catnap"},
                      reward={"cash": 55, "ripple_id": "ripple_14"})]
        session = self.session(rows)
        state, content = session.state, session._npc_content
        state.game_minutes = self.day_with(session, "marigold") * 1440 + 120
        self.hail(session, "marigold")
        self.assertTrue(self.choose(session, "give it a try"))
        state.game_minutes += 1
        # The hail itself completes talk_to, so this meeting opens on the ready node.
        chat = self.hail(session, "marigold")
        self.assertEqual(chat.node_id, "wc_marigold_a:dialogue:ready")
        self.assertTrue(self.choose(session, "how it went"))
        self.assertEqual(chat.node_id, "wc_marigold_a:dialogue:done")
        self.assertIsNone(state.narrative.quests["wc_marigold_a"].turned_in_by)
        hank = state.narrative.quest("wc_hank_mudpaw_a")
        hank.status = "ready"
        self.assertEqual(open_conversation(next(n for n in state.npcs if n.id == "grandmother_whiskers"),
                                           state, content).node_id,
                         content.quests["q01_tea_leaves_deep_holes"]["dialogue"]["available"])

    def test_a_cat_with_nothing_to_offer_waves(self):
        session = self.session([quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"},
                                      requires={"chapter_complete": 4})])
        state = session.state
        state.game_minutes = self.day_with(session, "marigold") * 1440 + 120
        self.assertIsNone(self.hail(session, "marigold"))
        self.assertIn("Marigold waves hello.", [toast[0] for toast in state.toasts])


class Letters(Worlds):
    def test_friends_write_once_and_pounce_brings_one_letter_a_day(self):
        rows = [quest("wc_marigold_a", "a", "marigold", "briar", {"type": "catnap"}),
                quest("wc_marigold_b", "b", "marigold", "briar", {"type": "catnap"}),
                quest("wc_old_gus_a", "a", "old_gus", "briar", {"type": "catnap"},
                      reward={"cash": 45, "ripple_id": "ripple_12"}),
                quest("wc_old_gus_b", "b", "old_gus", "briar", {"type": "catnap"})]
        cats = [{"id": cid, "greetings": {"day": "Hi."},
                 "letters": [f"Dear Skipper, {cid} {n}. — {cid}" for n in (1, 2, 3)]}
                for cid in ("marigold", "old_gus")]
        h = Harness(self, rows, cats)
        from .dialogue import _claim_and_pay
        for qid in ("wc_marigold_a", "wc_marigold_b", "wc_old_gus_a"):
            h.state.narrative.quest(qid).status = "ready"
            _claim_and_pay(h.state, h.content, qid)
        letters = h.state.v2["npcs"]["letters"]
        self.assertEqual([row["from"] for row in letters], ["marigold"])  # Old Gus isn't a friend yet
        h.state.narrative.quest("wc_old_gus_b").status = "ready"
        _claim_and_pay(h.state, h.content, "wc_old_gus_b")
        _claim_and_pay(h.state, h.content, "wc_old_gus_b")
        self.assertEqual([row["from"] for row in letters], ["marigold", "old_gus"])
        pounce = NPC("pounce", "Postmaster Pounce", None, self.worlds["briar"].anchors["briar:mail_mooring"], False)
        self.assertIsNone(open_conversation(pounce, h.state, h.content))  # written today, sent tomorrow
        h.state.game_minutes = 1440 + 180
        chat = open_conversation(pounce, h.state, h.content)
        self.assertEqual(chat.node(h.content)["text"], "Letter for you, {Skipper}! From Marigold.")
        chat.advance(h.state, h.content)
        variant = letters[0]["variant"]
        self.assertEqual(chat.node(h.content)["text"], f"Dear Skipper, marigold {variant + 1}. — marigold")
        self.assertIsNone(open_conversation(pounce, h.state, h.content))  # at most one a day
        h.state.game_minutes = 2 * 1440 + 180
        self.assertEqual(next_letter(h.state, h.content)["from"], "old_gus")
        chat = open_conversation(pounce, h.state, h.content)
        self.assertIn("From Old Gus", chat.node(h.content)["text"])
        h.state.game_minutes = 3 * 1440 + 180
        self.assertIsNone(open_conversation(pounce, h.state, h.content))
        self.assertEqual([row["delivered_day"] for row in letters], [1, 2])


if __name__ == "__main__":
    unittest.main()
