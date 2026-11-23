"""V1-27 Starlight Nebula Lagoon: void bed, habitats, currents, sky, scenery and starlight travel."""

from copy import deepcopy
import math
import unittest

import numpy as np

from . import ambient, calendar, nebula, starlight
from .audio import Audio
from .boat import BOATS
from .bottools import flow_at
from .content import ContentError, validate_content_v2
from .data import CONTENT_V2_RAW, LAKE_SPECIES_IDS, ZONE_ORDER
from .lakegen import LakeFields
from .marina import footprint_samples
from .sim import REEDS_CRAWL_SPEED, State
from .specieschecks import _reachable_samples, lake_witnesses
from .weather import lighting_at
from .world import World

NEBULA_INDEX = 4  # position of the Lagoon in lakes.json


def angle_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, (a[0]*b[0]+a[1]*b[1])/math.hypot(*a)/math.hypot(*b)))))


class NebulaFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("nebula")

    def test_void_bed_fields_are_finite_deterministic_and_bounded(self):
        world = self.world
        self.assertTrue(world.nebula)
        self.assertFalse(world.placeholder or world.caldera)
        fields = LakeFields(deepcopy(world.environment))
        for actual, expected in zip(fields.bake(), (world.shore_grid, world.depth_grid, world.coast)):
            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(actual.dtype, np.float32)
            self.assertTrue(np.isfinite(actual).all())
        self.assertEqual(world.height.shape, (567, 567))
        self.assertLess(sum(g.nbytes for g in (world.height, world.shore_grid, world.depth_grid)), 4_500_000)
        # The void well falls to sixty metres; the open bed is deep but shallows at every bank.
        self.assertGreater(float(world.depth(130, -30)), 55)
        self.assertGreater(float(world.depth(-80, -420)), 20)
        outline = world.coast[:360]
        bank = world.depth(outline[:, 0]-outline[:, 2]*4, outline[:, 1]-outline[:, 3]*4)
        self.assertLess(float(np.median(bank)), 6)
        self.assertEqual([(p.kind, p.x, p.z, p.h) for p in World("nebula").props],
                         [(p.kind, p.x, p.z, p.h) for p in world.props])

    def test_every_habitat_and_both_current_lanes_are_reachable_and_every_fish_catchable(self):
        world = self.world
        self.assertEqual({row[0] for row in world.zones},
                         {"inlet", "flats", "lilies", "cypress", "rocks", "deep", "reeds", "current"})
        x, z = _reachable_samples(world)
        ids = world.zone_ids(x, z)
        for zone in ("inlet", "flats", "lilies", "cypress", "rocks", "deep", "reeds", "current", "open"):
            self.assertTrue(np.any(ids == ZONE_ORDER.index(zone)), zone)
        for lane in world.environment["lanes"]:
            near = np.zeros(x.shape, bool)
            for px, pz in lane["points"]:
                self.assertEqual(world.zone_at(px, pz), "current")
                near |= np.hypot(x-px, z-pz) < lane["width"]
            self.assertTrue(near.any())
        for zone, cx, cz, _radius in world.environment["zones"]:
            self.assertEqual(world.zone_at(cx, cz), zone)
            self.assertTrue(all(world.hull_clear(cx, cz, .7, boat) for boat in BOATS))
        fish = lake_witnesses(world)
        self.assertEqual({row["species"] for row in fish}, set(LAKE_SPECIES_IDS["nebula"]))
        self.assertGreaterEqual(min(row["ratio"] for row in fish), 1.0)

    def test_lily_drifts_are_solid_islands_ringed_by_open_water(self):
        world = self.world
        for cx, cz, rx, rz in world.environment["drifts"]:
            self.assertGreater(float(world.shore_sd(cx, cz)), 0)
            self.assertEqual(world.zone_at(cx, cz), "shore")
            self.assertFalse(any(world.hull_clear(cx, cz, 0, boat) for boat in BOATS))
            for angle in np.linspace(0, math.tau, 16, endpoint=False):
                px, pz = cx+math.cos(angle)*(rx+12), cz+math.sin(angle)*(rz+12)
                self.assertTrue(world.hull_clear(px, pz, angle+math.pi/2, "jon"), (cx, cz, angle))
        lilies = [p for p in world.props if p.kind == "starlily"]
        self.assertGreaterEqual(len(lilies), 2*len(world.environment["drifts"]))
        self.assertTrue(all(float(world.shore_sd(p.x, p.z)) >= 0 for p in lilies))

    def test_station_landing_and_crystal_scenery_collide_like_the_other_lakes(self):
        world = self.world
        state = State.new(world)
        self.assertEqual(state.slip_status(world), "docked")
        for boat in BOATS:
            parked = State.new(world)
            parked.boat_id = boat
            parked.owned_boats.append(boat)
            parked._park(world)
            self.assertTrue(world.hull_clear(parked.x, parked.z, parked.yaw, boat), boat)
        for a in np.linspace(-120, 4, 60):
            px, pz = world.slip.world(float(a), 0)
            self.assertTrue(all(world.hull_clear(px, pz, state.yaw, boat) for boat in BOATS))
        for footprint in world.marina.shore_buildings:
            for a, s in footprint_samples(footprint):
                self.assertGreaterEqual(float(world.shore_sd(*world.slip.world(a, s))), 1)
        station = nebula.station_faces(world)
        self.assertTrue(all(np.isfinite(face.pts).all() for face in station))
        self.assertTrue(any(face.emissive == 1.0 for face in station))
        lanterns = [face for face in world.faces if face.emissive == 1.0]
        self.assertGreater(len(lanterns), len([face for face in station if face.emissive == 1.0]))
        kinds = {p.kind for p in world.props}
        self.assertEqual(kinds, set(nebula.GLOW_KINDS))
        self.assertTrue(all(2.0 <= p.shade <= 3.0 for p in world.props))
        for p in world.props:
            if p.kind in ("kelp", "meteor"):
                self.assertFalse(world.hull_clear(p.x, p.z, 0, "jon"), p)
                self.assertLess(float(world.shore_sd(p.x, p.z)), -3)
        reeds = [p for p in world.props if p.kind == "lightreed"]
        self.assertGreater(len(reeds), 40)
        self.assertTrue(all(world.zone_at(p.x, p.z) == "reeds" for p in reeds))
        self.assertEqual(len(world.solid_props), sum(p.kind in ("kelp", "meteor") for p in world.props))
        # Light-reeds slow a hull like Briar's Reed Passage, without blocking it.
        _, rx, rz, _radius = next(row for row in world.environment["zones"] if row[0] == "reeds")
        state.x, state.z, state.yaw = rx, rz+30, math.pi
        state.anchored, state.speed = False, 3.0
        state.throttle = state.throttle_setting = 1.0
        for _ in range(40):
            state.drive(.25, 1, 0, world)
        self.assertEqual(world.zone_at(state.x, state.z), "reeds")
        self.assertLessEqual(abs(state.speed), REEDS_CRAWL_SPEED+1e-6)


