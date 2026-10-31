"""V1-35: the story's small moments, drawn on a card beside the dialogue (05 §1–2).

- **The book on the counter** (`pro_05`–`pro_06`): the landing's old fish book, with the short
  pencil in its spine.
- **Grandmother knitting the collar** (chapter one's turn-in, "It is warm."): Bot, with the
  wool collar knitted on stitch by stitch.
- **The collar slipping** (chapter three, "It is holding on by one loop."): the collar loose,
  swaying in the mountain wind.
- **The knot choice** (`story_c4_knot`): Bot wearing whichever knot is highlighted, and then
  the one chosen ("It adjusts.").

Bot is drawn with his own mesh and shell (`botshots.preview`). The card is part of the
dialogue: it says nothing the bubbles don't, and it goes when they do. Reduced Motion shows
each moment finished and still.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

KNIT_S = 2.5  # how long the collar takes to knit on


def vignette_for(node: dict, chat, state) -> tuple[str, str | None] | None:
    """(kind, detail) for the bubble on screen, or None."""
    from .botidentity import profile
    node_id, scene = node.get("id", ""), node.get("scene")
    if scene in ("pro_05", "pro_05b", "pro_06"):
        return "book", None
    if node_id.startswith("story_c1_s3:dialogue:done"):
        return "knit", None
    if node_id == "story_c3_s3:dialogue:ready:3":
        return "slip", None
    if scene == "story_c4_knot":
        choices = node.get("choices", [])
        choice = choices[chat.selected % len(choices)] if choices else {}
        return "knot", choice.get("knot")
    if scene == "story_c4_tied":
        return "knot", profile(state).get("collar", {}).get("knot")
    return None


@lru_cache(maxsize=24)
def bot_card(shell: str, stage: str, knot: str | None, size: int, angle: float = 0.6):
    """Bot in his shell, with this collar, on a small lit floor (read-only, cached)."""
    from .botshots import preview
    card = preview(shell, collar=stage != "none", knot=knot if stage == "retied" else None, angle=angle,
                   size=size, stage=stage if stage != "none" else "received")
    card.setflags(write=False)
    return card


def bot_image(kind: str, detail: str | None, t: float, state, size: int, *, reduced: bool):
    from .botidentity import profile
    from .data import BOT_SHELLS
    shell = profile(state).get("shell", "tin")
    shell = shell if shell in BOT_SHELLS else "tin"
    if kind == "knit":
        done = 1.0 if reduced else min(1.0, t / KNIT_S)
        bare, collared = bot_card(shell, "none", None, size), bot_card(shell, "received", None, size)
        # Stitch by stitch: the collar comes in from one side as Grandmother knits.
        cut = int(round(done * size))
        image = bare.copy()
        image[:, :cut] = collared[:, :cut]
        return image
    if kind == "slip":
        sway = 0.0 if reduced else 0.12 * np.sin(t * 3.1)  # the mountain wind
        return bot_card(shell, "loose", None, size, round(0.6 + float(sway), 2))
    return bot_card(shell, "retied", detail if detail in ("square", "bow", "sailors_hitch") else "bow", size)


def draw_book(ui, frame, x: int, y: int, w: int, h: int):
    """The landing's old fish book on the counter, the short pencil in its spine."""
    wood = np.array([112, 74, 44], np.float32)
    frame[y:y + h, x:x + w] = (frame[y:y + h, x:x + w] * 0.1 + np.array([214, 196, 160], np.float32) * 0.9).astype(frame.dtype)
    counter = y + int(h * 0.62)
    frame[counter:y + h, x:x + w] = wood.astype(frame.dtype)
    frame[counter:counter + max(2, h // 60), x:x + w] = (wood * 0.6).astype(frame.dtype)
    bw, bh = int(w * 0.46), int(h * 0.42)
    bx, by = x + (w - bw) // 2, counter - bh + int(h * 0.06)
    frame[by:by + bh, bx:bx + bw] = np.array([46, 76, 58], np.uint8)            # green leather
    frame[by:by + bh, bx:bx + max(3, bw // 12)] = np.array([30, 52, 40], np.uint8)  # the spine
    frame[by + 3:by + bh - 3, bx + bw - 4:bx + bw - 1] = np.array([236, 226, 200], np.uint8)  # page edges
    size = max(10, h // 14)
    ui._center(frame, "FISH", bx + bw / 2 + bw * 0.04, by + bh * 0.28, size, (214, 178, 96))
    ui._center(frame, "BOOK", bx + bw / 2 + bw * 0.04, by + bh * 0.28 + size * 1.3, size, (214, 178, 96))
    px = bx + max(3, bw // 12) // 2
    ui._haul_segment(frame, px, by - h * 0.10, px, by + h * 0.04, (222, 182, 70), max(3, h // 45))  # the pencil
    ui._haul_segment(frame, px, by - h * 0.10, px, by - h * 0.13, (60, 56, 52), max(2, h // 60))
