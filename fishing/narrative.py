"""Version-one narrative save ledger. No scheduling, event evaluation or payouts.

The optional object lives inside the existing version-one fishing save. Invalid
optional fields are repaired independently so they cannot discard fishing state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from uuid import UUID


QUEST_IDS = (
    "q01_tea_leaves_deep_holes", "q02_lonely_star_current",
    "q03_unstrung_line", "q04_great_contour_chart", "q05_moonlight_trotlines",
    "q06_unrepeatable_sunrise", "q07_art_of_the_nap", "q08_channel_run",
    "q09_quiet_channel", "q10_ballad_lonely_star", "q11_deep_water_drift",
    "q12_first_voyage",
)
RIPPLE_BY_QUEST = {qid: f"ripple_{i:02d}" for i, qid in enumerate(QUEST_IDS[2:], 1)}
DAY_NPCS = {
    "briar": ("elder_moss", "pip_pebble", "willow", "silas"),
    "cedar": ("captain_maeve", "sparky", "quill", "dr_alder", "patch"),
}
_INVALID = object()


def deployment_id(value) -> str | None:
    """Keep the original UUID spelling so historical references stay identical."""
    if not isinstance(value, str):
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


def _number(value, default=0.0):
    if type(value) not in (int, float):
        return default
    try:
        return value if math.isfinite(value) and value >= 0 else default
    except OverflowError:
        return default


def _json_value(value, depth=0):
    """Copy finite JSON progress, dropping bad leaves rather than valid siblings."""
    if depth > 24:
        return _INVALID
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else _INVALID
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str):
                clean = _json_value(item, depth + 1)
                if clean is not _INVALID:
                    out[key] = clean
        return out
    if isinstance(value, list):
        return [clean for item in value
                if (clean := _json_value(item, depth + 1)) is not _INVALID]
    return _INVALID


def _ids(value, allowed):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value
                              if isinstance(item, str) and item in allowed))


@dataclass
class QuestProgress:
    status: str = "available"
    progress: dict = field(default_factory=dict)
    accepted_game_minute: float | None = None
    declined: bool = False

    def to_json(self):
        return {"status": self.status, "progress": deepcopy(self.progress),
                "accepted_game_minute": self.accepted_game_minute,
                "declined": self.declined}

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, dict):
            return cls()
        status = raw.get("status")
        if status not in ("available", "active", "ready", "completed"):
            status = "available"
        progress = raw.get("progress")
        return cls(status, _json_value(progress) if isinstance(progress, dict) else {},
                   _number(raw.get("accepted_game_minute"), None),
                   raw.get("declined") is True)


@dataclass
class NarrativeState:
    quests: dict[str, QuestProgress] = field(
        default_factory=lambda: {qid: QuestProgress() for qid in QUEST_IDS})
    ripples: list[str] = field(default_factory=list)
    schedule_seed: int = 0
    day_npc_by_lake: dict = field(default_factory=lambda: dict.fromkeys(DAY_NPCS))
    schedule_day_by_lake: dict = field(default_factory=lambda: dict.fromkeys(DAY_NPCS))
    bot_notes: list[str] = field(default_factory=list)
    reward_claims: list[str] = field(default_factory=list)
    guardian_seen: bool = False
    active_play_game_minutes: float = 0.0

    def record_reward_claim(self, quest_id: str) -> bool:
        """Latch a ready quest's claim once; the later turn-in code owns payouts.

        Completed quests also block claims, including older ledgers with no
        explicit reward_claims list. Loading this ledger never grants rewards.
        """
        quest = self.quests[quest_id]
        if quest_id in self.reward_claims or quest.status != "ready":
            return False
        self.reward_claims.append(quest_id)
        quest.status = "completed"
        return True

    def to_json(self):
        return {
            "quests": {qid: quest.to_json() for qid, quest in self.quests.items()},
            "ripples": list(self.ripples), "schedule_seed": self.schedule_seed,
            "day_npc_by_lake": dict(self.day_npc_by_lake),
            "schedule_day_by_lake": dict(self.schedule_day_by_lake),
            "bot_notes": list(self.bot_notes), "reward_claims": list(self.reward_claims),
            "guardian_seen": self.guardian_seen,
            "active_play_game_minutes": self.active_play_game_minutes,
        }

    @classmethod
    def from_json(cls, raw):
        st = cls()
        if not isinstance(raw, dict):
            return st
        quests = raw.get("quests")
        if isinstance(quests, dict):
            st.quests = {qid: QuestProgress.from_json(quests.get(qid)) for qid in QUEST_IDS}
        st.ripples = _ids(raw.get("ripples"), RIPPLE_BY_QUEST.values())
        seed = raw.get("schedule_seed")
        st.schedule_seed = seed if type(seed) is int else 0
        choices, days = raw.get("day_npc_by_lake"), raw.get("schedule_day_by_lake")
        if isinstance(choices, dict) and isinstance(days, dict):
            for lake, pool in DAY_NPCS.items():
                npc, day = choices.get(lake), days.get(lake)
                if isinstance(npc, str) and npc in pool and type(day) is int and day >= 0:
                    st.day_npc_by_lake[lake], st.schedule_day_by_lake[lake] = npc, day
        notes = raw.get("bot_notes")
        if isinstance(notes, list):
            st.bot_notes = [note for note in notes if isinstance(note, str)]
        st.reward_claims = _ids(raw.get("reward_claims"), QUEST_IDS)
        for qid, quest in st.quests.items():
            if qid in st.reward_claims:
                quest.status = "completed"
            elif quest.status == "completed":
                st.reward_claims.append(qid)
        st.guardian_seen = raw.get("guardian_seen") is True
        st.active_play_game_minutes = _number(raw.get("active_play_game_minutes"))
        return st
