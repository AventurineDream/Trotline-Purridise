"""V1-37 part 2: trophy replicas, their rails, and the book's Trophy page."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import replica
from .boat import BOATS
from .boatfamilies import _Mesh, family_faces, rail_centre
from .bookview import collection_rows, rail_status, trophy_items
from .content import load_content
from .game import Keys, Session
from .legendary import LEGENDARY_DATA
from .sim import Catch, State
from .world import World


def _caught(state, legendary_id):
    row = LEGENDARY_DATA[legendary_id]
    state._note_journal(Catch(legendary_id, row["weight_lb"], 1.0, 0.0, "open", row["bait"], 21.0, legendary=True))


def _shiny(state, species_id="bluegill"):
    state._note_journal(Catch(species_id, 0.8, 1.0, 0.0, "flats", "worm", 9.0, shiny=True))


def _aboard(world, boat_id="deepv_skiff", seed=7):
    state = State.new(world, seed=seed)
    state.owned_boats = list(dict.fromkeys(list(state.owned_boats) + [boat_id]))
    state.boat_id = boat_id
    return state


class Model(unittest.TestCase):
    def test_the_carved_fish_runs_snout_to_tail_with_its_own_outline(self):
        for item in ("old_lantern", "nebula_weaver", "bluegill"):
            cols = replica.silhouette(item)
            self.assertEqual(len(cols), replica.COLUMNS)
            self.assertEqual([c[0] for c in cols], sorted(c[0] for c in cols))  # snout first
            self.assertTrue(all(top >= bottom for _x, top, bottom in cols), item)
            self.assertLessEqual(max(c[0] for c in cols), 1.0)
        self.assertNotEqual(replica.silhouette("old_lantern"), replica.silhouette("nebula_weaver"))

    def test_one_replica_is_a_small_plaque_facing_the_cockpit(self):
        m = _Mesh()
        replica.rail_faces(m, "legendary", "caldera_fire_lizard", (0.0, 0.0, 0.0), (0, 0, 1), (1, 0, 0))
        self.assertLessEqual(len(m.faces), 30)
        pts = np.concatenate([f.pts for f in m.faces])
        length, height, depth = replica.PLAQUE
        self.assertLessEqual(float(np.ptp(pts[:, 2])), length + 1e-5)
        self.assertLessEqual(float(np.ptp(pts[:, 1])), height + 1e-5)
        self.assertGreaterEqual(float(pts[:, 0].min()), -1e-6)  # nothing behind the rail's side
        colours = {tuple(np.round(f.color, 3)) for f in m.faces}
        self.assertIn(tuple(np.round(np.asarray(replica.BRASS, np.float32), 3)), colours)

    def test_the_trophy_page_picture_is_cached_and_read_only(self):
        for kind, item in (("legendary", "obsidian_gar"), ("shiny", "bluegill")):
            image = replica.picture(kind, item, 240, 150)
            self.assertEqual(image.shape, (150, 240, 3))
            self.assertFalse(image.flags.writeable)
            self.assertIs(replica.picture(kind, item, 240, 150), image)
        self.assertFalse(np.array_equal(replica.picture("legendary", "obsidian_gar", 240, 150),
                                        replica.picture("legendary", "lily_queen", 240, 150)))


class Mounting(unittest.TestCase):
    def setUp(self):
        self.world = World("briar")
        self.state = _aboard(self.world)

    def test_a_caught_legendary_hangs_on_a_rail_and_the_book_is_untouched(self):
        self.assertIn("Record", self.state.mount_legendary_replica("old_lantern"))  # not caught yet
        _caught(self.state, "old_lantern")
        page = deepcopy(self.state.v2["legendaries"])
        self.assertIsNone(self.state.mount_legendary_replica("old_lantern"))
        self.assertIsNone(self.state.mount_legendary_replica("old_lantern"))  # once only
        self.assertEqual(self.state.rail_trophies(), [("legendary", "old_lantern")])
        self.assertEqual(self.state.v2["legendaries"], page)
        self.assertIn("trophy rail", self.state.mount_legendary_replica("old_lantern", boat_id="jon"))
        self.assertIn("own", self.state.mount_legendary_replica("old_lantern", boat_id="houseboat"))

    def test_a_witnessed_legendary_has_no_replica(self):
        self.state.v2["legendaries"]["star_whale"] = {"records": [{"witnessed": True, "game_minute": 0}]}
        self.assertIsNotNone(self.state.mount_legendary_replica("star_whale"))
        self.assertEqual(trophy_items(self.state)[0][:2], ("witnessed", "star_whale"))
        self.assertEqual(rail_status(self.state, "witnessed", "star_whale"), "")

    def test_the_rail_holds_four_shinies_and_replicas_together_and_survives_a_save(self):
        for legendary_id in ("old_lantern", "lily_queen", "glacial_phantom"):
            _caught(self.state, legendary_id)
            self.assertIsNone(self.state.mount_legendary_replica(legendary_id))
        _shiny(self.state)
        self.assertIsNone(self.state.mount_shiny_trophy("bluegill"))
        _caught(self.state, "obsidian_gar")
        self.assertIn("holds 4", self.state.mount_legendary_replica("obsidian_gar"))
        self.assertTrue(self.state.unmount_trophy("legendary", "lily_queen"))
        self.assertFalse(self.state.unmount_trophy("legendary", "lily_queen"))
        self.assertIsNone(self.state.mount_legendary_replica("obsidian_gar"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "save.json"
            self.state.save(path, update_stamp=False)
            loaded = State.load(path, self.world)
        self.assertEqual(loaded.rail_trophies(), self.state.rail_trophies())
        self.assertEqual(len(loaded.rail_trophies()), 4)

    def test_mounted_replicas_are_drawn_on_the_rail_and_unknown_ones_are_skipped(self):
        bare = len(family_faces(self.state))
        _caught(self.state, "old_lantern")
        _shiny(self.state)
        self.state.mount_legendary_replica("old_lantern")
        self.state.mount_shiny_trophy("bluegill")
        hung = family_faces(self.state)
        self.assertGreater(len(hung), bare + 20)
        self.assertLessEqual(len(hung), bare + 2 * 30)
        # A save naming a fish this build doesn't know still draws the boat.
        self.state.v2["boat_extras"]["deepv_skiff"]["legendary_replicas"].append("no_such_fish")
        self.assertEqual(len(family_faces(self.state)), len(hung))

    def test_every_boat_with_the_trait_draws_its_rail(self):
        for boat_id, model in BOATS.items():
            if "trophy_rail" not in model.traits:
                self.assertIsNone(rail_centre(model), boat_id)
                continue
            state = _aboard(self.world, boat_id)
            _caught(state, "old_lantern")
            self.assertIsNone(state.mount_legendary_replica("old_lantern"))
            bare = _aboard(self.world, boat_id)
            self.assertGreater(len(family_faces(state)), len(family_faces(bare)), boat_id)  # pontoons too
            view = replica.rail_view(state, 96)
            self.assertEqual(view.shape, (96, 96, 3), boat_id)
        self.assertIsNone(replica.rail_view(State.new(self.world, seed=1), 96))  # the jon has no rail


class TrophyPage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.world = World("briar")
        state = _aboard(self.world)
        _caught(state, "caldera_fire_lizard")
        _shiny(state)
        with patch("fishing.game.load_content", return_value=load_content()):
            self.session = Session(self.world, Path(tmp.name) / "save.json", state, True)
        self.session.ui.mode = "journal"
        self.session.ui.journal_page, self.session.ui.book_shelf = 2, 2

    def test_the_shelf_rows_and_the_trophy_items_agree(self):
        items = trophy_items(self.session.state)
        self.assertEqual([row[2:] for row in items], collection_rows(self.session.state, None, 2))
        self.assertEqual([i[:2] for i in items], [("legendary", "caldera_fire_lizard"), ("shiny", "bluegill")])
        self.assertEqual(items[0][2], "The Caldera Fire-Lizard")

    def test_f_hangs_the_selected_trophy_and_takes_it_down(self):
        ui, state = self.session.ui, self.session.state
        ui.book_collection_i = 0
        self.assertIn("F hangs it", rail_status(state, "legendary", "caldera_fire_lizard"))
        self.session.tick(Keys(pressed={"f"}), 0.05)
        self.assertEqual(state.rail_trophies(), [("legendary", "caldera_fire_lizard")])
        self.assertIn("takes it down", rail_status(state, "legendary", "caldera_fire_lizard"))
        ui.book_collection_i = 1
        self.session.tick(Keys(pressed={"f"}), 0.05)
        self.assertIn(("shiny", "bluegill"), state.rail_trophies())
        ui.book_collection_i = 0
        self.session.tick(Keys(pressed={"f"}), 0.05)
        self.assertEqual(state.rail_trophies(), [("shiny", "bluegill")])
        self.assertTrue(state.v2["legendaries"]["caldera_fire_lizard"]["records"])  # the book keeps it

    def test_a_boat_without_a_rail_says_so(self):
        state = self.session.state
        state.boat_id = "jon"
        self.assertIn("no trophy rail", rail_status(state, "legendary", "caldera_fire_lizard"))
        self.session.tick(Keys(pressed={"f"}), 0.05)
        self.assertEqual(state.rail_trophies(), [])


if __name__ == "__main__":
    unittest.main()
