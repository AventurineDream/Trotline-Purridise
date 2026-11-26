"""Procedural synthesis for the lake's voice: seamless stereo beds, event grains and cues.

How it fits: `fishing.audio` owns the SDL device, the live mix, crossfades and cue
scheduling; this module only turns (kind, sample rate, loop length) into NumPy arrays.
It never touches SDL or game state. `audio` runs `_worker` in a child interpreter at
low CPU priority, so its Python-level event loops never hold the game's GIL or steal
its core; the samples come back through a memory-mapped scratch file.

Constraints:
- Fully vectorised NumPy, no samples, no per-sample Python. Loops only run over events
  (laps, drops, chirps, bird phrases), at most a few thousand per bed.
- Every bed is an exact loop: noise is synthesised in the frequency domain (periodic by
  construction), event trains wrap around the end, and every modulator has whole
  cycles per loop. The seam is therefore indistinguishable from any other sample.
- Music pieces (`songs.py`, keys `song:<id>`) are one-shot renders, not loops. They come
  through `build_bed` so the bed store's worker path serves them as it serves the beds.
- Every grain and cue ramps in over at least `MIN_ATTACK` seconds; nothing starts on a
  step, so nothing clicks or startles.
- Beds come back unit-RMS so the mixer sets their level in dBFS; cues come back
  normalised to a stated peak in dBFS.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import zlib
from dataclasses import dataclass

import numpy as np

F32 = np.float32
# Control-rate decimation: envelopes are drawn at rate/64 (689 Hz at 44.1 kHz) and
# upsampled linearly, so laps, gusts and phrases cost 1/64 of an audio-rate pass.
CTL = 64
MIN_ATTACK = 0.004
LAKES = ("briar", "cedar", "flathead", "crater", "nebula")


@dataclass(frozen=True)
class Bed:
    """One pre-rendered stereo loop.

    Attributes:
        data: int16 samples, shape (2, n) (left row, right row); int16 halves the
            memory of float32 and channel rows keep every build pass contiguous.
        unit: Multiplier that turns `data` into unit-RMS float samples.
    """

    data: np.ndarray
    unit: float

    @property
    def nbytes(self) -> int:
        return int(self.data.nbytes)


def seed_for(key: str) -> np.random.Generator:
    """A generator seeded from a bed or cue name, so every build is reproducible."""
    return np.random.default_rng(zlib.crc32(key.encode("ascii")))


def loop_length(seconds: float, rate: int) -> int:
    """Frames in a bed loop: the 2^a*3^b multiple of 1024 nearest `seconds`.

    Smooth lengths keep the FFTs fast; a 1024 multiple keeps every control-rate and
    carrier divisor exact.
    """
    target = max(1.0, seconds) * rate
    best = 1024
    for b in range(0, 6):
        a = 10
        while 2 ** a * 3 ** b < target * 2:
            value = 2 ** a * 3 ** b
            if abs(value - target) < abs(best - target):
                best = value
            a += 1
    return best


def divisor_near(n: int, target: float, *, at_most: bool = True) -> int:
    """The divisor of `n` that is a multiple of CTL and closest to `target` frames."""
    best = n
    for k in range(1, 4097):
        if n % k or (n // k) % CTL:
            continue
        d = n // k
        if at_most and d > target and d != n:
            continue
        if abs(d - target) < abs(best - target) or (at_most and best > target):
            best = d
    return best


def next_fast(n: int) -> int:
    """Smallest 2^a*3^b*5^c >= n, for quick FFT convolution."""
    best = 1 << (int(n) - 1).bit_length()
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            v = p35
            while v < n:
                v *= 2
            best = min(best, v)
            p35 *= 3
        p5 *= 5
    return best


# Spectral shapes, all taking frequency in Hz (float32 array, DC excluded).
def bump(f, fc, octaves):
    """Gaussian band centred on fc Hz, `octaves` standard deviation wide."""
    return np.exp(-0.5 * (np.log2(f / fc) / octaves) ** 2)


def highpass(f, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (fc / f) ** (2 * order))


def lowpass(f, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (f / fc) ** (2 * order))


def noise(rng, n: int, rate: float, shape, *, lowcut: float = 18.0) -> np.ndarray:
    """Periodic coloured noise of `n` frames with magnitude response `shape(f)`.

    Synthesised as a random spectrum and one inverse FFT, so it loops exactly and costs
    one FFT. DC and everything below `lowcut` Hz is removed (no offset, no rumble).
    Returns unit-RMS float32.
    """
    f = np.fft.rfftfreq(n, 1.0 / rate).astype(F32)
    f[0] = 1.0
    mag = np.asarray(shape(f), F32)
    mag[f < lowcut] = 0.0
    mag[0] = 0.0
    spec = np.empty(f.size, np.complex64)
    spec.real = rng.standard_normal(f.size, F32) * mag
    spec.imag = rng.standard_normal(f.size, F32) * mag
    x = np.fft.irfft(spec, n).astype(F32, copy=False)
    x /= F32(np.sqrt(np.dot(x, x) / n) + 1e-12)
    return x


def drift(rng, m: int, ctl_rate: float, cutoff: float) -> np.ndarray:
    """Smooth periodic random control signal: m points, Gaussian low-pass at `cutoff` Hz.

    Zero-mean, unit-RMS float32.
    """
    return noise(rng, m, ctl_rate, lambda f: np.exp(-((f / cutoff) ** 2)), lowcut=0.0)


def upsample(ctl: np.ndarray, out: np.ndarray | None = None) -> np.ndarray:
    """Periodic linear interpolation of a control signal to audio rate (x CTL).

    Writes into `out` (len(ctl)*CTL float32) when given, to spare a large allocation.
    """
    frac = np.arange(CTL, dtype=F32) / F32(CTL)
    grid = out.reshape(len(ctl), CTL) if out is not None else np.empty((len(ctl), CTL), F32)
    np.multiply((np.roll(ctl, -1) - ctl)[:, None], frac[None, :], out=grid)
    grid += ctl[:, None]
    return grid.reshape(-1)


def layer(dst: np.ndarray, rng, rate: int, shape, length: int, env: np.ndarray | None,
          scale: float, tmp: np.ndarray) -> None:
    """dst += tile(noise of `length` frames) * upsample(env) * scale, in place.

    `length` divides len(dst) and is a CTL multiple, so the tiled carrier lines up with
    the control grid. Noise repeating every ~10 s under a full-length envelope is not
    heard as a repeat, and it is an order of magnitude cheaper than a full-length FFT.
    `tmp` is a len(dst) float32 scratch buffer.
    """
    c = noise(rng, length, rate, shape)
    c *= F32(scale)
    k = len(dst) // length
    if env is None:
        dst.reshape(k, length)[:] += c[None, :]
        return
    up = upsample(env, tmp).reshape(k, length)
    up *= c[None, :]
    dst += tmp


def carrier_length(n: int, rate: int) -> int:
    """Length of the tiled noise carriers in an n-frame bed (about 10 s, dividing n)."""
    return divisor_near(n, 10 * rate)


def periodic_freq(freq: float, n: int, rate: int) -> float:
    """Nudge `freq` so it completes whole cycles in n frames (seamless loops)."""
    return max(1, round(freq * n / rate)) * rate / n


def envelope(n: int, rate: int, attack: float, tau: float, *, release: float = 0.008) -> np.ndarray:
    """Raised-cosine attack (>= MIN_ATTACK) into an exponential decay of time constant
    `tau` seconds, with a short raised-cosine release at the end so the grain ends at 0."""
    t = np.arange(n, dtype=F32) / F32(rate)
    a = max(MIN_ATTACK, attack)
    env = np.where(t < a, 0.5 - 0.5 * np.cos(np.pi * np.minimum(t / a, 1.0)),
                   np.exp(-(t - a) / max(tau, 1e-4))).astype(F32)
    r = min(n, max(2, int(release * rate)))
    env[-r:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r))).astype(F32)
    return env


def fade(n: int, rate: int, attack: float, release: float) -> np.ndarray:
    """Flat gain with raised-cosine ramps in (>= MIN_ATTACK) and out."""
    env = np.ones(n, F32)
    a = min(n, max(2, int(max(MIN_ATTACK, attack) * rate)))
    r = min(n, max(2, int(release * rate)))
    env[:a] *= (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a))).astype(F32)
    env[-r:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r))).astype(F32)
    return env


def voice(freq: np.ndarray, rate: int, partials=((1.0, 1.0),)) -> np.ndarray:
    """Harmonic/inharmonic oscillator following a per-sample frequency curve (Hz).

    `partials` are (ratio, amplitude) pairs; partials above 0.45*rate are dropped so
    nothing aliases on the 22.05 kHz tier.
    """
    phase = np.cumsum(np.asarray(freq, np.float64)) * (2.0 * np.pi / rate)
    peak = float(np.max(freq)) if len(freq) else 0.0
    out = np.zeros(len(freq), F32)
    for ratio, amp in partials:
        if ratio * peak < 0.45 * rate:
            out += F32(amp) * np.sin(ratio * phase).astype(F32)
    return out


def glide(n: int, points) -> np.ndarray:
    """Piecewise-linear frequency curve: `points` are (fraction 0..1, Hz)."""
    xs = np.array([p[0] for p in points], np.float64)
    ys = np.array([p[1] for p in points], np.float64)
    return np.interp(np.linspace(0.0, 1.0, n), xs, ys).astype(F32)


def pan_gains(p: float) -> tuple[float, float]:
    """Equal-power pan: p=-1 hard left, 0 centre, +1 hard right."""
    a = (min(1.0, max(-1.0, p)) + 1.0) * np.pi / 4.0
    return float(np.cos(a)), float(np.sin(a))


def add_wrapped(dst: np.ndarray, grain: np.ndarray, at: int, gain: float) -> None:
    """dst[at:at+len] += gain*grain, wrapping past the end of a loop."""
    n = dst.shape[-1]
    g = grain.shape[-1]
    at %= n
    end = at + g
    if end <= n:
        dst[..., at:end] += F32(gain) * grain
    else:
        head = n - at
        dst[..., at:] += F32(gain) * grain[..., :head]
        dst[..., :g - head] += F32(gain) * grain[..., head:]


def place(dst: np.ndarray, dry: np.ndarray, wet: np.ndarray | None, at: int, p: float,
          gain: float, rate: int) -> None:
    """Place a mono dry grain at pan `p` (with up to 0.35 ms delay to the far ear) plus
    its fixed diffuse stereo reverb `wet` into a (2, n) bed."""
    left, right = pan_gains(p)
    lag = int(abs(p) * 0.00035 * rate)
    add_wrapped(dst[0], dry, at + (lag if p > 0 else 0), gain * left)
    add_wrapped(dst[1], dry, at + (lag if p < 0 else 0), gain * right)
    if wet is not None:
        add_wrapped(dst, wet, at, gain)


def reverb_ir(rate: int, rt60: float, seed: str, *, damping: float = 0.45,
              predelay: float = 0.014) -> np.ndarray:
    """Short synthetic room/lake tail: (2, L) float32, unit energy per channel.

    Decorrelated noise per ear, highs decaying `damping` times faster than lows, a few
    early reflections, and a raised-cosine end so the tail never truncates.
    """
    rng = seed_for("ir:" + seed)
    length = int(rate * rt60 * 0.9) + int(predelay * rate)
    fast = next_fast(length)
    t = np.arange(length, dtype=F32) / F32(rate)
    ir = np.zeros((2, length), F32)
    pre = int(predelay * rate)
    tt = np.maximum(t - predelay, 0.0)
    for ch in range(2):
        low = noise(rng, fast, rate, lambda f: lowpass(f, 2600.0, 2))[:length]
        high = noise(rng, fast, rate, lambda f: highpass(f, 2600.0, 2) * lowpass(f, 9000.0, 2))[:length]
        ir[ch] = low * np.exp(-6.91 * tt / rt60) + 0.5 * high * np.exp(-6.91 * tt / (rt60 * damping))
        ir[ch, :pre] = 0.0
        for k in range(5):
            tap = pre + int(rng.uniform(0.004, 0.04) * rate)
            if tap < length:
                ir[ch, tap] += F32(rng.uniform(0.6, 1.4) * (0.7 ** k) * 6.0)
    ir *= fade(length, rate, 0.004, min(0.3, rt60 * 0.25))[None, :]
    ir /= np.sqrt(np.sum(ir * ir, axis=1, keepdims=True)) + 1e-9
    return ir


def reverberate(dry: np.ndarray, ir: np.ndarray, wet_db: float) -> np.ndarray:
    """Wet-only stereo tail (2, len(dry)+L-1) of mono `dry` through `ir`, at `wet_db`
    relative to the dry signal's own energy scale."""
    n = len(dry) + ir.shape[1] - 1
    size = next_fast(n)
    spec = np.fft.rfft(dry, size)
    wet = np.fft.irfft(spec[None, :] * np.fft.rfft(ir, size, axis=1), size, axis=1)[:, :n]
    return (wet * 10 ** (wet_db / 20.0)).astype(F32)


