"""V1-29 cats: roster data, the rig and its LODs, shader agreement, actors in the world, portraits and the Skipper."""

from copy import deepcopy
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from . import actors, catart, catmesh, skipper
from .catmesh import FUR_PARTS, LOD0, LOD1, PATTERNS, POSES
from .content import _BOAT_PAINT_IDS, ContentError, load_content, load_content_v2, validate_content_v2
from .data import CONTENT_V2_RAW, PAINT
from .dialogue import HAIL_RANGE_M, HAIL_SPEED_MPS, nearby_npc
from .narrative import DAY_NPCS
from .npcs import NPC, active_npcs
from .sim import State
from .world import World

ROSTER = load_content_v2().roster
NARRATIVE = load_content()
SHADERS = Path(__file__).with_name("shaders")


def _gl_context(test):
    try:
        import moderngl
    except ImportError:
        test.skipTest("ModernGL is not installed in this environment")
    try:
        return moderngl.create_standalone_context(require=330, backend="egl")
    except Exception as exc:
        test.skipTest(f"Standalone EGL is unavailable: {exc}")


def _lake(lake_id, seed=3):
    world = World(lake_id)
    state = State.new(world, seed=seed)
    state.game_minutes = 10 * 60
    state.npcs = active_npcs(state, world, NARRATIVE)
    return world, state


class RosterData(unittest.TestCase):
    def test_52_cats_in_51_rows_with_hosts_travelers_and_water_cats(self):
        self.assertEqual(len(ROSTER), 51)
        cats = sum(1 + ("twin" in row["appearance"]) for row in ROSTER.values())
        self.assertEqual(cats, 52)
        roles = [row["role"] for row in ROSTER.values()]
        self.assertEqual((roles.count("host"), roles.count("traveler"), roles.count("water")), (5, 2, 44))
        self.assertEqual([npc_id for npc_id, row in ROSTER.items() if "twin" in row["appearance"]], ["pip_pebble"])
        for lake, pool in DAY_NPCS.items():
            for npc_id in pool:
                self.assertEqual(ROSTER[npc_id]["lake"], lake, npc_id)
        for row in ROSTER.values():
            if row["role"] == "host":
                self.assertIsNone(row["boat"])
            else:
                self.assertNotIn(row["boat"], {"jon", "rowboat", "sail", "pontoon"})

    def test_every_pose_pattern_and_coat_is_cast(self):
        looks = [row["appearance"] for row in ROSTER.values()]
        self.assertEqual({look["pose"] for look in looks}, set(POSES))
        self.assertEqual({look["pattern"] for look in looks}, set(PATTERNS))
        self.assertEqual({look["ears"] for look in looks}, {"pointed", "folded", "tufted", "rounded"})
        self.assertEqual({look["tail"] for look in looks}, {"long", "bob", "none", "plume"})

    def test_boat_paint_ids_mirror_the_shop_paints(self):
        for slot, ids in _BOAT_PAINT_IDS.items():
            self.assertEqual(ids, {row[0] for row in PAINT[slot]}, slot)

    def test_validator_rejects_bad_cats_without_crashing(self):
        cases = []

        def case(where, message, edit):
            raw = deepcopy(CONTENT_V2_RAW)
            edit(raw["npcs.json"]["npcs"])
            cases.append((raw, where, message))

        def look(i):
            return lambda rows: rows[i]["appearance"]

        case("npcs[0](grandmother_whiskers).appearance.pattern", "unknown value/reference 'plaid'",
             lambda rows: rows[0]["appearance"].update(pattern="plaid"))
        case("npcs[0](grandmother_whiskers).appearance.size", "<= 1.4",
             lambda rows: rows[0]["appearance"].update(size=2.0))
        case("npcs[1](doc_barnaby).appearance.attire[0].kind", "unknown value/reference",
             lambda rows: rows[1]["appearance"].update(attire=[{"kind": {"x": 1}, "color": [1, 1, 1]}]))
        case("npcs[1](doc_barnaby).appearance.attire", "each attire kind once",
             lambda rows: rows[1]["appearance"].update(attire=[{"kind": "cap", "color": [1, 1, 1]}] * 2))
        case("npcs[1](doc_barnaby).appearance.attire", "at most four",
             lambda rows: rows[1]["appearance"].update(attire=[
                 {"kind": kind, "color": [1, 1, 1]} for kind in ("cap", "scarf", "vest", "shawl", "goggles")]))
        case("npcs[7](elder_moss).appearance.prop", "unknown value/reference 'brush'",
             lambda rows: rows[7]["appearance"].update(prop="brush"))
        case("npcs[8](pip_pebble).appearance.twin", "unknown field 'twin'",
             lambda rows: rows[8]["appearance"]["twin"].update(twin=deepcopy(rows[8]["appearance"]["twin"])))
        case("npcs[2](captain_huckleberry).boat", "hosts stand on their landing",
             lambda rows: rows[2].update(boat="dory"))
        case("npcs[7](elder_moss).boat", "generated family boat", lambda rows: rows[7].update(boat="jon"))
        case("npcs[7](elder_moss).boat_paint", "hull, deck or motor", lambda rows: rows[7].update(boat_paint={"sail": "red"}))
        case("npcs", "5 hosts, 2 travelers and 44 water-cat rows", lambda rows: rows.pop())
        case("npcs[0](grandmother_whiskers).appearance", "unknown field 'hat'",
             lambda rows: look(0)(rows).update(hat=True))
        for raw, where, message in cases:
            with self.subTest(where=where, message=message), self.assertRaises(ContentError) as caught:
                validate_content_v2(raw)
            text = str(caught.exception)
            self.assertIn(where, text)
            self.assertIn(message, text)


