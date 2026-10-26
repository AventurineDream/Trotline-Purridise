# Issue #41 — Shinies and the Shiny Tracker

## Acceptance evidence

- Seed 41013: **10,000 tracked catches**, 275 shinies, longest gap **50**.
- Seed 41014: **128,000 untracked catches**, 2,045 shinies (1.59765625%).
  This is **2.25%** above the base 1/64 rate, within the required ±10%.
- `shiny-odds.json` records those measurements. The same sequences and bounds
  are exercised by `fishing.test_shinies`.
- Counter/target saves, deterministic reloads, the 49→50 boundary, natural resets,
  target switching, Verified eligibility, 3× sales, Treasured protection, the
  mounting hook, and keyboard/mouse/controller selection have regression checks.
- Fresh counters start at zero. Already saved counters, including the earlier
  schema's value of three, are preserved.

Run the focused regressions with the repository's Python environment:

```sh
python -m unittest fishing.test_shinies fishing.test_book fishing.test_bookview fishing.test_catches -v
```

All **42** focused checks passed locally. The migration check's Briar fixtures
passed; its Cedar fixture could not run locally because this workspace lacks
the tracked `fishing/assets/cedar.npz`. Full migration coverage and the software
selftest run in the existing `gameplay-tests` CI job.

## Presentation evidence

The book portion of `python -m fishing --shots <directory>` now also produces:

- `book-tracker-ready.png`: the button on a Verified entry.
- `book-tracker-one-left.png`: a tracked entry with the next catch guaranteed.
- `book-tracker-compact-accessible.png`: every page at 480×270 with the largest
  accessibility font.

The sparkle marker is drawn into the bounded text cache, so it remains visible
when a system or accessibility font lacks the ✦ glyph. Catch cards already use
the authored shiny palettes and a textual SHINY badge.

`book-benchmark.json` reports **140 warmed book compositions** at 1280×720,
largest text size: p50 **13.94 ms**, p95 **18.83 ms**, peak RSS **172.9 MiB**,
text cache **8.38 MB** (within 8 MiB). This measures the book composition only;
it excludes the lake renderer and is not a whole-game frame benchmark.

The four current boats have no trophy rail. Shinies appear in the book's
Trophy shelf now; `State.mount_shiny_trophy` provides the saved, idempotent
cosmetic hook for a boat with `trophy_rail` when the expanded fleet arrives.
