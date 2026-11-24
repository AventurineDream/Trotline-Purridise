"""The player's own cat: the Skipper's name and look, chosen at a new game and saved in `v2.skipper`.

The look is a subset of an NPC's `appearance` (npcs.json, catmesh.py): pattern,
the three coat colours, eyes, ears, tail, fur and up to three attire items from
the shared kit. `appearance()` fills the rest with the roster's neutral values
(size, build and legs 1.0), so the Skipper is built, painted and animated by the
same rig as the 52 cats: the third-person and staged views, the creator's
preview, the first-person paws and the calm-water reflection all read it here.

Body proportions stay fixed on purpose: the first-person camera, the paws' grips
and the reflection are placed for a size-1 cat, so size, build and legs are not
player options.

Saves written before the creator existed have no `v2.skipper`; `normalize`
gives them `DEFAULT`, the dusk-brown tabby the game always drew, named Skipper.
Unknown future fields are kept; malformed known fields fall back one by one.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re

DEFAULT_NAME = "Skipper"
NAME_MAX = 16

# Natural coat colours, shared by the base, markings and accent rows (linear 0-1 RGB).
COAT_SWATCHES = (
    ("Dusk brown", (0.66, 0.54, 0.40)),
    ("Dark stripe", (0.33, 0.25, 0.17)),
    ("Mitten cream", (0.93, 0.90, 0.84)),
    ("Snow", (0.95, 0.94, 0.91)),
    ("Ginger", (0.88, 0.54, 0.22)),
    ("Cinnamon", (0.62, 0.38, 0.24)),
    ("Cocoa", (0.36, 0.24, 0.16)),
    ("Fawn", (0.80, 0.68, 0.55)),
    ("Lilac", (0.70, 0.64, 0.66)),
    ("Silver", (0.76, 0.77, 0.78)),
    ("Blue grey", (0.52, 0.56, 0.60)),
    ("Charcoal", (0.20, 0.20, 0.22)),
    ("Ink", (0.10, 0.09, 0.09)),
)
EYE_SWATCHES = (
    ("Gold", (0.86, 0.70, 0.22)),
    ("Green", (0.48, 0.74, 0.30)),
    ("Copper", (0.85, 0.48, 0.18)),
    ("Blue", (0.38, 0.62, 0.90)),
    ("Hazel", (0.64, 0.62, 0.30)),
    ("Amber", (0.92, 0.58, 0.12)),
)
CLOTH_SWATCHES = (
    ("Oilskin yellow", (0.93, 0.74, 0.16)),
    ("Harbour red", (0.72, 0.20, 0.20)),
    ("Navy", (0.16, 0.22, 0.40)),
    ("Moss", (0.36, 0.48, 0.26)),
    ("Heather", (0.62, 0.52, 0.70)),
    ("Teal", (0.18, 0.52, 0.52)),
    ("Oatmeal", (0.84, 0.78, 0.64)),
    ("Rust", (0.70, 0.36, 0.18)),
)
BRASS = (0.76, 0.72, 0.60)  # spectacle and goggle frames, as the roster's

# Spectacle and goggle frame finishes: preset RGB triples cycled on the head
# colour row while a specs/goggles item is worn. Distinct from each other and
# from the cyan goggle lens tint baked in catmesh.paint; any saved RGB still
# round-trips, these are only the selectable presets.
FRAME_FINISHES = (
    ("Brass", BRASS),
    ("Silver", (0.78, 0.80, 0.83)),
    ("Gold", (0.95, 0.70, 0.20)),
    ("Rose gold", (0.85, 0.55, 0.48)),
)

PATTERN_LABELS = {"solid": "Solid", "tabby": "Tabby", "mackerel": "Mackerel", "calico": "Calico",
                  "tortoiseshell": "Tortoiseshell", "tuxedo": "Tuxedo", "point": "Colourpoint",
                  "spotted": "Spotted", "bicolor": "Bicolour"}
# Which coat colours each pattern shows (catmesh.coat_weights): the creator dims the rest.
PATTERN_COLORS = {"solid": ("base",), "tabby": ("base", "secondary"), "mackerel": ("base", "secondary"),
                  "spotted": ("base", "secondary"), "point": ("base", "secondary"),
                  "calico": ("base", "secondary", "accent"), "tortoiseshell": ("base", "secondary", "accent"),
                  "tuxedo": ("base", "accent"), "bicolor": ("base", "accent")}
EARS = {"pointed": "Pointed", "rounded": "Rounded", "tufted": "Tufted", "folded": "Folded back",
        "folded_left": "Folded left", "folded_right": "Folded right"}
TAILS = {"long": "Long", "plume": "Plume", "bob": "Bobbed", "none": "None (Manx)"}
COATS = {"short": "Short", "long": "Long", "rex": "Curly (rex)", "hairless": "Hairless"}
# Attire slots: one item each from the shared kit (the lantern is a deck prop, not worn).
SLOTS = {
    "head": {"none": "None", "cap": "Cap", "spectacles": "Spectacles", "goggles": "Goggles"},
    "neck": {"none": "None", "scarf": "Scarf", "bandana": "Bandana"},
    "body": {"none": "None", "oilskin": "Oilskin", "parka": "Parka", "sweater": "Sweater", "vest": "Vest",
             "life_jacket": "Life jacket", "shawl": "Shawl"},
}
NAME_SUGGESTIONS = ("Skipper", "Mochi", "Juniper", "Biscuit", "Pepper", "Marlow", "Tansy", "Rook", "Clementine",
                    "Moss", "Sorrel", "Wren", "Bramble", "Otto")

DEFAULT = {
    "name": DEFAULT_NAME,
    "created": False,
    "pattern": "tabby",
    "colors": {"base": [0.66, 0.54, 0.40], "secondary": [0.33, 0.25, 0.17], "accent": [0.93, 0.90, 0.84]},
    "eyes": [0.86, 0.70, 0.22],
    "ears": "pointed",
    "tail": "long",
    "coat": "short",
    "attire": [],
}

# The creator's rows, top to bottom: (key, label). "done" confirms.
ROWS = (("name", "Name"), ("pattern", "Pattern"), ("base", "Coat"), ("secondary", "Markings"),
        ("accent", "Bib & mitts"), ("eyes", "Eyes"), ("ears", "Ears"), ("tail", "Tail"), ("coat", "Fur"),
        ("head", "Hat & specs"), ("head_color", "Hat colour"), ("neck", "Neckwear"),
        ("neck_color", "Neckwear colour"),
        ("body", "Jacket"), ("body_color", "Jacket colour"), ("done", "Done"))

COLOR_ROWS = ("head_color", "neck_color", "body_color")  # each recolours its slot's item
_NAME_CHARS = re.compile(r"[^A-Za-z0-9 '.\-]")


def clean_name(value) -> str:
    """A display-safe Skipper name, or DEFAULT_NAME.

    Keeps letters, digits, spaces, apostrophes, hyphens and full stops, collapses
    runs of spaces and trims to NAME_MAX characters; a value without a letter
    (or not a string) becomes DEFAULT_NAME.
    """
    if not isinstance(value, str):
        return DEFAULT_NAME
    text = " ".join(_NAME_CHARS.sub("", value).split())[:NAME_MAX].strip()
    return text if any(c.isalpha() for c in text) else DEFAULT_NAME


def _rgb(value, fallback):
    """`value` as a list of three finite 0-1 floats, else a copy of `fallback`."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            out = [float(v) for v in value]
        except (TypeError, ValueError, OverflowError):
            return list(fallback)
        if all(type(v) in (int, float) for v in value) and all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in out):
            return out
    return list(fallback)


