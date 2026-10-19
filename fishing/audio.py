"""Small procedural mixer on SDL's queue. Silent if the device won't open."""

from __future__ import annotations

import ctypes
import math
from ctypes import c_char_p, c_int, c_uint8, c_uint16, c_uint32, c_void_p

import numpy as np

from .platform import SDL_AudioSpec, SDL_INIT_AUDIO, _load

SR = 22050
AUDIO_S16LSB = 0x8010


class Audio:
    def __init__(self):
        self.ok = False
        self.dev = 0
        self.sdl = None
        self.time = 0.0
        self.motor_phase = 0.0
        self.oar_phase = 0.0
        self.shots: list[tuple[np.ndarray, int]] = []
        self._water = self._make_water()
        self._water_at = 0
        self._wind = self._noise_bed(5, 0.11)
        self._wind_at = 0
        self._crickets = self._make_crickets()
        self._cricket_at = 0
        self._bird_at = 4.0
        self._frog_at = 2.5
        self._hour = 12.0
        self._rain = 0.0
        self._sailing = False
        self._motorized = True
        self._rowing = False
        try:
            self.sdl = _load("libSDL2-2.0.so.0")
            s = self.sdl
            s.SDL_Init.argtypes = [c_uint32]
            s.SDL_Init.restype = c_int
            s.SDL_GetError.restype = c_char_p
            s.SDL_OpenAudioDevice.argtypes = [
                c_char_p, c_int, ctypes.POINTER(SDL_AudioSpec),
                ctypes.POINTER(SDL_AudioSpec), c_int,
            ]
            s.SDL_OpenAudioDevice.restype = c_uint32
            s.SDL_PauseAudioDevice.argtypes = [c_uint32, c_int]
            s.SDL_QueueAudio.argtypes = [c_uint32, c_void_p, c_uint32]
            s.SDL_QueueAudio.restype = c_int
            s.SDL_GetQueuedAudioSize.argtypes = [c_uint32]
            s.SDL_GetQueuedAudioSize.restype = c_uint32
            s.SDL_ClearQueuedAudio.argtypes = [c_uint32]
            s.SDL_CloseAudioDevice.argtypes = [c_uint32]
            s.SDL_Init(SDL_INIT_AUDIO)
            want = SDL_AudioSpec()
            want.freq = SR
            want.format = AUDIO_S16LSB
            want.channels = 2
            want.samples = 1024
            want.callback = None
            want.userdata = None
            have = SDL_AudioSpec()
            dev = s.SDL_OpenAudioDevice(None, 0, ctypes.byref(want), ctypes.byref(have), 0)
            if not dev:
                return
            self.dev = dev
            self.ok = True
            s.SDL_PauseAudioDevice(dev, 0)
        except Exception:
            self.ok = False

    def _make_water(self) -> np.ndarray:
        rng = np.random.default_rng(3)
        n = SR * 2
        noise = rng.uniform(-1, 1, n).astype(np.float32)
        # A couple of one-pole lows so it laps instead of hissing.
        out = np.empty_like(noise)
        acc = 0.0
        for i, v in enumerate(noise):
            acc += (float(v) - acc) * 0.02
            out[i] = acc
        out *= 0.35 / (np.max(np.abs(out)) + 1e-6)
        # Slow swell.
        t = np.arange(n, dtype=np.float32) / SR
        out *= 0.65 + 0.35 * np.sin(2 * np.pi * 0.18 * t)
        return out.astype(np.float32)

    def _noise_bed(self, seed: int, pole: float) -> np.ndarray:
        rng = np.random.default_rng(seed)
        n = SR * 2
        noise = rng.uniform(-1, 1, n).astype(np.float32)
        low = np.empty_like(noise)
        acc = 0.0
        for i, v in enumerate(noise):
            acc += (float(v) - acc) * pole
            low[i] = acc
        slow = np.empty_like(noise)
        acc = 0.0
        for i, v in enumerate(low):
            acc += (float(v) - acc) * 0.02
            slow[i] = acc
        bed = low - slow
        bed *= 0.5 / (np.max(np.abs(bed)) + 1e-6)
        return bed.astype(np.float32)

    def _make_crickets(self) -> np.ndarray:
        n = SR * 3
        buf = np.zeros(n, np.float32)
        rng = np.random.default_rng(11)
        t0 = 0.18
        while t0 < 2.9:
            start = int(t0 * SR)
            length = int(0.055 * SR)
            t = np.arange(length, dtype=np.float32) / SR
            chirp = np.sin(2 * np.pi * 4550 * t) * (0.45 + 0.55 * np.sin(2 * np.pi * 48 * t))
            chirp *= np.exp(-t * 22)
            end = min(n, start + length)
            buf[start:end] += chirp[: end - start]
            t0 += 0.28 + float(rng.random()) * 0.55
        buf *= 0.9 / (np.max(np.abs(buf)) + 1e-6)
        return buf.astype(np.float32)

    def blip(self, kind: str):
        if not self.ok:
            return
        self.shots.append((self._tone(kind), 0))

    def _cue(self, kind: str):
        # Ambience waits its turn. A burst of frogs must not bury a bite.
        if len(self.shots) >= 4:
            return
        self.shots.append((self._tone(kind), 0))

    def _tone(self, kind: str) -> np.ndarray:
        if kind == "bite":
            n = int(SR * 0.32)
            t = np.arange(n, dtype=np.float32) / SR
            rng = np.random.default_rng(7)
            splash = rng.uniform(-1, 1, n).astype(np.float32)
            acc = 0.0
            for i, v in enumerate(splash):
                acc += (float(v) - acc) * 0.42
                splash[i] = acc
            splash *= np.exp(-t * 26)
            pluck = np.sin(2 * np.pi * (690 - 420 * t) * t) * np.exp(-t * 6.2)
            wave = splash * 0.9 + pluck * 0.75
            gain = 0.42
        elif kind == "loon":
            n = int(SR * 0.72)
            t = np.arange(n, dtype=np.float32) / SR
            trem = 0.62 + 0.38 * np.sin(2 * np.pi * 6.2 * t)
            first = (t < 0.24) * np.exp(-np.clip(t - 0.02, 0, None) * 3.4)
            second = (t >= 0.30) * (t < 0.70) * np.exp(-np.clip(t - 0.32, 0, None) * 2.6)
            wave = np.sin(2 * np.pi * (540 - 35 * t) * t) * first
            wave += np.sin(2 * np.pi * (410 - 22 * t) * t) * second
            wave *= trem
            gain = 0.20
        elif kind == "gull":
            n = int(SR * 0.46)
            t = np.arange(n, dtype=np.float32) / SR
            cry = np.sin(2 * np.pi * (940 - 180 * t) * t) * np.exp(-t * 3.2) * (t < 0.28)
            cry += np.sin(2 * np.pi * (760 - 140 * t) * t) * np.exp(-np.clip(t - 0.18, 0, None) * 3.6) * (t >= 0.16)
            wave = cry
            gain = 0.16
        elif kind == "frog":
            n = int(SR * 0.22)
            t = np.arange(n, dtype=np.float32) / SR
            wave = np.sin(2 * np.pi * 188 * t) * np.exp(-t * 12)
            wave += np.sin(2 * np.pi * 92 * t) * np.exp(-t * 36) * 0.55
            gain = 0.22
        elif kind == "error":
            n = int(SR * 0.12)
            t = np.arange(n, dtype=np.float32) / SR
            wave = np.sin(2 * np.pi * 140 * t) * np.exp(-t * 18)
            gain = 0.35
        elif kind == "splash":
            n = int(SR * 0.12)
            t = np.arange(n, dtype=np.float32) / SR
            rng = np.random.default_rng(int(self.time * 1000) & 0xFFFF or 1)
            wave = rng.uniform(-1, 1, n).astype(np.float32) * np.exp(-t * 10)
            gain = 0.35
        elif kind == "sell":
            n = int(SR * 0.12)
            t = np.arange(n, dtype=np.float32) / SR
            wave = np.sin(2 * np.pi * 660 * t) * (t < 0.06) + np.sin(2 * np.pi * 880 * t) * (t >= 0.06)
            wave *= np.exp(-t * 18)
            gain = 0.35
        elif kind == "bot":
            n = int(SR * 0.16)
            t = np.arange(n, dtype=np.float32) / SR
            wave = np.sin(2 * np.pi * 880 * t) * (t < 0.05) + np.sin(2 * np.pi * 1320 * t) * (t >= 0.07)
            wave *= np.exp(-t * 10)
            gain = 0.35
        else:
            n = int(SR * 0.12)
            t = np.arange(n, dtype=np.float32) / SR
            wave = np.sin(2 * np.pi * 740 * t) * np.exp(-t * 18)
            gain = 0.35
        return (wave * gain * 32767).astype(np.int16)

    def _span(self, base: float, spread: float) -> float:
        h = math.sin(self.time * 12.9898 + self._bird_at) * 43758.5453
        return base + spread * (h - math.floor(h))

    def _schedule(self):
        hour = self._hour
        rain = self._rain
        edge = (5.3 <= hour <= 8.3) or (17.5 <= hour <= 20.9)
        day = 8.3 < hour < 17.5
        night = hour < 5.1 or hour > 20.6
        if self.time >= self._bird_at:
            if edge and rain < 0.75:
                self._cue("loon")
                self._bird_at = self.time + self._span(18.0, 16.0)
            elif day and rain < 0.9:
                self._cue("gull")
                self._bird_at = self.time + self._span(24.0, 20.0)
            else:
                self._bird_at = self.time + 6.0
        if night and rain < 0.8 and self.time >= self._frog_at:
            self._cue("frog")
            self._frog_at = self.time + self._span(6.0, 7.0)

    def update(self, dt: float, throttle: float, speed: float, muted: bool,
               *, hour: float = 12.0, rain: float = 0.0, sailing: bool = False,
               motorized: bool = True, rowing: bool = False):
        # hour, rain, and sailing stay keyword-only. The window smoke test
        # still calls this with the four positional arguments.
        if not self.ok:
            return
        self.time += max(0.0, float(dt))
        self._hour = float(hour)
        self._rain = max(0.0, float(rain))
        self._sailing = bool(sailing)
        self._motorized = bool(motorized)
        self._rowing = bool(rowing)
        if muted:
            self.shots.clear()
            self.sdl.SDL_PauseAudioDevice(self.dev, 1)
            return
        self._schedule()
        self.sdl.SDL_PauseAudioDevice(self.dev, 0)
        queued = self.sdl.SDL_GetQueuedAudioSize(self.dev)
        # stereo s16 -> 4 bytes a frame. Keep about 80ms ahead.
        if queued > SR * 4 * 0.08:
            return
        self._queue(self._mix(1024, throttle, speed))

    def _slice(self, loop: np.ndarray, at: int, frames: int) -> tuple[np.ndarray, int]:
        n = len(loop)
        at %= n
        if at + frames <= n:
            return loop[at:at + frames], at + frames
        head = n - at
        return np.concatenate((loop[at:], loop[: frames - head])), frames - head

    def _mix(self, frames: int, throttle: float, speed: float) -> np.ndarray:
        water, self._water_at = self._slice(self._water, self._water_at, frames)
        drive = max(abs(float(throttle)), min(1.0, abs(float(speed)) / 3.0))
        freq = 52.0 + drive * 78.0
        idx = np.arange(frames, dtype=np.float32)
        phase = self.motor_phase + idx * (freq / SR)
        self.motor_phase = float(phase[-1] + freq / SR) % 1.0
        if self._motorized:
            motor = np.sin(2 * np.pi * phase) * (0.04 + 0.10 * drive)
            motor += np.sin(2 * np.pi * phase * 2.0) * (0.02 * drive)
        elif self._rowing and drive > 0.01:
            cadence = self.oar_phase + idx * (1.65 / SR)
            self.oar_phase = float(cadence[-1] + 1.65 / SR) % 1.0
            stroke = np.maximum(0.0, np.sin(2 * np.pi * cadence)) ** 5
            motor = np.sin(2 * np.pi * cadence * 8.0) * (0.035 * drive) * stroke
        else:
            motor = np.zeros_like(water)
        mix = water * 0.22 + motor
        # One-shots stay centered. Wind and crickets sit a little wider.
        alive = []
        for samples, cursor in self.shots:
            take = min(frames, len(samples) - cursor)
            if take <= 0:
                continue
            mix[:take] += samples[cursor:cursor + take].astype(np.float32) / 32767.0
            cursor += take
            if cursor < len(samples):
                alive.append((samples, cursor))
        self.shots = alive
        wind, self._wind_at = self._slice(self._wind, self._wind_at, frames)
        gust = 0.028 + 0.12 * self._rain + (0.075 if self._sailing else 0.0) + 0.05 * drive
        pan = 0.22 * math.sin(self.time * 0.31)
        left = mix + wind * gust * (1.0 - pan)
        right = mix + wind * gust * (1.0 + pan)
        if self._hour < 5.1 or self._hour > 20.6:
            bugs, self._cricket_at = self._slice(self._crickets, self._cricket_at, frames)
            level = 0.055 * (1.0 - min(1.0, self._rain) * 0.65)
            left = left + bugs * level * 0.85
            right = right + bugs * level * 1.15
        stereo = np.empty(frames * 2, np.int16)
        stereo[0::2] = (np.clip(left, -1.0, 1.0) * 32767).astype(np.int16)
        stereo[1::2] = (np.clip(right, -1.0, 1.0) * 32767).astype(np.int16)
        return stereo

    def _queue(self, stereo: np.ndarray):
        data = np.ascontiguousarray(stereo)
        self.sdl.SDL_QueueAudio(self.dev, data.ctypes.data_as(c_void_p), data.nbytes)

    def close(self):
        if self.ok and self.dev:
            self.sdl.SDL_CloseAudioDevice(self.dev)
            self.dev = 0
            self.ok = False
