"""V1-38: every sound the game makes, its caption and bus, and each lake's voice (02 §18).

Everything is synthesized here and needs no audio device, so the tests and the benchmark can
hear it too. `audio.Audio` only schedules, mixes and queues it.

- **Captions.** Every sound has one (`CAPTIONS`), shown when Captions is on, so nothing is
  heard that can't be read. Bot's shell chimes keep the shell's own caption (`bot.json`).
- **Buses.** Each sound plays on one of V1-06's mixer buses (`bus`): music, ambience or SFX,
  all under master. M mutes them all.
- **Lake ambience** (`AMBIENCE`). Briar and Cedar keep their loons, gulls and frogs.
  - Flathead: wind in the larches, loons, and ice ticking at the shore on cold hours.
  - Crater: a deep hush (its water and wind are quieter, with no crickets), bubbling springs,
    and ravens by day.
  - The Lagoon: star twinkles, a soft choir, and a low whale song on nights after the finale.
- **Music.** One sparse motif per lake (`MOTIFS`), for dawn, dusk and the story's staged
  moments. Silence is the default between them.
- **Cues.** The hail horn, a Lake Day bell, the cookout triangle, a legendary's chord as its
  name comes up, and the whale song when the Star-Whale rises. The line's hum is V1-37's.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

SR = 22050
AUDIO_BUDGET_BYTES = 150 * 1024 ** 2   # 06 §7: audio synthesis buffers + music
LAKES = ("briar", "cedar", "flathead", "crater", "nebula")

SFX_CAPTIONS = {
    "bite": "Fish on the line.",
    "bot": "Bot's chime sounds.",
    "sell": "Sale complete.",
    "error": "That action is unavailable.",
    "click": "A soft click sounds.",
    "splash": "A splash breaks the quiet.",
    "hum": "The line hums.",
    "hum_winch": "The winch hums, steady.",
    "horn": "Your horn gives a friendly toot.",
    "lake_day": "A bell rings in the day. It's a Lake Day.",
    "cookout": "The cookout triangle rings at the landing.",
    "legendary": "A low, bright chord rises with it.",
    "whale_song": "A long, low whale song rolls over the water.",
}
AMBIENCE_CAPTIONS = {
    "loon": "A loon calls.",
    "gull": "A gull cries.",
    "frog": "Frogs croak.",
    "twinkle": "Starlight twinkles.",
    "larch_wind": "Wind moves through the larches.",
    "ice_tick": "Ice ticks at the shore.",
    "spring": "A hot spring bubbles.",
    "raven": "A raven croaks.",
    "choir": "A soft choir hums in the stars.",
}
MUSIC_CAPTIONS = {
    "motif_briar": "♪ Little Briar's tune plays softly.",
    "motif_cedar": "♪ Cedar Creek's tune plays softly.",
    "motif_flathead": "♪ Flathead's tune plays softly.",
    "motif_crater": "♪ The Caldera's tune plays softly.",
    "motif_nebula": "♪ The Lagoon's tune plays softly.",
}
CAPTIONS = {**SFX_CAPTIONS, **AMBIENCE_CAPTIONS, **MUSIC_CAPTIONS}
KINDS = tuple(CAPTIONS)

# Which ambient calls each lake schedules (`audio.Audio._schedule`).
AMBIENCE = {
    "briar": ("loon", "gull", "frog"),
    "cedar": ("loon", "gull", "frog"),
    "flathead": ("loon", "larch_wind", "ice_tick"),
    "crater": ("spring", "raven"),
    "nebula": ("twinkle", "choir", "whale_song"),
}
# How loud each lake's water and wind beds sit: Crater is hushed.
BED_LEVEL = {"crater": 0.55}

# One motif per lake: (root Hz, beat seconds, timbre, notes as (semitones, beats)).
MOTIFS = {
    "briar": (293.66, 0.62, "pluck", ((0, 1), (2, 1), (4, 1), (7, 2), (9, 1), (7, 1), (4, 2))),
    "cedar": (196.00, 0.58, "wood", ((0, 1), (4, 1), (7, 1), (10, 2), (7, 1), (5, 1), (4, 1), (2, 2))),
    "flathead": (329.63, 0.80, "flute", ((0, 2), (7, 1), (12, 2), (10, 1), (7, 1), (3, 2), (0, 3))),
    "crater": (220.00, 0.90, "marimba", ((0, 1), (3, 1), (7, 2), (5, 1), (3, 1), (-2, 2), (0, 3))),
    "nebula": (261.63, 0.85, "glass", ((0, 1), (4, 1), (6, 2), (11, 1), (7, 2), (4, 1), (2, 1), (0, 3))),
}


def bus(kind: str) -> str:
    """The mixer bus a sound plays on."""
    if kind in MUSIC_CAPTIONS:
        return "music"
    if kind in AMBIENCE_CAPTIONS:
        return "ambience"
    return "sfx"


def caption(kind: str, state=None) -> str:
    """What the caption says for a sound. Bot's chimes say what his shell sounds like."""
    if kind == "bot" or kind.startswith("bot_"):
        from .bot import chime_caption
        return chime_caption(state) if state is not None else CAPTIONS["bot"]
    return CAPTIONS.get(kind, f"Sound cue: {kind.replace('_', ' ')}.")


