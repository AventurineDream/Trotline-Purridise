"""Measured proof that the lake's voice is calm, clean and unclipped (no listening needed).

Every check renders through `Audio.render_offline`, i.e. the same update/mix path the game
plays, on device-less mixers, so the tests are deterministic and need no sound card.

Also a listening-set tool for humans:
    python -m fishing.test_audio --dump /tmp/trotline-pass2/audio [--tier ultra]
writes 20 s WAVs, a spectrogram PNG per WAV, and prints the loudness table, startup
synthesis time, per-block mix cost and memory per tier.

Thresholds (dBFS is relative to int16 full scale, RMS over both channels):
- peaks <= -1 dBFS everywhere; |DC| < 0.002 of full scale;
- ambience RMS in AMBIENCE_BAND; propulsion scenes no louder than -20 dBFS RMS;
- cues alone peak between -16 and -6 dBFS and ramp in over >= 4 ms;
- no click: no adjacent-sample step above JUMP_LIMIT (scaled to 44.1 kHz, since the same
  sound steps twice as far per sample at 22.05 kHz), and block boundaries and loop
  seams never step further than the signal does elsewhere;
- beds' L/R correlation < 0.9.
"""

from __future__ import annotations

import math
import sys
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from . import audiosynth as synth
from . import detail, soundscape
from .audio import BED_CAP_BYTES, SCENE_FADE, Audio, _store_for
from .botchimes import CHIMES

AMBIENCE_BAND = (-35.0, -24.0)
JUMP_LIMIT = 0.25          # full-scale units per 44.1 kHz sample; a click is a step this big
CUE_KINDS = ("bite", "splash", "sell", "click", "error", "bot", "loon", "gull", "frog", "twinkle")

SCENES = {
    **{f"{lake}-{when}": dict(lake_id=lake, hour=hour)
       for lake in synth.LAKES for when, hour in (("dawn", 6.3), ("noon", 12.0), ("night", 23.0))},
    "crater-dusk": dict(lake_id="crater", hour=18.8),
    "rain-light": dict(lake_id="briar", hour=12.0, rain=0.3),
    "rain": dict(lake_id="briar", hour=12.0, rain=1.0),
    "cedar-noon-windy": dict(lake_id="cedar", hour=12.0, rain=0.4, sailing=True),
}
PROPULSION = {
    "outboard-idle": dict(lake_id="briar", hour=12.0, motorized=True),
    "outboard-half": dict(lake_id="briar", hour=12.0, motorized=True, throttle=0.5, speed=1.5),
    "outboard-full": dict(lake_id="briar", hour=12.0, motorized=True, throttle=1.0, speed=3.0),
    "electric": dict(lake_id="briar", hour=12.0, motorized=True, electric=True, throttle=0.6, speed=1.2),
    "rowing": dict(lake_id="briar", hour=7.0, rowing=True, throttle=0.6, speed=1.0),
    "sailing": dict(lake_id="cedar", hour=12.0, sailing=True, speed=2.0),
}


def dbfs(x: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) + 1e-12)


def peak_db(x: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.max(np.abs(x))) + 1e-12)


def unit(pcm: np.ndarray) -> np.ndarray:
    return pcm.astype(np.float64) / 32767.0


def band_energy(x: np.ndarray, rate: int, lo: float, hi: float) -> float:
    mono = x.mean(axis=1)
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    f = np.fft.rfftfreq(len(mono), 1.0 / rate)
    return float(spec[(f >= lo) & (f <= hi)].sum())


class AudioChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audio = Audio(device=False, tier="standard")
        cls.rate = cls.audio.rate

    def render(self, seconds=10.0, **scene):
        return unit(self.audio.render_offline(seconds, **scene))

    def check_clean(self, name, x, rate=None):
        self.assertLessEqual(peak_db(x), -1.0, name)
        self.assertLess(abs(float(x.mean())), 0.002, name)
        step = float(np.max(np.abs(np.diff(x, axis=0)))) * (rate or self.rate) / 44100
        self.assertLess(step, JUMP_LIMIT, name)

    def test_coverage_report_counts_the_shared_bed_store_once(self):
        """Every lake warms one tier cache; report its resident bytes once, not per lake."""
        class FakeAudio:
            buffer_calls = 0

            def __init__(self, *, open_device=True):
                self.shots = []
                self.time = 0.0
                self.lake = ""

            def reset_schedule(self, lake_id, hour, *, finale=False, rain=0.0):
                self.lake = lake_id

            def _schedule(self):
                return None

            def take_played(self):
                return soundscape.AMBIENCE[self.lake]

            def _mix(self, frames, throttle, speed):
                return np.ones(frames, np.int16)

            def buffer_bytes(self):
                type(self).buffer_calls += 1
                return 1024

        FakeAudio.buffer_calls = 0
        samples = np.ones(2, np.int16)
        with patch("fishing.audio.Audio", FakeAudio), patch.object(
                soundscape, "tone", return_value=samples):
            report = soundscape.coverage_report()
        expected_bytes = len(soundscape.KINDS + CHIMES) * samples.nbytes + 1024
        self.assertTrue(report["complete"])
        self.assertTrue(report["within_budget"])
        self.assertEqual(FakeAudio.buffer_calls, 1)
        self.assertEqual(report["bytes"], expected_bytes)

    def test_every_lake_hour_and_weather_is_calm_and_clean(self):
        for name, scene in SCENES.items():
            x = self.render(10.0, **scene)
            self.check_clean(name, x)
            low, high = AMBIENCE_BAND
            self.assertTrue(low <= dbfs(x) <= high, f"{name}: {dbfs(x):.1f} dBFS")

    def test_propulsion_is_smooth_and_never_dominates(self):
        for name, scene in PROPULSION.items():
            x = self.render(10.0, **scene)
            self.check_clean(name, x)
            self.assertTrue(-35.0 <= dbfs(x) <= -20.0, f"{name}: {dbfs(x):.1f} dBFS")
        # Throttle sweeps ramp RPM and level; no zipper means no block-edge steps.
        x = self.render(8.0, lake_id="briar", hour=12.0, motorized=True,
                       script=[(t * 0.5, {"throttle": (t % 4) / 3.0, "speed": t % 3}) for t in range(16)])
        self.check_clean("throttle sweep", x)

    def test_lagoon_has_no_birds_or_frogs_and_flathead_no_frogs(self):
        def layers(lake, hour):
            audio = Audio(device=False, tier="low")
            audio._hour = hour
            return [name for name, (_, _, amp, _) in audio._targets(lake).items() if amp > 0]
        night = layers("nebula", 23.0)
        self.assertFalse([k for k in night if k.startswith(("frogs", "insects"))])
        self.assertEqual([k for k in night if k.startswith("birds")], ["birds:nebula"])
        self.assertNotIn("frogs:flathead", layers("flathead", 23.0))
        self.assertNotIn("insects", layers("flathead", 23.0))
        self.assertIn("frogs:briar", layers("briar", 23.0))

    def test_cues_are_clear_soft_edged_and_unclipped(self):
        for kind in CUE_KINDS + CHIMES:
            bus = soundscape.bus(kind)
            volumes = {name: float(name == bus) for name in ("ambience", "music", "sfx")}
            x = self.render(3.0, volumes=volumes, cues=[(0.05, kind)])
            self.assertTrue(-16.0 <= peak_db(x) <= -6.0, f"{kind}: {peak_db(x):.1f} dBFS")
            self.assertLess(float(np.max(np.abs(np.diff(x, axis=0)))), JUMP_LIMIT, kind)
            tone = self.audio._tone(kind)
            tone = tone.astype(np.float64) / (32767.0 if tone.dtype == np.int16 else 1.0)
            env = np.abs(tone.reshape(len(tone), -1)).max(axis=1)
            first = int(0.001 * self.rate)
            settled = float(env[: int(0.03 * self.rate)].max())
            # A >= 4 ms raised-cosine attack reaches only ~15% by 1 ms.
            self.assertLess(float(env[:first].max()), 0.25 * settled, kind)

    def test_bite_rises_above_a_frog_chorus(self):
        scene = dict(lake_id="briar", hour=23.0)
        frogs = [(1.0 + 0.02 * i, "frog", "ambience") for i in range(6)]
        bed = self.render(3.0, cues=frogs, **scene)
        mixed = self.render(3.0, cues=frogs + [(1.2, "bite")], **scene)
        alone = self.render(3.0, cues=[(1.2, "bite")], volumes={"ambience": 0.0}, **scene)
        onset = int(np.argmax(np.abs(mixed - bed).max(axis=1) > 1e-3))
        window = slice(onset, onset + int(0.3 * self.rate))
        # What the player hears under the bite: the frog-laden bed as the bite ducks it.
        under = mixed - alone
        ratio = (band_energy(alone[window], self.rate, 300, 3000)
                 / band_energy(under[window], self.rate, 300, 3000))
        self.assertGreaterEqual(10 * math.log10(ratio), 6.0)
        # The wildlife queue is capped so frogs can never crowd the bite out.
        audio = Audio(device=False, tier="low")
        for _ in range(6):
            audio._cue("frog")
        self.assertEqual(len(audio.shots), 4)
        audio.blip("bite")
        self.assertEqual(len(audio.shots), 5)

    def test_block_boundaries_crossfades_and_loops_do_not_click(self):
        script = [(6.0, {"hour": 20.5}), (14.0, {"rain": 0.8}), (22.0, {"lake_id": "cedar"}),
                  (30.0, {"motorized": True, "throttle": 1.0, "speed": 3.0}),
                  (38.0, {"throttle": 0.0, "speed": 0.5}), (44.0, {"rain": 0.0, "hour": 23.5}),
                  (50.0, {"lake_id": "nebula"})]
        x = self.render(60.0, lake_id="briar", hour=18.0, script=script)
        self.check_clean("60 s journey", x)
        steps = np.abs(np.diff(x, axis=0)).max(axis=1)
        block = self.audio.block
        edges = np.arange(block - 1, len(steps), block)
        inner = np.ones(len(steps), bool)
        inner[edges] = False
        self.assertLessEqual(float(steps[edges].max()), float(steps[inner].max()))
        # No 100 ms window leaps 10 dB above the one before it (a step, not a fade).
        win = int(0.1 * self.rate)
        levels = [dbfs(x[i:i + win]) for i in range(0, len(x) - win, win)]
        for i in range(1, len(levels)):
            self.assertLess(levels[i] - levels[i - 1], 10.0, f"step at {i * 0.1:.1f} s")

    def test_scene_changes_are_equal_power_crossfades(self):
        for start, end in ((dict(lake_id="briar", hour=12.0), dict(lake_id="cedar", hour=12.0)),
                           (dict(lake_id="crater", hour=18.8), dict(lake_id="crater", hour=23.0)),
                           (dict(lake_id="cedar", hour=23.0), dict(lake_id="nebula", hour=23.0))):
            audio = Audio(device=False, tier="low")
            audio.prime(**start)
            powers = [sum(g * g for g in audio._gains.values()) + audio._pad_gain ** 2]
            audio._lake_id, audio._hour = end["lake_id"], end["hour"]
            dt = audio.block / audio.rate
            for _ in range(int(4.0 / dt)):
                audio._mix(audio.block, 0.0, 0.0)
                powers.append(sum(g * g for g in audio._gains.values()) + audio._pad_gain ** 2)
            p0, p1 = powers[0], powers[-1]
            # The ambience never dips (or swells) more than 1 dB beyond its two ends ...
            self.assertGreater(min(powers), min(p0, p1) * 10 ** -0.1, end)
            self.assertLess(max(powers), max(p0, p1) * 10 ** 0.1, end)
            # ... and the fade is over within SCENE_FADE.
            settled = int(math.ceil(SCENE_FADE / dt)) + 1
            self.assertTrue(all(abs(p - p1) < 1e-12 for p in powers[settled:]), end)

    def test_beds_loop_seamlessly_with_decorrelated_ears(self):
        store = self.audio._store
        groups = [["lap", "wash", "rain_light", "rain_heavy", "insects"]] + [
            [f"{kind}:{lake}" for kind in ("wind", "birds", "frogs") if kind != "frogs" or lake in synth.FROGS]
            for lake in synth.LAKES]
        for keys in groups:
            # Queue a whole group first so the workers build it in parallel.
            for key in keys:
                store.request(key)
            for key in keys:
                self.check_loop(key, store.get(key, True))

    def check_loop(self, key, bed):
        """A bed's seam steps no further than its interior, its ears differ, no DC."""
        x = bed.data.astype(np.float32) * bed.unit
        jumps = np.abs(np.diff(x, axis=1)).max(axis=0)
        seam = float(np.abs(x[:, 0] - x[:, -1]).max())
        self.assertLessEqual(seam, float(jumps.max()), key)
        self.assertLess(float(np.corrcoef(x[0], x[1])[0, 1]), 0.9, key)
        self.assertLess(float(np.abs(x.mean(axis=1)).max()), 0.002, key)

    def test_mute_volume_clamp_and_four_argument_update(self):
        audio = Audio(device=False, tier="low")
        for _ in range(30):
            audio.blip("bite")
            audio.update(1 / 60, 0.0, 0.0, True)
        self.assertEqual(audio.shots, [])
        self.assertEqual(audio._virtual_frames, 0.0)
        self.assertEqual(audio._clock, 0)
        audio.update(1 / 60, 0.0, 0.0, False)
        self.assertGreater(audio._clock, 0)
        audio.set_volumes(master=2.0, music=-1.0, ambience="loud", sfx=float("nan"))
        self.assertEqual(audio._volumes, {"master": 1.0, "music": 0.0, "ambience": 1.0, "sfx": 1.0})
        audio.set_volumes({"ambience": 0.25})
        self.assertEqual(audio._volumes["ambience"], 0.25)

    def test_low_tier_runs_at_22050(self):
        audio = Audio(device=False, tier="low")
        self.assertEqual(audio.rate, 22050)
        x = unit(audio.render_offline(6.0, lake_id="briar", hour=23.0, cues=[(1.0, "bite")]))
        self.assertEqual(len(x), 6 * 22050)
        self.check_clean("low", x, rate=22050)
        self.assertTrue(AMBIENCE_BAND[0] - 2 <= dbfs(x) <= AMBIENCE_BAND[1])

    def test_renders_are_deterministic_and_memory_is_bounded(self):
        a = self.audio.render_offline(4.0, lake_id="cedar", hour=6.3, rain=0.5, cues=[(1.0, "sell")])
        b = self.audio.render_offline(4.0, lake_id="cedar", hour=6.3, rain=0.5, cues=[(1.0, "sell")])
        np.testing.assert_array_equal(a, b)
        ultra = _store_for(detail.TIERS["ultra"])
        # Shared: lap, wash, both rains (noise length) and insects (event length);
        # per lake, for two lakes: wind (noise), birds and frogs (event).
        worst = (6 * ultra.noise_frames + 5 * ultra.event_frames) * 2 * 2
        # Cues are the same size on every 44.1 kHz tier: measure the finished bank.
        store = self.audio._store
        store.prefetch_cues()
        while isinstance(store._cue_job, tuple):
            store._cue_job[0].wait()
            store.tick()
        cues = sum(c.nbytes for c in store._cues.values()) + sum(s.nbytes for s in store._strokes)
        self.assertLessEqual(worst + cues, BED_CAP_BYTES)
        self.assertLessEqual(self.audio.memory_bytes(), BED_CAP_BYTES)


