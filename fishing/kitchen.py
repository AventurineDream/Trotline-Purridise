"""Pantry transactions and fish-safe cooking, shared by landing and galley UI."""

from dataclasses import dataclass

from . import comfort
from .data import (BAIT_BY_ID, BAIT_RECIPES, DISHES, DISH_CARD_PRICE, DOZEN,
                   PANTRY, PANTRY_CAPACITY, SPECIES_BY_ID)


def at_landing(state, world):
    return state.slip_status(world) == 'docked' and abs(state.speed) < .45


def can_cook(state, world):
    return at_landing(state, world) or ('galley' in state.boat.traits and state.anchored)


def chapter(state):
    value = state.v2.get('story', {}).get('chapter', 0)
    return value if type(value) is int and value >= 0 else 0


def card_available(state, dish):
    completed = state.v2.get('story', {}).get('completed_chapters', [])
    return chapter(state) > dish.chapter or (isinstance(completed, list) and dish.chapter in completed)


def teach(state, npc_id):
    """Host chapter teaching and clue-teller cards; repeat conversations are inert."""
    learned = []
    for dish in DISHES.values():
        if dish.host == npc_id and chapter(state) == dish.chapter and dish.id not in state.v2['dishes_known']:
            state.v2['dishes_known'].append(dish.id)
            learned.append(dish.name)
    for bait_id, recipe in BAIT_RECIPES.items():
        if recipe.teller == npc_id and bait_id not in state.v2['recipes']:
            state.v2['recipes'].append(bait_id)
            learned.append(BAIT_BY_ID[bait_id].name + ' recipe')
    for name in learned:
        state.toast('Learned: ' + name + '.')
    return bool(learned)


def buy_ingredient(state, world, item_id):
    item = PANTRY.get(item_id)
    if item is None or not at_landing(state, world):
        return 'Buy pantry items at a landing.'
    if item.lake not in ('all', world.id):
        return 'This host sells their own specialty ingredient.'
    pantry = state.v2['pantry']
    if pantry.get(item_id, 0) >= PANTRY_CAPACITY:
        return f'The pantry holds {PANTRY_CAPACITY} of each item.'
    if state.money < item.price:
        return 'Not enough cash.'
    state._spend(item.price)
    pantry[item_id] = pantry.get(item_id, 0) + 1
    state.toast('Aboard: ' + item.name + '.')
    return None


def buy_card(state, world, dish_id):
    dish = DISHES.get(dish_id)
    if dish is None or not at_landing(state, world) or PANTRY[dish.ingredient].lake != world.id:
        return 'Ask the dish\'s host at their landing.'
    if dish_id in state.v2['dishes_known']:
        return 'You already know this dish.'
    if not card_available(state, dish):
        return f'This card follows chapter {dish.chapter}.'
    if state.money < DISH_CARD_PRICE:
        return 'Not enough cash.'
    state._spend(DISH_CARD_PRICE)
    state.v2['dishes_known'].append(dish_id)
    return None


def eligible_fish(state, food):
    """Only ordinary food fish, with a stable smallest-first automatic choice."""
    result = []
    for index, fish in enumerate(state.well):
        species = SPECIES_BY_ID.get(fish.species)
        if (species is None or fish.shiny or fish.treasured or fish.legendary
                or 'protected' in species.tags or species.food == 'none'):
            continue
        if food == 'any' or species.food == food:
            result.append(index)
    return sorted(result, key=lambda i: (state.well[i].weight, i))


def dish_error(state, world, dish_id, fish_index=None):
    dish = DISHES.get(dish_id)
    if dish is None or dish_id not in state.v2['dishes_known']:
        return 'Learn this dish from its host or buy its card after the chapter.'
    if not can_cook(state, world):
        return 'Cook at a landing, or anchor a boat with a galley.'
    if state.v2['pantry'].get(dish.ingredient, 0) < 1:
        return 'Need one ' + PANTRY[dish.ingredient].name + '.'
    fish = eligible_fish(state, dish.food)
    if not fish or (fish_index is not None and fish_index not in fish):
        return 'Need an ordinary ' + dish.food + ' food fish. Special fish stay safe.'
    return None


def cook_dish(state, world, dish_id, fish_index=None):
    error = dish_error(state, world, dish_id, fish_index)
    if error:
        return error
    dish = DISHES[dish_id]
    chosen = eligible_fish(state, dish.food)[0] if fish_index is None else fish_index
    state.well.pop(chosen)
    state.v2['pantry'][dish.ingredient] -= 1
    comfort.serve_dish(state, dish)
    state.emit_quest_event({'type': 'cook_dish', 'dish_id': dish_id,
                            'lake_id': world.id, 'game_minute': state.game_minutes})
    return None


