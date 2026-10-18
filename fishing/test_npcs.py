"""Schedule boundaries and real session/save/travel regressions."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .content import load_content
from .game import Keys, Session
from .narrative import DAY_NPCS, QUEST_IDS
from .npcs import active_npcs
from .sim import State
from .world import World


class NPCChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {lake: World(lake) for lake in DAY_NPCS}
        cls.content = load_content()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='briar-npc-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'save.json'
        self.world = self.worlds['briar']
        self.state = State.new(self.world, seed=87)

    def session(self):
        return Session(self.world, self.path, self.state, False)

    def cast(self, minute, lake='briar'):
        self.state.game_minutes = minute
        return active_npcs(self.state, self.worlds[lake], self.content)

    def test_contract_boundaries_and_day_origin(self):
        # Clock starts at 06:00; 840 = 20:00, 1320 = next 04:00.
        for minute, expected in ((0, 'elder_moss'), (839, 'elder_moss'),
                                 (840, 'master_cinder'), (1079, 'master_cinder'),
                                 (1080, 'master_cinder'), (1319, 'master_cinder'),
                                 (1320, 'elder_moss'), (1439, 'elder_moss'),
                                 (1440, 'pip_pebble'), (2280, 'master_cinder'),
                                 (2760, 'pip_pebble'), (2880, 'willow')):
            with self.subTest(minute=minute):
                actors = self.cast(minute)
                self.assertEqual([a.id for a in actors], ['grandmother_whiskers', expected])
                self.assertEqual(self.state.narrative.schedule_day_by_lake['briar'], minute // 1440)

    def test_pool_order_saved_seed_and_cedar_all_night(self):
        for seed in (0, -17, 999):
            self.state.narrative.schedule_seed = seed
            for lake, pool in DAY_NPCS.items():
                for day in range(12):
                    for minute in ((0, 840, 1080, 1320) if lake == 'cedar' else (0, 1320)):
                        self.assertEqual(self.cast(day * 1440 + minute, lake)[1].id,
                                         pool[(seed + day) % len(pool)])
        self.assertEqual(self.state.narrative.schedule_seed, 999)

    def test_only_active_lake_actors_and_permanent_host_positions(self):
        for lake, host, anchor in (('briar', 'grandmother_whiskers', 'briar:landing'),
                                  ('cedar', 'doc_barnaby', 'cedar:docs_marina_dock')):
            for minute in (0, 840, 1080, 1320, 1440, 8000):
                actors = self.cast(minute, lake)
                self.assertEqual(len(actors), 2)
                self.assertEqual((actors[0].id, actors[0].anchor.id), (host, anchor))
                self.assertEqual(sum(a.permanent for a in actors), 1)
                self.assertTrue(all(a.anchor.lake_id == lake for a in actors))

    def test_session_tick_uses_effective_time_and_freezes(self):
        session = self.session()
        session.ui.mode = 'play'
        self.state.game_minutes = 839
        self.state.time_scale = 1
        session.tick(Keys(), 1)
        self.assertEqual(self.state.npcs[1].id, 'master_cinder')
        self.state.game_minutes = 1319
        session.ui.mode = 'pause'
        session.tick(Keys(), 12)
        self.assertEqual(self.state.game_minutes, 1319)
        self.assertEqual(self.state.npcs[1].id, 'master_cinder')
        session.ui.mode = 'play'
        self.state.time_scale = 12
        session.tick(Keys(), 1)
        self.assertEqual(self.state.game_minutes, 1331)
        self.assertEqual(self.state.npcs[1].id, 'elder_moss')
        self.state.game_minutes = 1439
        session.tick(Keys(), 1)
        self.assertEqual(self.state.npcs[1].id, 'pip_pebble')

    def test_save_reload_and_offline_refresh_do_not_grant_progress(self):
        self.state.narrative.schedule_seed = -17
        self.state.narrative.quests[QUEST_IDS[2]].status = 'active'
        self.state.narrative.quests[QUEST_IDS[2]].progress = {'elapsed': 12}
        session = self.session()
        self.state.game_minutes = 839
        session.save()
        expected_quests = deepcopy(self.state.narrative.quests)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.narrative.day_npc_by_lake['briar'], 'silas')
        with patch('fishing.sim.time.time', return_value=loaded.stamp + 3 * 1440 + 1):
            loaded.catch_up()
        new = Session(self.world, self.path, loaded, True)
        self.assertEqual(loaded.game_minutes, 5160)
        self.assertEqual(loaded.npcs[1].id, 'master_cinder')
        self.assertEqual(loaded.narrative.day_npc_by_lake['briar'], 'willow')
        self.assertEqual(loaded.narrative.schedule_day_by_lake['briar'], 3)
        self.assertEqual(loaded.narrative.quests, expected_quests)
        self.assertEqual(loaded.narrative.active_play_game_minutes, 0)
        self.assertEqual(loaded.narrative.ripples, [])
        new.save()
        again = State.load(self.path, self.world)
        Session(self.world, self.path, again, True)
        self.assertEqual(again.npcs, loaded.npcs)
        self.assertEqual(again.narrative.schedule_seed, -17)
        self.assertNotIn('npcs', again.to_json())

    def test_lake_travel_skips_offscreen_days_without_loading_extra_cast(self):
        session = self.session()
        self.assertIsNone(self.state.narrative.day_npc_by_lake['cedar'])
        self.assertIsNone(session.change_lake('cedar'))
        self.assertEqual([a.id for a in self.state.npcs], ['doc_barnaby', 'captain_maeve'])
        self.state.game_minutes = 3 * 1440
        session._refresh_npcs()
        self.assertEqual(self.state.narrative.schedule_day_by_lake['briar'], 0)
        self.assertIsNone(session.change_lake('briar'))
        self.assertEqual([a.id for a in self.state.npcs], ['grandmother_whiskers', 'silas'])
        self.assertEqual(self.state.narrative.schedule_day_by_lake['briar'], 3)
        self.assertIsNone(session.change_lake('cedar'))
        self.assertEqual(self.state.npcs[1].id, 'dr_alder')
        self.assertEqual(self.state.narrative.schedule_seed, 0)
        self.assertTrue(all(a.anchor.lake_id == 'cedar' for a in self.state.npcs))

    def test_legacy_missing_seed_initializes_before_first_selection(self):
        for missing in ('seed', 'ledger'):
            raw = self.state.to_json()
            if missing == 'ledger':
                del raw['narrative_v1']
            else:
                del raw['narrative_v1']['schedule_seed']
            self.path.write_text(json.dumps(raw))
            loaded = State.load(self.path, self.world)
            session = Session(self.world, self.path, loaded, True)
            self.assertEqual(loaded.narrative.schedule_seed, 0)
            self.assertEqual(loaded.npcs[1].id, 'elder_moss')
            session.save()
            self.assertEqual(json.loads(self.path.read_text())['narrative_v1']['schedule_seed'], 0)

    def test_schedule_does_not_consume_rng_or_change_fishing(self):
        before = self.state.to_json()
        session = self.session()
        for minute in (840, 1320, 1440, 2880):
            self.state.game_minutes = minute
            session._refresh_npcs()
        after = self.state.to_json()
        for key in before:
            if key not in ('stamp', 'game_minutes', 'narrative_v1'):
                self.assertEqual(before[key], after[key], key)
        for lake in DAY_NPCS:
            self.world = self.worlds[lake]
            self.state = State.new(self.world, seed=87)
            session = self.session()
            session.ui.mode = 'play'
            session._open_e()
            self.assertEqual(session.ui.mode, 'shop')


def npc_checks():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(NPCChecks))
    if not result.wasSuccessful():
        raise AssertionError('NPC schedule regressions')


if __name__ == '__main__':
    unittest.main()
