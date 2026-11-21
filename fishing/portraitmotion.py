"""Celeste-style life for the dialogue portrait: breath, sway, blinks, a talk bounce and a mood.

The portrait card is a CPU raster of the cat rig (catart), tens of milliseconds a render
(docs/issue-57), so it is never re-rasterized per frame. catart renders the cat once into
layers (paper, cat, coverage and three lid states) and a PortraitRig warps only the cat layer
with a small affine transform (lean, squash and stretch) about the bottom centre, so the
seated cat keeps its feet planted while the still paper and border stay put, like a sprite
moving in a fixed frame.

Motion is a pure function of two clocks the session advances while a conversation is open
(`UIState.dialogue_s` and `dialogue_line_s`), stepped to PORTRAIT_FPS like hand-drawn
portrait frames (which also lets the rig's memo skip most redraws). Every frame is therefore
reproducible in tests and screenshots, and both clocks at zero give the rest pose. Reduced
motion holds the rest pose; only a mood's static lids remain, since a still half-lid is
expression rather than movement.

Each speaker moves in a Style: cats by default, and Bot (botportrait), whose card is the
same rig with his lamp shutter as the lids, in his own stiffer, tin one.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import zlib

import numpy as np

PORTRAIT_FPS = 20.0      # pose steps a second; a held step reuses the last composited frame

# Idle: a slow breath (a touch of stretch) and a slower sway, both always on.
BREATH_HZ = 0.32
BREATH_STRETCH = 0.008   # about 1 px of rise at the 176 px panel
SWAY_HZ = 0.13
SWAY_RAD = math.radians(1.1)

# Talking: small hops while a fresh line is "spoken", one per syllable or so.
TALK_CPS = 30.0          # characters a second the cat is taken to say
TALK_MIN_S, TALK_MAX_S = 0.5, 3.2
TALK_HZ = 3.4            # hops a second
TALK_STRETCH = 0.04      # stretch at the top of a hop; it lands with a little squash
TALK_SQUASH = 0.4        # the share of a hop below rest height as it lands
TALK_EASE_S = 0.2        # the hops settle over this long at the end of the line

# A new line starts with a little "hup": a stretch that rings down in about half a second.
POP_STRETCH = 0.035
POP_DECAY = 9.0
POP_HZ = 3.5

# Blinks: at most one per slot (sometimes a double), at a per-cat pseudo-random moment.
BLINK_SLOT_S = 3.6
BLINK_S = 0.16
DOUBLE_BLINK_GAP_S = 0.28
DOUBLE_BLINK_CHANCE = 0.25

# Moods read from the line's punctuation; story text carries no explicit mood field.
CURIOUS_TILT = math.radians(4.5)
CURIOUS_EASE_S = 0.3
BRIGHT_GRIN_S = 0.45     # a bright line opens with a happy squint (closed, smiling lids)

LIDS = (0.0, 0.5, 1.0)   # lid states catart renders: open, half, closed


@dataclass(frozen=True)
class Style:
    """How one kind of speaker moves; the defaults are the cats' (the constants above).

    Attributes:
        breath: Idle stretch amplitude. sway_hz, sway_rad: the idle lean's rate and size.
        talk_hz, talk_stretch, talk_squash: hops a second while speaking, their stretch,
            and the share of a hop spent squashed below rest as it lands.
        pop_stretch, pop_hz, pop_decay: the line-start "hup".
        blink_slot_s, double_blink_chance: one blink per slot, sometimes doubled.
    """

    breath: float = BREATH_STRETCH
    sway_hz: float = SWAY_HZ
    sway_rad: float = SWAY_RAD
    talk_hz: float = TALK_HZ
    talk_stretch: float = TALK_STRETCH
    talk_squash: float = TALK_SQUASH
    pop_stretch: float = POP_STRETCH
    pop_hz: float = POP_HZ
    pop_decay: float = POP_DECAY
    blink_slot_s: float = BLINK_SLOT_S
    double_blink_chance: float = DOUBLE_BLINK_CHANCE


CAT = Style()
# Bot is a tin deckhand (bot.py, botmesh): he does not breathe, and tin does not squash.
# He rides the bow, so his card rocks a little more and a little faster than a seated
# cat's sway; his literal, word-at-a-time lines get one stiff nod per word or so; a line
# opens with a quick, chime-like ping; and his lamp shutter blinks on a slower cycle,
# never doubled.
BOT = Style(breath=0.0, sway_hz=0.18, sway_rad=math.radians(1.6), talk_hz=2.4, talk_stretch=0.028,
            talk_squash=0.0, pop_stretch=0.03, pop_hz=6.0, pop_decay=12.0, blink_slot_s=5.0,
            double_blink_chance=0.0)
SPEAKER_STYLES = {"bot": BOT}  # every other speaker is a cat


@dataclass(frozen=True)
class Motion:
    """One frame's portrait pose, applied about the bottom centre of the card.

    Attributes:
        tilt: Lean in radians; positive leans right, toward the text.
        stretch: Vertical scale (1 = rest); width takes half the opposite change.
        lid: Eyelid closure, one of LIDS.
    """

    tilt: float = 0.0
    stretch: float = 1.0
    lid: float = 0.0


REST = Motion()  # the still card: no lean, no squash, open lids; a fresh plain line starts here


def mood(text: str) -> str:
    """The line's mood from its punctuation: "wistful", "bright", "curious" or "plain".

    An ellipsis anywhere wins (a trailing-off line stays soft even if it ends "!");
    otherwise the final mark decides, ignoring closing quotes and brackets.
    """
    text = str(text).strip()
    if "..." in text or "…" in text:
        return "wistful"
    end = text.rstrip("\"'”’)]* ")[-1:]
    return {"!": "bright", "?": "curious"}.get(end, "plain")


def talk_seconds(text: str) -> float:
    """How long the cat is shown speaking a line, from its length, in seconds."""
    return min(TALK_MAX_S, max(TALK_MIN_S, len(str(text).strip()) / TALK_CPS))


def _hash01(seed: int, n: int) -> float:
    """A stable 0–1 value for (seed, n), independent of Python's hash randomization."""
    return (zlib.crc32(f"{seed}:{n}".encode()) & 0xFFFFFF) / float(0xFFFFFF)


