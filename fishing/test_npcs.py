"""The 52-cat daily schedule (V1-30): coverage, pins, travelers, determinism and V3 migration."""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .anchors import ANCHORS
from .content import load_content, load_content_v2
from .game import Keys, Session
from .lakes import LAKES
from .narrative import DAY_NPCS, QUEST_IDS
from .npcs import (DAY_ENCOUNTERS, SATURDAY, active_npcs, cast, day_encounters, night_encounter, pinned,
                   pounce_lake, present_ids)
from .sim import State
from .world import World

ROSTER = load_content_v2().roster


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

    def cast_at(self, minute, lake='briar'):
        self.state.game_minutes = minute
        return active_npcs(self.state, self.worlds[lake], self.content)

    def test_day_night_and_dawn_boundaries(self):
        # The clock starts at 06:00: 840 = 20:00, 1320 = 04:00, 1440 = 06:00 next day.
        seed = self.state.narrative.schedule_seed
        day0 = list(day_encounters(seed, 'briar', 0))
        for minute, expected in ((0, day0), (839, day0), (840, ['master_cinder']), (1319, ['master_cinder']),
                                 (1320, []), (1439, []), (1440, list(day_encounters(seed, 'briar', 1)))):
            with self.subTest(minute=minute):
                ids = [a.id for a in self.cast_at(minute) if a.id != 'pounce']
                self.assertEqual(ids, ['grandmother_whiskers', *expected])
        self.assertEqual(len(day0), DAY_ENCOUNTERS)
        self.assertEqual(len(set(day0)), DAY_ENCOUNTERS)

    def test_cedar_night_alternates_hank_and_luz(self):
        seen = set()
        for day in range(4):
            night = [a.id for a in self.cast_at(day * 1440 + 900, 'cedar')]
            self.assertEqual(night[0], 'doc_barnaby')
            self.assertEqual(len(night), 2)
            seen.add(night[1])
        self.assertEqual(seen, {'hank_mudpaw', 'senora_luz'})

    def test_only_active_lake_actors_and_permanent_host_positions(self):
        for lake, host, anchor in (('briar', 'grandmother_whiskers', 'briar:landing'),
                                   ('cedar', 'doc_barnaby', 'cedar:docs_marina_dock')):
            for minute in (0, 840, 1080, 1320, 1440, 8000):
                actors = self.cast_at(minute, lake)
                self.assertEqual((actors[0].id, actors[0].anchor.id), (host, anchor))
                self.assertEqual(sum(a.permanent for a in actors), 1)
                self.assertTrue(all(a.anchor.lake_id == lake for a in actors))
                # Hail circles never overlap, so the nearest cat is the one you meant.
                for i, a in enumerate(actors):
                    for b in actors[i + 1:]:
                        self.assertGreater(math.dist(a.anchor.position, b.anchor.position), 40.0)

    def test_every_cookout_guest_can_be_hailed_from_a_docked_boat(self):
        # Cookout chats and attend_event need a hail while docked (`at_landing`). Under V1-30's
        # layout the host and the first guest stood at the slip mouth, nearer no docked boat.
        from .boat import BOATS
        from .dialogue import nearby_npc
        longest = max(BOATS, key=lambda boat_id: BOATS[boat_id].length)
        for lake in LAKES:
            world = self.worlds.get(lake) or World(lake)
            state = State.new(world, seed=32)
            state.game_minutes = 6 * 1440 + 11 * 60 + 30  # Sunday 17:30
            state.npcs = active_npcs(state, world, self.content)
            slip, host = world.slip, cast().hosts[lake]
            for boat_id in ('jon', longest):
                hailed = set()
                for yaw in (math.atan2(-slip.ix, -slip.iz), math.atan2(slip.ix, slip.iz)):
                    for a in range(5, int(slip.land_ext * 2) + 1):  # half-metre steps
                        for s in range(-int(slip.half_w * 2), int(slip.half_w * 2) + 1):
                            state.x, state.z = slip.world(a / 2, s / 2)
                            if state.slip_status(world) == 'docked' and world.hull_clear(state.x, state.z, yaw,
                                                                                         boat_id):
                                hailed.add(nearby_npc(state).id)
                with self.subTest(lake=lake, boat=boat_id):
                    # Every cat from the jon; the host even from the longest hull, which can't go deep.
                    self.assertEqual(len(state.npcs), len(present_ids(state, world, self.content)))
                    if boat_id == 'jon':
                        self.assertEqual(hailed, {npc.id for npc in state.npcs})
                    self.assertIn(host, hailed)

    def test_quests_pin_their_cats_with_an_extra_slot(self):
        seed = self.state.narrative.schedule_seed
        day = next(d for d in range(7) if 'willow' not in day_encounters(seed, 'briar', d))
        minute = day * 1440 + 120
        self.assertNotIn('willow', [a.id for a in self.cast_at(minute)])
        # A quest waiting to be turned in needs its giver present.
        self.state.narrative.quests['q06_unrepeatable_sunrise'].status = 'ready'
        ids = [a.id for a in self.cast_at(minute) if a.id != 'pounce']
        self.assertEqual(ids[-1], 'willow')
        self.assertEqual(len(ids), 1 + DAY_ENCOUNTERS + 1)
        # A night cat is pinned to its own night, never into the day.
        self.state.narrative.quests['q05_moonlight_trotlines'].status = 'ready'
        self.assertNotIn('master_cinder', [a.id for a in self.cast_at(minute)])
        self.assertIn('master_cinder', [a.id for a in self.cast_at(day * 1440 + 900)])
        # An active talk_to step pins its cat; a cat already present takes no extra slot.
        content = deepcopy(self.content)
        quest = content.quests['q03_unstrung_line']
        quest['objective'] = [quest['objective'], {'type': 'talk_to', 'npc_id': 'old_gus'}]
        self.state.narrative.quests['q03_unstrung_line'].status = 'active'
        self.assertIn('old_gus', pinned(self.state, content))
        self.state.game_minutes = minute
        ids = present_ids(self.state, self.world, content)
        self.assertIn('old_gus', ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.state.narrative.quests['q06_unrepeatable_sunrise'].status = 'completed'
        self.assertNotIn('willow', pinned(self.state, self.content))

    def test_travelers_keep_their_own_rules(self):
        lakes = ('briar', 'cedar')
        for day in range(14):
            visits = [lake for lake in lakes
                      if 'pounce' in [a.id for a in self.cast_at(day * 1440 + 180, lake)]]
            self.assertEqual(visits, [pounce_lake(self.state, day)])
            for minute in (day * 1440 + 60, day * 1440 + 600):  # 07:00 and 16:00
                self.assertNotIn('pounce', [a.id for a in self.cast_at(minute, visits[0])])
            saturday = day % 7 == SATURDAY
            for lake in lakes:
                at_ten = [a.id for a in self.cast_at(day * 1440 + 240, lake)]
                self.assertEqual('thistle' in at_ten, saturday)
                self.assertNotIn('thistle', [a.id for a in self.cast_at(day * 1440 + 720, lake)])
        # Pounce only visits unlocked lakes: Flathead opens after chapter 2.
        self.assertTrue(all(pounce_lake(self.state, day) in lakes for day in range(60)))
        self.state.v2['story']['chapter'] = 5
        self.assertEqual({pounce_lake(self.state, day) for day in range(60)}, set(LAKES))

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
        self.assertEqual([a.id for a in self.state.npcs], ['grandmother_whiskers'])
        self.state.game_minutes = 1439
        session.tick(Keys(), 1)
        self.assertEqual(self.state.npcs[1].id, day_encounters(self.state.narrative.schedule_seed, 'briar', 1)[0])

    def test_quest_progress_refreshes_the_cast(self):
        session = self.session()
        session.ui.mode = 'play'
        seed = self.state.narrative.schedule_seed
        day = next(d for d in range(7) if 'silas' not in day_encounters(seed, 'briar', d))
        self.state.game_minutes = day * 1440 + 120
        session.tick(Keys(), 0)
        self.assertNotIn('silas', [a.id for a in self.state.npcs])
        self.state.narrative.quests['q07_art_of_the_nap'].status = 'ready'
        session.tick(Keys(), 0)
        self.assertIn('silas', [a.id for a in self.state.npcs])

    def test_save_reload_and_offline_refresh_are_deterministic_and_grant_nothing(self):
        self.state.narrative.schedule_seed = -17
        self.state.narrative.quests[QUEST_IDS[2]].status = 'active'
        self.state.narrative.quests[QUEST_IDS[2]].progress = {'elapsed': 12}
        session = self.session()
        self.state.game_minutes = 839
        session.save()
        expected_quests = deepcopy(self.state.narrative.quests)
        before = self.state.npcs
        loaded = State.load(self.path, self.world)
        Session(self.world, self.path, loaded, True)
        self.assertEqual(loaded.npcs, before)
        with patch('fishing.sim.time.time', return_value=loaded.stamp + 3 * 1440 + 1):
            loaded.catch_up()
        new = Session(self.world, self.path, loaded, True)
        self.assertEqual(loaded.game_minutes, 5160)
        self.assertEqual(loaded.npcs[1].id, 'master_cinder')
        self.assertEqual(loaded.narrative.quests, expected_quests)
        self.assertEqual(loaded.narrative.active_play_game_minutes, 0)
        self.assertEqual(loaded.narrative.ripples, [])
        # The schedule writes nothing to the ledger.
        self.assertEqual(loaded.narrative.day_npc_by_lake, {'briar': None, 'cedar': None})
        new.save()
        again = State.load(self.path, self.world)
        Session(self.world, self.path, again, True)
        self.assertEqual(again.npcs, loaded.npcs)
        self.assertEqual(again.narrative.schedule_seed, -17)
        self.assertNotIn('npcs', again.to_json())

    def test_lake_switches_do_not_change_either_lakes_schedule(self):
        session = self.session()
        briar_first = [a.id for a in self.state.npcs]
        self.assertIsNone(session.change_lake('cedar'))
        cedar = [a.id for a in self.state.npcs]
        self.assertEqual(cedar[0], 'doc_barnaby')
        self.assertEqual(cedar[1:1 + DAY_ENCOUNTERS], list(day_encounters(0, 'cedar', 0)))
        self.assertIsNone(session.change_lake('briar'))
        self.assertEqual([a.id for a in self.state.npcs], briar_first)
        self.state.game_minutes = 3 * 1440
        session._refresh_npcs()
        later = [a.id for a in self.state.npcs]
        self.assertIsNone(session.change_lake('cedar'))
        self.assertIsNone(session.change_lake('briar'))
        self.assertEqual([a.id for a in self.state.npcs], later)
        self.assertTrue(all(a.anchor.lake_id == 'briar' for a in self.state.npcs))

    def test_v3_day_selection_migrates_for_its_own_day(self):
        """A V3 save chose one day cat per lake. On load it stays for the rest of that day."""
        seed = 0
        day = next(d for d in range(7) if 'willow' not in day_encounters(seed, 'briar', d))
        raw = self.state.to_json()
        raw['narrative_v1']['schedule_seed'] = seed
        raw['narrative_v1']['day_npc_by_lake'] = {'briar': 'willow', 'cedar': 'not_a_cat'}
        raw['narrative_v1']['schedule_day_by_lake'] = {'briar': day, 'cedar': day}
        raw['game_minutes'] = day * 1440 + 300
        self.path.write_text(json.dumps(raw))
        loaded = State.load(self.path, self.world)
        Session(self.world, self.path, loaded, True)
        self.assertIn('willow', [a.id for a in loaded.npcs])
        loaded.game_minutes = day * 1440 + 900
        self.assertNotIn('willow', [a.id for a in active_npcs(loaded, self.world, self.content)])
        loaded.game_minutes = (day + 1) * 1440 + 300
        self.assertEqual('willow' in [a.id for a in active_npcs(loaded, self.world, self.content)],
                         'willow' in day_encounters(seed, 'briar', day + 1))
        # The unknown Cedar pick is ignored, and the saved fields are kept untouched.
        cedar = active_npcs(loaded, self.worlds['cedar'], self.content)
        self.assertNotIn('not_a_cat', [a.id for a in cedar])
        self.assertEqual(loaded.narrative.to_json()['day_npc_by_lake']['briar'], 'willow')

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
            self.assertEqual(loaded.npcs[1].id, day_encounters(0, 'briar', 0)[0])
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
        self.assertEqual(before['narrative_v1'], after['narrative_v1'])
        for lake in DAY_NPCS:
            self.world = self.worlds[lake]
            self.state = State.new(self.world, seed=87)
            session = self.session()
            session.ui.mode = 'play'
            session._open_e()
            self.assertEqual(session.ui.mode, 'shop')


class ScheduleProperties(unittest.TestCase):
    """Properties of the pure schedule, over many seeds and every lake."""

    def test_every_encounter_appears_in_every_three_day_span_over_10000_seeds(self):
        roster = cast()
        for seed in range(10000):
            for lake in roster.lakes:
                day_pool, night_pool = set(roster.day[lake]), set(roster.night[lake])
                start = seed % 997  # spans across the whole calendar, not just its first week
                days = [day_encounters(seed, lake, d) for d in range(start, start + 5)]
                nights = [night_encounter(seed, lake, d) for d in range(start, start + 5)]
                for d in days:
                    self.assertEqual(len(d), DAY_ENCOUNTERS)
                    self.assertEqual(len(set(d)), DAY_ENCOUNTERS)
                for i in range(3):
                    if set().union(*days[i:i + 3]) != day_pool or set(nights[i:i + 3]) != night_pool:
                        self.fail(f"seed {seed} on {lake} misses an encounter in days {start + i}–{start + i + 2}")

    def test_the_schedule_is_a_pure_function_of_seed_lake_and_day(self):
        from . import npcs
        first = [day_encounters(s, 'cedar', d) for s in (-3, 0, 7) for d in (0, 1, 50)]
        npcs._permutation.cache_clear()
        self.assertEqual([day_encounters(s, 'cedar', d) for s in (-3, 0, 7) for d in (0, 1, 50)], first)
        self.assertNotEqual(day_encounters(0, 'cedar', 0), day_encounters(1, 'cedar', 0))
        self.assertEqual([night_encounter(9, 'briar', d) for d in range(5)], ['master_cinder'] * 5)


class CastData(unittest.TestCase):
    def test_every_cat_has_a_slot_anchor_and_quests(self):
        lakes = {}
        for npc_id, row in ROSTER.items():
            with self.subTest(npc=npc_id):
                if row['role'] == 'traveler':
                    self.assertIsNone(row['anchor'])
                    continue
                anchor = ANCHORS[row['anchor']]
                self.assertEqual(anchor.lake_id, row['lake'])
                lakes.setdefault(row['lake'], []).append(anchor)
                self.assertEqual(anchor.kind, 'dock' if row['role'] == 'host' else 'water')
        # The V3 cast keeps its V3 anchors and quests.
        for row in load_content().npcs.values():
            self.assertEqual(ROSTER[row['id']]['anchor'], row['anchor_id'])
            self.assertEqual(ROSTER[row['id']]['quests'][0], row['quest_id'])
        for lake, anchors in lakes.items():
            self.assertEqual(len(anchors), len(set(anchors)))
            water = [a for a in anchors if a.kind == 'water'] + [ANCHORS[f'{lake}:mail_mooring'],
                                                                 ANCHORS[f'{lake}:tinker_mooring']]
            for i, a in enumerate(water):
                for b in water[i + 1:]:
                    self.assertGreater(math.dist(a.position, b.position), 45.0, (a.id, b.id))
        counts = {lake: (len(cast().day[lake]), len(cast().night[lake])) for lake in cast().lakes}
        self.assertEqual(counts, {'briar': (7, 1), 'cedar': (7, 2), 'flathead': (7, 2), 'crater': (7, 2),
                                  'nebula': (7, 2)})


def npc_checks():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(NPCChecks))
    if not result.wasSuccessful():
        raise AssertionError('NPC schedule regressions')


if __name__ == '__main__':
    unittest.main()