def encode(x: np.ndarray) -> Bed:
    """(2, n) float32 → unit-RMS int16 Bed. Removes any residual mean; consumes `x`."""
    n = x.shape[1]
    x -= x.mean(axis=1, keepdims=True)
    rms = float(np.sqrt((np.dot(x[0], x[0]) + np.dot(x[1], x[1])) / (2 * n)))
    peak = max(float(x.max()), -float(x.min()))
    if peak < 1e-9:
        return Bed(np.zeros((2, n), np.int16), 0.0)
    q = 32000.0 / peak
    x *= F32(q)
    return Bed(x.astype(np.int16), 1.0 / (rms * q))


def events(rng, seconds: float, mean_gap: float, shape: float = 4.0, start: float = 0.0):
    """Irregular event times in [0, seconds): gamma-distributed gaps (shape 4 = lively
    but not metronomic)."""
    out = []
    t = start + rng.uniform(0, mean_gap)
    while t < seconds:
        out.append(t)
        t += rng.gamma(shape, mean_gap / shape)
    return out


# ---------------------------------------------------------------- grains

def bubble(rate: int, rng, f0: float, tau: float) -> np.ndarray:
    """Water drop/bubble: a sine whose pitch rises ~25% as it rings (Minnaert bubble)."""
    n = int(rate * min(0.12, tau * 5 + 0.01))
    f = glide(n, ((0.0, f0), (1.0, f0 * rng.uniform(1.15, 1.35))))
    return voice(f, rate) * envelope(n, rate, MIN_ATTACK, tau)


