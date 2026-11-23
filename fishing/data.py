"""Typed gameplay data loaded from the versioned content files."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


SPOIL_HOURS = 13.0
DOZEN = 12
CONTENT_V2_PATH = Path(__file__).with_name("assets") / "content_v2"
_CONTENT_FILES = ("species.json", "baits.json", "boats.json", "lakes.json",
                  "pantry.json", "dishes.json", "calendar.json", "bot.json", "legendaries.json",
                  "npcs.json", "quests.json", "ripples.json", "keepsakes.json")


def _unique_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_content_file(filename: str) -> dict:
    path = CONTENT_V2_PATH / filename
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_keys)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


# Keep the source documents available to the authoring validator. Runtime
# consumers use the typed views below, never duplicate hard-coded rosters.
CONTENT_V2_RAW = {filename: _read_content_file(filename) for filename in _CONTENT_FILES}


def _validate_content_v2_files(raw_files: dict) -> None:
    # Validate before building typed runtime objects so malformed rows fail with
    # their source file and content ID instead of a bare KeyError or TypeError.
    from .content import validate_content_v2

    validate_content_v2(raw_files)


_validate_content_v2_files(CONTENT_V2_RAW)


@dataclass(frozen=True)
class BotShell:
    id: str
    name: str
    chapter: int
    tool_id: str
    body: tuple[float, float, float]
    trim: tuple[float, float, float]
    secondary: tuple[float, float, float]
    chime: str
    caption: str


@dataclass(frozen=True)
class BotTool:
    id: str
    name: str
    price: int
    requires_finder: bool


_BOT_DATA = CONTENT_V2_RAW["bot.json"]
BOT_PREFIXES = tuple(_BOT_DATA["name_prefixes"])
BOT_SUFFIX_MIN, BOT_SUFFIX_MAX = _BOT_DATA["suffix_min"], _BOT_DATA["suffix_max"]
BOT_SHELLS = {row["id"]: BotShell(**{**row, **{key: tuple(row[key]) for key in ("body", "trim", "secondary")}}) for row in _BOT_DATA["shells"]}
BOT_TOOLS = {row["id"]: BotTool(**row) for row in _BOT_DATA["tools"]}
BOT_COLLAR_STAGES = {row["id"]: row["name"] for row in _BOT_DATA["collar_stages"]}
BOT_KNOTS = {row["id"]: row["name"] for row in _BOT_DATA["knots"]}


@dataclass(frozen=True)
class LakeDay:
    id: str
    lake: str
    weekday: int
    name: str
    band: str
    multiplier: float
    foods: tuple[str, ...]
    species: tuple[str, ...]
    zones: tuple[str, ...]
    weather_bias: str
    fireflies: bool


@dataclass(frozen=True)
class WeatherWindow:
    id: str
    lake: str
    start_hour: int
    end_hour: int
    weathers: tuple[str, ...]
    recent_rain: bool
    minimum_minutes: int


@dataclass(frozen=True)
class WeatherReservation:
    lake: str
    start_hour: int
    end_hour: int
    weathers: tuple[str, ...]


CALENDAR_DATA = CONTENT_V2_RAW["calendar.json"]
LAKE_DAYS = tuple(LakeDay(**{**row, **{key: tuple(row[key]) for key in
                         ("foods", "species", "zones")}}) for row in CALENDAR_DATA["lake_days"])
LEGENDARY_WINDOWS = {row["id"]: WeatherWindow(**{**row, "weathers": tuple(row["weathers"])})
                     for row in CALENDAR_DATA["legendary_windows"]}
WEATHER_RESERVATIONS = tuple(WeatherReservation(**{**row, "weathers": tuple(row["weathers"])})
                             for row in CALENDAR_DATA["reservations"])

_TIER_DEFAULTS = {
    row["tier"]: {key: row[key] for key in ("rate", "trophy")}
    for row in CONTENT_V2_RAW["species.json"]["tier_defaults"]
}


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
    folk_name: str = ""
    lakes: tuple[str, ...] = ()
    food: str = "none"
    tags: tuple[str, ...] = ()
    shiny: str = "albino"
    baits: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    weather_affinities: dict[str, float] = field(default_factory=dict)


def _species_values(row: dict) -> dict:
    """Apply tier defaults while allowing row-level rate and trophy overrides."""
    values = dict(_TIER_DEFAULTS.get(row.get("tier"), {}))
    values.update(row)
    values.pop("tier", None)
    values.pop("look", None)
    return values


SPECIES: tuple[Species, ...] = tuple(
    Species(**{**_species_values(row), "depth": tuple(row["depth"]), "lakes": tuple(row["lakes"]),
               "tags": tuple(row["tags"]), "baits": tuple(row.get("baits", ())),
               "zones": tuple(row.get("zones", ()))})
    for row in CONTENT_V2_RAW["species.json"]["species"]
)

SPECIES_BY_ID = {s.id: s for s in SPECIES}


@dataclass(frozen=True)
class Bait:
    id: str
    name: str
    price: float  # per dozen
    blurb: str
    sold_at: tuple[str, ...] = ("all",)


BAITS: tuple[Bait, ...] = tuple(
    Bait(**{key: row[key] for key in ("id", "name", "price", "blurb")},
         sold_at=tuple(row.get("sold_at", ["all"])))
    for row in CONTENT_V2_RAW["baits.json"]["baits"]
)

BAIT_BY_ID = {b.id: b for b in BAITS}

BAIT_MATCH: dict[str, dict[str, float]] = {
    row["id"]: dict(row["matches"])
    for row in CONTENT_V2_RAW["baits.json"]["baits"]
}
BAIT_FALLBACK_MULTIPLIER = CONTENT_V2_RAW["baits.json"]["fallback_multiplier"]


@dataclass(frozen=True)
class BaitRecipe:
    parents: tuple[str, str]
    ingredient: str
    teller: str


BAIT_RECIPES = {row["id"]: BaitRecipe(tuple(row["recipe"]["parents"]),
                                      row["recipe"]["ingredient"], row["recipe"]["teller"])
                for row in CONTENT_V2_RAW["baits.json"]["baits"] if "recipe" in row}
for _bait_id, _recipe in BAIT_RECIPES.items():
    BAIT_MATCH[_bait_id] = {
        sid: max(BAIT_MATCH[parent].get(sid, BAIT_FALLBACK_MULTIPLIER)
                 for parent in _recipe.parents) for sid in SPECIES_BY_ID}


@dataclass(frozen=True)
class PantryItem:
    id: str
    name: str
    host: str
    lake: str
    price: float


@dataclass(frozen=True)
class Dish:
    id: str
    name: str
    host: str
    chapter: int
    food: str
    ingredient: str
    effect: str
    minutes: int
    charges: int
    value: float
    blurb: str


PANTRY = {row["id"]: PantryItem(**row) for row in CONTENT_V2_RAW["pantry.json"]["items"]}
PANTRY_CAPACITY = CONTENT_V2_RAW["pantry.json"]["capacity"]
DISH_CARD_PRICE = CONTENT_V2_RAW["pantry.json"]["card_price"]
DISHES = {row["id"]: Dish(**row) for row in CONTENT_V2_RAW["dishes.json"]["dishes"]}

_LAKE_CONTENT = CONTENT_V2_RAW["lakes.json"]
ZONE_ORDER = tuple(_LAKE_CONTENT["zone_order"])
ZONE_MATCH: dict[str, dict[str, float]] = {
    row["id"]: dict(row["matches"]) for row in _LAKE_CONTENT["zones"]
}
ZONE_FALLBACK_MULTIPLIER = _LAKE_CONTENT["zone_fallback_multiplier"]
ZONE_NAME = {row["id"]: row["name"] for row in _LAKE_CONTENT["zones"]}
LAKES = {row["id"]: {key: value for key, value in row.items()
                      if key not in ("id", "species_count", "species_ids", "rate_multipliers", "zone_labels",
                                     "loading_quips")}
         for row in _LAKE_CONTENT["lakes"]}
LAKE_SPECIES_IDS = {row["id"]: tuple(row["species_ids"]) for row in _LAKE_CONTENT["lakes"]}
# Loading-card lines: shared ones suit any water, each lake's own are unique to it.
LOADING_QUIPS = tuple(_LAKE_CONTENT["loading_quips"])
LAKE_LOADING_QUIPS = {row["id"]: tuple(row["loading_quips"]) for row in _LAKE_CONTENT["lakes"]}
LAKE_RATE_MULTIPLIERS = {}
for _lake in _LAKE_CONTENT["lakes"]:
    _rates = {species_id: 0.0 for species_id in SPECIES_BY_ID}
    _rates.update({species_id: 1.0 for species_id in _lake["species_ids"]})
    _rates.update(_lake.get("rate_multipliers", {}))
    LAKE_RATE_MULTIPLIERS[_lake["id"]] = _rates
CEDAR_ZONES = dict(next(row for row in _LAKE_CONTENT["lakes"] if row["id"] == "cedar")["zone_labels"])
LAKE_ZONE_NAMES = {row["id"]: dict(row["zone_labels"]) for row in _LAKE_CONTENT["lakes"]}
CEDAR_FISH = dict(LAKE_RATE_MULTIPLIERS["cedar"])
BOAT_DATA: tuple[dict, ...] = tuple(CONTENT_V2_RAW["boats.json"]["boats"])


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
    return BAIT_MATCH.get(bait, {}).get(species, BAIT_FALLBACK_MULTIPLIER)


def zone_mult(zone: str, species: str) -> float:
    return ZONE_MATCH.get(zone, {}).get(species, ZONE_FALLBACK_MULTIPLIER)


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
    fish = SPECIES_BY_ID.get(species)
    if fish is not None and fish.weather_affinities:
        return fish.weather_affinities.get(weather, 1.0)
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


def weight_string(weight: float) -> str:
    """Keep tiny minnows visible while retaining the usual one-decimal weight."""
    value = f"{weight:.3f}".rstrip('0').rstrip('.') if 0 < weight < .1 else f"{weight:.1f}"
    return value + " lb"


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
