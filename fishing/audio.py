"""The lake's voice: a procedural stereo mixer on SDL's audio queue.

How it fits: `game.run` builds one `Audio()`, calls `blip(kind)` for sound cues and
`update(...)` once per frame with the scene (hour, lake, rain, propulsion, volumes). This
module picks levels, crossfades and cue timing; `fishing.audiosynth` synthesises the
beds and cues. Captions are produced elsewhere from the same cue kind names.

Design:
- Long, seamless stereo beds (water lapping on the hull, wash, lake wind, rain, insects,
  frogs, birds) are pre-rendered by worker processes at the tier's rate and length
  (`detail.current().audio_rate` / `.ambience_seconds`) and looped from one sample clock.
  Beds are built when first needed, so startup builds only what the opening scene plays.
- Every layer's gain moves linearly in *power* toward its target, so two layers trading
  places (dawn birds for night insects, one lake for the next, light rain for heavy)
  form an equal-power crossfade with no dip, step or click. Gains ramp per sample
  inside each block.
- Propulsion (outboard harmonics, electric hum, oar strokes, sail flutter) is
  synthesised live from smoothed controls.
- Four saved buses (master, music, ambience, sfx); a bite ducks the ambience; a soft
  limiter with a -1 dBFS ceiling means the queue never clips.
- `render_offline` drives the very same `update`/`_mix` path into memory, so tests and
  WAV dumps hear exactly what plays.

Constraints: the device is optional (silent if it will not open); a frame never waits
for synthesis (unready beds stay silent and fade in); pre-rendered audio stays under
250 MiB on "ultra"; the mixer never produces a sample beyond -1 dBFS.
"""

from __future__ import annotations

import atexit
import ctypes
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time as _time
from concurrent.futures import Future, ThreadPoolExecutor
from ctypes import c_char_p, c_int, c_uint32, c_void_p
from pathlib import Path

import numpy as np

from . import audiosynth as synth
from . import detail
from .botchimes import CHIMES, SAMPLE_RATE as CHIME_RATE, synthesize as synthesize_chime
from .platform import SDL_AudioSpec, SDL_INIT_AUDIO, _load

AUDIO_S16LSB = 0x8010
F32 = np.float32
MIB = 1024 * 1024
BED_CAP_BYTES = 250 * MIB
AHEAD_SECONDS = 0.08          # audio kept queued ahead of the device
MAX_BLOCKS_PER_UPDATE = 4     # catch-up bound after a long frame
SHORT_LOOP_SECONDS = 8.0      # "low" tier (ambience_seconds == 0): short loops as before
EVENT_LOOP_SECONDS = 30.0     # birds/frogs/insects are never shorter than this
CEILING = 10 ** (-1.0 / 20)   # limiter ceiling, -1 dBFS
LIMIT_KNEE = 0.6
LIMIT_TARGET = 10 ** (-4.0 / 20)
DUCK_GAIN = 10 ** (-7.0 / 20)  # ambience under a bite
PRIORITY_CUES = ("bite",)
EVENT_BEDS = ("insects", "birds", "frogs")
WORKERS = 3                   # beds synthesised at once
PACKAGE_ROOT = str(Path(__file__).resolve().parents[1])
# Child interpreter entry: put the package on sys.path, then run one synthesis job.
WORKER_BOOT = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
               "from fishing.audiosynth import _worker; _worker(sys.argv[1:])")


def _scratch_directory() -> str:
    """Choose writable /dev/shm to avoid worker-sample disk I/O; otherwise use system temp."""
    return "/dev/shm" if os.access("/dev/shm", os.W_OK) else tempfile.gettempdir()

# Bed levels in dBFS RMS at full weight, per lake. Tuned against the loudness table in
# fishing/test_audio.py (ambience sits between -35 and -24 dBFS).
LAP_DB = {"briar": -32.0, "cedar": -30.0, "flathead": -33.0, "crater": -34.0, "nebula": -35.0}
WIND_DB = {"briar": -37.0, "cedar": -31.0, "flathead": -33.0, "crater": -37.0, "nebula": -46.0}
INSECT_DB = {"briar": -34.0, "cedar": -36.0, "crater": -38.0}
FROG_DB = {"briar": -33.0, "cedar": -36.0, "crater": -39.0}
BIRD_DB = {"briar": -31.0, "cedar": -33.0, "flathead": -34.0, "crater": -37.0, "nebula": -35.0}
BIRD_DAY = {"briar": 0.3, "cedar": 0.6, "flathead": 0.35, "crater": 0.2, "nebula": 0.4}
RAIN_LIGHT_DB, RAIN_HEAVY_DB = -32.0, -28.5
WASH_DB = -29.0
PAD_DB = -42.0
# Seconds a layer takes to go from silence to full power (or back).
SCENE_FADE = 2.5
MOTION_FADE = 0.35

# Nebula pad: (Hz, amplitude, pan). Detuned pairs drift against each other, so the pad
# shimmers and its ears stay decorrelated. Each pair is unequal (about 5:3) so the beat
# swells by ~12 dB instead of cancelling to a dead gap when the ears are summed to mono.
PAD_PARTIALS = ((110.0, 0.5, -0.4), (110.21, 0.3, 0.4), (164.81, 0.32, 0.5), (165.07, 0.2, -0.5),
                (220.1, 0.22, 0.0), (329.6, 0.1, -0.6), (659.3, 0.035, 0.7), (1318.5, 0.018, -0.7))

# Outboard partials: firing harmonics plus quiet half orders (a four-stroke's putter).
ENGINE_ORDERS = np.arange(0.5, 16.5, 0.5)

_STORES: dict[tuple[int, int, int], "_BedStore"] = {}
_STORES_LOCK = threading.Lock()


def _db(value: float) -> float:
    return 10.0 ** (value / 20.0)


def _smooth(s: float) -> float:
    s = min(1.0, max(0.0, s))
    return 0.5 - 0.5 * math.cos(math.pi * s)


def _daywindow(hour: float, up0: float, up1: float, down0: float, down1: float) -> float:
    """Power weight 0..1 on the 24 h circle: rises up0→up1, holds, falls down0→down1."""
    x = (hour - up0) % 24.0
    u1, d0, d1 = (up1 - up0) % 24.0, (down0 - up0) % 24.0, (down1 - up0) % 24.0
    if x < u1:
        return _smooth(x / u1)
    if x < d0:
        return 1.0
    if x < d1:
        return 1.0 - _smooth((x - d0) / (d1 - d0))
    return 0.0


