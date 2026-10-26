"""Book presentation and shared geometry for drawing and pointer navigation."""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .book import (BOOK_SPECIES_IDS, LEGENDARY_IDS, SPECIES_RUMORS,
                   legendary_page, species_page)
from .data import BAIT_BY_ID, CEDAR_FISH, LAKES, SPECIES_BY_ID
from .imageops import resize_rgb
from .narrative import QUEST_IDS, RIPPLE_BY_QUEST

BOOK_TABS = ("Fish", "Book", "Ripples & Keepsakes", "Story", "Watch")
BOOK_TITLES = {"fishypedia": "Fishypedia", "book_of_five_waters": "The Book of Five Waters",
               "pescapedia": "Pescapedia"}
ENTRY_IDS = BOOK_SPECIES_IDS + LEGENDARY_IDS
PAPER = (232, 224, 200)
INK = (36, 58, 53)
FADED = (82, 102, 91)
OCHRE = (137, 91, 36)
RULE = (196, 183, 151)
LEATHER = (40, 64, 59)


@dataclass(frozen=True)
class BookLayout:
    x: int
    y: int
    w: int
    h: int
    tabs: tuple
    content: tuple
    columns: int
    rows: int

    @property
    def capacity(self):
        return self.columns * self.rows

    def cells(self):
        x, y, w, h = self.content
        gap = 10
        cw = (w - gap * (self.columns - 1)) // self.columns
        ch = (h - gap * (self.rows - 1)) // self.rows
        return tuple((x + col * (cw + gap), y + row * (ch + gap), cw, ch)
                     for row in range(self.rows) for col in range(self.columns))


