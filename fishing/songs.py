"""Lake songs (issue #168): 27 procedural pieces, five or six for each lake, composed in NumPy.

How it fits: `music.Layer` plays each lake's pieces in a seeded rotation on the music bus.
`audiosynth.build_bed` sends `song:<id>` keys here, so the bed store renders each piece in a
worker process at the mixer's sample rate, or on a thread on frozen builds. A stop flag ends
a render the store abandons, within one block (#168). `soundscape`
takes its captions from `CATALOGUE`.

Constraints:
- No sample files. Every choice comes from the piece's id, so one id and rate always give the
  same samples.
- A piece is `bars` bars of `meter` beats at `bpm`, then a TAIL_SECONDS fade. Its length is
  known before it is rendered; every piece lasts 60-150 s (the tests check it).
- Each piece has its own key, tempo, meter, form and motifs. Its lake supplies the timbres
  (`FAMILIES`). Every attack is at least `audiosynth.MIN_ATTACK`, and high partials stay soft.
- Form: A and B sections of eight bars (two four-bar phrases each), then a four-bar coda. A
  letter's repeats alternate: its second occurrence is turned upside down and its third is
  upright again. Strong beats land on chord tones, and each phrase cadences on the tonic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import threading
import time
import zlib

import numpy as np

from . import audiosynth as synth

F32 = np.float32
TAIL_SECONDS = 5.0      # release fade at the end of every piece
FADE_IN_SECONDS = 0.25  # a piece opens softly; the mixer adds its own layer fade
SECTION_BARS = 8        # each letter of a form: two four-bar phrases
CODA_BARS = 4
CHUNK = 1 << 15         # overlap-add block of the reverb, in samples (keeps each FFT small)
SONG_PREFIX = "song:"   # bed-store key and caption kind of a piece: "song:<id>"
VIBRATO_HZ = 5.2
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# Scale shapes as semitone steps of the seven degrees (index 0 is the tonic).
MODES = {
    "ionian": (0, 2, 4, 5, 7, 9, 11),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
}
MODE_NAMES = {"ionian": "major", "aeolian": "minor"}  # other modes keep their own names
CHORD_STEPS = (0, 2, 4)  # a triad on a degree: root, third, fifth (in scale steps)
# Melodic steps favour small motion; a few leaps keep the line from sounding walked.
STEP_CHOICES = (-3, -2, -2, -1, -1, 1, 1, 2, 2, 3)
RHYTHMS = {
    3: ((1, 1, 1), (2, 1), (1, 2), (1.5, 1.5), (1, 0.5, 0.5, 1)),
    4: ((1, 1, 1, 1), (2, 1, 1), (1, 1, 2), (1.5, 0.5, 2), (2, 2), (1, 0.5, 0.5, 2)),
}
MELODY_AMP = 0.40
BASS_AMP = 0.28
PAD_AMP = 0.09
PAD_SEND = 0.6
MELODY_SEND = 0.55
MELODY_PAN = 0.3
PAD_PANS = (-0.6, 0.0, 0.6)


@dataclass(frozen=True)
class Timbre:
    """How one kind of note sounds.

    Attributes:
        partials: (ratio, amplitude) pairs over the fundamental, kept below 0.45 of the rate.
        attack: Seconds to full level; never below `audiosynth.MIN_ATTACK`.
        tau: Decay time constant in seconds for plucked notes, or None for a held note.
        release: Seconds of fade-out after a held note's written length.
        detune: Fraction of pitch for a chorus pair (0 for none).
        vibrato: Fraction of pitch depth of a slow vibrato at VIBRATO_HZ (0 for none).
    """

    partials: tuple[tuple[float, float], ...]
    attack: float
    tau: float | None
    release: float = 0.0
    detune: float = 0.0
    vibrato: float = 0.0


TIMBRES = {
    "pluck": Timbre(((1.0, 1.0), (2.0, 0.30), (3.0, 0.10)), 0.012, 0.8),
    "wood": Timbre(((1.0, 1.0), (3.0, 0.22), (5.0, 0.08)), 0.010, 0.55),
    "marimba": Timbre(((1.0, 1.0), (3.9, 0.20)), 0.008, 0.45),
    "glass": Timbre(((1.0, 1.0), (2.76, 0.35), (5.4, 0.10)), 0.020, 2.2),
    "flute": Timbre(((1.0, 1.0), (2.0, 0.10), (3.0, 0.03)), 0.09, None, 0.20, vibrato=0.006),
    "horn": Timbre(((1.0, 1.0), (2.0, 0.35), (3.0, 0.15)), 0.12, None, 0.25),
    "warm": Timbre(((1.0, 1.0), (2.0, 0.18), (3.0, 0.06)), 0.60, None, 0.90, detune=0.0015),
    "deep": Timbre(((1.0, 1.0), (2.0, 0.15)), 0.90, None, 1.20, detune=0.0015),
    "shimmer": Timbre(((1.0, 1.0), (2.0, 0.12), (3.0, 0.04)), 1.20, None, 1.50, detune=0.0030),
}


@dataclass(frozen=True)
class Family:
    """A lake's sound: melody, bass and pad timbres, and its room (`reverb_s` is the RT60 of
    the tail, `wet_db` its level against the dry signal)."""

    melody: str
    bass: str
    pad: str
    reverb_s: float
    wet_db: float


FAMILIES = {
    "briar": Family("pluck", "pluck", "warm", 1.8, -13.0),
    "cedar": Family("wood", "wood", "warm", 2.2, -12.0),
    "flathead": Family("flute", "horn", "warm", 2.6, -12.0),
    "crater": Family("marimba", "marimba", "deep", 2.0, -13.0),
    "nebula": Family("glass", "pluck", "shimmer", 3.2, -10.0),
}


@dataclass(frozen=True)
class Song:
    """One piece of the catalogue.

    Attributes:
        id: Stable `<lake>-<n>` key; the bed key is `SONG_PREFIX + id`.
        lake: Lake whose playlist and timbres it uses.
        title: Short title; its caption reads "Music: <title>.".
        tonic: MIDI note of the key centre (62 is D4; 69 is A4 at 440 Hz).
        mode: Key of `MODES`.
        bpm: Tempo in beats per minute.
        meter: Beats per bar, 3 or 4.
        form: Section letters, each `SECTION_BARS` long; A uses the first progression, B the second.
        progressions: Two tuples of four chord roots (scale steps), one per section letter.
        register: Melody centre in scale steps above the tonic; the melody stays within four.
    """

    id: str
    lake: str
    title: str
    tonic: int
    mode: str
    bpm: float
    meter: int
    form: str
    progressions: tuple[tuple[int, ...], tuple[int, ...]]
    register: int

    @property
    def seed(self) -> int:
        """Seed of every random choice in this piece (stable across runs)."""
        return zlib.crc32(self.id.encode("ascii"))

    @property
    def bars(self) -> int:
        """Bars in the piece: the sections and the coda."""
        return SECTION_BARS * len(self.form) + CODA_BARS

    @property
    def seconds(self) -> float:
        """Length in seconds: the bars plus the TAIL_SECONDS fade."""
        return self.bars * self.meter * 60.0 / self.bpm + TAIL_SECONDS

    @property
    def key_name(self) -> str:
        """Key for the playlist table, for example "D major" or "G mixolydian"."""
        quality = MODE_NAMES.get(self.mode, self.mode)
        return f"{NOTE_NAMES[self.tonic % 12]} {quality}"


# Each lake's pieces are built around its pre-#168 root: briar D4, cedar G3, flathead E4,
# crater A3, nebula C4. Every tonic sits within a fifth of its lake's root.
# (lake, title, tonic MIDI, mode, bpm, meter, form, progression A, progression B, register).
_ROWS = (
    ("briar", "Morning on the Briar", 62, "ionian", 84, 4, "ABAB", (0, 4, 5, 3), (0, 3, 4, 0), 3),
    ("briar", "Reed Bank Waltz", 57, "mixolydian", 76, 3, "AABA", (0, 6, 3, 0), (0, 3, 4, 0), 3),
    ("briar", "Little Eddy", 62, "dorian", 92, 4, "ABAB", (0, 3, 0, 6), (0, 6, 3, 4), 2),
    ("briar", "Dock Lantern Tune", 67, "ionian", 88, 4, "AABA", (5, 3, 0, 4), (0, 5, 3, 4), 2),
    ("briar", "Hollow Oar", 62, "mixolydian", 66, 4, "ABAB", (0, 6, 3, 0), (0, 3, 4, 0), 2),
    ("briar", "Kettle Sunday", 64, "ionian", 96, 3, "ABAB", (0, 4, 5, 3), (5, 3, 0, 4), 3),
    ("cedar", "Cedar Creek Round", 55, "mixolydian", 76, 4, "ABAB", (0, 6, 3, 0), (0, 3, 4, 0), 3),
    ("cedar", "Knotwood", 55, "dorian", 72, 4, "AABA", (0, 3, 0, 6), (0, 6, 3, 4), 2),
    ("cedar", "Woodsmoke at Dusk", 50, "dorian", 84, 4, "ABAB", (0, 3, 0, 6), (0, 6, 3, 4), 3),
    ("cedar", "Bark and Bird", 48, "ionian", 80, 3, "ABAB", (0, 4, 5, 3), (0, 3, 4, 0), 3),
    ("cedar", "Long Shade", 57, "aeolian", 66, 4, "AABA", (0, 5, 2, 6), (0, 3, 6, 0), 2),
    ("flathead", "Larch Gold", 64, "lydian", 72, 3, "ABAB", (0, 1, 5, 4), (0, 4, 1, 0), 3),
    ("flathead", "Ice Tick Hymn", 64, "ionian", 66, 4, "AABA", (0, 4, 5, 3), (0, 3, 4, 0), 2),
    ("flathead", "Flathead Wind", 59, "mixolydian", 76, 3, "ABAB", (0, 6, 3, 0), (0, 3, 4, 0), 3),
    ("flathead", "Snowmelt Walk", 64, "aeolian", 64, 4, "ABAB", (0, 5, 2, 6), (0, 3, 6, 0), 2),
    ("flathead", "High Meadow Ring", 69, "ionian", 70, 3, "AABA", (5, 3, 0, 4), (0, 4, 5, 3), 3),
    ("crater", "Warm Stone", 57, "aeolian", 66, 4, "ABAB", (0, 5, 2, 6), (0, 3, 6, 0), 2),
    ("crater", "Ember Floor", 57, "dorian", 72, 4, "AABA", (0, 3, 0, 6), (0, 6, 3, 4), 2),
    ("crater", "Obsidian Rest", 62, "dorian", 64, 3, "ABAB", (0, 3, 0, 6), (0, 6, 3, 4), 2),
    ("crater", "Hot Spring Lullaby", 57, "aeolian", 60, 3, "AABA", (0, 5, 2, 6), (0, 3, 6, 0), 1),
    ("crater", "Cinder Road", 55, "dorian", 70, 4, "ABAB", (0, 3, 0, 6), (0, 6, 3, 4), 2),
    ("nebula", "Starlight on the Lagoon", 60, "lydian", 62, 4, "ABAB", (0, 1, 5, 4), (0, 4, 1, 0), 3),
    ("nebula", "Reflection Bell", 65, "lydian", 66, 4, "AABA", (0, 1, 5, 4), (0, 2, 5, 4), 3),
    ("nebula", "Pale Choir", 60, "lydian", 60, 3, "ABAB", (0, 1, 5, 4), (0, 2, 5, 4), 3),
    ("nebula", "Drifting Constellation", 55, "lydian", 64, 4, "AABA", (0, 1, 5, 4), (0, 4, 1, 0), 2),
    ("nebula", "Still Water Glass", 62, "lydian", 66, 4, "ABAB", (0, 4, 1, 0), (0, 1, 5, 4), 3),
    ("nebula", "Lagoon Moon", 57, "lydian", 66, 3, "ABAB", (0, 2, 5, 4), (0, 1, 5, 4), 2),
)


def _catalogue() -> tuple[Song, ...]:
    """Number each lake's rows in order: briar-1 .. briar-6, cedar-1 .. and so on."""
    count: dict[str, int] = {}
    out = []
    for lake, title, tonic, mode, bpm, meter, form, prog_a, prog_b, register in _ROWS:
        count[lake] = count.get(lake, 0) + 1
        out.append(Song(f"{lake}-{count[lake]}", lake, title, tonic, mode, float(bpm), meter,
                        form, (prog_a, prog_b), register))
    return tuple(out)