# ------------------------------------------------------------------ listening set

LISTEN = {
    "briar-dawn": dict(lake_id="briar", hour=6.3),
    "briar-night": dict(lake_id="briar", hour=23.0, cues=[(4.0, "frog", "ambience")]),
    "cedar-noon-windy": dict(lake_id="cedar", hour=12.0, rain=0.4, sailing=True),
    "flathead-noon": dict(lake_id="flathead", hour=12.0, cues=[(3.0, "loon", "ambience")]),
    "crater-dusk": dict(lake_id="crater", hour=18.8),
    "nebula-night": dict(lake_id="nebula", hour=23.0, cues=[(5.0, "twinkle", "ambience")]),
    "rain": dict(lake_id="briar", hour=12.0, rain=0.2,
                 script=[(5.0, {"rain": 0.5}), (10.0, {"rain": 1.0})]),
    "outboard-run": dict(lake_id="briar", hour=12.0, motorized=True,
                         script=[(3.0, {"throttle": 0.5, "speed": 1.2}), (8.0, {"throttle": 1.0, "speed": 3.0}),
                                 (14.0, {"throttle": 0.2, "speed": 1.0}), (17.0, {"throttle": 0.0, "speed": 0.0})]),
    "rowing": dict(lake_id="briar", hour=7.0, rowing=True, throttle=0.6, speed=1.0),
    "sailing": dict(lake_id="cedar", hour=12.0, sailing=True, speed=2.0),
    "cues-sampler": dict(lake_id="briar", hour=12.0, volumes={"ambience": 0.5},
                         cues=[(0.5 + 1.25 * i, k) for i, k in enumerate(CUE_KINDS + CHIMES)]),
}