def motif_for(lake_id: str) -> str:
    return f"motif_{lake_id}" if lake_id in MOTIFS else "motif_briar"


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds), dtype=np.float32) / SR


def _lowpass(noise: np.ndarray, pole: float) -> np.ndarray:
    out = np.empty_like(noise)
    acc = 0.0
    for i, v in enumerate(noise):
        acc += (float(v) - acc) * pole
        out[i] = acc
    return out


def _note(freq: float, seconds: float, timbre: str) -> np.ndarray:
    t = _t(seconds)
    if timbre == "pluck":
        wave = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t)
        env = np.exp(-t * 3.2)
    elif timbre == "wood":
        phase = 2 * np.pi * freq * t
        wave = sum((-1) ** i * np.sin((2 * i + 1) * phase) / (2 * i + 1) ** 2 for i in range(3))
        env = np.exp(-t * 4.5)
    elif timbre == "flute":
        wave = np.sin(2 * np.pi * freq * t + 0.04 * np.sin(2 * np.pi * 5.0 * t)) + 0.12 * np.sin(4 * np.pi * freq * t)
        env = np.minimum(1.0, t / 0.12) * np.exp(-t * 1.1)
    elif timbre == "marimba":
        wave = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 3.9 * t) * np.exp(-t * 14)
        env = np.exp(-t * 2.6)
    else:  # glass: inharmonic, long tails
        wave = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2.76 * t) + 0.2 * np.sin(2 * np.pi * freq * 5.4 * t)
        env = np.exp(-t * 1.4)
    return (wave * env).astype(np.float32)


def _motif(lake_id: str) -> tuple[np.ndarray, float]:
    root, beat, timbre, notes = MOTIFS[lake_id]
    length = sum(b for _s, b in notes) * beat + 2.5
    out = np.zeros(int(SR * length), np.float32)
    at = 0.0
    for semis, beats in notes:
        tone = _note(root * 2 ** (semis / 12), beats * beat + 1.6, timbre)
        start = int(at * SR)
        end = min(len(out), start + len(tone))
        out[start:end] += tone[:end - start]
        at += beats * beat
    fade = np.minimum(1.0, (len(out) - np.arange(len(out))) / (SR * 0.8)).astype(np.float32)
    return out * fade, 0.16


