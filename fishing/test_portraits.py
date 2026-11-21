"""Animated dialogue portraits: the motion's timing and moods, the rig's frames, Bot's card, and the session clocks."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from . import botportrait, catart
from .game import Keys, Session
from .portraitmotion import (BREATH_STRETCH, BRIGHT_GRIN_S, PORTRAIT_FPS, REST, TALK_EASE_S, Motion, PortraitRig,
                             mood, portrait_motion, talk_seconds)
from .sim import State
from .world import World

CAT = "grandmother_whiskers"
LINE = "The herons were out early on the flats this morning, and so was I."
BOT = botportrait.BOT
BOT_LINE = "The marker is visible. It is a brass ring on a post. It is pointing up."


def _frames(npc_id, text, seconds, *, reduced=False, line_start=0.0):
    """Poses at 60 fps for `seconds`, the line arriving at line_start."""
    return [portrait_motion(npc_id, text, t / 60, t / 60 - line_start, reduced_motion=reduced)
            for t in range(int(seconds * 60))]


class PortraitMotion(unittest.TestCase):
    def test_a_fresh_conversation_opens_at_rest(self):
        self.assertEqual(portrait_motion(CAT, LINE, 0.0, 0.0), REST)

    def test_reduced_motion_holds_one_pose_with_only_a_moods_lids(self):
        poses = set(_frames(CAT, LINE, 12, reduced=True))
        self.assertEqual(poses, {REST})
        self.assertEqual(set(_frames(CAT, "Well... I suppose so.", 12, reduced=True)), {Motion(lid=0.5)})

    def test_the_cat_bobs_while_it_speaks_then_settles_to_breathing(self):
        talk = talk_seconds(LINE)
        poses = _frames(CAT, LINE, talk + TALK_EASE_S + 3)
        speaking = [p.stretch for p in poses[: int(talk * 60)]]
        after = [p.stretch for p in poses[int((talk + TALK_EASE_S + 0.6) * 60):]]
        self.assertGreater(max(speaking) - min(speaking), 0.05)
        self.assertLessEqual(max(abs(s - 1) for s in after), BREATH_STRETCH + 0.002)
        self.assertGreater(max(after) - min(after), 0.0)  # still breathing, not frozen

    def test_poses_step_like_drawn_frames(self):
        poses = _frames(CAT, LINE, 2)
        changes = sum(a != b for a, b in zip(poses, poses[1:]))
        self.assertLessEqual(changes, int(2 * PORTRAIT_FPS))

    def test_cats_blink_now_and_then_and_not_in_unison(self):
        def closed(npc_id):
            return [p.lid == 1.0 for p in _frames(npc_id, "Hm.", 30, line_start=-10)]

        whiskers, barnaby = closed(CAT), closed("doc_barnaby")
        self.assertGreaterEqual(sum(a and not b for a, b in zip(whiskers, whiskers[1:])), 5)  # blinks begin
        self.assertLess(sum(whiskers) / len(whiskers), 0.1)  # eyes are mostly open
        self.assertNotEqual(whiskers, barnaby)

    def test_moods_read_from_punctuation(self):
        self.assertEqual(mood("Look at that one!"), "bright")
        self.assertEqual(mood("Did you hear it?\u201d"), "curious")
        self.assertEqual(mood("I used to fish here... long ago!"), "wistful")
        self.assertEqual(mood("Tea's on."), "plain")
        # A question cocks the head and holds it; a bright line opens with a happy squint.
        curious = portrait_motion(CAT, "Is that a sturgeon?", 0.0, 1.0)
        plain = portrait_motion(CAT, "That is a sturgeon.", 0.0, 1.0)
        self.assertGreater(abs(curious.tilt - plain.tilt), 0.05)
        self.assertEqual(portrait_motion(CAT, "A sturgeon!", 0.2, BRIGHT_GRIN_S / 2).lid, 1.0)
        self.assertEqual(portrait_motion(CAT, "A sturgeon!", 0.2, BRIGHT_GRIN_S + 0.2).lid, 0.0)


class Rig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catart.clear_caches()
        cls.rig = catart.portrait_rig(CAT, 176)

    def test_rest_matches_the_still_card(self):
        from .imageops import resize_rgb
        still = resize_rgb(catart.portrait(CAT), 176, 176).astype(int)
        diff = np.abs(self.rig.frame(REST).astype(int) - still)
        self.assertLess(diff.mean(), 1.0)

    def test_lids_close_over_the_eyes_only(self):
        open_ = self.rig.frame(REST).astype(int)
        shut = self.rig.frame(Motion(lid=1.0)).astype(int)
        changed = np.abs(open_ - shut).sum(axis=2) > 24
        self.assertGreater(changed.sum(), 10)
        layers = catart.portrait_layers(CAT)
        ys, xs = np.nonzero(layers.eyes)
        scale = 176 / catart.PORTRAIT_SIZE
        cy, cx = np.nonzero(changed)
        self.assertGreaterEqual(cy.min(), ys.min() * scale - 2)
        self.assertLessEqual(cy.max(), ys.max() * scale + 2)
        self.assertGreaterEqual(cx.min(), xs.min() * scale - 2)
        self.assertLessEqual(cx.max(), xs.max() * scale + 2)

    def test_the_card_stays_put_while_the_cat_moves(self):
        rest = self.rig.frame(REST)
        moved = self.rig.frame(Motion(tilt=0.08, stretch=1.05))
        self.assertGreater(int(np.abs(rest.astype(int) - moved.astype(int)).sum()), 10**5)
        # The border and the paper outside the cat are untouched.
        for edge in (np.s_[:5, :], np.s_[-5:, :12], np.s_[:, :5], np.s_[:, -5:]):
            np.testing.assert_array_equal(moved[edge], rest[edge])
        self.assertFalse(moved.flags.writeable)

    def test_a_positive_lean_tips_the_head_toward_the_text(self):
        rest = self.rig.frame(REST).astype(int)
        leaned = self.rig.frame(Motion(tilt=0.1)).astype(int)
        paper = rest[6, 6]

        def head_x(image):
            # The centre of the cat's pixels in the top third of the card, where the head is.
            ys, xs = np.nonzero(np.abs(image[8:58, 8:-8] - paper).sum(axis=2) > 60)
            return xs.mean()

        self.assertGreater(head_x(leaned) - head_x(rest), 2.0)

    def test_memory_bound_covers_what_the_caches_hold(self):
        self.rig.frame(Motion(stretch=1.01))
        self.assertGreaterEqual(PortraitRig.bytes_for(176), self.rig.nbytes())
        layers = catart.portrait_layers(CAT)
        held = sum(a.nbytes for a in layers) + self.rig.nbytes() + catart._paper().nbytes
        self.assertGreaterEqual(catart.portrait_bytes_bound(), held)
        with self.assertRaises(ValueError):
            catart.portrait_rig(CAT, catart.PORTRAIT_SIZE + 1)


class BotPortrait(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catart.clear_caches()
        cls.rig = catart.portrait_rig(BOT, 176, botportrait.DEFAULT_LOOK)

    def test_bot_opens_at_rest_and_holds_still_under_reduced_motion(self):
        self.assertEqual(portrait_motion(BOT, BOT_LINE, 0.0, 0.0), REST)
        self.assertEqual(set(_frames(BOT, BOT_LINE, 12, reduced=True)), {REST})

    def test_tin_nods_as_he_speaks_without_squashing_or_breathing(self):
        talk = talk_seconds(BOT_LINE)
        poses = _frames(BOT, BOT_LINE, talk + TALK_EASE_S + 3)
        speaking = [p.stretch for p in poses[: int(talk * 60)]]
        after = poses[int((talk + TALK_EASE_S + 0.6) * 60):]
        self.assertGreater(max(speaking) - 1, 0.02)
        self.assertGreater(min(speaking), 0.995)  # tin does not squash as a nod lands
        self.assertLess(max(abs(p.stretch - 1) for p in after), 1e-4)  # nor breathe once he has said it
        tilts = [p.tilt for p in after]
        self.assertGreater(max(tilts) - min(tilts), 0.01)  # still rocking with the bow, not frozen

    def test_his_lamp_shutter_blinks_slower_than_a_cat_and_never_doubles(self):
        def starts(npc_id):
            shut = [p.lid == 1.0 for p in _frames(npc_id, "Hm.", 60, line_start=-10)]
            return [i for i, (before, now) in enumerate(zip(shut, shut[1:])) if now and not before]

        bot, cat = starts(BOT), starts(CAT)
        self.assertGreaterEqual(len(bot), 6)
        self.assertLess(len(bot), len(cat))
        self.assertGreater(min(b - a for a, b in zip(bot, bot[1:])), 30)  # half a second at least

    def test_rest_matches_his_still_card(self):
        from .imageops import resize_rgb
        still = resize_rgb(botportrait.portrait_layers(botportrait.DEFAULT_LOOK).card, 176, 176).astype(int)
        self.assertLess(np.abs(self.rig.frame(REST).astype(int) - still).mean(), 1.0)

    def test_the_shutter_closes_over_his_lamp_only(self):
        open_ = self.rig.frame(REST).astype(int)
        shut = self.rig.frame(Motion(lid=1.0)).astype(int)
        changed = np.abs(open_ - shut).sum(axis=2) > 24
        self.assertGreater(changed.sum(), 30)
        ys, xs = np.nonzero(botportrait.portrait_layers(botportrait.DEFAULT_LOOK).eyes)
        scale = 176 / catart.PORTRAIT_SIZE
        cy, cx = np.nonzero(changed)
        self.assertGreaterEqual(cy.min(), ys.min() * scale - 2)
        self.assertLessEqual(cy.max(), ys.max() * scale + 2)
        self.assertGreaterEqual(cx.min(), xs.min() * scale - 2)
        self.assertLessEqual(cx.max(), xs.max() * scale + 2)
        # The glowing lamp goes dim behind the shutter (the antenna's lamp is not an eye).
        self.assertLess(shut[changed].sum(), open_[changed].sum() * 0.8)

    def test_his_card_wears_the_saved_shell_and_collar(self):
        state = State.new(World(), seed=87)
        self.assertEqual(botportrait.look(state), botportrait.DEFAULT_LOOK)
        profile = state.v2["profile"]
        profile["shell"] = "duck"
        profile["collar"].update(stage="retied", knot="bow")
        self.assertEqual(botportrait.look(state), botportrait.Look("duck", "bow"))
        state.v2["settings"]["collar_visible"] = False
        self.assertEqual(botportrait.look(state), botportrait.Look("duck", "none"))
        tin = botportrait.portrait_layers(botportrait.DEFAULT_LOOK).card.astype(int)
        duck = botportrait.portrait_layers(botportrait.Look("duck", "none")).card.astype(int)
        self.assertGreater(int(np.abs(tin - duck).sum()), 10**6)

    def test_memory_bound_covers_his_layers(self):
        self.rig.frame(Motion(stretch=1.01))
        layers = botportrait.portrait_layers(botportrait.DEFAULT_LOOK)
        held = sum(a.nbytes for a in layers) + self.rig.nbytes() + catart._paper().nbytes
        self.assertGreaterEqual(catart.portrait_bytes_bound(), held)
        with self.assertRaises(ValueError):
            catart.portrait_rig(BOT, catart.PORTRAIT_SIZE + 1, botportrait.DEFAULT_LOOK)


class SessionClocks(unittest.TestCase):
    def test_the_line_clock_restarts_on_each_new_line(self):
        world = World()
        with tempfile.TemporaryDirectory() as tmp:
            state = State.new(world, seed=87)
            session = Session(world, Path(tmp) / "save.json", state, False)
            session.ui.mode = "play"
            state.x, state.z = state.npcs[0].anchor.position
            session.tick(Keys(pressed={"c"}), 0)
            self.assertEqual(session.ui.mode, "dialogue")
            self.assertEqual((session.ui.dialogue_s, session.ui.dialogue_line_s), (0.0, 0.0))
            session.tick(Keys(), 0.5)
            self.assertAlmostEqual(session.ui.dialogue_line_s, 0.5)
            first = session.conversation.node_id
            session.tick(Keys(pressed={"return"}), 0.1)
            self.assertNotEqual(session.conversation.node_id, first)
            self.assertEqual(session.ui.dialogue_line_s, 0.0)
            self.assertAlmostEqual(session.ui.dialogue_s, 0.6)


if __name__ == "__main__":
    unittest.main()
