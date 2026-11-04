"""The loop. Driving, menus, and the save. Headless callers use Session.tick."""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
import time

import numpy as np

from .content import load_content
from .quests import QuestManager, autostart_story, scene_state
from .dialogue import nearby_npc, open_conversation, record_hail
from .story import (begin_prologue, due_scene, scene_conversation, settle_near, settle_progress, settle_spot,
                    settle_step_active, settle_tick)
from . import staging
from .npcs import active_npcs, schedule_key
from .audio import Audio
from .data import BAITS, BAIT_BY_ID, SPECIES, hour_of_day
from .weather import weather_visuals
from . import calendar
from .platform import Platform, Text
from .gamepad import (
    ACTION_ALIASES, ACTION_SYMBOLS, KEY_NAMES, default_key_bindings,
    session_input, set_key_binding,
)
from .render import Renderer
from .imageops import resize_rgb
from .guardian import maybe_start_sighting, pause_sighting_clock
from .haul import haul_cadence
from .book import BOOK_SPECIES_IDS, BOOK_TITLE_STATES, legendary_page, remember_rumor
from .book import take_dream_clue
from . import comfort
from . import encounter
from . import kitchen
from .bookview import (BOOK_TABS, ENTRY_IDS, book_controls, book_layout, contains,
                       move_selection, tracker_species, turn_page)
from .bot import reset as reset_bot
from .bot import summon as summon_bot
from .bot import tick as tick_bot
from .sim import State
from .savepaths import LEGACY_SAVE, load_game_save, resolve_save_path
from .ui import (UI, UIState, SHOP_TABS, HELP_N, GAME_TITLE, CREDITS_HOLD_S, check_rows,
                 comfort_controls, shop_rows, title_options)
from .world import World
from .lakes import travel_caption, travel_lock_reason

DRIVING = {"play"}
MENU_DIRECTIONS = {"up": "w", "down": "s", "left": "a", "right": "d"}
NAVIGATION_KEYS = set(MENU_DIRECTIONS) | set(MENU_DIRECTIONS.values())
DRIVING_KEYS = {"w", "s", "a", "d", "up", "down", "left", "right"}
PAUSE_N = 5
SOUND_CAPTIONS = {
    "bite": "Fish on the line.",
    "bot": "Bot's chime sounds.",
    "sell": "Sale complete.",
    "error": "That action is unavailable.",
    "click": "A soft click sounds.",
    "splash": "A splash breaks the quiet.",
    "hum": "The line hums.",
    "hum_winch": "The winch hums, steady.",
}



def _save_target(root: Path, override: str | Path | None) -> tuple[Path, bool]:
    """Use a local compatibility path if SDL cannot provide the user folder."""
    try:
        return resolve_save_path(override), False
    except RuntimeError:
        if override is not None:
            raise
        return root / "saves" / "save.json", True


class Keys:
    """Enough of Input for a headless tick. `pressed` is the edge set."""

    def __init__(self, pressed=(), held=(), quit=False, focused=True, *,
                 mouse_click=None, mouse_wheel=0, viewport=(1280, 720)):
        self.pressed = set(pressed)
        self.held = set(held) | set(pressed)
        self.quit = quit
        self.focused = bool(focused)
        self.mouse_click, self.mouse_wheel, self.viewport = mouse_click, mouse_wheel, viewport

    def tap(self, name: str, dt: float) -> bool:
        return name in self.pressed


class MenuKeys:
    """Arrow/WASD aliases sharing the real input's held-key repeat behavior."""

    def __init__(self, keys):
        self.keys = keys
        self.pressed = keys.pressed
        self.held = keys.held
        self.physical_keyboard_pressed = getattr(
            keys, "physical_keyboard_pressed", getattr(keys, "keyboard_pressed", keys.pressed))
        self.physical_keyboard_held = getattr(
            keys, "physical_keyboard_held", getattr(keys, "keyboard_held", keys.held))
        self.physical_keyboard_press_order = getattr(
            keys, "physical_keyboard_press_order",
            getattr(keys, "keyboard_press_order", ()))

    def tap(self, name: str, dt: float) -> bool:
        if name not in MENU_DIRECTIONS:
            return self.keys.tap(name, dt)
        arrow = self.keys.tap(name, dt)
        alias = self.keys.tap(MENU_DIRECTIONS[name], dt)
        return arrow or alias

    def __getattr__(self, name):
        return getattr(self.keys, name)


