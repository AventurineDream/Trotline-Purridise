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
        """Sunday begins day zero and every week; midnight never changes the game day."""
        self.assertEqual(calendar.WEEKDAYS,
                         ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'))
        for week in (0, 1, 12):
            start = week * calendar.WEEK_MINUTES
            for day, name in enumerate(calendar.WEEKDAYS):
                for offset in (0, 1079.99, 1080, 1439.99):
                    minute = start + day * 1440 + offset
                    self.assertEqual(calendar.weekday(minute), day)
                    self.assertEqual(calendar.day_name(minute), name)
            self.assertEqual(calendar.day_name(start + 10079.99), 'Saturday')
            self.assertEqual(calendar.day_name(start + 10080), 'Sunday')
            self.assertEqual(hour_of_day(start + 10080), 6)
            for offset, active in ((659.99, False), (660, True), (839.99, True), (840, False)):
                self.assertEqual(calendar.cookout_active(start + offset), active)
                self.assertFalse(calendar.cookout_active(start + 6 * 1440 + offset))

    def test_all_ten_authored_specials_keep_their_named_weekday_and_boost(self):
        """Every authored Lake Day repeats on its named day, including Saturday day six."""
        rows = (
            ('mayfly_morning', 'briar', 2, 'Tuesday', 0, 'bluegill', 'flats', 1.3),
            ('firefly_night', 'briar', 5, 'Friday', 840, 'channel', 'deep', 1.25),
            ('shad_run', 'cedar', 4, 'Thursday', 840, 'blue', 'deep', 1.3),
            ('breezy_bass', 'cedar', 6, 'Saturday', 360, 'largemouth', 'open', 1.25),
            ('clear_sky_trout', 'flathead', 1, 'Monday', 0, 'lake_trout', 'deep', 1.3),
            ('larch_gold', 'flathead', 3, 'Wednesday', 360, 'yellow_perch', 'flats', 1.25),
            ('warm_springs', 'crater', 2, 'Tuesday', 360, 'ember_char', 'springs', 1.3),
            ('fog_lift', 'crater', 5, 'Friday', 0, 'mistfin_dace', 'flats', 1.4),
            ('meteor_shower', 'nebula', 3, 'Wednesday', 840, 'bluegill', 'open', 1.15),
            ('aurora_tide', 'nebula', 6, 'Saturday', 360, 'galaxy_gar', 'current', 1.3),
        )
        self.assertEqual({row[0] for row in rows}, {row.id for row in calendar.LAKE_DAYS})
        for week in (0, 1, 8):
            for event_id, lake, day, name, offset, species, zone, multiplier in rows:
                with self.subTest(week=week, event=event_id):
                    minute = week * calendar.WEEK_MINUTES + day * 1440 + offset
                    self.assertEqual(calendar.day_name(minute), name)
                    self.assertEqual(calendar.active_lake_day(lake, minute, zone).id, event_id)
                    self.assertEqual(calendar.rate_multiplier(lake, minute, species, zone), multiplier)
                    for other in range(7):
                        special = calendar.lake_day(lake, week * calendar.WEEK_MINUTES + other * 1440)
                        self.assertEqual(special is not None and special.id == event_id, other == day)

    def test_weekly_weather_slots_start_sunday_and_apply_named_weather_biases(self):
        """Hourly lookups keep all 168 dawn-based slots, including the Sunday week seam."""
        for seed in (4, 16, 44016):
            for week in (0, 1, 12):
                start = week * calendar.WEEK_MINUTES
                for lake in calendar.LAKE_IDS:
                    plan = calendar.weekly_plan(seed, lake, week)
                    self.assertEqual(len(plan), 168)
                    for slot, weather in enumerate(plan):
                        self.assertEqual(calendar.planned_weather(seed, lake, start + slot * 60), weather)
                        self.assertEqual(calendar.planned_weather(seed, lake, start + slot * 60 + 59.99), weather)
                self.assertEqual(calendar.planned_weather(seed, 'flathead', start + 1440 + 60), 'clear')
                self.assertEqual(calendar.planned_weather(seed, 'crater', start + 5 * 1440), 'fog')
                self.assertEqual(calendar.planned_weather(seed, 'crater', start + 5 * 1440 + 60), 'clear')
                self.assertEqual(calendar.planned_weather(seed, 'nebula', start + 6 * 1440 + 360), 'aurora')

    def test_briar_and_cedar_modifiers_only_on_their_day_band_species_and_zone(self):
        """Weekday reindexing leaves the existing band/species/zone multipliers intact."""
        rows = [
            ('briar', 2*1440, 'bluegill', 'flats', 1.3),
            ('briar', 2*1440 + 120, 'bluegill', 'flats', 1),
            ('briar', 1440, 'bluegill', 'flats', 1),
            ('briar', 2*1440, 'channel', 'flats', 1),
            ('briar', 5*1440+840, 'channel', 'deep', 1.25),
            ('briar', 5*1440+660, 'channel', 'deep', 1),
            ('cedar', 4*1440+840, 'blue', 'deep', 1.3),
            ('cedar', 4*1440+840, 'flathead', 'deep', 1),
            ('cedar', 6*1440+360, 'largemouth', 'open', 1.25),
            ('cedar', 6*1440+360, 'largemouth', 'rocks', 1.25),
            ('cedar', 6*1440+360, 'largemouth', 'lilies', 1),
            ('cedar', 5*1440+360, 'largemouth', 'open', 1)]
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
        """Place the player at the first Sunday's 17:00 cookout with an ordinary fish."""
        self.state.game_minutes = 660
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

    def test_save_reload_at_sunday_rollover_preserves_clock_rng_forecast_and_social_ledgers(self):
        """Old-style saves retain absolute days; rebuilding week caches cannot replay social events."""
        state = self.state
        state.game_minutes = calendar.WEEK_MINUTES - 1
        ledger = {
            'cookout_gifts': {'briar': 6},
            'cookout_chats': {'grandmother_whiskers': 6},
            'invitation_day': 6, 'invitations_used': 1,
            'lake_day_notes': {'briar': 5},
        }
        state.v2['calendar'].update(deepcopy(ledger))
        # Calendar saves have no weekday epoch marker. Keep that shape rather than
        # shifting game minutes, NPC selection days, or last-day social ledgers.
        calendar.ensure_plans(state)
        expected = {lake: [calendar.planned_weather(44016, lake, t)
                           for t in range(10020, 30240, 60)] for lake in calendar.LAKE_IDS}
        rng, narrative = state.rng.s, deepcopy(state.narrative.to_json())
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.game_minutes, state.game_minutes)
        self.assertEqual(calendar.day_name(loaded.game_minutes), 'Saturday')
        self.assertEqual(loaded.rng.s, rng)
        self.assertEqual(loaded.narrative.to_json(), narrative)
        for key, value in ledger.items():
            self.assertEqual(loaded.v2['calendar'][key], value)
        loaded.advance_bulk(1)
        self.assertEqual(loaded.game_minutes, calendar.WEEK_MINUTES)
        self.assertEqual(calendar.day_name(loaded.game_minutes), 'Sunday')
        self.assertEqual({row['week'] for row in loaded.v2['calendar']['weather_windows'].values()}, {1, 2})
        loaded.save(self.path, update_stamp=False)
        reloaded = State.load(self.path, self.world)
        for lake in calendar.LAKE_IDS:
            reloaded.bind(SimpleNamespace(id=lake))
            self.assertEqual([calendar.weather_at(reloaded, t) for t in range(10020, 30240, 60)], expected[lake])
        for key, value in ledger.items():
            self.assertEqual(reloaded.v2['calendar'][key], value)
        self.assertEqual(reloaded.rng.s, rng)

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
        """The simulation receives the Tuesday Lake Day minute and its deterministic forecast."""
        from .sim import Hook, SetLine
        state = self.state
        state.game_minutes = 2 * 1440
        state.lines = [SetLine('std', 'worm', 10, 205, 22, 205, 'flats', [Hook(True)])]
        with patch('fishing.sim.species_rates', wraps=species_rates) as rates:
            state._one_span(1/60)
        self.assertEqual(rates.call_args.args[3], calendar.weather_at(state))
        self.assertEqual(rates.call_args.kwargs['game_minutes'], 2 * 1440)

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
        """The first Sunday's gathering starts at 17:00 and restores the night cast at 20:00."""
        keys = set()
        for minute, count in ((659, 4), (660, 9), (839, 9), (840, 2)):
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
        """Cookout interactions require the landing/window and chats cannot repeat after reload."""
        self.sunday()
        state = self.state
        for friend in calendar.cookout_friends(self.content, 'briar'):
            self.assertTrue(calendar.chat(state, self.world, friend['id'], self.content))
            self.assertIn(calendar.CALENDAR_DATA['cookout_lines'][friend['id']], state.toasts[-1][0])
            self.assertFalse(calendar.chat(state, self.world, friend['id'], self.content))
        state.save(self.path, update_stamp=False)
        state = State.load(self.path, self.world)
        before = state.to_json()
        for friend in calendar.cookout_friends(self.content, 'briar'):
            self.assertFalse(calendar.chat(state, self.world, friend['id'], self.content))
        self.assertEqual(state.to_json(), before)
        with patch.object(state, 'slip_status', return_value='away'):
            self.assertIsNotNone(calendar.share_fish(state, self.world))
        state.game_minutes = 840
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

    def test_week_tab_lists_sunday_cookout_first_and_saturday_last_across_rollover(self):
        """Week rows, selected titles and cookout details share the Sunday-first epoch."""
        text = Text()
        self.addCleanup(text.close)
        painter = UI(text, self.world)
        frame = np.zeros((720, 1280, 3), np.uint8)
        for minute, selected, week, name, day in ((0, 0, 1, 'Sunday', 1),
                                                 (10079, 6, 1, 'Saturday', 7),
                                                 (10080, 0, 2, 'Sunday', 8)):
            self.state.game_minutes = minute
            panel = UIState(mode='journal', journal_page=5, book_week_i=selected)
            with patch.object(painter, '_text', wraps=painter._text) as drawn:
                painter.draw(frame, self.state, panel)
            labels = [call.args[1] for call in drawn.call_args_list]
            rows = [label for label in labels if label.startswith(tuple(day[:3] + ' · ' for day in calendar.WEEKDAYS))]
            self.assertEqual([label[:3] for label in rows], ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
            self.assertIn('Cookout', rows[0])
            self.assertNotIn('Cookout', rows[-1])
            self.assertIn(f'{name} · Day {day}', labels)
            self.assertTrue(any(label.startswith(f'Week {week} · ') for label in labels))
            self.assertEqual(any('Landing Cookout' in label for label in labels), selected == 0)

    def test_week_tab_keyboard_pointer_and_every_forecast_page_are_read_only(self):
        """Route Week selection only after its geometry is displayed; forecasts stay read-only."""
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
        ui.draw(np.zeros((720, 1280, 3), np.uint8), state, session.ui)
        session.tick(Keys(mouse_click=(rect[0]+3, rect[1]+3)), .1)
        self.assertEqual(session.ui.book_week_i, 6)
        session.tick(Keys(pressed={'down'}), .1)
        self.assertEqual(session.ui.book_week_i, 0)
        self.assertEqual(state.game_minutes, 0)


if __name__ == '__main__':
    unittest.main()