class Rig(unittest.TestCase):
    def test_every_cat_builds_finite_read_only_lods_within_budget(self):
        for npc_id, row in ROSTER.items():
            twin = "twin" in row["appearance"]
            counts = {}
            for lod in (LOD0, LOD1):
                with self.subTest(npc=npc_id, lod=lod):
                    mesh = catmesh.cat_mesh(npc_id, lod)
                    counts[lod] = mesh.triangle_count
                    base = row["appearance"]["pose"]
                    self.assertIn(base, mesh.positions)
                    self.assertIn("wave", mesh.positions)
                    for positions in mesh.positions.values():
                        self.assertTrue(np.isfinite(positions).all())
                        self.assertFalse(positions.flags.writeable)
                    self.assertGreaterEqual(int(mesh.triangles.min()), 0)
                    self.assertLess(int(mesh.triangles.max()), len(mesh.part))
                    self.assertEqual(len(mesh.cats), 2 if twin else 1)
            self.assertLessEqual(counts[LOD0], 5000 if twin else 2800, npc_id)
            self.assertLessEqual(counts[LOD1], 1600 if twin else 1000, npc_id)
            self.assertLess(counts[LOD1] * 2.5, counts[LOD0], npc_id)

    def test_the_lod0_mesh_cache_stays_bounded(self):
        catmesh.clear_caches()
        for npc_id in list(ROSTER)[:40]:
            catmesh.cat_mesh(npc_id, LOD1)
        self.assertLessEqual(catmesh._cached.cache_info().currsize, catmesh.MESH_CACHE)
        self.assertLess(catmesh.cache_bytes_bound(), 20 * 2 ** 20)

    def test_solid_coats_are_plain_and_every_other_pattern_marks_fur(self):
        for pattern, npc_id in ((row["appearance"]["pattern"], npc_id) for npc_id, row in ROSTER.items()):
            mesh = catmesh.cat_mesh(npc_id, LOD0)
            look, lo, hi = mesh.cats[0]
            fur = np.isin(mesh.part[lo:hi], FUR_PARTS)
            sec, acc = catmesh.coat_weights(pattern, mesh.coat[lo:hi], mesh.coat_normals[lo:hi], mesh.part[lo:hi],
                                            mesh.along[lo:hi], size=float(look["size"]))
            marked = float(((sec + acc) > 0.5)[fur].mean())
            with self.subTest(npc=npc_id, pattern=pattern):
                if pattern == "solid":
                    self.assertEqual(marked, 0.0)
                else:
                    self.assertGreater(marked, 0.02)

    def test_paint_carries_attire_and_prop_colours(self):
        mesh = catmesh.cat_mesh("grandmother_whiskers", LOD0)
        rgb, glow = catmesh.paint(mesh)
        look = mesh.cats[0][0]
        shawl = next(i for i, item in enumerate(look["attire"]) if item["kind"] == "shawl")
        worn = (mesh.tags == shawl) & (mesh.part == catmesh.ATTIRE)
        self.assertTrue(worn.any())
        np.testing.assert_allclose(rgb[worn], np.broadcast_to(look["attire"][shawl]["color"], rgb[worn].shape),
                                   atol=1e-6)
        prop = mesh.part == catmesh.PROP
        np.testing.assert_allclose(rgb[prop][0], catmesh.PROP_COLOURS[look["prop"]], atol=1e-6)
        self.assertEqual(float(glow.max()), 0.0)


