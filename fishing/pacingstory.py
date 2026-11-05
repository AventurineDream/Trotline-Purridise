"""Story pacing for the attentive player of pacing.py (V1-44): chapter durations against
02 §1, built day by day on the real cat schedule, then the book curve and when each
legendary can first be caught.

On each chapter's lake the attentive player:
- **does the story.** Each step starts once the step before it is turned in and any gear it
  needs is bought.
- **takes the lake's first quests.** Each cat's first (`kind` "a") and the V3 quests, plus
  the lake host's errand. A cat offers its quest only on a day it is out (three by day and one
  by night from the lake's round-robin), and the player takes on up to `QUESTS_PER_DAY` a day.
  Turn-ins need no waiting: a quest's cat is pinned until it is turned in.
- **does second quests (`kind` "b") on the way.** They open the day after the first, and the
  player does them while still on the lake, but doesn't stay for them.
- **plans each day as one tour.** From the landing, past every cat and place the day's quests
  need, and back. What is left of the waking day (06:00–22:00) goes on the fishing routine,
  with its income.
- **leaves** once the story chapter, the first quests and the host's errand are done.

Each objective is costed from its own numbers (`estimate`). Waiting objectives (a soak, a
catch, the weather, a count) run alongside everything else, from halfway round the tour.
Being somewhere (anchoring a while, a scout) uses the day's waking minutes. Driving takes
real time one second a game minute, talk and menus freeze the clock, and each day adds
`BROWSE_S_PER_DAY` for the book, the shop and the chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math

from . import bottools, calendar, pacing
from .content import load_content
from .lakes import place
from .npcs import cast, day_encounters, night_encounter
from .reading import reading_seconds
from .sim import State, species_rates
from .world import World

# Story time targets in real minutes (02 §1: chapter 1 ≈ 60–90 min, 2 ≈ 2 h, 3 ≈ 2.5 h,
# 4 ≈ 2.5 h, 5 ≈ 1.5 h; the story 10–12 h). Every chapter gets its figure ±25% (chapter 1's
# figure is the middle of its range). The spec's chapter figures add up to 9.75 h, below its
# own 10 h floor, so a story that meets every chapter can't reach 10 h: the story band runs
# from that sum to 12 h. (V1-44 flags the mismatch for 02 §1.)
CHAPTER_FIGURES = {1: 75, 2: 120, 3: 150, 4: 150, 5: 90}
CHAPTER_TARGETS = {c: (round(m * 0.75), round(m * 1.25)) for c, m in CHAPTER_FIGURES.items()}
STORY_TARGET = (sum(CHAPTER_FIGURES.values()), 720)
BOT_SCOUT_MIN = 20     # game minutes for Bot to sound a spot and report
MENU_S = 8.0           # a shop, cook or tool menu
SCENE_CHOICE_S = 2.0
MAX_DAYS = 21
WAKING_MIN = 960       # 06:00 to 22:00
# Real time a game day takes beyond driving, hauling and talking: the book's pages, the shop,
# the chart, the pantry. 02 §1's session (20–40 min for one to two game days) leaves about this.
BROWSE_S_PER_DAY = 300.0
# Side quests the attentive player takes on in a game day: what the day's three cats offer.
QUESTS_PER_DAY = 3

STORY_STEPS = {
    1: ("story_c0_s1", "story_c0_s2", "story_c0_s3", "story_c1_s1", "story_c1_s2", "story_c1_s3"),
    2: ("story_c2_s1", "story_c2_s2", "story_c2_s3"),
    3: ("story_c3_s1", "story_c3_s2", "story_c3_s3"),
    4: ("story_c4_s1", "story_c4_s2", "story_c4_s3"),
    5: ("story_c5_s1", "story_c5_s2", "story_c5_s3"),
}
CHAPTER_LAKE = {1: "briar", 2: "cedar", 3: "flathead", 4: "crater", 5: "nebula"}
CHAPTER_STAGE = {1: "start", 2: "ch2", 3: "ch3", 4: "ch4", 5: "post"}
CHAPTER_SCENES = {1: ("pro_",), 2: (), 3: ("story_c3_",), 4: ("story_c4_",), 5: ("story_c5_", "end_")}
# Gear a step needs before it can be done, and what it costs.
STEP_GEAR = {"story_c2_s3": ("prem", 145.0)}


@dataclass
class Item:
    quest_id: str
    giver: str | None
    story: bool


# --- costing an objective ---------------------------------------------------------------

def _zone_name(ref):
    return ref.split(":", 1)[1] if isinstance(ref, str) and ":" in ref else ref


def _place_xy(ref, world):
    found = place(ref)
    if found is not None:
        row = found[1]
        if "x" in row:
            return row["x"], row["z"]
        pts = row["points"]
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    zone = _zone_name(ref)
    centres = [(x, z) for name, x, z, _r in world.zones if name == zone]
    return centres[0] if centres else world.dock


@lru_cache(maxsize=None)
def lake_world(lake):
    return World(lake)


@lru_cache(maxsize=None)
def _points(lake):
    return pacing._candidate_points(lake_world(lake))


@lru_cache(maxsize=None)
def catch_minutes(lake, species_id=None, zone=None, tag=None, cold_band=False, hooks=12):
    """Expected game minutes for a dedicated line of `hooks` hooks, at the best place and
    bait the player finds for it, to hook a qualifying fish, at 06:00–22:00 rates."""
    from .data import SPECIES_BY_ID
    world = lake_world(lake)
    groups = _points(lake)
    candidates = groups.get(zone, []) if zone else [p for pts in groups.values() for p in pts]
    best = 0.0
    for x, z in candidates:
        depth = float(world.depth(x, z))
        here = world.zone_at(x, z)
        for bait in pacing.baits_for(lake):
            per_hour = 0.0
            for step in range(16):
                hour = 6.5 + step  # clock hours, the waking day
                cold = bottools.cold_layer_m(lake, hour, pacing.REFERENCE_WEATHER)
                tool = bottools.ToolState(cold, False, False, False)
                rates = species_rates(here, bait, hour, pacing.REFERENCE_WEATHER, depth, lake, tool=tool)
                for sid, rate in rates.items():
                    if rate <= 0 or (species_id and sid != species_id):
                        continue
                    sp = SPECIES_BY_ID[sid]
                    if lake not in sp.lakes or (tag and tag not in sp.tags):
                        continue
                    if cold_band and not (cold is not None and cold <= depth <= cold + bottools.COLD_BAND_M):
                        continue
                    per_hour += rate
            best = max(best, per_hour / 16.0)
    return 60.0 / (best * hooks) if best > 0 else math.inf


def _weather_wait(seed, lake, start, weather, then=None, minutes=0):
    """Game minutes from `start` until the plan shows `weather` (then `then`) for `minutes`."""
    t = start
    for _ in range(24 * 21):
        if calendar.planned_weather(seed, lake, t) == weather:
            if then is None:
                return t - start + minutes
            u = t
            while calendar.planned_weather(seed, lake, u) == weather and u - t < 24 * 60:
                u += 60
            if calendar.planned_weather(seed, lake, u) == then:
                return u - start + minutes
        t += 60
    return math.inf


def estimate(objective, ctx):
    """(driving seconds, menu seconds, exclusive game minutes, passive game minutes) for one
    objective. Driving runs the clock one game minute a second; menus freeze it. Exclusive
    minutes need the player there; passive ones pass while they do other things."""
    kind = objective.get("type")
    world, lake, speed = ctx["world"], ctx["lake"], ctx["speed"]
    dock = world.dock

    # Places are collected on ctx["stops"]; _cost drives one tour through all of a quest's
    # stops (its cat's and its objectives'). These return no driving of their own.
    def there_and_back(ref):
        ctx["stops"].append(_place_xy(ref, world))
        return 0.0

    def through(refs):
        ctx["stops"].extend(_place_xy(ref, world) for ref in refs)
        return 0.0

    def window_wait(windows, index):
        if not windows:
            return 0.0
        start = (windows[index][0] - 360) % 1440  # clock minutes to minutes after 06:00
        return float((start - ctx["clock"] % 1440) % 1440)

    if kind == "talk_to":
        place_xy = world_anchor(world, objective.get("npc_id"))
        if place_xy is not None:
            ctx["stops"].append(place_xy)
        return 0.0, 0.0, 0.0, max(0, int(objective.get("distinct_days", 1)) - 1) * 1440.0
    if kind == "line_set":
        return there_and_back(objective.get("area_id") or f"{lake}:landing"), MENU_S, 0.0, 0.0
    if kind in ("line_check", "line_scout", "line_scout_check"):
        ref = objective.get("zone_id") or objective.get("area_id") or f"{lake}:open"
        scout = BOT_SCOUT_MIN if "scout" in kind else 0.0
        return there_and_back(ref), 2 * MENU_S, scout, float(objective.get("active_soak_game_minutes", 60))
    if kind == "scout_report":
        refs = objective.get("waypoint_ids") or [objective.get("zone_id") or f"{lake}:open"]
        windows = objective.get("windows")
        passive = window_wait(windows, len(windows) - 1) if windows and len(windows) > 1 else 0.0
        return through(refs), 0.0, BOT_SCOUT_MIN * len(refs), passive
    if kind in ("visit_sequence", "visit_zones"):
        refs = objective.get("waypoint_ids") or objective.get("zone_ids") or []
        return through(refs), 0.0, 0.0, window_wait(objective.get("windows"), 0)
    if kind == "travel_distance":
        there_and_back(objective.get("zone_id"))
        return float(objective.get("distance_m", 200)) / speed, 0.0, 0.0, 0.0
    if kind == "anchor_idle":
        return there_and_back(objective.get("zone_id")), 0.0, float(objective.get("continuous_game_minutes", 60)), 0.0
    if kind == "catnap":
        return there_and_back(objective.get("zone_id") or f"{lake}:landing"), 3.0, 120.0, 0.0
    if kind in ("catch_species", "fish_livewell"):
        species = objective.get("species_id")
        if species and species not in ctx["catchable"]:
            return 0.0, 0.0, 0.0, math.inf  # a legendary keeps its own clock (legendary_report)
        minutes = catch_minutes(lake, species, _zone_name(objective.get("zone_id")), objective.get("tag"),
                                bool(objective.get("in_cold_band")), ctx["hooks"])
        if objective.get("entry_window"):
            minutes += window_wait([objective["entry_window"]], 0)
        return there_and_back(objective.get("zone_id") or f"{lake}:open"), 2 * MENU_S, 0.0, minutes
    if kind == "wait_weather":
        wait = _weather_wait(ctx["weather_seed"], lake, ctx["clock"], objective.get("weather"),
                             objective.get("then_weather"), float(objective.get("minutes", 0)))
        refs = objective.get("area_ids") or [objective.get("zone_id") or f"{lake}:open"]
        return there_and_back(refs[0]), 0.0, float(objective.get("minutes", 0)), wait
    if kind == "book_stage":
        count = int(objective.get("count", 1))
        per_day = max(0.5, ctx["new_species_per_day"])
        return 0.0, 0.0, 0.0, 1440.0 * max(0.0, count - ctx["identified"]) / per_day
    if kind in ("cook_dish", "tool_use"):
        return 0.0, 2 * MENU_S, 0.0, 0.0
    if kind == "attend_event":
        return 0.0, 30.0, 0.0, 1440.0 * 3.5  # a cookout comes round once a week
    if kind == "settle":
        return 0.0, 45.0 + 40.0, 0.0, 0.0
    return 0.0, 30.0, 0.0, 0.0


def _objectives(quest):
    objective = quest.get("objective")
    return objective if isinstance(objective, list) else [objective]


def _dialogue_seconds(content, quest_id, state):
    from .botidentity import format_text
    total = 0.0
    for stage in ("offer", "accept", "ready", "completion", "done", "return"):
        node = content.dialogue.get(f"{quest_id}:dialogue:{stage}")
        if not node:
            continue
        for bubble in pacing._bubbles(node.get("text")):
            total += reading_seconds(format_text(bubble, state)) + pacing.READ_KEY_S
    return total


def _scene_seconds(content, prefixes, state):
    from .botidentity import format_text
    total = 0.0
    for scene_id, scene in content.scenes.items():
        if any(scene_id.startswith(p) for p in prefixes):
            for line in scene.get("lines", ()):
                total += reading_seconds(format_text(line, state)) + pacing.READ_KEY_S
            if scene.get("choices"):
                total += SCENE_CHOICE_S
    return total


# --- a chapter, day by day ----------------------------------------------------------------

def _available(quest, chapter):
    """Whether a side quest can be offered during this chapter (its `requires`)."""
    needs = quest.get("requires") or {}
    if "chapter_complete" in needs:
        return int(needs["chapter_complete"]) < chapter
    if "travel_unlocked" in needs:
        lakes = [lake for c, lake in CHAPTER_LAKE.items() if c <= chapter]
        return needs["travel_unlocked"] in lakes
    return True


def _side_quests(content, lake, chapter, kinds=("a", "host", "b")):
    quests = []
    for quest_id, quest in content.quests.items():
        if quest.get("lake_id") != lake or quest_id.startswith("story_"):
            continue
        if (quest.get("kind", "v3") in kinds or "kind" not in quest) and _available(quest, chapter):
            quests.append(Item(quest_id, quest.get("giver_id"), False))
    return quests


def _before(content, quest_id):
    """The quest a cat's B quest waits on (quests.quest_available)."""
    quest = content.quests[quest_id]
    if quest.get("kind") != "b":
        return None
    chain = (content.cats.get(quest.get("giver_id"), {}) or {}).get("quests", [])
    return chain[chain.index(quest_id) - 1] if quest_id in chain[1:] else None


