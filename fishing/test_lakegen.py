"""Alpine geometry, navigation, read-only weather and both rendering paths."""

from copy import deepcopy
import math
import unittest

import numpy as np

from . import ambient, calendar
from .audio import Audio
from .boat import BOATS
from .content import ContentError, validate_content_v2
from .data import CONTENT_V2_RAW, LAKE_SPECIES_IDS, ZONE_ORDER
from .forest import atlas, tree
from .lakegen import LakeFields, larch_gold, smoke_faces
from .sim import State
from .specieschecks import _reachable_samples, lake_witnesses
from .weather import lighting_at, wind_at
from .world import World, shore_radius


class AlpineChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World('flathead')

    def test_fields_are_finite_deterministic_bounded_and_match_collision_grid(self):
        world = self.world
        fields = LakeFields(deepcopy(world.environment))
        shore, depth, coast = fields.bake()
        np.testing.assert_array_equal(shore, world.shore_grid)
        np.testing.assert_array_equal(depth, world.depth_grid)
        np.testing.assert_array_equal(coast, world.coast)
        self.assertEqual(world.height.shape, (545, 673))
        for grid in (shore, depth, coast, world.height):
            self.assertEqual(grid.dtype, np.float32)
            self.assertTrue(np.isfinite(grid).all())
        self.assertFalse(world.placeholder)
        self.assertGreater(float(world.height.max()), 200)
        self.assertGreater(float(depth.max()), 44)
        self.assertLess(sum(g.nbytes for g in (shore, depth, coast, world.height)), 5_000_000)
        x, z = np.meshgrid(np.linspace(-700,700,60), np.linspace(-650,650,60))
        near = np.abs(fields.shore(x,z)) < 30
        np.testing.assert_allclose(world.shore_sd(x,z)[near], fields.shore(x,z)[near], atol=.22)
        self.assertEqual([(p.kind,p.x,p.z,p.h) for p in World('flathead').props],
                         [(p.kind,p.x,p.z,p.h) for p in world.props])

    def test_area_and_habitat_chart_match_authored_alpine_layout(self):
        world = self.world
        angles = np.linspace(0,math.tau,361)
        briar = np.array([shore_radius(angle) for angle in angles])
        area = np.trapezoid(world.fields.radius(angles)**2, angles)
        ratio = area/np.trapezoid(briar**2, angles)
        self.assertTrue(2.15 < ratio < 2.35)
        self.assertEqual({row[0] for row in world.zones}, {'inlet','flats','lilies','cypress','rocks','deep'})
        for zone, x, z, radius in world.zones:
            self.assertEqual(world.zone_at(x,z), zone)
            self.assertEqual(ZONE_ORDER[int(world.zone_ids(x,z))], zone)
            self.assertTrue(all(world.hull_clear(x,z,.3,boat) for boat in BOATS))
        self.assertGreater(world.depth(55,-45), world.depth(170,-310))
        self.assertEqual(world.map_rgb.shape[0], int(360*1700/2100))

    def test_all_habitats_and_34_species_have_full_hull_routes_from_outpost(self):
        world = self.world
        x, z = _reachable_samples(world)
        zones = world.zone_ids(x,z)
        for zone, *_ in world.zones:
            self.assertTrue(np.any(zones == ZONE_ORDER.index(zone)), zone)
        witnesses = lake_witnesses(world)
        self.assertEqual({row['species'] for row in witnesses}, set(LAKE_SPECIES_IDS['flathead']))
        self.assertGreaterEqual(min(row['ratio'] for row in witnesses), .5)
        state = State.new(world)
        for a in np.linspace(-120,4,60):
            px,pz = world.slip.world(float(a),0)
            self.assertTrue(all(world.hull_clear(px,pz,state.yaw,boat) for boat in BOATS))
        stumps = [p for p in world.props if p.kind == 'stump']
        self.assertEqual(len(stumps), 12)
        self.assertTrue(all(not world.hull_clear(p.x,p.z,0) for p in stumps))
        self.assertFalse(world.navigable(1000,800))
        from .marina import footprint_samples
        for footprint in world.marina.footprints:
            px,pz=world.slip.world(footprint.a,footprint.s)
            self.assertTrue(all(not world.hull_clear(px,pz,0,boat) for boat in BOATS))
            if footprint.kind=='boat':
                for a,s in footprint_samples(footprint):
                    self.assertLess(float(world.shore_sd(*world.slip.world(a,s))),-1)
        for footprint in world.marina.shore_buildings:
            for a,s in footprint_samples(footprint):
                self.assertGreaterEqual(float(world.shore_sd(*world.slip.world(a,s))),1)

    def test_smoke_and_larch_gold_are_bounded_visuals_without_save_or_rng_changes(self):
        state = State.new(self.world,seed=723)
        before, rng = deepcopy(state.to_json()), state.rng.s
        first = smoke_faces(state,self.world)
        state.anim = 10
        later = smoke_faces(state,self.world)
        self.assertEqual(len(first),12)
        self.assertFalse(np.array_equal(first[0].pts,later[0].pts))
        state.v2['settings']['reduced_motion'] = True
        still = smoke_faces(state,self.world)
        state.anim = 90
        for a,b in zip(still,smoke_faces(state,self.world)):
            np.testing.assert_array_equal(a.pts,b.pts)
        del state.v2['settings']['reduced_motion']
        state.anim = 0
        self.assertEqual(state.to_json(),before)
        self.assertEqual(state.rng.s,rng)
        for minute in (0,360,900,2*1440+360):
            state.game_minutes = minute
            faces = ambient.faces(state,self.world)
            self.assertLessEqual(len(faces),ambient.MAX_FACES)
            self.assertTrue(all(np.isfinite(face.pts).all() for face in faces))
        self.assertTrue(larch_gold(state))
        normal,gold = tree('larch',0),tree('larchgold',0)
        np.testing.assert_array_equal(normal[:,:,3],gold[:,:,3])
        self.assertGreater(float(gold[:,:,0].sum()),float(normal[:,:,0].sum()))
        old,_ = atlas((1,.5,0))
        alpine,images = atlas((1,.5,0),alpine=True)
        self.assertNotIn('larch0',old)
        self.assertIn('larchgold2',alpine)
        self.assertLess(images.nbytes,6_000_000)

    def test_snow_mist_blends_and_alpine_ambience_uses_loons_and_larch_wind(self):
        state = State.new(self.world,seed=723)
        state.game_minutes = 5
        self.assertEqual(calendar.weather_at(state,5),'snow_mist')
        self.assertGreater(lighting_at(5,state)['snow'],.5)
        self.assertEqual(lighting_at(120,state)['snow'],0)
        self.assertGreater(wind_at(120,state)[1],wind_at(120)[1])
        before = deepcopy(state.to_json())
        for minute in np.linspace(28,92,50):
            light = lighting_at(float(minute),state)
            self.assertTrue(all(np.isfinite(light[key]).all() for key in ('horizon','zenith')))
            self.assertTrue(0 <= light['snow'] <= 1)
        self.assertEqual(state.to_json(),before)
        # Exercise the actual scheduling hook without opening an audio device.
        audio = Audio.__new__(Audio)
        audio._hour,audio._rain,audio._lake_id = 12,0,'flathead'
        audio.time,audio._bird_at,audio._frog_at = 20,0,0
        cues=[]
        audio._cue=cues.append
        audio._span=lambda base,spread: base
        audio._schedule()
        self.assertEqual(cues,['loon'])
        audio._hour,audio.time = 23,50
        audio._schedule()
        self.assertEqual(cues,['loon'])

    def test_environment_validator_collects_bad_shapes_allocations_and_ranges(self):
        bad = deepcopy(CONTENT_V2_RAW)
        environment = bad['lakes.json']['lakes'][2]['environment']
        environment.update(grid=[1025,True],bounds=[1,2,3,4],outline=[[0,500],[360,400]],
                           peaks=[[1,2,500,0]],tree_count=900,ambience=['missing'])
        environment['depths']['deep']=[50,2]
        environment['zones'].append(['deep',0,0,0])
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(bad)
        for key in ('grid','bounds','outline','peaks','tree_count','ambience','depths.deep','zones'):
            self.assertIn('.environment.'+key,str(caught.exception))
        for malformed in (None,[],{'outline':None}):
            bad=deepcopy(CONTENT_V2_RAW)
            bad['lakes.json']['lakes'][2]['environment']=malformed
            with self.assertRaises(ContentError):
                validate_content_v2(bad)

    def test_software_alpine_snow_and_gold_render_without_retained_state(self):
        from .software import SoftwareRenderer
        state=State.new(self.world,seed=723)
        before,rng=deepcopy(state.to_json()),state.rng.s
        renderer=SoftwareRenderer(self.world,160,90)
        try:
            frames=[]
            for minute in (5,360,780,960,2*1440+360):
                state.game_minutes=minute
                frame=renderer.render(state)
                self.assertEqual(frame.shape,(90,160,3))
                self.assertGreater(float(frame.std()),5)
                frames.append(frame.copy())
            self.assertFalse(np.array_equal(frames[0],frames[1]))
            self.assertFalse(np.array_equal(frames[1],frames[-1]))
            state.game_minutes=0
            self.assertEqual(state.to_json(),before)
            self.assertEqual(state.rng.s,rng)
        finally:
            renderer.close()

    def test_chart_habitat_labels_do_not_overlap(self):
        from .platform import Text
        from .ui import UI
        text=Text()
        ui=UI(text,self.world)
        frame=np.zeros((720,1280,3),np.uint8)
        labels=[]
        ui._text=lambda frame,label,x,y,size,*args,**kwargs: labels.append(
            (x,y,x+ui._measure(label,size),y+ui.cell(size)[1]))
        try:
            ui._plot_habitats(frame,100,100,360,291)
            self.assertEqual(len(labels),6)
            for i,a in enumerate(labels):
                self.assertTrue(100 <= a[0] < a[2] <= 460)
                self.assertTrue(100 <= a[1] < a[3] <= 391)
                for b in labels[i+1:]:
                    self.assertTrue(a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])
        finally:
            text.close()

    def test_native_snow_and_gold_reuse_buffers_and_preserve_depth(self):
        try:
            import moderngl
            ctx=moderngl.create_standalone_context(require=330,backend='egl')
        except Exception as error:
            self.skipTest('Standalone EGL unavailable: '+str(error))
        from .glrender import LakeRenderer
        renderer=None
        try:
            renderer=LakeRenderer(self.world,160,90,context=ctx)
            state=State.new(self.world,seed=723)
            count=len(renderer._objects)
            state.game_minutes=360
            renderer.render(state)
            original=renderer.prop_data.copy()
            depth=np.frombuffer(renderer.read_depth(),np.float32).copy()
            state.game_minutes=2*1440+360
            renderer.render(state)
            np.testing.assert_array_equal(depth,np.frombuffer(renderer.read_depth(),np.float32))
            np.testing.assert_array_equal(original[:,:5],renderer.prop_data[:,:5])
            self.assertTrue(np.any(original[:,5] != renderer.prop_data[:,5]))
            state.game_minutes=5
            frame=renderer.render(state)
            self.assertGreater(float(frame.std()),5)
            self.assertEqual(len(renderer._objects),count)
            self.assertTrue(np.isfinite(np.frombuffer(renderer.read_depth(),np.float32)).all())
        finally:
            if renderer is not None:
                renderer.close()
            ctx.release()


if __name__=='__main__':
    unittest.main()