class Session:
    def __init__(self, world: World, save_path: Path, state: State, has_save: bool):
        self.world = world
        self.save_path = Path(save_path)
        self.state = state
        # Offline catch-up ends when this process opens the title screen. Time
        # spent reading there must not be added when Continue is selected.
        self._continue_catchup_at = time.time()
        self._title_catchup_pending = bool(has_save)
        self.focused = True
        self.ui = UIState(has_save=has_save)
        self.quit = False
        self._menu_held: set[str] = set()
        self._input_repeat: dict[str, float] = {}
        self._npc_content = load_content()
        self.quest_manager = QuestManager(self._npc_content)
        autostart_story(self.state, self._npc_content)  # a story step starts once its chapter is open (V1-34)
        self._attach_quest_manager()
        self.conversation = None
        self.ui.dialogue_content = self._npc_content
        self._npc_key = None
        self._refresh_npcs()
        self.stage = None  # the story staging under way (V1-35)
        self.whale_clock = None  # the Star-Whale's return under way (V1-37)
        self.whale_wait = 0.0
        self._whale_recorded = False
        self._replays = self._saved_pending()

    def _saved_pending(self) -> set:
        """Scenes (and the credits) left pending in the save: they replay, and can be skipped."""
        story = self.state.v2.get("story", {}) if isinstance(self.state.v2, dict) else {}
        states = story.get("scene_states", {}) if isinstance(story, dict) else {}
        return {sid for sid, st in states.items() if st == "pending"} if isinstance(states, dict) else set()

    def tick(self, keys, dt: float) -> None:
        self.sound = None
        self.ui.input_device = getattr(keys, "device", self.ui.input_device)
        settings = self.state.v2.get("settings", {}) if isinstance(self.state.v2, dict) else {}
        keys = session_input(keys, settings.get("key_bindings"), self._input_repeat)
        self.focused = bool(getattr(keys, "focused", True))
        if keys.quit:
            if self.ui.mode != "title" or self.ui.has_save:
                self.save()
            self.quit = True
            return
        self._book_presentation(dt)
        driving_presses = keys.pressed & DRIVING_KEYS if self.ui.mode in DRIVING else set()
        self._menu_held.intersection_update(keys.held)
        if self.ui.mode in DRIVING:
            self._menu_held.difference_update(keys.pressed)
        else:
            self._menu_held.update(keys.held & NAVIGATION_KEYS)
        self._refresh_npcs()
        previous_page = (self.ui.mode, self.ui.journal_page, self.ui.book_entry_i)
        self._keys(keys, dt)
        self.state.hauling = self.ui.mode == "haul"
        current_page = (self.ui.mode, self.ui.journal_page, self.ui.book_entry_i)
        if (current_page != previous_page or keys.pressed
                or getattr(keys, "mouse_click", None) is not None
                or getattr(keys, "mouse_wheel", 0)):
            self._remember_book_page()
        self._simulate(keys, dt, driving_presses)
        self._tick_settle(dt)
        self._play_due_scene()
        self._tick_whale(dt)
        self._tick_stage(dt)
        self._tick_caption(dt)

    def _tick_stage(self, dt: float) -> None:
        """Run the staging of the story scene, or the credits, on screen (V1-35)."""
        scene = None
        if self.ui.mode == "credits":
            scene = "credits"
        elif self.ui.mode == "dialogue" and self.conversation is not None:
            scene = self.conversation.node(self._npc_content).get("scene")
        stage_id = staging.stage_of(scene)
        clock = self.stage
        if self.ui.mode == "help" and clock is not None:
            pass  # Help pauses the staging, and returns to it
        elif stage_id is None and clock is not None and not clock.over and not clock.stage.hold \
                and self.ui.mode == "play":
            # A scene read before its staging is done: the rest plays out quickly, so the fog
            # thins and the view comes home instead of cutting.
            clock.t = min(clock.stage.duration, clock.t + dt * staging.RELEASE)
        elif stage_id is None:
            self.stage = None
        elif self.stage is None or self.stage.stage_id != stage_id:
            self.stage = staging.Clock(stage_id, repeat=scene in self._replays)
        elif self.focused:
            self.stage.t += dt
        reduced = bool(self.state.v2.get("settings", {}).get("reduced_motion", False))
        self._tick_vignette(dt)
        active = self.stage if self.stage is not None else self.whale_clock  # a scene's staging comes first
        self.ui.stage_fx = staging.sample(active, reduced=reduced)
        self.ui.stage_skip = self.stage_skippable()
        self.ui.credits_rise = staging.credits_rise(self.stage, reduced=reduced)
        self.state.stage_light = staging.light_overrides(active, reduced=reduced)
        self.ui.whale_return = self.stage is None and self.whale_clock is not None
        # A legendary's scene stills the lake under the haul (V1-37).
        self.state.encounter_still = encounter.water_still(self.ui, reduced=reduced)

    def _tick_whale(self, dt: float) -> None:
        """The Star-Whale comes back to a Skipper settled by the reflection on a clear night,
        after the finale (V1-37, `whale.py`)."""
        from . import whale
        if self.ui.mode != "play" or not self.focused or self.stage is not None:
            return  # menus, scenes and the book pause it
        clock = self.whale_clock
        if clock is None:
            self.whale_wait = self.whale_wait + dt if whale.can_return(self.state, self.world) else 0.0
            if self.whale_wait >= whale.WAIT_S:
                self.whale_clock = staging.Clock("whale_return", repeat=True)
                self.whale_wait, self._whale_recorded = 0.0, False
            return
        still = whale.settled(self.state, self.world)
        before = clock.t
        clock.t += dt * (1.0 if still else staging.RELEASE)  # moving off lets it sink early
        if not self._whale_recorded and before < whale.RISEN_S <= clock.t and still:
            self._whale_recorded = whale.record(self.state, self.world) or True
            self.save()
        if clock.over:
            self.whale_clock = None

    def _skip_whale(self) -> None:
        """Esc (B) skips a returning whale to its end; it has been seen, so it is recorded."""
        from . import whale
        if not self._whale_recorded and whale.settled(self.state, self.world):
            self._whale_recorded = whale.record(self.state, self.world) or True
            self.save()
        self.whale_clock = None

    def _tick_vignette(self, dt: float) -> None:
        """The card beside a story moment's bubble: the book, the collar, the knot (V1-35)."""
        from .vignettes import vignette_for
        found = None
        if self.ui.mode == "dialogue" and self.conversation is not None:
            found = vignette_for(self.conversation.node(self._npc_content), self.conversation, self.state)
        current = self.ui.vignette
        if found is None:
            if self.ui.mode != "help":
                self.ui.vignette = None
        elif current is None or current["kind"] != found[0]:
            self.ui.vignette = {"kind": found[0], "detail": found[1], "t": 0.0}
        else:
            current["detail"] = found[1]  # the highlighted knot follows the selection
            if self.focused:
                current["t"] += dt

    def stage_skippable(self) -> bool:
        """A scene replayed from the save can skip the rest of its staging (V1-35)."""
        clock = self.stage
        return clock is not None and clock.repeat and clock.t < clock.stage.duration

    def _skip_stage(self, keys) -> bool:
        """Esc (B) skips a replayed scene's staging to its last frame; reading keys still read."""
        if "esc" not in keys.pressed or not self.stage_skippable():
            return False
        self.stage.t = self.stage.stage.duration
        return True

    def _play_due_scene(self) -> None:
        """A story scene whose moment has come plays as soon as the Skipper is free (V1-34).
        After the ending, the credits roll once; a game quit during them rolls them again."""
        if self.ui.mode != "play" or self.conversation is not None or not self.focused:
            return
        scene_id = due_scene(self.state, self._npc_content)
        if scene_id is not None:
            self._show_conversation(scene_conversation(self.state, self._npc_content, scene_id))
        elif scene_state(self.state, "credits") == "pending":
            self.ui.settling = False
            self.ui.credits_s = 0.0
            self.ui.mode = "credits"

    def _credits_keys(self, keys, dt: float) -> None:
        """The credits hold for a few seconds before a key returns to play (V1-35 stages the roll)."""
        if self.focused:
            self.ui.credits_s += dt
        if self.ui.credits_s < CREDITS_HOLD_S:
            return
        if keys.pressed or getattr(keys, "mouse_click", None) is not None:
            self.state.set_scene_status("credits", "done")
            self.ui.mode = "play"  # play resumes at the landing (05 §3)
            self.save()

    def _tick_settle(self, dt: float) -> None:
        """Settle In (02 §13.5): real seconds of stillness add up near the calm reflection; moving
        pauses them and nothing resets them. Weather and needs don't interrupt."""
        state, ui = self.state, self.ui
        active = settle_step_active(state, self._npc_content)
        spot = active and settle_spot(state, self.world)
        if not active:
            ui.settling, ui.settle_prompt = False, ""
            return
        from .botidentity import name as bot_name
        settle = settle_progress(state)
        if ui.settling and ui.mode == "play" and self.focused:
            still = spot and abs(state.speed) < 0.1
            for line in settle_tick(state, self.world, dt, still=still):
                state.toast(f"{bot_name(state)}: {line}")
            if settle["cues"] >= 3:
                ui.settling = False
        if ui.settling:
            near = settle_near(state, self.world)
            ui.settle_prompt = (("Watching together" if near else "Watching together, paused. Come back to the reflection.")
                                if settle["together"] else
                                "Settling in. Keep still." if spot else "Settling in, paused. Anchor by the reflection.")
            ui.settle_prompt += f"  ({settle['cues']} of 3)  {{key}} Stop"
        else:
            ui.settle_prompt = "{key}  Settle in" if spot else ""

    def _settling_here(self) -> bool:
        """Settling in by the reflection, where needs and naps wait (02 §13.5). A settle paused
        elsewhere holds nothing off."""
        return self.ui.settling and settle_near(self.state, self.world)

    def _toggle_settle(self) -> bool:
        """The hail key settles in (or stops) while no cat is in range. Progress is kept."""
        if not settle_step_active(self.state, self._npc_content):
            return False
        if self.ui.settling:
            self.ui.settling = False
            return True
        if not settle_spot(self.state, self.world):
            return False
        self.ui.settling = True
        self.state.toast("Settling in. Measure nothing.")
        return True

    def _show_conversation(self, conversation) -> None:
        self.conversation = conversation
        self.ui.conversation = conversation
        self.ui.dialogue_from = self.ui.mode
        self.ui.mode = "dialogue"

    def _remember_book_page(self):
        """Opening a page records its rumor; drawing the book never saves it."""
        if self.ui.mode != "journal" or self.ui.journal_page != 1 or self.ui.book_ceremony:
            return
        sid = ENTRY_IDS[self.ui.book_entry_i % len(ENTRY_IDS)]
        if sid in BOOK_SPECIES_IDS:
            remember_rumor(self.state.v2["book"], sid)
            clue = self.state.v2["book"].get("dream_clue")
            if isinstance(clue, dict) and clue.get("species") == sid:
                take_dream_clue(self.state.v2["book"])
        else:
            legendary_page(sid, self.state.v2)

    def _book_presentation(self, dt):
        events = self.state.take_book_events()
        if events:
            self.ui.book_prompt_species = events[-1]["species"]
            self.ui.book_prompt_timer = 3.0
        else:
            self.ui.book_prompt_timer = max(0.0, self.ui.book_prompt_timer - dt)
            if not self.ui.book_prompt_timer:
                self.ui.book_prompt_species = ""
        if self.ui.mode != "play" or not self.focused or self.world.id != "briar":
            return
        if self.state.slip_status(self.world) != "docked":
            return
        # The ending retitles the book; its new title is shown once the story and credits are told.
        if due_scene(self.state, self._npc_content) is not None or scene_state(self.state, "credits") == "pending":
            return
        book = self.state.v2["book"]
        title = book.get("title", "fishypedia")
        if title not in BOOK_TITLE_STATES:
            return
        seen = book.get("titles_seen", ["fishypedia"])
        if not isinstance(seen, list):
            seen = ["fishypedia"]
        for milestone in BOOK_TITLE_STATES[1:BOOK_TITLE_STATES.index(title) + 1]:
            if milestone not in seen:
                self.ui.book_ceremony = milestone
                self.ui.journal_page = 1
                self.ui.mode = "journal"
                break

    def _tick_caption(self, dt: float) -> None:
        settings = self.state.v2.get("settings", {}) if isinstance(self.state.v2, dict) else {}
        if not settings.get("captions", True):
            self.ui.caption = ""
            self.ui.caption_timer = 0.0
            return
        if self.sound:
            if self.sound == "bot":
                from .bot import chime_caption
                self.ui.caption = chime_caption(self.state)
            else:
                self.ui.caption = SOUND_CAPTIONS.get(self.sound, f"Sound cue: {self.sound}.")
            self.ui.caption_timer = 2.4
        elif self.ui.caption_timer > 0:
            self.ui.caption_timer = max(0.0, self.ui.caption_timer - max(0.0, float(dt)))
            if self.ui.caption_timer == 0:
                self.ui.caption = ""

    def _refresh_npcs(self):
        key = (id(self.state),) + schedule_key(self.state, self.world, self._npc_content)
        if key != self._npc_key:
            self.state.npcs = active_npcs(self.state, self.world, self._npc_content)
            self._npc_key = key

    def save(self) -> None:
        if self._title_catchup_pending and self.ui.has_save:
            self.state.catch_up(now=self._continue_catchup_at)
            self._title_catchup_pending = False
        self._refresh_npcs()
        self.state.save(self.save_path)
        self.ui.has_save = True

    def _attach_quest_manager(self) -> None:
        self.state._quest_event_handler = self.quest_manager.handle_event

    def world_running(self) -> bool:
        """Whether this frame may advance the shared world simulation."""
        return self.focused and self.ui.mode == "play"

    def advance_bulk(self, game_minutes: int) -> tuple[int, int]:
        """Advance online world time for actions such as a future catnap."""
        if not self.world_running():
            return 0, 0
        before = self.state.game_minutes
        result = self.state.advance_bulk(game_minutes)
        self._record_world_advance(before)
        return result

    def _record_world_advance(self, before: float) -> None:
        state = self.state
        elapsed = max(0.0, state.game_minutes - before)
        zone = self.world.zone_at(state.x, state.z)
        state.emit_quest_event({
            "type": "anchor.sample",
            "lake_id": self.world.id,
            "zone_id": f"{self.world.id}:{zone}",
            "game_minute": state.game_minutes,
            "elapsed_game_minutes": elapsed,
            "anchored": state.anchored,
            "engine_idle": (not state.sail_raised and abs(state.throttle) <= 0.01
                            and abs(state.throttle_setting) <= 0.01),
            # For wait_weather and area checks (V1-31). A long advance can cross forecast changes.
            "weather": calendar.weather_at(state),
            "weather_spans": calendar.weather_spans(state, before, state.game_minutes),
            "x": state.x, "z": state.z,
        })
        calendar.active_tick(state, before)
        self._refresh_npcs()

    def _simulate(self, keys, dt: float, driving_presses=()):
        mode = self.ui.mode
        state = self.state
        if self.world_running():
            if comfort.doze_due(state.v2) and not self._settling_here():
                self._start_catnap(forced=True)
                state.tick_toasts(dt)
                return
            comfort.active_time(state.v2, dt)
            # A held menu direction must be released before it drives or looks
            # around, even when Enter/Esc closes the menu in this same tick.
            driving_pressed = set(driving_presses)
            driving_held = set(keys.held)
            # The controller D-pad is navigation only. The left stick supplies
            # W/S/A/D equivalents for throttle and steering while playing.
            pad_navigation = (set(getattr(keys, "gamepad_held", ()))
                              | set(getattr(keys, "gamepad_pressed", ())))
            keyboard_navigation = (set(getattr(keys, "keyboard_held", ()))
                                   | set(getattr(keys, "keyboard_pressed", ())))
            for name in ("up", "down", "left", "right"):
                if name in pad_navigation and name not in keyboard_navigation:
                    driving_held.discard(name)
                    driving_pressed.discard(name)
            driving_keys = Keys(
                pressed=driving_pressed - self._menu_held,
                held=driving_held - self._menu_held,
                focused=self.focused,
            )
            state.drive(dt,_throttle(driving_keys,mode),_steer(driving_keys,mode),self.world,
                        idle=bool((driving_keys.held | keys.pressed) & {"shift","rshift"}),
                        player_controlled=True)
            sound = tick_bot(state, self.world, dt)
            if sound:
                self.sound = sound
            look = 0.0
            if "up" in driving_keys.held:
                look += 1.0
            if "down" in driving_keys.held:
                look -= 1.0
            state.look = max(-0.45, min(0.62, state.look + look * 0.55 * dt))
            hooked_before = state.hooked_total
            game_minute_before = state.game_minutes
            state.advance(dt, frozen=False)
            maybe_start_sighting(state, self.world, mode)
            self._record_world_advance(game_minute_before)
            if state.hooked_total > hooked_before:
                self.sound = "bite"
            self._react_to_nearby_npc()
            if self._speaker_left():
                self._close_dialogue()
        else:
            pause_sighting_clock(state)
            self._refresh_npcs()
            if self._speaker_left():
                self._close_dialogue()
        if self.world_running() and not self._settling_here():  # needs never interrupt Settle In (02 §13.5)
            if comfort.doze_due(state.v2):
                self._start_catnap(forced=True)
            else:
                kind = comfort.next_prompt(state.v2)
                if kind:
                    self.ui.needs_kind = kind
                    self.ui.comfort_i = 0
                    self.ui.mode = "needs"
                    self.save()
        state.tick_toasts(dt)

    def _speaker_left(self) -> bool:
        """A cat who has left ends the conversation. A story scene is read through wherever its
        speaker is; Bot, who speaks some, is never on the lake's roster (V1-34)."""
        chat = self.conversation
        return (chat is not None and not chat.in_scene(self._npc_content)
                and not any(n.id == chat.npc_id for n in self.state.npcs))

    def _react_to_nearby_npc(self):
        npc = nearby_npc(self.state)
        if npc is None:
            return
        note = f"Bot: His brass ears turn toward {npc.name}."
        if self.state.narrative.record_bot_reaction(f"npc:{npc.id}", note):
            self.state.toast(note)

    def _keys(self, keys, dt: float):
        mode = self.ui.mode
        if mode not in DRIVING:
            keys = MenuKeys(keys)
        if mode!="title" and keys.held & {"shift","rshift"}:
            self.state.throttle_setting = 0.0
            self.state.throttle = 0.0
        if "m" in keys.pressed and mode != "title":
            self.state.muted = not self.state.muted
        if mode == "title":
            self._title_keys(keys, dt)
        elif mode in {"new_mode", "needs"}:
            self._comfort_keys(keys, dt)
        elif mode == "catnap":
            if self.focused:
                self.ui.nap_timer = max(0.0, self.ui.nap_timer - dt)
                if keys.pressed or getattr(keys, "mouse_click", None) or not self.ui.nap_timer:
                    self.ui.mode = "play"
        elif mode in {"kitchen", "cook_confirm", "cooking"}:
            self._kitchen_keys(keys, dt)
        elif mode == "play":
            self._play_keys(keys)
        elif mode == "dialogue":
            self._dialogue_keys(keys, dt)
        elif mode == "shop":
            self._shop_keys(keys, dt)
        elif mode == "setbait":
            self._set_keys(keys, dt)
        elif mode == "check":
            self._check_keys(keys, dt)
        elif mode == "haul":
            self._haul_keys(keys, dt)
        elif mode == "journal":
            self._journal_keys(keys, dt)
        elif mode == "well":
            if "t" in keys.pressed or "return" in keys.pressed or "space" in keys.pressed:
                if self.state.toggle_treasured(self.ui.well_i) is None:
                    self.save()
            else:
                n = max(1, len(self.state.well))
                self._list_keys(keys, dt, "well_i", n, "i")
        elif mode == "map":
            if "tab" in keys.pressed or "esc" in keys.pressed:
                self.ui.mode = "play"
            elif "c" in keys.pressed:
                self._hail()
            elif "space" in keys.pressed:
                self._anchor()
            elif "q" in keys.pressed:
                self._sail()
            elif "r" in keys.pressed:
                self._tow()
            elif "b" in keys.pressed:
                self._bot()
        elif mode == "pause":
            self._pause_keys(keys, dt)
        elif mode == "credits":
            self._credits_keys(keys, dt)
        elif mode == "settings":
            self._settings_keys(keys, dt)
        elif mode == "help":
            self._help_keys(keys, dt)

    def _title_keys(self, keys, dt):
        options = title_options(self.ui.has_save)
        if self.ui.confirm_new:
            if "esc" in keys.pressed:
                self.ui.confirm_new = False
            elif "return" in keys.pressed or "space" in keys.pressed:
                self.ui.confirm_new = False
                self.ui.new_mode_i = 0
                self.ui.mode = "new_mode"
            return
        if keys.tap("up", dt):
            self.ui.title_i = (self.ui.title_i - 1) % len(options)
        if keys.tap("down", dt):
            self.ui.title_i = (self.ui.title_i + 1) % len(options)
        if "h" in keys.pressed:
            self._open_help("title")
        if "n" in keys.pressed and self.ui.has_save:
            self.ui.confirm_new = True
        if "return" in keys.pressed or "space" in keys.pressed:
            choice = options[self.ui.title_i % len(options)]
            if choice == "Continue":
                try:
                    self.state = State.load(self.save_path, self.world)
                except (OSError, ValueError, KeyError):
                    self.state.toast("That save could not be read.")
                    return
                self._attach_quest_manager()
                if self._title_catchup_pending:
                    self.state.catch_up(now=self._continue_catchup_at)
                    self._title_catchup_pending = False
                self.ui.mode = "play"
            elif choice == "New morning":
                self.ui.confirm_new = True
            else:
                self.ui.new_mode_i = 0
                self.ui.mode = "new_mode"

    def _comfort_keys(self, keys, dt):
        choosing_mode = self.ui.mode == "new_mode"
        if not choosing_mode and comfort.mode(self.state.v2) != "old_salt":
            self.ui.mode = "play"
            return
        if "esc" in keys.pressed or (not choosing_mode and "f" in keys.pressed):
            if choosing_mode:
                self.ui.mode = "title"
            else:
                comfort.snooze(self.state.v2, self.ui.needs_kind)
                self.ui.mode = "play"
                self.save()
            return
        field = "new_mode_i" if choosing_mode else "comfort_i"
        if any(keys.tap(key, dt) for key in ("left", "right", "up", "down")):
            setattr(self.ui, field, 1 - getattr(self.ui, field))
        select = bool(keys.pressed & {"return", "space"})
        click = getattr(keys, "mouse_click", None)
        if click is not None:
            for index, rect in enumerate(comfort_controls(getattr(keys, "viewport", (1280, 720)))):
                if contains(rect, click):
                    setattr(self.ui, field, index)
                    select = True
        if not select:
            return
        if choosing_mode:
            selected = comfort.MODES[self.ui.new_mode_i]
            previous = deepcopy(self.state.v2["settings"])
            if self.world.id != "briar":
                self.world = World("briar")  # a new game opens at Briar Landing (05 §1)
            state = State.new(self.world)
            state.v2["settings"] = previous
            comfort.change_mode(state.v2, selected)
            state.v2["profile"]["collar"]["visible"] = previous.get("collar_visible", True)
            begin_prologue(state)
            self.state = state
            self._replays = set()
            self._attach_quest_manager()
            self._title_catchup_pending = False
            self.ui = UIState(mode="play", input_device=self.ui.input_device,
                              dialogue_content=self._npc_content)
            self.save()
        else:
            kind, later = self.ui.needs_kind, self.ui.comfort_i == 1
            self.ui.mode = "play"
            if later:
                comfort.snooze(self.state.v2, kind)
            elif kind == "energy":
                self.state.anchored = True
                self._start_catnap()
            elif self.state.v2["pantry"].get("kibble", 0):
                kitchen.snack(self.state)
            self.save()

    def _start_catnap(self, *, forced=False):
        if not self.world_running():
            return False
        before = self.state.game_minutes
        error = self.state.catnap(self.world, forced=forced)
        if error:
            self.state.toast(error)
            return False
        self._record_world_advance(before)
        self.ui.nap_forced = forced
        self.ui.nap_timer = 3.0
        self.ui.mode = "catnap"
        self.save()
        return True

    def _play_keys(self, keys):
        if "esc" in keys.pressed and self.whale_clock is not None:
            self._skip_whale()
            return
        if "esc" in keys.pressed:
            self.ui.mode = "pause"
            self.ui.pause_i = 0
            self.ui.note = ""
            return
        if "h" in keys.pressed:
            self._open_help("play")
            return
        if "z" in keys.pressed:
            self._start_catnap()
            return
        if "k" in keys.pressed:
            self._open_kitchen()
            return
        if "c" in keys.pressed:
            if nearby_npc(self.state) is None and self._toggle_settle():
                return
            self._hail()
            return
        if "space" in keys.pressed:
            self._anchor()
        if "q" in keys.pressed:
            self._sail()
        if "r" in keys.pressed:
            self._tow()
        if "t" in keys.pressed:
            err = self.state.cycle_scale()
            if err:
                self.state.toast(err)
        if "g" in keys.pressed:
            err = self.state.use_chime(self.world)
            if err:
                self.state.toast(err)
        if "tab" in keys.pressed:
            self.ui.mode = "map"
        if "j" in keys.pressed:
            self.ui.mode = "journal"
            self.ui.journal_i = 0
            self.ui.journal_page = 0
            self.ui.journal_quest_i = 0
            self.ui.book_detail_page = 0
            self.ui.book_detail_pages = 1
            clue = self.state.v2["book"].get("dream_clue")
            dream_sid = clue.get("species") if isinstance(clue, dict) else None
            sid = self.ui.book_prompt_species or dream_sid
            if sid in BOOK_SPECIES_IDS:
                self.ui.book_entry_i = BOOK_SPECIES_IDS.index(sid)
                self.ui.journal_i = self.ui.book_entry_i
                self.ui.journal_page = 1
                self.ui.book_prompt_species = ""
        if "i" in keys.pressed:
            self.ui.mode = "well"
            self.ui.well_i = 0
        if "b" in keys.pressed:
            self._bot()
        if "f" in keys.pressed:
            self._open_set()
        if "e" in keys.pressed:
            self._open_e()

    def _hail(self):
        npc = nearby_npc(self.state)
        if npc is None:
            return
        # The hail is an event first, so a talk_to step can make its quest ready.
        first = record_hail(self.state, self.world, npc)
        cookout_chat = calendar.chat(self.state, self.world, npc.id, self._npc_content)
        if kitchen.teach(self.state, npc.id) or cookout_chat:
            self.save()
        conversation = open_conversation(npc, self.state, self._npc_content, first=first, world=self.world)
        if conversation is None:
            # A cat with nothing to say yet (no quest on offer, no greeting) waves.
            if not cookout_chat:
                self.state.toast(f"{npc.name} waves hello.")
            return
        self._show_conversation(conversation)

    def _close_dialogue(self):
        self.conversation = None
        self.ui.conversation = None
        self.ui.mode = self.ui.dialogue_from

    def _dialogue_keys(self, keys, dt):
        chat = self.conversation
        if self._skip_stage(keys):
            return
        if "esc" in keys.pressed and not (chat is not None and chat.in_scene(self._npc_content)):
            # A story scene is read through; closing the game mid-scene replays it (V1-34).
            self._close_dialogue()
            return
        if "h" in keys.pressed:
            self._open_help("dialogue")
            return
        if chat is None:
            self._close_dialogue()
            return
        node = chat.node(self._npc_content)
        choices = node.get('choices', [])
        if choices:
            if keys.tap("up", dt):
                chat.selected = (chat.selected - 1) % len(choices)
            if keys.tap("down", dt):
                chat.selected = (chat.selected + 1) % len(choices)
        select = bool(keys.pressed & {"return", "space", "c"})
        for i in range(len(choices)):
            if str(i + 1) in keys.pressed:
                chat.selected = i
                select = True
                break
        if select:
            more = chat.advance(self.state, self._npc_content)
            if chat.finished_scene:
                chat.finished_scene = False
                self.save()  # a scene's effects and its claim are written together (06 §3.3)
            if not more:
                self._close_dialogue()
                if chat.trip:
                    self._free_trip(chat.trip)

    def _anchor(self):
        if self.state.anchored:
            self.state.anchored = False
            self.state.toast("Anchor up.")
        else:
            self.state.anchored = True
            self.state.throttle_setting = 0.0
            self.state.throttle = 0.0
            self.state.sail_raised = False
            self.state.toast("Anchor down.")

    def _sail(self):
        error = self.state.toggle_sail()
        if error:
            self.state.toast(error)

    def _bot(self):
        sound = summon_bot(self.state, self.world)
        if sound:
            self.sound = sound

    def _tow(self):
        if not self.world_running():
            return
        before = self.state.game_minutes
        error = self.state.tow_to_landing(self.world)
        if error:
            self.state.toast(error)
        else:
            reset_bot(self.state)
            self._record_world_advance(before)

    def change_lake(self,lake_id):
        if self.state.lines:
            return "Pick up your deployed lines before towing to another lake."
        if self.state.slip_status(self.world)!="docked" or abs(self.state.speed)>=0.45:
            return "Return to the landing to tow to another lake."
        if lake_id==self.world.id:
            return "You are already on this lake."
        error = travel_lock_reason(self.state, lake_id)
        if error:
            return error
        self._travel_to(lake_id)
        return None

    def _free_trip(self, lake_id: str) -> None:
        """The trip home after the Star-Whale, offered once and taken from wherever the boat is
        (02 §13). Deployed lines must come aboard first; the landing's travel still works."""
        if lake_id == self.world.id:
            return
        if self.state.lines:
            self.state.toast("Bring your lines aboard; the landing can take you home any time.")
            return
        self._travel_to(lake_id)

    def _travel_to(self, lake_id: str) -> None:
        caption = travel_caption(self.world.id, lake_id)
        destination = World(lake_id)
        self.world = destination
        self.state.bind(destination)
        self.state.rowboat_charge_kwh_this_visit = 0.0
        self.state._park(destination)
        reset_bot(self.state)
        self.ui.mode = "play"
        self.ui.settling = False  # Settle In is kept, and taken up again by the reflection
        self.stage = None  # a staging stays on the lake it was staged on (V1-35)
        self.ui.note = ""
        self.state.toast(caption)
        self.save()
        return None

    def _open_help(self, origin: str):
        self.ui.help_from = origin
        self.ui.help_page = 0
        self.ui.mode = "help"

    def _open_set(self):
        if abs(self.state.speed) > 0.5:
            self.state.toast("Idle the boat before you set.")
            return
        if not self.state.held:
            self.state.toast("Every line you own is already in the water.")
            return
        self.ui.mode = "setbait"
        self.ui.set_line = 0
        prefer = self.state.preferred_bait
        self.ui.set_bait = next((i for i, b in enumerate(BAITS) if b.id == prefer), 0)
        self.ui.set_sections = 1
        self.ui.set_section = 0
        self.ui.set_section_baits = (self.ui.set_bait,) * 3
        self.ui.note = ""

    def _open_e(self):
        status = self.state.slip_status(self.world)
        if status == "docked" and abs(self.state.speed) < 0.45:
            self.ui.mode = "shop"
            self.ui.shop_tab = 0
            self.ui.shop_i = 0
            self.ui.note = ""
            return
        if status == "slip":
            self.state.toast("Nose up to the dock.")
            return
        nearest = self.state.nearest_line()
        if nearest is not None and abs(self.state.speed) < 1.4:
            self.ui.mode = "haul"
            self.ui.check_line = nearest
            self.ui.check_i = 0
            self.ui.haul_index = 0
            self.ui.haul_timer = 0.0
            self.ui.haul_phase = "rise"
            self.ui.haul_phase_timer = 0.0
            self.ui.haul_badge_enabled = True
            self.ui.haul_legendary = ""
            self.ui.haul_encounter_only = False
            self.ui.note = ""
            if self.state.prepare_catch_dispositions(nearest):
                self.ui.note = "The livewell is full. I picked the smallest to swim home. You can change that."
            line = self.state.lines[nearest]
            self.ui.haul_picnic_factor = comfort.haul_factor(self.state)
            self.ui.haul_picnic_started = False
            catches_on_line = {}
            for hook in line.hooks:
                if hook.catch is not None:
                    catches_on_line[hook.catch.species] = catches_on_line.get(hook.catch.species, 0) + 1
            self.ui.haul_counts_before = {
                species: max(0, int(record.get("count", 0)) - catches_on_line.get(species, 0))
                for species, record in self.state.journal.items()
                if isinstance(record, dict)
            }
            self.state.emit_quest_event({
                "type": "line.check",
                "lake_id": self.state.lake_id,
                "zone_id": f"{self.state.lake_id}:{line.zone}",
                "line_id": line.line_id,
                "game_minute": self.state.game_minutes,
                "active_game_minute": self.state.narrative.active_play_game_minutes,
                "bait_sections": list(line.bait_sections),
                "eligible_catch_records": [
                    {
                        "species_id": hook.catch.species,
                        "source_line_id": line.line_id,
                        "lake_id": self.state.lake_id,
                        "source_zone_id": f"{self.state.lake_id}:{line.zone}",
                        "bait_id": hook.catch.bait,
                        "bait_sections": list(line.bait_sections),
                        "catch_game_minute": hook.catch.catch_game_minute,
                    }
                    for hook in line.hooks if hook.catch is not None
                ],
            })
            if line.zone == "current" and self.state.owns_tool("zero_g_winch"):
                # The winch held this line against the current while it soaked.
                self.state.emit_tool_use(self.world, "zero_g_winch", line.zone)
            settings = self.state.v2.get("settings", {}) if isinstance(self.state.v2, dict) else {}
            if settings.get("haul_speed") == "instant":
                self._start_haul_perk(line)
                first = next((i for i, hook in enumerate(line.hooks) if encounter.is_legendary(hook.catch)
                              and not encounter.presented(self.state.v2, hook.catch.species)), None)
                if first is not None:
                    # Instant hauls skip to the summary, but a legendary's first scene still plays (02 §7.2).
                    self.ui.haul_index = first
                    self.ui.haul_encounter_only = True
                    self._begin_encounter(line.hooks[first])
                    return
                self.ui.mode = "check"
            return
        self.state.toast("Nothing here to check.")

    def _start_haul_perk(self, line):
        if self.ui.haul_picnic_started or not line.hooks:
            return
        before = comfort.active_buff(self.state)
        self.ui.haul_picnic_factor = comfort.begin_haul(self.state, line)
        self.ui.haul_picnic_started = True
        if before and before.effect in {"quick_haul", "keep_bait", "shiny_credit"}:
            self.save()

    def _haul_keys(self, keys, dt: float) -> None:
        if not self.focused:
            return
        index = self.ui.check_line
        if index < 0 or index >= len(self.state.lines):
            self.ui.mode = "play"
            return
        line = self.state.lines[index]
        if not line.hooks:
            self.ui.mode = "check"
            return
        if self.ui.haul_phase == "encounter" and self.ui.haul_index < len(line.hooks):
            self._encounter_keys(keys, dt, line.hooks[self.ui.haul_index])
            return
        if "esc" in keys.pressed:
            self._start_haul_perk(line)
            self.ui.mode = "check"
            self.ui.check_i = 0
            self.ui.haul_legendary = ""
            self.ui.haul_encounter_only = False
            return

        settings = self.state.v2.get("settings", {}) if isinstance(self.state.v2, dict) else {}
        speed = settings.get("haul_speed", "normal")
        if speed not in {"normal", "quick", "instant"}:
            speed = "normal"
        if speed == "instant" and not self.ui.haul_encounter_only:
            self._start_haul_perk(line)
            self.ui.mode = "check"
            self.ui.check_i = 0
            return
        cadence = haul_cadence(self.state) * self.ui.haul_picnic_factor
        multiplier = 3.0 if "e" in keys.held else 1.0
        step = max(0.0, float(dt)) * multiplier
        if self.ui.haul_index >= len(line.hooks):
            self.ui.mode = "check"
            self.ui.check_i = 0
            return
        if self.ui.haul_phase == "card" and keys.pressed - {"e"}:
            # A legendary's page stands a moment first, so keys pressed through its scene don't
            # turn it unread.
            if not (encounter.is_legendary(line.hooks[self.ui.haul_index].catch)
                    and self.ui.haul_phase_timer < encounter.PAGE_SETTLE_S):
                self._next_haul_hook()
                return

        remaining = step
        for _ in range(len(line.hooks) * 3 + 4):
            if remaining <= 1e-9 or self.ui.mode != "haul":
                return
            if self.ui.haul_index >= len(line.hooks):
                self.ui.mode = "check"
                self.ui.check_i = 0
                return
            hook = line.hooks[self.ui.haul_index]
            if self.ui.haul_phase == "encounter":
                return  # the scene keeps its own clock (`_encounter_keys`)
            if self.ui.haul_phase == "card":
                # A legendary's book page holds longer than a fish card.
                hold = encounter.PHOTO_S if encounter.is_legendary(hook.catch) else 1.2
                needed = max(0.0, hold - self.ui.haul_phase_timer)
                used = min(remaining, needed)
                self.ui.haul_phase_timer += used
                remaining -= used
                if self.ui.haul_phase_timer + 1e-9 >= hold:
                    self._next_haul_hook()
                    continue
                return
            if self.ui.haul_phase == "surface":
                needed = max(0.0, 0.24 - self.ui.haul_phase_timer)
                used = min(remaining, needed)
                self.ui.haul_phase_timer += used
                remaining -= used
                if self.ui.haul_phase_timer + 1e-9 >= 0.24:
                    self.ui.haul_phase = "card"
                    self.ui.haul_phase_timer = 0.0
                    if hook.catch is not None:
                        self.ui.haul_badge_enabled = not hook.catch.haul_seen
                        hook.catch.haul_seen = True
                    continue
                return
            needed = max(0.0, cadence - self.ui.haul_timer)
            used = min(remaining, needed)
            self.ui.haul_timer += used
            remaining -= used
            if self.ui.haul_timer + 1e-9 < cadence:
                return
            self._start_haul_perk(line)
            if encounter.is_legendary(hook.catch):
                self._begin_encounter(hook)
                return
            if hook.catch is not None:
                self.ui.haul_phase = "surface"
                self.ui.haul_timer = cadence
                self.ui.haul_phase_timer = 0.0
            else:
                self._next_haul_hook()

    def _begin_encounter(self, hook) -> None:
        """The haul slows into the legendary's calm scene (V1-37, 02 §7.2)."""
        self.ui.mode = "haul"
        self.ui.haul_phase = "encounter"
        self.ui.haul_phase_timer = 0.0
        self.ui.haul_timer = haul_cadence(self.state) * self.ui.haul_picnic_factor
        self.ui.haul_legendary = hook.catch.species

    def _encounter_keys(self, keys, dt: float, hook) -> None:
        """The scene runs on its own clock. Seen once, it can be skipped (Esc / B, or any key
        but E) or hurried (hold E); the first time nothing does either."""
        if not encounter.is_legendary(hook.catch):
            self._next_haul_hook()
            return
        legendary_id = hook.catch.species
        repeat = encounter.presented(self.state.v2, legendary_id)
        if repeat and keys.pressed - {"e"}:
            self._finish_encounter(hook)
            return
        t0 = self.ui.haul_phase_timer
        step = max(0.0, float(dt)) * (3.0 if repeat and "e" in keys.held else 1.0)
        self.ui.haul_phase_timer = min(encounter.SCENE_S, t0 + step)
        if encounter.hum_due(t0, self.ui.haul_phase_timer):
            self.sound = "hum_winch" if encounter.variant(self.state) == "winch" else "hum"
        if self.ui.haul_phase_timer + 1e-9 >= encounter.SCENE_S:
            self._finish_encounter(hook)

    def _finish_encounter(self, hook) -> None:
        """The scene is over: the book page, with the photo and the release, comes up."""
        encounter.mark_presented(self.state.v2, hook.catch.species)
        self.ui.haul_phase = "card"
        self.ui.haul_phase_timer = 0.0
        self.ui.haul_badge_enabled = not hook.catch.haul_seen
        hook.catch.haul_seen = True

    def _next_haul_hook(self) -> None:
        self.ui.haul_index += 1
        self.ui.haul_timer = 0.0
        self.ui.haul_phase = "rise"
        self.ui.haul_phase_timer = 0.0
        self.ui.haul_legendary = ""
        if self.ui.haul_encounter_only:
            # An instant haul played its legendary's first scene; the summary follows.
            self.ui.haul_encounter_only = False
            self.ui.mode = "check"
            self.ui.check_i = 0
            return
        if self.ui.check_line >= len(self.state.lines) or (
                self.ui.check_line < 0
                or self.ui.haul_index >= len(self.state.lines[self.ui.check_line].hooks)):
            self.ui.mode = "check"
            self.ui.check_i = 0

    def _open_kitchen(self):
        self.ui.kitchen_from = self.ui.mode
        self.ui.mode = "kitchen"
        self.ui.shop_i = 0
        self.ui.note = ""

    def _kitchen_menu_keys(self, keys, rows, dt):
        if keys.tap("up", dt):
            self.ui.shop_i = (self.ui.shop_i - 1) % len(rows)
            self.ui.note = ""
        if keys.tap("down", dt):
            self.ui.shop_i = (self.ui.shop_i + 1) % len(rows)
            self.ui.note = ""
        select = bool(keys.pressed & {"return", "space"})
        click = getattr(keys, "mouse_click", None)
        if click is not None:
            for index, rect in self.ui.kitchen_hitboxes:
                if contains(rect, click) and index < len(rows):
                    self.ui.shop_i, select = index, True
        if select:
            row = rows[self.ui.shop_i % len(rows)]
            self.sound = self._buy(row) if row.kind.startswith("bot_") else self._kitchen_action(row)

    def _kitchen_action(self, row):
        if not row.enabled:
            return self._fail(row.blurb)
        if row.kind in {"dish", "recipe", "cookout"}:
            self.ui.cook_from = self.ui.mode
            self.ui.cook_kind, self.ui.cook_arg = row.kind, row.arg
            self.ui.cook_label = (kitchen.DISHES[row.arg].name if row.kind == "dish"
                                  else "Sunday landing cookout" if row.kind == "cookout" else BAIT_BY_ID[row.arg].name)
            self.ui.cook_fish = self.ui.comfort_i = 0
            self.ui.note = ""
            self.ui.mode = "cook_confirm"
            return "click"
        error = None
        if row.kind == "ingredient":
            error = kitchen.buy_ingredient(self.state, self.world, row.arg)
        elif row.kind == "dish_card":
            error = kitchen.buy_card(self.state, self.world, row.arg)
        elif row.kind == "snack":
            error = kitchen.snack(self.state)
        elif row.kind == "weather":
            error = comfort.weather_invitation(self.state)
        elif row.kind == "cookout_chat":
            calendar.chat(self.state, self.world, row.arg, self._npc_content)
        elif row.kind == "teach":
            kitchen.teach(self.state, row.arg)
        if error:
            return self._fail(error)
        self.ui.note = ""
        self.save()
        return "click"

    def _kitchen_keys(self, keys, dt):
        if not self.focused:
            return
        if self.ui.mode == "cooking":
            self.ui.cook_timer = max(0., self.ui.cook_timer - dt)
            if keys.pressed or getattr(keys, "mouse_click", None) or not self.ui.cook_timer:
                self.ui.mode = self.ui.cook_from
            return
        if "esc" in keys.pressed:
            self.ui.mode = (self.ui.kitchen_from if self.ui.mode == "kitchen"
                            else self.ui.cook_from)
            self.ui.note = ""
            self.save()
            return
        if self.ui.mode == "kitchen":
            self._kitchen_menu_keys(keys, kitchen.rows(self.state, self.world), dt)
            return
        if keys.tap("up", dt):
            self.ui.cook_fish -= 1
        if keys.tap("down", dt):
            self.ui.cook_fish += 1
        if keys.tap("left", dt) or keys.tap("right", dt):
            self.ui.comfort_i = 1 - self.ui.comfort_i
        select = bool(keys.pressed & {"return", "space"})
        click = getattr(keys, "mouse_click", None)
        if click is not None:
            for index, rect in enumerate(comfort_controls(getattr(keys, "viewport", (1280, 720)))):
                if contains(rect, click):
                    self.ui.comfort_i, select = index, True
        if not select:
            return
        if self.ui.comfort_i:
            self.ui.mode = self.ui.cook_from
            return
        if self.ui.cook_kind == "cookout":
            fish = kitchen.eligible_fish(self.state, "any", food_only=False)
            chosen = fish[self.ui.cook_fish % len(fish)] if fish else None
            gift = kitchen.PANTRY[calendar.cookout_gift(self.state)].name
            error = calendar.share_fish(self.state, self.world, chosen)
            text = "Your fish joins the table. " + gift + " joins your pantry. Stay for the company."
        elif self.ui.cook_kind == "dish":
            dish = kitchen.DISHES[self.ui.cook_arg]
            fish = kitchen.eligible_fish(self.state, dish.food)
            chosen = fish[self.ui.cook_fish % len(fish)] if fish else None
            error = kitchen.cook_dish(self.state, self.world, dish.id, chosen)
            text = dish.blurb
        else:
            error = kitchen.cook_bait(self.state, self.world, self.ui.cook_arg)
            text = "A cooked dozen, ready for your lines."
        if error:
            self._fail(error)
            return
        self.ui.note = ""
        self.ui.cook_text, self.ui.cook_timer = text, 2.0
        self.ui.mode = "cooking"
        self.save()

    def _shop_keys(self, keys, dt):
        if "esc" in keys.pressed:
            self.ui.mode = "play"
            self.save()
            return
        if keys.tap("left", dt):
            self.ui.shop_tab = (self.ui.shop_tab - 1) % len(SHOP_TABS)
            self.ui.shop_i = 0
            self.ui.note = ""
        if keys.tap("right", dt):
            self.ui.shop_tab = (self.ui.shop_tab + 1) % len(SHOP_TABS)
            self.ui.shop_i = 0
            self.ui.note = ""
        rows = shop_rows(self.state, self.ui.shop_tab)
        if self.ui.shop_tab in (6, 7):
            self._kitchen_menu_keys(keys, rows, dt)
            return
        if rows and keys.tap("up", dt):
            self.ui.shop_i = (self.ui.shop_i - 1) % len(rows)
            self.ui.note = ""
        if rows and keys.tap("down", dt):
            self.ui.shop_i = (self.ui.shop_i + 1) % len(rows)
            self.ui.note = ""
        if rows and ("return" in keys.pressed or "space" in keys.pressed):
            self.sound = self._buy(rows[self.ui.shop_i % len(rows)])

    def _buy(self, row):
        state = self.state
        err = None
        if row.kind in {"bot_shell", "bot_tool", "bot_knot"}:
            from . import botidentity
            if not row.enabled:
                return self._fail(row.blurb)
            if row.kind == "bot_shell":
                err = botidentity.swap_shell(state, self.world, row.arg)
            elif row.kind == "bot_tool":
                err = botidentity.buy_tool(state, self.world, row.arg)
            elif not botidentity.at_landing(state, self.world):
                err = "Tie the collar at a landing while stopped."
            else:
                err = botidentity.choose_knot(state, row.arg)
            if err:
                return self._fail(err)
            self.ui.note = ""
            self.save()
            return "bot" if row.kind == "bot_shell" else "click"
        if row.kind in {"ingredient", "dish_card", "dish", "recipe", "snack", "weather", "teach", "cookout", "cookout_chat"}:
            return self._kitchen_action(row)
        if not row.enabled and row.kind != "paint":
            self.ui.note = row.blurb or "Not for sale."
            return "error"
        if row.kind == "sell_all":
            msg = state.sell_all()
            self.ui.note = "" if state.well or msg.startswith("Sold") else msg
            if msg.startswith("Sold"):
                self.ui.note = ""
                return "sell"
            self.ui.note = msg
            return "error"
        if row.kind == "sell_one":
            err = state.sell_index(int(row.arg))
            return "sell" if err is None else self._fail(err)
        if row.kind == "bait":
            err = state.buy_bait(row.arg)
        elif row.kind == "motor":
            err = state.buy_motor()
        elif row.kind == "well":
            err = state.buy_well()
        elif row.kind == "box":
            err = state.buy_box()
        elif row.kind == "finder":
            err = state.buy_finder()
        elif row.kind == "light":
            err = state.buy_light()
        elif row.kind == "line":
            err = state.buy_line(row.arg)
        elif row.kind == "boat":
            err = state.buy_boat(row.arg,self.world)
        elif row.kind == "fuel":
            err = state.refuel()
        elif row.kind == "trolling_motor":
            err = state.buy_rowboat_trolling_motor()
        elif row.kind == "battery":
            err = state.charge_rowboat_battery()
        elif row.kind == "lake":
            err = self.change_lake(row.arg)
        elif row.kind == "paint":
            slot, pid = row.arg.split(":", 1)
            err = state.buy_paint(slot, pid)
        if err:
            return self._fail(err)
        self.ui.note = ""
        return "click"

    def _fail(self, err: str):
        self.ui.note = err
        self.sound = "error"
        return "error"

    def _set_keys(self, keys, dt):
        if "esc" in keys.pressed or not self.state.held:
            self.ui.mode = "play"
            return
        if keys.tap("left", dt):
            self.ui.set_line = (self.ui.set_line - 1) % len(self.state.held)
            self.ui.note = ""
        if keys.tap("right", dt):
            self.ui.set_line = (self.ui.set_line + 1) % len(self.state.held)
            self.ui.note = ""
        section_baits = list(self.ui.set_section_baits)
        old_sections = self.ui.set_sections
        if "q" in keys.pressed or "g" in keys.pressed:
            self.ui.set_sections = self.ui.set_sections % 3 + 1
            for i in range(old_sections, self.ui.set_sections):
                section_baits[i] = self.ui.set_bait
            self.ui.set_section %= self.ui.set_sections
            self.ui.set_bait = section_baits[self.ui.set_section]
            self.ui.set_section_baits = tuple(section_baits)
            self.ui.note = ""
        if "tab" in keys.pressed:
            self.ui.set_section = (self.ui.set_section + 1) % self.ui.set_sections
            self.ui.set_bait = section_baits[self.ui.set_section]
            self.ui.note = ""
        if keys.tap("up", dt):
            self.ui.set_bait = (self.ui.set_bait - 1) % len(BAITS)
            section_baits[self.ui.set_section] = self.ui.set_bait
            self.ui.set_section_baits = tuple(section_baits)
            self.ui.note = ""
        if keys.tap("down", dt):
            self.ui.set_bait = (self.ui.set_bait + 1) % len(BAITS)
            section_baits[self.ui.set_section] = self.ui.set_bait
            self.ui.set_section_baits = tuple(section_baits)
            self.ui.note = ""
        for i, name in enumerate("12345"):
            if name in keys.pressed:
                self.ui.set_bait = i
                section_baits[self.ui.set_section] = self.ui.set_bait
                self.ui.set_section_baits = tuple(section_baits)
                self.ui.note = ""
        if "return" in keys.pressed or "space" in keys.pressed:
            baits = [BAITS[index % len(BAITS)].id
                     for index in self.ui.set_section_baits[:self.ui.set_sections]]
            err = self.state.try_set(self.world, self.ui.set_line, baits)
            if err:
                self.ui.note = err
                self.sound = "error"
                return
            self.ui.mode = "play"
            self.sound = "splash"
            return

    def _check_keys(self, keys, dt):
        if "esc" in keys.pressed or self.ui.check_line >= len(self.state.lines):
            self.ui.mode = "play"
            return
        rows = check_rows(self.state, self.ui.check_line)
        if not rows:
            self.ui.mode = "play"
            return
        if keys.tap("up", dt):
            self.ui.check_i = (self.ui.check_i - 1) % len(rows)
            self.ui.note = ""
        if keys.tap("down", dt):
            self.ui.check_i = (self.ui.check_i + 1) % len(rows)
            self.ui.note = ""
        selected = rows[self.ui.check_i % len(rows)]
        if selected.kind == "hook" and keys.pressed & {"left", "right"}:
            self._check_act(selected)
        elif "return" in keys.pressed or "space" in keys.pressed:
            self._check_act(selected)

    def _check_act(self, row):
        index = self.ui.check_line
        if row.kind == "hook":
            err = self.state.toggle_catch_disposition(index, int(row.arg))
            if err:
                self.ui.note = err
                return "error"
            catch = self.state.lines[index].hooks[int(row.arg)].catch
            self.ui.note = ("Marked for Release." if catch and catch.disposition == "release"
                            else "Marked to Keep.")
            self.save()
            return "click"
        if row.kind == "take_all":
            msg = self.state.take_all(index)
            self.ui.note = "" if msg.startswith("Resolved") else msg
            if msg.startswith("Resolved"):
                self.save()
            return "click" if msg.startswith("Resolved") else "error"
        if row.kind == "rebait":
            err = self.state.rebait(index)
            if err:
                return self._fail(err)
            self.ui.note = ""
            return "click"
        if row.kind == "pull":
            err = self.state.pull_line(index)
            if err:
                return self._fail(err)
            self.ui.mode = "play"
            self.save()
            return "click"
        return None

    def _list_keys(self, keys, dt, field: str, count: int, close_key: str):
        if "esc" in keys.pressed or close_key in keys.pressed:
            self.ui.mode = "play"
            return
        if count <= 0:
            return
        if keys.tap("up", dt):
            setattr(self.ui, field, (getattr(self.ui, field) - 1) % count)
        if keys.tap("down", dt):
            setattr(self.ui, field, (getattr(self.ui, field) + 1) % count)

    def _journal_keys(self, keys, dt):
        click = getattr(keys, "mouse_click", None)
        viewport = getattr(keys, "viewport", (1280, 720))
        if self.ui.book_ceremony:
            if keys.pressed & {"return", "space", "esc", "j"} or click is not None:
                book = self.state.v2["book"]
                seen = book.setdefault("titles_seen", ["fishypedia"])
                if not isinstance(seen, list):
                    seen = book["titles_seen"] = ["fishypedia"]
                if self.ui.book_ceremony not in seen:
                    seen.append(self.ui.book_ceremony)
                self.ui.book_ceremony = ""
                self.save()
                if keys.pressed & {"esc", "j"}:
                    self.ui.mode = "play"
            return
        if "esc" in keys.pressed or "j" in keys.pressed:
            self.ui.mode = "play"
            self.save()
            return
        if "f" in keys.pressed:
            self._toggle_book_tracker()
            return
        layout = book_layout(*viewport)
        if click is not None:
            for name, rect in book_controls(layout, self.state, self.ui).items():
                if contains(rect, click):
                    if name == "close":
                        self.ui.mode = "play"
                        self.save()
                    elif name == "turn":
                        turn_page(self.state, self.ui, viewport)
                    elif name == "tracker":
                        self._toggle_book_tracker()
                    else:
                        move_selection(self.state, self.ui, self._npc_content,
                                       -1 if name == "previous" else 1)
                    return
            for index, rect in enumerate(layout.tabs):
                if contains(rect, click):
                    self.ui.journal_page = index
                    self.ui.book_detail_page = 0
                    self.ui.book_detail_pages = 1
                    if index == 1:
                        self.ui.book_entry_i = self.ui.journal_i
                    return
            if self.ui.journal_page == 0:
                start = self.ui.journal_i // layout.capacity * layout.capacity
                for offset, rect in enumerate(layout.cells()):
                    if contains(rect, click) and start + offset < len(BOOK_SPECIES_IDS):
                        self.ui.journal_i = start + offset
                        turn_page(self.state, self.ui, viewport)
                        return
            if self.ui.journal_page == 5:
                from .bookview import week_rects
                for index, rect in enumerate(week_rects(layout)):
                    if contains(rect, click):
                        self.ui.book_week_i = index
                        self.ui.book_detail_page = 0
                        return
        left = keys.tap("left", dt)
        right = keys.tap("right", dt)
        if left or right:
            self.ui.journal_page = (self.ui.journal_page + (1 if right else -1)) % len(BOOK_TABS)
            self.ui.book_detail_page = 0
            self.ui.book_detail_pages = 1
            if self.ui.journal_page == 1:
                self.ui.book_entry_i = self.ui.journal_i
            return
        if keys.tap("up", dt):
            move_selection(self.state, self.ui, self._npc_content, -1)
        if keys.tap("down", dt):
            move_selection(self.state, self.ui, self._npc_content, 1)
        wheel = getattr(keys, "mouse_wheel", 0)
        if wheel:
            move_selection(self.state, self.ui, self._npc_content, -wheel)
        if keys.pressed & {"return", "space"}:
            turn_page(self.state, self.ui, viewport)

    def _toggle_book_tracker(self):
        sid = tracker_species(self.state, self.ui)
        if sid is None:
            if self.ui.journal_page == 2 and self.ui.book_shelf == 2:
                self._toggle_rail_trophy()
            return
        target = None if self.state.v2["book"].get("tracked") == sid else sid
        if self.state.set_shiny_tracker(target) is None:
            self.save()

    def _toggle_rail_trophy(self):
        """F on the Trophy shelf hangs the replica on this boat's rail, or takes it down (V1-37)."""
        from .bookview import trophy_items
        items = trophy_items(self.state)
        if not items:
            return
        kind, item_id = items[self.ui.book_collection_i % len(items)][:2]
        if kind == "witnessed":
            return
        if (kind, item_id) in self.state.rail_trophies():
            self.state.unmount_trophy(kind, item_id)
            self.state.toast("Taken down. The book keeps it.")
        else:
            mount = self.state.mount_legendary_replica if kind == "legendary" else self.state.mount_shiny_trophy
            refused = mount(item_id)
            if refused:
                self.state.toast(refused)
                return
            self.state.toast("Hung on the rail.")
        self.save()

    def _pause_keys(self, keys, dt):
        if keys.pressed & {"k", "b"}:
            self._open_kitchen()
            return
        if keys.pressed & {"z", "f"}:
            self.ui.mode = "play"
            if not self._start_catnap():
                self.ui.mode = "pause"
                self.ui.note = "Anchor or dock for a catnap."
            return
        if "esc" in keys.pressed:
            self.ui.mode = "play"
            return
        if keys.tap("up", dt):
            self.ui.pause_i = (self.ui.pause_i - 1) % PAUSE_N
        if keys.tap("down", dt):
            self.ui.pause_i = (self.ui.pause_i + 1) % PAUSE_N
        if "return" in keys.pressed or "space" in keys.pressed:
            choice = self.ui.pause_i
            if choice == 0:
                self.ui.mode = "play"
            elif choice == 1:
                self.ui.settings_page = "main"
                self.ui.settings_i = 0
                self.ui.mode = "settings"
            elif choice == 2:
                self._open_help("pause")
            elif choice == 3:
                self.save()
                self._continue_catchup_at = self.state.stamp
                self._title_catchup_pending = True
                self.ui.mode = "title"
                self.ui.title_i = 0
                self.ui.confirm_new = False
            else:
                self.save()
                self.quit = True

    def _settings_keys(self, keys, dt: float) -> None:
        if self.ui.settings_page == "keys":
            self._keybindings_keys(keys, dt)
            return
        if "esc" in keys.pressed:
            self.ui.mode = "pause"
            return
        rows = self.ui.settings_i
        settings = self.state.v2.setdefault("settings", {})
        if keys.tap("up", dt):
            self.ui.settings_i = (self.ui.settings_i - 1) % 12
        elif keys.tap("down", dt):
            self.ui.settings_i = (self.ui.settings_i + 1) % 12
        elif keys.tap("left", dt):
            self._adjust_setting(rows, -1)
        elif keys.tap("right", dt):
            self._adjust_setting(rows, 1)
        elif "return" in keys.pressed or "space" in keys.pressed:
            if rows == 11:
                self.ui.settings_page = "keys"
                self.ui.key_binding_i = 0
                self.ui.capturing_key = False
            else:
                self._adjust_setting(rows, 1)

    def _adjust_setting(self, row: int, direction: int) -> None:
        settings = self.state.v2.setdefault("settings", {})
        if row == 0:
            mode = settings.get("mode", self.state.v2.get("mode", "cozy"))
            mode = "old_salt" if mode == "cozy" else "cozy"
            comfort.change_mode(self.state.v2, mode)
        elif row == 1:
            current = settings.get("text_size", 1)
            if type(current) is not int or current not in range(3):
                current = 1
            settings["text_size"] = (current + direction) % 3
        elif row == 2:
            settings["dyslexia_font"] = not bool(settings.get("dyslexia_font", False))
        elif row == 3:
            settings["reduced_motion"] = not bool(settings.get("reduced_motion", False))
        elif row == 4:
            speeds = ("normal", "quick", "instant")
            current = settings.get("haul_speed", "normal")
            if current not in speeds:
                current = "normal"
            settings["haul_speed"] = speeds[(speeds.index(current) + (1 if direction >= 0 else -1)) % len(speeds)]
        elif row == 5:
            settings["captions"] = not bool(settings.get("captions", True))
        elif 6 <= row <= 9:
            name = ("master", "music", "ambience", "sfx")[row - 6]
            volumes = settings.get("volumes")
            if not isinstance(volumes, dict):
                volumes = {}
                settings["volumes"] = volumes
            current = volumes.get(name, 1.0)
            try:
                current = float(current)
            except (TypeError, ValueError, OverflowError):
                current = 1.0
            if not math.isfinite(current):
                current = 1.0
            volumes[name] = round(max(0.0, min(1.0, current + direction * 0.1)), 2)
        elif row == 10:
            profile = self.state.v2.setdefault("profile", {})
            collar = profile.setdefault("collar", {})
            visible = not bool(settings.get("collar_visible", collar.get("visible", True)))
            settings["collar_visible"] = visible
            collar["visible"] = visible
        self.save()

    def _keybindings_keys(self, keys, dt: float) -> None:
        settings = self.state.v2.setdefault("settings", {})
        bindings = settings.setdefault("key_bindings", default_key_bindings())
        actions = [action for action in ACTION_SYMBOLS
                   if action not in {alias for group in ACTION_ALIASES for alias in group[1:]}]
        rows = len(actions) + 1
        self.ui.key_binding_i %= rows
        if self.ui.capturing_key:
            physical = getattr(keys, "physical_keyboard_pressed", None)
            if physical is None:
                physical = getattr(keys, "keyboard_pressed", keys.pressed)
            if "esc" in physical or "backspace" in physical:
                self.ui.capturing_key = False
                return
            order = getattr(keys, "physical_keyboard_press_order", ())
            ordered = [key for key in order if key in physical and key in KEY_NAMES]
            if not ordered:
                ordered = sorted(key for key in physical if key in KEY_NAMES)
            if ordered:
                action = actions[self.ui.key_binding_i]
                bindings = set_key_binding(bindings, action, ordered[0])
                settings["key_bindings"] = bindings
                self.ui.capturing_key = False
                self.save()
            return
        if "esc" in keys.pressed:
            self.ui.settings_page = "main"
            self.ui.capturing_key = False
            return
        if keys.tap("up", dt):
            self.ui.key_binding_i = (self.ui.key_binding_i - 1) % rows
        elif keys.tap("down", dt):
            self.ui.key_binding_i = (self.ui.key_binding_i + 1) % rows
        elif "return" in keys.pressed or "space" in keys.pressed:
            if self.ui.key_binding_i == len(actions):
                settings["key_bindings"] = default_key_bindings()
                self.save()
            else:
                self.ui.capturing_key = True

    def _help_keys(self, keys, dt):
        if "esc" in keys.pressed or "h" in keys.pressed:
            self.ui.mode = self.ui.help_from
            return
        left, up = keys.tap("left", dt), keys.tap("up", dt)
        right, down = keys.tap("right", dt), keys.tap("down", dt)
        if left or up:
            self.ui.help_page = (self.ui.help_page - 1) % HELP_N
        if right or down:
            self.ui.help_page = (self.ui.help_page + 1) % HELP_N


