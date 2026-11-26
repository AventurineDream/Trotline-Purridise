"""The music layer (issue #168): a lake's songs in a seeded rotation, on the music bus.

How it fits: `audio.Audio` calls `Layer.advance` once per mixed block, adds the samples it
returns to the music bus, and queues the song kinds it reports for captions. Pieces come from
the bed store (`song:<id>` keys, rendered in worker processes by `songs.render`), so nothing
here synthesises. `soundscape.MUSIC_CUE` (dawn, dusk and staged story moments) reaches
`Layer.cue`.

Constraints:
- At most one piece sounds at a time, and a piece never starts over another.
- Between a lake's pieces the layer rests REST_SECONDS (20-45 s, seeded), so music is an
  occasional visitor rather than a bed.
- A lake change crosses over on the music bus: the sounding piece fades out (FADE_SECONDS,
  equal power), a SWITCH_SECONDS dip follows, and the new lake's first piece fades in. Nothing
  is cut, and the two lakes never sound together.
- A cue starts the queued piece now if the layer is resting. During a piece it removes the
  rest after that piece, so the next piece follows as soon as this one has faded out.
- Mute drops the sounding piece at once (`stop`) and cancels any crossover.
- The store holds at most RESIDENT_PIECES pieces: the sounding one and the next one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import audiosynth as synth
from . import songs

F32 = np.float32
MUSIC_DB = -26.0        # a piece's RMS at full music-bus volume (the old motifs averaged -26 dBFS)
FADE_SECONDS = 3.0      # equal-power fade-in and fade-out of a piece on the music bus
SWITCH_SECONDS = 2.0    # silence between the old lake's fade-out and the new lake's first piece
REST_SECONDS = (20.0, 45.0)
PREFETCH_SECONDS = 8.0  # the queued piece starts building this long before its rest ends
RESIDENT_PIECES = 2     # the sounding piece and the next one (a crossover holds the new lake's)
SILENT = 1e-4           # linear gain under which a fading piece counts as gone


class Rotation:
    """One lake's playlist in a seeded shuffle.

    Each bag holds every piece of the lake once, and the first piece of a bag never repeats
    the last piece of the bag before it. Rests are drawn from the same seeded stream, so a
    lake's whole sequence is the same on every run.
    """

    def __init__(self, lake: str):
        self._pieces = songs.playlist(lake)
        self._rng = synth.seed_for(f"rotation:{lake}")
        self._bag: list[songs.Song] = []
        self._last: songs.Song | None = None

    def next(self) -> songs.Song:
        """The next piece in the rotation."""
        if not self._bag:
            bag = list(self._pieces)
            self._rng.shuffle(bag)
            if len(bag) > 1 and bag[0] is self._last:
                bag[0], bag[1] = bag[1], bag[0]
            self._bag = bag
        self._last = self._bag.pop(0)
        return self._last

    def rest(self) -> float:
        """Seconds of silence before the next piece, drawn from REST_SECONDS."""
        return float(self._rng.uniform(*REST_SECONDS))


def resident_bytes(rate: int) -> int:
    """Upper bound on the music held in memory at `rate`: RESIDENT_PIECES of the longest
    piece, as int16 stereo (4 bytes a frame)."""
    return RESIDENT_PIECES * songs.longest_frames(rate) * 4


@dataclass
class _Playlist:
    """A lake's rotation together with the piece it will play next."""

    lake: str
    rotation: Rotation
    queued: songs.Song


def _playlist(lake: str) -> _Playlist:
    """A fresh rotation for `lake`, with its first piece chosen."""
    rotation = Rotation(lake)
    return _Playlist(lake, rotation, rotation.next())