def run_chapter(chapter, seed, income, money=0.0, kinds=("a", "host", "b"), leave_when=("story", "a", "host"),
                quests_per_day=QUESTS_PER_DAY):
    """One chapter, day by day: its real minutes, game days, quests done and money."""
    content = load_content()
    lake = CHAPTER_LAKE[chapter]
    stage = next(s for s in pacing.STAGES if s.id == CHAPTER_STAGE[chapter])
    world = lake_world(lake)
    state = State.new(world, seed=seed)
    schedule = state.narrative.schedule_seed
    routine = income[stage.id]
    ctx = {"world": world, "lake": lake, "speed": routine["speed_m_s"],
           "hooks": max(pacing.LINE_TIERS[t]["hooks"] for t in stage.lines),
           "catchable": set(_points_species(lake)), "weather_seed": calendar.forecast_seed(state),
           "identified": 0.0, "new_species_per_day": routine["new_species_per_day"], "clock": 0}
    steps = list(STORY_STEPS[chapter])
    side = _side_quests(content, lake, chapter, kinds)
    # A cat's first quest before anyone's second.
    side.sort(key=lambda item: content.quests[item.quest_id].get("kind") == "b")
    done_on = {}
    real = _scene_seconds(content, CHAPTER_SCENES[chapter], state) + (10.0 if chapter > 1 else 0.0)
    rounds_per_day = max(1.0, routine["rounds_per_day"])
    round_min = routine["drive_min_per_day"] / rounds_per_day
    income_per_round = routine["net_per_day"] / rounds_per_day
    fish_per_round = routine["fish_per_day"] / rounds_per_day
    hooks_set = sum(pacing.LINE_TIERS[t]["hooks"] for t in stage.lines)
    frozen_per_round = (pacing.REAL["landing_s"] + len(stage.lines) * pacing.REAL["line_s"]
                        + hooks_set * pacing.REAL["hook_s"] + fish_per_round * pacing.REAL["card_s"])
    waiting, done, log = [], set(), []
    day, used = 0, 0.0

    def complete(due_by):
        nonlocal money
        finished = False
        for ready, quest_id in sorted(waiting):
            if ready <= due_by:
                waiting.remove((ready, quest_id))
                money += float((content.quests[quest_id].get("reward") or {}).get("cash", 0) or 0)
                done.add(quest_id)
                done_on[quest_id] = int(due_by // 1440)
                log.append((round(due_by / 1440, 2), quest_id))
                finished = True
        return finished

    def finished():
        """The chapter's story is done, and every quest the player stays for."""
        must = [i for i in side if i.quest_id not in done
                and content.quests[i.quest_id].get("kind", "a") in leave_when
                and math.isfinite(_cost(content, i.quest_id, ctx, state)[3])]
        return all(q in done for q in steps) and not must

    def startable(today, taken):
        """The story's next step, and the quests the cats out today offer, up to the day's share."""
        batch = []
        nxt = next((q for q in steps if q not in done), None)
        if nxt is not None and all(q != nxt for _r, q in waiting):
            gear = STEP_GEAR.get(nxt)
            if gear is None or money >= gear[1]:
                batch.append(nxt)
        for item in side:
            if item.quest_id in done or any(q == item.quest_id for _r, q in waiting):
                continue
            before = _before(content, item.quest_id)
            if before is not None and (before not in done or done_on.get(before, day) >= day):
                continue  # B opens the game day after A is turned in
            if item.giver in today and taken + sum(1 for q in batch if not q.startswith("story_")) < quests_per_day:
                batch.append(item.quest_id)
        return batch

    while day < MAX_DAYS and not finished():
        present = set(day_encounters(schedule, lake, day)) | {cast().hosts.get(lake)}
        tonight = night_encounter(schedule, lake, day)
        if tonight:
            present.add(tonight)
        taken = 0
        while used < WAKING_MIN:
            ctx["clock"] = day * 1440 + used
            batch = []
            for quest_id in startable(present, taken):
                frozen, stops, exclusive, passive, extra = _parts(content, quest_id, ctx, state)
                if math.isfinite(passive):
                    batch.append((quest_id, frozen, stops, exclusive, passive, extra))
            if not batch:
                break
            # One tour through every stop of the batch, from the landing and back.
            stops = [p for row in batch for p in row[2]]
            drive = sum(row[5] for row in batch)
            drive += pacing.route(world.dock, stops)[1] / ctx["speed"] if stops else 0.0
            exclusive = sum(row[3] for row in batch)
            # Lines and waits start on the way round (on average halfway), not after the tour.
            under_way = day * 1440 + used + drive / 2
            used += drive + exclusive
            real += drive + sum(row[1] for row in batch) + exclusive / pacing.REAL["wait_scale"]
            taken += sum(1 for row in batch if not row[0].startswith("story_"))
            for quest_id, _f, _s, exclusive_min, passive, _x in batch:
                if quest_id in STEP_GEAR:
                    money -= STEP_GEAR[quest_id][1]
                ready = max(day * 1440 + used, under_way + exclusive_min + passive) if passive else day * 1440 + used
                waiting.append((ready, quest_id))
            complete(day * 1440 + used)
        if finished():
            # Done by mid-day: the player tows on to the next lake rather than finish the day
            # here. The day's browsing comes with them, so it counts in proportion.
            real += BROWSE_S_PER_DAY * min(1.0, used / WAKING_MIN)
            break
        # The rest of the waking day goes on the lines: whole rounds and a part one (the
        # nearer lines), at 1x, with their income and hauls.
        left = max(0.0, WAKING_MIN - used)
        rounds = left / round_min
        money += rounds * income_per_round
        real += left + rounds * frozen_per_round
        real += (1440 - WAKING_MIN) / pacing.REAL["night_scale"] + BROWSE_S_PER_DAY
        ctx["identified"] += routine["new_species_per_day"] * rounds / rounds_per_day
        # Minutes past the waking day run on: whole days of travel, then the next morning's share.
        overflow = max(0.0, used - WAKING_MIN)
        day, used = day + 1 + int(overflow // 1440), overflow % 1440
        complete(day * 1440)  # what came due overnight, collected in the morning
    return {"chapter": chapter, "lake": lake, "seed": seed, "days": day,
            "real_min": round(real / 60.0, 1), "money_end": round(money, 1),
            "story_done": all(q in done for q in steps),
            "side_done": sum(1 for i in side if i.quest_id in done), "side_total": len(side),
            "side_left": [i.quest_id for i in side if i.quest_id not in done], "log": log}


def _parts(content, quest_id, ctx, state):
    """A quest's (frozen real seconds, stops to drive through, exclusive minutes, passive
    minutes, extra driving seconds). Frozen: talk and menus."""
    quest = content.quests[quest_id]
    drive = menus = exclusive = passive = 0.0
    sequential = "kind" in quest  # a V1.0 quest's steps run in order; V3 objectives are one
    ctx["stops"] = []
    giver = world_anchor(ctx["world"], quest.get("giver_id"))
    if giver is not None and not quest_id.startswith("story_"):
        ctx["stops"].append(giver)  # its cat, for the offer and the turn-in
    for objective in _objectives(quest):
        if not isinstance(objective, dict):
            continue
        d, m, e, p = estimate(objective, ctx)
        drive, menus, exclusive = drive + d, menus + m, exclusive + e
        passive = passive + p if sequential else max(passive, p)
    return menus + _dialogue_seconds(content, quest_id, state), list(ctx["stops"]), exclusive, passive, drive


def _cost(content, quest_id, ctx, state):
    """(active real seconds, driving minutes, exclusive minutes, passive minutes) for a
    quest done on its own tour."""
    frozen, stops, exclusive, passive, extra = _parts(content, quest_id, ctx, state)
    drive = extra + (pacing.route(ctx["world"].dock, stops)[1] / ctx["speed"] if stops else 0.0)
    return frozen + drive, drive, exclusive, passive


def world_anchor(world, npc_id):
    anchor = world.anchors.get(cast().anchors.get(npc_id, "") or "")
    return (anchor.x, anchor.z) if anchor is not None else None


@lru_cache(maxsize=None)
def _points_species(lake):
    from .data import SPECIES
    return tuple(sp.id for sp in SPECIES if lake in sp.lakes)


# --- the book --------------------------------------------------------------------------------

BOOK_TARGET_H = (40.0, 60.0)  # all 144 verified in about 50 h (02 §1)
VERIFIED = 5
PERIODS = ((0, 8), (8, 16), (16, 24))  # a day's soaks, in hours after 06:00
BOOK_DAY_REAL_MIN = 22.0  # a book-hunting day: the routine's real minutes on a mid lake


@lru_cache(maxsize=None)
def catch_table(lake):
    """Expected catches of each species per hook per game day, for every sampled place and
    bait on the lake: (places, baits, species ids, array[place, bait, species])."""
    import numpy as np
    from .data import SPECIES
    world = lake_world(lake)
    ids = [sp.id for sp in SPECIES if lake in sp.lakes]
    index = {sid: i for i, sid in enumerate(ids)}
    places = [p for pts in _points(lake).values() for p in pts]
    baits = pacing.baits_for(lake)
    table = np.zeros((len(places), len(baits), len(ids)))
    for pi, (x, z) in enumerate(places):
        depth, here = float(world.depth(x, z)), world.zone_at(x, z)
        for bi, bait in enumerate(baits):
            for lo, hi in PERIODS:
                lam = np.zeros(len(ids))
                for step in range(lo, hi):
                    hour = (6.5 + step) % 24
                    cold = bottools.cold_layer_m(lake, hour, pacing.REFERENCE_WEATHER)
                    tool = bottools.ToolState(cold, False, False, False)
                    for sid, rate in species_rates(here, bait, hour, pacing.REFERENCE_WEATHER, depth, lake,
                                                   tool=tool).items():
                        if rate > 0 and sid in index:
                            lam[index[sid]] += rate
                total = lam.sum()
                if total > 0:
                    table[pi, bi] += (1.0 - math.exp(-total)) * lam / total
    return places, baits, ids, table


BOOK_LINES = 2  # lines the attentive player aims at the book each day; the rest keep earning


def _routine_per_day(lake, stage_id, income):
    """Expected catches per species per day from a stage's routine lines on this lake."""
    import numpy as np
    stage = next(s for s in pacing.STAGES if s.id == stage_id)
    places, baits, ids, table = catch_table(lake)
    hooks = [pacing.LINE_TIERS[t]["hooks"] for t in stage.lines]
    per_day = np.zeros(len(ids))
    for k, spot in enumerate(income[stage_id]["spots"][:len(hooks)]):
        rows = [i for i, p in enumerate(places) if lake_world(lake).zone_at(*p) == spot["zone"]]
        if rows and spot["bait"] in baits:
            per_day += table[rows, baits.index(spot["bait"])].mean(axis=0) * hooks[k]
    return per_day


def book_curve(chapters, income, max_hours=200.0):
    """Real hours until every species is verified (five catches). The story's routine
    fishing first. Then, after the story, each day on the lake with the most still to find,
    `BOOK_LINES` lines go where the species short of five bite best (the book's rumours say
    where) and the rest stay on the earning routine."""
    import numpy as np
    from .data import SPECIES
    counts = {sp.id: 0.0 for sp in SPECIES}
    curve, hours, verified_at = [], 0.0, {}

    def note():
        for sid, c in counts.items():
            if c >= VERIFIED and sid not in verified_at:
                verified_at[sid] = round(hours, 1)

    def stage_counts():
        return {stage: sum(1 for c in counts.values() if c >= threshold)
                for stage, threshold in (("identified", 1), ("verified", VERIFIED), ("mastered", 10))}

    # The story: each chapter's routine, at its own spots, for its days.
    for chapter in chapters:
        lake = chapter["lake"]
        _places, _baits, ids, _table = catch_table(lake)
        per_day = _routine_per_day(lake, CHAPTER_STAGE[chapter["chapter"]], income)
        for sid, n in zip(ids, per_day * chapter["days"]):
            counts[sid] += n
        hours += chapter["real_min"] / 60.0
        note()
        curve.append({"hours": round(hours, 1), "after": f"chapter {chapter['chapter']}", **stage_counts()})
    story_hours = hours
    # After the story: a lake at a time, while a day of aimed lines can still find something.
    post = next(s for s in pacing.STAGES if s.id == "post")
    hook_list = [pacing.LINE_TIERS[t]["hooks"] for t in post.lines[:BOOK_LINES]]
    lakes = list(CHAPTER_LAKE.values())
    routine = {lake: _routine_per_day(lake, CHAPTER_STAGE[c], income) * (len(post.lines) - BOOK_LINES)
               / len(next(s for s in pacing.STAGES if s.id == CHAPTER_STAGE[c]).lines)
               for c, lake in CHAPTER_LAKE.items()}
    while hours < max_hours and any(c < VERIFIED for c in counts.values()):
        best = None
        for lake in lakes:
            places, baits, ids, table = catch_table(lake)
            need = np.array([max(0.0, VERIFIED - counts[sid]) for sid in ids])
            if need.sum() <= 0:
                continue
            gain, plan, left = 0.0, [], need.copy()
            for hooks in hook_list:
                expected = table * hooks  # [place, bait, species]
                value = np.minimum(expected, left).sum(axis=2)
                pi, bi = np.unravel_index(int(value.argmax()), value.shape)
                gain += float(value[pi, bi])
                left = np.maximum(0.0, left - expected[pi, bi])
                plan.append((pi, bi))
            if best is None or gain > best[0]:
                best = (gain, lake, plan)
        if best is None or best[0] <= 1e-6:
            break  # nothing left that any line can find
        _gain, lake, plan = best
        places, baits, ids, table = catch_table(lake)
        for (pi, bi), hooks in zip(plan, hook_list):
            for sid, n in zip(ids, table[pi, bi] * hooks):
                counts[sid] += n
        for sid, n in zip(ids, routine[lake]):
            counts[sid] += n
        hours += BOOK_DAY_REAL_MIN / 60.0
        note()
        if not curve or hours - curve[-1]["hours"] >= 5.0:
            curve.append({"hours": round(hours, 1), "after": "book hunting", **stage_counts()})
    unreached = sorted(sid for sid, c in counts.items() if c < VERIFIED)
    curve.append({"hours": round(hours, 1), "after": "end", **stage_counts()})
    return {"story_hours": round(story_hours, 1), "all_verified_hours": None if unreached else round(hours, 1),
            "unverified": unreached, "curve": curve, "target_hours": list(BOOK_TARGET_H),
            "verified_at": verified_at}


# --- the legendaries -------------------------------------------------------------------------

REAL_MIN_PER_GAME_DAY = 22.0  # an attentive day on the water, for converting waits to real time


def legendary_report(chapters, money_by_chapter=None):
    """When each legendary first becomes catchable for the attentive player, in real hours
    from a new game: its lake reached, its bait in hand (a recipe from its teller, the
    parents and the ingredient on sale), its gate met, then its next calendar window."""
    from .data import BAIT_BY_ID, BAIT_RECIPES, CONTENT_V2_RAW, PANTRY
    content = load_content()
    rows = CONTENT_V2_RAW["legendaries.json"]["legendaries"]
    arrive, finish, game_day0, marks, day_at = {}, {}, {}, {}, {}
    t, days = 0.0, 0
    for chapter in chapters:
        arrive[chapter["lake"]] = t
        game_day0[chapter["lake"]] = days
        for day, quest_id in chapter["log"]:
            marks[quest_id] = t + day / max(1, chapter["days"]) * chapter["real_min"]
            day_at[quest_id] = days + day
        t += chapter["real_min"]
        days += chapter["days"]
        finish[chapter["chapter"]] = t
    lakes_by_time = sorted(arrive, key=arrive.get)

    def first_sale(sold_at):
        if "all" in sold_at:
            return 0.0
        options = [arrive[lake] for lake in sold_at if lake in arrive]
        return min(options) if options else math.inf

    def teller_met(npc_id):
        lake = cast().anchors.get(npc_id, "").split(":")[0]
        quests = [marks[q] for q in marks if content.quests.get(q, {}).get("giver_id") == npc_id]
        return min(quests) if quests else arrive.get(lake, math.inf) + REAL_MIN_PER_GAME_DAY

    # V3 ripples (the narrative ledger's) in the order their quests were turned in.
    v3_ripples = sorted(marks[q] for q in marks if "kind" not in content.quests.get(q, {"kind": 1})
                        and (content.rewards.get(f"{q}:reward") or {}).get("ripple_id"))
    report = []
    for row in rows:
        lake, needs = row["lake"], row["requirements"]
        when = {"lake reached": arrive.get(lake, math.inf)}
        bait = needs.get("bait")
        if bait in BAIT_RECIPES:
            recipe = BAIT_RECIPES[bait]
            when["recipe told"] = teller_met(recipe.teller)
            when["parents on sale"] = max(first_sale(BAIT_BY_ID[p].sold_at) for p in recipe.parents)
            when["ingredient on sale"] = arrive.get(PANTRY[recipe.ingredient].lake, 0.0) \
                if PANTRY[recipe.ingredient].lake != "all" else 0.0
        elif bait:
            when["bait on sale"] = first_sale(BAIT_BY_ID[bait].sold_at)
        gate = needs.get("gate")
        if isinstance(gate, dict) and "chapter" in gate:
            when[f"chapter {gate['chapter']} done"] = finish.get(gate["chapter"], math.inf)
        elif isinstance(gate, dict) and gate.get("line_tier") == "heavy":
            when["heavy line"] = arrive.get("crater", math.inf)  # bought for chapter 4 (pacing.STAGES)
        elif isinstance(gate, dict) and "ripples" in gate:
            need = int(gate["ripples"])
            when[f"{need} ripples"] = v3_ripples[need - 1] if len(v3_ripples) >= need else math.inf
        elif gate == "spotlight":
            when["spotlight"] = arrive.get("briar", 0.0) + 2 * REAL_MIN_PER_GAME_DAY  # $ after two days
        elif gate == "cold_band":
            when["cold band"] = arrive.get("flathead", math.inf)
        elif gate == "whopper_story":
            when["Whopper told thrice"] = marks.get("host_flathead", finish.get(3, math.inf))
        elif gate == "mist_poem":
            when["mist poem"] = marks.get("wc_mist_a", math.inf)
        elif gate == "zero_g_winch":
            when["winch bought"] = arrive.get("nebula", math.inf)
        eligible = max(when.values())
        # Then its window: the forecast's next favourable stretch, three game days at most.
        window = 0.0
        if math.isfinite(eligible) and row["kind"] == "caught":
            minute = (day_at.get(max(when, key=when.get)) or game_day0.get(lake, 0)) * 1440
            try:
                start, _end = calendar.next_legendary_window(37, row["id"], float(minute))
                window = (start - minute) / 1440.0 * REAL_MIN_PER_GAME_DAY
            except (KeyError, ValueError):
                window = 0.0
        report.append({"id": row["id"], "lake": lake, "kind": row["kind"],
                       "eligible_h": round((eligible + window) / 60.0, 2) if math.isfinite(eligible) else None,
                       "gates_h": {k: round(v / 60.0, 2) if math.isfinite(v) else None for k, v in when.items()},
                       "window_wait_min": round(window, 1)})
    return report
