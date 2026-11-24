"""Isolated displayed-hitbox, ownership and menu-routing regressions for #143.

No window or gameplay key synthesis is required; native-font cases below also
verify that representative renderers publish the controls the router consumes.
"""

from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

import numpy as np

from . import pointer, skipperlook
from .game import Keys, Session
from .platform import Text
from .sim import Catch, Hook, SetLine, State
from .ui import UI, pause_options, shop_rows
from .world import World


class HitTestingChecks(unittest.TestCase):
    """Pure geometry checks with no SDL/window dependency."""

    def test_half_open_bounds_and_topmost_target(self):
        """Check half-open UI-pixel edges and overlapping-control precedence."""
        registry = pointer.Registry()
        registry.begin("menu", (100, 80))
        registry.add((10, 20, 30, 40), field="title_i", value=1)
        registry.add((20, 30, 5, 5), action="back")
        self.assertIsNone(registry.hit((9, 20)))
        self.assertIsNone(registry.hit((40, 20)))
        self.assertIsNone(registry.hit((10, 60)))
        self.assertEqual(registry.hit((10, 20)).value, 1)
        self.assertEqual(registry.hit((20, 30)).action, "back")
        registry.add((0, 0, 0, 20))
        self.assertIsNone(registry.hit((0, 0)))

    def test_hover_does_not_recenter_a_window(self):
        """Keep row positions stable under hover, but permit scrolling and invalidation."""
        registry = pointer.Registry()
        registry.begin("shop", (100, 80))
        self.assertEqual(registry.window("rows", 5, 20, 5), (3, 8))
        registry.owner = "pointer"
        self.assertEqual(registry.window("rows", 7, 20, 5), (3, 8))
        registry.owner = "scroll"
        self.assertEqual(registry.window("rows", 8, 20, 5), (6, 11))
        registry.begin("other tab", (100, 80))
        self.assertEqual(registry.windows, {})
        self.assertIsNone(registry.hovered)