def _throttle(keys, mode: str) -> float:
    if mode != "play" and mode != "map":
        return 0.0
    return float(("w" in keys.held)-("s" in keys.held))


def _steer(keys, mode: str) -> float:
    left = "a" in keys.held or (mode == "play" and "left" in keys.held)
    right = "d" in keys.held or (mode == "play" and "right" in keys.held)
    if left and not right:
        return -1.0
    if right and not left:
        return 1.0
    return 0.0


def _window_size(display_w: int, display_h: int) -> tuple[int, int]:
    width = min(1440, int(display_w * 0.88), int(display_h * 0.88 * 16 / 9))
    width = max(480, width // 16 * 16)
    return width, width * 9 // 16


def run(*,software=False, save_path: str | Path | None = None) -> None:
    root = Path(__file__).resolve().parents[1]
    legacy_path = root / LEGACY_SAVE if save_path is None else None
    save_path, used_local_fallback = _save_target(root, save_path)
    world, state, has_save = load_game_save(
        save_path, State, World, legacy_path=legacy_path)
    if used_local_fallback:
        state.toast("Platform save folder unavailable; using the local save folder.")
    session = Session(world, save_path, state, has_save)

    dw, dh = Platform.display_size()
    width, height = _window_size(dw, dh)
    platform = Platform(width, height, GAME_TITLE,graphics=not software)
    text = Text()
    ui = UI(text, world)
    # Show a real first frame while the forest and shaders initialize.
    loading = np.empty((height,width,3),np.uint8)
    loading[:] = (17,31,32)
    ui._center(loading,GAME_TITLE,width/2,int(height*0.40),
               max(36,height//12),(238,233,216),"serif")
    ui._center(loading,"Opening the lake...",width/2,int(height*0.58),
               max(14,height//40),(218,187,124))
    platform.present(loading)
    audio = Audio()
    renderer = Renderer(world,width,height,software=software or platform.context is None,
                        context=platform.context)
    ui.fish_card_renderer = getattr(renderer, "fish_card", None)
    last = platform.ticks()
    save_acc = 0.0
    blip = None
    low = None
    try:
        while not session.quit:
            now = platform.ticks()
            dt = min(0.25, max(0.0, (now - last) / 1000.0))
            last = now
            keys = platform.poll(dt)
            session.tick(keys, dt)
            if session.sound:
                from .bot import sound_kind
                audio.blip(sound_kind(session.state, session.sound))
            if session.quit:
                break
            if renderer.world is not session.world:
                # The transition runs on the last lake image without its HUD.
                scene = None if low is None else resize_rgb(low, width, height)
                renderer, ui = _enter_lake(platform, session, renderer, ui, text, loading,
                                           software or platform.context is None, scene)
                # The startup variable must not retain the first lake's grids.
                world = session.world
                last = platform.ticks()
            cam = _camera(renderer, session)
            platform.make_current()
            low = renderer.render(session.state, cam)
            big = resize_rgb(low, width, height)
            ui.draw(big, session.state, session.ui, cam)
            platform.present(big)
            motion_reduced = bool(session.state.v2.get("settings", {}).get("reduced_motion", False))
            if session.world_running() and not motion_reduced:
                renderer.poke_splashes(session.state)
            minutes = session.state.game_minutes
            boat = session.state.boat
            electric = (session.state.boat_id=="rowboat" and session.state.rowboat_trolling_motor
                        and session.state.rowboat_battery_kwh>0)
            audio.update(dt, session.state.throttle, session.state.speed, session.state.muted,
                         hour=hour_of_day(minutes), lake_id=session.state.lake_id,
                         rain=float(weather_visuals(minutes, session.state)["rain"]),
                         sailing=session.state.sail_raised,
                         # A starlight barge glides without either sound.
                         motorized=electric or (boat.fuelled and session.state.boat_id!="rowboat"),
                         rowing=(boat.power in ("paddle", "oars") and not electric
                                 and abs(session.state.throttle)>0.01),
                         volumes=session.state.v2.get("settings", {}).get("volumes", {}))
            if session.ui.mode != "title" or session.ui.has_save:
                save_acc += dt
                if save_acc >= 45.0:
                    session.save()
                    save_acc = 0.0
            spent = platform.ticks() - now
            platform.delay(max(0, 16 - spent))
    finally:
        if session.ui.mode != "title":
            try:
                session.save()
            except OSError:
                pass
        audio.close()
        renderer.close()
        text.close()
        platform.close()


def _enter_lake(platform, session, renderer, ui, text, loading, software, last_frame):
    """Swap to the session's new lake and return its renderer and UI.

    Travel to or from the Lagoon tips into starlight from the last lake image
    (`last_frame`, without the HUD); the new lake loads under the full
    starfield. Other routes show the plain loading card, as before.
    """
    from . import starlight
    height, width = loading.shape[:2]
    starlit = (last_frame is not None
               and starlight.touches_starlight(renderer.world.id, session.world.id))
    reduced = bool(session.state.v2.get("settings", {}).get("reduced_motion", False))
    if starlit:
        _play_starlight(platform, session, last_frame, None, 0.0, starlight.TIP_END, reduced)
    else:
        loading[:] = (17,31,32)
        ui._center(loading,f"Opening {session.world.name}...",width/2,height/2,
                   max(18,height//30),(238,233,216),"serif")
        platform.present(loading)
    renderer.close()
    ui = UI(text,session.world)
    renderer = Renderer(session.world,width,height,software=software,context=platform.context)
    ui.fish_card_renderer = getattr(renderer, "fish_card", None)
    if starlit and not session.quit:
        platform.make_current()
        # The HUD returns with the first ordinary frame on the new water.
        arrival = resize_rgb(renderer.render(session.state, _camera(renderer, session)), width, height)
        _play_starlight(platform, session, last_frame, arrival, starlight.TIP_END, 1.0, reduced)
    return renderer, ui


def _play_starlight(platform, session, source, destination, start, end, reduced):
    """Present the starlight transition from progress `start` to `end`.

    The session does not tick, so the world and the clock stay paused. Closing
    the window still quits immediately.
    """
    from . import starlight
    begin = platform.ticks()
    while True:
        elapsed = (platform.ticks() - begin) / 1000.0
        t = min(end, start + elapsed / starlight.DURATION)
        if platform.poll(0.0).quit:
            session.quit = True
            return
        platform.present(starlight.frame(source, destination, t, reduced_motion=reduced))
        if t >= end:
            return
        platform.delay(8)


def _camera(renderer: Renderer, session: Session):
    state = session.state
    if session.ui.mode != "title":
        reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
        clock = session.stage if session.stage is not None else session.whale_clock  # V1-35, V1-37
        return staging.staged_camera(renderer, state, clock, reduced=reduced)
    settings = state.v2.get("settings", {}) if isinstance(state.v2, dict) else {}
    reduced_motion = bool(settings.get("reduced_motion", False))
    yaw = state.yaw if reduced_motion else state.yaw + math.sin(state.anim * 0.12) * 0.55
    pitch = -0.05 if reduced_motion else -0.05 + math.sin(state.anim * 0.07) * 0.025
    return renderer.camera_for(state, yaw=yaw, pitch=pitch)