class ShaderAgreement(unittest.TestCase):
    def test_cat_frag_coat_patterns_match_the_numpy_reference(self):
        ctx = _gl_context(self)
        import moderngl
        try:
            source = (SHADERS / "cat.frag").read_text()
            body = source[source.index("const float TORSO"):source.index("void main()")]
            program = ctx.program(vertex_shader="#version 330\nin vec2 in_xy;\n"
                                                "void main() { gl_Position = vec4(in_xy, 0.0, 1.0); }",
                                  fragment_shader="#version 330\nuniform int pattern;\nuniform sampler2D samples;\n"
                                                  "out vec4 frag;\n" + body + """
void main() {
    int i = int(gl_FragCoord.x);
    vec4 a = texelFetch(samples, ivec2(i, 0), 0);
    vec4 b = texelFetch(samples, ivec2(i, 1), 0);
    frag = vec4(coat_weights(a.xyz, normalize(b.xyz), a.w, b.w), 0.0, 1.0);
}""")
            quad = ctx.buffer(np.array([[-1, -1], [3, -1], [-1, 3]], np.float32).tobytes())
            vao = ctx.vertex_array(program, [(quad, "2f", "in_xy")])
            for pattern, npc_id in sorted({row["appearance"]["pattern"]: npc_id
                                           for npc_id, row in ROSTER.items()}.items()):
                mesh = catmesh.cat_mesh(npc_id, LOD0)
                look, lo, hi = mesh.cats[0]
                size = float(look["size"])
                fur = np.flatnonzero(np.isin(mesh.part[lo:hi], FUR_PARTS)) + lo
                p, n = mesh.coat[fur] / size, mesh.coat_normals[fur]
                data = np.zeros((2, len(fur), 4), np.float32)
                data[0, :, :3], data[0, :, 3] = p, mesh.part[fur]
                data[1, :, :3], data[1, :, 3] = n, mesh.along[fur]
                texture = ctx.texture((len(fur), 2), 4, data.tobytes(), dtype="f4")
                texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
                target = ctx.texture((len(fur), 1), 4, dtype="f4")
                fb = ctx.framebuffer([target])
                fb.use()
                ctx.viewport = (0, 0, len(fur), 1)
                texture.use(0)
                program["samples"] = 0
                program["pattern"] = PATTERNS.index(pattern)
                vao.render()
                gl = np.frombuffer(fb.read(components=4, dtype="f4"), np.float32).reshape(-1, 4)
                n_unit = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
                sec, acc = catmesh.coat_weights(pattern, mesh.coat[fur], n_unit, mesh.part[fur], mesh.along[fur],
                                                size=size)
                agree = (np.abs(gl[:, 0] - sec) < 0.02) & (np.abs(gl[:, 1] - acc) < 0.02)
                with self.subTest(pattern=pattern, npc=npc_id):
                    self.assertGreater(float(agree.mean()), 0.97)
                for obj in (fb, target, texture):
                    obj.release()
            for obj in (vao, quad, program):
                obj.release()
        finally:
            ctx.release()

    def test_cat_vert_motion_matches_the_numpy_rig(self):
        ctx = _gl_context(self)
        import moderngl
        try:
            common = (SHADERS / "common.glsl").read_text()
            program = ctx.program(vertex_shader="#version 330\n" + common + "\n" + (SHADERS / "cat.vert").read_text(),
                                  varyings=["pos"])
            # Headless EGL has no default framebuffer, and a draw needs one even with no fragments.
            fb = ctx.simple_framebuffer((1, 1))
            fb.use()
            world, state = _lake("briar")
            for actor in actors.ActorCache(world).sync(state.npcs, actors.roster()):
                for distance, t in ((6.0, 3.7), (35.0, 11.2), (60.0, 0.4)):
                    mesh = actor.mesh(LOD0)
                    params = actors.pose_state(actor, actor.x + distance, actor.z + 1.0, t, False)
                    vertices = catmesh.vertex_block(mesh)
                    vbo = ctx.buffer(vertices.tobytes())
                    out = ctx.buffer(reserve=len(vertices) * 12)
                    # Only `pos` is captured, so the compiler drops the paint attributes.
                    vao = ctx.vertex_array(program, [(vbo, catmesh.VERTEX_FORMAT, *catmesh.VERTEX_ATTRIBUTES)],
                                           skip_errors=True)
                    for key, value in {**actors.shader_uniforms(actor, mesh, params), "mirror": 1.0}.items():
                        if key in program:
                            program[key].value = value
                    vao.transform(out, moderngl.POINTS, vertices=len(vertices))
                    gl = np.frombuffer(out.read(), np.float32).reshape(-1, 3)
                    cpu = actor.local_to_world(actors.animate(mesh, params)[0])
                    with self.subTest(npc=actor.npc_id, distance=distance):
                        np.testing.assert_allclose(gl, cpu, atol=2e-4)
                    for obj in (vao, out, vbo):
                        obj.release()
            fb.release()
            program.release()
        finally:
            ctx.release()