def hull_knock(rate: int, rng, base: float, tau: float = 0.14) -> np.ndarray:
    """Aluminium hull answering a small wave: a few inharmonic, quickly damped modes."""
    n = int(rate * 0.42)
    t = np.arange(n, dtype=F32) / F32(rate)
    out = np.zeros(n, F32)
    for ratio, amp, decay in ((1.0, 1.0, 1.0), (1.47, 0.7, 0.8), (2.09, 0.45, 0.62),
                              (2.56, 0.3, 0.5), (3.39, 0.16, 0.38)):
        f = base * ratio * rng.uniform(0.985, 1.015)
        if f < 0.45 * rate:
            out += F32(amp) * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)).astype(F32) \
                * np.exp(-t / (tau * decay)).astype(F32)
    return out * fade(n, rate, 0.005, 0.02)


def drop(rate: int, rng) -> np.ndarray:
    """One rain drop on water: soft tick plus a rising bubble ring."""
    f0 = float(np.exp(rng.uniform(np.log(1000), np.log(2900))))
    ring = bubble(rate, rng, f0, rng.uniform(0.008, 0.022))
    n = len(ring)
    tick = noise(rng, next_fast(n), rate, lambda f: bump(f, 3000.0, 0.8))[:n]
    tick *= envelope(n, rate, MIN_ATTACK, 0.003) * F32(0.12)
    return ring + tick


def chirp_grain(rate, rng, freq, pulses, pulse_len, gap) -> np.ndarray:
    """A cricket chirp: `pulses` raised-cosine pulses of a pure carrier."""
    plen = int(pulse_len * rate)
    step = int((pulse_len + gap) * rate)
    n = step * (pulses - 1) + plen + 8
    t = np.arange(n, dtype=F32) / F32(rate)
    car = np.sin(2 * np.pi * freq * t).astype(F32) + 0.08 * np.sin(4 * np.pi * freq * t).astype(F32)
    env = np.zeros(n, F32)
    window = (0.5 - 0.5 * np.cos(np.linspace(0, 2 * np.pi, plen))).astype(F32)
    for k in range(pulses):
        env[k * step:k * step + plen] += window * F32(1.0 - 0.12 * k + rng.uniform(-0.05, 0.05))
    return car * env


# Birds: a few distinct FM species. Each returns a dry mono phrase.
def bird_feebee(rate, rng):
    k = rng.uniform(0.95, 1.05)
    parts = []
    for f_hi, f_lo, dur in ((3950 * k, 3880 * k, 0.28), (3480 * k, 3420 * k, 0.32)):
        n = int(dur * rate)
        parts += [voice(glide(n, ((0, f_hi), (0.5, f_hi * 0.995), (1, f_lo))), rate,
                        ((1, 1.0), (2, 0.04))) * fade(n, rate, 0.025, 0.05),
                  np.zeros(int(0.07 * rate), F32)]
    return np.concatenate(parts)


def bird_warble(rate, rng):
    parts = []
    for _ in range(int(rng.integers(3, 6))):
        n = int(rng.uniform(0.11, 0.18) * rate)
        a, b, c = rng.uniform(2000, 2400), rng.uniform(2800, 3300), rng.uniform(2200, 2600)
        parts += [voice(glide(n, ((0, a), (0.45, b), (1, c))), rate, ((1, 1.0), (2, 0.12)))
                  * fade(n, rate, 0.012, 0.03),
                  np.zeros(int(rng.uniform(0.06, 0.13) * rate), F32)]
    return np.concatenate(parts)


def bird_twitter(rate, rng):
    parts = []
    for _ in range(2):
        n = int(0.09 * rate)
        f = rng.uniform(4300, 4700)
        parts += [voice(glide(n, ((0, f), (1, f * 0.97))), rate) * fade(n, rate, 0.01, 0.02),
                  np.zeros(int(0.07 * rate), F32)]
    for i in range(int(rng.integers(7, 12))):
        n = int(0.03 * rate)
        top = rng.uniform(5200, 6000) * (1 - 0.015 * i)
        parts += [voice(glide(n, ((0, top), (1, top * 0.58))), rate) * fade(n, rate, MIN_ATTACK, 0.01),
                  np.zeros(int(0.026 * rate), F32)]
    return np.concatenate(parts)


def bird_flute(rate, rng):
    parts = []
    notes = rng.choice([1760, 1975, 2217, 2349, 2637], 3, replace=False)
    for f in notes:
        n = int(rng.uniform(0.16, 0.24) * rate)
        curve = glide(n, ((0, f * 0.98), (0.2, f), (1, f * 1.01)))
        parts += [voice(curve, rate, ((1, 1.0), (2, 0.3), (3, 0.12))) * fade(n, rate, 0.02, 0.06),
                  np.zeros(int(0.05 * rate), F32)]
    n = int(0.32 * rate)
    t = np.arange(n, dtype=F32) / F32(rate)
    trill = 3700 + 450 * np.sign(np.sin(2 * np.pi * 22 * t))
    trill = np.convolve(trill, np.ones(64, F32) / 64, "same").astype(F32)
    parts.append(voice(trill, rate, ((1, 0.55), (2, 0.08))) * fade(n, rate, 0.02, 0.08))
    return np.concatenate(parts)