class NebulaCurrents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("nebula")

    def test_lanes_are_continuous_streamlines_of_the_drift_flow_field(self):
        for lane in self.world.environment["lanes"]:
            points = lane["points"]
            for a, b in zip(points, points[1:]):
                self.assertLessEqual(math.dist(a, b), lane["width"])
                mid = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                self.assertLess(angle_between((b[0]-a[0], b[1]-a[1]), flow_at(*mid)), 12)

    def test_dashes_point_and_move_downstream_with_the_flow(self):
        x, z = self.world.environment["lanes"][0]["points"][8]
        first = nebula.dash_segments(x-30, z-30, x+30, z+30, 3.0)
        later = nebula.dash_segments(x-30, z-30, x+30, z+30, 4.0)
        self.assertGreater(len(first), 40)
        self.assertEqual(len(first), len(later))
        moved = 0
        for (x0, z0, dx, dz), (x1, z1, _dx, _dz) in zip(first, later):
            self.assertLess(angle_between((dx, dz), flow_at(x0, z0)), 10)
            step = (x1-x0)*dx+(z1-z0)*dz
            if step > 0:
                moved += 1
                self.assertAlmostEqual(step, nebula.DASH_RATE*nebula.DASH_CELL, places=4)
        self.assertGreater(moved, len(first)*.8)
        # The scalar field lights the dash heads and nothing far from them.
        hx, hz = first[:, 0], first[:, 1]
        self.assertGreater(float(nebula.dashes(hx, hz, 3.0).mean()), .2)

    def test_software_current_streaks_follow_the_flow_field(self):
        from .nebulashots import flow_alignment
        from .software import SoftwareRenderer
        renderer = SoftwareRenderer(self.world, 320, 180)
        state = State.new(self.world, seed=4)
        state.game_minutes, state.anim = 1200, 14
        try:
            rows = flow_alignment(renderer, self.world, state)
        finally:
            renderer.close()
        self.assertTrue(all(row["angle_error_deg"] < 15 and row["coherence"] > .3 for row in rows), rows)

    def test_native_currents_bands_and_aurora_reuse_graphics_resources(self):
        try:
            import moderngl
            ctx = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as error:
            self.skipTest("Standalone EGL unavailable: "+str(error))
        from .glrender import LakeRenderer
        from .nebulashots import finite_band_check, flow_alignment
        renderer = None
        try:
            renderer = LakeRenderer(self.world, 320, 180, context=ctx)
            self.assertTrue(renderer.celestial)
            state = State.new(self.world, seed=4)
            count = len(renderer._objects)
            frames = []
            for minute in (30, 360, 750, 900, 1200):
                state.game_minutes = minute
                frames.append(renderer.render(state).copy())
                self.assertEqual(len(renderer._objects), count)
            for a, b in zip(frames, frames[1:]):
                self.assertFalse(np.array_equal(a, b))
            state.game_minutes, state.anim = 1200, 14
            rows = flow_alignment(renderer, self.world, state)
            self.assertTrue(all(row["angle_error_deg"] < 15 and row["coherence"] > .3 for row in rows), rows)
            self.assertEqual(finite_band_check(renderer, self.world), 10)
            self.assertEqual(len(renderer._objects), count)
        finally:
            if renderer is not None:
                renderer.close()
            ctx.release()


