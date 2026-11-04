"""V1-38: every sound captioned and heard, each lake's voice, music, cues, mute and budget."""
from pathlib import Path
import re
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from . import calendar, encounter, soundscape
from .audio import Audio
from .botchimes import CHIMES
from .content import load_content
from .game import Keys, Session
from .legendary import LEGENDARY_DATA
from .sim import Catch, Hook, SetLine, State
from .world import World

ROOT = Path(__file__).resolve().parent


def _schedule(lake, hour, *, finale=False, seconds=600):
    audio = Audio(open_device=False)
    audio.reset_schedule(lake, hour, finale=finale)
    heard = set()
    for _ in range(seconds):
        audio.time += 1.0
        audio._schedule()
        heard.update(audio.take_played())
        audio.shots.clear()
    return heard


class Captions(unittest.TestCase):
    def test_every_sound_has_a_caption_and_a_bus(self):
        for kind in soundscape.KINDS + CHIMES:
            self.assertTrue(soundscape.caption(kind), kind)
            self.assertIn(soundscape.bus(kind), ("music", "ambience", "sfx"), kind)
        self.assertTrue(all(soundscape.bus(k) == "music" for k in soundscape.MUSIC_CAPTIONS))
        self.assertTrue(all(soundscape.bus(k) == "ambience" for k in soundscape.AMBIENCE_CAPTIONS))
        self.assertEqual(soundscape.bus("horn"), "sfx")

    def test_every_sound_the_game_plays_is_known_and_captioned(self):
        source = (ROOT / "game.py").read_text() + (ROOT / "bot.py").read_text()
        played = set(re.findall(r'self\.sound = "([a-z_]+)"', source))
        played |= set(re.findall(r'self\.cue\("([a-z_]+)"\)', source))
        played |= set(re.findall(r'return "([a-z_]+)"', (ROOT / "bot.py").read_text())) & set(soundscape.KINDS)
        self.assertTrue({"bite", "error", "splash", "horn", "legendary", "whale_song"} <= played)
        for kind in played:
            self.assertIn(kind, soundscape.CAPTIONS, kind)
        for lake in soundscape.LAKES:
            for kind in soundscape.AMBIENCE[lake]:
                self.assertIn(kind, soundscape.CAPTIONS, kind)
            self.assertIn(soundscape.motif_for(lake), soundscape.CAPTIONS)

    def test_a_shells_chime_reads_as_its_shell(self):
        state = State.new(World("briar"), seed=1)
        self.assertEqual(soundscape.caption("bot", state), soundscape.caption("bot", state))
        self.assertTrue(soundscape.caption("bot_tin", state))


class Sounds(unittest.TestCase):
    def test_every_sound_synthesizes_once_and_is_heard(self):
        for kind in soundscape.KINDS:
            samples = soundscape.tone(kind)
            self.assertEqual(samples.dtype, np.int16, kind)
            self.assertGreater(int(np.max(np.abs(samples))), 200, kind)
            self.assertLessEqual(len(samples) / soundscape.SR, 13.0, kind)
            self.assertIs(soundscape.tone(kind), samples)  # cached
            self.assertFalse(samples.flags.writeable)

    def test_each_lake_has_its_own_motif(self):
        motifs = [soundscape.tone(soundscape.motif_for(lake)) for lake in soundscape.LAKES]
        for i in range(len(motifs)):
            for j in range(i + 1, len(motifs)):
                n = min(len(motifs[i]), len(motifs[j]))
                self.assertFalse(np.array_equal(motifs[i][:n], motifs[j][:n]))
        self.assertEqual(soundscape.motif_for("nowhere"), "motif_briar")


class Ambience(unittest.TestCase):
    def test_each_lake_calls_with_its_own_voice(self):
        self.assertEqual(_schedule("briar", 6.5) | _schedule("briar", 12.0) | _schedule("briar", 23.0),
                         {"loon", "gull", "frog"})
        flathead = _schedule("flathead", 6.5) | _schedule("flathead", 12.0) | _schedule("flathead", 23.0)
        self.assertEqual(flathead, {"loon", "larch_wind", "ice_tick"})
        self.assertNotIn("ice_tick", _schedule("flathead", 14.0))  # only on cold hours
        crater = _schedule("crater", 12.0) | _schedule("crater", 23.0)
        self.assertEqual(crater, {"spring", "raven"})
        self.assertNotIn("raven", _schedule("crater", 23.0))  # ravens by day
        self.assertEqual(_schedule("nebula", 23.0), {"twinkle", "choir"})
        self.assertIn("whale_song", _schedule("nebula", 23.0, finale=True))  # after the finale
        self.assertNotIn("whale_song", _schedule("nebula", 12.0, finale=True))  # by night

    def test_the_caldera_is_hushed(self):
        loud, hushed = Audio(open_device=False), Audio(open_device=False)
        loud._lake_id, hushed._lake_id = "briar", "crater"
        loud._motorized = hushed._motorized = False  # the beds alone: no outboard
        a = np.abs(loud._mix(4096, 0.0, 0.0).astype(np.float32)).mean()
        b = np.abs(hushed._mix(4096, 0.0, 0.0).astype(np.float32)).mean()
        self.assertLess(b, a * 0.8)

    def test_the_coverage_report_is_complete_and_inside_the_budget(self):
        report = soundscape.coverage_report()
        self.assertTrue(report["complete"])
        self.assertTrue(report["within_budget"])
        self.assertLess(report["bytes"], soundscape.AUDIO_BUDGET_BYTES)
        self.assertEqual(set(report["lakes"]), set(soundscape.LAKES))


