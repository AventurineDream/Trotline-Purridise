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
    # V1-30: the rest of the cast. Every water-cat encounter has its own anchor in its
    # zone (04 §4), at least 60 m from the next, and each lake keeps a mail and a tinker
    # mooring for the travelers. Positions were searched once and are fixed here.
    Anchor("briar:open", "briar:open", "Open water swim", -276.0, -170.0),
    Anchor("briar:rocks", "briar:rocks", "Heron rocks", 18.0, -194.0),
    Anchor("briar:bread_flats", "briar:flats", "Bread-barge flats", 42.0, 256.0),
    Anchor("briar:mail_mooring", "briar:open", "Mail mooring", -342.0, 142.0),
    Anchor("briar:tinker_mooring", "briar:open", "Tinker mooring", -384.0, 22.0),
    Anchor("cedar:lower_inlet", "cedar:inlet", "Lower creek mouth", -400.389, 893.323),
    Anchor("cedar:cypress", "cedar:cypress", "Pecan cypress", 559.611, -432.677),
    Anchor("cedar:rocks", "cedar:rocks", "Marked Pool rocks", 379.611, -1260.677),
    Anchor("cedar:ranger_flats", "cedar:flats", "Ranger flats", -286.389, 479.323),
    Anchor("cedar:mail_mooring", "cedar:open", "Mail mooring", 1117.611, -918.677),
    Anchor("cedar:tinker_mooring", "cedar:open", "Tinker mooring", 979.611, -1050.677),
    # The alpine, caldera and starlight landings, then their water-cats.
    Anchor("flathead:landing", "flathead:landing", "Glacial Peak Outpost", -597.363, 115.872,
           "dock", (-585.582, 113.587, 1.7623889803846897)),
    Anchor("flathead:deep", "flathead:deep", "The trench", 54.0, -46.0),
    Anchor("flathead:trench_edge", "flathead:deep", "Trench edge", 102.0, -10.0),
    Anchor("flathead:inlet", "flathead:inlet", "Glacier inlet", -318.0, 326.0),
    Anchor("flathead:flats", "flathead:flats", "Moraine flats", -18.0, 332.0),
    Anchor("flathead:cypress", "flathead:cypress", "Larch shore", 396.0, 74.0),
    Anchor("flathead:larch_bay", "flathead:cypress", "Larch bay", 360.0, 122.0),
    Anchor("flathead:rocks", "flathead:rocks", "Owl rocks", 168.0, -310.0),
    Anchor("flathead:open", "flathead:open", "Big open", -294.0, 14.0),
    Anchor("flathead:wind_reach", "flathead:open", "Wind reach", -282.0, 170.0),
    Anchor("flathead:mail_mooring", "flathead:open", "Mail mooring", -504.0, 80.0),
    Anchor("flathead:tinker_mooring", "flathead:open", "Tinker mooring", -528.0, 188.0),
    Anchor("crater:landing", "crater:landing", "Caldera Rim Dock", -472.722, 57.765,
           "dock", (-460.811, 56.309, 1.6923889803846899)),
    Anchor("crater:springs", "crater:springs", "Hot springs", 282.0, -234.0),
    Anchor("crater:rocks", "crater:rocks", "Glass shore", 150.0, 30.0),
    Anchor("crater:basalt", "crater:rocks", "Basalt shelf", 150.0, -150.0),
    Anchor("crater:flats", "crater:flats", "Pumice flats", -12.0, -342.0),
    Anchor("crater:lilies", "crater:lilies", "Lantern moss", -378.0, -126.0),
    Anchor("crater:open", "crater:open", "Lookout water", -228.0, 264.0),
    Anchor("crater:star_water", "crater:open", "Star water", -246.0, -168.0),
    Anchor("crater:cypress", "crater:cypress", "Fog stand", 330.0, 138.0),
    Anchor("crater:deep", "crater:deep", "Clear deep", -96.0, 18.0),
    Anchor("crater:mail_mooring", "crater:open", "Mail mooring", -438.0, -36.0),
    Anchor("crater:tinker_mooring", "crater:open", "Tinker mooring", -390.0, 114.0),
    Anchor("nebula:landing", "nebula:landing", "Cosmic Drift Station", -424.051, -264.919,
           "dock", (-413.874, -258.561, 1.0123889803846897)),
    Anchor("nebula:open", "nebula:open", "Hover reach", -166.0, -454.0),
    Anchor("nebula:far_open", "nebula:open", "Edge of the map", -124.0, -154.0),
    Anchor("nebula:current", "nebula:current", "Star-chime current", -484.0, 116.0),
    Anchor("nebula:fast_current", "nebula:current", "Fast lane", -424.0, 116.0),
    Anchor("nebula:inlet", "nebula:inlet", "Comet stream", -598.0, 158.0),
    Anchor("nebula:lilies", "nebula:lilies", "Harp drift", 380.0, -130.0),
    Anchor("nebula:lily_nursery", "nebula:lilies", "Lily nursery", 428.0, -94.0),
    Anchor("nebula:flats", "nebula:flats", "Moon garden", -250.0, 332.0),
    Anchor("nebula:deep", "nebula:deep", "Lanternfish deep", 128.0, -28.0),
    Anchor("nebula:mail_mooring", "nebula:open", "Mail mooring", -358.0, -190.0),
    Anchor("nebula:tinker_mooring", "nebula:open", "Tinker mooring", -352.0, -334.0),
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