def normalize(v2: dict) -> dict:
    """Repair `v2["skipper"]` in place and return it.

    A missing or non-dict entry becomes a copy of DEFAULT (the migration for saves
    from before the creator). Each known field is validated on its own, so one bad
    colour keeps the rest of the look; unknown fields are kept for newer builds.
    """
    from .catmesh import PATTERNS
    saved = v2.get("skipper")
    look = deepcopy(saved) if isinstance(saved, dict) else {}
    look["name"] = clean_name(look.get("name"))
    look["created"] = look.get("created") is True
    # Membership tests need a str first: a list or dict from a hand-edited save is unhashable,
    # and a TypeError here would set the whole save aside as corrupt.
    if not isinstance(look.get("pattern"), str) or look["pattern"] not in PATTERNS:
        look["pattern"] = DEFAULT["pattern"]
    colors = look.get("colors") if isinstance(look.get("colors"), dict) else {}
    look["colors"] = {**colors, **{key: _rgb(colors.get(key), DEFAULT["colors"][key])
                                   for key in ("base", "secondary", "accent")}}
    look["eyes"] = _rgb(look.get("eyes"), DEFAULT["eyes"])
    for key, allowed in (("ears", EARS), ("tail", TAILS), ("coat", COATS)):
        if not isinstance(look.get(key), str) or look[key] not in allowed:
            look[key] = DEFAULT[key]
    attire, taken = [], set()
    raw = look.get("attire")
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, dict):
            continue
        slot = _slot_of(item.get("kind"))
        if slot is None or slot in taken:
            continue
        taken.add(slot)
        attire.append({"kind": item["kind"], "color": _rgb(item.get("color"), _default_color(item["kind"]))})
    look["attire"] = attire
    v2["skipper"] = look
    return look