def write_wav(path: Path, pcm: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(np.ascontiguousarray(pcm, "<i2").tobytes())


def spectrogram(pcm: np.ndarray, rate: int, height: int = 480) -> np.ndarray:
    """RGB spectrogram (log frequency 40 Hz..Nyquist, 10 ms columns, -110..-20 dBFS) with
    an RMS strip on top and one-second ticks."""
    x = pcm.astype(np.float32).mean(axis=1) / 32767.0
    n_fft, hop = 2048, rate // 100
    frames = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    win = np.hanning(n_fft).astype(np.float32)
    mag = np.abs(np.fft.rfft(x[idx] * win, axis=1)) / (win.sum() / 2)
    db = 20 * np.log10(mag + 1e-9)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / rate)
    rows = np.geomspace(40.0, rate / 2, height)[::-1]
    img = np.empty((height, frames), np.float32)
    for c in range(frames):
        img[:, c] = np.interp(rows, freqs, db[c])
    s = np.clip((img + 110.0) / 90.0, 0, 1)
    stops = np.array([[0, 0, 0], [40, 10, 90], [150, 30, 120], [235, 110, 50], [252, 230, 140], [255, 255, 255]],
                     np.float32)
    pos = s * (len(stops) - 1)
    lo = np.floor(pos).astype(int).clip(0, len(stops) - 2)
    frac = (pos - lo)[..., None]
    rgb = stops[lo] * (1 - frac) + stops[lo + 1] * frac
    strip = np.zeros((60, frames, 3), np.float32)
    level = np.array([dbfs(x[i * hop:i * hop + n_fft]) for i in range(frames)])
    bar = np.clip((level + 60.0) / 60.0, 0, 1) * 59
    for c in range(frames):
        strip[59 - int(bar[c]):, c] = (90, 200, 120)
    out = np.concatenate([strip, rgb], axis=0)
    out[:, ::100] = np.maximum(out[:, ::100], 70)
    for f in (100, 1000, 10000):
        r = 60 + int(np.argmin(np.abs(rows - f)))
        out[r, ::4] = (90, 160, 255)
    return out.astype(np.uint8)