def bird_whistle(rate, rng):
    """White-throated-sparrow style: long pure whistles then soft triplets (alpine)."""
    k = rng.uniform(0.96, 1.04)
    parts = []
    t_vib = None
    for f, dur in ((3200 * k, 0.62), (3900 * k, 0.5)):
        n = int(dur * rate)
        t_vib = np.arange(n, dtype=F32) / F32(rate)
        curve = f * (1 + 0.004 * np.sin(2 * np.pi * 5.0 * t_vib))
        parts += [voice(curve, rate, ((1, 1.0), (2, 0.03))) * fade(n, rate, 0.04, 0.08),
                  np.zeros(int(0.06 * rate), F32)]
    for _ in range(int(rng.integers(2, 4))):
        for _ in range(3):
            n = int(0.11 * rate)
            parts += [voice(glide(n, ((0, 3700 * k), (1, 3640 * k))), rate) * fade(n, rate, 0.012, 0.03),
                      np.zeros(int(0.035 * rate), F32)]
    return np.concatenate(parts)


def gull_call(rate, rng, calls=None):
    """'Kyow' calls: a falling harmonic-rich cry with a nasal formant."""
    parts = []
    for _ in range(calls or int(rng.integers(2, 4))):
        n = int(rng.uniform(0.2, 0.26) * rate)
        f0 = rng.uniform(1020, 1150)
        curve = glide(n, ((0, f0 * 0.9), (0.18, f0), (1, f0 * 0.66)))
        partials = tuple((k, 0.82 ** k * (1 + 1.6 * np.exp(-0.5 * ((k * f0 - 2200) / 700) ** 2)))
                         for k in range(1, 7))
        t = np.arange(n, dtype=F32) / F32(rate)
        rough = 1 + 0.15 * np.sin(2 * np.pi * 68 * t)
        parts += [voice(curve, rate, partials) * rough * fade(n, rate, 0.015, 0.06),
                  np.zeros(int(rng.uniform(0.1, 0.16) * rate), F32)]
    return np.concatenate(parts)


def star_bell(rate, rng, freq=None):
    """A soft star twinkle: one high bell with a faint inharmonic overtone."""
    f = freq or float(rng.choice([1568.0, 1760.0, 2093.0, 2349.0, 2637.0, 3136.0]))
    n = int(1.2 * rate)
    t = np.arange(n, dtype=F32) / F32(rate)
    out = np.sin(2 * np.pi * f * t).astype(F32)
    if 2.76 * f < 0.45 * rate:
        out += 0.12 * np.sin(2 * np.pi * 2.76 * f * t).astype(F32) * np.exp(-t * 6).astype(F32)
    return out * envelope(n, rate, 0.008, 0.32, release=0.05)


def frog_peep(rate, rng):
    n = int(rng.uniform(0.05, 0.07) * rate)
    f = rng.uniform(2650, 2850)
    return voice(glide(n, ((0, f * 0.92), (1, f * 1.08))), rate, ((1, 1.0), (2, 0.06))) \
        * fade(n, rate, 0.006, 0.02)


def frog_gunk(rate, rng):
    """Green frog: a plucked-banjo 'gunk' with a falling pitch and a low formant."""
    n = int(0.16 * rate)
    f0 = rng.uniform(175, 215)
    curve = glide(n, ((0, f0 * 1.06), (1, f0 * 0.9)))
    partials = tuple((k, (1.0 / k) * (1 + 2.0 * np.exp(-0.5 * ((k * f0 - 700) / 260) ** 2)))
                     for k in range(1, 11))
    return voice(curve, rate, partials) * envelope(n, rate, 0.005, 0.045, release=0.03)


def frog_bull(rate, rng):
    """Bullfrog 'rumm': deep, rough, 0.5 s."""
    n = int(rng.uniform(0.45, 0.6) * rate)
    f0 = rng.uniform(100, 120)
    t = np.arange(n, dtype=F32) / F32(rate)
    partials = tuple((k, (1.0 / k) * (1 + 2.5 * np.exp(-0.5 * ((k * f0 - 260) / 90) ** 2)))
                     for k in range(1, 9))
    tone = voice(np.full(n, f0, F32), rate, partials)
    rough = 0.7 + 0.3 * np.sin(2 * np.pi * 21 * t).astype(F32)
    return tone * rough * fade(n, rate, 0.03, 0.1)


# ---------------------------------------------------------------- beds

def _ctl(n, rate):
    return n // CTL, rate / CTL


def _unit(x: np.ndarray) -> np.ndarray:
    """Scale a positive control signal to unit RMS."""
    return (x / np.sqrt(np.mean(x * x))).astype(F32)


def bed_lap(rate: int, n: int) -> Bed:
    """Water lapping against an aluminium hull: irregular wavelets in swell groups,
    each a sloshing noise burst, a bubbly glug or two and sometimes a soft hull knock."""
    rng = seed_for("lap")
    m, ctl = _ctl(n, rate)
    nc = carrier_length(n, rate)
    secs = n / rate
    swell = 0.62 + 0.38 * np.tanh(1.2 * drift(rng, m, ctl, 0.09))
    env = np.zeros((2, m), F32)
    kernels = [envelope(int(ctl * 0.9), int(ctl), a, tau) for a, tau in
               ((0.05, 0.16), (0.07, 0.22), (0.04, 0.12))]
    knocks = [hull_knock(rate, rng, rng.uniform(150, 250), rng.uniform(0.1, 0.16)) for _ in range(8)]
    glugs = [bubble(rate, rng, rng.uniform(320, 900), rng.uniform(0.015, 0.03)) for _ in range(12)]
    out = np.zeros((2, n), F32)
    for t in events(rng, secs, 0.62):
        i = int(t * ctl)
        amp = float(rng.lognormal(0.0, 0.3)) * float(swell[i % m])
        p = rng.uniform(-0.75, 0.75)
        left, right = pan_gains(p)
        k = kernels[int(rng.integers(3))]
        add_wrapped(env[0], k, i, amp * left * 1.41)
        add_wrapped(env[1], k, i, amp * right * 1.41)
        at = int((t + 0.03) * rate)
        if rng.random() < 0.5:
            place(out, knocks[int(rng.integers(8))], None, at, p, 0.09 * amp, rate)
        for _ in range(int(rng.integers(1, 3))):
            place(out, glugs[int(rng.integers(12))], None,
                  at + int(rng.uniform(0.0, 0.25) * rate), p, 0.07 * amp, rate)
    env += 0.12 * swell[None, :]
    # Lapping lives below ~2 kHz; only a whisper of fizz above, so the wavelets stay soft.
    shape = (lambda f: highpass(f, 90.0, 2) * (0.9 * bump(f, 420.0, 1.0) + 0.3 * bump(f, 1300.0, 0.9)
                                                + 0.025 * bump(f, 4200.0, 1.0)))
    tmp = np.empty(n, F32)
    for ch in range(2):
        layer(out[ch], rng, rate, shape, nc, env[ch], 0.6, tmp)
    return encode(out)


