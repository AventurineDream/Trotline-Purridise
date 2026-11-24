"""V1-29 cats: roster data, the rig and its LODs, shader agreement, actors in the world, portraits and the Skipper."""

from copy import deepcopy
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from . import actors, catart, catmesh, catmotion, skipper, skipperlook
from .botidentity import format_text
from .catmesh import FUR_PARTS, LOD0, LOD1, PATTERNS, POSES
from .content import _BOAT_PAINT_IDS, ContentError, load_content, load_content_v2, validate_content_v2
from .data import CONTENT_V2_RAW, PAINT
from .dialogue import HAIL_RANGE_M, HAIL_SPEED_MPS, nearby_npc
from .narrative import DAY_NPCS
from .npcs import NPC, active_npcs
from .portraitmotion import REST, portrait_motion
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


def _skipper_actor(ears: str = "pointed"):
    """Return a custom helm Actor with validated `ears`, using the creator's appearance builder."""
    from . import skipperview
    look = skipperlook.cycle(skipperlook.normalize({}), "pattern",
                             PATTERNS.index("tuxedo") - PATTERNS.index(skipperlook.DEFAULT["pattern"]))
    for key in ("head", "neck", "body"):
        look = skipperlook.cycle(look, key, 1)
    look["ears"] = ears
    appearance = skipperlook.appearance(look, "helm")
    return actors.Actor("skipper", "Skipper", 3.0, 0.0, -2.0, 0.9, None, {}, [], skipperview.SEED, appearance=appearance)


def _pose_cast():
    """One actor per authored pose and craft prop, plus Pip & Pebble, at the origin."""
    picks, seen = [], set()
    for npc_id, row in ROSTER.items():
        look = row["appearance"]
        key = "twin" if "twin" in look else (look["pose"], look["prop"])
        if key not in seen:
            seen.add(key)
            picks.append(actors.Actor(npc_id, npc_id, 0.0, 0.0, 0.0, 0.4, None, {}, [], actors._seed(npc_id)))
    return picks