class NebulaSky(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("nebula")

    def test_four_named_bands_ease_between_palettes_and_starlight_never_fades(self):
        self.assertEqual([nebula.band_label(h) for h in (6, 12, 18, 23, 2)],
                         ["Rising", "Bright", "Fading", "Deep", "Deep"])
        bands = self.world.environment["bands"]
        for hour, name in ((6.5, "rising"), (12, "bright"), (18.5, "fading"), (23, "deep"), (2, "deep")):
            palette = nebula.sky_palette(hour, bands)
            np.testing.assert_allclose(palette["zenith"], bands[name]["zenith"], atol=1e-6)
            self.assertAlmostEqual(palette["stars"], bands[name]["stars"])
        state = State.new(self.world, seed=4)
        for minute in range(0, 1440, 20):
            light = lighting_at(minute, state)
            self.assertGreater(light["starlight"], .1)
            self.assertTrue(all(np.isfinite(light[key]).all() for key in ("zenith", "horizon")))
        briar = State.new(World("briar"), seed=4)
        self.assertNotIn("starlight", lighting_at(360, briar))

    def test_aurora_nights_and_the_meteor_shower_are_scheduled_and_read_only(self):
        state = State.new(self.world, seed=4)
        before, rng = deepcopy(state.to_json()), state.rng.s
        self.assertEqual(calendar.weather_at(state, 900), "aurora")
        self.assertEqual(lighting_at(900, state)["aurora"], 1)
        self.assertEqual(lighting_at(360, state)["aurora"], 0)
        self.assertTrue(0 < lighting_at(835, state)["aurora"] < 1)
        self.assertEqual(lighting_at(2*1440+1170, state)["meteors"], 1)
        self.assertEqual(lighting_at(1170, state)["meteors"], 0)
        self.assertEqual(lighting_at(2*1440+360, state)["meteors"], 0)
        self.assertEqual(state.to_json(), before)
        self.assertEqual(state.rng.s, rng)

    def test_hud_names_the_band_and_chart_keys_each_habitat_once(self):
        from .platform import Text
        from .ui import UI, UIState
        text = Text()
        ui = UI(text, self.world)
        state = State.new(self.world, seed=4)
        state.game_minutes = 30
        drawn = []
        original = ui._text
        ui._text = lambda frame, label, *args, **kwargs: (drawn.append(label), original(frame, label, *args, **kwargs))
        try:
            ui.draw(np.zeros((720, 1280, 3), np.uint8), state, UIState(mode="play", has_save=True))
            self.assertTrue(any(label.startswith("RISING  /  ") for label in drawn))
            ui._text = original
            chart = np.zeros((720, 1280, 3), np.uint8)
            places = ui._plot_habitats(chart, 50, 50, 360, 360)
            self.assertEqual([number for number, *_ in places],list(range(1,9)))
            self.assertEqual(len({name for _number,name,*_ in places}),8)
            self.assertGreater(np.count_nonzero(chart),0)
        finally:
            text.close()

    def test_software_bands_render_distinctly_without_rng_or_save_changes(self):
        from .software import SoftwareRenderer
        state = State.new(self.world, seed=4)
        state.x, state.z, state.yaw = -300, -160, .9
        before, rng = deepcopy(state.to_json()), state.rng.s
        renderer = SoftwareRenderer(self.world, 160, 90)
        try:
            frames = []
            for minute in (30, 360, 750, 900, 1200):
                state.game_minutes = minute
                frame = renderer.render(state)
                self.assertGreater(float(frame.std()), 5)
                frames.append(frame.astype(np.float32).mean(axis=(0, 1)))
            for i, a in enumerate(frames):
                for b in frames[i+1:]:
                    self.assertGreater(float(np.abs(a-b).max()), 2)
            # Wednesday's Deep night adds the Meteor Shower to the same sky.
            state.anim, state.look = 16.5, .12
            state.game_minutes = 1170
            quiet = renderer.render(state).astype(np.int32)
            state.game_minutes = 2*1440+1170
            shower = renderer.render(state).astype(np.int32)
            self.assertGreater(int((np.abs(shower-quiet).sum(axis=2) > 90).sum()), 3)
            state.anim, state.look = 0, 0
            state.game_minutes = 0
            self.assertEqual(state.to_json(), before)
            self.assertEqual(state.rng.s, rng)
        finally:
            renderer.close()


class NebulaLife(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("nebula")

    def test_star_motes_replace_wildlife_are_bounded_and_hold_under_reduced_motion(self):
        state = State.new(self.world, seed=4)
        state.x, state.z = -300, -160
        for minute in (360, 1200):
            state.game_minutes = minute
            faces = ambient.faces(state, self.world)
            self.assertTrue(faces)
            self.assertLessEqual(len(faces), ambient.MAX_FACES)
            self.assertTrue(all(face.emissive == 1.0 for face in faces))
            self.assertTrue(all(float(self.world.shore_sd(*face.pts[0, [0, 2]])) < 0 for face in faces))
        state.anim = 3
        moving = ambient.faces(state, self.world)
        state.anim = 9
        self.assertFalse(np.array_equal(moving[0].pts, ambient.faces(state, self.world)[0].pts))
        state.v2["settings"]["reduced_motion"] = True
        held = ambient.faces(state, self.world)
        state.anim = 40
        for a, b in zip(held, ambient.faces(state, self.world)):
            np.testing.assert_array_equal(a.pts, b.pts)

    def test_lagoon_twinkles_and_hums_without_birds_frogs_or_crickets(self):
        audio = Audio.__new__(Audio)
        audio._hour, audio._rain, audio._lake_id = 12, 0, "nebula"
        audio.time, audio._bird_at, audio._frog_at = 20, 0, 0
        cues = []
        audio._cue = cues.append
        audio._span = lambda base, spread: base
        audio._schedule()
        audio._hour, audio.time = 23, 50
        audio._schedule()
        # Twinkles and the choir (V1-38); no birds or frogs, and no whale song before the finale.
        self.assertEqual(cues, ["twinkle", "choir", "twinkle", "choir"])
        mixes = {}
        for lake in ("nebula", "flathead", "briar"):
            sound = Audio()
            try:
                sound._lake_id, sound._hour, sound._rain = lake, 23, 0
                sound._sailing = sound._motorized = sound._rowing = False
                mixes[lake] = sound._mix(1024, 0, 0)
            finally:
                sound.close()
        self.assertFalse(np.array_equal(mixes["nebula"], mixes["flathead"]))
        self.assertGreater(len(Audio.__new__(Audio)._tone("twinkle")), 0)


class StarlightTravel(unittest.TestCase):
    def test_transition_is_pure_and_ends_on_both_lakes(self):
        rng = np.random.default_rng(5)
        source = rng.integers(0, 255, (90, 160, 3), dtype=np.uint8)
        arrival = rng.integers(0, 255, (90, 160, 3), dtype=np.uint8)
        self.assertTrue(starlight.touches_starlight("crater", "nebula"))
        self.assertTrue(starlight.touches_starlight("nebula", "briar"))
        self.assertFalse(starlight.touches_starlight("briar", "cedar"))
        for reduced in (False, True):
            np.testing.assert_array_equal(starlight.frame(source, None, 0.0, reduced_motion=reduced), source)
            np.testing.assert_array_equal(starlight.frame(source, arrival, 1.0, reduced_motion=reduced), arrival)
            middle = starlight.frame(source, None, .5, reduced_motion=reduced)
            self.assertEqual(middle.dtype, np.uint8)
            self.assertEqual(middle.shape, source.shape)
            # The middle of the journey is starlight: violet, never either lake.
            self.assertGreater(float(middle[..., 2].mean()), float(middle[..., 1].mean()))
            np.testing.assert_array_equal(middle, starlight.frame(source, None, .5, reduced_motion=reduced))
        # Reduced Motion holds the stars still; otherwise they stream outward.
        np.testing.assert_array_equal(starlight._starfield(90, 160, .1, True), starlight._starfield(90, 160, .9, True))
        self.assertFalse(np.array_equal(starlight._starfield(90, 160, .1, False),
                                        starlight._starfield(90, 160, .9, False)))

    def test_run_loop_plays_the_sequence_paused_and_still_quits(self):
        from .game import _play_starlight

        class Platform:
            def __init__(self, quit_at=None):
                self.now, self.frames, self.quit_at = 0, [], quit_at

            def ticks(self):
                self.now += 100
                return self.now

            def poll(self, dt):
                return type("Input", (), {"quit": self.quit_at is not None and len(self.frames) >= self.quit_at})()

            def present(self, frame):
                self.frames.append(frame)

            def delay(self, ms):
                pass

        class Session:
            quit = False

        source = np.full((36, 64, 3), 40, np.uint8)
        arrival = np.full((36, 64, 3), 200, np.uint8)
        platform, session = Platform(), Session()
        _play_starlight(platform, session, source, None, 0.0, starlight.TIP_END, False)
        _play_starlight(platform, session, source, arrival, starlight.TIP_END, 1.0, False)
        self.assertGreater(len(platform.frames), 10)
        np.testing.assert_array_equal(platform.frames[-1], arrival)
        self.assertFalse(session.quit)
        platform, session = Platform(quit_at=2), Session()
        _play_starlight(platform, session, source, None, 0.0, starlight.TIP_END, False)
        self.assertTrue(session.quit)
        self.assertEqual(len(platform.frames), 2)

    def test_transition_uses_a_safety_floor_when_vsync_does_not_block(self):
        from unittest.mock import patch
        from .game import _play_starlight

        class Platform:
            vsync = True

            def __init__(self, focused):
                self.now = 0
                self.focused = focused

            def ticks(self):
                self.now += 10
                return self.now

            def poll(self, _dt):
                return type("Input", (), {"quit": False, "focused": self.focused})()

            def present(self, _frame):
                pass

        class Session:
            quit = False
            focused = True

        source = np.zeros((8, 8, 3), np.uint8)
        # Freeze the frame clock so every frame reports zero render time: the
        # requested sleep is then exactly the policy period, independent of
        # how fast or how loaded the host is.
        for focused, period, minimum in ((True, 1 / 240, 0.002), (False, 1 / 30, 0.03)):
            platform = Platform(focused)
            with patch("fishing.game.time.perf_counter", return_value=0.0), \
                    patch("fishing.game.time.sleep") as sleep:
                _play_starlight(platform, Session(), source, None, 0.0, 0.05, False)
            slept = [call.args[0] for call in sleep.call_args_list]
            self.assertTrue(slept)
            for seconds in slept:
                self.assertAlmostEqual(seconds, period)
            self.assertTrue(all(seconds >= minimum for seconds in slept))

    def test_lake_change_tips_into_starlight_only_on_lagoon_routes(self):
        import random
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from . import game
        from .game import Session, _enter_lake
        from .imageops import resize_rgb
        from .lakes import LoadingQuips, loading_quips
        from .platform import Text
        from .render import Renderer
        from .ui import UI

        class Platform:
            context = None

            def __init__(self):
                self.now, self.frames = 0, []

            def ticks(self):
                self.now += 120
                return self.now

            def poll(self, dt):
                return type("Input", (), {"quit": False})()

            def present(self, frame):
                self.frames.append(frame.copy())

            def delay(self, ms):
                pass

            def make_current(self):
                pass

        text = Text()
        quips = LoadingQuips(random.Random(138))
        try:
            # Both Lagoon directions and an ordinary trip: each names the destination and a quip.
            for source, destination, starlit in (("crater", "nebula", True), ("nebula", "briar", True),
                                                 ("flathead", "crater", False)):
                with tempfile.TemporaryDirectory(prefix="starlight-") as temp:
                    world = World(source)
                    state = State.new(world, seed=4)
                    state.v2["story"]["chapter"] = 5
                    session = Session(world, Path(temp)/"save.json", state, False)
                    session.ui.mode = "play"
                    renderer, ui = Renderer(world, 320, 180, software=True), UI(text, world)
                    shown = resize_rgb(renderer.render(state), 320, 180)
                    before = state.game_minutes
                    self.assertIsNone(session.change_lake(destination))
                    platform = Platform()
                    loading = np.empty((180, 320, 3), np.uint8)
                    with patch("fishing.game._travel_card_text", wraps=game._travel_card_text) as card:
                        renderer, ui = _enter_lake(
                            platform, session, renderer, ui, text, loading, True, True, shown,
                            quips=quips)
                    try:
                        self.assertIs(renderer.world, session.world)
                        self.assertEqual(renderer.world.id, destination)
                        self.assertEqual(state.game_minutes, before)
                        self.assertIn(quips.last, loading_quips(destination))
                        self.assertTrue(card.call_args_list)
                        for call in card.call_args_list:
                            self.assertEqual(call.args[2:], (session.world.name, quips.last))
                        if starlit:
                            self.assertGreater(len(platform.frames), 10)
                            # The tip starts from the last frame shown on the source water,
                            # before the card joins the stars; the card clears as the lake rises.
                            first = platform.frames[0].astype(np.float32)
                            self.assertLess(float(np.abs(first-shown).mean()), 25)
                            self.assertLess(card.call_count, len(platform.frames) - 1)
                        else:
                            self.assertEqual(len(platform.frames), 1)
                            self.assertEqual(card.call_count, 1)
                            self.assertTrue(np.any(platform.frames[0] != (17, 31, 32)))
                    finally:
                        renderer.close()
        finally:
            text.close()


class NebulaSaveRecovery(unittest.TestCase):
    """Saves from the flat placeholder Lagoon survive the new drifts and reefs."""

    def test_old_lines_and_boats_on_new_drifts_move_to_clear_water_once(self):
        import json
        import tempfile
        from pathlib import Path
        from .sim import Hook, SetLine
        world = World("nebula")
        cx, cz, rx, rz = world.environment["drifts"][0]
        with tempfile.TemporaryDirectory(prefix="nebula-old-save-") as temp:
            path = Path(temp)/"save.json"
            state = State.new(world, seed=55)
            buried = SetLine("std", "worm", cx-8, cz, cx+8, cz, "lilies", [Hook(True)],
                             line_id="20000000-0000-4000-8000-000000000001")
            wet = SetLine("std", "worm", -250, -20, -230, -20, "current", [Hook(True)],
                          line_id="20000000-0000-4000-8000-000000000002")
            state.lines = [buried, wet]
            state.x, state.z, state.yaw = cx, cz, 0.0
            state.anchored = True
            state.save(path, update_stamp=False)
            loaded = State.load(path, world)
            moved, kept = loaded.lines
            self.assertTrue(world.hull_clear(loaded.x, loaded.z, loaded.yaw, loaded.boat_id))
            self.assertNotEqual((moved.x0, moved.z0), (cx-8, cz))
            self.assertAlmostEqual(math.hypot(moved.x1-moved.x0, moved.z1-moved.z0), 16)
            samples = np.linspace(0, 1, 17)
            self.assertTrue(all(float(world.shore_sd(moved.x0+(moved.x1-moved.x0)*t, moved.z0+(moved.z1-moved.z0)*t)) < 0
                                for t in samples))
            self.assertEqual((kept.x0, kept.z0, kept.x1, kept.z1), (-250, -20, -230, -20))
            self.assertEqual(moved.line_id, buried.line_id)
            loaded.save(path, update_stamp=False)
            once = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(State.load(path, world).to_json(), once)


class NebulaValidator(unittest.TestCase):
    def test_validator_collects_bad_lanes_drifts_bands_and_misplaced_keys(self):
        bad = deepcopy(CONTENT_V2_RAW)
        environment = bad["lakes.json"]["lakes"][NEBULA_INDEX]["environment"]
        environment["lanes"][0]["points"][3] = [9999, 0]
        environment["lanes"][1]["width"] = 5
        environment["drifts"][0] = [0, 0, 2, 90]
        environment["bands"]["deep"]["stars"] = 2
        del environment["bands"]["rising"]
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(bad)
        for key in ("lanes[0].points[3]", "lanes[1].width", "drifts[0]", "bands"):
            self.assertIn(".environment."+key, str(caught.exception))
        for key in ("lanes", "drifts", "bands", "water_mid"):
            bad = deepcopy(CONTENT_V2_RAW)
            del bad["lakes.json"]["lakes"][NEBULA_INDEX]["environment"][key]
            with self.assertRaises(ContentError):
                validate_content_v2(bad)
        bad = deepcopy(CONTENT_V2_RAW)
        bad["lakes.json"]["lakes"][3]["environment"]["drifts"] = [[0, 0, 10, 10]]
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(bad)
        self.assertIn("belong to a nebula environment", str(caught.exception))
        self.assertEqual(CONTENT_V2_RAW["lakes.json"]["lakes"][NEBULA_INDEX]["id"], "nebula")


if __name__ == "__main__":
    unittest.main()