class PointerRoutingChecks(unittest.TestCase):
    """Exercise native selections and semantic activation without a renderer."""

    @classmethod
    def setUpClass(cls):
        """Load the authored world once for deterministic session fixtures."""
        cls.world = World()

    def setUp(self):
        """Create a fresh session and intercept persistence for each routing check."""
        temporary = tempfile.TemporaryDirectory(prefix="trotline-pointer-")
        self.addCleanup(temporary.cleanup)
        self.state = State.new(self.world, seed=143)
        self.session = Session(self.world, Path(temporary.name) / "save.json", self.state, False)
        save = patch.object(self.session, "save")
        self.saved = save.start()
        self.addCleanup(save.stop)

    def display(self, mode, *, action="activate", field="", value=None, scroll=""):
        """Publish one semantic target in the current context at fixed UI pixels."""
        ui = self.session.ui
        ui.mode = mode
        ui.pointer.begin(pointer.context(self.state, ui), (1280, 720), scroll)
        ui.pointer.add((20, 20, 100, 40), action, field, value)

    def click(self, **kwargs):
        """Dispatch one click at the published control, with optional input metadata."""
        self.session._keys(Keys(mouse_click=(30, 30), **kwargs), 0)

    def test_title_confirmation_click_is_not_replayed_in_creator(self):
        """Require newly rendered confirmation geometry before advancing again."""
        self.session.ui.has_save = True
        self.display("title", field="title_i", value=1)
        self.click()
        self.assertTrue(self.session.ui.confirm_new)
        self.assertEqual(self.session.ui.mode, "title")
        # This is still the old displayed title, not its confirmation geometry.
        self.click()
        self.assertEqual(self.session.ui.mode, "title")
        self.display("title")
        self.click()
        self.assertEqual(self.session.ui.mode, "new_mode")
        self.assertIsNone(self.session.ui.skipper_look)

    def test_hover_keyboard_and_stationary_pointer_share_native_selection(self):
        """Let real motion take focus without stationary mouse coordinates stealing it."""
        self.session.ui.has_save = True
        self.display("title", field="title_i", value=1)
        self.session._keys(Keys(mouse_pos=(30, 30), mouse_moved=True), 0)
        self.assertEqual(self.session.ui.title_i, 1)
        self.assertEqual(self.session.ui.pointer.owner, "pointer")
        self.session._keys(Keys(pressed={"up"}, mouse_pos=(30, 30)), 0)
        self.assertEqual(self.session.ui.title_i, 0)
        self.assertEqual(self.session.ui.pointer.owner, "keyboard")
        self.session._keys(Keys(mouse_pos=(30, 30)), 0)
        self.assertEqual(self.session.ui.title_i, 0)
        self.click()
        self.assertTrue(self.session.ui.confirm_new)

    def test_blank_stale_resized_and_unfocused_clicks_do_not_activate(self):
        """Reject geometry that was not displayed for this context and viewport."""
        for change in ("blank", "viewport", "resize", "context", "focus"):
            with self.subTest(change=change):
                self.session.ui.confirm_new = False
                self.session.ui.has_save = True
                self.display("title", field="title_i", value=1)
                keys = Keys(mouse_click=(30, 30))
                if change == "blank":
                    keys.mouse_click = (500, 500)
                elif change == "viewport":
                    keys.viewport = (800, 600)
                elif change == "resize":
                    keys.resized = True
                elif change == "context":
                    self.session.ui.confirm_new = True
                else:
                    self.session.focused = False
                self.session._keys(keys, 0)
                self.assertEqual(self.session.ui.mode, "title")
                self.assertEqual(self.session.ui.confirm_new, change == "context")
                self.session.focused = True

    def test_pause_resume_consumes_click_without_gameplay_actions(self):
        """Resume without redispatching the click or held menu direction into play."""
        self.display("pause", field="pause_i", value=0)
        with patch.object(self.session, "_play_keys") as play:
            self.session.tick(Keys(mouse_click=(30, 30), held={"w"}), 0)
        play.assert_not_called()
        self.assertEqual(self.session.ui.mode, "play")
        self.assertIn("w", self.session._menu_held)
        self.assertFalse(self.state.lines)
        self.assertEqual(self.state.throttle, 0)

    def test_settings_adjustment_binding_capture_and_back(self):
        """Adjust values and cancel key capture through their existing native state."""
        self.display("settings", action="adjust_plus", field="settings_i", value=7)
        self.state.v2["settings"].setdefault("volumes", {})["master"] = .4
        # A content mutation requires a newly displayed frame.
        self.display("settings", action="adjust_plus", field="settings_i", value=7)
        self.click()
        self.assertEqual(self.state.v2["settings"]["volumes"]["master"], .5)
        self.session.ui.settings_page = "keys"
        self.display("settings", field="key_binding_i", value=0)
        self.click()
        self.assertTrue(self.session.ui.capturing_key)
        self.display("settings", action="back")
        self.click()
        self.assertFalse(self.session.ui.capturing_key)
        self.assertEqual(self.session.ui.settings_page, "keys")
        self.display("settings", action="back")
        self.click()
        self.assertEqual(self.session.ui.settings_page, "main")

    def test_creator_typing_done_and_cancel_use_draft_semantics(self):
        """Allow pointer exits while typing without committing a cancelled draft."""
        original = skipperlook.saved(self.state)
        self.session._open_skipper("pause")
        self.display("skipper", field="skipper_i", value=0)
        self.click()
        self.assertTrue(self.session.ui.skipper_typing)
        self.session.ui.skipper_look["name"] = "Pointer Cat"
        self.display("skipper", action="creator_cancel")
        self.click()
        self.assertEqual(skipperlook.saved(self.state), original)
        self.assertEqual(self.session.ui.mode, "pause")
        self.session._open_skipper("pause")
        self.session.ui.skipper_typing = True
        self.session.ui.skipper_look["name"] = "Pointer Cat"
        self.display("skipper", action="creator_done")
        self.click()
        self.assertEqual(skipperlook.saved(self.state)["name"], "Pointer Cat")
        self.assertEqual(self.session.ui.mode, "pause")

    def test_help_scroll_wraps_and_close_restores_origin(self):
        """Use rendered spread counts and preserve the Help return mode."""
        self.session.ui.help_from = "settings"
        self.session.ui.help_spreads = 5
        self.display("help", action="next", scroll="help")
        self.click()
        self.assertEqual(self.session.ui.help_spread, 1)
        self.display("help", scroll="help")
        self.session._keys(Keys(mouse_wheel=2), 0)
        self.assertEqual(self.session.ui.help_spread, 4)
        self.display("help", action="back")
        self.click()
        self.assertEqual(self.session.ui.mode, "settings")

    def test_shop_tabs_and_purchase_use_focused_row_once(self):
        """Purchase the clicked native row once and reject obsolete shop content."""
        self.display("shop", action="tab", value=1)
        self.click()
        self.assertEqual(self.session.ui.shop_tab, 1)
        rows = shop_rows(self.state, 1)
        self.display("shop", field="shop_i", value=0)
        with patch.object(self.session, "_buy", return_value="click") as buy:
            self.click()
        buy.assert_called_once_with(rows[0])
        self.assertEqual(self.session.ui.shop_i, 0)
        self.display("shop", field="shop_i", value=0)
        self.state.money += 1
        with patch.object(self.session, "_buy") as buy:
            self.click()
        buy.assert_not_called()

    def test_bait_selection_does_not_deploy_until_set(self):
        """Select section baits independently from the explicit deployment control."""
        self.display("setbait", action="focus", field="set_bait", value=2)
        self.click()
        self.assertEqual(self.session.ui.set_bait, 2)
        self.assertEqual(self.session.ui.set_section_baits[0], 2)
        self.assertFalse(self.state.lines)
        self.display("setbait", action="set_sections", value=3)
        self.click()
        self.assertEqual(self.session.ui.set_sections, 3)
        self.display("setbait", action="set_section", value=2)
        self.click()
        self.assertEqual(self.session.ui.set_section, 2)
        self.display("setbait", action="set")
        with patch.object(self.state, "try_set", return_value=None) as deploy:
            self.click()
        deploy.assert_called_once()
        self.assertEqual(self.session.ui.mode, "play")

    def test_check_rows_toggle_and_pull_through_native_actions(self):
        """Select a catch disposition and pull the displayed line without play input."""
        catch = Catch("bluegill", .5, 1, 0, "flats", "worm", 8)
        self.state.lines = [SetLine("std", "worm", 0, 0, 10, 0, "open", [Hook(True, catch)])]
        before = catch.disposition
        self.display("check", field="check_i", value=0)
        self.click()
        self.assertNotEqual(catch.disposition, before)
        from .ui import check_rows
        pull = next(index for index, row in enumerate(check_rows(self.state, 0))
                    if row.kind == "pull")
        self.display("check", field="check_i", value=pull)
        self.click()
        self.assertEqual(self.session.ui.mode, "play")
        self.assertFalse(self.state.lines)

    def test_keyboard_confirm_uses_visible_auxiliary_focus(self):
        """Confirm a hovered shortcut instead of accidentally activating an old row."""
        self.display("pause", action="kitchen")
        self.session._keys(Keys(mouse_pos=(30, 30), mouse_moved=True), 0)
        self.session._keys(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.ui.mode, "kitchen")

    def test_dialogue_hover_choice_continue_and_allowed_exit(self):
        """Route focus and continuation once, preserving the dialogue return mode."""
        chat = Mock(node_id="choice", npc_id="speaker", selected=0, finished_scene=False)
        chat.node.return_value = {"choices": [{}, {}]}
        chat.advance.return_value = True
        chat.in_scene.return_value = False
        self.session.conversation = self.session.ui.conversation = chat
        self.session.ui.dialogue_from = "map"
        self.display("dialogue", field="dialogue_selected", value=1, scroll="dialogue")
        self.session._keys(Keys(mouse_pos=(30, 30), mouse_moved=True), 0)
        self.assertEqual(chat.selected, 1)
        chat.advance.assert_not_called()
        self.click()
        chat.advance.assert_called_once_with(self.state, self.session._npc_content)
        self.display("dialogue", action="back")
        self.click()
        self.assertEqual(self.session.ui.mode, "map")
        self.assertIsNone(self.session.conversation)

    def test_all_shop_tabs_route_through_their_native_action(self):
        """Cover each tab including Kitchen and Bot without repeating a purchase."""
        from .ui import SHOP_TABS
        for tab in range(len(SHOP_TABS)):
            with self.subTest(tab=tab):
                self.session.ui.shop_tab = tab
                rows = shop_rows(self.state, tab)
                self.assertTrue(rows)
                self.display("shop", field="shop_i", value=0)
                with patch.object(self.session, "_buy") as buy, patch.object(
                        self.session, "_kitchen_action") as cook:
                    self.click()
                expected = cook if tab == 6 and not rows[0].kind.startswith("bot_") else buy
                expected.assert_called_once_with(rows[0])
                (buy if expected is cook else cook).assert_not_called()

    def test_map_shortcuts_and_livewell_treasure_are_not_keys(self):
        for action, method in (("map_hail", "_hail"), ("map_anchor", "_anchor"),
                               ("map_sail", "_sail"), ("map_tow", "_map_tow"),
                               ("map_bot", "_bot")):
            self.display("map", action=action)
            with patch.object(self.session, method) as act, patch.object(
                    self.session, "_play_keys") as play:
                self.click()
            act.assert_called_once_with()
            play.assert_not_called()
        self.display("well", action="treasure", field="well_i", value=0)
        with patch.object(self.state, "toggle_treasured", return_value=None) as treasure:
            self.click()
        treasure.assert_called_once_with(0)

    def test_scene_skip_is_guarded_and_unseen_transient_cannot_take_click(self):
        """Keep first scenes protected and require a displayed transient before dismissal."""
        from types import SimpleNamespace
        self.session.stage = SimpleNamespace(repeat=False, t=1,
                                             stage=SimpleNamespace(duration=10))
        self.display("dialogue", action="skip_scene")
        self.click()
        self.assertEqual(self.session.stage.t, 1)
        self.session.stage.repeat = True
        self.session.ui.stage_skip = True
        self.display("dialogue", action="skip_scene")
        self.click()
        self.assertEqual(self.session.stage.t, 10)
        self.session.ui.mode = "catnap"
        self.session.ui.nap_timer = 5
        self.click()
        self.assertEqual(self.session.ui.mode, "catnap")

    def test_transient_click_dismissal_is_preserved(self):
        """Keep timed cards dismissible while respecting the credits' minimum hold."""
        self.session.ui.mode = "catnap"
        self.session.ui.nap_timer = 5
        self.display("catnap")
        self.click()
        self.assertEqual(self.session.ui.mode, "play")
        self.session.ui.mode = "cooking"
        self.session.ui.cook_timer = 5
        self.session.ui.cook_from = "shop"
        self.display("cooking")
        self.click()
        self.assertEqual(self.session.ui.mode, "shop")
        self.session.ui.mode = "credits"
        self.session.ui.credits_s = 0
        self.display("credits")
        self.click()
        self.assertEqual(self.session.ui.mode, "credits")

    def test_story_dialogue_back_cannot_skip_scene(self):
        """Preserve the story-scene exit restriction even for a routed back intent."""
        chat = Mock(node_id="story-node", npc_id="story-speaker")
        chat.in_scene.return_value = True
        self.session.conversation = self.session.ui.conversation = chat
        self.display("dialogue", action="back")
        self.click()
        self.assertEqual(self.session.ui.mode, "dialogue")
        self.assertIs(self.session.conversation, chat)