def book_layout(width, height):
    margin = max(8, min(28, width // 35))
    x, y, w, h = margin, margin, width - margin * 2, height - margin * 2
    pad = 20 if width >= 700 else 10
    weights = (0.75, 0.75, 1.65, 0.8, 0.8)
    tabs, tx = [], x + pad
    for weight in weights:
        tw = int((w - pad * 2) * weight / sum(weights))
        tabs.append((tx, y + (46 if width >= 700 else 38), tw, 36 if width >= 700 else 30))
        tx += tw
    content_top = 96 if width >= 700 else 76
    content = (x + pad, y + content_top, w - pad * 2, max(54, h - content_top - 68))
    return BookLayout(x, y, w, h, tuple(tabs), content,
                      4 if width >= 960 else (3 if width >= 640 else 2),
                      3 if height >= 600 else (2 if height >= 400 else 1))


def contains(rect, point):
    x, y, w, h = rect
    return x <= point[0] < x + w and y <= point[1] < y + h


def book_controls(layout):
    return {
        "previous": (layout.x + layout.w - 185, layout.y + layout.h - 70, 36, 34),
        "turn": (layout.x + layout.w - 143, layout.y + layout.h - 70, 88, 34),
        "next": (layout.x + layout.w - 49, layout.y + layout.h - 70, 32, 34),
        "close": (layout.x + layout.w - 120, layout.y + 6, 110, 32),
    }


def move_selection(state, ui, content, delta):
    field, count = (("journal_i", len(BOOK_SPECIES_IDS)),
                    ("book_entry_i", len(ENTRY_IDS)),
                    ("book_collection_i", len(collection_rows(state, content, ui.book_shelf))),
                    ("journal_quest_i", len(QUEST_IDS)),
                    ("book_watch_i", len(LEGENDARY_IDS)))[ui.journal_page]
    setattr(ui, field, (getattr(ui, field) + delta) % max(1, count))
    ui.book_detail_page = 0
    ui.book_detail_pages = 1


def turn_page(state, ui, viewport=(1280, 720)):
    if ui.journal_page == 0:
        ui.book_entry_i = ui.journal_i
        ui.journal_page = 1
        ui.book_detail_page, ui.book_detail_pages = 0, 1
    elif ui.journal_page in (1, 3):
        # Actual font metrics determine the pages; input must not impose a cap.
        ui.book_detail_page += 1
    elif ui.book_detail_page + 1 < ui.book_detail_pages:
        ui.book_detail_page += 1
    elif ui.journal_page == 2:
        ui.book_shelf = (ui.book_shelf + 1) % 3
        ui.book_collection_i = 0
        ui.book_detail_page, ui.book_detail_pages = 0, 1
    else:
        ui.book_entry_i = len(BOOK_SPECIES_IDS) + ui.book_watch_i % len(LEGENDARY_IDS)
        ui.journal_page = 1
        ui.book_detail_page, ui.book_detail_pages = 0, 1


def collection_rows(state, content, shelf):
    if shelf == 0:
        earned = set(state.narrative.ripples)
        rows = []
        for qid, rid in RIPPLE_BY_QUEST.items():
            if rid in earned:
                quest = content.quests[qid]
                rows.append((quest["title"], "Ripple", f"Remembered with {content.npcs[quest['giver_id']]['name']}."))
        for row in state.v2.get("ripples_v2", []):
            rows.append(_keepsake_row(row, "Ripple"))
        return rows
    if shelf == 1:
        return [_keepsake_row(row, "Keepsake") for row in state.v2.get("keepsakes", [])]
    rows = []
    for lid, page in state.v2.get("legendaries", {}).items():
        records = page.get("records", []) if isinstance(page, dict) else []
        if records:
            rows.append((lid.replace("_", " ").title(), "Legendary replica", "A record in the book; a fish returned to the water."))
    shinies = {sid for sid, page in state.v2.get("book", {}).get("species", {}).items()
               if isinstance(page, dict) and page.get("shiny", 0)}
    shinies.update(c.species for c in state.well if c.shiny)
    for sid in sorted(shinies):
        sp = SPECIES_BY_ID.get(sid)
        rows.append((sp.name if sp else sid.replace("_", " ").title(), "Shiny", "A sparkling catch, remembered here."))
    return rows


def _keepsake_row(row, kind):
    if isinstance(row, dict):
        return (str(row.get("name", row.get("id", kind))).replace("_", " "), kind,
                str(row.get("text", row.get("description", "A memory kept from the water."))))
    return str(row).replace("_", " ").title(), kind, "A memory kept from the water."


def _note_text(value):
    if isinstance(value, dict):
        return " · ".join(key.replace("_", " ").capitalize() + ": " + _note_text(item)
                          for key, item in value.items() if key not in {"id", "schema_version"})
    if isinstance(value, (list, tuple)):
        return "; ".join(_note_text(item) for item in value)
    return str(value).replace("_", " ")


@lru_cache(maxsize=24)
def silhouette(width, height):
    yy, xx = np.mgrid[:height, :width]
    body = ((xx - width * .54) / (width * .30)) ** 2 + ((yy - height * .5) / (height * .28)) ** 2 < 1
    tail = ((xx > width * .08) & (xx < width * .32)
            & (np.abs(yy - height * .5) < (width * .32 - xx) * .6))
    image = np.full((height, width, 3), PAPER, dtype=np.uint8)
    image[body | tail] = FADED
    image.setflags(write=False)
    return image


class BookView:
    def __init__(self, owner, frame, state, ui):
        self.u, self.frame, self.state, self.ui = owner, frame, state, ui
        self.layout = book_layout(frame.shape[1], frame.shape[0])
        self.small = owner._size(frame, "small")
        self.body = owner._size(frame, "body")
        self.head = owner._size(frame, "head")
        self.line = owner.cell(self.small)[1] + 4
        self.x, self.y, self.w, self.h = self.layout.content
        self.bottom = self.y + self.h
        self.compact = self.w < 620 or self.h < self.line * 10
        self._last_content_text = None

    def fill(self, rect, color, alpha=1):
        if alpha == 1:
            x, y, w, h = rect
            self.frame[max(0, y):y+h, max(0, x):x+w] = color
        else:
            self.u._fill(self.frame, *rect, color, alpha)

    def text(self, value, x, y, width, size=None, color=INK):
        size = self.small if size is None else size
        value = str(value)
        if y + self.u.cell(size)[1] > self.layout.y + self.layout.h - 6:
            return y
        label = value
        while label and self.u._render(label, size, color).shape[1] > width:
            value = value[:-1]
            label = value.rstrip() + "…" if value else ""
        self.u._text(self.frame, label, int(x), int(y), size, color, shadow=False)
        if color != PAPER and self.y <= y and y + self.u.cell(size)[1] <= self.bottom:
            self._last_content_text = (label, x, y, width, size, color)
        return y + self.u.cell(size)[1] + 4

    def mark_cut(self):
        """Mark the last visible content line when a later paragraph has no room."""
        previous = self._last_content_text or (
            "", self.x, self.bottom - self.line, self.w, self.small, FADED)
        label, x, y, width, size, color = previous
        self.fill((int(x), int(y), int(width), self.u.cell(size)[1]), PAPER)
        self.text(label.rstrip(" …") + " …", x, y, width, size, color)

    def lines(self, value, width):
        # Measure actual glyphs; the accessibility font is proportional.
        result = []
        for paragraph in str(value).splitlines() or [""]:
            remaining = paragraph.strip()
            while remaining:
                low, high = 1, len(remaining)
                while low < high:
                    middle = (low + high + 1) // 2
                    if self.u._render(remaining[:middle], self.small, INK).shape[1] <= width:
                        low = middle
                    else:
                        high = middle - 1
                end = low
                if end < len(remaining) and not remaining[end].isspace():
                    boundary = remaining.rfind(" ", 0, end + 1)
                    if boundary > 0:
                        end = boundary
                result.append(remaining[:end].rstrip())
                remaining = remaining[end:].lstrip()
        return result or [""]

    def paragraph(self, value, x, y, width, bottom=None):
        bottom = self.bottom if bottom is None else bottom
        lines = self.lines(value, width)
        available = max(0, (bottom - y) // self.line)
        if not available:
            self.mark_cut()
            return y
        for index, line in enumerate(lines[:available]):
            if index == available - 1 and len(lines) > available:
                line += " …"
            y = self.text(line, x, y, width)
        return y

    def footer(self, value, color=FADED):
        self.text(value, self.x, self.bottom + 4, self.w - 190, color=color)

    def text_pages(self, values, width, top):
        """Wrap the full text first, then divide it into visible lines."""
        lines = [line for value in values for line in self.lines(value, width)]
        rows = max(1, (self.bottom - top) // self.line)
        return tuple(tuple(lines[start:start + rows])
                     for start in range(0, len(lines), rows)) or ((),)

    def draw_lines(self, lines, x, top, width):
        for index, line in enumerate(lines):
            self.text(line, x, top + index * self.line, width)

    def paginated(self, title, values):
        top = self.text(title, self.x, self.y, self.w,
                        self.small if self.compact else self.head) + 4
        pages = self.text_pages(values, self.w, top)
        self.ui.book_detail_pages = len(pages)
        index = self.ui.book_detail_page % len(pages)
        self.ui.book_detail_page = index
        self.draw_lines(pages[index], self.x, top, self.w)
        return index + 1, len(pages)

    def art(self, sid, count, rect):
        x, y, w, h = rect
        if count and sid in SPECIES_BY_ID:
            from .fishmesh import fish_card, fish_thumbnail
            if w > 128:
                image = self.u.fish_card_renderer(sid) if self.u.fish_card_renderer else fish_card(sid)
            else:
                image = fish_thumbnail(sid)
            image = resize_rgb(image, w, h)
        else:
            image = silhouette(w, h)
        self.u._blit_rgb(self.frame, image, x, y)

    def draw(self):
        l = self.layout
        self.ui.book_detail_pages = 1
        self.fill((l.x - 5, l.y - 5, l.w + 10, l.h + 10), LEATHER)
        self.fill((l.x, l.y, l.w, l.h), PAPER)
        title = BOOK_TITLES.get(self.state.v2["book"].get("title"), "Fishypedia")
        self.text(title, self.x, l.y + 9, self.w - 130, self.head)
        self.text("× Close", l.x + l.w - 112, l.y + 12, 102)
        for index, rect in enumerate(l.tabs):
            active = index == self.ui.journal_page
            self.fill(rect, LEATHER if active else (218, 210, 185))
            label = BOOK_TABS[index]
            if self.frame.shape[1] < 700 and index == 2:
                label = "Ripples"
            self.text(label, rect[0] + 7, rect[1] + 5, rect[2] - 14,
                      color=PAPER if active else INK)
            # Short stitches keep the tabs distinct without an animated texture.
            for stitch in range(rect[0] + 8, rect[0] + rect[2] - 5, 15):
                self.fill((stitch, rect[1] + rect[3] - 3, 5, 1), RULE)
        if self.ui.book_ceremony:
            self.ceremony()
        else:
            (self.grid, self.entry, self.shelf, self.story, self.watch)[self.ui.journal_page]()
        for name, rect in book_controls(l).items():
            if name != "close":
                self.fill(rect, (218, 210, 185))
                label = {"previous": "‹", "turn": "Turn", "next": "›"}[name]
                glyphs = self.u._render(label, self.small, INK)
                self.text(label, rect[0] + (rect[2] - glyphs.shape[1]) // 2,
                          rect[1] + (rect[3] - glyphs.shape[0]) // 2, rect[2] - 8)
        foot = ("D-pad choose · Left/right tabs · A opens / turns · B closes"
                if self.ui.input_device == "gamepad" else
                "W/S choose · A/D tabs · Enter opens / turns · J closes · Click to choose")
        # Shortcut hints have a fixed footer row. Keep tall accessibility glyphs
        # inside that row instead of treating the hint as overflowing content.
        hint_size = self.small
        while hint_size > 1 and self.u.cell(hint_size)[1] > 26:
            hint_size -= 1
        self.text(foot, self.x, l.y + l.h - 32, self.w, hint_size)

    def grid(self):
        self.ui.journal_i %= len(BOOK_SPECIES_IDS)
        start = self.ui.journal_i // self.layout.capacity * self.layout.capacity
        for index, rect in enumerate(self.layout.cells(), start):
            if index >= len(BOOK_SPECIES_IDS):
                break
            sid = BOOK_SPECIES_IDS[index]
            count = self.state.journal.get(sid, {}).get("count", 0)
            if index == self.ui.journal_i:
                self.fill(rect, OCHRE)
            x, y, w, h = rect
            self.fill((x + 2, y + 2, w - 4, h - 4), (242, 235, 214))
            ah = max(18, min(66, h - self.line * 2 - 12))
            aw = min(w - 16, ah * 2)
            self.art(sid, count, (x + (w - aw) // 2, y + 5, aw, ah))
            sp = SPECIES_BY_ID.get(sid)
            label = sp.name if count and sp else SPECIES_RUMORS[sid].folk_name
            self.text(label, x + 8, y + ah + 8, w - 16)
            self.text(f"{count} caught" if count else "What we heard", x + 8,
                      y + ah + 8 + self.line, w - 16, color=FADED)
        seen = sum(1 for sid in BOOK_SPECIES_IDS if self.state.journal.get(sid, {}).get("count", 0))
        count = len(BOOK_SPECIES_IDS)
        self.footer(f"{seen}/{count} identified · Fish {self.ui.journal_i + 1}/{count} · Enter reads this page", OCHRE)

    def entry(self):
        self.ui.book_entry_i %= len(ENTRY_IDS)
        sid = ENTRY_IDS[self.ui.book_entry_i]
        if sid in LEGENDARY_IDS:
            return self.legendary(sid)
        rec = self.state.journal.get(sid, {})
        page = species_page(self.state.v2["book"], sid, rec.get("count", 0), rec,
                            remember=False)
        name = page["name"] or page["folk_name"]
        stage = page["stage"].replace("_", " ").upper()
        stats = f"{page['count']} caught  ·  Best {page['best_weight']:.1f} lb"
        heard = ('“' + page["heard"]["text"] + '”', "— " + page["heard"]["teller"])
        details = []
        if page["best_bait"]:
            details.append("Best bait: " + BAIT_BY_ID[page["best_bait"]].name)
        sp = SPECIES_BY_ID.get(sid)
        if page["tracker_unlocked"] and sp:
            details.append(f"Verified · {sp.depth[0]*3.28084:.0f}–{sp.depth[1]*3.28084:.0f} ft · {sp.pref_time}")
        found = page["found"]
        # Old saves may have only journal conditions until their first new catch.
        if not found and rec.get("count"):
            found = [{key: rec.get(key, "") for key in ("zone", "bait", "band")}]
        notes = []
        for row in found:
            if not isinstance(row, dict):
                continue
            note = " · ".join(str(row[k]).replace("_", " ") for k in ("zone", "bait", "band") if row.get(k))
            if row.get("lake_id"):
                lake = LAKES.get(row["lake_id"], {}).get("name", row["lake_id"].title())
                note = lake + " · " + note
            if "depth_m" in row:
                note += f" · {row['depth_m']*3.28084:.0f} ft"
            if "weight" in row:
                note += f" · {row['weight']:.1f} lb"
            notes.append(note)
        if not notes:
            notes.append("Find this one on Little Briar."
                         if self.u.world.id == "cedar" and sid in CEDAR_FISH and not CEDAR_FISH[sid]
                         else "No catch yet. A place to begin, and room for your own notes.")
        if self.compact:
            top = self.text(name, self.x, self.y, self.w) + 4
            sections = (("What we heard", heard),
                        ("What we found", (stats, *notes)),
                        ("Field notes", (stage, *details)))
            pages = [(label, lines) for label, values in sections
                     for lines in self.text_pages(values, self.w, top)]
            index = self.ui.book_detail_page % len(pages)
            self.ui.book_detail_page, self.ui.book_detail_pages = index, len(pages)
            label, lines = pages[index]
            self.draw_lines(lines, self.x, top, self.w)
            self.footer(f"{label} {index + 1}/{len(pages)}")
            return
        title_bottom = self.text(name, self.x, self.y, self.w - 210, self.head)
        stamp = (self.x + self.w - 200, self.y, 200, self.line + 6)
        self.fill(stamp, OCHRE if page["mastered"] else LEATHER)
        self.text(stage, stamp[0] + 9, stamp[1] + 3, stamp[2] - 18, color=PAPER)
        top = self.text(stats, self.x, title_bottom + 4, self.w, color=OCHRE) + 12
        cw = (self.w - 48) // 2
        left_top = self.text("What we heard", self.x, top, cw, self.body)
        art_h = min(112, max(25, (self.bottom - left_top) // 3))
        self.art(sid, page["count"], (self.x, left_top + 4, art_h * 2, art_h))
        left_top += art_h + 12
        rx = self.x + cw + 48
        right_top = self.text("What we found", rx, top, cw, self.body)
        left = self.text_pages(heard, cw, left_top)
        right = self.text_pages((*details, *notes), cw, right_top)
        count = max(len(left), len(right))
        index = self.ui.book_detail_page % count
        self.ui.book_detail_page, self.ui.book_detail_pages = index, count
        self.draw_lines(left[index % len(left)], self.x, left_top, cw)
        self.draw_lines(right[index % len(right)], rx, right_top, cw)
        self.footer(f"Entry {self.ui.book_entry_i + 1}/{len(ENTRY_IDS)} · Page {index + 1}/{count}")

    def legendary(self, sid):
        page = legendary_page(sid, self.state.v2, remember=False)
        values = ["RECORDED" if page["verified"] else "A LAKE STORY",
                  '“' + page["story"] + '” — ' + page["teller"]]
        for index, record in enumerate(page["records"], 1):
            values.append(f"Record {index}/{len(page['records'])} · {record.get('weight', 0):.1f} lb · {record.get('zone', '')}")
            values.append("Eligibility notes: " + _note_text(record["eligibility"])
                          if record.get("eligibility") else "A memory of the fish, safely returned.")
        if not page["records"]:
            values.append("No first-hand record yet.")
        index, count = self.paginated(sid.replace("_", " ").title(), values)
        self.footer(f"Page {index}/{count} · Enter turns")

    def shelf(self):
        names = ("Ripples", "Keepsakes", "Trophies")
        rows = collection_rows(self.state, self.u.narrative_content, self.ui.book_shelf)
        if rows:
            self.ui.book_collection_i %= len(rows)
            title, kind, description = rows[self.ui.book_collection_i]
            values = (title, f"{kind} · {self.ui.book_collection_i+1}/{len(rows)}", description)
        else:
            values = ("A little room for the memories still to come.",)
        index, count = self.paginated("The keepsake shelf · " + names[self.ui.book_shelf], values)
        self.footer(f"Page {index}/{count} · Turn / shelf")

    def story_pages(self):
        """Lay out every quest field before choosing a visible page."""
        from .ui import quest_journal_details
        index = self.ui.journal_quest_i % len(QUEST_IDS)
        detail = quest_journal_details(self.state, self.u.narrative_content, QUEST_IDS[index])
        compact = self.compact
        width = self.w if compact else (self.w - 40) // 2
        top = self.y + self.u.cell(self.small if compact else self.head)[1] + 12
        rows = max(1, (self.bottom - top) // self.line)
        values = {
            "chapter": f"Chapter {self.state.v2['story']['chapter']} · {len(set(self.state.narrative.ripples))}/10 Ripples · Quest {index+1}/{len(QUEST_IDS)}",
            "title": detail["title"], "status": "Status: " + detail["status"],
            "giver": "Giver: " + detail["giver"], "objective": "Objective: " + detail["objective"],
            "progress": "Progress: " + detail["progress"],
            "prerequisites": "Prerequisites: " + detail["prerequisites"],
            "bot": detail["latest_bot_note"] or "No Bot notes yet.",
            "guardian": detail["guardian_status"],
            "reminder": "Declined? Re-hail. Missed windows repeat; no expiry.",
        }
        groups = (tuple(values),) if compact else (
            ("chapter", "title", "status", "giver", "objective", "progress", "prerequisites"),
            ("bot", "guardian", "reminder"),
        )
        lines = [[line for key in group for line in self.lines(values[key], width)]
                 for group in groups]
        pages = tuple(tuple(tuple(column[start:start + rows]) for column in lines)
                      for start in range(0, max(map(len, lines)), rows))
        if compact:
            # Keep the original three-line overview. Its abbreviated labels are
            # also present in full in the following measured, wrapped pages.
            overview = tuple(values[key] for key in ("title", "progress", "guardian"))
            pages = ((overview[:rows],),) + pages
        return pages, top, width

    def story(self):
        pages, top, width = self.story_pages()
        page = self.ui.book_detail_page % len(pages)
        self.ui.book_detail_page, self.ui.book_detail_pages = page, len(pages)
        self.text("Lake Whispers & Ripples", self.x, self.y, self.w,
                  self.small if self.compact else self.head)
        for column, lines in enumerate(pages[page]):
            for row, line in enumerate(lines):
                self.text(line, self.x + column * (width + 40), top + row * self.line, width)
        self.footer(f"Page {page + 1}/{len(pages)} · Enter turns")

    def watch(self):
        sid = LEGENDARY_IDS[self.ui.book_watch_i % len(LEGENDARY_IDS)]
        page = legendary_page(sid, self.state.v2, remember=False)
        values = ["Recorded" if page["verified"] else "A lead from " + page["teller"],
                  page["story"], *(_note_text(clue) for clue in page["clues"])]
        index, count = self.paginated("Watch cards · " + sid.replace("_", " ").title(), values)
        self.footer(f"Watch {self.ui.book_watch_i + 1}/{len(LEGENDARY_IDS)} · Page {index}/{count}")

    def ceremony(self):
        if self.compact:
            y = self.text(BOOK_TITLES[self.ui.book_ceremony], self.x, self.y, self.w)
            self.paragraph("The water kept its stories. You kept your notes.", self.x, y + 4, self.w)
            self.footer("Enter / A to continue", OCHRE)
            return
        y = self.y + max(4, self.h // 5)
        y = self.text("A new name for these pages", self.x, y, self.w, self.body, OCHRE)
        y = self.text(BOOK_TITLES[self.ui.book_ceremony], self.x, y + 18, self.w, self.head)
        y = self.paragraph("The water kept its stories. You kept your notes.", self.x, y + 24, self.w)
        self.text("Enter / A or click to turn the title page", self.x, y + 18, self.w, color=OCHRE)


def book_gallery(destination, *, text=None, world=None):
    """The --shots book matrix, plus a warmed presentation benchmark."""
    import json
    from pathlib import Path
    import resource
    import time
    from .platform import Text
    from .pngsave import write_png
    from .sim import Catch, State
    from .ui import UI, UIState
    from .world import World

    own_text = text is None
    text = Text() if own_text else text
    world = World() if world is None else world
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    state = State.new(world, seed=712)
    for sid, count in zip(BOOK_SPECIES_IDS[:6], (1, 3, 5, 10, 0, 1)):
        for _ in range(count):
            state._note_journal(Catch(sid, .75, 1, 0, "flats", "worm", 8,
                                      depth_m=2.5, catch_game_minute=480))
    state._note_journal(Catch("old_lantern", 24, 1, 0, "landing", "shad", 21,
                              legendary=True))
    state.v2["book"]["species"]["bluegill"]["shiny"] = 1
    state.v2["keepsakes"] = [{"name": "Reed knot", "text": "A little knot, tied at the landing."}]
    state.narrative.ripples = list(RIPPLE_BY_QUEST.values())
    state.narrative.bot_journal = ["Bot: The flats were quiet this morning. I kept the notes."]
    state.v2["legendaries"]["old_lantern"]["clues"] = [
        {"zone": "landing", "band": "night", "bait": "shad"}]
    state.toasts.clear()
    renderer = UI(text, world)
    frames = []
    try:
        for tab, name in enumerate(("fish", "entry", "keepsakes", "story", "watch")):
            for size, suffix in ((0, "small"), (2, "large")):
                state.v2["settings"]["text_size"] = size
                panel = UIState(mode="journal", journal_page=tab, book_entry_i=3)
                frame = np.full((720, 1280, 3), LEATHER, dtype=np.uint8)
                renderer.draw(frame, state, panel)
                write_png(out / f"book-{name}-{suffix}.png", frame)
                frames.append(resize_rgb(frame, 640, 360))
        state.v2["settings"]["text_size"] = 2
        for name, panel in (
            ("legendary", UIState(mode="journal", journal_page=1, book_entry_i=len(BOOK_SPECIES_IDS))),
            ("trophies", UIState(mode="journal", journal_page=2, book_shelf=2)),
            ("keepsake-shelf", UIState(mode="journal", journal_page=2, book_shelf=1)),
            ("ceremony", UIState(mode="journal", journal_page=1, book_ceremony="book_of_five_waters")),
        ):
            frame = np.full((720, 1280, 3), LEATHER, dtype=np.uint8)
            renderer.draw(frame, state, panel)
            write_png(out / f"book-{name}.png", frame)
        write_png(out / "book-contact-sheet.png", np.concatenate([
            np.concatenate(frames[index:index+2], axis=1) for index in range(0, 10, 2)
        ], axis=0))
        quest_index = next((index for index, qid in enumerate(QUEST_IDS)
            if renderer.narrative_content.quests[qid]["objective"]["type"] == "line_scout_check"), 0)
        compact_cases = (
            ("fish", UIState(mode="journal")),
            ("entry", UIState(mode="journal", journal_page=1)),
            ("shelf", UIState(mode="journal", journal_page=2)),
            ("keepsake", UIState(mode="journal", journal_page=2, book_shelf=1)),
            ("trophies", UIState(mode="journal", journal_page=2, book_shelf=2)),
            ("story", UIState(mode="journal", journal_page=3, journal_quest_i=quest_index)),
            ("watch", UIState(mode="journal", journal_page=4)),
            ("legendary", UIState(mode="journal", journal_page=1, book_entry_i=len(BOOK_SPECIES_IDS))),
            ("unrecorded", UIState(mode="journal", journal_page=1, book_entry_i=len(BOOK_SPECIES_IDS) + 1)),
            ("ceremony", UIState(mode="journal", book_ceremony="book_of_five_waters")),
        )
        for size, accessibility in ((0, False), (1, False), (2, False), (2, True)):
            state.v2["settings"]["text_size"] = size
            state.v2["settings"]["dyslexia_font"] = accessibility
            for name, panel in compact_cases:
                panel.book_detail_page = 0
                frame = np.full((270, 480, 3), LEATHER, dtype=np.uint8)
                renderer.draw(frame, state, panel)
                compact_frames = []
                for index in range(panel.book_detail_pages):
                    panel.book_detail_page = index
                    frame = np.full((270, 480, 3), LEATHER, dtype=np.uint8)
                    renderer.draw(frame, state, panel)
                    compact_frames.append(frame)
                if len(compact_frames) % 2:
                    compact_frames.append(np.full_like(frame, LEATHER))
                sheet = np.concatenate([
                    np.concatenate(compact_frames[index:index+2], axis=1)
                    for index in range(0, len(compact_frames), 2)
                ], axis=0)
                suffix = "-accessible" if accessibility else ""
                write_png(out / f"book-{name}-compact-text{size}{suffix}.png", sheet)
                if name == "story" and size == 2 and not accessibility:
                    write_png(out / "book-story-compact.png", sheet)
        state.v2["settings"]["dyslexia_font"] = False
        timings = []
        for index in range(150):
            panel = UIState(mode="journal", journal_page=index % 5, book_entry_i=3)
            frame = np.full((720, 1280, 3), LEATHER, dtype=np.uint8)
            start = time.perf_counter()
            renderer.draw(frame, state, panel)
            if index >= 10:
                timings.append((time.perf_counter() - start) * 1000)
        report = {"frames": len(timings), "resolution": [1280, 720],
                  "p95_ms": round(float(np.percentile(timings, 95)), 2),
                  "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                  "text_cache_mb": round(text.cache_bytes / 1e6, 2),
                  "tabs": list(BOOK_TABS), "text_sizes": [0, 2]}
        (out / "book-benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
        print("book shots / benchmark: " + json.dumps(report))
        return report
    finally:
        if own_text:
            text.close()
