"""Every screen UI.draw can show, each with real content (V1-06, V1-43).

The layout and contrast tests draw each of these at the largest text size, and
`python -m fishing --shots <dir> --ui-matrix` draws each at every text size, for keyboard
and gamepad and pointer (uishots.py), including shared row focus and action-button outlines.
"""

from __future__ import annotations

from types import SimpleNamespace

from . import comfort, skipperlook
from .data import BAIT_RECIPES, DISHES, PANTRY
from .sim import Catch, Hook, SetLine, State
from .ui import HELP_SPREADS, SHOP_TABS, SPECIES, UIState, pause_options
from .world import World

LARGEST_TEXT = 2


def settled_state(world, seed, dyslexia_font, text_size=LARGEST_TEXT):
    state = State.new(world, seed=seed)
    state.v2["settings"]["text_size"] = text_size
    state.v2["settings"]["dyslexia_font"] = dyslexia_font
    return state


def kitchen_state(world, dyslexia_font, text_size=LARGEST_TEXT):
    """A pantry stocked with every dish and recipe, and fish in the well to cook with."""
    state = settled_state(world, 43015, dyslexia_font, text_size)
    state.money = 600
    state.v2["dishes_known"] = list(DISHES)
    state.v2["recipes"] = list(BAIT_RECIPES)
    state.v2["pantry"] = {item: 4 for item in PANTRY}
    state.bait.update({bait: 1 for recipe in BAIT_RECIPES.values() for bait in recipe.parents})
    state.well = [Catch("bluegill", .9, 1, 0, "flats", "worm", 8),
                  Catch("bluegill", 2, 1, 0, "flats", "worm", 8)]
    comfort.serve_dish(state, DISHES["pecan_chowder"])
    state.toasts.clear()
    state.tutorial = 4
    return state


def haul_state(world, dyslexia_font, *, fish=False, shiny=False, text_size=LARGEST_TEXT):
    """A line with twelve hooks; the fish and the shiny sit on the hooks the panels show."""
    state = settled_state(world, 17 + int(fish) + int(shiny), dyslexia_font, text_size)
    state.toasts.clear()
    state.tutorial = 4
    hooks = [Hook(True) for _ in range(12)]
    if fish:
        catch = Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0, shiny=shiny)
        hooks[0] = Hook(False, catch)
        state._note_journal(catch)
    if shiny:
        shiny_catch = Catch("channel", 2.4, 1.0, 0.0, "flats", "worm", 8.0, shiny=True)
        hooks[5] = Hook(False, shiny_catch)
        state._note_journal(shiny_catch)
    state.lines = [SetLine("std", "worm", state.x + 6, state.z + 6,
                           state.x + 44, state.z + 10, "flats", hooks)]
    return state

def skipper_look(name: str = "Mochi") -> dict:
    """A Skipper look that uses most creator rows (a calico in a cap, a scarf and a parka)."""
    return skipperlook.normalize({"skipper": {
        "name": name, "pattern": "calico", "ears": "tufted", "tail": "plume", "coat": "long",
        "colors": {"base": [0.88, 0.54, 0.22], "secondary": [0.20, 0.20, 0.22], "accent": [0.95, 0.94, 0.91]},
        "eyes": [0.48, 0.74, 0.30],
        "attire": [{"kind": "cap", "color": [0.16, 0.22, 0.40]}, {"kind": "scarf", "color": [0.72, 0.20, 0.20]},
                   {"kind": "parka", "color": [0.93, 0.74, 0.16]}],
    }})


