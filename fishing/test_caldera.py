"""Shared Crater fields, island navigation, thermal effects and still nights."""

from copy import deepcopy
import math
import unittest

import numpy as np

from . import ambient, calendar
from .boat import BOATS
from .caldera import reflection_strength, survey_faces, thermal_faces
from .content import ContentError, validate_content_v2
from .data import CONTENT_V2_RAW, LAKE_SPECIES_IDS, ZONE_ORDER
from .lakegen import LakeFields
from .marina import footprint_samples
from .sim import State
from .specieschecks import _reachable_samples, lake_witnesses
from .weather import lighting_at
from .world import World


class CalderaChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=World('crater')

    def test_round_caldera_has_sheer_rim_cinder_island_and_shared_finite_fields(self):
        world=self.world
        fields=LakeFields(deepcopy(world.environment))
        self.assertTrue(world.caldera)
        self.assertFalse(world.placeholder)
        self.assertEqual(world.height.shape,(601,601))
        for actual,expected in zip(fields.bake(),(world.shore_grid,world.depth_grid,world.coast)):
            np.testing.assert_array_equal(actual,expected)
            self.assertEqual(actual.dtype,np.float32)
            self.assertTrue(np.isfinite(actual).all())
        self.assertGreater(world.sample_height(550,0),100)
        self.assertLess(world.sample_height(460,0),1)
        self.assertGreater(world.sample_height(150,-60),50)
        self.assertEqual(world.zone_at(150,-60),'shore')
        self.assertEqual(world.depth(150,-60),0)
        self.assertGreater(float(world.depth_grid.max()),59)
        self.assertGreater(float(world.shore_sd(150,-60)),65)
        self.assertLess(float(world.shore_sd(150-110,-60)),-15)
        self.assertLess(world.environment['outline'][0][1],500)
        self.assertLess(sum(grid.nbytes for grid in (world.height,world.shore_grid,world.depth_grid)),4_500_000)

    def test_island_hull_ring_and_all_six_habitats_are_connected_to_landing(self):
        world=self.world
        x,z=_reachable_samples(world)
        ids=world.zone_ids(x,z)
        self.assertEqual({row[0] for row in world.zones},{'flats','lilies','cypress','rocks','deep','springs'})
        for zone,*_ in world.zones:
            self.assertTrue(np.any(ids==ZONE_ORDER.index(zone)),zone)
        for angle in np.linspace(0,math.tau,48,endpoint=False):
            px,pz=150+math.cos(angle)*100,-60+math.sin(angle)*86
            for boat in BOATS:
                self.assertTrue(world.hull_clear(px,pz,angle+.7,boat),(angle,boat))
        for boat in BOATS:
            self.assertFalse(world.hull_clear(150,-60,0,boat))
        fish=lake_witnesses(world)
        self.assertEqual({row['species'] for row in fish},set(LAKE_SPECIES_IDS['crater']))
        self.assertGreaterEqual(min(row['ratio'] for row in fish),.5)

    def test_caldera_rim_dock_buildings_are_dry_and_all_piers_are_solid(self):
        world=self.world
        state=State.new(world)
        self.assertEqual(state.slip_status(world),'docked')
        for footprint in world.marina.shore_buildings:
            for a,s in footprint_samples(footprint):
                self.assertGreaterEqual(float(world.shore_sd(*world.slip.world(a,s))),1)
        for footprint in world.marina.footprints:
            px,pz=world.slip.world(footprint.a,footprint.s)
            self.assertTrue(all(not world.hull_clear(px,pz,0,boat) for boat in BOATS))
        for a in np.linspace(-120,4,60):
            px,pz=world.slip.world(float(a),0)
            self.assertTrue(all(world.hull_clear(px,pz,state.yaw,boat) for boat in BOATS))
        drowned=[p for p in world.props if p.kind=='deadpine']
        self.assertEqual(len(drowned),12)
        self.assertTrue(all(not world.hull_clear(p.x,p.z,0) for p in drowned))
        marker=survey_faces(world)
        self.assertTrue(marker)
        self.assertTrue(all(np.isfinite(face.pts).all() for face in marker))

    def test_thermal_steam_and_bubbles_are_bounded_reduced_motion_and_read_only(self):
        world=self.world
        state=State.new(world,seed=4)
        before,rng=deepcopy(state.to_json()),state.rng.s
        first=thermal_faces(state,world)
        state.anim=9
        later=thermal_faces(state,world)
        self.assertEqual(len(first),28)
        self.assertFalse(np.array_equal(first[0].pts,later[0].pts))
        state.v2['settings']['reduced_motion']=True
        frozen=thermal_faces(state,world)
        state.anim=100
        for a,b in zip(frozen,thermal_faces(state,world)):
            np.testing.assert_array_equal(a.pts,b.pts)
        del state.v2['settings']['reduced_motion']
        state.anim=0
        self.assertEqual(state.to_json(),before)
        self.assertEqual(state.rng.s,rng)
        for x,z in world.environment['thermal']:
            self.assertLess(float(world.shore_sd(x,z)),-2)
            self.assertEqual(world.zone_at(x,z),'springs')
        for minute in (0,360,960,4*1440+20):
            state.game_minutes=minute
            for x,z in world.environment['thermal']:
                state.x,state.z=x,z
                faces=ambient.faces(state,world)
                self.assertLessEqual(len(faces),ambient.MAX_FACES)
                self.assertTrue(all(np.isfinite(face.pts).all() for face in faces))

    def test_fog_lifts_with_forecast_and_clear_night_hook_never_advances_story(self):
        state=State.new(self.world,seed=4)
        before,rng=deepcopy(state.to_json()),state.rng.s
        fog=lighting_at(4*1440+20,state)
        clearing=lighting_at(4*1440+60,state)
        clear=lighting_at(4*1440+100,state)
        self.assertGreater(fog['mist'],clearing['mist'])
        self.assertGreater(clearing['mist'],clear['mist'])
        self.assertEqual(clear['mist'],0)
        state.game_minutes=4*1440+960
        self.assertEqual(calendar.weather_at(state,state.game_minutes),'clear')
        self.assertEqual(reflection_strength(state,lighting_at(state.game_minutes,state)),1)
        self.assertEqual(reflection_strength(state,lighting_at(4*1440+360,state)),0)
        self.assertEqual(reflection_strength(state,{**fog,'night':1}),0)
        state.game_minutes=0
        self.assertEqual(state.to_json(),before)
        self.assertEqual(state.rng.s,rng)
        other=State.new(World('flathead'))
        self.assertEqual(reflection_strength(other,lighting_at(960,other)),0)

    def test_validator_collects_invalid_islands_rims_vents_and_channels(self):
        bad=deepcopy(CONTENT_V2_RAW)
        environment=bad['lakes.json']['lakes'][3]['environment']
        environment.update(islands=[[450,0,80,70,40],[0,0,0,80,float('nan')]],
                           rim=[2000,True],thermal=[[1],[0,float('inf')]])
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(bad)
        for key in ('islands[0]','islands[1]','rim','thermal[0]','thermal[1]'):
            self.assertIn('.environment.'+key,str(caught.exception))
        for key in ('islands','rim','thermal'):
            bad=deepcopy(CONTENT_V2_RAW)
            del bad['lakes.json']['lakes'][3]['environment'][key]
            with self.assertRaises(ContentError):
                validate_content_v2(bad)

    def test_software_caldera_plays_fog_clear_night_and_springs_without_rng_changes(self):
        from .software import SoftwareRenderer
        state=State.new(self.world,seed=4)
        state.x,state.z,state.yaw=-230,40,1.828
        before,rng=deepcopy(state.to_json()),state.rng.s
        renderer=SoftwareRenderer(self.world,160,90)
        frames=[]
        try:
            for minute in (4*1440+20,4*1440+100,4*1440+360,4*1440+960):
                state.game_minutes=minute
                frame=renderer.render(state)
                self.assertEqual(frame.shape,(90,160,3))
                self.assertGreater(float(frame.std()),5)
                frames.append(frame.copy())
            self.assertFalse(np.array_equal(frames[0],frames[1]))
            self.assertFalse(np.array_equal(frames[2],frames[3]))
            state.game_minutes=0
            self.assertEqual(state.to_json(),before)
            self.assertEqual(state.rng.s,rng)
        finally:
            renderer.close()

    def test_full_chart_labels_fit_their_actual_monospace_width(self):
        from .platform import Text
        from .ui import UI
        text=Text()
        ui=UI(text,self.world)
        frame=np.zeros((720,1280,3),np.uint8)
        boxes=[]
        ui._text=lambda frame,label,x,y,size,*args,**kwargs: boxes.append(
            (x,y,x+ui._measure(label,size,"mono"),y+ui.cell(size)[1]))
        try:
            ui._plot_habitats(frame,50,50,360,360)
            self.assertEqual(len(boxes),6)
            for i,a in enumerate(boxes):
                self.assertTrue(50<=a[0]<a[2]<=410)
                self.assertTrue(50<=a[1]<a[3]<=410)
                for b in boxes[i+1:]:
                    self.assertTrue(a[2]<b[0] or b[2]<a[0] or a[3]<b[1] or b[3]<a[1])
        finally:
            text.close()

    def test_native_reflection_depth_and_thermal_draws_reuse_graphics_resources(self):
        try:
            import moderngl
            ctx=moderngl.create_standalone_context(require=330,backend='egl')
        except Exception as error:
            self.skipTest('Standalone EGL unavailable: '+str(error))
        from .glrender import LakeRenderer
        renderer=None
        try:
            renderer=LakeRenderer(self.world,160,90,context=ctx)
            state=State.new(self.world,seed=4)
            count=len(renderer._objects)
            depths=[]
            for minute in (4*1440+20,4*1440+100,4*1440+360,4*1440+960):
                state.game_minutes=minute
                frame=renderer.render(state)
                self.assertGreater(float(frame.std()),5)
                depths.append(renderer.read_depth())
                raw=renderer.reflect_fb.depth_attachment.read(alignment=1)
                self.assertTrue(np.isfinite(np.frombuffer(raw,np.float32)).all())
                self.assertEqual(len(renderer._objects),count)
            self.assertTrue(all(value==depths[0] for value in depths[1:]))
            from .calderashots import finite_night_check
            self.assertEqual(finite_night_check(renderer,self.world),2)
            self.assertEqual(len(renderer._objects),count)
        finally:
            if renderer is not None:
                renderer.close()
            ctx.release()


if __name__=='__main__':
    unittest.main()
