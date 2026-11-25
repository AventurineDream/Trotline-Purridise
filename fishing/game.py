"""The loop. Driving, menus, and the save. Headless callers use Session.tick."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import sys
import time

import numpy as np

from .bundle import is_frozen
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
from . import comfort, saveslots, skipperlook
from . import pointer
from . import encounter
from . import soundscape
from . import detail as detail_tiers
from . import kitchen
from .bookview import (BOOK_TABS, ENTRY_IDS, move_selection, tracker_species, turn_page)
from .bot import reset as reset_bot
from .bot import summon as summon_bot
from .bot import tick as tick_bot
from .sim import Catch, State
from .savepaths import LEGACY_SAVE, load_game_save, resolve_save_path
from .ui import (UI, UIState, SHOP_TABS, HELP_SPREADS, GAME_TITLE, CREDITS_HOLD_S, check_rows,
                 pause_options, shop_rows, title_options, CHART_ZOOMS,
                 SETTINGS_ROW_COUNT, SETTINGS_KEYBOARD_CONTROLS_ROW)
from .world import World
from .lakes import LoadingQuips, travel_caption, travel_lock_reason

DRIVING = {"play"}
# Modes that actually draw toasts (ui.py). The timer pauses in every other
# mode so a menu cannot eat a notice the player never saw (issue #155).
TOAST_VISIBLE_MODES = {"play", "title", "saves", "dialogue"}
MENU_DIRECTIONS = {"up": "w", "down": "s", "left": "a", "right": "d"}
NAVIGATION_KEYS = set(MENU_DIRECTIONS) | set(MENU_DIRECTIONS.values())
DRIVING_KEYS = {"w", "s", "a", "d", "up", "down", "left", "right"}
from .soundscape import CAPTIONS as SOUND_CAPTIONS  # every sound's caption (V1-38)
from .reading import reading_seconds
PAUSE_N = 5
# A fixed level chase pose keeps the boat centred without adding camera animation.
THIRD_PERSON_DISTANCE = 6.0  # world units behind the boat
THIRD_PERSON_ELEVATION = 2.2  # world units above the pilot's eye

CAPTION_SECONDS = 2.4  # the shortest a sound caption shows; longer ones hold to be read
# The Skipper creator's card turns this fast while Q/E or LB/RB is held (radians per second).
SKIPPER_TURN_RATE = 2.4


def _save_target(root: Path, override: str | Path | None) -> tuple[Path, bool]:
    """Use a local compatibility path if SDL cannot provide the user folder."""
    try:
        return resolve_save_path(override), False
    except RuntimeError:
        if override is not None:
            raise
        return root / "saves" / "save.json", True


class Keys:
    """Headless input in UI pixels; pointer edges last for exactly one tick."""

    def __init__(self, pressed=(), held=(), quit=False, focused=True, *,
                 mouse_click=None, mouse_wheel=0, viewport=(1280, 720),
                 mouse_pos=None, mouse_moved=False, resized=False):
        """Create frame input; positions/viewport are UI pixels, wheel is whole steps."""
        self.pressed = set(pressed)
        self.held = set(held) | set(pressed)
        self.quit = quit
        self.focused = bool(focused)
        self.mouse_click, self.mouse_wheel, self.viewport = mouse_click, mouse_wheel, viewport
        self.mouse_pos, self.mouse_moved, self.resized = mouse_pos, mouse_moved, resized

    def tap(self, name: str, dt: float) -> bool:
        """Return whether the named key has a press edge; headless input never repeats."""
        return name in self.pressed


class MenuKeys:
    """Arrow/WASD aliases sharing the real input's held-key repeat behavior."""

    def __init__(self, keys):
        self.keys = keys
        self.pointer_only = False
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
        """Repeat a menu key after ``dt`` seconds unless pointer intent owns navigation."""
        if name not in MENU_DIRECTIONS:
            return self.keys.tap(name, dt)
        if self.pointer_only:
            return False
        arrow = self.keys.tap(name, dt)
        alias = self.keys.tap(MENU_DIRECTIONS[name], dt)
        return arrow or alias

    def __getattr__(self, name):
        return getattr(self.keys, name)