def dump(out_dir: str, tier: str) -> None:
    """Write the listening set and print the numbers the report needs."""
    from .pngsave import write_png
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    audio = Audio(device=False, tier=tier)
    audio.prime(lake_id="briar", hour=6.3)
    print(f"startup synthesis ({tier}, briar dawn set, 3 workers): "
          f"{time.perf_counter() - start:.3f} s; per bed: "
          + ", ".join(f"{k} {v * 1000:.0f} ms" for k, v in audio._store.build_seconds.items()))
    print("| scene | RMS dBFS | peak dBFS | max step | L/R corr |")
    print("|---|---|---|---|---|")
    for name, scene in {**LISTEN, **{k: v for k, v in SCENES.items() if k not in LISTEN},
                        **{k: v for k, v in PROPULSION.items() if k not in LISTEN}}.items():
        pcm = audio.render_offline(20.0 if name in LISTEN else 10.0, **scene)
        x = unit(pcm)
        print(f"| {name} | {dbfs(x):.1f} | {peak_db(x):.1f} | {np.abs(np.diff(x, axis=0)).max():.3f} "
              f"| {np.corrcoef(x[:, 0], x[:, 1])[0, 1]:.2f} |")
        if name in LISTEN:
            write_wav(out / f"{name}.wav", pcm, audio.rate)
            write_png(out / f"{name}.png", spectrogram(pcm, audio.rate))
    times = []
    for scene in (LISTEN["briar-night"], LISTEN["outboard-run"], LISTEN["rain"]):
        twin = Audio(device=False, tier=tier)
        twin.prime(**{k: v for k, v in scene.items() if k not in ("cues", "script", "volumes")})
        twin.blip("bite")
        for _ in range(600):
            t = time.perf_counter()
            twin._mix(twin.block, 0.6, 1.5, wait=False)
            times.append((time.perf_counter() - t) * 1000)
    print(f"mix per block ({audio.block} frames = {audio.block / audio.rate * 1000:.1f} ms audio): "
          f"p50 {np.percentile(times, 50):.3f} ms, p95 {np.percentile(times, 95):.3f} ms")
    print(f"memory_bytes ({tier}): {audio.memory_bytes() / 2**20:.1f} MiB")


if __name__ == "__main__" and "--dump" in sys.argv:
    args = sys.argv[sys.argv.index("--dump") + 1:]
    tier_name = args[args.index("--tier") + 1] if "--tier" in args else "ultra"
    dump(args[0], tier_name)
elif __name__ == "__main__":
    unittest.main()