class Actors(unittest.TestCase):
    def test_both_lakes_show_their_host_and_day_cat_where_they_belong(self):
        for lake in ("briar", "cedar"):
            world, state = _lake(lake)
            present = actors.ActorCache(world).sync(state.npcs, actors.roster())
            self.assertEqual([a.npc_id for a in present], [npc.id for npc in state.npcs])
            for actor, npc in zip(present, state.npcs):
                with self.subTest(lake=lake, npc=actor.npc_id):
                    row = ROSTER[actor.npc_id]
                    offset = math.hypot(actor.x - npc.anchor.x, actor.z - npc.anchor.z)
                    if row["role"] == "host":
                        self.assertIsNone(actor.boat_id)
                        self.assertLessEqual(offset, actors.PIER_REACH)
                        self.assertTrue(actor.boat_faces or actor.y in (actors.PIER_DECK, actors.MARINA_DECK))
                    else:
                        self.assertEqual(actor.boat_id, row["boat"])
                        self.assertTrue(actor.boat_faces)
                        self.assertLess(offset, 3.0)

    def test_the_cache_keeps_at_most_14_actors_within_150_mib(self):
        world = World("briar")
        water = [npc_id for npc_id, row in ROSTER.items() if row["role"] == "water"][:20]
        anchors = [a for a in world.anchors.values() if a.kind == "water"]
        cache = actors.ActorCache(world)
        for count in range(1, len(water) + 1):
            npcs = tuple(NPC(npc_id, ROSTER[npc_id]["name"], "", anchors[i % len(anchors)], False)
                         for i, npc_id in enumerate(water[:count]))
            present = cache.sync(npcs, ROSTER)
            self.assertLessEqual(len(present), actors.MAX_ACTORS)
            self.assertLessEqual(len(cache.actors), actors.MAX_ACTORS)
        for actor in cache.actors.values():
            actor.mesh(LOD0)
            actor.mesh(LOD1)
        report = actors.memory_report(cache)
        self.assertEqual(report["resident_actors"], actors.MAX_ACTORS)
        self.assertLessEqual(report["total_bytes_bound"], actors.ACTOR_BUDGET)
        # The newest arrivals stay; the earliest leave first.
        self.assertEqual(list(cache.actors), water[-actors.MAX_ACTORS:])

    def test_cats_wave_and_turn_within_40_m_and_hold_still_for_reduced_motion(self):
        world, state = _lake("briar")
        actor = next(a for a in actors.ActorCache(world).sync(state.npcs, actors.roster())
                     if a.look["pose"] != "wave")
        near = actors.pose_state(actor, actor.x + 5.0, actor.z, 2.0, False)
        far = actors.pose_state(actor, actor.x + 45.0, actor.z, 2.0, False)
        self.assertEqual(near["blend"], 1.0)
        self.assertEqual(far["blend"], 0.0)
        self.assertEqual(far["head_yaw"], 0.0)
        self.assertNotEqual(near["head_yaw"], 0.0)
        self.assertLessEqual(abs(near["head_yaw"]), 1.1)
        behind = actors.pose_state(actor, actor.x - math.sin(actor.yaw) * 5, actor.z - math.cos(actor.yaw) * 5, 2.0,
                                   False)
        self.assertAlmostEqual(abs(behind["head_yaw"]), 1.1)
        mesh = actor.mesh(LOD0)
        moving = [actors.animate(mesh, actors.pose_state(actor, actor.x + 5, actor.z, t, False))[0] for t in (0.3, 1.9)]
        self.assertFalse(np.array_equal(*moving))
        still = [actors.animate(mesh, actors.pose_state(actor, actor.x + 5, actor.z, t, True))[0] for t in (0.3, 1.9)]
        np.testing.assert_array_equal(*still)

    def test_hailing_range_and_speed_are_unchanged(self):
        self.assertEqual(HAIL_RANGE_M, 20.0)
        self.assertAlmostEqual(HAIL_SPEED_MPS, 3 * 1852 / 3600)
        _world, state = _lake("briar")
        host = state.npcs[0]
        for distance, speed, hails in ((19.5, 0.0, True), (20.5, 0.0, False),
                                       (10.0, HAIL_SPEED_MPS * 0.99, True), (10.0, HAIL_SPEED_MPS, False)):
            state.x, state.z, state.speed = host.anchor.x + distance, host.anchor.z, speed
            with self.subTest(distance=distance, speed=speed):
                self.assertEqual(nearby_npc(state) is not None, hails)

    def test_the_software_renderer_draws_the_cats_and_their_boats(self):
        from .software import SoftwareRenderer
        for lake in ("briar", "cedar"):
            world, state = _lake(lake)
            renderer = SoftwareRenderer(world, 240, 135)
            for actor in renderer.actor_cache.sync(state.npcs, actors.roster()):
                state.x, state.z = actor.x + math.sin(actor.yaw) * 6, actor.z + math.cos(actor.yaw) * 6
                state.yaw = math.atan2(actor.x - state.x, actor.z - state.z)
                with_cats = renderer.render(state)
                npcs, state.npcs = state.npcs, ()
                without = renderer.render(state)
                state.npcs = npcs
                changed = np.abs(with_cats.astype(int) - without.astype(int)).sum(-1) > 30
                with self.subTest(lake=lake, npc=actor.npc_id):
                    self.assertGreater(int(changed.sum()), 40)
            self.assertLessEqual(renderer.actor_memory()["total_bytes_bound"], actors.ACTOR_BUDGET)

    def test_the_gl_renderer_draws_cats_without_new_gpu_objects(self):
        _gl_context(self).release()
        from .glrender import LakeRenderer
        world, state = _lake("cedar")
        renderer = LakeRenderer(world, 320, 180)
        try:
            actor = renderer.actor_cache.sync(state.npcs, actors.roster())[1]
            state.x, state.z = actor.x + math.sin(actor.yaw) * 7, actor.z + math.cos(actor.yaw) * 7
            state.yaw = math.atan2(actor.x - state.x, actor.z - state.z)
            npcs = state.npcs
            state.npcs = ()
            empty = renderer.render(state)
            objects = len(renderer._objects)
            state.npcs = npcs
            frames = [renderer.render(state) for state.anim in (1.0, 2.0)]
            self.assertEqual(len(renderer._objects), objects)
            changed = np.abs(frames[0].astype(int) - empty.astype(int)).sum(-1) > 30
            self.assertGreater(int(changed.sum()), 40)
            far = [d[2] for d in renderer._actor_draws if d[0].npc_id != actor.npc_id]
            self.assertTrue(all(lod is None or lod == LOD1 for lod in far))
            self.assertLessEqual(renderer.actor_memory()["total_bytes_bound"], actors.ACTOR_BUDGET)
        finally:
            renderer.close()


    def test_a_cat_moved_to_a_new_anchor_gets_a_fresh_gl_slot(self):
        _gl_context(self).release()
        from dataclasses import replace
        from .glrender import LakeRenderer
        world, state = _lake("briar")
        renderer = LakeRenderer(world, 160, 90)
        try:
            host, water = state.npcs[:2]
            renderer.render(state)
            before = next(s for s in renderer.actor_slots if s["npc_id"] == water.id)
            self.assertGreater(before["boat_vertices"], 0)
            # The Sunday cookout moves a water cat onto the landing, without its boat.
            state.npcs = (host, replace(water, anchor=replace(host.anchor, id="briar:cookout:" + water.id)),
                          *state.npcs[2:])
            renderer.render(state)
            actor = renderer.actor_cache.actors[water.id]
            slot = next(s for s in renderer.actor_slots if s["npc_id"] == water.id)
            self.assertIs(slot["actor"], actor)
            self.assertEqual(actor.boat_faces, [])
            self.assertEqual(slot["boat_vertices"], 0)
        finally:
            renderer.close()