def screens(ui, world, dyslexia_font, text_size=LARGEST_TEXT):
    """Return real-content (name, state, UIState) fixtures for every rendered screen.

    ``ui`` supplies authored content and ``world`` the lake; font and text-size
    settings select the same layout inputs as play. No input is routed or saved.
    """
    from . import legendshots
    from .bookview import BOOK_TABS, ENTRY_IDS
    from .kitchen import rows as kitchen_rows
    screens = []

    def add(name, state, panel):
        screens.append((name, state, panel))

    base = settled_state(world, 51, dyslexia_font, text_size)
    add("title", base, UIState(mode="title", has_save=True))
    add("title new game", base, UIState(mode="title", has_save=False))
    add("title confirmation", base, UIState(mode="title", has_save=True, confirm_new=True))
    add("play", base, UIState(mode="play"))
    add("map", base, UIState(mode="map"))
    add("dialogue", base, UIState(
        mode="dialogue",
        conversation=SimpleNamespace(
            npc_id=next(iter(ui.narrative_content.npcs)),
            node_id=next(iter(ui.narrative_content.dialogue)),
            selected=0,
        ),
        dialogue_content=ui.narrative_content,
    ))
    for tab in range(len(SHOP_TABS)):
        add(f"shop {SHOP_TABS[tab]}", base, UIState(mode="shop", shop_tab=tab, shop_i=0))
    add("setbait", base, UIState(mode="setbait"))
    add("setbait sections", base, UIState(mode="setbait", set_sections=3, set_section=1,
                                          set_section_baits=(0, 1, 2)))

    haul = haul_state(world, dyslexia_font, fish=True, shiny=True, text_size=text_size)
    add("haul rise", haul_state(world, dyslexia_font, fish=True, text_size=text_size), UIState(
        mode="haul", check_line=0, haul_index=6, haul_timer=0.13,
        haul_counts_before={"bluegill": 0}))
    add("haul surface", haul_state(world, dyslexia_font, fish=True, text_size=text_size), UIState(
        mode="haul", check_line=0, haul_index=0, haul_phase="surface",
        haul_counts_before={"bluegill": 0}))
    add("haul card", haul_state(world, dyslexia_font, fish=True, text_size=text_size), UIState(
        mode="haul", check_line=0, haul_index=0, haul_phase="card",
        haul_counts_before={"bluegill": 0}))
    add("haul shiny card", haul_state(world, dyslexia_font, shiny=True, text_size=text_size), UIState(
        mode="haul", check_line=0, haul_index=5, haul_phase="card",
        haul_counts_before={"channel": 0}))
    add("haul empty hook", base, UIState(mode="haul", check_line=0, haul_index=0))
    add("haul summary", haul, UIState(mode="check", check_line=0, check_i=0))
    add("check", base, UIState(mode="check"))

    # The legendary encounter: its hook, the scene as it holds, and its book page.
    legend_world = World("briar")
    legend_state = legendshots._staged(legend_world, "old_lantern")
    legend_state.v2["settings"]["text_size"] = text_size
    legend_state.v2["settings"]["dyslexia_font"] = dyslexia_font
    add("legendary rise", legend_state, legendshots._panel("old_lantern", "rise", 0.0))
    add("legendary encounter", legend_state, legendshots._panel("old_lantern", "encounter", 4.6))
    add("legendary card", legend_state, legendshots._panel("old_lantern", "card", 0.0))

    kitchen = kitchen_state(world, dyslexia_font, text_size)
    dish_row = next(i for i, row in enumerate(kitchen_rows(kitchen, world))
                    if row.arg == "pan_fritters")
    add("kitchen menu", kitchen, UIState(mode="kitchen", shop_i=dish_row))
    add("kitchen landing", kitchen, UIState(mode="shop", shop_tab=SHOP_TABS.index("Kitchen")))
    add("cook dish", kitchen, UIState(
        mode="cook_confirm", cook_kind="dish", cook_arg="pan_fritters",
        cook_label="Sunny Pan Fritters", cook_fish=1))
    add("cook recipe", kitchen, UIState(
        mode="cook_confirm", cook_kind="recipe", cook_arg="lantern_liver",
        cook_label="Lantern Liver"))
    add("cook share", kitchen, UIState(
        mode="cook_confirm", cook_kind="cookout", cook_label="Cookout"))
    add("cooking", kitchen, UIState(
        mode="cooking", cook_label="Sunny Pan Fritters", cook_timer=1,
        cook_text=DISHES["pan_fritters"].blurb))

    add("pick a pace: cozy", base, UIState(mode="new_mode", new_mode_i=0))
    add("pick a pace: old salt", base, UIState(mode="new_mode", new_mode_i=1))
    salty = settled_state(world, 52, dyslexia_font, text_size)
    salty.v2["settings"]["mode"] = "old_salt"
    add("needs energy", salty, UIState(mode="needs", needs_kind="energy", comfort_i=0))
    add("needs hunger", salty, UIState(mode="needs", needs_kind="hunger", comfort_i=1))
    add("catnap", base, UIState(mode="catnap", nap_timer=1.0))
    add("catnap forced", base, UIState(mode="catnap", nap_timer=1.0, nap_forced=True))
    add("credits", base, UIState(mode="credits", credits_s=0.0))

    for shelf in range(3):
        add(f"journal trophy shelf {shelf + 1}", base, UIState(
            mode="journal", journal_page=2, book_shelf=shelf, book_collection_i=0))
    # Every species caught, so each Fish and Book entry (and its next page) has real text.
    caught = settled_state(world, 74, dyslexia_font, text_size)
    for index, species in enumerate(SPECIES):
        caught.journal[species.id] = {
            "count": 3 + index % 4, "best": 2.1, "lake_id": "briar", "zone": "flats",
            "bait": "worm", "band": "trophy",
        }
    for tab in range(len(BOOK_TABS)):
        add(f"journal {BOOK_TABS[tab]}", caught, UIState(
            mode="journal", journal_page=tab, journal_i=0, book_entry_i=0,
            journal_quest_i=0, book_week_i=0, book_watch_i=0))
    for entry in range(len(ENTRY_IDS)):
        add(f"book entry {entry + 1}", caught, UIState(
            mode="journal", journal_page=1, book_entry_i=entry, book_detail_page=0))
    add("species detail next page", caught, UIState(mode="journal", journal_page=1,
                                                    book_entry_i=0, book_detail_page=1))
    add("species detail on the Fish tab", caught, UIState(mode="journal", journal_page=0,
                                                          journal_i=0))
    add("well", base, UIState(mode="well"))
    well = settled_state(world, 75, dyslexia_font, text_size)
    well.well = [Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0)]
    add("well with a fish", well, UIState(mode="well", well_i=0))
    add("pause", base, UIState(mode="pause"))
    add("pause scrolled", base, UIState(mode="pause", pause_i=len(pause_options(base)) - 1))
    add("settings", base, UIState(mode="settings"))
    add("settings volume", base, UIState(mode="settings", settings_i=7))
    add("keyboard controls", base, UIState(mode="settings", settings_page="keys", key_binding_i=0))
    add("keyboard controls scrolled", base, UIState(
        mode="settings", settings_page="keys", key_binding_i=29))
    add("keyboard capture", base, UIState(mode="settings", settings_page="keys", capturing_key=True))
    # The Skipper creator: from the pause menu, a look with most rows in use; typing its name; and
    # the same creator as a new morning's (Done there starts the game).
    add("your skipper", base, UIState(mode="skipper", skipper_origin="pause", skipper_look=skipper_look(),
                                      skipper_i=1))
    add("your skipper typing", base, UIState(mode="skipper", skipper_origin="pause",
                                             skipper_look=skipper_look("Mo"), skipper_i=0, skipper_typing=True))
    add("your skipper new morning", base, UIState(mode="skipper", skipper_origin="new",
                                                  skipper_look=skipper_look()))
    # The Field Guide notebook (#139): its opening spread, one from the middle, and the last,
    # which help_spread -1 wraps to however many spreads the text size makes.
    add("help opening spread", base, UIState(mode="help"))
    add("help middle spread", base, UIState(mode="help", help_spread=HELP_SPREADS // 2))
    add("help final spread", base, UIState(mode="help", help_spread=-1))
    return screens