class Session:
    def __init__(self, world: World, save_path: Path, state: State, has_save: bool, *,
                 dev=False, legacy_path=None):
        """Create a gameplay session with optional unsaved playtest controls.

        Args:
            world: Authored lake world bound to ``state``.
            save_path: Original main-save file; its parent also roots named slots.
            state: Loaded or newly-created simulation state.
            has_save: Whether a persistent save was loaded.
            dev: Enable the overlay and disable all save writes for this session.
            legacy_path: Install-era save searched at startup, or None when an
                explicit ``--save`` path bypassed it. Kept so renaming the main
                save can retire the stale legacy copy instead of re-importing it.

        Returns:
            None.
        """
        self.world = world
        self.default_save_path = Path(save_path)
        self.slots_dir = saveslots.slot_root(self.default_save_path)
        self.save_path = self.default_save_path
        self.dev = bool(dev)
        self.legacy_path = Path(legacy_path) if legacy_path is not None else None
        self.state = state
        self.dev_mode = None
        if dev:
            from .devmode import DevMode
            self.dev_mode = DevMode(self)
        # Offline catch-up ends when this process opens the title screen. Time
        # spent reading there must not be added when Continue is selected.
        self._continue_catchup_at = time.time()
        self._title_catchup_pending = bool(has_save)
        self.focused = True
        self.ui = UIState(has_save=has_save)
        self.quit = False
        self._menu_held: set[str] = set()
        self._pointer_activate = False
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
        self.cues: list[str] = []  # sounds this tick beyond `sound` (V1-38)
        self._heard_hour = None
        self._heard_days: dict = {}
        self.whale_wait = 0.0
        self._whale_recorded = False
        self._replays = self._saved_pending()
        self._skipper_hint_shown = False  # the Continue toast nudging an uncreated Skipper: once a session

    def _saved_pending(self) -> set:
        """Scenes (and the credits) left pending in the save: they replay, and can be skipped."""
        story = self.state.v2.get("story", {}) if isinstance(self.state.v2, dict) else {}
        states = story.get("scene_states", {}) if isinstance(story, dict) else {}
        return {sid for sid, st in states.items() if st == "pending"} if isinstance(states, dict) else set()

    def cue(self, kind: str) -> None:
        """Play a sound this tick on its own bus, alongside `sound` (V1-38)."""
        self.cues.append(kind)

    def tick(self, keys, dt: float) -> None:
        """Advance one input frame and its simulation state.

        Args:
            keys: Platform or headless input object for this frame.
            dt: Elapsed real time in seconds, clamped by the caller.

        Returns:
            None.

        Side effects:
            Updates UI/simulation and displayed pointer focus. Menu pointer edges
            are consumed before native activation; Devmode may consume all input.
        """
        self.sound = None
        self.cues = []
        self.ui.input_device = getattr(keys, "device", self.ui.input_device)
        settings = self.state.v2.get("settings", {}) if isinstance(self.state.v2, dict) else {}
        input_source = keys
        keys = session_input(keys, settings.get("key_bindings"), self._input_repeat)
        self.focused = bool(getattr(keys, "focused", True))
        if keys.quit:
            if self.ui.mode != "title" or self.ui.has_save:
                self.save()
            self.quit = True
            return
        if self.dev_mode is not None:
            physical_pressed = getattr(keys, "physical_keyboard_pressed",
                                       getattr(keys, "keyboard_pressed", keys.pressed))
            consumed = self.dev_mode.handle(set(physical_pressed), set(keys.pressed))
            if consumed:
                # The overlay owns all input for this frame, including the key that closes it.
                keys.pressed.clear()
                keys.held.clear()
                # Settings key capture reads physical metadata as well as action sets.
                for name in ("physical_keyboard_pressed", "physical_keyboard_press_order"):
                    physical = getattr(keys, name, None)
                    if hasattr(physical, "clear"):
                        physical.clear()
                keys.mouse_click = None
                keys.mouse_wheel = 0
                keys.mouse_moved = False
                # The fractional wheel remainder belongs to SDL's input, not its action wrapper.
                wheel_remainder = getattr(input_source, "mouse_wheel_remainder", None)
                if wheel_remainder is not None:
                    input_source.mouse_wheel_remainder = 0.0
            if self.dev_mode.skip_world_tick:
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
        pointer_used = (getattr(keys, "mouse_click", None) is not None
                        or bool(getattr(keys, "mouse_wheel", 0)))
        self._keys(keys, dt)
        self.state.hauling = self.ui.mode == "haul"
        current_page = (self.ui.mode, self.ui.journal_page, self.ui.book_entry_i)
        if (current_page != previous_page or keys.pressed
                or pointer_used):
            self._remember_book_page()
        self._simulate(keys, dt, driving_presses)
        self._tick_settle(dt)
        self._play_due_scene()
        self._tick_whale(dt)
        self._tick_stage(dt)
        self._tick_soundscape()
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
            # A staged story moment brings the lake's motif; the Star-Whale, its song (V1-38).
            self.cue("whale_song" if stage_id == "story_c5_whale" else soundscape.motif_for(self.state.lake_id))
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

    def _tick_soundscape(self) -> None:
        """The lake's music and calendar cues (V1-38): its motif at dawn and dusk, a Lake Day's
        bell and the cookout's triangle, each once a day."""
        state = self.state
        hour = hour_of_day(state.game_minutes)
        previous, self._heard_hour = self._heard_hour, hour
        if self.ui.mode != "play" or previous is None:
            return
        for mark in (6.0, 19.0):  # dawn, dusk
            if previous < mark <= hour or (previous > hour and (mark > previous or mark <= hour)):
                self.cue(soundscape.motif_for(state.lake_id))
        day = calendar.day_number(state.game_minutes)
        if calendar.lake_day(state.lake_id, state.game_minutes) is not None and self._heard_days.get("lake_day") != (state.lake_id, day):
            self._heard_days["lake_day"] = (state.lake_id, day)
            self.cue("lake_day")
        if calendar.cookout_active(state.game_minutes) and self._heard_days.get("cookout") != (state.lake_id, day):
            self._heard_days["cookout"] = (state.lake_id, day)
            self.cue("cookout")

    def hear_ambient(self, kind: str) -> None:
        """An ambient call the mixer played: captioned when nothing else is (V1-38)."""
        settings = self.state.v2.get("settings", {}) if isinstance(self.state.v2, dict) else {}
        if settings.get("captions", True) and self.ui.caption_timer <= 0:
            self.ui.caption = soundscape.caption(kind, self.state)
            self.ui.caption_timer = reading_seconds(self.ui.caption, CAPTION_SECONDS)

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
                self.cue("whale_song")
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
        self.ui.dialogue_s = self.ui.dialogue_line_s = 0.0  # the portrait starts from rest

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
        heard = [kind for kind in (self.sound, *getattr(self, "cues", ())) if kind]
        if heard:
            # The SFX sound wins a shared tick; a cue's caption otherwise (V1-38).
            self.ui.caption = soundscape.caption(heard[0], self.state)
            self.ui.caption_timer = reading_seconds(self.ui.caption, CAPTION_SECONDS)
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
        """Persist the active game, not Devmode or an unsaved browser preview.

        Returns:
            None.

        Side effects:
            Writes to ``save_path`` unless Devmode is enabled or the save browser
            is showing a bootstrap state with no existing active save.
        """
        if self.dev_mode is not None or (self.ui.mode == "saves" and not self.ui.has_save):
            return
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
                            and abs(state.throttle_setting) <= 0.01
                            # Issue #153: a fuelled engine idling in neutral is
                            # not "at rest" until it is switched off.
                            and (not state.boat.fuelled or not state.engine_on)),
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
        if self.ui.mode in TOAST_VISIBLE_MODES:
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

    def _menu_selected(self, keys):
        """Unify native confirm and one semantic activation, never gameplay keys."""
        return self._pointer_activate or bool(keys.pressed & {"return", "space"})

    def _pointer_focus(self, target):
        ui = self.ui
        if target.field == "dialogue_selected":
            if self.conversation is not None:
                self.conversation.selected = target.value
        elif target.field:
            if getattr(ui, target.field) != target.value:
                ui.note = ""
            setattr(ui, target.field, target.value)
            if target.field == "book_week_i":
                ui.book_detail_page = 0
            if target.field == "set_bait":
                baits = list(ui.set_section_baits)
                baits[ui.set_section] = ui.set_bait
                ui.set_section_baits = tuple(baits)
            if target.field == "slot_i":
                ui.slot_action_i = 0

    def _route_pointer(self, keys):
        """Consume input against displayed geometry, then dispatch at most once.

        Native menu handlers own activation and selection. Stale/blank clicks
        are consumed rather than interpreted as fallback confirmation.
        """
        ui, registry = self.ui, self.ui.pointer
        if not self.focused:
            registry.hovered = None
            return ui.mode not in DRIVING
        if ui.mode in DRIVING and not ui.whale_return:
            registry.hovered = None
            return False
        click = getattr(keys, "mouse_click", None)
        wheel = getattr(keys, "mouse_wheel", 0)
        moved = getattr(keys, "mouse_moved", False)
        position = click if click is not None else getattr(keys, "mouse_pos", None)
        source = keys.keys if isinstance(keys, MenuKeys) else keys
        valid = (registry.identity == pointer.context(self.state, ui)
                 and registry.viewport == getattr(keys, "viewport", (1280, 720))
                 and not getattr(keys, "resized", False))
        if ui.mode in {"catnap", "cooking", "haul", "credits"} or ui.book_ceremony:
            if not valid:
                source.mouse_click, source.mouse_wheel = None, 0
            return False
        source.mouse_click, source.mouse_wheel = None, 0
        # Auxiliary controls have no list index. Confirm honors their visible
        # semantic focus; navigation returns ownership to the screen's row index.
        hovered = registry.hovered
        if (valid and registry.owner == "pointer" and hovered is not None
                and not hovered.field and keys.pressed & {"return", "space"}
                and not ui.skipper_typing and not ui.slot_renaming and not ui.capturing_key):
            return self._pointer_action(hovered.action, hovered.value)
        if keys.pressed or (keys.held & NAVIGATION_KEYS and not moved and click is None):
            registry.owner = "keyboard"
            registry.hovered = None
            return False
        if not valid:
            registry.hovered = None
            return click is not None or bool(wheel)
        if wheel:
            if ui.skipper_typing or ui.slot_renaming or ui.capturing_key:
                # Swallow the wheel but still run native handlers: they read
                # physical_keyboard_pressed for typed letters and Backspace.
                return False
            registry.owner = "scroll"
            registry.hovered = None
            self._pointer_scroll(registry.scroll, -int(wheel))
            return True
        if not moved and click is None:
            return False
        registry.owner = "pointer"
        keys.pointer_only = True
        registry.hovered = registry.hit(position) if position is not None else None
        target = registry.hovered
        if target is None:
            return click is not None
        if not (ui.skipper_typing or ui.slot_renaming) or click is not None:
            self._pointer_focus(target)
        if click is None:
            return False
        if ui.mode == "skipper" and ui.skipper_typing:
            ui.skipper_look["name"] = skipperlook.clean_name(ui.skipper_look["name"])
            ui.skipper_typing = ui.skipper_fresh = False
        return self._pointer_action(target.action, target.value)

    def _pointer_scroll(self, kind, amount):
        ui = self.ui
        if kind == "help":
            ui.help_spread = (ui.help_spread + amount) % (ui.help_spreads or HELP_SPREADS)
            return
        if kind == "book":
            move_selection(self.state, ui, self._npc_content, amount)
            return
        counts = {
            "title": ("title_i", len(title_options(ui.has_save))),
            "saves": ("slot_i", len(ui.slots)),
            "pause": ("pause_i", len(pause_options(self.state))),
            "settings": ("settings_i", SETTINGS_ROW_COUNT),
            "keys": ("key_binding_i", len(ACTION_SYMBOLS)
                     - sum(len(group) - 1 for group in ACTION_ALIASES) + 1),
            "skipper": ("skipper_i", len(skipperlook.ROWS)),
            "bait": ("set_bait", len(BAITS)),
            "well": ("well_i", len(self.state.well)),
            "check": ("check_i", len(check_rows(self.state, ui.check_line))),
        }
        if kind in {"shop", "kitchen"}:
            rows = (shop_rows(self.state, ui.shop_tab) if ui.mode == "shop"
                    else kitchen.rows(self.state, self.world))
            counts[kind] = ("shop_i", len(rows))
        if kind == "dialogue" and self.conversation is not None:
            count = len(self.conversation.node(self._npc_content).get("choices", []))
            if count:
                self.conversation.selected = (self.conversation.selected + amount) % count
            return
        if kind == "cook_fish":
            ui.cook_fish += amount
            return
        if kind in counts:
            field, count = counts[kind]
            if count:
                value = (getattr(ui, field) + amount) % count
                self._pointer_focus(pointer.Target((0, 0, 0, 0), field=field, value=value))
                ui.note = ""

    def _pointer_action(self, action, value):
        ui, mode = self.ui, self.ui.mode
        if action in {"activate", "set"}:
            self._pointer_activate = True
            return False
        if action == "focus":
            return True
        if action == "skip_scene":
            if self.stage_skippable():
                self.stage.t = self.stage.stage.duration
        elif action == "skip_whale":
            if mode == "play" and ui.whale_return and self.whale_clock is not None:
                self._skip_whale()
        elif action in {"back", "creator_cancel"}:
            self._pointer_back()
        elif action == "help":
            self._open_help(mode)
        elif action == "slot_rename_done" and mode == "saves":
            self._finish_slot_rename()
        elif action == "creator_done":
            self._close_skipper(confirm=True)
        elif action in {"previous", "next"}:
            self._pointer_scroll(ui.pointer.scroll, -1 if action == "previous" else 1)
        elif action in {"adjust_minus", "adjust_plus"}:
            direction = -1 if action == "adjust_minus" else 1
            if mode == "skipper":
                key = skipperlook.ROWS[ui.skipper_i][0]
                if key != "done":
                    self._skipper_change(key, direction)
            elif mode == "settings" and ui.settings_page == "main":
                self._adjust_setting(ui.settings_i, direction)
        elif action == "tab":
            if mode == "shop":
                ui.shop_tab, ui.shop_i, ui.note = value, 0, ""
            elif mode == "journal":
                ui.journal_page = value
                ui.book_detail_page, ui.book_detail_pages = 0, 1
                if value == 1:
                    ui.book_entry_i = ui.journal_i
        elif action == "set_line":
            if self.state.held:
                ui.set_line, ui.note = value % len(self.state.held), ""
        elif action == "set_sections":
            old, ui.set_sections = ui.set_sections, value
            baits = list(ui.set_section_baits)
            for index in range(old, value):
                baits[index] = ui.set_bait
            ui.set_section %= value
            ui.set_bait = baits[ui.set_section]
            ui.set_section_baits, ui.note = tuple(baits), ""
        elif action == "set_section":
            ui.set_section = value % ui.set_sections
            ui.set_bait, ui.note = ui.set_section_baits[ui.set_section], ""
        elif action == "book_turn":
            turn_page(self.state, ui, ui.pointer.viewport)
        elif action == "book_tracker":
            self._toggle_book_tracker()
        elif action in {"book_previous", "book_next"}:
            move_selection(self.state, ui, self._npc_content,
                           -1 if action == "book_previous" else 1)
        elif action == "kitchen":
            self._open_kitchen()
        elif action == "catnap":
            ui.mode = "play"
            if not self._start_catnap():
                ui.mode, ui.note = "pause", "Anchor or dock for a catnap."
        elif action == "treasure":
            if self.state.toggle_treasured(ui.well_i) is None:
                self.save()
        elif mode == "map":
            actions = {"map_hail": self._hail, "map_anchor": self._anchor,
                       "map_sail": self._sail, "map_tow": self._map_tow, "map_bot": self._bot}
            if action in actions:
                actions[action]()
        return True

    def _pointer_back(self):
        ui, mode = self.ui, self.ui.mode
        if mode == "title":
            ui.confirm_new = False
        elif mode == "saves":
            if ui.slot_renaming:
                ui.slot_renaming = ui.slot_name_fresh = False
                ui.note = ""
            else:
                ui.mode = "title"
        elif mode == "help":
            ui.mode = ui.help_from
        elif mode == "skipper":
            self._close_skipper(confirm=False)
        elif mode == "settings":
            if ui.capturing_key:
                ui.capturing_key = False
            elif ui.settings_page == "keys":
                ui.settings_page = "main"
            else:
                ui.mode = "pause"
        elif mode == "dialogue":
            if self.conversation is None or not self.conversation.in_scene(self._npc_content):
                self._close_dialogue()
        elif mode == "new_mode":
            ui.mode = "title"
        elif mode == "needs":
            comfort.snooze(self.state.v2, ui.needs_kind)
            ui.mode = "play"
            self.save()
        elif mode in {"kitchen", "cook_confirm"}:
            ui.mode = ui.kitchen_from if mode == "kitchen" else ui.cook_from
            ui.note = ""
            self.save()
        elif mode in {"pause", "shop", "setbait", "check", "journal", "well", "map"}:
            ui.mode = "play"
            if mode in {"shop", "journal"}:
                self.save()

    def _keys(self, keys, dt: float):
        mode = self.ui.mode
        if mode not in DRIVING:
            keys = MenuKeys(keys)
        self._pointer_activate = False
        if self._route_pointer(keys):
            return
        # Names use M and Shift as text, not mute or throttle actions.
        typing = ((mode == "skipper" and self.ui.skipper_typing)
                  or (mode == "saves" and self.ui.slot_renaming))
        if mode!="title" and not typing and keys.held & {"shift","rshift"}:
            self.state.throttle_setting = 0.0
            self.state.throttle = 0.0
        if "m" in keys.pressed and mode != "title" and not typing:
            self.state.muted = not self.state.muted
        if mode == "title":
            self._title_keys(keys, dt)
        elif mode == "saves":
            self._saves_keys(keys, dt)
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
            if self._menu_selected(keys) or "t" in keys.pressed:
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
            elif "v" in keys.pressed:
                self._engine()
            elif "r" in keys.pressed:
                self._map_tow()
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
        elif mode == "skipper":
            self._skipper_keys(keys, dt)

    def _title_keys(self, keys, dt):
        options = title_options(self.ui.has_save)
        if self.ui.confirm_new:
            if "esc" in keys.pressed:
                self.ui.confirm_new = False
            elif self._menu_selected(keys):
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
        if self._menu_selected(keys):
            choice = options[self.ui.title_i % len(options)]
            if choice == "Continue":
                if self.dev_mode is None:
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
                if not self._skipper_hint_shown and not skipperlook.saved(self.state)["created"]:
                    # Once per session, and only a hint: the save plays on without the creator.
                    self._skipper_hint_shown = True
                    self.state.toast("Dress your Skipper: Esc, then Your Skipper.")
            elif choice == "New morning":
                self.ui.confirm_new = True
            elif choice == "Saves":
                self._open_saves()
            else:
                self.ui.new_mode_i = 0
                self.ui.mode = "new_mode"

    def _open_saves(self):
        """Refresh the slot browser without changing the active save or writing files."""
        ui = self.ui
        try:
            ui.slots = saveslots.list_slots(self.default_save_path)
        except OSError as error:
            self.state.toast(f"Saves could not be listed: {error}")
            return
        ui.slot_i = next((i for i, slot in enumerate(ui.slots)
                          if slot.path == self.save_path), 0)
        ui.slot_action_i = 0
        ui.slot_renaming = ui.slot_name_fresh = False
        ui.slot_name_buf = ui.note = ""
        ui.mode = "saves"

    def _saves_keys(self, keys, dt):
        """Browse saves with menu directions; physical name keys never trigger actions."""
        ui = self.ui
        if ui.slot_renaming:
            physical = set(getattr(keys, "physical_keyboard_pressed", keys.pressed))
            gamepad = set(getattr(keys, "gamepad_pressed", ()))
            if "esc" in physical or "esc" in gamepad:
                ui.slot_renaming = ui.slot_name_fresh = False
                ui.note = ""
                return
            ordered = [key for key in getattr(keys, "physical_keyboard_press_order", ())
                       if key in physical]
            typed = [key for key in ordered + sorted(physical - set(ordered))
                     if key == "backspace" or key in skipperlook.NAME_KEYS]
            if typed:
                current = "" if ui.slot_name_fresh else ui.slot_name_buf
                ui.slot_name_buf = skipperlook.type_name(current, typed)
                ui.slot_name_fresh = False
            if "return" in physical or "return" in gamepad:
                self._finish_slot_rename()
            return
        if "esc" in keys.pressed:
            ui.mode = "title"
            return
        if ui.slots:
            step = int(keys.tap("down", dt)) - int(keys.tap("up", dt))
            if step:
                ui.slot_i = (ui.slot_i + step) % len(ui.slots)
                ui.slot_action_i = 0
                ui.note = ""
        step = int(keys.tap("right", dt)) - int(keys.tap("left", dt))
        if step:
            ui.slot_action_i = (ui.slot_action_i + step) % 4
            ui.note = ""
        if not self._menu_selected(keys):
            return
        if ui.slot_action_i == 2:
            ui.new_mode_i = 0
            ui.mode = "new_mode"
        elif ui.slot_action_i == 3:
            ui.mode = "title"
        elif ui.slots:
            slot = ui.slots[ui.slot_i % len(ui.slots)]
            if ui.slot_action_i == 1:
                if self.dev:
                    ui.note = "Devmode does not rename saves."
                elif not slot.path.is_file():
                    ui.note = "No save to rename yet."
                else:
                    ui.slot_name_buf = slot.name
                    ui.slot_renaming = ui.slot_name_fresh = True
            else:
                try:
                    self._load_slot(slot)
                except (OSError, ValueError, KeyError) as error:
                    ui.note = f"That save could not be loaded: {error}"

    def _finish_slot_rename(self):
        """Commit the browser's draft and keep the active path and metadata in sync."""
        ui = self.ui
        if not ui.slot_renaming or self.dev or not ui.slots:
            return
        slot = ui.slots[ui.slot_i % len(ui.slots)]
        name = skipperlook.clean_name(ui.slot_name_buf)
        try:
            renamed = saveslots.rename_slot(self.default_save_path, slot.slug, name,
                                          legacy_path=self.legacy_path)
        except (OSError, ValueError) as error:
            ui.note = f"That save could not be renamed: {error}"
            return
        if renamed is None:
            ui.note = "That save is no longer there."
            return
        _slug, path = renamed
        if self.save_path == slot.path:
            self.save_path = path
            saveslots.stamp_slot_name(self.state, name)
        self._open_saves()
        ui.slot_i = next((i for i, entry in enumerate(ui.slots) if entry.path == path), 0)
        ui.note = f"Renamed to {name}."

    def _load_slot(self, slot: saveslots.Slot):
        """Load slot's own lake and state; apply offline catch-up once before play.

        slot supplies the save path and toast name. Loading may migrate/recover
        ordinary saves but is read-only in Devmode. Missing/unrecoverable slots
        leave the current session untouched and show an explanation. I/O/version
        errors propagate; every non-error path returns None.
        """
        world, state, has_save = load_game_save(
            slot.path, State, World, persist_changes=not self.dev)
        if not has_save:
            message = f"{slot.name} could not be loaded."
            self.state.toast(message)
            self.ui.note = message
            return
        self._close_dialogue()
        self.world, self.state, self.save_path = world, state, slot.path
        autostart_story(self.state, self._npc_content)
        self._replays = self._saved_pending()
        self._attach_quest_manager()
        self._continue_catchup_at = time.time()
        self._title_catchup_pending = bool(has_save)
        if self._title_catchup_pending:
            state.catch_up(now=self._continue_catchup_at)
            self._title_catchup_pending = False
        self.stage = self.whale_clock = None
        self.whale_wait = 0.0
        self._whale_recorded = False
        self._heard_hour = None
        self._heard_days = {}
        self.ui = UIState(mode="play", has_save=has_save, input_device=self.ui.input_device,
                          dialogue_content=self._npc_content)
        self._refresh_npcs()
        if has_save:
            state.toast(f"Loaded {slot.name}.")
            if not self._skipper_hint_shown and not skipperlook.saved(state)["created"]:
                self._skipper_hint_shown = True
                state.toast("Dress your Skipper: Esc, then Your Skipper.")

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
        select = self._menu_selected(keys)
        if not select:
            return
        if choosing_mode:
            # The creator comes before the first morning: its Done starts the game (_close_skipper).
            self._open_skipper("new")
            return
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
        if "v" in keys.pressed:
            self._engine()
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
            self._open_book()
        if "i" in keys.pressed:
            self._open_well()
        if "b" in keys.pressed:
            self._bot()
        if "f" in keys.pressed:
            self._open_set()
        if "e" in keys.pressed:
            self._open_e()
        if "x" in keys.pressed:
            self._cycle_chart_zoom()

    def _cycle_chart_zoom(self):
        """Step the corner chart to its next CHART_ZOOMS level, back to 1x after the last."""
        zooms = CHART_ZOOMS
        current = self.ui.chart_zoom if self.ui.chart_zoom in zooms else zooms[0]
        self.ui.chart_zoom = zooms[(zooms.index(current) + 1) % len(zooms)]

    def _open_book(self):
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

    def _open_well(self):
        self.ui.mode = "well"
        self.ui.well_i = 0

    def _hail(self):
        npc = nearby_npc(self.state)
        if npc is None:
            return
        self.cue("horn")  # the hail horn (V1-38)
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
        npc = getattr(self.conversation, "npc_id", None)
        self.conversation = None
        self.ui.conversation = None
        self.ui.mode = self.ui.dialogue_from
        # Issue #156: Bot explains time scaling once Grandmother's first
        # conversation has actually closed, never over it.
        if npc == "grandmother_whiskers":
            self._explain_time_scale()

    def _explain_time_scale(self):
        """Bot's one-time explanation of the time-scale key, in his own voice."""
        if self.state.time_tip_given():
            return
        self.state.mark_time_tip()
        from .gamepad import normalize_key_bindings
        saved = self.state.v2.get("settings", {})
        bindings = normalize_key_bindings(saved.get("key_bindings") if isinstance(saved, dict) else None)
        key = bindings.get("time_scale", "t").upper()
        self.state.toast(f"Bot: Anchor, then press {key} to let time run faster.")
        self.save()

    def _dialogue_keys(self, keys, dt):
        chat = self.conversation
        # The portrait's clocks (portraitmotion) run while the box is open.
        self.ui.dialogue_s += dt
        self.ui.dialogue_line_s += dt
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
        select = self._menu_selected(keys) or "c" in keys.pressed
        for i in range(len(choices)):
            if str(i + 1) in keys.pressed:
                chat.selected = i
                select = True
                break
        if select:
            line = (chat.npc_id, chat.node_id)
            more = chat.advance(self.state, self._npc_content)
            if (chat.npc_id, chat.node_id) != line:
                self.ui.dialogue_line_s = 0.0  # a new line: the speaker talks it with a fresh bounce
            if chat.finished_scene:
                chat.finished_scene = False
                self.save()  # A scene's effects and claim are written together (06 §3.3).
            elif choices:
                # A quest choice must be durable before the journal can be reopened.
                self.save()
            if not more:
                self._close_dialogue()
                if chat.trip:
                    self._free_trip(chat.trip)

    def _anchor(self):
        self.state.set_anchored(not self.state.anchored)

    def _sail(self):
        error = self.state.toggle_sail()
        if error:
            self.state.toast(error)

    def _engine(self):
        error = self.state.toggle_engine()
        if error:
            self.state.toast(error)


    def _bot(self):
        sound = summon_bot(self.state, self.world)
        if sound:
            self.sound = sound

    def _tow(self, toast=True) -> str | None:
        if not self.world_running():
            return None
        before = self.state.game_minutes
        error = self.state.tow_to_landing(self.world)
        if error:
            if toast:
                self.state.toast(error)
            return error
        reset_bot(self.state)
        self._record_world_advance(before)
        return None

    def _map_tow(self):
        """Call a tow from the chart: it advances the world, so run it from play."""
        self.ui.mode = "play"
        error = self._tow(toast=False)
        if error:
            self.ui.mode = "map"
            self.state.toast(error)

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
        self.ui.help_spread = 0
        self.ui.help_spreads = 0  # counted again by the next draw, at this window's text size
        self.ui.mode = "help"

    def _open_set(self):
        if abs(self.state.speed) > 0.5:
            self.state.toast("Idle the boat before you set.")
            return
        if not self.state.held:
            self.state.toast("Every line you own is already in the water.")
            return
        # Issue #152: restricted water warns here, before the bait menu opens.
        # Any held line that fits opens the menu; the chosen line is re-checked
        # on confirm inside try_set.
        zone_error = None
        for held in self.state.held:
            zone_error = self.state.line_zone_error(self.world, held.hooks)
            if zone_error is None:
                break
        if zone_error is not None:
            self.state.toast(zone_error, 5.0)
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
            first = next((i for i, hook in enumerate(line.hooks)
                          if encounter.is_legendary(hook.catch)
                          and not encounter.presented(self.state.v2, hook.catch.species)), None)
            if first is None:
                self.ui.mode = "check"
                self.ui.check_i = 0
            else:
                # Instant skips ordinary hooks, but never a legendary's first scene (02 §7.2).
                self.ui.haul_index = first
                self.ui.haul_encounter_only = True
                self._begin_encounter(line.hooks[first])
            return
        cadence = haul_cadence(self.state) * self.ui.haul_picnic_factor
        multiplier = 3.0 if "e" in keys.held else 1.0
        step = max(0.0, float(dt)) * multiplier
        if self.ui.haul_index >= len(line.hooks):
            self.ui.mode = "check"
            self.ui.check_i = 0
            return
        if self.ui.haul_phase == "card" and (
                keys.pressed - {"e"} or getattr(keys, "mouse_click", None) is not None):
            # A legendary's framed book page must remain readable before it advances.
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
                return
            if self.ui.haul_phase == "card":
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
                self.ui.haul_timer = cadence
                self.ui.haul_phase = "surface"
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
        """Run the encounter clock; only a repeat allows key/click skipping or E hurrying."""
        if not encounter.is_legendary(hook.catch):
            self._next_haul_hook()
            return
        legendary_id = hook.catch.species
        repeat = encounter.presented(self.state.v2, legendary_id)
        if repeat and (keys.pressed - {"e"} or getattr(keys, "mouse_click", None) is not None):
            self._finish_encounter(hook)
            return
        t0 = self.ui.haul_phase_timer
        step = max(0.0, float(dt)) * (3.0 if repeat and "e" in keys.held else 1.0)
        self.ui.haul_phase_timer = min(encounter.SCENE_S, t0 + step)
        if encounter.hum_due(t0, self.ui.haul_phase_timer):
            self.sound = "hum_winch" if encounter.variant(self.state) == "winch" else "hum"
        if t0 < encounter.NAME[0] <= self.ui.haul_phase_timer:
            self.cue("legendary")  # its chord rises with its name (V1-38)
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
        if rows and self._menu_selected(keys):
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
        select = self._menu_selected(keys)
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
        if rows and self._menu_selected(keys):
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
        for i, name in enumerate("123456789"[:len(BAITS)]):
            if name in keys.pressed:
                self.ui.set_bait = i
                section_baits[self.ui.set_section] = self.ui.set_bait
                self.ui.set_section_baits = tuple(section_baits)
                self.ui.note = ""
        if self._menu_selected(keys):
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
        elif self._menu_selected(keys):
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
        if self._menu_selected(keys):
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
        options = pause_options(self.state)
        if keys.tap("up", dt):
            self.ui.pause_i = (self.ui.pause_i - 1) % len(options)
        if keys.tap("down", dt):
            self.ui.pause_i = (self.ui.pause_i + 1) % len(options)
        if self._menu_selected(keys):
            choice = options[self.ui.pause_i % len(options)]
            self.ui.note = ""
            if choice == "Resume":
                self.ui.mode = "play"
            elif choice == "Book":
                self._open_book()
            elif choice == "Livewell":
                self._open_well()
            elif choice in ("Raise the sail", "Lower the sail"):
                self.ui.mode = "play"
                self._sail()
            elif choice in ("Turn the engine off", "Turn the engine on"):
                self.ui.mode = "play"
                self._engine()
            elif choice == "Call a tow":
                # A tow moves the world, so it runs from play; a refusal stays in the menu.
                self.ui.mode = "play"
                error = self._tow(toast=False)
                if error:
                    self.ui.mode = "pause"
                    self.ui.note = error
            elif choice.startswith("Time "):
                error = self.state.cycle_scale()
                if error:
                    self.ui.note = error
            elif choice == "Your Skipper":
                self._open_skipper("pause")
            elif choice == "Settings":
                self.ui.settings_page = "main"
                self.ui.settings_i = 0
                self.ui.mode = "settings"
            elif choice == "Help":
                self._open_help("pause")
            elif choice == "Main menu":
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
            self.ui.settings_i = (self.ui.settings_i - 1) % SETTINGS_ROW_COUNT
        elif keys.tap("down", dt):
            self.ui.settings_i = (self.ui.settings_i + 1) % SETTINGS_ROW_COUNT
        elif keys.tap("left", dt):
            self._adjust_setting(rows, -1)
        elif keys.tap("right", dt):
            self._adjust_setting(rows, 1)
        elif self._menu_selected(keys):
            if rows == SETTINGS_KEYBOARD_CONTROLS_ROW:
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
            settings["third_person"] = not bool(settings.get("third_person", False))
        elif row == 5:
            speeds = ("normal", "quick", "instant")
            current = settings.get("haul_speed", "normal")
            if current not in speeds:
                current = "normal"
            settings["haul_speed"] = speeds[(speeds.index(current) + (1 if direction >= 0 else -1)) % len(speeds)]
        elif row == 6:
            settings["captions"] = not bool(settings.get("captions", True))
        elif 7 <= row <= 10:
            name = ("master", "music", "ambience", "sfx")[row - 7]
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
        elif row == 11:
            profile = self.state.v2.setdefault("profile", {})
            collar = profile.setdefault("collar", {})
            visible = not bool(settings.get("collar_visible", collar.get("visible", True)))
            settings["collar_visible"] = visible
            collar["visible"] = visible
        elif row == 12:
            settings["auto_anchor"] = not bool(settings.get("auto_anchor", False))
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
        elif self._menu_selected(keys):
            if self.ui.key_binding_i == len(actions):
                settings["key_bindings"] = default_key_bindings()
                self.save()
            else:
                self.ui.capturing_key = True

    # --- The Skipper creator (skipperlook; drawn by ui._skipper) ---------------------

    def _open_skipper(self, origin: str) -> None:
        """Open the Skipper creator on a draft of the saved look. Nothing is saved until Done.

        Args:
            origin: "new" while the morning's pace is chosen (Done starts the game, Esc returns
                to the pace choice) or "pause" (Done saves and returns to the pause menu, Esc
                discards the draft).

        Side effects:
            Sets the creator's UI fields and the mode to "skipper". The clock restarts at 0, so
            the card's motion is the same on every opening.
        """
        ui = self.ui
        ui.skipper_origin = origin
        ui.skipper_look = skipperlook.saved(self.state)
        ui.skipper_i = 0
        ui.skipper_typing = False
        ui.skipper_fresh = False
        ui.skipper_clock = 0.0
        ui.skipper_changed_at = -99.0
        ui.skipper_turn = 0.0
        ui.mode = "skipper"

    def _skipper_keys(self, keys, dt: float) -> None:
        """Rows, typing, the card's turn and the exits: Enter or Space on Done saves, Esc leaves.

        Typed letters come from the physical keyboard, not from `pressed`: that set also carries
        the gamepad's A ("e" and "return") and the letters bound to menu actions.
        """
        ui = self.ui
        if self.focused:
            ui.skipper_clock += dt
        physical = set(getattr(keys, "physical_keyboard_pressed", keys.pressed))
        if ui.skipper_typing:
            self._skipper_type(keys, physical)
            self._skipper_turn(keys, dt, ui.skipper_typing)
            return
        if "esc" in keys.pressed:
            self._close_skipper(confirm=False)
            return
        count = len(skipperlook.ROWS)
        if keys.tap("up", dt):
            ui.skipper_i = (ui.skipper_i - 1) % count
        elif keys.tap("down", dt):
            ui.skipper_i = (ui.skipper_i + 1) % count
        key = skipperlook.ROWS[ui.skipper_i][0]
        step = int(keys.tap("right", dt)) - int(keys.tap("left", dt))
        if step and key != "done":
            self._skipper_change(key, step)
        if self._menu_selected(keys):
            if key == "done":
                self._close_skipper(confirm=True)
                return
            if key == "name":
                ui.skipper_typing = True
                ui.skipper_fresh = True
            else:
                self._skipper_change(key, 1)
        self._skipper_turn(keys, dt, ui.skipper_typing)

    def _skipper_type(self, keys, physical: set) -> None:
        """Type into the name from this frame's physical key presses, in press order.

        Letters, digits, space, minus, apostrophe and period type; Backspace deletes. Physical Return,
        Esc, Up and Down end typing; gamepad A, B and d-pad directions retain those controls. Remapped
        keyboard actions are ignored while typing. Only the gamepad's left/right d-pad cycles suggestions.
        """
        ui = self.ui
        draft = ui.skipper_look
        ordered = [key for key in getattr(keys, "physical_keyboard_press_order", ()) if key in physical]
        typed = [key for key in ordered + sorted(physical - set(ordered))
                 if key == "backspace" or key in skipperlook.NAME_KEYS]
        if typed:
            # Entering the name selects it, so the first key typed replaces it and a new name is
            # never glued onto the old one. Enter or Esc with nothing typed keeps the old name.
            current = "" if ui.skipper_fresh else draft["name"]
            ui.skipper_fresh = False
            name = skipperlook.type_name(current, typed)
            if name != draft["name"]:
                draft["name"] = name
                ui.skipper_changed_at = ui.skipper_clock
        gamepad = set(getattr(keys, "gamepad_pressed", ()))
        end_keys = {"return", "esc", "up", "down"}
        if physical & end_keys or gamepad & end_keys:
            draft["name"] = skipperlook.clean_name(draft["name"])
            ui.skipper_typing = False
            ui.skipper_fresh = False
            direction_keys = (physical | gamepad) & {"up", "down"}
            if direction_keys:
                ui.skipper_i = (ui.skipper_i + (1 if "down" in direction_keys else -1)) % len(skipperlook.ROWS)
            return
        if "left" in gamepad:
            self._skipper_change("name", -1)
        elif "right" in gamepad:
            self._skipper_change("name", 1)

    def _skipper_change(self, key: str, step: int) -> None:
        """Move row `key` one option (skipperlook.cycle). The card waves only if the look changed."""
        ui = self.ui
        changed = skipperlook.cycle(ui.skipper_look, key, step)
        if changed != ui.skipper_look:
            ui.skipper_look = changed
            ui.skipper_changed_at = ui.skipper_clock

    def _skipper_turn(self, keys, dt: float, typing: bool) -> None:
        """Turn the card while a turn key is held, at SKIPPER_TURN_RATE radians per second.

        Q and E turn it from the keyboard, not while typing. The gamepad's shoulders arrive as
        "g" (LB) and "c" (RB) with no physical key behind them. Its A also sends "e", so "e"
        turns only when the keyboard sent it.
        """
        held = set(getattr(keys, "physical_keyboard_held", keys.held))
        direction = 0
        if not typing:
            direction += ("e" in held) - ("q" in held)
        if "c" in keys.held and "c" not in held:
            direction += 1
        if "g" in keys.held and "g" not in held:
            direction -= 1
        if direction:
            self.ui.skipper_turn = (self.ui.skipper_turn + direction * SKIPPER_TURN_RATE * dt) % (2 * math.pi)

    def _close_skipper(self, *, confirm: bool) -> None:
        """Leave the creator: Done (confirm) keeps the draft, Esc discards it.

        A "new" creator starts the game on Done, with the look in the new state before its
        prologue begins. Esc goes back to the pace choice. A "pause" creator saves the look on
        Done and returns to the pause menu; Esc returns there and changes nothing.

        Args:
            confirm: True for Done, False for Esc.

        Side effects:
            Saves the game (pause origin, Done) or starts a new one (new origin, Done).
        """
        ui = self.ui
        origin = ui.skipper_origin
        draft = ui.skipper_look or skipperlook.saved(self.state)
        ui.skipper_look, ui.skipper_typing = None, False
        look = skipperlook.normalize({"skipper": {**draft, "created": True}}) if confirm else None
        if origin == "new":
            if confirm:
                self._start_new_game(comfort.MODES[ui.new_mode_i], look)
            else:
                ui.mode = "new_mode"
            return
        if confirm:
            self.state.v2["skipper"] = look
            self.save()
        ui.mode = "pause"

    def _start_new_game(self, mode: str, look: dict) -> None:
        """Begin a new morning in mode with the Skipper's look in a fresh named save.

        mode is a comfort mode id; look is the creator's normalized appearance.
        Settings and collar visibility carry over. The prologue starts after the
        creator; only this new slot is written (nothing is written in Devmode).
        Returns None and propagates save I/O errors.
        """
        previous = deepcopy(self.state.v2["settings"])
        if self.world.id != "briar":
            self.world = World("briar")  # a new game opens at Briar Landing (05 §1)
        state = State.new(self.world)
        state.v2["settings"] = previous
        comfort.change_mode(state.v2, mode)
        state.v2["profile"]["collar"]["visible"] = previous.get("collar_visible", True)
        state.v2["skipper"] = look
        begin_prologue(state)
        name = skipperlook.clean_name(look.get("name")) or "Skipper"
        slot_path, display = saveslots.allocate_slot(self.default_save_path, name)
        saveslots.stamp_slot_name(state, display)
        self.save_path = slot_path
        self.state = state
        self._replays = set()
        self._attach_quest_manager()
        self._title_catchup_pending = False
        self.ui = UIState(mode="play", input_device=self.ui.input_device,
                          dialogue_content=self._npc_content)
        self.save()

    def _help_keys(self, keys, dt):
        """Esc or H closes the Field Guide; left or up turns back a spread, right or down on.

        Turns wrap around, by the spread count the guide last drew, which follows the window
        and text size (HELP_SPREADS before the first draw)."""
        if "esc" in keys.pressed or "h" in keys.pressed:
            self.ui.mode = self.ui.help_from
            return
        spreads = self.ui.help_spreads or HELP_SPREADS
        left, up = keys.tap("left", dt), keys.tap("up", dt)
        right, down = keys.tap("right", dt), keys.tap("down", dt)
        if left or up:
            self.ui.help_spread = (self.ui.help_spread - 1) % spreads
        if right or down:
            self.ui.help_spread = (self.ui.help_spread + 1) % spreads


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


