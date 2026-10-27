"""Fixed geometry, planar reflections, and a bounded OpenGL 3.3 framebuffer.

Uses the SDL window's context during play and standalone EGL for headless QA.
SDL owns input, sound, and the window. The renderer releases its own objects;
the window releases the shared context after scenery and presentation close.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import moderngl
import numpy as np

from .camera import Camera
from .data import paint_rgb
from .forest import H as ATLAS_H, W as ATLAS_W, atlas
from .imageops import resize_rgb
from .software import FOV, BASE_PITCH, SoftwareRenderer
from .weather import lighting_at
from . import comfort
from .world import Face
from .boat import HULL_INNER_BEAM, HULL_HALF_BEAM, HULL_BOW

SHADERS = Path(__file__).with_name("shaders")


class LakeRenderer(SoftwareRenderer):
    def __init__(self, world, width=960, height=540, *, context=None):
        self.world = world
        self.ctx = context
        self._owns_context = context is None
        self._objects = []
        self.splashes = []
        self.last_ms = 0.0
        self._boat_key = None
        self._boat_local = None
        self._fish_card_painter = None
        try:
            # EGL is available on Linux with both real GPUs and Mesa software GL.
            if self.ctx is None:
                try:
                    self.ctx = moderngl.create_standalone_context(require=330,backend="egl")
                except Exception:
                    self.ctx = moderngl.create_standalone_context(require=330)
            device = self.ctx.info["GL_RENDERER"]
            self.software_gl = any(s in device.lower() for s in ("llvmpipe","softpipe","swrast"))
            cap_w, cap_h = (640,360) if self.software_gl else (1440,810)
            scale = min(1.0,cap_w/width,cap_h/height)
            self.w = max(160,int(width*scale))
            self.h = max(90,int(height*scale))
            self.backend = device
            self._build()
            from .fishmesh import FishCardPainter
            self._fish_card_painter = FishCardPainter(self.ctx)
        except Exception as exc:
            self.close()
            raise RuntimeError(f"OpenGL setup: {exc}") from exc

    def own(self, obj):
        self._objects.append(obj)
        return obj

    def program(self, vert, frag):
        common = "#version 330\n"+(SHADERS/"common.glsl").read_text()+"\n"
        return self.own(self.ctx.program(
            vertex_shader=common+(SHADERS/vert).read_text(),
            fragment_shader=common+(SHADERS/frag).read_text()))

    def target(self, width, height):
        tex = self.own(self.ctx.texture((width,height),3))
        tex.filter = (moderngl.LINEAR,moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        depth = self.own(self.ctx.depth_renderbuffer((width,height)))
        fb = self.own(self.ctx.framebuffer([tex],depth))
        return tex,fb

    def _build(self):
        ctx = self.ctx
        self.sky_p = self.program("sky.vert","sky.frag")
        self.mesh_p = self.program("mesh.vert","mesh.frag")
        self.tree_p = self.program("foliage.vert","foliage.frag")
        self.water_p = self.program("water.vert","water.frag")
        self.post_p = self.program("sky.vert","post.frag")
        quad = self.own(ctx.buffer(np.array([[-1,-1],[3,-1],[-1,3]],np.float32).tobytes()))
        self.sky_vao = self.own(ctx.vertex_array(self.sky_p,[(quad,"2f","in_xy")]))
        self.post_vao = self.own(ctx.vertex_array(self.post_p,[(quad,"2f","in_xy")]))
        self.scene_tex,self.scene_fb = self.target(self.w,self.h)
        self.draw_fb = self.scene_fb
        self.samples = 1
        if not self.software_gl:
            self.samples = min(4,ctx.max_samples)
            if self.samples>1:
                color = self.own(ctx.renderbuffer((self.w,self.h),3,samples=self.samples))
                depth = self.own(ctx.depth_renderbuffer((self.w,self.h),samples=self.samples))
                self.draw_fb = self.own(ctx.framebuffer([color],depth))
        self.reflect_tex,self.reflect_fb = self.target(max(80,self.w//2),max(45,self.h//2))
        self.output_tex,self.output_fb = self.target(self.w,self.h)
        for name,grid in (("shore_tex",self.world.shore_grid),
                          ("depth_tex",getattr(self.world,"depth_grid",None))):
            values = np.zeros((1,1),np.float32) if grid is None else grid
            tex = self.own(ctx.texture((values.shape[1],values.shape[0]),1,values.tobytes(),dtype="f4"))
            tex.filter = (moderngl.LINEAR,moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            setattr(self,name,tex)
        self.terrain = self._terrain()
        self.camp = self.mesh(self._pack_faces(self.world.faces))
        self.boat_buf = self.own(ctx.buffer(reserve=500000,dynamic=True))
        self.boat_vao = self.mesh_vao(self.boat_buf)
        x0,z0,x1,z1 = self.world.bounds
        x0,z0,x1,z1 = min(-1900,x0-300),min(-1900,z0-300),max(1900,x1+300),max(1900,z1+300)
        plane = np.array([[x0,0,z0],[x1,0,z0],[x1,0,z1],
                          [x0,0,z0],[x1,0,z1],[x0,0,z1]],np.float32)
        water_buf = self.own(ctx.buffer(plane.tobytes()))
        self.water_vao = self.own(ctx.vertex_array(self.water_p,[(water_buf,"3f","in_pos")]))
        self.layers,images = atlas(paint_rgb("buoy","orange"))
        self.atlas = self.own(ctx.texture_array((ATLAS_W,ATLAS_H,len(images)),4,images.tobytes()))
        self.atlas.filter = (moderngl.LINEAR,moderngl.LINEAR)
        self.atlas.repeat_x = self.atlas.repeat_y = False
        self._buoy_id = "orange"
        corners = np.array([[-.5,0],[.5,0],[.5,1],[-.5,0],[.5,1],[-.5,1]],np.float32)
        self.tree_quad = self.own(ctx.buffer(corners.tobytes()))
        self.prop_data = self._props()
        self.prop_buf = self.own(ctx.buffer(self.prop_data.tobytes()))
        self.prop_vao = self.tree_vao(self.prop_buf)
        self.buoy_buf = self.own(ctx.buffer(reserve=7*4*24,dynamic=True))
        self.buoy_vao = self.tree_vao(self.buoy_buf)
        # One cork per hook, built once. Eight heavy lines is 192.
        self.cork_buf = self.own(ctx.buffer(reserve=7*4*192,dynamic=True))
        self.cork_vao = self.tree_vao(self.cork_buf)
        self.tree_p["atlas"] = 0
        self.water_p["reflection"] = 1
        self.post_p["scene"] = 2

    def mesh_vao(self, buf, indices=None):
        return self.own(self.ctx.vertex_array(self.mesh_p,
            [(buf,"3f 3f 3f 1f","in_pos","in_normal","in_color","in_material")],indices))

    def tree_vao(self, buf):
        return self.own(self.ctx.vertex_array(self.tree_p,[
            (self.tree_quad,"2f","in_corner"),
            (buf,"3f 2f 1f 1f /i","in_pos","in_size","in_layer","in_shade")]))

    def mesh(self, vertices):
        buf = self.own(self.ctx.buffer(vertices.astype(np.float32).tobytes()))
        return self.mesh_vao(buf)

    def _terrain(self):
        # Two-metre samples near the shore; a coarser outer apron for ridges.
        # This geometry is built exactly once and never depends on the camera.
        coords = np.unique(np.concatenate([
            np.arange(-1400,-520,20),np.arange(-520,522,3),np.arange(540,1401,20)])).astype(np.float32)
        xs,zs = coords,coords
        if self.world.id=="cedar":
            x0,z0,x1,z1 = self.world.bounds
            xs = np.arange(x0-300,x1+301,6,dtype=np.float32)
            zs = np.arange(z0-300,z1+301,6,dtype=np.float32)
        x,z = np.meshgrid(xs,zs)
        y = self.world.sample_height(x,z)
        # Match the continuous shore formula in the shader. Interior triangles
        # are clipped there, so the grid cannot move the water boundary.
        dz,dx = np.gradient(y,zs,xs)
        normals = np.stack([-dx,np.ones_like(dx),-dz],-1)
        normals /= np.linalg.norm(normals,axis=-1,keepdims=True)
        vertices = np.zeros((x.size,10),np.float32)
        vertices[:,:3] = np.stack([x,y,z],-1).reshape(-1,3)
        vertices[:,3:6] = normals.reshape(-1,3)
        vertices[:,6:9] = 0.4
        n = len(xs)
        cell = np.arange(len(zs)*n,dtype=np.uint32).reshape(len(zs),n)[:-1,:-1].reshape(-1)
        # Discard cells safely inside the lake before uploading indices.
        # The shore shader handles the remaining boundary cells precisely.
        sd = self.world.shore_sd(x,z).reshape(-1)
        land = np.maximum.reduce([sd[cell],sd[cell+1],sd[cell+n],sd[cell+n+1]])>-2.0
        cell = cell[land]
        indices = np.stack([cell,cell+1,cell+n+1,cell,cell+n+1,cell+n],-1).reshape(-1)
        buf = self.own(self.ctx.buffer(vertices.tobytes()))
        ibuf = self.own(self.ctx.buffer(indices.tobytes()))
        return self.mesh_vao(buf,ibuf)

    def _pack_faces(self, faces, cam=None):
        result = []
        for face in faces:
            pts, normal = face.pts, face.normal
            if face.space=="cam" and cam is not None:
                pts = cam.eye+pts[:,0:1]*cam.right+pts[:,1:2]*cam.up+pts[:,2:3]*cam.forward
                normal = normal[0]*cam.right+normal[1]*cam.up+normal[2]*cam.forward
            c = face.color
            # Wood has warm channels; neutral surfaces have a brushed finish.
            material = 1.0 if c[0]>c[2]*1.35 else 2.0
            if c[0]>0.8 and c[1]>0.5 and c[2]<0.3:
                material = 3.0
            if face.space=="cam":
                material += 4.0
            for i in (0,1,2,0,2,3):
                result.append((*pts[i],*normal,*c,material))
        return np.asarray(result,np.float32)

    def _detailed_boat(self, state):
        faces = self._boat_faces(state)
        if state.boat_id!="jon":
            return faces
        def q(pts,normal,color):
            faces.append(Face(np.array(pts,np.float32),np.array(normal,np.float32),
                              np.array(color,np.float32),"cam"))
        # Three actual bench boards with gaps and gently different wood tones.
        for i in range(3):
            z = 1.704+i*0.045
            c = (0.48+i*0.018,0.34+i*0.012,0.21+i*0.009)
            beam = HULL_INNER_BEAM-.035
            q([(-beam,-.736,z),(beam,-.736,z),(beam,-.736,z+.039),(-beam,-.736,z+.039)],(0,1,0),c)
        # A lipped lid and a metal clasp on the livewell.
        cy = -.96+.36*(1+state.well_tier*.12)
        q([(-.481,cy+.008,1.919),(-.139,cy+.008,1.919),(-.139,cy+.008,1.947),(-.481,cy+.008,1.947)],
          (0,1,0),(.37,.43,.42))
        q([(-.33,cy-.08,1.915),(-.27,cy-.08,1.915),(-.27,cy+.006,1.915),(-.33,cy+.006,1.915)],
          (0,0,-1),(.27,.32,.31))
        # Small gunwale rivets are geometry, visible even without texture maps.
        rail_centre = (HULL_INNER_BEAM+HULL_HALF_BEAM)*0.5
        for x in (-rail_centre,rail_centre):
            for z in np.linspace(0.5,HULL_BOW-.08,12):
                r = .009
                q([(x-r,-.46,z-r),(x+r,-.46,z-r),(x+r,-.46,z+r),(x-r,-.46,z+r)],
                  (0,1,0),(.27,.32,.33))
        # A coil of hemp line on the bow.
        for ring in range(4):
            radius = .045+ring*.012
            for i in range(24):
                a,b = i*np.pi/12,(i+1)*np.pi/12
                pts = []
                for angle,rad in ((a,radius),(b,radius),(b,radius+.007),(a,radius+.007)):
                    pts.append((.25+math.cos(angle)*rad,-.487,2.66+math.sin(angle)*rad))
                q(pts,(0,1,0),(.48,.39,.23))
        # Tread strips on the front deck.
        for x in np.linspace(-.4,.4,9):
            q([(x-.006,-.494,2.425),(x+.006,-.494,2.425),(x+.006,-.494,2.48),(x-.006,-.494,2.48)],
              (0,1,0),(.34,.39,.39))
        return faces

    def _props(self):
        from .sprites import PROP_ASPECTS, WATERLINE_KINDS
        rows = []
        for i,prop in enumerate(self.world.props):
            tree = prop.kind in ("pine","oak","cypress")
            kind = f"{prop.kind}{i%3}" if tree else prop.kind
            gy = 0 if prop.kind in WATERLINE_KINDS else float(self.world.sample_height(prop.x,prop.z))
            height = prop.h*(1.35 if tree else 1)
            aspect = ATLAS_W/ATLAS_H if tree else {
                "rock":1.5,"reed":0.50,"stump":1.17,"knee":0.56,**PROP_ASPECTS}.get(kind,0.57)
            rows.append((prop.x,gy,prop.z,height*aspect,height,self.layers[kind],prop.shade))
        return np.asarray(rows,np.float32)

    def camera_for(self,state,yaw=None,pitch=None,x=None,z=None):
        return Camera(state.x if x is None else x,state.boat.eye_height,
                      state.z if z is None else z,
                      state.yaw if yaw is None else yaw,
                      BASE_PITCH+state.look if pitch is None else pitch,
                      0.0,FOV,self.w,self.h,build_rays=False)

    def _boat_vertices(self,state,cam):
        wind_key = round(state.game_minutes+state.minute_acc,2) if state.sail_raised else 0
        key = (state.boat_id,state.sail_raised,wind_key,tuple(sorted(state.look_paint.items())),state.well_tier,state.light,float(state.steer),state.rowboat_trolling_motor)
        if key!=self._boat_key:
            self._boat_local = self._pack_faces(self._detailed_boat(state))
            self._boat_key = key
        boat = self._boat_local.copy()
        basis = np.stack([cam.right,cam.up,cam.forward],axis=1)
        boat[:,:3] = self._boat_local[:,:3]@basis.T+cam.eye
        boat[:,3:6] = self._boat_local[:,3:6]@basis.T
        return boat

    def _uniforms(self, program, state, cam, light, mirror, viewport):
        cr,sr,cp,sp = cam._cr,cam._sr,cam._cp,cam._sp
        right = cam.right*cr-cam.up*cp*sr+cam.forward*sp*sr
        up = cam.right*sr+cam.up*cp*cr-cam.forward*sp*cr
        forward = cam.up*sp+cam.forward*cp
        sl = self.world.slip
        values = dict(
            eye=tuple(cam.eye),view_right=tuple(right),view_up=tuple(up),view_forward=tuple(forward),
            tanx=cam.tanx,tany=cam.tany,anim=float(state.anim)%10000,viewport=viewport,
            sun=tuple(light["sun"]),sun_i=light["sun_i"],moon=tuple(light["moon"]),moon_i=light["moon_i"],
            night=light["night"],gold=light["gold"],horizon=tuple(light["horizon"]),zenith=tuple(light["zenith"]),
            cloud_cover=light["cloud_cover"],rain=light["rain"],mist=light.get("mist", 0.0),mirror=float(mirror),
            lake_kind=float(self.world.id=="cedar"),lake_bounds=self.world.bounds,
            lake_grid=(self.world.nx,self.world.nz),lake_shore=3,lake_depth=4,
            lily_centre=next((tuple(row[1:3]) for row in self.world.zones if row[0]=="lilies"),(-175,-115)),
            boat_pos=(state.x,state.z),boat_forward=(math.sin(state.yaw),math.cos(state.yaw)),
            speed=float(state.speed),spotlight=float(state.light),comfort_fog_radius=comfort.fog_radius(state),
            slip_origin=(sl.ox,sl.oz),slip_inland=(sl.ix,sl.iz),slip_side=(sl.sx,sl.sz),
            slip_size=(sl.half_w,sl.land_ext,sl.water_ext))
        for key,value in values.items():
            if key in program:
                program[key].value = value

    def _buoys(self,state):
        bid = state.look_paint["buoy"]
        if bid!=self._buoy_id:
            # Update only the two buoy layers, preserving all forest textures.
            from .sprites import buoy
            from .forest import _bleed_edges
            rgb = tuple(int(c*255) for c in paint_rgb("buoy",bid))
            for name,flag in (("buoy",False),("buoy_flag",True)):
                src = buoy(rgb,flag)
                ys = np.minimum(np.arange(ATLAS_H)*src.shape[0]//ATLAS_H,src.shape[0]-1)
                xs = np.minimum(np.arange(ATLAS_W)*src.shape[1]//ATLAS_W,src.shape[1]-1)
                img = _bleed_edges(src[ys[:,None],xs[None,:]])[::-1].copy()
                self.atlas.write(img.tobytes(),viewport=(0,0,self.layers[name],ATLAS_W,ATLAS_H,1))
            self._buoy_id = bid
        rows = []
        for line in state.lines:
            name = "buoy_flag" if line.fish_on() else "buoy"
            for x,z in line.buoys():
                bob = math.sin(state.anim*1.7+x)*0.025
                rows.append((x,bob,z,0.39,0.68,self.layers[name],
                             -1.0 if comfort.has_buff(state, "glow_buoys") else 1.0))
        if rows:
            self.buoy_buf.write(np.array(rows,np.float32).tobytes())
        return len(rows)

    def _corks(self, state):
        rows = []
        for line in state.lines:
            for i, hook in enumerate(line.hooks):
                if hook.catch is None and not hook.baited:
                    continue
                x, z = line.point_at(i)
                fish = hook.catch is not None
                bob = math.sin(state.anim * 1.7 + x * 0.3 + i) * 0.018
                name = "buoy_flag" if fish else "buoy"
                rows.append((
                    x, bob, z,
                    0.16 if fish else 0.09,
                    0.36 if fish else 0.16,
                    self.layers[name],
                    1.0 if fish else 0.7,
                ))
                if len(rows) >= 192:
                    break
            if len(rows) >= 192:
                break
        if rows:
            self.cork_buf.write(np.array(rows, np.float32).tobytes())
        return len(rows)

    def _scene(self,state,cam,light,mirror,fb,buoys,corks):
        ctx = self.ctx
        fb.use()
        ctx.viewport = (0,0,*fb.size)
        fb.clear(0,0,0,depth=1)
        ctx.disable(moderngl.DEPTH_TEST)
        self._uniforms(self.sky_p,state,cam,light,mirror,fb.size)
        self.sky_vao.render()
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<="
        self._uniforms(self.mesh_p,state,cam,light,mirror,fb.size)
        self.terrain.render()
        self.camp.render()
        self._uniforms(self.tree_p,state,cam,light,mirror,fb.size)
        self.atlas.use(0)
        self.prop_vao.render(instances=len(self.prop_data))
        if buoys:
            self.buoy_vao.render(instances=buoys)
        if corks:
            self.cork_vao.render(instances=corks)

    def render(self,state,cam:Camera|None=None):
        # Bind our context explicitly even when another library has presented
        # a window since the preceding frame.
        if self._owns_context:
            with self.ctx:
                return self._checked_frame(state,cam)
        return self._checked_frame(state,cam)

    def _checked_frame(self,state,cam):
        frame = self._render_frame(state,cam)
        error = self.ctx.error
        if error!="GL_NO_ERROR":
            raise RuntimeError(f"Lake rendering failed: {error}")
        return frame

    def read_depth(self):
        if self._owns_context:
            with self.ctx:
                return self.scene_fb.read(attachment=-1,components=1,dtype="f4",alignment=1)
        return self.scene_fb.read(attachment=-1,components=1,dtype="f4",alignment=1)

    def _render_frame(self,state,cam:Camera|None=None):
        t0 = time.perf_counter()
        cam = self.camera_for(state) if cam is None else cam
        light = lighting_at(state.game_minutes + state.minute_acc, state)
        self.shore_tex.use(3)
        self.depth_tex.use(4)
        buoys = self._buoys(state)
        corks = self._corks(state)
        self._scene(state,cam,light,-1,self.reflect_fb,buoys,corks)
        self._scene(state,cam,light,1,self.draw_fb,buoys,corks)
        self._uniforms(self.water_p,state,cam,light,1,self.draw_fb.size)
        self.reflect_tex.use(1)
        segments = np.zeros((8,4),np.float32)
        heat = np.zeros(8,np.float32)
        for i,line in enumerate(state.lines[:8]):
            segments[i] = (line.x0,line.z0,line.x1,line.z1)
            if line.fish_on():
                heat[i] = 1.0
        self.water_p["line_segments"].write(segments.tobytes())
        self.water_p["line_heat"].write(heat.tobytes())
        self.water_p["line_count"] = min(len(state.lines),8)
        ripples = np.zeros((4,4),np.float32)
        ripple_n = 0
        candidates = [(state.splash_x,state.splash_z,state.splash_anim),*self.splashes]
        for x,z,born in candidates:
            if ripple_n>=4:
                break
            age = float(state.anim)-float(born)
            if age<0.0 or age>2.4:
                continue
            ripples[ripple_n] = (float(x),float(z),age,1.0)
            ripple_n += 1
        self.water_p["ripples"].write(ripples.tobytes())
        self.water_p["ripple_count"] = ripple_n
        self.water_vao.render()
        boat = self._boat_vertices(state,cam)
        from .bot import faces as bot_faces
        extra = self._pack_faces(bot_faces(state))
        if len(extra):
            boat = np.concatenate([boat, extra])
        self.boat_buf.write(boat.tobytes())
        self._uniforms(self.mesh_p,state,cam,light,1,self.scene_fb.size)
        self.boat_vao.render(vertices=len(boat))
        from .ambient import faces as ambient_faces
        wildlife = self._pack_faces(ambient_faces(state,self.world,light))
        if len(wildlife):
            self.boat_buf.write(wildlife.tobytes())
            # Wildlife tests against the scene, but keeps the stable terrain
            # depth attachment untouched and allocates no extra GPU objects.
            self.draw_fb.depth_mask = False
            try:
                self.boat_vao.render(vertices=len(wildlife))
            finally:
                self.draw_fb.depth_mask = True
        if self.draw_fb is not self.scene_fb:
            self.ctx.copy_framebuffer(self.scene_fb,self.draw_fb)
        self.output_fb.use()
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.scene_tex.use(2)
        self._uniforms(self.post_p,state,cam,light,1,self.output_fb.size)
        self.post_vao.render()
        raw = self.output_fb.read(components=3,alignment=1)
        frame = np.frombuffer(raw,np.uint8).reshape(self.h,self.w,3)[::-1].copy()
        self.last_ms = (time.perf_counter()-t0)*1000
        return frame

    def close(self):
        if self.ctx is not None:
            if self._owns_context:
                with self.ctx:
                    if self._fish_card_painter is not None:
                        self._fish_card_painter.close()
                        self._fish_card_painter = None
                    self._release_objects()
                self.ctx.release()
            else:
                if self._fish_card_painter is not None:
                    self._fish_card_painter.close()
                    self._fish_card_painter = None
                self._release_objects()
            self.ctx = None

    def fish_card(self, species_id: str, shiny: bool = False):
        from .fishmesh import fish_card
        if self._fish_card_painter is None:
            return fish_card(species_id, shiny)
        if self._owns_context:
            with self.ctx:
                return self._fish_card_painter.render(species_id, shiny)
        return self._fish_card_painter.render(species_id, shiny)

    def _release_objects(self):
        for obj in reversed(self._objects):
            obj.release()
        self._objects.clear()