CATALOGUE = _catalogue()
BY_ID = {song.id: song for song in CATALOGUE}


def get(song_id: str) -> Song:
    """The catalogue entry for `song_id` (for example "briar-1").

    Raises:
        KeyError: unknown id.
    """
    return BY_ID[song_id]


def playlist(lake: str) -> tuple[Song, ...]:
    """The lake's pieces in catalogue order (the rotation shuffles them)."""
    return tuple(song for song in CATALOGUE if song.lake == lake)


def key(song: Song) -> str:
    """The bed-store key and caption kind of `song`: "song:<id>"."""
    return SONG_PREFIX + song.id


def frames(song_id: str, rate: int) -> int:
    """Length of the piece in frames at `rate` Hz; the bed store needs it before rendering."""
    return int(round(get(song_id).seconds * rate))


def longest_frames(rate: int) -> int:
    """Frames of the longest piece at `rate` (sizes the music memory bound)."""
    return max(int(round(song.seconds * rate)) for song in CATALOGUE)


def _scale_hz(tonic: int, mode: str, index: int) -> float:
    """Frequency of scale step `index` (0 is the tonic, 7 one octave up), equal temperament
    at A440."""
    octave, step = divmod(index, 7)
    semitones = 12 * octave + MODES[mode][step]
    return 440.0 * 2.0 ** ((tonic + semitones - 69) / 12.0)