class DisplayedPointerChecks(unittest.TestCase):
    """Verify font-measured publication boundaries without opening a game window."""

    @classmethod
    def setUpClass(cls):
        """Load the authored world shared by native-font publication checks."""
        cls.world = World()

    def test_native_renderers_publish_visible_targets_and_own_focus(self):
        """Publish bounded UI-pixel targets at large and compact window sizes."""
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        self.addCleanup(renderer.close)
        state = State.new(self.world, seed=143)
        from .dialogue import Conversation
        Session(self.world, Path("unused-pointer-render.json"), state, False)
        chat = Conversation.start(state.npcs[0], state, renderer.narrative_content)
        from .ui import UIState
        for viewport in ((1280, 720), (480, 270)):
            for mode in ("title", "pause", "settings", "help", "shop", "setbait", "well", "map",
                         "new_mode", "skipper", "dialogue", "cook_confirm"):
                with self.subTest(viewport=viewport, mode=mode):
                    ui = UIState(mode=mode, skipper_look=skipperlook.saved(state),
                                 conversation=chat, dialogue_content=renderer.narrative_content,
                                 cook_kind="dish", cook_arg="pan_fritters",
                                 cook_label="Sunny Pan Fritters")
                    frame = np.zeros((viewport[1], viewport[0], 3), np.uint8)
                    renderer.draw(frame, state, ui)
                    self.assertEqual(ui.pointer.viewport, viewport)
                    self.assertEqual(ui.pointer.identity, pointer.context(state, ui))
                    self.assertTrue(ui.pointer.targets)
                    for target in ui.pointer.targets:
                        x, y, w, h = target.rect
                        self.assertGreater(w, 0)
                        self.assertGreater(h, 0)
                        self.assertGreaterEqual(x, 0)
                        self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(x + w, viewport[0])
                        self.assertLessEqual(y + h, viewport[1])
        self.assertIn("Settings", pause_options(state))
