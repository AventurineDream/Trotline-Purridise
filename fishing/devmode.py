"""Opt-in keyboard playtest tools; all mutations stay in the current in-memory session.

The game loop routes physical grave-key input here before gameplay and draws this
panel after the normal UI. Cheats use simulation mutators where possible; the
legendary fixture builds valid authored conditions and invokes the real hook API.
The DEV badge names the toggle key by the character the player's layout types on it.
"""

from __future__ import annotations

import math
from copy import deepcopy

from .data import SPECIES, SPECIES_BY_ID, hour_of_day
from .lakes import LAKES
from .sim import Catch

COMMANDS = (
    "+$1,000", "Refill bait", "Starter kit", "Advance 1 game hour",
    "Catch standard fish", "Fill first line", "Change lake",
    "Set up Old Lantern encounter", "Reset in-memory session",
)

# The key's layout-independent name (as the controls list spells it), shown when the
# layout types no character there, such as German's dead "^".
DEFAULT_KEY_LABEL = "Grave"


def hotkey_label(layout_name: str) -> str:
    """Return the badge's name for the Devmode toggle key.

    Args:
        layout_name: The layout's character for the physical grave key, as from
            ``Platform.key_label("grave")``; may be "" or padded.
    Returns:
        That name in brackets, such as "[`]", so a one-glyph key still reads as a key;
        "[Grave]" when the layout types no character there.
    """
    name = layout_name.strip() or DEFAULT_KEY_LABEL
    return f"[{name}]"


