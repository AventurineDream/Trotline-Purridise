"""Contract and malformed-authoring regressions for the narrative content API."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .content import CONTENT_PATH, ContentError, load_content, validate_content
from .narrative import QUEST_IDS, RIPPLE_BY_QUEST, DAY_NPCS


class ContentChecks(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(CONTENT_PATH.read_text())

    def invalid(self, edit, expected):
        raw = deepcopy(self.raw)
        edit(raw)
        with self.assertRaises(ContentError) as caught:
            validate_content(raw, source="authoring.json")
        message = str(caught.exception)
        self.assertIn("authoring.json:", message)
        self.assertIn(expected, message)

    def test_complete_canonical_roster_and_rewards(self):
        c = load_content()
        # The V1.0 quests (content_v2, marked by `kind`) sit beside the twelve V3 ones.
        self.assertEqual({qid for qid, q in c.quests.items() if 'kind' not in q}, set(QUEST_IDS))
        self.assertEqual(len(c.npcs), 12)
        self.assertEqual(sum(n['presence'] == 'permanent' for n in c.npcs.values()), 2)
        rotating = {n['id'] for n in c.npcs.values() if n['presence'] != 'permanent'}
        self.assertEqual(rotating, set(DAY_NPCS['briar'] + DAY_NPCS['cedar']) | {'master_cinder'})
        cash = [60, 90, 45, 45, 50, 55, 40, 65, 50, 45, 60, 50]
        for qid, amount in zip(QUEST_IDS, cash):
            q = c.quests[qid]
            reward = c.rewards[q['reward_id']]
            self.assertEqual(reward['cash'], amount, qid)
            self.assertEqual(reward['ripple_id'], RIPPLE_BY_QUEST.get(qid), qid)
            self.assertEqual(q['prerequisites'], [])
        self.assertEqual(len({r['ripple_id'] for r in c.rewards.values() if r['ripple_id']}), 10)
        self.assertEqual(c.npcs['doc_barnaby']['anchor_id'], 'cedar:docs_marina_dock')
        self.assertEqual(c.npcs['quill']['anchor_id'], 'cedar:flats')
        self.assertEqual(c.npcs['patch']['anchor_id'], 'cedar:lilies')

    def test_objectives_match_normative_contract(self):
        c = load_content()
        objectives = [c.quests[qid]['objective'] for qid in QUEST_IDS]
        self.assertTrue(all(o['after_acceptance'] for o in objectives))
        expected = {
            0: ('line_scout', 'briar:lilies', 'std', 12, 'worm'),
            1: ('line_check', 'cedar:rocks', 'std', 12, 'minnow'),
            4: ('line_check', 'briar:deep', 'std', 12, 'shad'),
            8: ('line_check', 'cedar:inlet', 'std', 12, 'liver'),
            10: ('line_scout_check', 'cedar:deep', 'prem', 18, 'shad'),
        }
        for i, values in expected.items():
            o = objectives[i]
            self.assertEqual(tuple(o[k] for k in ('type','zone_id','tier_id','hook_count','bait_id')), values)
            self.assertTrue(o['set_after_acceptance'])
        for i in (0, 10):
            self.assertEqual(objectives[i]['scout_range_lt_m'], 140)
        for i in (1, 4, 8, 10):
            self.assertEqual(objectives[i]['active_soak_game_minutes'], 60)
        self.assertEqual(objectives[4]['set_window'], [1200, 240])
        self.assertTrue(objectives[10]['scout_before_check'])
        for i, zone in ((2, 'briar:cypress'), (6, 'briar:inlet')):
            o = objectives[i]
            self.assertEqual((o['type'], o['zone_id'], o['continuous_game_minutes']), ('anchor_idle', zone, 120))
            self.assertTrue(o['reset_on_interruption'])
        self.assertEqual(objectives[3]['type'], 'scout_report')
        self.assertEqual(objectives[3]['zone_id'], 'briar:flats')
        self.assertFalse(objectives[3]['exact_depth_required'])
        sunrise = objectives[5]
        self.assertEqual((sunrise['type'], sunrise['species_id'], sunrise['zone_id'], sunrise['bait_id']),
                         ('fish_livewell','golden_shiner','briar:lilies','worm'))
        self.assertEqual(sunrise['entry_window'], [300, 480])
        self.assertEqual(sunrise['window_field'], 'entry_game_minute')
        self.assertFalse(sunrise['set_after_acceptance'])
        self.assertFalse(sunrise['consume_fish'])
        distance = objectives[7]
        self.assertEqual((distance['type'],distance['zone_id'],distance['distance_m']), ('travel_distance','cedar:open',300))
        self.assertEqual(distance['measurement'], 'in_zone_path')
        self.assertEqual(distance['propulsion'], ['motor','sail','oar'])
        self.assertTrue(distance['player_controlled'])
        self.assertFalse(distance['count_tow'])
        self.assertEqual(objectives[9]['zone_ids'], ['cedar:rocks','cedar:lilies','cedar:open'])
        self.assertFalse(objectives[9]['ordered'])
        voyage = objectives[11]
        self.assertEqual(voyage['zone_ids'], ['cedar:landing','cedar:lilies','cedar:landing'])
        self.assertTrue(voyage['ordered'])
        self.assertEqual(voyage['movement_cause'], 'boat')
        self.assertTrue(voyage['player_controlled'])

    def test_authored_dialogue_has_every_branch_and_unique_choices(self):
        c = load_content()
        self.assertEqual(sum(node['quest_id'] in QUEST_IDS for node in c.dialogue.values()), 108)
        for qid in QUEST_IDS:
            for stage in ('greeting','offer','accept','decline','progress','ready','ready_wait','completion','return'):
                node = c.dialogue[qid + ':dialogue:' + stage]
                self.assertTrue(node['text'].strip())
                self.assertEqual(node['quest_id'], qid)
            offer = c.dialogue[qid+':dialogue:offer']
            self.assertEqual([choice['action'] for choice in offer['choices']], ['accept','decline'])
            self.assertEqual(c.quests[qid]['dialogue']['completed'], qid+':dialogue:return')
        text = c.dialogue[QUEST_IDS[5]+':dialogue:offer']['text']
        self.assertIn('livewell between 05:00 and 08:00', text)
        self.assertIn('when it took the hook does not matter', text)

    def test_missing_fields_and_duplicate_ids(self):
        for group, field in [('npcs','name'),('quests','objective'),('rewards','cash'),('dialogue','text')]:
            with self.subTest(group=group):
                self.invalid(lambda d: d[group][0].pop(field), 'missing required field')
                self.invalid(lambda d: d[group].append(deepcopy(d[group][0])), 'duplicate ID')
        self.invalid(lambda d: d['dialogue'][1]['choices'][1].update(id=d['dialogue'][1]['choices'][0]['id']), 'duplicate ID')
        self.invalid(lambda d: d['quests'].pop(), 'canonical IDs differ')

    def test_unknown_references_and_lake_mismatches(self):
        cases = [
            (lambda d: d['quests'][0].update(giver_id='missing'), '.giver_id'),
            (lambda d: d['quests'][0].update(reward_id='missing'), '.reward_id'),
            (lambda d: d['quests'][0].update(lake_id='unknown'), '.lake_id'),
            (lambda d: d['npcs'][0].update(anchor_id='briar:docs_marina_dock'), '.anchor_id'),
            (lambda d: d['quests'][0]['objective'].update(zone_id='cedar:lilies'), 'location must belong'),
            (lambda d: d['quests'][0]['objective'].update(zone_id='briar:unknown'), '.zone_id'),
            (lambda d: d['quests'][0]['objective'].update(bait_id='new_bait'), '.bait_id'),
            (lambda d: d['quests'][5]['objective'].update(species_id='new_fish'), '.species_id'),
            (lambda d: d['quests'][0]['objective'].update(tier_id='new_gear'), '.tier_id'),
            (lambda d: d['dialogue'][0].update(next='missing'), '.target'),
            (lambda d: d['dialogue'][0].update(next=d['dialogue'][9]['id']), 'another quest'),
            (lambda d: d['dialogue'][0].update(speaker_id='doc_barnaby'), 'speaker is not'),
        ]
        for edit, expected in cases:
            with self.subTest(expected=expected):
                self.invalid(edit, expected)

    def test_invalid_types_conditions_and_unsupported_mechanics(self):
        cases = [
            (lambda d: d['quests'][0]['objective'].update(type='thermal_sensor'), '.type'),
            (lambda d: d['quests'][0]['objective'].update(temperature_c=20), 'unknown field'),
            (lambda d: d['quests'][0]['objective'].update(hook_count=18), 'does not match'),
            (lambda d: d['quests'][0]['objective'].update(hook_count=True), 'positive integer'),
            (lambda d: d['quests'][1]['objective'].update(active_soak_game_minutes=float('nan')), 'finite positive'),
            (lambda d: d['quests'][1]['objective'].update(active_soak_game_minutes=-1), 'finite positive'),
            (lambda d: d['quests'][1]['objective'].update(active_soak_game_minutes=10**500), 'finite positive'),
            (lambda d: d['quests'][4]['objective'].update(set_window=[1440,0]), 'clock minutes'),
            (lambda d: d['quests'][5]['objective'].update(window_field='catch_game_minute'), 'entry_game_minute'),
            (lambda d: d['quests'][5]['objective'].update(consume_fish=True), 'expected False'),
            (lambda d: d['quests'][11]['objective'].update(movement_cause='tow'), "expected 'boat'"),
            (lambda d: d['rewards'][0].update(ripple_id='ripple_01'), 'hosts award cash only'),
            (lambda d: d['rewards'][2].update(ripple_id='ripple_02'), 'canonical Ripple'),
            (lambda d: d['rewards'][0].update(item_id='new_lure'), 'unknown field'),
            (lambda d: d['quests'][1].update(reward_id=d['quests'][0]['reward_id']), 'shared'),
            (lambda d: d['quests'][0].update(prerequisites=[QUEST_IDS[1]]), 'expected []'),
            (lambda d: d.update(schema_version=True), 'expected 1'),
        ]
        for edit, expected in cases:
            with self.subTest(expected=expected):
                self.invalid(edit, expected)

    def test_dialogue_graph_must_be_usable(self):
        self.invalid(lambda d: d['dialogue'][0].update(next=d['dialogue'][0]['id']), 'cycle')
        self.invalid(lambda d: d['dialogue'][1]['choices'][0].update(action='teleport'), '.action')
        self.invalid(lambda d: d['dialogue'][1]['choices'][0].update(target='missing'), '.target')
        self.invalid(lambda d: d['quests'][0]['dialogue'].update(active=d['quests'][0]['dialogue']['available']), 'not valid')
        self.invalid(lambda d: d['dialogue'][0].update(choices=[]), 'exactly one')
        self.invalid(lambda d: d['dialogue'].append(dict(id='orphan',quest_id=QUEST_IDS[0],speaker_id='grandmother_whiskers',text='Lost.',next=None)), 'unreachable')

    def test_malformed_structures_raise_content_error(self):
        for group in ('npcs','quests','rewards','dialogue'):
            for bad in (None, 42, {}, ['bad']):
                with self.subTest(group=group, bad=bad):
                    self.invalid(lambda d: d.update({group:bad}), group)
        for field in ('giver_id','reward_id','lake_id'):
            self.invalid(lambda d: d['quests'][0].update({field:[]}), field)
        self.invalid(lambda d: d['quests'][0].update(objective=[]), 'objective')
        self.invalid(lambda d: d['quests'][0]['objective'].update(type=[]), '.type')
        self.invalid(lambda d: d['dialogue'][0].update(next=[]), '.target')
        self.invalid(lambda d: d['dialogue'][1].update(choices=[None]), 'expected an object')
        self.invalid(lambda d: d['dialogue'][1]['choices'][0].update(action=[]), '.action')
        self.invalid(lambda d: d['dialogue'][0].update(quest_id=[]), '.quest_id')
        self.invalid(lambda d: d['quests'][0].update(dialogue={'available':[]}), '.dialogue')

    def test_file_errors_and_duplicate_json_keys_include_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'authored.json'
            for text in ('{', '{"schema_version":1,"schema_version":1}'):
                path.write_text(text)
                with self.assertRaises(ContentError) as caught:
                    load_content(path)
                self.assertIn(str(path), str(caught.exception))
            path.unlink()
            with self.assertRaises(ContentError):
                load_content(path)

    def test_loads_are_isolated_and_independent_of_working_directory(self):
        first = load_content()
        first.npcs['elder_moss']['name'] = 'Changed locally'
        self.assertEqual(load_content().npcs['elder_moss']['name'], 'Elder Moss')
        self.assertTrue(CONTENT_PATH.is_absolute())


def content_checks():
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ContentChecks))
    if not result.wasSuccessful():
        raise AssertionError('narrative content regressions')


if __name__ == '__main__':
    unittest.main()
