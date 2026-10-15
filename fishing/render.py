"""Bounded 16:9 renderer, with a CPU fallback for machines without OpenGL."""

from __future__ import annotations

import sys

VIEW_W = 960
VIEW_H = 540


class Renderer:
    def __new__(cls, world, width=VIEW_W, height=VIEW_H, *, software=False,context=None):
        if not software:
            try:
                from .glrender import LakeRenderer
                return LakeRenderer(world, width, height,context=context)
            except (ImportError, RuntimeError) as exc:
                print(f"Graphics unavailable ({exc}); using the CPU renderer.", file=sys.stderr)
        from .software import SoftwareRenderer
        scale = min(1.0, 480 / width, 270 / height)
        return SoftwareRenderer(world, max(160, int(width * scale)), max(90, int(height * scale)))