def bed_wash(rate: int, n: int) -> Bed:
    """Open-water rush along the hull: turbulent broadband wash with small bow slaps."""
    rng = seed_for("wash")
    m, ctl = _ctl(n, rate)
    nc = carrier_length(n, rate)
    shape = (lambda f: highpass(f, 60.0, 2) * (1.0 / np.sqrt(f / 200.0 + 1.0))
             * (0.45 * bump(f, 1500.0, 1.5) + 0.35 * bump(f, 220.0, 1.0) + 0.12 * bump(f, 5200.0, 0.9)))
    slow = drift(rng, m, ctl, 0.25)
    out = np.zeros((2, n), F32)
    tmp = np.empty(n, F32)
    for ch in range(2):
        layer(out[ch], rng, rate, shape, nc,
              _unit(np.exp(0.32 * np.tanh(drift(rng, m, ctl, 7.0)) + 0.22 * np.tanh(slow))), 1.0, tmp)
    glugs = [bubble(rate, rng, rng.uniform(400, 1400), rng.uniform(0.01, 0.025)) for _ in range(10)]
    for t in events(rng, n / rate, 0.45):
        place(out, glugs[int(rng.integers(10))], None, int(t * rate), rng.uniform(-0.8, 0.8),
              float(rng.lognormal(0, 0.3)) * 0.3, rate)
    return encode(out)


WIND = {
    # body shape, detail shape, gust cutoff Hz, gust depth, detail exponent, detail level
    "briar": (lambda f: highpass(f, 70, 2) * (bump(f, 380, 1.3) + 0.25 * bump(f, 120, 0.8)),
              lambda f: bump(f, 3600, 0.9) * highpass(f, 1500, 2), 0.07, 0.75, 1.6, 0.55),
    "cedar": (lambda f: highpass(f, 40, 2) * (bump(f, 260, 1.6) + 0.5 * bump(f, 90, 0.8)),
              lambda f: bump(f, 1400, 1.0) + 0.4 * bump(f, 3200, 0.8), 0.09, 0.95, 2.0, 0.6),
    "flathead": (lambda f: highpass(f, 350, 3) * bump(f, 1700, 1.2),
                 lambda f: bump(f, 1180, 0.07) + 0.6 * bump(f, 1760, 0.06) + 0.3 * bump(f, 4200, 0.6),
                 0.08, 0.9, 2.2, 0.45),
    "crater": (lambda f: highpass(f, 35, 2) * (bump(f, 110, 0.35) + 0.6 * bump(f, 230, 0.4)
                                               + 0.25 * bump(f, 420, 0.8)),
               lambda f: bump(f, 900, 0.8), 0.03, 0.6, 1.5, 0.15),
    "nebula": (lambda f: highpass(f, 200, 2) * bump(f, 2600, 1.4),
               lambda f: bump(f, 6000, 0.5), 0.04, 0.5, 1.5, 0.2),
}


def bed_wind(rate: int, n: int, lake: str) -> Bed:
    """Lake wind: a body band that follows slow gusts and a detail band (leaves, larch
    whistle, canyon hollow) that brightens more than linearly with each gust. The right
    ear hears each gust ~0.4 s later, as wind crossing the boat."""
    rng = seed_for("wind:" + lake)
    body, detail, cutoff, depth, power, level = WIND[lake]
    m, ctl = _ctl(n, rate)
    nc = carrier_length(n, rate)
    # tanh bounds each gust to a few dB above the mean: wind swells, it never slams.
    gust = _unit(np.exp(depth * 1.2 * np.tanh(drift(rng, m, ctl, cutoff) / 1.2)
                        + 0.15 * np.tanh(drift(rng, m, ctl, 0.7))))
    lag = int(0.4 * ctl)
    out = np.zeros((2, n), F32)
    tmp = np.empty(n, F32)
    for ch in range(2):
        g = np.roll(gust, lag * ch)
        hi = g ** power
        if lake in ("briar", "cedar"):
            # Leaves flutter in their own quick rhythm on top of the gusts.
            hi = hi * (0.6 + 0.4 * np.tanh(drift(rng, m, ctl, 6.0)))
        layer(out[ch], rng, rate, body, nc, g, 1.0, tmp)
        layer(out[ch], rng, rate, detail, nc, _unit(hi), level, tmp)
    return encode(out)


def bed_rain(rate: int, n: int, heavy: bool) -> Bed:
    """Rain on the lake: fine hiss plus discrete drops (and the odd tink on the hull).

    The light layer is sparse distinct drops; the heavy layer adds dense drops and a
    low patter, so density (not only loudness) follows the rain amount.
    """
    rng = seed_for("rain:" + ("heavy" if heavy else "light"))
    m, ctl = _ctl(n, rate)
    nc = carrier_length(n, rate)
    # A soft, rounded hiss (peak ~4 kHz, rolled off above 9 kHz): calm rain, not static.
    hiss = (lambda f: highpass(f, 900.0, 2) * bump(f, 4200.0, 1.2) * lowpass(f, 9000.0, 2)
            + (0.45 * bump(f, 650.0, 1.1) if heavy else 0.0))
    out = np.zeros((2, n), F32)
    tmp = np.empty(n, F32)
    for ch in range(2):
        layer(out[ch], rng, rate, hiss, nc, _unit(np.exp(0.18 * drift(rng, m, ctl, 0.4))),
              0.55 if heavy else 0.35, tmp)
    drops = [drop(rate, rng) for _ in range(24)]
    tinks = [hull_knock(rate, rng, rng.uniform(1900, 2600), 0.03) * F32(0.5) for _ in range(4)]
    for t in events(rng, n / rate, 1 / (60.0 if heavy else 13.0), shape=1.5):
        at = int(t * rate)
        p = rng.uniform(-1, 1)
        if rng.random() < 0.06:
            place(out, tinks[int(rng.integers(4))], None, at, p, float(rng.lognormal(0, 0.3)) * 0.3, rate)
        else:
            place(out, drops[int(rng.integers(24))], None, at, p, float(rng.lognormal(0, 0.4)) * 0.45, rate)
    return encode(out)


