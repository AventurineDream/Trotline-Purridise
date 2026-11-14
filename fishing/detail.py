"""Detail tiers: how much memory the presentation may spend on this machine.

The game is built to a 3 GB hard cap with a 2.6 GB peak target (docs/v1/06 §7).
Baked textures, render targets, audio beds and UI caches all size themselves
from the one `Detail` chosen at startup, so the cap is honoured in one place
and weaker machines step down instead of swapping.

Constraints: a tier is chosen once per process, before the first renderer is
built; nothing here may import the renderer, SDL or NumPy. Code that never
calls `configure()` (unit tests, library use) gets `DEFAULT`, not Auto, so
frames do not depend on how much memory the test machine has free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MIB = 1024 * 1024
GIB = 1024 * MIB

# Free memory a tier needs beyond its own budget before Auto will pick it, so
# the desktop and its page cache keep room and the game never drives swapping.
AUTO_HEADROOM = 1.3

ENV_OVERRIDE = "TROTLINE_DETAIL"


@dataclass(frozen=True)
class Detail:
    """One presentation tier. Sizes are texels unless a unit is named.

    Attributes:
        name: Tier id accepted by --detail and the TROTLINE_DETAIL override.
        budget_bytes: Intended peak for process RSS plus GPU memory.
        hdr: Float scene targets and a bloom chain. False (CPU fallback's GL
            cousin, Mesa software GL, tight memory) clamps highlights at 1.0;
            every tier otherwise runs the same shaders at its own texture sizes.
        atlas_scale: Foliage/prop atlas texels per base texel (base 160x256).
        foliage_variants: Distinct sprites per tree species.
        terrain_texels: Edge of the baked ground colour and normal maps.
        wave_texels: Edge of one frame of the looping water normal volume.
        wave_frames: Frames in that loop.
        sky_texels: Width of the baked star/cloud panorama (height is half).
        shadow_texels: Edge of the baked canopy/dock shadow map.
        particles: Particle budget in thousands of seeds; per-system instance counts
            scale as (particles / 256) ** 0.6 from the standard tier.
        audio_rate: Mixer sample rate in Hz.
        ambience_seconds: Length of each pre-mixed ambience bed in seconds.
        ui_layer_cache_bytes: Cap in bytes for cached chart images and title washes.
        text_cache_bytes: Cap in bytes for the rendered-text cache.
        render_scale: Internal 3D resolution as a fraction of the window; UI stays native-size.
    """

    name: str
    budget_bytes: int
    hdr: bool
    atlas_scale: int
    foliage_variants: int
    terrain_texels: int
    wave_texels: int
    wave_frames: int
    sky_texels: int
    shadow_texels: int
    particles: int
    audio_rate: int
    ambience_seconds: int
    ui_layer_cache_bytes: int
    text_cache_bytes: int
    render_scale: float = 1.0


TIERS: dict[str, Detail] = {
    tier.name: tier for tier in (
        Detail("low", 600 * MIB, False, 1, 3, 1024, 128, 16, 1024, 512, 64,
               22050, 0, 32 * MIB, 8 * MIB, render_scale=0.55),
        Detail("standard", 1200 * MIB, True, 2, 4, 2048, 256, 32, 2048, 1024, 256,
               44100, 30, 96 * MIB, 16 * MIB, render_scale=0.60),
        Detail("high", 1900 * MIB, True, 3, 6, 4096, 384, 48, 4096, 2048, 512,
               44100, 60, 192 * MIB, 32 * MIB, render_scale=0.90),
        Detail("ultra", 2600 * MIB, True, 4, 8, 8192, 512, 64, 8192, 4096, 768,
               44100, 80, 256 * MIB, 64 * MIB, render_scale=1.0),
    )
}
ORDER = ("low", "standard", "high", "ultra")
# Unconfigured processes get a fixed tier so tests render the same everywhere.
DEFAULT = "standard"

_current: Detail | None = None


def mem_available_bytes() -> int | None:
    """Memory the kernel says is available without swapping, or None off Linux."""
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def select(*, software: bool = False, available_bytes: int | None = None,
           override: str | None = None) -> Detail:
    """Pick the tier for this run without storing it.

    Args:
        software: True for the CPU renderer or Mesa software GL; forces "low".
        available_bytes: Memory available now; None means unknown and selects
            "standard", which fits every machine the game supports.
        override: A tier name or "auto"/None. Unknown names fall back to Auto.

    Returns:
        The richest tier whose budget, with headroom, fits available memory.
    """
    if software:
        return TIERS["low"]
    if override in TIERS:
        return TIERS[override]
    if available_bytes is None:
        return TIERS["standard"]
    for name in reversed(ORDER):
        if available_bytes >= TIERS[name].budget_bytes * AUTO_HEADROOM:
            return TIERS[name]
    return TIERS["low"]


def configure(*, software: bool = False, override: str | None = None) -> Detail:
    """Choose and remember this process's tier.

    The TROTLINE_DETAIL environment variable wins over `override`, so a
    headless capture can pin a tier without touching a save's settings.

    Side effects:
        Replaces the tier returned by `current()`; renderers built afterwards
        size themselves from it.
    """
    global _current
    chosen = os.environ.get(ENV_OVERRIDE) or override
    _current = select(software=software, available_bytes=mem_available_bytes(), override=chosen)
    return _current


def current() -> Detail:
    """The tier in force: the configured one, else TROTLINE_DETAIL, else `DEFAULT`."""
    if _current is not None:
        return _current
    return TIERS.get(os.environ.get(ENV_OVERRIDE, ""), TIERS[DEFAULT])


def render_dimensions(width: int, height: int, *, software: bool = False,
                     tier: Detail | None = None) -> tuple[int, int]:
    """Return the offscreen 3D target size while preserving native-size UI.

    Args:
        width: Window width in pixels.
        height: Window height in pixels.
        software: Keep the requested size; the software renderer applies its own cap.
        tier: Optional explicit presentation tier; defaults to the configured tier.
    Returns:
        Internal 3D render width and height in pixels.

    Side effects:
        None.

    Raises:
        ZeroDivisionError: If GPU dimensions include zero.
    """
    if software:
        return width, height
    chosen = tier or current()
    scale = min(chosen.render_scale, 1440 / width, 810 / height)
    return max(320, int(width * scale)), max(180, int(height * scale))
