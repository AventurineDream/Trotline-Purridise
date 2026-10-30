"""V1-34 story scenes: the script's authored moments (05 §1–3), each pending or done (06 §3.3).

A scene is one speaker's bubbles, followed by the next scene or a choice between scenes
(`quests.json` scenes). It is pending from its first bubble and done once its last bubble
is read. Its effects (a story step turned in, the prologue's steps starting) run only when
it is done, and every reward is claimed once through the ledger. A pending scene replays
from its start: an interrupted game reloads into it and never pays twice.

Scenes start by themselves when their moment comes (`due_scene`, checked while the
Skipper is free to talk) or when their cat is hailed (`hail_scene`). A scene can't be
left half-read: Esc does not close it.
"""

import math

from .quests import _story, autostart_story, claim_story_step, current_step, quest_status, scene_state

# Scenes that play by themselves when their moment comes, in story order: (first scene of
# the chain, whether its moment has come). A chain replays from its first scene not yet done.
_AUTO = (
    ("pro_01", lambda state: scene_state(state, "prologue") == "pending"),   # a new game (05 §1)
    ("pro_03", lambda state: quest_status(state, "story_c0_s1") == "ready"),  # the first line is set
    ("pro_04", lambda state: quest_status(state, "story_c0_s2") == "ready"),  # the first catch
    ("story_c3_cold", lambda state: quest_status(state, "story_c3_s2") == "ready"),  # both readings (05 §2.3)
    ("story_c4_clear", lambda state: quest_status(state, "story_c4_s2") == "ready"),  # the fog lifts (05 §2.4)
    # At the marker, before the reading; it stays due until Bot has his knot.
    ("story_c4_knot", lambda state: quest_status(state, "story_c4_s3") in ("ready", "completed")),
    ("story_c5_arrive", lambda state: _chapter(state) >= 5),  # the first trip onto the sky (05 §2.5)
    ("story_c5_together", lambda state: quest_status(state, "story_c5_s2") == "active"
     and settle_progress(state)["cues"] >= 1),  # after the first cue, Astra-9 drifts alongside
    ("story_c5_whale", lambda state: quest_status(state, "story_c5_s2") == "ready"),
    # Home at Briar Landing, by the free trip or any other way (02 §13, 05 §3).
    ("end_01", lambda state: quest_status(state, "story_c5_s3") in ("active", "ready")),
)
# Scenes a hail opens: (first scene, the cat hailed, whether its moment has come).
_HAIL = (
    ("pro_05", "grandmother_whiskers", lambda state: quest_status(state, "story_c0_s3") == "ready"),
)
# The story step a scene turns in once it is done.
_TURNS_IN = {"pro_03": "story_c0_s1", "pro_04": "story_c0_s2", "pro_06": "story_c0_s3",
             "story_c3_cold": "story_c3_s2", "story_c4_clear": "story_c4_s2", "story_c5_drawn": "story_c5_s2",
             "end_03": "story_c5_s3"}
# The ending completes the last step, "Go home to Briar Landing", whatever brought the Skipper home.
_COMPLETES = {"end_03": "story_c5_s3"}

# Settle In (02 §13.5): 45 real seconds of stillness near the calm reflection, in three cues.
SETTLE_AREA = "nebula:calm_reflection"
SETTLE_ZONE = "nebula:open"  # where "Settle in" is offered, and the zone the settle step names
SETTLE_RADIUS_M = 200.0
SETTLE_CUES = (15.0, 30.0, 45.0)
SETTLE_LINES = ("The stars have stopped wobbling.",
                "The lilies are drifting toward us. Slowly. I think they are curious.",
                "Something is coming up. It is not in a hurry.")


def _chapter(state) -> int:
    chapter = _story(state).get("chapter", 0)
    return chapter if type(chapter) is int else 0


