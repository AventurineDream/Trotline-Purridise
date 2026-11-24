"""Displayed menu geometry and semantic pointer intents, independent of SDL and gameplay.

Renderers publish rectangles in UI pixels. Context changes retire every old target;
focus remains in the screen's existing selection field, never in this registry.
"""

from dataclasses import dataclass, field


def context(state, ui):
    """Return the content/layout identity whose displayed targets may still be used.

    Most hover-owned row indices do not participate, keeping their frames live.
    Save selection does: its action row and rename draft belong to that slot.
    Tabs, pages, content changes and submodes also invalidate displayed targets.
    Only read each screen's actual model contract, so lightweight settings/title
    renderers need not manufacture unrelated gameplay state.
    """
    v2 = getattr(state, "v2", {})
    settings = v2.get("settings", {}) if isinstance(v2, dict) else {}
    chat = ui.conversation
    content = ()
    if ui.mode in {"shop", "check", "kitchen"}:
        from .ui import check_rows, shop_rows
        if ui.mode == "shop":
            rows = shop_rows(state, ui.shop_tab)
        elif ui.mode == "check":
            rows = check_rows(state, ui.check_line)
        else:
            from .kitchen import rows as kitchen_rows
            rows = kitchen_rows(state, state._world)
        content = (tuple((row.kind, row.arg, row.label, row.right, row.enabled) for row in rows),
                   state.money, repr(state.well), repr(state.bait),
                   repr(state.v2.get("pantry", {})))
    elif ui.mode == "setbait":
        content = repr((state.held, state.bait))
    elif ui.mode == "well":
        content = repr(state.well)
    elif ui.mode == "journal":
        content = repr((state.v2.get("book"), state.v2.get("keepsakes"),
                        state.v2.get("ripples_v2"), state.v2.get("legendaries"),
                        state.journal, state.narrative))
    elif ui.mode == "pause":
        from .ui import pause_options
        content = tuple(pause_options(state))
    elif ui.mode == "map":
        content = (state.boat_id, state.sail_raised, repr(state.lines))
    elif ui.mode == "cook_confirm":
        content = repr((state.well, state.v2.get("pantry", {})))
    return (ui.mode, ui.has_save, ui.confirm_new, ui.settings_page, ui.capturing_key,
            ui.shop_tab, ui.set_line, ui.set_sections, ui.set_section,
            ui.journal_page, ui.book_detail_page, ui.book_shelf, ui.book_ceremony,
            ui.help_spread, ui.skipper_typing, ui.cook_kind, ui.cook_arg,
            getattr(chat, "node_id", None), getattr(chat, "npc_id", None),
            repr(settings), content, ui.check_line, ui.needs_kind, ui.skipper_origin,
            ui.kitchen_from, ui.cook_from, ui.help_from, ui.stage_skip, ui.whale_return,
            ui.haul_phase, ui.haul_index, tuple(ui.slots), ui.slot_i, ui.slot_action_i,
            ui.slot_renaming, ui.slot_name_buf, ui.slot_name_fresh)


@dataclass(frozen=True)
class Target:
    """A displayed rectangle, optional canonical focus assignment, and semantic action.

    Rectangles use half-open (x, y, width, height) UI pixels. Actions are interpreted
    only by Session's menu router; they are never keyboard/gameplay events.
    """

    rect: tuple
    action: str = "activate"
    field: str = ""
    value: object = None

    def contains(self, point):
        """Return whether the UI-pixel point lies within this target's half-open bounds."""
        x, y, w, h = self.rect
        return w > 0 and h > 0 and x <= point[0] < x + w and y <= point[1] < y + h


@dataclass
class Registry:
    """One completed render's hit targets and scroll behavior, invalid until published.

    Renderers call begin/add; input checks identity and viewport before hit testing.
    The scroll intent names the screen's native selection/page operation.
    """

    identity: object = None
    viewport: tuple = (0, 0)
    targets: list = field(default_factory=list)
    scroll: str = ""
    owner: str = "keyboard"
    windows: dict = field(default_factory=dict)

    hovered: Target | None = None

    def begin(self, identity, viewport, scroll=""):
        """Replace geometry for a displayed context and UI-pixel viewport; return None."""
        if identity != self.identity or viewport != self.viewport:
            self.windows.clear()
            self.hovered = None
        self.identity, self.viewport, self.scroll = identity, viewport, scroll
        self.targets.clear()

    def add(self, rect, action="activate", field="", value=None):
        """Publish a displayed target; later overlapping targets take precedence."""
        self.targets.append(Target(tuple(rect), action, field, value))

    def hit(self, point):
        """Return the topmost displayed target at a UI-pixel point, or None."""
        return next((target for target in reversed(self.targets) if target.contains(point)), None)

    def window(self, key, index, count, capacity):
        """Keep hovered lists stationary; keyboard/scroll may move their visible window."""
        capacity = max(1, capacity)
        start = self.windows.get(key)
        if start is None or self.owner != "pointer":
            start = max(0, min(index - capacity // 2, count - capacity))
        start = max(0, min(start, max(0, count - capacity)))
        self.windows[key] = start
        return start, min(count, start + capacity)