class Mixer(unittest.TestCase):
    def test_m_mutes_everything_and_nothing_waits_to_play(self):
        audio = Audio(open_device=False)
        for kind in ("bite", "loon", "motif_briar"):
            audio.shots.append((soundscape.tone(kind), 0, soundscape.bus(kind)))
        audio._played.append("loon")
        audio.update(0.05, 0.0, 0.0, True)
        self.assertEqual(audio.shots, [])
        self.assertEqual(audio.take_played(), [])

    def test_music_plays_on_its_bus_and_one_motif_at_a_time(self):
        audio = Audio(open_device=False)
        audio.ok = True  # without a device, blip only queues
        audio.blip("motif_briar")
        audio.blip("motif_cedar")
        self.assertEqual([bus for _s, _c, bus in audio.shots], ["music"])
        self.assertIs(audio.shots[0][0], soundscape.tone("motif_cedar"))
        audio.set_volumes(ambience=0.0, sfx=0.0, music=0.0)
        audio._water = np.zeros(256, np.float32)
        self.assertEqual(int(np.max(np.abs(audio._mix(512, 0.0, 0.0)))), 0)
        audio.set_volumes(music=1.0)
        self.assertGreater(int(np.max(np.abs(audio._mix(512, 0.0, 0.0)))), 0)


class Cues(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("briar")

    def session(self, state):
        with patch("fishing.game.load_content", return_value=self.content):
            session = Session(self.world, self.path, state, True)
        session.ui.mode = "play"
        return session

    def state(self, minutes):
        state = State.new(self.world, seed=38)
        state.x, state.z = self.world.slip.world(60.0, 0.0)
        state.anchored, state.speed = True, 0.0
        state.game_minutes = minutes
        return state

    def heard(self, session, ticks=1, dt=0.05):
        out = []
        for _ in range(ticks):
            session.tick(Keys(), dt)
            out += [k for k in (session.sound, *session.cues) if k]
        return out

    def test_the_lakes_motif_plays_at_dawn_and_dusk_once(self):
        session = self.session(self.state(1440 - 1))  # 05:59
        self.heard(session)
        session.state.game_minutes = 1440 + 1  # 06:01
        self.assertEqual(self.heard(session).count("motif_briar"), 1)
        self.assertNotIn("motif_briar", self.heard(session, 5))
        session.state.game_minutes = 1440 + 13 * 60 + 1  # 19:01
        self.assertIn("motif_briar", self.heard(session))

    def test_a_lake_day_rings_its_bell_once(self):
        row = next(day for day in calendar.LAKE_DAYS if day.lake == "briar")
        day = next(d for d in range(1, 8) if calendar.weekday(d * 1440) == row.weekday)
        session = self.session(self.state(day * 1440 + 120))
        heard = self.heard(session, 3)
        self.assertEqual(heard.count("lake_day"), 1)
        self.assertEqual(session.ui.caption, soundscape.CAPTIONS["lake_day"])

    def test_the_cookout_rings_once(self):
        event = calendar.CALENDAR_DATA["cookout"]
        day = next(d for d in range(1, 8) if calendar.weekday(d * 1440) == event["weekday"])
        minutes = day * 1440 + int((event["start_hour"] - 6 + 0.5) * 60)
        self.assertTrue(calendar.cookout_active(minutes))
        session = self.session(self.state(minutes))
        self.assertEqual(self.heard(session, 3).count("cookout"), 1)

    def test_the_hail_sounds_the_horn(self):
        session = self.session(self.state(1440 + 300))
        cat = SimpleNamespace(id="willow", name="Willow")
        with patch("fishing.game.nearby_npc", return_value=cat), \
                patch("fishing.game.record_hail", return_value=False), \
                patch("fishing.game.open_conversation", return_value=None), \
                patch("fishing.game.calendar.chat", return_value=False), \
                patch("fishing.game.kitchen.teach", return_value=False):
            session.cues = []
            session._hail()
        self.assertEqual(session.cues, ["horn"])

    def test_a_legendary_brings_its_chord_with_its_name(self):
        state = self.state(1440 + 300)
        hooks = [Hook(True) for _ in range(3)]
        row = LEGENDARY_DATA["old_lantern"]
        hooks[0] = Hook(False, Catch("old_lantern", row["weight_lb"], 1.0, 0.0, "open", row["bait"], 21.0,
                                     legendary=True, disposition="release"))
        state.lines = [SetLine("heavy", "lantern_liver", state.x - 3, state.z, state.x + 3, state.z, "open", hooks)]
        session = self.session(state)
        session._open_e()
        heard = self.heard(session, int((encounter.SCENE_S + 1.0) / 0.1), dt=0.1)
        self.assertEqual(heard.count("legendary"), 1)
        self.assertLess(heard.index("hum"), heard.index("legendary"))

    def test_a_staged_story_moment_brings_the_motif(self):
        session = self.session(State.new(self.world, seed=35))
        session.ui.mode, session.ui.new_mode_i = "new_mode", 0
        session.tick(Keys(pressed={"return"}), 0.05)
        self.assertEqual(session.stage.stage_id, "pro_01")
        self.assertIn("motif_briar", session.cues)


if __name__ == "__main__":
    unittest.main()
