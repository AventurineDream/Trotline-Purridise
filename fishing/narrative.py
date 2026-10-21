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
NPC_IDS = frozenset({"grandmother_whiskers", "doc_barnaby", "master_cinder"}).union(
    *(set(pool) for pool in DAY_NPCS.values()))
BOT_REACTION_KEYS = frozenset(
    [f"npc:{npc_id}" for npc_id in NPC_IDS]
    + [f"quest:{quest_id}" for quest_id in QUEST_IDS])
BOT_JOURNAL_LIMIT = 40
_INVALID = object()
_QUEST_PROGRESS_FIELDS = frozenset({
    "status", "progress", "accepted_game_minute", "declined",
})
_NARRATIVE_FIELDS = frozenset({
    "quests", "ripples", "schedule_seed", "day_npc_by_lake",
    "schedule_day_by_lake", "bot_notes", "bot_reactions", "bot_journal",
    "reward_claims", "guardian_seen", "active_play_game_minutes",
})


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


def _preserve_unknown_list(current, source, allowed, unknown):
    if isinstance(source, list) and current == _ids(source, allowed):
        return deepcopy(source)
    result = list(current)
    result.extend(deepcopy(item) for item in unknown if item not in result)
    return result


@dataclass
class QuestProgress:
    status: str = "available"
    progress: dict = field(default_factory=dict)
    accepted_game_minute: float | None = None
    declined: bool = False
    extra_fields: dict = field(default_factory=dict, repr=False)

    def to_json(self):
        result = deepcopy(self.extra_fields)
        result.update({"status": self.status, "progress": deepcopy(self.progress),
                      "accepted_game_minute": self.accepted_game_minute,
                      "declined": self.declined})
        return result

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
                   raw.get("declined") is True,
                   {key: deepcopy(value) for key, value in raw.items()
                    if key not in _QUEST_PROGRESS_FIELDS})


