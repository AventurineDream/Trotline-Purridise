"""Kitchen acceptance, ten picnic effects, persistence and protected choices."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import bot, comfort, kitchen
from .book import roll_shiny, take_dream_clue
from .boat import BOATS
from .content import ContentError, validate_content_v2
from .data import (BAIT_BY_ID, BAIT_RECIPES, CONTENT_V2_RAW, DISHES, PANTRY,
                   SPECIES_BY_ID, bait_mult)
from .game import Keys, Session
from .haul import haul_cadence
from .platform import Text
from .sim import Catch, Hook, RNG, SetLine, State, species_rates
from .software import SoftwareRenderer
from .ui import UI, UIState, comfort_controls, shop_rows


class KitchenChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .world import World
        cls.world = World()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='trotline-kitchen-')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'save.json'
        self.state = State.new(self.world, seed=43015)
        self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = 'play'

    def buff(self, dish_id):
        comfort.serve_dish(self.state, DISHES[dish_id])

    def line(self, hooks=None):
        state = self.state
        state.x, state.z = 100., 100.
        line = SetLine('std', 'worm', 100., 100., 112., 100., 'flats',
                       hooks if hooks is not None else [Hook(True) for _ in range(12)])
        state.lines = [line]
        return line

    def food(self):
        state = self.state
        state.v2['dishes_known'] = list(DISHES)
        state.v2['recipes'] = list(BAIT_RECIPES)
        state.v2['pantry'] = dict.fromkeys(PANTRY, 4)
        state.well = [Catch('bluegill', 1., 1., 0, 'flats', 'worm', 8),
                      Catch('bluegill', 2., 1., 0, 'flats', 'worm', 8)]

    def test_content_references_and_invalid_values_are_validated_together(self):
        self.assertEqual(len(DISHES), 10)
        self.assertEqual(len(BAIT_RECIPES), 8)
        broken = deepcopy(CONTENT_V2_RAW)
        broken['dishes.json']['dishes'][0]['ingredient'] = 'missing'
        broken['dishes.json']['dishes'][1]['charges'] = -1
        broken['pantry.json']['capacity'] = 21
        broken['baits.json']['baits'][-1]['recipe']['parents'] = ['missing', 'worm']
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)
        for location in ('dishes.json', 'pantry.json', 'baits.json'):
            self.assertIn(location, str(caught.exception))

    def test_each_host_stock_price_capacity_and_failed_purchase_are_atomic(self):
        state = self.state
        state.money = 10000
        for item in PANTRY.values():
            world = type('Landing', (), {'id': item.lake if item.lake != 'all' else 'briar'})()
            with patch.object(state, 'slip_status', return_value='docked'):
                before = state.money
                for _ in range(20):
                    self.assertIsNone(kitchen.buy_ingredient(state, world, item.id))
                self.assertEqual(state.v2['pantry'][item.id], 20)
                self.assertAlmostEqual(before - state.money, item.price * 20)
                snapshot = state.to_json()
                self.assertIsNotNone(kitchen.buy_ingredient(state, world, item.id))
                self.assertEqual(snapshot, state.to_json())
        state.v2['pantry']['herbs'] = 0
        state.money = 0
        snapshot = state.to_json()
        self.assertIsNotNone(kitchen.buy_ingredient(state, self.world, 'herbs'))
        self.assertIsNotNone(kitchen.buy_ingredient(state, self.world, 'pecan'))
        self.assertEqual(snapshot, state.to_json())

    def test_cooking_never_chooses_special_fish_even_when_explicitly_selected(self):
        self.food()
        state = self.state
        shiny = Catch('bluegill', .1, 1, 0, 'flats', 'worm', 8, shiny=True, treasured=False)
        treasured = Catch('bluegill', .2, 1, 0, 'flats', 'worm', 8, treasured=True)
        protected = Catch('bowfin', .3, 1, 0, 'flats', 'worm', 8)
        legendary = Catch('bluegill', .4, 1, 0, 'flats', 'worm', 8, legendary=True)
        ordinary = list(state.well)
        state.well = [shiny, treasured, protected, legendary, *ordinary]
        with patch.dict(SPECIES_BY_ID, {'bowfin': replace(SPECIES_BY_ID['bowfin'], food='panfish', tags=('protected',))}):
            self.assertEqual(kitchen.eligible_fish(state, 'panfish'), [4, 5])
            for i in range(4):
                snapshot = state.to_json()
                self.assertIsNotNone(kitchen.cook_dish(state, self.world, 'pan_fritters', i))
                self.assertEqual(state.to_json(), snapshot)
            book = deepcopy(state.v2['book'])
            self.assertIsNone(kitchen.cook_dish(state, self.world, 'pan_fritters'))
            self.assertEqual(state.well, [shiny, treasured, protected, legendary, ordinary[1]])
            self.assertEqual(state.v2['book'], book)

    def test_dish_confirmation_choice_cancel_and_skip_commit_once(self):
        self.food()
        state = self.state
        self.session.tick(Keys(pressed={'k'}), 0)
        self.assertEqual(self.session.ui.mode, 'kitchen')
        row = next(r for r in kitchen.rows(state, self.world) if r.kind == 'dish' and r.arg == 'pan_fritters')
        before = state.to_json()
        self.session._kitchen_action(row)
        self.session.tick(Keys(pressed={'esc'}), 0)
        self.assertEqual(state.well[0].weight, 1)
        self.assertEqual(state.v2['pantry']['herbs'], before['v2']['pantry']['herbs'])
        self.session._kitchen_action(row)
        self.session.tick(Keys(pressed={'down'}), 0)
        self.session.tick(Keys(pressed={'return'}), 0)
        self.assertEqual(self.session.ui.mode, 'cooking')
        self.assertEqual([c.weight for c in state.well], [1])
        self.assertEqual(state.v2['pantry']['herbs'], 3)
        self.assertEqual(state.game_minutes, before['game_minutes'])
        self.session.tick(Keys(pressed={'space'}), 0)
        self.assertEqual(state.v2['pantry']['herbs'], 3)
        self.assertEqual(State.load(self.path, self.world).v2['buff'], state.v2['buff'])

    def test_all_recipe_baits_cook_a_dozen_take_better_parent_and_reject_overflow(self):
        self.food()
        state = self.state
        for bait_id, recipe in BAIT_RECIPES.items():
            with self.subTest(bait=bait_id):
                state.bait = {parent: 1 for parent in recipe.parents}
                state.v2['pantry'][recipe.ingredient] = 1
                for species in SPECIES_BY_ID:
                    self.assertEqual(bait_mult(bait_id, species), max(bait_mult(p, species) for p in recipe.parents))
                self.assertIsNone(kitchen.cook_bait(state, self.world, bait_id))
                self.assertEqual(state.bait[bait_id], 12)
                self.assertEqual(state.bait_count(), 12)
                self.assertEqual(state.v2['pantry'][recipe.ingredient], 0)
                before = state.to_json()
                self.assertIsNotNone(kitchen.cook_bait(state, self.world, bait_id))
                self.assertEqual(state.to_json(), before)
        state.bait = {'liver': 24, 'dough': 24}
        state.v2['pantry']['herbs'] = 1
        before = state.to_json()
        self.assertIsNotNone(kitchen.cook_bait(state, self.world, 'lantern_liver'))
        self.assertIsNotNone(state.buy_bait('lantern_liver'))
        self.assertEqual(state.to_json(), before)

    def test_host_chapter_teaching_card_purchase_and_clue_teller_are_idempotent(self):
        state = self.state
        state.money = 100
        self.assertIsNotNone(kitchen.buy_card(state, self.world, 'pan_fritters'))
        state.v2['story']['chapter'] = 1
        self.assertTrue(kitchen.teach(state, 'grandmother_whiskers'))
        self.assertFalse(kitchen.teach(state, 'grandmother_whiskers'))
        self.assertEqual(set(state.v2['dishes_known']), {'herbal_stew', 'pan_fritters'})
        self.assertIn('lantern_liver', state.v2['recipes'])
        state.v2['dishes_known'].remove('pan_fritters')
        self.assertIsNotNone(kitchen.buy_card(state, self.world, 'pan_fritters'))
        state.v2['story']['chapter'] = 2
        self.assertIsNone(kitchen.buy_card(state, self.world, 'pan_fritters'))
        self.assertEqual(state.money, 60)
        self.assertIsNotNone(kitchen.buy_card(state, self.world, 'pan_fritters'))
        self.assertEqual(state.money, 60)

    def test_galley_requires_anchor_and_snacks_work_on_any_boat_without_replacing_buff(self):
        self.food()
        state = self.state
        state.x = state.z = 100
        state.anchored = False
        self.assertIsNotNone(kitchen.cook_dish(state, self.world, 'pan_fritters'))
        with patch.dict(BOATS, {'jon': replace(BOATS['jon'], traits=('galley',))}):
            self.assertFalse(kitchen.can_cook(state, self.world))
            state.anchored = True
            self.assertIsNone(kitchen.cook_dish(state, self.world, 'pan_fritters'))
        comfort.change_mode(state.v2, 'old_salt')
        state.v2['needs']['since_meal_h'] = 30
        buff = deepcopy(state.v2['buff'])
        self.assertIsNone(kitchen.snack(state))
        self.assertEqual(comfort.speed_factor(state.v2), 1)
        self.assertEqual(state.v2['buff'], buff)

    def test_herbal_stew_scout_names_two_likeliest_species_without_randomness(self):
        state = self.state
        state.bot_x = state.bot_z = 100
        with patch.object(self.world, 'zone_at', return_value='flats'), patch.object(self.world, 'depth', return_value=3):
            before = bot._report(state, self.world)
            self.assertNotIn('Likeliest here:', before)
            self.buff('herbal_stew')
            rng = state.rng.s
            report = bot._report(state, self.world)
            self.assertIn('Likeliest here:', report)
            self.assertIn(' and ', report.split('Likeliest here:')[1])
            self.assertEqual(rng, state.rng.s)

    def test_fritters_three_checks_keep_last_speed_bonus_and_do_not_spend_in_menus(self):
        line = self.line()
        self.buff('pan_fritters')
        for remaining in (2, 1, 0):
            self.session.ui.mode = 'play'
            self.session.tick(Keys(pressed={'e'}), 0)
            self.assertEqual(self.session.ui.haul_picnic_factor, .8)
            self.assertAlmostEqual(haul_cadence(self.state) * self.session.ui.haul_picnic_factor, .2)
            self.session.tick(Keys(focused=False), 1)
            self.assertEqual(self.state.v2['buff']['charges'], remaining + 1)
            self.session.tick(Keys(), .21)
            buff = self.state.v2['buff']
            self.assertEqual(buff['charges'] if buff else 0, remaining)
        self.assertEqual(comfort.begin_haul(self.state, line), 1)

    def test_chowder_reduces_actual_fuel_burn_without_altering_propulsion(self):
        state = self.state
        other = State.new(self.world, seed=43015)
        self.buff('pecan_chowder')
        for item in (state, other):
            item.anchored = False
            item.throttle = item.throttle_setting = 1
            item.drive(1, 0, 0, self.world)
        base_burn = 12 - other.fuel
        self.assertGreater(base_burn, 0)
        self.assertAlmostEqual(12 - state.fuel, base_burn * .75)
        self.assertAlmostEqual(state.speed, other.speed)

    def test_tacos_give_one_extra_weather_invitation_today_only(self):
        state = self.state
        spot = {'lake_id': 'briar', 'zone': 'flats', 'x': 100., 'z': 100.,
                'band': 'day', 'until_game_minutes': 120}
        with patch('fishing.comfort.weather_spot', return_value=None):
            self.assertIsNone(comfort.weather_invitation(state))
            self.assertNotIn('invitations_used', state.v2['calendar'])
        with patch('fishing.comfort.weather_spot', return_value=spot):
            self.assertIsNone(comfort.weather_invitation(state))
            self.assertEqual(state.v2['calendar']['invitation_mark'], spot)
            self.assertIsNotNone(comfort.weather_invitation(state))
            self.buff('smoky_tacos')
            self.assertIsNone(comfort.weather_invitation(state))
            self.assertIsNone(state.v2['buff'])
            self.buff('smoky_tacos')
            self.assertIsNotNone(comfort.weather_invitation(state))
            state.advance_bulk(1440)
            self.assertFalse(comfort.has_buff(state, 'weather_invitation'))
            self.assertIsNone(comfort.weather_invitation(state))

    def test_weather_marks_only_current_favorable_nearby_water(self):
        state = self.state
        _zone, state.x, state.z, _radius = next(row for row in self.world.zones if row[0] == 'flats')
        state.game_minutes = 360
        before = state.rng.s
        with patch('fishing.data.weather_at', return_value='clear'):
            spot = comfort.weather_spot(state)
            self.assertIsNotNone(spot)
            self.assertEqual(spot['band'], 'day')
            self.assertLessEqual(np.hypot(spot['x'] - state.x, spot['z'] - state.z), 300)
            self.assertIsNone(comfort.weather_invitation(state))
            self.assertEqual(state.v2['calendar']['invitation_mark'], spot)
        with patch('fishing.data.weather_at', return_value='mist'):
            self.assertIsNone(comfort.weather_spot(state))
        self.assertEqual(state.rng.s, before)

    def test_trout_extends_actual_scout_target_and_suppresses_snow_gust_push(self):
        state = self.state
        line = self.line()
        line.x0, line.x1 = 250, 270  # midpoint 160 m from skipper
        with patch('fishing.bot._afloat', return_value=True):
            self.assertIsNone(bot._target(state, self.world)[2])
            self.buff('smoked_trout')
            self.assertEqual(bot._target(state, self.world)[2], line.line_id)
        self.assertEqual(comfort.gust_factor(state, 'snow_mist'), 0)
        self.assertEqual(comfort.scout_range_factor(state, 'snow_mist'), 1)
        self.assertEqual(comfort.scout_range_factor(state, 'clear'), 1.25)
        state.anchored, state.anim = False, 1.
        with patch('fishing.sim.weather_at', return_value='snow_mist'), patch('fishing.sim.wind_at', return_value=(1., 5.)):
            with patch.object(state, '_move', return_value=(True, [])) as move:
                state.drive(1, 0, 0, self.world)
                self.assertEqual(move.call_args.args[:2], (state.x, state.z))
            state.v2['buff'] = None
            with patch.object(state, '_move', return_value=(True, [])) as move:
                state.drive(1, 0, 0, self.world)
                self.assertNotEqual(move.call_args.args[:2], (state.x, state.z))
        state.v2['buff'] = None
        self.assertEqual(comfort.gust_factor(state, 'snow_mist'), 1)

    def test_pie_queues_extra_dream_despite_unread_and_rested_then_consumes_once(self):
        state = self.state
        state.catnap(self.world)
        first = deepcopy(state.v2['book']['dream_clue'])
        self.buff('huckle_pie')
        state.catnap(self.world)
        self.assertEqual(state.v2['book']['dream_clue'], first)
        self.assertEqual(len(state.v2['book']['dream_queue']), 1)
        queued = deepcopy(state.v2['book']['dream_queue'][0])
        self.assertNotEqual(queued['species'], first['species'])
        state.catnap(self.world)
        self.assertEqual(len(state.v2['book']['dream_queue']), 1)
        self.assertEqual(take_dream_clue(state.v2['book']), first)
        self.assertEqual(state.v2['book']['dream_clue'], queued)
        self.assertIsNone(state.v2['buff'])

    def test_mineral_broth_thins_fog_locally_and_changes_software_frame(self):
        state = self.state
        renderer = SoftwareRenderer(self.world, 160, 90)
        self.addCleanup(renderer.close)
        original = renderer.render(state).copy()
        self.buff('mineral_broth')
        self.assertEqual(comfort.fog_factor(state, 149), .25)
        self.assertEqual(comfort.fog_factor(state, 151), 1)
        changed = renderer.render(state).copy()
        self.assertTrue(np.any(original != changed))

    def test_hotpot_keeps_empty_hook_bait_for_three_checks_without_changing_unbuffed_hooks(self):
        line = self.line([Hook(False), Hook(True)])
        comfort.begin_haul(self.state, line)
        self.assertFalse(line.hooks[0].baited)
        self.buff('ember_hotpot')
        for _ in range(3):
            line.hooks[0].baited = False
            comfort.begin_haul(self.state, line)
            self.assertTrue(line.hooks[0].baited)
        line.hooks[0].baited = False
        comfort.begin_haul(self.state, line)
        self.assertFalse(line.hooks[0].baited)

    def test_pudding_counts_tracked_fish_twice_once_and_preserves_the_normal_shiny_roll(self):
        state = self.state
        fish = Catch('bluegill', 1, 1, 0, 'flats', 'worm', 8)
        line = self.line([Hook(False, fish)])
        state.journal['bluegill']['count'] = 6
        state.v2['book']['tracked'] = 'bluegill'
        state.v2['book']['species']['bluegill'] = {'since_shiny': 49}
        self.buff('moon_pudding')
        comfort.begin_haul(state, line)
        self.assertEqual(state.v2['book']['species']['bluegill']['since_shiny'], 50)
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        comfort.begin_haul(loaded, loaded.lines[0])
        self.assertEqual(loaded.v2['book']['species']['bluegill']['since_shiny'], 50)
        rng = type('NoRandomShiny', (), {'chance': lambda self, p: False})()
        self.assertTrue(roll_shiny(loaded.v2['book'], loaded.journal, 'bluegill', rng))
        self.assertEqual(loaded.v2['book']['species']['bluegill']['since_shiny'], 0)

    def test_soup_glows_buoys_and_extends_meal_to_48_hours_beyond_visual_buff(self):
        state = self.state
        self.line()
        comfort.change_mode(state.v2, 'old_salt')
        self.buff('starlight_soup')
        self.assertTrue(comfort.has_buff(state, 'glow_buoys'))
        comfort.change_mode(state.v2, 'cozy')
        comfort.change_mode(state.v2, 'old_salt')
        self.assertEqual(state.v2['needs']['meal_hours'], 48)
        state.advance_bulk(25 * 60)
        self.assertFalse(comfort.has_buff(state, 'glow_buoys'))
        self.assertEqual(comfort.speed_factor(state.v2), 1)
        state.advance_bulk(23 * 60 + 1)
        self.assertEqual(comfort.speed_factor(state.v2), .8)
        comfort.meal(state.v2)
        self.assertEqual(state.v2['needs']['meal_hours'], 24)

    def test_buffs_never_stack_and_pantry_recipes_future_fields_round_trip(self):
        self.food()
        state = self.state
        self.buff('pecan_chowder')
        self.buff('pan_fritters')
        self.assertEqual(comfort.fuel_factor(state), 1)
        self.assertTrue(comfort.has_buff(state, 'quick_haul'))
        state.v2['pantry']['future_item'] = {'keep': True}
        state.v2['buff']['future'] = 42
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        for key in ('pantry', 'recipes', 'dishes_known', 'buff'):
            self.assertEqual(state.v2[key], loaded.v2[key])
        loaded.bind(self.world)
        self.assertTrue(comfort.has_buff(loaded, 'quick_haul'))
        before = deepcopy(loaded.v2['buff'])
        loaded.catch_up(now=loaded.stamp + 3600)
        self.assertEqual(before, loaded.v2['buff'])

    def test_no_active_buff_preserves_base_rates_bait_matches_and_seeded_catches(self):
        ordinary_baits = ('worm', 'liver', 'shad', 'minnow', 'craw')
        matches = {bait: CONTENT_V2_RAW['baits.json']['baits'][i]['matches'] for i, bait in enumerate(ordinary_baits)}
        self.assertEqual(hashlib.sha256(json.dumps(matches, sort_keys=True).encode()).hexdigest(),
                         'a68bd13fb8a92a543aaf8fb807ecac5a755e806e33a0246a33c128703812f7cf')
        rates = [species_rates(zone, bait, hour, weather, depth)
                 for zone in ('flats', 'deep', 'lilies') for bait in ordinary_baits
                 for hour in (6, 12, 18, 23) for weather in ('clear', 'mist', 'rain') for depth in (2, 10)]
        self.assertEqual(hashlib.sha256(json.dumps(rates, sort_keys=True).encode()).hexdigest(),
                         '4dbcdcdf6f675eac4cc9e993719daa65f2076aff75f9adae2152dc96f2cfa5cc')
        state, other = self.state, State.new(self.world, seed=43015)
        line = self.line([Hook(True) for _ in range(12)])
        other.lines = [SetLine.from_json(line.to_json())]
        other.v2['buff'] = {'dish': 'future_dish', 'future': True}
        state.advance_bulk(600)
        other.advance_bulk(600)
        self.assertEqual(state.rng.s, other.rng.s)
        self.assertEqual([x.to_json() for x in state.lines], [x.to_json() for x in other.lines])
        self.assertEqual(comfort.fuel_factor(state), 1)
        self.assertEqual(comfort.begin_haul(state, line), 1)

    def test_kitchen_panels_fit_both_fonts_all_sizes_and_do_not_mutate_save(self):
        self.food()
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        records = []
        original = renderer._text
        def record(frame, label, x, y, size, color, shadow=True, family='mono'):
            image = renderer._render(label, size, color, family)
            if label:
                records.append((label, x, y, image.shape[1], image.shape[0]))
            return original(frame, label, x, y, size, color, shadow, family)
        renderer._text = record
        for w, h in ((1280, 720), (480, 270)):
            for font in (False, True):
                for size in range(3):
                    self.state.v2['settings'].update({'text_size': size, 'dyslexia_font': font})
                    for mode in ('kitchen', 'shop', 'cook_confirm', 'cooking'):
                        ui = UIState(mode=mode, shop_tab=6, cook_kind='dish', cook_arg='pan_fritters',
                                     cook_label='Sunny Pan Fritters', cook_text=DISHES['pan_fritters'].blurb,
                                     caption='A soft click sounds.', caption_timer=1)
                        records.clear()
                        before = deepcopy(self.state.v2)
                        renderer.draw(np.zeros((h, w, 3), np.uint8), self.state, ui)
                        self.assertEqual(self.state.v2, before)
                        for i, (label, x, y, rw, rh) in enumerate(records):
                            with self.subTest(mode=mode, width=w, font=font, size=size, label=label):
                                self.assertGreaterEqual(x, 0)
                                self.assertGreaterEqual(y, 0)
                                self.assertLessEqual(x + rw, w)
                                self.assertLessEqual(y + rh, h)
                                for other, ox, oy, ow, oh in records[:i]:
                                    self.assertFalse(x < ox + ow and ox < x + rw and y < oy + oh and oy < y + rh,
                                                     f'{label!r} overlaps {other!r}')

    def test_mouse_purchase_controller_access_and_hunger_snack(self):
        state = self.state
        state.money = 100
        self.session.tick(Keys(pressed={'e'}), 0)
        self.session.ui.shop_tab = 6
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        renderer.draw(np.zeros((720, 1280, 3), np.uint8), state, self.session.ui)
        rows = kitchen.rows(state, self.world)
        target = next(i for i, row in enumerate(rows) if row.kind == 'ingredient' and row.arg == 'kibble')
        box = next(rect for index, rect in self.session.ui.kitchen_hitboxes if index == target)
        self.session.tick(Keys(mouse_click=(box[0] + 3, box[1] + 3)), 0)
        self.assertEqual(state.v2['pantry']['kibble'], 1)
        self.assertEqual(state.money, 97)
        self.session.ui.mode = 'pause'
        from .platform import Input
        keys = Input()
        keys.device, keys.gamepad_pressed = 'gamepad', {'b'}
        self.session.tick(keys, 0)
        self.assertEqual(self.session.ui.mode, 'kitchen')
        self.session.tick(Keys(pressed={'esc'}), 0)
        self.assertEqual(self.session.ui.mode, 'pause')
        self.session.ui.mode = 'play'
        comfort.change_mode(state.v2, 'old_salt')
        state.v2['needs']['since_meal_h'] = 30
        self.session.tick(Keys(), 0)
        self.assertEqual(self.session.ui.needs_kind, 'hunger')
        self.session.tick(Keys(pressed={'return'}), 0)
        self.assertEqual(state.v2['pantry']['kibble'], 0)
        self.assertEqual(comfort.speed_factor(state.v2), 1)

    def test_timed_buff_freezes_with_menus_focus_loss_offline_and_expires_in_play(self):
        self.buff('pecan_chowder')
        state = self.state
        before = state.narrative.active_play_game_minutes
        for mode in ('kitchen', 'cook_confirm', 'cooking', 'shop', 'pause'):
            self.session.ui.mode = mode
            self.session.tick(Keys(focused=False), 2)
            self.assertEqual(state.narrative.active_play_game_minutes, before)
        self.session.ui.mode = 'play'
        self.session.tick(Keys(focused=False), 10)
        state.catch_up(now=state.stamp + 3600)
        self.assertTrue(comfort.has_buff(state, 'fuel_saver'))
        self.assertEqual(state.narrative.active_play_game_minutes, before)
        state.advance_bulk(359)
        self.assertTrue(comfort.has_buff(state, 'fuel_saver'))
        state.advance_bulk(1)
        self.assertFalse(comfort.has_buff(state, 'fuel_saver'))

    def test_soup_changes_visible_buoys_on_water_and_chart_without_mutating_state(self):
        state = self.state
        fx, fz = np.sin(state.yaw), np.cos(state.yaw)
        state.lines = [SetLine('std', 'worm', state.x + fx * 18, state.z + fz * 18,
                               state.x + fx * 30, state.z + fz * 30, 'open', [Hook(True)])]
        state.game_minutes = 18 * 60  # midnight
        renderer = SoftwareRenderer(self.world, 160, 90)
        self.addCleanup(renderer.close)
        ordinary = renderer.render(state).copy()
        self.buff('starlight_soup')
        glowing = renderer.render(state).copy()
        self.assertTrue(np.any(ordinary != glowing))
        text = Text()
        self.addCleanup(text.close)
        painter = UI(text, self.world)
        points = []
        old_dot = painter._dot
        painter._dot = lambda *args: (points.append(args[1:]), old_dot(*args))[-1]
        before = state.to_json()
        painter.draw(np.zeros((720, 1280, 3), np.uint8), state, UIState(mode='map'))
        self.assertEqual(before, state.to_json())
        self.assertTrue(any(radius == 4 for _x, _y, radius, _color in points))


if __name__ == '__main__':
    unittest.main()
