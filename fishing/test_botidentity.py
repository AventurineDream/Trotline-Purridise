"""Bot identity, migration, atomic purchases, collar choices and presentation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import bot, botidentity as identity
from .content import ContentError, validate_content_v2
from .data import (BOT_COLLAR_STAGES, BOT_KNOTS, BOT_PREFIXES, BOT_SHELLS, BOT_TOOLS,
                   CONTENT_V2_RAW)
from .dialogue import Conversation
from .game import Keys, Session
from .platform import Text
from .savepaths import merge_v2_defaults
from .sim import State
from .ui import SHOP_TABS, UI, UIState, shop_rows
from .world import World


class BotDataChecks(unittest.TestCase):
    def test_twelve_prefixes_range_and_stable_name_for_signed_seeds(self):
        self.assertEqual(len(BOT_PREFIXES), 12)
        self.assertIn('Rivet', BOT_PREFIXES)
        self.assertNotIn('Pebble', BOT_PREFIXES)
        prefixes = set()
        for seed in range(-1000, 1000):
            name = identity.generated_name(seed)
            self.assertEqual(name, identity.generated_name(seed))
            word, suffix = name.split('-')
            self.assertEqual(len(suffix), 3)
            self.assertLessEqual(11, int(suffix))
            self.assertLessEqual(int(suffix), 999)
            prefixes.add(word)
        self.assertEqual(prefixes, set(BOT_PREFIXES))
        self.assertEqual(identity.generated_name(0), 'Cobalt-774')
        self.assertNotEqual(identity.generated_name(517), identity.generated_name(-517))

    def test_registry_has_five_shells_prices_and_three_knots(self):
        self.assertEqual(tuple(BOT_SHELLS), ('tin', 'frog', 'duck', 'sub', 'astral'))
        self.assertEqual([s.chapter for s in BOT_SHELLS.values()], [0, 1, 2, 3, 5])
        self.assertEqual([BOT_TOOLS[s.tool_id].price for s in BOT_SHELLS.values()], [150, 120, 180, 260, 400])
        self.assertTrue(BOT_TOOLS['sonar_grid'].requires_finder)
        self.assertEqual(tuple(BOT_KNOTS.values()), ('Square knot', 'Bow', "Sailor's hitch"))

    def test_bad_bot_data_reports_all_locations(self):
        raw = deepcopy(CONTENT_V2_RAW)
        raw['bot.json']['name_prefixes'][10] = 'Pebble'
        raw['bot.json']['suffix_min'] = 0
        raw['bot.json']['shells'][1]['tool_id'] = 'missing'
        raw['bot.json']['tools'][0]['price'] = -1
        raw['bot.json']['tools'][1]['requires_finder'] = 'yes'
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(raw)
        for field in ('name_prefixes', 'suffix_min', 'tool_id', 'price', 'requires_finder'):
            self.assertIn(field, str(caught.exception))

    def test_invalid_prefix_shape_collects_errors_instead_of_crashing(self):
        for value in (None, ['Rivet'] * 12, [{}] * 12):
            raw = deepcopy(CONTENT_V2_RAW)
            raw['bot.json']['name_prefixes'] = value
            with self.assertRaises(ContentError):
                validate_content_v2(raw)


class BotIdentityChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='trotline-bot-')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'save.json'
        self.state = State.new(self.world, seed=4517)
        self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = 'play'

    def ready_knot(self):
        self.state.v2['story'].update(chapter=4, completed_chapters=[1, 2, 3],
                                      scene_states={'story_c4_knot': 'ready'})
        identity.sync_story_rewards(self.state)

    def test_name_migrates_from_schedule_seed_without_fishing_rng_draws(self):
        state = self.state
        raw = state.to_json()
        raw['version'] = 1
        raw.pop('v2')
        raw['narrative_v1']['schedule_seed'] = -517
        self.path.write_text(json.dumps(raw))
        loaded = State.load(self.path, self.world)
        self.assertEqual(identity.name(loaded), 'Brass-373')
        self.assertEqual(loaded.rng.s, raw['seed'])
        loaded.save(self.path, update_stamp=False)
        again = State.load(self.path, self.world)
        self.assertEqual(identity.name(again), 'Brass-373')
        again.narrative.schedule_seed = 123456
        again.save(self.path, update_stamp=False)
        self.assertEqual(identity.name(State.load(self.path, self.world)), 'Brass-373')

    def test_existing_valid_name_stays_and_old_placeholder_is_repaired(self):
        for saved, expected in (('Copper-316', 'Copper-316'), ('Nova-777', 'Nova-777'),
                                ('Copper-000', 'Cobalt-774'), ('', 'Cobalt-774')):
            state = self.state
            state.v2['profile']['bot_name'] = saved
            state.save(self.path, update_stamp=False)
            loaded = State.load(self.path, self.world)
            self.assertEqual(identity.name(loaded), expected)

    def test_unknown_profile_fields_and_future_ids_survive_normalization(self):
        saved = {'profile': {'bot_name': 'Nova-777', 'shell': 'future_shell',
                    'shells': ['tin', 'future_shell', 'frog', 'frog', {}],
                    'tools': ['future_tool', 'reed_anchor', None],
                    'future': {'kept': True},
                    'collar': {'stage': 'future_stage', 'knot': 'future_knot', 'future': 42}}}
        normalized = merge_v2_defaults(self.state, saved)
        p = normalized['profile']
        self.assertEqual(p['bot_name'], 'Nova-777')
        self.assertEqual(p['shell'], 'future_shell')
        self.assertEqual(p['shells'], ['tin', 'future_shell', 'frog'])
        self.assertEqual(p['tools'], ['future_tool', 'reed_anchor'])
        self.assertEqual(p['future'], {'kept': True})
        self.assertEqual(p['collar']['stage'], 'future_stage')
        self.assertEqual(p['collar']['knot'], 'future_knot')
        self.assertEqual(p['collar']['future'], 42)
        self.assertEqual(saved['profile']['shells'][-1], {})

    def test_completed_chapters_reconcile_rewards_without_replaying_or_auto_equipping(self):
        state = self.state
        name, money, rng, toasts = identity.name(state), state.money, state.rng.s, deepcopy(state.toasts)
        state.v2['story']['completed_chapters'] = [1, 2, 3, 5]
        self.assertTrue(identity.sync_story_rewards(state))
        self.assertFalse(identity.sync_story_rewards(state))
        self.assertEqual(set(identity.profile(state)['shells']), set(BOT_SHELLS))
        self.assertEqual(identity.profile(state)['shell'], 'tin')
        self.assertEqual(identity.profile(state)['collar']['stage'], 'loose')
        self.assertEqual(identity.profile(state)['tools'], [])
        self.assertEqual((identity.name(state), state.money, state.rng.s, state.toasts), (name, money, rng, toasts))
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(identity.profile(loaded), identity.profile(state))

    def test_shell_swap_keeps_all_memories_scouting_fields_and_progress_after_reload(self):
        state = self.state
        identity.grant_shell(state, 'frog')
        state.bot_phase, state.bot_tx, state.bot_tz = 'out', 75., -25.
        state.bot_target_line_id = 'saved-target'
        state.narrative.record_bot_note('Bot: A remembered depth.')
        state.narrative.record_bot_reaction('kept', 'An approving click.')
        before = state.to_json()
        self.assertIsNone(identity.swap_shell(state, self.world, 'frog'))
        after = state.to_json()
        before['v2']['profile']['shell'] = 'frog'
        self.assertEqual(before, after)
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(identity.profile(loaded)['shell'], 'frog')
        self.assertEqual(loaded.narrative.bot_notes, state.narrative.bot_notes)
        self.assertEqual(loaded.narrative.bot_reactions, state.narrative.bot_reactions)
        self.assertEqual(loaded.bot_phase, 'out')
        self.assertTrue(identity.grant_shell(state, 'duck'))
        self.assertFalse(identity.grant_shell(state, 'duck'))

    def test_unearned_shell_or_moving_or_away_swap_is_atomic(self):
        state = self.state
        for shell in ('frog', 'missing'):
            before = state.to_json()
            self.assertIsNotNone(identity.swap_shell(state, self.world, shell))
            self.assertEqual(before, state.to_json())
        identity.grant_shell(state, 'frog')
        for status, speed in (('docked', .5), ('away', 0)):
            state.speed = speed
            before = state.to_json()
            with patch.object(state, 'slip_status', return_value=status):
                self.assertIsNotNone(identity.swap_shell(state, self.world, 'frog'))
            self.assertEqual(before, state.to_json())

    def test_tool_purchase_requires_earned_shell_not_equipped_shell_and_never_double_charges(self):
        state = self.state
        state.money = 2000
        for shell in BOT_SHELLS.values():
            tool = BOT_TOOLS[shell.tool_id]
            if shell.id != 'tin':
                before = state.to_json()
                self.assertIsNotNone(identity.buy_tool(state, self.world, tool.id))
                self.assertEqual(before, state.to_json())
                identity.grant_shell(state, shell.id)
            if tool.requires_finder:
                before = state.to_json()
                self.assertIsNotNone(identity.buy_tool(state, self.world, tool.id))
                self.assertEqual(before, state.to_json())
                state.finder = True
            before = state.money
            self.assertIsNone(identity.buy_tool(state, self.world, tool.id))
            self.assertEqual(state.money, before-tool.price)
            self.assertEqual(identity.profile(state)['shell'], 'tin')
            snapshot = state.to_json()
            self.assertIsNotNone(identity.buy_tool(state, self.world, tool.id))
            self.assertEqual(snapshot, state.to_json())
        self.assertEqual(set(identity.profile(state)['tools']), set(BOT_TOOLS))
        self.assertIsNone(identity.swap_shell(state, self.world, 'duck'))
        self.assertEqual(set(identity.profile(state)['tools']), set(BOT_TOOLS))

    def test_tool_failure_and_free_story_grant_are_atomic(self):
        state = self.state
        state.finder, state.money = True, 0
        before = state.to_json()
        self.assertIsNotNone(identity.buy_tool(state, self.world, 'sonar_grid'))
        self.assertEqual(before, state.to_json())
        state.money = 500
        with patch.object(state, 'slip_status', return_value='away'):
            before = state.to_json()
            self.assertIsNotNone(identity.buy_tool(state, self.world, 'sonar_grid'))
            self.assertEqual(before, state.to_json())
        self.assertTrue(identity.grant_tool(state, 'reed_anchor'))
        self.assertFalse(identity.grant_tool(state, 'reed_anchor'))
        self.assertEqual(state.money, 500)
        self.assertEqual(identity.profile(state)['shells'], ['tin'])

    def test_collar_arc_and_each_saved_cosmetic_choice_keep_visibility_and_do_not_replay(self):
        for knot in BOT_KNOTS:
            state = State.new(self.world, seed=4517)
            self.state = state
            state.v2['settings']['collar_visible'] = False
            state.v2['profile']['collar']['visible'] = False
            self.assertFalse(identity.advance_collar(state, 'loose'))
            self.assertTrue(identity.advance_collar(state, 'received'))
            self.assertFalse(identity.advance_collar(state, 'received'))
            self.assertTrue(identity.advance_collar(state, 'loose'))
            state.v2['story']['chapter'] = 4
            self.assertIsNotNone(identity.choose_knot(state, knot))  # marker scene not ready
            self.ready_knot()
            self.assertIsNone(identity.choose_knot(state, knot))
            self.assertEqual(identity.profile(state)['collar']['stage'], 'retied')
            self.assertEqual(identity.profile(state)['collar']['knot'], knot)
            self.assertFalse(identity.profile(state)['collar']['visible'])
            other = next(k for k in BOT_KNOTS if k != knot)
            before = state.to_json()
            self.assertIsNotNone(identity.choose_knot(state, other))
            self.assertEqual(before, state.to_json())
            self.assertTrue(identity.advance_collar(state, 'favorite'))
            state.save(self.path, update_stamp=False)
            loaded = State.load(self.path, self.world)
            self.assertEqual(identity.profile(loaded)['collar'], identity.profile(state)['collar'])
            self.assertFalse(loaded.v2['settings']['collar_visible'])

    def test_render_collar_only_after_receiving_and_settings_never_change_story(self):
        state = self.state
        def wool():
            return any(np.allclose(face.color, bot._COLLAR_WOOL) for face in bot.faces(state))
        self.assertFalse(wool())
        identity.advance_collar(state, 'received')
        self.assertTrue(wool())
        for shell in BOT_SHELLS:
            identity.grant_shell(state, shell)
            identity.swap_shell(state, self.world, shell)
            self.assertTrue(wool())
            before = deepcopy(identity.profile(state)['collar'])
            state.v2['settings']['collar_visible'] = False
            self.assertFalse(wool())
            self.assertEqual(identity.profile(state)['collar'], before)
            state.v2['settings']['collar_visible'] = True

    def test_dialogue_placeholder_and_book_ending_credit_are_read_only(self):
        state = self.state
        before = state.to_json()
        value = identity.format_text('Hello {BotName}. {Skipper} keeps {unknown} and {literal:03d}.', state)
        self.assertEqual(value, 'Hello Cobalt-774. Skipper keeps {unknown} and {literal:03d}.')
        self.assertEqual(before, state.to_json())
        self.assertIn('with Cobalt-774', identity.book_credit(state))
        state.v2['story']['scene_states']['end_02'] = 'done'
        self.assertEqual(identity.book_credit(state), 'the Skipper & Cobalt-774')

    def test_keyboard_and_pointer_landing_actions_save_once_and_pause_time(self):
        state, session = self.state, self.session
        identity.grant_shell(state, 'frog')
        session.ui.mode, session.ui.shop_tab = 'shop', SHOP_TABS.index('Bot')
        session.ui.shop_i = 1
        before = state.game_minutes
        session.tick(Keys(pressed={'return'}), 1)
        self.assertEqual(identity.profile(state)['shell'], 'frog')
        self.assertEqual(state.game_minutes, before)
        self.assertEqual(identity.profile(State.load(self.path, self.world))['shell'], 'frog')
        state.finder, state.money = True, 200
        rows = shop_rows(state, 7)
        index = next(i for i, row in enumerate(rows) if row.arg == 'sonar_grid')
        session.ui.kitchen_hitboxes = [(index, (20, 20, 150, 30))]
        session.tick(Keys(mouse_click=(30, 30)), 1)
        self.assertEqual(state.money, 50)
        self.assertIn('sonar_grid', identity.profile(state)['tools'])
        self.assertEqual(state.game_minutes, before)

    def test_new_menu_title_slot_book_and_dialogue_draw_without_mutating_state(self):
        state = self.state
        text = Text()
        self.addCleanup(text.close)
        painter = UI(text, self.world)
        content = deepcopy(self.session._npc_content)
        npc = state.npcs[0]
        chat = Conversation.start(npc, state, content)
        content.dialogue[chat.node_id]['text'] = 'Hello, {BotName}. Welcome back, {Skipper}.'
        labels = []
        original = painter._text
        def record(frame, label, *args, **kwargs):
            labels.append(label)
            return original(frame, label, *args, **kwargs)
        painter._text = record
        before, rng = deepcopy(state.v2), state.rng.s
        for size in (0, 1, 2):
            state.v2['settings']['text_size'] = size
            for panel in (UIState(mode='title', has_save=True), UIState(mode='journal'),
                          UIState(mode='shop', shop_tab=7),
                          UIState(mode='dialogue', conversation=chat, dialogue_content=content)):
                painter.draw(np.zeros((720, 1280, 3), np.uint8), state, panel)
        state.v2['settings'] = before['settings']
        self.assertEqual(state.v2, before)
        self.assertEqual(state.rng.s, rng)
        self.assertTrue(any('Continue · Cobalt-774' in s for s in labels))
        self.assertTrue(any('Hello, Cobalt-774' in s for s in labels))
        self.assertFalse(any('{BotName}' in s for s in labels))

    def test_existing_scout_launch_report_return_and_stationary_mesh_checks(self):
        bot.checks(self.world)


if __name__ == '__main__':
    unittest.main()
