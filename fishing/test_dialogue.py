"""Real input/session coverage for optional conversations and simulation."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .platform import SCAN
from .dialogue import Conversation, HAIL_SPEED_MPS, nearby_npc
from .game import Keys, Session
from .sim import Catch, State
from .npcs import active_npcs
from .narrative import DAY_NPCS
from .quests import chain as quest_chain
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

    def test_bot_proximity_cue_is_nonblocking_once_per_npc_and_persisted(self):
        key = f"npc:{self.npc.id}"
        self.state.speed = HAIL_SPEED_MPS
        self.key(dt=0)
        self.assertNotIn(key, self.state.narrative.bot_reactions)

        before = (self.state.money, list(self.state.narrative.ripples),
                  [quest.status for quest in self.state.narrative.quests.values()],
                  [line.to_json() for line in self.state.lines],
                  [catch.to_json() for catch in self.state.well])
        self.state.speed = 0
        self.key(dt=0)
        note = f"Bot: His brass ears turn toward {self.npc.name}."
        self.assertEqual(self.state.narrative.bot_reactions[key], note)
        self.assertEqual(self.state.narrative.bot_journal[-1], note)
        self.assertEqual([toast[0] for toast in self.state.toasts].count(note), 1)
        self.key(dt=0)
        self.assertEqual([toast[0] for toast in self.state.toasts].count(note), 1)
        after = (self.state.money, list(self.state.narrative.ripples),
                 [quest.status for quest in self.state.narrative.quests.values()],
                 [line.to_json() for line in self.state.lines],
                 [catch.to_json() for catch in self.state.well])
        self.assertEqual(after, before)

        self.session.save()
        restored = State.load(self.path, self.world)
        resumed = Session(self.world, self.path, restored, True)
        resumed.ui.mode = 'play'
        resumed.tick(Keys(), 0)
        self.assertEqual(restored.narrative.bot_reactions[key], note)
        self.assertEqual(restored.narrative.bot_journal[-1], note)
        self.assertEqual([toast[0] for toast in restored.toasts].count(note), 0)

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
            drive.assert_not_called()
        self.key('tab')
        with patch.object(self.state, 'drive') as drive:
            self.key('w', dt=.1)
            self.assertGreater(drive.call_args.args[1], 0)
        self.state._park(self.world)
        self.key('e'); self.assertEqual(self.session.ui.mode, 'shop')

    def test_dialogue_pauses_clock_lines_and_bot_without_driving(self):
        self.key('c')
        before = self.state.game_minutes
        with patch.object(self.state, 'drive', wraps=self.state.drive) as drive, patch('fishing.game.tick_bot') as bot:
            bot.return_value = None
            self.session.tick(Keys(held=['w', 'a']), 2)
            drive.assert_not_called()
            bot.assert_not_called()
        self.assertEqual(self.state.game_minutes, before)
        self.assertEqual(self.state.narrative.quests[self.npc.quest_id].progress, {})

    def test_ready_wait_does_not_pay_until_explicit_turn_in(self):
        self.key('c')
        self.state.game_minutes = 840
        self.session._simulate(Keys(), 0)
        self.assertEqual(self.session.ui.mode, 'play')
        self.state.game_minutes = 0
        self.session._refresh_npcs()
        quest_id = self.npc.quest_id
        q = self.state.narrative.quests[quest_id]
        q.status = 'ready'
        money = self.state.money
        reward = self.session._npc_content.rewards[
            self.session._npc_content.quests[quest_id]['reward_id']]
        self.key('c'); self.key('2')
        self.assertEqual(q.status, 'ready')
        self.assertEqual(self.state.money, money)
        self.assertNotIn(quest_id, self.state.narrative.reward_claims)
        self.key('c')  # Acknowledge the authored "come back" line.
        self.assertEqual(self.session.ui.mode, 'play')
        self.key('c'); self.key('1')
        self.assertEqual(q.status, 'completed')
        self.assertEqual(self.state.money, round(money + reward['cash'], 2))

    def test_turn_in_is_idempotent_and_preserves_a_full_starter_livewell(self):
        content = self.session._npc_content
        quest_id = self.npc.quest_id
        quest = content.quests[quest_id]
        reward = content.rewards[quest['reward_id']]
        progress = self.state.narrative.quests[quest_id]
        progress.status = 'ready'
        catch = Catch('bluegill', 0.5, 0.8, 2, 'flats', 'worm', 7)
        self.state.well = [catch for _ in range(int(self.state.well_cap() / catch.weight))]
        self.assertEqual(self.state.well_load(), self.state.well_cap())
        well_before = [item.to_json() for item in self.state.well]
        money_before = self.state.money
        earned_before = self.state.earned
        spent_before = self.state.spent

        self.key('c')
        conversation = self.session.conversation
        ready_node = conversation.node_id
        self.key('1')

        self.assertEqual(progress.status, 'completed')
        self.assertIn(quest_id, self.state.narrative.reward_claims)
        reaction_key = f"quest:{quest_id}"
        reaction_note = "Bot: He gives a small approving brass click."
        self.assertEqual(self.state.narrative.bot_reactions[reaction_key], reaction_note)
        self.assertEqual(self.state.narrative.bot_journal[-1], reaction_note)
        self.assertEqual([toast[0] for toast in self.state.toasts].count(reaction_note), 1)
        self.assertEqual(self.state.money, round(money_before + reward['cash'], 2))
        self.assertEqual(self.state.earned, earned_before)
        self.assertEqual(self.state.spent, spent_before)
        self.assertEqual([item.to_json() for item in self.state.well], well_before)
        self.assertEqual(self.state.well_load(), self.state.well_cap())
        ripple_id = reward['ripple_id']
        if ripple_id is None:
            self.assertNotIn(None, self.state.narrative.ripples)
        else:
            self.assertIn(ripple_id, self.state.narrative.ripples)

        # A stale ready conversation cannot pay the completed quest again.
        paid_money = self.state.money
        conversation.node_id = ready_node
        self.assertFalse(conversation.advance(self.state, content))
        self.assertEqual(self.state.money, paid_money)
        if ripple_id is None:
            self.assertNotIn(None, self.state.narrative.ripples)
        else:
            self.assertEqual(self.state.narrative.ripples.count(ripple_id), 1)

        self.session.save()
        restored = State.load(self.path, self.world)
        self.assertEqual(restored.money, paid_money)
        self.assertEqual(restored.earned, earned_before)
        self.assertEqual(restored.well_load(), restored.well_cap())
        self.assertEqual([item.to_json() for item in restored.well], well_before)
        self.assertEqual(restored.narrative.quests[quest_id].status, 'completed')
        self.assertIn(quest_id, restored.narrative.reward_claims)
        self.assertEqual(restored.narrative.bot_reactions[reaction_key], reaction_note)
        self.assertEqual(restored.narrative.bot_journal[-1], reaction_note)
        if ripple_id is not None:
            self.assertIn(ripple_id, restored.narrative.ripples)

    def test_turn_in_requires_the_same_present_giver(self):
        content = self.session._npc_content
        quest_id = self.npc.quest_id
        self.state.narrative.quests[quest_id].status = 'ready'
        conversation = Conversation.start(self.npc, self.state, content)
        money = self.state.money
        other = self.state.npcs[0]
        self.state.x, self.state.z = other.anchor.position

        self.assertFalse(conversation.advance(self.state, content))
        self.assertEqual(self.state.narrative.quests[quest_id].status, 'ready')
        self.assertEqual(self.state.money, money)
        self.assertNotIn(quest_id, self.state.narrative.reward_claims)

    def test_cash_only_turn_in_does_not_create_a_ripple(self):
        content = self.session._npc_content
        giver = next(npc for npc in self.state.npcs
                     if content.rewards[content.quests[npc.quest_id]['reward_id']]['ripple_id'] is None)
        self.state.x, self.state.z = giver.anchor.position
        quest_id = giver.quest_id
        reward = content.rewards[content.quests[quest_id]['reward_id']]
        self.state.narrative.quests[quest_id].status = 'ready'
        money = self.state.money
        ripples = list(self.state.narrative.ripples)
        conversation = Conversation.start(giver, self.state, content)
        ready_node = conversation.node_id

        self.assertTrue(conversation.advance(self.state, content))
        self.assertEqual(self.state.money, round(money + reward['cash'], 2))
        self.assertEqual(self.state.narrative.ripples, ripples)
        conversation.node_id = ready_node
        self.assertFalse(conversation.advance(self.state, content))
        self.assertEqual(self.state.money, round(money + reward['cash'], 2))
        self.assertEqual(self.state.narrative.ripples, ripples)

    def test_every_giver_and_saved_status_uses_authored_entry(self):
        content = self.session._npc_content
        seen, met = set(), set()
        for lake in DAY_NPCS:
            world = self.world if lake == 'briar' else World(lake)
            state = State.new(world)
            # Any three days bring every encounter (02 §11.3), day and night.
            for day in range(3):
                for minute in (day * 1440, day * 1440 + 840):
                    state.game_minutes = minute
                    for npc in active_npcs(state, world, content):
                        seen.add(npc.id)
                        state.npcs = (npc,)
                        state.x, state.z = npc.anchor.position
                        session = Session(world, self.path, state, False)
                        if npc.quest_id is None:
                            # A V1.0 cat (V1-32) greets and offers quest A; the rest of the cast waves.
                            session.ui.mode = 'play'
                            session.tick(Keys(pressed=['c']), 0)
                            chain = quest_chain(content, npc.id)
                            if chain:
                                self.assertEqual(session.conversation.quest_id, chain[0])
                                session.tick(Keys(pressed=['esc']), 0)
                            else:
                                self.assertIsNone(session.conversation)
                                self.assertIn(npc.name + ' waves', state.toasts[-1][0])
                            continue
                        for status in ('available', 'active', 'ready', 'completed'):
                            state.narrative.quests[npc.quest_id].status = status
                            # A turn-in today: the return line answers it (a greeting from tomorrow).
                            state.narrative.quests[npc.quest_id].completed_game_minute = state.game_minutes
                            session.ui.mode = 'play'
                            session.tick(Keys(pressed=['c']), 0)
                            entry = content.quests[npc.quest_id]['dialogue'][status]
                            conversation = session.conversation
                            if npc.id not in met and 'first' in content.cats[npc.id]['greetings']:
                                # Doc's `first` line (05 §4.2) opens the first meeting, then his entry.
                                self.assertEqual(conversation.node_id, f'{npc.id}:greeting')
                                self.assertEqual(conversation.node(content)['next'], entry)
                            else:
                                self.assertEqual(conversation.node_id, entry)
                            met.add(npc.id)
                            session.tick(Keys(pressed=['esc']), 0)
        self.assertEqual(seen & set(content.npcs), set(content.npcs))

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
