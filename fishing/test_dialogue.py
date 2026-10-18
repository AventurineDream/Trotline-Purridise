"""Real input/session coverage for optional conversations and simulation."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .platform import SCAN
from .dialogue import HAIL_SPEED_MPS, nearby_npc
from .game import Keys, Session
from .sim import State
from .npcs import active_npcs
from .narrative import DAY_NPCS
from .world import World


class DialogueChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'save.json'
        self.state = State.new(self.world, seed=87)
        self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = 'play'
        self.npc = self.state.npcs[1]
        self.state.x, self.state.z = self.npc.anchor.position

    def key(self, *keys, dt=0):
        self.session.tick(Keys(pressed=keys), dt)

    def test_native_hail_binding(self):
        self.assertEqual(SCAN["c"], 6)
        self.assertEqual(SCAN["h"], 11)
        self.assertEqual(SCAN["e"], 8)

    def test_range_speed_and_nearest(self):
        for distance, speed, expected in ((20, 0, True), (20.0001, 0, False),
                (0, HAIL_SPEED_MPS-.00001, True), (0, HAIL_SPEED_MPS, False),
                (0, -HAIL_SPEED_MPS, False), (0, -HAIL_SPEED_MPS+.00001, True)):
            self.state.x = self.npc.anchor.x + distance
            self.state.speed = speed
            self.assertEqual(nearby_npc(self.state) is not None, expected)
        self.state.speed = 0
        self.state.x = self.npc.anchor.x
        other = replace(self.state.npcs[0], anchor=replace(self.npc.anchor, x=self.state.x+5))
        self.state.npcs = (other, self.npc)
        self.assertEqual(nearby_npc(self.state).id, self.npc.id)
        self.state.npcs = (replace(self.npc, anchor=replace(self.npc.anchor, id='cedar:open')),)
        self.assertIsNone(nearby_npc(self.state))

    def test_hail_decline_accept_persistence(self):
        q = self.state.narrative.quests[self.npc.quest_id]
        self.key('c'); self.assertEqual(self.session.ui.mode, 'dialogue')
        self.assertEqual(q.status, 'available')
        self.key('c'); self.key('2')
        self.assertEqual(q.status, 'available')
        self.assertTrue(q.declined)
        self.key('esc'); self.key('c'); self.key('space'); self.key('1')
        self.assertEqual(q.status, 'active')
        accepted = q.accepted_game_minute
        self.session.save()
        restored = State.load(self.path, self.world)
        self.assertEqual(restored.narrative.quests[self.npc.quest_id].status, 'active')
        self.assertEqual(restored.narrative.quests[self.npc.quest_id].accepted_game_minute, accepted)
        self.key('return'); self.key('c')
        self.assertTrue(self.session.conversation.node_id.endswith(':progress'))

    def test_help_shop_chart_and_controls_restore(self):
        self.key('h'); self.assertEqual(self.session.ui.mode, 'help')
        self.key('esc'); self.key('tab'); self.key('c')
        self.assertEqual(self.session.ui.mode, 'dialogue')
        self.key('h'); self.assertEqual(self.session.ui.mode, 'help')
        self.key('esc'); self.assertEqual(self.session.ui.mode, 'dialogue')
        self.key('s')
        self.session.tick(Keys(pressed=['esc'], held=['s']), 0)
        self.assertEqual(self.session.ui.mode, 'map')
        with patch.object(self.state, 'drive') as drive:
            self.session.tick(Keys(held=['s']), .1)
            self.assertEqual(drive.call_args.args[1], 0)
        self.key('tab')
        with patch.object(self.state, 'drive') as drive:
            self.key('w', dt=.1)
            self.assertGreater(drive.call_args.args[1], 0)
        self.state._park(self.world)
        self.key('e'); self.assertEqual(self.session.ui.mode, 'shop')

    def test_dialogue_ticks_clock_lines_and_bot_without_driving(self):
        self.key('c')
        before = self.state.game_minutes
        with patch.object(self.state, 'drive', wraps=self.state.drive) as drive, patch('fishing.game.tick_bot') as bot:
            bot.return_value = None
            self.session.tick(Keys(held=['w', 'a']), 2)
            self.assertEqual(drive.call_args.args[1:3], (0, 0))
            self.assertTrue(drive.call_args.kwargs['idle'])
            bot.assert_called_once()
        self.assertGreater(self.state.game_minutes, before)
        self.assertEqual(self.state.narrative.quests[self.npc.quest_id].progress, {})

    def test_schedule_exit_and_ready_does_not_pay(self):
        self.key('c')
        self.state.game_minutes = 840
        self.session._simulate(Keys(), 0)
        self.assertEqual(self.session.ui.mode, 'play')
        self.state.game_minutes = 0
        self.session._refresh_npcs()
        q = self.state.narrative.quests[self.npc.quest_id]
        q.status = 'ready'
        money = self.state.money
        self.key('c'); self.key('1')
        self.assertEqual(q.status, 'ready')
        self.assertEqual(self.state.money, money)
        self.assertEqual(self.state.narrative.ripples, [])
        self.assertEqual(self.session.ui.mode, 'play')

    def test_every_giver_and_saved_status_uses_authored_entry(self):
        content = self.session._npc_content
        seen = set()
        for lake in DAY_NPCS:
            world = self.world if lake == 'briar' else World(lake)
            state = State.new(world)
            for seed in range(len(DAY_NPCS[lake])):
                state.narrative.schedule_seed = seed
                for minute in (0, 840):
                    state.game_minutes = minute
                    for npc in active_npcs(state, world, content):
                        seen.add(npc.id)
                        state.npcs = (npc,)
                        state.x, state.z = npc.anchor.position
                        session = Session(world, self.path, state, False)
                        for status in ('available', 'active', 'ready', 'completed'):
                            state.narrative.quests[npc.quest_id].status = status
                            session.ui.mode = 'play'
                            session.tick(Keys(pressed=['c']), 0)
                            self.assertEqual(session.conversation.node_id,
                                content.quests[npc.quest_id]['dialogue'][status])
                            session.tick(Keys(pressed=['esc']), 0)
        self.assertEqual(seen, set(content.npcs))

    def test_arrow_and_wasd_choices(self):
        self.key('c'); self.key('c')
        for key in ('down', 'w', 's', 'up'):
            self.key(key)
        self.assertEqual(self.session.conversation.selected, 0)
        self.key('return')
        self.assertEqual(self.state.narrative.quests[self.npc.quest_id].status, 'active')


def dialogue_checks():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(DialogueChecks))
    if not result.wasSuccessful():
        raise AssertionError('Dialogue regressions')


if __name__ == '__main__':
    unittest.main()