def _busy_moments(actor):
    """Clock times (s) when this cat is mid-blink and when its work loop swings hardest."""
    seed, look = actors._int_seed(actor), actor.look
    times = [t / 40.0 for t in range(1600)]
    blink = next(t for t in times if catmotion.blink(t, seed) > 0.5)
    work = max(times, key=lambda t: abs(catmotion.work(t, seed, look["pose"], look["prop"])[0])
               + abs(catmotion.work(t, seed, look["pose"], look["prop"])[1]))
    return blink, work


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
        # The windswept folds are creator options; the authored roster keeps its four shapes.
        self.assertEqual({look["ears"] for look in looks} | {"folded_left", "folded_right"},
                         set(skipperlook.EARS))
        self.assertEqual({look["tail"] for look in looks}, {"long", "bob", "none", "plume"})

    def test_boat_paint_ids_mirror_the_shop_paints(self):
        for slot, ids in _BOAT_PAINT_IDS.items():
            self.assertEqual(ids, {row[0] for row in PAINT[slot]}, slot)

    def test_validator_accepts_every_creator_ear_shape(self):
        """Every saved creator ear value is also valid in an NPC appearance."""
        for ears in skipperlook.EARS:
            with self.subTest(ears=ears):
                raw = deepcopy(CONTENT_V2_RAW)
                raw["npcs.json"]["npcs"][0]["appearance"]["ears"] = ears
                content = validate_content_v2(raw)
                self.assertEqual(content.roster["grandmother_whiskers"]["appearance"]["ears"], ears)

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
        # V1-30's schedule fields.
        case("npcs[0](grandmother_whiskers).role", "unknown value/reference ['host']",
             lambda rows: rows[0].update(role=["host"]))
        case("npcs[0](grandmother_whiskers).slot", "unknown value/reference 'day'",
             lambda rows: rows[0].update(slot="day"))
        case("npcs[5](pounce).anchor", "expected null", lambda rows: rows[5].update(anchor="briar:open"))
        case("npcs[7](elder_moss).anchor", "on the cat's own lake", lambda rows: rows[7].update(anchor="cedar:rocks"))
        case("npcs[7](elder_moss).anchor", "already the anchor of 'grandmother_whiskers'",
             lambda rows: rows[7].update(anchor="briar:landing"))
        case("npcs[7](elder_moss).quests[0]", "already given by 'grandmother_whiskers'",
             lambda rows: rows[7]["quests"].__setitem__(0, "q01_tea_leaves_deep_holes"))
        case("npcs[7](elder_moss).quests[1]", "the cat's own quest id",
             lambda rows: rows[7]["quests"].__setitem__(1, "wc_willow_b"))
        case("npcs[5](pounce).quests", "expected 0 quest id(s)", lambda rows: rows[5].update(quests=["wc_pounce_a"]))
        case("npcs", "Master Cinder keeps the Briar night slot", lambda rows: rows[9].update(slot="day"))
        case("npcs", "expected the V3 cat 'willow' on briar by day", lambda rows: rows[10].update(slot="night"))
        case("npcs", "briar needs 1–3 night encounters, found 4",
             lambda rows: [row.update(slot="night") for row in rows[10:13]])
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
                    self.assertIn(catmesh.GESTURES[base] or base, mesh.positions)
                    for pose, positions in mesh.positions.items():
                        self.assertTrue(np.isfinite(positions).all())
                        self.assertFalse(positions.flags.writeable)
                        self.assertEqual(len(mesh.pivots[pose]), len(mesh.cats))
                    self.assertGreaterEqual(int(mesh.triangles.min()), 0)
                    self.assertLess(int(mesh.triangles.max()), len(mesh.part))
                    self.assertEqual(len(mesh.cats), 2 if twin else 1)
            self.assertLessEqual(counts[LOD0], 5000 if twin else 2800, npc_id)
            self.assertLessEqual(counts[LOD1], 1600 if twin else 1000, npc_id)
            self.assertLess(counts[LOD1] * 2.5, counts[LOD0], npc_id)

    def test_folded_ears_sweep_backward_and_to_the_cats_left_or_right_in_every_pose(self):
        """Both ear surfaces fold behind their roots in head space, at unchanged LOD budgets."""
        look = skipperlook.appearance(skipperlook.normalize({}))
        scale = catmesh.HEAD_SCALE * look["size"]
        for lod in (LOD0, LOD1):
            for pose, joints in catmesh.POSE_JOINTS.items():
                _head, pitch, yaw = joints["head"]
                head_rot = catmesh._rot(pitch=pitch, yaw=yaw)
                reference = catmesh.build(look, pose, lod)
                deltas = {}
                for ears in ("folded", "folded_left", "folded_right"):
                    with self.subTest(ears=ears, pose=pose, lod=lod):
                        pos, nrm, part, along, tris, _tags, _pivots = catmesh.build(dict(look, ears=ears), pose, lod)
                        self.assertTrue(np.isfinite(pos).all())
                        self.assertTrue(np.isfinite(nrm).all())
                        self.assertEqual(pos.shape, reference[0].shape)
                        np.testing.assert_array_equal(tris, reference[4])
                        self.assertLessEqual(len(tris), 2800 if lod == LOD0 else 1000)
                        for surface in (catmesh.EAR, catmesh.INNER_EAR):
                            roots = pos[(part == surface) & (along == 0)].reshape(2, -1, 3).mean(axis=1)
                            tips = pos[(part == surface) & (along == 1)].reshape(2, -1, 3)
                            delta = (tips - roots[:, None, :]) @ head_rot / scale
                            # +z faces the muzzle; every tip vertex must be behind its own root.
                            self.assertTrue(np.all(delta[:, :, 2] < -0.02))
                            deltas[ears, surface] = delta.mean(axis=1)
                for surface in (catmesh.EAR, catmesh.INNER_EAR):
                    neutral = deltas["folded", surface]
                    left, right = deltas["folded_left", surface], deltas["folded_right", surface]
                    # Positive head-local x is the cat's left, for BOTH ears.
                    self.assertTrue(np.all(left[:, 0] - neutral[:, 0] > 0.02))
                    self.assertTrue(np.all(right[:, 0] - neutral[:, 0] < -0.02))
                    np.testing.assert_allclose(left[:, 1:], neutral[:, 1:], atol=1e-6)
                    np.testing.assert_allclose(right[:, 1:], neutral[:, 1:], atol=1e-6)

    def _assert_tail_root_inside_torso(self, pos, part, along, triangles, size):
        """Check the ring and start cap against the actual posed torso facets."""
        root = pos[(part == catmesh.TAIL) & (along == 0)]
        self.assertGreaterEqual(len(root), 5)
        faces = pos[triangles[np.all(part[triangles] == catmesh.TORSO, axis=1)]]
        normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        lengths = np.linalg.norm(normals, axis=1)
        valid = lengths > 1e-10 * size * size
        faces, normals = faces[valid], normals[valid] / lengths[valid, None]
        centre = pos[part == catmesh.TORSO].mean(axis=0)
        outward = np.sum(normals * (faces.mean(axis=1) - centre), axis=1)
        normals *= np.where(outward < 0, -1.0, 1.0)[:, None]
        distances = np.sum((root[:, None, :] - faces[None, :, 0]) * normals[None, :, :], axis=2)
        self.assertLessEqual(float(distances.max()), 2e-6 * size,
                             "the tail's first ring and start cap must stay hidden inside the torso")

    def test_tail_roots_are_embedded_for_every_pose_lod_kind_and_body_extreme(self):
        """Both LODs must hide every tail's root, including lying and greeting poses."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        look.update(attire=[], prop="none")
        bodies = ((0.5, 0.7, 0.5, "hairless"), (1.0, 1.0, 1.0, "short"),
                  (1.4, 1.4, 1.3, "long"), (1.0, 0.7, 1.3, "rex"))
        for size, build, legs, coat in bodies:
            look.update(size=size, build=build, legs=legs, coat=coat)
            for pose in catmesh.POSE_JOINTS:
                for tail in ("long", "bob", "none", "plume"):
                    look["tail"] = tail
                    for lod in (LOD0, LOD1):
                        with self.subTest(pose=pose, tail=tail, lod=lod, body=(size, build, legs, coat)):
                            pos, _nrm, part, along, triangles, _tags, _pivots = catmesh.build(look, pose, lod)
                            self.assertEqual(int(np.count_nonzero((part == catmesh.TAIL) & (along == 0))),
                                             catmesh._counts(lod)["tail_sides"] + 1)
                            self._assert_tail_root_inside_torso(pos, part, along, triangles, size)

    def test_tail_roots_stay_embedded_during_idle_turns_and_pose_blends(self):
        """Breathing, tail sway, whole-body turns and greetings cannot expose a root."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        look.update(size=0.5, build=0.7, legs=0.5, coat="hairless", attire=[], prop="none")
        frames = ((0.0, 0.0, -1.0), (2.9, 0.5, 1.0), (7.3, 1.0, -1.0), (11.2, 0.5, 1.0))
        for pose in POSES:
            for tail in ("long", "bob", "none", "plume"):
                appearance = dict(look, pose=pose, tail=tail)
                actor = actors.Actor("tail-test", "Tail", 3.0, 0.0, -2.0, 0.9, None, {}, [],
                                     seed=0.3, appearance=appearance)
                for lod in (LOD0, LOD1):
                    mesh = actor.mesh(lod)
                    for t, blend, side in frames:
                        with self.subTest(pose=pose, tail=tail, lod=lod, t=t, blend=blend, side=side):
                            params = actors.pose_state(actor, actor.x + side * 6, actor.z + 3, t, False,
                                                       gesture=blend, steer=side)
                            pos = actor.local_to_world(actors.animate(mesh, params)[0])
                            self._assert_tail_root_inside_torso(pos, mesh.part, mesh.along, mesh.triangles,
                                                                appearance["size"])

    def test_short_tail_rings_stay_ordered_through_greeting_lift(self):
        """Greeting lift must not push adjacent bob/Manx ring surfaces through each other."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        look.update(size=1.0, legs=1.0, attire=[], prop="none")
        frames = ((0.0, 0.0), (2.9, 0.5), (7.3, 1.0), (11.2, 1.0))
        for build, coat in ((0.7, "hairless"), (1.0, "short"), (1.4, "long"), (0.7, "rex")):
            for pose in POSES:
                for tail in ("none", "bob"):
                    appearance = dict(look, build=build, coat=coat, pose=pose, tail=tail)
                    actor = actors.Actor("tail-fold", "Tail", 0.0, 0.0, 0.0, 0.9, None, {}, [],
                                         seed=0.3, appearance=appearance)
                    for lod in (LOD0, LOD1):
                        mesh = actor.mesh(lod)
                        counts = catmesh._counts(lod)
                        ring_vertices = counts["tail"] * counts["tail_sides"]
                        for t, blend in frames:
                            params = actors.pose_state(actor, -6.0, 3.0, t, False, gesture=blend)
                            for sway in (True, False):
                                motion = params if sway else dict(params, tail=0.0, tail_curl=0.0)
                                with self.subTest(build=build, coat=coat, pose=pose, tail=tail, lod=lod,
                                                  t=t, blend=blend, sway=sway):
                                    pos = actors.animate(mesh, motion)[0][mesh.part == catmesh.TAIL]
                                    # Exclude the buried ring and both cap vertices. Centre order alone
                                    # misses folds where an edge crosses the neighboring ring's plane.
                                    rings = pos[:ring_vertices].reshape(-1, counts["tail_sides"], 3)[1:]
                                    centres = rings.mean(axis=1)
                                    tangents = np.cross(rings[:, 1] - rings[:, 0], rings[:, 2] - rings[:, 0])
                                    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)
                                    forward = np.sum((rings[1:] - centres[:-1, None, :])
                                                     * tangents[:-1, None, :], axis=2)
                                    backward = np.sum((centres[1:, None, :] - rings[:-1])
                                                      * tangents[1:, None, :], axis=2)
                                    self.assertGreater(float(forward.min()), 1e-6,
                                                       "a tail ring crosses back through its predecessor")
                                    self.assertGreater(float(backward.min()), 1e-6,
                                                       "a tail ring crosses forward through its successor")

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

    def test_goggle_frames_take_their_finish_while_lenses_stay_cyan(self):
        """A non-brass frame colour reaches ATTIRE verts; the GLOW lens tint ignores it."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        look.update(attire=[{"kind": "goggles", "color": [0.78, 0.80, 0.83]}], prop="none")
        mesh = catmesh.look_mesh(look, LOD0)
        rgb, _glow = catmesh.paint(mesh)
        frame = (mesh.tags == 0) & (mesh.part == catmesh.ATTIRE)
        self.assertTrue(frame.any())
        np.testing.assert_allclose(rgb[frame], np.broadcast_to([0.78, 0.80, 0.83], rgb[frame].shape),
                                   atol=1e-6)
        lens = (mesh.tags == 0) & (mesh.part == catmesh.GLOW)
        self.assertTrue(lens.any())
        np.testing.assert_allclose(rgb[lens], np.broadcast_to((0.55, 0.85, 0.95), rgb[lens].shape),
                                   atol=1e-6)

    def test_coat_kinds_move_real_geometry(self):
        """Rex curls and the hairless slim build must displace vertices, not just labels."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        # Long adds the neck ruff, so only same-topology coats compare vertex-for-vertex.
        look.update(attire=[], prop="none", pose="sit_fish", size=1.0)
        reference = catmesh.build(dict(look, coat="short"), "sit_fish", LOD0)[0]
        for coat in ("rex", "hairless"):
            with self.subTest(coat=coat):
                pos = catmesh.build(dict(look, coat=coat), "sit_fish", LOD0)[0]
                self.assertEqual(pos.shape, reference.shape)
                self.assertGreater(float(np.abs(pos - reference).max()), 0.004)

    def test_hairless_cats_wear_no_fur_pattern_on_cpu_or_gpu(self):
        """Hairless fur parts take only the base colour; cat.frag gates identically."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        look.update(attire=[], prop="none", coat="hairless", pattern="tabby",
                    colors={"base": [0.6, 0.3, 0.2], "secondary": [0.1, 0.1, 0.1],
                            "accent": [0.9, 0.9, 0.9]})
        mesh = catmesh.look_mesh(look, LOD0)
        rgb, _glow = catmesh.paint(mesh)
        fur = np.isin(mesh.part, catmesh.FUR_PARTS)
        base = np.asarray(look["colors"]["base"], np.float32)
        np.testing.assert_allclose(rgb[fur], np.broadcast_to(base, rgb[fur].shape), atol=1e-6)
        # Control: the same cat short-coated shows tabby markings on fur.
        look["coat"] = "short"
        mesh = catmesh.look_mesh(look, LOD0)
        rgb, _glow = catmesh.paint(mesh)
        fur = np.isin(mesh.part, catmesh.FUR_PARTS)
        self.assertGreater(float(np.abs(rgb[fur] - base).max()), 0.05)
        # The shader mirror: COAT_KINDS order is the uniform's contract.
        source = (SHADERS / "cat.frag").read_text(encoding="utf-8")
        self.assertIn("uniform int coat_kind", source)
        self.assertIn(f"coat_kind == {catmesh.COAT_KINDS.index('hairless')}", source)

    def test_each_jacket_kind_has_its_own_styling_geometry(self):
        """The six body kinds must not share one silhouette: details differ per kind."""
        look = deepcopy(next(iter(ROSTER.values()))["appearance"])
        look.pop("twin", None)
        look.update(attire=[], prop="none", pose="sit_fish", size=1.0)
        signatures = {}
        for kind in ("oilskin", "parka", "sweater", "vest", "life_jacket", "shawl"):
            with self.subTest(kind=kind):
                item = {"kind": kind, "color": [0.5, 0.5, 0.5]}
                pos, _nrm, part, _along, _tris, tags, _pivots = catmesh.build(
                    dict(look, attire=[item]), "sit_fish", LOD0)
                worn = tags == 0
                self.assertTrue(worn.any())
                verts = pos[worn]
                # Signature: vertex count plus the extent of the worn geometry.
                lo, hi = verts.min(axis=0), verts.max(axis=0)
                signatures[kind] = (len(verts), tuple(np.round(hi - lo, 2)))
        # No two kinds may produce the same worn-geometry signature.
        self.assertEqual(len(set(signatures.values())), len(signatures))
        # The shawl's drape is the only kind reaching well behind the torso:
        # its tail hangs down the back past every other jacket's rear extent.
        item = {"kind": "shawl", "color": [0.5, 0.5, 0.5]}
        pos, _nrm, part, _along, _tris, tags, _pivots = catmesh.build(
            dict(look, attire=[item]), "sit_fish", LOD0)
        worn = (tags == 0) & (part == catmesh.ATTIRE)
        tail = pos[worn]
        self.assertLess(float(tail[:, 2].min()), -0.15)


