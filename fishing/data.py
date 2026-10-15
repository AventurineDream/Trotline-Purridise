"""Species, bait, gear, and paint. All gameplay numbers live here."""

from __future__ import annotations

from dataclasses import dataclass


SPOIL_HOURS = 13.0
MAX_LINES = 5
DOZEN = 12


@dataclass(frozen=True)
class Species:
    id: str
    name: str
    price: float
    min_lb: float
    max_lb: float
    trophy: float
    rate: float
    pref_time: str
    depth: tuple[float, float]
    blurb: str


SPECIES: tuple[Species, ...] = (
    Species("bluegill", "Bluegill", 1.40, 0.12, 0.90, 0.03, 0.055, "day", (0.4, 3.2),
            "Worms on the flats. A sweet fillet, and they keep a line busy."),
    Species("bullhead", "Yellow bullhead", 1.55, 0.30, 2.2, 0.04, 0.040, "dusk", (0.4, 4.5),
            "Small cat, big mouth. Dusk, worms, and skinny water."),
    Species("crappie", "Black crappie", 3.10, 0.25, 2.0, 0.05, 0.022, "dawn", (1.0, 6.0),
            "Papermouth. Minnows at dawn around brush and lilies."),
    Species("carp", "Common carp", 0.72, 2.0, 18.0, 0.04, 0.016, "day", (0.8, 8.0),
            "They will pull a jug under. Worms on the warm flats."),
    Species("drum", "Freshwater drum", 1.15, 1.0, 12.0, 0.04, 0.012, "day", (2.0, 14.0),
            "Croaker. Crawfish and cut bait over deep mud."),
    Species("channel", "Channel catfish", 2.55, 1.0, 16.0, 0.05, 0.026, "night", (1.5, 12.0),
            "The lake's wage. Liver at night along cypress and the creek."),
    Species("blue", "Blue catfish", 3.15, 3.0, 30.0, 0.06, 0.0065, "night", (6.0, 18.0),
            "The big one. Cut shad, the deep hole, after dark."),
    Species("flathead", "Flathead catfish", 3.40, 2.0, 28.0, 0.06, 0.007, "night", (2.0, 10.0),
            "They want it alive. Minnows on the south rocks at night."),
    Species("largemouth", "Largemouth bass", 4.10, 0.8, 8.5, 0.05, 0.010, "dawn", (0.6, 5.0),
            "A bass will take a trotline minnow at dawn in the lilies."),
    Species("smallmouth", "Smallmouth bass", 5.00, 0.7, 5.5, 0.05, 0.008, "day", (1.0, 6.5),
            "Bronze and mean. Crawfish along the south rocks."),
    Species("gar", "Longnose gar", 0.95, 2.0, 16.0, 0.04, 0.007, "night", (1.0, 8.0),
            "Long teeth. Cut bait in the cypress after sunset."),
    Species("buffalo", "Smallmouth buffalo", 1.05, 2.0, 22.0, 0.04, 0.010, "day", (4.0, 16.0),
            "A deep-water drifter. Not prized, but they fill a well."),
    Species("white_crappie", "White crappie", 3.15, 0.25, 2.4, 0.05, 0.014, "dawn", (1.0, 7.0),
            "Minnows beside brush and creek channels. Cedar Creek's other papermouth."),
    Species("redear", "Redear sunfish", 1.85, 0.15, 1.5, 0.04, 0.012, "day", (0.6, 4.5),
            "Shellcracker. Worms and small crawfish on a firm, shallow bottom."),
    Species("green_sunfish", "Green sunfish", 1.10, 0.08, 0.8, 0.04, 0.009, "day", (0.3, 3.0),
            "A hungry little creek fish. Worms near rocks and flooded banks."),
    Species("warmouth", "Warmouth", 1.75, 0.15, 1.2, 0.04, 0.009, "dusk", (0.4, 4.0),
            "Big mouth, small fish. Minnows and worms in brushy coves."),
    Species("redbreast", "Redbreast sunfish", 1.55, 0.10, 1.0, 0.04, 0.008, "day", (0.4, 3.5),
            "Long ear flap and a copper belly. Worms in creek mouths."),
    Species("longear", "Longear sunfish", 1.45, 0.08, 0.7, 0.04, 0.008, "day", (0.3, 3.0),
            "Bright colors in clear shallows. Worms along rocky banks."),
    Species("spotted_bass", "Spotted bass", 4.35, 0.6, 5.5, 0.05, 0.006, "dawn", (1.0, 8.0),
            "A creek-channel hunter. Minnows or crawfish around rock and drops."),
    Species("white_bass", "White bass", 2.95, 0.4, 3.2, 0.05, 0.010, "dawn", (2.0, 12.0),
            "Schooling sand bass. Minnows where the creek channel meets open water."),
    Species("yellow_bass", "Yellow bass", 1.95, 0.2, 1.6, 0.04, 0.007, "day", (1.5, 10.0),
            "Golden schooling bass. Small minnows over submerged humps."),
    Species("hybrid_striper", "Hybrid striped bass", 5.20, 1.2, 13.0, 0.05, 0.004, "dawn", (3.0, 16.5),
            "Cedar Creek's stocked powerhouse. Shad and minnows over deep humps."),
    Species("striped_bass", "Striped bass", 5.35, 2.0, 22.0, 0.05, 0.0025, "dawn", (5.0, 18.0),
            "A rare Little Briar stocking. Cut shad in deep, open water."),
    Species("bowfin", "Bowfin", 1.30, 1.0, 11.0, 0.04, 0.004, "night", (0.5, 6.0),
            "An old swamp predator. Cut bait in warm, weedy backwaters."),
    Species("spotted_gar", "Spotted gar", 1.15, 0.8, 9.0, 0.04, 0.004, "dusk", (0.5, 6.0),
            "A spotted ambush fish. Shad and minnows beside flooded timber."),
    Species("shortnose_gar", "Shortnose gar", 1.10, 0.6, 7.5, 0.04, 0.0025, "dusk", (1.0, 8.0),
            "A short, broad snout. Cut bait near muddy creek mouths."),
    Species("alligator_gar", "Alligator gar", 1.70, 5.0, 65.0, 0.025, 0.0008, "night", (2.0, 12.0),
            "The heavyweight. Cut shad in creek channels; a big one needs a big well."),
    Species("black_bullhead", "Black bullhead", 1.55, 0.3, 3.0, 0.04, 0.006, "night", (0.5, 5.0),
            "A small cat from quiet, muddy water. Liver or worms after dark."),
    Species("brown_bullhead", "Brown bullhead", 1.70, 0.4, 4.0, 0.04, 0.004, "night", (0.6, 6.0),
            "A mottled Little Briar catfish. Liver beside flooded brush."),
    Species("blue_sucker", "Blue sucker", 1.60, 1.5, 12.0, 0.04, 0.002, "day", (4.0, 15.0),
            "A rare channel-bottom visitor in Little Briar. Worms on deeper gravel."),
    Species("bigmouth_buffalo", "Bigmouth buffalo", 0.95, 3.0, 35.0, 0.04, 0.003, "day", (3.0, 14.0),
            "A broad-backed drifter. An occasional worm catch over deep mud."),
    Species("black_buffalo", "Black buffalo", 1.15, 3.0, 30.0, 0.04, 0.002, "day", (4.0, 16.0),
            "A scarce Little Briar bottom fish. Worms or cut bait on the deep shelf."),
    Species("golden_shiner", "Golden shiner", 0.80, 0.04, 0.35, 0.03, 0.006, "day", (0.3, 3.0),
            "A flashing gold forage fish. Tiny worm bites among the weeds."),
    Species("gizzard_shad", "Gizzard shad", 0.70, 0.15, 1.8, 0.03, 0.002, "day", (1.5, 10.0),
            "Broad schools over open water. An occasional small worm catch."),
    Species("threadfin_shad", "Threadfin shad", 0.60, 0.02, 0.25, 0.02, 0.002, "day", (1.0, 8.0),
            "A tiny forage fish, rarely caught on a baited hook. Warm open water."),
    Species("chain_pickerel", "Chain pickerel", 3.40, 0.6, 5.0, 0.04, 0.003, "dawn", (0.4, 5.0),
            "A toothy Little Briar weed hunter. Live minnows in the lily cove."),
)