def _slot_of(kind):
    """The attire slot a kind belongs to, or None for "none", unknown or non-str kinds."""
    if not isinstance(kind, str):
        return None
    return next((slot for slot, kinds in SLOTS.items() if kind in kinds and kind != "none"), None)


def _default_color(kind):
    """A new item's colour: brass frames, a navy cap, a red neckerchief, an oilskin-yellow jacket."""
    if kind in ("spectacles", "goggles"):
        return list(BRASS)
    return list(CLOTH_SWATCHES[{"head": 2, "neck": 1}.get(_slot_of(kind), 0)][1])


def saved(state) -> dict:
    """The Skipper's saved look on a live state (normalized), without changing the save."""
    v2 = getattr(state, "v2", None)
    look = v2.get("skipper") if isinstance(v2, dict) else None
    return normalize({"skipper": look})


def name(state) -> str:
    """The Skipper's display name: the `{Skipper}` placeholder in dialogue and letters."""
    return saved(state)["name"]


def appearance(look: dict, pose: str = "helm") -> dict:
    """A full npcs.json-style appearance for the cat rig from a Skipper look.

    Args:
        look: A normalized Skipper look (`normalize` / `saved`).
        pose: An authored catmesh pose; the Skipper holds no prop, so "helm",
            "wave" or "nap_curl" (a pose whose prop may be "none").

    Returns:
        A new dict the content validator accepts (`cat_look`), with fixed
        size, build, legs and whiskers.
    """
    return {"breed": "Skipper", "size": 1.0, "build": 1.0, "legs": 1.0, "coat": look["coat"],
            "ears": look["ears"], "tail": look["tail"], "pattern": look["pattern"],
            "colors": {key: list(look["colors"][key]) for key in ("base", "secondary", "accent")},
            "eyes": list(look["eyes"]), "whiskers": 1.0,
            "attire": [{"kind": item["kind"], "color": list(item["color"])} for item in look["attire"]],
            "pose": pose, "prop": "none"}


# --- The creator's rows ---------------------------------------------------------

def _nearest(swatches, rgb) -> int:
    return min(range(len(swatches)), key=lambda i: sum((a - b) ** 2 for a, b in zip(swatches[i][1], rgb)))


def _item(look, slot):
    return next((item for item in look["attire"] if _slot_of(item["kind"]) == slot), None)