@dataclass
class NarrativeState:
    quests: dict[str, QuestProgress] = field(
        default_factory=lambda: {qid: QuestProgress() for qid in QUEST_IDS})
    ripples: list[str] = field(default_factory=list)
    schedule_seed: int = 0
    day_npc_by_lake: dict = field(default_factory=lambda: dict.fromkeys(DAY_NPCS))
    schedule_day_by_lake: dict = field(default_factory=lambda: dict.fromkeys(DAY_NPCS))
    bot_notes: list[str] = field(default_factory=list)
    bot_reactions: dict[str, str] = field(default_factory=dict)
    bot_journal: list[str] = field(default_factory=list)
    reward_claims: list[str] = field(default_factory=list)
    guardian_seen: bool = False
    active_play_game_minutes: float = 0.0
    extra_fields: dict = field(default_factory=dict, repr=False)
    extra_quest_entries: dict = field(default_factory=dict, repr=False)
    extra_day_npc_by_lake: dict = field(default_factory=dict, repr=False)
    extra_schedule_days: dict = field(default_factory=dict, repr=False)
    extra_bot_reactions: dict = field(default_factory=dict, repr=False)
    extra_ripples: list = field(default_factory=list, repr=False)
    source_ripples: list | None = field(default=None, repr=False)
    extra_reward_claims: list = field(default_factory=list, repr=False)
    source_reward_claims: list | None = field(default=None, repr=False)

    def _append_bot_journal(self, note: str) -> None:
        self.bot_journal.append(note)
        del self.bot_journal[:-BOT_JOURNAL_LIMIT]

    def record_bot_note(self, note: str) -> bool:
        """Keep the existing two scout reports and journal their delivery."""
        if not isinstance(note, str) or not note.strip():
            return False
        note = note.strip()
        self.bot_notes.append(note)
        del self.bot_notes[:-2]
        self._append_bot_journal(note)
        return True

    def record_bot_reaction(self, key: str, note: str) -> bool:
        """Record a one-time NPC or completed-quest cue without game effects."""
        if (not isinstance(key, str) or key not in BOT_REACTION_KEYS
                or key in self.bot_reactions
                or not isinstance(note, str) or not note.strip()):
            return False
        note = note.strip()
        self.bot_reactions[key] = note
        self._append_bot_journal(note)
        return True

    def record_reward_claim(self, quest_id: str) -> bool:
        """Latch a ready quest once before applying its validated reward.

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
        quests = deepcopy(self.extra_quest_entries)
        quests.update({qid: quest.to_json() for qid, quest in self.quests.items()})
        day_npc_by_lake = deepcopy(self.extra_day_npc_by_lake)
        day_npc_by_lake.update(self.day_npc_by_lake)
        schedule_days = deepcopy(self.extra_schedule_days)
        schedule_days.update(self.schedule_day_by_lake)
        bot_reactions = deepcopy(self.extra_bot_reactions)
        bot_reactions.update(self.bot_reactions)
        ripples = _preserve_unknown_list(self.ripples, self.source_ripples,
                                         RIPPLE_BY_QUEST.values(), self.extra_ripples)
        claims = _preserve_unknown_list(self.reward_claims, self.source_reward_claims,
                                        QUEST_IDS, self.extra_reward_claims)
        result = deepcopy(self.extra_fields)
        result.update({
            "quests": quests,
            "ripples": ripples, "schedule_seed": self.schedule_seed,
            "day_npc_by_lake": day_npc_by_lake,
            "schedule_day_by_lake": schedule_days,
            "bot_notes": list(self.bot_notes),
            "bot_reactions": bot_reactions,
            "bot_journal": list(self.bot_journal),
            "reward_claims": claims,
            "guardian_seen": self.guardian_seen,
            "active_play_game_minutes": self.active_play_game_minutes,
        })
        return result

    @classmethod
    def from_json(cls, raw):
        st = cls()
        if not isinstance(raw, dict):
            return st
        st.extra_fields = {key: deepcopy(value) for key, value in raw.items()
                           if key not in _NARRATIVE_FIELDS}
        quests = raw.get("quests")
        if isinstance(quests, dict):
            st.extra_quest_entries = {
                key: deepcopy(value) for key, value in quests.items()
                if key not in QUEST_IDS
            }
            st.quests = {qid: QuestProgress.from_json(quests.get(qid)) for qid in QUEST_IDS}
        ripple_values = raw.get("ripples")
        if isinstance(ripple_values, list):
            st.source_ripples = deepcopy(ripple_values)
            st.extra_ripples = [deepcopy(item) for item in ripple_values
                                if not (isinstance(item, str)
                                        and item in RIPPLE_BY_QUEST.values())]
        st.ripples = _ids(raw.get("ripples"), RIPPLE_BY_QUEST.values())
        seed = raw.get("schedule_seed")
        st.schedule_seed = seed if type(seed) is int else 0
        choices, days = raw.get("day_npc_by_lake"), raw.get("schedule_day_by_lake")
        if isinstance(choices, dict):
            st.extra_day_npc_by_lake = {
                key: deepcopy(value) for key, value in choices.items()
                if key not in DAY_NPCS
            }
        if isinstance(days, dict):
            st.extra_schedule_days = {
                key: deepcopy(value) for key, value in days.items()
                if key not in DAY_NPCS
            }
        if isinstance(choices, dict) and isinstance(days, dict):
            for lake, pool in DAY_NPCS.items():
                npc, day = choices.get(lake), days.get(lake)
                if isinstance(npc, str) and npc in pool and type(day) is int and day >= 0:
                    st.day_npc_by_lake[lake], st.schedule_day_by_lake[lake] = npc, day
        notes = raw.get("bot_notes")
        if isinstance(notes, list):
            st.bot_notes = [note.strip() for note in notes
                            if isinstance(note, str) and note.strip()][-2:]
        reactions = raw.get("bot_reactions")
        if isinstance(reactions, dict):
            st.extra_bot_reactions = {
                key: deepcopy(value) for key, value in reactions.items()
                if key not in BOT_REACTION_KEYS
            }
            st.bot_reactions = {
                key: note.strip()[:240]
                for key, note in reactions.items()
                if (isinstance(key, str) and key in BOT_REACTION_KEYS
                    and isinstance(note, str) and note.strip())
            }
        journal = raw.get("bot_journal")
        if isinstance(journal, list):
            st.bot_journal = [note.strip()[:240] for note in journal
                              if isinstance(note, str) and note.strip()][-BOT_JOURNAL_LIMIT:]
        else:
            # Older saves only had the last two delivered scout reports.
            st.bot_journal = (list(st.bot_notes)
                              + [note for note in st.bot_reactions.values()])[-BOT_JOURNAL_LIMIT:]
        st.reward_claims = _ids(raw.get("reward_claims"), QUEST_IDS)
        raw_claims = raw.get("reward_claims")
        if isinstance(raw_claims, list):
            st.source_reward_claims = deepcopy(raw_claims)
            st.extra_reward_claims = [deepcopy(item) for item in raw_claims
                                      if not (isinstance(item, str) and item in QUEST_IDS)]
        for qid, quest in st.quests.items():
            if qid in st.reward_claims:
                quest.status = "completed"
            elif quest.status == "completed":
                st.reward_claims.append(qid)
        st.guardian_seen = raw.get("guardian_seen") is True
        st.active_play_game_minutes = _number(raw.get("active_play_game_minutes"))
        return st