def bed_insects(rate: int, n: int) -> Bed:
    """Night insects: four field-cricket voices (each its own pitch, rhythm and place)
    and one tree-cricket trill that sings in long phrases."""
    rng = seed_for("insects")
    secs = n / rate
    out = np.zeros((2, n), F32)
    voices = ((4600, 3, 0.018, 0.022, 0.42, -0.6, 1.0), (4150, 4, 0.014, 0.018, 0.61, 0.55, 0.7),
              (5050, 2, 0.016, 0.02, 0.33, 0.12, 0.42), (3900, 3, 0.02, 0.025, 0.75, -0.25, 0.3))
    for freq, pulses, plen, gap, period, p, gain in voices:
        freq = min(freq, 0.42 * rate)
        grains = [chirp_grain(rate, rng, freq * rng.uniform(0.99, 1.01), pulses, plen, gap) for _ in range(4)]
        t = rng.uniform(0, period)
        while t < secs:
            # Each cricket drifts in and out of song a little.
            g = gain * (0.75 + 0.25 * np.sin(2 * np.pi * t / secs * 3 + p * 5))
            place(out, grains[int(rng.integers(4))], None, int(t * rate), p, g, rate)
            t += period * rng.uniform(0.94, 1.06)
    # Tree cricket: a seamless trill tile (whole carrier and pulse cycles) under phrases.
    tile = divisor_near(n, 1.5 * rate)
    f_car = periodic_freq(min(2900.0, 0.4 * rate), tile, rate)
    f_pulse = periodic_freq(42.0, tile, rate)
    tt = np.arange(tile, dtype=np.float64) / rate
    trill = (np.sin(2 * np.pi * f_car * tt) * (0.5 - 0.5 * np.cos(2 * np.pi * f_pulse * tt)) ** 2).astype(F32)
    m, ctl = _ctl(n, rate)
    phrase = np.zeros(m, F32)
    for t in events(rng, secs, 14.0, shape=3.0):
        length = int(rng.uniform(5, 11) * ctl)
        add_wrapped(phrase, fade(length, int(ctl), 0.6, 0.9), int(t * ctl), 1.0)
    tmp = upsample(np.minimum(phrase, 1.0) * F32(0.32))
    tmp.reshape(n // tile, tile)[:] *= trill[None, :]
    left, right = pan_gains(-0.3)
    out[0] += tmp * F32(left)
    tmp *= F32(right)
    add_wrapped(out[1], tmp, int(0.0002 * rate), 1.0)
    return encode(out)


FROGS = {
    # (peepers, green frogs, bullfrogs, distance gain)
    "briar": (8, 2, 1, 1.0),
    "cedar": (3, 2, 1, 0.8),
    "crater": (2, 1, 0, 0.55),
}


def bed_frogs(rate: int, n: int, lake: str) -> Bed:
    """Frog chorus after dark: peepers calling in waxing and waning bouts, a couple of
    green frogs and the odd distant bullfrog, all in a soft lake reverb."""
    rng = seed_for("frogs:" + lake)
    peepers, greens, bulls, distance = FROGS[lake]
    secs = n / rate
    ir = reverb_ir(rate, 0.9, "frogs")
    out = np.zeros((2, n), F32)
    m, ctl = _ctl(n, rate)

    def bank(make, count, wet_db):
        dry = [make(rate, rng) for _ in range(count)]
        return [(d, reverberate(d, ir, wet_db)) for d in dry]

    peeps = bank(frog_peep, 6, -9.0)
    for _ in range(peepers):
        p = rng.uniform(-0.9, 0.9)
        g = distance * rng.uniform(0.35, 1.0)
        # Bouts: each peeper sings for a while, rests, and joins in again.
        bout = 0.5 + 0.5 * np.tanh(2.0 * drift(rng, m, ctl, 0.03))
        t = rng.uniform(0, 1)
        while t < secs:
            if rng.random() < bout[int(t * ctl) % m]:
                d, w = peeps[int(rng.integers(len(peeps)))]
                place(out, d, w, int(t * rate), p, g * 0.55, rate)
            t += rng.uniform(0.85, 1.35)
    gunks = bank(frog_gunk, 4, -8.0)
    for _ in range(greens):
        p, g = rng.uniform(-0.8, 0.8), distance * rng.uniform(0.6, 1.0)
        for t in events(rng, secs, 9.0, shape=2.0):
            for k in range(int(rng.integers(1, 4))):
                d, w = gunks[int(rng.integers(len(gunks)))]
                place(out, d, w, int((t + 0.32 * k) * rate), p, g, rate)
    if bulls:
        rumms = bank(frog_bull, 3, -6.0)
        for _ in range(bulls):
            p = rng.uniform(-0.9, 0.9)
            for t in events(rng, secs, 22.0, shape=3.0):
                d, w = rumms[int(rng.integers(len(rumms)))]
                place(out, d, w, int(t * rate), p, distance * 0.7, rate)
    return encode(out)


BIRDS = {
    # (species, individuals, mean seconds between phrases, gain, phrase variants, wet dB)
    "briar": ((bird_feebee, 1, 10.0, 0.7, 4, -10.0), (bird_warble, 2, 8.0, 0.8, 6, -11.0),
              (bird_twitter, 1, 12.0, 0.45, 4, -10.0), (bird_flute, 1, 14.0, 0.6, 4, -8.0)),
    "cedar": ((gull_call, 2, 15.0, 0.55, 5, -6.0), (bird_warble, 1, 14.0, 0.6, 4, -10.0),
              (bird_twitter, 1, 18.0, 0.35, 3, -10.0)),
    "flathead": ((bird_whistle, 1, 17.0, 0.6, 4, -7.0), (bird_feebee, 1, 26.0, 0.45, 3, -8.0)),
    "crater": ((bird_twitter, 1, 28.0, 0.35, 3, -6.0), (bird_whistle, 1, 34.0, 0.35, 3, -5.0)),
    "nebula": ((star_bell, 4, 7.0, 0.25, 8, -2.0),),
}


def bed_birds(rate: int, n: int, lake: str) -> Bed:
    """Dawn/dusk birdsong for a lake (on the Lagoon: a sparse field of star bells).

    Each species is a handful of phrase variants with their own reverb, sung by one or
    two individuals at fixed places around the shore, sparse and irregular.
    """
    rng = seed_for("birds:" + lake)
    secs = n / rate
    ir = reverb_ir(rate, 2.2 if lake == "nebula" else 1.1, "birds:" + lake, damping=0.4)
    out = np.zeros((2, n), F32)
    for species, individuals, gap, gain, variants, wet_db in BIRDS[lake]:
        dry = [species(rate, rng) for _ in range(variants)]
        bank = [(d, reverberate(d, ir, wet_db)) for d in dry]
        for _ in range(individuals):
            p = rng.uniform(-0.85, 0.85)
            g = gain * rng.uniform(0.6, 1.0)
            for t in events(rng, secs, gap, shape=2.5):
                d, w = bank[int(rng.integers(len(bank)))]
                place(out, d, w, int(t * rate), p, g * float(rng.uniform(0.75, 1.0)), rate)
    return encode(out)


def build_bed(key: str, rate: int, n: int, stop: threading.Event | None = None) -> Bed:
    """Build the bed named `key` ("lap", "wash", "rain_light", "rain_heavy", "insects",
    "wind:<lake>", "birds:<lake>", "frogs:<lake>") as an n-frame loop at `rate` Hz, or the
    music piece "song:<id>" (`songs.render`), whose length n the piece fixes.
    `stop` goes to `songs.render`, which ends an abandoned piece within one block (#168); beds
    are short and ignore it.

    Raises:
        KeyError: unknown bed, lake or song.
        ValueError: `n` is not the piece's length at `rate`.
    """
    kind, _, lake = key.partition(":")
    if kind == "song":
        from . import songs  # songs imports this module, so it is imported only when needed
        bed = songs.render(lake, rate, stop=stop)
        if bed.data.shape[1] != n:
            raise ValueError(f"{key}: {n} frames asked for, the piece has {bed.data.shape[1]}")
        return bed
    if kind == "lap":
        return bed_lap(rate, n)
    if kind == "wash":
        return bed_wash(rate, n)
    if kind == "rain_light":
        return bed_rain(rate, n, False)
    if kind == "rain_heavy":
        return bed_rain(rate, n, True)
    if kind == "insects":
        return bed_insects(rate, n)
    if kind == "wind":
        return bed_wind(rate, n, lake)
    if kind == "birds":
        return bed_birds(rate, n, lake)
    if kind == "frogs":
        return bed_frogs(rate, n, lake)
    raise KeyError(key)


# ---------------------------------------------------------------- cues

# Peak level each cue is normalised to, in dBFS. All sit between -16 and -6 dBFS; the bite
# is the loudest so the ambience never buries it.
CUE_PEAK_DB = {"bite": -8.0, "splash": -12.0, "sell": -11.0, "click": -15.0, "error": -13.0,
               "bot": -12.0, "loon": -13.0, "gull": -14.0, "frog": -14.0, "twinkle": -15.0}
DEFAULT_PEAK_DB = -14.0
CUE_VARIANTS = {"loon": 3, "gull": 3, "frog": 4, "twinkle": 3, "splash": 4}


def _bell(rate, freq, n, tau, partials=((1.0, 1.0), (2.0, 0.22), (3.0, 0.08), (4.2, 0.04))):
    t = np.arange(n, dtype=F32) / F32(rate)
    out = np.zeros(n, F32)
    for ratio, amp in partials:
        if ratio * freq < 0.45 * rate:
            out += F32(amp) * np.sin(2 * np.pi * freq * ratio * t).astype(F32) \
                * np.exp(-t * ratio ** 0.7 / tau).astype(F32)
    return out * envelope(n, rate, MIN_ATTACK, 1e3, release=0.03)


def _at(n, rate, start, grain):
    out = np.zeros(n, F32)
    i = int(start * rate)
    out[i:i + len(grain)] += grain[:max(0, n - i)]
    return out


def _splash(rate, rng, size=1.0):
    """Water splash: two shaped noise bursts (impact, fall-back) and a few droplets."""
    n = int(0.55 * rate)
    body = noise(rng, next_fast(n), rate, lambda f: highpass(f, 250, 2) * bump(f, 1400, 1.4))[:n]
    out = body * envelope(n, rate, 0.005, 0.045 * size)
    out += 0.5 * body[::-1].copy() * _at(n, rate, 0.06, envelope(int(0.3 * rate), rate, 0.012, 0.07))
    for _ in range(3):
        out += 0.35 * _at(n, rate, rng.uniform(0.08, 0.24), bubble(rate, rng, rng.uniform(1300, 2800), 0.018))
    return out


def cue_dry(kind: str, rate: int, variant: int) -> tuple[np.ndarray, float, float]:
    """Dry mono source of one cue variant, its reverb time (s) and wet level (dB)."""
    rng = seed_for(f"cue:{kind}:{variant}")
    if kind == "bite":
        splash = _splash(rate, rng)
        n = int(0.9 * rate)
        pluck = _bell(rate, 392.0, int(0.8 * rate), 0.22,
                      tuple((k, 1.0 / k ** 1.4) for k in range(1, 7)))
        return _at(n, rate, 0.0, splash) * 0.9 + _at(n, rate, 0.035, pluck) * 0.8, 0.6, -14.0
    if kind == "splash":
        return _splash(rate, rng, 0.8 + 0.1 * variant), 0.5, -16.0
    if kind == "loon":
        n = int(1.9 * rate)
        lift = rng.uniform(0.94, 1.06)
        curve = glide(n, ((0, 560), (0.16, 600), (0.3, 930), (0.62, 910), (0.8, 780), (1, 740))) * F32(lift)
        t = np.arange(n, dtype=F32) / F32(rate)
        curve *= 1 + 0.010 * np.sin(2 * np.pi * 5.4 * t) * np.clip((t - 0.5) * 3, 0, 1)
        dry = voice(curve, rate, ((1, 1.0), (2, 0.3), (3, 0.1))) * fade(n, rate, 0.12, 0.35)
        return dry, 1.8, -5.0
    if kind == "gull":
        return gull_call(rate, rng, 2 + variant % 2), 1.2, -8.0
    if kind == "frog":
        g = frog_gunk(rate, rng)
        if variant % 2:
            g = np.concatenate([g, np.zeros(int(0.12 * rate), F32), frog_gunk(rate, rng) * F32(0.8)])
        return g, 0.6, -9.0
    if kind == "twinkle":
        n = int(1.3 * rate)
        notes = ((1568.0, 2093.0, 2637.0), (1760.0, 2349.0, 2637.0), (2093.0, 2637.0, 3136.0))[variant % 3]
        dry = sum(_at(n, rate, 0.11 * i, star_bell(rate, rng, f)[:n]) for i, f in enumerate(notes))
        return dry, 2.0, -3.0
    if kind == "sell":
        n = int(0.7 * rate)
        return (_at(n, rate, 0.0, _bell(rate, 784.0, int(0.6 * rate), 0.16))
                + _at(n, rate, 0.075, _bell(rate, 1175.0, int(0.6 * rate), 0.2))), 0.5, -13.0
    if kind == "bot":
        n = int(0.4 * rate)
        return (_at(n, rate, 0.0, _bell(rate, 880.0, int(0.3 * rate), 0.07, ((1.0, 1.0), (2.0, 0.08))))
                + _at(n, rate, 0.07, _bell(rate, 1320.0, int(0.3 * rate), 0.09, ((1.0, 1.0), (2.0, 0.06))))), \
            0.4, -16.0
    if kind == "error":
        # A soft wooden "bonk-bonk", falling a third: tells, never scolds.
        n = int(0.42 * rate)
        part = ((1.0, 1.0), (3.9, 0.12))
        return (_at(n, rate, 0.0, _bell(rate, 392.0, int(0.3 * rate), 0.07, part))
                + _at(n, rate, 0.12, _bell(rate, 311.0, int(0.3 * rate), 0.08, part))), 0.35, -18.0
    if kind == "click":
        n = int(0.09 * rate)
        return _bell(rate, 1500.0, n, 0.012, ((1.0, 1.0), (1.93, 0.4), (0.27, 0.5))), 0.3, -20.0
    n = int(0.15 * rate)
    return _bell(rate, 740.0, n, 0.03, ((1.0, 1.0), (2.0, 0.1))), 0.3, -20.0


def build_cue(kind: str, rate: int, variant: int = 0) -> np.ndarray:
    """A finished cue: (n, 2) float32 at `rate`, dry centred plus a short stereo
    reverb tail, peak-normalised to CUE_PEAK_DB (dBFS)."""
    dry, rt60, wet_db = cue_dry(kind, rate, variant)
    dry = dry.astype(F32) * fade(len(dry), rate, MIN_ATTACK, 0.01)
    wet = reverberate(dry, reverb_ir(rate, rt60, "cue:" + kind), wet_db)
    out = wet
    out[:, :len(dry)] += dry[None, :] * F32(0.7071)
    out *= fade(out.shape[1], rate, MIN_ATTACK, 0.04)[None, :]
    out -= out.mean(axis=1, keepdims=True)
    peak = float(np.max(np.abs(out))) + 1e-9
    out *= F32(10 ** (CUE_PEAK_DB.get(kind, DEFAULT_PEAK_DB) / 20.0) / peak)
    return np.ascontiguousarray(out.T)


def stroke(rate: int, variant: int) -> np.ndarray:
    """One oar stroke for both oars: catch, swish through the water, oarlock knock, and
    drips falling off the blades on the recovery. (n, 2) float32, peak about -16 dBFS."""
    rng = seed_for(f"stroke:{variant}")
    n = int(1.4 * rate)
    out = np.zeros((2, n), F32)
    swish_len = int(0.5 * rate)
    for ch, lag in ((0, 0.0), (1, rng.uniform(0.01, 0.03))):
        sw = noise(rng, next_fast(swish_len), rate, lambda f: bump(f, 900, 1.0) * highpass(f, 200, 2))[:swish_len]
        env = fade(swish_len, rate, 0.12, 0.25) * np.sin(np.linspace(0, np.pi, swish_len)).astype(F32)
        add_wrapped(out[ch], sw * env * F32(0.5), int(lag * rate), 1.0)
        catch = _splash(rate, rng, 0.5)[: int(0.2 * rate)] * fade(int(0.2 * rate), rate, 0.006, 0.08)
        add_wrapped(out[ch], catch * F32(0.35), int(lag * rate), 1.0)
        knock = hull_knock(rate, rng, rng.uniform(170, 210), 0.05) * F32(0.18)
        add_wrapped(out[ch], knock, int((lag + 0.02) * rate), 1.0)
        for _ in range(int(rng.integers(3, 6))):
            d = bubble(rate, rng, rng.uniform(1200, 2600), rng.uniform(0.01, 0.02))
            add_wrapped(out[ch], d * F32(rng.uniform(0.1, 0.2)), int(rng.uniform(0.6, 1.2) * rate), 1.0)
    out *= fade(n, rate, MIN_ATTACK, 0.05)[None, :]
    out -= out.mean(axis=1, keepdims=True)
    out *= F32(10 ** (-16 / 20) / (float(np.max(np.abs(out))) + 1e-9))
    return np.ascontiguousarray(out.T)


# ---------------------------------------------------------------- worker process

STROKE_VARIANTS = 6


def write_bed(key: str, rate: int, n: int, path: str) -> float:
    """Build bed `key` (see `build_bed`) and write its int16 (2, n) samples raw to `path`.

    Returns the bed's `unit` (float scale that makes the samples unit-RMS).
    """
    bed = build_bed(key, rate, n)
    bed.data.tofile(path)
    return bed.unit


def write_cues(rate: int, path: str) -> list[list]:
    """Build every cue variant and oar stroke at `rate` and write them back to back to
    `path` as raw float32 (frames, 2) blocks.

    Returns:
        [[name, variant, first_frame, frames], ...]; name is a cue kind or "stroke".
    """
    index, start = [], 0
    with open(path, "wb") as out:
        jobs = [(kind, v) for kind in CUE_PEAK_DB for v in range(CUE_VARIANTS.get(kind, 1))]
        jobs += [("stroke", v) for v in range(STROKE_VARIANTS)]
        for kind, variant in jobs:
            sound = stroke(rate, variant) if kind == "stroke" else build_cue(kind, rate, variant)
            sound.astype(F32, copy=False).tofile(out)
            index.append([kind, variant, start, len(sound)])
            start += len(sound)
    return index


def _worker(argv: list[str]) -> None:
    """`bed <key> <rate> <frames> <path>` or `cues <rate> <path>`: synthesise, write the
    samples to path, and print one JSON line ({"unit"} or {"index"}, plus "seconds").

    Side effect: on platforms with `os.nice`, raises this process's niceness by 10 so the
    game's frames come first; this priority adjustment is Unix/platform-dependent.
    """
    if hasattr(os, "nice"):
        os.nice(10)
    start = time.perf_counter()
    if argv[0] == "bed":
        result = {"unit": write_bed(argv[1], int(argv[2]), int(argv[3]), argv[4])}
    elif argv[0] == "cues":
        result = {"index": write_cues(int(argv[1]), argv[2])}
    else:
        raise SystemExit(f"unknown job {argv[0]!r}")
    result["seconds"] = time.perf_counter() - start
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    _worker(sys.argv[1:])