def value_label(look: dict, key: str) -> str:
    """The value shown on a creator row for `key` (one of ROWS)."""
    if key == "name":
        return look["name"]
    if key == "pattern":
        return PATTERN_LABELS[look["pattern"]]
    if key in ("base", "secondary", "accent"):
        return COAT_SWATCHES[_nearest(COAT_SWATCHES, look["colors"][key])][0]
    if key == "eyes":
        return EYE_SWATCHES[_nearest(EYE_SWATCHES, look["eyes"])][0]
    if key in ("ears", "tail", "coat"):
        return {"ears": EARS, "tail": TAILS, "coat": COATS}[key][look[key]]
    if key in SLOTS:
        item = _item(look, key)
        return SLOTS[key][item["kind"] if item else "none"]
    if key in COLOR_ROWS:
        item = _item(look, key[:4])
        if item is None:
            return "—"
        if item["kind"] in ("spectacles", "goggles"):
            return FRAME_FINISHES[_nearest(FRAME_FINISHES, item["color"])][0]
        return CLOTH_SWATCHES[_nearest(CLOTH_SWATCHES, item["color"])][0]
    return ""


def row_enabled(look: dict, key: str) -> bool:
    """Whether a row changes what the cat looks like right now (unused colours are dimmed)."""
    if key in ("base", "secondary", "accent"):
        return key in PATTERN_COLORS[look["pattern"]]
    if key in COLOR_ROWS:
        item = _item(look, key[:4])
        return item is not None
    return True


def _cycle(options, current, step):
    options = list(options)
    index = options.index(current) if current in options else 0
    return options[(index + step) % len(options)]


def cycle(look: dict, key: str, step: int) -> dict:
    """A new look with row `key` moved `step` options (±1) along its list.

    The name row steps through NAME_SUGGESTIONS (the gamepad's way to name the
    cat); typed names use `type_name`. Rows without options return a copy.
    """
    from .catmesh import PATTERNS
    out = deepcopy(look)
    if key == "name":
        out["name"] = _cycle(NAME_SUGGESTIONS, out["name"], step)
    elif key == "pattern":
        out["pattern"] = _cycle(PATTERNS, out["pattern"], step)
    elif key in ("base", "secondary", "accent"):
        index = (_nearest(COAT_SWATCHES, out["colors"][key]) + step) % len(COAT_SWATCHES)
        out["colors"][key] = list(COAT_SWATCHES[index][1])
    elif key == "eyes":
        out["eyes"] = list(EYE_SWATCHES[(_nearest(EYE_SWATCHES, out["eyes"]) + step) % len(EYE_SWATCHES)][1])
    elif key in ("ears", "tail", "coat"):
        out[key] = _cycle({"ears": EARS, "tail": TAILS, "coat": COATS}[key], out[key], step)
    elif key in SLOTS:
        item = _item(out, key)
        kind = _cycle(SLOTS[key], item["kind"] if item else "none", step)
        # Keep the slot's colour when changing what is worn in it.
        colour = item["color"] if item and kind not in ("spectacles", "goggles") and item["kind"] not in (
            "spectacles", "goggles") else _default_color(kind)
        out["attire"] = [i for i in out["attire"] if _slot_of(i["kind"]) != key]
        if kind != "none":
            out["attire"].append({"kind": kind, "color": list(colour)})
            # A stable order (head, neck, body) keeps attire tags, and so the mesh cache key, steady.
            out["attire"].sort(key=lambda i: tuple(SLOTS).index(_slot_of(i["kind"])))
    elif key in COLOR_ROWS:
        item = _item(out, key[:4])
        if item is not None:
            swatches = FRAME_FINISHES if item["kind"] in ("spectacles", "goggles") else CLOTH_SWATCHES
            index = (_nearest(swatches, item["color"]) + step) % len(swatches)
            item["color"] = list(swatches[index][1])
    return out


# Key names (gamepad.KEY_NAMES) that type into the name, and what they type.
NAME_KEYS = {**{c: c for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
             "space": " ", "minus": "-", "apostrophe": "'", "period": "."}


def type_name(current: str, keys) -> str:
    """The name after typing `keys` (key names in press order) at its end.

    Letters start words in capitals; "backspace" deletes the last character. The
    result can be empty while typing; `clean_name` restores the default on confirm.
    """
    text = current
    for key in keys:
        if key == "backspace":
            text = text[:-1]
        elif key in NAME_KEYS and len(text) < NAME_MAX:
            char = NAME_KEYS[key]
            text += char.upper() if char.isalpha() and (not text or text[-1] in " -.") else char
    return text