class _BedStore:
    """Builds beds and the cue bank in worker processes and keeps the ones in use.

    Why processes: bed synthesis runs Python loops over thousands of events. On threads
    those loops hold the GIL for whole switch intervals, and measured frames stalled
    5-14 ms while beds built. A worker process (`python -m fishing.audiosynth`) writes
    raw samples to scratch space (/dev/shm when writable, system temp otherwise); completed
    outputs are copied into ordinary arrays, then their maps are closed before unlinking.
    Frozen builds or a failed spawn fall back to threads.

    One store per (rate, loop lengths) is shared by every Audio in the process, so tests
    and offline renders reuse the beds the game built. Lake-specific beds are kept for the
    two most recently requested lakes (the current one and the one fading out), which
    bounds memory at 5 shared + 6 lake beds. All methods run on the game thread.
    """

    def __init__(self, rate: int, noise_frames: int, event_frames: int):
        self.rate = rate
        self.noise_frames = noise_frames
        self.event_frames = event_frames
        self.build_seconds: dict[str, float] = {}
        self._beds: dict[str, synth.Bed] = {}
        self._running: dict[str, tuple[subprocess.Popen, str]] = {}
        self._threads: dict[str, Future] = {}
        self._waiting: list[str] = []
        self._lakes: list[str] = []
        self._cues: dict[tuple[str, int], np.ndarray] = {}
        self._strokes: list[np.ndarray] = []
        self._cue_job: tuple[subprocess.Popen, str] | Future | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._spawn_ok = bool(sys.executable) and not getattr(sys, "frozen", False)
        self._serial = itertools.count()
        atexit.register(self.shutdown)

    def frames(self, key: str) -> int:
        """Loop length in frames of bed `key`."""
        return self.event_frames if key.partition(":")[0] in EVENT_BEDS else self.noise_frames

    # ------------------------------------------------------------ jobs

    def _scratch(self, label: str) -> str:
        name = f"trotline-audio-{os.getpid()}-{next(self._serial)}-{label.replace(':', '-')}.raw"
        return os.path.join(_scratch_directory(), name)

    def _spawn(self, args: list[str], path: str) -> subprocess.Popen | None:
        if not self._spawn_ok:
            return None
        try:
            # The inherited environment is passed untouched: copying and re-encoding it
            # for every spawn showed up in profiles of the game thread.
            return subprocess.Popen([sys.executable, "-c", WORKER_BOOT, PACKAGE_ROOT, *args, path],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except OSError:
            self._spawn_ok = False
            return None

    def _threads_pool(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="trotline-audio")
        return self._pool

    def _build_here(self, key: str) -> synth.Bed:
        start = _time.perf_counter()
        bed = synth.build_bed(key, self.rate, self.frames(key))
        self.build_seconds[key] = _time.perf_counter() - start
        return bed

    def _start(self, key: str) -> None:
        path = self._scratch(key)
        proc = self._spawn(["bed", key, str(self.rate), str(self.frames(key))], path)
        if proc is not None:
            self._running[key] = (proc, path)
        else:
            self._threads[key] = self._threads_pool().submit(self._build_here, key)

    @staticmethod
    def _result(proc: subprocess.Popen) -> dict | None:
        """The worker's JSON line once it has exited cleanly, else None."""
        out = proc.stdout.read() if proc.stdout else b""
        if proc.stdout:
            proc.stdout.close()
        try:
            return json.loads(out) if proc.returncode == 0 else None
        except ValueError:
            return None

    def _finish(self, key: str, proc: subprocess.Popen, path: str) -> None:
        info = self._result(proc)
        try:
            if info is None:
                raise OSError(f"audio worker for {key} failed")
            data = _copy_worker_output(path, np.int16, (2, self.frames(key)))
            self._beds[key] = synth.Bed(data, float(info["unit"]))
            self.build_seconds[key] = float(info["seconds"])
        except (OSError, ValueError, KeyError):
            _unlink(path)
            self._threads[key] = self._threads_pool().submit(self._build_here, key)

    def poll(self) -> None:
        """Collect finished workers and start queued ones (never blocks)."""
        for key, (proc, path) in list(self._running.items()):
            if proc.poll() is not None:
                del self._running[key]
                self._finish(key, proc, path)
        for key, future in list(self._threads.items()):
            if future.done():
                del self._threads[key]
                self._beds[key] = future.result()
        while self._waiting and len(self._running) + len(self._threads) < WORKERS:
            self._start(self._waiting.pop(0))

    def _forget(self, key: str) -> None:
        self._beds.pop(key, None)
        if key in self._waiting:
            self._waiting.remove(key)
        job = self._running.pop(key, None)
        if job:
            job[0].kill()
            job[0].wait()
            if job[0].stdout:
                job[0].stdout.close()
            _unlink(job[1])
        future = self._threads.pop(key, None)
        if future:
            future.cancel()

    # ------------------------------------------------------------ beds

    def request(self, key: str) -> None:
        """Queue `key` for building unless it is built or on its way."""
        if key in self._beds or key in self._running or key in self._threads or key in self._waiting:
            return
        lake = key.partition(":")[2]
        if lake:
            if lake in self._lakes:
                self._lakes.remove(lake)
            self._lakes.append(lake)
            for old in self._lakes[:-2]:
                for name in [k for k in (*self._beds, *self._running, *self._threads, *self._waiting)
                             if k.endswith(":" + old)]:
                    self._forget(name)
            self._lakes = self._lakes[-2:]
        self._waiting.append(key)
        self.poll()

    def get(self, key: str, wait: bool) -> synth.Bed | None:
        """The bed if ready, else None; with `wait`, build it first (blocking)."""
        bed = self._beds.get(key)
        if bed is not None:
            return bed
        self.request(key)
        self.poll()
        while wait and key not in self._beds:
            if key in self._waiting:
                self._waiting.remove(key)
                self._start(key)
            if key in self._running:
                proc, path = self._running.pop(key)
                proc.wait()
                self._finish(key, proc, path)
            if key in self._threads:
                self._beds[key] = self._threads.pop(key).result()
        return self._beds.get(key)

    # ------------------------------------------------------------ cues

    def prefetch_cues(self) -> None:
        """Start building every cue and oar stroke so blip() never has to synthesise."""
        if self._cue_job is not None or self._cues:
            return
        path = self._scratch("cues")
        proc = self._spawn(["cues", str(self.rate)], path)
        self._cue_job = (proc, path) if proc else self._threads_pool().submit(self._cues_here)

    def _cues_here(self) -> None:
        start = _time.perf_counter()
        for kind in synth.CUE_PEAK_DB:
            for variant in range(synth.CUE_VARIANTS.get(kind, 1)):
                self._cues.setdefault((kind, variant), synth.build_cue(kind, self.rate, variant))
        self._strokes = [synth.stroke(self.rate, v) for v in range(synth.STROKE_VARIANTS)]
        self.build_seconds["cues"] = _time.perf_counter() - start

    def _poll_cues(self) -> None:
        job = self._cue_job
        if not isinstance(job, tuple) or job[0].poll() is None:
            return
        proc, path = job
        self._cue_job = None
        info = self._result(proc)
        try:
            if info is None:
                raise OSError("audio cue worker failed")
            bank = _copy_worker_output(path, F32).reshape(-1, 2)
            strokes = []
            for kind, variant, first, frames in info["index"]:
                sound = bank[first:first + frames]
                if kind == "stroke":
                    strokes.append(sound)
                else:
                    self._cues[(kind, variant)] = sound
            self._strokes = strokes
            self.build_seconds["cues"] = float(info["seconds"])
        except (OSError, ValueError, KeyError):
            _unlink(path)
            self._cue_job = self._threads_pool().submit(self._cues_here)

    def cue(self, kind: str, variant: int) -> np.ndarray:
        """Finished (n, 2) float32 cue; synthesised on the spot if the bank is not ready."""
        self._poll_cues()
        sound = self._cues.get((kind, variant))
        if sound is None:
            if kind in synth.CUE_PEAK_DB:
                sound = synth.build_cue(kind, self.rate, variant)
            else:
                # V1-38 motifs and story/ambient calls have authored waveforms, not generic cue presets.
                sound = _soundscape_cue(kind, self.rate)
            self._cues[(kind, variant)] = sound
        return sound

    def strokes(self) -> list[np.ndarray]:
        """The oar-stroke variants; synthesised on the spot if the bank is not ready."""
        self._poll_cues()
        if len(self._strokes) < synth.STROKE_VARIANTS:
            self._strokes = [synth.stroke(self.rate, v) for v in range(synth.STROKE_VARIANTS)]
        return self._strokes

    def tick(self) -> None:
        """Once per mixed block: collect finished workers and start queued ones."""
        if self._running or self._threads or self._waiting:
            self.poll()
        if self._cue_job is not None:
            self._poll_cues()

    def nbytes(self) -> int:
        """Bytes of samples held: built beds, cues and strokes."""
        return (sum(bed.nbytes for bed in self._beds.values())
                + sum(c.nbytes for c in self._cues.values()) + sum(s.nbytes for s in self._strokes))

    def shutdown(self) -> None:
        """Stop workers and delete their scratch files (registered with atexit)."""
        for key in list(self._running):
            self._forget(key)
        if isinstance(self._cue_job, tuple):
            proc, path = self._cue_job
            proc.kill()
            proc.wait()
            if proc.stdout:
                proc.stdout.close()
            _unlink(path)
            self._cue_job = None
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)