SPECIES_BY_ID = {s.id: s for s in SPECIES}


@dataclass(frozen=True)
class Bait:
    id: str
    name: str
    price: float  # per dozen
    blurb: str


BAITS: tuple[Bait, ...] = (
    Bait("worm", "Nightcrawlers", 6.0, "Panfish, bullheads, and carp."),
    Bait("liver", "Chicken liver", 8.0, "Channel cats and bullheads."),
    Bait("shad", "Cut shad", 10.0, "Blue cats, drum, and gar."),
    Bait("minnow", "Live minnows", 14.0, "Bass, crappie, and flatheads."),
    Bait("craw", "Crawfish", 16.0, "Smallmouth, largemouth, and drum."),
)

BAIT_BY_ID = {b.id: b for b in BAITS}

# Preferred bait multiplier. Missing pairs fall back to 0.05.
BAIT_MATCH: dict[str, dict[str, float]] = {
    "worm": {
        "bluegill": 1.0, "bullhead": 1.0, "carp": 0.9, "buffalo": 0.65,
        "channel": 0.4, "crappie": 0.22, "drum": 0.2, "largemouth": 0.18,
        "smallmouth": 0.12, "blue": 0.12,
    },
    "liver": {
        "channel": 1.0, "bullhead": 0.95, "blue": 0.72, "flathead": 0.22,
        "drum": 0.18, "gar": 0.12, "buffalo": 0.2,
    },
    "shad": {
        "blue": 1.0, "channel": 0.85, "gar": 0.95, "drum": 0.8,
        "flathead": 0.32, "buffalo": 0.45, "carp": 0.15,
    },
    "minnow": {
        "flathead": 1.0, "largemouth": 1.0, "crappie": 1.0, "smallmouth": 0.7,
        "channel": 0.28, "bluegill": 0.15,
    },
    "craw": {
        "smallmouth": 1.0, "largemouth": 0.85, "drum": 0.75, "channel": 0.3,
        "flathead": 0.2, "bullhead": 0.25,
    },
}