def begin_prologue(state) -> None:
    """A new game opens with the prologue (05 §1). Migrated saves skip it (06 §3.3)."""
    if scene_state(state, "prologue") is None:
        state.set_scene_status("prologue", "pending")


def _targets(row: dict) -> list:
    if "choices" in row:
        return [choice["next"] for choice in row["choices"] if choice["next"] is not None]
    return [row["next"]] if row.get("next") is not None else []


def resume(state, content, scene_id: str | None) -> str | None:
    """The first scene of this chain that is not done. After a choice, only the branch the
    Skipper took is followed. Taking a choice starts its next scene in the same step, so a done
    scene with no branch started ended the chain there (a choice with no next scene)."""
    seen = set()
    while scene_id is not None and scene_id not in seen and scene_id in content.scenes:
        seen.add(scene_id)
        if scene_state(state, scene_id) != "done":
            return scene_id
        row = content.scenes[scene_id]
        targets = _targets(row)
        if "choices" in row:
            targets = ([t for t in targets if scene_state(state, t) == "pending"]
                       or [t for t in targets if scene_state(state, t) == "done"])
        scene_id = targets[0] if targets else None
    return None


def due_scene(state, content) -> str | None:
    """The scene whose moment has come on this lake, if any."""
    for start, moment in _AUTO:
        if start in content.scenes and moment(state):
            scene_id = resume(state, content, start)
            if scene_id is not None and content.scenes[scene_id]["lake_id"] == state.lake_id:
                return scene_id
    return None


def hail_scene(state, content, npc_id: str) -> str | None:
    """The scene hailing this cat opens: theirs to tell now, or one of theirs left pending."""
    for start, cat, moment in _HAIL:
        if cat == npc_id and start in content.scenes and moment(state):
            scene_id = resume(state, content, start)
            if scene_id is not None:
                return scene_id
    scene_id = due_scene(state, content)
    if scene_id is not None and content.scenes[scene_id]["speaker_id"] == npc_id:
        return scene_id
    return None


def scene_conversation(state, content, scene_id: str):
    """The conversation that plays this scene and every scene it leads to, one node a bubble."""
    from .dialogue import Conversation, enter_node
    nodes = {}
    stack = [scene_id]
    while stack:
        sid = stack.pop()
        if f"scene:{sid}" in nodes:
            continue
        row = content.scenes[sid]
        lines = row["lines"] if isinstance(row["lines"], list) else [row["lines"]]
        ids = [f"scene:{sid}"] + [f"scene:{sid}:{i}" for i in range(2, len(lines) + 1)]
        for i, (node_id, text) in enumerate(zip(ids, lines)):
            node = {"id": node_id, "quest_id": None, "speaker_id": row["speaker_id"], "text": text,
                    "scene": sid}
            if i == 0:
                node["scene_start"] = sid
            if i + 1 < len(ids):
                node["next"] = ids[i + 1]
            else:
                node["scene_end"] = sid
                if "choices" in row:
                    node["choices"] = [
                        {"id": f"scene:{sid}:choice:{j}", "text": choice["text"], "action": "scene",
                         "target": f"scene:{choice['next']}" if choice["next"] is not None else None,
                         **{key: choice[key] for key in ("knot", "together", "trip") if key in choice}}
                        for j, choice in enumerate(row["choices"])]
                else:
                    node["next"] = f"scene:{row['next']}" if row.get("next") is not None else None
                stack.extend(_targets(row))
            nodes[node_id] = node
    chat = Conversation(content.scenes[scene_id]["speaker_id"], None, f"scene:{scene_id}", nodes=nodes)
    enter_node(state, nodes[chat.node_id])
    return chat


def start_scene(state, scene_id: str) -> None:
    """Its first bubble is on screen: the scene is pending until it is read through."""
    if scene_state(state, scene_id) != "done":
        state.set_scene_status(scene_id, "pending")