def _snap(index: int, root: int) -> int:
    """The chord tone of the triad on degree `root` nearest to `index` (within two steps).

    Strong beats use this so the melody's landing notes agree with the harmony.
    """
    for d in (0, 1, -1, 2, -2):
        if (index + d - root) % 7 in CHORD_STEPS:
            return index + d
    return index


def _into_band(index: int, low: int) -> int:
    """Move `index` by whole octaves into the seven-step band starting at `low`."""
    while index < low:
        index += 7
    while index >= low + 7:
        index -= 7
    return index


def _motif(rng, meter: int) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """One bar of melody as (steps from the previous note, beats per note)."""
    durs = RHYTHMS[meter][int(rng.integers(len(RHYTHMS[meter])))]
    steps = tuple(int(rng.choice(STEP_CHOICES)) for _ in durs)
    return steps, tuple(float(d) for d in durs)


def _events(song: Song) -> list[tuple]:
    """Every note of the piece as (beat, length in beats, voice, scale index, amplitude,
    pan, reverb send), in the order the sections fall."""
    rng = np.random.default_rng(song.seed)
    motifs = {letter: _motif(rng, song.meter) for letter in "AB"}
    progressions = {"A": song.progressions[0], "B": song.progressions[1]}
    low, high = song.register - 4, song.register + 4  # the melody's band
    pad_low = song.register - 5
    strong = (0.0,) if song.meter == 3 else (0.0, 2.0)
    target = 7 * round(song.register / 7)  # the tonic octave nearest the melody centre
    events: list[tuple] = []
    cursor = song.register
    seen = {"A": 0, "B": 0}
    bar = 0
    for letter in song.form:
        steps, durs = motifs[letter]
        if seen[letter] % 2:  # a repeat returns upside down
            steps = tuple(-s for s in steps)
        seen[letter] += 1
        chords = progressions[letter]
        for _phrase in range(2):
            for b in range(4):
                start = bar * song.meter
                root = chords[b]
                pan = MELODY_PAN if bar % 2 == 0 else -MELODY_PAN
                if b == 3:  # cadence: one step toward the tonic, then the tonic
                    step = (target > cursor) - (target < cursor)
                    approach = cursor + step
                    events.append((start, song.meter - 2, "melody", approach,
                                   MELODY_AMP * (1 + 0.08 * rng.uniform(-1, 1)), pan, MELODY_SEND))
                    events.append((start + song.meter - 2, 2, "melody", target,
                                   MELODY_AMP * (1 + 0.08 * rng.uniform(-1, 1)), pan, MELODY_SEND))
                    cursor = target
                else:
                    bar_steps = steps
                    if b == 1:  # sequence: the motif again, one step higher
                        cursor += 1
                    elif b == 2:  # inversion
                        bar_steps = tuple(-s for s in bar_steps)
                    offset = 0.0
                    for s, d in zip(bar_steps, durs):
                        index = cursor + s
                        if index > high or index < low:  # turn back toward the band
                            index = cursor - s
                        if offset in strong:
                            index = _snap(index, root)
                        index = min(max(index, low), high)  # snapping can nudge past an edge
                        events.append((start + offset, d, "melody", index,
                                       MELODY_AMP * (1 + 0.08 * rng.uniform(-1, 1)), pan,
                                       MELODY_SEND))
                        cursor = index
                        offset += d
                _bass_and_pad(events, song, start, root, pad_low)
                bar += 1
    for b, root in enumerate((0, 0, 3, 0)):  # coda: the tonic, held
        start = bar * song.meter
        tone = target + (0, 2, 4, 0)[b]
        events.append((start, song.meter, "melody", tone,
                       MELODY_AMP * (1 + 0.08 * rng.uniform(-1, 1)), 0.0, MELODY_SEND))
        _bass_and_pad(events, song, start, root, pad_low)
        bar += 1
    return events


