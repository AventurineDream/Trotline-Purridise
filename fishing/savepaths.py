"""Platform save paths, v1 migration backups, and v2 save defaults."""

from __future__ import annotations

import ctypes
import ctypes.util
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Callable, Sequence, Type


SAVE_FILENAME = "save.json"
LEGACY_SAVE = Path("saves") / "briar.json"
SDL_ORGANIZATION = "TrotLineSim"
SDL_APPLICATION = "TrotlinePurridise"
V2_REWARD_KINDS = ("story", "legendary_record", "book_stage_up")
BOOK_STAGES = ((10, "mastered"), (5, "verified"), (3, "bait_known"),
               (1, "identified"), (0, "rumor"))
_LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError, OverflowError,
                IndexError, AttributeError)


def parse_save_option(argv: Sequence[str]) -> tuple[list[str], Path | None]:
    """Remove the optional ``--save PATH`` argument from application args."""
    args = list(argv)
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(args):
        if args[i] == "--save":
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise ValueError("--save requires a path")
            found.append((i, args[i + 1]))
            i += 2
            continue
        if args[i].startswith("--save="):
            found.append((i, args[i].split("=", 1)[1]))
        i += 1
    if len(found) > 1:
        raise ValueError("--save may only be specified once")
    if not found:
        return args, None
    index, value = found[0]
    if not value:
        raise ValueError("--save requires a path")
    if args[index] == "--save":
        del args[index:index + 2]
    else:
        del args[index]
    return args, Path(value).expanduser()


def _sdl_library():
    candidates = [ctypes.util.find_library("SDL2"), "libSDL2-2.0.so.0",
                  "SDL2.dll", "/Library/Frameworks/SDL2.framework/SDL2"]
    seen = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise RuntimeError("SDL2 is required to locate the platform save folder")


def sdl_pref_path() -> Path:
    """Return SDL's platform user-data directory for this game."""
    sdl = _sdl_library()
    sdl.SDL_GetPrefPath.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    sdl.SDL_GetPrefPath.restype = ctypes.c_void_p
    pointer = sdl.SDL_GetPrefPath(SDL_ORGANIZATION.encode(), SDL_APPLICATION.encode())
    if not pointer:
        message = "SDL_GetPrefPath failed"
        try:
            sdl.SDL_GetError.restype = ctypes.c_char_p
            detail = sdl.SDL_GetError()
            if detail:
                message += f": {detail.decode(errors='replace')}"
        except AttributeError:
            pass
        raise RuntimeError(message)
    try:
        return Path(ctypes.string_at(pointer).decode("utf-8"))
    finally:
        sdl.SDL_free.argtypes = [ctypes.c_void_p]
        sdl.SDL_free.restype = None
        sdl.SDL_free(pointer)


def resolve_save_path(override: str | Path | None = None) -> Path:
    """Choose the explicit save override or SDL's platform user-data path."""
    if override is not None:
        if not str(override).strip():
            raise ValueError("save path cannot be empty")
        path = Path(override).expanduser()
        return path
    return sdl_pref_path() / SAVE_FILENAME


def backup_directory(save_path: str | Path) -> Path:
    return Path(save_path).parent / "backup"


def backup_candidates(save_path: str | Path) -> list[Path]:
    directory = backup_directory(save_path)
    if not directory.is_dir():
        return []
    # Timestamp names sort in chronological order, including microseconds.
    return sorted(directory.glob("briar.v1.*.json"), key=lambda path: path.name,
                  reverse=True)


def is_backup_path(path: str | Path, save_path: str | Path) -> bool:
    return Path(path).parent == backup_directory(save_path)