def _copy_worker_output(path: str, dtype, shape: tuple[int, ...] | None = None) -> np.ndarray:
    """Detach worker samples before closing and unlinking their backing file.

    Args:
        path: Completed worker scratch file.
        dtype: Numpy sample type written by the worker.
        shape: Optional bed shape; cues remain flat until their index is applied.

    Returns:
        An ordinary ndarray that remains valid after the scratch file is removed.
    """
    mapped = None
    try:
        mapped = np.memmap(path, dtype, mode="r", shape=shape)
        samples = np.array(mapped, copy=True)
        return samples
    finally:
        try:
            if mapped is not None:
                mapped._mmap.close()
        finally:
            _unlink(path)


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except (FileNotFoundError, PermissionError):
        pass


def _store_for(tier: detail.Detail) -> _BedStore:
    rate = tier.audio_rate
    seconds = tier.ambience_seconds or SHORT_LOOP_SECONDS
    key = (rate, synth.loop_length(seconds, rate),
           synth.loop_length(max(seconds, EVENT_LOOP_SECONDS), rate))
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            store = _STORES[key] = _BedStore(*key)
        return store


def _soundscape_cue(kind: str, rate: int) -> np.ndarray:
    """Resample an authored mono soundscape cue to stereo float32 at the mixer rate."""
    from . import soundscape

    source = soundscape.tone(kind).astype(F32) / F32(32767.0)
    if rate != soundscape.SR:
        count = max(1, int(round(len(source) * rate / soundscape.SR)))
        positions = np.arange(count, dtype=F32) * F32(soundscape.SR / rate)
        left = np.floor(positions).astype(np.intp)
        right = np.minimum(left + 1, len(source) - 1)
        fraction = positions - left
        source = source[left] + (source[right] - source[left]) * fraction
    stereo = np.empty((len(source), 2), dtype=F32)
    stereo[:, 0] = source
    stereo[:, 1] = source
    stereo.setflags(write=False)
    return stereo


