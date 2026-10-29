"""Calendar acceptance: 1,000 seeded weeks, real transactions and paused UI."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import math
import unittest
from unittest.mock import patch

import numpy as np

from . import calendar, comfort, kitchen
from .bookview import BOOK_TABS, book_layout, week_rects
from .content import ContentError, load_content, validate_content_v2
from .data import CONTENT_V2_RAW, LEGENDARY_WINDOWS, PANTRY_CAPACITY, hour_of_day
from .game import Keys, Session
from .npcs import active_npcs, schedule_key
from .platform import Text
from .sim import Catch, State, species_rates
from .ui import UI, UIState
from .weather import lighting_at, weather_visuals, wind_at
from .world import World


class ForecastChecks(unittest.TestCase):
    def test_1000_seeded_weeks_cover_all_twelve_windows_within_three_days(self):
        # Eligibility just after a weather slot and at a fractional week seam.
        # Assert actual continuous weather+clock overlap, not just a returned date.
        for seed in range(1000):
            week = seed % 13
            for sid, window in LEGENDARY_WINDOWS.items():
                for eligible in (week * calendar.WEEK_MINUTES + 239.25,
                                 (week + 1) * calendar.WEEK_MINUTES - .5):
                    start, end = calendar.next_legendary_window(seed, sid, eligible)
                    self.assertGreaterEqual(start, eligible)
                    self.assertLessEqual(end, eligible + 3 * 1440)
                    self.assertGreaterEqual(end - start, 120)
                    points = [start, end - .001]
                    points += list(np.arange((int(start // 60) + 1) * 60, end, 60))
                    self.assertTrue(all(calendar.window_favorable(seed, window, float(t)) for t in points), (seed, sid, start))

    def test_seed_and_lake_change_forecasts_without_using_global_randomness(self):
        a = calendar.weekly_plan(44, 'briar', 5)
        self.assertEqual(len(a), 168)
        self.assertEqual(a, calendar.weekly_plan(44, 'briar', 5))
        self.assertNotEqual(a, calendar.weekly_plan(45, 'briar', 5))
        self.assertNotEqual(a, calendar.weekly_plan(44, 'cedar', 5))
        with self.assertRaises(ValueError):
            calendar.weekly_plan(1, 'missing', 0)

    def test_day_origin_week_and_cookout_boundaries(self):
        self.assertEqual(calendar.day_name(0), 'Monday')
        self.assertEqual(calendar.day_name(1439), 'Monday')
        self.assertEqual(calendar.day_name(1440), 'Tuesday')
        self.assertEqual(calendar.day_name(10080), 'Monday')
        for minute, active in ((9299, False), (9300, True), (9479.99, True), (9480, False), (10080, False)):
            self.assertEqual(calendar.cookout_active(minute), active)

    def test_briar_and_cedar_modifiers_only_on_their_day_band_species_and_zone(self):
        rows = [
            ('briar', 1440, 'bluegill', 'flats', 1.3),
            ('briar', 1440 + 120, 'bluegill', 'flats', 1),
            ('briar', 0, 'bluegill', 'flats', 1),
            ('briar', 1440, 'channel', 'flats', 1),
            ('briar', 4*1440+840, 'channel', 'deep', 1.25),
            ('briar', 4*1440+660, 'channel', 'deep', 1),
            ('cedar', 3*1440+840, 'blue', 'deep', 1.3),
            ('cedar', 3*1440+840, 'flathead', 'deep', 1),
            ('cedar', 5*1440+360, 'largemouth', 'open', 1.25),
            ('cedar', 5*1440+360, 'largemouth', 'rocks', 1.25),
            ('cedar', 5*1440+360, 'largemouth', 'lilies', 1),
            ('cedar', 4*1440+360, 'largemouth', 'open', 1)]
        for lake, minute, sid, zone, expected in rows:
            self.assertEqual(calendar.rate_multiplier(lake, minute, sid, zone), expected)
            base = species_rates(zone, 'worm', hour_of_day(minute), 'clear', 3, lake)
            actual = species_rates(zone, 'worm', hour_of_day(minute), 'clear', 3, lake, game_minutes=minute)
            self.assertAlmostEqual(actual[sid], base[sid] * expected)

    def test_calendar_content_collects_bad_references_and_numbers(self):
        raw = deepcopy(CONTENT_V2_RAW)
        raw['calendar.json']['lake_days'][0]['weekday'] = 9
        raw['calendar.json']['lake_days'][1]['multiplier'] = float('nan')
        raw['calendar.json']['legendary_windows'][0]['weathers'] = ['missing']
        raw['calendar.json']['legendary_windows'][1]['minimum_minutes'] = 119
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(raw)
        for field in ('weekday', 'multiplier', 'weathers', 'minimum_minutes'):
            self.assertIn(field, str(caught.exception))


class CalendarPlayChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()
        cls.content = load_content()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='trotline-calendar-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'save.json'
        self.state = State.new(self.world, seed=44016)
        self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = 'play'

    def sunday(self):
        self.state.game_minutes = 9300
        self.state.well = [Catch('bluegill', .5, 1., 0, 'flats', 'worm', 17)]
        self.session._refresh_npcs()

    def test_reload_lake_switch_and_fishing_rng_do_not_reroll_forecast(self):
        state = self.state
        before = [calendar.weather_at(state, t) for t in range(0, 22000, 37)]
        seed = calendar.forecast_seed(state)
        self.assertEqual(seed, 44016)
        for _ in range(20):
            state.rng.u01()
        state.v2['calendar']['future_calendar'] = {'kept': True}
        state.v2['calendar']['weather_windows']['future_lake:100'] = {'kept': True}
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(calendar.forecast_seed(loaded), seed)
        self.assertEqual(before, [calendar.weather_at(loaded, t) for t in range(0, 22000, 37)])
        cedar = SimpleNamespace(id='cedar')  # No second terrain is needed for the plan.
        loaded.bind(cedar)
        cedar_plan = calendar.weather_at(loaded, 960)
        loaded.bind(self.world)
        self.assertEqual(before, [calendar.weather_at(loaded, t) for t in range(0, 22000, 37)])
        loaded.bind(cedar)
        self.assertEqual(cedar_plan, calendar.weather_at(loaded, 960))
        self.assertEqual(loaded.v2['calendar']['future_calendar'], {'kept': True})
        self.assertIn('future_lake:100', loaded.v2['calendar']['weather_windows'])
        other = State.new(self.world, seed=44017)
        self.assertNotEqual(state.v2['calendar']['weather_windows'], other.v2['calendar']['weather_windows'])

    def test_saved_plans_roll_forward_offline_with_bounded_storage_and_no_social_replay(self):
        state = self.state
        state.stamp = 1000
        before = deepcopy(state.v2['calendar'])
        state.catch_up(now=1000 + 6*3600)
        weeks = {row['week'] for key, row in state.v2['calendar']['weather_windows'].items()}
        self.assertEqual(weeks, {2, 3})
        self.assertEqual(len(state.v2['calendar']['weather_windows']), 10)
        for key in ('cookout_gifts', 'cookout_chats', 'invitation_day', 'lake_day_notes'):
            self.assertEqual(before.get(key), state.v2['calendar'].get(key))

    def test_weather_lighting_wind_are_read_only_and_continuous_across_week_seam(self):
        state = self.state
        before, rng = deepcopy(state.v2), state.rng.s
        for minute in (59.999, 60.001, 10079.999, 10080.001):
            self.assertTrue(np.isfinite(lighting_at(minute, state)['sun']).all())
            self.assertTrue(all(np.isfinite(value) for value in weather_visuals(minute, state).values()))
            self.assertTrue(all(np.isfinite(value) for value in wind_at(minute, state)))
        for boundary in (60, 1440, 10080):
            a, b = weather_visuals(boundary-.001, state), weather_visuals(boundary+.001, state)
            self.assertLess(max(abs(a[k]-b[k]) for k in a), .001)
        self.assertEqual(state.v2, before)
        self.assertEqual(state.rng.s, rng)

    def test_simulation_uses_planned_weather_and_lake_day_rates(self):
        from .sim import Hook, SetLine
        state = self.state
        state.game_minutes = 1440
        state.lines = [SetLine('std', 'worm', 10, 205, 22, 205, 'flats', [Hook(True)])]
        with patch('fishing.sim.species_rates', wraps=species_rates) as rates:
            state._one_span(1/60)
        self.assertEqual(rates.call_args.args[3], calendar.weather_at(state))
        self.assertEqual(rates.call_args.kwargs['game_minutes'], 1440)

    def test_bot_fireflies_follow_forecast_when_legacy_weather_disagrees(self):
        from .data import weather_at as legacy_weather
        from .life import extra_faces
        state = self.state
        # Both are night: planned rain under a legacy clear sky, then planned
        # fair weather under legacy rain. The water ring remains in either case.
        for minute, planned, legacy, count in ((4080, 'drizzle', 'clear', 6),
                                               (5160, 'fair', 'drizzle', 11)):
            with self.subTest(minute=minute):
                state.game_minutes = minute
                self.assertEqual(calendar.weather_at(state), planned)
                self.assertEqual(legacy_weather(minute), legacy)
                before = state.to_json()
                self.assertEqual(len(extra_faces(state)), count)
                self.assertEqual(state.to_json(), before)

    def test_all_current_lake_friends_gather_and_restore_normal_schedule(self):
        # Sunday 16:59: the host and three day cats. 17:00–20:00: Briar's whole cast on
        # the landing piers. 20:00: the host and Master Cinder.
        keys = set()
        for minute, count in ((9299, 4), (9300, 9), (9479, 9), (9480, 2)):
            self.state.game_minutes = minute
            actors = active_npcs(self.state, self.world, self.content)
            self.assertEqual(len(actors), count)
            self.assertEqual(len({a.anchor.position for a in actors}), count)
            self.assertTrue(all(a.anchor.lake_id == 'briar' for a in actors))
            if calendar.cookout_active(minute):
                slip = self.world.slip
                for actor in actors:
                    self.assertEqual(actor.anchor.kind, 'dock')
                    self.assertLess(math.hypot(actor.anchor.x - slip.ox, actor.anchor.z - slip.oz), 20.0)
            keys.add(schedule_key(self.state, self.world, self.content))
        self.assertEqual(len(keys), 3)
        # Content-only Cedar roster, without loading another lake's terrain.
        self.assertEqual(len(calendar.cookout_friends(self.content, 'cedar')), 6)

    def test_cookout_transaction_is_explicit_atomic_and_once_after_reload(self):
        self.sunday()
        state = self.state
        gift = calendar.cookout_gift(state)
        before = state.to_json()
        kitchen.rows(state, self.world)
        self.assertEqual(before, state.to_json())
        self.assertIsNone(calendar.share_fish(state, self.world))
        self.assertFalse(state.well)
        self.assertEqual(state.v2['pantry'][gift], 1)
        state.save(self.path, update_stamp=False)
        state = State.load(self.path, self.world)
        state.well = [Catch('bluegill', .5, 1, 0, 'flats', 'worm', 17)]
        before = state.to_json()
        self.assertIsNotNone(calendar.share_fish(state, self.world))
        self.assertEqual(before, state.to_json())
        state.game_minutes += 7*1440
        self.assertIsNone(calendar.share_fish(state, self.world))
        self.assertEqual(state.v2['pantry'][calendar.cookout_gift(state)], 1 + int(gift == calendar.cookout_gift(state)))

    def test_cookout_protects_special_fish_allows_non_food_and_checks_capacity(self):
        self.sunday()
        state = self.state
        ordinary = state.well[0]
        state.well = [replace(ordinary, shiny=True), replace(ordinary, treasured=True),
                      replace(ordinary, legendary=True)]
        before = state.to_json()
        self.assertIsNotNone(calendar.share_fish(state, self.world, 0))
        self.assertEqual(before, state.to_json())
        state.well.append(replace(ordinary, species='gar'))
        self.assertEqual(kitchen.eligible_fish(state, 'any', food_only=False), [3])
        gift = calendar.cookout_gift(state)
        state.v2['pantry'][gift] = PANTRY_CAPACITY
        before = state.to_json()
        self.assertIsNotNone(calendar.share_fish(state, self.world, 3))
        self.assertEqual(before, state.to_json())
        state.v2['pantry'][gift] -= 1
        self.assertIsNone(calendar.share_fish(state, self.world, 3))
        self.assertEqual(len(state.well), 3)

    def test_cookout_requires_landing_and_event_and_each_friend_has_one_chat(self):
        self.sunday()
        state = self.state
        for friend in calendar.cookout_friends(self.content, 'briar'):
            self.assertTrue(calendar.chat(state, self.world, friend['id'], self.content))
            self.assertIn(calendar.CALENDAR_DATA['cookout_lines'][friend['id']], state.toasts[-1][0])
            self.assertFalse(calendar.chat(state, self.world, friend['id'], self.content))
        with patch.object(state, 'slip_status', return_value='away'):
            self.assertIsNotNone(calendar.share_fish(state, self.world))
        state.game_minutes = 9480
        self.assertIsNotNone(calendar.share_fish(state, self.world))
        self.assertFalse(calendar.chat(state, self.world, 'grandmother_whiskers', self.content))

    def test_cookout_confirmation_spends_once_and_scene_pauses(self):
        self.sunday()
        state, session = self.state, self.session
        row = next(row for row in kitchen.rows(state, self.world) if row.kind == 'cookout')
        session.ui.mode = 'kitchen'
        session._kitchen_action(row)
        before = state.game_minutes
        session.tick(Keys(pressed={'return'}), .1)
        self.assertEqual(session.ui.mode, 'cooking')
        self.assertFalse(state.well)
        session.tick(Keys(), .2)
        self.assertEqual(state.game_minutes, before)
        session.tick(Keys(pressed={'space'}), .1)
        self.assertEqual(session.ui.mode, 'kitchen')
        self.assertEqual(sum(state.v2['pantry'].values()), 1)

    def test_invitation_only_on_actual_online_advance_and_once_per_day(self):
        state, session = self.state, self.session
        spot = {'lake_id': 'briar', 'zone': 'flats', 'x': 10., 'z': 205.,
                'band': 'dawn', 'until_game_minutes': 120}
        with patch('fishing.comfort.weather_spot', return_value=None):
            session.tick(Keys(), 1)
            self.assertNotIn('invitation_day', state.v2['calendar'])
        session._hail()
        self.assertIsNotNone(session.conversation)
        with patch('fishing.comfort.weather_spot', return_value=spot):
            for mode in ('pause', 'journal', 'kitchen', 'map', 'dialogue'):
                session.ui.mode = mode
                session.tick(Keys(), 2)
            self.assertNotIn('invitation_day', state.v2['calendar'])
            session.ui.mode = 'play'
            session.tick(Keys(focused=False), 2)
            self.assertNotIn('invitation_day', state.v2['calendar'])
            session.tick(Keys(), 1)
            self.assertEqual(state.v2['calendar']['invitations_used'], 1)
            session.tick(Keys(), 1)
            self.assertEqual(state.v2['calendar']['invitations_used'], 1)
        self.assertEqual(state.v2['calendar']['invitation_mark'], spot)

    def test_week_tab_keyboard_pointer_and_every_forecast_page_are_read_only(self):
        state, session = self.state, self.session
        session.ui.mode, session.ui.journal_page = 'journal', len(BOOK_TABS)-1
        before, rng = deepcopy(state.v2), state.rng.s
        text = Text()
        self.addCleanup(text.close)
        ui = UI(text, self.world)
        for size in (0, 1, 2):
            state.v2['settings']['text_size'] = size
            for width, height in ((1280, 720), (480, 270)):
                for day in range(7):
                    panel = UIState(mode='journal', journal_page=5, book_week_i=day)
                    frame = np.zeros((height, width, 3), np.uint8)
                    ui.draw(frame, state, panel)
                    pages = panel.book_detail_pages
                    for page in range(pages):
                        panel.book_detail_page = page
                        ui.draw(frame, state, panel)
                        self.assertEqual(panel.book_detail_page, page)
        state.v2['settings'] = before['settings']
        self.assertEqual(state.v2, before)
        self.assertEqual(state.rng.s, rng)
        rect = week_rects(book_layout(1280, 720))[6]
        session.tick(Keys(mouse_click=(rect[0]+3, rect[1]+3)), .1)
        self.assertEqual(session.ui.book_week_i, 6)
        session.tick(Keys(pressed={'down'}), .1)
        self.assertEqual(session.ui.book_week_i, 0)
        self.assertEqual(state.game_minutes, 0)


if __name__ == '__main__':
    unittest.main()