# Zone affinity. Missing pairs fall back to 0.07. "open" and "landing" are thin.
ZONE_MATCH: dict[str, dict[str, float]] = {
    "flats": {"bluegill": 1.0, "bullhead": 1.0, "carp": 0.85, "largemouth": 0.3, "crappie": 0.25},
    "lilies": {"largemouth": 1.0, "bluegill": 0.75, "crappie": 0.7, "bullhead": 0.28},
    "cypress": {"gar": 1.0, "channel": 0.85, "crappie": 0.5, "largemouth": 0.35, "bullhead": 0.2},
    "deep": {"blue": 1.0, "buffalo": 1.0, "drum": 0.75, "channel": 0.55},
    "rocks": {"flathead": 1.0, "smallmouth": 1.0, "drum": 0.4, "channel": 0.28},
    "inlet": {"channel": 0.95, "blue": 0.65, "carp": 0.8, "drum": 0.55, "gar": 0.4},
    "open": {"channel": 0.4, "drum": 0.4, "carp": 0.32, "buffalo": 0.3, "bluegill": 0.15},
    "landing": {"crappie": 0.2, "bluegill": 0.15},
}

# Additional fish share ecological preferences, but retain individual rates,
# sizes, prices, and records. All 36 are available in fictional Little Briar.
_GROUPS = (
    (("redear", "green_sunfish", "redbreast", "longear", "golden_shiner"),
     {"worm": 1.0, "craw": 0.35}, {"flats": 1.0, "lilies": 0.8, "inlet": 0.6, "rocks": 0.5}),
    (("warmouth", "white_crappie", "chain_pickerel"),
     {"minnow": 1.0, "worm": 0.3}, {"lilies": 1.0, "cypress": 0.8, "inlet": 0.5}),
    (("spotted_bass",), {"minnow": 1.0, "craw": 0.9}, {"rocks": 1.0, "inlet": 0.8}),
    (("white_bass", "yellow_bass", "hybrid_striper", "striped_bass"),
     {"minnow": 1.0, "shad": 0.8}, {"open": 1.0, "deep": 1.0, "inlet": 0.65, "rocks": 0.5}),
    (("bowfin", "spotted_gar", "shortnose_gar", "alligator_gar"),
     {"shad": 1.0, "minnow": 0.8}, {"cypress": 1.0, "inlet": 0.85, "lilies": 0.6}),
    (("black_bullhead", "brown_bullhead"),
     {"liver": 1.0, "worm": 0.9}, {"inlet": 1.0, "cypress": 0.8, "flats": 0.65}),
    (("blue_sucker", "bigmouth_buffalo", "black_buffalo"),
     {"worm": 0.8, "shad": 0.35}, {"deep": 1.0, "inlet": 0.75, "open": 0.5}),
    (("gizzard_shad", "threadfin_shad"), {"worm": 0.3}, {"open": 1.0, "flats": 0.5}),
)
for _ids, _baits, _zones in _GROUPS:
    for _id in _ids:
        for _bait, _match in _baits.items():
            BAIT_MATCH[_bait][_id] = _match
        for _zone, _match in _zones.items():
            ZONE_MATCH[_zone][_id] = _match

