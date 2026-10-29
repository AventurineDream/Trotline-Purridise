"""Real-chart, full-hull and lake-travel regressions for V3 locations."""

from collections import deque
from dataclasses import FrozenInstanceError, replace
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .anchors import ANCHORS, anchors_for_lake, validate_anchors
from .boat import BOATS
from .content import load_content
from .game import Session
from .sim import State
from .world import World


class AnchorChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {lake: World(lake) for lake in ("briar", "cedar")}

    def test_every_authored_npc_resolves_on_its_lake(self):
        for npc in load_content().npcs.values():
            w = self.worlds[npc['lake_id']]
            a = w.anchors[npc['anchor_id']]
            self.assertEqual(a.lake_id, npc['lake_id'])
            self.assertEqual(w.zone_at(*a.position), a.zone_id.split(':')[1])
            if a.kind == 'water':
                self.assertEqual(a.name, w.zone_name(a.zone_id.split(':')[1]))
        self.assertNotIn('cedar:docs_marina_dock', self.worlds['briar'].anchors)

    def test_marina_and_named_waypoints_retain_contract_coordinates(self):
        cedar = self.worlds['cedar']
        doc = cedar.anchors['cedar:docs_marina_dock']
        self.assertEqual(doc.position, (-186.451, -400.499))
        self.assertEqual(doc.zone_id, 'cedar:open')
        self.assertEqual(doc.name, "Doc's Lonely Star Marina")
        self.assertGreater(math.dist(doc.position, cedar.dock), 1000)
        self.assertEqual(cedar.anchors['cedar:trinidad_cove'].position, (186.862, -855.722))
        self.assertEqual(cedar.anchors['cedar:lonely_star_deep'].zone_id, 'cedar:deep')
        self.assertEqual(cedar.anchors['cedar:lonely_star_deep'].position,
                         cedar.anchors['cedar:deep'].position)
        self.assertNotIn('lonely_star_deep', [row[0] for row in cedar.zones])
        self.assertNotIn('east_cove', [row[0] for row in cedar.zones])

    def test_full_hull_approaches_and_landing_exclusions(self):
        for w in self.worlds.values():
            validate_anchors(w)
            for a in w.anchors.values():
                self.assertTrue(w.navigable(*a.position), a.id)
                x, z, yaw = a.player_position
                self.assertLessEqual(math.dist((x, z), a.position), 20.0)
                for boat in BOATS:
                    self.assertTrue(w.hull_clear(x, z, yaw, boat), (a.id, boat))
                if a.kind == 'water':
                    self.assertGreaterEqual(math.dist(a.position, w.dock), 50)
            # Dock hosts are reference points, never boat spawns in the slip.
            for boat in BOATS:
                yaw = math.atan2(-w.slip.ix, -w.slip.iz)
                for along in np.linspace(4, -20, 49):
                    self.assertTrue(w.hull_clear(*w.slip.world(along, 0), yaw, boat))

    def test_immutable_locations_and_unknown_lakes(self):
        with self.assertRaises(TypeError):
            self.worlds['briar'].anchors['new'] = ANCHORS['briar:landing']
        with self.assertRaises(FrozenInstanceError):
            ANCHORS['briar:landing'].x = 0
        with self.assertRaises(ValueError):
            anchors_for_lake('unknown')
        with self.assertRaises(KeyError):
            self.worlds['briar'].anchors['cedar:open']

    def test_chart_drift_is_reported_without_relocating(self):
        w = self.worlds['briar']
        original = w.anchors
        try:
            w.anchors = {'briar:flats': replace(ANCHORS['briar:flats'], x=10000)}
            with self.assertRaisesRegex(ValueError, 'invalid water/zone'):
                validate_anchors(w)
            w.anchors = {'briar:flats': replace(ANCHORS['briar:flats'], approach=(10000, 0, 0))}
            with self.assertRaisesRegex(ValueError, 'outside hail range'):
                validate_anchors(w)
        finally:
            w.anchors = original

    def test_actual_lake_switch_and_reconstruction_keep_locations(self):
        with tempfile.TemporaryDirectory(prefix='briar-anchors-') as temp:
            briar = self.worlds['briar']
            st = State.new(briar, seed=41)
            session = Session(briar, Path(temp)/'save.json', st, True)
            for lake in ('cedar', 'briar', 'cedar'):
                st._park(session.world)
                self.assertIsNone(session.change_lake(lake))
                self.assertEqual(dict(session.world.anchors), dict(self.worlds[lake].anchors))
                validate_anchors(session.world)
            # Serialization emits the current wall-clock stamp each time.
            with patch("fishing.sim.time.time", return_value=1234.0):
                before = st.to_json()
                validate_anchors(session.world)
                self.assertEqual(st.to_json(), before)

    def test_routes_from_landing_reach_every_interaction_site(self):
        # A conservative 4m grid: a 5.8m clear disk covers the largest hull
        # (under 3.7m radius) plus a 2m half-edge. Deepest draft is the sailboat.
        # This connectivity check is test-only, not a gameplay pathfinder.
        for w in self.worlds.values():
            step, clearance = 4.0, 5.8
            x0, z0, x1, z1 = w.bounds
            xs, zs = np.arange(x0, x1, step), np.arange(z0, z1, step)
            x, z = np.meshgrid(xs, zs)
            safe = w.navigable_mask(x, z, max(b.draft for b in BOATS.values()))
            for radius in (clearance/2, clearance):
                for angle in np.arange(16)*math.tau/16:
                    safe &= w.navigable_mask(x+radius*math.cos(angle), z+radius*math.sin(angle), .72)
            a, s = w.slip.local(x, z)
            for ca, cs, ea, es in w.dock_barriers:
                safe &= (abs(a-ca) > ea+clearance) | (abs(s-cs) > es+clearance)
            for px, pz, r in w.solid_props:
                i, j = int((px-x0)/step), int((pz-z0)/step)
                n = math.ceil((r+clearance)/step)+1
                ia, ib = max(0, i-n), min(len(xs), i+n+1)
                ja, jb = max(0, j-n), min(len(zs), j+n+1)
                if ia < ib and ja < jb:
                    safe[ja:jb, ia:ib] &= ((x[ja:jb, ia:ib]-px)**2 +
                                         (z[ja:jb, ia:ib]-pz)**2 > (r+clearance)**2)
            sx, sz = w.slip.world(-20, 0)
            start = (round((float(sz)-z0)/step), round((float(sx)-x0)/step))
            self.assertTrue(safe[start], w.id)
            seen = np.zeros(safe.shape, bool)
            seen[start] = True
            queue = deque([start])
            while queue:
                j, i = queue.popleft()
                for jj, ii in ((j+1,i), (j-1,i), (j,i+1), (j,i-1)):
                    if (0 <= jj < safe.shape[0] and 0 <= ii < safe.shape[1]
                            and safe[jj, ii] and not seen[jj, ii]):
                        seen[jj, ii] = True
                        queue.append((jj, ii))
            for anchor in w.anchors.values():
                reachable = seen & ((x-anchor.x)**2+(z-anchor.z)**2 <= 20.0**2)
                self.assertTrue(np.any(reachable), anchor.id)
                # Confirm an actual full hull fits at the accessible point.
                j, i = np.argwhere(reachable)[0]
                for boat in BOATS:
                    self.assertTrue(w.hull_clear(xs[i], zs[j], 0.0, boat), (anchor.id, boat))


