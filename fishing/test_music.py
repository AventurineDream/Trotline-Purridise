"""Issue #168's music: the songs, their rotation, and the layer that plays them.

The catalogue and rotation checks read metadata only. The piece checks render every piece
once at 11025 Hz and keep only its features, so the file stays fast; the click check renders
one piece per lake at the low tier's 22050 Hz. The layer checks drive a `music.Layer` in
mixer blocks over synthetic beds, so crossovers, rests and mutes run in seconds of simulated
time, not minutes of rendering.

Thresholds are the values measured on the shipped catalogue, with margin (issue #168):
pieces in one lake differ by at least 2 dB RMS in their average log spectrum and their onset
envelopes correlate below 0.95; under 2% of energy sits at or above 2.5 kHz; centroids stay
under 800 Hz.
"""

from __future__ import annotations

import dataclasses
import math
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from . import audiosynth as synth
from . import music, songs, soundscape

FONT = Path(__file__).resolve().parent / "assets" / "fonts" / "AtkinsonHyperlegible-Regular.ttf"
FEATURE_RATE = 11025   # catalogue pass; spectra stop at 5.5 kHz, which the checks respect
LOW_RATE = 22050       # the low tier's mixer rate
BLOCK = 1024           # frames per simulated mixer block at LOW_RATE
BLOCK_S = BLOCK / LOW_RATE
SPECTRUM = 2048        # FFT size of the spectra, with half-overlapping Hann frames
PIECE_SECONDS = 30.0   # the stand-in piece's length in the layer tests
STEP_LIMIT = 0.5       # full-scale per sample at LOW_RATE (0.25 at 44.1 kHz, as in test_audio)


