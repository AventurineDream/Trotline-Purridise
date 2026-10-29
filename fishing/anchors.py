"""Fixed V3 story locations, distinct from fishing zones and player spawns.

Coordinates are the normative contract's X/Z game metres. Dock hosts use a
water interaction reference, not a boat occupying the player's docking lane.
"""

from dataclasses import dataclass
from types import MappingProxyType

from .boat import BOATS


@dataclass(frozen=True)
class Anchor:
    id: str
    zone_id: str
    name: str
    x: float
    z: float
    kind: str = "water"
    approach: tuple[float, float, float] | None = None  # player x, z, yaw

    @property
    def lake_id(self):
        return self.id.split(":", 1)[0]

    @property
    def position(self):
        return self.x, self.z

    @property
    def player_position(self):
        return self.approach if self.approach is not None else (self.x, self.z, 0.0)


# No random placement or nearest-zone-centre fallback: chart drift must be
# reported by validation, rather than silently relocating an established site.
_ANCHORS = (
    Anchor("briar:landing", "briar:landing", "Briar Landing", -435.789, 107.381,
           "dock", (-424.138, 104.510, 1.81238898038469)),
    Anchor("briar:cypress", "briar:cypress", "Cypress shore", 330.0, 20.0),
    Anchor("briar:flats", "briar:flats", "North flats", 10.0, 205.0),
    Anchor("briar:deep", "briar:deep", "Deep hole", 75.0, -25.0),
    Anchor("briar:lilies", "briar:lilies", "Lily cove", -175.0, -115.0),
    Anchor("briar:inlet", "briar:inlet", "Creek inlet", -210.0, 155.0),
    Anchor("cedar:docs_marina_dock", "cedar:open", "Doc's Lonely Star Marina",
           -186.451, -400.499, "dock", (-182.208, -396.256, 0.0)),
    Anchor("cedar:open", "cedar:open", "Cedar open water", 0.0, 0.0),
    Anchor("cedar:inlet", "cedar:inlet", "Creek channels", -423.772, 948.817),
    Anchor("cedar:flats", "cedar:flats", "Upper lake flats", -234.448, 509.948),
    Anchor("cedar:deep", "cedar:deep", "Southern basin", 330.854, -754.864),
    Anchor("cedar:lilies", "cedar:lilies", "Clear Creek coves", 632.171, -964.758),
    # Five metres off, bow toward the cove, so the longest hulls clear the launch.
    Anchor("cedar:trinidad_cove", "cedar:deep", "Trinidad Cove", 186.862, -855.722,
           "water", (184.362, -851.392, 2.6179938779914944)),
    Anchor("cedar:lonely_star_deep", "cedar:deep", "Lonely Star Deep", 330.854, -754.864),
)
ANCHORS = MappingProxyType({anchor.id: anchor for anchor in _ANCHORS})


def anchors_for_lake(lake_id):
    """Immutable location lookup for only the loaded lake; reject unknown lakes."""
    from .lakes import LAKES
    if lake_id not in LAKES:
        raise ValueError(f"Unknown anchor lake: {lake_id}")
    return MappingProxyType({key: anchor for key, anchor in ANCHORS.items()
                             if anchor.lake_id == lake_id})


def validate_anchors(world):
    """Fail explicitly if a chart rebuild invalidates a site or boat approach.

    Full-hull checks include draft, shore, rocks, stumps and dock barriers for
    every player boat. Route connectivity is exercised by test_anchors.
    """
    import math

    for anchor in world.anchors.values():
        expected_zone = anchor.zone_id.split(":", 1)[1]
        if world.zone_at(anchor.x, anchor.z) != expected_zone or not world.navigable(anchor.x, anchor.z):
            raise ValueError(f"{anchor.id}: invalid water/zone location")
        x, z, yaw = anchor.player_position
        if math.hypot(x - anchor.x, z - anchor.z) > 20.0:
            raise ValueError(f"{anchor.id}: approach outside hail range")
        for boat_id in BOATS:
            if not world.hull_clear(x, z, yaw, boat_id):
                raise ValueError(f"{anchor.id}: blocked {boat_id} approach")
        if anchor.kind == "water" and math.hypot(anchor.x-world.slip.ox, anchor.z-world.slip.oz) < 50.0:
            raise ValueError(f"{anchor.id}: NPC boat inside landing exclusion")
