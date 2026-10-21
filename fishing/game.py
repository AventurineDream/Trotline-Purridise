"""The loop. Driving, menus, and the save. Headless callers use Session.tick."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .content import load_content
from .quests import QuestManager
from .dialogue import Conversation, nearby_npc
from .npcs import active_npcs, schedule_key
from .audio import Audio
from .data import BAITS, SPECIES, hour_of_day
from .weather import weather_visuals
from .platform import Platform, Text
from .render import Renderer
from .imageops import resize_rgb
from .guardian import maybe_start_sighting, pause_sighting_clock
from .bot import reset as reset_bot
from .bot import summon as summon_bot
from .bot import tick as tick_bot
from .sim import State
from .savepaths import LEGACY_SAVE, load_game_save, resolve_save_path
from .ui import UI, UIState, SHOP_TABS, HELP_N, check_rows, shop_rows, title_options
from .world import World

FROZEN = {"title", "setbait", "check", "pause", "help"}
DRIVING = {"play", "map"}
MENU_DIRECTIONS = {"up": "w", "down": "s", "left": "a", "right": "d"}
NAVIGATION_KEYS = set(MENU_DIRECTIONS) | set(MENU_DIRECTIONS.values())
DRIVING_KEYS = {"w", "s", "a", "d", "up", "down", "left", "right"}
PAUSE_N = 4


class Keys:
    """Enough of Input for a headless tick. `pressed` is the edge set."""

    def __init__(self, pressed=(), held=(), quit=False):
        self.pressed = set(pressed)
        self.held = set(held) | set(pressed)
        self.quit = quit

    def tap(self, name: str, dt: float) -> bool:
        return name in self.pressed


class MenuKeys:
    """Arrow/WASD aliases sharing the real input's held-key repeat behavior."""

    def __init__(self, keys):
        self.keys = keys
        self.pressed = keys.pressed
        self.held = keys.held

    def tap(self, name: str, dt: float) -> bool:
        arrow = self.keys.tap(name, dt)
        alias = self.keys.tap(MENU_DIRECTIONS[name], dt)
        return arrow or alias