def _bass_and_pad(events: list[tuple], song: Song, start: float, root: int, pad_low: int) -> None:
    """Append one bar's bass (root and fifth, or the root alone in 3/4) and its three-voice
    pad chord. Both sit an octave below the melody's band."""
    if song.meter == 4:
        events.append((start, 2, "bass", root - 7, BASS_AMP, 0.0, 0.0))
        events.append((start + 2, 2, "bass", root + 4 - 7, BASS_AMP * 0.85, 0.0, 0.0))
    else:
        events.append((start, 3, "bass", root - 7, BASS_AMP, 0.0, 0.0))
    for voice, offset in enumerate(CHORD_STEPS):
        index = _into_band(root + offset, pad_low)
        events.append((start, song.meter, "pad", index, PAD_AMP, PAD_PANS[voice], PAD_SEND))


def _grain(timbre: Timbre, freq: float, seconds: float, rate: int) -> np.ndarray:
    """One note as mono float32: its written length, then the timbre's own release or ring.

    A plucked note rings for three time constants (at most six seconds) after it is written,
    so the decay is not cut off at the next note.
    """
    if timbre.tau is None:
        n = int(round((seconds + timbre.release) * rate))
        env = synth.fade(n, rate, timbre.attack, timbre.release)
    else:
        n = int(round((seconds + min(3.0 * timbre.tau, 6.0)) * rate))
        env = synth.envelope(n, rate, timbre.attack, timbre.tau)
    curve = np.full(n, freq, np.float64)
    if timbre.vibrato:
        t = np.arange(n, dtype=np.float64) / rate
        curve *= 1.0 + timbre.vibrato * np.sin(2.0 * np.pi * VIBRATO_HZ * t)
    if timbre.detune:
        wave = 0.5 * (synth.voice(curve * (1 - timbre.detune), rate, timbre.partials)
                      + synth.voice(curve * (1 + timbre.detune), rate, timbre.partials))
    else:
        wave = synth.voice(curve, rate, timbre.partials)
    return (wave * env).astype(F32)