def finish_scene(state, content, scene_id: str) -> bool:
    """Its last bubble is read: mark it done and run its effects, once."""
    if scene_state(state, scene_id) == "done":
        return False
    state.set_scene_status(scene_id, "done")
    if scene_id == "end_02":
        state.set_book_title("book_of_five_waters")  # the spine re-stitched (05 §3)
    completes = _COMPLETES.get(scene_id)
    progress = state.narrative.quests.get(completes) if completes else None
    if progress is not None and progress.status == "active":
        progress.status = "ready"
    quest_id = _TURNS_IN.get(scene_id)
    if quest_id is not None:
        claim_story_step(state, content, quest_id)
    if scene_id == "end_03":
        from .botidentity import sync_story_rewards
        state.set_scene_status("ending", "done")
        sync_story_rewards(state)  # "Still my favorite." (V1-17)
        state.set_scene_status("credits", "pending")  # then the credits roll, once
    autostart_story(state, content)  # the prologue's steps begin once its arrival is told
    return True


# --- Settle In (02 §13.5) -----------------------------------------------------------------
def settle_progress(state) -> dict:
    """The saved Settle In progress: real seconds of stillness, cues reached and whether
    Astra-9 watches too. It pauses and never resets, across a reload too."""
    story = state.v2.setdefault("story", {})
    settle = story.get("settle")
    if not isinstance(settle, dict):
        settle = story["settle"] = {}
    seconds = settle.get("seconds")
    settle["seconds"] = float(seconds) if isinstance(seconds, (int, float)) and not isinstance(
        seconds, bool) and math.isfinite(seconds) and seconds >= 0 else 0.0
    cues = settle.get("cues")
    settle["cues"] = cues if type(cues) is int and 0 <= cues <= len(SETTLE_CUES) else 0
    if type(settle.get("together")) is not bool:
        settle["together"] = False
    return settle


def settle_near(state, world) -> bool:
    """The boat is in Nebula open, within 200 m of the marked reflection: where Settle In counts."""
    from .lakes import place
    if world.id != "nebula" or world.zone_at(state.x, state.z) != "open":
        return False
    found = place(SETTLE_AREA)
    if found is None:
        return False
    row = found[1]
    return math.hypot(state.x - row["x"], state.z - row["z"]) <= SETTLE_RADIUS_M


def settle_spot(state, world) -> bool:
    """"Settle in" is offered: the boat is anchored near the marked reflection."""
    return state.anchored and settle_near(state, world)


def settle_step_active(state, content) -> bool:
    definition = content.quests.get("story_c5_s2")
    progress = state.narrative.quests.get("story_c5_s2")
    if definition is None or progress is None or progress.status != "active":
        return False
    step, _data = current_step(definition, progress)
    return step is not None and step["type"] == "settle"


def settle_tick(state, world, dt: float, *, still: bool) -> list[str]:
    """Add real seconds while the Skipper keeps still by the reflection (or Astra-9 watches too,
    anywhere near it); return Bot's cue lines reached. At the third cue the interaction finishes
    and emits settle.complete. Away from the reflection nothing counts or finishes."""
    settle = settle_progress(state)
    lines = []
    if not settle_near(state, world):
        return lines
    if (still or settle["together"]) and settle["cues"] < len(SETTLE_CUES):
        settle["seconds"] = min(SETTLE_CUES[-1], settle["seconds"] + max(0.0, dt))
        while settle["cues"] < len(SETTLE_CUES) and settle["seconds"] >= SETTLE_CUES[settle["cues"]]:
            lines.append(SETTLE_LINES[settle["cues"]])
            settle["cues"] += 1
    if settle["cues"] == len(SETTLE_CUES):
        # Called only while the settle step is under way: a finish the step missed is sent again.
        state.emit_quest_event({"type": "settle.complete", "lake_id": world.id, "zone_id": SETTLE_ZONE,
                                "cues": settle["cues"], "game_minute": state.game_minutes})
    return lines
