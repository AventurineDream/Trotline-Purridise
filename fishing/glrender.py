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
from .florafx import ATLAS_H, ATLAS_W, GL_SAMPLE_ALPHA_TO_COVERAGE, GL_SAMPLE_ALPHA_TO_ONE, FloraAtlas, FloraFx
from .imageops import resize_rgb
from .software import FOV, BASE_PITCH, SoftwareRenderer
from .weather import lighting_at
from . import comfort
from . import detail as detail_tiers
from .world import Face
from .skyfx import SkyFx
from .waterfx import WaterFx
from .boat import HULL_INNER_BEAM, HULL_HALF_BEAM, HULL_BOW
from .landfx import LandFx
from .particlefx import ParticleFx
from .fx import reduced_motion

SHADERS = Path(__file__).with_name("shaders")
# Effect layers in draw order; each is a `fishing.fx.Fx` subclass.
FX_LAYERS: tuple = (LandFx, SkyFx, FloraFx, WaterFx, ParticleFx)
# Renderer-owned texture units beyond the effect layers' ranges (see fx.py).
BLOOM_UNIT = 20
BLOOM_SOURCE_UNIT = 21
BLOOM_LEVELS = 5
# Per-slot GPU reserves: the largest actor (Pip & Pebble, both LODs) fits with room.
CAT_VBO_BYTES = 420_000
CAT_IBO_BYTES = 90_000
CAT_BOAT_BYTES = 120_000