class Portraits(unittest.TestCase):
    def test_portraits_are_cached_read_only_and_differ_by_cat(self):
        catart.clear_caches()
        first = catart.portrait("grandmother_whiskers")
        self.assertEqual(first.shape, (256, 256, 3))
        self.assertEqual(first.dtype, np.uint8)
        self.assertFalse(first.flags.writeable)
        self.assertIs(catart.portrait("grandmother_whiskers"), first)
        self.assertGreater(int(np.abs(first.astype(int) - catart.portrait("doc_barnaby").astype(int)).sum()), 10**6)
        self.assertIsNone(catart.portrait_at("not_a_cat", 128))
        self.assertEqual(catart.portrait_at("doc_barnaby", 128).shape, (128, 128, 3))

    def test_impostors_crop_to_the_cat_with_feet_on_the_bottom_row(self):
        sprite, width_m, height_m, base_m = catart.impostor("elder_moss")
        alpha = sprite[..., 3] > 0
        self.assertTrue(alpha[-1].any())
        self.assertTrue(alpha[0].any())
        self.assertGreater(height_m, 0.2)
        self.assertAlmostEqual(width_m / height_m, sprite.shape[1] / sprite.shape[0], places=6)
        self.assertLess(abs(base_m), 0.1)

    def test_the_dialogue_panel_shows_the_portrait_left_of_the_text(self):
        from .platform import Text
        from .ui import UI, UIState
        world, state = _lake("briar")
        text = Text()
        try:
            ui = UI(text, world)
            records = []
            draw_text = ui._text

            def record(frame, label, x, y, size, color, shadow=True, family="mono"):
                records.append((label, int(x)))
                return draw_text(frame, label, x, y, size, color, shadow, family)

            ui._text = record
            node = next(k for k, v in ui.narrative_content.dialogue.items() if v.get("choices"))
            frame = np.zeros((720, 1280, 3), np.uint8)
            screen = UIState(mode="dialogue", dialogue_content=ui.narrative_content,
                             conversation=SimpleNamespace(npc_id="grandmother_whiskers", node_id=node, selected=0))
            ui.draw(frame, state, screen)
            side = min(176, max(96, 720 // 4))
            portrait = catart.portrait_at("grandmother_whiskers", side)
            found = [(y, x) for y in range(720 - side) for x in range(0, 640, 4)
                     if np.array_equal(frame[y, x:x + 8], portrait[0, :8])
                     and np.array_equal(frame[y + side - 1, x:x + 8], portrait[-1, :8])]
            self.assertTrue(found)
            left = found[0][1] + side
            name = next(x for label, x in records if label == "Grandmother Whiskers")
            self.assertGreater(name, left)
        finally:
            text.close()


class Skipper(unittest.TestCase):
    def _state(self, boat_id, **extra):
        world = World("briar")
        state = State.new(world, seed=3)
        state.boat_id = boat_id
        for key, value in extra.items():
            setattr(state, key, value)
        return state

    def test_paws_take_the_tiller_oars_paddle_and_haul_line(self):
        cases = {("jon", ()): "tiller", ("rowboat", ()): "oars", ("rowboat", ("rowboat_trolling_motor",)): "tiller_oar",
                 ("log_raft", ()): "paddle", ("dory", ()): "oars", ("river_runner", ()): "tiller",
                 ("sail", ()): "tiller", ("pontoon", ()): None, ("mahogany_runabout", ()): None,
                 ("mahogany_runabout", ("hauling",)): "haul"}
        tanx = math.tan(math.radians(74) / 2)
        tany = tanx * 9 / 16
        for (boat_id, flags), kind in cases.items():
            state = self._state(boat_id, **{flag: True for flag in flags})
            with self.subTest(boat=boat_id, flags=flags):
                self.assertEqual(skipper.grip_kind(state), kind)
                pos, nrm, rgb, tris = skipper.paw_mesh(state)
                if kind is None:
                    self.assertEqual(len(tris), 0)
                    continue
                self.assertTrue(np.isfinite(pos).all())
                # Every mitt is in view at 16:9 and 74 degrees.
                mitts = pos[np.all(np.isclose(rgb, skipper.MITT), axis=1)]
                self.assertGreater(len(mitts), 0)
                visible = ((mitts[:, 2] > 0.3) & (np.abs(mitts[:, 0]) < mitts[:, 2] * tanx)
                           & (np.abs(mitts[:, 1]) < mitts[:, 2] * tany))
                self.assertGreater(float(visible.mean()), 0.6)

    def test_the_head_reflection_shows_only_idle_on_calm_water_past_the_bow(self):
        state = self._state("jon")
        calm = {"rain": 0.0, "mist": 0.0}
        self.assertTrue(skipper.shows_reflection(state, calm))
        self.assertFalse(skipper.shows_reflection(state, {"rain": 0.6, "mist": 0.0}))
        state.speed = 1.0
        self.assertFalse(skipper.shows_reflection(state, calm))
        state.speed, state.hauling = 0.0, True
        self.assertFalse(skipper.shows_reflection(state, calm))
        state.hauling = False
        pos, _n, _c, _t = skipper.head_silhouette(state)
        eye = state.boat.eye_height
        # Where each mirrored point meets the water, seen from the eye: all beyond the bow.
        ahead = (pos[:, 2] - state.z) * math.cos(state.yaw) + (pos[:, 0] - state.x) * math.sin(state.yaw)
        landing = ahead * eye / (eye + pos[:, 1])
        self.assertGreater(float(landing.min()), state.boat.bow * 2.5)

    def test_hauling_is_transient_and_never_saved(self):
        import tempfile
        state = self._state("jon", hauling=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            state.save(path)
            self.assertNotIn("hauling", path.read_text())
            self.assertFalse(State.load(path, World("briar")).hauling)


class ChartPins(unittest.TestCase):
    def test_pins_wear_each_cats_coat(self):
        from .platform import Text
        from .ui import UI
        world, state = _lake("briar")
        text = Text()
        try:
            ui = UI(text, world)
            frame = np.zeros((400, 400, 3), np.uint8)
            ui._plot_npcs(frame, state, 0, 0, 400, 400)
            for npc in state.npcs:
                u, v = world.map_pixel(npc.anchor.x, npc.anchor.z, 400, 400)
                coat = [int(c * 255 + 0.5) for c in ROSTER[npc.id]["appearance"]["colors"]["base"]]
                with self.subTest(npc=npc.id):
                    np.testing.assert_array_equal(frame[int(v), int(u)], coat)
        finally:
            text.close()


if __name__ == "__main__":
    unittest.main()
