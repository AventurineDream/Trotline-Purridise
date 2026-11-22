"""Five-shell geometry, shared collar, scout rig, night light and shell voices."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from . import bot, botidentity, botmesh
from .audio import Audio
from .botchimes import CHIMES, SAMPLE_RATE, synthesize
from .botshots import preview
from .content import ContentError, validate_content_v2
from .data import BOT_SHELLS, CONTENT_V2_RAW
from .game import Keys, Session
from .glrender import LakeRenderer
from .sim import State
from .world import Face, World


class ShellGeometryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=World()

    def test_all_shells_and_collars_are_finite_outward_bounded_read_only_meshes(self):
        shapes=set()
        for shell in BOT_SHELLS:
            for style in ('none','loop','loose','square','bow','sailors_hitch'):
                mesh=botmesh.local_mesh(shell,style)
                self.assertLessEqual(len(mesh.points),botmesh.MAX_FACES)
                self.assertLess(mesh.nbytes,100_000)
                self.assertTrue(np.isfinite(mesh.points).all())
                self.assertTrue(np.isfinite(mesh.normals).all())
                self.assertTrue(((mesh.colors>=0)&(mesh.colors<=1)).all())
                self.assertTrue(((mesh.emission>=0)&(mesh.emission<=1)).all())
                self.assertLess(np.max(np.abs(mesh.points)),.7)
                np.testing.assert_allclose(np.linalg.norm(mesh.normals,axis=1),1.,atol=1e-5)
                self.assertFalse(mesh.points.flags.writeable)
                if style=='none':shapes.add(hashlib.sha256(mesh.points.tobytes()).hexdigest())
        self.assertEqual(len(shapes),5)
        self.assertLessEqual(botmesh.local_mesh.cache_info().currsize,12)

    def test_each_knot_and_the_loose_loop_have_distinct_shared_wool_geometry(self):
        for shell in BOT_SHELLS:
            hashes=set()
            bare=botmesh.local_mesh(shell,'none')
            for style in ('loop','loose','square','bow','sailors_hitch'):
                mesh=botmesh.local_mesh(shell,style)
                self.assertGreater(len(mesh.points),len(bare.points))
                self.assertTrue(np.any(np.all(np.isclose(mesh.colors,botmesh.WOOL),axis=1)))
                hashes.add(hashlib.sha256(mesh.points.tobytes()).hexdigest())
            self.assertEqual(len(hashes),5)

    def test_home_idles_still_under_reduced_motion_moves_otherwise_and_scouting_keeps_its_rig(self):
        state=State.new(self.world,seed=4618)
        for shell in BOT_SHELLS:
            state.v2['profile']['shell']=shell
            state.bot_phase='home'
            state.v2['settings']['reduced_motion']=True
            state.anim=0.;still=bot._points(bot.faces(state))
            state.anim=37.;np.testing.assert_array_equal(still,bot._points(bot.faces(state)),shell)
            state.v2['settings']['reduced_motion']=False
            state.anim=12.5;first=bot._points(bot.faces(state))
            np.testing.assert_array_equal(first,bot._points(bot.faces(state)),shell)
            decks,lamps=set(),set()
            for t in np.arange(0.,60.,.5):
                state.anim=float(t)
                faces=bot.faces(state)
                decks.add(bot._points(faces).tobytes())
                lamps.add(b''.join(f.pts.tobytes() for f in faces if float(f.color[0])>.9 and float(f.color[2])<.3))
            self.assertGreaterEqual(len(decks),4,shell)
            self.assertGreaterEqual(len(lamps),4,shell)
            state.bot_phase='out';state.bot_x=30.;state.bot_z=30.
            state.anim=0.;first=bot._points(bot.faces(state))
            state.anim=.18;second=bot._points(bot.faces(state))
            self.assertFalse(np.array_equal(first,second),shell)
            state.bot_phase='home'
            state.v2['settings']['reduced_motion']=False

    def test_idle_pose_keeps_normals_unit_leaves_the_cache_alone_and_moves_only_its_parts(self):
        for shell in BOT_SHELLS:
            mesh=botmesh.local_mesh(shell,'loop')
            before=mesh.points.tobytes()
            self.assertTrue(mesh.head,shell)
            points,normals=botmesh._posed(mesh,botmesh.Idle(yaw=.4,pitch=-.2,flick=(1.,1.)))
            self.assertEqual(before,mesh.points.tobytes())
            np.testing.assert_allclose(np.linalg.norm(normals,axis=-1),1.,atol=1e-5)
            changed=np.any(points!=mesh.points,axis=(1,2))
            body=~np.isin(mesh.parts,mesh.head_parts)
            self.assertFalse(changed[body].any(),shell)
            self.assertTrue(changed[np.isin(mesh.parts,mesh.head_parts)].any(),shell)
            points,_=botmesh._posed(mesh,botmesh.Idle(blink=1.))
            changed=np.any(points!=mesh.points,axis=(1,2))
            self.assertTrue(changed[mesh.parts==botmesh.EYE].any(),shell)
            self.assertFalse(changed[mesh.parts!=botmesh.EYE].any(),shell)
            lamp=points[mesh.parts==botmesh.EYE].reshape(-1,3)
            self.assertLess(float(np.ptp(lamp[:,1])),float(np.ptp(mesh.points[mesh.parts==botmesh.EYE].reshape(-1,3)[:,1])))

    def test_idle_pose_is_the_rest_pose_under_reduced_motion_and_bounded_otherwise(self):
        for shell in BOT_SHELLS:
            mesh=botmesh.local_mesh(shell,'loop')
            self.assertTrue(np.array_equal(botmesh._posed(mesh,botmesh.Idle())[0],mesh.points))
        for seed in (1,2,3):
            for t in np.arange(0.,30.,.25):
                pose=bot.idle_pose(float(t),seed,False)
                self.assertLessEqual(abs(pose.yaw),botmesh.YAW_LIMIT)
                self.assertLessEqual(abs(pose.pitch),botmesh.PITCH_LIMIT)
                self.assertLessEqual(pose.hum,.003)
                self.assertEqual(bot.idle_pose(float(t),seed,True),botmesh.Idle())

    def _cat_at(self, state, origin, rest_right, rest_forward, lateral, ahead, npc=None):
        """A cat placed `lateral` metres along the rest frame's right and `ahead` along its forward."""
        npc = npc or SimpleNamespace(anchor=SimpleNamespace(x=0.,z=0.))
        npc.anchor.x=float(origin[0]+rest_right[0]*lateral+rest_forward[0]*ahead)
        npc.anchor.z=float(origin[2]+rest_right[2]*lateral+rest_forward[2]*ahead)
        return npc

    def test_idle_watches_a_cat_in_range_and_fades_out_between_20_and_25_metres(self):
        state=State.new(self.world,seed=4618)
        eye,right,_up,forward=bot._boat_basis(state)
        origin=eye+right*.34-np.array((0,.49,0),np.float32)+forward*2.24
        rest_right,rest_forward=-right,-forward
        state.npcs=(self._cat_at(state,origin,rest_right,rest_forward,5.,0.),)
        yaw,pitch,weight=bot._watch(state,origin,rest_right,rest_forward)
        self.assertAlmostEqual(weight,1.)
        self.assertGreater(yaw,1.)
        self.assertAlmostEqual(pitch,0.)
        state.npcs=(self._cat_at(state,origin,rest_right,rest_forward,40.,0.),)
        self.assertEqual(bot._watch(state,origin,rest_right,rest_forward)[2],0.)
        state.npcs=(self._cat_at(state,origin,rest_right,rest_forward,0.,-3.),)
        self.assertEqual(bot._watch(state,origin,rest_right,rest_forward)[2],0.)

    def test_head_yaw_moves_smoothly_as_a_cat_sweeps_from_15_to_30_metres_and_as_two_cats_trade_places(self):
        state=State.new(self.world,seed=4618)
        eye,right,_up,forward=bot._boat_basis(state)
        origin=eye+right*.34-np.array((0,.49,0),np.float32)+forward*2.24
        rest_right,rest_forward=-right,-forward
        def head_yaw(npcs):
            state.npcs=npcs
            return bot.idle_pose(10.,7,False,bot._watch(state,origin,rest_right,rest_forward)).yaw
        cat=self._cat_at(state,origin,rest_right,rest_forward,0.,0.)
        steps=np.arange(1500)*.01
        yaws=[]
        for d in 15.+steps:
            self._cat_at(state,origin,rest_right,rest_forward,.8*d,.6*d,cat)
            yaws.append(head_yaw((cat,)))
        self.assertLess(float(np.max(np.abs(np.diff(yaws)))),.02)
        left=self._cat_at(state,origin,rest_right,rest_forward,-.8*18,.6*18)
        right_cat=self._cat_at(state,origin,rest_right,rest_forward,.8*22,.6*22)
        trade=[]
        for step in steps[:400]:
            d_left,d_right=18.+step,22.-step
            self._cat_at(state,origin,rest_right,rest_forward,-.8*d_left,.6*d_left,left)
            self._cat_at(state,origin,rest_right,rest_forward,.8*d_right,.6*d_right,right_cat)
            trade.append(head_yaw((left,right_cat)))
        self.assertLess(float(np.max(np.abs(np.diff(trade)))),.02)

    def test_home_rig_rows_match_the_face_builder_with_idle_and_cats_in_view(self):
        from .bot import HomeRig
        renderer=LakeRenderer.__new__(LakeRenderer)
        state=State.new(self.world,seed=4618)
        rig=HomeRig()
        for shell in BOT_SHELLS:
            state.v2['profile']['shell']=shell
            eye,right,_up,forward=bot._boat_basis(state)
            origin=eye+right*.34-np.array((0,.49,0),np.float32)+forward*2.24
            state.npcs=(self._cat_at(state,origin,-right,-forward,6.,4.),)
            for reduced in (False,True):
                state.v2['settings']['reduced_motion']=reduced
                for anim in np.arange(0.,20.,.7):
                    state.anim=float(anim)
                    expected=renderer._pack_faces(bot.faces(state))
                    np.testing.assert_allclose(rig.rows(state,renderer._pack_faces),expected,atol=2e-5,err_msg=(shell,reduced,anim))
            state.v2['settings']['reduced_motion']=False

    def test_rendering_and_repeated_shell_switches_preserve_state_and_rng(self):
        state=State.new(self.world,seed=4618)
        state.v2['profile']['shells']=list(BOT_SHELLS)
        state.v2['profile']['collar'].update(stage='retied',knot='sailors_hitch')
        state.bot_phase='out'
        for shell in BOT_SHELLS:
            botidentity.swap_shell(state,self.world,shell)
            before=state.to_json();rng=state.rng.s
            for _ in range(3):bot.faces(state)
            self.assertEqual(before,state.to_json())
            self.assertEqual(state.rng.s,rng)

    def test_every_shell_perches_inside_each_existing_boat(self):
        from .boat import BOATS
        state=State.new(self.world,seed=4618)
        for boat_id,model in BOATS.items():
            state.boat_id=boat_id
            eye,right,_up,forward=bot._boat_basis(state)
            for shell in BOT_SHELLS:
                state.v2['profile']['shell']=shell
                points=bot._points(bot.faces(state)).reshape(-1,3)-eye
                along,side=points@forward,points@right
                self.assertGreater(float(along.min()),model.stern,(boat_id,shell))
                self.assertLess(float(along.max()),model.bow,(boat_id,shell))
                self.assertLess(float(np.abs(side).max()),model.half_beam+.01,(boat_id,shell))

    def test_duck_enamel_is_not_classified_as_a_lamp_and_astral_emission_is_packed(self):
        renderer=LakeRenderer.__new__(LakeRenderer)
        for shell in BOT_SHELLS:
            faces=botmesh.faces((0,0,0),(1,0,0),(0,1,0),(0,0,1),shell=shell)
            packed=renderer._pack_faces(faces)
            self.assertLess(packed.nbytes,500_000)
            self.assertTrue(np.isfinite(packed).all())
            self.assertEqual(packed.shape[1],10)
            for i,face in enumerate(faces):
                material=packed[i*6,9]
                self.assertEqual(material,2. if face.emissive==0 else np.float32(8.+face.emissive))
        legacy=Face(np.zeros((4,3),np.float32),np.array((0,1,0),np.float32),np.array((1.,.7,.2),np.float32))
        self.assertEqual(renderer._pack_faces([legacy])[0,9],3.)

    def test_software_astral_glow_is_night_only_and_every_shell_is_visible(self):
        for shell in BOT_SHELLS:
            day=preview(shell,night=False,size=96)
            night=preview(shell,night=True,size=96)
            self.assertEqual(day.dtype,np.uint8)
            self.assertGreater(float(day.std()),12)
            self.assertFalse(np.array_equal(day,night))
        np.testing.assert_array_equal(preview('astral',night=False,size=96),preview('astral',night=False,size=96,emission=False))
        bright=preview('astral',night=True,size=96)
        dark=preview('astral',night=True,size=96,emission=False)
        self.assertGreater(int(bright.astype(int).sum()-dark.astype(int).sum()),1000)

    def test_new_art_data_is_validated_and_cannot_share_a_voice(self):
        raw=deepcopy(CONTENT_V2_RAW)
        raw['bot.json']['shells'][1]['body']=[float('nan'),.5,2.]
        raw['bot.json']['shells'][2]['chime']='bot_tin'
        raw['bot.json']['shells'][3]['caption']=''
        with self.assertRaises(ContentError) as caught:validate_content_v2(raw)
        for key in ('body','chime','caption'):self.assertIn(key,str(caught.exception))