# Survey-backed core fish dominate Cedar Creek; several Little Briar
# specialties are absent. The remaining community and bite rates are gameplay.
CEDAR_FISH = {sp.id: 0.7 for sp in SPECIES}
for _id in ("smallmouth", "striped_bass", "brown_bullhead", "blue_sucker", "black_buffalo", "chain_pickerel"):
    CEDAR_FISH[_id] = 0.0
CEDAR_FISH.update(blue=2.4, channel=0.85, white_bass=2.0, hybrid_striper=2.6,
                  white_crappie=1.9, crappie=1.1, largemouth=1.25, yellow_bass=1.4)

ZONE_NAME = {
    "flats": "North flats",
    "lilies": "Lily cove",
    "cypress": "Cypress shore",
    "deep": "Deep hole",
    "rocks": "South rocks",
    "inlet": "Creek inlet",
    "open": "Open water",
    "landing": "Briar Landing",
    "shore": "Bank",
}

# Order used by the map legend and zone ids.
ZONE_ORDER = ("landing", "inlet", "flats", "lilies", "cypress", "rocks", "deep", "open")


LINE_TIERS = {
    "std": {"hooks": 12, "price": 70.0, "name": "Trotline, 12 hooks",
            "blurb": "A staged line with a buoy at each end."},
    "prem": {"hooks": 18, "price": 145.0, "name": "Trotline, 18 hooks",
             "blurb": "More hooks, more soak, more to check."},
    "heavy": {"hooks": 24, "price": 250.0, "name": "Trotline, 24 hooks",
              "blurb": "A long line. Mind the livewell."},
}

MOTORS = (
    {"name": "6 hp tiller", "speed": 3.15, "price": 0.0},
    {"name": "9.9 hp tiller", "speed": 4.95, "price": 175.0},
    {"name": "15 hp tiller", "speed": 7.15, "price": 400.0},
)

WELLS = (40.0, 80.0, 140.0)
WELL_PRICE = (0.0, 100.0, 240.0)
BOXES = (48, 96, 180)
BOX_PRICE = (0.0, 50.0, 120.0)
FINDER_PRICE = 95.0
LIGHT_PRICE = 80.0

# id, label, rgb 0-1, price. Price 0 is the starting look, already owned.
HULLS = (
    ("aluminum", "Aluminum", (0.64, 0.66, 0.68), 0.0),
    ("green", "John-boat green", (0.20, 0.36, 0.26), 20.0),
    ("olive", "Olive drab", (0.30, 0.32, 0.18), 20.0),
    ("carolina", "Carolina blue", (0.24, 0.42, 0.58), 20.0),
    ("red", "Barn red", (0.52, 0.18, 0.16), 20.0),
    ("black", "Black", (0.14, 0.15, 0.16), 20.0),
    ("sand", "Sand", (0.66, 0.58, 0.40), 20.0),
    ("white", "White", (0.82, 0.82, 0.78), 20.0),
)
DECKS = (
    ("aluminum", "Bare aluminum", (0.50, 0.52, 0.54), 0.0),
    ("wood", "Wood floor", (0.48, 0.34, 0.20), 20.0),
    ("carpet", "Blue carpet", (0.16, 0.26, 0.40), 20.0),
)
BUOYS = (
    ("orange", "Orange jug", (0.90, 0.42, 0.12), 0.0),
    ("white", "White jug", (0.90, 0.90, 0.86), 15.0),
    ("red", "Red jug", (0.75, 0.16, 0.14), 15.0),
    ("yellow", "Yellow jug", (0.90, 0.78, 0.20), 15.0),
)
MOTORS_PAINT = (
    ("black", "Black tiller", (0.12, 0.12, 0.13), 0.0),
    ("red", "Red tiller", (0.62, 0.14, 0.12), 15.0),
    ("white", "White tiller", (0.85, 0.85, 0.82), 15.0),
    ("green", "Green tiller", (0.16, 0.36, 0.24), 15.0),
)