def anchor_checks():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(AnchorChecks))
    if not result.wasSuccessful():
        raise AssertionError('narrative anchor checks failed')


if __name__ == '__main__':
    unittest.main()


class RosterAnchorChecks(unittest.TestCase):
    """V1-30: every lake's anchors validate, and each cat's own boat floats at its anchor."""

    def test_every_lake_validates_and_seats_its_cats(self):
        from .actors import _seed
        from .content import load_content_v2
        roster = load_content_v2().roster
        moorings = {"pounce": "mail_mooring", "thistle": "tinker_mooring"}
        for lake in ("briar", "cedar", "flathead", "crater", "nebula"):
            world = World(lake)
            validate_anchors(world)
            for npc_id, row in roster.items():
                if row["role"] == "host" and row["lake"] == lake:
                    self.assertEqual(world.anchors[row["anchor"]].kind, "dock")
                    continue
                if row["role"] == "traveler":
                    anchor = world.anchors[f"{lake}:{moorings[npc_id]}"]
                elif row["lake"] == lake:
                    anchor = world.anchors[row["anchor"]]
                else:
                    continue
                yaw = _seed(anchor.id) * math.tau
                with self.subTest(lake=lake, npc=npc_id):
                    self.assertTrue(world.hull_clear(anchor.x, anchor.z, yaw, row["boat"]))