class ShellChimeChecks(unittest.TestCase):
    def test_five_quiet_distinct_synthesized_pcm_voices_have_bounded_storage(self):
        hashes=set();spectra=[]
        for kind in CHIMES:
            pcm=synthesize(kind)
            self.assertEqual(pcm.dtype,np.int16)
            self.assertLessEqual(len(pcm),SAMPLE_RATE)
            self.assertFalse(pcm.flags.writeable)
            self.assertEqual(int(pcm[0]),0)
            self.assertLess(abs(int(pcm[-1])),32)
            self.assertLess(np.max(np.abs(pcm.astype(int))),10000)
            self.assertGreater(float(np.sqrt(np.mean(pcm.astype(float)**2))),200)
            self.assertIs(pcm,synthesize(kind))
            hashes.add(hashlib.sha256(pcm.tobytes()).hexdigest())
            spectrum=np.abs(np.fft.rfft(pcm.astype(float),n=32768))
            spectra.append(spectrum/np.linalg.norm(spectrum))
            np.testing.assert_array_equal(Audio.__new__(Audio)._tone(kind),pcm)
        self.assertEqual(len(hashes),5)
        self.assertLess(sum(synthesize(k).nbytes for k in CHIMES),150_000)
        for i,first in enumerate(spectra):
            for second in spectra[i+1:]:self.assertLess(float(first@second),.85)
        self.assertEqual(synthesize.cache_info().maxsize,5)

    def test_scout_events_and_shell_changes_use_the_matching_caption_with_mute_controls(self):
        world=World();state=State.new(world,seed=4618)
        with tempfile.TemporaryDirectory() as d:
            session=Session(world,Path(d)/'save.json',state,False)
            for shell,row in BOT_SHELLS.items():
                state.v2['profile']['shell']=shell
                session.sound='bot';session._tick_caption(0.)
                self.assertEqual(session.ui.caption,row.caption)
                self.assertEqual(bot.sound_kind(state,'bot'),row.chime)
                self.assertEqual(bot.sound_kind(state,'bite'),'bite')
            state.v2['settings']['captions']=False
            session._tick_caption(0.)
            self.assertEqual(session.ui.caption,'')
            self.assertEqual(bot.sound_kind(state,'bot'),'bot_astral')

    def test_landing_shell_swap_plays_the_new_shell_voice_without_changing_scouting(self):
        world=World();state=State.new(world,seed=4618)
        state.v2['profile']['shells']=list(BOT_SHELLS)
        with tempfile.TemporaryDirectory() as d:
            session=Session(world,Path(d)/'save.json',state,False)
            session.ui.mode='shop';session.ui.shop_tab=7;session.ui.shop_i=2
            phase=state.bot_phase
            session.tick(Keys(pressed={'return'}),.1)
            self.assertEqual(state.v2['profile']['shell'],'duck')
            self.assertEqual(session.sound,'bot')
            self.assertEqual(session.ui.caption,BOT_SHELLS['duck'].caption)
            self.assertEqual(state.bot_phase,phase)


if __name__=='__main__':unittest.main()