def _synth(kind: str) -> tuple[np.ndarray, float]:
    if kind.startswith("motif_"):
        return _motif(kind[len("motif_"):])
    if kind == "bite":
        t = _t(0.32)
        rng = np.random.default_rng(7)
        splash = _lowpass(rng.uniform(-1, 1, len(t)).astype(np.float32), 0.42) * np.exp(-t * 26)
        pluck = np.sin(2 * np.pi * (690 - 420 * t) * t) * np.exp(-t * 6.2)
        return splash * 0.9 + pluck * 0.75, 0.42
    if kind == "loon":
        t = _t(0.72)
        trem = 0.62 + 0.38 * np.sin(2 * np.pi * 6.2 * t)
        first = (t < 0.24) * np.exp(-np.clip(t - 0.02, 0, None) * 3.4)
        second = (t >= 0.30) * (t < 0.70) * np.exp(-np.clip(t - 0.32, 0, None) * 2.6)
        wave = np.sin(2 * np.pi * (540 - 35 * t) * t) * first + np.sin(2 * np.pi * (410 - 22 * t) * t) * second
        return wave * trem, 0.20
    if kind == "twinkle":
        # Three soft rising bell partials: the Lagoon's starlight.
        t = _t(0.9)
        wave = np.zeros_like(t)
        for i, freq in enumerate((1568.0, 2093.0, 2637.0)):
            onset = np.clip(t - i * 0.11, 0, None)
            wave += np.sin(2 * np.pi * freq * onset) * np.exp(-onset * 4.5) * (t >= i * 0.11)
        return wave, 0.07
    if kind == "gull":
        t = _t(0.46)
        cry = np.sin(2 * np.pi * (940 - 180 * t) * t) * np.exp(-t * 3.2) * (t < 0.28)
        cry += np.sin(2 * np.pi * (760 - 140 * t) * t) * np.exp(-np.clip(t - 0.18, 0, None) * 3.6) * (t >= 0.16)
        return cry, 0.16
    if kind == "frog":
        t = _t(0.22)
        return np.sin(2 * np.pi * 188 * t) * np.exp(-t * 12) + np.sin(2 * np.pi * 92 * t) * np.exp(-t * 36) * 0.55, 0.22
    if kind in ("hum", "hum_winch"):
        # A legendary on the line (V1-37): a low hum that swells and fades. By hand it wavers;
        # the Zero-G Winch's is steady and a little higher.
        t = _t(2.0)
        winch = kind == "hum_winch"
        phase = 2 * np.pi * (131.0 if winch else 110.0) * t + (0.0 if winch else 0.35 * np.sin(2 * np.pi * 5.5 * t))
        wave = np.sin(phase) * 0.7 + np.sin(2 * phase) * 0.22 + np.sin(3 * phase) * 0.08
        return wave * np.sin(np.pi * t / 2.0) ** 2, 0.22
    if kind == "error":
        t = _t(0.12)
        return np.sin(2 * np.pi * 140 * t) * np.exp(-t * 18), 0.35
    if kind == "splash":
        t = _t(0.12)
        return np.random.default_rng(29).uniform(-1, 1, len(t)) * np.exp(-t * 10), 0.35
    if kind == "sell":
        t = _t(0.12)
        wave = np.sin(2 * np.pi * 660 * t) * (t < 0.06) + np.sin(2 * np.pi * 880 * t) * (t >= 0.06)
        return wave * np.exp(-t * 18), 0.35
    if kind == "bot":
        t = _t(0.16)
        wave = np.sin(2 * np.pi * 880 * t) * (t < 0.05) + np.sin(2 * np.pi * 1320 * t) * (t >= 0.07)
        return wave * np.exp(-t * 10), 0.35
    if kind == "horn":
        # A small boat horn: two soft reedy toots, the second a little lower.
        t = _t(0.95)
        wave = np.zeros_like(t)
        for start, length, freq in ((0.0, 0.32, 233.1), (0.42, 0.48, 207.7)):
            u = t - start
            on = (u >= 0) & (u < length)
            env = np.clip(u / 0.03, 0, 1) * np.clip((length - u) / 0.06, 0, 1)
            phase = 2 * np.pi * freq * u
            wave += on * env * (np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.3 * np.sin(3 * phase))
        return wave, 0.24
    if kind == "lake_day":
        # A handbell, rung twice.
        t = _t(1.6)
        wave = np.zeros_like(t)
        for start in (0.0, 0.42):
            u = np.clip(t - start, 0, None)
            wave += (t >= start) * np.exp(-u * 3.0) * (np.sin(2 * np.pi * 1318.5 * u) + 0.5 * np.sin(2 * np.pi * 3297 * u))
        return wave, 0.12
    if kind == "cookout":
        # A dinner triangle, struck a few times.
        t = _t(1.4)
        wave = np.zeros_like(t)
        for start in (0.0, 0.16, 0.32, 0.48):
            u = np.clip(t - start, 0, None)
            wave += (t >= start) * np.exp(-u * 4.0) * (np.sin(2 * np.pi * 2093 * u) + 0.6 * np.sin(2 * np.pi * 5230 * u))
        return wave, 0.08
    if kind == "legendary":
        # A low, bright chord that swells as a legendary's name comes up (V1-37).
        t = _t(2.4)
        wave = sum(np.sin(2 * np.pi * f * t) * g for f, g in ((130.8, 1.0), (196.0, 0.7), (329.6, 0.5), (523.3, 0.25)))
        return wave * np.sin(np.pi * np.minimum(1.0, t / 2.4)) ** 1.5, 0.14
    if kind == "whale_song":
        # Long, low gliding calls: the Star-Whale.
        t = _t(4.2)
        glide = 2 * np.pi * (70 * t + 22 * np.sin(2 * np.pi * 0.35 * t) / (2 * np.pi * 0.35))
        wave = np.sin(glide) + 0.45 * np.sin(2.01 * glide) + 0.2 * np.sin(3.02 * glide)
        return wave * np.sin(np.pi * t / 4.2) ** 2 * (0.7 + 0.3 * np.sin(2 * np.pi * 0.9 * t)), 0.22
    if kind == "larch_wind":
        t = _t(3.0)
        noise = _lowpass(np.random.default_rng(13).uniform(-1, 1, len(t)).astype(np.float32), 0.06)
        noise /= np.max(np.abs(noise)) + 1e-6
        return noise * np.sin(np.pi * t / 3.0) ** 2, 0.22
    if kind == "ice_tick":
        t = _t(0.35)
        wave = np.zeros_like(t)
        for start, freq in ((0.0, 3200.0), (0.11, 2650.0), (0.19, 3900.0)):
            u = np.clip(t - start, 0, None)
            wave += (t >= start) * np.exp(-u * 120) * np.sin(2 * np.pi * freq * u)
        return wave, 0.12
    if kind == "spring":
        # A few low bubbles rising and popping.
        t = _t(0.9)
        wave = np.zeros_like(t)
        rng = np.random.default_rng(17)
        for i in range(6):
            start = i * 0.13 + float(rng.uniform(0, 0.05))
            freq = float(rng.uniform(180, 320))
            u = np.clip(t - start, 0, None)
            wave += (t >= start) * np.exp(-u * 26) * np.sin(2 * np.pi * (freq * u + 900 * u * u))
        return wave, 0.20
    if kind == "raven":
        t = _t(0.62)
        caw = np.zeros_like(t)
        for start in (0.0, 0.32):
            u = t - start
            on = (u >= 0) & (u < 0.24)
            buzz = np.sign(np.sin(2 * np.pi * 310 * u)) * 0.5 + np.sin(2 * np.pi * (620 - 260 * u) * u)
            caw += on * buzz * np.sin(np.pi * np.clip(u / 0.24, 0, 1))
        return caw, 0.10
    if kind == "choir":
        # Soft "ah" voices: three detuned voices in a fifth, slow swell.
        t = _t(4.0)
        wave = np.zeros_like(t)
        for f in (220.0, 221.4, 329.6, 330.9, 440.0):
            wave += np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)
        return wave * np.sin(np.pi * t / 4.0) ** 2 / 5.0, 0.20
    t = _t(0.12)  # a click, for anything else
    return np.sin(2 * np.pi * 740 * t) * np.exp(-t * 18), 0.35


