"""How long a line of text stays up: long enough to read at a young reader's pace (V1-43).

Toasts and sound captions used to hold for a fixed time, so a long line vanished before a
slow reader finished it. Now the hold grows with the text: a beat to notice it, then
about 14 characters a second, a comfortable pace for a ten-year-old reading aloud. A
short line keeps its old hold, and no line stays up past READ_MAX_SECONDS.
"""

from __future__ import annotations

READ_CHARS_PER_SECOND = 14.0
READ_NOTICE_SECONDS = 1.0
READ_MAX_SECONDS = 9.0


def reading_seconds(text: str, floor: float = 0.0) -> float:
    """Seconds to show this text: its reading time, never under floor or over the cap."""
    read = READ_NOTICE_SECONDS + len(str(text).strip()) / READ_CHARS_PER_SECOND
    return max(float(floor), min(READ_MAX_SECONDS, read))
