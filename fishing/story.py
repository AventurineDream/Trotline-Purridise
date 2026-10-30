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

from .quests import autostart_story, claim_story_step, quest_status, scene_state

# Scenes that play by themselves when their moment comes, in story order: (first scene of
# the chain, whether its moment has come). A chain replays from its first scene not yet done.
_AUTO = (
    ("pro_01", lambda state: scene_state(state, "prologue") == "pending"),   # a new game (05 §1)
    ("pro_03", lambda state: quest_status(state, "story_c0_s1") == "ready"),  # the first line is set
    ("pro_04", lambda state: quest_status(state, "story_c0_s2") == "ready"),  # the first catch
)
# Scenes a hail opens: (first scene, the cat hailed, whether its moment has come).
_HAIL = (
    ("pro_05", "grandmother_whiskers", lambda state: quest_status(state, "story_c0_s3") == "ready"),
)
# The story step a scene turns in once it is done.
_TURNS_IN = {"pro_03": "story_c0_s1", "pro_04": "story_c0_s2", "pro_06": "story_c0_s3"}


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
                         "target": f"scene:{choice['next']}" if choice["next"] is not None else None}
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
    quest_id = _TURNS_IN.get(scene_id)
    if quest_id is not None:
        claim_story_step(state, content, quest_id)
    autostart_story(state, content)  # the prologue's steps begin once its arrival is told
    return True