def save_candidates(save_path: str | Path,
                    legacy_path: str | Path | None = None) -> list[Path]:
    """List the active save, newest backups, and optional install-era save."""
    target = Path(save_path)
    legacy = Path(legacy_path) if legacy_path is not None else None
    candidates: list[Path] = []
    if target.is_file():
        candidates.append(target)
        candidates.extend(backup_candidates(target))
        if legacy is not None and legacy.is_file():
            candidates.append(legacy)
    else:
        if legacy is not None and legacy.is_file():
            candidates.append(legacy)
        candidates.extend(backup_candidates(target))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        key = candidate.resolve()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _write_backup(source: Path, save_path: Path) -> Path:
    raw = source.read_bytes()
    for existing in backup_candidates(save_path):
        try:
            if existing.read_bytes() == raw:
                return existing
        except OSError:
            continue

    directory = backup_directory(save_path)
    directory.mkdir(parents=True, exist_ok=True)
    instant = datetime.now(timezone.utc)
    timestamp = instant.strftime("%Y%m%dT%H%M%S%fZ")
    destination = directory / f"briar.v1.{timestamp}.json"
    while destination.exists():
        instant += timedelta(microseconds=1)
        timestamp = instant.strftime("%Y%m%dT%H%M%S%fZ")
        destination = directory / f"briar.v1.{timestamp}.json"

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".briar-v1-",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if destination.read_bytes() != raw:
            raise OSError("v1 save backup did not match the original")
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _merge_defaults(default: dict, saved: dict) -> dict:
    """Fill missing v2 fields while preserving unknown fields at every depth."""
    merged = deepcopy(saved)
    for key, value in default.items():
        if key not in saved:
            merged[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(saved[key], dict):
            merged[key] = _merge_defaults(value, saved[key])
    return merged


def book_stage(count: int) -> str:
    try:
        count = max(0, int(count))
    except (TypeError, ValueError, OverflowError):
        count = 0
    return next(stage for threshold, stage in BOOK_STAGES if count >= threshold)


def _book_defaults(state) -> dict:
    species = {}
    for species_id, entry in state.journal.items():
        if not isinstance(entry, dict):
            continue
        try:
            count = max(0, int(entry.get("count", 0)))
        except (TypeError, ValueError, OverflowError):
            count = 0
        if count <= 0:
            continue
        found = []
        conditions = {key: entry.get(key) for key in ("zone", "bait", "band")}
        if all(isinstance(value, str) and value for value in conditions.values()):
            found.append(conditions)
        species[species_id] = {"found": found, "shiny": 0, "since_shiny": 3}
    return species


def default_v2(state=None) -> dict:
    """Build the guide's v2 defaults, seeded only from existing save data."""
    schedule_seed = 0
    journal_species = {}
    scenes_seen = []
    scene_states = {}
    if state is not None:
        schedule_seed = state.narrative.schedule_seed
        journal_species = _book_defaults(state)
        if journal_species:
            scenes_seen = ["prologue"]
            scene_states = {"prologue": "done"}

    return {
        "mode": "cozy",
        "profile": {
            "bot_name": f"Copper-{abs(int(schedule_seed)) % 1000:03d}",
            "shell": "tin", "shells": ["tin"], "tools": [],
            "collar": {"stage": "none", "knot": None, "visible": True},
        },
        "needs": {"awake_h": 0.0, "since_meal_h": 0.0, "rested_until": None,
                  "last_prompt_real_s": 0},
        "buff": None,
        "pantry": {"herbs": 0},
        "recipes": [], "dishes_known": [],
        "boat_extras": {},
        "book": {"species": journal_species, "tracked": None,
                 "title": "fishypedia", "dream_clue": None},
        "legendaries": {},
        "story": {"chapter": 0, "steps": {}, "scenes_seen": scenes_seen,
                  "pending_rewards": [], "scene_states": scene_states},
        "npcs": {"letters": [], "talk_days": {}},
        "keepsakes": [], "ripples_v2": [],
        "calendar": {"weather_windows": {}},
        "settings": {"text_size": 1, "haul_speed": "normal",
                     "reduced_motion": False},
        # Quest claims remain in narrative_v1.reward_claims, the existing
        # authority. This ledger covers the three reward kinds introduced with v2.
        "reward_claims": {"story": [], "legendary_record": [],
                          "book_stage_up": []},
    }


def merge_v2_defaults(state, saved_v2: object) -> dict:
    if saved_v2 is None:
        saved_v2 = {}
    if not isinstance(saved_v2, dict):
        raise ValueError("save v2 must be an object")
    defaults = default_v2(state)
    merged = _merge_defaults(defaults, saved_v2)
    _validate_v2(merged, defaults)
    return merged


def _validate_shape(value, default, path: str) -> None:
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise ValueError(f"save {path} must be an object")
        for key, child_default in default.items():
            if key in value:
                _validate_shape(value[key], child_default, f"{path}.{key}")
        return
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"save {path} must be a list")
        return
    if default is None:
        return
    if type(default) is bool:
        valid = type(value) is bool
    elif type(default) is int:
        valid = type(value) is int
    elif type(default) is float:
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
    else:
        valid = isinstance(value, type(default))
    if not valid:
        raise ValueError(f"save {path} has an invalid value")


def _validate_v2(v2: dict, defaults: dict) -> None:
    _validate_shape(v2, defaults, "v2")
    if v2.get("buff") is not None and not isinstance(v2.get("buff"), dict):
        raise ValueError("save v2.buff must be an object or null")
    story = v2["story"]
    if any(status not in ("pending", "done")
           for status in story["scene_states"].values()):
        raise ValueError("save v2 story scenes must be pending or done")
    claims = v2["reward_claims"]
    for kind in V2_REWARD_KINDS:
        if any(not isinstance(key, str) for key in claims[kind]):
            raise ValueError(f"save v2.reward_claims.{kind} keys must be text")


def load_game_save(save_path: str | Path, state_type: Type,
                   world_factory: Callable[[str], object],
                   legacy_path: str | Path | None = None):
    """Load, migrate, or recover a save; return ``(world, state, has_save)``."""
    target = Path(save_path)
    active_existed = target.is_file()
    candidates = save_candidates(target, legacy_path)
    for source in candidates:
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("save root must be an object")
            version = raw.get("version")
            lake_id = raw.get("lake_id", "briar")
            if not isinstance(lake_id, str):
                raise ValueError("saved lake id must be text")
            world = world_factory(lake_id)
            state = state_type.load(source, world)
            from_backup = is_backup_path(source, target)
            is_v1 = version == 1
            if is_v1:
                if not from_backup:
                    _write_backup(source, target)
                state.save(target, update_stamp=False)
            elif source.resolve() != target.resolve():
                state.save(target)
            if from_backup or (active_existed and source.resolve() != target.resolve()):
                state.toast("Your save was restored from a backup.")
            return world, state, True
        except _LOAD_ERRORS:
            continue

    world = world_factory("briar")
    state = state_type.new(world)
    if candidates:
        state.toast("The saved game could not be restored. Your files are still available in the save folder.")
    return world, state, False