class DevMode:
    """Opt-in, in-memory playtest controls attached to one game session."""

    def __init__(self, session):
        """Attach a closed panel to a live session.

        Args:
            session: Game session that owns the in-memory state and safe mutators.

        Returns:
            None.

        Side effects:
            Stores the session reference only; no save or gameplay RNG is touched.
        """
        self.session = session
        self.open = False
        self.selected = 0
        self.species_index = 0
        choices = self.available_lakes()
        self.lake_index = (choices.index(session.state.lake_id)
                           if session.state.lake_id in choices else 0)
        self.confirming_reset = False
        self.reset_choice = 1  # Cancel is the safe default.
        self.message = ""
        self.perf = (0.0, 0.0, 0.0, None)
        # The layout's character for the toggle key; refresh_key_label keeps it current.
        self.key_label = DEFAULT_KEY_LABEL

    def refresh_key_label(self, platform) -> None:
        """Read the toggle key's current character from the window's keyboard layout.

        Args:
            platform: The live `Platform`; its `key_label("grave")` asks SDL's keymap.
        Side effects:
            Sets `key_label`, so a layout switched mid-session shows on the next draw.
        """
        self.key_label = platform.key_label("grave")

    def handle(self, physical_pressed, action_pressed) -> bool:
        """Route grave and panel actions; return whether this frame's game input is consumed.

        Args:
            physical_pressed: Physical keyboard key names, before rebinding.
            action_pressed: Normalized keyboard/gamepad action names.

        Returns:
            True while the panel is open or toggled this frame, so gameplay input is swallowed.

        Side effects:
            Changes panel selection/open state and runs a selected command on activation.
        """
        physical_pressed = set(physical_pressed)
        action_pressed = set(action_pressed)
        self.skip_world_tick = False
        was_open = self.open
        toggled = "grave" in physical_pressed
        if toggled:
            self.open = not self.open
            if not self.open:
                self.confirming_reset = False
        if toggled:
            return True
        if self.open:
            if self.confirming_reset:
                if "esc" in action_pressed:
                    self.confirm_reset(False)
                    self.open = False
                elif action_pressed & {"grave"}:
                    self.confirm_reset(False)
                    self.open = False
                elif action_pressed & {"return", "space"}:
                    self.confirm_reset(self.reset_choice == 0)
                elif action_pressed & {"left", "right", "a", "d", "up", "down", "w", "s"}:
                    self.reset_choice = 1 - self.reset_choice
            else:
                if action_pressed & {"esc", "grave"}:
                    self.open = False
                elif "up" in action_pressed or "w" in action_pressed:
                    self.selected = (self.selected - 1) % len(COMMANDS)
                elif "down" in action_pressed or "s" in action_pressed:
                    self.selected = (self.selected + 1) % len(COMMANDS)
                elif "left" in action_pressed or "a" in action_pressed:
                    self._cycle_choice(-1)
                elif "right" in action_pressed or "d" in action_pressed:
                    self._cycle_choice(1)
                elif action_pressed & {"return", "space"}:
                    self.execute(self.selected)
        return was_open or self.open

    def _cycle_choice(self, delta):
        """Rotate the current authored fish or lake selection."""
        if self.selected in (4, 5):
            self.species_index = (self.species_index + delta) % len(SPECIES)
        elif self.selected == 6:
            choices = self.available_lakes()
            if choices:
                current = min(self.lake_index, len(choices) - 1)
                self.lake_index = (current + delta) % len(choices)

    def available_lakes(self):
        """List every authored lake ID in authored order."""
        return list(LAKES)

    def execute(self, command_index: int) -> None:
        """Apply one command to the current in-memory session.

        Args:
            command_index: Zero-based index in ``COMMANDS``; unsupported indexes do nothing.

        Returns:
            None. The result or a safe precondition failure is shown in the panel.

        Side effects:
            Mutates the active session only; Devmode saves are disabled.
        """
        state = self.session.state
        self.message = ""
        if command_index == 0:
            state._earn(1000)
            self.message = "Added $1,000."
        elif command_index == 1:
            self._refill_bait()
        elif command_index == 2:
            state._earn(1000)
            self._refill_bait()
            self.message = "Starter kit: $1,000 and a full bait box."
        elif command_index == 3:
            before = state.game_minutes
            result = self.session.advance_bulk(60) if self.session.world_running() else None
            if result is None:
                state.advance_bulk(60)
                self.session._record_world_advance(before)
            self.skip_world_tick = True
            self.message = "Advanced exactly one game hour."
        elif command_index == 4:
            self._catch_one()
        elif command_index == 5:
            self._fill_first_line()
        elif command_index == 6:
            self._change_lake()
        elif command_index == 7:
            self._setup_legendary()
        elif command_index == 8:
            self.confirming_reset = True
            self.reset_choice = 1
            self.message = "Choose Reset to confirm; Cancel or Esc keeps this session."

    def _refill_bait(self):
        """Fill remaining bait-box capacity with common worms, without exceeding the box."""
        state = self.session.state
        room = max(0, state.box_cap() - state.bait_count())
        state.bait["worm"] = state.bait.get("worm", 0) + room
        self.message = f"Added {room} worms; bait box capacity respected."

    def _species(self):
        """Return the selected authored standard species, never a legendary record."""
        return SPECIES[self.species_index % len(SPECIES)]

    def _make_catch(self, species_id, line, hook_index):
        """Build a deterministic catch using the bait assigned to one zero-based hook."""
        species = SPECIES_BY_ID[species_id]
        bait = line.bait_for_hook(hook_index) if line.hooks else "worm"
        weight = (species.min_lb + species.max_lb) / 2
        return Catch(species_id, weight, 1.0, 0.0, line.zone, bait,
                     hour_of_day(self.session.state.game_minutes),
                     self.session.state.lake_id,
                     catch_game_minute=self.session.state.game_minutes)

    def _place_catch(self, hook, species_id, line, hook_index):
        """Apply standard catch bookkeeping on a particular deployed hook."""
        state = self.session.state
        catch = self._make_catch(species_id, line, hook_index)
        hook.catch = catch
        hook.baited = False
        state.hooked_total += 1
        state._note_journal(catch)

    def _catch_one(self):
        """Place the selected authored standard species on the next open, nonduplicate hook."""
        state = self.session.state
        species = self._species()
        used = {hook.catch.species for line in state.lines for hook in line.hooks
                if hook.catch is not None}
        if species.id in used:
            self.message = f"{species.name} is already caught; choose another fish."
            return
        for line in state.lines:
            for hook_index, hook in enumerate(line.hooks):
                if hook.catch is None:
                    self._place_catch(hook, species.id, line, hook_index)
                    self.message = f"Placed {species.name} on the next open hook."
                    return
        self.message = "Set a line with an open hook first."

    def _fill_first_line(self):
        """Fill open hooks on the first deployed line with unique authored species."""
        state = self.session.state
        if not state.lines:
            self.message = "Set a line first."
            return
        line = state.lines[0]
        used = {hook.catch.species for line in state.lines for hook in line.hooks
                if hook.catch is not None}
        species = [row for row in SPECIES if row.id not in used]
        cursor = self.species_index % len(species) if species else 0
        added = 0
        for hook_index, hook in enumerate(line.hooks):
            if hook.catch is not None:
                continue
            if not species:
                break
            row = species[cursor]
            self._place_catch(hook, row.id, line, hook_index)
            used.add(row.id)
            species = [entry for entry in species if entry.id not in used]
            cursor = 0
            added += 1
        self.message = (f"Placed {added} fish on the first line."
                        if added else "No open hooks on the first line.")

    def _change_lake(self):
        """Attempt the selected authored lake through the game's safe-travel API."""
        choices = self.available_lakes()
        if not choices:
            self.message = "No lake is currently unlocked."
            return
        if self.session.state.lines:
            self.message = "Pick up your deployed lines before towing to another lake."
            return
        if self.session.state.slip_status(self.session.world) != "docked" or abs(self.session.state.speed) >= 0.45:
            self.message = "Dock the boat before towing to another lake."
            return
        lake_id = choices[min(self.lake_index, len(choices) - 1)]
        unlocks = self.session.state.v2.setdefault("unlocks", [])
        route = f"travel:{lake_id}"
        if route not in unlocks:
            unlocks.append(route)
        error = self.session.change_lake(lake_id)
        name = LAKES[lake_id]["name"]
        if error:
            self.message = error
        elif self.session.pending_lake == lake_id:
            # Windowed trips only queue here; the run loop builds and commits the lake.
            self.message = f"Towing to {name}..."
        else:
            self.message = f"Travelled to {name}."

    def _setup_legendary(self):
        """Prepare Old Lantern at its authored site and use the real legendary hook evaluator."""
        state, world = self.session.state, self.session.world
        if state.lake_id != "briar" or world.id != "briar":
            self.message = "Select Little Briar first; this fixture uses its authored Old Lantern site."
            return
        if state.lines or not state.held:
            self.message = "Bring all deployed lines aboard and keep one held line for this fixture."
            return
        bait_id = "lantern_liver"
        added_bait = max(0, 12 - state.bait.get(bait_id, 0))
        if state.bait_count() + added_bait > state.box_cap():
            self.message = "Make room in the bait box, then try the fixture again."
            return

        previous = {
            "pose": (state.x, state.z, state.yaw, state.game_minutes, state.minute_acc,
                     state.light, state.anchored, state.speed, state.throttle,
                     state.throttle_setting),
            "bait": dict(state.bait),
            "held": list(state.held),
            "lines": list(state.lines),
            "rng": state.rng.s,
            "v2": deepcopy(state.v2),
            "narrative": deepcopy(state.narrative),
            "preferred_bait": state.preferred_bait,
            "journal": deepcopy(state.journal),
            "book_events": list(state.book_events),
            "toasts": deepcopy(state.toasts),
            "records": list(state._records),
            "tired": list(state._tired),
            "hooked_total": state.hooked_total,
            "money": state.money,
            "earned": state.earned,
            "spent": state.spent,
        }

        def rollback_fixture():
            """Restore every state surface the temporary hook evaluator may touch."""
            (state.x, state.z, state.yaw, state.game_minutes, state.minute_acc,
             state.light, state.anchored, state.speed, state.throttle,
             state.throttle_setting) = previous["pose"]
            state.bait = previous["bait"]
            state.held = previous["held"]
            state.lines = previous["lines"]
            state.rng.s = previous["rng"]
            state.v2 = previous["v2"]
            state.narrative = previous["narrative"]
            state.preferred_bait = previous["preferred_bait"]
            state.journal = previous["journal"]
            state.book_events = previous["book_events"]
            state.toasts = previous["toasts"]
            state._records = previous["records"]
            state._tired = previous["tired"]
            state.hooked_total = previous["hooked_total"]
            state.money = previous["money"]
            state.earned = previous["earned"]
            state.spent = previous["spent"]

        state.bait[bait_id] = state.bait.get(bait_id, 0) + added_bait
        state.light = True
        day_start = math.floor(state.game_minutes / 1440) * 1440
        encounter_minute = day_start + 15 * 60
        if encounter_minute < state.game_minutes:
            encounter_minute += 1440
        state.game_minutes = encounter_minute
        state.minute_acc = 0.0
        # This is the authored test location used by the legendary acceptance tests.
        state.x, state.z, state.yaw = -355.789, 107.381, math.pi / 2
        state.speed = state.throttle = state.throttle_setting = 0.0
        state.anchored = True
        try:
            error = state.try_set(world, 0, bait_id)
        except Exception as exc:
            rollback_fixture()
            self.message = f"Could not set the fixture line; state restored: {exc}"
            return
        if error:
            rollback_fixture()
            self.message = f"Could not set the fixture line: {error}; state restored."
            return
        fixture_line = state.lines[-1]
        # The authored landing-edge test line is short and centered inside the area.
        fixture_line.x0, fixture_line.z0 = -360.789, 107.381
        fixture_line.x1, fixture_line.z1 = -350.789, 107.381
        fixture_line.zone = "landing_edge"
        try:
            catch = state.check_legendary_hook(state.lines[-1])
        except Exception as exc:
            rollback_fixture()
            self.message = f"The encounter check failed; fixture rolled back: {exc}"
            return
        state.rng.s = previous["rng"]
        if catch is None:
            rollback_fixture()
            self.message = "Requirements were not met; the temporary fixture was rolled back."
            return
        self.message = "Old Lantern is ready on the line."

    def confirm_reset(self, confirmed: bool) -> bool:
        """Complete the explicit reset prompt without writing or deleting any save.

        Args:
            confirmed: True to start a fresh Briar session; False to cancel.

        Returns:
            True only when a pending prompt was confirmed and the in-memory state reset.
        """
        if not self.confirming_reset:
            return False
        self.confirming_reset = False
        if not confirmed:
            self.message = "Reset cancelled; current session retained."
            return False
        self.open = False
        session = self.session
        from .game import UIState
        from .sim import State
        from .story import begin_prologue
        from .world import World
        settings = deepcopy(session.state.v2.get("settings", {}))
        session.world = World("briar")
        session.pending_lake = None  # a queued trip belongs to the session being reset
        session.state = State.new(session.world, seed=1)
        session.state.v2["settings"] = settings
        begin_prologue(session.state)
        session._refresh_npcs()
        session._attach_quest_manager()
        session._replays = set()
        session._title_catchup_pending = False
        session._menu_held.clear()
        session._input_repeat.clear()
        session.ui = UIState(mode="play", input_device=session.ui.input_device,
                             dialogue_content=session._npc_content)
        session.conversation = None
        session.stage = None
        self.message = "Started a fresh in-memory session; the save file was not changed."
        return True

    def draw(self, frame, ui) -> None:
        """Draw the DEV marker and optional panel over the rendered RGB frame.

        Args:
            frame: Render target in RGB pixel coordinates, after normal UI drawing.
            ui: Existing UI renderer providing scaled text and panel helpers.

        Returns:
            None; modifies ``frame`` in place without changing gameplay state.
        """
        h, w = frame.shape[:2]
        small = ui._size(frame, "small")
        fps, frame_ms, rss_mb, gpu_mb = self.perf
        gpu = "?" if gpu_mb is None else f"{gpu_mb:.0f}"
        key = hotkey_label(self.key_label)
        perf = f"{fps:.0f} fps  {frame_ms:.1f} ms  {rss_mb:.0f}+{gpu} MB"
        # The toggle key outranks the readout: narrower windows shed the readout, then the
        # word, then the key, so the text fits its badge down to a bare "DEV" (~90 px).
        for marker in (f"DEV  {key} tools  {perf}", f"DEV  {key} tools", f"DEV {key}", "DEV"):
            if ui._measure(marker, small, "mono") <= w - 32:
                break
        badge_w = min(w - 16, max(250, ui._measure(marker, small, "mono") + 16))
        badge_h = max(28, small + 12)
        panel_w = min(w - 32, 520)
        panel_h = min(h - 32, 390)
        x, y = (w - panel_w) // 2, (h - panel_h) // 2
        # The screen corners belong to the play HUD, so the badge sits centred between its two
        # cards. On short frames the open panel needs that strip and the badge yields to it.
        if not self.open or y >= 8 + badge_h + 4:
            badge_x = (w - badge_w) // 2
            ui._panel(frame, badge_x, 8, badge_w, badge_h, 0.88)
            ui._text(frame, marker, badge_x + 8, 12, small, (232, 199, 113))
        if not self.open:
            return

        compact = h < 420
        title_size = max(small + 2, min(ui._size(frame, "title"), 22 if compact else 32))
        header_h = 34 if compact else title_size + 24
        footer_size = small if compact else max(10, small - 4)
        footer_lines = ("Up/Down choose · Left/Right option", f"Enter run · Esc/{key} close")
        footer_line_h = ui.cell(footer_size)[1] + 2
        footer_h = footer_line_h * len(footer_lines) + 4
        message_h = small + 6 if self.message else 0
        padding = 12 if compact else 20
        available_rows = panel_h - header_h - footer_h - message_h - padding
        row_step = max(small + 1, available_rows // len(COMMANDS))
        row_step = min(row_step, small + (4 if compact else 10))

        ui._panel(frame, x, y, panel_w, panel_h, 0.94)
        ui._text(frame, "PLAYTEST DEVTOOLS", x + 22, y + 8, title_size,
                 (232, 199, 113))

        if self.confirming_reset:
            prompt_y = y + header_h
            ui._text(frame, "Reset only this in-memory session?", x + 22, prompt_y,
                     small, (230, 228, 212))
            options = ("Reset", "Cancel")
            for index, label in enumerate(options):
                color = (232, 199, 113) if index == self.reset_choice else (190, 199, 190)
                ui._text(frame, f"{'›' if index == self.reset_choice else ' '} {label}",
                         x + 28, prompt_y + small + 6 + index * (small + 4), small, color)
        else:
            for index, label in enumerate(COMMANDS):
                color = (232, 199, 113) if index == self.selected else (190, 199, 190)
                detail = ""
                if index in (4, 5):
                    detail = f" — {self._species().name}"
                elif index == 6:
                    choices = self.available_lakes()
                    if choices:
                        selected = choices[min(self.lake_index, len(choices) - 1)]
                        detail = f" — {LAKES[selected]['name']}"
                ui._text(frame, f"{'›' if index == self.selected else ' '} {label}{detail}",
                         x + 22, y + header_h + index * row_step, small, color)

        if self.message:
            message_y = y + panel_h - footer_h - message_h
            # Status lines are sentences; proportional type fits them in the panel.
            message = ui._trim(self.message, small, panel_w - 44, "sans")
            ui._text(frame, message, x + 22, message_y, small, (185, 210, 192), True, "sans")
        footer_y = y + panel_h - footer_h
        for index, line in enumerate(footer_lines):
            ui._text(frame, line, x + 22, footer_y + index * footer_line_h,
                     footer_size, (155, 170, 162))