def _features(song: songs.Song) -> dict:
    """The measurements the piece checks compare, from one render at FEATURE_RATE."""
    x = songs.render_float(song, FEATURE_RATE).astype(np.float64).mean(axis=0)
    rms = float(np.sqrt(np.mean(x * x)))
    window = np.hanning(SPECTRUM)
    power = np.mean([np.abs(np.fft.rfft(x[i:i + SPECTRUM] * window)) ** 2
                     for i in range(0, len(x) - SPECTRUM, SPECTRUM // 2)], axis=0)
    freqs = np.fft.rfftfreq(SPECTRUM, 1.0 / FEATURE_RATE)
    blocks = np.sqrt(np.mean(x[: len(x) // 512 * 512].reshape(-1, 512) ** 2, axis=1))
    env = blocks - blocks.mean()
    env /= np.linalg.norm(env) + 1e-12
    tail = x[-int(0.2 * FEATURE_RATE):]
    return {
        "frames": len(x),
        "seconds": len(x) / FEATURE_RATE,
        "db": 10.0 * np.log10(power[1:] + 1e-12),
        "env": env,
        "centroid": float(np.sum(freqs * power) / np.sum(power)),
        "high": float(power[freqs >= 2500.0].sum() / power.sum()),
        "step": float(np.max(np.abs(np.diff(x)))) / rms,
        "head": float(np.max(np.abs(x[: int(0.01 * FEATURE_RATE)]))) / rms,
        "tail": float(np.sqrt(np.mean(tail * tail))) / rms,
        "dc": abs(float(x.mean())) / rms,
    }


def _mono(bed: synth.Bed) -> np.ndarray:
    """A bed's mono float samples at unit RMS."""
    return bed.data.astype(np.float64).mean(axis=0) * bed.unit


def _tone_bed(seconds: float) -> synth.Bed:
    """A unit-RMS stereo tone whose cycles divide a mixer block exactly: every block of a fade
    then carries the same RMS, so the fade's shape is what the tests measure."""
    t = np.arange(int(seconds * LOW_RATE), dtype=np.float64) / LOW_RATE
    tone = np.sin(2 * np.pi * (LOW_RATE * 16 / BLOCK) * t)
    return synth.encode(np.stack([tone, tone]).astype(np.float32))


def _covered_codepoints(path: Path) -> set[int]:
    """Code points the font maps to a real glyph, from its cmap subtables (formats 4 and 12).

    Glyph 0 is the font's notdef box, so a code point whose only glyph is 0 is not covered.
    """
    data = path.read_bytes()
    (tables,) = struct.unpack_from(">H", data, 4)
    cmap = next(struct.unpack_from(">I", data, 12 + 16 * i + 8)[0] for i in range(tables)
                if data[12 + 16 * i:16 + 16 * i] == b"cmap")
    (subtables,) = struct.unpack_from(">H", data, cmap + 2)
    covered: set[int] = set()
    for k in range(subtables):
        (offset,) = struct.unpack_from(">I", data, cmap + 4 + 8 * k + 4)
        base = cmap + offset
        (fmt,) = struct.unpack_from(">H", data, base)
        if fmt == 4:
            (seg2,) = struct.unpack_from(">H", data, base + 6)
            segs = seg2 // 2
            ends = struct.unpack_from(f">{segs}H", data, base + 14)
            starts = struct.unpack_from(f">{segs}H", data, base + 16 + seg2)
            deltas = struct.unpack_from(f">{segs}h", data, base + 16 + 2 * seg2)
            ranges_at = base + 16 + 3 * seg2
            ranges = struct.unpack_from(f">{segs}H", data, ranges_at)
            for i in range(segs):
                for c in range(starts[i], min(ends[i], 0xFFFE) + 1):
                    if ranges[i] == 0:
                        glyph = (c + deltas[i]) & 0xFFFF
                    else:
                        (glyph,) = struct.unpack_from(
                            ">H", data, ranges_at + 2 * i + ranges[i] + 2 * (c - starts[i]))
                        glyph = (glyph + deltas[i]) & 0xFFFF if glyph else 0
                    if glyph:
                        covered.add(c)
        elif fmt == 12:
            (groups,) = struct.unpack_from(">I", data, base + 12)
            for g in range(groups):
                first, last, _glyph = struct.unpack_from(">III", data, base + 16 + 12 * g)
                covered.update(range(first, last + 1))
    return covered


class FakeStore:
    """The bed store as the layer sees it: every song key returns `bed`, and the calls that
    manage memory are recorded for the retention check."""

    def __init__(self, bed: synth.Bed | None = None):
        self.bed = bed if bed is not None else _tone_bed(PIECE_SECONDS)
        self.kept: list[frozenset] = []
        self.requested: list[str] = []

    def request(self, key: str) -> None:
        """Beds here are ready at once; the requests are recorded, in order, for the tests."""
        self.requested.append(key)

    def keep_songs(self, keys: set[str]) -> None:
        """Record which keys the layer asked to keep resident."""
        self.kept.append(frozenset(keys))

    def get(self, key: str, wait: bool) -> synth.Bed:
        """The bed for `key`; the same stand-in for every piece."""
        return self.bed


class SizedStore(FakeStore):
    """A store whose pieces have their real lengths at `rate`, so held bytes can be measured.

    Beds are built on the first `request` or `get` and dropped when `keep_songs` leaves them
    out, as the bed store drops them.
    """

    def __init__(self, rate: int):
        super().__init__()
        self.rate = rate
        self.built: dict[str, synth.Bed] = {}

    def request(self, key: str) -> None:
        """The bed store builds a queued piece in the background; here it is built at once, so
        the next piece is held beside the sounding one, as it is there."""
        self.get(key, wait=True)

    def get(self, key: str, wait: bool) -> synth.Bed:
        """The piece for `key`, built at its real length the first time it is asked for."""
        if key not in self.built:
            frames = songs.frames(key[len(songs.SONG_PREFIX):], self.rate)
            self.built[key] = synth.Bed(np.zeros((2, frames), np.int16), 1.0)
        return self.built[key]

    def keep_songs(self, keys: set[str]) -> None:
        """Record the kept keys, then drop every other piece."""
        super().keep_songs(keys)
        for key in [k for k in self.built if k not in keys]:
            del self.built[key]

    def held_bytes(self) -> int:
        """Bytes of the int16 pieces the store holds now."""
        return sum(bed.data.nbytes for bed in self.built.values())


class Clock:
    """Drives a layer one mixer block at a time at LOW_RATE, recording what it returned."""

    def __init__(self, layer: music.Layer):
        self.layer = layer
        self.frame = 0
        self.starts: list[tuple[float, str]] = []  # (block time in s, song key) at each start
        self.outs: list[tuple[float, np.ndarray | None]] = []

    @property
    def now(self) -> float:
        """Time at the start of the next block, in seconds."""
        return self.frame / LOW_RATE

    def run(self, seconds: float, lake: str) -> "Clock":
        """Advance `seconds` of blocks on `lake`; returns self for chaining."""
        for _ in range(round(seconds * LOW_RATE / BLOCK)):
            out, started = self.layer.advance(BLOCK, lake, True)
            self.outs.append((self.now, out))
            self.starts.extend((self.now, key) for key in started)
            self.frame += BLOCK
        return self


class Catalogue(unittest.TestCase):
    def test_every_lake_has_five_or_more_pieces_and_no_two_share_their_metadata(self):
        ids = [song.id for song in songs.CATALOGUE]
        titles = [song.title for song in songs.CATALOGUE]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(titles), len(set(titles)))
        metadata = [(s.lake, s.tonic, s.mode, s.bpm, s.form, tuple(s.progressions))
                    for s in songs.CATALOGUE]
        self.assertEqual(len(metadata), len(set(metadata)))
        for lake in soundscape.LAKES:
            self.assertGreaterEqual(len(songs.playlist(lake)), 5, lake)
            self.assertTrue(all(s.lake == lake for s in songs.playlist(lake)), lake)

    def test_every_piece_lasts_one_to_two_and_a_half_minutes(self):
        for song in songs.CATALOGUE:
            self.assertTrue(60.0 <= song.seconds <= 150.0, f"{song.id}: {song.seconds:.1f} s")

    def test_every_piece_draws_its_own_seed(self):
        """Pieces share no random draws. A seed shared across a lake repeats motifs; the spectral
        and onset checks only partly catch that (nebula's closest pair falls to 3 dB)."""
        seeds = [song.seed for song in songs.CATALOGUE]
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_music_captions_are_ascii_and_drawn_by_the_bundled_font(self):
        covered = _covered_codepoints(FONT)
        self.assertEqual(set(soundscape.MUSIC_CAPTIONS), {songs.key(s) for s in songs.CATALOGUE})
        for key, caption in soundscape.MUSIC_CAPTIONS.items():
            self.assertTrue(caption.startswith("Music: "), caption)
            for ch in caption:
                self.assertLess(ord(ch), 128, f"{key}: {caption!r}")  # every fallback font has ASCII
                self.assertIn(ord(ch), covered, f"{ch!r} is not in {FONT.name}: {caption!r}")

    def test_held_pieces_stay_under_the_budget_at_the_top_tier_rate(self):
        """Held bytes are measured, not derived: over a run with lake changes at 44.1 kHz the
        store never holds more than RESIDENT_PIECES pieces, and under 50 MiB of int16 (two of
        the longest pieces hold 48.6 MiB)."""
        store = SizedStore(44100)
        layer = music.Layer(store, 44100)
        peak_bytes = peak_pieces = 0
        for lake, seconds in (("briar", 600.0), ("cedar", 300.0), ("briar", 300.0)):
            for _ in range(round(seconds * 44100 / 4096)):
                layer.advance(4096, lake, True)
                peak_bytes = max(peak_bytes, store.held_bytes())
                peak_pieces = max(peak_pieces, len(store.built))
        self.assertEqual(peak_pieces, music.RESIDENT_PIECES)
        self.assertLessEqual(peak_bytes, 50 * 2 ** 20)


class Pieces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = {song.id: _features(song) for song in songs.CATALOGUE}

    def test_each_piece_has_the_length_its_metadata_gives(self):
        for song in songs.CATALOGUE:
            self.assertEqual(self.features[song.id]["frames"], songs.frames(song.id, FEATURE_RATE), song.id)

    def test_pieces_in_one_lake_are_distinct_in_spectrum_and_onsets(self):
        for lake in soundscape.LAKES:
            ids = [song.id for song in songs.playlist(lake)]
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    fa, fb = self.features[a], self.features[b]
                    spectral = float(np.sqrt(np.mean((fa["db"] - fb["db"]) ** 2)))
                    onsets = float(np.max(np.correlate(fa["env"], fb["env"], mode="full")))
                    self.assertGreaterEqual(spectral, 2.0, f"{a} vs {b}: {spectral:.2f} dB")
                    self.assertLess(onsets, 0.95, f"{a} vs {b}: onset correlation {onsets:.3f}")

    def test_pieces_stay_gentle_in_timbre(self):
        for song in songs.CATALOGUE:
            f = self.features[song.id]
            self.assertLess(f["centroid"], 800.0, f"{song.id}: centroid {f['centroid']:.0f} Hz")
            self.assertLess(f["high"], 0.02, f"{song.id}: {100 * f['high']:.2f}% at or above 2.5 kHz")

    def test_pieces_ramp_in_and_fade_to_silence_without_dc(self):
        for song in songs.CATALOGUE:
            f = self.features[song.id]
            self.assertLess(f["head"], 0.05, f"{song.id}: onset {f['head']:.3f}")
            self.assertLess(f["tail"], 0.01, f"{song.id}: tail {f['tail']:.4f}")
            self.assertLess(f["dc"], 0.01, song.id)

    def test_no_piece_steps_like_a_click(self):
        for song in songs.CATALOGUE:
            self.assertLess(self.features[song.id]["step"], 3.0, song.id)


class Clicks(unittest.TestCase):
    def test_one_piece_per_lake_has_no_click_or_hard_start_at_the_low_tier_rate(self):
        for lake in soundscape.LAKES:
            song = songs.playlist(lake)[0]
            x = _mono(songs.render(song.id, LOW_RATE))
            rms = float(np.sqrt(np.mean(x * x)))
            self.assertLess(float(np.max(np.abs(np.diff(x)))) / rms, 3.0, song.id)
            self.assertLess(float(np.max(np.abs(x[: int(0.004 * LOW_RATE)]))) / rms, 0.05, song.id)

    def test_renders_are_deterministic(self):
        song = songs.playlist("cedar")[0]
        np.testing.assert_array_equal(songs.render(song.id, LOW_RATE).data,
                                      songs.render(song.id, LOW_RATE).data)

    def test_the_layer_plays_a_real_piece_at_music_level_and_under_minus_one_dbfs(self):
        song = songs.playlist("briar")[0]
        layer = music.Layer(FakeStore(songs.render(song.id, LOW_RATE)), LOW_RATE)
        clock = Clock(layer).run(0.1, "briar")  # the first block builds the playlist
        layer.cue()
        clock.run(12.0, "briar")
        sounding = [(t, out) for t, out in clock.outs if out is not None]
        self.assertTrue(sounding)
        out = np.concatenate([o for _t, o in sounding], axis=1)
        self.assertLessEqual(float(np.max(np.abs(out))), 10 ** (-1 / 20))
        self.assertLess(float(np.max(np.abs(np.diff(out.mean(axis=0))))), STEP_LIMIT)
        steady = np.concatenate([o for t, o in sounding if t >= 4.0], axis=1)
        level = 20 * math.log10(float(np.sqrt(np.mean(steady.astype(np.float64) ** 2))))
        self.assertTrue(music.MUSIC_DB - 4.0 <= level <= music.MUSIC_DB + 4.0, f"{level:.1f} dBFS")


class ResidentMusic(unittest.TestCase):
    def test_resident_music_at_44100_hz_is_pinned(self):
        # RESIDENT_PIECES (2) x the longest piece (nebula-1, 6,366,048 frames) x 4 bytes a frame.
        self.assertEqual(music.resident_bytes(44100), 50_928_384)


class StreamedRender(unittest.TestCase):
    """`songs.render` streams two passes; its int16 must agree with one float pass to within one
    LSB (#168), so a drift in the streaming code fails here and not only in the spectra."""

    def test_the_streamed_render_matches_the_float_path_within_one_lsb(self):
        short = dataclasses.replace(songs.get("briar-1"), form="A")  # 12 bars: both ramps fit
        with patch.object(songs, "get", return_value=short):
            streamed = songs.render("briar-1", LOW_RATE).data
        reference = synth.encode(songs.render_float(short, LOW_RATE)).data
        self.assertEqual(streamed.shape, reference.shape)
        gap = np.abs(streamed.astype(np.int32) - reference.astype(np.int32))
        self.assertLessEqual(int(gap.max()), 1)


class Rotation(unittest.TestCase):
    def test_a_seed_gives_the_same_order_and_rests(self):
        a, b = music.Rotation("cedar"), music.Rotation("cedar")
        self.assertEqual([a.next().id for _ in range(12)], [b.next().id for _ in range(12)])
        self.assertEqual([a.rest() for _ in range(5)], [b.rest() for _ in range(5)])

    def test_each_bag_holds_every_piece_once_and_no_piece_follows_itself(self):
        for lake in soundscape.LAKES:
            ids = {song.id for song in songs.playlist(lake)}
            rotation = music.Rotation(lake)
            picks = [rotation.next().id for _ in range(3 * len(ids))]
            for k in range(0, len(picks), len(ids)):
                self.assertEqual(set(picks[k:k + len(ids)]), ids, lake)
            self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])), lake)

    def test_rests_are_drawn_from_the_rest_range(self):
        rotation = music.Rotation("flathead")
        rests = [rotation.rest() for _ in range(200)]
        self.assertTrue(all(60.0 <= r <= 120.0 for r in rests))
        self.assertGreater(max(rests) - min(rests), 10.0)

    def test_each_lake_plays_only_its_own_pieces(self):
        for lake in soundscape.LAKES:
            ids = {song.id for song in songs.playlist(lake)}
            rotation = music.Rotation(lake)
            self.assertTrue({rotation.next().id for _ in range(2 * len(ids))} <= ids, lake)


class Layer(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.layer = music.Layer(self.store, LOW_RATE)

    def test_the_rest_is_pinned_to_the_spec_60_to_120_seconds(self):
        self.assertEqual(music.REST_SECONDS, (60.0, 120.0))

    def test_one_piece_at_a_time_then_a_rest_of_60_to_120_seconds(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()  # ends the opening rest
        clock.run(600.0, "briar")
        times = [t for t, _key in clock.starts]
        self.assertGreaterEqual(len(times), 4)
        self.assertLess(times[0], 1.0 + 2 * BLOCK_S)
        for before, after in zip(times, times[1:]):
            gap = after - before - PIECE_SECONDS
            self.assertTrue(60.0 - 2 * BLOCK_S <= gap <= 120.0 + 2 * BLOCK_S,
                            f"rest {gap:.2f} s")

    def test_the_opening_rest_is_60_to_120_seconds(self):
        clock = Clock(self.layer).run(130.0, "briar")
        first = clock.starts[0][0]
        self.assertTrue(60.0 - 2 * BLOCK_S <= first <= 120.0 + 2 * BLOCK_S, f"{first:.2f} s")

    def test_a_cue_during_the_rest_starts_the_queued_piece_now(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(0.2, "briar")
        self.assertEqual(len(clock.starts), 1)
        self.assertLess(clock.starts[0][0], 1.0 + 2 * BLOCK_S)

    def test_a_cue_during_a_piece_removes_the_rest_after_it(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(5.0, "briar")
        self.layer.cue()
        clock.run(40.0, "briar")
        self.assertEqual(len(clock.starts), 2)
        self.assertAlmostEqual(clock.starts[1][0] - clock.starts[0][0], PIECE_SECONDS,
                               delta=2 * BLOCK_S)

    def test_a_lake_change_fades_the_piece_out_then_the_new_lake_fades_in(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(5.0, "briar")
        switch = clock.now
        clock.run(15.0, "cedar")
        self.assertEqual(len(clock.starts), 2)
        (first_time, _), (second_time, key) = clock.starts
        self.assertIn(key, {songs.key(song) for song in songs.playlist("cedar")})
        fade_end = switch + music.FADE_SECONDS
        self.assertLess(abs((second_time - fade_end) - music.SWITCH_SECONDS), 2 * BLOCK_S)
        dip = [out is None for t, out in clock.outs if fade_end + BLOCK_S < t < second_time - BLOCK_S]
        self.assertTrue(dip and all(dip))  # the two lakes never sound together
        levels = [float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))
                  for t, out in clock.outs if switch <= t < fade_end and out is not None]
        self.assertGreater(len(levels), 10)
        # A linear power ramp over FADE_SECONDS: while the level is above half its start, each
        # block keeps at least 90% of the one before, so a hard cut at the switch would fail.
        steps = [b / a for a, b in zip(levels, levels[1:]) if a > 0.5 * levels[0]]
        self.assertTrue(steps and all(0.9 <= s <= 1 + 1e-6 for s in steps))

    def test_a_crossover_back_to_the_playing_lake_cancels_it(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(5.0, "briar")
        clock.run(1.0, "cedar")
        back = clock.now
        clock.run(10.0, "briar")
        self.assertEqual(len(clock.starts), 1)
        levels = [float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))
                  for t, out in clock.outs if t >= back and out is not None]
        self.assertGreater(levels[-1], levels[0])  # the piece fades back in

    def test_a_mute_drops_the_piece_and_any_crossover_at_once(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(5.0, "briar")
        self.layer.stop()
        stopped = clock.now
        clock.run(15.0, "briar")
        self.assertTrue(all(out is None for t, out in clock.outs if t >= stopped))
        self.assertEqual(len(clock.starts), 1)  # the rest after a stop is a minute or more

    def test_the_store_keeps_at_most_the_sounding_piece_and_the_next(self):
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(40.0, "briar")
        clock.run(1.0, "cedar")
        self.assertTrue(self.store.kept)
        self.assertLessEqual(max(len(keys) for keys in self.store.kept), music.RESIDENT_PIECES)

    def test_a_return_visit_resumes_the_lakes_rotation(self):
        """A lake keeps its rotation and queued piece while the layer is elsewhere (#168): the
        return plays the piece queued when the layer left, not the one just heard."""
        clock = Clock(self.layer).run(1.0, "briar")
        self.layer.cue()
        clock.run(5.0, "briar")
        heard = clock.starts[0][1]
        queued = self.store.requested[-1]  # briar's next piece, requested while its first sounds
        clock.run(20.0, "cedar")  # the crossover fades briar out; cedar's first piece plays
        returned = clock.now
        clock.run(20.0, "briar")  # cedar fades out, and briar's queued piece follows
        back = [key for when, key in clock.starts if when > returned]
        self.assertEqual(back[0], queued)
        self.assertNotEqual(back[0], heard)

    def test_the_next_piece_is_requested_before_its_rest_ends(self):
        """The render gets the whole rest (#168): the queued piece is requested on the first
        block, not in the last seconds of the rest."""
        clock = Clock(self.layer).run(1.0, "briar")
        early = list(self.store.requested)
        clock.run(130.0, "briar")
        self.assertTrue(early)
        self.assertEqual(early[-1], clock.starts[0][1])


class Duty(unittest.TestCase):
    """How much of the time music sounds (#168). The header of music.py states the measured figure."""

    def test_music_sounds_about_half_of_each_hour_on_every_lake(self):
        block = 4096
        blocks = round(3600.0 * LOW_RATE / block)
        for lake in soundscape.LAKES:
            layer = music.Layer(SizedStore(LOW_RATE), LOW_RATE)
            sounding = sum(layer.advance(block, lake, True)[0] is not None for _ in range(blocks))
            self.assertTrue(0.45 <= sounding / blocks <= 0.65, f"{lake}: {sounding / blocks:.1%}")


if __name__ == "__main__":
    unittest.main()