def recipe_error(state, world, bait_id):
    recipe = BAIT_RECIPES.get(bait_id)
    if recipe is None or bait_id not in state.v2['recipes']:
        return 'Learn this recipe from its legendary clue teller.'
    if not can_cook(state, world):
        return 'Cook at a landing, or anchor a boat with a galley.'
    if state.v2['pantry'].get(recipe.ingredient, 0) < 1:
        return 'Need one ' + PANTRY[recipe.ingredient].name + '.'
    if any(state.bait.get(parent, 0) < 1 for parent in recipe.parents):
        return 'Need one piece of each parent bait.'
    # Two pieces leave the bait box before the dozen is added.
    if state.bait_count() - 2 + DOZEN > state.box_cap():
        return 'Make room for the cooked dozen in the bait box.'
    return None


def cook_bait(state, world, bait_id):
    error = recipe_error(state, world, bait_id)
    if error:
        return error
    recipe = BAIT_RECIPES[bait_id]
    for parent in recipe.parents:
        state.bait[parent] -= 1
    state.v2['pantry'][recipe.ingredient] -= 1
    state.bait[bait_id] = state.bait.get(bait_id, 0) + DOZEN
    return None


def snack(state):
    if state.v2['pantry'].get('kibble', 0) < 1:
        return 'No Kibble Tin aboard. All landing hosts sell them.'
    state.v2['pantry']['kibble'] -= 1
    comfort.meal(state.v2)
    state.toast('A Kibble Tin. A little meal; your picnic buff stays.')
    return None


@dataclass(frozen=True)
class MenuRow:
    label: str
    right: str
    blurb: str
    enabled: bool
    kind: str
    arg: str = ''


def rows(state, world):
    """Read-only menu model; purchases and learning happen only on input."""
    result = [MenuRow('Eat Kibble Tin', f"{state.v2['pantry'].get('kibble', 0)} aboard",
                      'A meal without replacing your picnic buff.',
                      state.v2['pantry'].get('kibble', 0) > 0, 'snack'),
              MenuRow('Ask Bot about nearby water', 'Mark',
                      'Bot marks favorable water once a day; tacos allow one extra. Quiet if none is nearby.', True, 'weather')]
    landing = at_landing(state, world)
    for item in PANTRY.values():
        if item.lake in ('all', world.id):
            count = state.v2['pantry'].get(item.id, 0)
            result.append(MenuRow('Buy ' + item.name, f'${item.price:.0f} · {count}/{PANTRY_CAPACITY}',
                                  'One pantry item. Each host sells their specialty and Kibble Tins.',
                                  landing and count < PANTRY_CAPACITY, 'ingredient', item.id))
    for dish in DISHES.values():
        if dish.id in state.v2['dishes_known']:
            error = dish_error(state, world, dish.id)
            fish = eligible_fish(state, dish.food)
            choice = state.well[fish[0]] if fish else None
            picked = (f' Uses {choice.weight:.1f} lb {SPECIES_BY_ID[choice.species].name}; choose another before cooking.'
                      if choice is not None else '')
            result.append(MenuRow(dish.name, 'Cook', error or dish.blurb + picked,
                                  error is None, 'dish', dish.id))
        elif PANTRY[dish.ingredient].lake == world.id:
            if chapter(state) == dish.chapter:
                result.append(MenuRow('Learn ' + dish.name, 'From host',
                                      'Your host teaches this dish during the chapter.', landing, 'teach', dish.host))
            else:
                ready = card_available(state, dish)
                result.append(MenuRow(dish.name + ' card', f'${DISH_CARD_PRICE:.0f}' if ready else f'Chapter {dish.chapter}',
                                      f'Ask the host during chapter {dish.chapter}; cards are sold after it.',
                                      landing and ready, 'dish_card', dish.id))
    for bait_id, recipe in BAIT_RECIPES.items():
        if bait_id in state.v2['recipes']:
            error = recipe_error(state, world, bait_id)
            inputs = ' + '.join(BAIT_BY_ID[parent].name for parent in recipe.parents)
            result.append(MenuRow(BAIT_BY_ID[bait_id].name, 'Cook 12',
                                  error or inputs + ' + ' + PANTRY[recipe.ingredient].name + '.',
                                  error is None, 'recipe', bait_id))
        elif PANTRY[recipe.ingredient].lake == world.id:
            result.append(MenuRow(BAIT_BY_ID[bait_id].name, 'Recipe',
                                  'Ask ' + recipe.teller.replace('_', ' ').title() + ' for the recipe card.',
                                  False, 'recipe', bait_id))
    return result
