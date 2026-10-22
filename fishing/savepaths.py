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

from .gamepad import default_key_bindings


SAVE_FILENAME = "save.json"
LEGACY_SAVE = Path("saves") / "briar.json"
SDL_ORGANIZATION = "TrotLineSim"
SDL_APPLICATION = "TrotlinePurridise"
V2_REWARD_KINDS = ("story", "legendary_record", "book_stage_up")
BOOK_STAGES = ((10, "mastered"), (5, "verified"), (3, "bait_known"),
               (1, "identified"), (0, "rumor"))
_LOAD_ERRORS = (ValueError, KeyError, TypeError, OverflowError,
                IndexError, AttributeError)


class UnsupportedSaveVersionError(ValueError):
    """Raised when this build sees a save written by a newer build."""

    def __init__(self, saved_version: int, current_version: int):
        self.saved_version = saved_version
        self.current_version = current_version
        super().__init__(
            f"Save version {saved_version} is newer than this game supports "
            f"(version {current_version}); update the game before loading it."
        )


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


def _preserve_rejected_save(save_path: Path) -> Path:
    """Keep rejected active-save bytes before a backup replaces the file."""
    raw = save_path.read_bytes()
    instant = datetime.now(timezone.utc)
    timestamp = instant.strftime("%Y%m%dT%H%M%S%fZ")
    destination = save_path.with_name(f"save.rejected.{timestamp}.json")
    while destination.exists():
        instant += timedelta(microseconds=1)
        timestamp = instant.strftime("%Y%m%dT%H%M%S%fZ")
        destination = save_path.with_name(f"save.rejected.{timestamp}.json")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=save_path.parent,
                                         prefix=".save-rejected-", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if destination.read_bytes() != raw:
            raise OSError("rejected save copy did not match the original")
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
                     "reduced_motion": False,
                     "key_bindings": default_key_bindings()},
        # Quest claims remain in narrative_v1.reward_claims, the existing
        # authority. This ledger covers the three reward kinds introduced with v2.
        "reward_claims": {"story": [], "legendary_record": [],
                          "book_stage_up": []},
    }


def merge_v2_defaults(state, saved_v2: object) -> dict:
    if saved_v2 is None:
        saved_v2 = {}
    if not isinstance(saved_v2, dict):
        # The legacy envelope is still usable if only its v2 extension is
        # malformed. Preserve all legacy progress and start v2 from defaults.
        saved_v2 = {}
    defaults = default_v2(state)
    return _normalize_known_v2(defaults, saved_v2, "v2")


def _valid_leaf(value, default, path: str) -> bool:
    if path == "v2.buff":
        return value is None or isinstance(value, dict)
    if path == "v2.needs.last_prompt_real_s":
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    if default is None:
        return True
    if type(default) is bool:
        return type(value) is bool
    if type(default) is int:
        return type(value) is int
    if type(default) is float:
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    return isinstance(value, type(default))


def _normalize_known_v2(default, saved, path: str):
    """Default malformed known fields while retaining unknown JSON fields."""
    if isinstance(default, dict):
        if not isinstance(saved, dict):
            return deepcopy(default)
        normalized = deepcopy(saved)
        for key, child_default in default.items():
            if key in saved:
                normalized[key] = _normalize_known_v2(
                    child_default, saved[key], f"{path}.{key}")
            else:
                normalized[key] = deepcopy(child_default)
        return normalized
    if isinstance(default, list):
        return deepcopy(saved) if isinstance(saved, list) else deepcopy(default)
    return deepcopy(saved) if _valid_leaf(saved, default, path) else deepcopy(default)


def load_game_save(save_path: str | Path, state_type: Type,
                   world_factory: Callable[[str], object],
                   legacy_path: str | Path | None = None):
    """Load, migrate, or recover a save; return ``(world, state, has_save)``."""
    target = Path(save_path)
    active_existed = target.is_file()
    candidates = save_candidates(target, legacy_path)
    for source in candidates:
        try:
            source_text = source.read_text(encoding="utf-8")
        except OSError:
            if is_backup_path(source, target):
                continue
            raise
        except UnicodeDecodeError:
            # Invalid text makes this candidate corrupt, just like malformed
            # JSON. Keep checking backups so a readable older save can load.
            continue

        try:
            raw = json.loads(source_text)
            if not isinstance(raw, dict):
                raise ValueError("save root must be an object")
            version = raw.get("version")
            current_version = getattr(state_type, "SAVE_VERSION", 2)
            if type(version) is int and version > current_version:
                raise UnsupportedSaveVersionError(version, current_version)
            lake_id = raw.get("lake_id", "briar")
            if not isinstance(lake_id, str):
                raise ValueError("saved lake id must be text")
            world = world_factory(lake_id)
            state = state_type.load(source, world)
        except UnsupportedSaveVersionError:
            raise
        except OSError:
            if is_backup_path(source, target):
                continue
            raise
        except _LOAD_ERRORS:
            continue

        from_backup = is_backup_path(source, target)
        is_v1 = version == 1
        is_other_source = source.resolve() != target.resolve()
        if active_existed and is_other_source:
            _preserve_rejected_save(target)
        if is_v1:
            if not from_backup:
                _write_backup(source, target)
            state.save(target, update_stamp=False)
        elif is_other_source:
            state.save(target)
        if from_backup or (active_existed and is_other_source):
            state.toast("Your save was restored from a backup.")
        return world, state, True

    world = world_factory("briar")
    state = state_type.new(world)
    if candidates:
        if active_existed:
            _preserve_rejected_save(target)
            state.toast("The saved game could not be restored. A copy was kept for recovery.")
        else:
            state.toast("The saved game could not be restored. Your files are still available in the save folder.")
    return world, state, False
