"""V1-43: every line a cat or Bot speaks follows the writing rules (05 §0).

1. No mechanics in dialogue: no money amounts, counts of minutes, metres or hooks, clock
   times, line tiers or zone ids. Those live in the book's objective text.
2. At most 140 characters a bubble and 3 bubbles a node.
3. Only the script's placeholders, and never one at the start of a sentence.
"""

from __future__ import annotations

import re
import unittest

from .content import load_content

MECHANICS = re.compile(
    r"\$\d"                                                     # money
    r"|\b\d+\b[^.!?]{0,24}?\b(minutes?|metres?|meters?|hours?|lb|lbs|hooks?)\b"  # counted rules
    r"|\b\d+-hook\b"
    r"|\b(premium|heavy|standard)\s+line\b"                     # line tiers
    r"|\b[a-z]+:[a-z_]+\b"                                      # zone ids such as briar:lilies
    r"|active play"
    r"|\b\d{1,2}:\d{2}\b")                                      # clock times
PLACEHOLDERS = {"{BotName}", "{Skipper}", "{lake}", "{fish}", "{depth_ft}", "{zone}"}
SENTENCE_START = re.compile(r"(^|[.!?…]\s+)\{")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _bubbles(text):
    return [text] if isinstance(text, str) else list(_strings(text))


class CopyRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = load_content()
        spoken = {}
        for node_id, node in cls.content.dialogue.items():
            spoken[node_id] = _bubbles(node.get("text"))
        for cat_id, cat in cls.content.cats.items():
            for key, value in (cat.get("greetings") or {}).items():
                alternatives = value if isinstance(value, list) else [value]
                for index, alternative in enumerate(alternatives):
                    spoken[f"{cat_id}:greetings:{key}:{index}"] = _bubbles(alternative)
        cls.spoken = spoken
        cls.written = {f"{cat_id}:{kind}": list(_strings(cat.get(kind)))
                       for cat_id, cat in cls.content.cats.items() for kind in ("letters", "story")}

    def test_spoken_lines_state_no_mechanics(self):
        for node_id, bubbles in {**self.spoken, **self.written}.items():
            for text in bubbles:
                with self.subTest(node=node_id):
                    match = MECHANICS.search(text)
                    self.assertIsNone(match, f"{node_id}: {match and match.group(0)!r} in {text!r}")

    def test_bubbles_are_short_and_few(self):
        for node_id, bubbles in self.spoken.items():
            with self.subTest(node=node_id):
                self.assertLessEqual(len(bubbles), 3)
                for text in bubbles:
                    self.assertLessEqual(len(text), 140, text)

    def test_placeholders_are_known_and_never_open_a_sentence(self):
        for node_id, bubbles in {**self.spoken, **self.written}.items():
            for text in bubbles:
                with self.subTest(node=node_id):
                    self.assertLessEqual(set(re.findall(r"\{[A-Za-z_]+\}", text)), PLACEHOLDERS, text)
                    self.assertIsNone(SENTENCE_START.search(text), text)


if __name__ == "__main__":
    unittest.main()