class Audio:
    """The game's sound: ambience beds, propulsion and cues mixed onto SDL's queue.

    Args:
        open_device: Open SDL audio for interactive play; False enables device-less rendering.
        device: Optional explicit override for ``open_device``.
        tier: Detail tier name to size for; None uses ``detail.current()``.

    The mixer is silent (but harmless) when the SDL device will not open.
    """

    def __init__(self, open_device: bool = True, *, device: bool | None = None,
                 tier: str | None = None):
        if device is None:
            device = bool(open_device)
        self._setup(detail.TIERS[tier] if tier in detail.TIERS else detail.current(),
                    wait=not device)
        # Offline twins use _setup's virtual default; an interactive mixer must open SDL first.
        self._virtual = not device
        # Do not synthesize beds or cues for a mixer that can neither play nor render.
        if device:
            self._open_device()
        if self.ok or self._virtual:
            self._store.request("lap")
            self._store.request("wash")
            self._store.prefetch_cues()

    def _setup(self, tier: detail.Detail, *, wait: bool, store: _BedStore | None = None) -> None:
        self.ok = False
        self.dev = 0
        self.sdl = None
        self.tier = tier
        self.rate = tier.audio_rate
        self.block = 1024 if self.rate >= 44100 else 512
        self._store = store or _store_for(tier)
        self._wait_beds = wait
        self._virtual = True
        self._virtual_frames = 0.0
        self._sink: list[np.ndarray] | None = None
        self.time = 0.0
        self.shots: list[tuple[np.ndarray, int, str]] = []
        self._volumes = {"master": 1.0, "music": 1.0, "ambience": 1.0, "sfx": 1.0}
        self._clock = 0
        self._gains: dict[str, float] = {}
        # Loudest target each layer has had: fades move a fixed share of that power per
        # second, so a fade-out ends on time instead of decaying forever.
        self._ref: dict[str, float] = {}
        self._primed = False
        self._start_ramp = False
        self._bird_at = 4.0
        self._frog_at = 2.5
        self._hour = 12.0
        self._rain = 0.0
        self._lake_id = "briar"
        self._scene_lake: str | None = None
        self._lake_wait = 0.0
        self._sailing = False
        self._motorized = True
        self._electric = False
        self._rowing = False
        self._extra_at = 12.0
        self._finale = False
        self._played: list[str] = []
        self._throttle = 0.0
        self._speed = 0.0
        self._f0 = 0.0
        self._engine_gain = 0.0
        self._hum_gain = 0.0
        self._engine_phase = 0.0
        self._hum_phase = 0.0
        self._oar_phase = 0.85
        self._stroke_next = 0
        self._pad_phase = np.zeros(len(PAD_PARTIALS), np.float64)
        self._duck = 1.0
        self._duck_frames = 0
        self._pad_gain = 0.0
        self._limit = 1.0
        self._variant: dict[str, int] = {}

    def _open_device(self) -> None:
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
            want.freq = self.rate
            want.format = AUDIO_S16LSB
            want.channels = 2
            want.samples = self.block
            want.callback = None
            want.userdata = None
            have = SDL_AudioSpec()
            dev = s.SDL_OpenAudioDevice(None, 0, ctypes.byref(want), ctypes.byref(have), 0)
            if not dev:
                return
            self.dev = dev
            self.ok = True
            self._virtual = False
            self._start_ramp = True
            s.SDL_PauseAudioDevice(dev, 0)
        except Exception:
            self.ok = False

    # ------------------------------------------------------------ public API

    def memory_bytes(self) -> int:
        """Bytes of pre-rendered audio (beds, cues, oar strokes) this process holds."""
        return self._store.nbytes()

    def blip(self, kind: str, *, bus=None):
        """Queue the cue `kind` on its captioned mixer bus.

        Args:
            kind: Cue identifier understood by the audio synthesizer.
            bus: Optional explicit mixer bus; otherwise use the soundscape's mapping.

        Side effects: priority cues duck ambience while they play.
        """
        if not (self.ok or self._virtual):
            return
        from .soundscape import bus as bus_of
        bus = bus or bus_of(kind)
        if bus == "music":
            # One motif at a time: a new one replaces any still playing (V1-38).
            self.shots = [shot for shot in self.shots if shot[2] != "music"]
        sound = self._voice(kind)
        self.shots.append((sound, 0, bus if bus in self._volumes else "sfx"))
        if kind in PRIORITY_CUES:
            self._duck_frames = max(self._duck_frames, len(sound))

    def _cue(self, kind: str):
        # Ambience waits its turn. A burst of frogs must not bury a bite.
        if len(self.shots) >= 4:
            return
        self.shots.append((self._voice(kind), 0, "ambience"))
        self._played.append(kind)

    def take_played(self) -> list[str]:
        """The ambient calls scheduled since the last look, for their captions (V1-38)."""
        played, self._played = self._played, []
        return played

    def reset_schedule(self, lake_id: str, hour: float, *, finale: bool = False, rain: float = 0.0):
        """Start a lake's calls afresh at this hour (the benchmark's coverage check)."""
        self._lake_id, self._hour, self._finale, self._rain = lake_id, float(hour), bool(finale), float(rain)
        self._bird_at = self._frog_at = self._extra_at = self.time
        self.shots.clear()

    def buffer_bytes(self) -> int:
        """Resident synthesis buffers: the beds and whatever one-shots are queued."""
        beds = self._store.nbytes()
        return beds + sum(samples.nbytes for samples, _cursor, _bus in self.shots)

    def set_volumes(self, volumes=None, **levels):
        """Set the four saved mixer buses, clamping malformed values safely."""
        if isinstance(volumes, dict):
            levels = {**volumes, **levels}
        for name in self._volumes:
            value = levels.get(name, self._volumes[name])
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                value = self._volumes[name]
            if not math.isfinite(value):
                value = self._volumes[name]
            self._volumes[name] = max(0.0, min(1.0, value))

    def _tone(self, kind: str, variant: int = 0) -> np.ndarray:
        """Return one cue as PCM at the mixer's sample rate.

        Shell chimes use `botchimes.synthesize` (mono int16). With the normal
        store, synth-bank kinds are (n, 2) float32 cues from `build_cue`; other
        V1-38 kinds use authored `soundscape.tone` waveforms resampled by
        `_soundscape_cue`. A bare diagnostic Audio object without a store falls
        back to `build_cue`.
        """
        rate = getattr(self, "rate", CHIME_RATE)
        if kind in CHIMES:
            return synthesize_chime(kind, rate) if rate != CHIME_RATE else synthesize_chime(kind)
        store = getattr(self, "_store", None)
        return store.cue(kind, variant) if store else synth.build_cue(kind, rate, variant)

    def _voice(self, kind: str) -> np.ndarray:
        count = synth.CUE_VARIANTS.get(kind, 1)
        variant = self._variant.get(kind, 0)
        self._variant[kind] = (variant + 1) % count
        return self._tone(kind, variant)

    def _span(self, base: float, spread: float) -> float:
        h = math.sin(self.time * 12.9898 + self._bird_at) * 43758.5453
        return base + spread * (h - math.floor(h))

    def _schedule(self):
        hour = self._hour
        lake = getattr(self, "_lake_id", "briar")
        alpine = lake == "flathead"
        rain = self._rain
        night = hour < 5.1 or hour > 20.6
        extra_at = getattr(self, "_extra_at", 12.0)
        if lake == "nebula":
            # No birds or frogs beyond the reflection: star twinkles, a soft choir, and on
            # nights after the finale the whale's song (V1-38).
            if self.time >= self._bird_at:
                self._cue("twinkle")
                self._bird_at = self.time + self._span(9.0, 14.0)
            if self.time >= self._frog_at:
                self._cue("choir")
                self._frog_at = self.time + self._span(30.0, 15.0)
            if getattr(self, "_finale", False) and night and self.time >= extra_at:
                self._cue("whale_song")
                self._extra_at = self.time + self._span(70.0, 30.0)
            return
        if lake == "crater":
            # A deep hush: springs bubbling, and ravens by day (V1-38).
            if self.time >= self._frog_at:
                self._cue("spring")
                self._frog_at = self.time + self._span(6.0, 5.0)
            if self.time >= self._bird_at:
                if 7.0 <= hour <= 19.0 and rain < 0.8:
                    self._cue("raven")
                    self._bird_at = self.time + self._span(25.0, 15.0)
                else:
                    self._bird_at = self.time + 6.0
            return
        if alpine:
            # Wind through the larches, and ice ticking at the shore on cold hours (V1-38).
            if self.time >= extra_at:
                self._cue("larch_wind")
                self._extra_at = self.time + self._span(30.0, 20.0)
            if (hour < 9.0 or hour > 20.0) and self.time >= self._frog_at:
                self._cue("ice_tick")
                self._frog_at = self.time + self._span(8.0, 8.0)
        edge = (5.3 <= hour <= 8.3) or (17.5 <= hour <= 20.9)
        day = 8.3 < hour < 17.5
        night = hour < 5.1 or hour > 20.6
        if self.time >= self._bird_at:
            if (edge or (alpine and day)) and rain < 0.75:
                self._cue("loon")
                self._bird_at = self.time + self._span(18.0, 16.0)
            elif day and rain < 0.9:
                self._cue("gull")
                self._bird_at = self.time + self._span(24.0, 20.0)
            else:
                self._bird_at = self.time + 6.0
        if not alpine and night and rain < 0.8 and self.time >= self._frog_at:
            self._cue("frog")
            self._frog_at = self.time + self._span(6.0, 7.0)

    def update(self, dt: float, throttle: float, speed: float, muted: bool,
               *, hour: float = 12.0, rain: float = 0.0, sailing: bool = False,
               motorized: bool = True, rowing: bool = False, volumes=None, lake_id="briar",
               finale: bool = False, electric: bool = False):
        """Advance the soundscape by `dt` seconds and keep ~80 ms queued ahead.

        Args:
            dt: Frame time in seconds.
            throttle: -1..1 lever; speed: boat speed in m/s (drives wash and engine).
            muted: Pauses the device and drops queued cues (no queue growth).
            hour: Local hour 0..24; lake_id: lake whose wind/birds/frogs play.
            rain: 0..1 rain amount; sailing/motorized/rowing/electric: propulsion.
            volumes: Optional saved bus levels, as for `set_volumes`.
            finale: Enable the post-finale Star-Whale ambience cue.

        Side effects: queues at most MAX_BLOCKS_PER_UPDATE blocks onto the device.
        """
        # hour, rain, and sailing stay keyword-only. The window smoke test
        # still calls this with the four positional arguments.
        self._lake_id = lake_id
        self._finale = bool(finale)
        if volumes is not None:
            self.set_volumes(volumes)
        if muted:
            # Mute drops every bus and its pending captions; nothing waits to play after.
            self.shots.clear()
            self._played.clear()
        if not (self.ok or self._virtual):
            return
        dt = max(0.0, float(dt))
        self.time += dt
        self._hour = float(hour)
        self._rain = max(0.0, float(rain))
        self._sailing = bool(sailing)
        self._motorized = bool(motorized)
        self._electric = bool(electric)
        self._rowing = bool(rowing)
        if self._virtual:
            self._virtual_frames = max(0.0, self._virtual_frames - dt * self.rate)
        if muted:
            self.shots.clear()
            if self.ok:
                self.sdl.SDL_PauseAudioDevice(self.dev, 1)
            return
        self._schedule()
        if self.ok:
            self.sdl.SDL_PauseAudioDevice(self.dev, 0)
        for _ in range(MAX_BLOCKS_PER_UPDATE):
            if self._queued_frames() >= AHEAD_SECONDS * self.rate:
                break
            self._queue(self._mix(self.block, throttle, speed, wait=self._wait_beds))

    def prime(self, *, hour: float = 12.0, lake_id: str = "briar", rain: float = 0.0,
              throttle: float = 0.0, speed: float = 0.0, sailing: bool = False,
              motorized: bool = False, rowing: bool = False, electric: bool = False) -> None:
        """Set the scene and snap every gain to it at once, without fades.

        For offline renders and tests that want steady state from the first sample.
        Builds (and waits for) the beds the scene needs.
        """
        self._lake_id, self._scene_lake = lake_id, self._known(lake_id)
        self._hour, self._rain = float(hour), max(0.0, float(rain))
        self._sailing, self._motorized, self._rowing = bool(sailing), bool(motorized), bool(rowing)
        self._electric = bool(electric)
        self._throttle, self._speed = float(throttle), float(speed)
        self._snap(wait=True)

    def render_offline(self, seconds: float, *, hour: float = 12.0, lake_id: str = "briar",
                       rain: float = 0.0, throttle: float = 0.0, speed: float = 0.0,
                       sailing: bool = False, motorized: bool = False, rowing: bool = False,
                       electric: bool = False, muted: bool = False, volumes=None,
                       cues=(), script=(), fps: float = 60.0) -> np.ndarray:
        """Render a scripted scenario through the real update/mix path, no device needed.

        Args:
            seconds: Length to render.
            hour, lake_id, rain, throttle, speed, sailing, motorized, rowing, electric,
                muted, volumes: The starting scene, as `update` takes it.
            cues: (time_s, kind) or (time_s, kind, "ambience") pairs; ambience cues go
                through the same priority rule as the scheduled wildlife.
            script: (time_s, {param: value}) scene changes, e.g. (10, {"rain": 1.0}).
            fps: Frame rate of the simulated game loop calling `update`.

        Returns:
            int16 array (frames, 2) at the mixer rate. Uses a fresh mixer state that
            shares this instance's beds; this instance and its device are untouched.
        """
        twin = Audio.__new__(Audio)
        twin._setup(self.tier, wait=True, store=self._store)
        scene = dict(hour=hour, lake_id=lake_id, rain=rain, throttle=throttle, speed=speed,
                     sailing=sailing, motorized=motorized, rowing=rowing, electric=electric)
        twin.prime(**scene)
        if volumes is not None:
            twin.set_volumes(volumes)
        twin._sink = []
        pending = sorted(cues, key=lambda c: c[0])
        changes = sorted(script, key=lambda c: c[0])
        total = int(round(seconds * self.rate))
        dt = 1.0 / fps
        t = 0.0
        while twin._clock < total and t < seconds + 1.0:
            while changes and changes[0][0] <= t:
                change = dict(changes.pop(0)[1])
                muted = bool(change.pop("muted", muted))
                scene.update(change)
            while pending and pending[0][0] <= t:
                cue = pending.pop(0)
                if len(cue) > 2 and cue[2] == "ambience":
                    twin._cue(cue[1])
                else:
                    twin.blip(cue[1])
            twin.update(dt, scene["throttle"], scene["speed"], muted,
                        hour=scene["hour"], lake_id=scene["lake_id"], rain=scene["rain"],
                        sailing=scene["sailing"], motorized=scene["motorized"],
                        rowing=scene["rowing"], electric=scene["electric"])
            t += dt
        pcm = np.concatenate(twin._sink) if twin._sink else np.zeros(0, np.int16)
        out = np.zeros((total, 2), np.int16)
        frames = min(total, len(pcm) // 2)
        out[:frames] = pcm[:frames * 2].reshape(-1, 2)
        return out

    def close(self):
        if self.ok and self.dev:
            self.sdl.SDL_CloseAudioDevice(self.dev)
            self.dev = 0
            self.ok = False

    # ------------------------------------------------------------ scene

    @staticmethod
    def _known(lake: str) -> str:
        return lake if lake in synth.LAKES else "briar"

    def _targets(self, lake: str | None = None) -> dict[str, tuple[str, float, float, str]]:
        """Layer name → (bed key, loop offset 0..1, target amplitude, bus) for `lake`
        (default: the lake the ambience is currently on)."""
        lake = lake or self._scene_lake or self._known(self._lake_id)
        hour = self._hour % 24.0
        rain = min(1.0, self._rain)
        speed = min(1.0, abs(float(self._speed)) / 3.0)
        drive = max(min(1.0, abs(float(self._throttle))), speed)
        out = {
            "lap": ("lap", 0.0, _db(LAP_DB[lake]) * (1.0 - 0.35 * speed), "ambience"),
            "wind:" + lake: ("wind:" + lake, 0.0,
                             _db(WIND_DB[lake] + 5.0 * rain + (3.0 if self._sailing else 0.0)),
                             "ambience"),
        }
        if rain > 0.0:
            out["rain_light"] = ("rain_light", 0.0, _db(RAIN_LIGHT_DB) * min(1.0, rain / 0.25) ** 0.5,
                                 "ambience")
        if rain > 0.3:
            out["rain_heavy"] = ("rain_heavy", 0.0, _db(RAIN_HEAVY_DB) * ((rain - 0.3) / 0.7) ** 0.5,
                                 "ambience")
        night = _daywindow(hour, 19.5, 21.0, 4.5, 6.0)
        if lake in INSECT_DB and night > 0:
            out["insects"] = ("insects", 0.0, _db(INSECT_DB[lake]) * math.sqrt(night) * (1 - 0.7 * rain),
                              "ambience")
        frogs = _daywindow(hour, 20.0, 21.5, 3.5, 5.0)
        if lake in FROG_DB and frogs > 0 and rain < 0.95:
            out["frogs:" + lake] = ("frogs:" + lake, 0.0,
                                    _db(FROG_DB[lake]) * math.sqrt(frogs) * (1 - 0.8 * rain), "ambience")
        if lake == "nebula":
            birds = 1.0 - (1.0 - BIRD_DAY[lake]) * _daywindow(hour, 6.0, 7.5, 18.5, 20.0)
        else:
            edges = max(_daywindow(hour, 4.8, 5.6, 7.6, 8.8), _daywindow(hour, 17.2, 18.0, 19.6, 20.8))
            daylight = _daywindow(hour, 5.6, 7.0, 18.5, 20.0)
            birds = max(edges, BIRD_DAY[lake] * daylight)
        if birds > 0:
            out["birds:" + lake] = ("birds:" + lake, 0.0,
                                    _db(BIRD_DB[lake]) * math.sqrt(birds) * (1 - 0.8 * rain), "ambience")
        if speed > 0.0:
            out["wash"] = ("wash", 0.0, _db(WASH_DB + (2.0 if self._sailing else 0.0)) * speed ** 0.8,
                           "ambience")
        if self._motorized:
            prop_db = (-50.0 + 10.0 * drive) if self._electric else (-44.0 + 12.0 * drive)
            out["prop"] = ("wash", 0.5, _db(prop_db) * (0.3 + 0.7 * drive), "sfx")
        if self._sailing:
            out["flutter"] = ("wash", 0.25, _db(-39.0) * (0.6 + 0.4 * (1.0 - speed)), "sfx")
        return out

    def _ready_lake(self, wait: bool) -> None:
        """Switch the ambience to the requested lake once its beds are built (or after
        4 s), so travel crossfades lake to lake instead of dipping through silence."""
        lake = self._known(self._lake_id)
        if self._scene_lake == lake:
            return
        if self._scene_lake is None or wait:
            self._scene_lake = lake
            return
        keys = {key for key, _, amp, _ in self._targets(lake).values() if amp > 0}
        ready = all(self._store.get(k, False) is not None for k in keys)
        self._lake_wait += self.block / self.rate
        if ready or self._lake_wait > 4.0:
            self._scene_lake = lake
            self._lake_wait = 0.0

    def _snap(self, wait: bool) -> None:
        self._ready_lake(wait)
        self._gains = {}
        targets = self._targets()
        # Ask for every bed before waiting on any, so the workers build them together.
        for key, _, amp, _ in targets.values():
            if amp > 0:
                self._store.request(key)
        for name, (key, _, amp, _) in targets.items():
            bed = self._store.get(key, wait) if amp > 0 else None
            self._gains[name] = amp if bed is not None else 0.0
        drive = self._drive()
        self._f0 = self._engine_f0(drive)
        self._engine_gain = self._engine_target(drive)
        self._hum_gain = self._hum_target(drive)
        self._pad_gain = _db(PAD_DB) if self._scene_lake == "nebula" else 0.0
        self._primed = True

    # ------------------------------------------------------------ propulsion

    def _drive(self) -> float:
        return max(min(1.0, abs(float(self._throttle))), min(1.0, abs(float(self._speed)) / 3.0))

    @staticmethod
    def _engine_f0(drive: float) -> float:
        # Firing frequency: a slow idle putter up to a steady cruising drone.
        return 30.0 + 58.0 * drive

    def _engine_target(self, drive: float) -> float:
        return _db(-37.0 + 11.0 * drive) if self._motorized and not self._electric else 0.0

    def _hum_target(self, drive: float) -> float:
        return _db(-46.0 + 8.0 * drive) if self._motorized and self._electric else 0.0

    def _engine(self, frames: int, dt: float) -> np.ndarray:
        """Outboard: a stable harmonic engine tone. RPM and level follow the throttle
        through one-pole smoothing and are ramped per sample, so nothing zippers."""
        drive = self._drive()
        g0, f_start = self._engine_gain, self._f0
        target = self._engine_target(drive)
        tau = 0.3 if target > g0 else 0.6
        g1 = g0 + (target - g0) * (1.0 - math.exp(-dt / tau))
        f_end = f_start + (self._engine_f0(drive) - f_start) * (1.0 - math.exp(-dt / 0.45))
        self._engine_gain, self._f0 = g1, f_end
        if g0 < 1e-6 and g1 < 1e-6:
            return np.zeros(frames, F32)
        t = (self._clock + np.arange(frames)) / self.rate
        freq = np.linspace(f_start, f_end, frames, endpoint=False)
        freq *= 1.0 + 0.004 * np.sin(2 * np.pi * 1.7 * t) + 0.003 * np.sin(2 * np.pi * 3.1 * t + 1.0)
        phase = self._engine_phase + np.cumsum(freq) * (2 * np.pi / self.rate)
        # Half orders give a four-stroke its uneven putter; keep phase in [0, 4*pi).
        self._engine_phase = float(phase[-1] % (4 * np.pi))
        f_mid = 0.5 * (f_start + f_end)
        orders = ENGINE_ORDERS[ENGINE_ORDERS * f_mid <= 3200.0]
        fk = orders * f_mid
        amps = orders ** -1.15 * (1.0 + 1.3 * np.exp(-0.5 * (np.log2(fk / 450.0) / 0.8) ** 2))
        amps /= 1.0 + (fk / 2200.0) ** 4
        amps[orders % 1 > 0] *= 0.18
        # One (orders x frames) sine table summed down the orders, instead of a loop per
        # order. Not `@`: a BLAS call may wake its own thread pool mid-frame.
        table = np.sin(np.outer(orders, phase).astype(F32))
        table *= (amps / amps.sum()).astype(F32)[:, None]
        out = table.sum(axis=0)
        return out * np.linspace(g0 * 2.2, g1 * 2.2, frames, endpoint=False, dtype=F32)

    def _hum(self, frames: int, dt: float) -> np.ndarray:
        """Electric trolling motor: a quiet hum with a faint whine."""
        drive = self._drive()
        g0 = self._hum_gain
        target = self._hum_target(drive)
        g1 = g0 + (target - g0) * (1.0 - math.exp(-dt / 0.3))
        self._hum_gain = g1
        if g0 < 1e-6 and g1 < 1e-6:
            return np.zeros(frames, F32)
        f = 92.0 + 46.0 * drive
        phase = self._hum_phase + np.arange(1, frames + 1) * (2 * np.pi * f / self.rate)
        self._hum_phase = float(phase[-1] % (2 * np.pi))
        out = (np.sin(phase) + 0.45 * np.sin(2 * phase) + 0.12 * np.sin(3 * phase)
               + 0.03 * np.sin(11 * phase)) / 1.6
        return (out * np.linspace(g0, g1, frames, endpoint=False) * 1.4).astype(F32)

    def _oars(self, frames: int) -> None:
        """Queue oar strokes on the rowing cadence (one every 1.7-2.6 s)."""
        if not self._rowing:
            self._oar_phase = 0.85
            return
        period = 2.6 - 0.9 * min(1.0, abs(float(self._throttle)))
        step = frames / (period * self.rate)
        before = self._oar_phase
        self._oar_phase += step
        if self._oar_phase >= 1.0:
            self._oar_phase -= 1.0
            offset = int((1.0 - before) / step * frames)
            strokes = self._store.strokes()
            self.shots.append((strokes[self._stroke_next % len(strokes)], -offset, "sfx"))
            self._stroke_next += 1

    def _flutter_am(self, frames: int) -> np.ndarray:
        t = (self._clock + np.arange(frames)) / self.rate
        wave = (np.sin(2 * np.pi * 7.3 * t) + 0.6 * np.sin(2 * np.pi * 11.9 * t + 1.0)
                + 0.4 * np.sin(2 * np.pi * 4.1 * t + 2.0)) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.11 * t))
        return (0.55 + 0.45 * np.tanh(1.5 * wave)).astype(F32)

    def _pad(self, frames: int, g0: float, g1: float) -> np.ndarray:
        """The Lagoon's faint shimmering pad, synthesised live (2, frames)."""
        idx = np.arange(1, frames + 1)
        out = np.zeros((2, frames), np.float64)
        t = (self._clock + np.arange(frames)) / self.rate
        swell = 0.75 + 0.25 * np.sin(2 * np.pi * 0.05 * t)
        for i, (f, amp, p) in enumerate(PAD_PARTIALS):
            phase = self._pad_phase[i] + idx * (2 * np.pi * f / self.rate)
            self._pad_phase[i] = phase[-1] % (2 * np.pi)
            shimmer = 1.0 if f < 600 else 0.6 + 0.4 * np.sin(2 * np.pi * (0.13 + 0.04 * i) * t + i)
            wave = amp * np.sin(phase) * shimmer
            left, right = synth.pan_gains(p)
            out[0] += left * wave
            out[1] += right * wave
        # Measured: the partials and swell sum to RMS 0.336, so this makes gain == RMS.
        out *= swell * np.linspace(g0, g1, frames, endpoint=False) * (1.0 / 0.336)
        return out.astype(F32)

    # ------------------------------------------------------------ mixing

    def _bed_chunk(self, bed: synth.Bed, offset: float, frames: int) -> np.ndarray:
        n = bed.data.shape[1]
        at = (self._clock + int(offset * n)) % n
        if at + frames <= n:
            return bed.data[:, at:at + frames]
        return np.concatenate((bed.data[:, at:], bed.data[:, :frames - (n - at)]), axis=1)

    def _mix(self, frames: int, throttle: float, speed: float, *, wait: bool = True) -> np.ndarray:
        """Mix one block: interleaved int16 stereo, frames*2 samples.

        `wait` builds missing beds first (offline, tests); live play passes False and
        missing beds stay silent until they are ready, then fade in.
        """
        self._throttle, self._speed = float(throttle), float(speed)
        self._store.tick()
        if not self._primed:
            self._snap(wait)
        else:
            self._ready_lake(wait)
        dt = frames / self.rate
        buses = {"ambience": np.zeros((2, frames), F32), "sfx": np.zeros((2, frames), F32),
                 "music": np.zeros((2, frames), F32)}
        targets = self._targets()
        gains = {}
        for name in sorted(set(targets) | set(self._gains)):
            key, offset, target, bus = targets.get(name, (None, 0.0, 0.0, "ambience"))
            if key is None:
                key = "wash" if name in ("prop", "flutter") else name
                bus = "sfx" if name in ("prop", "flutter") else "ambience"
                offset = {"prop": 0.5, "flutter": 0.25}.get(name, 0.0)
            g0 = self._gains.get(name, 0.0)
            bed = self._store.get(key, wait) if (target > 0 or g0 > 0) else None
            if bed is None:
                g1 = 0.0
            else:
                full = SCENE_FADE if name not in ("wash", "prop", "flutter") else MOTION_FADE
                ref = self._ref[name] = max(self._ref.get(name, 0.0), target, g0)
                p0, p1 = g0 * g0, target * target
                step = ref * ref * dt / full
                g1 = math.sqrt(max(0.0, p0 + max(-step, min(step, p1 - p0))))
            if g1 > 0 or (target > 0 and bed is None):
                gains[name] = g1
            if bed is None or (g0 == 0 and g1 == 0):
                continue
            ramp = np.linspace(g0 * bed.unit, g1 * bed.unit, frames, endpoint=False, dtype=F32)
            chunk = self._bed_chunk(bed, offset, frames) * ramp
            if name == "flutter":
                chunk *= self._flutter_am(frames)
            buses[bus] += chunk
        self._gains = gains
        pad0 = self._pad_gain
        pad_target = _db(PAD_DB) if self._scene_lake == "nebula" else 0.0
        step = _db(PAD_DB) ** 2 * dt / SCENE_FADE
        pad1 = math.sqrt(max(0.0, pad0 ** 2 + max(-step, min(step, pad_target ** 2 - pad0 ** 2))))
        self._pad_gain = pad1
        if pad0 > 0 or pad1 > 0:
            buses["ambience"] += self._pad(frames, pad0, pad1)
        motor = self._engine(frames, dt) + self._hum(frames, dt)
        buses["sfx"] += motor[None, :]
        self._oars(frames)
        alive = []
        for samples, cursor, bus in self.shots:
            start = max(0, -cursor)
            src = max(0, cursor)
            take = min(frames - start, len(samples) - src)
            if take > 0:
                seg = samples[src:src + take]
                seg = seg.astype(F32) * F32(1 / 32767) if seg.dtype == np.int16 else seg
                target = buses["music"] if bus == "music" else buses["ambience"] if bus == "ambience" \
                    else buses["sfx"]
                target[:, start:start + take] += seg.T if seg.ndim == 2 else seg[None, :]
            cursor += frames
            if cursor < len(samples):
                alive.append((samples, cursor, bus))
        self.shots = alive
        duck0 = self._duck
        want = DUCK_GAIN if self._duck_frames > 0 else 1.0
        tau = 0.03 if want < duck0 else 0.5
        duck1 = duck0 + (want - duck0) * (1.0 - math.exp(-dt / tau))
        self._duck = duck1
        self._duck_frames = max(0, self._duck_frames - frames)
        vol = self._volumes
        amb = buses["ambience"]
        amb *= np.linspace(duck0 * vol["ambience"], duck1 * vol["ambience"], frames,
                           endpoint=False, dtype=F32)
        mix = amb
        mix += buses["sfx"] * F32(vol["sfx"])
        mix += buses["music"] * F32(vol["music"])
        mix *= F32(vol["master"])
        mix = self._limit_block(mix, dt)
        if self._start_ramp:
            # The first block after the device opens fades in from silence.
            mix *= np.linspace(0.0, 1.0, frames, dtype=F32)
            self._start_ramp = False
        self._clock += frames
        out = np.empty((frames, 2), np.int16)
        out[:] = (mix * F32(32767)).T
        return out.reshape(-1)

    def _limit_block(self, mix: np.ndarray, dt: float) -> np.ndarray:
        """Soft limiter: a block-rate gain rider aiming at -4 dBFS peaks (instant attack
        ramped across the block, 0.4 s release), then a smooth knee that bends anything
        above 0.6 toward the -1 dBFS ceiling. Silence stays exactly silent."""
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        g0 = self._limit
        want = min(1.0, LIMIT_TARGET / peak) if peak > 0 else 1.0
        if want < g0:
            g1 = want
        else:
            g1 = min(want, g0 + (1.0 - g0) * (1.0 - math.exp(-dt / 0.4)))
        self._limit = g1
        if g0 < 1.0 or g1 < 1.0:
            mix *= np.linspace(g0, g1, mix.shape[1], endpoint=False, dtype=F32)
        if peak * max(g0, g1) > LIMIT_KNEE:
            mag = np.abs(mix)
            over = mag > LIMIT_KNEE
            span = CEILING - LIMIT_KNEE
            mix[over] = np.sign(mix[over]) * (LIMIT_KNEE + span * np.tanh((mag[over] - LIMIT_KNEE) / span))
        return mix

    def _queued_frames(self) -> float:
        if self._virtual:
            return self._virtual_frames
        return self.sdl.SDL_GetQueuedAudioSize(self.dev) / 4

    def _queue(self, stereo: np.ndarray):
        if self._virtual:
            self._virtual_frames += len(stereo) // 2
            if self._sink is not None:
                self._sink.append(stereo)
            return
        data = np.ascontiguousarray(stereo)
        self.sdl.SDL_QueueAudio(self.dev, data.ctypes.data_as(c_void_p), data.nbytes)
