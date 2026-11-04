"""V1-39: the same seed gives the same NPC schedule, Bot name, shiny rolls and weather plan
across a save and reload, and across lake switches (06 §0.3, §9)."""
from functools import lru_cache
from pathlib import Path
import tempfile
import unittest

from . import botidentity, calendar
from .book import SPECIES_RUMORS, roll_shiny
from .content import load_content
from .npcs import present_ids
from .savepaths import load_game_save, merge_v2_defaults
from .sim import State
from .world import World

SEED = 1939
LAKES = ("briar", "cedar")
DAY_SAMPLES = [minute for minute in range(0, 3 * 1440, 90)]   # every 90 game minutes, three days
WEATHER_SAMPLES = [minute for minute in range(0, 7 * 1440, 60)]  # one forecast point per hour, a week


@lru_cache(maxsize=None)
def _world(lake: str) -> World:
    """One charted world per lake: building a lake takes about a second."""
    return World(lake)


def _state(lake: str = "briar", seed: int = SEED) -> State:
    world = _world(lake)
    state = State.new(world, seed=seed)
    # The saved seeds drive the schedule and the forecast; set them explicitly so the test
    # does not depend on which fallback State.new uses.
    state.narrative.schedule_seed = seed
    # Defaults (the Bot's profile name included) are built from the schedule seed, as in a new save.
    state.v2 = merge_v2_defaults(state, {})
    state.v2.setdefault("calendar", {})["seed"] = seed
    return state


def _schedule(state: State, world: World, content) -> list:
    rows = []
    for minute in DAY_SAMPLES:
        state.game_minutes = minute
        rows.append(present_ids(state, world, content))
    return rows


def _weather(state: State) -> list:
    return [calendar.weather_at(state, minute) for minute in WEATHER_SAMPLES]


def _shiny_rolls(state: State, count: int, offset: int = 0) -> list:
    species = list(SPECIES_RUMORS)
    rolls = []
    for step in range(offset, offset + count):
        sid = species[(step * 7) % len(species)]
        rolls.append(roll_shiny(state.v2["book"], state.journal, sid, state.rng))
    return rolls


class SeedReproducibility(unittest.TestCase):
    def setUp(self):
        self.content = load_content()
        self.temp = tempfile.TemporaryDirectory(prefix="determinism-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "save.json"

    def _reload(self, state: State, lake: str) -> State:
        """Save, then load through the same path the game uses on startup."""
        state.save(self.path)
        world, loaded, has_save = load_game_save(self.path, State, _world)
        self.assertTrue(has_save)
        self.assertEqual(world.id, lake)
        return loaded

    def test_npc_schedule_is_the_same_after_save_reload_and_lake_switches(self):
        state = _state("briar")
        first = _schedule(state, _world("briar"), self.content)
        self.assertTrue(any(first), "the schedule should place someone on the lake")
        reloaded = self._reload(state, "briar")
        self.assertEqual(_schedule(reloaded, _world("briar"), self.content), first)
        # Switch lakes and back: the cast on each lake is a pure function of the seed and clock.
        cedar_before = _schedule(_state("cedar"), _world("cedar"), self.content)
        reloaded.bind(_world("cedar"))
        self.assertEqual(_schedule(reloaded, _world("cedar"), self.content), cedar_before)
        reloaded.bind(_world("briar"))
        self.assertEqual(_schedule(reloaded, _world("briar"), self.content), first)

    def test_bot_name_is_the_same_after_save_reload_and_lake_switches(self):
        state = _state("briar")
        name = botidentity.name(state)
        self.assertRegex(name, r"^[A-Za-z][A-Za-z0-9]*-[0-9]{3}$")
        self.assertEqual(name, botidentity.generated_name(SEED))
        reloaded = self._reload(state, "briar")
        self.assertEqual(botidentity.name(reloaded), name)
        reloaded.bind(_world("cedar"))
        self.assertEqual(botidentity.name(reloaded), name)
        self.assertEqual(botidentity.name(_state("cedar")), name)

    def test_shiny_roll_sequence_continues_identically_after_save_reload_and_lake_switch(self):
        uninterrupted = _shiny_rolls(_state("briar"), 240)
        self.assertTrue(any(uninterrupted) and not all(uninterrupted))
        state = _state("briar")
        head = _shiny_rolls(state, 80)
        reloaded = self._reload(state, "briar")
        reloaded.bind(_world("cedar"))
        middle = _shiny_rolls(reloaded, 80, offset=80)
        reloaded.bind(_world("briar"))
        tail = _shiny_rolls(reloaded, 80, offset=160)
        self.assertEqual(head + middle + tail, uninterrupted)

    def test_weather_plan_over_a_week_is_the_same_across_reloads_and_lake_switches(self):
        for lake in LAKES:
            state = _state(lake)
            first = _weather(state)
            self.assertGreater(len(set(first)), 1, lake)
            reloaded = self._reload(state, lake)
            self.assertEqual(_weather(reloaded), first, lake)
            other = "cedar" if lake == "briar" else "briar"
            reloaded.bind(_world(other))
            reloaded.bind(_world(lake))
            self.assertEqual(_weather(reloaded), first, lake)

    def test_a_different_seed_gives_a_different_plan(self):
        self.assertNotEqual(_weather(_state("briar", SEED)), _weather(_state("briar", SEED + 1)))


if __name__ == "__main__":
    unittest.main()