class LakeRenderer(SoftwareRenderer):
    """Build scene and output targets and render the final frame.

    Args:
        world: Authored or generated lake to render.
        width: Internal scene-target width in pixels.
        height: Internal scene-target height in pixels.
        context: Optional current OpenGL context.
        output_size: Final output dimensions in pixels; defaults to the scene target.
    Returns:
        None.
    Side effects:
        Allocates OpenGL textures, framebuffers, programs, and buffers.
    Raises:
        RuntimeError: If OpenGL setup fails.
    """

    def __init__(self, world, width=960, height=540, *, context=None, output_size=None):
        self.world = world
        self.ctx = context
        self._owns_context = context is None
        self.splashes = []
        self.last_ms = 0.0
        self._objects = []
        self._program_members = {}
        self._uniform_cache = {}
        self._bot_pack_key = None
        self._bot_pack = None
        self._boat_key = None
        self._boat_local = None
        self._fish_card_painter = None
        from .actors import ActorCache
        self.actor_cache = ActorCache(world)
        self._actor_draws = []
        self._impostors = 0
        self.fx = []
        self._fx_values = {}
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
            # Keep expensive scene work tiered; post-process to the window on-GPU before readback.
            target_w, target_h = ((self.w, self.h) if self.software_gl
                                  else output_size or (self.w, self.h))
            output_scale = min(1.0, 1440 / target_w, 810 / target_h)
            self.output_w = max(160, int(target_w * output_scale))
            self.output_h = max(90, int(target_h * output_scale))
            self.backend = device
            # Mesa software GL shares the lightest tier with tight-memory machines.
            self.detail = (detail_tiers.select(software=True) if self.software_gl
                           else detail_tiers.current())
            self.hdr = self.detail.hdr
            self._build()
            from .fishmesh import FishCardPainter
            self._fish_card_painter = FishCardPainter(self.ctx)
        except Exception as exc:
            self.close()
            raise RuntimeError(f"OpenGL setup: {exc}") from exc

    def program(self, vert, frag):
        """Compile a shader pair with `common.glsl` and this tier's build flags prepended."""
        common = (f"#version 330\n#define HDR {int(self.hdr)}\n"
                  + (SHADERS/"common.glsl").read_text(encoding="utf-8")+"\n")
        p = self.own(self.ctx.program(
            vertex_shader=common+(SHADERS/vert).read_text(encoding="utf-8"),
            fragment_shader=common+(SHADERS/frag).read_text(encoding="utf-8")))
        self._program_members[p] = set(p)
        return p

    def own(self, obj):
        self._objects.append(obj)
        return obj

    def program(self, vert, frag):
        common = "#version 330\n"+(SHADERS/"common.glsl").read_text(encoding="utf-8")+"\n"
        return self.own(self.ctx.program(
            vertex_shader=common+(SHADERS/vert).read_text(encoding="utf-8"),
            fragment_shader=common+(SHADERS/frag).read_text(encoding="utf-8")))

    def target(self, width, height, *, sample_depth=False, hdr=False):
        """A colour texture and framebuffer; `hdr` makes it RGBA16F so values may exceed 1."""
        tex = self.own(self.ctx.texture((width,height),4,dtype="f2") if hdr
                       else self.ctx.texture((width,height),3))
        tex.filter = (moderngl.LINEAR,moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        if sample_depth:
            depth = self.own(self.ctx.depth_texture((width,height)))
            depth.compare_func = ""
            depth.filter = (moderngl.NEAREST,moderngl.NEAREST)
            depth.repeat_x = depth.repeat_y = False
        else:
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
        self.cat_p = self.program("cat.vert","cat.frag")
        quad = self.own(ctx.buffer(np.array([[-1,-1],[3,-1],[-1,3]],np.float32).tobytes()))
        self.sky_vao = self.own(ctx.vertex_array(self.sky_p,[(quad,"2f","in_xy")]))
        self.post_vao = self.own(ctx.vertex_array(self.post_p,[(quad,"2f","in_xy")]))
        self.scene_tex,self.scene_fb = self.target(self.w,self.h,hdr=self.hdr)
        self.draw_fb = self.scene_fb
        # Save samples for the highest tiers; low/standard favour interactive speed.
        requested_samples = {"low": 1, "standard": 1, "high": 4, "ultra": 4}.get(
            self.detail.name, 1)
        self.samples = 1 if self.software_gl else min(requested_samples, ctx.max_samples)
        if self.samples>1:
            color = self.own(ctx.renderbuffer((self.w,self.h),4,samples=self.samples,dtype="f2") if self.hdr
                             else ctx.renderbuffer((self.w,self.h),3,samples=self.samples))
            depth = self.own(ctx.depth_renderbuffer((self.w,self.h),samples=self.samples))
            self.draw_fb = self.own(ctx.framebuffer([color],depth))
        self.celestial = self.world.caldera or self.world.nebula
        self.reflect_tex,self.reflect_fb = self.target(max(80,self.w//2),max(45,self.h//2),
                                                       sample_depth=True,hdr=self.hdr)
        self.output_tex,self.output_fb = self.target(self.output_w,self.output_h)
        self.bloom = []
        if self.hdr:
            self.bloom_down_p = self.program("sky.vert","bloom_down.frag")
            self.bloom_up_p = self.program("sky.vert","bloom_up.frag")
            self.bloom_down_vao = self.own(ctx.vertex_array(self.bloom_down_p,[(quad,"2f","in_xy")]))
            self.bloom_up_vao = self.own(ctx.vertex_array(self.bloom_up_p,[(quad,"2f","in_xy")]))
            bw,bh = self.w,self.h
            for _level in range(BLOOM_LEVELS):
                bw,bh = max(2,bw//2),max(2,bh//2)
                tex = self.own(ctx.texture((bw,bh),4,dtype="f2"))
                tex.filter = (moderngl.LINEAR,moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                self.bloom.append((tex,self.own(ctx.framebuffer([tex]))))
            self.bloom_down_p["src"] = BLOOM_SOURCE_UNIT
            self.bloom_up_p["src"] = BLOOM_SOURCE_UNIT
            self.post_p["bloom"] = BLOOM_UNIT
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
        # Spare layers for the distant cats' impostors, written as actors arrive.
        from .actors import MAX_ACTORS
        self.flora_atlas = FloraAtlas(self, paint_rgb("buoy","orange"), MAX_ACTORS)
        self.layers = self.flora_atlas.layers
        self.actor_layer0 = self.flora_atlas.reserve0
        self._nebula_arrays = self._nebula_uniforms()
        self.atlas = self.flora_atlas.colour
        self._buoy_id = "orange"
        corners = np.array([[-.5,0],[.5,0],[.5,1],[-.5,0],[.5,1],[-.5,1]],np.float32)
        self.tree_quad = self.own(ctx.buffer(corners.tobytes()))
        self.prop_data = self._props()
        self.prop_buf = self.own(ctx.buffer(self.prop_data.tobytes() or bytes(7*4)))
        self.prop_vao = self.tree_vao(self.prop_buf)
        self.buoy_buf = self.own(ctx.buffer(reserve=7*4*24,dynamic=True))
        self.buoy_vao = self.tree_vao(self.buoy_buf)
        # One cork per hook, built once. Eight heavy lines is 192.
        self.cork_buf = self.own(ctx.buffer(reserve=7*4*192,dynamic=True))
        self.cork_vao = self.tree_vao(self.cork_buf)
        self._build_actor_slots()
        self.tree_p["atlas"] = 0
        self.water_p["reflection"] = 1
        self.post_p["scene"] = 2
        self.fx = []
        # Procedural effect atlases use throwaway FBOs. Restore the renderer target
        # between layers so the next baker never begins with a released FBO bound.
        self.scene_fb.use()
        ctx.viewport = (0, 0, self.w, self.h)
        for layer in FX_LAYERS:
            self.fx.append(layer(self, self.detail))
            self.scene_fb.use()
            ctx.viewport = (0, 0, self.w, self.h)

    def fx_memory_bytes(self) -> int:
        """GPU bytes held by the effect layers' baked textures and buffers."""
        return sum(layer.memory_bytes() for layer in self.fx)

    def _bloom(self):
        """Build the bloom pyramid from the resolved scene into `self.bloom[0]`."""
        ctx = self.ctx
        ctx.disable(moderngl.DEPTH_TEST)
        source = self.scene_tex
        for index,(tex,fb) in enumerate(self.bloom):
            fb.use()
            ctx.viewport = (0,0,*fb.size)
            source.use(BLOOM_SOURCE_UNIT)
            self.bloom_down_p["prefilter"] = float(index==0)
            self.bloom_down_vao.render()
            source = tex
        # Each coarser level is added back into the next finer one.
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE,moderngl.ONE
        try:
            for index in range(len(self.bloom)-1,0,-1):
                tex,_fb = self.bloom[index]
                _finer,fb = self.bloom[index-1]
                fb.use()
                ctx.viewport = (0,0,*fb.size)
                tex.use(BLOOM_SOURCE_UNIT)
                self.bloom_up_vao.render()
        finally:
            ctx.disable(moderngl.BLEND)
        self.bloom[0][0].use(BLOOM_UNIT)

    def _build_actor_slots(self):
        """Fixed GPU slots for resident cats: both LODs, the boat, and one impostor layer each."""
        from .actors import MAX_ACTORS
        ctx = self.ctx
        self.actor_slots = []
        from .catmesh import VERTEX_ATTRIBUTES, VERTEX_FORMAT
        fmt, names = VERTEX_FORMAT, VERTEX_ATTRIBUTES
        for index in range(MAX_ACTORS):
            vbo = self.own(ctx.buffer(reserve=CAT_VBO_BYTES,dynamic=True))
            ibo = self.own(ctx.buffer(reserve=CAT_IBO_BYTES,dynamic=True))
            vao = self.own(ctx.vertex_array(self.cat_p,[(vbo,fmt,*names)],ibo,index_element_size=4))
            boat_vbo = self.own(ctx.buffer(reserve=CAT_BOAT_BYTES,dynamic=True))
            boat_vao = self.mesh_vao(boat_vbo)
            self.actor_slots.append({"vbo":vbo,"ibo":ibo,"vao":vao,"boat_vbo":boat_vbo,"boat_vao":boat_vao,
                                     "actor":None,"npc_id":None,
                                     "layer":self.actor_layer0+index})
        self.impostor_buf = self.own(ctx.buffer(reserve=7*4*MAX_ACTORS,dynamic=True))
        self.impostor_vao = self.tree_vao(self.impostor_buf)

    def actor_memory(self) -> dict:
        """The cat budget with this renderer's fixed slot reserves and impostor layers."""
        from .actors import MAX_ACTORS, memory_report
        gpu = (MAX_ACTORS*(CAT_VBO_BYTES+CAT_IBO_BYTES+CAT_BOAT_BYTES+self.flora_atlas.layer_bytes)
               + self.impostor_buf.size)
        return memory_report(self.actor_cache,gpu_bytes=gpu)

    def _upload_actor(self, slot, actor):
        """Both LODs of one cat, its boat, and its impostor into a slot (once per arrival)."""
        from .catmesh import LOD0, LOD1, vertex_block
        from .catart import impostor
        blocks, tris, ranges, offset, first = [], [], {}, 0, 0
        for lod in (LOD0, LOD1):
            mesh = actor.mesh(lod)
            blocks.append(vertex_block(mesh))
            cat_ranges = []
            for look, lo, hi in mesh.cats:
                owned = np.flatnonzero((mesh.triangles[:,0] >= lo) & (mesh.triangles[:,0] < hi))
                cat_ranges.append((look, first+int(owned.min())*3, int(len(owned))*3))
            ranges[lod] = cat_ranges
            tris.append(mesh.triangles+offset)
            offset += len(blocks[-1])
            first += len(mesh.triangles)*3
        vertices = np.concatenate(blocks).astype(np.float32)
        indices = np.concatenate(tris).astype(np.uint32)
        if vertices.nbytes > CAT_VBO_BYTES or indices.nbytes > CAT_IBO_BYTES:
            raise RuntimeError(f"cat {actor.npc_id} exceeds its GPU slot")
        slot["vbo"].write(vertices.tobytes())
        slot["ibo"].write(indices.tobytes())
        boat = self._pack_faces(actor.boat_faces) if actor.boat_faces else np.zeros((0,10),np.float32)
        if boat.nbytes > CAT_BOAT_BYTES:
            raise RuntimeError(f"boat for {actor.npc_id} exceeds its GPU slot")
        if len(boat):
            slot["boat_vbo"].write(boat.tobytes())
        slot.update(actor=actor, npc_id=actor.npc_id, ranges=ranges, boat_vertices=len(boat))
        # The impostor fills its atlas layer, feet on the bottom edge.
        sprite,width_m,height_m,base_m = impostor(actor.npc_id)
        self.flora_atlas.write_sprite(slot["layer"],sprite)
        slot["impostor"] = (width_m,height_m,base_m)

    def _prepare_actors(self, state, cam):
        """Pick each present cat's slot, LOD and animation for this frame."""
        from .actors import lod_for, pose_state, roster
        actors = self.actor_cache.sync(getattr(state,"npcs",()) or (), roster())
        reduced = bool(state.v2.get("settings",{}).get("reduced_motion",False)) if isinstance(state.v2,dict) else False
        draws, impostors = [], []
        # Slots follow the placed actor, not the cat: a cat moved to a new anchor
        # (a cookout on the landing) is re-placed, and its slot is uploaded afresh.
        live = {id(actor) for actor in actors}
        for slot in self.actor_slots:
            if id(slot["actor"]) not in live:
                slot["actor"] = slot["npc_id"] = None
        for actor in actors:
            slot = next((s for s in self.actor_slots if s["actor"] is actor),None)
            if slot is None:
                slot = next(s for s in self.actor_slots if s["actor"] is None)
                self._upload_actor(slot,actor)
            distance = math.hypot(actor.x-cam.eye[0],actor.z-cam.eye[2])
            lod = lod_for(distance)
            if lod is None:
                width_m,height_m,base_m = slot["impostor"]
                impostors.append((actor.x,actor.y+base_m,actor.z,width_m,height_m,slot["layer"],1.0))
            draws.append((actor,slot,lod,pose_state(actor,state.x,state.z,state.anim,reduced)))
        self._actor_draws = draws
        if impostors:
            self.impostor_buf.write(np.asarray(impostors,np.float32).tobytes())
        self._impostors = len(impostors)

    def _draw_actors(self, state, cam, light, mirror, fb):
        if not self._actor_draws:
            return
        from .actors import shader_uniforms
        from .catmesh import PATTERNS
        self._uniforms(self.mesh_p,state,cam,light,mirror,fb.size)
        for _actor,slot,_lod,_p in self._actor_draws:
            if slot["boat_vertices"]:
                slot["boat_vao"].render(vertices=slot["boat_vertices"])
        self._uniforms(self.cat_p,state,cam,light,mirror,fb.size)
        program = self.cat_p
        for actor,slot,lod,params in self._actor_draws:
            if lod is None:
                continue
            for key,value in shader_uniforms(actor,actor.mesh(lod),params).items():
                if key in self._program_members[program]:
                    program[key].value = value
            for cat_look,first,count in slot["ranges"][lod]:
                colors = cat_look["colors"]
                coat = dict(pattern=PATTERNS.index(cat_look["pattern"]),coat_base=tuple(colors["base"]),
                            coat_secondary=tuple(colors["secondary"]),coat_accent=tuple(colors["accent"]),
                            coat_scale=float(cat_look["size"]),coat_glow=float(cat_look.get("glow",0.0)))
                for key,value in coat.items():
                    if key in self._program_members[program]:
                        program[key].value = value
                slot["vao"].render(moderngl.TRIANGLES,vertices=count,first=first)

    def _nebula_uniforms(self):
        """Fixed lane circles and drift ellipses, packed once for the shaders."""
        lanes = np.zeros((48,3),np.float32)
        drifts = np.zeros((12,4),np.float32)
        lane_count = drift_count = 0
        if self.world.nebula:
            from .nebula import lane_circles
            rows = lane_circles(self.world)
            lane_count = len(rows)
            lanes[:lane_count] = rows
            shapes = np.asarray(self.world.environment["drifts"],np.float32)
            drift_count = len(shapes)
            drifts[:drift_count] = shapes
        return {"lane_circles":(lanes.tobytes(),lane_count),"drift_shapes":(drifts.tobytes(),drift_count)}

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
        if self.world.placeholder:
            xs = np.arange(-600, 601, 10, dtype=np.float32)
            zs = np.arange(-500, 501, 10, dtype=np.float32)
        if self.world.id=="cedar" or self.world.generated:
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
        """Pack quads into the exact triangle-vertex order consumed by mesh shaders."""
        if not faces:
            return np.zeros((0, 10), np.float32)
        points, normals, colors, materials = [], [], [], []
        for face in faces:
            pts, normal = face.pts, face.normal
            if face.space == "cam" and cam is not None:
                pts = cam.eye + pts[:, 0:1] * cam.right + pts[:, 1:2] * cam.up + pts[:, 2:3] * cam.forward
                normal = normal[0] * cam.right + normal[1] * cam.up + normal[2] * cam.forward
            c = face.color
            material = 1.0 if c[0] > c[2] * 1.35 else 2.0
            if c[0] > 0.8 and c[1] > 0.5 and c[2] < 0.3:
                material = 3.0
            if face.emissive is not None:
                material = 8.0 + face.emissive if face.emissive > 0 else 2.0
            if face.space == "cam":
                material += 4.0
            points.append(pts)
            normals.append(normal)
            colors.append(c)
            materials.append(material)
        points = np.asarray(points, np.float32)[:, (0, 1, 2, 0, 2, 3), :]
        count = len(faces)
        result = np.empty((count, 6, 10), np.float32)
        result[:, :, :3] = points
        result[:, :, 3:6] = np.asarray(normals, np.float32)[:, None, :]
        result[:, :, 6:9] = np.asarray(colors, np.float32)[:, None, :]
        result[:, :, 9] = np.asarray(materials, np.float32)[:, None]
        return result.reshape(-1, 10)

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
        self._prop_variant = []
        for i,prop in enumerate(self.world.props):
            tree = prop.kind in ("pine","oak","cypress","larch","spruce","hemlock","whitebark","deadpine")
            # Painted variants are picked by position so neighbours differ.
            variant = self.flora_atlas.variant(prop.kind,prop.x,prop.z)
            self._prop_variant.append(variant)
            kind = prop.kind
            gy = 0 if prop.kind in WATERLINE_KINDS else float(self.world.sample_height(prop.x,prop.z))
            height = prop.h*(1.35 if tree else 1)
            aspect = ATLAS_W/ATLAS_H if tree else {
                "rock":1.5,"reed":0.50,"stump":1.17,"knee":0.56,**PROP_ASPECTS}.get(kind,0.57)
            rows.append((prop.x,gy,prop.z,height*aspect,height,self.layers[f"{kind}{variant}"],prop.shade))
        return np.asarray(rows,np.float32)

    def camera_for(self,state,yaw=None,pitch=None,x=None,z=None):
        """Create a ray-free scene camera whose screen coordinates match final output.

        Args:
            state: Current simulation state.
            yaw: Optional camera yaw in radians.
            pitch: Optional camera pitch in radians.
            x: Optional camera x position in world units.
            z: Optional camera z position in world units.
        Returns:
            Camera used by the scene renderer and screen-space overlays.
        Side effects:
            None.
        """
        return Camera(state.x if x is None else x,state.boat.eye_height,
                      state.z if z is None else z,
                      state.yaw if yaw is None else yaw,
                      BASE_PITCH+state.look if pitch is None else pitch,
                      0.0,FOV,self.output_w,self.output_h,build_rays=False)

    def _boat_vertices(self,state,cam):
        wind_key = round(state.game_minutes+state.minute_acc,2) if state.sail_raised else 0
        key = (state.boat_id,state.sail_raised,wind_key,tuple(sorted(state.look_paint.items())),state.well_tier,state.light,float(state.steer),state.rowboat_trolling_motor)
        if key!=self._boat_key:
            self._boat_local = self._pack_faces(self._detailed_boat(state))
            self._boat_key = key
        boat = self._boat_local.copy()
        cam = cam.boat or cam  # a staged view sees the boat where it floats (V1-35)
        basis = np.stack([cam.right,cam.up,cam.forward],axis=1)
        boat[:,:3] = self._boat_local[:,:3]@basis.T+cam.eye
        boat[:,3:6] = self._boat_local[:,3:6]@basis.T
        return boat

    def _uniforms(self, program, state, cam, light, mirror, viewport):
        cache_key = (mirror, tuple(viewport))
        values = self._uniform_cache.get(cache_key)
        if values is None:
            cr,sr,cp,sp = cam._cr,cam._sr,cam._cp,cam._sp
            right = cam.right*cr-cam.up*cp*sr+cam.forward*sp*sr
            up = cam.right*sr+cam.up*cp*cr-cam.forward*sp*cr
            forward = cam.up*sp+cam.forward*cp
            sl = self.world.slip
            from .caldera import reflection_strength
            anim = 0.0 if reduced_motion(state) else float(state.anim) % 10000
            island = (self.world.environment or {}).get("islands", [(0,0,1,1,0)])[0]
            values = dict(still_reflection=reflection_strength(state, light),cinder_island=tuple(island[:4]),
                eye=tuple(cam.eye),view_right=tuple(right),view_up=tuple(up),view_forward=tuple(forward),
                tanx=cam.tanx,tany=cam.tany,anim=anim,viewport=viewport,
                sun=tuple(light["sun"]),sun_i=light["sun_i"],moon=tuple(light["moon"]),moon_i=light["moon_i"],
                night=light["night"],gold=light["gold"],horizon=tuple(light["horizon"]),zenith=tuple(light["zenith"]),
                cloud_cover=light["cloud_cover"],rain=light["rain"],mist=light.get("mist", 0.0),mirror=float(mirror),
                lake_kind=(5.0 if self.world.nebula else 4.0 if self.world.caldera else 3.0 if self.world.generated
                           else (2.0 if self.world.placeholder else float(self.world.id=="cedar"))),
                starlight=float(light.get("starlight",0.0)),aurora_i=float(light.get("aurora",0.0)),
                meteors=float(light.get("meteors",0.0)),
                nebula_mid=tuple((self.world.environment or {}).get("water_mid",(.2,.1,.4))),
                shoal=next((tuple(row[1:4]) for row in self.world.zones if row[0]=="flats"),(0,0,1)),
                snow=light.get("snow", 0.0),snow_anim=anim,
                snow_line=(self.world.environment or {}).get("snow_line", 95),
                alpine_shallow=tuple((self.world.environment or {}).get("water_shallow", (.17,.49,.43))),
                alpine_deep=tuple((self.world.environment or {}).get("water_deep", (.015,.15,.23))),
                lake_bounds=self.world.bounds,
                lake_water=tuple(self.world.palette["water"]),
                lake_grid=(self.world.nx,self.world.nz),lake_shore=3,lake_depth=4,reflection_depth=5,
                lily_centre=next((tuple(row[1:3]) for row in self.world.zones if row[0]=="lilies"),(-175,-115)),
                boat_pos=(state.x,state.z),boat_forward=(math.sin(state.yaw),math.cos(state.yaw)),
                speed=float(state.speed),spotlight=float(state.light),comfort_fog_radius=comfort.fog_radius(state),
                slip_origin=(sl.ox,sl.oz),slip_inland=(sl.ix,sl.iz),slip_side=(sl.sx,sl.sz),
                slip_size=(sl.half_w,sl.land_ext,sl.water_ext))
            self._uniform_cache[cache_key] = values
        members = self._program_members[program]
        for key,value in values.items():
            if key in members:
                program[key].value = value
        for key,(data,count) in self._nebula_arrays.items():
            if key in members:
                program[key].write(data)
                program[key.split("_")[0]+"_count"].value = count
        for key,value in self._fx_values.items():
            if key in members:
                if isinstance(value,(bytes,bytearray)):
                    program[key].write(value)
                else:
                    program[key].value = value

    def _buoys(self,state):
        anim = 0.0 if reduced_motion(state) else float(state.anim)
        bid = state.look_paint["buoy"]
        if bid!=self._buoy_id:
            # Update only the two buoy layers, preserving all forest textures.
            from .sprites import buoy
            rgb = tuple(int(c*255) for c in paint_rgb("buoy",bid))
            for name,flag in (("buoy",False),("buoy_flag",True)):
                self.flora_atlas.write_sprite(self.layers[name],buoy(rgb,flag))
            self._buoy_id = bid
        rows = []
        for line in state.lines:
            name = "buoy_flag" if line.fish_on() else "buoy"
            for x,z in line.buoys():
                bob = math.sin(anim*1.7+x)*0.025
                rows.append((x,bob,z,0.39,0.68,self.layers[name],
                             -1.0 if comfort.has_buff(state, "glow_buoys") else 1.0))
        if rows:
            self.buoy_buf.write(np.array(rows,np.float32).tobytes())
        return len(rows)

    def _corks(self, state):
        anim = 0.0 if reduced_motion(state) else float(state.anim)
        rows = []
        for line in state.lines:
            for i, hook in enumerate(line.hooks):
                if hook.catch is None and not hook.baited:
                    continue
                x, z = line.point_at(i)
                fish = hook.catch is not None
                bob = math.sin(anim * 1.7 + x * 0.3 + i) * 0.018
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
        self.flora_atlas.refresh()
        self.atlas.use(0)
        # Alpha-to-coverage antialiases billboard edges in the multisampled main
        # pass; the half-res reflection has one sample and alpha-tests instead.
        coverage = mirror>0 and self.samples>1
        if coverage:
            ctx.enable_direct(GL_SAMPLE_ALPHA_TO_COVERAGE)
            ctx.enable_direct(GL_SAMPLE_ALPHA_TO_ONE)
        try:
            if len(self.prop_data):
                self.prop_vao.render(instances=len(self.prop_data))
            if buoys:
                self.buoy_vao.render(instances=buoys)
            if corks:
                self.cork_vao.render(instances=corks)
            if self._impostors:
                self.impostor_vao.render(instances=self._impostors)
        finally:
            if coverage:
                ctx.disable_direct(GL_SAMPLE_ALPHA_TO_COVERAGE)
                ctx.disable_direct(GL_SAMPLE_ALPHA_TO_ONE)
        self._draw_actors(state,cam,light,mirror,fb)
        if mirror<0:
            self._draw_skipper_reflection(state,cam,light,mirror,fb)
        for layer in self.fx:
            layer.draw(state,cam=cam,light=light,mirror=mirror,stage="scene")

    def _paw_vertices(self, state, cam):
        """The Skipper's paws in the eye frame, as cockpit triangles (V1-29)."""
        from .skipper import paw_mesh
        reduced = bool(state.v2.get("settings",{}).get("reduced_motion",False))
        pos,nrm,rgb,tris = paw_mesh(state,reduced)
        flat = tris.reshape(-1)
        out = np.empty((len(flat),10),np.float32)
        cam = cam.boat or cam
        basis = np.stack([cam.right,cam.up,cam.forward],axis=1)
        out[:,:3] = pos[flat]@basis.T+cam.eye
        out[:,3:6] = nrm[flat]@basis.T
        out[:,6:9] = rgb[flat]
        out[:,9] = 6.0  # cockpit space, plain finish
        return out

    def _draw_skipper_reflection(self, state, cam, light, mirror, fb):
        """The Skipper's head, drawn into the reflection pass only, on calm water at idle."""
        from .skipper import head_silhouette, shows_reflection
        if not shows_reflection(state,light):
            return
        pos,nrm,rgb,tris = head_silhouette(state)
        flat = tris.reshape(-1)
        head = np.empty((len(flat),10),np.float32)
        head[:,:3],head[:,3:6],head[:,6:9],head[:,9] = pos[flat],nrm[flat],rgb[flat],2.0
        # The cockpit buffer is free until the main pass writes this frame's boat.
        self.boat_buf.write(head.tobytes())
        self._uniforms(self.mesh_p,state,cam,light,mirror,fb.size)
        self.boat_vao.render(vertices=len(head))

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
        self._uniform_cache = {}
        t0 = time.perf_counter()
        cam = self.camera_for(state) if cam is None else cam
        light = lighting_at(state.game_minutes + state.minute_acc, state)
        self.shore_tex.use(3)
        self.depth_tex.use(4)
        self._fx_values = {}
        for layer in self.fx:
            layer.bind()
            self._fx_values.update(layer.uniforms(state,light,cam))
        if self.world.generated:
            from .lakegen import larch_gold
            gold = larch_gold(state)
            if gold != getattr(self, "_larch_gold", None):
                for i, prop in enumerate(self.world.props):
                    if prop.kind == "larch":
                        self.prop_data[i, 5] = self.layers[f"{'larchgold' if gold else 'larch'}{self._prop_variant[i]}"]
                self.prop_buf.write(self.prop_data.tobytes())
                self._larch_gold = gold
        buoys = self._buoys(state)
        corks = self._corks(state)
        self._prepare_actors(state,cam)
        self._scene(state,cam,light,-1,self.reflect_fb,buoys,corks)
        self._scene(state,cam,light,1,self.draw_fb,buoys,corks)
        self._uniforms(self.water_p,state,cam,light,1,self.draw_fb.size)
        self.reflect_tex.use(1)
        if self.celestial:
            self.reflect_fb.depth_attachment.use(5)
        segments = np.zeros((8,4),np.float32)
        heat = np.zeros(8,np.float32)
        for i,line in enumerate(state.lines[:8]):
            segments[i] = (line.x0,line.z0,line.x1,line.z1)
            if line.fish_on():
                heat[i] = 1.0
        self.water_p["line_segments"].write(segments.tobytes())
        self.water_p["line_heat"].write(heat.tobytes())
        self.water_p["line_count"] = min(len(state.lines),8)
        anim = 0.0 if reduced_motion(state) else float(state.anim)
        ripples = np.zeros((4,4),np.float32)
        ripple_n = 0
        candidates = [(state.splash_x,state.splash_z,state.splash_anim),*self.splashes]
        for x,z,born in candidates:
            if ripple_n>=4:
                break
            age = anim - float(born)
            if age<0.0 or age>2.4:
                continue
            ripples[ripple_n] = (float(x),float(z),age,1.0)
            ripple_n += 1
        self.water_p["ripples"].write(ripples.tobytes())
        self.water_p["ripple_count"] = ripple_n
        self.water_vao.render()
        boat = self._boat_vertices(state,cam)
        from .bot import faces as bot_faces
        profile = state.v2.get("profile", {}) if isinstance(state.v2, dict) else {}
        settings = state.v2.get("settings", {}) if isinstance(state.v2, dict) else {}
        collar = profile.get("collar", {}) if isinstance(profile, dict) else {}
        if state.bot_phase == "home":
            bot_key = (
                state.x, state.z, state.yaw, state.boat_id, state.boat.eye_height,
                profile.get("shell", "tin"), collar.get("stage", "none"),
                collar.get("knot"), collar.get("visible", True),
                settings.get("collar_visible", True), settings.get("reduced_motion", False),
            )
            if bot_key != self._bot_pack_key:
                self._bot_pack = self._pack_faces(bot_faces(state))
                self._bot_pack_key = bot_key
            extra = self._bot_pack
        else:
            self._bot_pack_key = None
            extra = self._pack_faces(bot_faces(state))
        if len(extra):
            boat = np.concatenate([boat, extra])
        paws = self._paw_vertices(state,cam)
        if len(paws):
            boat = np.concatenate([boat, paws])
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
        for layer in self.fx:
            layer.draw(state,cam=cam,light=light,mirror=1,stage="over")
        if self.draw_fb is not self.scene_fb:
            self.ctx.copy_framebuffer(self.scene_fb,self.draw_fb)
        if self.bloom:
            self._bloom()
        self.output_fb.use()
        self.ctx.viewport = (0,0,*self.output_fb.size)
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.scene_tex.use(2)
        self._uniforms(self.post_p,state,cam,light,1,self.output_fb.size)
        self.post_vao.render()
        raw = self.output_fb.read(components=3,alignment=1)
        frame = np.frombuffer(raw,np.uint8).reshape(self.output_h,self.output_w,3)[::-1].copy()
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