def _ramps(n: int, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """The fade-in and the tail of an `n`-frame piece, as gain ramps.

    The same raised cosines as `audiosynth.fade`, so the streamed render can apply them one
    block at a time and produce the same samples.

    Returns:
        (head, tail): float32 ramps for the fade-in and for the tail.
    """
    attack = min(n, max(2, int(max(synth.MIN_ATTACK, FADE_IN_SECONDS) * rate)))
    release = min(n, max(2, int(TAIL_SECONDS * rate)))
    head = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, attack))).astype(F32)
    tail = (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, release))).astype(F32)
    return head, tail


class RenderCancelled(Exception):
    """A piece render stopped because its stop flag was set: the bed store abandoned it (#168).

    Raised between blocks, so an abandoned piece ends within one block of the abandonment.
    """


def _synthesize(song: Song, rate: int, sink: Callable[[int, np.ndarray], None],
                stop: threading.Event | None = None) -> None:
    """Render `song` one CHUNK at a time, passing each block to `sink(start, block)`.

    A block is stereo float32 (2, length) with the fades applied, and blocks come in time
    order. Only the notes still sounding, the reverb still to come and the current block are
    held, so no piece-length buffer exists (#168). `time.sleep(0)` after each block gives the
    GIL to other threads: a piece renders on a thread on frozen builds, beside the frame loop.
    Once `stop` is set, no further block is synthesised: `RenderCancelled` is raised before the
    next one, so an abandoned render ends within one block (#168).
    """
    spb = 60.0 / song.bpm
    n = int(round(song.seconds * rate))
    family = FAMILIES[song.lake]
    timbres = {"melody": TIMBRES[family.melody], "bass": TIMBRES[family.bass],
               "pad": TIMBRES[family.pad]}
    ir = synth.reverb_ir(rate, family.reverb_s, f"song:{song.id}")
    ir_len = ir.shape[1]
    size = synth.next_fast(CHUNK + ir_len)
    spectra = np.fft.rfft(ir, size, axis=1)
    wet_gain = 10.0 ** (family.wet_db / 20.0)
    head, tail = _ramps(n, rate)
    notes = []
    for beat, length, voice, index, amp, pan, send_level in _events(song):
        at = int(round(beat * spb * rate))
        if at < n:  # a note past the piece's end never sounds
            notes.append((at, length, voice, index, amp, pan, send_level))
    notes.sort(key=lambda note: note[0])
    carry = np.zeros((2, CHUNK + ir_len), F32)  # reverb from earlier blocks, still to come
    sounding: list[tuple[int, int, np.ndarray, float, float, float]] = []
    queued = 0
    for start in range(0, n, CHUNK):
        if stop is not None and stop.is_set():
            raise RenderCancelled(song.id)
        end = min(n, start + CHUNK)
        while queued < len(notes) and notes[queued][0] < end:
            at, length, voice, index, amp, pan, send_level = notes[queued]
            queued += 1
            freq = _scale_hz(song.tonic, song.mode, index)
            grain = _grain(timbres[voice], freq, length * spb, rate)
            seg_end = min(n, at + len(grain))
            seg = grain[:seg_end - at] * F32(amp)
            left, right = synth.pan_gains(pan)
            sounding.append((at, seg_end, seg, left, right, send_level))
        block = np.zeros((2, end - start), F32)
        send = np.zeros(end - start, F32)
        for at, seg_end, seg, left, right, send_level in sounding:
            lo, hi = max(at, start), min(seg_end, end)
            if lo < hi:
                part = seg[lo - at:hi - at]
                block[0, lo - start:hi - start] += part * F32(left)
                block[1, lo - start:hi - start] += part * F32(right)
                if send_level:
                    send[lo - start:hi - start] += part * F32(send_level)
        sounding = [note for note in sounding if note[1] > end]
        if send.any():
            spec = np.fft.rfft(send, size)
            for ch in range(2):
                wet = np.fft.irfft(spec * spectra[ch], size)[:len(send) + ir_len - 1]
                carry[ch, :len(wet)] += (wet_gain * wet).astype(F32)
        block += carry[:, :end - start]
        carry[:, :-CHUNK] = carry[:, CHUNK:]
        carry[:, -CHUNK:] = 0.0
        if start < len(head):
            k = min(end, len(head)) - start
            block[:, :k] *= head[start:start + k]
        tail_from = n - len(tail)
        if end > tail_from:
            first = max(start, tail_from)
            block[:, first - start:] *= tail[first - tail_from:end - tail_from]
        sink(start, block)
        time.sleep(0)


