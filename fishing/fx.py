"""Renderer effect layers: baked GPU resources that plug into `LakeRenderer`.

Each visual slice (sky, water, land, particles) is one `Fx` subclass that
bakes its textures when a lake loads, hands the renderer its uniforms every
frame, and frees everything when the lake changes. The renderer only knows
this interface, so a slice never edits the frame loop.

Constraints: an effect is deterministic for a given state (frames are compared
in tests), animates from `state.anim` only, and honours Reduced Motion.
"""

from __future__ import annotations

# Texture units reserved per slice (0-5 and 20-21 belong to the renderer itself).
SKY_UNITS = (6, 7, 8, 9)
WATER_UNITS = (10, 11, 12)
LAND_UNITS = (13, 14, 15)
FLORA_UNITS = (16, 17)
PARTICLE_UNITS = (18, 19)


def reduced_motion(state) -> bool:
    """True when the player's Reduced Motion setting asks animation to hold still."""
    v2 = getattr(state, "v2", None)
    settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
    return bool(settings.get("reduced_motion", False))


class Fx:
    """One effect layer owned by a `LakeRenderer`.

    Args:
        renderer: The owning renderer. Use `renderer.ctx` for GL objects,
            `renderer.own(obj)` so they are released with the lake,
            `renderer.program(vert, frag)` for shaders that include
            `common.glsl`, and `renderer.world` for the lake.
        detail: The `fishing.detail.Detail` tier that sizes baked resources.
    """

    def __init__(self, renderer, detail):
        self.renderer = renderer
        self.detail = detail

    def uniforms(self, state, light, cam) -> dict:
        """Uniform values by name for this frame.

        They are set on every program that declares the name, so samplers are
        given as their texture unit (an int from this slice's unit range).
        """
        return {}

    def bind(self) -> None:
        """Bind this layer's textures to its units; called once per frame."""

    def draw(self, state, light, cam, *, mirror: float, stage: str) -> None:
        """Draw extra geometry.

        Args:
            mirror: -1.0 in the planar reflection pass, 1.0 in the main pass.
            stage: "scene" after opaque scenery in either pass (depth test on),
                or "over" in the main pass after water, boat and wildlife.
        """

    def memory_bytes(self) -> int:
        """GPU bytes held, mipmaps included, for the memory report."""
        return 0
