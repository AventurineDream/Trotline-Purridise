"""Canonical transcription, unchanged legacy data and real-map catchability."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from . import kitchen
from .book import BOOK_SPECIES_IDS, SPECIES_RUMORS
from .content import ContentError, validate_content_v2
from .data import (BAIT_BY_ID, BAIT_MATCH, CONTENT_V2_RAW, LAKE_SPECIES_IDS,
                   SPECIES_BY_ID, ZONE_MATCH, bait_mult, weather_mult, weight_string, zone_mult)
from .game import Session
from .sim import Catch, Hook, SetLine, State
from .specieschecks import validate_catchability
from .world import World

ROOT = Path(__file__).resolve().parents[1]


def _canonical_rows():
    source = (ROOT / 'docs/v1/03-CONTENT-TABLES.md').read_text()
    result = []
    for number, lake in ((3, 'cedar'), (4, 'flathead'), (5, 'crater'), (6, 'nebula')):
        block = source.split(f'### 1.{number} ')[1].split('### 1.')[0].split('## 2.')[0]
        for line in block.splitlines():
            fields = [word.strip() for word in line.strip().strip('|').split('|')]
            if line.startswith('| ') and len(fields) == 13 and fields[3] in ('C', 'U', 'R', 'V'):
                result.append((lake, fields))
    return result


class SpeciesDataChecks(unittest.TestCase):
    def test_tiny_species_never_display_as_zero_weight(self):
        self.assertEqual(weight_string(.005), '0.005 lb')
        self.assertEqual(weight_string(.02), '0.02 lb')
        self.assertEqual(weight_string(2.34), '2.3 lb')
        self.assertEqual(weight_string(0), '0.0 lb')

    def test_galley_picks_never_show_tiny_fish_as_zero_weight(self):
        minnow = Catch('bluntnose_minnow', .015, 1.0, 0.0, 'flats', 'worm', 8.0)
        self.assertEqual(kitchen.pick_label(minnow), f"0.015 lb {SPECIES_BY_ID['bluntnose_minnow'].name}")

    def test_all_108_rows_match_the_canonical_table_and_rumor_attribution(self):
        rows = _canonical_rows()
        self.assertEqual(len(rows), 108)
        authored = {r['id']: r for r in CONTENT_V2_RAW['species.json']['species']}
        self.assertEqual(len(authored), 144)
        self.assertEqual(set(authored), set(BOOK_SPECIES_IDS))
        script = (ROOT / 'docs/v1/05-SCRIPT.md').read_text()
        rumors = {}
        for line in script.split('## 8. Book rumors')[1].split('## 9.')[0].splitlines():
            fields = [word.strip() for word in line.strip().strip('|').split('|')]
            if line.startswith('| ') and len(fields) == 3:
                rumors[fields[0]] = fields[1].strip('"'), fields[2]
        for lake, fields in rows:
            sid, name, folk, tier, band, baits, depth, zones, weight, price, food, tags, shiny = fields
            with self.subTest(species=sid):
                row, fish = authored[sid], SPECIES_BY_ID[sid]
                self.assertEqual((fish.name, fish.folk_name, row['tier'], fish.pref_time), (name, folk, tier, band))
                self.assertEqual(fish.lakes, (lake,))
                self.assertEqual(fish.depth, tuple(float(n) for n in depth.split('–')))
                self.assertEqual((fish.min_lb, fish.max_lb), tuple(float(n) for n in weight.split('–')))
                self.assertEqual(fish.price, 0 if price == '—' else float(price))
                self.assertEqual((fish.food, fish.shiny), (food, shiny))
                self.assertEqual(fish.tags, () if tags == '—' else tuple(t.strip() for t in tags.split(',')))
                self.assertEqual(fish.baits, tuple(baits.split('/')))
                self.assertEqual(fish.zones, tuple(z.strip() for z in zones.split(',')))
                self.assertEqual((SPECIES_RUMORS[sid].text, SPECIES_RUMORS[sid].teller), rumors[sid])
                for index, bait in enumerate(fish.baits):
                    self.assertEqual(bait_mult(bait, sid), 1 if index == 0 else .6)
                for index, zone in enumerate(fish.zones):
                    self.assertEqual(zone_mult(zone, sid), 1 if index == 0 else .7)

    def test_original_36_rows_five_baits_and_habitat_matches_are_unchanged(self):
        baseline = json.loads((ROOT / 'docs/issue-52/baseline.json').read_text())
        authored = {r['id']: r for r in CONTENT_V2_RAW['species.json']['species']}
        for sid, expected in baseline['species'].items():
            digest = hashlib.sha256(json.dumps(authored[sid], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(digest, expected, sid)
        for bait in ('worm', 'liver', 'shad', 'minnow', 'craw'):
            for sid in baseline['species']:
                self.assertEqual(BAIT_MATCH[bait].get(sid), baseline['bait_matches'][bait].get(sid))
        for zone, matches in baseline['zone_matches'].items():
            for sid in baseline['species']:
                self.assertEqual(ZONE_MATCH[zone].get(sid), matches.get(sid))
        for sid in ('gizzard_shad', 'threadfin_shad'):
            self.assertEqual(BAIT_MATCH['roe'][sid], .6)

    def test_lake_counts_and_cedar_only_additions(self):
        self.assertEqual({lake: len(ids) for lake, ids in LAKE_SPECIES_IDS.items()},
                         {'briar': 36, 'cedar': 36, 'flathead': 34, 'crater': 34, 'nebula': 34})
        additions = {fields[0] for lake, fields in _canonical_rows() if lake == 'cedar'}
        self.assertEqual(len(additions), 6)
        self.assertTrue(additions.isdisjoint(LAKE_SPECIES_IDS['briar']))
        self.assertTrue(all(SPECIES_BY_ID[sid].lakes == ('cedar',) for sid in additions))

    def test_weather_affinities_and_tier_defaults_are_exact(self):
        tiers = {row['tier']: row for row in CONTENT_V2_RAW['species.json']['tier_defaults']}
        for lake, fields in _canonical_rows():
            sid, tier = fields[0], fields[3]
            fish = SPECIES_BY_ID[sid]
            self.assertEqual((fish.rate, fish.trophy), (tiers[tier]['rate'], tiers[tier]['trophy']))
            expected = ({'aurora': 1.25} if lake == 'nebula' else {'fog': 1.4}
                        if sid in ('mistfin_dace', 'fog_mudminnow') else {'clear': 1.4}
                        if sid == 'glasswing_trout' else {})
            self.assertEqual(fish.weather_affinities, expected)
            for condition, multiplier in expected.items():
                self.assertEqual(weather_mult(sid, condition), multiplier)
                self.assertEqual(weather_mult(sid, 'fair'), 1)

    def test_specialty_stock_and_travel_with_roe_for_legacy_shad(self):
        self.assertEqual(BAIT_BY_ID['dough'].sold_at, ('all',))
        self.assertEqual(BAIT_BY_ID['roe'].sold_at, ('flathead', 'crater'))
        self.assertEqual(BAIT_BY_ID['grub'].sold_at, ('crater',))
        self.assertEqual(BAIT_BY_ID['stardust'].sold_at, ('nebula',))
        with tempfile.TemporaryDirectory() as directory:
            world = World('flathead')
            state = State.new(world)
            state.v2['story']['chapter'] = 5
            self.assertIsNone(state.buy_bait('roe'))
            session = Session(world, Path(directory)/'save.json', state, False)
            self.assertIsNone(session.change_lake('briar'))
            self.assertEqual(state.bait['roe'], 12)
            before = state.money
            self.assertIsNotNone(state.buy_bait('roe'))
            self.assertEqual(state.money, before)

    def test_all_protected_species_release_even_if_keep_is_requested(self):
        world = World('flathead')
        for fish in SPECIES_BY_ID.values():
            if 'protected' not in fish.tags:
                continue
            state = State.new(world)
            catch = Catch(fish.id, fish.min_lb, 1, 0, 'deep', 'roe', 6, lake_id=fish.lakes[0])
            state.lines = [SetLine('std', 'roe', 0, 0, 12, 0, 'deep', [Hook(False, catch)])]
            state._note_journal(catch)
            self.assertIsNone(state.take_hook(0, 0, disposition='keep'))
            self.assertFalse(state.well)
            self.assertIsNone(state.lines[0].hooks[0].catch)
            self.assertEqual(state.journal[fish.id]['count'], 1)
            self.assertEqual(fish.price, 0)

    def test_validator_rejects_wrong_count_preferences_affinities_and_soundings(self):
        bad = deepcopy(CONTENT_V2_RAW)
        bad['species.json']['species'].pop()
        fish = bad['species.json']['species'][36]
        fish['baits'] = ['missing']
        fish['zones'] = ['springs']  # Cedar has no springs.
        fish['weather_affinities'] = {'impossible': float('nan')}
        bad['lakes.json']['lakes'][2]['placeholder_depths']['deep'] = [10, 2]
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(bad)
        for location in ('144 standard species', '.baits', '.zones', '.weather_affinities', '.placeholder_depths.deep'):
            self.assertIn(location, str(caught.exception))


class SpeciesCatchabilityChecks(unittest.TestCase):
    def test_every_species_has_a_reachable_bait_time_habitat_and_rate(self):
        witnesses = validate_catchability()
        self.assertEqual(len(witnesses), 174)
        self.assertEqual({row['species'] for row in witnesses}, set(SPECIES_BY_ID))
        for sid in SPECIES_BY_ID:
            self.assertGreaterEqual(max(row['ratio'] for row in witnesses if row['species'] == sid), .5)
        self.assertTrue(all(row['zone'] not in ('landing', 'shore') for row in witnesses))


if __name__ == '__main__':
    unittest.main()
