"""The H Field Guide drawn as a lined notebook, two facing pages at a time (#139).

`UI._help` resolves the help topics (`ui.help_topics`: the authored pages, then the keyboard
and gamepad tables, in the active device's wording) and this module lays them out and draws
them. Each topic starts on a fresh page. Its lines wrap to the page, and a topic too long for
one page runs on to the next, so no text is clipped or drawn below the game's 12 px floor, even
at 480x270 with the largest text. The page count therefore follows the window and the text
settings. Pages pair into spreads; an odd last page faces a blank, lined page that closes the
guide.

A page turn moves a whole spread. Each draw wraps `UIState.help_spread` into range and records
`help_spreads`, which the game's page turns wrap by, and `help_shown`, the topics on view.
Laying out measures many strings with the game's own text rendering, so layouts are cached on
the UI by window size, text settings and content.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from .bookview import FADED, INK, LEATHER, OCHRE, PAPER

# School-paper ruling: pale blue lines under the text and a red margin line beside it. Text
# never crosses the margin line, and the rules are pale enough that ink touching them keeps
# its WCAG AA contrast.
RULE_BLUE = (152, 184, 216)
MARGIN_RED = (206, 128, 116)
EDGE = (214, 205, 180)       # the other pages' edges beside the spread; the cover's hint line
FOLD = (204, 192, 160)       # the back of a turned-up corner,
UNDER = (220, 211, 185)      # the page that shows beneath it,
CREASE = (156, 144, 114)     # and the crease along its fold
SPINE = (20, 34, 31)         # the shade the spine casts on each page's inner edge
SHADOW = (5, 10, 10)         # under the notebook, as under every UI panel
TRACK_READ = (128, 141, 124)  # the cover's progress track: spreads before the open one,
TRACK_AHEAD = (74, 98, 90)    # and spreads still ahead
BODY_FAMILY = "mono"   # the tables line up in measured columns of this face
TITLE_FAMILY = "serif"
TABLE_GAP_EMS = 2      # space between table columns, in em (the body face's "M" width)
HANG_EMS = 2           # how far a wrapped sentence's later rows sit in, in em
FOOT_GAP_EMS = 2       # least space between a page number and the cue at the same foot, in em
CONTINUED = "continued"
END_NOTE = "End of the Field Guide"
# Cues at the foot of a page, longest first: the first that fits is drawn. ‹ and › are in
# every bundled face, unlike arrows such as ► or →. Each chevron sits at the cue's outer end
# and points at the page's outer corner, where the notebook turns that way.
TURN_CUES = ("Turn the page ›", "More ›", "›")
FIRST_CUES = ("Back to page 1 ›", "Page 1 ›", "›")
BACK_CUES = ("‹ Turn back", "‹ Back", "‹")
_LAYOUTS_KEPT = 4  # per UI: both devices at two text settings
# A segment of a prose line: the gap before it, then words one space apart. A run of two or
# more spaces is an authored gap between segments ("F sets a trotline     E checks a line").
_SEGMENT = re.compile(r"( *)(\S+(?: \S+)*)")


@dataclass(frozen=True)
class GuidePage:
    """One notebook page: all of a help topic, or one part of a long one."""

    topic: int     # index into the topics, in `ui.help_pages` order
    title: str     # the topic's title
    heading: tuple  # the title as drawn, one line unless it is too wide for the page
    rows: tuple    # ruled rows, top down: ((text, x offset in px), ...), or () when blank
    part: int      # 0 on the topic's first page
    parts: int     # pages the topic runs to
    mark: tuple    # (x, y) in the page of the "continued" marker, or () on a topic's first page


@dataclass(frozen=True)
class GuideLayout:
    """Where everything goes for one window size, text setting and set of topics.

    Rectangles are (x, y, w, h) in frame pixels. Bare x and y values are offsets inside a
    page from its top-left corner. Text sizes are UI sizes, before the text scale.
    """

    cover: tuple     # the notebook, leather cover included
    pages: tuple     # the left page's rectangle, then the right page's
    band: int        # height of the cover showing above and below the pages
    pad: int         # padding inside those bands, above and below their text
    stack: int       # width beside each page where the other pages' edges show
    body: int        # text size of the rows, page numbers, cues and cover text
    title_size: int  # text size of the page titles
    title_h: int     # height of one title line, px
    margin: int      # x of the red margin line
    text_x: int      # x of the text column
    text_w: int      # width of the text column, px
    title_y: int     # y of the title
    first_row: int   # y of the first ruled row's top
    foot_y: int      # y of the page number and cue
    pitch: int       # spacing of the ruled rows, px
    rows: int        # ruled rows a page holds
    rule: int        # how far below a row's top its rule runs: just under the letters
    corner: int      # side of a turned-up corner, px
    page_count: int
    spreads: tuple   # ((left GuidePage, right GuidePage or None), ...)


class _Meter:
    """Measures strings at one size, face and colour as the UI renders them, once each."""

    def __init__(self, owner, size, family, color):
        self._owner, self._size, self._family, self._color = owner, size, family, color
        self.seen = {}

    def extent(self, text):
        """(width, height) of `text` in pixels."""
        found = self.seen.get(text)
        if found is None:
            image = self._owner._render(text, self._size, self._color, self._family)
            found = self.seen[text] = (image.shape[1], image.shape[0])
        return found

    def width(self, text):
        """Width of `text` in pixels."""
        return self.extent(text)[0]


def _extent(owner, text, size, family, color):
    """(width, height) in pixels of non-empty `text` as `owner` renders it."""
    image = owner._render(text, size, color, family)
    return image.shape[1], image.shape[0]


def _fit(text, width, measure):
    """How many leading characters of `text` fit `width`, at least one."""
    low, high = 1, len(text) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle]) <= width:
            low = middle
        else:
            high = middle - 1
    return low


def _wrap(text, width, measure, hang=0):
    """`text` broken at spaces into lines that fit `width` px; `measure` gives a line's width.

    Lines after the first are `hang` px narrower, for a hanging indent. Text that fits comes
    back as written. A word wider than a whole line is split between characters, so no line
    runs past the page.
    """
    if measure(text) <= width:
        return [text]
    lines, line = [], ""
    for word in text.split():
        room = width - hang if lines else width
        if line and measure(line + " " + word) <= room:
            line += " " + word
            continue
        if line:
            lines.append(line)
            room = width - hang
        line = word
        while len(line) > 1 and measure(line) > room:
            cut = _fit(line, room, measure)
            lines.append(line[:cut])
            line = line[cut:]
            room = width - hang
    if line:
        lines.append(line)
    return lines


def _prose(text, width, measure, hang):
    """A line of prose as ruled rows ((text, x offset in px),), top down, `width` px wide.

    Runs of two or more spaces split the line into segments, such as the commands of "F sets
    a trotline     E checks a line or the landing". A row holds whole segments, their
    authored gaps between them, or part of one segment too wide for a row. So a segment
    joins the row before it only when all of it fits there; otherwise it starts a row of its
    own at the margin, and a key never ends one row while its action starts the next. A
    segment that wraps hangs its later rows `hang` px in.
    """
    rows, open_row = [], False
    for gap, segment in _SEGMENT.findall(text):
        if open_row:
            joined = rows[-1][0][0] + gap + segment
            if measure(joined) <= width:
                rows[-1] = ((joined, 0),)
                continue
        lines = _wrap(segment, width, measure, hang)
        rows.append(((lines[0], 0),))
        rows.extend(((line, hang),) for line in lines[1:])
        open_row = len(lines) == 1
    return rows


def _columns(rows, measure, gap):
    """Column offsets for table `rows`, and the table's width, both px.

    Column c is as wide as its widest cell, and columns sit `gap` apart (the V1-41 tables).
    """
    widths = [0] * max(len(row) for row in rows)
    for row in rows:
        for index, cell in enumerate(row):
            if cell:
                widths[index] = max(widths[index], measure(cell))
    offsets, x = [], 0
    for column_w in widths:
        offsets.append(x)
        x += column_w + gap
    return offsets, max(0, x - gap)


def _table(rows, width, measure, gap, indent):
    """Table rows laid out in measured columns that fit `width` px.

    Returns one group per table row: its ruled rows, which pagination keeps together. A ruled
    row is ((text, x offset), ...). A table of two (key, action) pairs per row that is too
    wide stacks its pairs. A last column that still cannot fit wraps beneath itself while it
    keeps half the page; narrower than that, each row's last cell goes beneath the others,
    `indent` px in, and wraps there.
    """
    rows = [tuple(cell or "" for cell in row) for row in rows]
    offsets, total = _columns(rows, measure, gap)
    if total > width and all(len(row) == 4 for row in rows):
        rows = [pair for row in rows for pair in (row[:2], row[2:]) if any(pair)]
        offsets, total = _columns(rows, measure, gap)
    if total <= width:
        return [[tuple((cell, x) for cell, x in zip(row, offsets) if cell)] for row in rows]
    last = offsets[-1]
    wrapped = width - last >= width // 2
    groups = []
    for row in rows:
        cells = tuple((cell, x) for cell, x in zip(row[:-1], offsets) if cell)
        if wrapped:
            pieces = _wrap(row[-1], width - last, measure) if row[-1] else []
            first = cells + ((pieces[0], last),) if pieces else cells
            groups.append([first] + [((piece, last),) for piece in pieces[1:]])
            continue
        heads = [((piece, 0),) for cell, _x in cells for piece in _wrap(cell, width, measure)]
        tail = _wrap(row[-1], width - indent, measure) if row[-1] else []
        groups.append(heads + [((piece, indent),) for piece in tail])
    return groups


def _paragraphs(lines):
    """A topic's lines with its sentences joined up again.

    The help was written in lines of up to 55 characters for a one-page panel, so many a
    sentence runs on to the next line. A line ending in a comma or semicolon, or followed by
    one that starts in lower case, continues there; the notebook rewraps the whole sentence
    to its own page width. A line that ends in neither a comma nor a semicolon, followed by
    one that starts with a capital, a digit or a bracket, stands as it was written: the
    command list on ON THE WATER keeps a line per command, so none of its lines may end in a
    comma or semicolon. Elsewhere the authored lines break a sentence only where this rule
    joins it again, and test_help checks that every other paragraph ends a sentence.
    """
    joined = []
    for line in lines:
        if (isinstance(line, str) and line and joined and isinstance(joined[-1], str)
                and joined[-1] and (joined[-1][-1] in ",;" or line[0].islower())):
            joined[-1] += " " + line
        else:
            joined.append(line)
    return joined


def _groups(lines, width, measure, gap, indent):
    """A topic's lines as row groups for pagination.

    A blank line is [()]. Prose wraps with its later rows `indent` px in, so each paragraph
    (`_paragraphs`), and each command of a line split by authored gaps (`_prose`), starts at
    the margin; a paragraph's later sentences run on in its rows. Every prose row is a group
    of its own: prose may break across pages. Each table row is one group of its ruled rows.
    """
    groups, table = [], []
    for line in (*_paragraphs(lines), None):
        if isinstance(line, tuple):
            table.append(line)
            continue
        if table:
            groups.extend(_table(table, width, measure, gap, indent))
            table = []
        if line is None:
            break
        if not line:
            groups.append([()])
            continue
        groups.extend([row] for row in _prose(line, width, measure, indent))
    return groups


def _fill_pages(groups, capacity, keep=0):
    """Row groups filled greedily into pages of `capacity` ruled rows.

    A group moves whole to a fresh page when it would not fit what is left of one; only a
    group longer than a fresh page holds is split. A blank row never opens or ends a page.
    Each page after the first opens with `keep` blank rows (fewer than `capacity`), held for
    the "continued" marker.
    """
    pages, page, top = [], [], 0  # `top`: the held rows that open `page`
    for group in groups:
        if group == [()]:
            if top < len(page) < capacity:
                page.append(())
            continue
        if len(page) > top and len(page) + len(group) > capacity >= keep + len(group):
            pages.append(page)
            page, top = [()] * keep, keep
        for row in group:
            if len(page) == capacity:
                pages.append(page)
                page, top = [()] * keep, keep
            page.append(row)
    pages.append(page)
    for rows in pages:
        while rows and rows[-1] == ():
            rows.pop()
    return tuple(tuple(rows) for rows in pages)


def _paginate(groups, capacity, keep=0):
    """A topic's row groups as pages of at most `capacity` ruled rows, a tuple of row tuples.

    Each page after the first opens with `keep` blank rows for the "continued" marker (see
    `_fill_pages`). A topic that runs over a page shares its rows evenly between as few
    pages as hold it, rather than leaving a stub of a line or two on its last page.
    """
    pages = _fill_pages(groups, capacity, keep)
    if len(pages) > 1:
        rows = sum(map(len, pages))
        for even in range(math.ceil(rows / len(pages)), capacity):
            balanced = _fill_pages(groups, even, keep)
            if len(balanced) == len(pages):
                return balanced
    return pages


def layout(owner, frame, topics, title, hint):
    """The notebook laid out for `frame`'s size, measured with `owner`'s text settings.

    Args:
        owner: the UI painter; its text scale and dyslexia face take part in the measuring.
        frame: the RGB target; only its size in pixels matters.
        topics: (title, lines) per help topic, as `ui.help_topics` gives them; a line is a
            string, or a tuple of table cells.
        title: the notebook's name, on the cover above the pages.
        hint: the controls line on the cover below them.

    Returns:
        The GuideLayout, from a small cache on `owner` when the same layout was asked for
        recently, since laying out measures every line.
    """
    height, width = frame.shape[:2]
    key = (width, height, getattr(owner, "_text_scale", 1.0),
           getattr(owner, "_dyslexia_font", False), topics, title, hint)
    cache = getattr(owner, "_guide_layouts", None)
    if cache is None:
        cache = owner._guide_layouts = OrderedDict()
    guide = cache.get(key)
    if guide is None:
        guide = cache[key] = _lay_out(owner, frame, topics, title, hint)
        while len(cache) > _LAYOUTS_KEPT:
            cache.popitem(last=False)
    else:
        cache.move_to_end(key)
    return guide


def _lay_out(owner, frame, topics, title, hint):
    """Measure and paginate the notebook; see `layout`."""
    height, width = frame.shape[:2]
    body = owner._size(frame, "small")
    head = owner._size(frame, "head") if height >= 400 else body
    em = owner.cell(body)[0]
    text = _Meter(owner, body, BODY_FAMILY, INK)
    # Across: the cover, room for the other pages' edges, then a page either side of the spine.
    outer = max(4, min(16, height // 45))
    cover = (outer, outer, width - 2 * outer, height - 2 * outer)
    edge = max(3, min(12, height // 60))
    stack = max(2, min(8, width // 160))
    gutter = max(2, width // 320)
    page_w = (cover[2] - 2 * (edge + stack) - gutter) // 2
    margin = max(8, 2 * em)
    text_x = margin + max(4, em // 2)
    text_w = page_w - text_x - max(6, em)
    # Titles take the largest size, from the head size down to the body size, at which every
    # title fits on one line; a title too wide even then wraps.
    title_size = head
    while title_size > body and max(
            _Meter(owner, title_size, TITLE_FAMILY, OCHRE).width(topic)
            for topic, _lines in topics) > text_w:
        title_size -= 1
    heading = _Meter(owner, title_size, TITLE_FAMILY, OCHRE)
    headings = [tuple(_wrap(topic, text_w, heading.width)) for topic, _lines in topics]
    title_h = max(heading.extent(line)[1] for lines in headings for line in lines)
    gap = TABLE_GAP_EMS * em
    groups = [_groups(lines, text_w, text.width, gap, HANG_EMS * em) for _topic, lines in topics]
    # Rows are spaced by the tallest string drawn in them: a fallback face can give some
    # strings a taller surface than "M".
    for probe in (*TURN_CUES, *FIRST_CUES, *BACK_CUES, END_NOTE, CONTINUED, "0123456789"):
        text.extent(probe)
    body_h = max(extent[1] for extent in text.seen.values())
    band_h = max(_extent(owner, title, body, TITLE_FAMILY, PAPER)[1],
                 _extent(owner, hint, body, BODY_FAMILY, EDGE)[1],
                 _extent(owner, "Pages 0–0 of 0", body, BODY_FAMILY, PAPER)[1])
    # Down: cover above and below the pages; on a page, the title, ruled rows, the page number.
    pad = max(2, height // 135)
    band = band_h + 2 * pad
    page_y = cover[1] + band
    page_h = cover[3] - 2 * band
    lead = max(2, body_h // 5)
    pitch = body_h + lead
    title_y = max(3, body_h // 3)
    first_row = title_y + max(map(len, headings)) * title_h + max(3, body_h // 3)
    foot_gap = max(3, body_h // 4)
    foot_y = page_h - foot_gap - body_h
    # At least two rows: a carried-over page may give its first to the "continued" marker.
    rows = max(2, (foot_y - foot_gap - first_row + lead) // pitch)
    # The rules sit where the letters do: just under the ink of an "M".
    ink = np.flatnonzero(owner._render("M", body, INK, BODY_FAMILY)[:, :, 3].max(axis=1))
    rule = int(ink[-1]) + 1 if ink.size else body_h
    last_rule = first_row + (rows - 1) * pitch + rule
    corner = max(4, min(2 * em, margin - 2, page_h - last_rule - 2))
    mark_w, mark_h = text.extent(CONTINUED)
    pages = []
    for index, ((topic, _lines), lines, topic_groups) in enumerate(zip(topics, headings, groups)):
        # A page that carries a topic over always says so: at the end of the title's last
        # line, or on the first ruled row, held empty for it, when the title leaves no room.
        if heading.width(lines[-1]) + em + mark_w <= text_w:
            keep = 0
            mark = (text_x + text_w - mark_w,
                    title_y + (len(lines) - 1) * title_h + max(0, title_h - mark_h))
        else:
            keep, mark = 1, (text_x, first_row)
        chunks = _paginate(topic_groups, rows, keep)
        pages += [GuidePage(index, topic, lines, chunk, part, len(chunks), mark if part else ())
                  for part, chunk in enumerate(chunks)]
    spreads = tuple((pages[i], pages[i + 1] if i + 1 < len(pages) else None)
                    for i in range(0, len(pages), 2))
    left_x = cover[0] + edge + stack
    return GuideLayout(
        cover=cover,
        pages=((left_x, page_y, page_w, page_h), (left_x + page_w + gutter, page_y, page_w, page_h)),
        band=band, pad=pad, stack=stack, body=body, title_size=title_size, title_h=title_h,
        margin=margin, text_x=text_x, text_w=text_w, title_y=title_y, first_row=first_row,
        foot_y=foot_y, pitch=pitch, rows=rows, rule=rule, corner=corner,
        page_count=len(pages), spreads=spreads)


def spread_label(guide, spread):
    """The cover's page indicator for `spread`, longest form first: ("Pages 3–4 of 24",
    "3–4 / 24"), or ("Page 25 of 25", "25 / 25") for an odd last page facing a blank one."""
    first = 2 * spread + 1
    total = guide.page_count
    if guide.spreads[spread][1] is None:
        return f"Page {first} of {total}", f"{first} / {total}"
    return f"Pages {first}–{first + 1} of {total}", f"{first}–{first + 1} / {total}"


def draw(owner, frame, ui, topics, title, hint, caption=""):
    """Draw the Field Guide notebook open at the reader's spread.

    Args:
        owner: the UI painter, with font metrics and fill and text primitives.
        frame: the RGB target, drawn into in place.
        ui: the UIState; `help_spread` picks the spread.
        topics: (title, lines) per help topic, in the reader's device wording.
        title: the notebook's name, on the cover above the pages.
        hint: the controls line, on the cover below them.
        caption: a sound's caption to show, or "". The notebook covers the window, so the
            caption takes the hint's place below the pages while it shows, clear of them.

    Side effects:
        Wraps `ui.help_spread` into range and sets `ui.help_spreads` to the spread count and
        `ui.help_shown` to the topics on the open pages (left, then right unless it is blank).
    """
    guide = layout(owner, frame, topics, title, hint)
    count = len(guide.spreads)
    ui.help_spread %= count
    ui.help_spreads = count
    spread = ui.help_spread
    left, right = guide.spreads[spread]
    ui.help_shown = tuple(page.topic for page in (left, right) if page is not None)
    x, y, w, h = guide.cover
    # The shadow a UI panel casts, 2 px right and 4 px down; the opaque cover hides the rest.
    owner._fill(frame, x + w, y + 4, 2, h, SHADOW, 0.20)
    owner._fill(frame, x + 2, y + h, w - 2, 4, SHADOW, 0.20)
    owner._round_fill(frame, x, y, w, h, LEATHER, 1.0)
    _edges(owner, frame, guide, spread, count)
    _top_band(owner, frame, guide, title, spread_label(guide, spread))
    more = spread < count - 1
    first = 2 * spread + 1
    _page(owner, frame, guide, 0, left, first, BACK_CUES if spread else (), spread > 0)
    _page(owner, frame, guide, 1, right, first + 1,
          TURN_CUES if more else FIRST_CUES if count > 1 else (), more)
    _foot_band(owner, frame, guide, hint, caption, spread, count)


def _edges(owner, frame, guide, spread, count):
    """The other pages' edges beside the spread: those already read on the left, those still
    to come on the right, each side as thick as its share of the notebook."""
    if count < 2:
        return
    thick = 1 if guide.stack < 6 else 2
    most = max(1, guide.stack // (thick + 1))
    (left_x, top, _w, page_h), (right_x, _y, page_w, _h) = guide.pages
    for side, share in ((0, spread), (1, count - 1 - spread)):
        for k in range(math.ceil(most * share / (count - 1))):
            ex = (left_x - (k + 1) * (thick + 1) if side == 0
                  else right_x + page_w + 1 + k * (thick + 1))
            owner._fill(frame, ex, top + k + 1, thick, page_h - 2 * (k + 1), EDGE, 1.0)


def _top_band(owner, frame, guide, title, labels):
    """The notebook's name above the left page and the page indicator above the right one,
    in the longest form that leaves a gap between them."""
    (left_x, _y, _w, _h), (right_x, _ry, page_w, _rh) = guide.pages
    gap = owner.cell(guide.body)[0]
    name_w, name_h = _extent(owner, title, guide.body, TITLE_FAMILY, PAPER)
    for label in labels:
        label_w, label_h = _extent(owner, label, guide.body, BODY_FAMILY, PAPER)
        if name_w + gap + label_w <= right_x + page_w - left_x:
            break
    inner = guide.band - 2 * guide.pad
    top = guide.cover[1] + guide.pad
    owner._text(frame, title, left_x, top + (inner - name_h) // 2, guide.body, PAPER, False,
                TITLE_FAMILY)
    owner._text(frame, label, right_x + page_w - label_w, top + (inner - label_h) // 2,
                guide.body, PAPER, False, BODY_FAMILY)


def _foot_band(owner, frame, guide, hint, caption, spread, count):
    """The controls hint below the left page, or in its place a sound's caption cut to the
    spread's width, and a progress track under the right page in the room left: a segment
    per spread, the open one bright and raised."""
    (left_x, _y, _w, _h), (right_x, _ry, page_w, _rh) = guide.pages
    inner = guide.band - 2 * guide.pad
    top = guide.cover[1] + guide.cover[3] - guide.band + guide.pad
    right = right_x + page_w
    label, color = hint, EDGE
    if caption:
        def measure(text):
            return _extent(owner, text, guide.body, BODY_FAMILY, PAPER)[0]
        label, color = caption, PAPER
        if measure(caption) > right - left_x:
            room = right - left_x - measure("..")
            label = caption[:_fit(caption, room, measure)].rstrip() + ".."
    label_w, label_h = _extent(owner, label, guide.body, BODY_FAMILY, color)
    owner._text(frame, label, left_x, top + (inner - label_h) // 2, guide.body, color, False,
                BODY_FAMILY)
    em = owner.cell(guide.body)[0]
    track = min(right - (left_x + label_w + 2 * em), count * 3 * em)
    if count < 2 or track < 2 * count:
        return
    bar = max(3, inner // 4)
    bar_y = top + (inner - bar) // 2
    start = right - track
    space = 1 if track >= 4 * count else 0
    for index in range(count):
        a = start + index * track // count
        b = start + (index + 1) * track // count - space
        if index == spread:
            owner._fill(frame, a, bar_y - 1, b - a, bar + 2, PAPER, 1.0)
        else:
            owner._fill(frame, a, bar_y, b - a, bar,
                        TRACK_READ if index < spread else TRACK_AHEAD, 1.0)


def _page(owner, frame, guide, side, page, number, cues, corner):
    """One page of the spread (side 0 left, 1 right): ruled paper, the topic's title and rows,
    the "continued" marker when it carries a topic over, the page number at the inner foot by
    the spine, a cue at the outer foot by the corner the page turns at, and that corner
    turned up when the notebook goes on past this side. A missing page is the blank one
    facing an odd last page; it closes the guide."""
    x, y, w, h = guide.pages[side]
    em = owner.cell(guide.body)[0]
    owner._fill(frame, x, y, w, h, PAPER, 1.0)
    for row in range(guide.rows):
        owner._fill(frame, x, y + guide.first_row + row * guide.pitch + guide.rule, w, 1,
                    RULE_BLUE, 1.0)
    owner._fill(frame, x + guide.margin, y, 1, h, MARGIN_RED, 1.0)
    shade = max(2, guide.margin // 4)
    for i in range(shade):
        owner._fill(frame, x + w - shade + i if side == 0 else x + shade - 1 - i, y, 1, h,
                    SPINE, 0.22 * (i + 1) / shade)
    tx = x + guide.text_x
    if page is None:
        lines = _wrap(END_NOTE, guide.text_w,
                      lambda s: _extent(owner, s, guide.body, BODY_FAMILY, FADED)[0])
        top = max(0, (guide.rows - len(lines)) // 2)
        for i, line in enumerate(lines):
            line_w = _extent(owner, line, guide.body, BODY_FAMILY, FADED)[0]
            owner._text(frame, line, tx + (guide.text_w - line_w) // 2,
                        y + guide.first_row + (top + i) * guide.pitch, guide.body, FADED, False,
                        BODY_FAMILY)
    else:
        for i, line in enumerate(page.heading):
            owner._text(frame, line, tx, y + guide.title_y + i * guide.title_h,
                        guide.title_size, OCHRE, False, TITLE_FAMILY)
        if page.mark:
            owner._text(frame, CONTINUED, x + page.mark[0], y + page.mark[1], guide.body, FADED,
                        False, BODY_FAMILY)
        for i, row in enumerate(page.rows):
            row_y = y + guide.first_row + i * guide.pitch
            for cell, offset in row:
                owner._text(frame, cell, tx + offset, row_y, guide.body, INK, False, BODY_FAMILY)
    # The number keeps to the spine and the cue to the outer corner, at least FOOT_GAP_EMS
    # apart, so a cue's chevron points at the corner the page turns at, never at the number.
    foot = y + guide.foot_y
    label = str(number) if page is not None else ""
    label_w = _extent(owner, label, guide.body, BODY_FAMILY, FADED)[0] if label else 0
    apart = FOOT_GAP_EMS * em if label else 0
    if side == 0:
        label_x = tx + guide.text_w - label_w
        start, end = tx, label_x - apart
    else:
        label_x = tx
        start, end = tx + label_w + apart, x + w - guide.corner - max(4, em // 2)
    if label:
        owner._text(frame, label, label_x, foot, guide.body, FADED, False, BODY_FAMILY)
    for cue in cues:
        cue_w = _extent(owner, cue, guide.body, BODY_FAMILY, OCHRE)[0]
        if cue_w <= end - start:
            owner._text(frame, cue, start if side == 0 else end - cue_w, foot,
                        guide.body, OCHRE, False, BODY_FAMILY)
            break
    if corner:
        _corner(owner, frame, x, y, w, h, guide.corner, side)


def _corner(owner, frame, x, y, w, h, size, side):
    """Turn up the page's bottom outer corner, the page beneath showing: the notebook goes
    on that way. Drawn a pixel row at a time: the flap, then what lies past the fold."""
    for i in range(size):
        row = y + h - size + i
        if side:
            owner._fill(frame, x + w - size, row, size - i, 1, FOLD, 1.0)
            owner._fill(frame, x + w - i, row, i, 1, UNDER, 1.0)
            owner._fill(frame, x + w - i - 1, row, 1, 1, CREASE, 1.0)
        else:
            owner._fill(frame, x + i, row, size - i, 1, FOLD, 1.0)
            owner._fill(frame, x, row, i, 1, UNDER, 1.0)
            owner._fill(frame, x + i, row, 1, 1, CREASE, 1.0)