class ShaderAgreement(unittest.TestCase):
    def test_cat_frag_coat_patterns_match_the_numpy_reference(self):
        ctx = _gl_context(self)
        import moderngl
        try:
            source = (SHADERS / "cat.frag").read_text(encoding="utf-8")
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
            common = (SHADERS / "common.glsl").read_text(encoding="utf-8")
            program = ctx.program(vertex_shader="#version 330\n" + common + "\n" + (SHADERS / "cat.vert").read_text(encoding="utf-8"),
                                  varyings=["pos", "normal"])
            # Headless EGL has no default framebuffer, and a draw needs one even with no fragments.
            fb = ctx.simple_framebuffer((1, 1))
            fb.use()
            world, state = _lake("briar")
            # The lake's own cats, and one of every pose (and Pip & Pebble) caught mid-blink and mid-work.
            cast = [(a, ((6.0, 3.7, {}), (35.0, 11.2, {}), (60.0, 0.4, {})))
                    for a in actors.ActorCache(world).sync(state.npcs, actors.roster())]
            cast += [(a, ((60.0, _busy_moments(a)[0], {}), (60.0, _busy_moments(a)[1], {}), (34.0, 7.3, {})))
                     for a in _pose_cast()]
            # The Skipper's own look mesh at the helm: the gesture override (wave back) and steering lean.
            cast += [(_skipper_actor(ears), ((60.0, 2.9, {"steer": 0.7}),
                                            (12.0, 5.1, {"gesture": 0.6, "steer": -0.4}),
                                            (8.0, 0.0, {"gesture": 1.0})))
                     for ears in ("pointed", "folded", "folded_left", "folded_right")]
            for actor, frames in cast:
                for distance, t, extra in frames:
                    mesh = actor.mesh(LOD0)
                    params = actors.pose_state(actor, actor.x + distance, actor.z + 1.0, t, False, **extra)
                    vertices = catmesh.vertex_block(mesh)
                    vbo = ctx.buffer(vertices.tobytes())
                    out = ctx.buffer(reserve=len(vertices) * 24)
                    # Only `pos` and `normal` are captured, so the compiler drops the paint attributes.
                    vao = ctx.vertex_array(program, [(vbo, catmesh.VERTEX_FORMAT, *catmesh.VERTEX_ATTRIBUTES)],
                                           skip_errors=True)
                    for key, value in {**actors.shader_uniforms(actor, mesh, params), "mirror": 1.0}.items():
                        if key in program:
                            program[key].value = value
                    vao.transform(out, moderngl.POINTS, vertices=len(vertices))
                    gl = np.frombuffer(out.read(), np.float32).reshape(-1, 6)
                    posed, normals = actors.animate(mesh, params)
                    cpu = actor.local_to_world(posed)
                    # Normals carry no translation; both sides are compared as unit directions.
                    cpu_n = actor.local_to_world(normals) - actor.local_to_world(np.zeros((1, 3), np.float32))
                    unit = lambda v: v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
                    with self.subTest(npc=actor.npc_id, distance=distance, t=t, **extra):
                        np.testing.assert_allclose(gl[:, :3], cpu, atol=2e-4)
                        np.testing.assert_allclose(unit(gl[:, 3:]), unit(cpu_n), atol=2e-3)
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
        # Far off, the cat looks about on its own: where the player is makes no difference.
        far_left = actors.pose_state(actor, actor.x - 45.0, actor.z, 2.0, False)
        self.assertEqual(far["head_yaw"], far_left["head_yaw"])
        self.assertNotEqual(near["head_yaw"], 0.0)
        self.assertLessEqual(abs(near["head_yaw"]), 1.1)
        beside = actors.pose_state(actor, actor.x + math.cos(actor.yaw) * 5, actor.z - math.sin(actor.yaw) * 5, 2.0,
                                   False)
        self.assertAlmostEqual(abs(beside["head_yaw"]), 1.1)
        # Circling the cat, its head follows without a snap where the player passes behind it.
        circle = [actors.pose_state(actor, actor.x + math.sin(a / 90.0) * 5, actor.z + math.cos(a / 90.0) * 5, 2.0,
                                    True)["head_yaw"] for a in range(round(math.tau * 90) + 1)]
        self.assertLess(max(abs(b - a) for a, b in zip(circle, circle[1:])), 0.1)
        mesh = actor.mesh(LOD0)
        moving = [actors.animate(mesh, actors.pose_state(actor, actor.x + 5, actor.z, t, False))[0] for t in (0.3, 1.9)]
        self.assertFalse(np.array_equal(*moving))
        still = [actors.animate(mesh, actors.pose_state(actor, actor.x + 5, actor.z, t, True))[0] for t in (0.3, 1.9)]
        np.testing.assert_array_equal(*still)

    def test_idle_life_is_a_pure_seeded_function_of_the_clock(self):
        times = [t / 40.0 for t in range(2400)]
        for actor in _pose_cast():
            with self.subTest(npc=actor.npc_id):
                self.assertEqual(actors.pose_state(actor, None, None, 47.3, False),
                                 actors.pose_state(actor, None, None, 47.3, False))
                frames = [actors.pose_state(actor, None, None, t, False) for t in times]
                # Within a minute every cat blinks, twitches each ear and breathes.
                for key in ("blink", "ear_l", "ear_r"):
                    self.assertGreater(max(f[key] for f in frames), 0.5, key)
                self.assertGreater(np.ptp([f["breath"] for f in frames]), 0.01)
                self.assertGreater(np.ptp([f["tail"] for f in frames]), 0.0)
                if actor.look["pose"] != "nap_curl":
                    # Awake cats look about; sitters cast, crafters work and helmsmen steer.
                    self.assertGreater(np.ptp([f["head_yaw"] for f in frames]), 0.2)
                if actor.look["pose"] in ("sit_fish", "craft", "helm", "wave"):
                    self.assertGreater(np.ptp([f["arm"] + f["forearm"] for f in frames]), 0.05)
        # Two cats in the same pose are out of step.
        sitters = [actors.Actor(n, n, 0.0, 0.0, 0.0, 0.0, None, {}, [], actors._seed(n)) for n, row in ROSTER.items()
                   if row["appearance"]["pose"] == "sit_fish"][:2]
        blinks = [[actors.pose_state(a, None, None, t, False)["blink"] > 0.5 for t in times] for a in sitters]
        self.assertNotEqual(*blinks)

    def test_reduced_motion_zeroes_every_clock_driven_term(self):
        for actor in _pose_cast():
            for t in (0.0, 13.1, 52.9):
                with self.subTest(npc=actor.npc_id, t=t):
                    p = actors.pose_state(actor, actor.x + 80.0, actor.z, t, True)
                    for key in ("blink", "ear_l", "ear_r", "breath", "rise", "tail", "tail_curl", "forearm", "arm",
                                "body_roll", "body_pitch", "head_yaw", "head_pitch", "head_roll"):
                        self.assertEqual(p[key], 0.0, key)

    def test_every_gesture_blend_keeps_the_body_whole_mid_way(self):
        # A linear blend between a lying and a sitting torso squashes it into a blob mid-way:
        # each pose blends to a gesture built on its own body instead.
        for actor in _pose_cast():
            mesh = actor.mesh(LOD1)
            if catmesh.slots(mesh)[1] is None:
                continue
            torso = mesh.part == catmesh.TORSO

            def spread(w):
                pos = mesh.blend(catart._pose_weights(mesh, w))[0][torso]
                return float(np.linalg.norm(pos - pos.mean(0), axis=1).mean())

            with self.subTest(npc=actor.npc_id):
                self.assertGreater(spread(0.5), 0.95 * min(spread(0.0), spread(1.0)))

    def test_pebble_turns_her_head_about_her_own_neck(self):
        actor = actors.Actor("pip_pebble", "Pip & Pebble", 0.0, 0.0, 0.0, 0.0, None, {}, [], 0.3)
        mesh = actor.mesh(LOD1)
        _look, lo, hi = mesh.cats[1]
        head = np.zeros(len(mesh.part), bool)
        head[lo:hi] = mesh.part[lo:hi] == catmesh.HEAD
        body = np.zeros(len(mesh.part), bool)
        body[lo:hi] = mesh.part[lo:hi] == catmesh.TORSO
        for side in (1.0, -1.0):
            # Held in the idle pose (gesture=0) with the player close beside: only the head turns.
            turned = actors.animate(mesh, actors.pose_state(actor, side * 20.0, 20.0, 0.0, True, gesture=0.0))[0]
            rest = actors.animate(mesh, actors.pose_state(actor, None, None, 0.0, True))[0]
            self.assertGreater(np.abs(turned[head] - rest[head]).max(), 0.02)
            offset = [np.linalg.norm((p[head].mean(0) - p[body].mean(0))[[0, 2]]) for p in (rest, turned)]
            with self.subTest(side=side):
                self.assertLess(abs(offset[1] - offset[0]), 0.03)

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
        self.assertIsNone(catart.portrait_rig("not_a_cat", 128))
        self.assertEqual(catart.portrait_rig("doc_barnaby", 128).frame(REST).shape, (128, 128, 3))

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
            line = format_text(ui.narrative_content.dialogue[node]["text"], state)
            pose = portrait_motion("grandmother_whiskers", line, screen.dialogue_s, screen.dialogue_line_s)
            portrait = catart.portrait_rig("grandmother_whiskers", side).frame(pose)
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
                pos, nrm, rgb, tris, part = skipper.paw_mesh(state, parts=True)
                if kind is None:
                    self.assertEqual(len(tris), 0)
                    continue
                self.assertTrue(np.isfinite(pos).all())
                # Every mitt is in view at 16:9 and 74 degrees.
                mitts = pos[part == skipper.PART_MITT]
                self.assertGreater(len(mitts), 0)
                visible = ((mitts[:, 2] > 0.3) & (np.abs(mitts[:, 0]) < mitts[:, 2] * tanx)
                           & (np.abs(mitts[:, 1]) < mitts[:, 2] * tany))
                self.assertGreater(float(visible.mean()), 0.6)

    def test_the_paws_and_reflection_wear_the_saved_coat(self):
        from . import skipperlook
        state = self._state("jon")
        _p, _n, rgb, _t, part = skipper.paw_mesh(state, parts=True)
        arm = rgb[part == skipper.PART_FOREARM]
        # The default tabby's forearm is ringed: its base coat and its darker stripe both show.
        self.assertGreater(float(np.ptp(arm.mean(axis=1))), 0.12)
        look = skipperlook.cycle(skipperlook.saved(state), "pattern", PATTERNS.index("tuxedo")
                                 - PATTERNS.index("tabby"))
        look = skipperlook.cycle(look, "base", [n for n, _c in skipperlook.COAT_SWATCHES].index("Ink"))
        state.v2["skipper"] = look
        _p, _n, rgb, _t, part = skipper.paw_mesh(state, parts=True)
        accent, base = (np.asarray(look["colors"][k], np.float32) for k in ("accent", "base"))
        # A tuxedo wears white mitts at the end of a black arm, as the rig paints the same cat.
        self.assertLess(float(np.abs(rgb[part == skipper.PART_MITT] - accent).max()), 0.05)
        self.assertLess(float(np.abs(np.median(rgb[part == skipper.PART_FOREARM], axis=0) - base).max()), 0.05)
        _p, _n, shade, _t = skipper.head_silhouette(state)
        np.testing.assert_allclose(shade[0], base * skipper.SHADOW, rtol=1e-6)

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

    def test_folded_ear_reflections_keep_the_cat_relative_sweep(self):
        """Reflections support all fold values and shift both tips toward the chosen head side."""
        state = self._state("jon", yaw=0.7)
        state.v2["skipper"]["ears"] = "folded"
        neutral, _n, _rgb, triangles = skipper.head_silhouette(state)
        rot = skipper._rot(0.0, state.yaw + math.pi)
        for ears, sign in (("folded_left", 1), ("folded_right", -1)):
            with self.subTest(ears=ears):
                state.v2["skipper"]["ears"] = ears
                pos, _n, _rgb, tris = skipper.head_silhouette(state)
                np.testing.assert_array_equal(tris, triangles)
                delta = (pos[-12:] - neutral[-12:]) @ rot
                tips = delta[[2, 5, 8, 11]]
                self.assertTrue(np.all(tips[:, 0] * sign > 0))
                np.testing.assert_allclose(delta[:, 1:], 0, atol=1e-5)
                np.testing.assert_array_equal(pos[:-12], neutral[:-12])

    def test_the_figure_turns_smoothly_as_two_cats_trade_places(self):
        from . import skipperview
        figure = skipperview.SkipperFigure()
        figure.actor = _skipper_actor()
        cats = [SimpleNamespace(anchor=SimpleNamespace(x=x, z=8.0, lake_id="briar")) for x in (-6.0, 6.0)]
        state = SimpleNamespace(npcs=cats, lake_id="briar", speed=0.0, steer=0.0, anim=0.0)
        figure.actor.yaw = 0.0
        yaws = []
        # Sail across the line between the two cats, 1 cm a step: the nearest cat switches midway.
        for i in range(1601):
            figure.actor.x, figure.actor.z = -8.0 + i * 0.01, 0.0
            yaws.append(figure.params(state, True)["head_yaw"])
        steps = np.abs(np.diff(yaws))
        self.assertLess(float(steps.max()), 0.02)
        # It still looks at the cats: left of centre at the start, right at the end.
        self.assertLess(yaws[0] * yaws[-1], 0.0)

    def test_the_figure_fades_head_attention_when_two_cats_cancel(self):
        from . import skipperview
        figure = skipperview.SkipperFigure()
        figure.actor = _skipper_actor()
        cats = [SimpleNamespace(anchor=SimpleNamespace(x=x, z=0.0, lake_id="briar")) for x in (-6.0, 6.0)]
        state = SimpleNamespace(npcs=cats, lake_id="briar", speed=0.0, steer=0.0, anim=0.0)
        figure.actor.yaw = 0.0
        yaws, blends = [], []
        for i in range(601):
            figure.actor.x, figure.actor.z = -3.0 + i * 0.01, 0.0
            params = figure.params(state, True)
            yaws.append(params["head_yaw"])
            blends.append(params["blend"])
        self.assertLess(float(np.abs(np.diff(yaws)).max()), 0.02)
        self.assertLess(float(np.abs(np.diff(blends)).max()), 0.02)
        self.assertAlmostEqual(yaws[300], 0.0, places=6)
        self.assertAlmostEqual(blends[300], 1.0, places=6)

    def test_generated_hull_figure_feet_stand_just_above_each_actual_deck(self):
        from . import boatfamilies, boat
        from . import skipperview
        for boat_id, model in boat.BOATS.items():
            if model.handcrafted:
                continue
            spec = boatfamilies.SPECS[boat_id]
            state = SimpleNamespace(boat_id=boat_id, boat=model, v2={})
            cam = SimpleNamespace(
                eye_to_world=lambda p, eye=model.eye_height: np.asarray(p) + np.asarray((0.0, eye, 0.0)),
                forward=np.asarray((0.0, 0.0, 1.0), np.float32))
            figure = skipperview.SkipperFigure()
            actor = figure.place(state, cam)
            faces = boatfamilies.npc_faces(boat_id, 0.0, 0.0, 0.0)
            deck = np.asarray(spec.deck_color, np.float32)
            candidates = []
            for face in faces:
                if face.normal[1] <= 0.99 or not np.allclose(face.color, deck, atol=1e-5):
                    continue
                extent = np.ptp(face.pts[:, (0, 2)], axis=0)
                candidates.append((float(extent[0] * extent[1]), float(face.pts[:, 1].mean())))
            with self.subTest(boat=boat_id):
                self.assertTrue(candidates, "generated hull has a deck face in its authored deck colour")
                deck_y = max(candidates)[1]
                self.assertAlmostEqual(actor.y, deck_y + 0.02, places=5)

    def test_hauling_is_transient_and_never_saved(self):
        import tempfile
        state = self._state("jon", hauling=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            state.save(path)
            self.assertNotIn("hauling", path.read_text(encoding="utf-8"))
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
