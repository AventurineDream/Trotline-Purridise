"""Named save directories beside the original save, shared by Session and its menus.

Each slot owns save.json and its backups. Allocation stays read-only so Devmode
can start mornings without creating directories; display names live in the save.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Slot:
    """One selectable save: filesystem slug, display name, file path and main-save flag.

    The default slot uses an empty slug; named slugs are directory names beneath
    slot_root. Constructing a descriptor neither reads nor writes the save.
    """

    slug: str
    name: str
    path: Path
    is_default: bool


def slot_root(save_path: str | Path) -> Path:
    """Return the slots directory beside the original save_path without creating it."""
    return Path(save_path).parent / "slots"


def slot_slug(name: str) -> str:
    """Return a lowercase, portable directory key of at most 40 characters for name.

    Separators and non-ASCII characters become hyphens; empty and Windows device
    names receive safe fallbacks. This pure conversion never produces a path.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].rstrip("-") or "slot"
    if slug in {"con", "prn", "aux", "nul"} or re.fullmatch(r"(?:com|lpt)[1-9]", slug):
        slug = "slot-" + slug
    return slug


def slot_display_name(path: Path) -> str:
    """Read path's slot_name, then Skipper name, else its slug (main file: stem).

    Missing, malformed and unreadable save metadata falls back without changing
    any files. Nested legacy metadata must be objects before names are read.
    """
    path = Path(path)
    fallback = path.parent.name if path.parent.parent.name == "slots" else path.stem
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    if not isinstance(raw, dict):
        return fallback
    name = raw.get("slot_name")
    if isinstance(name, str) and name.strip():
        return name
    v2 = raw.get("v2")
    skipper = v2.get("skipper") if isinstance(v2, dict) else None
    name = skipper.get("name") if isinstance(skipper, dict) else None
    return name if isinstance(name, str) and name.strip() else fallback


def list_slots(save_path: str | Path) -> list[Slot]:
    """Read the main save and named saves beside save_path in display-name order.

    The main save is always first, even when absent. Empty slot directories and
    symlinks are not selectable; listing never creates directories or save files.
    Filesystem errors other than a missing slots directory propagate to callers.
    """
    default = Path(save_path)
    root = slot_root(default)
    result = [Slot("", slot_display_name(default), default, True)]
    if not root.exists():
        return result
    named = []
    for directory in root.iterdir():
        path = directory / "save.json"
        if directory.is_dir() and not directory.is_symlink() and path.is_file() and not path.is_symlink():
            named.append(Slot(directory.name, slot_display_name(path), path, False))
    result.extend(sorted(named, key=lambda slot: (slot.name.casefold(), slot.slug)))
    return result


def _unique_slug(root: Path, name: str, excluding: str = "") -> tuple[str, int]:
    """Choose an unused case-insensitive directory key, excluding a renamed slot.

    Returns the slug and its numeric suffix (1 for the bare base, 2+ after
    collisions) so callers can mirror the suffix in the displayed name.
    """
    existing = {path.name.casefold() for path in root.iterdir()
                if path.name != excluding} if root.exists() else set()
    base = slot_slug(name)
    slug, suffix = base, 1
    while slug.casefold() in existing:
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug, suffix


def allocate_slot(save_path: str | Path, display_name: str) -> tuple[Path, str]:
    """Return an unused slot file beside save_path and its numbered display name.

    Existing directory keys collide case-insensitively, including empty slots;
    a collision appends the same index to the shown name ("Mochi", "Mochi 2").
    No path is reserved or created until the caller saves; I/O errors propagate.
    """
    root = slot_root(save_path)
    slug, suffix = _unique_slug(root, display_name)
    shown = display_name if suffix == 1 else f"{display_name} {suffix}"
    return root / slug / "save.json", shown


def stamp_slot_name(state, name: str) -> None:
    """Set state's round-tripped top-level slot_name to name; do not write a file."""
    state.unknown_save_fields["slot_name"] = name


def rename_slot(save_path: str | Path, old_slug: str, new_display: str,
                legacy_path: str | Path | None = None) -> tuple[str, Path] | None:
    """Rename old_slug beside the original save_path, preserving progress and backups.

    An empty old_slug identifies the main save: move it, its backup directory and
    the install-era legacy file (when ``legacy_path`` is given and exists) into a
    new named slot. The legacy copy lands in the slot's backup folder under a
    ``briar.v1.*`` name so startup cannot re-import the stale v1 as a new main
    save, and the bytes stay recoverable. Return the new slug and save path, or
    None if missing. Metadata is replaced atomically before moving, so a failed
    directory rename leaves the live save at its original path. Invalid JSON and
    I/O errors raise.
    """
    default = Path(save_path)
    root = slot_root(default)
    if old_slug and (old_slug in {".", ".."} or Path(old_slug).name != old_slug or "\\" in old_slug):
        return None
    source = root / old_slug / "save.json" if old_slug else default
    if not source.is_file() or source.is_symlink() or (old_slug and source.parent.is_symlink()):
        return None
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("save root must be an object")
    slug, _suffix = _unique_slug(root, new_display, excluding=old_slug)
    target = root / slug / "save.json"
    raw["slot_name"] = new_display
    temporary = source.with_suffix(".tmp")
    temporary.write_text(json.dumps(raw), encoding="utf-8")
    temporary.replace(source)
    if old_slug:
        if source.parent != target.parent:
            source.parent.rename(target.parent)
    else:
        target.parent.mkdir(parents=True)
        backup = default.parent / "backup"
        # Move backups first: if moving the save fails, restore their old location
        # so recovery still belongs to the file the Session is currently using.
        moved_backup = backup.is_dir()
        if moved_backup:
            backup.rename(target.parent / "backup")
        slot_backup = target.parent / "backup"
        try:
            source.rename(target)
        except OSError:
            if moved_backup:
                slot_backup.rename(backup)
            raise
        if legacy_path is not None:
            # Best effort: the save already moved, so a failed legacy move only
            # means the stale v1 could be imported again — never lose the file.
            legacy = Path(legacy_path)
            if legacy.is_file() and not legacy.is_symlink():
                try:
                    slot_backup.mkdir(parents=True, exist_ok=True)
                    instant = datetime.now(timezone.utc)
                    stamp = instant.strftime("%Y%m%dT%H%M%S%fZ")
                    legacy_target = slot_backup / f"briar.v1.{stamp}.json"
                    while legacy_target.exists():
                        instant += timedelta(microseconds=1)
                        stamp = instant.strftime("%Y%m%dT%H%M%S%fZ")
                        legacy_target = slot_backup / f"briar.v1.{stamp}.json"
                    legacy.rename(legacy_target)
                except OSError:
                    pass
    return slug, target