@lru_cache(maxsize=48)
def tone(kind: str) -> np.ndarray:
    """A sound as int16 samples at `SR`, synthesized once and cached (read-only)."""
    from .botchimes import CHIMES, synthesize
    if kind in CHIMES:
        return synthesize(kind)
    wave, gain = _synth(kind)
    out = (np.clip(np.asarray(wave, np.float32) * gain, -1.0, 1.0) * 32767).astype(np.int16)
    out.setflags(write=False)
    return out


def coverage_report() -> dict:
    """What `--benchmark` checks of the audio (V1-38): every sound synthesizes, is heard,
    has a caption and a bus; each lake's ambience mixes; all of it inside the audio budget."""
    from .audio import Audio
    from .botchimes import CHIMES
    kinds = {}
    total = 0
    for kind in KINDS + CHIMES:
        samples = tone(kind)
        total += samples.nbytes
        kinds[kind] = {"seconds": round(len(samples) / SR, 2), "peak": int(np.max(np.abs(samples))),
                       "bus": bus(kind), "captioned": bool(caption(kind))}
    lakes = {}
    for lake in LAKES:
        audio = Audio(open_device=False)
        heard = set()
        for hour in (2.0, 6.5, 12.0, 19.0, 23.0):
            audio.reset_schedule(lake, hour, finale=True)
            for _ in range(240):  # four minutes of calls, a second at a time
                audio.time += 1.0
                audio._schedule()
                heard.update(audio.take_played())
                audio.shots.clear()  # as if each had played out
        block = audio._mix(SR // 2, 0.0, 0.0)
        lakes[lake] = {"ambience": sorted(heard), "bed_peak": int(np.max(np.abs(block))),
                       "expected": sorted(AMBIENCE[lake])}
        total += audio.buffer_bytes()
    complete = (all(v["peak"] > 0 and v["captioned"] for v in kinds.values())
                and all(set(v["ambience"]) == set(v["expected"]) and v["bed_peak"] > 0 for v in lakes.values()))
    return {"kinds": kinds, "lakes": lakes, "bytes": total, "budget_bytes": AUDIO_BUDGET_BYTES,
            "within_budget": total <= AUDIO_BUDGET_BYTES, "complete": complete}
