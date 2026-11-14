"""Old flat-Crater deployments survive the island without trapping a save."""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

from .boat import BOATS
from .game import Session
from .sim import Catch, Hook, SetLine, State
from .world import World


class CalderaSaveRecoveryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=World('crater')

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='crater-old-lines-')
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'save.json'
        self.state=State.new(self.world,seed=134)
        self.state.v2['story']['chapter']=5

    def load(self):
        self.state.save(self.path,update_stamp=False)
        return State.load(self.path,self.world)

    def test_buried_mixed_line_keeps_equipment_catches_ids_and_future_fields(self):
        catch=Catch('coho',2.4,.9,1.2,'open','roe',12,'crater',
                    extra_fields={'future_catch':{'keep':True}},shiny=True,treasured=True)
        line=SetLine('std',['roe','insect'],140,-60,159.6,-60,'open',
                     [Hook(False,catch,{'future_hook':17}),Hook(True)],
                     line_id='10000000-0000-4000-8000-000000000001',extra_fields={'future_line':[1,2]})
        self.state.lines=[line]
        self.state.bot_phase='out'
        self.state.bot_target_line_id=line.line_id
        before=deepcopy(self.state.to_json())
        loaded=self.load()
        recovered=loaded.lines[0]
        self.assertNotEqual((recovered.x0,recovered.z0),(140,-60))
        self.assertAlmostEqual(math.hypot(recovered.x1-recovered.x0,recovered.z1-recovered.z0),19.6)
        for key,value in line.to_json().items():
            if key not in ('x0','z0','x1','z1','zone'):
                self.assertEqual(recovered.to_json()[key],value,key)
        self.assertEqual(loaded.rng.s,before['seed'])
        for key in ('money','bait','held','well','journal','narrative_v1','v2'):
            self.assertEqual(loaded.to_json()[key],before[key],key)
        self.assertEqual(loaded.bot_target_line_id,recovered.line_id)
        self.assertEqual((loaded.bot_tx,loaded.bot_tz),recovered.point_at(0))
        loaded.save(self.path,update_stamp=False)
        once=json.loads(self.path.read_text(encoding="utf-8"))
        again=State.load(self.path,self.world)
        self.assertEqual(again.to_json(),once)

    def test_line_crossing_island_is_recovered_even_when_both_ends_are_wet(self):
        self.state.lines=[SetLine('heavy','roe',40,-60,260,-60,'rocks',[Hook(True)])]
        self.assertLess(float(self.world.shore_sd(40,-60)),0)
        self.assertLess(float(self.world.shore_sd(260,-60)),0)
        loaded=self.load()
        line=loaded.lines[0]
        self.assertNotEqual((line.x0,line.z0),(40,-60))
        for t in (0,.25,.5,.75,1):
            self.assertTrue(self.world.hull_clear(line.x0+(line.x1-line.x0)*t,
                                                 line.z0+(line.z1-line.z0)*t,0,loaded.boat_id))

    def test_wet_deployments_stay_byte_equivalent_after_load(self):
        self.state.lines=[SetLine('std','insect',-240,140,-220,140,'open',[Hook(True)],line_id='10000000-0000-4000-8000-000000000002')]
        before=self.state.lines[0].to_json()
        loaded=self.load()
        self.assertEqual(loaded.lines[0].to_json(),before)

    def test_all_boats_can_reach_pull_and_travel_after_recovering_multiple_lines(self):
        for boat in BOATS:
            with self.subTest(boat=boat):
                self.state=State.new(self.world,seed=134)
                self.state.v2['story']['chapter']=5
                self.state.boat_id=boat
                self.state.owned_boats=list(BOATS)
                self.state.x,self.state.z=150,-60
                self.state.lines=[SetLine('std','insect',140+i,-60,159.6+i,-60,'open',
                                         [Hook(True) for _ in range(12)],line_id=f'20000000-0000-4000-8000-{i:012d}') for i in range(6)]
                loaded=self.load()
                self.assertEqual(len(loaded.lines),6)
                self.assertTrue(self.world.hull_clear(loaded.x,loaded.z,loaded.yaw,boat))
                before=len(loaded.held)
                while loaded.lines:
                    line=loaded.lines[0]
                    loaded.x,loaded.z=line.x0,line.z0
                    loaded.yaw=math.atan2(line.x1-line.x0,line.z1-line.z0)
                    self.assertTrue(self.world.hull_clear(loaded.x,loaded.z,loaded.yaw,boat))
                    self.assertEqual(loaded.nearest_line(),0)
                    self.assertIsNone(loaded.pull_line(0))
                self.assertEqual(len(loaded.held),before+6)
                loaded.x,loaded.z=self.world.slip.world(4,0)
                loaded.speed=0
                session=Session(self.world,self.path,loaded,False)
                self.assertIsNone(session.change_lake('briar'))
                self.assertEqual(loaded.lake_id,'briar')


if __name__=='__main__':
    unittest.main()