class Layer:
    """The music bus's piece player: a state machine over mixed blocks (see the header).

    Args:
        store: The bed store, which supplies `get`, `request` and `keep_songs`.
        rate: Mixer sample rate in Hz; sets how long a block lasts.
    """

    def __init__(self, store, rate: int):
        self._store = store
        self._rate = rate
        self._ref = 10.0 ** (MUSIC_DB / 20.0)
        self._active: _Playlist | None = None  # the lake whose rotation is playing
        self._switch: _Playlist | None = None  # the lake being crossed over to, if any
        self._rest = 0.0                       # silence left before the queued piece may start
        self._piece: songs.Song | None = None  # the sounding piece
        self._bed: synth.Bed | None = None
        self._cursor = 0
        self._gain = 0.0

    def cue(self) -> None:
        """Dawn, dusk or a staged story moment: the queued piece starts as soon as it may.

        While resting that is now. While a piece sounds, the rest after it is dropped, so the
        next piece follows as soon as this one has faded out.
        """
        if self._active is not None:
            self._rest = 0.0

    def stop(self) -> None:
        """Mute: drop the sounding piece at once and cancel any crossover in progress."""
        self._piece = self._bed = None
        self._cursor = 0
        self._gain = 0.0
        self._switch = None
        self._retain()

    def advance(self, frames: int, lake: str, wait: bool) -> tuple[np.ndarray | None, list[str]]:
        """Mix one block of `frames` for `lake`.

        Args:
            frames: Block length in frames at the layer's rate.
            lake: The lake the player is on; unknown names are the caller's to map.
            wait: Build a missing piece before returning (offline renders and tests).

        Returns:
            The block as (2, frames) float32, or None when nothing sounds; and the song kinds
            that started in this block, for their captions.
        """
        if self._active is None:
            self._active = _playlist(lake)
            self._rest = self._active.rotation.rest()
        elif lake == self._active.lake:
            self._switch = None  # back on the lake that was playing: its piece fades back in
        elif self._piece is None:
            self._active = _playlist(lake)  # nothing sounds: the new lake starts after a dip
            self._switch = None
            self._rest = SWITCH_SECONDS
        elif self._switch is None or self._switch.lake != lake:
            self._switch = _playlist(lake)
        dt = frames / self._rate
        out = None
        if self._piece is not None:
            out = self._play(frames, dt)
        else:
            self._rest -= dt
        started: list[str] = []
        if self._piece is None:
            started = self._try_start(wait)
        elif self._switch is not None:
            self._store.request(songs.key(self._switch.queued))
        self._retain()
        return out, started

    def _play(self, frames: int, dt: float) -> np.ndarray:
        """The sounding piece's next block: ramped toward full level, or toward silence when a
        crossover is under way. The piece ends when it runs out or has faded to silence; a
        crossover then adopts the new lake."""
        fading = self._switch is not None
        g0 = self._gain
        g1 = self._ramp(g0, 0.0 if fading else self._ref, dt)
        out = self._chunk(frames, g0, g1)
        self._gain = g1
        self._cursor += frames
        done = self._cursor >= self._bed.data.shape[1]
        if done or (fading and g1 <= SILENT):
            self._piece = self._bed = None
            self._cursor = 0
            self._gain = 0.0
            if fading:
                self._active, self._switch = self._switch, None
                self._rest = SWITCH_SECONDS
        return out

    def _try_start(self, wait: bool) -> list[str]:
        """Start the queued piece once its rest is over and the piece is built.

        Returns:
            The song key that started, as a list (empty when nothing started).
        """
        key = songs.key(self._active.queued)
        if self._rest <= PREFETCH_SECONDS:
            self._store.request(key)
        if self._rest > 0.0:
            return []
        bed = self._store.get(key, wait)
        if bed is None:
            return []
        self._start(bed)
        return [key]

    def _start(self, bed: synth.Bed) -> None:
        """Begin the queued piece and queue the next one. Its rest is drawn now and counts from
        the moment this piece ends."""
        self._piece = self._active.queued
        self._bed = bed
        self._cursor = 0
        self._gain = 0.0
        self._active.queued = self._active.rotation.next()
        self._rest = self._active.rotation.rest()
        self._store.request(songs.key(self._active.queued))

    def _retain(self) -> None:
        """Keep only the sounding piece and the next one; during a crossover that is the new
        lake's first piece, and the old lake's queue is released."""
        next_up = self._switch if self._switch is not None else self._active
        pending = next_up.queued if next_up is not None else None
        keep = {songs.key(s) for s in (self._piece, pending) if s is not None}
        self._store.keep_songs(keep)

    def _ramp(self, gain: float, target: float, dt: float) -> float:
        """Move `gain` toward `target` over FADE_SECONDS in power, so the level changes evenly."""
        p0, p1 = gain * gain, target * target
        step = self._ref * self._ref * dt / FADE_SECONDS
        return math.sqrt(max(0.0, p0 + max(-step, min(step, p1 - p0))))

    def _chunk(self, frames: int, g0: float, g1: float) -> np.ndarray:
        """The sounding piece's next `frames` samples, with the gain ramped from g0 to g1.

        The bed's `unit` scales it to unit RMS, so a gain of g plays at RMS g. A piece that
        ends mid-block is zero-padded.
        """
        out = np.zeros((2, frames), F32)
        take = min(frames, self._bed.data.shape[1] - self._cursor)
        if take > 0:
            ramp = np.linspace(g0, g1, frames, endpoint=False, dtype=F32)[:take] * F32(self._bed.unit)
            out[:, :take] = self._bed.data[:, self._cursor:self._cursor + take] * ramp
        return out