class Session:
    def __init__(self, world: World, save_path: Path, state: State, has_save: bool):
        self.world = world
        self.save_path = Path(save_path)
        self.state = state
        self.ui = UIState(has_save=has_save)
        self.quit = False
        self._menu_held: set[str] = set()
        self._npc_content = load_content()
        self.quest_manager = QuestManager(self._npc_content)
        self._attach_quest_manager()
        self.conversation = None
        self.ui.dialogue_content = self._npc_content
        self._npc_key = None
        self._refresh_npcs()

    def tick(self, keys, dt: float) -> None:
        self.sound = None
        if keys.quit and self.ui.mode != "title":
            self.save()
            self.quit = True
            return
        if keys.quit:
            self.quit = True
            return
        driving_presses = keys.pressed & DRIVING_KEYS if self.ui.mode in DRIVING else set()
        self._menu_held.intersection_update(keys.held)
        if self.ui.mode in DRIVING:
            self._menu_held.difference_update(keys.pressed)
        else:
            self._menu_held.update(keys.held & NAVIGATION_KEYS)
        self._refresh_npcs()
        self._keys(keys, dt)
        self._simulate(keys, dt, driving_presses)

    def _refresh_npcs(self):
        key = (id(self.state),) + schedule_key(self.state, self.world)
        if key != self._npc_key:
            self.state.npcs = active_npcs(self.state, self.world, self._npc_content)
            self._npc_key = key

    def save(self) -> None:
        self._refresh_npcs()
        self.state.save(self.save_path)
        self.ui.has_save = True

    def _attach_quest_manager(self) -> None:
        self.state._quest_event_handler = self.quest_manager.handle_event

    def _simulate(self, keys, dt: float, driving_presses=()):
        mode = self.ui.mode
        state = self.state
        if mode in DRIVING:
            # A held menu direction must be released before it drives or looks
            # around, even when Enter/Esc closes the menu in this same tick.
            driving_keys = Keys(
                pressed=set(driving_presses) - self._menu_held,
                held=keys.held - self._menu_held,
            )
            state.drive(dt,_throttle(driving_keys,mode),_steer(driving_keys,mode),self.world,
                        idle=bool((driving_keys.held | keys.pressed) & {"shift","rshift"}),
                        player_controlled=True)
            if mode == "play":
                look = 0.0
                if "up" in driving_keys.held:
                    look += 1.0
                if "down" in driving_keys.held:
                    look -= 1.0
                state.look = max(-0.45, min(0.62, state.look + look * 0.55 * dt))
        elif mode not in FROZEN:
            state.sail_raised = False
            state.drive(dt,0.0,0.0,self.world,idle=True)
        if mode in DRIVING or mode == "dialogue":
            sound = tick_bot(state, self.world, dt)
            if sound:
                self.sound = sound
        hooked_before = state.hooked_total
        game_minute_before = state.game_minutes
        state.advance(dt, mode in FROZEN)
        maybe_start_sighting(state, self.world, mode)
        if mode != "play":
            pause_sighting_clock(state)
        elapsed = max(0.0, state.game_minutes - game_minute_before)
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
        })
        if state.hooked_total > hooked_before:
            self.sound = "bite"
        self._refresh_npcs()
        if mode in DRIVING:
            self._react_to_nearby_npc()
        if self.conversation and not any(n.id == self.conversation.npc_id for n in state.npcs):
            self._close_dialogue()
        state.tick_toasts(dt)

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
        elif mode == "journal":
            self._journal_keys(keys, dt)
        elif mode == "well":
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
        elif mode == "help":
            self._help_keys(keys, dt)

    def _title_keys(self, keys, dt):
        options = title_options(self.ui.has_save)
        if self.ui.confirm_new:
            if "esc" in keys.pressed:
                self.ui.confirm_new = False
            elif "return" in keys.pressed or "space" in keys.pressed:
                self.state = State.new(self.world)
                self._attach_quest_manager()
                self.ui.confirm_new = False
                self.ui.mode = "play"
                self.ui.note = ""
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
                self.state.catch_up()
                self.ui.mode = "play"
            elif choice == "New morning":
                self.ui.confirm_new = True
            else:
                self.ui.mode = "play"

    def _play_keys(self, keys):
        if "esc" in keys.pressed:
            self.ui.mode = "pause"
            self.ui.pause_i = 0
            return
        if "h" in keys.pressed:
            self._open_help("play")
            return
        if "c" in keys.pressed:
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
        if "tab" in keys.pressed:
            self.ui.mode = "map"
        if "j" in keys.pressed:
            self.ui.mode = "journal"
            self.ui.journal_i = 0
            self.ui.journal_page = 0
            self.ui.journal_quest_i = 0
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
        self.conversation = Conversation.start(npc, self.state, self._npc_content)
        self.ui.conversation = self.conversation
        self.ui.dialogue_from = self.ui.mode
        self.ui.mode = "dialogue"

    def _close_dialogue(self):
        self.conversation = None
        self.ui.conversation = None
        self.ui.mode = self.ui.dialogue_from

    def _dialogue_keys(self, keys, dt):
        if "esc" in keys.pressed:
            self._close_dialogue()
            return
        if "h" in keys.pressed:
            self._open_help("dialogue")
            return
        chat = self.conversation
        if chat is None:
            self._close_dialogue()
            return
        node = self._npc_content.dialogue[chat.node_id]
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
        if select and not chat.advance(self.state, self._npc_content):
            self._close_dialogue()

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
        error = self.state.tow_to_landing(self.world)
        if error:
            self.state.toast(error)
        else:
            reset_bot(self.state)

    def change_lake(self,lake_id):
        if self.state.lines:
            return "Pick up your deployed lines before towing to another lake."
        if self.state.slip_status(self.world)!="docked" or abs(self.state.speed)>=0.45:
            return "Return to the landing to tow to another lake."
        if lake_id==self.world.id:
            return "You are already on this lake."
        destination = World(lake_id)
        self.world = destination
        self.state.bind(destination)
        self.state.rowboat_charge_kwh_this_visit = 0.0
        self.state._park(destination)
        reset_bot(self.state)
        self.ui.mode = "play"
        self.ui.note = ""
        self.state.toast(f"Welcome to {destination.name}. All your gear came along.")
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
            self.ui.mode = "check"
            self.ui.check_line = nearest
            self.ui.check_i = 0
            self.ui.note = ""
            line = self.state.lines[nearest]
            self.state.emit_quest_event({
                "type": "line.check",
                "lake_id": self.state.lake_id,
                "zone_id": f"{self.state.lake_id}:{line.zone}",
                "line_id": line.line_id,
                "game_minute": self.state.game_minutes,
                "active_game_minute": self.state.narrative.active_play_game_minutes,
                "eligible_catch_records": [
                    {
                        "species_id": hook.catch.species,
                        "source_line_id": line.line_id,
                        "lake_id": self.state.lake_id,
                        "source_zone_id": f"{self.state.lake_id}:{line.zone}",
                        "bait_id": line.bait,
                        "catch_game_minute": hook.catch.catch_game_minute,
                    }
                    for hook in line.hooks if hook.catch is not None
                ],
            })
            return
        self.state.toast("Nothing here to check.")

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
        if keys.tap("up", dt):
            self.ui.set_bait = (self.ui.set_bait - 1) % len(BAITS)
            self.ui.note = ""
        if keys.tap("down", dt):
            self.ui.set_bait = (self.ui.set_bait + 1) % len(BAITS)
            self.ui.note = ""
        for i, name in enumerate("12345"):
            if name in keys.pressed:
                self.ui.set_bait = i
                self.ui.note = ""
        if "return" in keys.pressed or "space" in keys.pressed:
            bait = BAITS[self.ui.set_bait % len(BAITS)].id
            err = self.state.try_set(self.world, self.ui.set_line, bait)
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
        if "return" in keys.pressed or "space" in keys.pressed:
            self._check_act(rows[self.ui.check_i % len(rows)])

    def _check_act(self, row):
        index = self.ui.check_line
        if row.kind == "hook":
            if not row.enabled:
                self.ui.note = "Nothing on that hook."
                return "error"
            err = self.state.take_hook(index, int(row.arg))
            if err:
                return self._fail(err)
            self.ui.note = ""
            return "click"
        if row.kind == "take_all":
            msg = self.state.take_all(index)
            self.ui.note = "" if msg.startswith("Took") else msg
            return "click" if msg.startswith("Took") else "error"
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
        if "esc" in keys.pressed or "j" in keys.pressed:
            self.ui.mode = "play"
            return
        left = keys.tap("left", dt)
        right = keys.tap("right", dt)
        if left or right:
            self.ui.journal_page = (self.ui.journal_page + (1 if right else -1)) % 2
            return
        if self.ui.journal_page == 1:
            field, count = "journal_quest_i", len(self._npc_content.quests)
        else:
            field, count = "journal_i", len(SPECIES)
        if count <= 0:
            return
        if keys.tap("up", dt):
            setattr(self.ui, field, (getattr(self.ui, field) - 1) % count)
        if keys.tap("down", dt):
            setattr(self.ui, field, (getattr(self.ui, field) + 1) % count)

    def _pause_keys(self, keys, dt):
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
                self._open_help("pause")
            elif choice == 2:
                self.save()
                self.ui.mode = "title"
                self.ui.title_i = 0
                self.ui.confirm_new = False
            else:
                self.save()
                self.quit = True

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
    save_path = resolve_save_path(save_path)
    world, state, has_save = load_game_save(
        save_path, State, World, legacy_path=legacy_path)
    session = Session(world, save_path, state, has_save)

    dw, dh = Platform.display_size()
    width, height = _window_size(dw, dh)
    platform = Platform(width, height, "Little Briar",graphics=not software)
    text = Text()
    ui = UI(text, world)
    # Show a real first frame while the forest and shaders initialize.
    loading = np.empty((height,width,3),np.uint8)
    loading[:] = (17,31,32)
    ui._center(loading,"Little Briar",width/2,int(height*0.40),
               max(36,height//12),(238,233,216),"serif")
    ui._center(loading,"Opening the lake...",width/2,int(height*0.58),
               max(14,height//40),(218,187,124))
    platform.present(loading)
    audio = Audio()
    renderer = Renderer(world,width,height,software=software or platform.context is None,
                        context=platform.context)
    last = platform.ticks()
    save_acc = 0.0
    blip = None
    try:
        while not session.quit:
            now = platform.ticks()
            dt = min(0.25, max(0.0, (now - last) / 1000.0))
            last = now
            keys = platform.poll()
            session.tick(keys, dt)
            if session.sound:
                audio.blip(session.sound)
            if session.quit:
                break
            if renderer.world is not session.world:
                loading[:] = (17,31,32)
                ui._center(loading,f"Opening {session.world.name}...",width/2,height/2,
                           max(18,height//30),(238,233,216),"serif")
                platform.present(loading)
                renderer.close()
                ui = UI(text,session.world)
                renderer = Renderer(session.world,width,height,
                                    software=software or platform.context is None,context=platform.context)
                last = platform.ticks()
            cam = _camera(renderer, session)
            platform.make_current()
            low = renderer.render(session.state, cam)
            big = resize_rgb(low, width, height)
            ui.draw(big, session.state, session.ui, cam)
            platform.present(big)
            renderer.poke_splashes(session.state)
            minutes = session.state.game_minutes
            audio.update(dt, session.state.throttle, session.state.speed, session.state.muted,
                         hour=hour_of_day(minutes),
                         rain=float(weather_visuals(minutes)["rain"]),
                         sailing=session.state.sail_raised,
                         motorized=(session.state.boat_id!="rowboat"
                                    or (session.state.rowboat_trolling_motor
                                        and session.state.rowboat_battery_kwh>0)),
                         rowing=(session.state.boat_id=="rowboat"
                                 and (not session.state.rowboat_trolling_motor
                                      or session.state.rowboat_battery_kwh<=0)
                                 and abs(session.state.throttle)>0.01))
            if session.ui.mode != "title":
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


def _camera(renderer: Renderer, session: Session):
    state = session.state
    if session.ui.mode != "title":
        return renderer.camera_for(state)
    yaw = state.yaw + math.sin(state.anim * 0.12) * 0.55
    pitch = -0.05 + math.sin(state.anim * 0.07) * 0.025
    return renderer.camera_for(state, yaw=yaw, pitch=pitch)