def _seed(npc_id: str) -> int:
    return zlib.crc32(str(npc_id).encode("utf-8"))


def _smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def blink(t: float, seed: int, style: Style = CAT) -> float:
    """Lid closure from blinking at time t (s): 0 open, rising to 1 mid-blink.

    Time is cut into the style's blink slots; each holds one blink at a pseudo-random
    offset (and sometimes a second just after), so blinks never sync across speakers.
    """
    if t <= 0:
        return 0.0
    slot = style.blink_slot_s
    n = int(t // slot)
    start = n * slot + 0.3 + (slot - 1.0) * _hash01(seed, n)
    starts = [start]
    if _hash01(seed + 1, n) < style.double_blink_chance:
        starts.append(start + DOUBLE_BLINK_GAP_S)
    for s in starts:
        u = (t - s) / BLINK_S
        if 0.0 <= u < 1.0:
            return 1.0 - abs(2.0 * u - 1.0)
    return 0.0


def _quantize_lid(closure: float) -> float:
    # Three lid states are rendered; a blink's triangle spends about a third of its time in each.
    return 1.0 if closure > 0.66 else 0.5 if closure > 0.2 else 0.0


def portrait_motion(npc_id: str, text: str, dialogue_s: float, line_s: float, *,
                    reduced_motion: bool = False) -> Motion:
    """The portrait's pose for this frame.

    Args:
        npc_id: The speaker; picks its Style (SPEAKER_STYLES, else a cat's) and seeds the
            blink rhythm and sway phase.
        text: The line on screen, already formatted; sets mood and talk length.
        dialogue_s: Seconds the conversation has been open (idle breath, sway, blinks).
        line_s: Seconds the current line has been on screen (talk bounce, pop, mood ease).
        reduced_motion: Hold the rest pose; keep only a mood's static lids.

    Returns:
        The Motion to hand to PortraitRig.frame.
    """
    feel = mood(text)
    static_lid = 0.5 if feel == "wistful" else 0.0
    if reduced_motion:
        return Motion(lid=static_lid)
    dialogue_s = math.floor(max(0.0, dialogue_s) * PORTRAIT_FPS) / PORTRAIT_FPS
    line_s = math.floor(max(0.0, line_s) * PORTRAIT_FPS) / PORTRAIT_FPS
    seed = _seed(npc_id)
    style = SPEAKER_STYLES.get(npc_id, CAT)
    phase = (seed & 0xFFFF) / 65535.0 * math.tau
    stretch = 1.0 + style.breath * math.sin(math.tau * BREATH_HZ * dialogue_s)
    # Centred on upright and zero at t=0, so a conversation opens on the rest pose; the
    # speaker's seed varies the sway's size a little so neighbours don't rock identically.
    tilt = style.sway_rad * math.sin(math.tau * style.sway_hz * dialogue_s) * (0.8 + 0.2 * math.cos(phase))

    talk = talk_seconds(text)
    if line_s < talk + TALK_EASE_S:
        energy = {"bright": 1.5, "wistful": 0.6}.get(feel, 1.0)
        hz = style.talk_hz * (1.15 if feel == "bright" else 0.8 if feel == "wistful" else 1.0)
        # Eased in from rest (the "hup" leads) and settled out after the line is said.
        envelope = _smooth(line_s / 0.1) * (1.0 - _smooth((line_s - talk) / TALK_EASE_S))
        hop = abs(math.sin(math.pi * hz * line_s))
        # Stretched at the top of a hop, squashed by the style's share as it lands.
        stretch += style.talk_stretch * energy * envelope * (hop - style.talk_squash * (1.0 - hop))
    stretch += (style.pop_stretch * math.exp(-style.pop_decay * line_s)
                * math.sin(math.tau * style.pop_hz * line_s))
    if feel == "curious":
        tilt += CURIOUS_TILT * _smooth(line_s / CURIOUS_EASE_S)

    closure = max(static_lid, blink(dialogue_s, seed, style))
    if feel == "bright" and 0.0 < line_s < BRIGHT_GRIN_S:
        closure = 1.0
    return Motion(tilt=tilt, stretch=stretch, lid=_quantize_lid(closure))


class PortraitRig:
    """A portrait split into still paper and a movable cat, composited per frame at panel size.

    Args:
        paper: (side, side, 3) uint8 ground behind the cat.
        cats: {lid: (side, side, 3) uint8} the cat over paper for each of LIDS.
        cover: (side, side) float 0–1 cat coverage.
        frame_rgb: RGB of the card's border line.
        frame_weight: (side, side) float 0–1 border coverage, stamped over everything.

    `frame(REST)` reproduces the still card to within resampling. The last frame is memoized
    on its quantized pose, so a held pose (reduced motion, or a step of the stepped clock)
    costs a comparison.
    """

    def __init__(self, paper, cats: dict, cover, frame_rgb, frame_weight):
        self.side = int(paper.shape[0])
        alpha = np.asarray(cover, np.float32)[..., None]
        keep = 1.0 - np.asarray(frame_weight, np.float32)[..., None]
        # The border is drawn over everything: fold it into the paper terms once.
        self._under = paper.astype(np.float32) * keep + np.asarray(frame_rgb, np.float32) * (1.0 - keep)
        self._paper_kept = paper.astype(np.float32) * keep
        self._keep = keep
        # Premultiplied cat and its coverage, flattened for one gather per bilinear corner.
        self._layers = {lid: np.concatenate((img.astype(np.float32) * alpha, alpha), axis=2).reshape(-1, 4)
                        for lid, img in cats.items()}
        self._last_key = None
        self._last = None
        grid = np.mgrid[0:self.side, 0:self.side].astype(np.float32)
        self._gy, self._gx = grid[0] + 0.5, grid[1] + 0.5

    def nbytes(self) -> int:
        """Bytes held by the rig's layers and its memoized frame."""
        held = [self._under, self._paper_kept, self._keep, self._gy, self._gx, *self._layers.values()]
        return sum(a.nbytes for a in held) + (self._last.nbytes if self._last is not None else 0)

    @staticmethod
    def bytes_for(side: int) -> int:
        """The most a rig of this side holds: float32 under, kept paper (3 each), keep and the
        two grids (1 each), RGBA per lid state, and one uint8 RGB frame."""
        return side * side * (4 * (3 + 3 + 1 + 2 + 4 * len(LIDS)) + 3)

    def frame(self, motion: Motion) -> np.ndarray:
        """The portrait in this pose: (side, side, 3) uint8, read-only and possibly shared."""
        side = self.side
        # Quantize finer than a pixel moves so the memo hits on held poses without visible steps.
        key = (round(math.degrees(motion.tilt) * 20), round(motion.stretch * 1000), motion.lid)
        if key == self._last_key:
            return self._last
        tilt, sy = math.radians(key[0] / 20.0), key[1] / 1000.0
        sx = 1.0 - (sy - 1.0) * 0.5
        layer = self._layers[motion.lid]
        if key[:2] == (0, 1000):
            moved = layer.reshape(side, side, 4)
        else:
            # Inverse map about the bottom centre, where the cat sits: un-rotate, then un-scale.
            # In y-down pixels, sampling at R(-tilt) leans the cat's top toward +x for positive tilt.
            px, py = side / 2.0, float(side)
            dx, dy = self._gx - px, self._gy - py
            c, s = math.cos(tilt), math.sin(tilt)
            ux, uy = (c * dx + s * dy) / sx, (c * dy - s * dx) / sy
            moved = self._sample(layer, ux + px - 0.5, uy + py - 0.5)
        out = self._under - self._paper_kept * moved[..., 3:] + moved[..., :3] * self._keep
        image = np.clip(out + 0.5, 0, 255).astype(np.uint8)
        image.setflags(write=False)
        self._last_key, self._last = key, image
        return image

    def _sample(self, layer, x, y):
        """Bilinear premultiplied cat at source coordinates, clamped to the card's edge so
        a cat cut off by the bottom of the card stays cut off as it leans."""
        side = self.side
        x = np.clip(x, 0, side - 1).astype(np.float32, copy=False).ravel()
        y = np.clip(y, 0, side - 1).astype(np.float32, copy=False).ravel()
        fx, fy = np.floor(x), np.floor(y)
        wx, wy = (x - fx)[:, None], (y - fy)[:, None]  # float32: int32 arithmetic would promote
        x0, y0 = fx.astype(np.int32), fy.astype(np.int32)
        i00 = y0 * side + x0
        right = (x0 < side - 1).astype(np.int32)
        down = (y0 < side - 1).astype(np.int32) * side

        a, b = np.take(layer, i00, axis=0), np.take(layer, i00 + right, axis=0)
        c, d = np.take(layer, i00 + down, axis=0), np.take(layer, i00 + down + right, axis=0)
        top = a + (b - a) * wx
        bottom = c + (d - c) * wx
        return (top + (bottom - top) * wy).reshape(side, side, 4)
