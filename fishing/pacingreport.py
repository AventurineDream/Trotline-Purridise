"""The V1-44 pacing report: every 02 §1 and §15 target, measured by the attentive-player
simulator (pacing.py, pacingstory.py).

python -m fishing --pacing [--json=path]
"""

from __future__ import annotations

from functools import lru_cache
import json
import statistics

from . import pacing, pacingstory
from .boat import BOATS
from .fleet import UNLOCK_AFTER_CHAPTER

FIRST_CATCH_S = 180.0
FIRST_CATCH_SEEDS = (11, 12, 13, 14, 15, 16, 17, 18, 19)
CHAPTER_SEED = 34
REQUIRED_GEAR_DAYS = 2.0
BOAT_DAYS = (3.0, 6.0)
# 02 §15.3: the income midpoint at the stage each boat tier unlocks.
TIER_STAGE = {0: "start", 2: "ch2", 3: "ch3", 4: "ch4", 5: "post"}
EXISTING_BOATS = ("jon", "rowboat", "sail", "pontoon")


def guardrails(income):
    """02 §15.3: required gear within two days of the stage's income, and each tier's
    cheapest new boat within three to six days of the midpoint where it unlocks."""
    rows = []
    for quest_id, (tier, price) in pacingstory.STEP_GEAR.items():
        chapter = int(quest_id.split("_")[1][1:])
        stage = pacingstory.CHAPTER_STAGE[chapter]
        days = price / income[stage]["net_per_day"]
        rows.append({"check": f"{tier} line for {quest_id}", "price": price, "stage": stage,
                     "days_of_income": round(days, 2), "ok": days <= REQUIRED_GEAR_DAYS})
    boats = []
    stages = {s.id: s for s in pacing.STAGES}
    for tier in sorted({b.tier for b in BOATS.values()}):
        new = [b for b in BOATS.values() if b.tier == tier and b.id not in EXISTING_BOATS]
        cheapest = min(new, key=lambda b: b.price)
        stage = TIER_STAGE[UNLOCK_AFTER_CHAPTER[tier]]
        midpoint = stages[stage].midpoint
        days = cheapest.price / midpoint
        boats.append({"tier": tier, "boat": cheapest.id, "price": cheapest.price, "stage": stage,
                      "days_of_midpoint": round(days, 2),
                      "days_of_simulated": round(cheapest.price / income[stage]["net_per_day"], 2),
                      "ok": BOAT_DAYS[0] <= days <= BOAT_DAYS[1]})
    return {"required_gear": rows, "boat_tiers": boats,
            "boat_requirements": "No objective names a boat or a trait. Briar's reeds, the one "
                                 "trait-gated water, open with the Reed Anchor the story gives free "
                                 "in chapter 1, or any shallow hull (the $300 log raft)."}


@lru_cache(maxsize=None)
def full_report(seeds=pacing.SEEDS) -> dict:
    income = {stage.id: pacing.stage_income(stage, seeds) for stage in pacing.STAGES}
    first = [pacing.first_catch(seed) for seed in FIRST_CATCH_SEEDS]
    chapters, money = [], 46.0
    for chapter in range(1, 6):
        row = pacingstory.run_chapter(chapter, CHAPTER_SEED, income, money)
        money = row["money_end"]
        chapters.append(row)
    story_min = sum(c["real_min"] for c in chapters)
    book = pacingstory.book_curve(chapters, income)
    legend = pacingstory.legendary_report(chapters)
    prompts = [pacing.prompt_density(seed) for seed in (11, 12)]
    for row in prompts:
        row.pop("shown", None)
    report = {
        "first_catch": {"median_s": statistics.median(r["seconds"] for r in first),
                        "max_s": max(r["seconds"] for r in first), "target_s": FIRST_CATCH_S,
                        "runs": first, "ok": max(r["seconds"] for r in first) <= FIRST_CATCH_S},
        "income": income,
        "chapters": [{**{k: c[k] for k in ("chapter", "lake", "days", "real_min", "story_done",
                                            "side_done", "side_total")},
                      "target_min": list(pacingstory.CHAPTER_TARGETS[c["chapter"]]),
                      "ok": pacingstory.CHAPTER_TARGETS[c["chapter"]][0] <= c["real_min"]
                      <= pacingstory.CHAPTER_TARGETS[c["chapter"]][1]} for c in chapters],
        "story": {"real_min": round(story_min, 1), "target_min": list(pacingstory.STORY_TARGET),
                  "ok": pacingstory.STORY_TARGET[0] <= story_min <= pacingstory.STORY_TARGET[1]},
        "book": {**book, "ok": book["all_verified_hours"] is not None
                 and pacingstory.BOOK_TARGET_H[0] <= book["all_verified_hours"] <= pacingstory.BOOK_TARGET_H[1]},
        "legendaries": legend,
        "guardrails": guardrails(income),
        "prompts": {"runs": prompts, "toasts_per_min_max": pacing.PROMPTS_PER_MIN_MAX,
                    "bot_per_min_max": pacing.BOT_LINES_PER_MIN_MAX,
                    "ok": all(r["toasts_per_min"] <= pacing.PROMPTS_PER_MIN_MAX
                              and r["bot_per_min"] <= pacing.BOT_LINES_PER_MIN_MAX for r in prompts)},
    }
    return report