PAINT = {"hull": HULLS, "deck": DECKS, "buoy": BUOYS, "motor": MOTORS_PAINT}
PAINT_LABEL = {"hull": "Hull", "deck": "Deck", "buoy": "Buoys", "motor": "Tiller"}


def paint_rgb(slot: str, pid: str) -> tuple[float, float, float]:
    for item in PAINT[slot]:
        if item[0] == pid:
            return item[2]
    return (0.5, 0.5, 0.5)


def paint_name(slot: str, pid: str) -> str:
    for item in PAINT[slot]:
        if item[0] == pid:
            return item[1]
    return pid


def bait_mult(bait: str, species: str) -> float:
    return BAIT_MATCH.get(bait, {}).get(species, 0.05)


def zone_mult(zone: str, species: str) -> float:
    return ZONE_MATCH.get(zone, {}).get(species, 0.07)


def band_of(hour: float) -> str:
    h = hour % 24.0
    if 5.0 <= h < 8.0:
        return "dawn"
    if 8.0 <= h < 17.0:
        return "day"
    if 17.0 <= h < 20.0:
        return "dusk"
    return "night"


_ADJ = {
    "dawn": {"night", "day"},
    "day": {"dawn", "dusk"},
    "dusk": {"day", "night"},
    "night": {"dusk", "dawn"},
}


def time_mult(pref: str, hour: float) -> float:
    band = band_of(hour)
    if pref == "any":
        return 0.8
    if pref == band:
        return 1.0
    if band in _ADJ[pref]:
        return 0.42
    return 0.12


_CATS = {"channel", "blue", "flathead", "bullhead", "black_bullhead", "brown_bullhead"}
_BASS = {"largemouth", "smallmouth", "crappie", "white_crappie", "spotted_bass",
         "white_bass", "yellow_bass", "hybrid_striper", "striped_bass"}


def weather_mult(species: str, weather: str) -> float:
    if weather == "drizzle":
        if species in _CATS:
            return 1.40
        if species in _BASS:
            return 0.62
        return 0.90
    if weather == "overcast":
        if species in _CATS:
            return 1.15
        return 0.95
    if weather == "clear":
        if species in _BASS or species == "bluegill":
            return 1.12
        return 1.0
    return 1.0


def depth_mult(species: Species, depth: float) -> float:
    lo, hi = species.depth
    if lo <= depth <= hi:
        return 1.0
    if depth < lo:
        return max(0.20, 1.0 - (lo - depth) / 3.5)
    return max(0.20, 1.0 - (depth - hi) / 5.0)


def piece_price(bait_id: str) -> float:
    return BAIT_BY_ID[bait_id].price / DOZEN


def quality_of(age_hours: float) -> float:
    if age_hours < 5.0:
        return 1.0
    if age_hours < 9.0:
        return 0.72
    if age_hours < SPOIL_HOURS:
        return 0.42
    return 0.0


def quality_name(q: float) -> str:
    if q >= 0.95:
        return "prime"
    if q >= 0.60:
        return "good"
    return "tired"


def fish_value(species_id: str, weight: float, quality: float) -> float:
    return round(SPECIES_BY_ID[species_id].price * weight * quality, 2)


def line_length(hooks: int) -> float:
    return 7.0 + hooks * 1.05


def weather_at(game_minutes: float) -> str:
    """Morning starts clear. Later days bring cloud and rain."""
    hour = hour_of_day(game_minutes)
    day = int(game_minutes // (24.0 * 60.0))
    if hour < 10.0:
        return "fair" if day % 5 == 4 else "clear"
    if hour < 16.5:
        return ("clear", "fair", "clear", "overcast")[day % 4]
    if hour < 20.5:
        return ("clear", "fair", "fair", "drizzle")[day % 4]
    return ("fair", "clear", "overcast", "drizzle")[day % 4]


def hour_of_day(game_minutes: float) -> float:
    """Dawn start: minute 0 is 6:00."""
    return ((6.0 * 60.0 + game_minutes) % (24.0 * 60.0)) / 60.0


def clock_string(game_minutes: float) -> str:
    m = int(6 * 60 + game_minutes) % (24 * 60)
    h, minute = divmod(m, 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{minute:02d} {suffix}"


def dollars(n: float) -> str:
    return f"${n:.2f}"