def app_root() -> Path:
    """The folder that holds the install-era saves/ folder (the executable's, in a build)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class OpenedSave:
    world: World
    state: State
    has_save: bool
    path: Path
    legacy_path: Path | None
    # The install-era save was the source: the platform folder had no save yet.
    started_from_legacy: bool
    used_local_fallback: bool


def open_save(save_path: str | Path | None = None, *, persist_changes: bool = True) -> OpenedSave:
    """Select, migrate, or recover the save for this run.

    Args:
        save_path: Optional explicit save path; otherwise use the platform location.
        persist_changes: Whether load-time migration/recovery may write save files.

    Returns:
        The loaded world, state, and save-selection metadata.

    Side effects:
        Reads saves; when enabled, migration/recovery may write backups and saves.
    """
    root = app_root()
    target, used_local_fallback = _save_target(root, save_path)
    # A renamed-away main save retires its install-era v1: the marker beside the
    # save file keeps the stale legacy copy out of save_candidates forever.
    legacy_path = (root / LEGACY_SAVE
                   if save_path is None and not saveslots.legacy_retired(target)
                   else None)
    started_from_legacy = (legacy_path is not None and legacy_path.is_file()
                           and not target.is_file())
    world, state, has_save = load_game_save(
        target, State, World, legacy_path=legacy_path, persist_changes=persist_changes)
    return OpenedSave(world, state, has_save, target, legacy_path,
                      started_from_legacy, used_local_fallback)


def run(*, software=False, save_path: str | Path | None = None, dev=False,
        detail: str | None = None) -> None:
    """Run interactive play with optional software rendering and unsaved Devmode.

    Args:
        software: Use the CPU renderer instead of the OpenGL renderer.
        save_path: Optional save path; None selects the platform save location.
        dev: Enable playtest controls and suppress all save writes.
        detail: Detail tier name, or None/``auto`` to fit available memory.

    Side effects:
        Opens a resizable game window and shows its pointer outside gameplay.
        Ordinary play saves, while Devmode remains in memory.
    """
    opened = open_save(save_path, persist_changes=not dev)
    world, state, has_save = opened.world, opened.state, opened.has_save
    if opened.used_local_fallback:
        state.toast("Platform save folder unavailable; using the local save folder.")
    session = Session(world, opened.path, state, has_save, dev=dev,
                      legacy_path=opened.legacy_path)

    dw, dh = Platform.display_size()
    width, height = _window_size(dw, dh)
    platform = Platform(width, height, GAME_TITLE,graphics=not software)
    # Do not create render targets until an initially minimized drawable exists.
    while min(platform.viewport) <= 0:
        if platform.poll(0).quit:
            platform.close()
            return
        time.sleep(1 / 30)
    width, height = platform.viewport
    software_backend = software or platform.context is None
    renderer_name = (str(platform.context.info.get("GL_RENDERER", "")).lower()
                     if platform.context is not None else "")
    software_tier = software_backend or any(
        name in renderer_name for name in ("llvmpipe", "softpipe", "swrast"))
    # Text, UI, and audio snapshot tier budgets; Mesa software GL needs the same
    # low-memory policy as the CPU renderer even though its GL context is usable.
    detail_tiers.configure(software=software_tier, override=detail)
    text = Text()
    ui = UI(text, world)
    # One picker for the run, so startup and every trip after it vary without repeats.
    quips = LoadingQuips()
    # Show a real first frame while the forest and shaders initialize.
    loading = np.empty((height,width,3),np.uint8)
    loading[:] = (17,31,32)
    ui._center(loading,GAME_TITLE,width/2,int(height*0.40),
               max(36,height//12),(238,233,216),"serif")
    _loading_quip(ui, loading, quips.pick(world.id), int(height*0.58))
    platform.present(loading)
    audio = Audio(tier=detail_tiers.current().name)
    render_width, render_height = detail_tiers.render_dimensions(
        width, height, software=software_tier)
    renderer = Renderer(world,render_width,render_height,software=software_backend,
                        context=platform.context, output_size=(width, height))
    ui.fish_card_renderer = getattr(renderer, "fish_card", None)
    last = platform.ticks()
    save_acc = 0.0
    blip = None
    low = None
    frame_deadline = time.perf_counter()
    previous_frame_started = None
    smooth_frame_ms = 0.0
    perf_sample_at = 0.0
    try:
        while not session.quit:
            frame_started = time.perf_counter()
            # The first frame has no predecessor to time against.
            frame_elapsed = (None if previous_frame_started is None
                             else frame_started - previous_frame_started)
            previous_frame_started = frame_started
            now = platform.ticks()
            dt = min(0.25, max(0.0, (now - last) / 1000.0))
            last = now
            keys = platform.poll(dt)
            session.tick(keys, dt)
            if session.sound:
                from .bot import sound_kind
                audio.blip(sound_kind(session.state, session.sound))
            for kind in session.cues:  # music and calendar cues on their own buses (V1-38)
                audio.blip(kind)
            if session.quit:
                break
            platform.set_pointer_visible(session.ui.mode != "play" or session.ui.whale_return)
            viewport = keys.viewport
            if viewport[0] <= 0 or viewport[1] <= 0:
                # Keep consuming window/input events without allocating empty render targets.
                time.sleep(1 / 30)
                continue
            if viewport != (width, height):
                width, height = viewport
                session.ui.pointer.begin(None, viewport)
                platform.make_current()
                render_world = renderer.world
                renderer.close()
                render_width, render_height = detail_tiers.render_dimensions(
                    width, height, software=software_tier)
                renderer = Renderer(render_world, render_width, render_height,
                                    software=software_backend, context=platform.context,
                                    output_size=viewport)
                ui.fish_card_renderer = getattr(renderer, "fish_card", None)
                loading = np.empty((height, width, 3), np.uint8)
                low = None
            if renderer.world is not session.world:
                # The transition runs on the last lake image without its HUD.
                scene = low
                if scene is not None and scene.shape[:2] != (height, width):
                    scene = resize_rgb(scene, width, height)
                renderer, ui = _enter_lake(platform, session, renderer, ui, text, loading,
                                           software_backend, software_tier, scene, quips=quips)
                # The startup variable must not retain the first lake's grids.
                world = session.world
                last = platform.ticks()
            cam = _camera(renderer, session)
            platform.make_current()
            low = renderer.render(session.state, cam)
            # The UI paints into a separate array: `low` stays HUD-free for the lake transition.
            big = (low.copy() if low.shape[:2] == (height, width)
                   else resize_rgb(low, width, height))
            ui.draw(big, session.state, session.ui, cam)
            if session.dev_mode is not None:
                if frame_elapsed is not None:
                    smooth_frame_ms = (frame_elapsed * 1000 if not smooth_frame_ms
                                       else smooth_frame_ms * 0.9 + frame_elapsed * 100)
                if time.perf_counter() - perf_sample_at >= 1.0:
                    from .verify import gpu_memory_bytes, rss_bytes
                    gpu_bytes = gpu_memory_bytes()
                    session.dev_mode.perf = (
                        # One rate from the smoothed frame time, so the two figures agree.
                        1000.0 / smooth_frame_ms if smooth_frame_ms else 0.0,
                        smooth_frame_ms, rss_bytes() / 1024**2,
                        None if gpu_bytes is None else gpu_bytes / 1024**2,
                    )
                    perf_sample_at = time.perf_counter()
                session.dev_mode.draw(big, ui)
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
                         motorized=electric or (boat.fuelled and session.state.boat_id!="rowboat"
                                 and session.state.engine_on),
                         electric=electric,
                         rowing=(boat.power in ("paddle", "oars") and not electric
                                 and abs(session.state.throttle)>0.01),
                         volumes=session.state.v2.get("settings", {}).get("volumes", {}),
                         finale=scene_state(session.state, "story_c5_whale") == "done")
            for kind in audio.take_played():
                session.hear_ambient(kind)
            if session.ui.mode != "title" or session.ui.has_save:
                save_acc += dt
                if save_acc >= 45.0:
                    session.save()
                    save_acc = 0.0
            # Unfocused windows idle at 30 Hz; otherwise the loop targets 60 Hz.
            # Accepted swap intervals may still return immediately on some drivers,
            # so keep a 240 Hz safety floor when focused.
            period = 1 / 30 if not session.focused else 1 / 60
            if getattr(platform, "vsync", False) and session.focused:
                period = 1 / 240
            frame_deadline += period
            remaining = frame_deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            else:
                frame_deadline += math.ceil(-remaining / period) * period
    finally:
        if session.ui.mode != "title":
            try:
                session.save()
            except OSError:
                pass
        audio.close()
        ui.close()
        renderer.close()
        text.close()
        platform.close()


def _enter_lake(platform, session, renderer, ui, text, loading, software_backend,
                software_tier, last_frame, *, quips: LoadingQuips | None = None):
    """Swap to the session's new lake and return its renderer and UI.

    Travel to or from the Lagoon tips into starlight from the last lake image
    (`last_frame`, without the HUD); the new lake loads under the full
    starfield, which carries the travel card's text. Other routes show the
    plain loading card. Both name the destination and add a quip from
    `quips` (a fresh picker when None) for the destination lake.
    """
    from . import starlight
    height, width = loading.shape[:2]
    starlit = (last_frame is not None
               and starlight.touches_starlight(renderer.world.id, session.world.id))
    reduced = bool(session.state.v2.get("settings", {}).get("reduced_motion", False))
    quip = (quips if quips is not None else LoadingQuips()).pick(session.world.id)
    if starlit:
        _play_starlight(platform, session, last_frame, None, 0.0, starlight.TIP_END, reduced,
                        card=(ui, session.world.name, quip))
    else:
        loading[:] = (17,31,32)
        _travel_card_text(ui, loading, session.world.name, quip)
        platform.present(loading)
    # The starlight card spans the UI swap; keep the player's text size and font on it.
    text_style = (ui._text_scale, ui._dyslexia_font)
    ui.close()
    renderer.close()
    ui = UI(text,session.world)
    ui._text_scale, ui._dyslexia_font = text_style
    render_width, render_height = detail_tiers.render_dimensions(
        width, height, software=software_tier)
    renderer = Renderer(session.world,render_width,render_height,
                        software=software_backend, context=platform.context,
                        output_size=(width, height))
    ui.fish_card_renderer = getattr(renderer, "fish_card", None)
    if starlit and not session.quit:
        platform.make_current()
        # The HUD returns with the first ordinary frame on the new water.
        arrival = renderer.render(session.state, _camera(renderer, session))
        if arrival.shape[:2] != (height, width):
            arrival = resize_rgb(arrival, width, height)
        _play_starlight(platform, session, last_frame, arrival, starlight.TIP_END, 1.0, reduced,
                        card=(ui, session.world.name, quip))
    return renderer, ui


# Join the text with the starfield while the old lake remains visible beneath it.
# Clear the card as the new water surfaces so its copy stays legible over the transition.
_STARLIGHT_CARD_START = 0.2


def _loading_quip(ui, frame, quip, y):
    """Center a loading quip on `frame` with its top at row `y`.

    The size follows the window height, like the rest of the card; the line is
    trimmed only if a larger text setting would push it past the frame's edges.
    """
    height, width = frame.shape[:2]
    size = max(14, height//40)
    ui._center(frame, ui._trim(quip, size, int(width*0.92), "sans"), width/2, y, size,
               (218,187,124))


def _travel_card_text(ui, frame, lake_name, quip):
    """Paint the travel card's destination heading and quip onto `frame` in place."""
    height, width = frame.shape[:2]
    ui._center(frame, f"Opening {lake_name}...", width/2, int(height*0.46),
               max(18,height//30), (238,233,216), "serif")
    _loading_quip(ui, frame, quip, int(height*0.56))


def _play_starlight(platform, session, source, destination, start, end, reduced, *, card=None):
    """Present the starlight transition from progress `start` to `end`.

    `card` is the travel card as (ui, lake name, quip), drawn over the stars
    from `_STARLIGHT_CARD_START` until the destination begins to surface, so
    the Lagoon route says where it goes like every other trip. The session
    does not tick, so the world and the clock stay paused. Closing the window
    still quits immediately.
    """
    from . import starlight
    begin = platform.ticks()
    while True:
        frame_started = time.perf_counter()
        elapsed = (platform.ticks() - begin) / 1000.0
        t = min(end, start + elapsed / starlight.DURATION)
        keys = platform.poll(0.0)
        if keys.quit:
            session.quit = True
            return
        shown = starlight.frame(source, destination, t, reduced_motion=reduced)
        if card is not None and _STARLIGHT_CARD_START <= t < starlight.RISE_START:
            card_ui, lake_name, quip = card
            _travel_card_text(card_ui, shown, lake_name, quip)
        platform.present(shown)
        if t >= end:
            return
        focused = bool(getattr(keys, "focused", getattr(session, "focused", True)))
        session.focused = focused
        # Transitions retain the old 8 ms cadence without vsync; keep the same
        # unfocused and nonblocking-swap safety floors as the main loop.
        if not focused:
            period = 1 / 30
        elif getattr(platform, "vsync", False):
            period = 1 / 240
        else:
            period = 1 / 125
        remaining = period - (time.perf_counter() - frame_started)
        if remaining > 0:
            time.sleep(remaining)


def _camera(renderer: Renderer, session: Session):
    state = session.state
    if session.ui.mode != "title":
        settings = state.v2.get("settings", {}) if isinstance(state.v2, dict) else {}
        reduced = bool(settings.get("reduced_motion", False))
        clock = session.stage if session.stage is not None else session.whale_clock  # V1-35, V1-37
        cam = staging.staged_camera(renderer, state, clock, reduced=reduced)
        if cam.boat is not None or settings.get("third_person") is not True:
            return cam
        yaw = state.yaw
        pitch = -math.atan2(THIRD_PERSON_ELEVATION, THIRD_PERSON_DISTANCE) + state.look
        x = state.x - math.sin(yaw) * THIRD_PERSON_DISTANCE
        z = state.z - math.cos(yaw) * THIRD_PERSON_DISTANCE
        chase = renderer.camera_for(state, yaw=yaw, pitch=pitch, x=x, z=z)
        # Both camera position representations must move together; rays depend only on yaw/pitch.
        chase.y += THIRD_PERSON_ELEVATION
        chase.eye[1] += THIRD_PERSON_ELEVATION
        # The hull and paws stay at the ordinary boat camera while the view moves behind them.
        chase.boat = cam
        return chase
    settings = state.v2.get("settings", {}) if isinstance(state.v2, dict) else {}
    reduced_motion = bool(settings.get("reduced_motion", False))
    yaw = state.yaw if reduced_motion else state.yaw + math.sin(state.anim * 0.12) * 0.55
    pitch = -0.05 if reduced_motion else -0.05 + math.sin(state.anim * 0.07) * 0.025
    return renderer.camera_for(state, yaw=yaw, pitch=pitch)