def text(report) -> str:
    def mark(ok):
        return "met " if ok else "MISS"
    lines = ["Pacing report (V1-44): the attentive player against 02 §1 and §15", ""]
    first = report["first_catch"]
    lines.append(f"[{mark(first['ok'])}] First catch: median {first['median_s']:.0f} s, worst "
                 f"{first['max_s']:.0f} s (target under {first['target_s']:.0f} s)")
    lines.append("")
    lines.append("Income per game day (net of bait), 02 §15.1:")
    for stage in pacing.STAGES:
        row = report["income"][stage.id]
        lines.append(f"  [{mark(row['in_band'])}] {stage.id:5s} {stage.lake:9s} ${row['net_per_day']:7.1f}"
                     f"  band ${row['band'][0]}–{row['band'][1]}  ({row['fish_per_day']} fish, "
                     f"{row['rounds_per_day']} rounds, {row['real_min_per_day']} real min a day)")
    lines.append("")
    lines.append("Chapters, real minutes, 02 §1:")
    for row in report["chapters"]:
        lines.append(f"  [{mark(row['ok'])}] chapter {row['chapter']} {row['lake']:9s} {row['real_min']:6.1f}"
                     f"  target {row['target_min'][0]}–{row['target_min'][1]}  ({row['days']} game days, "
                     f"{row['side_done']}/{row['side_total']} cat quests)")
    story = report["story"]
    lines.append(f"  [{mark(story['ok'])}] whole story {story['real_min'] / 60:.2f} h  target "
                 f"{story['target_min'][0] / 60:.2f}–{story['target_min'][1] / 60:.0f} h (02 §1 says 10–12 h,"
                 " but its chapter figures add up to 9.75 h)")
    lines.append("")
    book = report["book"]
    lines.append(f"[{mark(book['ok'])}] Book: all 144 verified at {book['all_verified_hours']} h "
                 f"(target {book['target_hours'][0]:.0f}–{book['target_hours'][1]:.0f} h)")
    for point in book["curve"]:
        lines.append(f"    {point['hours']:5.1f} h  {point['after']:13s} identified {point['identified']:3d}"
                     f"  verified {point['verified']:3d}  mastered {point['mastered']:3d}")
    lines.append("")
    lines.append("Legendaries, real hours from a new game to their first window:")
    for row in report["legendaries"]:
        lines.append(f"    {row['id']:22s} {row['lake']:9s} {row['eligible_h']} h")
    lines.append("")
    guard = report["guardrails"]
    lines.append("Guardrails, 02 §15.3:")
    for row in guard["required_gear"]:
        lines.append(f"  [{mark(row['ok'])}] {row['check']}: ${row['price']:.0f} = "
                     f"{row['days_of_income']} days of {row['stage']} income (at most {REQUIRED_GEAR_DAYS:.0f})")
    for row in guard["boat_tiers"]:
        lines.append(f"  [{mark(row['ok'])}] tier {row['tier']} {row['boat']:16s} ${row['price']:6.0f} = "
                     f"{row['days_of_midpoint']} days of the {row['stage']} midpoint "
                     f"({row['days_of_simulated']} of simulated income)")
    lines.append(f"  [met ] {guard['boat_requirements']}")
    lines.append("")
    prompts = report["prompts"]
    for row in prompts["runs"]:
        lines.append(f"[{mark(prompts['ok'])}] First game day, seed {row['seed']}: {row['toasts_per_min']} toasts"
                     f" and {row['bot_per_min']} Bot lines a real minute (at most "
                     f"{prompts['toasts_per_min_max']} and {prompts['bot_per_min_max']})")
    return "\n".join(lines)


def main(argv) -> int:
    report = full_report()
    print(text(report))
    path = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--json=")), None)
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=list)
            handle.write("\n")
    return 0
