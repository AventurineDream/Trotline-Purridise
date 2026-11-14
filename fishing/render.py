"""Bounded 16:9 renderer, with a CPU fallback for machines without OpenGL."""

from __future__ import annotations

import sys

VIEW_W = 960
VIEW_H = 540


class Renderer:
    """Factory for a lake renderer and a bounded CPU fallback.

    Args:
        world: Authored or generated lake to render.
        width: Internal scene-target width in pixels.
        height: Internal scene-target height in pixels.
        software: Skip OpenGL and use the CPU renderer.
        context: Optional current OpenGL context.
        output_size: Optional final frame size in pixels; GPU rendering upscales
            on-GPU, while software backends retain their existing cap.
    Returns:
        A renderer-compatible backend with `render` and `close`.
    Side effects:
        Allocates renderer resources; OpenGL context ownership follows `context`.
    """

    def __new__(cls, world, width=VIEW_W, height=VIEW_H, *, software=False,
                context=None, output_size=None):
        if not software:
            try:
                from .glrender import LakeRenderer
                return LakeRenderer(world, width, height, context=context, output_size=output_size)
            except (ImportError, RuntimeError) as exc:
                print(f"Graphics unavailable ({exc}); using the CPU renderer.", file=sys.stderr)
        from .software import SoftwareRenderer
        scale = min(1.0, 480 / width, 270 / height)
        return SoftwareRenderer(world, max(160, int(width * scale)), max(90, int(height * scale)))