def render_float(song: Song, rate: int) -> np.ndarray:
    """The whole piece as stereo float32 at `rate` Hz, before it is scaled to int16.

    Tests and analysis use this. `render` streams instead and never holds such a copy (#168).

    Returns:
        Array (2, n) with n = `frames`; silent at both ends (the fade-in and the tail).
    """
    out = np.zeros((2, int(round(song.seconds * rate))), F32)

    def keep(start: int, block: np.ndarray) -> None:
        out[:, start:start + block.shape[1]] = block

    _synthesize(song, rate, keep)
    return out


def render(song_id: str, rate: int, stop: threading.Event | None = None) -> synth.Bed:
    """The piece as a unit-RMS int16 `Bed` at `rate` (what the worker writes out).

    Two passes (#168). The first measures the mean, RMS and peak that `audiosynth.encode`
    normalises by; the second writes int16 blocks. Synthesis runs twice, so a render takes about
    twice as long (nebula-1 at 22.05 kHz: 4.2 s, against 1.9 s before). Beyond its output, a
    render holds the notes still sounding, their FFT buffers and one block's temporaries: 34 MiB
    at 44.1 kHz for nebula-1, against 79 MiB for the render it replaces (measured with
    tracemalloc; `soundscape.coverage_report` budgets the 34 MiB).

    Args:
        stop: Optional flag the bed store sets when it abandons the piece. Once it is set, the
            render raises `RenderCancelled` before its next block.

    Raises:
        KeyError: unknown id.
        RenderCancelled: `stop` was set during the render.
    """
    song = get(song_id)
    n = int(round(song.seconds * rate))
    total = np.zeros(2)
    squares = np.zeros(2)
    high = np.full(2, -np.inf)
    low = np.full(2, np.inf)

    def measure(_start: int, block: np.ndarray) -> None:
        values = block.astype(np.float64)
        total[:] += values.sum(axis=1)
        squares[:] += np.square(values).sum(axis=1)
        high[:] = np.maximum(high, values.max(axis=1))
        low[:] = np.minimum(low, values.min(axis=1))

    _synthesize(song, rate, measure, stop)
    mean = total / n
    rms = math.sqrt(float(np.mean(squares / n - mean * mean)))
    peak = float(max(np.max(high - mean), np.max(mean - low)))
    if peak < 1e-9:  # silent, as `audiosynth.encode` leaves it
        return synth.Bed(np.zeros((2, n), np.int16), 0.0)
    scale = 32000.0 / peak
    data = np.zeros((2, n), np.int16)

    def write(start: int, block: np.ndarray) -> None:
        end = start + block.shape[1]
        data[:, start:end] = ((block - mean[:, None]) * scale).astype(np.int16)

    _synthesize(song, rate, write, stop)
    return synth.Bed(data, 1.0 / (rms * scale))
